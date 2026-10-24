"""Claude's vision as the legibility reader of the plantillas_ai eval (m-24849234 PR 3).

`ClaudeLegibilityReader` implements `image_metrics.LegibilityReader`: it shows Claude
one generated image and asks for the exact text it shows, through one strict tool call
(`transcribir_texto`), so the answer is the text and nothing else.

Spend is capped on its own, independently of the generation ceiling (`spend_control`):
`ReadBudget` allows at most `HARD_MAX_READS` reads and `HARD_MAX_USD` per run, and each
read reserves its WORST case before the request leaves:

- the image is downscaled to `READ_IMAGE_MAX_SIDE` px on its long side first, so it is
  at most ~1600 image tokens (the API's w × h / 750 rule);
- input is bounded by `MAX_INPUT_TOKENS` (the image plus the short system prompt,
  instruction and tool schema, with ample margin), priced as if all of it were a cache
  write (1.25 × the input price) — the conservative reading;
- output is bounded by `max_tokens = MAX_OUTPUT_TOKENS`, thinking included.

A read that would take the count past `max_reads`, or spent + held + its worst case past
`max_usd`, raises `ReadBudgetExceeded` BEFORE any request. After the answer the
reservation settles at the real usage; when the request fails without an answer it
settles at the worst case (it may have been billed). The retry the ticket asks for on a
mismatch is a second read: it reserves and counts like the first.
"""

from __future__ import annotations

import io
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from PIL import Image, ImageOps

from qualify_api import claude_tools
from qualify_api.claude_tools import ClaudeToolError, ClientFactory, ModelConfig, strict_tool
from qualify_api.creative.font_ai import image_blocks
from qualify_api.evals.image_metrics import ReaderUnavailable

READER_MODEL = "claude-sonnet-5"
#: Low effort: transcribing a short word needs little thinking (font_ai uses medium for
#: a harder judgement). Sonnet 5 rejects sampling parameters, so no temperature is sent.
READER_EFFORT = "low"
READER_PROMPT_VERSION = "legibilidad-claude-v1"
READ_TOOL = "transcribir_texto"

#: Founder's caps (2026-10-23): independent of the generation ceiling, never above these.
HARD_MAX_READS = 50
HARD_MAX_USD = Decimal("0.50")
#: Downscale before sending: 1092² / 750 ≈ 1590 image tokens at most.
READ_IMAGE_MAX_SIDE = 1092
#: Worst-case input tokens of one read (image ≤ ~1600 + prompt, instruction, tool schema
#: and the tool-use system preamble, all well under 1000).
MAX_INPUT_TOKENS = 4000
#: `max_tokens` of the request: the output, thinking included, can never exceed it.
MAX_OUTPUT_TOKENS = 2048
#: Cache writes are billed at 1.25 × input; every input token is priced so in the worst case.
CACHE_WRITE_FACTOR = Decimal("1.25")
_MILLION = Decimal(1_000_000)

SYSTEM = """\
Eres un verificador de legibilidad. Miras una imagen generada (un logo o una palabra con \
una textura) y transcribes el texto que se ve en ella, exactamente como aparece: mismas \
letras, tildes, «ñ», signos y espacios, en mayúsculas o minúsculas según se vea. No \
corrijas, no completes, no traduzcas ni adivines la palabra que debería ser: si una letra \
no se lee o falta, no la escribas. Si no hay texto legible, entrega una cadena vacía. \
Entregas la respuesta con la herramienta transcribir_texto, una sola vez, sin nada más."""

INSTRUCTION = "Transcribe con transcribir_texto el texto exacto que se ve en esta imagen."


class ReadBudgetExceeded(ReaderUnavailable):
    """The next read would pass the reader's cap (reads or USD): it is not sent."""


def _price(model_id: str) -> tuple[Decimal, Decimal]:
    """(input, output) USD per token from `claude_tools.PRICES` — no price, no read."""
    if model_id not in claude_tools.PRICES:
        raise ValueError(f"no price for {model_id!r} in claude_tools.PRICES")
    price_in, price_out = claude_tools.PRICES[model_id]
    return Decimal(str(price_in)) / _MILLION, Decimal(str(price_out)) / _MILLION


def worst_case_usd(model_id: str) -> Decimal:
    price_in, price_out = _price(model_id)
    return MAX_INPUT_TOKENS * CACHE_WRITE_FACTOR * price_in + MAX_OUTPUT_TOKENS * price_out


def usage_usd(usage: Any, model_id: str) -> Decimal:
    """What one answer cost: input, cache reads (at the full input price) and cache
    writes (at 1.25 ×), plus output."""
    price_in, price_out = _price(model_id)
    tokens_in = Decimal(int(usage.input_tokens)) + int(
        getattr(usage, "cache_read_input_tokens", 0) or 0
    )
    writes = Decimal(int(getattr(usage, "cache_creation_input_tokens", 0) or 0))
    return (
        tokens_in * price_in
        + writes * CACHE_WRITE_FACTOR * price_in
        + int(usage.output_tokens) * price_out
    )


@dataclass
class ReadBudget:
    """Thread-safe cap on the reader: count and USD. `reserve` holds a read's worst case
    BEFORE it is sent and refuses the one that would pass either cap; `settle` replaces
    the hold with the real cost (the worst case when unknown). Nothing is clamped: a
    real cost above the reservation is recorded as `overage_usd`."""

    max_reads: int = HARD_MAX_READS
    max_usd: Decimal = HARD_MAX_USD
    reads: int = 0
    spent_usd: Decimal = Decimal(0)
    held_usd: Decimal = Decimal(0)
    overage_usd: Decimal = Decimal(0)
    _open: dict[int, Decimal] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self.max_usd = Decimal(self.max_usd)
        if not 1 <= self.max_reads <= HARD_MAX_READS:
            raise ValueError(f"max_reads must be within 1..{HARD_MAX_READS}")
        if not (self.max_usd.is_finite() and Decimal(0) < self.max_usd <= HARD_MAX_USD):
            raise ValueError(f"max_usd must be above 0 and at most {HARD_MAX_USD}")

    def reserve(self, worst_usd: Decimal) -> int:
        with self._lock:
            if self.reads + 1 > self.max_reads:
                raise ReadBudgetExceeded(
                    f"the reader already made {self.reads} of its {self.max_reads} reads"
                )
            committed = self.spent_usd + self.held_usd
            if committed + worst_usd > self.max_usd:
                raise ReadBudgetExceeded(
                    f"a read may cost USD {worst_usd}: with USD {committed} committed it would "
                    f"pass the reader's cap of USD {self.max_usd}"
                )
            self.reads += 1
            self._open[self.reads] = worst_usd
            self.held_usd += worst_usd
            return self.reads

    def settle(self, number: int, actual_usd: Decimal | None) -> Decimal:
        with self._lock:
            reserved = self._open.pop(number)
            self.held_usd -= reserved
            amount = reserved if actual_usd is None else actual_usd
            if amount > reserved:
                self.overage_usd += amount - reserved
            self.spent_usd += amount
            return amount

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "lecturas": self.reads,
                "tope_lecturas": self.max_reads,
                "gastado_usd": str(self.spent_usd),
                "retenido_usd": str(self.held_usd),
                "exceso_sobre_reserva_usd": str(self.overage_usd),
                "tope_usd": str(self.max_usd),
            }


def downscaled_png(data: bytes, max_side: int = READ_IMAGE_MAX_SIDE) -> bytes:
    """The image upright and at most `max_side` px on its long side, as PNG."""
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
    image.thumbnail((max_side, max_side), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _answer(response: Any) -> str:
    """The transcription: the `transcribir_texto` tool's `texto`. An answer without that
    tool call is not a reading (prose must never become `leido` nor trigger the paid
    retry): `ClaudeToolError`."""
    for block in response.content or ():
        if getattr(block, "type", None) == "tool_use" and block.name == READ_TOOL:
            value = (block.input or {}).get("texto", "")
            return value if isinstance(value, str) else ""
    raise ClaudeToolError(f"no final tool: the answer did not call {READ_TOOL}")


class ClaudeLegibilityReader:
    """Reads the text of an image with Claude, under a `ReadBudget`."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = READER_MODEL,
        effort: str | None = READER_EFFORT,
        budget: ReadBudget | None = None,
        client_factory: ClientFactory | None = None,
        create: Callable[..., Any] | None = None,
    ) -> None:
        self.config = ModelConfig(model, effort)
        self.budget = budget or ReadBudget()
        self.worst_usd = worst_case_usd(model)  # no price, no reader
        self._client = (client_factory or claude_tools.default_client)(api_key)
        self._create = create or claude_tools.messages_create

    def _request(self, image_bytes: bytes) -> dict[str, Any]:
        blocks = image_blocks([("lectura.png", downscaled_png(image_bytes))])
        kwargs: dict[str, Any] = {
            "model": self.config.model_id,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "system": SYSTEM,
            "messages": [
                {"role": "user", "content": [*blocks, {"type": "text", "text": INSTRUCTION}]}
            ],
            "tools": [
                strict_tool(
                    READ_TOOL,
                    "Entrega el texto exacto que se ve en la imagen.",
                    {"texto": {"type": "string"}},
                )
            ],
            "tool_choice": claude_tools.forced_or_auto(self.config, READ_TOOL),
        }
        if self.config.effort:
            kwargs["output_config"] = {"effort": self.config.effort}
        return kwargs

    def read_text(self, image_bytes: bytes) -> str:
        kwargs = self._request(image_bytes)  # an unreadable image fails before any spend
        number = self.budget.reserve(self.worst_usd)  # ReadBudgetExceeded: nothing sent
        try:
            response = self._create(self._client, self.config, **kwargs)
        except BaseException:
            self.budget.settle(number, None)  # it may have been billed: the worst case
            raise
        try:
            actual: Decimal | None = usage_usd(response.usage, self.config.model_id)
        except Exception:  # noqa: BLE001 — an odd usage object: settle the worst case
            actual = None
        self.budget.settle(number, actual)
        if response.stop_reason in ("refusal", "max_tokens"):
            raise ClaudeToolError(f"{self.config.model_id} stop_reason={response.stop_reason}")
        return _answer(response)

    def report(self) -> dict[str, object]:
        return {
            "tipo": "claude",
            "modelo": self.config.model_id,
            "esfuerzo": self.config.effort,
            "prompt_version": READER_PROMPT_VERSION,
            "peor_caso_por_lectura_usd": str(self.worst_usd),
            **self.budget.snapshot(),
        }

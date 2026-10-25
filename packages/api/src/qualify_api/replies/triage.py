"""Comment triage by Claude Haiku 5.5 — sentiment, kind and «needs a reply» in ONE call
(ATENDER-4a, m-24848532). The candidate that replaces robertuito on the comments path.

Why it exists: the public-reply gate (`gate.py`) still routes on robertuito's POS label,
but the production image ships without torch (`sentiment.service.local_model_available`),
so in production no comment ever gets a sentiment and only commercial ones get a draft.
robertuito also has no declared license. ATENDER-4b (m-24848533) wants a draft for any
comment — positive, question or complaint — and needs a classifier that runs where the
app runs and that was measured first. This module is that classifier. ATENDER-4b wired
it into the gate (`ReplyService._triage` → `gate.TriageEvidence`) behind a per-tenant
setting that is OFF by default (`replies.any_comment`) until `docs/respuestas-comentarios-
medicion.md` says, on real comments, which classes are reliable.

The contract (labeling rules in `docs/respuestas-comentarios-medicion.md` §2):

- `sentiment`: `pos` | `neu` | `neg` — the commenter's tone towards the business.
- `kind`: `praise` | `question` | `complaint` | `other` — what the comment does.
- `needs_reply`: whether the business owes an answer (a question, a request or a
  complaint). Missing one is the expensive error, so its recall bar is 0.95.

Prompt versions (`TRIAGE_PROMPTS`, m-24854495):

- `atender4a.1` — the three fields above. Still the default: it is what ATENDER-4b ships.
- `atender4a.1-conf` — the same rules plus a `confidence` (0..1) on the sentiment, so a stored
  sentiment keeps a real `score` once Haiku replaces robertuito (whose `score` is the
  softmax of its label). Measured on the golden set before it becomes the default
  (`docs/modelos-generativos/pruebas.md`, SENT-HAIKU-001). Not called `atender4a.2`:
  that name belongs to the drafts prompt in `any_comment_drafts`.

Provenance: every `Triage` carries the model id and its prompt version; the batch
cost is in `last_stats` and the wall time of each batch in `last_latencies_s`. Same API
facts as `intent.classifier` (Haiku 5.5 thinks by default → `tool_choice: auto` and the
caller checks the tool was called).
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Protocol

from qualify_shared import observability

from qualify_api.claude_tools import (
    CallStats,
    ClaudeToolError,
    Meter,
    ModelConfig,
    create_turn,
    default_client,
    forced_or_auto,
    strict_tool,
    tool_uses,
)

TRIAGE_MODEL: Final = "claude-haiku-5-5"
TRIAGE_EFFORT: Final = "low"
#: Bump whenever `SYSTEM_PROMPT` or the tool changes: it is the detector version a
#: reliability report is written under.
TRIAGE_PROMPT_VERSION: Final = "atender4a.1"
#: Same rules + a sentiment confidence (m-24854495). Not the default until measured.
TRIAGE_PROMPT_VERSION_CONFIDENCE: Final = "atender4a.1-conf"
TRIAGE_BATCH: Final = 25
TRIAGE_TOOL: Final = "registrar_comentarios"


class Sentiment(StrEnum):
    POS = "pos"
    NEU = "neu"
    NEG = "neg"


class CommentKind(StrEnum):
    PRAISE = "praise"
    QUESTION = "question"
    COMPLAINT = "complaint"
    OTHER = "other"


@dataclass(frozen=True)
class Triage:
    sentiment: Sentiment
    kind: CommentKind
    needs_reply: bool
    model_id: str = TRIAGE_MODEL
    prompt_version: str = TRIAGE_PROMPT_VERSION
    #: The model's own confidence in `sentiment`, 0..1 — `atender4a.1-conf` on; None under
    #: `atender4a.1` (no score is ever invented).
    confidence: float | None = None


class CommentTriager(Protocol):
    """`triage` returns one result per text, in order; `None` = no usable answer for
    that text (the caller leaves the comment untriaged, never guesses)."""

    model_id: str
    prompt_version: str

    def triage(self, texts: Sequence[str]) -> list[Triage | None]: ...


SYSTEM_PROMPT: Final = """\
Lees comentarios públicos que personas dejan en publicaciones de Instagram y Facebook de \
pequeños negocios de Colombia, Venezuela y Uruguay (comida, tiendas, servicios, \
inmobiliarias, turismo). Para cada comentario decides tres cosas.

1. sentiment — el tono de quien comenta hacia el negocio:
- pos: elogio, agradecimiento, entusiasmo ("qué rico", "lo amo", "gracias", emojis de \
amor o fuego).
- neg: queja, reclamo, molestia, desconfianza, burla o mala reseña ("nunca responden", \
"llegó frío", "carísimo", "estafa"), aunque sea educada.
- neu: ni lo uno ni lo otro: preguntas sin tono, etiquetas a otras personas, información.
Una pregunta con elogio ("¡qué belleza! ¿cuánto cuesta?") es pos. Una pregunta con \
molestia ("¿hasta cuándo esperando el pedido?") es neg. El sarcasmo ("excelente servicio, \
tres horas esperando") es neg.

2. kind — lo que hace el comentario:
- complaint: se queja o reclama algo al negocio (pedido, trato, demora, calidad, precio).
- question: pregunta o pide algo al negocio (precio, información, dirección, horario, \
envíos, "info", "dm", "precio", "me escriben"), aunque no use signos de pregunta.
- praise: solo elogia o agradece, sin pedir nada.
- other: etiquetas o menciones a otras personas sin pedir nada, conversación entre \
usuarios, publicidad ajena, spam, emojis sueltos sin tono claro, texto sin sentido.
Si un comentario se queja y además pregunta, es complaint. Si elogia y pregunta, es \
question.

3. needs_reply — si el negocio le debe una respuesta a esa persona:
- true para toda question y toda complaint, y para un pedido directo al negocio.
- false para praise (agradecer es opcional) y para other.

Reglas:
- Juzga solo el texto del comentario; no inventes contexto.
- Responde SIEMPRE llamando a la herramienta registrar_comentarios, con una entrada por \
cada comentario recibido, usando su número.
"""

#: `atender4a.1-conf`: `SYSTEM_PROMPT` word for word plus the confidence section, so any
#: difference measured against `atender4a.1` comes from asking for the confidence.
SYSTEM_PROMPT_CONFIDENCE: Final = SYSTEM_PROMPT.replace(
    "\nReglas:\n",
    """
4. confidence — qué tan seguro estás del sentiment que elegiste, un número de 0 a 1:
- 0.9 o más cuando el tono es inequívoco ("qué rico", "pésimo servicio").
- entre 0.5 y 0.8 cuando dudas entre dos tonos: posible sarcasmo, solo emojis, \
mezcla de elogio y queja, texto muy corto o sin contexto.
- menos de 0.5 cuando casi adivinas.
No pongas siempre el mismo valor: debe reflejar la duda de cada comentario.

Reglas:
""",
    1,
)


@dataclass(frozen=True)
class TriagePrompt:
    system: str
    with_confidence: bool


TRIAGE_PROMPTS: Final[Mapping[str, TriagePrompt]] = {
    TRIAGE_PROMPT_VERSION: TriagePrompt(SYSTEM_PROMPT, with_confidence=False),
    TRIAGE_PROMPT_VERSION_CONFIDENCE: TriagePrompt(SYSTEM_PROMPT_CONFIDENCE, with_confidence=True),
}


def _triage_tool(*, with_confidence: bool = False) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "id": {"type": "integer"},
        "sentiment": {"type": "string", "enum": [s.value for s in Sentiment]},
        "kind": {"type": "string", "enum": [k.value for k in CommentKind]},
        "needs_reply": {"type": "boolean"},
    }
    description = "Registra sentimiento, tipo y si necesita respuesta de cada comentario."
    if with_confidence:
        # Strict tool schemas reject `minimum`/`maximum`: the range is in the prompt and
        # `parse_confidence` clamps.
        properties["confidence"] = {
            "type": "number",
            "description": "Confianza en el sentiment, de 0 a 1.",
        }
        description = (
            "Registra sentimiento (con su confianza), tipo y si necesita respuesta de "
            "cada comentario."
        )
    return strict_tool(
        TRIAGE_TOOL,
        description,
        {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": properties,
                    "required": list(properties),
                    "additionalProperties": False,
                },
            }
        },
    )


def parse_confidence(raw: Any) -> float | None:
    """A model confidence into 0..1, or None when it is not a finite number (a bool is
    not a number here, whatever Python says)."""
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    value = float(raw)
    if not math.isfinite(value):
        return None
    return min(1.0, max(0.0, value))


def _user_message(texts: Sequence[str]) -> str:
    lines = "\n".join(f"{i}. {' '.join(text.split())}" for i, text in enumerate(texts, 1))
    return f"Comentarios ({len(texts)}):\n{lines}"


def parse_triage(
    item: Any, *, model_id: str, prompt_version: str, with_confidence: bool = False
) -> Triage | None:
    """One tool-result entry into a `Triage`, or None when anything is off-contract.
    A complaint or question always needs a reply, whatever the model said: that is the
    labeling rule, and it can only raise `needs_reply` (the recall-critical side). A
    missing or malformed confidence leaves `confidence=None` but keeps the labels."""
    if not isinstance(item, dict):
        return None
    try:
        sentiment = Sentiment(item.get("sentiment"))
        kind = CommentKind(item.get("kind"))
    except ValueError:
        return None
    needs = item.get("needs_reply")
    if not isinstance(needs, bool):
        return None
    if kind in (CommentKind.QUESTION, CommentKind.COMPLAINT):
        needs = True
    return Triage(
        sentiment=sentiment,
        kind=kind,
        needs_reply=needs,
        model_id=model_id,
        prompt_version=prompt_version,
        confidence=parse_confidence(item.get("confidence")) if with_confidence else None,
    )


ClientFactory = Callable[[str], Any]


@dataclass
class ClaudeCommentTriager:
    api_key: str
    config: ModelConfig = ModelConfig(TRIAGE_MODEL, TRIAGE_EFFORT)
    client_factory: ClientFactory | None = None
    batch_size: int = TRIAGE_BATCH
    prompt_version: str = TRIAGE_PROMPT_VERSION
    #: Alias ids are not pinned revisions — NULL, same honest-null rule as intent.
    model_revision: str | None = None

    def __post_init__(self) -> None:
        if self.prompt_version not in TRIAGE_PROMPTS:
            known = ", ".join(sorted(TRIAGE_PROMPTS))
            raise ValueError(f"unknown triage prompt {self.prompt_version!r} (known: {known})")
        self._prompt = TRIAGE_PROMPTS[self.prompt_version]
        self._client: Any = None
        self.last_stats: list[CallStats] = []
        #: Wall time of each batch call, seconds (evals report p50/p95 per batch).
        self.last_latencies_s: list[float] = []

    @property
    def model_id(self) -> str:
        return self.config.model_id

    @observability.traced("clasificar comentarios para responder", tags=("interacciones",))
    def triage(self, texts: Sequence[str]) -> list[Triage | None]:
        self.last_stats = []
        self.last_latencies_s = []
        results: list[Triage | None] = []
        for start in range(0, len(texts), self.batch_size):
            began = time.perf_counter()
            found, stats = self._triage_batch(texts[start : start + self.batch_size])
            self.last_latencies_s.append(time.perf_counter() - began)
            self.last_stats.append(stats)
            results.extend(found)
        return results

    def _triage_batch(self, texts: Sequence[str]) -> tuple[list[Triage | None], CallStats]:
        if self._client is None:
            self._client = (self.client_factory or default_client)(self.api_key)
        meter = Meter(self.config)
        response = create_turn(
            self._client,
            self.config,
            meter,
            system=self._prompt.system,
            messages=[{"role": "user", "content": _user_message(texts)}],
            tools=[_triage_tool(with_confidence=self._prompt.with_confidence)],
            tool_choice=forced_or_auto(self.config, TRIAGE_TOOL),
            max_tokens=max(4096, 100 * len(texts)),
        )
        calls = [b for b in tool_uses(response) if b.name == TRIAGE_TOOL]
        if not calls:
            raise ClaudeToolError(f"{self.config.model_id} did not call {TRIAGE_TOOL}")
        meter.tool_calls = 1
        by_id: dict[int, Triage | None] = {}
        for item in (calls[0].input or {}).get("results") or []:
            index = item.get("id") if isinstance(item, dict) else None
            if not isinstance(index, int) or not 1 <= index <= len(texts) or index in by_id:
                continue
            by_id[index] = parse_triage(
                item,
                model_id=self.model_id,
                prompt_version=self.prompt_version,
                with_confidence=self._prompt.with_confidence,
            )
        return [by_id.get(i) for i in range(1, len(texts) + 1)], meter.stats()


__all__ = [
    "SYSTEM_PROMPT",
    "SYSTEM_PROMPT_CONFIDENCE",
    "TRIAGE_MODEL",
    "TRIAGE_PROMPTS",
    "TRIAGE_PROMPT_VERSION",
    "TRIAGE_PROMPT_VERSION_CONFIDENCE",
    "ClaudeCommentTriager",
    "CommentKind",
    "CommentTriager",
    "Sentiment",
    "Triage",
    "TriagePrompt",
    "parse_confidence",
    "parse_triage",
]

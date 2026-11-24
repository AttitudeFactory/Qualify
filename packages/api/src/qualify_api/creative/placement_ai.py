"""Where a video's text and logo go, read from what the video shows (EF-20, m-25026599).

Phase 1 of the ticket: the decision alone, NOT wired to the compose step yet (EF-18 is
changing `media.py`, `video_pipeline/local.py`, `recompose.py`, `part_join.py` and the
contact sheet; phase 2 connects this behind `PLACEMENT_SWITCH`, off by default).

Deivid's decision (2026-11-23, via «creacion de tickets»): a vision model, the same way
the reel analysis reads frames (`qualify_api.referentes.reel_analysis_ai`), with Claude
Haiku 5.5. `VisionPlacer.place` sends 1 to 3 frames of the PREPARED video (upright, 9:16,
at most 720×1280 — `sample_placement_frames`) and asks where the subject or product is,
in the three bands the text catalog already has (`VIDEO_TEXT_PLACES`: `top`, `middle`,
`bottom`, thirds of the frame). The answer is the band for the text, the band for the
logo and a short reason, plus the bands the subject occupies — so `resolve_places` can
check the model against itself: a text or logo band the model itself says the subject
covers moves to a free band (`adjustments` records it).

Guards, as in the reel analysis:

- **per request:** `worst_request_usd` prices the worst the one call can bill (the
  cached prefix as a cache write, `IMAGE_TOKEN_CEILING` per frame, `MAX_OUTPUT_TOKENS`
  of output, thinking included) and a test pins it under `MAX_REQUEST_USD`; a request over
  it is never sent. Prices: `claude_tools.PRICES`, the mirror of the versioned table
  (`qualify_creative/pricing_data/v10.json`, entry `claude-haiku-5-5`, unchanged).
- **per piece and per fleet:** an injected `CallGuard` counts the call BEFORE it is made
  (`charge`): at most `MAX_CALLS_PER_PIECE` per piece and `fleet_daily()` a day for every
  business together. `InMemoryCallGuard` is the one for tests and evals; phase 2's
  Postgres-backed one is `placement_advice.SourceCallGuard` over
  `PostgresPlacementLedger` (reservations in `creative_usage_events` under an advisory
  lock), since several worker processes share the daily cap.
- **per run (optional):** a `DollarMeter` (`budget`) reserves the worst case of the turn
  and settles it with what was billed — the eval's hard ceiling.

Any failure — frames that do not fit, no key, a guard that says no, a refusal, a cut or
malformed answer, a network error — returns today's places (`FALLBACK_TEXT_PLACE` =
`bottom`, `FALLBACK_LOGO_PLACE` = `top`, the fixed top-left corner of
`qualify_creative.compose._logo`) with the reason code; `place` never raises. What a
failed call billed is still recorded (`cost_usd`).

Provenance (`PlacementDecision.provenance`): model id and revision, effort, prompt version
and fingerprint, the frames used (time, size, sha256 prefix), tokens, cost and the
pricing table version. The call is booked by `claude_tools.messages_create` to the piece's
business, feature `FEATURE`.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import os
import threading
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from qualify_creative.schemas import VIDEO_TEXT_PLACES

from qualify_api.claude_tools import (
    CACHE_WRITE_MULTIPLIER,
    PRICES,
    PRICING_TABLE_VERSION,
    Attribution,
    BudgetExhausted,
    ClaudeToolError,
    ClientFactory,
    DollarMeter,
    Meter,
    MissingAPIKey,
    ModelConfig,
    api_key_from_env,
    create_turn,
    default_client,
    forced_or_auto,
    request_bytes,
    strict_tool,
    tool_uses,
)

logger = logging.getLogger(__name__)

#: Deivid, 2026-11-23: Haiku 5.5 (id and price from the `claude-api` skill, cached
#: 2026-11-03: $0.10 in / $0.50 out per million tokens up to 100K-token prompts; the
#: versioned table `pricing_data/v10.json` already carries it).
MODEL_ID = "claude-haiku-5-5"
#: Haiku 5.5 thinks by default (adaptive, default effort `medium`); `low` is enough to find
#: a product in three frames and keeps the output — thinking included — short.
MODEL_EFFORT = "low"
MODEL = ModelConfig(MODEL_ID, MODEL_EFFORT)

#: Bump with any change to what the model reads (system prompt, tool, message layout, frame
#: limits): `prompt_fingerprint` is pinned next to it by a test.
PLACEMENT_PROMPT_VERSION = "placement-prompt-1"
#: The consumption ledger's function name for this call.
FEATURE = "video-placement"

TEXT_PLACE = "text"
LOGO_PLACE = "logo"
#: Today's places (phase 2 keeps them whenever this module falls back): the text at the
#: bottom (`VideoTextLayer.place`'s default) and the logo in its fixed top corner.
FALLBACK_TEXT_PLACE = "bottom"
FALLBACK_LOGO_PLACE = "top"
#: When the model's band is covered by the subject (by its own answer), the first free
#: band in this order — the text keeps to the bottom when it can, the logo to the top.
TEXT_PREFERENCE: tuple[str, ...] = ("bottom", "top", "middle")
LOGO_PREFERENCE: tuple[str, ...] = ("top", "bottom", "middle")

#: 1 to 3 frames of the prepared video; each fits 720×1280 (portrait or landscape) — the
#: same box as the reel analysis' frames.
MIN_FRAMES = 1
MAX_FRAMES = 3
FRAME_BOX: tuple[int, int] = (720, 1280)
MAX_FRAME_BYTES = 1_500_000
#: Where the frames are taken in the prepared video (share of its length).
FRAME_POSITIONS: tuple[float, ...] = (0.2, 0.5, 0.8)
FRAME_JPEG_QUALITY = 85

#: Tokens of one image are ≈ width × height / 750: a 720×1280 frame is 1,229. The bound
#: counts 1,600 per image (the reel analysis' ceiling), whatever the frame's size.
IMAGE_TOKEN_CEILING = 1600
#: Tool-use system prompt and per-message framing the API adds around the request bytes.
FRAMING_MARGIN_TOKENS = 1000
#: Output, thinking included (Haiku 5.5 counts its thinking inside `max_tokens`). The
#: answer itself is ~150 tokens; the rest is room for thinking at `low`.
MAX_OUTPUT_TOKENS = 2048
#: The bound of the worst request (3 frames at the image ceiling, the prefix as a cache
#: write, `MAX_OUTPUT_TOKENS` of output): USD 0.001943 with prompt 1
#: (`test_the_worst_request_is_pinned`). A request over it is never sent.
MAX_REQUEST_USD = Decimal("0.0021")

#: A piece asks at most this many times in its life (a regeneration included).
MAX_CALLS_PER_PIECE = 2
FLEET_DAILY_ENV = "QUALIFY_VIDEO_PLACEMENT_FLEET_DAILY"
#: Calls a day for every business together: 1,500 x the bound = at most USD 3.15 a day.
DEFAULT_FLEET_DAILY = 1500
#: Phase 2's switch (off by default): until it is `on` the compose step keeps today's
#: places and this module is never called.
PLACEMENT_SWITCH = "QUALIFY_VIDEO_PLACEMENT_AI"

#: Fallback reason codes (`PlacementDecision.fallback_reason`).
FALLBACK_BAD_FRAMES = "bad_frames"
FALLBACK_OVER_BOUND = "over_bound"
FALLBACK_NO_KEY = "no_key"
FALLBACK_GUARD = "guard_refused"
FALLBACK_BUDGET = "budget_exhausted"
FALLBACK_MODEL_ERROR = "model_error"
FALLBACK_REQUEST_ERROR = "request_error"
FALLBACK_NO_TOOL = "no_tool_call"
FALLBACK_BAD_ANSWER = "bad_answer"

TOOL_NAME = "ubicar_texto_y_logo"
SUBJECT_MAX = 120
REASON_MAX = 200

SYSTEM_PROMPT = """\
You place two layers on a short vertical video (9:16) of a small business: a block of \
text (one or two lines across most of the width) and the business's logo (a small mark, \
about a sixth of the width, in a corner). Neither may cover the subject.

The subject is what the video sells or shows: the product, the dish or drink, the \
place, or the person presenting it. If there is none, it is the most important element \
of the image.

You get 1 to 3 frames of the same video, in time order. Split each frame into three \
equal horizontal bands: "top" (upper third), "middle" (central third) and "bottom" \
(lower third). The layers stay in the same band for the whole video, so judge all the \
frames together.

Call the tool `ubicar_texto_y_logo` once:
- `subject`: what the subject is, in a few words of Spanish.
- `subject_bands`: every band where the subject appears in ANY frame (a band counts when \
the subject fills a visible part of it, not when only an edge touches it).
- `text_place`: the band for the text — one the subject does not occupy. Prefer "bottom" \
when it is free, then "top".
- `logo_place`: the band for the logo — free of the subject and, when possible, not the \
text's band. Prefer "top" when it is free.
- `reason`: one short sentence in plain Spanish, no English words, saying where the \
subject is and why the layers go where they go.
If the subject fills every band, choose the band where the layers cover the least of it \
and say so in `reason`.
"""


class PlacementRefused(RuntimeError):
    """A `CallGuard` said no; `reason` is `piece_cap` or `fleet_cap`."""

    def __init__(self, reason: str, message: str = "") -> None:
        super().__init__(message or reason)
        self.reason = reason


class CallGuard(Protocol):
    """Counts a model call BEFORE it is made; raises `PlacementRefused` when it may not."""

    def charge(self, piece_id: UUID) -> None: ...


def fleet_daily(env: Mapping[str, str] | None = None) -> int:
    raw = (env if env is not None else os.environ).get(FLEET_DAILY_ENV, "").strip()
    try:
        value = int(raw) if raw else DEFAULT_FLEET_DAILY
    except ValueError:
        return DEFAULT_FLEET_DAILY
    return max(0, value)


def placement_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Phase 2's switch: `on` / `1` / `true` turns the vision placement on."""
    raw = (env if env is not None else os.environ).get(PLACEMENT_SWITCH, "")
    return raw.strip().lower() in {"on", "1", "true"}


@dataclass
class InMemoryCallGuard:
    """Per-piece and fleet caps in one process (tests, evals). The fleet window is the
    last 24 h. Thread-safe."""

    per_piece: int = MAX_CALLS_PER_PIECE
    fleet_cap: int = field(default_factory=fleet_daily)
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    _pieces: dict[UUID, int] = field(default_factory=dict, init=False, repr=False)
    _fleet: deque[datetime] = field(default_factory=deque, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def charge(self, piece_id: UUID) -> None:
        with self._lock:
            now = self.clock()
            while self._fleet and self._fleet[0] <= now - timedelta(hours=24):
                self._fleet.popleft()
            if self._pieces.get(piece_id, 0) >= self.per_piece:
                raise PlacementRefused("piece_cap", f"piece {piece_id}: {self.per_piece} calls")
            if len(self._fleet) >= self.fleet_cap:
                raise PlacementRefused("fleet_cap", f"fleet: {self.fleet_cap} calls a day")
            self._pieces[piece_id] = self._pieces.get(piece_id, 0) + 1
            self._fleet.append(now)


@dataclass(frozen=True)
class PlacementFrame:
    """One still of the prepared video: a JPEG fitting `FRAME_BOX`, and when it was taken."""

    jpeg: bytes = field(repr=False)
    width: int
    height: int
    at_s: float | None = None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.jpeg).hexdigest()


@dataclass(frozen=True)
class PlacementDecision:
    """Where the text and the logo go. `source` is `model` or `fallback`; on a fallback
    `fallback_reason` says why and the places are today's."""

    text_place: str
    logo_place: str
    reason: str
    source: str
    fallback_reason: str | None = None
    subject: str | None = None
    subject_bands: tuple[str, ...] = ()
    #: `(layer, from, to)` of every band `resolve_places` moved.
    adjustments: tuple[tuple[str, str, str], ...] = ()
    cost_usd: Decimal = Decimal(0)
    provenance: Mapping[str, Any] = field(default_factory=dict)

    @property
    def fell_back(self) -> bool:
        return self.source == "fallback"


def frame_problems(frames: Sequence[PlacementFrame]) -> list[str]:
    """Why these frames cannot be sent; empty when they can."""
    problems: list[str] = []
    if not MIN_FRAMES <= len(frames) <= MAX_FRAMES:
        problems.append(f"{len(frames)} frames (allowed {MIN_FRAMES}-{MAX_FRAMES})")
    short_box, long_box = sorted(FRAME_BOX)
    for i, frame in enumerate(frames, 1):
        short, long_ = sorted((frame.width, frame.height))
        if short < 1 or short > short_box or long_ > long_box:
            problems.append(f"frame {i}: {frame.width}x{frame.height} outside {FRAME_BOX}")
        if not frame.jpeg.startswith(b"\xff\xd8") or len(frame.jpeg) > MAX_FRAME_BYTES:
            problems.append(f"frame {i}: not a JPEG of at most {MAX_FRAME_BYTES} bytes")
    return problems


def _seconds(value: float | None) -> str:
    return "" if value is None else f" (segundo {value:.1f})"


def placement_tool() -> dict[str, Any]:
    band = {"type": "string", "enum": list(VIDEO_TEXT_PLACES)}
    return strict_tool(
        TOOL_NAME,
        "Records where the subject is and the band for the text and for the logo.",
        {
            "subject": {"type": "string", "description": "What the subject is, in Spanish."},
            "subject_bands": {"type": "array", "items": band},
            "text_place": band,
            "logo_place": band,
            "reason": {"type": "string", "description": "One short sentence in Spanish."},
        },
    )


def build_messages(frames: Sequence[PlacementFrame]) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = []
    for i, frame in enumerate(frames, 1):
        content.append(
            {"type": "text", "text": f"Cuadro {i} de {len(frames)}{_seconds(frame.at_s)}:"}
        )
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": base64.standard_b64encode(frame.jpeg).decode("ascii"),
                },
            }
        )
    content.append(
        {"type": "text", "text": f"Ubica el texto y el logo: llama a `{TOOL_NAME}` una vez."}
    )
    return [{"role": "user", "content": content}]


def _text_bytes(messages: list[dict[str, Any]]) -> int:
    text = [
        {**m, "content": [b for b in m["content"] if b.get("type") != "image"]} for m in messages
    ]
    return request_bytes("", text, [])


def _images(messages: list[dict[str, Any]]) -> int:
    return sum(1 for m in messages for b in m["content"] if b.get("type") == "image")


def input_token_ceiling(messages: list[dict[str, Any]]) -> tuple[int, int]:
    """`(prefix_tokens, message_tokens)` at most: the prefix (system + tool; a token is
    never shorter than a byte) and the message (text bytes + `IMAGE_TOKEN_CEILING` per
    image — the base64 says nothing about image tokens)."""
    prefix = request_bytes(SYSTEM_PROMPT, [], [placement_tool()]) + FRAMING_MARGIN_TOKENS
    return prefix, _text_bytes(messages) + _images(messages) * IMAGE_TOKEN_CEILING


def worst_request_usd(
    messages: list[dict[str, Any]], max_tokens: int = MAX_OUTPUT_TOKENS
) -> Decimal:
    """The most the one call can bill, with `PRICES`: the prefix as a cache write, the
    message at the input rate and `max_tokens` of output (thinking included)."""
    price_in, price_out = PRICES[MODEL_ID]
    prefix, body = input_token_ceiling(messages)
    usd = prefix * price_in * CACHE_WRITE_MULTIPLIER + body * price_in + max_tokens * price_out
    return Decimal(repr(usd / 1_000_000)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def prompt_fingerprint() -> str:
    """What the model reads that is not data; pinned next to `PLACEMENT_PROMPT_VERSION`."""
    material = json.dumps(
        {
            "system": SYSTEM_PROMPT,
            "tool": placement_tool(),
            "layout": build_messages(
                [PlacementFrame(jpeg=b"\xff\xd8", width=720, height=1280, at_s=1.0)]
            ),
            "frames": [MIN_FRAMES, MAX_FRAMES, list(FRAME_BOX), list(FRAME_POSITIONS)],
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "effort": MODEL_EFFORT,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _first_free(preference: Sequence[str], taken: set[str]) -> str | None:
    return next((band for band in preference if band not in taken), None)


def resolve_places(
    text_place: str, logo_place: str, subject_bands: Sequence[str]
) -> tuple[str, str, tuple[tuple[str, str, str], ...]]:
    """The model's bands, checked against its own `subject_bands`: a layer on a band the
    subject occupies moves to the first free band of its preference (the logo also avoids
    the text's band when it can). When the subject fills every band the model's choice
    stays — it was told to pick the least covered one."""
    covered = set(subject_bands)
    moves: list[tuple[str, str, str]] = []
    text = text_place
    if text in covered:
        free = _first_free(TEXT_PREFERENCE, covered)
        if free is not None:
            moves.append((TEXT_PLACE, text, free))
            text = free
    logo = logo_place
    if logo in covered or logo == text:
        free = _first_free(LOGO_PREFERENCE, covered | {text})
        if free is None and logo in covered:
            free = _first_free(LOGO_PREFERENCE, covered)  # shares the text's band
        if free is not None and free != logo:
            moves.append((LOGO_PLACE, logo, free))
            logo = free
    return text, logo, tuple(moves)


def _clip(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def parse_answer(raw: Any) -> dict[str, Any] | None:
    """The tool input, validated; None when it is unusable."""
    if not isinstance(raw, Mapping):
        return None
    text, logo = raw.get("text_place"), raw.get("logo_place")
    bands = raw.get("subject_bands")
    if text not in VIDEO_TEXT_PLACES or logo not in VIDEO_TEXT_PLACES:
        return None
    if not isinstance(bands, list) or any(b not in VIDEO_TEXT_PLACES for b in bands):
        return None
    reason = _clip(raw.get("reason"), REASON_MAX)
    if not reason:
        return None
    ordered = tuple(b for b in VIDEO_TEXT_PLACES if b in set(bands))
    return {
        "subject": _clip(raw.get("subject"), SUBJECT_MAX) or None,
        "subject_bands": ordered,
        "text_place": text,
        "logo_place": logo,
        "reason": reason,
    }


def _usd(value: float) -> Decimal:
    return Decimal(repr(value)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


class VisionPlacer:
    """See the module docstring. Collaborators are injectable: the guard (required), the
    client factory (a fake in tests) and the key."""

    def __init__(
        self,
        *,
        guard: CallGuard,
        api_key: str | None = None,
        client_factory: ClientFactory | None = None,
        config: ModelConfig = MODEL,
    ) -> None:
        self._guard = guard
        self._api_key = api_key
        self._client_factory = client_factory or default_client
        self._config = config

    def _provenance(self, frames: Sequence[PlacementFrame], **extra: Any) -> dict[str, Any]:
        return {
            "model_id": self._config.model_id,
            "effort": self._config.effort,
            "prompt_version": PLACEMENT_PROMPT_VERSION,
            "prompt_fingerprint": prompt_fingerprint(),
            "pricing_table_version": PRICING_TABLE_VERSION,
            "frames": [
                {"at_s": f.at_s, "width": f.width, "height": f.height, "sha256": f.sha256[:16]}
                for f in frames
            ],
            **extra,
        }

    def _fallback(
        self,
        frames: Sequence[PlacementFrame],
        code: str,
        detail: str,
        *,
        meter: Meter | None = None,
    ) -> PlacementDecision:
        stats = meter.stats() if meter is not None else None
        cost = _usd(stats.cost_usd) if stats is not None else Decimal(0)
        extra: dict[str, Any] = {"detail": detail[:300]}
        if stats is not None and stats.turns:
            extra.update(
                model_revision=stats.model_revision,
                input_tokens=stats.input_tokens
                + stats.cache_read_tokens
                + stats.cache_creation_tokens,
                output_tokens=stats.output_tokens,
            )
        logger.info("video placement fell back (%s): %s", code, detail[:300])
        return PlacementDecision(
            text_place=FALLBACK_TEXT_PLACE,
            logo_place=FALLBACK_LOGO_PLACE,
            reason="Lugar de siempre: texto abajo y logo arriba.",
            source="fallback",
            fallback_reason=code,
            cost_usd=cost,
            provenance=self._provenance(frames, **extra),
        )

    def place(
        self,
        frames: Sequence[PlacementFrame],
        *,
        tenant_id: UUID,
        piece_id: UUID,
        brand_id: UUID | None = None,
        budget: DollarMeter | None = None,
    ) -> PlacementDecision:
        """Never raises: any failure returns today's places (see the module docstring)."""
        frames = list(frames)
        problems = frame_problems(frames)
        if problems:
            return self._fallback(frames, FALLBACK_BAD_FRAMES, "; ".join(problems))
        messages = build_messages(frames)
        worst = worst_request_usd(messages)
        if worst > MAX_REQUEST_USD:
            return self._fallback(frames, FALLBACK_OVER_BOUND, f"worst {worst} USD")
        try:
            api_key = self._api_key or api_key_from_env()
        except MissingAPIKey as error:
            return self._fallback(frames, FALLBACK_NO_KEY, str(error))
        try:
            self._guard.charge(piece_id)  # counted BEFORE the call
        except PlacementRefused as error:
            return self._fallback(frames, FALLBACK_GUARD, f"{error.reason}: {error}")
        except Exception as error:  # noqa: BLE001 — a broken guard never lets a call through
            return self._fallback(frames, FALLBACK_GUARD, f"guard error: {error}")
        meter = Meter(self._config)
        prefix, body = input_token_ceiling(messages)
        try:
            client = self._client_factory(api_key)
            response = create_turn(
                client,
                self._config,
                meter,
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=[placement_tool()],
                tool_choice=forced_or_auto(self._config, TOOL_NAME),
                max_tokens=MAX_OUTPUT_TOKENS,
                attribution=Attribution(
                    tenant_id=tenant_id,
                    feature=FEATURE,
                    brand_id=brand_id,
                    prompt_version=PLACEMENT_PROMPT_VERSION,
                ),
                budget=budget,
                input_ceiling=prefix + body,
            )
        except BudgetExhausted as error:
            return self._fallback(frames, FALLBACK_BUDGET, str(error), meter=meter)
        except ClaudeToolError as error:
            return self._fallback(frames, FALLBACK_MODEL_ERROR, str(error), meter=meter)
        except Exception as error:  # noqa: BLE001 — network, 4xx, 5xx: today's places
            return self._fallback(
                frames, FALLBACK_REQUEST_ERROR, f"{type(error).__name__}: {error}", meter=meter
            )
        calls = [b for b in tool_uses(response) if getattr(b, "name", None) == TOOL_NAME]
        if not calls:
            return self._fallback(frames, FALLBACK_NO_TOOL, f"{TOOL_NAME} not called", meter=meter)
        meter.tool_calls = 1
        answer = parse_answer(calls[0].input)
        if answer is None:
            return self._fallback(
                frames, FALLBACK_BAD_ANSWER, f"unusable: {calls[0].input!r}"[:300], meter=meter
            )
        text, logo, moves = resolve_places(
            answer["text_place"], answer["logo_place"], answer["subject_bands"]
        )
        stats = meter.stats()
        return PlacementDecision(
            text_place=text,
            logo_place=logo,
            reason=answer["reason"],
            source="model",
            subject=answer["subject"],
            subject_bands=answer["subject_bands"],
            adjustments=moves,
            cost_usd=_usd(stats.cost_usd),
            provenance=self._provenance(
                frames,
                model_revision=stats.model_revision,
                input_tokens=stats.input_tokens
                + stats.cache_read_tokens
                + stats.cache_creation_tokens,
                output_tokens=stats.output_tokens,
                model_places={"text": answer["text_place"], "logo": answer["logo_place"]},
                worst_request_usd=str(worst),
            ),
        )


def frame_from_image(image: Any, *, at_s: float | None = None) -> PlacementFrame:
    """A PIL image as a `PlacementFrame`: fitted inside `FRAME_BOX` (never upscaled), RGB,
    JPEG at `FRAME_JPEG_QUALITY`."""
    import io

    rgb = image.convert("RGB")
    short_box, long_box = sorted(FRAME_BOX)
    short, long_ = sorted(rgb.size)
    scale = min(1.0, short_box / max(1, short), long_box / max(1, long_))
    if scale < 1.0:
        size = (max(2, math.floor(rgb.width * scale)), max(2, math.floor(rgb.height * scale)))
        rgb = rgb.resize(size)
    buffer = io.BytesIO()
    rgb.save(buffer, format="JPEG", quality=FRAME_JPEG_QUALITY)
    return PlacementFrame(jpeg=buffer.getvalue(), width=rgb.width, height=rgb.height, at_s=at_s)


def sample_placement_frames(
    source: str | os.PathLike[str],
    duration_s: float,
    *,
    positions: Sequence[float] = FRAME_POSITIONS,
) -> list[PlacementFrame]:
    """The frames at `positions` (shares of `duration_s`) of the prepared video at
    `source`, upright and fitted inside `FRAME_BOX` (`qualify_creative.video.shots`)."""
    from qualify_creative.video.shots import SamplingPlan, ShotSpan, sample_frames

    if duration_s <= 0 or not positions:
        return []
    plan = SamplingPlan(
        positions=tuple(positions),
        two_frames_min_s=0.0,
        anchors=(),
        max_frames=MAX_FRAMES,
        box=FRAME_BOX,
        jpeg_quality=FRAME_JPEG_QUALITY,
    )
    stills = sample_frames(Path(source), [ShotSpan(0, 0.0, float(duration_s))], plan=plan)
    return [
        PlacementFrame(jpeg=s.jpeg, width=s.width, height=s.height, at_s=s.time_s) for s in stills
    ]


__all__ = [
    "DEFAULT_FLEET_DAILY",
    "FALLBACK_LOGO_PLACE",
    "FALLBACK_TEXT_PLACE",
    "FEATURE",
    "FLEET_DAILY_ENV",
    "MAX_CALLS_PER_PIECE",
    "MAX_FRAMES",
    "MAX_OUTPUT_TOKENS",
    "MAX_REQUEST_USD",
    "MODEL",
    "MODEL_ID",
    "PLACEMENT_PROMPT_VERSION",
    "PLACEMENT_SWITCH",
    "CallGuard",
    "InMemoryCallGuard",
    "PlacementDecision",
    "PlacementFrame",
    "PlacementRefused",
    "VisionPlacer",
    "build_messages",
    "fleet_daily",
    "frame_from_image",
    "frame_problems",
    "parse_answer",
    "placement_enabled",
    "placement_tool",
    "prompt_fingerprint",
    "resolve_places",
    "sample_placement_frames",
    "worst_request_usd",
]

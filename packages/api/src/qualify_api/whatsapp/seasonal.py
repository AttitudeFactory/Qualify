"""The business's seasonal library of stickers and short videos (m-24976891, design
`docs/opciones-stickers-videos-cortos.md` §1, §7–§9; founder decision 2026-11-08: beta at
zero cost with recipes B + E in `media-worker`, «Crear con IA» per piece).

## Why it lives in `whatsapp/`

What it makes is only ever SENT in a WhatsApp chat (a sticker cannot be published to the
networks), and its consumers are the chat's send menu and the outbox. It reads pieces and
the logo as SOURCES (provenance), the way the chat picker does; the creative module keeps
owning pieces.

## The table and the file

`brand_seasonal_media` (0145): one sticker (animated WebP, ≤ 500 KB) or short silent
video (MP4) per (business, season, recipe, source) — the unique slot makes `plan_batch`
idempotent. **Provenance** (hard rule): `source_kind` + `source_ref` + `recipe` +
`pipeline_version`, plus `cost_usd` (0 for B/E). The file lives at
`seasonal/{tenant}/{brand}/{season_key}/{media_id}.{webp|mp4}` (`ObjectGate.
put_seasonal_media`), OUTSIDE `t/` and outside the ADR 39 purge (amendment 2026-11-08):
past seasons are kept; the owner archives a season, and only deleting it deletes files.

## The life of a medium

`pending` (planned, job queued) → `ready` (the worker stored the file: `mark_ready`) or
`failed` (`mark_failed`); `ready` → `approved` (the owner, `approve`) or `rejected`
(`reject`). Any status → `deleted` («Eliminar», `delete`, m-25016851): the row stays for
provenance (recipe, source, `cost_usd`, and the paid `creative_jobs` rows a hard delete
would cascade away), its file fields are cleared, every attempt's R2 file is deleted
through the gate, and it never shows again — not in the library, not in the chat.
Archiving a season (`archive`) moves its `approved` rows to `archived` and
stamps `archived_at` on all of them; `restore` brings them back. **Only `approved` rows of
an unarchived season reach the chat** (`list_approved_for_chat`) — stricter than pieces,
as the founder asked. Nothing here sends anything: the chat sends on the owner's tap.

## The queue contract (for the recipes in `media-worker`)

`plan_batch` enqueues ONE `gallery_jobs` row per new medium (the `media-worker` queue,
0133), `kind = 'seasonal_media'`, `idempotency_key = 'seasonal:{media_id}:{attempt}'`,
`pipeline_version = SEASONAL_PIPELINE_VERSION`, and `payload`:

    {"media_id": "<uuid>", "tenant_id": "<uuid>", "brand_id": "<uuid>",
     "kind": "sticker" | "video", "recipe": "e-latido" | "b-zoom" | …,
     "source_kind": "piece" | "logo" | "text", "source_ref": "<draft ids, comma-separated
     | logo key | text>", "season_key": "navidad-2026", "attempt": 1}

The worker renders the recipe, writes the file with `ObjectGate.put_seasonal_media(…,
attempt=payload["attempt"])` — the key is `…/{season}/{media_id}-{attempt}.{webp|mp4}` —
and calls `SeasonalMediaService.mark_ready(tenant_id=…, brand_id=…, media_id=…,
attempt=…, object_key=…, bytes=…, width=…, height=…, duration_ms=…, cost_usd=…)`, or
`mark_failed(tenant_id=…, brand_id=…, media_id=…, attempt=…, reason=…)`. A result of an
older attempt is refused (`StaleAttempt`): drop it.

«Pedir otro» (`request_another`) reuses the SAME row (the slot stays unique): `attempt`
+1 (no owner-facing cap since m-25016851; `MAX_ATTEMPTS` = 99 is only the key format's
technical ceiling), back to `pending`, file fields cleared, a NEW job
`seasonal:{media_id}:{attempt}` in the same transaction; the previous file is deleted
through the gate by its exact key after that commit.

The worker claims only the kinds it knows, so these jobs wait (queued) until the recipes
ship.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal
from typing import Any, Final, Literal, Protocol
from uuid import UUID, uuid4

from qualify_shared.objects.keys import (
    SEASON_KEY_RE,
    SEASONAL_MAX_ATTEMPTS,
    seasonal_media_key,
)

SEASONAL_PIPELINE_VERSION: Final = "seasonal-v1"
JOB_KIND: Final = "seasonal_media"
MAX_LABEL_CHARS: Final = 24

STATUS_PENDING: Final = "pending"
STATUS_READY: Final = "ready"
STATUS_APPROVED: Final = "approved"
STATUS_REJECTED: Final = "rejected"
STATUS_ARCHIVED: Final = "archived"
STATUS_FAILED: Final = "failed"
#: «Eliminar» (m-25016851): kept for provenance, never shown, no file.
STATUS_DELETED: Final = "deleted"

KIND_STICKER: Final = "sticker"
KIND_VIDEO: Final = "video"
EXTENSIONS: Final = {KIND_STICKER: "webp", KIND_VIDEO: "mp4"}

SOURCE_PIECE: Final = "piece"
SOURCE_LOGO: Final = "logo"
SOURCE_TEXT: Final = "text"

Mode = Literal["free", "ai"]

#: The paid recipe (m-24976893): Seedance, run by `creative-worker` as a `creative_jobs`
#: row of kind `seasonal_video` (0146) — never by `media-worker`.
AI_RECIPE: Final = "ai-seedance"
AI_JOB_KIND: Final = "seasonal_video"


def is_ai(recipe: str) -> bool:
    return recipe.startswith("ai-")


#: The owner's words for a row's `fail_reason` — recipes B/E and «Con IA» alike
#: (`qualify-copy-es`). `creative.seasonal_ai.REASON_TEXT` is this same dict.
REASON_TEXT: Final[dict[str, str]] = {
    # «Con IA» reasons say whether it was charged (verified in `creative.seasonal_ai`):
    # budget_cap / no_budget_cap / price_changed never call BytePlus; vendor_failed and
    # vendor_expired book nothing; vendor_timeout and vendor_url_refused book a cost.
    "budget_cap": (
        "Este video pasaría tu límite de gasto del mes: no lo creamos ni se cobró. "
        "Usa «Con lo que ya tienes», que es gratis."
    ),
    "no_budget_cap": (
        "Falta definir cuánto puede gastar tu negocio al mes en videos con IA. "
        "Escríbenos y lo dejamos listo."
    ),
    "price_changed": (
        "El precio de los videos con IA cambió: no lo creamos ni se cobró. "
        "Revisa el nuevo costo y pide otro."
    ),
    "vendor_timeout": (
        "El video con IA tardó demasiado. Lo anotamos como gasto por si el proveedor lo "
        "cobra. Puedes pedir otro."
    ),
    "vendor_url_refused": (
        "No pudimos traer el video con IA. Quedó anotado como gasto y ya lo estamos revisando."
    ),
    "vendor_failed": "No pudimos crear el video con IA y no se cobró. Puedes pedir otro.",
    "vendor_expired": "La IA no alcanzó a crear el video y no se cobró. Puedes pedir otro.",
    "no_source": "No encontramos la foto o el logo para crearlo. Revisa tu marca y pide otro.",
    "unreadable_source": "No pudimos abrir la foto o el logo. Súbelo de nuevo y pide otro.",
    "too_large": "Salió muy pesado para WhatsApp. Puedes pedir otro.",
    "ffmpeg_failed": "No pudimos prepararlo. Puedes pedir otro.",
    "ffmpeg_missing": "No pudimos prepararlo. Ya lo estamos revisando.",
    "webp_unavailable": "No pudimos preparar el sticker. Ya lo estamos revisando.",
}
_DEFAULT_REASON_TEXT = "No pudimos preparar esta pieza. Puedes pedir otra."


def reason_text(reason: str | None) -> str:
    """The owner's words for a row's `fail_reason`."""
    return REASON_TEXT.get(reason or "", _DEFAULT_REASON_TEXT)


@dataclass(frozen=True)
class RecipeSlot:
    """One medium of the standard batch: what it is, the recipe, and what it is made from
    (`pieces` = how many approved pieces it takes; `text` = the words for `e-texto`, with
    `{season}` replaced by the season's label)."""

    kind: str
    recipe: str
    source_kind: str
    pieces: int = 0
    text: str = ""


#: The standard batch, by mode (≈ 6 stickers + 4 videos). «free» = recipes B (videos from
#: approved photos) + E (stickers drawn from the logo or a short text), US$0. «ai»
#: (m-24976893, founder 2026-11-08) = ONLY videos: Seedance animates one approved photo
#: each — the top `AI_VIDEOS` approved photo pieces, newest first (the batch chooses;
#: a «¿Qué foto animamos?» step comes later). IA makes no stickers (no transparency).
STANDARD_BATCH: Final[dict[str, tuple[RecipeSlot, ...]]] = {
    "free": (
        RecipeSlot(KIND_STICKER, "e-latido", SOURCE_LOGO),
        RecipeSlot(KIND_STICKER, "e-rebote", SOURCE_LOGO),
        RecipeSlot(KIND_STICKER, "e-giro", SOURCE_LOGO),
        RecipeSlot(KIND_STICKER, "e-brillo", SOURCE_LOGO),
        RecipeSlot(KIND_STICKER, "e-texto", SOURCE_TEXT, text="¡Feliz {season}!"),
        RecipeSlot(KIND_STICKER, "e-texto", SOURCE_TEXT, text="¡Gracias por tu pedido!"),
        RecipeSlot(KIND_VIDEO, "b-zoom", SOURCE_PIECE, pieces=1),
        RecipeSlot(KIND_VIDEO, "b-pan", SOURCE_PIECE, pieces=1),
        RecipeSlot(KIND_VIDEO, "b-xfade", SOURCE_PIECE, pieces=3),
        RecipeSlot(KIND_VIDEO, "b-logo", SOURCE_LOGO),
    ),
    "ai": (
        RecipeSlot(KIND_VIDEO, AI_RECIPE, SOURCE_PIECE, pieces=1),
        RecipeSlot(KIND_VIDEO, AI_RECIPE, SOURCE_PIECE, pieces=1),
        RecipeSlot(KIND_VIDEO, AI_RECIPE, SOURCE_PIECE, pieces=1),
    ),
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


logger = logging.getLogger("qualify_api.whatsapp.seasonal")


# ======================================================================================
# Errors (Spanish `message` for the owner)
# ======================================================================================


class SeasonalError(ValueError):
    message: str = "No pudimos preparar tus stickers y videos."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)
        if message:
            self.message = message


class SeasonInvalid(SeasonalError):
    message = "Escribe el nombre de la temporada (hasta 24 caracteres)."


class NothingToMake(SeasonalError):
    message = "Para preparar la temporada, agrega tu logo o aprueba al menos una pieza con foto."


class ModeNotAvailable(SeasonalError):
    """«Con IA» is off in this service (no estimate or worker wired), or the business has
    no approved photo to animate: the screen shows the reason instead of a dead option."""

    message = "Pronto podrás crear videos con inteligencia artificial."


class NoPhotoToAnimate(ModeNotAvailable):
    message = "Necesitas al menos una foto aprobada para animar."


class CostNotConfirmed(SeasonalError):
    """A paid batch (or «Pedir otro» of a paid video) without the owner's confirmation of
    the estimate shown — nothing is planned, nothing is sent."""

    message = "Confirma el costo antes de crear con IA."


class SelectionChanged(CostNotConfirmed):
    """The photos «Con IA» would animate now are not the ones the owner was quoted (a
    piece was approved or removed meanwhile): quote again, nothing is planned."""

    message = "Las fotos cambiaron desde que viste el costo. Revísalo de nuevo antes de crear."


@dataclass(frozen=True)
class QuotedPhoto:
    """One approved photo the «Con IA» batch will animate, as the quote shows it."""

    draft_id: UUID
    name: str
    thumbnail_key: str | None


@dataclass(frozen=True)
class BatchQuote:
    """What «Revisa y crea» shows before anything is made: how many of each and, for «Con
    IA», «unos US$X por video» (rounded up to the cent) and the total."""

    mode: str
    stickers: int
    videos: int
    ai_videos: int
    per_ai_video_usd: Decimal
    total_usd: Decimal
    #: The photos the AI videos animate, in batch order — the SAME selection
    #: `plan_batch` makes; pass their `draft_id`s back as `accepted_draft_ids`.
    photos: tuple[QuotedPhoto, ...] = ()


class MediaNotFound(LookupError):
    """No seasonal medium with this id in this business."""


class WrongState(SeasonalError):
    message = "Este sticker o video ya no está en ese paso."


class ObjectKeyRefused(SeasonalError):
    message = "El archivo no está donde debe."


class StaleAttempt(SeasonalError):
    """A worker result of an attempt older than the row's: the owner already asked again."""

    message = "Este sticker o video ya se está preparando de nuevo."


class AttemptsExhausted(SeasonalError):
    """The slot reached the technical ceiling (`MAX_ATTEMPTS`, 99) — practically never; the
    owner reads no count (m-25016851), only what to do instead."""

    message = "Ya no podemos crear otra versión. Si no te sirve, toca «Eliminar»."


#: Technical ceiling of «Pedir otro» per slot (the key format and 0152's CHECK) — not an
#: owner-facing limit: m-25016851 removed the cap of three. «Con IA» is bounded by its cost
#: confirmation and the brand's monthly spend guard, not by a count.
MAX_ATTEMPTS: Final = SEASONAL_MAX_ATTEMPTS
#: The statuses «Pedir otro» starts from.
REQUESTABLE: Final = frozenset({STATUS_READY, STATUS_REJECTED, STATUS_FAILED})
#: What `requeue` may restart: «Pedir otro»'s statuses, plus a deleted slot that planning
#: the season again brings back (m-25016851).
REQUEUEABLE: Final = REQUESTABLE | {STATUS_DELETED}


class AiVideoInProgress(SeasonalError):
    """«Eliminar» on a «Con IA» video still being made: the paid task is already running
    and its cost must reach the ledger when it ends (`creative.seasonal_ai.finish` only
    books a `pending` row), so the owner deletes it once it is ready or failed."""

    message = "Este video con IA se está creando. Podrás eliminarlo cuando esté listo."


# ======================================================================================
# Records
# ======================================================================================


@dataclass(frozen=True)
class SeasonalMedia:
    id: UUID
    tenant_id: UUID
    brand_id: UUID
    season_key: str
    season_label: str
    kind: str
    recipe: str
    source_kind: str
    source_ref: str
    pipeline_version: str = SEASONAL_PIPELINE_VERSION
    status: str = STATUS_PENDING
    attempt: int = 1
    object_key: str | None = None
    bytes: int | None = None
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    fail_reason: str | None = None
    cost_usd: Decimal = Decimal("0")
    created_by: UUID | None = None
    created_at: datetime = field(default_factory=_utcnow)
    approved_at: datetime | None = None
    archived_at: datetime | None = None


@dataclass(frozen=True)
class Season:
    """One season of a business, for «Por aprobar» and the library."""

    season_key: str
    season_label: str
    archived: bool
    counts: dict[str, int]
    last_activity: datetime


def job_key(media: SeasonalMedia) -> str:
    """The job's idempotency key: one job per (medium, attempt)."""
    return f"seasonal:{media.id}:{media.attempt}"


def job_payload(media: SeasonalMedia) -> dict[str, str | int]:
    """The `seasonal_media` job's payload (module docstring)."""
    return {
        "media_id": str(media.id),
        "tenant_id": str(media.tenant_id),
        "brand_id": str(media.brand_id),
        "kind": media.kind,
        "recipe": media.recipe,
        "source_kind": media.source_kind,
        "source_ref": media.source_ref,
        "season_key": media.season_key,
        "attempt": media.attempt,
    }


def check_object_key(media: SeasonalMedia, object_key: str) -> str:
    """The file of `media` must be `seasonal/{tenant}/{brand}/{season}/{id}-{attempt}.{ext}`
    — the CURRENT attempt's key, never an earlier one."""
    expected = seasonal_media_key(
        media.tenant_id,
        media.brand_id,
        media.season_key,
        media.id,
        EXTENSIONS[media.kind],
        media.attempt,
    )
    if object_key != expected:
        raise ObjectKeyRefused()
    return object_key


# ======================================================================================
# Seams
# ======================================================================================


class SeasonalRepository(Protocol):
    """Tenant-scoped (Postgres: `tenant_session`, RLS)."""

    def insert_planned(self, rows: Sequence[SeasonalMedia]) -> list[tuple[SeasonalMedia, bool]]:
        """Insert each row unless its slot exists (`ON CONFLICT DO NOTHING`), enqueue a
        job for each NEW row in the same transaction; returns (row as stored, new?)."""
        ...

    def get(self, *, tenant_id: UUID, media_id: UUID) -> SeasonalMedia | None: ...

    def list_brand(
        self, *, tenant_id: UUID, brand_id: UUID, season_key: str | None = None
    ) -> list[SeasonalMedia]: ...

    def save(self, media: SeasonalMedia, *, expected: SeasonalMedia) -> SeasonalMedia:
        """Write `media` only if the LOCKED stored row still is `expected` (the copy the
        service decided on): same `attempt` (else `StaleAttempt`), same `status` and
        archived-ness (else `WrongState`) — a concurrent «Pedir otro», approve or archive
        is a typed refusal, never a lost update or a raw constraint error."""
        ...

    def save_all(
        self, changes: Sequence[tuple[SeasonalMedia, SeasonalMedia]]
    ) -> list[SeasonalMedia]:
        """`save` for several `(media, expected)` pairs in ONE transaction: every row is
        locked and checked first; the first offender raises and nothing is written."""
        ...

    def requeue(self, media: SeasonalMedia, *, from_attempt: int) -> SeasonalMedia:
        """Write `media` (the next attempt, `pending`) only if the stored row is still at
        `from_attempt` in a requestable status, and enqueue its job — one transaction.
        Raises `WrongState` when someone got there first."""
        ...


class SourceReads(Protocol):
    def approved_photo_pieces(self, tenant_id: UUID, brand_id: UUID, limit: int) -> list[UUID]:
        """The business's approved photo pieces, newest first."""
        ...

    def logo_key(self, tenant_id: UUID, brand_id: UUID) -> str | None: ...

    def photo_details(
        self, tenant_id: UUID, brand_id: UUID, draft_ids: Sequence[UUID]
    ) -> dict[UUID, tuple[str, str | None]]:
        """(name, thumbnail object key) of each approved photo piece asked for — what the
        «Con IA» quote shows of the photos it will animate."""
        ...


# ======================================================================================
# Service
# ======================================================================================


def _clean_label(label: str) -> str:
    cleaned = " ".join((label or "").split())
    if not cleaned or len(cleaned) > MAX_LABEL_CHARS:
        raise SeasonInvalid()
    return cleaned


def _check_season(season_key: str) -> str:
    if not SEASON_KEY_RE.fullmatch(season_key or ""):
        raise SeasonInvalid("Esa temporada no es válida.")
    return season_key


class SeasonalMediaService:
    def __init__(
        self,
        repo: SeasonalRepository,
        sources: SourceReads,
        clock: Callable[[], datetime] = _utcnow,
        id_factory: Callable[[], UUID] = uuid4,
        worker_reader: Callable[[UUID, UUID], list[SeasonalMedia]] | None = None,
        delete_objects: Callable[[UUID, UUID, list[str]], None] | None = None,
        ai_mode: bool = False,
        ai_video_estimate_usd: Callable[[], Decimal] | None = None,
    ) -> None:
        if ai_mode and ai_video_estimate_usd is None:
            raise ValueError("ai_mode needs the per-video estimate (m-24976893)")
        self._ai_estimate = ai_video_estimate_usd
        # m-24976893 turns this on with the AI recipes and their per-video estimate.
        self._ai_mode = ai_mode
        self._repo = repo
        self._delete_objects = delete_objects
        self._sources = sources
        self._worker_reader = worker_reader
        self._clock = clock
        self._new_id = id_factory

    def _media(self, tenant_id: UUID, brand_id: UUID, media_id: UUID) -> SeasonalMedia:
        media = self._repo.get(tenant_id=tenant_id, media_id=media_id)
        if media is None or media.brand_id != brand_id:
            raise MediaNotFound(str(media_id))
        return media

    # --- planning ----------------------------------------------------------------------

    def _planned_rows(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        season_key: str,
        season_label: str,
        mode: Mode,
        user_id: UUID | None,
    ) -> list[SeasonalMedia]:
        """The batch's rows as they would be planned (nothing written)."""
        if mode not in STANDARD_BATCH:
            raise ValueError(f"mode must be one of {tuple(STANDARD_BATCH)}")
        if mode == "ai" and not self._ai_mode:
            raise ModeNotAvailable()
        season_key = _check_season(season_key)
        label = _clean_label(season_label)
        slots = STANDARD_BATCH[mode]
        wanted = sum(s.pieces for s in slots)
        pieces = list(self._sources.approved_photo_pieces(tenant_id, brand_id, max(wanted, 1)))
        logo = self._sources.logo_key(tenant_id, brand_id)
        if mode == "ai" and not pieces:
            raise NoPhotoToAnimate()
        if not logo and not pieces:
            # Text stickers alone would carry no brand identity: ask for a logo or a piece.
            raise NothingToMake()
        rows: list[SeasonalMedia] = []
        cursor = 0
        for slot in slots:
            if slot.source_kind == SOURCE_LOGO:
                if not logo:
                    continue
                ref = logo
            elif slot.source_kind == SOURCE_TEXT:
                ref = slot.text.replace("{season}", label)
            else:
                if not pieces:
                    continue
                # Rotate through the pieces so each video uses different photos.
                chosen = [pieces[(cursor + i) % len(pieces)] for i in range(slot.pieces)]
                cursor += slot.pieces
                ref = ",".join(str(p) for p in dict.fromkeys(chosen))
            rows.append(
                SeasonalMedia(
                    id=self._new_id(),
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    season_key=season_key,
                    season_label=label,
                    kind=slot.kind,
                    recipe=slot.recipe,
                    source_kind=slot.source_kind,
                    source_ref=ref,
                    created_by=user_id,
                    created_at=self._clock(),
                )
            )
        # The unique slot is (brand, season, recipe, source_ref): duplicates inside one
        # batch (the same recipe on the same source) collapse here first.
        unique: dict[tuple[str, str], SeasonalMedia] = {}
        for row in rows:
            unique.setdefault((row.recipe, row.source_ref), row)
        if not unique:
            raise NothingToMake()
        return list(unique.values())

    def _per_ai_video(self) -> Decimal:
        assert self._ai_estimate is not None
        return Decimal(self._ai_estimate()).quantize(Decimal("0.01"), rounding=ROUND_CEILING)

    def ai_video_price_usd(self) -> Decimal:
        """The current price of ONE «Con IA» video as the owner is asked to confirm it
        («Pedir otro cuesta unos US$0,05. ¿Lo creamos?»): the same figure `request_another`
        checks `accepted_cost_usd` against, rounded up to the cent. Independent of the
        batch quote (no photo needed). Raises `ModeNotAvailable` while «Con IA» is off."""
        if not self._ai_mode:
            raise ModeNotAvailable()
        return self._per_ai_video()

    @staticmethod
    def reason_text(reason: str | None) -> str:
        """The owner's words for a failed medium (`REASON_TEXT`), for the screens."""
        return reason_text(reason)

    def quote_batch(self, tenant_id: UUID, brand_id: UUID, mode: Mode) -> BatchQuote:
        """What the batch would make and, with IA, cost — shown BEFORE creating (UX doc §1
        step 3, «Revisa y crea»). Raises like `plan_batch` would."""
        rows = self._planned_rows(tenant_id, brand_id, "cotizacion", "Cotización", mode, None)
        ai = sum(1 for r in rows if is_ai(r.recipe))
        per = self._per_ai_video() if ai else Decimal("0.00")
        selection = _ai_selection(rows)
        details = self._sources.photo_details(tenant_id, brand_id, selection) if selection else {}
        photos = tuple(QuotedPhoto(d, *details.get(d, ("", None))) for d in selection)
        return BatchQuote(
            photos=photos,
            mode=mode,
            stickers=sum(1 for r in rows if r.kind == KIND_STICKER),
            videos=sum(1 for r in rows if r.kind == KIND_VIDEO),
            ai_videos=ai,
            per_ai_video_usd=per,
            total_usd=per * ai,
        )

    def plan_batch(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        season_key: str,
        season_label: str,
        mode: Mode,
        user_id: UUID | None,
        *,
        accepted_total_usd: Decimal | None = None,
        accepted_draft_ids: Sequence[UUID] | None = None,
    ) -> list[SeasonalMedia]:
        """The season's standard batch as `pending` rows, one job each (`media-worker`
        for B/E, `creative-worker` for «Con IA»). Idempotent: a slot already planned is
        returned as it is (no second job). Slots whose source is missing (no logo, too few
        approved pieces) are skipped. «Con IA» needs `accepted_total_usd` — the total the
        owner confirmed from `quote_batch` — to cover the current quote; otherwise
        `CostNotConfirmed` and nothing is planned (double approval: the cost, then the
        result in «Por aprobar»)."""
        unique = {
            (r.recipe, r.source_ref): r
            for r in self._planned_rows(
                tenant_id, brand_id, season_key, season_label, mode, user_id
            )
        }
        ai = sum(1 for r in unique.values() if is_ai(r.recipe))
        if ai:
            total = self._per_ai_video() * ai
            if accepted_total_usd is None or Decimal(accepted_total_usd) < total:
                raise CostNotConfirmed()
            # exactly the photos the owner was quoted, in the same order
            if accepted_draft_ids is None or [UUID(str(d)) for d in accepted_draft_ids] != (
                _ai_selection(list(unique.values()))
            ):
                raise SelectionChanged()
        out = []
        for stored, _new in self._repo.insert_planned(list(unique.values())):
            if stored.status == STATUS_DELETED and stored.attempt < MAX_ATTEMPTS:
                stored = self._revive(stored)
            out.append(stored)
        return out

    def _revive(self, media: SeasonalMedia) -> SeasonalMedia:
        """A slot the owner deleted, planned again (m-25016851): the same row is made anew
        — the next attempt, `pending`, a new job — like «Pedir otro». Without it the season
        would show «Listo: estamos preparando…» and nothing would ever arrive."""
        try:
            return self._repo.requeue(
                replace(
                    media,
                    status=STATUS_PENDING,
                    attempt=media.attempt + 1,
                    object_key=None,
                    bytes=None,
                    width=None,
                    height=None,
                    duration_ms=None,
                    fail_reason=None,
                    approved_at=None,
                ),
                from_attempt=media.attempt,
            )
        except (WrongState, StaleAttempt):  # another tap revived it first
            return self._media(media.tenant_id, media.brand_id, media.id)

    # --- the worker ----------------------------------------------------------------------

    def mark_ready(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        media_id: UUID,
        attempt: int,
        object_key: str,
        bytes: int,
        width: int | None,
        height: int | None,
        duration_ms: int | None,
        cost_usd: Decimal | float | str = 0,
    ) -> SeasonalMedia:
        """The worker stored the file of `attempt` (only the row's current attempt, only
        from `pending` or a retried `failed`)."""
        media = self._media(tenant_id, brand_id, media_id)
        if attempt != media.attempt:
            raise StaleAttempt()
        if media.status not in (STATUS_PENDING, STATUS_FAILED):
            raise WrongState()
        check_object_key(media, object_key)
        cost = Decimal(str(cost_usd))
        if cost < 0 or bytes <= 0:
            raise ValueError("bytes must be positive and cost_usd non-negative")
        return self._repo.save(
            replace(
                media,
                status=STATUS_READY,
                object_key=object_key,
                bytes=bytes,
                width=width,
                height=height,
                duration_ms=duration_ms,
                cost_usd=cost,
                fail_reason=None,
            ),
            expected=media,
        )

    def mark_failed(
        self, *, tenant_id: UUID, brand_id: UUID, media_id: UUID, attempt: int, reason: str
    ) -> SeasonalMedia:
        media = self._media(tenant_id, brand_id, media_id)
        if attempt != media.attempt:
            raise StaleAttempt()
        if media.status not in (STATUS_PENDING, STATUS_FAILED):
            raise WrongState()
        return self._repo.save(
            replace(media, status=STATUS_FAILED, fail_reason=(reason or "unknown")[:200]),
            expected=media,
        )

    # --- the owner ------------------------------------------------------------------------

    def approve(
        self, tenant_id: UUID, brand_id: UUID, media_ids: Iterable[UUID], user_id: UUID | None
    ) -> list[SeasonalMedia]:
        """Approve `ready` media of an unarchived season (others are refused, nothing is
        half-approved: every id is checked first)."""
        chosen = [self._media(tenant_id, brand_id, m) for m in dict.fromkeys(media_ids)]
        for media in chosen:
            if media.status != STATUS_READY or media.archived_at is not None:
                raise WrongState()
        now = self._clock()
        return self._repo.save_all(
            [(replace(m, status=STATUS_APPROVED, approved_at=now), m) for m in chosen]
        )

    def reject(
        self, tenant_id: UUID, brand_id: UUID, media_id: UUID, user_id: UUID | None
    ) -> SeasonalMedia:
        """«No me gusta»: a `ready` (or already `approved`) medium leaves the library."""
        media = self._media(tenant_id, brand_id, media_id)
        if media.status not in (STATUS_READY, STATUS_APPROVED):
            raise WrongState()
        return self._repo.save(replace(media, status=STATUS_REJECTED), expected=media)

    def request_another(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        media_id: UUID,
        user_id: UUID | None,
        *,
        accepted_cost_usd: Decimal | None = None,
    ) -> SeasonalMedia:
        """«Pedir otro»: the SAME row (its slot stays unique) is made again — from `ready`,
        `rejected` or `failed` of an unarchived season, as many times as the owner wants
        (`MAX_ATTEMPTS` is only a technical ceiling). Row + new job commit together; the
        previous file is deleted afterwards (exact key, best effort: a leftover file is
        unreachable — no row points at it — and «Eliminar» sweeps every attempt's key)."""
        media = self._media(tenant_id, brand_id, media_id)
        if is_ai(media.recipe):
            # another paid call: the owner confirms its cost again (m-24976893)
            if not self._ai_mode:
                raise ModeNotAvailable()
            if accepted_cost_usd is None or Decimal(accepted_cost_usd) < self._per_ai_video():
                raise CostNotConfirmed()
        if media.status not in REQUESTABLE or media.archived_at is not None:
            raise WrongState()
        if media.attempt >= MAX_ATTEMPTS:
            raise AttemptsExhausted()
        previous_key = media.object_key
        stored = self._repo.requeue(
            replace(
                media,
                status=STATUS_PENDING,
                attempt=media.attempt + 1,
                object_key=None,
                bytes=None,
                width=None,
                height=None,
                duration_ms=None,
                fail_reason=None,
                approved_at=None,
            ),
            from_attempt=media.attempt,
        )
        if previous_key and self._delete_objects is not None:
            try:
                self._delete_objects(tenant_id, brand_id, [previous_key])
            except Exception:  # noqa: BLE001 — the row is already right; log, move on
                logger.warning(
                    "seasonal: previous file not deleted media=%s attempt=%s",
                    media.id,
                    media.attempt,
                    exc_info=True,
                )
        return stored

    def delete(
        self, tenant_id: UUID, brand_id: UUID, media_id: UUID, user_id: UUID | None
    ) -> SeasonalMedia:
        """«Eliminar» (m-25016851): the medium leaves the library and the chat for good, from
        any status. The row is KEPT as `deleted` (provenance and the paid jobs' trail stay;
        the slot stays the same row) with its
        file fields cleared; then every attempt's file (1…`attempt`: the current one and
        any an earlier «Pedir otro» failed to delete) is deleted through the gate, bounded
        to this business. A «Con IA» video still `pending` is refused (`AiVideoInProgress`):
        its paid task is running and must be booked. Planning the season again revives a
        deleted slot (`_revive`). Idempotent: an already deleted medium is returned as it is (its
        files are swept again). A job still running for it finds `WrongState` at
        `mark_ready` and deletes the file it wrote (`creative.seasonal_job`,
        `creative.seasonal_ai`). A sticker already sent stays in the chat's history: the
        transcript never reads the library file."""
        stored: SeasonalMedia | None = None
        for _ in range(3):  # a worker or another tap may move the row between read and lock
            media = self._media(tenant_id, brand_id, media_id)
            if media.status == STATUS_DELETED:
                stored = media
                break
            if media.status == STATUS_PENDING and is_ai(media.recipe):
                raise AiVideoInProgress()
            try:
                stored = self._repo.save(
                    replace(
                        media,
                        status=STATUS_DELETED,
                        object_key=None,
                        bytes=None,
                        width=None,
                        height=None,
                        duration_ms=None,
                        approved_at=None,
                    ),
                    expected=media,
                )
                break
            except (StaleAttempt, WrongState):
                continue
        if stored is None:
            raise WrongState()
        self._delete_files(stored)
        return stored

    def _delete_files(self, media: SeasonalMedia) -> None:
        """Every attempt's key of `media` (best effort: the row is already right)."""
        if self._delete_objects is None:
            return
        keys = [
            seasonal_media_key(
                media.tenant_id,
                media.brand_id,
                media.season_key,
                media.id,
                EXTENSIONS[media.kind],
                attempt,
            )
            for attempt in range(1, min(media.attempt, MAX_ATTEMPTS) + 1)
        ]
        try:
            self._delete_objects(media.tenant_id, media.brand_id, keys)
        except Exception:  # noqa: BLE001 — logged; a retry of «Eliminar» sweeps again
            logger.warning("seasonal: files not deleted media=%s", media.id, exc_info=True)

    def archive(self, tenant_id: UUID, brand_id: UUID, season_key: str) -> list[SeasonalMedia]:
        """The season leaves the chat: approved → archived; every row stamped."""
        now = self._clock()
        out = []
        for media in self._repo.list_brand(
            tenant_id=tenant_id, brand_id=brand_id, season_key=_check_season(season_key)
        ):
            if media.archived_at is not None or media.status == STATUS_DELETED:
                continue
            status = STATUS_ARCHIVED if media.status == STATUS_APPROVED else media.status
            out.append(
                self._repo.save(replace(media, status=status, archived_at=now), expected=media)
            )
        return out

    def restore(self, tenant_id: UUID, brand_id: UUID, season_key: str) -> list[SeasonalMedia]:
        out = []
        for media in self._repo.list_brand(
            tenant_id=tenant_id, brand_id=brand_id, season_key=_check_season(season_key)
        ):
            if media.archived_at is None or media.status == STATUS_DELETED:
                continue
            status = STATUS_APPROVED if media.status == STATUS_ARCHIVED else media.status
            out.append(
                self._repo.save(replace(media, status=status, archived_at=None), expected=media)
            )
        return out

    # --- reads -----------------------------------------------------------------------------

    def list_season(self, tenant_id: UUID, brand_id: UUID, season_key: str) -> list[SeasonalMedia]:
        rows = [
            m
            for m in self._repo.list_brand(
                tenant_id=tenant_id, brand_id=brand_id, season_key=_check_season(season_key)
            )
            if m.status != STATUS_DELETED
        ]
        return sorted(rows, key=lambda m: (m.kind != KIND_STICKER, m.created_at, str(m.id)))

    def list_seasons(self, tenant_id: UUID, brand_id: UUID) -> list[Season]:
        """Every season of the business, the most recently active first (deleted media do
        not count; a season whose media were all deleted is gone)."""
        groups: dict[str, list[SeasonalMedia]] = {}
        for media in self._repo.list_brand(tenant_id=tenant_id, brand_id=brand_id):
            if media.status == STATUS_DELETED:
                continue
            groups.setdefault(media.season_key, []).append(media)
        seasons = []
        for key, rows in groups.items():
            counts: dict[str, int] = {}
            for media in rows:
                counts[media.status] = counts.get(media.status, 0) + 1
            seasons.append(
                Season(
                    season_key=key,
                    season_label=rows[0].season_label,
                    archived=all(m.archived_at is not None for m in rows),
                    counts=counts,
                    last_activity=max(m.approved_at or m.created_at for m in rows),
                )
            )
        return sorted(seasons, key=lambda s: s.last_activity, reverse=True)

    def list_approved_for_chat(
        self, tenant_id: UUID, brand_id: UUID, *, as_worker: bool = False
    ) -> list[SeasonalMedia]:
        """What the chat may send: `approved` media of unarchived seasons, the current
        season (most recently approved) first, stickers before videos inside a season.
        Each row carries what the chat card needs: `id`, `kind`, `season_label`,
        `object_key`, `bytes`, `width`, `height`, `duration_ms`, `approved_at`. A preview
        reads the file through `ObjectGate.open_seasonal_media(tenant_id, brand_id,
        object_key)`, bounded to `seasonal/{tenant}/{brand}/`.
        `as_worker=True` reads through the webhook worker's column grants
        (`approved_for_worker`, or the injected `worker_reader`)."""
        if as_worker:
            reader = self._worker_reader or approved_for_worker
            source = reader(tenant_id, brand_id)
        else:
            source = self._repo.list_brand(tenant_id=tenant_id, brand_id=brand_id)
        rows = [
            m
            for m in source
            if m.status == STATUS_APPROVED and m.archived_at is None and m.object_key
        ]
        latest: dict[str, datetime] = {}
        for media in rows:
            stamp = media.approved_at or media.created_at
            latest[media.season_key] = max(latest.get(media.season_key, stamp), stamp)
        return sorted(
            rows,
            key=lambda m: (
                -latest[m.season_key].timestamp(),
                m.season_key,
                m.kind != KIND_STICKER,
                m.created_at,
                str(m.id),
            ),
        )


# ======================================================================================
# In memory (tests)
# ======================================================================================


def _check_unchanged(
    attempt: int, status: str, archived_at: datetime | None, expected: SeasonalMedia
) -> None:
    """The stored row (locked) against the copy the service decided on."""
    if attempt != expected.attempt:
        raise StaleAttempt()
    if status != expected.status or (archived_at is None) != (expected.archived_at is None):
        raise WrongState()


class MemorySeasonalRepository:
    def __init__(self) -> None:
        self.rows: dict[UUID, SeasonalMedia] = {}
        self.jobs: list[dict[str, Any]] = []

    def insert_planned(self, rows: Sequence[SeasonalMedia]) -> list[tuple[SeasonalMedia, bool]]:
        out = []
        for row in rows:
            existing = next(
                (
                    r
                    for r in self.rows.values()
                    if (r.brand_id, r.season_key, r.recipe, r.source_ref)
                    == (row.brand_id, row.season_key, row.recipe, row.source_ref)
                ),
                None,
            )
            if existing is not None:
                out.append((existing, False))
                continue
            self.rows[row.id] = row
            self.jobs.append(
                {
                    "tenant_id": row.tenant_id,
                    "brand_id": row.brand_id,
                    "kind": AI_JOB_KIND if is_ai(row.recipe) else JOB_KIND,
                    "idempotency_key": job_key(row),
                    "pipeline_version": SEASONAL_PIPELINE_VERSION,
                    "payload": job_payload(row),
                }
            )
            out.append((row, True))
        return out

    def requeue(self, media: SeasonalMedia, *, from_attempt: int) -> SeasonalMedia:
        current = self.get(tenant_id=media.tenant_id, media_id=media.id)
        if current is None:
            raise MediaNotFound(str(media.id))
        if current.attempt != from_attempt or current.status not in REQUEUEABLE:
            raise WrongState()
        key = job_key(media)
        if any(j["idempotency_key"] == key for j in self.jobs):
            raise WrongState()
        self.rows[media.id] = media
        self.jobs.append(
            {
                "tenant_id": media.tenant_id,
                "brand_id": media.brand_id,
                "kind": AI_JOB_KIND if is_ai(media.recipe) else JOB_KIND,
                "idempotency_key": key,
                "pipeline_version": SEASONAL_PIPELINE_VERSION,
                "payload": job_payload(media),
            }
        )
        return media

    def get(self, *, tenant_id: UUID, media_id: UUID) -> SeasonalMedia | None:
        found = self.rows.get(media_id)
        return found if found is not None and found.tenant_id == tenant_id else None

    def list_brand(
        self, *, tenant_id: UUID, brand_id: UUID, season_key: str | None = None
    ) -> list[SeasonalMedia]:
        return [
            r
            for r in self.rows.values()
            if r.tenant_id == tenant_id
            and r.brand_id == brand_id
            and (season_key is None or r.season_key == season_key)
        ]

    def save(self, media: SeasonalMedia, *, expected: SeasonalMedia) -> SeasonalMedia:
        return self.save_all([(media, expected)])[0]

    def save_all(
        self, changes: Sequence[tuple[SeasonalMedia, SeasonalMedia]]
    ) -> list[SeasonalMedia]:
        for media, expected in changes:
            current = self.get(tenant_id=media.tenant_id, media_id=media.id)
            if current is None or current.brand_id != media.brand_id:
                raise MediaNotFound(str(media.id))
            _check_unchanged(current.attempt, current.status, current.archived_at, expected)
        for media, _ in changes:
            self.rows[media.id] = media
        return [media for media, _ in changes]


class MemorySourceReads:
    def __init__(self) -> None:
        self.pieces: dict[tuple[UUID, UUID], list[UUID]] = {}
        self.logos: dict[tuple[UUID, UUID], str] = {}

    def approved_photo_pieces(self, tenant_id: UUID, brand_id: UUID, limit: int) -> list[UUID]:
        return list(self.pieces.get((tenant_id, brand_id), []))[:limit]

    def logo_key(self, tenant_id: UUID, brand_id: UUID) -> str | None:
        return self.logos.get((tenant_id, brand_id))

    def photo_details(
        self, tenant_id: UUID, brand_id: UUID, draft_ids: Sequence[UUID]
    ) -> dict[UUID, tuple[str, str | None]]:
        known = self.pieces.get((tenant_id, brand_id), [])
        return {d: (f"Pieza {known.index(d) + 1}", None) for d in draft_ids if d in known}


# ======================================================================================
# Postgres
# ======================================================================================


def _from_row(row: Any) -> SeasonalMedia:
    return SeasonalMedia(
        id=row.id,
        tenant_id=row.tenant_id,
        brand_id=row.brand_id,
        season_key=row.season_key,
        season_label=row.season_label,
        kind=row.kind,
        recipe=getattr(row, "recipe", ""),
        source_kind=getattr(row, "source_kind", ""),
        source_ref=getattr(row, "source_ref", ""),
        pipeline_version=getattr(row, "pipeline_version", SEASONAL_PIPELINE_VERSION),
        status=row.status,
        attempt=getattr(row, "attempt", 1) or 1,
        object_key=row.object_key,
        bytes=getattr(row, "bytes", None),
        width=getattr(row, "width", None),
        height=getattr(row, "height", None),
        duration_ms=getattr(row, "duration_ms", None),
        fail_reason=getattr(row, "fail_reason", None),
        cost_usd=Decimal(str(getattr(row, "cost_usd", 0) or 0)),
        created_by=getattr(row, "created_by", None),
        created_at=getattr(row, "created_at", None) or _utcnow(),
        approved_at=row.approved_at,
        archived_at=row.archived_at,
    )


_SAVED_COLUMNS: Final = (
    "status",
    "object_key",
    "bytes",
    "width",
    "height",
    "duration_ms",
    "fail_reason",
    "cost_usd",
    "approved_at",
    "archived_at",
)


class PostgresSeasonalRepository:
    """`tenant_session(tenant_id)` per call (`qualify_app`, RLS). The planned rows and their
    jobs are written in ONE transaction: a row never exists without its job."""

    def insert_planned(self, rows: Sequence[SeasonalMedia]) -> list[tuple[SeasonalMedia, bool]]:
        if not rows:
            return []
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import select  # noqa: PLC0415
        from sqlalchemy.dialects.postgresql import insert  # noqa: PLC0415

        from qualify_api.whatsapp.models import BrandSeasonalMedia as T  # noqa: PLC0415

        tenant_id = rows[0].tenant_id
        out: list[tuple[SeasonalMedia, bool]] = []
        with tenant_session(tenant_id) as session:
            for row in rows:
                new_id = session.scalar(
                    insert(T)
                    .values(
                        id=row.id,
                        tenant_id=row.tenant_id,
                        brand_id=row.brand_id,
                        season_key=row.season_key,
                        season_label=row.season_label,
                        kind=row.kind,
                        recipe=row.recipe,
                        source_kind=row.source_kind,
                        source_ref=row.source_ref,
                        pipeline_version=row.pipeline_version,
                        status=STATUS_PENDING,
                        created_by=row.created_by,
                        created_at=row.created_at,
                    )
                    .on_conflict_do_nothing(constraint="uq_brand_seasonal_media_slot")
                    .returning(T.id)
                )
                if new_id is None:
                    existing = session.scalar(
                        select(T).where(
                            T.brand_id == row.brand_id,
                            T.season_key == row.season_key,
                            T.recipe == row.recipe,
                            T.source_ref == row.source_ref,
                        )
                    )
                    assert existing is not None  # the conflict proves it exists
                    out.append((_from_row(existing), False))
                    continue
                _enqueue(session, row)
                out.append((row, True))
        return out

    def get(self, *, tenant_id: UUID, media_id: UUID) -> SeasonalMedia | None:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415

        from qualify_api.whatsapp.models import BrandSeasonalMedia as T  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            row = session.get(T, media_id)
            return _from_row(row) if row is not None else None

    def list_brand(
        self, *, tenant_id: UUID, brand_id: UUID, season_key: str | None = None
    ) -> list[SeasonalMedia]:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import select  # noqa: PLC0415

        from qualify_api.whatsapp.models import BrandSeasonalMedia as T  # noqa: PLC0415

        stmt = select(T).where(T.brand_id == brand_id)
        if season_key is not None:
            stmt = stmt.where(T.season_key == season_key)
        with tenant_session(tenant_id) as session:
            return [_from_row(r) for r in session.scalars(stmt).all()]

    def save(self, media: SeasonalMedia, *, expected: SeasonalMedia) -> SeasonalMedia:
        return self.save_all([(media, expected)])[0]

    def save_all(
        self, changes: Sequence[tuple[SeasonalMedia, SeasonalMedia]]
    ) -> list[SeasonalMedia]:
        if not changes:
            return []
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import select  # noqa: PLC0415

        from qualify_api.whatsapp.models import BrandSeasonalMedia as T  # noqa: PLC0415

        tenant_id = changes[0][0].tenant_id
        if any(media.tenant_id != tenant_id for media, _ in changes):
            raise ValueError("one tenant per save_all")
        with tenant_session(tenant_id) as session:
            # Locked in id order (two concurrent multi-row approvals cannot deadlock) and
            # all checked before any is written.
            locked = {
                row.id: row
                for row in session.scalars(
                    select(T)
                    .where(T.id.in_([media.id for media, _ in changes]))
                    .order_by(T.id)
                    .with_for_update()
                )
            }
            for media, expected in changes:
                row = locked.get(media.id)
                if row is None or row.brand_id != media.brand_id:
                    raise MediaNotFound(str(media.id))
                _check_unchanged(row.attempt, row.status, row.archived_at, expected)
            for media, _ in changes:
                row = locked[media.id]
                for column in _SAVED_COLUMNS:
                    setattr(row, column, getattr(media, column))
            session.flush()
            return [_from_row(locked[media.id]) for media, _ in changes]

    def requeue(self, media: SeasonalMedia, *, from_attempt: int) -> SeasonalMedia:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415

        from qualify_api.whatsapp.models import BrandSeasonalMedia as T  # noqa: PLC0415

        with tenant_session(media.tenant_id) as session:
            row = session.get(T, media.id, with_for_update=True)
            if row is None or row.brand_id != media.brand_id:
                raise MediaNotFound(str(media.id))
            if row.attempt != from_attempt or row.status not in REQUEUEABLE:
                raise WrongState()
            for column in (
                "status",
                "attempt",
                "object_key",
                "bytes",
                "width",
                "height",
                "duration_ms",
                "fail_reason",
                "approved_at",
            ):
                setattr(row, column, getattr(media, column))
            _enqueue(session, media)
            session.flush()
            return _from_row(row)


def _ai_selection(rows: Sequence[SeasonalMedia]) -> list[UUID]:
    """The approved photo pieces the AI rows animate, in batch order (one per row)."""
    return [UUID(r.source_ref.split(",")[0]) for r in rows if is_ai(r.recipe)]


def _enqueue(session: Any, media: SeasonalMedia) -> None:
    """The job of one medium attempt, in the caller's transaction: B/E on the Galería's
    queue (`gallery_jobs`, `media-worker`); «Con IA» on the generation queue
    (`creative_jobs` kind `seasonal_video`, `creative-worker`, ADR 41 slots)."""
    if is_ai(media.recipe):
        from qualify_creative.seasonal.ai import AI_PRICING_VERSION  # noqa: PLC0415

        from qualify_api.creative import job_queue as q  # noqa: PLC0415

        q.enqueue_seasonal_job(
            session,
            tenant_id=media.tenant_id,
            seasonal_media_id=media.id,
            attempt=media.attempt,
            # the table the owner's quote came from: the worker never pays more than it
            pricing_version=AI_PRICING_VERSION,
            pipeline_version=SEASONAL_PIPELINE_VERSION,
        )
        return
    from qualify_api.catalog.business_media_models import GalleryJob  # noqa: PLC0415

    session.add(
        GalleryJob(
            tenant_id=media.tenant_id,
            brand_id=media.brand_id,
            kind=JOB_KIND,
            idempotency_key=job_key(media),
            pipeline_version=SEASONAL_PIPELINE_VERSION,
            payload=job_payload(media),
        )
    )


def approved_for_worker(tenant_id: UUID, brand_id: UUID) -> list[SeasonalMedia]:
    """The chat-sendable media read as `qualify_webhook_worker` (0145's column grants),
    tenant AND brand filtered here — for an automation path that runs under that door."""
    from qualify_shared.db.webhook import webhook_worker_session  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    from qualify_api.whatsapp.models import BrandSeasonalMedia as T  # noqa: PLC0415

    columns = (
        T.id,
        T.tenant_id,
        T.brand_id,
        T.season_key,
        T.season_label,
        T.kind,
        T.object_key,
        T.bytes,
        T.width,
        T.height,
        T.duration_ms,
        T.status,
        T.approved_at,
        T.archived_at,
        T.created_at,
    )
    with webhook_worker_session() as session:
        rows = session.execute(
            select(*columns).where(
                T.tenant_id == tenant_id,
                T.brand_id == brand_id,
                T.status == STATUS_APPROVED,
                T.archived_at.is_(None),
            )
        ).all()
    return [_from_row(r) for r in rows]


class PostgresSourceReads:
    def photo_details(
        self, tenant_id: UUID, brand_id: UUID, draft_ids: Sequence[UUID]
    ) -> dict[UUID, tuple[str, str | None]]:
        from qualify_api.whatsapp.attachments import PostgresAttachmentReads  # noqa: PLC0415

        wanted = set(draft_ids)
        return {
            p.id: (p.title, p.image_key or None)
            for p in PostgresAttachmentReads().pieces(tenant_id, brand_id)
            if p.id in wanted
        }

    def approved_photo_pieces(self, tenant_id: UUID, brand_id: UUID, limit: int) -> list[UUID]:
        from qualify_api.whatsapp.attachments import PostgresAttachmentReads  # noqa: PLC0415

        pieces = PostgresAttachmentReads().pieces(tenant_id, brand_id)
        return [
            p.id
            for p in pieces
            if p.status in ("approved", "staged", "published") and p.media_type == "image"
        ][:limit]

    def logo_key(self, tenant_id: UUID, brand_id: UUID) -> str | None:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import select  # noqa: PLC0415

        from qualify_api.creative.models import BrandKit  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            return session.scalar(
                select(BrandKit.logo_asset_key).where(BrandKit.brand_id == brand_id)
            )


def production_seasonal_service() -> SeasonalMediaService:
    from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
    from qualify_shared.objects.gate import ObjectGate  # noqa: PLC0415
    from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

    def delete_objects(tenant_id: UUID, brand_id: UUID, keys: list[str]) -> None:
        ObjectGate(R2ObjectStore(R2Settings.from_env())).delete_seasonal_media(
            tenant_id, brand_id, keys
        )

    return SeasonalMediaService(
        PostgresSeasonalRepository(), PostgresSourceReads(), delete_objects=delete_objects
    )


__all__ = [
    "REASON_TEXT",
    "BatchQuote",
    "CostNotConfirmed",
    "QuotedPhoto",
    "SelectionChanged",
    "reason_text",
    "EXTENSIONS",
    "JOB_KIND",
    "MAX_ATTEMPTS",
    "SEASONAL_PIPELINE_VERSION",
    "STANDARD_BATCH",
    "STATUS_DELETED",
    "AiVideoInProgress",
    "AttemptsExhausted",
    "MediaNotFound",
    "MemorySeasonalRepository",
    "MemorySourceReads",
    "ModeNotAvailable",
    "NothingToMake",
    "ObjectKeyRefused",
    "PostgresSeasonalRepository",
    "PostgresSourceReads",
    "RecipeSlot",
    "Season",
    "SeasonInvalid",
    "SeasonalError",
    "SeasonalMedia",
    "SeasonalMediaService",
    "StaleAttempt",
    "WrongState",
    "approved_for_worker",
    "check_object_key",
    "job_key",
    "job_payload",
    "production_seasonal_service",
]

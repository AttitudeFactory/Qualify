"""The business's seasonal library of stickers and short videos (m-24976891, design
`docs/opciones-stickers-videos-cortos.md` §1, §7–§9; founder decision 2026-11-08: beta at
zero cost with recipes B + E in `media-worker`, «Crear con IA» per piece).

## Why it lives in `whatsapp/`

What it makes is only ever SENT in a WhatsApp chat (a sticker cannot be published to the
networks), and its consumers are the chat's send menu and the outbox. It reads pieces and
the logo as SOURCES (provenance), the way the chat picker does; the creative module keeps
owning pieces.

## The table and the file

`brand_seasonal_media` (0142): one sticker (animated WebP, ≤ 500 KB) or short silent
video (MP4) per (business, season, recipe, source) — the unique slot makes `plan_batch`
idempotent. **Provenance** (hard rule): `source_kind` + `source_ref` + `recipe` +
`pipeline_version`, plus `cost_usd` (0 for B/E). The file lives at
`seasonal/{tenant}/{brand}/{season_key}/{media_id}.{webp|mp4}` (`ObjectGate.
put_seasonal_media`), OUTSIDE `t/` and outside the ADR 39 purge (amendment 2026-11-08):
past seasons are kept; the owner archives a season, and only deleting it deletes files.

## The life of a medium

`pending` (planned, job queued) → `ready` (the worker stored the file: `mark_ready`) or
`failed` (`mark_failed`); `ready` → `approved` (the owner, `approve`) or `rejected`
(`reject`). Archiving a season (`archive`) moves its `approved` rows to `archived` and
stamps `archived_at` on all of them; `restore` brings them back. **Only `approved` rows of
an unarchived season reach the chat** (`list_approved_for_chat`) — stricter than pieces,
as the founder asked. Nothing here sends anything: the chat sends on the owner's tap.

## The queue contract (for the recipes in `media-worker`)

`plan_batch` enqueues ONE `gallery_jobs` row per new medium (the `media-worker` queue,
0133), `kind = 'seasonal_media'`, `idempotency_key = 'seasonal:{media_id}'`,
`pipeline_version = SEASONAL_PIPELINE_VERSION`, and `payload`:

    {"media_id": "<uuid>", "tenant_id": "<uuid>", "brand_id": "<uuid>",
     "kind": "sticker" | "video", "recipe": "e-latido" | "b-zoom" | …,
     "source_kind": "piece" | "logo" | "text", "source_ref": "<draft ids, comma-separated
     | logo key | text>", "season_key": "navidad-2026"}

The worker renders the recipe, writes the file with `ObjectGate.put_seasonal_media` and
calls `SeasonalMediaService.mark_ready(tenant_id=…, brand_id=…, media_id=…, object_key=…,
bytes=…, width=…, height=…, duration_ms=…, cost_usd=…)`, or `mark_failed(tenant_id=…,
brand_id=…, media_id=…, reason=…)`. The worker claims only the kinds it knows, so these
jobs wait (queued) until the recipes ship.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final, Literal, Protocol
from uuid import UUID, uuid4

from qualify_shared.objects.keys import SEASON_KEY_RE, seasonal_brand_prefix

SEASONAL_PIPELINE_VERSION: Final = "seasonal-v1"
JOB_KIND: Final = "seasonal_media"
MAX_LABEL_CHARS: Final = 24

STATUS_PENDING: Final = "pending"
STATUS_READY: Final = "ready"
STATUS_APPROVED: Final = "approved"
STATUS_REJECTED: Final = "rejected"
STATUS_ARCHIVED: Final = "archived"
STATUS_FAILED: Final = "failed"

KIND_STICKER: Final = "sticker"
KIND_VIDEO: Final = "video"
EXTENSIONS: Final = {KIND_STICKER: "webp", KIND_VIDEO: "mp4"}

SOURCE_PIECE: Final = "piece"
SOURCE_LOGO: Final = "logo"
SOURCE_TEXT: Final = "text"

Mode = Literal["free", "ai"]


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


#: The standard batch, by mode — DATA the recipes ticket fills and tunes (≈ 6 stickers +
#: 4 videos). «free» = recipes B (videos from approved photos) + E (stickers drawn from the
#: logo or a short text), US$0. «ai» = the same stickers, videos animated with Seedance
#: (priced and guarded by the worker, ADR 41).
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
        RecipeSlot(KIND_STICKER, "e-latido", SOURCE_LOGO),
        RecipeSlot(KIND_STICKER, "e-rebote", SOURCE_LOGO),
        RecipeSlot(KIND_STICKER, "e-giro", SOURCE_LOGO),
        RecipeSlot(KIND_STICKER, "e-brillo", SOURCE_LOGO),
        RecipeSlot(KIND_STICKER, "e-texto", SOURCE_TEXT, text="¡Feliz {season}!"),
        RecipeSlot(KIND_STICKER, "e-texto", SOURCE_TEXT, text="¡Gracias por tu pedido!"),
        RecipeSlot(KIND_VIDEO, "ai-seedance", SOURCE_PIECE, pieces=1),
        RecipeSlot(KIND_VIDEO, "ai-seedance", SOURCE_PIECE, pieces=1),
        RecipeSlot(KIND_VIDEO, "ai-seedance", SOURCE_PIECE, pieces=1),
        RecipeSlot(KIND_VIDEO, "b-logo", SOURCE_LOGO),
    ),
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


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


class MediaNotFound(LookupError):
    """No seasonal medium with this id in this business."""


class WrongState(SeasonalError):
    message = "Este sticker o video ya no está en ese paso."


class ObjectKeyRefused(SeasonalError):
    message = "El archivo no está donde debe."


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


def job_payload(media: SeasonalMedia) -> dict[str, str]:
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
    }


def check_object_key(media: SeasonalMedia, object_key: str) -> str:
    """The file of `media` must be `seasonal/{tenant}/{brand}/{season}/{id}.{ext}`."""
    expected = (
        f"{seasonal_brand_prefix(media.tenant_id, media.brand_id)}{media.season_key}/"
        f"{media.id}.{EXTENSIONS[media.kind]}"
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

    def save(self, media: SeasonalMedia) -> SeasonalMedia: ...


class SourceReads(Protocol):
    def approved_photo_pieces(self, tenant_id: UUID, brand_id: UUID, limit: int) -> list[UUID]:
        """The business's approved photo pieces, newest first."""
        ...

    def logo_key(self, tenant_id: UUID, brand_id: UUID) -> str | None: ...


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
    ) -> None:
        self._repo = repo
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

    def plan_batch(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        season_key: str,
        season_label: str,
        mode: Mode,
        user_id: UUID | None,
    ) -> list[SeasonalMedia]:
        """The season's standard batch as `pending` rows, one `seasonal_media` job each.
        Idempotent: a slot already planned is returned as it is (no second job). Slots
        whose source is missing (no logo, too few approved pieces) are skipped."""
        if mode not in STANDARD_BATCH:
            raise ValueError(f"mode must be one of {tuple(STANDARD_BATCH)}")
        season_key = _check_season(season_key)
        label = _clean_label(season_label)
        slots = STANDARD_BATCH[mode]
        wanted = sum(s.pieces for s in slots)
        pieces = list(self._sources.approved_photo_pieces(tenant_id, brand_id, max(wanted, 1)))
        logo = self._sources.logo_key(tenant_id, brand_id)
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
        return [stored for stored, _new in self._repo.insert_planned(list(unique.values()))]

    # --- the worker ----------------------------------------------------------------------

    def mark_ready(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        media_id: UUID,
        object_key: str,
        bytes: int,
        width: int | None,
        height: int | None,
        duration_ms: int | None,
        cost_usd: Decimal | float | str = 0,
    ) -> SeasonalMedia:
        """The worker stored the file (only from `pending` or a retried `failed`)."""
        media = self._media(tenant_id, brand_id, media_id)
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
            )
        )

    def mark_failed(
        self, *, tenant_id: UUID, brand_id: UUID, media_id: UUID, reason: str
    ) -> SeasonalMedia:
        media = self._media(tenant_id, brand_id, media_id)
        if media.status not in (STATUS_PENDING, STATUS_FAILED):
            raise WrongState()
        return self._repo.save(
            replace(media, status=STATUS_FAILED, fail_reason=(reason or "unknown")[:200])
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
        return [
            self._repo.save(replace(m, status=STATUS_APPROVED, approved_at=now)) for m in chosen
        ]

    def reject(
        self, tenant_id: UUID, brand_id: UUID, media_id: UUID, user_id: UUID | None
    ) -> SeasonalMedia:
        """«Pedir otro»: a `ready` (or already `approved`) medium leaves the library."""
        media = self._media(tenant_id, brand_id, media_id)
        if media.status not in (STATUS_READY, STATUS_APPROVED):
            raise WrongState()
        return self._repo.save(replace(media, status=STATUS_REJECTED))

    def archive(self, tenant_id: UUID, brand_id: UUID, season_key: str) -> list[SeasonalMedia]:
        """The season leaves the chat: approved → archived; every row stamped."""
        now = self._clock()
        out = []
        for media in self._repo.list_brand(
            tenant_id=tenant_id, brand_id=brand_id, season_key=_check_season(season_key)
        ):
            if media.archived_at is not None:
                continue
            status = STATUS_ARCHIVED if media.status == STATUS_APPROVED else media.status
            out.append(self._repo.save(replace(media, status=status, archived_at=now)))
        return out

    def restore(self, tenant_id: UUID, brand_id: UUID, season_key: str) -> list[SeasonalMedia]:
        out = []
        for media in self._repo.list_brand(
            tenant_id=tenant_id, brand_id=brand_id, season_key=_check_season(season_key)
        ):
            if media.archived_at is None:
                continue
            status = STATUS_APPROVED if media.status == STATUS_ARCHIVED else media.status
            out.append(self._repo.save(replace(media, status=status, archived_at=None)))
        return out

    # --- reads -----------------------------------------------------------------------------

    def list_season(self, tenant_id: UUID, brand_id: UUID, season_key: str) -> list[SeasonalMedia]:
        rows = self._repo.list_brand(
            tenant_id=tenant_id, brand_id=brand_id, season_key=_check_season(season_key)
        )
        return sorted(rows, key=lambda m: (m.kind != KIND_STICKER, m.created_at, str(m.id)))

    def list_seasons(self, tenant_id: UUID, brand_id: UUID) -> list[Season]:
        """Every season of the business, the most recently active first."""
        groups: dict[str, list[SeasonalMedia]] = {}
        for media in self._repo.list_brand(tenant_id=tenant_id, brand_id=brand_id):
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
            ),
        )


# ======================================================================================
# In memory (tests)
# ======================================================================================


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
                    "kind": JOB_KIND,
                    "idempotency_key": f"seasonal:{row.id}",
                    "pipeline_version": SEASONAL_PIPELINE_VERSION,
                    "payload": job_payload(row),
                }
            )
            out.append((row, True))
        return out

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

    def save(self, media: SeasonalMedia) -> SeasonalMedia:
        if self.get(tenant_id=media.tenant_id, media_id=media.id) is None:
            raise MediaNotFound(str(media.id))
        self.rows[media.id] = media
        return media


class MemorySourceReads:
    def __init__(self) -> None:
        self.pieces: dict[tuple[UUID, UUID], list[UUID]] = {}
        self.logos: dict[tuple[UUID, UUID], str] = {}

    def approved_photo_pieces(self, tenant_id: UUID, brand_id: UUID, limit: int) -> list[UUID]:
        return list(self.pieces.get((tenant_id, brand_id), []))[:limit]

    def logo_key(self, tenant_id: UUID, brand_id: UUID) -> str | None:
        return self.logos.get((tenant_id, brand_id))


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


class PostgresSeasonalRepository:
    """`tenant_session(tenant_id)` per call (`qualify_app`, RLS). The planned rows and their
    jobs are written in ONE transaction: a row never exists without its job."""

    def insert_planned(self, rows: Sequence[SeasonalMedia]) -> list[tuple[SeasonalMedia, bool]]:
        if not rows:
            return []
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import select  # noqa: PLC0415
        from sqlalchemy.dialects.postgresql import insert  # noqa: PLC0415

        from qualify_api.catalog.business_media_models import GalleryJob  # noqa: PLC0415
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
                session.add(
                    GalleryJob(
                        tenant_id=row.tenant_id,
                        brand_id=row.brand_id,
                        kind=JOB_KIND,
                        idempotency_key=f"seasonal:{row.id}",
                        pipeline_version=SEASONAL_PIPELINE_VERSION,
                        payload=job_payload(row),
                    )
                )
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

    def save(self, media: SeasonalMedia) -> SeasonalMedia:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415

        from qualify_api.whatsapp.models import BrandSeasonalMedia as T  # noqa: PLC0415

        with tenant_session(media.tenant_id) as session:
            row = session.get(T, media.id, with_for_update=True)
            if row is None or row.brand_id != media.brand_id:
                raise MediaNotFound(str(media.id))
            for column in (
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
            ):
                setattr(row, column, getattr(media, column))
            session.flush()
            return _from_row(row)


def approved_for_worker(tenant_id: UUID, brand_id: UUID) -> list[SeasonalMedia]:
    """The chat-sendable media read as `qualify_webhook_worker` (0142's column grants),
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
        T.status,
        T.approved_at,
        T.archived_at,
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
    return SeasonalMediaService(PostgresSeasonalRepository(), PostgresSourceReads())


__all__ = [
    "EXTENSIONS",
    "JOB_KIND",
    "SEASONAL_PIPELINE_VERSION",
    "STANDARD_BATCH",
    "MediaNotFound",
    "MemorySeasonalRepository",
    "MemorySourceReads",
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
    "WrongState",
    "approved_for_worker",
    "check_object_key",
    "job_payload",
    "production_seasonal_service",
]

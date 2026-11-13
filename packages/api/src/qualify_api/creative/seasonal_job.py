"""The `seasonal_media` job of `media-worker` (m-24976892): render ONE seasonal sticker or
short video with the recipes of `qualify_creative.seasonal` and hand it to the library
(`qualify_api.whatsapp.seasonal`, m-24976891).

One job = one ATTEMPT of one `brand_seasonal_media` row, planned `pending` by
`SeasonalMediaService.plan_batch` (attempt 1) or `request_another` («Pedir otro», the
next attempt of the same row), whose `gallery_jobs` row carries the payload
`{media_id, tenant_id, brand_id, kind, recipe, source_kind, source_ref, season_key,
attempt}`.

1. **Idempotent start:** the row is read first; a row already past this attempt (the
   owner asked for another) or anything but `pending` / `failed` (it is already `ready`,
   approved, rejected…) ends the job as `skipped` — no render, no upload. A `StaleAttempt`
   from the service at the end means the same, and the result is dropped.
2. **Sources through the gate, bounded to the tenant:** `piece` → the approved pieces'
   first images (`source_ref` = comma-separated draft ids, re-checked to be THIS brand's
   approved photo pieces); `logo` → the Brand Kit logo (`source_ref` = its object key);
   `text` → the words themselves. The Brand Kit's palette and heading font come along
   (creative rule 7). Every read goes through `ObjectGate.open_object`, which refuses a key
   outside the tenant's roots.
3. **Render in a temp dir** that is removed whatever happens; FFmpeg on one thread under
   `nice` with a timeout; the output is validated (size, dimensions, transparency, no
   audio) BEFORE anything is stored — an over-limit file is never written.
4. **Store** with `ObjectGate.put_seasonal_media` at the deterministic key
   `seasonal/{tenant}/{brand}/{season}/{media_id}-{attempt}.{webp|mp4}` — a retry of the
   same attempt overwrites the same key, never a second file — retried `PUT_ATTEMPTS`
   times (creative rule 3).
5. **Mark:** `mark_ready` with the size, dimensions, duration and `cost_usd = 0` (no paid
   call happens: recipes B and E are FFmpeg + Pillow). A permanent failure is
   `mark_failed(reason)` with a short code (`no_source`, `unreadable_source`, `too_large`,
   `ffmpeg_failed`, `unknown_recipe`); a transient one (FFmpeg killed or timed out, an R2
   hiccup) returns `retry` and the worker re-queues the job; when its attempts run out the
   worker calls `give_up`, which marks the row failed and deletes the deterministic key.

The row's `pipeline_version` is the library's (`seasonal-v1`, set at planning); the
recipe's own version (`seasonal-b-1` / `seasonal-d-1` / `seasonal-c-2` / `seasonal-e-1`),
its encoding, the engine that drew it and why the Remotion recipe (C or D) fell back go in
the log line and the job's `result` — see `SeasonalOutcome.result`.

**Stickers (m-24987158):** production draws them with recipe C — the Remotion render
service at `QUALIFY_RENDER_URL` — and falls back to recipe E (Pillow) whenever that
service is off (its compose profile is not on yet), unreachable or fails.
`QUALIFY_SEASONAL_STICKERS=pillow` forces recipe E.

**Product stickers (m-25017372):** `source_kind = character` rows (season `productos`) are
an approved «tierno» character (`product_sticker_characters`) with a message
(`source_ref` = `{character_id}:{message}`), recipe `k-animado` or `k-quieto`. They are
drawn ONLY by the Remotion `sticker` template v2 (caption mode) — no Pillow fallback
(founder 2026-11-12): while the service is off or failing the job retries
(`render_unavailable`, transient) and, when its attempts run out, the row fails with it.

**Videos (m-25016848):** the same service draws them with recipe D and falls back to
recipe B (FFmpeg); `QUALIFY_SEASONAL_VIDEOS=ffmpeg` forces B. A photo video also reads the
Brand Kit logo for its closing sign-off — a missing or unreadable logo only drops the
sign-off, it never fails the video.
"""

from __future__ import annotations

import functools
import io
import logging
import os
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Protocol
from uuid import UUID

from PIL import Image
from qualify_creative.seasonal import (
    BrandLook,
    RecipeError,
    RecipeOutput,
    RemotionStickerRenderer,
    RemotionVideoRenderer,
    run_recipe,
)
from qualify_creative.seasonal.errors import NO_SOURCE, UNREADABLE_SOURCE
from qualify_creative.seasonal.look import load_image
from qualify_shared.objects.gate import ObjectNotFound
from qualify_shared.objects.keys import TenantPrefixViolation, seasonal_media_key

from qualify_api.whatsapp.seasonal import StaleAttempt, WrongState

logger = logging.getLogger("qualify_api.creative.seasonal_job")

JOB_SEASONAL = "seasonal_media"
SOURCE_PIECE = "piece"
SOURCE_LOGO = "logo"
SOURCE_TEXT = "text"
SOURCE_CHARACTER = "character"
#: m-25017372: the product stickers' recipes (animated, still).
PRODUCT_RECIPE_ANIMATED = "k-animado"
PRODUCT_RECIPES = (PRODUCT_RECIPE_ANIMATED, "k-quieto")
RENDER_UNAVAILABLE = "render_unavailable"
CHARACTER_UNAVAILABLE = "character_unavailable"
#: The render service's failures worth a retry (it was off, starting, busy or crashed).
TRANSIENT_RENDER_CODES = frozenset({"unreachable", "not_ready", "no_template", "render_failed"})
#: The statuses a job may (re)render from; anything else is already settled.
RENDERABLE = ("pending", "failed")
PUT_ATTEMPTS = 3
PUT_BACKOFF_SECONDS = 2.0
#: The largest source file read into memory (a piece image or a logo is far below).
MAX_SOURCE_BYTES = 25 * 1024 * 1024
#: The largest font file read (the Brand Kit upload's own ceiling).
MAX_FONT_BYTES = 20 * 1024 * 1024
MAX_PIECES = 3
#: Which engine draws the stickers: `remotion` (recipe C, falling back to E) or `pillow`
#: (recipe E only). Read once when the worker builds its handler.
STICKERS_ENGINE_ENV = "QUALIFY_SEASONAL_STICKERS"
#: Which engine draws the videos: `remotion` (recipe D, falling back to B) or `ffmpeg`
#: (recipe B only). Read once when the worker builds its handler.
VIDEOS_ENGINE_ENV = "QUALIFY_SEASONAL_VIDEOS"
KIND_VIDEO = "video"
RENDER_URL_ENV = "QUALIFY_RENDER_URL"


@dataclass(frozen=True)
class SeasonalJob:
    media_id: UUID
    tenant_id: UUID
    brand_id: UUID
    kind: str
    recipe: str
    source_kind: str
    source_ref: str
    season_key: str
    #: «Pedir otro» reuses the row: each attempt has its own job and its own file.
    attempt: int = 1

    @classmethod
    def from_payload(
        cls, payload: Mapping[str, Any] | None, *, tenant_id: UUID, brand_id: UUID
    ) -> SeasonalJob:
        """The payload, checked against the job row's own tenant and brand (a payload
        naming another tenant is refused, never followed)."""
        if not payload:
            raise ValueError("seasonal job without payload")
        job = cls(
            media_id=UUID(str(payload["media_id"])),
            tenant_id=UUID(str(payload["tenant_id"])),
            brand_id=UUID(str(payload["brand_id"])),
            kind=str(payload["kind"]),
            recipe=str(payload["recipe"]),
            source_kind=str(payload["source_kind"]),
            source_ref=str(payload.get("source_ref") or ""),
            season_key=str(payload["season_key"]),
            attempt=int(payload.get("attempt") or 1),
        )
        if job.attempt < 1:
            raise ValueError("seasonal attempt must be positive")
        if job.tenant_id != tenant_id or job.brand_id != brand_id:
            raise ValueError("seasonal payload does not match its job's tenant/brand")
        return job


@dataclass(frozen=True)
class SeasonalOutcome:
    status: str  # done | failed | retry | skipped | lost_lease
    reason: str = ""
    object_key: str | None = None
    result: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MediaRow:
    """What the job needs of the `brand_seasonal_media` row."""

    brand_id: UUID
    status: str
    attempt: int = 1
    object_key: str | None = None
    #: What the row says the medium is: the payload must agree (review of 58855151).
    season_key: str | None = None
    kind: str | None = None
    recipe: str | None = None
    source_kind: str | None = None
    source_ref: str | None = None

    def agrees_with(self, job: SeasonalJob) -> bool:
        """Every field the payload repeats equals the row's (a field the reader did not
        fill is not compared)."""
        pairs = (
            (self.season_key, job.season_key),
            (self.kind, job.kind),
            (self.recipe, job.recipe),
            (self.source_kind, job.source_kind),
            (self.source_ref, job.source_ref),
        )
        return all(mine is None or mine == theirs for mine, theirs in pairs)


# --- seams --------------------------------------------------------------------------------


class SeasonalObjects(Protocol):
    """The `ObjectGate` methods this job uses."""

    def open_object(self, tenant_id: UUID, object_key: str) -> IO[bytes]: ...

    def put_seasonal_media(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        season_key: str,
        media_id: UUID,
        extension: str,
        fileobj: IO[bytes],
        content_type: str,
        attempt: int = 1,
    ) -> str: ...

    def delete_seasonal_media(
        self, tenant_id: UUID, brand_id: UUID, object_keys: list[str]
    ) -> None: ...


class SeasonalMarks(Protocol):
    """`SeasonalMediaService`'s worker half."""

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
        cost_usd: Any = 0,
    ) -> Any: ...

    def mark_failed(
        self, *, tenant_id: UUID, brand_id: UUID, media_id: UUID, attempt: int, reason: str
    ) -> Any: ...


class SeasonalSources(Protocol):
    """Tenant-scoped reads of what a recipe draws from."""

    def media_row(self, tenant_id: UUID, media_id: UUID) -> MediaRow | None: ...

    def piece_image_keys(
        self, tenant_id: UUID, brand_id: UUID, draft_ids: Sequence[UUID]
    ) -> list[str]:
        """The first image's object key of each draft that is still one of this brand's
        approved photo pieces, in the order asked; the others are left out."""
        ...

    def palette(self, tenant_id: UUID, brand_id: UUID) -> list[str]: ...

    def character_art_key(self, tenant_id: UUID, brand_id: UUID, character_id: UUID) -> str | None:
        """The cut-out of an APPROVED character of this brand (m-25017372), or None."""
        ...

    def logo_key(self, tenant_id: UUID, brand_id: UUID) -> str | None:
        """The brand kit's logo object key (`BrandKit.logo_asset_key`), or None."""
        ...

    def heading_font(self, tenant_id: UUID, brand_id: UUID) -> tuple[str | None, str | None]:
        """(the heading font file's object key, the heading family's name)."""
        ...


Renderer = Callable[..., RecipeOutput]


class _Permanent(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# --- the handler --------------------------------------------------------------------------


class SeasonalMediaJobHandler:
    def __init__(
        self,
        *,
        objects: SeasonalObjects,
        marks: SeasonalMarks,
        sources: SeasonalSources,
        render: Renderer = run_recipe,
        product_render: ProductRenderer | None = None,
        google_fonts: Callable[[str], bytes | None] | None = None,
        tmp_root: Path | None = None,
        put_attempts: int = PUT_ATTEMPTS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._objects = objects
        self._marks = marks
        self._sources = sources
        self._render = render
        self._product_render = product_render
        self._google_fonts = google_fonts
        self._tmp_root = tmp_root
        self._put_attempts = max(1, put_attempts)
        self._sleep = sleep

    def handle(
        self, job: SeasonalJob, *, still_ours: Callable[[], bool] = lambda: True
    ) -> SeasonalOutcome:
        """Run one job. `still_ours` is asked right before the upload (the worker renews
        its lease there); False stops the job without writing anything."""
        row = self._sources.media_row(job.tenant_id, job.media_id)
        if row is None or row.brand_id != job.brand_id:
            return SeasonalOutcome("failed", "no_row")
        if not row.agrees_with(job):  # a crafted or stale payload: never followed
            return SeasonalOutcome("failed", "payload_mismatch")
        if row.attempt != job.attempt:  # the owner asked for another meanwhile
            return SeasonalOutcome("skipped", "stale_attempt")
        if row.status not in RENDERABLE:
            return SeasonalOutcome("skipped", row.status)
        try:
            with tempfile.TemporaryDirectory(prefix="qualify-seasonal-", dir=self._tmp_root) as tmp:
                output = self._render_job(job, Path(tmp))
        except _Permanent as exc:
            return self._failed(job, exc.code)
        except RecipeError as exc:
            if exc.transient:
                return SeasonalOutcome("retry", exc.code)
            return self._failed(job, exc.code)
        except Exception as exc:  # noqa: BLE001 — an R2 read hiccup, a full disk: retry
            logger.warning("seasonal_job.render_error media=%s %s", job.media_id, exc)
            return SeasonalOutcome("retry", f"render:{type(exc).__name__}")
        if output.kind != job.kind:
            return self._failed(job, "kind_mismatch")
        if not still_ours():
            return SeasonalOutcome("lost_lease")
        try:
            key = self._put(job, output)
        except Exception as exc:  # noqa: BLE001 — the bucket kept refusing: retry the job
            logger.warning("seasonal_job.put_failed media=%s %s", job.media_id, exc)
            return SeasonalOutcome("retry", f"r2_write:{type(exc).__name__}")
        result = {
            "media_id": str(job.media_id),
            "attempt": job.attempt,
            "recipe": output.recipe,
            "recipe_version": output.pipeline_version,
            "encoding": output.encoding,
            "bytes": output.bytes,
            "frames": output.frames,
            "over_target": output.over_target,
            "engine": output.engine,
            "fallback": output.fallback,
        }
        try:
            self._marks.mark_ready(
                tenant_id=job.tenant_id,
                brand_id=job.brand_id,
                media_id=job.media_id,
                attempt=job.attempt,
                object_key=key,
                bytes=output.bytes,
                width=output.width,
                height=output.height,
                duration_ms=output.duration_ms,
                cost_usd=output.cost_usd,
            )
        except StaleAttempt:  # «Pedir otro» meanwhile: this result is dropped
            self._delete_quietly(job)
            return SeasonalOutcome("skipped", "stale_attempt")
        except WrongState:
            # Settled meanwhile: drop the result. Keep the file only if the row points at
            # it (another run of this same attempt finished first); otherwise (rejected,
            # archived, failed while this ran) delete OUR exact key — `seasonal/` is
            # outside the purge, so an orphan there would never go away.
            now = self._sources.media_row(job.tenant_id, job.media_id)
            if now is not None and now.object_key == key:
                return SeasonalOutcome("skipped", "settled", key, result)
            self._delete_quietly(job)
            return SeasonalOutcome("skipped", "settled")
        except Exception as exc:  # noqa: BLE001
            logger.warning("seasonal_job.mark_ready_failed media=%s %s", job.media_id, exc)
            # the same key is overwritten on retry; the row is still pending/failed
            return SeasonalOutcome("retry", f"mark_ready:{type(exc).__name__}")
        logger.info(
            "seasonal_job.ready tenant=%s media=%s recipe=%s version=%s engine=%s "
            "fallback=%s encoding=%s bytes=%d",
            job.tenant_id,
            job.media_id,
            output.recipe,
            output.pipeline_version,
            output.engine or "-",
            output.fallback or "-",
            output.encoding,
            output.bytes,
        )
        return SeasonalOutcome("done", "", key, result)

    def give_up(self, job: SeasonalJob, reason: str) -> None:
        """The worker ran out of attempts: the row is failed and the deterministic key is
        deleted (an upload whose `mark_ready` never landed). Best effort, never raises."""
        try:
            self._marks.mark_failed(
                tenant_id=job.tenant_id,
                brand_id=job.brand_id,
                media_id=job.media_id,
                attempt=job.attempt,
                reason=reason or "attempts_exhausted",
            )
        except StaleAttempt:
            pass  # a newer attempt owns the row; this attempt's file is still ours to drop
        except Exception as exc:  # noqa: BLE001
            logger.warning("seasonal_job.give_up_mark_failed media=%s %s", job.media_id, exc)
            return  # the row may be ready after all: keep its file
        self._delete_quietly(job)

    def _delete_quietly(self, job: SeasonalJob) -> None:
        """Remove THIS attempt's file (never another attempt's: the key carries it)."""
        try:
            self._objects.delete_seasonal_media(
                job.tenant_id, job.brand_id, [self.expected_key(job)]
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("seasonal_job.delete_failed media=%s %s", job.media_id, exc)

    @staticmethod
    def expected_key(job: SeasonalJob) -> str:
        ext = "mp4" if job.kind == "video" else "webp"
        return seasonal_media_key(
            job.tenant_id, job.brand_id, job.season_key, job.media_id, ext, job.attempt
        )

    # -- steps ---------------------------------------------------------------------------

    def _failed(self, job: SeasonalJob, code: str) -> SeasonalOutcome:
        try:
            self._marks.mark_failed(
                tenant_id=job.tenant_id,
                brand_id=job.brand_id,
                media_id=job.media_id,
                attempt=job.attempt,
                reason=code,
            )
        except StaleAttempt:
            return SeasonalOutcome("skipped", "stale_attempt")
        except WrongState:  # settled by another run meanwhile: drop this failure
            return SeasonalOutcome("skipped", "settled")
        except Exception as exc:  # noqa: BLE001
            logger.warning("seasonal_job.mark_failed_failed media=%s %s", job.media_id, exc)
        logger.info(
            "seasonal_job.failed tenant=%s media=%s code=%s", job.tenant_id, job.media_id, code
        )
        return SeasonalOutcome("failed", code)

    def _read(self, tenant_id: UUID, key: str, limit: int = MAX_SOURCE_BYTES) -> bytes:
        try:
            stream = self._objects.open_object(tenant_id, key)
        except (ObjectNotFound, TenantPrefixViolation) as exc:
            raise _Permanent(NO_SOURCE) from exc
        try:
            data = stream.read(limit + 1)
        finally:
            close = getattr(stream, "close", None)
            if close is not None:
                close()
        if len(data) > limit:
            raise _Permanent(UNREADABLE_SOURCE)
        return data

    def _look(
        self, job: SeasonalJob, logo_key: str | None, *, logo_optional: bool = False
    ) -> BrandLook:
        palette = self._sources.palette(job.tenant_id, job.brand_id)
        font_key, family = self._sources.heading_font(job.tenant_id, job.brand_id)
        font: bytes | None = None
        if font_key:
            try:
                font = self._read(job.tenant_id, font_key, MAX_FONT_BYTES)
            except _Permanent:
                font = None  # an unreadable font falls back; it never fails the sticker
        if font is None and family and self._google_fonts is not None:
            try:
                font = self._google_fonts(family)
            except Exception:  # noqa: BLE001 — a nicety: the bundled face otherwise
                font = None
        logo: bytes | None = None
        if logo_key:
            try:
                logo = self._read(job.tenant_id, logo_key)
            except _Permanent:
                if not logo_optional:
                    raise
            except Exception as exc:  # noqa: BLE001 — an R2 hiccup
                if not logo_optional:
                    raise
                # only a photo video's sign-off needs it: never retry the job for it
                logger.warning(
                    "seasonal_job.optional_logo_unread media=%s %s",
                    job.media_id,
                    type(exc).__name__,
                )
        try:
            return BrandLook.from_kit(palette=palette, logo=logo, font=font, family=family)
        except RecipeError:
            if not logo_optional or logo is None:
                raise
            # an unreadable logo only drops a photo video's sign-off
            return BrandLook.from_kit(palette=palette, logo=None, font=font, family=family)

    def _render_character(self, job: SeasonalJob, work: Path) -> RecipeOutput:
        """A product sticker (m-25017372): the approved character's cut-out and the
        message, drawn by the Remotion template v2 only."""
        from qualify_api.creative.product_stickers import parse_source_ref  # noqa: PLC0415

        if job.recipe not in PRODUCT_RECIPES:
            raise _Permanent("unknown_recipe")
        try:
            character_id, message = parse_source_ref(job.source_ref)
        except ValueError as exc:
            raise _Permanent(NO_SOURCE) from exc
        key = self._sources.character_art_key(job.tenant_id, job.brand_id, character_id)
        if not key:
            raise _Permanent(CHARACTER_UNAVAILABLE)
        art = load_image(self._read(job.tenant_id, key), rgba=True)
        look = self._look(job, None, logo_optional=True)
        if self._product_render is None:
            raise RecipeError(RENDER_UNAVAILABLE, "no render service", transient=True)
        return self._product_render(job.recipe, look, work, art=art, message=message)

    def _render_job(self, job: SeasonalJob, work: Path) -> RecipeOutput:
        if job.source_kind == SOURCE_CHARACTER:
            return self._render_character(job, work)
        images: list[Image.Image] = []
        text: str | None = None
        logo_key: str | None = None
        if job.source_kind == SOURCE_LOGO:
            # The logo is the brand kit's own, read like the palette and the font; the
            # payload only has to name the same key (review of 58855151: a key taken from
            # the payload could be another brand's object of the same tenant).
            logo_key = self._sources.logo_key(job.tenant_id, job.brand_id)
            if not logo_key or job.source_ref != logo_key:
                raise _Permanent(NO_SOURCE)
        elif job.source_kind == SOURCE_PIECE:
            if job.kind == KIND_VIDEO:
                # the closing sign-off of a photo video (recipe D): optional
                logo_key = self._sources.logo_key(job.tenant_id, job.brand_id)
            ids = _draft_ids(job.source_ref)
            keys = self._sources.piece_image_keys(job.tenant_id, job.brand_id, ids)
            if not keys:
                raise _Permanent(NO_SOURCE)
            images = [load_image(self._read(job.tenant_id, k), rgba=False) for k in keys]
        elif job.source_kind == SOURCE_TEXT:
            text = job.source_ref.strip()
            if not text:
                raise _Permanent(NO_SOURCE)
        else:
            raise _Permanent(NO_SOURCE)
        # The logo is part of the look for every recipe that draws it (logo stickers,
        # the video end card, a photo video's sign-off); a text sticker needs only the
        # colours. Only a logo recipe fails without it.
        look = self._look(job, logo_key, logo_optional=job.source_kind != SOURCE_LOGO)
        return self._render(job.recipe, look, work, images=images, text=text)

    def _put(self, job: SeasonalJob, output: RecipeOutput) -> str:
        last: Exception | None = None
        for attempt in range(self._put_attempts):
            try:
                return self._objects.put_seasonal_media(
                    job.tenant_id,
                    job.brand_id,
                    job.season_key,
                    job.media_id,
                    output.ext,
                    io.BytesIO(output.data),
                    output.content_type,
                    attempt=job.attempt,
                )
            except Exception as exc:  # noqa: BLE001
                last = exc
                if attempt + 1 < self._put_attempts:
                    self._sleep(PUT_BACKOFF_SECONDS * (attempt + 1))
        assert last is not None
        raise last


def _draft_ids(source_ref: str) -> list[UUID]:
    ids: list[UUID] = []
    for part in source_ref.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(UUID(part))
        except ValueError as exc:
            raise _Permanent(NO_SOURCE) from exc
    return list(dict.fromkeys(ids))[:MAX_PIECES]


# --- production wiring --------------------------------------------------------------------


class PostgresSeasonalSources:
    """`tenant_session` reads (RLS) of the row, the pieces and the Brand Kit."""

    def media_row(self, tenant_id: UUID, media_id: UUID) -> MediaRow | None:
        from qualify_api.whatsapp.seasonal import PostgresSeasonalRepository  # noqa: PLC0415

        media = PostgresSeasonalRepository().get(tenant_id=tenant_id, media_id=media_id)
        if media is None:
            return None
        return MediaRow(
            brand_id=media.brand_id,
            status=media.status,
            attempt=media.attempt,
            object_key=media.object_key,
            season_key=media.season_key,
            kind=media.kind,
            recipe=media.recipe,
            source_kind=media.source_kind,
            source_ref=media.source_ref,
        )

    def character_art_key(self, tenant_id: UUID, brand_id: UUID, character_id: UUID) -> str | None:
        from qualify_api.creative.product_stickers import (  # noqa: PLC0415
            STATUS_APPROVED,
            PostgresCharacterRepository,
        )

        found = PostgresCharacterRepository().get(tenant_id=tenant_id, character_id=character_id)
        if found is None or found.brand_id != brand_id or found.status != STATUS_APPROVED:
            return None
        return found.object_key

    def logo_key(self, tenant_id: UUID, brand_id: UUID) -> str | None:
        from qualify_api.whatsapp.seasonal import PostgresSourceReads  # noqa: PLC0415

        return PostgresSourceReads().logo_key(tenant_id, brand_id)

    def piece_image_keys(
        self, tenant_id: UUID, brand_id: UUID, draft_ids: Sequence[UUID]
    ) -> list[str]:
        from qualify_api.whatsapp.attachments import PostgresAttachmentReads  # noqa: PLC0415

        usable = {
            p.id: p.image_key
            for p in PostgresAttachmentReads().pieces(tenant_id, brand_id)
            if p.brand_id == brand_id
            and p.status in ("approved", "staged", "published")
            and p.media_type == "image"
            and p.image_key
        }
        return [usable[d] for d in draft_ids if d in usable]

    def palette(self, tenant_id: UUID, brand_id: UUID) -> list[str]:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import select  # noqa: PLC0415

        from qualify_api.creative.models import BrandKit  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            value = session.scalar(
                select(BrandKit.palette_rgb).where(BrandKit.brand_id == brand_id)
            )
        return list(value or [])

    def heading_font(self, tenant_id: UUID, brand_id: UUID) -> tuple[str | None, str | None]:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import select  # noqa: PLC0415

        from qualify_api.creative.brand_fonts import DbBrandFontFiles  # noqa: PLC0415
        from qualify_api.creative.models import BrandKit  # noqa: PLC0415

        key = DbBrandFontFiles()(tenant_id=tenant_id, brand_id=brand_id)
        with tenant_session(tenant_id) as session:
            family = session.scalar(
                select(BrandKit.font_heading).where(BrandKit.brand_id == brand_id)
            )
        return key, family


def sticker_renderer_from_env(
    env: Mapping[str, str] | None = None,
) -> RemotionStickerRenderer | None:
    """Recipe C's renderer, or None when stickers must stay on recipe E
    (`QUALIFY_SEASONAL_STICKERS=pillow`, or no `QUALIFY_RENDER_URL`). A renderer is
    returned even when the service is down: each sticker checks `/health` and falls back
    to E on its own, so the worker needs no restart when the profile is turned on."""
    env = os.environ if env is None else env
    engine = (env.get(STICKERS_ENGINE_ENV) or "remotion").strip().lower()
    url = (env.get(RENDER_URL_ENV) or "").strip()
    if engine == "pillow" or not url:
        logger.info("seasonal_job.stickers engine=pillow url=%s", url or "-")
        return None
    logger.info("seasonal_job.stickers engine=remotion fallback=pillow url=%s", url)
    return RemotionStickerRenderer.from_url(url)


def video_renderer_from_env(
    env: Mapping[str, str] | None = None,
) -> RemotionVideoRenderer | None:
    """Recipe D's renderer, or None when videos must stay on recipe B
    (`QUALIFY_SEASONAL_VIDEOS=ffmpeg`, or no `QUALIFY_RENDER_URL`). Like the stickers', a
    renderer is returned even when the service is down: each video checks `/health`."""
    env = os.environ if env is None else env
    engine = (env.get(VIDEOS_ENGINE_ENV) or "remotion").strip().lower()
    url = (env.get(RENDER_URL_ENV) or "").strip()
    if engine == "ffmpeg" or not url:
        logger.info("seasonal_job.videos engine=ffmpeg url=%s", url or "-")
        return None
    logger.info("seasonal_job.videos engine=remotion fallback=ffmpeg url=%s", url)
    return RemotionVideoRenderer.from_url(url)


class ProductRenderer(Protocol):
    def __call__(
        self, recipe: str, look: BrandLook, work: Path, *, art: Image.Image, message: str
    ) -> RecipeOutput: ...


def product_sticker_output(
    renderer: RemotionStickerRenderer,
    recipe: str,
    look: BrandLook,
    work: Path,
    *,
    art: Image.Image,
    message: str,
) -> RecipeOutput:
    """One product sticker as a `RecipeOutput` (m-25017372): Remotion v2 only. A service
    failure is `render_unavailable` (transient when retrying may help)."""
    from qualify_creative.seasonal.sticker_c import StickerRenderError  # noqa: PLC0415
    from qualify_creative.seasonal.sticker_caption import make_product_sticker  # noqa: PLC0415

    try:
        sticker = make_product_sticker(
            renderer,
            look,
            work,
            art=art,
            message=message,
            animated=recipe == PRODUCT_RECIPE_ANIMATED,
        )
    except StickerRenderError as exc:
        raise RecipeError(
            RENDER_UNAVAILABLE, exc.code, transient=exc.code in TRANSIENT_RENDER_CODES
        ) from exc
    except ValueError as exc:  # a message the service refused at planning time
        raise RecipeError(NO_SOURCE, str(exc)) from exc
    return RecipeOutput(
        data=sticker.data,
        kind="sticker",
        recipe=recipe,
        content_type="image/webp",
        ext="webp",
        width=sticker.width,
        height=sticker.height,
        duration_ms=sticker.duration_ms,
        frames=sticker.frames,
        bytes=sticker.bytes,
        pipeline_version=sticker.pipeline_version,
        encoding=f"remotion+pillow q={sticker.quality} motion={sticker.motion}",
        engine=sticker.engine,
    )


def production_seasonal_handler(objects: SeasonalObjects) -> SeasonalMediaJobHandler:
    from qualify_creative.brand.fonts import google_font_file  # noqa: PLC0415

    from qualify_api.whatsapp.seasonal import production_seasonal_service  # noqa: PLC0415

    render: Renderer = functools.partial(
        run_recipe,
        sticker_renderer=sticker_renderer_from_env(),
        video_renderer=video_renderer_from_env(),
    )
    # product stickers have no Pillow fallback: without a render URL they wait (retry)
    url = (os.environ.get(RENDER_URL_ENV) or "").strip()
    product_render: ProductRenderer | None = (
        functools.partial(product_sticker_output, RemotionStickerRenderer.from_url(url))
        if url
        else None
    )
    return SeasonalMediaJobHandler(
        objects=objects,
        marks=production_seasonal_service(),
        sources=PostgresSeasonalSources(),
        render=render,
        product_render=product_render,
        google_fonts=google_font_file,
    )

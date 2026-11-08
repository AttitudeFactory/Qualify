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
recipe's own version (`seasonal-b-1` / `seasonal-e-1`) and its encoding go in the log line
and the job's `result` — see `SeasonalOutcome.result`.
"""

from __future__ import annotations

import io
import logging
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Protocol
from uuid import UUID

from PIL import Image
from qualify_creative.seasonal import BrandLook, RecipeError, RecipeOutput, run_recipe
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
#: The statuses a job may (re)render from; anything else is already settled.
RENDERABLE = ("pending", "failed")
PUT_ATTEMPTS = 3
PUT_BACKOFF_SECONDS = 2.0
#: The largest source file read into memory (a piece image or a logo is far below).
MAX_SOURCE_BYTES = 25 * 1024 * 1024
#: The largest font file read (the Brand Kit upload's own ceiling).
MAX_FONT_BYTES = 20 * 1024 * 1024
MAX_PIECES = 3


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
        google_fonts: Callable[[str], bytes | None] | None = None,
        tmp_root: Path | None = None,
        put_attempts: int = PUT_ATTEMPTS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._objects = objects
        self._marks = marks
        self._sources = sources
        self._render = render
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
            "seasonal_job.ready tenant=%s media=%s recipe=%s version=%s encoding=%s bytes=%d",
            job.tenant_id,
            job.media_id,
            output.recipe,
            output.pipeline_version,
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

    def _look(self, job: SeasonalJob, logo_key: str | None) -> BrandLook:
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
        logo = self._read(job.tenant_id, logo_key) if logo_key else None
        return BrandLook.from_kit(palette=palette, logo=logo, font=font)

    def _render_job(self, job: SeasonalJob, work: Path) -> RecipeOutput:
        images: list[Image.Image] = []
        text: str | None = None
        logo_key: str | None = None
        if job.source_kind == SOURCE_LOGO:
            logo_key = job.source_ref or None
            if logo_key is None:
                raise _Permanent(NO_SOURCE)
        elif job.source_kind == SOURCE_PIECE:
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
        # the video end card); a text sticker or a piece video needs only the colours.
        look = self._look(job, logo_key)
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
        )

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


def production_seasonal_handler(objects: SeasonalObjects) -> SeasonalMediaJobHandler:
    from qualify_creative.brand.fonts import google_font_file  # noqa: PLC0415

    from qualify_api.whatsapp.seasonal import production_seasonal_service  # noqa: PLC0415

    return SeasonalMediaJobHandler(
        objects=objects,
        marks=production_seasonal_service(),
        sources=PostgresSeasonalSources(),
        google_fonts=google_font_file,
    )

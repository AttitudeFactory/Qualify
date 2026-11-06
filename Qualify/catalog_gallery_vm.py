"""View models of «Fotos y videos de tu negocio» in Galería (CM-2, m-24955919).

Pure: no Reflex, no database. What the section says and shows is decided here, from the
plain records `catalog_gallery_provider` reads (`BusinessMediaRecord`,
`GalleryJobRecord`) and the outcome of an upload, so every text and state has a test.

Contract: `docs/epica-galeria-medios-negocio.md` §5 CM-2 — the copy below is verbatim
from it, except where a line names the variant it derives (photos instead of a video).
The backend's own sentences (too heavy, 3 videos waiting, the Galería full, a file that
did not arrive) are imported, never retyped, so the screen and the service cannot drift.

States of a tile (`GalleryItemVM.state`):

- ``ready``     — a photo or a video in the Galería: thumbnail, «Quitar».
- ``preparing`` — an `ingest` job still running in `media-worker`: «Preparando tu
  video…». Read from the job, so it survives a reload and a deploy (§4.3).
- ``failed``    — an `ingest` job that failed: «No pudimos preparar este video. Súbelo
  otra vez.» with «Quitar» (dismisses the job; there is no file to lose).
- ``cutting``   — a video with an active `cut` job (CM-3): it cannot be removed.

Only ``ready`` tiles are ``selectable`` (CM-5) and ``cuttable`` (CM-4, videos only).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from qualify_api.catalog.business_media import (
    CUTTING_TEXT,
    EMPTY_FILE_TEXT,
    GALLERY_FULL_TEXT,
    MAX_WAITING_VIDEOS,
    MIN_PART_MS,
    PHOTO_TOO_HEAVY_TEXT,
    VIDEO_TOO_HEAVY_TEXT,
    VIDEOS_WAITING_TEXT,
)
from qualify_api.catalog.business_media_models import (
    ACTIVE_STATUSES,
    JOB_CUT,
    JOB_INGEST,
    STATUS_DONE,
    STATUS_FAILED,
)
from qualify_api.catalog.business_media_staging import MAX_UPLOAD_BYTES
from qualify_creative.video import is_video_filename

__all__ = [
    "ADD_LABEL",
    "CUTTING_NOTE",
    "CUTTING_TEXT",
    "EMPTY_FILE_TEXT",
    "FAILED_TEXT",
    "GALLERY_DESCRIPTION",
    "GALLERY_EMPTY",
    "GALLERY_FULL_TEXT",
    "GALLERY_MEDIA_ACCEPT",
    "GALLERY_TITLE",
    "MAX_UPLOAD_BYTES",
    "MAX_WAITING_VIDEOS",
    "PREPARING_TEXT",
    "REMOVE_DESCRIPTION",
    "TRIMMED_DISMISS",
    "TRIMMED_TEXT",
    "UPLOAD_CUT_TEXT",
    "VIDEOS_WAITING_TEXT",
    "VIDEO_TOO_HEAVY_TEXT",
    "VIDEOS_WAITING_NOTICE",
    "VISIBLE_TILES",
    "GalleryItemVM",
    "OutcomeRow",
    "build_gallery_items",
    "count_videos",
    "duration_label",
    "duration_spoken",
    "more_label",
    "outcome_messages",
    "rejection_text",
    "remove_title",
    "trimmed_job_ids",
    "upload_text",
    "videos_waiting",
    "visible_items",
]

#: A video being cut (CM-4's text): the tile says it until media-worker is done.
CUTTING_NOTE = "Cortando tu video… Puedes salir; tus partes aparecerán en tu Galería."
GALLERY_TITLE = "Fotos y videos de tu negocio"
GALLERY_DESCRIPTION = "Muestra tu local, tu equipo y cómo trabajas. Úsalas en tus publicaciones."
ADD_LABEL = "Agregar fotos o videos"
GALLERY_EMPTY = (
    "Todavía no tienes fotos ni videos de tu negocio. "
    "Sube algunas de tu local, tu equipo o tu trabajo."
)
UPLOAD_CUT_TEXT = "Se cortó la subida. Revisa tu conexión y vuelve a intentarlo."
PREPARING_TEXT = "Preparando tu video… Puedes salir; aparecerá aquí cuando esté listo."
FAILED_TEXT = "No pudimos preparar este video. Súbelo otra vez."
TRIMMED_TEXT = (
    "Tu video dura más de un minuto y guardamos solo el primero. "
    "Si quieres otra parte, recórtala en tu teléfono antes de subirla."
)
TRIMMED_DISMISS = "Entendido"
REMOVE_DESCRIPTION = "Las publicaciones que ya hiciste no cambian."
#: The service's 3-waiting sentence (the epic's), then what the owner CAN do now
#: (founder via main thread, 2026-11-06).
PHOTOS_STILL_OK = "Las fotos sí puedes subirlas ahora."
VIDEOS_WAITING_NOTICE = f"{VIDEOS_WAITING_TEXT} {PHOTOS_STILL_OK}"
#: How many tiles show before «Ver todas (N)» (main thread, 2026-11-06): the products
#: below stay within reach on a phone.
VISIBLE_TILES = 6
SHOW_LESS = "Ver menos"
#: An upload error the screen cannot attribute (the database down while saving).
SAVE_FAILED_TEXT = "Algo falló de nuestro lado. Inténtalo otra vez en un minuto."

#: What the picker offers: the phone's photos (HEIC included, the service converts them)
#: and its videos. Same families as a product's media (`catalog_vm.MEDIA_ACCEPT`).
GALLERY_MEDIA_ACCEPT: dict[str, list[str]] = {
    "image/*": [".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif"],
    "video/mp4": [".mp4", ".m4v"],
    "video/quicktime": [".mov"],
}

STATE_READY = "ready"
STATE_PREPARING = "preparing"
STATE_FAILED = "failed"
STATE_CUTTING = "cutting"


class MediaLike(Protocol):
    id: UUID
    media_type: str
    poster_key: str | None
    object_key: str
    duration_ms: int | None
    created_at: datetime


class JobLike(Protocol):
    id: UUID
    kind: str
    status: str
    source_media_id: UUID | None
    media_id: UUID | None
    trimmed: bool


@dataclass(frozen=True)
class GalleryItemVM:
    """One tile of the section. `key` is unique across media and jobs (React's key)."""

    key: str
    state: str
    media_id: str
    job_id: str
    media_type: str
    #: `/r2media/<token>` of the photo or the video's poster ("" → the placeholder).
    thumb_url: str
    #: `/r2media/<token>` of the video itself ("" for a photo, or not ready).
    video_url: str
    #: «0:42» for a video, "" otherwise.
    duration: str
    #: The video's length in ms (0 for a photo): the cutter's timeline (CM-4).
    duration_ms: int
    #: What a screen reader hears: «Foto de tu negocio», «Video de 42 segundos».
    label: str
    #: What «Quitar» says to a screen reader: «Quitar la foto de tu negocio».
    remove_label: str
    #: The line under the tile while it is not simply ready ("" when it is).
    note: str
    note_tone: str
    can_remove: bool
    #: CM-5: may be chosen for a publication. CM-4: a video that may be cut.
    selectable: bool
    cuttable: bool


@dataclass(frozen=True)
class OutcomeRow:
    """What one file of an upload became, reduced to what the screen says about it."""

    filename: str
    error_text: str = ""
    duplicate: bool = False
    is_video: bool = False


# -- durations -------------------------------------------------------------------------------


def duration_label(duration_ms: int | None) -> str:
    """«0:42» (the same rounding as `BusinessMediaRecord.duration_label`)."""
    if duration_ms is None:
        return ""
    seconds = int(round(max(duration_ms, 0) / 1000))
    return f"{seconds // 60}:{seconds % 60:02d}"


def duration_spoken(duration_ms: int | None) -> str:
    """«42 segundos», «1 minuto», «1 minuto y 5 segundos» — for screen readers."""
    if duration_ms is None:
        return ""
    seconds = int(round(max(duration_ms, 0) / 1000))
    minutes, rest = divmod(seconds, 60)
    parts: list[str] = []
    if minutes:
        parts.append(f"{minutes} minuto" + ("" if minutes == 1 else "s"))
    if rest or not minutes:
        parts.append(f"{rest} segundo" + ("" if rest == 1 else "s"))
    return " y ".join(parts)


# -- the tiles ---------------------------------------------------------------------------------


def _active(job: JobLike) -> bool:
    return job.status in ACTIVE_STATUSES


def videos_waiting(jobs: Iterable[JobLike]) -> int:
    """Videos still being prepared (active `ingest` jobs): the «3 waiting» count."""
    return sum(1 for j in jobs if j.kind == JOB_INGEST and _active(j))


def trimmed_job_ids(jobs: Iterable[JobLike]) -> list[str]:
    """Finished uploads whose video passed a minute (D2): the notice stays until the
    owner says «Entendido» (the jobs are dismissed) or a day goes by (the service)."""
    return [
        str(j.id)
        for j in jobs
        if j.kind == JOB_INGEST and j.status == STATUS_DONE and j.trimmed and j.media_id is not None
    ]


def build_gallery_items(
    media: Sequence[MediaLike],
    jobs: Sequence[JobLike],
    url_for: Callable[[str, str], str],
) -> list[GalleryItemVM]:
    """The tiles, in the order the owner reads them: what is still being prepared (or
    failed) first, right under «Agregar fotos o videos», then the Galería newest first
    (main thread, 2026-11-06: what was just uploaded is in view). Media saved together
    (the parts of one cut) share their creation time and keep the service's own order.
    `url_for(key, "image" | "video")` mints the browser path of an R2 key ("" when it
    cannot)."""
    cutting = {
        str(j.source_media_id)
        for j in jobs
        if j.kind == JOB_CUT and _active(j) and j.source_media_id is not None
    }
    items: list[GalleryItemVM] = []
    for job in jobs:
        if job.kind != JOB_INGEST or job.status == STATUS_DONE:
            continue
        failed = job.status == STATUS_FAILED
        items.append(
            GalleryItemVM(
                key=f"job-{job.id}",
                state=STATE_FAILED if failed else STATE_PREPARING,
                media_id="",
                job_id=str(job.id),
                media_type="video",
                thumb_url="",
                video_url="",
                duration="",
                duration_ms=0,
                label="Video que no pudimos preparar" if failed else "Video en preparación",
                remove_label="el video que no pudimos preparar",
                note=FAILED_TEXT if failed else PREPARING_TEXT,
                note_tone="error" if failed else "info",
                can_remove=failed,
                selectable=False,
                cuttable=False,
            )
        )
    for m in sorted(media, key=lambda m: m.created_at, reverse=True):
        media_id = str(m.id)
        is_video = m.media_type == "video"
        busy = media_id in cutting
        thumb_key = m.poster_key or ("" if is_video else m.object_key)
        items.append(
            GalleryItemVM(
                key=f"media-{media_id}",
                state=STATE_CUTTING if busy else STATE_READY,
                media_id=media_id,
                job_id="",
                media_type="video" if is_video else "image",
                thumb_url=url_for(thumb_key, "image") if thumb_key else "",
                video_url=url_for(m.object_key, "video") if is_video else "",
                duration=duration_label(m.duration_ms) if is_video else "",
                duration_ms=int(m.duration_ms or 0) if is_video else 0,
                label=(
                    f"Video de {duration_spoken(m.duration_ms)}"
                    if is_video and m.duration_ms is not None
                    else ("Video de tu negocio" if is_video else "Foto de tu negocio")
                ),
                remove_label=(
                    f"el video de {duration_spoken(m.duration_ms)}"
                    if is_video and m.duration_ms is not None
                    else ("el video de tu negocio" if is_video else "la foto de tu negocio")
                ),
                note=CUTTING_NOTE if busy else "",
                note_tone="info" if busy else "neutral",
                can_remove=not busy,
                selectable=not busy,
                # a cut needs room for two parts of 3 s
                cuttable=is_video and not busy and int(m.duration_ms or 0) >= 2 * MIN_PART_MS,
            )
        )
    return items


def more_label(total: int, *, expanded: bool) -> str:
    """«Ver todas (14)» while only the first `VISIBLE_TILES` show, «Ver menos» after;
    "" when everything fits."""
    if total <= VISIBLE_TILES:
        return ""
    return SHOW_LESS if expanded else f"Ver todas ({total})"


def visible_items(items: Sequence[GalleryItemVM], *, expanded: bool) -> list[GalleryItemVM]:
    return list(items) if expanded else list(items[:VISIBLE_TILES])


def remove_title(media_type: str) -> str:
    """The confirmation's question («¿Quitar este video…?» or «…esta foto…»)."""
    if media_type == "video":
        return "¿Quitar este video de tu Galería?"
    return "¿Quitar esta foto de tu Galería?"


# -- the upload ----------------------------------------------------------------------------


def _name(row: Mapping[str, Any]) -> str:
    return str(row.get("name") or row.get("path") or "")


def count_videos(picked: Iterable[Mapping[str, Any]]) -> int:
    """How many of the picked files are videos — by name, the same rule the service
    stages them by (`is_video_filename`), so the pre-check counts what it will count."""
    return sum(1 for row in picked if is_video_filename(_name(row)))


def upload_text(percent: int, *, videos: int, photos: int) -> str:
    """«Subiendo tu video (45 %). Deja esta pantalla abierta hasta que termine.» — the
    epic's sentence for one video; the same shape for photos or a mix."""
    p = min(max(int(percent), 0), 100)
    if videos == 1 and photos == 0:
        what = "tu video"
    elif videos > 1 and photos == 0:
        what = "tus videos"
    elif photos == 1 and videos == 0:
        what = "tu foto"
    elif videos == 0:
        what = "tus fotos"
    else:
        what = "tus fotos y videos"
    return f"Subiendo {what} ({p} %). Deja esta pantalla abierta hasta que termine."


def rejection_text(rejected: Sequence[object]) -> str:
    """The owner's sentence for files the picker refused before uploading
    (react-dropzone's `fileRejections`): over 500 MB is the service's «muy pesado»;
    anything else is not a photo or a video."""
    too_large_video = too_large_photo = other = False
    for row in rejected or ():
        if not isinstance(row, dict):
            other = True
            continue
        codes = {str(e.get("code", "")) for e in (row.get("errors") or ()) if isinstance(e, dict)}
        file = row.get("file")
        name = _name(file) if isinstance(file, dict) else ""
        if "file-too-large" in codes:
            if name and not is_video_filename(name):
                too_large_photo = True
            else:
                too_large_video = True
        else:
            other = True
    if too_large_video:
        return VIDEO_TOO_HEAVY_TEXT
    if too_large_photo:
        return PHOTO_TOO_HEAVY_TEXT
    if other:
        return "Ese archivo no es una foto ni un video. Prueba con otro de tu teléfono."
    return ""


def outcome_messages(rows: Sequence[OutcomeRow]) -> tuple[str, str]:
    """(what went wrong, what went right) after an upload, in the owner's words.

    Each refusal is the service's own sentence; only when several files failed is each
    one named (the phone's file name means little, but it tells two failures apart).
    What went right confirms the photos saved (videos confirm themselves with their
    «Preparando…» tile) and says which files were already there."""
    errors = [r for r in rows if r.error_text]
    seen: list[str] = []
    for r in errors:
        text = VIDEOS_WAITING_NOTICE if r.error_text == VIDEOS_WAITING_TEXT else r.error_text
        line = f"{r.filename}: {text}" if len(errors) > 1 and r.filename else text
        if line not in seen:
            seen.append(line)
    ok = [r for r in rows if not r.error_text]
    dup = [r for r in ok if r.duplicate]
    saved_photos = sum(1 for r in ok if not r.duplicate and not r.is_video)
    parts: list[str] = []
    if saved_photos == 1:
        parts.append("Listo: tu foto ya está en tu Galería.")
    elif saved_photos > 1:
        parts.append(f"Listo: subimos {saved_photos} fotos a tu Galería.")
    if dup:
        if len(rows) == 1:
            parts.append(
                "Ese video ya estaba en tu Galería."
                if dup[0].is_video
                else "Esa foto ya estaba en tu Galería."
            )
        elif len(dup) == 1:
            parts.append(
                "Uno de los videos ya estaba en tu Galería; subimos los demás."
                if dup[0].is_video
                else "Una de las fotos ya estaba en tu Galería; subimos las demás."
            )
        else:
            parts.append(f"{len(dup)} ya estaban en tu Galería; no los subimos de nuevo.")
    return " · ".join(seen), " ".join(parts)

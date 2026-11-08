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
- ``part_pending`` — a part a queued or running `cut` job will save (m-24976806): a
  placeholder where the part will land (the top of the Galería, newest first), with a
  spinner and «Parte 1 de 2: cortándose…». The video being cut leaves the grid
  meanwhile: the cut's card above the tiles shows it (`build_cut_cards`), and it comes
  back as it was if the cut fails.

Only ``ready`` tiles are ``selectable`` (CM-5) and ``cuttable`` (CM-4, videos only).
A ready video is cuttable when it lasts MORE than one minimum part (m-24976897): keeping
one part and leaving the rest out — a trim — is a cut too («dejar por fuera partes del
clip»). A shorter one still shows «Cortar video», disabled, with the reason beside it
(`cut_reason`): an action is never hidden without saying why.

A cut's card (`CutCardVM`, m-24976806) says where the cut is — the job's own status:
en cola → cortando → guardando —, then «Listo: tu video quedó en N partes.» with the
parts, or «No pudimos cortar este video. Tu video original sigue igual.».
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
    STATUS_PARTS_SAVED,
    STATUS_QUEUED,
    STATUS_RUNNING,
)
from qualify_api.catalog.business_media_staging import MAX_UPLOAD_BYTES
from qualify_creative.video import is_video_filename

__all__ = [
    "ADD_LABEL",
    "TOO_SHORT_TO_CUT_TEXT",
    "can_cut",
    "CUT_FAILED_NOTICE",
    "CUT_LEAVE_OK",
    "CUT_RETRY",
    "CUTTING_NOTE",
    "DROP_HINT",
    "DRAG_HINT",
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
    "CutCardVM",
    "GalleryItemVM",
    "OutcomeRow",
    "build_cut_cards",
    "build_gallery_items",
    "cut_done_text",
    "cut_title",
    "retry_spans",
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

#: m-24976897: why «Cortar video» is disabled on a video that is too short to keep a
#: part and leave something out (the minimum is the service's: `MIN_PART_MS`).
TOO_SHORT_TO_CUT_TEXT = (
    f"Este video es muy corto para cortarlo: cada parte debe durar al menos "
    f"{MIN_PART_MS // 1000} segundos."
)


def can_cut(duration_ms: int | None) -> bool:
    """Longer than one minimum part: one part can stay and something can go."""
    return int(duration_ms or 0) > MIN_PART_MS


#: A video being cut (CM-4's text): the tile says it until media-worker is done.
CUTTING_NOTE = "Cortando tu video… Puedes salir; tus partes aparecerán en tu Galería."
#: m-24976806: the cut's card and the cutter's waiting step. The stages are the job's
#: own status, in the order media-worker goes through them.
CUT_STAGES: tuple[tuple[str, str], ...] = (
    (STATUS_QUEUED, "Esperando su turno…"),
    (STATUS_RUNNING, "Cortando las partes…"),
    (STATUS_PARTS_SAVED, "Guardando tus partes…"),
)
CUT_LEAVE_OK = "Puedes salir; tus partes aparecerán en tu Galería."
CUT_LEAVE_OK_ONE = "Puedes salir; aparecerá en tu Galería."
#: The founder's sentence (2026-11-08) — the service's own says the same in other words.
CUT_FAILED_NOTICE = "No pudimos cortar este video. Tu video original sigue igual."
CUT_RETRY = "Intentar de nuevo"
#: Drag and drop onto the whole section (m-24976806): what the highlight says, and the
#: one line under the button on a computer (a phone has no dragging).
DROP_HINT = "Suelta aquí tus fotos y videos"
DRAG_HINT = "También puedes arrastrar tus fotos y videos aquí."
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
STATE_PART_PENDING = "part_pending"


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


class CutJobLike(JobLike, Protocol):
    status: str
    created_at: datetime
    part_ids: tuple[UUID, ...]
    segments: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class CutCardVM:
    """One cut, above the tiles and in the cutter's waiting step (m-24976806)."""

    job_id: str
    #: The video being cut (it stays in the Galería until the parts are saved).
    source_id: str
    #: ``active`` (queued, cutting or saving), ``done`` or ``failed``.
    phase: str
    parts: int
    #: «Cortando tu video en 2 partes…» / «Listo: tu video quedó en 2 partes.» / the
    #: failure.
    title: str
    #: «Puedes salir; tus partes aparecerán en tu Galería.» while active, else "".
    detail: str
    #: The running stage's sentence («Cortando las partes…»), "" once it ended.
    stage_text: str
    #: `progress_panel`'s stages: `{"title", "status"}` (done / running / pending).
    steps: list[dict[str, str]]
    #: The video's poster (the first part's once the original is gone).
    thumb_url: str
    #: The parts' posters, in order, once they exist.
    part_thumbs: list[str]


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
    #: m-24976897: a ready video shows «Cortar video» — enabled (`cuttable`) or, too
    #: short to cut, disabled with `cut_reason` beside it.
    cut_shown: bool = False
    cut_reason: str = ""


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
    # m-24976806: the parts of a cut that is still queued or running, where they will
    # land (the newest cut's first); once saved they are real tiles in the same place
    for job in reversed([j for j in jobs if j.kind == JOB_CUT]):
        if job.status not in (STATUS_QUEUED, STATUS_RUNNING):
            continue
        segments = tuple(getattr(job, "segments", ()) or ())
        total = len(segments)
        for n, (start_ms, end_ms) in enumerate(segments, start=1):
            items.append(
                GalleryItemVM(
                    key=f"cut-{job.id}-{n}",
                    state=STATE_PART_PENDING,
                    media_id="",
                    job_id=str(job.id),
                    media_type="video",
                    thumb_url="",
                    video_url="",
                    duration=duration_label(end_ms - start_ms),
                    duration_ms=0,
                    label=f"Parte {n} de {total}, en camino",
                    remove_label="",
                    note=f"Parte {n} de {total}: en camino…",
                    note_tone="info",
                    can_remove=False,
                    selectable=False,
                    cuttable=False,
                )
            )
    for m in sorted(media, key=lambda m: m.created_at, reverse=True):
        media_id = str(m.id)
        is_video = m.media_type == "video"
        if media_id in cutting:
            continue  # its card (above the tiles) shows it while it is being cut
        thumb_key = m.poster_key or ("" if is_video else m.object_key)
        items.append(
            GalleryItemVM(
                key=f"media-{media_id}",
                state=STATE_READY,
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
                note="",
                note_tone="neutral",
                can_remove=True,
                selectable=True,
                # a trim is a cut: one part of 3 s and anything left out (m-24976897)
                cuttable=is_video and can_cut(m.duration_ms),
                cut_shown=is_video,
                cut_reason=(
                    TOO_SHORT_TO_CUT_TEXT if is_video and not can_cut(m.duration_ms) else ""
                ),
            )
        )
    return items


# -- cuts (m-24976806) ----------------------------------------------------------------


def cut_title(parts: int) -> str:
    """«Cortando tu video en 2 partes…»; one kept part is a trim."""
    return "Recortando tu video…" if parts <= 1 else f"Cortando tu video en {parts} partes…"


def cut_done_text(parts: int) -> str:
    return f"Listo: tu video quedó en {parts} {'parte' if parts == 1 else 'partes'}."


def cut_steps(status: str) -> list[dict[str, str]]:
    """The three stages for `progress_panel`, the job's own status running."""
    order = [s for s, _ in CUT_STAGES]
    at = order.index(status) if status in order else len(order)
    return [
        {
            "title": stage_text(s),
            "status": "done" if i < at else ("running" if i == at else "pending"),
        }
        for i, s in enumerate(order)
    ]


def stage_text(status: str) -> str:
    """«Paso 2 de 3: Cortando las partes…» — the step counts even while a bar crawls
    (UX review)."""
    order = [s for s, _ in CUT_STAGES]
    i = order.index(status) if status in order else 0
    return f"Paso {i + 1} de {len(order)}: {CUT_STAGES[i][1]}"


def build_cut_cards(
    cuts: Sequence[CutJobLike],
    media: Sequence[MediaLike],
    url_for: Callable[[str, str], str],
) -> list[CutCardVM]:
    """The cuts of the last day (`list_cut_jobs`), newest first, as the cards above the
    tiles. The state decides which ones show (the active ones, and the ended ones this
    tab is waiting for)."""
    posters = {
        str(m.id): (m.poster_key or "") for m in media if m.media_type == "video" and m.poster_key
    }
    cards: list[CutCardVM] = []
    for job in sorted(cuts, key=lambda j: j.created_at, reverse=True):
        part_ids = [str(p) for p in (getattr(job, "part_ids", ()) or ())]
        parts = len(tuple(getattr(job, "segments", ()) or ())) or len(part_ids)
        source_id = str(job.source_media_id) if job.source_media_id else ""
        part_keys = [posters[p] for p in part_ids if p in posters]
        poster = posters.get(source_id) or (part_keys[0] if part_keys else "")
        if job.status == STATUS_DONE:
            phase, title, detail, stage = "done", cut_done_text(parts), "", ""
        elif job.status == STATUS_FAILED:
            phase, title, detail, stage = "failed", CUT_FAILED_NOTICE, "", ""
        else:
            phase, title = "active", cut_title(parts)
            detail = CUT_LEAVE_OK_ONE if parts <= 1 else CUT_LEAVE_OK
            stage = stage_text(job.status)
        cards.append(
            CutCardVM(
                job_id=str(job.id),
                source_id=source_id,
                phase=phase,
                parts=parts,
                title=title,
                detail=detail,
                stage_text=stage,
                steps=cut_steps(job.status) if phase == "active" else [],
                thumb_url=url_for(poster, "image") if poster else "",
                part_thumbs=[url_for(k, "image") for k in part_keys] if phase == "done" else [],
            )
        )
    return cards


def retry_spans(
    segments: Sequence[tuple[int, int]], duration_ms: int | None
) -> list[tuple[int, int, bool]]:
    """«Intentar de nuevo»: the whole timeline again — the kept spans, and the gaps
    between them as removed spans — `(start_ms, end_ms, keep)`, what `start_cut` takes.
    Without a known length the end is the last kept span's end."""
    spans: list[tuple[int, int, bool]] = []
    at = 0
    for start_ms, end_ms in sorted(segments):
        if start_ms > at:
            spans.append((at, start_ms, False))
        spans.append((start_ms, end_ms, True))
        at = end_ms
    if duration_ms is not None and duration_ms > at and spans:
        spans.append((at, duration_ms, False))
    return spans


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

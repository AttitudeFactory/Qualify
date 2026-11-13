"""«Subir foto o video» in «Nueva publicación», step 1 (m-25026384). Pure: no Reflex, no
I/O — what the planner's upload view takes, refuses and says.

The owner picks ONE file the planner can publish as it is: a photo (JPEG, PNG, HEIC,
WebP — stored as a JPEG of at most 8 MB, Meta's rule, by `upload_images`) or a video
(MP4, MOV — streamed to storage as it came). The file is stored as soon as it is
picked, so the view can show it; «Guardar y continuar» turns it into a piece
(`qualify_api.creative.own_upload.record_planner_upload`) and selects it.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import PurePath

from qualify_shared.objects.gate import MAX_MEDIA_BYTES

from .upload_images import PHOTO_MAX_BYTES, PHOTO_MAX_MB

#: The dropzone's id (one zone: the empty one and «Cambiar archivo» share it).
UPLOAD_ID = "planner_own_upload"

IMAGE = "image"
VIDEO = "video"

#: The heaviest video: `ObjectGate`'s single-PUT ceiling (300 MB). The video is never
#: read into memory — Starlette spools the request to disk past 1 MB and `put_object`
#: streams from that file — so the 768 MB app container does not bound it.
VIDEO_MAX_BYTES = MAX_MEDIA_BYTES
VIDEO_MAX_MB = VIDEO_MAX_BYTES // (1024 * 1024)
#: What the picker refuses before sending (react-dropzone has one size for all files;
#: a photo's own 50 MB is checked again on the server).
PICKER_MAX_BYTES = VIDEO_MAX_BYTES

_PHOTO_SUFFIXES = {".jpg": IMAGE, ".jpeg": IMAGE, ".png": IMAGE, ".heic": IMAGE}
_PHOTO_SUFFIXES |= {".heif": IMAGE, ".webp": IMAGE}
#: The stored content type of each video suffix (what the publisher sends to Meta).
VIDEO_CONTENT_TYPES = {".mp4": "video/mp4", ".mov": "video/quicktime"}

#: react-dropzone's `accept` (a MIME type or an extension matches).
ACCEPT: dict[str, list[str]] = {
    "image/jpeg": [".jpg", ".jpeg"],
    "image/png": [".png"],
    "image/webp": [".webp"],
    "image/heic": [".heic"],
    "image/heif": [".heif"],
    "video/mp4": [".mp4"],
    "video/quicktime": [".mov"],
}

# -- copy (qualify-copy-es) -------------------------------------------------------------

ADD_TILE_TITLE = "Subir foto o video"
ADD_TILE_HINT = "Desde tu teléfono"
ADD_TILE_LABEL = "Subir una foto o un video tuyo para programarlo"
VIEW_TITLE = "Sube tu foto o video"
VIEW_HINT = "Una foto o un video que hiciste tú. Después eliges cuándo sale."
BACK_TO_GRID = "Volver a elegir"
PICK_TITLE = "Toca para elegir una foto o un video"
#: Formats and sizes are said only when a file is refused (UX review m-25026384).
PICK_HINT = "Una foto o un video de tu teléfono."
PICK_DESKTOP_HINT = "Desde la computadora también puedes arrastrarlo aquí."
DROP_HINT = "Suelta aquí tu foto o video"
CHANGE_FILE = "Cambiar archivo"
CAPTION_LABEL = "Texto de la publicación (opcional)"
CAPTION_PLACEHOLDER = "Escribe lo que quieres que diga tu publicación."
SAVE = "Guardar y continuar"
SAVING = "Guardando…"
EMPTY_HINT = "Sube una foto o un video tuyo, o crea una publicación y apruébala."

UPLOADING_TEXT = "Subiendo tu archivo…"
PREPARING_TEXT = "Preparando tu archivo…"
CUT_CONNECTION_HINT = "Si se corta tu conexión, vuelve a elegir el archivo."

TOO_MANY_TEXT = "Elige un solo archivo: una foto o un video."
WRONG_TYPE_TEXT = (
    "Ese archivo no es una foto ni un video que podamos usar. Elige una foto JPG, PNG, "
    "HEIC o WebP, o un video MP4 o MOV."
)
VIDEO_TOO_HEAVY_TEXT = f"El video pesa más de {VIDEO_MAX_MB} MB. Elige uno más liviano."
PHOTO_TOO_HEAVY_TEXT = f"La foto pesa más de {PHOTO_MAX_MB} MB. Elige una más liviana."
PICKER_TOO_HEAVY_TEXT = f"El archivo pesa más de {VIDEO_MAX_MB} MB. Elige uno más liviano."
PHOTO_UNREADABLE_TEXT = "No pudimos abrir esa foto. Prueba con otra."
PHOTO_TOO_BIG_TEXT = (
    "Esta foto es demasiado grande para subirla. Elige otra o tómala con la cámara en modo normal."
)
PHOTO_BUSY_TEXT = "Estamos preparando otra foto. Vuelve a intentarlo en un momento."
UPLOAD_FAILED_TEXT = "No pudimos subir tu archivo. Vuelve a elegirlo."
NO_FILE_TEXT = "Primero elige una foto o un video."
SAVE_FAILED_TEXT = "No pudimos guardar tu publicación. Toca «Guardar y continuar» otra vez."
NOT_LISTED_TEXT = "Guardamos tu publicación, pero todavía no aparece en la lista."
#: Reads the candidates again (same file, same piece — never a second one).
SHOW_AGAIN = "Mostrarla otra vez"
#: A file picked while «Guardar y continuar» runs (the zone is disabled then; a browser
#: can still send one).
SAVING_WAIT_TEXT = "Espera a que terminemos de guardar tu publicación."
#: Ids the focus moves to when the view opens and closes (UX review m-25026384).
VIEW_TITLE_ID = "q-own-upload-title"
ADD_TILE_ID = "q-own-upload-card"


#: ISO base media (MP4, MOV): every file starts with a box whose type, at bytes 4-8, is
#: `ftyp` (QuickTime files from old cameras may open with `moov`/`mdat`/`wide`/`free`).
_ISO_BMFF_FIRST_BOXES = (b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip")


def looks_like_video(head: bytes) -> bool:
    """Whether a file's first bytes are an MP4/MOV container (its first box type at
    offset 4) — the name alone is not trusted."""
    return len(head) >= 8 and head[4:8] in _ISO_BMFF_FIRST_BOXES


def media_kind(name: str) -> str:
    """`IMAGE`, `VIDEO` or "" (not something the planner takes), by the file's suffix."""
    suffix = PurePath(name or "").suffix.lower()
    if suffix in VIDEO_CONTENT_TYPES:
        return VIDEO
    return _PHOTO_SUFFIXES.get(suffix, "")


def size_problem(kind: str, size: int) -> str:
    """The owner's sentence for a file over its kind's limit, or "" when it fits."""
    if kind == IMAGE and size > PHOTO_MAX_BYTES:
        return PHOTO_TOO_HEAVY_TEXT
    if kind == VIDEO and size > VIDEO_MAX_BYTES:
        return VIDEO_TOO_HEAVY_TEXT
    return ""


def rejection_text(rejected: Sequence[object] | None) -> str:
    """react-dropzone's `fileRejections` as one sentence: what to pick instead."""
    codes: set[str] = set()
    for row in rejected or ():
        errors = row.get("errors", []) if isinstance(row, dict) else []
        codes |= {str(e.get("code", "")) for e in errors or () if isinstance(e, dict)}
    if "too-many-files" in codes:
        return TOO_MANY_TEXT
    if "file-too-large" in codes:
        return PICKER_TOO_HEAVY_TEXT
    return WRONG_TYPE_TEXT if codes or rejected else ""


def progress_text(percent: int) -> str:
    """The line under the spinner: the bytes going up, then the server's own work."""
    if percent >= 100:
        return PREPARING_TEXT
    if percent <= 0:
        return UPLOADING_TEXT
    return f"{UPLOADING_TEXT} {percent} %"

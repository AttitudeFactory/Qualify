"""The clip's references on step 2, by category (UI-3, Deivid 2026-11-09) — pure.

«Referencias (opcional)» has three subsections — «Fotos», «Videos», «Audios» — each with
its tiles and its own drop zone filtered to its types (round 15: «en las fotos se suban
fotos»). This module holds what is not Reflex nor I/O: how many of each still fit, what
a full category says, what a file that does not fit or that the browser refused says,
and the tiles.

Limits are the brief's (`MediaInputs`): 9 photos, 3 videos — the reel's original counts
— and 3 audios. A file over them is SAID, never dropped silently.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

# -- kinds and limits -------------------------------------------------------------------

IMAGE = "image"
VIDEO = "video"
AUDIO = "audio"
KINDS = (IMAGE, VIDEO, AUDIO)
#: A zone of photos AND videos (the avatar's references, m-24985141): its refusals only.
MIXED = "mixed"

MAX_IMAGES = 9
MAX_VIDEOS = 3
MAX_AUDIOS = 3

# -- copy -------------------------------------------------------------------------------

TITLE = "Referencias (opcional)"
HINT = "Todo lo que el clip debe seguir: fotos, videos y música."
SECTION_TITLES: Mapping[str, str] = {IMAGE: "Fotos", VIDEO: "Videos", AUDIO: "Audios"}
SECTION_HINTS: Mapping[str, str] = {
    IMAGE: "Hasta 9: tu producto, tu lugar o un estilo a imitar.",
    VIDEO: "Hasta 3, de 2 a 15 s: su movimiento, cámara y ritmo. Sin personas reales.",
    AUDIO: "Hasta 3: la música o el sonido que acompaña el clip.",
}
#: Round 16 (Deivid: «centralizado en un botón»): ONE button opens the picker, its
#: categories first; each ends with its own upload button.
PICK_LABEL = "Elegir fotos, videos o audios"
PICK_SWITCH_LABEL = "Qué quieres agregar"
UPLOAD_LABELS: Mapping[str, str] = {
    IMAGE: "Subir fotos",
    VIDEO: "Subir videos",
    AUDIO: "Subir audios",
}
#: Audio has no source but the owner's own files.
AUDIO_SOURCE_NOTE = "Sube la música o el sonido que tengas guardado."
VIDEO_TAG = "Movimiento"
AUDIO_TAG = "Música"
#: What a zone takes, in the owner's words (a refused type is told this).
_TYPES_TEXT: Mapping[str, str] = {
    IMAGE: "aquí van fotos PNG, JPG o WEBP.",
    VIDEO: "aquí van videos MP4 o MOV.",
    AUDIO: "aquí van audios MP3 o WAV.",
    MIXED: "aquí van fotos PNG, JPG o WEBP, o videos MP4 o MOV.",
}
#: The drop zones' size cap (the server's own, `_CLIP_MAX_BYTES`), in the owner's words.
MAX_MB = 200
#: A file name from the browser is cut to this many characters («…» marks the cut).
NAME_MAX = 60
#: At most this many names are listed; the rest are counted («y 2 más»).
NAMES_SHOWN = 3


def room(kind: str, images: int, videos: int, audios: int) -> int:
    """How many more of `kind` the clip takes (the reel's original among the videos)."""
    if kind == IMAGE:
        return max(MAX_IMAGES - images, 0)
    if kind == VIDEO:
        return max(MAX_VIDEOS - videos, 0)
    if kind == AUDIO:
        return max(MAX_AUDIOS - audios, 0)
    return 0


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one}" if n == 1 else f"{n} {many}"


def _own_videos(held: int, reel_video: bool) -> str:
    own = max(held - 1, 0) if reel_video else held
    return "1 tuyo" if own == 1 else f"{own} tuyos"


def full_text(kind: str, *, held: int, reel_video: bool = False) -> str:
    """A full category, instead of its drop zone: «Ya tienes 9 fotos, el máximo. Quita
    una para cambiarla.» — "" while it still takes files."""
    if kind == IMAGE and held >= MAX_IMAGES:
        return f"Ya tienes {MAX_IMAGES} fotos, el máximo. Quita una para cambiarla."
    if kind == VIDEO and held >= MAX_VIDEOS:
        if reel_video:
            own = max(held - 1, 0)
            videos = "1 video tuyo" if own == 1 else f"{own} videos tuyos"
            return f"Ya tienes {videos}, el máximo con un reel. Quita uno para cambiarlo."
        return f"Ya tienes {MAX_VIDEOS} videos, el máximo. Quita uno para cambiarlo."
    if kind == AUDIO and held >= MAX_AUDIOS:
        return f"Ya tienes {MAX_AUDIOS} audios, el máximo. Quita uno para cambiarlo."
    return ""


def refused_text(kind: str, refused: int, *, held: int, reel_video: bool = False) -> str:
    """What files that did not fit say, and what to do: «No agregamos 1 video: ya
    tienes 2 tuyos, el máximo con un reel. Quita uno para cambiarlo.» — "" when nothing
    was refused. `held` is what the clip holds after the drop."""
    if refused <= 0:
        return ""
    if kind == IMAGE:
        return (
            f"No agregamos {_count(refused, 'foto', 'fotos')}: ya tienes {MAX_IMAGES}, el "
            "máximo. Quita una para cambiarla."
        )
    if kind == VIDEO:
        videos = _count(refused, "video", "videos")
        if reel_video:
            return (
                f"No agregamos {videos}: ya tienes {_own_videos(held, True)}, el máximo con "
                "un reel. Quita uno para cambiarlo."
            )
        return (
            f"No agregamos {videos}: ya tienes {MAX_VIDEOS}, el máximo. Quita uno para cambiarlo."
        )
    audios = _count(refused, "audio", "audios")
    return f"No agregamos {audios}: ya tienes {MAX_AUDIOS}, el máximo. Quita uno para cambiarlo."


def _short(name: str) -> str:
    return name if len(name) <= NAME_MAX else name[: NAME_MAX - 1].rstrip() + "…"


def _file_name(row: object) -> str:
    file = row.get("file") if isinstance(row, dict) else None
    if not isinstance(file, dict):
        return ""
    name = str(file.get("path") or file.get("name") or "")
    # react-dropzone prefixes a dropped file with «./»: only that prefix goes
    return _short(name.removeprefix("./"))


def _names(names: Sequence[str]) -> str:
    """«a.mp4», «a.mp4 y b.mp4», «a.mp4, b.mp4 y c.mp4», «a.mp4, b.mp4, c.mp4 y 2 más»."""
    shown = list(names[:NAMES_SHOWN])
    rest = len(names) - len(shown)
    if rest > 0:
        return ", ".join(shown) + f" y {rest} más"
    if len(shown) == 1:
        return shown[0]
    return ", ".join(shown[:-1]) + f" y {shown[-1]}"


def rejected_text(rejected: Sequence[object] | None, kind: str) -> str:
    """What a category's drop zone refused in the browser before any upload
    (react-dropzone's `fileRejections`: `{"file": …, "errors": [{"code": …}]}` each):
    the files over the size cap by name (cut, at most a few), the wrong types by count
    with what goes there — never dropped silently."""
    too_big: list[str] = []
    other = 0
    for row in rejected or ():
        errors = row.get("errors", []) if isinstance(row, dict) else []
        codes = {str(e.get("code", "")) for e in errors or () if isinstance(e, dict)}
        if "file-too-large" in codes:
            too_big.append(_file_name(row) or "un archivo")
        else:
            other += 1
    notes: list[str] = []
    if too_big:
        weighs = "pesa" if len(too_big) == 1 else "pesan"
        notes.append(f"No agregamos {_names(too_big)}: {weighs} más de {MAX_MB} MB.")
    if other:
        files = _count(other, "archivo", "archivos")
        notes.append(f"No agregamos {files}: {_TYPES_TEXT.get(kind, _TYPES_TEXT[IMAGE])}")
    return " ".join(notes)


# -- tiles ------------------------------------------------------------------------------


def tiles(
    images: Sequence[Mapping[str, str]],
    videos: Sequence[Mapping[str, str]],
    audios: Sequence[Mapping[str, str]],
) -> list[dict[str, str]]:
    """The references' tiles, strings only: images (with their role, «product» when
    unset, the same `clip_images[].role` the strip had), the owner's videos — never the
    reel's original (`source == "reel"`), which the clip's order shows — and the audios."""
    out: list[dict[str, str]] = []
    for item in images:
        out.append(
            {
                "kind": IMAGE,
                "key": str(item["key"]),
                "name": str(item.get("name") or ""),
                "role": str(item.get("role") or "product"),
            }
        )
    for item in videos:
        if item.get("source") == "reel":
            continue
        out.append(
            {
                "kind": VIDEO,
                "key": str(item["key"]),
                "name": str(item.get("name") or ""),
                "role": "",
            }
        )
    for item in audios:
        out.append(
            {
                "kind": AUDIO,
                "key": str(item["key"]),
                "name": str(item.get("name") or ""),
                "role": "",
            }
        )
    return out


def notes_line(notes: Mapping[str, str]) -> str:
    """Every category's note in one line, under the grid (so it stays when the picker
    closes): photos, then videos, then audios."""
    return " ".join(notes.get(kind, "") for kind in KINDS if notes.get(kind, ""))


__all__ = [
    "AUDIO",
    "AUDIO_TAG",
    "HINT",
    "IMAGE",
    "KINDS",
    "MAX_AUDIOS",
    "MAX_IMAGES",
    "MAX_VIDEOS",
    "MIXED",
    "AUDIO_SOURCE_NOTE",
    "PICK_LABEL",
    "PICK_SWITCH_LABEL",
    "SECTION_HINTS",
    "SECTION_TITLES",
    "TITLE",
    "UPLOAD_LABELS",
    "VIDEO",
    "VIDEO_TAG",
    "full_text",
    "held_text",
    "refused_text",
    "rejected_text",
    "room",
    "tiles",
    "notes_line",
]


def held_text(photos: int, videos: int, audios: int) -> str:
    """What the references hold, under the media drawer: «2 fotos y 1 video en tus
    referencias» (m-24985141); «Aún no tienes referencias» when empty."""
    parts = []
    for count, one, many in (
        (photos, "foto", "fotos"),
        (videos, "video", "videos"),
        (audios, "audio", "audios"),
    ):
        if count:
            parts.append(f"1 {one}" if count == 1 else f"{count} {many}")
    if not parts:
        return "Aún no tienes referencias"
    joined = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " y " + parts[-1]
    return f"{joined} en tus referencias"

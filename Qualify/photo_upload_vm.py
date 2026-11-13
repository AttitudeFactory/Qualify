"""What «Subir» in «Crear publicación» says while a photo goes up and when one is refused
(m-25017273). Pure: no Reflex, no I/O — the state passes what the browser reported."""

from __future__ import annotations

from collections.abc import Sequence

from .upload_images import PHOTO_MAX_MB

#: What the picker takes (react-dropzone: a MIME type or an extension matches). HEIC/HEIF
#: are the iPhone's photos: the server converts them to JPEG (`upload_images`).
PHOTO_ACCEPT: dict[str, list[str]] = {
    "image/jpeg": [".jpg", ".jpeg"],
    "image/png": [".png"],
    "image/webp": [".webp"],
    "image/heic": [".heic"],
    "image/heif": [".heif"],
}

TOO_HEAVY_TEXT = f"pesa más de {PHOTO_MAX_MB} MB. Elige una foto más liviana."
TOO_HEAVY_MANY_TEXT = f"pesan más de {PHOTO_MAX_MB} MB. Elige fotos más livianas."
WRONG_TYPE_TEXT = "no es una foto que podamos usar. Sube una foto JPG, PNG, WEBP o del iPhone."
WRONG_TYPE_MANY_TEXT = "no son fotos que podamos usar. Sube fotos JPG, PNG, WEBP o del iPhone."
TOO_MANY_TEXT = "Elegiste más fotos de las que caben aquí. Elige menos y vuelve a intentarlo."
#: A photo that arrived but cannot be opened (damaged, or another kind of file renamed).
UNREADABLE_TEXT = "No pudimos abrir «{name}». Prueba con otra foto."
#: A photo over the limit that reached the server anyway.
SERVER_TOO_HEAVY_TEXT = "«{name}» " + TOO_HEAVY_TEXT

UPLOADING_TEXT = "Subiendo tu foto…"
PREPARING_TEXT = "Preparando tu foto…"


def _file_name(row: object) -> str:
    if not isinstance(row, dict):
        return ""
    file = row.get("file")
    if isinstance(file, dict):
        return str(file.get("path") or file.get("name") or "").lstrip("./")
    return ""


def rejection_text(rejected: Sequence[object] | None) -> str:
    """react-dropzone's `fileRejections` (`{"file": {...}, "errors": [{"code": ...}]}`
    each) as one sentence for the owner: what was refused and what to do instead."""
    too_heavy: list[str] = []
    wrong: list[str] = []
    too_many = False
    for row in rejected or ():
        errors = row.get("errors", []) if isinstance(row, dict) else []
        codes = {str(e.get("code", "")) for e in errors or () if isinstance(e, dict)}
        name = _file_name(row) or "archivo"
        if "too-many-files" in codes:
            too_many = True
        elif "file-too-large" in codes:
            too_heavy.append(name)
        elif codes:
            wrong.append(name)
    if too_many:
        return TOO_MANY_TEXT
    notes: list[str] = []
    if too_heavy:
        text = TOO_HEAVY_TEXT if len(too_heavy) == 1 else TOO_HEAVY_MANY_TEXT
        notes.append(f"{_names(too_heavy)} {text}")
    if wrong:
        text = WRONG_TYPE_TEXT if len(wrong) == 1 else WRONG_TYPE_MANY_TEXT
        notes.append(f"{_names(wrong)} {text}")
    return " ".join(notes)


def _names(names: list[str]) -> str:
    quoted = [f"«{n}»" for n in names[:3]]
    if len(names) > 3:
        quoted.append(f"{len(names) - 3} más")
    if len(quoted) == 1:
        return quoted[0]
    return ", ".join(quoted[:-1]) + " y " + quoted[-1]


def progress_text(percent: int) -> str:
    """The line under the spinner: the bytes going up, then the server's own work."""
    if percent >= 100:
        return PREPARING_TEXT
    if percent <= 0:
        return UPLOADING_TEXT
    return f"Subiendo tu foto… {percent} %"

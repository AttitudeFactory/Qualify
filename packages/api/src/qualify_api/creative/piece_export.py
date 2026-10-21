"""A piece downloaded whole (m-24828908): its files and its words in one `.zip`.

What goes in: every media item of the draft in order (the video, the image, the
carousel's slides), a video's thumbnail, and `texto.txt` — title, hook, caption, CTA,
hashtags, the caption ready to paste, and the script and its shots when there are any.
What never goes in: the prompt, the model, the cost or any key — the operator downloads
what is published, not how it was made.

Pure: the caller reads the bytes (`read`) and decides where the archive goes.
"""

from __future__ import annotations

import io
import logging
import re
import unicodedata
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from qualify_creative.schemas import CopyPayload

from .service import DraftDetail, VariantRecord

logger = logging.getLogger(__name__)

#: The words of the piece inside the archive.
TEXT_NAME = "texto.txt"
#: How long a slug for a file name may be.
_SLUG_MAX = 60
_EXTENSIONS = ("mp4", "mov", "jpg", "png", "webp")


@dataclass(frozen=True)
class PieceFile:
    name: str
    data: bytes


def slug(text: str) -> str:
    """`text` as a file-name part: no accents, lower case, `-` between words."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")[:_SLUG_MAX].strip("-")


def archive_name(brand: str, title: str) -> str:
    """`<marca>-<titulo>.zip`, with whatever of the two exists; `pieza.zip` with neither."""
    parts = [part for part in (slug(brand), slug(title)) if part]
    return "-".join(parts or ["pieza"]) + ".zip"


def piece_copy(detail: DraftDetail) -> CopyPayload | None:
    """The words the piece shows: its selected variant, else the first — the operator's
    edit when there is one (`edited_copy` is the whole payload, as the screen shows it)."""
    variants = sorted(detail.variants, key=lambda v: v.ordinal)
    chosen: VariantRecord | None = next(
        (v for v in variants if v.id == detail.selected_variant_id), None
    ) or (variants[0] if variants else None)
    if chosen is None:
        return None
    return CopyPayload.model_validate(
        chosen.edited_copy if chosen.edited_copy is not None else chosen.copy
    )


def _section(title: str, body: str) -> str:
    return f"{title}\n{body.strip()}" if body.strip() else ""


def piece_text(*, title: str, kind_label: str, copy: CopyPayload | None) -> str:
    """`texto.txt`: the piece's words, each under its heading — plain text, in Spanish,
    the order they are pasted in. Empty sections are left out."""
    head = title.strip() or "Pieza"
    lines = [head, f"Tipo: {kind_label}" if kind_label else ""]
    if copy is None:
        return "\n".join(line for line in lines if line) + "\n"
    shots = "\n".join(
        f"{number}. ({shot.seconds} s) {shot.visual.strip()}"
        + (f"\n   Dice: {shot.line.strip()}" if shot.line.strip() else "")
        for number, shot in enumerate(copy.shots, 1)
    )
    ads = "\n".join(
        f"{label}: {value.strip()}"
        for label, value in (
            ("Texto principal", copy.ads_primary_text or ""),
            ("Título", copy.ads_headline or ""),
            ("Descripción", copy.ads_description or ""),
        )
        if value.strip()
    )
    sections = [
        "\n".join(line for line in lines if line),
        _section("GANCHO", copy.hook),
        _section("DESCRIPCIÓN", copy.caption),
        _section("LLAMADO A LA ACCIÓN", copy.cta),
        _section("HASHTAGS", " ".join(f"#{tag.lstrip('#')}" for tag in copy.hashtags)),
        _section("TEXTO LISTO PARA PEGAR", copy.rendered_caption()),
        _section("GUION", copy.script),
        _section("TOMAS", shots),
        _section("ANUNCIO", ads),
    ]
    return "\n\n".join(section for section in sections if section) + "\n"


def _extension(key: str, media_type: str) -> str:
    """The key's own extension when it is a known media one, else the medium's."""
    name = key.rsplit("/", 1)[-1]
    suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if suffix == "jpeg":
        return "jpg"
    if suffix in _EXTENSIONS:
        return suffix
    return "mp4" if media_type == "video" else "jpg"


def piece_files(
    detail: DraftDetail, read: Callable[[str], bytes], *, stem: str = "pieza"
) -> tuple[list[PieceFile], list[str]]:
    """The draft's files in order — `<stem>-1.mp4`, `<stem>-2.jpg`… and a video's
    `<stem>-1-miniatura.jpg` — plus the names of those that could not be read (an object
    gone or R2 down: the rest of the piece still downloads, and `texto.txt` says so)."""
    files: list[PieceFile] = []
    missing: list[str] = []
    for number, item in enumerate(sorted(detail.media, key=lambda m: m.position), 1):
        params: Mapping[str, object] = item.params or {}
        key = item.object_key or item.media_url or ""
        if not key:
            continue
        wanted = [(key, f"{stem}-{number}.{_extension(key, item.media_type)}")]
        thumbnail = params.get("thumbnail_key")
        if item.media_type == "video" and isinstance(thumbnail, str) and thumbnail:
            wanted.append((thumbnail, f"{stem}-{number}-miniatura.jpg"))
        for source, name in wanted:
            try:
                files.append(PieceFile(name, read(source)))
            except Exception as exc:  # noqa: BLE001 — one missing file never blocks the rest
                logger.warning("piece file not read (%s): %s", name, type(exc).__name__)
                missing.append(name)
    return files, missing


def build_archive(files: list[PieceFile], text: str, missing: Sequence[str] = ()) -> bytes:
    """The `.zip`: the files and `texto.txt` (which lists, at its end, any file that
    could not be included)."""
    if missing:
        text = text + "\nNo se pudieron incluir: " + ", ".join(missing) + "\n"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(TEXT_NAME, text.encode("utf-8"))
        for item in files:
            # media is already compressed: storing it is as small and much faster
            archive.writestr(item.name, item.data, compress_type=zipfile.ZIP_STORED)
    return buffer.getvalue()

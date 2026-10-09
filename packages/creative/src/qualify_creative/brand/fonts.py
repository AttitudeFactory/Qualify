"""What a font FILE says about itself (§ request 2026-10-05, Tipografía: "qué pasa si le
subes un archivo y la fuente es open source, la busca y rellena el input").

- `family_name` reads the family out of the file's own `name` table — no font library,
  just the OpenType container format: TTF / OTF / TTC directly, WOFF after inflating its
  tables with zlib. WOFF2 tables are Brotli-compressed and no Brotli decoder is installed,
  so a WOFF2 (or anything unreadable) falls back to the file NAME ("OpenSans-Bold.woff2"
  → "Open Sans") — a guess, which is why the field stays editable.
- `on_google_fonts` asks Google Fonts' CSS API whether that family exists there: it
  answers 200 for a family it serves and 400 for one it does not. A family on Google Fonts
  is open source (every family it serves is under the OFL or Apache licence).

Pure stdlib and side-effect free except `on_google_fonts`, whose fetch is injectable.
"""

from __future__ import annotations

import re
import struct
import urllib.error
import urllib.parse
import urllib.request
import zlib
from collections.abc import Callable
from pathlib import PurePath

GOOGLE_FONTS_CSS = "https://fonts.googleapis.com/css2"
#: A Google Fonts check is a nicety on top of the upload: it must answer fast or not at all.
CHECK_TIMEOUT_SECONDS = 5.0
#: The largest font file an upload accepts. A static weight is tens to hundreds of KB and a
#: variable CJK face reaches ~20 MB; anything above is refused before it is read.
MAX_FONT_BYTES = 20 * 1024 * 1024
#: A `name` table is a few dozen strings — kilobytes. A WOFF declaring more is never
#: inflated: the length comes from the (user-supplied) file itself, and a zlib bomb
#: would otherwise expand to gigabytes inside the app process.
_MAX_INFLATED_TABLE_BYTES = 1024 * 1024

_TYPOGRAPHIC_FAMILY = 16  # "Montserrat" for every weight — preferred
_FAMILY = 1  # "Montserrat SemiBold" style families for non-RIBBI weights
_WINDOWS, _MAC = 3, 1
_ENGLISH_US = 0x409

#: Words a file name carries for the style, not the family ("Montserrat-SemiBoldItalic"
#: → "Semi", "Bold", "Italic"), lower-cased. Width words (Condensed, Expanded) are NOT
#: here: on Google Fonts they are part of the family ("Roboto Condensed").
_STYLE_WORDS = frozenset(
    {
        "variablefont", "variable", "font", "vf", "wght", "ital", "opsz", "wdth",
        "thin", "hairline", "light", "book", "regular", "normal", "roman", "medium",
        "bold", "black", "heavy", "italic", "oblique",
        "semi", "demi", "extra", "ultra",
    }
)  # fmt: skip


def family_name(data: bytes, filename: str = "") -> str:
    """The family the font file declares, or one guessed from `filename`, or ""."""
    try:
        found = _family_from_sfnt(data)
    except (struct.error, zlib.error, ValueError, IndexError):
        found = ""
    return found or family_from_filename(filename)


def family_from_filename(filename: str) -> str:
    """ "OpenSans-SemiBoldItalic.ttf" → "Open Sans", "roboto_condensed-bold.woff2" →
    "Roboto Condensed", "Inter[wght].ttf" → "Inter": the name's words (CamelCase split)
    minus the style words and weights ("400") at its end — a short number stays, it is
    part of the family ("Baloo2-Bold" → "Baloo 2")."""
    stem = re.sub(r"\[.*?\]", "", PurePath(filename).stem)  # a variable font's axes
    words: list[str] = []
    for token in re.split(r"[-_\s.]+", stem):
        words.extend(_WORD_BREAK.sub(" ", token).split())
    while len(words) > 1 and (words[-1].lower() in _STYLE_WORDS or _is_weight(words[-1])):
        words.pop()
    return " ".join(w[:1].upper() + w[1:] for w in words)


#: Where a name token splits into words: "OpenSans" → "Open Sans", "Light400" → "Light 400".
_WORD_BREAK = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Za-z])(?=[0-9])")


def _is_weight(word: str) -> bool:
    """A CSS weight (100…900) in a file name, not a number that belongs to the family."""
    return word.isdigit() and len(word) == 3


def on_google_fonts(
    family: str,
    *,
    fetch: Callable[[str], int] | None = None,
) -> bool | None:
    """True when Google Fonts serves `family` (so it is open source), False when it does
    not, None when it could not be asked (offline, timeout) — unknown is not "no"."""
    clean = " ".join(re.sub(r'["\\{};<>]', "", family).split())
    if not clean:
        return False
    url = f"{GOOGLE_FONTS_CSS}?family={urllib.parse.quote_plus(clean)}"
    try:
        status = (fetch or _status_of)(url)
    except (OSError, ValueError):
        return None
    if status == 200:
        return True
    if status == 400:
        return False
    return None


def _status_of(url: str) -> int:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=CHECK_TIMEOUT_SECONDS) as response:  # noqa: S310 — fixed https host
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


# --------------------------------------------------------------------------------------
# the OpenType container
# --------------------------------------------------------------------------------------


def _family_from_sfnt(data: bytes) -> str:
    tag = data[:4]
    if tag == b"wOFF":
        name_table = _woff_table(data, b"name")
    elif tag == b"ttcf":  # a collection: the first font's directory
        (offset,) = struct.unpack(">I", data[12:16])
        name_table = _sfnt_table(data, b"name", offset)
    elif tag in (b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1"):
        name_table = _sfnt_table(data, b"name", 0)
    else:  # WOFF2 (Brotli) or not a font at all
        return ""
    return _family_in_name_table(name_table) if name_table else ""


def _sfnt_table(data: bytes, wanted: bytes, start: int) -> bytes:
    (count,) = struct.unpack(">H", data[start + 4 : start + 6])
    for i in range(count):
        entry = start + 12 + 16 * i
        tag, _checksum, offset, length = struct.unpack(">4sIII", data[entry : entry + 16])
        if tag == wanted:
            return data[offset : offset + length]
    return b""


def _woff_table(data: bytes, wanted: bytes) -> bytes:
    (count,) = struct.unpack(">H", data[12:14])
    for i in range(count):
        entry = 44 + 20 * i
        tag, offset, comp_length, orig_length, _checksum = struct.unpack(
            ">4sIIII", data[entry : entry + 20]
        )
        if tag == wanted:
            raw = data[offset : offset + comp_length]
            if comp_length == orig_length:
                return raw
            if orig_length > _MAX_INFLATED_TABLE_BYTES:
                return b""
            # Bounded: never more than the declared length, whatever the stream holds.
            table = zlib.decompressobj().decompress(raw, orig_length)
            return table if len(table) == orig_length else b""
    return b""


def _family_in_name_table(table: bytes) -> str:
    _format, count, strings = struct.unpack(">HHH", table[:6])
    found: dict[tuple[int, int], str] = {}
    for i in range(count):
        record = 6 + 12 * i
        platform, _encoding, language, name_id, length, offset = struct.unpack(
            ">HHHHHH", table[record : record + 12]
        )
        if name_id not in (_TYPOGRAPHIC_FAMILY, _FAMILY):
            continue
        raw = table[strings + offset : strings + offset + length]
        if platform == _WINDOWS or platform == 0:
            text = raw.decode("utf-16-be", errors="ignore")
            rank = 0 if language == _ENGLISH_US else 1
        elif platform == _MAC:
            text = raw.decode("mac_roman", errors="ignore")
            rank = 2
        else:
            continue
        text = " ".join(text.split())
        if text:
            found.setdefault((name_id, rank), text)
    for name_id in (_TYPOGRAPHIC_FAMILY, _FAMILY):
        for rank in (0, 1, 2):
            if (name_id, rank) in found:
                return found[(name_id, rank)]
    return ""

"""Blank bands at the top or bottom of a generated photograph (draft 97f35052, 2026-11-03).

Seedream sometimes answers «keep the bottom fifth calm» with a flat, empty band across the
whole width — a letterbox, not a photograph. The gallery's scrim then darkened that white
band into a grey gradient and the slide looked «cut». `fill_blank_bands` finds such a band
(uniform rows, and a hard edge across nearly the whole width where the photograph starts),
crops it away and fills the original frame again by covering it with what is left. A
studio photo on a white sweep is not a band: its floor fades into the subject and the row
above it is mostly still background, so it is kept as it is.

Deterministic, offline, Pillow only. Bytes with no band come back unchanged (the same
object), so a scene without the defect is never re-encoded."""

from __future__ import annotations

import io
import logging

from PIL import Image

log = logging.getLogger(__name__)

#: Columns sampled per row: enough to see an edge, cheap on a 2 MP image.
_SAMPLE_WIDTH = 96
#: A row is flat when its sampled pixels span at most this many grey levels…
_FLAT_SPREAD = 14
#: …and its mean stays this close to the band's first row (a band is one tone).
_TONE_DRIFT = 8
#: The photograph's first row differs from the band by this much…
_EDGE_DELTA = 24
#: …in at least this share of the columns: the band ends across the whole width.
_EDGE_SHARE = 0.85
#: Only a band of at least this share of the height is trimmed (JPEG edge noise is not)…
MIN_BAND_SHARE = 0.03
#: …and never more than this: a mostly flat image is a design choice, not a defect.
MAX_BAND_SHARE = 0.35


def _rows(gray: Image.Image) -> list[bytes]:
    width, height = gray.size
    data = gray.tobytes()
    return [data[y * width : (y + 1) * width] for y in range(height)]


def _band(rows: list[bytes], order: range) -> int:
    """How many rows, walked in `order` from an edge, form a blank band with a hard edge;
    0 when there is none."""
    first = rows[order[0]]
    if max(first) - min(first) > _FLAT_SPREAD:
        return 0
    tone = sum(first) / len(first)
    count = 0
    for y in order:
        row = rows[y]
        if max(row) - min(row) > _FLAT_SPREAD or abs(sum(row) / len(row) - tone) > _TONE_DRIFT:
            break
        count += 1
    if count == len(order):
        return 0  # the whole image is one tone
    # the photograph's first rows (skip one: a JPEG blurs the boundary row)
    inside = [order[i] for i in (count, count + 1, count + 2) if i < len(order)]
    edge = max(sum(abs(v - tone) > _EDGE_DELTA for v in rows[y]) / len(rows[y]) for y in inside)
    return count if edge >= _EDGE_SHARE else 0


def blank_bands(data: bytes) -> tuple[int, int]:
    """(top, bottom): the rows of the blank band at each edge of the image, in the image's
    own pixels — (0, 0) when it has none worth trimming."""
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception:  # not an image we can read: nothing to trim, the caller decides
        return 0, 0
    width, height = image.size
    if height < 32 or width < 32:
        return 0, 0
    gray = image.convert("L").resize((_SAMPLE_WIDTH, height), Image.BILINEAR)
    rows = _rows(gray)
    top = _band(rows, range(0, height))
    bottom = _band(rows, range(height - 1, -1, -1))
    minimum, maximum = round(height * MIN_BAND_SHARE), round(height * MAX_BAND_SHARE)
    top = top if minimum <= top <= maximum else 0
    bottom = bottom if minimum <= bottom <= maximum else 0
    if top + bottom > maximum:
        return 0, 0
    return top, bottom


def fill_blank_bands(data: bytes) -> bytes:
    """The image without its blank top/bottom bands, covering its original frame again
    (same size, centred crop of the sides); `data` itself when it has none."""
    top, bottom = blank_bands(data)
    if not top and not bottom:
        return data
    image = Image.open(io.BytesIO(data))
    image.load()
    width, height = image.size
    kept = image.convert("RGB").crop((0, top, width, height - bottom))
    scale = max(width / kept.width, height / kept.height)
    resized = kept.resize(
        (max(width, round(kept.width * scale)), max(height, round(kept.height * scale))),
        Image.LANCZOS,
    )
    left = (resized.width - width) // 2
    upper = (resized.height - height) // 2
    filled = resized.crop((left, upper, left + width, upper + height))
    log.info(
        "generated scene: blank bands trimmed top=%d bottom=%d of %d rows", top, bottom, height
    )
    out = io.BytesIO()
    filled.save(out, format="PNG")
    return out.getvalue()

"""What a source of the LOCAL video assembly may be (m-25042483, founder's decision
«Bajarlos a 4K 8 bits»): at most 3840×2160 in either orientation (long side ≤ 3840,
short side ≤ 2160) and 8 bits per component. A bigger one (5K…) or a 10-bit one (an
iPhone's HEVC 10-bit, HDR) takes ~490–503 MiB to prepare inside the creative worker's
768m (`docs/armado-local-medicion.md`), so the `media-worker` brings it down first
(`local_normalize`) and the assembly only ever decodes the normalized copy.

`read_header` reads the container's header only — the stream's stored size, its pixel
format and the display rotation the container declares — and NEVER decodes a frame: a
source that may need normalizing is never decoded by the creative worker.

`needs_normalizing` is the pure rule. The display rotation does not change it: the limit
is on the long and the short side, whatever way up the picture is shown.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

#: The largest source the local assembly decodes: (long side, short side).
MAX_LOCAL_SOURCE: tuple[int, int] = (3840, 2160)
#: Bits per component the local assembly decodes.
MAX_LOCAL_BITS = 8
#: Version of this rule — provenance of a stretch's check.
SOURCE_LIMITS_VERSION = "local-source-limits-v1"

_TRAILING_DEPTH = re.compile(r"(?:p|f)?(\d{2})(?:le|be)$")
_SEMIPLANAR_DEPTH = re.compile(r"^p0(\d{2})")


@dataclass(frozen=True)
class SourceHeader:
    """A video's header: its stored size, pixel format, declared display rotation
    (degrees, 0 when none) and length in seconds when the header says it (else None)."""

    width: int
    height: int
    pix_fmt: str | None
    rotation: int = 0
    duration_s: float | None = None

    @property
    def bits(self) -> int | None:
        return pix_fmt_bits(self.pix_fmt)

    def needs_normalizing(self) -> bool:
        return needs_normalizing(self.width, self.height, self.rotation, self.pix_fmt)

    def to_dict(self) -> dict[str, object]:
        return {
            "width": self.width,
            "height": self.height,
            "pix_fmt": self.pix_fmt,
            "bits": self.bits,
            "rotation": self.rotation,
        }


def pix_fmt_bits(pix_fmt: str | None) -> int | None:
    """The largest bits per component of `pix_fmt` (`yuv420p` 8, `yuv420p10le` 10,
    `p010le` 10), or None when it is unknown. PyAV's own table when it has the format,
    else read off the name (FFmpeg's naming)."""
    if not pix_fmt:
        return None
    try:
        import av  # noqa: PLC0415 — lazy, like every PyAV use in this package

        components = av.VideoFormat(pix_fmt).components
        bits = max((int(c.bits) for c in components), default=0)
        if bits:
            return bits
    except Exception:  # noqa: BLE001 — an unknown name: read it off the name
        pass
    for pattern in (_SEMIPLANAR_DEPTH, _TRAILING_DEPTH):
        found = pattern.search(pix_fmt)
        if found:
            return int(found.group(1))
    return 8


def needs_normalizing(width: int, height: int, rotation: int, pix_fmt: str | None) -> bool:
    """Whether a video source must be normalized before the local assembly decodes it:
    larger than `MAX_LOCAL_SOURCE` in either orientation, or more than 8 bits per
    component — or a pixel format the header does not name (we cannot prove it is 8
    bits; normalizing costs nothing but time). `rotation` is accepted for the record:
    turning the picture does not change its long and short sides. A size the header
    does not give (0) is not judged here: the assembly refuses it as unreadable."""
    del rotation  # the long and short sides are the same whichever way it is shown
    if width <= 0 or height <= 0:
        return False
    long_side, short_side = max(width, height), min(width, height)
    if long_side > MAX_LOCAL_SOURCE[0] or short_side > MAX_LOCAL_SOURCE[1]:
        return True
    bits = pix_fmt_bits(pix_fmt)
    return bits is None or bits > MAX_LOCAL_BITS


def read_header(source: str | os.PathLike[str]) -> SourceHeader:
    """The header of `source`'s first video stream — no frame is decoded. Raises
    `VideoSourceError("unreadable")` (or `NoVideoStream`) like every reader here."""
    from qualify_creative.video._source import open_video  # noqa: PLC0415

    with open_video(source) as (container, stream):
        context = stream.codec_context
        width = int(context.width or 0)
        height = int(context.height or 0)
        pix_fmt = getattr(context, "pix_fmt", None) or None
        rotation = _declared_rotation(stream)
        duration_s = _header_duration(container, stream)
    return SourceHeader(
        width=width, height=height, pix_fmt=pix_fmt, rotation=rotation, duration_s=duration_s
    )


def _declared_rotation(stream: object) -> int:
    """The display rotation the container declares (the old `rotate` tag), 0 when none or
    unreadable — for the record only; the rule does not depend on it."""
    metadata = getattr(stream, "metadata", None) or {}
    try:
        return int(float(metadata.get("rotate", 0))) % 360
    except (TypeError, ValueError):
        return 0


def _header_duration(container: object, stream: object) -> float | None:
    duration = getattr(stream, "duration", None)
    time_base = getattr(stream, "time_base", None)
    if duration is not None and time_base is not None:
        seconds = float(duration * time_base)
        if seconds > 0:
            return round(seconds, 3)
    whole = getattr(container, "duration", None)  # microseconds (AV_TIME_BASE)
    if whole:
        return round(float(whole) / 1_000_000, 3)
    return None


__all__ = [
    "MAX_LOCAL_BITS",
    "MAX_LOCAL_SOURCE",
    "SOURCE_LIMITS_VERSION",
    "SourceHeader",
    "needs_normalizing",
    "pix_fmt_bits",
    "read_header",
]

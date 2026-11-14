"""«Preparar» an owner's video (EF-03, ADR 50): turn it upright, crop it to vertical and
keep the stretches they want — what the manual reference did with `transpose=1`,
`crop=ih*9/16:ih` and a fixed colour range, for footage that arrives lying down without
metadata (a GoPro), in 16:9, or with seconds to spare.

Three layers, so the editor's live preview (ED-01/ED-03) can reuse the same arithmetic:

- `plan_prepare` / `plan_segments` — PURE and cheap: from the stored size, the display
  rotation and a `PrepareSegment` (the stretch and the turn asked for), the operations
  (total turn, centred 9:16 crop, scale size), the final size and the warnings. Stretch
  errors come from here, with a machine-readable `reason` and the stretch's `index`. They
  open nothing; `read_source` is the separate helper that reads what they need (the first
  frame through `probe` without the end, the header's duration).
- `apply_prepare` — applies one plan to its source and encodes it: streamed frame by frame
  (one decoded frame held at a time), decoder, encoder and scaler bounded to
  `PREPARE_THREADS` threads, H.264 `yuv420p` limited range with BT.709 tagged on the stream
  (range, matrix, primaries, transfer), no audio, `+faststart`; written next to `out` and
  renamed on success, so a failure leaves no `out` behind and never touches an older one.
- `prepared_frame` — one frame of the same plan at a given second, as an RGB array, for a
  thumbnail.

The contract with «Cortar» (ED-03, `epica-efectos-propuesta-editor.md` §2.5): every stretch
arrives as the JSON dict `{"key", "start_s", "end_s", "speed", "rotate"}`, several per video
in an ordered tuple. `PrepareSegment.from_dict` takes that dict as it is and `to_dict` gives
it back unchanged (no rounding: the slider's 0.5 s steps are exact binary floats, and a time
off the 0.5 s grid is ACCEPTED as sent — the grid is the screen's rule, not the engine's).
«Usar el video entero» is `start_s=0, end_s=<duration>`; an end up to `END_SLACK_SECONDS`
past the source's own end (the browser's duration, rounded up to the slider's step) is cut at
the end, not refused. `rotate` is the turn asked for, in degrees CLOCKWISE (what CSS
`rotate()` shows in the preview; «Girar» adds a quarter turn per tap): only 0/90/180/270 —
a 360 is REFUSED, not wrapped, so every stored stretch has one spelling and the round trip
stays exact (the screen wraps its own taps). `speed` only travels here: EF-04 applies it.

Colour: every decoded frame is read to RGB with ITS OWN range and matrix (a `yuvj420p` /
full-range source is converted, not reinterpreted — read as limited, a pure red comes out
pinkish-magenta), and written to `yuv420p` limited with the BT.709 matrix explicitly — never
swscale's defaults (unspecified = BT.601). An untagged source is read as BT.709 when it is
HD and BT.601 below, as players do. HDR (BT.2020 PQ/HLG) is converted with its matrix but
WITHOUT tone mapping: it comes out washed out, not refused.

Every piece of a plan (`PrepareSegment`, `CropRect`, `PrepareWarning`, `PreparePlan`) is a
frozen dataclass with `to_dict`/`from_dict`. Pure: no network, no database; PyAV and numpy
are imported lazily like the rest of this package.
"""

from __future__ import annotations

import math
import os
import secrets
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from qualify_creative.video._source import (
    Timeline,
    VideoSourceError,
    _header_seconds,
    frame_seconds,
    open_video,
    probe,
)
from qualify_creative.video.cut import WINDOW_X264, _decode_from
from qualify_creative.video.upright import turn_pixels

#: The vertical frame every prepared video fits into, never grown past it.
TARGET_SIZE: tuple[int, int] = (1080, 1920)
#: The crop's aspect, width over height.
TARGET_ASPECT = Fraction(9, 16)
#: The turns that can be asked for, in degrees CLOCKWISE (the manual `transpose=1` is 90).
ALLOWED_ROTATIONS: tuple[int, ...] = (0, 90, 180, 270)
#: A stretch shorter than this is refused (`segment_too_short`).
MIN_SEGMENT_SECONDS = 1.0
#: How far past the source's end a stretch may end and still be cut at the end: «Cortar»'s
#: step (0.5 s) — the browser's duration rounded up to it must not refuse the whole video.
END_SLACK_SECONDS = 0.5
#: Below this crop width (before scaling) the plan carries a `low_resolution` warning.
LOW_RESOLUTION_WIDTH = 720
#: Codec threads for the decoder, the encoder and the scaler: frame threading keeps a whole
#: frame in flight per thread, which at 4K is what the creative worker cannot spare
#: (`join._bound`, `normalize.FFMPEG_THREADS`). Measured 2026-11-13 on Windows (8 cores,
#: `deploy/measure/prepare_memory.py`, 15 s of a 4K 30 fps H.264 to 1080×1920): peak
#: working set 277 MiB (290 MB) unturned, 276 MiB with `rotate=90` — of which the 4K
#: decoder plus the crop/turn ≈ 115 MiB and x264 at 1080×1920 ≈ 160 MiB; the thread count
#: (1, 2 or 4) and the lookahead (0-10) moved it by under 3 MiB. FFmpeg's automatic
#: threading on the first decode alone cost 224 MiB, hence `_bound` before every probe.
PREPARE_THREADS = 2
#: x264 for the prepared stretch: it is re-encoded once more downstream at most; a short
#: lookahead, since x264 keeps that many whole frames queued (`join.JOIN_X264`).
PREPARE_X264 = {**WINDOW_X264, "rc-lookahead": "10"}
#: Version of this recipe — recorded with what is made from it (provenance).
PREPARE_VERSION = "prepare-v1"
#: Slack for float noise when comparing a stretch with the source's length.
_EPSILON = 1e-3

#: AVColorSpace codes → the matrix swscale reads them with.
_MATRICES = {1: "ITU709", 4: "FCC", 5: "ITU601", 6: "ITU601", 7: "SMPTE240M", 9: "BT2020"}
#: AVCOL_* code 1 is BT.709 for range-independent tags (primaries, transfer, matrix).
_BT709 = 1
_LIMITED_RANGE = 1
_FULL_RANGE = 2


class PrepareRejected(VideoSourceError):
    """The preparation cannot be done as asked. `reason` is a stable code:
    `bad_segment` (a stretch dict that is not one), `rotation_unsupported` (a turn other
    than 0/90/180/270), `segment_too_short`, `segment_out_of_range`, `unknown_key` (no
    source for the stretch's key), `time_out_of_range` (`prepared_frame`), `plan_mismatch`
    (the plan was made for another source), `encode_failed` — plus `VideoSourceError`'s
    (`unreadable`, `no_video`). `index`: the position of the stretch that failed in the
    tuple it came in (0-based), None when no tuple was involved."""

    def __init__(self, reason: str, message: str, index: int | None = None) -> None:
        if index is not None:
            message = f"segment {index}: {message}"
        super().__init__(reason, message)
        self.index = index


# EF-02: `SourceSegment` (the `segments` field of the brief, `schemas.py`) is EF-02's; when
# it lands, this becomes that type (or is built from it) — same five fields, same JSON.
@dataclass(frozen=True)
class PrepareSegment:
    """One stretch as «Cortar» (ED-03) sends it: the file's `key`, `start_s`/`end_s` in
    seconds from the source's first decoded frame (the timeline `shots` and `cut` use),
    `speed` (EF-04's, carried untouched) and `rotate`, the turn asked for in degrees
    clockwise. Holds what was sent; `plan_prepare` validates it against the source."""

    key: str
    start_s: float
    end_s: float
    speed: float = 1.0
    rotate: int = 0

    @property
    def seconds(self) -> float:
        return self.end_s - self.start_s

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "start_s": self.start_s,
            "end_s": self.end_s,
            "speed": self.speed,
            "rotate": self.rotate,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], *, index: int | None = None) -> PrepareSegment:
        """The stretch in `data` (the JSON dict, as is); `bad_segment` when a field is
        missing or not of its type, a time or the speed is not finite (NaN or infinity —
        JSONB takes neither) or the speed is not above 0; `rotation_unsupported` for a turn
        outside 0/90/180/270."""
        try:
            key = data["key"]
            start, end = data["start_s"], data["end_s"]
            speed = data.get("speed", 1.0)
            rotate = data.get("rotate", 0)
        except (KeyError, TypeError) as error:
            raise PrepareRejected("bad_segment", f"not a stretch: {data!r}", index) from error
        if not isinstance(key, str) or not all(_is_number(v) for v in (start, end, speed)):
            raise PrepareRejected("bad_segment", f"not a stretch: {data!r}", index)
        if not all(math.isfinite(v) for v in (start, end, speed)) or speed <= 0:
            raise PrepareRejected(
                "bad_segment", f"times and speed must be finite, speed above 0: {data!r}", index
            )
        if (
            isinstance(rotate, bool)
            or not isinstance(rotate, int)
            or rotate not in (ALLOWED_ROTATIONS)
        ):
            raise PrepareRejected(
                "rotation_unsupported", f"a {rotate!r}° turn; only 0, 90, 180 or 270", index
            )
        return cls(
            key=key, start_s=float(start), end_s=float(end), speed=float(speed), rotate=rotate
        )


def segments_from_list(items: Sequence[Mapping[str, Any]]) -> tuple[PrepareSegment, ...]:
    """The ordered stretches of a JSON list, each error naming its stretch's `index`."""
    return tuple(PrepareSegment.from_dict(item, index=i) for i, item in enumerate(items))


@dataclass(frozen=True)
class CropRect:
    """The crop, in pixels of the picture already turned upright (after the total turn).
    In a `PreparePlan` it is exactly the window `apply_prepare` keeps: the crop made on the
    stored picture (`_stored_crop`) is this rectangle carried back through the turn, so a
    preview may draw it as is."""

    x: int
    y: int
    width: int
    height: int

    def to_dict(self) -> dict[str, Any]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CropRect:
        return cls(
            x=int(data["x"]), y=int(data["y"]), width=int(data["width"]), height=int(data["height"])
        )


@dataclass(frozen=True)
class PrepareWarning:
    """Something the owner should know, not an error. `code`: `low_resolution` (`width` is
    the crop's real width before scaling — what «Tu video quedaría de 342 × 608» shows)."""

    code: str
    width: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "width": self.width}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PrepareWarning:
        width = data.get("width")
        return cls(code=str(data["code"]), width=None if width is None else int(width))


@dataclass(frozen=True)
class SourceInfo:
    """What `plan_prepare` needs from a file, read cheaply by `read_source`: the stored
    picture size, its display rotation (degrees counter-clockwise, `_source.frame_rotation`)
    and its length in seconds from the first frame (the header's, or the decoded one when it
    has none)."""

    width: int
    height: int
    rotation: int
    duration_s: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "rotation": self.rotation,
            "duration_s": self.duration_s,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SourceInfo:
        return cls(
            width=int(data["width"]),
            height=int(data["height"]),
            rotation=int(data["rotation"]),
            duration_s=float(data["duration_s"]),
        )


@dataclass(frozen=True)
class PreparePlan:
    """Every operation of one stretch's preparation, computed by `plan_prepare`, in the
    order they run: keep `[start_s, end_s)` (the stretch as asked, cut at the source's end),
    turn the stored picture `turn` degrees COUNTER-clockwise (display rotation minus the
    turn asked for), crop `crop` out of the turned picture, scale it to `width`×`height`.
    `segment` is the stretch exactly as it was sent; `source` pins the plan to the file it
    was made for."""

    segment: PrepareSegment
    source: SourceInfo
    start_s: float
    end_s: float
    turn: int
    crop: CropRect
    width: int
    height: int
    warnings: tuple[PrepareWarning, ...] = ()
    version: str = PREPARE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "segment": self.segment.to_dict(),
            "source": self.source.to_dict(),
            "start_s": self.start_s,
            "end_s": self.end_s,
            "turn": self.turn,
            "crop": self.crop.to_dict(),
            "width": self.width,
            "height": self.height,
            "warnings": [warning.to_dict() for warning in self.warnings],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PreparePlan:
        return cls(
            segment=PrepareSegment.from_dict(data["segment"]),
            source=SourceInfo.from_dict(data["source"]),
            start_s=float(data["start_s"]),
            end_s=float(data["end_s"]),
            turn=int(data["turn"]),
            crop=CropRect.from_dict(data["crop"]),
            width=int(data["width"]),
            height=int(data["height"]),
            warnings=tuple(PrepareWarning.from_dict(item) for item in data.get("warnings", ())),
            version=str(data.get("version", PREPARE_VERSION)),
        )


@dataclass(frozen=True)
class PreparedVideo:
    """The prepared stretch written at `path`."""

    path: str
    width: int
    height: int
    duration_s: float
    frames: int
    warnings: tuple[PrepareWarning, ...] = ()
    content_type: str = "video/mp4"


def plan_prepare(
    width: int,
    height: int,
    source_rotation: int,
    segment: PrepareSegment,
    duration_s: float,
    *,
    index: int | None = None,
) -> PreparePlan:
    """The plan for `segment` of a source stored at `width`×`height`, with a display
    rotation of `source_rotation` degrees counter-clockwise, lasting `duration_s` from its
    first frame. Opens nothing. Raises `PrepareRejected` (`rotation_unsupported`,
    `segment_out_of_range`, `segment_too_short`), naming `index` when given."""
    rotate = segment.rotate
    if isinstance(rotate, bool) or not isinstance(rotate, int) or rotate not in ALLOWED_ROTATIONS:
        # a hand-built `PrepareSegment(rotate=90.0)` passes `in` but breaks `np.rot90`
        raise PrepareRejected(
            "rotation_unsupported", f"a {rotate!r}° turn; only 0, 90, 180 or 270", index
        )
    if source_rotation % 90:
        raise PrepareRejected(
            "rotation_unsupported", f"a {source_rotation}° display rotation", index
        )
    if width < 2 or height < 2:
        raise PrepareRejected("no_video", f"a {width}×{height} picture", index)
    start_s, end_s = _check_segment(segment, duration_s, index)
    # the stored picture as decoded, made even like `cut` does
    stored_w, stored_h = _even_floor(width), _even_floor(height)
    turn = (source_rotation - segment.rotate) % 360
    upright_w, upright_h = (stored_h, stored_w) if turn in (90, 270) else (stored_w, stored_h)
    crop = _centred_crop(upright_w, upright_h)
    out_w, out_h = _scaled(crop.width, crop.height)
    warnings: tuple[PrepareWarning, ...] = ()
    if crop.width < LOW_RESOLUTION_WIDTH:
        warnings = (PrepareWarning("low_resolution", width=crop.width),)
    return PreparePlan(
        segment=segment,
        source=SourceInfo(width, height, source_rotation % 360, duration_s),
        start_s=start_s,
        end_s=end_s,
        turn=turn,
        crop=crop,
        width=out_w,
        height=out_h,
        warnings=warnings,
    )


def plan_segments(
    segments: Sequence[PrepareSegment], sources: Mapping[str, SourceInfo]
) -> tuple[PreparePlan, ...]:
    """One plan per stretch, in order, each against the source of its `key` in `sources`
    (`read_source`'s). The first stretch that fails raises with its `index` (`unknown_key`
    when its key has no source). Opens nothing."""
    plans = []
    for index, segment in enumerate(segments):
        info = sources.get(segment.key)
        if info is None:
            raise PrepareRejected("unknown_key", f"no source for key {segment.key!r}", index)
        plans.append(
            plan_prepare(
                info.width, info.height, info.rotation, segment, info.duration_s, index=index
            )
        )
    return tuple(plans)


def read_source(source: str | os.PathLike[str]) -> SourceInfo:
    """The stored size, display rotation and length of `source`, for `plan_prepare`:
    decodes the first frame only, and reads the length from the header — decoding to the
    end (`probe` with its end) only when the header has none."""
    with open_video(source) as (container, stream):
        # before the first decode: `open_video` leaves FFmpeg's automatic threading, which
        # at 4K holds a frame per core just to read the first one (224 MiB on 8 cores)
        _bound(stream.codec_context, PREPARE_THREADS)
        width = int(stream.codec_context.width or 0)
        height = int(stream.codec_context.height or 0)
        timeline = probe(container, stream, need_end=False)
        # the video stream's own duration first; the container's only when the stream has
        # none (WebM), and that one may count a longer audio track — `apply_prepare` then
        # refuses the stretch against its planned length instead of writing it short
        header = _header_seconds(container, stream)
        if header is not None and stream.start_time is not None:
            # the header counts from the stream's start; the timeline from the first frame
            header -= max(0.0, timeline.origin_s - float(stream.start_time * stream.time_base))
        if header is None or header <= 0:
            container.seek(0)
            ended = probe(container, stream)
            assert ended.end_s is not None  # probed with its end
            header = ended.end_s
    return SourceInfo(
        width=width, height=height, rotation=timeline.rotation, duration_s=round(header, 4)
    )


def apply_prepare(
    source: str | os.PathLike[str],
    plan: PreparePlan,
    out: str | os.PathLike[str],
    *,
    threads: int = PREPARE_THREADS,
) -> PreparedVideo:
    """Write `plan` applied to `source` into `out` (MP4, H.264 `yuv420p`, limited range,
    BT.709 tagged, no audio) at the source's (average) frame rate, constant, stamped from
    0: `[plan.start_s, plan.end_s)` at its real pace — each frame once on a constant-rate
    source, repeated or thinned where a variable-rate one is slower or faster (`_encode`).
    `speed` is EF-04's, not applied here. Raises `PrepareRejected` / `VideoSourceError`."""
    import av  # noqa: PLC0415 — lazy, like every PyAV use in this package

    out_path = os.fspath(out)
    folder, name = os.path.split(out_path)
    partial = os.path.join(folder, f".{name}.{secrets.token_hex(6)}.part")
    try:
        with open_video(source) as (container, stream):
            _bound(stream.codec_context, threads)  # before the first decode (`read_source`)
            timeline = probe(container, stream, need_end=False)
            _check_plan(stream, timeline, plan)
        rate = timeline.rate
        with open_video(source) as (container, stream):
            _bound(stream.codec_context, threads)
            try:
                frames, coverage = _encode(av, container, stream, timeline, plan, partial, threads)
            except av.error.FFmpegError as error:
                # the decode surfaces its own errors (`decoded`): this is the writing
                raise PrepareRejected(
                    "encode_failed", f"the prepared video cannot be written: {error}"
                ) from error
        duration = frames / float(rate)
        planned = plan.end_s - plan.start_s
        # the source's REAL time covered (not frames / average rate, which a variable-rate
        # source understates) against the PLANNED length, as `cut` does: a header that
        # overstates the video (a WebM's container duration counting a longer audio) must
        # not come out short
        if frames == 0 or coverage < planned - 1.5 / float(rate):
            raise PrepareRejected(
                "segment_out_of_range",
                f"the source gave {coverage:.2f} s of the {planned:.2f} s stretch "
                f"at {plan.start_s} s",
            )
        os.replace(partial, out_path)
    except BaseException:
        if os.path.exists(partial):
            os.remove(partial)
        raise
    return PreparedVideo(
        path=out_path,
        width=plan.width,
        height=plan.height,
        duration_s=round(duration, 4),
        frames=frames,
        warnings=plan.warnings,
    )


def prepared_frame(source: str | os.PathLike[str], plan: PreparePlan, at_s: float) -> Any:
    """The frame shown at `at_s` (seconds from the source's first frame, anywhere in the
    source — a preview may scrub outside the stretch) with `plan`'s turn, crop and scale,
    as a `uint8` RGB numpy array of shape (`plan.height`, `plan.width`, 3) — what
    `PIL.Image.fromarray` takes for a JPEG thumbnail. It passes through the same limited
    BT.709 `yuv420p` picture `apply_prepare` encodes, so the thumbnail's colours are the
    video's. Seeks to the keyframe before `at_s` and decodes from there only."""
    import av  # noqa: PLC0415

    if not (-_EPSILON <= at_s <= plan.source.duration_s + _EPSILON):
        raise PrepareRejected(
            "time_out_of_range",
            f"{at_s} s is outside the source (0..{plan.source.duration_s} s)",
        )
    with open_video(source) as (container, stream):
        _bound(stream.codec_context, PREPARE_THREADS)  # before the first decode
        timeline = probe(container, stream, need_end=False)
        _check_plan(stream, timeline, plan)
    half_frame = 0.5 / float(timeline.rate)
    with open_video(source) as (container, stream):
        _bound(stream.codec_context, PREPARE_THREADS)
        held: Any = None
        for frame in _decode_from(container, stream, timeline, max(0.0, at_s)):
            time_s = frame_seconds(frame, stream)
            if time_s is None:
                continue
            if time_s - timeline.origin_s > at_s + half_frame:
                break
            held = frame
        if held is None:
            raise PrepareRejected("time_out_of_range", f"no frame at {at_s} s")
        picture = _Shaper(av, plan, PREPARE_THREADS)(held)
        return picture.to_ndarray(format="rgb24", src_colorspace="ITU709", src_color_range="MPEG")


def prepare(
    source: str | os.PathLike[str],
    out: str | os.PathLike[str],
    segment: PrepareSegment | None = None,
    *,
    threads: int = PREPARE_THREADS,
) -> PreparedVideo:
    """`read_source` → `plan_prepare` → `apply_prepare` in one call; `segment=None` is
    «Usar el video entero», unturned."""
    info = read_source(source)
    if segment is None:
        segment = PrepareSegment(
            key=os.path.basename(os.fspath(source)), start_s=0.0, end_s=info.duration_s
        )
    plan = plan_prepare(info.width, info.height, info.rotation, segment, info.duration_s)
    return apply_prepare(source, plan, out, threads=threads)


# --- the pure arithmetic --------------------------------------------------------------


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _check_segment(
    segment: PrepareSegment, duration_s: float, index: int | None
) -> tuple[float, float]:
    """The `[start, end)` actually kept of `segment` in a source of `duration_s` seconds:
    inside it (an end up to `END_SLACK_SECONDS` past it is cut at the end), at least
    `MIN_SEGMENT_SECONDS` long."""
    start, end = segment.start_s, segment.end_s
    if not all(math.isfinite(value) for value in (start, end, duration_s)):
        raise PrepareRejected("segment_out_of_range", f"not a stretch: {start}..{end}", index)
    if start < -_EPSILON or start >= duration_s or end > duration_s + END_SLACK_SECONDS + _EPSILON:
        raise PrepareRejected(
            "segment_out_of_range",
            f"{start}..{end} s is outside the video (0..{duration_s} s)",
            index,
        )
    start, end = max(0.0, start), min(end, duration_s)
    if end - start < MIN_SEGMENT_SECONDS - _EPSILON:
        raise PrepareRejected(
            "segment_too_short",
            f"the stretch lasts {max(0.0, end - start):.2f} s, at least "
            f"{MIN_SEGMENT_SECONDS:g} s is needed",
            index,
        )
    return start, end


def _centred_crop(width: int, height: int) -> CropRect:
    """The centred 9:16 crop of a `width`×`height` picture: the full height and
    `height·9/16` rounded to even wide when it is wider than 9:16 (the manual
    `crop=ih*9/16:ih`), else the full width and `width·16/9` tall."""
    if Fraction(width, height) > TARGET_ASPECT:
        crop_w = min(width, _even_round(height * TARGET_ASPECT))
        crop_h = height
    else:
        crop_w = width
        crop_h = min(height, _even_round(width / TARGET_ASPECT))
    return CropRect(
        x=_centred(width, crop_w), y=_centred(height, crop_h), width=crop_w, height=crop_h
    )


def _scaled(width: int, height: int) -> tuple[int, int]:
    """The size a `width`×`height` crop is scaled to: itself when it fits in
    `TARGET_SIZE` (never grown), else `TARGET_SIZE` — the crop is 9:16 give or take its
    rounding to even, so that is a stretch of a few tenths of a percent at most."""
    target_w, target_h = TARGET_SIZE
    if width <= target_w and height <= target_h:
        return width, height
    return target_w, target_h


def _even_round(value: Fraction) -> int:
    """`value` rounded to the nearest even integer (halves up), at least 2."""
    return max(2, math.floor(value / 2 + Fraction(1, 2)) * 2)


def _even_floor(value: int) -> int:
    return max(2, value // 2 * 2)


def _centred(outer: int, inner: int) -> int:
    """The offset that centres `inner` in `outer`, made even (4:2:0 chroma is cropped by
    pairs of pixels), so off centre by one pixel at most."""
    return (outer - inner) // 4 * 2


# --- the frame work -------------------------------------------------------------------


def _bound(context: Any, threads: int) -> None:
    """At most `threads` codec threads, slice-threaded (as `join._bound`, VE-10b)."""
    context.thread_count = threads
    context.thread_type = "SLICE"


def _check_plan(stream: Any, timeline: Timeline, plan: PreparePlan) -> None:
    """`plan_mismatch` unless the source is the size and display rotation the plan was
    made for (a plan is stored, and the file behind a key could change)."""
    width = int(stream.codec_context.width or 0)
    height = int(stream.codec_context.height or 0)
    have = (width, height, timeline.rotation)
    planned = (plan.source.width, plan.source.height, plan.source.rotation)
    if have != planned:
        raise PrepareRejected(
            "plan_mismatch",
            f"the plan is for a {planned[0]}×{planned[1]} source turned {planned[2]}°, "
            f"this one is {have[0]}×{have[1]} turned {have[2]}°",
        )


def _source_colour(frame: Any) -> tuple[str, str]:
    """(matrix, range) a decoded frame's YUV is to be read with: its own tags, a `yuvj*`
    format meaning full range; an untagged matrix is BT.709 for HD and BT.601 below."""
    full = frame.format.name.startswith("yuvj") or int(frame.color_range or 0) == _FULL_RANGE
    matrix = _MATRICES.get(int(frame.colorspace or 0))
    if matrix is None:
        matrix = "ITU709" if max(frame.width, frame.height) >= 1280 else "ITU601"
    return matrix, "JPEG" if full else "MPEG"


def _stored_crop(plan: PreparePlan) -> CropRect:
    """`plan.crop` in pixels of the STORED picture, before any turn — so the crop is done
    first, on the decoded YUV, and only the cropped part is ever turned or converted. It is
    `plan.crop` carried back through the counter-clockwise `plan.turn` (`np.rot90`'s), not
    centred again: centring the stored picture rounds on the other side and can land 2 px
    off. Sides and offsets stay even (the stored size is made even, the upright crop too)."""
    stored_w, stored_h = _even_floor(plan.source.width), _even_floor(plan.source.height)
    crop = plan.crop
    if plan.turn == 90:  # upright (row r, col c) is stored (row c, col W-1-r)
        return CropRect(
            x=stored_w - crop.y - crop.height, y=crop.x, width=crop.height, height=crop.width
        )
    if plan.turn == 180:
        return CropRect(
            x=stored_w - crop.x - crop.width,
            y=stored_h - crop.y - crop.height,
            width=crop.width,
            height=crop.height,
        )
    if plan.turn == 270:  # upright (row r, col c) is stored (row H-1-c, col r)
        return CropRect(
            x=crop.y, y=stored_h - crop.x - crop.width, width=crop.height, height=crop.width
        )
    return crop


class _Shaper:
    """Turns decoded frames into `plan`'s picture: crop (FFmpeg's `crop` filter on the
    decoded YUV — it only moves plane pointers, no 4K copy), scale and convert to RGB in one
    swscale pass with the source's own matrix and range, turn, then RGB → `yuv420p` limited
    BT.709. The only full-size arrays are the output's (1080×1920 at most)."""

    def __init__(self, av: Any, plan: PreparePlan, threads: int) -> None:
        self._av, self._plan, self._threads = av, plan, threads
        self._crop = _stored_crop(plan)
        turned = plan.turn in (90, 270)
        self._scaled = (plan.height, plan.width) if turned else (plan.width, plan.height)
        self._graph: Any = None
        self._graph_for: tuple[int, int, str] | None = None

    def __call__(self, frame: Any) -> Any:
        matrix, colour_range = _source_colour(frame)
        cropped = self._cropped(frame)
        width, height = self._scaled
        pixels = cropped.reformat(
            width=width,
            height=height,
            format="rgb24",
            src_colorspace=matrix,
            src_color_range=colour_range,
            interpolation="BICUBIC",
            threads=self._threads,
        ).to_ndarray()
        # the shared turn (`upright.turn_pixels`), once for the display rotation AND the
        # asked turn, on the already cropped and scaled RGB — not `upright_frame`, which
        # would turn the whole stored picture before the crop
        if self._plan.turn:
            pixels = turn_pixels(pixels, self._plan.turn)
        picture = self._av.VideoFrame.from_ndarray(pixels, format="rgb24")
        return picture.reformat(
            format="yuv420p",
            dst_colorspace="ITU709",
            dst_color_range="MPEG",
            dst_color_trc=_BT709,
            dst_color_primaries=_BT709,
            threads=self._threads,
        )

    def _cropped(self, frame: Any) -> Any:
        crop = self._crop
        if (crop.x, crop.y, crop.width, crop.height) == (0, 0, frame.width, frame.height):
            return frame
        shape = (frame.width, frame.height, frame.format.name)
        if self._graph is None or self._graph_for != shape:
            # built from the frame itself, not the stream: a decoder may hand out another
            # format (`yuvj420p` for a full-range `yuv420p`) than the stream announces
            graph = self._av.filter.Graph()
            source = graph.add_buffer(
                width=frame.width,
                height=frame.height,
                format=frame.format.name,
                time_base=frame.time_base or Fraction(1, 1000),
            )
            cut = graph.add("crop", f"w={crop.width}:h={crop.height}:x={crop.x}:y={crop.y}")
            sink = graph.add("buffersink")
            source.link_to(cut)
            cut.link_to(sink)
            graph.configure()
            self._graph, self._graph_for = graph, shape
        self._graph.vpush(frame)
        return self._graph.vpull()


def _encode(
    av: Any,
    container: Any,
    stream: Any,
    timeline: Timeline,
    plan: PreparePlan,
    partial: str,
    threads: int,
) -> tuple[int, float]:
    """Encode `[plan.start_s, plan.end_s)` into `partial` at the source's rate, as a constant
    grid like `cut._write_retimed`: output frame `k` (at `start + k / rate`) shows the
    latest source frame at or before it (half a frame of slack for jittery stamps) — so a
    variable-rate stretch (a phone in low light: 30 fps, then 15) keeps its real pace, a
    slow part's frames repeated, a fast part's thinned. On a constant-rate source it is
    frame for frame. Holds ONE shaped output picture besides the frame decoded; the last
    source frame lasts one frame, never more. Returns (frames written, real coverage in
    seconds: last kept source time − first kept + one frame; 0.0 when none)."""
    rate = timeline.rate
    tick = Fraction(1, 1) / rate
    frame_s = 1.0 / float(rate)
    half_frame = 0.5 * frame_s
    start, end = plan.start_s, plan.end_s
    last_tick = end - half_frame
    frames = 0
    shape = _Shaper(av, plan, threads)
    held: Any = None
    first_s: float | None = None
    held_s = 0.0
    # `_decode_from` checks where its seek landed and surfaces decode errors (`decoded`)
    source_frames: Iterator[Any] = _decode_from(container, stream, timeline, start)
    with av.open(partial, mode="w", format="mp4", options={"movflags": "+faststart"}) as sink:
        encoder = sink.add_stream("libx264", rate=rate)
        encoder.width, encoder.height = plan.width, plan.height
        encoder.pix_fmt = "yuv420p"
        encoder.options = {**PREPARE_X264, "threads": str(threads)}
        context = encoder.codec_context
        context.time_base = tick
        context.color_range = _LIMITED_RANGE
        context.colorspace = _BT709
        context.color_primaries = _BT709
        context.color_trc = _BT709
        _bound(context, threads)

        def emit(picture: Any) -> None:
            nonlocal frames
            # stamped by hand from 0 (see `cut._write_frames`); a repeated picture is the
            # same object re-stamped: the encoder took its pts and a reference at `encode`
            # time, and its pixels are never written to (`cut._write_retimed`)
            picture.pts = frames
            picture.time_base = tick
            for packet in encoder.encode(picture):
                sink.mux(packet)
            frames += 1

        def tick_s() -> float:
            return start + frames * frame_s

        for frame in source_frames:
            time_s = frame_seconds(frame, stream)
            if time_s is None:
                continue
            time_s -= timeline.origin_s
            if time_s < start - half_frame:
                continue
            # the held picture shows on every tick before this frame takes over
            while held is not None and tick_s() < last_tick and tick_s() + half_frame < time_s:
                emit(held)
            if time_s >= end - half_frame:
                break
            held, held_s = shape(frame), time_s
            if first_s is None:
                first_s = time_s
        # the last kept frame lasts one frame: a source that ends early still reads short
        while (
            held is not None and tick_s() < last_tick and tick_s() + half_frame < held_s + frame_s
        ):
            emit(held)
        for packet in encoder.encode():
            sink.mux(packet)
    coverage = 0.0 if first_s is None else held_s - first_s + frame_s
    return frames, coverage


__all__ = [
    "ALLOWED_ROTATIONS",
    "END_SLACK_SECONDS",
    "LOW_RESOLUTION_WIDTH",
    "MIN_SEGMENT_SECONDS",
    "PREPARE_THREADS",
    "PREPARE_VERSION",
    "TARGET_SIZE",
    "CropRect",
    "PreparePlan",
    "PrepareRejected",
    "PrepareWarning",
    "PreparedVideo",
    "PrepareSegment",
    "SourceInfo",
    "apply_prepare",
    "plan_segments",
    "plan_prepare",
    "prepare",
    "prepared_frame",
    "read_source",
    "segments_from_list",
]

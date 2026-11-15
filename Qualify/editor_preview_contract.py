"""The editor preview's data contract (ED-01 m-25026605, epic «Video automático con efectos, por
pasos»): what the screen keeps of the owner's choices and what the browser needs to show
them live — pure, serializable, no Reflex and no `qualify_creative` import.

Two halves, on purpose:

- **The recipe** (`SourceSegment`, `VideoTextLayer`, `EffectUse`, `PartRecipe`) uses
  EXACTLY the names and limits of EF-02 (`qualify_creative.schemas`, built in another
  session and not merged yet), so the day the backend takes it the screen hands it over
  as is. A normal Clip is a recipe of length 1 (`PartRecipe` alone).
- **What only the browser needs** (`PreviewSource`, `PreviewEffect`): the playable
  address of each `key`, the source's length the browser measured, and an effect's
  `preview_asset` / `blend`. It never travels in the recipe.

Every function here is pure and cheap (the screen calls them on each change of the
owner). Nothing decodes a video: the length comes from the browser's `loadedmetadata`.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, get_args

# -- EF-02's limits (qualify_creative.schemas, same values) ---------------------------------

EFFECTS_MAX = 8
SEGMENTS_MAX = 8
VIDEO_TEXT_MAX = 120
#: The speeds the backend can make: EF-04's `speed.MIN_SPEED`/`MAX_SPEED` (a test pins it).
SEGMENT_SPEED_MIN = 1.0
SEGMENT_SPEED_MAX = 30.0
EFFECT_ID_PATTERN = r"^[a-z][a-z0-9_]{0,39}$"
_EFFECT_ID = re.compile(EFFECT_ID_PATTERN)

VideoTextPlace = Literal["top", "middle", "bottom"]
VIDEO_TEXT_PLACES: tuple[str, ...] = get_args(VideoTextPlace)
ROTATIONS: tuple[int, ...] = (0, 90, 180, 270)
EffectParamValue = bool | int | float | str

# -- the screen's own rules ------------------------------------------------------------------

#: The shortest stretch the owner may keep (EF-03 refuses less).
SEGMENT_MIN_SECONDS = 1.0
#: «Tramo = el video entero (hasta 15 s)» (proposal E3): the stretch proposed at first.
DEFAULT_STRETCH_SECONDS = 15.0
#: «Cortar» moves a handle by half a second (←/→ and «− ½ s» / «+ ½ s»).
NUDGE_SECONDS = 0.5
#: Browsers play a `<video>` at most this fast (Chrome); above it the preview is slower.
PREVIEW_RATE_MAX = 16.0
#: Seconds are kept to the hundredth in the recipe (`to_dict` rounds).
_DECIMALS = 2

#: Problem codes (stable, never shown: `clip_editor_vm` turns them into Spanish).
SegmentProblem = Literal[
    "empty_key",
    "too_short",
    "ends_before_start",
    "outside_video",
    "bad_speed",
    "bad_rotate",
]
RecipeProblem = Literal[
    "too_many_effects",
    "too_many_segments",
    "bad_effect_id",
    "bad_effect_version",
    "effect_twice",
    "effect_span",
    "text_empty",
    "text_too_long",
    "bad_text_place",
    "text_span",
    "bad_text_layout",
]


@dataclass(frozen=True)
class SourceSegment:
    """A stretch of the owner's own video: from `start_s` to `end_s` seconds of `key`,
    at `speed` (1 = as recorded), turned `rotate` degrees clockwise. Order in the recipe's
    tuple = order in the video."""

    key: str
    start_s: float
    end_s: float
    speed: float = 1.0
    rotate: int = 0

    @property
    def source_seconds(self) -> float:
        """How much of the source the stretch takes."""
        return max(self.end_s - self.start_s, 0.0)

    @property
    def output_seconds(self) -> float:
        """How long it lasts in the video, at its speed (derived, never stored)."""
        return self.source_seconds / self.speed if self.speed > 0 else 0.0


@dataclass(frozen=True)
class VideoTextLayer:
    """The owner's text over the video: what, where (inside the safe zones) and when
    (`start_s` 0.0 = from the start of its part, `end_s` None = until its end): seconds
    of the part's OUTPUT, after its speed, so they move with the part on their own when
    parts are reordered. A `start_s` None arriving in JSON is read as 0.0.
    `layout_id`/`layout_version` name the layer_spec catalog design it is drawn with
    (EF-02, ADR 49 D1): both or neither."""

    text: str
    place: str = "bottom"
    start_s: float = 0.0
    end_s: float | None = None
    layout_id: str | None = None
    layout_version: int | None = None


@dataclass(frozen=True)
class EffectUse:
    """One effect the owner chose: the library entry (`effect_id` at `version`) and its
    parameters as sorted `(name, value)` pairs (EF-02 serializes them as an object).
    `start_s`/`end_s`: the span it covers, both or neither (None = all of it)."""

    effect_id: str
    version: int = 1
    params: tuple[tuple[str, EffectParamValue], ...] = ()
    start_s: float | None = None
    end_s: float | None = None

    @property
    def param_values(self) -> dict[str, EffectParamValue]:
        return dict(self.params)


@dataclass(frozen=True)
class PartRecipe:
    """One part of the video — a normal Clip is exactly one: its effects, its text and
    the stretches of own video it uses (EF-02's `PartRecipe` subset the screen writes;
    `mode`, `seconds` and the mode rule are the server's). A stretch's number is its
    position in `segments`, 0-based (EF-03 «Preparar», PR #679)."""

    effects: tuple[EffectUse, ...] = ()
    text_layer: VideoTextLayer | None = None
    segments: tuple[SourceSegment, ...] = ()


@dataclass(frozen=True)
class PreviewSource:
    """What the browser plays for a segment's `key`: its address ("" = none it can
    play) and the length it measured (0 = not known yet)."""

    key: str
    url: str = ""
    source_duration_s: float = 0.0


@dataclass(frozen=True)
class PreviewEffect:
    """A library effect as the screen offers it: its Spanish `label`, the stage it acts
    in (EF-02 `stage`), what it needs, and the preview loop (`preview_asset`, a path under
    `effects/`) laid over the video with `blend`. None = the preview simulates it with no
    file (`camara_rapida` = `playbackRate`)."""

    effect_id: str
    label: str
    stage: str
    version: int = 1
    preview_asset: str | None = None
    blend: str | None = None
    needs_own_video: bool = False
    params: tuple[tuple[str, EffectParamValue], ...] = field(default=())


@dataclass(frozen=True)
class PreviewTextDesign:
    """How the preview draws the owner's text (#674, m-25017283: the closed catalog of
    layouts `qualify_creative/layer_spec/catalog_v1.json`, ADR 49): the `scrim` layout —
    white text, no outline nor text shadow, over a black gradient (0 → 75 % across 45 % of
    the height of the chosen side, ≥ 60 % under every line), bold in the brand's title
    typography — inside the 9:16 safe zone (x 64–1016, y 270–1536 of 1080×1920). The
    title shrinks from 112 px to 76 px as it gets longer. `anchor` is the catalog's
    (`top`/`bottom`); the catalog has no middle for `scrim`, so «En el medio» centres the
    same gradient (an adaptation, to settle with EF-05). Only the browser reads it: the
    recipe's `VideoTextLayer` stays EF-02's (`text`, `place`, `start_s`, `end_s`)."""

    layout_id: str
    layout_version: int
    anchor: str
    #: Safe zone, as fractions of the 1080×1920 canvas.
    top: float
    bottom: float
    side: float
    #: The title's size range, in px of the 1080-px-wide canvas, and the characters the
    #: catalog lets `scrim`'s title hold in 9:16 (beyond that it is drawn at the minimum).
    font_px_max: int
    font_px_min: int
    title_max_chars: int


#: #674's catalog values for the `scrim` layout in 9:16. ADR 50 D1: a video's text is drawn
#: with the IMAGE catalog's closed designs (`qualify_creative.layer_spec`, catalog_v1.json),
#: so this is that catalog's `layout_version` — 3 since the band height of 2026-11-15. Copied (this
#: module imports no `qualify_creative`); `test_editor_preview_contract.py` keeps it equal.
TEXT_LAYOUT_ID = "scrim"
TEXT_LAYOUT_VERSION = 3
CANVAS_W, CANVAS_H = 1080, 1920
SAFE_TOP_PX, SAFE_BOTTOM_PX, SAFE_SIDE_PX = 270, 384, 64
TITLE_PX_MAX, TITLE_PX_MIN, TITLE_MAX_CHARS = 112, 76, 32


def text_design(place: str) -> PreviewTextDesign:
    """The design the preview uses for a text at `place` (`VideoTextLayer.place`)."""
    anchor = {"top": "top", "bottom": "bottom"}.get(place, "middle")
    return PreviewTextDesign(
        layout_id=TEXT_LAYOUT_ID,
        layout_version=TEXT_LAYOUT_VERSION,
        anchor=anchor,
        top=round(SAFE_TOP_PX / CANVAS_H, 4),
        bottom=round(SAFE_BOTTOM_PX / CANVAS_H, 4),
        side=round(SAFE_SIDE_PX / CANVAS_W, 4),
        font_px_max=TITLE_PX_MAX,
        font_px_min=TITLE_PX_MIN,
        title_max_chars=TITLE_MAX_CHARS,
    )


def text_is_long(text: str) -> bool:
    """Past `scrim`'s 32 characters the preview draws the title at its minimum size."""
    return len(text.strip()) > TITLE_MAX_CHARS


#: Cámara rápida's id (EF-02 `effects_data/v1.json`). PROVISIONAL decision, to align
#: with EF-02: its speed travels ONLY in the stretch (`SourceSegment.speed`); the
#: `camara_rapida` `EffectUse` carries empty `params` (EF-02's library v1 also lists a
#: `speed` parameter — one of the two must go).
FAST_MOTION = "camara_rapida"
#: The speeds «Velocidad» offers (×10 by default).
FAST_MOTION_SPEEDS: tuple[int, ...] = (5, 10, 20)
FAST_MOTION_DEFAULT = 10

#: The effects the Clip offers, in the order the screen lists them (EF-02 library v1:
#: the layers and «Cámara rápida»; `texto` is the text layer itself, the transitions are
#: between parts only and the Seedance templates are not offered).
CLIP_EFFECTS: tuple[PreviewEffect, ...] = (
    PreviewEffect(
        "vapor_capa",
        "Vapor",
        "compose",
        preview_asset="effects/vapor_capa/v1/preview.webm",
        blend="screen",
    ),
    PreviewEffect(
        "humo_capa",
        "Humo",
        "compose",
        preview_asset="effects/humo_capa/v1/preview.webm",
        blend="screen",
    ),
    PreviewEffect(
        "brasas_capa",
        "Brasas",
        "compose",
        preview_asset="effects/brasas_capa/v1/preview.webm",
        blend="screen",
    ),
    PreviewEffect(FAST_MOTION, "Cámara rápida", "local", needs_own_video=True),
)
_BY_ID = {effect.effect_id: effect for effect in CLIP_EFFECTS}


def effect_of(effect_id: str) -> PreviewEffect | None:
    return _BY_ID.get(effect_id)


def effects_offered(*, has_own_video: bool) -> tuple[PreviewEffect, ...]:
    """What the Clip lists: without own video, only what works on photos (no tools that
    would do nothing)."""
    return tuple(e for e in CLIP_EFFECTS if has_own_video or not e.needs_own_video)


def preview_effect_url(effect: PreviewEffect, assets_root: Path) -> str:
    """The address the browser loads the effect's loop from — only when the file is
    really there (today none is: the layer is then not drawn, and nothing 404s in the
    console). Never `..`, never outside `effects/`."""
    asset = effect.preview_asset or ""
    if not asset.startswith("effects/") or ".." in asset.split("/"):
        return ""
    return "/" + asset if (assets_root / asset).is_file() else ""


def effect_available(effect: PreviewEffect, assets_root: Path) -> bool:
    """Whether the screen offers the effect: a layer only once its loop exists (an
    effect with no file — «Cámara rápida» — always)."""
    return not effect.preview_asset or bool(preview_effect_url(effect, assets_root))


def preview_rate(speed: float) -> float:
    """The `playbackRate` the preview can use (browsers stop at ×16)."""
    return max(min(float(speed), PREVIEW_RATE_MAX), 0.0625)


def preview_is_slower(speed: float) -> bool:
    """«En la vista previa se ve más lento que en el video final.»"""
    return float(speed) > PREVIEW_RATE_MAX


# -- segments ------------------------------------------------------------------------------


def _round(value: float) -> float:
    return round(float(value), _DECIMALS)


def grid_end(source_duration_s: float) -> float:
    """The video's end on the half-second grid, rounded UP (a 7.33 s video ends at 7.5):
    EF-03 cuts an end up to 0.5 s past the source at the source's end, never refuses it."""
    return math.ceil(max(float(source_duration_s), 0.0) / NUDGE_SECONDS) * NUDGE_SECONDS


def max_units(source_duration_s: float) -> int:
    """The slider's maximum, in half seconds (`grid_end` × 2; at least 2 = 1 s)."""
    return max(int(round(grid_end(source_duration_s) / NUDGE_SECONDS)), 2)


def whole_video(key: str, source_duration_s: float) -> SourceSegment:
    """The stretch proposed at first: from 0 to the end (on the grid), up to 15 s (E3)."""
    end = min(grid_end(source_duration_s), DEFAULT_STRETCH_SECONDS)
    return SourceSegment(key=key, start_s=0.0, end_s=_round(end))


def segment_problems(segment: SourceSegment, source_duration_s: float = 0.0) -> list[str]:
    """Every problem of a stretch, as codes. `source_duration_s` 0 = the length is not
    known yet: the «inside the video» check waits for it."""
    problems: list[str] = []
    if not segment.key.strip():
        problems.append("empty_key")
    if segment.end_s <= segment.start_s:
        problems.append("ends_before_start")
    elif segment.source_seconds < SEGMENT_MIN_SECONDS:
        problems.append("too_short")
    if segment.start_s < 0 or (
        source_duration_s > 0 and segment.end_s > float(source_duration_s) + 0.01
    ):
        problems.append("outside_video")
    if not SEGMENT_SPEED_MIN <= segment.speed <= SEGMENT_SPEED_MAX:
        problems.append("bad_speed")
    if segment.rotate not in ROTATIONS:
        problems.append("bad_rotate")
    return problems


def clamp_stretch(start: float, end: float, source_duration_s: float) -> tuple[float, float]:
    """A stretch kept inside the video, on the half-second grid, at least 1 s long when
    the video allows it."""
    total = max(float(source_duration_s), 0.0)
    step = NUDGE_SECONDS
    start = round(max(float(start), 0.0) / step) * step
    end = round(max(float(end), 0.0) / step) * step
    if total > 0:
        total = grid_end(total)
        end = min(end, total)
        start = min(start, max(total - SEGMENT_MIN_SECONDS, 0.0))
    if end - start < SEGMENT_MIN_SECONDS:
        end = start + SEGMENT_MIN_SECONDS
        if total > 0 and end > total:
            end = total
            start = max(end - SEGMENT_MIN_SECONDS, 0.0)
    return _round(start), _round(end)


def nudge(
    start: float, end: float, *, handle: str, delta: float, source_duration_s: float
) -> tuple[float, float]:
    """«− ½ s» / «+ ½ s» on one handle («start» or «end»): the other one stays, and the
    stretch never drops under 1 s nor leaves the video (the move is refused instead)."""
    total = grid_end(source_duration_s)
    new_start, new_end = float(start), float(end)
    if handle == "start":
        new_start = new_start + delta
    else:
        new_end = new_end + delta
    if new_start < 0 or new_end - new_start < SEGMENT_MIN_SECONDS:
        return _round(start), _round(end)
    if total > 0 and new_end > total + 0.001:
        return _round(start), _round(end)
    return _round(new_start), _round(new_end)


def rotate_quarter(rotate: int) -> int:
    """«Girar»: a quarter turn clockwise per tap."""
    return (int(rotate) + 90) % 360 if int(rotate) in ROTATIONS else 0


def used_seconds(segments: Sequence[SourceSegment]) -> float:
    """How much of the owner's video the recipe uses (before any speed)."""
    return _round(sum(segment.source_seconds for segment in segments))


def output_seconds(segments: Sequence[SourceSegment]) -> float:
    """How long the video lasts, at each stretch's speed."""
    return _round(sum(segment.output_seconds for segment in segments))


# -- the recipe ------------------------------------------------------------------------------


def recipe_problems(recipe: PartRecipe) -> list[str]:
    """The recipe's own problems (the stretches' are `segment_problems`)."""
    problems: list[str] = []
    if len(recipe.effects) > EFFECTS_MAX:
        problems.append("too_many_effects")
    if len(recipe.segments) > SEGMENTS_MAX:
        problems.append("too_many_segments")
    seen: set[str] = set()
    for use in recipe.effects:
        if not _EFFECT_ID.match(use.effect_id):
            problems.append("bad_effect_id")
        if use.version < 1:
            problems.append("bad_effect_version")
        if use.effect_id in seen:
            problems.append("effect_twice")
        seen.add(use.effect_id)
        if (use.start_s is None) != (use.end_s is None) or (
            use.start_s is not None and use.end_s is not None and use.end_s <= use.start_s
        ):
            problems.append("effect_span")
    layer = recipe.text_layer
    if layer is not None:
        if not layer.text.strip():
            problems.append("text_empty")
        if len(layer.text) > VIDEO_TEXT_MAX:
            problems.append("text_too_long")
        if layer.place not in VIDEO_TEXT_PLACES:
            problems.append("bad_text_place")
        if layer.start_s < 0 or (layer.end_s is not None and layer.end_s <= layer.start_s):
            problems.append("text_span")
        has_id, has_version = bool(layer.layout_id), layer.layout_version is not None
        if has_id != has_version or (has_version and (layer.layout_version or 0) < 1):
            problems.append("bad_text_layout")
    return problems


def _num(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise ValueError("not a number")
    return float(value)


def _opt_num(value: object) -> float | None:
    return None if value is None else _round(_num(value))


def _param(value: object) -> EffectParamValue:
    if isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return _round(value)
    raise ValueError("an effect's parameter is a bool, a number or a text")


def to_dict(recipe: PartRecipe) -> dict[str, object]:
    """The recipe as JSON-ready data, in EF-02's shape (seconds rounded to 0.01)."""
    layer = recipe.text_layer
    return {
        "effects": [
            {
                "effect_id": use.effect_id,
                "version": int(use.version),
                "params": {name: _param(value) for name, value in use.params},
                "start_s": _opt_num(use.start_s),
                "end_s": _opt_num(use.end_s),
            }
            for use in recipe.effects
        ],
        "text_layer": None
        if layer is None
        else {
            "text": layer.text,
            "place": layer.place,
            "start_s": _round(layer.start_s),
            "end_s": _opt_num(layer.end_s),
            "layout_id": layer.layout_id,
            "layout_version": layer.layout_version,
        },
        "segments": [
            {
                "key": segment.key,
                "start_s": _round(segment.start_s),
                "end_s": _round(segment.end_s),
                "speed": _round(segment.speed),
                "rotate": int(segment.rotate),
            }
            for segment in recipe.segments
        ],
    }


def from_dict(data: Mapping[str, object]) -> PartRecipe:
    """The recipe back from `to_dict`'s data (rounded the same way). Raises ValueError on
    a shape it does not know; the limits are `recipe_problems`'s."""
    if not isinstance(data, Mapping):
        raise ValueError("a recipe is an object")
    effects_raw = data.get("effects") or []
    segments_raw = data.get("segments") or []
    if not isinstance(effects_raw, list | tuple) or not isinstance(segments_raw, list | tuple):
        raise ValueError("effects and segments are lists")
    effects: list[EffectUse] = []
    for item in effects_raw:
        if not isinstance(item, Mapping):
            raise ValueError("an effect is an object")
        params = item.get("params") or {}
        if not isinstance(params, Mapping):
            raise ValueError("an effect's params are an object")
        effects.append(
            EffectUse(
                effect_id=str(item.get("effect_id") or ""),
                version=int(_num(item.get("version", 1))),
                params=tuple(sorted((str(k), _param(v)) for k, v in params.items())),
                start_s=_opt_num(item.get("start_s")),
                end_s=_opt_num(item.get("end_s")),
            )
        )
    segments: list[SourceSegment] = []
    for item in segments_raw:
        if not isinstance(item, Mapping):
            raise ValueError("a stretch is an object")
        segments.append(
            SourceSegment(
                key=str(item.get("key") or ""),
                start_s=_round(_num(item.get("start_s", 0))),
                end_s=_round(_num(item.get("end_s", 0))),
                speed=_round(_num(item.get("speed", 1.0))),
                rotate=int(_num(item.get("rotate", 0))),
            )
        )
    layer_raw = data.get("text_layer")
    layer = None
    if layer_raw is not None:
        if not isinstance(layer_raw, Mapping):
            raise ValueError("the text layer is an object")
        layer = VideoTextLayer(
            text=str(layer_raw.get("text") or ""),
            place=str(layer_raw.get("place") or "bottom"),
            # EF-02: a missing or null start is the start of the part
            start_s=_round(_num(layer_raw.get("start_s") or 0.0)),
            end_s=_opt_num(layer_raw.get("end_s")),
            layout_id=_opt_layout_id(layer_raw.get("layout_id")),
            layout_version=_opt_layout_version(layer_raw.get("layout_version")),
        )
    return PartRecipe(effects=tuple(effects), text_layer=layer, segments=tuple(segments))


# -- words the screen shows (numbers only; the sentences are `clip_editor_vm`'s) ------------


def seconds_text(seconds: float) -> str:
    """«8», «8,5»: whole seconds without decimals, else one decimal with a comma."""
    value = round(max(float(seconds), 0.0), 1)
    if abs(value - round(value)) < 0.05:
        return str(int(round(value)))
    return f"{value:.1f}".replace(".", ",")


def clock_text(seconds: float) -> str:
    """«0:04», «1:02», «0:04,5» (a half second shows)."""
    value = max(float(seconds), 0.0)
    minutes = int(value // 60)
    rest = value - minutes * 60
    whole = int(rest)
    tenth = round(rest - whole, 1)
    if tenth >= 0.95:
        whole, tenth = whole + 1, 0.0
    text = f"{minutes}:{whole:02d}"
    if tenth >= 0.05:
        text += f",{int(round(tenth * 10))}"
    return text


def _opt_layout_id(value: object) -> str | None:
    return str(value) if value else None


def _opt_layout_version(value: object) -> int | None:
    return int(_num(value)) if value not in (None, "") else None

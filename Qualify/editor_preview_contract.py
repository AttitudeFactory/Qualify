"""The editor preview's data contract (ED-01 m-25026605, epic «Video automático con efectos, por
pasos»): what the screen keeps of the owner's choices and what the browser needs to show
them live — pure, serializable, no Reflex and no `qualify_creative` import.

Two halves, on purpose:

- **The recipe** (`SourceSegment`, `VideoTextLayer`, `EffectUse`, `PartRecipe`) uses
  EXACTLY the names and limits of EF-02 (`qualify_creative.schemas`), so the day the
  backend takes it the screen hands it over as is. A normal Clip is a recipe of length 1
  (`PartRecipe` alone). ED-15 (contract v2, m-25029105): up to `TEXT_LAYERS_MAX` texts
  (`PartRecipe.text_layers`; `text_layer` stays as the first one), still photos among
  the stretches (`SourceSegment.kind`) and an effect used more than once where its uses
  do not overlap. `packages/api/tests/test_editor_contract_parity.py` keeps these names
  and limits equal to the backend's.
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

from qualify_shared.objects import platform_effects as _platform_effects

# -- EF-02's limits (qualify_creative.schemas, same values) ---------------------------------

EFFECTS_MAX = 8
SEGMENTS_MAX = 8
VIDEO_TEXT_MAX = 120
#: ED-15 (D-T2): at most this many texts over one part (or Clip).
TEXT_LAYERS_MAX = 3
#: EF-05 (Deivid, 2026-11-16: «Que el dueño elija»): how long a text takes to appear, 0.3 to
#: 1.0 s (both included), 0.5 s when not chosen or stored before the field existed.
VIDEO_TEXT_FADE_MIN_S = 0.3
VIDEO_TEXT_FADE_MAX_S = 1.0
VIDEO_TEXT_FADE_DEFAULT_S = 0.5
#: ED-13 (m-25029108): how a text enters and leaves (the recipe's `motion_in` /
#: `motion_out`). The schema's defaults are what a text stored before them looked like
#: (it fades in, it leaves at once); the EDITOR puts new texts with `fade` / `fade`.
VideoTextMotionIn = Literal["fade", "slide", "zoom", "typewriter"]
VideoTextMotionOut = Literal["none", "fade", "slide", "zoom"]
VIDEO_TEXT_MOTIONS_IN: tuple[str, ...] = get_args(VideoTextMotionIn)
VIDEO_TEXT_MOTIONS_OUT: tuple[str, ...] = get_args(VideoTextMotionOut)
VIDEO_TEXT_MOTION_IN_DEFAULT = "fade"
VIDEO_TEXT_MOTION_OUT_DEFAULT = "none"
#: `slide` moves the text this share of the canvas' height (1920 → 96 px), from below.
VIDEO_TEXT_SLIDE_FRACTION = 0.05
#: `zoom` grows from (and shrinks to) this scale, centred on the text's block.
VIDEO_TEXT_ZOOM_FROM = 0.9
#: «Letra por letra» only for texts this short, at this many seconds per character.
VIDEO_TEXT_TYPEWRITER_MAX_CHARS = 40
VIDEO_TEXT_TYPEWRITER_S_PER_CHAR = 0.06
#: An entrance (or an exit) takes at most this share of the time the text shows.
VIDEO_TEXT_MOTION_MAX_SHARE = 1 / 3
#: ED-13: the backgrounds a text is drawn over — the image catalog's `scrim`, `band` and
#: `brand_fill` (same `layout_version`) plus `shadow` (no background, a strong shadow).
VideoTextLayoutId = Literal["scrim", "band", "brand_fill", "shadow"]
VIDEO_TEXT_LAYOUTS: tuple[str, ...] = get_args(VideoTextLayoutId)
#: `band` and `brand_fill` hug the text block by this much (px of the 1080-wide canvas);
#: `brand_fill`'s corners are this round.
VIDEO_TEXT_BOX_PAD_PX = 48
VIDEO_TEXT_BOX_RADIUS_PX = 24
#: `shadow` («Sin fondo», Deivid 2026-11-23): only the letters, white and clean — no text
#: shadow, no outline.
#: `band` («Franja», «oscura y neutra»): a fixed near-black strip with white letters,
#: whatever the brand — never the palette's surface (white on some brands).
VIDEO_TEXT_BAND_COLOR = "#111111"
VIDEO_TEXT_BAND_INK = "#FFFFFF"
#: ED-13 (Deivid 2026-11-23): the colour the owner picks for «Franja» / «Recuadro de tu
#: color» (`VideoTextLayer.box_color`): a `#RRGGBB` hex in capitals; None = the default.
VIDEO_TEXT_BOX_COLOR_PATTERN = r"^#[0-9A-F]{6}$"
_BOX_COLOR = re.compile(VIDEO_TEXT_BOX_COLOR_PATTERN)
VIDEO_TEXT_BOX_COLOR_LAYOUTS: tuple[str, ...] = ("band", "brand_fill")
#: ED-13 round 3 (Deivid 2026-11-23): the letters' colour the owner picks for «Sin fondo»
#: (`VideoTextLayer.text_color`): the same `#RRGGBB` in capitals; None = white.
VIDEO_TEXT_TEXT_COLOR_PATTERN = VIDEO_TEXT_BOX_COLOR_PATTERN
VIDEO_TEXT_TEXT_COLOR_LAYOUTS: tuple[str, ...] = ("shadow",)
#: On a picked colour the letters are white or near-black, whichever contrasts more
#: (`box_ink`, the render's `layout.ts` `boxInk`).
VIDEO_TEXT_INK_LIGHT = "#FFFFFF"
VIDEO_TEXT_INK_DARK = "#111111"
#: ED-13 round 4 (Deivid 2026-11-23: «3 tamaños»): the letters' size the owner picks
#: (`VideoTextLayer.text_size`), each scaling the catalog's 9:16 title range (112 → 76 px);
#: «Mediana» (`medium`) is the default, what every text looked like before. «Grande» takes
#: texts up to `VIDEO_TEXT_LARGE_MAX_CHARS` characters (longer, it is off and says why).
VideoTextSize = Literal["small", "medium", "large"]
VIDEO_TEXT_SIZES: tuple[str, ...] = get_args(VideoTextSize)
VIDEO_TEXT_SIZE_DEFAULT = "medium"
VIDEO_TEXT_SIZE_SCALE: dict[str, float] = {"small": 0.75, "medium": 1.0, "large": 1.25}
VIDEO_TEXT_LARGE_MAX_CHARS = 40
#: ED-15 (D-T1): a still photo among the stretches shows 1 to 5 s, from 0, at speed 1.
PHOTO_SECONDS_MIN = 1.0
PHOTO_SECONDS_MAX = 5.0
SegmentKind = Literal["video", "photo"]
#: The speeds the backend can make: EF-04's `speed.MIN_SPEED`/`MAX_SPEED` (a test pins it).
SEGMENT_SPEED_MIN = 1.0
SEGMENT_SPEED_MAX = 30.0
EFFECT_ID_PATTERN = r"^[a-z][a-z0-9_]{0,39}$"
_EFFECT_ID = re.compile(EFFECT_ID_PATTERN)
#: The library's hard cut (`qualify_creative.schemas.CUT_EFFECT_ID`): a block's
#: `transition_in` naming it is no transition (m-25114465).
CUT_EFFECT_ID = "corte"

VideoTextPlace = Literal["top", "middle", "bottom"]
VIDEO_TEXT_PLACES: tuple[str, ...] = get_args(VideoTextPlace)
ROTATIONS: tuple[int, ...] = (0, 90, 180, 270)
SEGMENT_KINDS: tuple[str, ...] = get_args(SegmentKind)
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
    # ED-15 — the screen's own (the backend refuses an unknown `kind` while reading it):
    "bad_kind",
    # ED-15 — the backend's own codes (`qualify_creative.schemas.RECIPE_REFUSALS`):
    "photo_not_from_start",
    "photo_with_speed",
    "photo_length_out_of_range",
]
RecipeProblem = Literal[
    "too_many_effects",
    "too_many_segments",
    "bad_effect_id",
    "bad_effect_version",
    #: Kept so maps that name it keep working; no longer emitted (ED-15: an effect may
    #: repeat where its uses do not overlap — `effect_uses_overlap`).
    "effect_twice",
    "effect_span",
    "text_empty",
    "text_too_long",
    "bad_text_place",
    "text_span",
    "bad_text_layout",
    # ED-15: the backend's own codes (`qualify_creative.schemas.RECIPE_REFUSALS`)
    "too_many_texts",
    "texts_overlap",
    "effect_uses_overlap",
    "text_bottom_with_subtitles",
    # ED-13 (m-25029108): appended, never reordered
    "unknown_text_motion",
    "typewriter_text_too_long",
    # ED-13 (m-25029108): appended, never reordered
    "bad_text_box_color",
    # ED-13 round 3 (m-25029108): appended, never reordered
    "bad_text_color",
    # ED-13 round 4 (m-25029108): appended, never reordered
    "unknown_text_size",
    "text_too_long_for_large",
]


@dataclass(frozen=True)
class SourceSegment:
    """A stretch of the owner's own video: from `start_s` to `end_s` seconds of `key`,
    at `speed` (1 = as recorded), turned `rotate` degrees clockwise. Order in the recipe's
    tuple = order in the video.

    ED-15: `kind` "photo" is a still photo in the same tuple, in its place among the
    videos: from 0 to `end_s` = how long it shows (1-5 s), at speed 1.

    m-25114465 (ADR 50 §10): `transition_in` is how this block blends with the block
    BEFORE it in a normal Clip («la unión»): a library `transition` (`fundido` /
    `barrido` v2) with no span of its own; None is «Corte» (never written, so a Clip with
    only cuts keeps its exact shape). Never on the first block."""

    key: str
    start_s: float
    end_s: float
    speed: float = 1.0
    rotate: int = 0
    kind: str = "video"
    transition_in: EffectUse | None = None

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
    (EF-02, ADR 49 D1): both or neither. `fade_s`: how long it takes to appear (EF-05,
    `VIDEO_TEXT_FADE_MIN_S`-`VIDEO_TEXT_FADE_MAX_S`); missing in JSON = the default.
    ED-13: `motion_in` / `motion_out` — how it enters and leaves (`VIDEO_TEXT_MOTIONS_IN`
    / `_OUT`), each taking `fade_s` (at most a third of its time on screen; «Letra por
    letra» its own length); missing in JSON = the schema's defaults. `layout_id` is one of
    `VIDEO_TEXT_LAYOUTS`. `box_color`: the colour the owner picked for `band` /
    `brand_fill` (`#RRGGBB`, None = the default; written only when there is one).
    `text_color`: the letters' colour the owner picked for `shadow` (`#RRGGBB`, None =
    white; written only when there is one). `text_size`: the letters' size
    (`VIDEO_TEXT_SIZES`; written only when not `medium`)."""

    text: str
    place: str = "bottom"
    start_s: float = 0.0
    end_s: float | None = None
    layout_id: str | None = None
    layout_version: int | None = None
    fade_s: float = VIDEO_TEXT_FADE_DEFAULT_S
    motion_in: str = VIDEO_TEXT_MOTION_IN_DEFAULT
    motion_out: str = VIDEO_TEXT_MOTION_OUT_DEFAULT
    box_color: str | None = None
    text_color: str | None = None
    text_size: str = VIDEO_TEXT_SIZE_DEFAULT


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
    """One part of the video — a normal Clip is exactly one: its effects, its texts and
    the stretches of own video it uses (EF-02's `PartRecipe` subset the screen writes;
    `mode`, `seconds` and the mode rule are the server's). A stretch's number is its
    position in `segments`, 0-based (EF-03 «Preparar», PR #679).

    ED-15: `text_layers` are its texts (up to `TEXT_LAYERS_MAX`), in order. `text_layer`
    stays for v1 callers and always equals the first text (None without any): given
    alone it is read as `text_layers` of one; given with `text_layers`, it is kept first
    unless they already hold it (the backend's rule). To change the texts of a recipe,
    build a new one with `text_layers` (a `dataclasses.replace` of `text_layers` alone
    would put the old first text back)."""

    effects: tuple[EffectUse, ...] = ()
    text_layer: VideoTextLayer | None = None
    segments: tuple[SourceSegment, ...] = ()
    text_layers: tuple[VideoTextLayer, ...] = ()

    def __post_init__(self) -> None:
        layers = tuple(self.text_layers)
        if self.text_layer is not None and self.text_layer not in layers:
            layers = (self.text_layer, *layers)
        object.__setattr__(self, "text_layers", layers)
        object.__setattr__(self, "text_layer", layers[0] if layers else None)


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
    `effects/` or an R2 platform key `platform/effects/<id>/v<n>/preview.mp4`, m-25120474)
    laid over the video with `blend`. None = the preview simulates it with no file
    (`camara_rapida` = `playbackRate`)."""

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


# -- ED-13 (m-25029108): backgrounds and motions, mirrored for the preview ---------------------

#: `packages/render/src/props.ts` `DEFAULT_*`: a brand without (valid) colours.
PALETTE_DEFAULT_ACCENT = "#0F766E"
PALETTE_DEFAULT_TEXT = "#FFFFFF"
PALETTE_DEFAULT_SURFACE = "#F8FAFC"
#: WCAG 2's ratio the text reaches on its background (`engine.ts` `TEXT_MIN`).
TEXT_MIN_CONTRAST = 4.5
_COLOR = re.compile(r"^#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$", re.IGNORECASE)


@dataclass(frozen=True)
class TextPalette:
    """The brand's three colours as the render reads them (`props.ts` `paletteOf`: the
    kit's palette in order — accent, text, surface — each its default when missing)."""

    accent: str = PALETTE_DEFAULT_ACCENT
    text: str = PALETTE_DEFAULT_TEXT
    surface: str = PALETTE_DEFAULT_SURFACE


def is_color(value: object) -> bool:
    return isinstance(value, str) and bool(_COLOR.match(value.strip()))


def palette_of(colors: Sequence[str]) -> TextPalette:
    """`paletteOf`: the kit's first three colours, a default for any that is not one."""
    picked = [str(c).strip() for c in list(colors)[:3]]
    picked += [""] * (3 - len(picked))
    accent, text, surface = picked
    return TextPalette(
        accent=accent if is_color(accent) else PALETTE_DEFAULT_ACCENT,
        text=text if is_color(text) else PALETTE_DEFAULT_TEXT,
        surface=surface if is_color(surface) else PALETTE_DEFAULT_SURFACE,
    )


def _rgb(color: str) -> tuple[int, int, int]:
    s = color.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    s = s[:6]
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def opaque(color: str) -> str:
    """`engine.ts` `opaque`: `#rgb` / `#rrggbb` / `#rrggbbaa` → `#RRGGBB`."""
    s = color.strip().lstrip("#")
    if len(s) in (3, 4):
        s = "".join(ch * 2 for ch in s[:3])
    return "#" + s[:6].upper()


def _channel(value: int) -> float:
    c = value / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(color: str) -> float:
    r, g, b = _rgb(color)
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(a: str, b: str) -> float:
    """WCAG 2 contrast ratio, 1-21 (`engine.ts` `contrast`)."""
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def text_color_on(background: str, palette: TextPalette) -> tuple[str, float]:
    """`engine.ts` `textColorOn`: the first of the brand's text colour, white, near-black
    and black that reaches 4.5:1 on `background` — the colour and its ratio."""
    candidates = (palette.text, "#FFFFFF", "#111111", "#000000")
    for color in candidates:
        ratio = contrast(color, background)
        if ratio >= TEXT_MIN_CONTRAST:
            return color, ratio
    best = max(candidates, key=lambda c: contrast(c, background))
    return best, contrast(best, background)


def is_box_color(value: object) -> bool:
    """A colour the owner may pick for a text's box: `#RRGGBB` in capitals."""
    return isinstance(value, str) and bool(_BOX_COLOR.match(value))


def box_ink(background: str) -> str:
    """`layout.ts` `boxInk`: the letters on a colour the owner picked — white or
    near-black, whichever has the higher contrast (a tie is white)."""
    light, dark = VIDEO_TEXT_INK_LIGHT, VIDEO_TEXT_INK_DARK
    return light if contrast(light, background) >= contrast(dark, background) else dark


def text_box_colors(
    layout: str, palette: TextPalette, box_color: str | None = None
) -> tuple[str, str]:
    """What a text is drawn over and in: `(background, ink)`. `band` on the fixed dark
    neutral `VIDEO_TEXT_BAND_COLOR` with `VIDEO_TEXT_BAND_INK` letters (whatever the brand),
    `brand_fill` on its accent with the ink `text_color_on` picks; on either, a colour the
    owner picked (`box_color`) with `box_ink`'s letters. `scrim` and `shadow` have no box of
    their own and white letters (`("", "#FFFFFF")`), whatever `box_color` says."""
    if layout not in VIDEO_TEXT_BOX_COLOR_LAYOUTS:
        return "", "#FFFFFF"
    if is_box_color(box_color):
        picked = str(box_color)
        return picked, box_ink(picked)
    if layout == "band":
        return VIDEO_TEXT_BAND_COLOR, VIDEO_TEXT_BAND_INK
    background = opaque(palette.accent)
    return background, text_color_on(background, palette)[0]


def default_box_color(layout: str, palette: TextPalette) -> str:
    """The colour `layout`'s box has when the owner picks none ("" = it has no box)."""
    return text_box_colors(layout, palette)[0]


def typewriter_fits(text: str) -> bool:
    """«Letra por letra» takes texts of up to `VIDEO_TEXT_TYPEWRITER_MAX_CHARS`."""
    return len(text.strip()) <= VIDEO_TEXT_TYPEWRITER_MAX_CHARS


def large_fits(text: str) -> bool:
    """«Grande» takes texts of up to `VIDEO_TEXT_LARGE_MAX_CHARS` (ED-13 round 4)."""
    return len(text.strip()) <= VIDEO_TEXT_LARGE_MAX_CHARS


def motion_seconds(fade_s: float, visible_s: float) -> float:
    """How long an entrance or an exit takes: `fade_s`, at most a third of the time the
    text shows."""
    return max(min(float(fade_s), float(visible_s) * VIDEO_TEXT_MOTION_MAX_SHARE), 0.0)


def typewriter_seconds(text: str, visible_s: float) -> float:
    """«Letra por letra»'s own length: 0,06 s per character, at most a third of its time."""
    return max(
        min(
            len(text.strip()) * VIDEO_TEXT_TYPEWRITER_S_PER_CHAR,
            float(visible_s) * VIDEO_TEXT_MOTION_MAX_SHARE,
        ),
        0.0,
    )


_WHITESPACE = re.compile(r"\s+")


def typed_chars(text: str) -> list[str]:
    """The characters «Letra por letra» types, as the render lays them: trimmed, every
    whitespace run one space, by code point (`layout.ts` `resolveVideoText`)."""
    return list(_WHITESPACE.sub(" ", text.strip()))


def motion_is_cut(fade_s: float, visible_s: float) -> bool:
    """The animation is shorter than chosen, so the text can be read."""
    return motion_seconds(fade_s, visible_s) < float(fade_s) - 1e-6


def ease_in(p: float) -> float:
    """The entrance's curve for position and scale: `1 - (1 - p)^3`."""
    p = min(max(float(p), 0.0), 1.0)
    return 1 - (1 - p) ** 3


def ease_out(p: float) -> float:
    """The exit's curve for position and scale: `p^3`."""
    p = min(max(float(p), 0.0), 1.0)
    return p**3


@dataclass(frozen=True)
class TextFrame:
    """A text's look at one moment: its alpha (0-1), how far down it is (a share of the
    canvas' height), its scale and how many characters show (-1 = all)."""

    alpha: float = 1.0
    dy: float = 0.0
    scale: float = 1.0
    chars: int = -1


def text_frame(
    into_s: float,
    visible_s: float,
    *,
    text: str = "",
    fade_s: float = VIDEO_TEXT_FADE_DEFAULT_S,
    motion_in: str = VIDEO_TEXT_MOTION_IN_DEFAULT,
    motion_out: str = VIDEO_TEXT_MOTION_OUT_DEFAULT,
    reduced: bool = False,
    breaks: int = 0,
) -> TextFrame:
    """The text `into_s` seconds after it appears, shown `visible_s` seconds: the
    contract's curves (alpha linear; position and scale `ease_in` / `ease_out`).
    `assets/edit-sequence-core.js` `textFrame` is the same (a node test keeps them
    equal). «Letra por letra» shows its letters in order, each at once (the box fades
    in over min(0,2 s, its length d)), on the final video's clock (`video_pipeline.compose`
    + `text_overlay.LetterReveal`): its n letters are `typed_chars` less the spaces the
    `breaks` line breaks eat, and letter i appears at `i * d / n` (the first at once);
    `chars` counts those letters. `reduced` (prefers-reduced-motion): only the alpha,
    every character at once."""
    t, visible = float(into_s), max(float(visible_s), 0.0)
    if t < 0 or t >= visible:
        return TextFrame(alpha=0.0, chars=0)
    typing = motion_in == "typewriter"
    if typing and not reduced:
        d_in = typewriter_seconds(text, visible)
    else:
        d_in = motion_seconds(fade_s, visible)
    d_out = 0.0 if motion_out == "none" else motion_seconds(fade_s, visible)
    alpha, dy, scale, chars = 1.0, 0.0, 1.0, -1
    if d_in > 0 and t < d_in:
        p = t / d_in
        if typing and not reduced:
            letters = max(len(typed_chars(text)) - max(int(breaks), 0), 1)
            step = d_in / letters
            chars = min(letters, int(math.floor(t / step + 1e-6)) + 1) if step > 0 else letters
            alpha = min(t / min(0.2, d_in), 1.0)
        else:
            alpha = p
            if not reduced and motion_in == "slide":
                dy = (1 - ease_in(p)) * VIDEO_TEXT_SLIDE_FRACTION
            if not reduced and motion_in == "zoom":
                scale = VIDEO_TEXT_ZOOM_FROM + (1 - VIDEO_TEXT_ZOOM_FROM) * ease_in(p)
    if d_out > 0 and t > visible - d_out:
        q = (t - (visible - d_out)) / d_out
        alpha = min(alpha, 1 - q)
        if not reduced and motion_out == "slide":
            dy = ease_out(q) * VIDEO_TEXT_SLIDE_FRACTION
        if not reduced and motion_out == "zoom":
            scale = 1 - (1 - VIDEO_TEXT_ZOOM_FROM) * ease_out(q)
    return TextFrame(
        alpha=round(min(max(alpha, 0.0), 1.0), 4),
        dy=round(dy, 4),
        scale=round(scale, 4),
        chars=chars,
    )


#: Cámara rápida's id (EF-02 `effects_data/v1.json`). PROVISIONAL decision, to align
#: with EF-02: its speed travels ONLY in the stretch (`SourceSegment.speed`); the
#: `camara_rapida` `EffectUse` carries empty `params` (EF-02's library v1 also lists a
#: `speed` parameter — one of the two must go).
FAST_MOTION = "camara_rapida"
#: The speeds «Velocidad» offers (×10 by default); each one only when the result lasts
#: 3–60 s (Deivid 2026-11-17: ×2 and ×3 so a video of 6 s or more can use it).
FAST_MOTION_SPEEDS: tuple[int, ...] = (2, 3, 5, 10, 20)
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


#: The backend route that serves an effect's «Así se ve» video from R2 (m-25120474,
#: `qualify_api.http.effect_preview_routes`). Its addresses are paths on the BACKEND's
#: origin, not the frontend's: the caller puts the backend origin in front
#: (`is_backend_effect_url`).
R2_EFFECTS_ROUTE = "/r2effects"
#: Exactly the key the route serves, built from the route's own expressions
#: (`qualify_shared.objects.platform_effects`: the library's effect id, a version 1..9999
#: with no leading zero, the fixed `preview.mp4`), so the two cannot drift apart.
_PLATFORM_PREVIEW_KEY = re.compile(
    re.escape(_platform_effects.PLATFORM_EFFECTS_PREFIX)
    + f"({_platform_effects.EFFECT_ID_RE.pattern})"
    + f"/v({_platform_effects.VERSION_RE.pattern})/"
    + re.escape(_platform_effects.PREVIEW_FILE)
)


def preview_effect_url(effect: PreviewEffect, assets_root: Path) -> str:
    """The address the browser loads the effect's loop from — a local loop only when the
    file is really there (else the layer is not drawn, and nothing 404s in the console);
    an R2 platform preview as its `/r2effects/<id>/v<n>` route (backend origin). Never
    `..`, never outside `effects/` or the exact platform key."""
    asset = effect.preview_asset or ""
    if m := _PLATFORM_PREVIEW_KEY.fullmatch(asset):
        return f"{R2_EFFECTS_ROUTE}/{m[1]}/v{m[2]}"  # m-25120474: R2 platform preview
    if not asset.startswith("effects/") or ".." in asset.split("/"):
        return ""
    return "/" + asset if (assets_root / asset).is_file() else ""


def is_backend_effect_url(url: str) -> bool:
    """Whether `url` (from `preview_effect_url`) is served by the backend, so the browser
    needs the backend's origin in front of it (in development the two are separate)."""
    return url.startswith(R2_EFFECTS_ROUTE + "/")


def effect_available(effect: PreviewEffect, assets_root: Path) -> bool:
    """Whether the screen offers the effect: a layer only once its loop exists (an
    effect with no file — «Cámara rápida» — always). An R2 platform preview cannot be
    checked from here without a store call: it is offered when its key is exactly one the
    route serves. If the object is missing the route answers 404 without touching any
    business data, the layer's `<video>` stays empty and the preview keeps playing the
    blocks under it (a layer has no broken state of its own)."""
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
    known yet: the «inside the video» check waits for it. A photo (ED-15) has no length
    of its own to fall inside: it shows 1-5 s from 0, at speed 1."""
    problems: list[str] = []
    photo = segment.kind == "photo"
    if not segment.key.strip():
        problems.append("empty_key")
    if segment.kind not in SEGMENT_KINDS:
        problems.append("bad_kind")
    if segment.end_s <= segment.start_s:
        problems.append("ends_before_start")
    elif segment.source_seconds < SEGMENT_MIN_SECONDS and not photo:
        problems.append("too_short")
    if segment.start_s < 0 or (
        not photo and source_duration_s > 0 and segment.end_s > float(source_duration_s) + 0.01
    ):
        problems.append("outside_video")
    if not SEGMENT_SPEED_MIN <= segment.speed <= SEGMENT_SPEED_MAX:
        problems.append("bad_speed")
    if segment.rotate not in ROTATIONS:
        problems.append("bad_rotate")
    if photo:
        if segment.start_s != 0:
            problems.append("photo_not_from_start")
        if segment.speed != 1:
            problems.append("photo_with_speed")
        if not PHOTO_SECONDS_MIN <= segment.end_s <= PHOTO_SECONDS_MAX:
            problems.append("photo_length_out_of_range")
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
    """How much of the owner's video the recipe uses (before any speed; photos aside)."""
    return _round(sum(s.source_seconds for s in segments if s.kind != "photo"))


def output_seconds(segments: Sequence[SourceSegment]) -> float:
    """How long the video lasts, at each stretch's speed."""
    return _round(sum(segment.output_seconds for segment in segments))


# -- the recipe ------------------------------------------------------------------------------


def _overlaps(spans: Sequence[tuple[float, float]]) -> bool:
    """Whether any two spans cover the same seconds (meeting at a second is fine)."""
    ordered = sorted(spans)
    return any(later[0] < earlier[1] for earlier, later in zip(ordered, ordered[1:]))


def recipe_problems(recipe: PartRecipe) -> list[str]:
    """The recipe's own problems (the stretches' are `segment_problems`). ED-15: up to
    `TEXT_LAYERS_MAX` texts, no two in the same place at the same time (`texts_overlap`),
    and an effect used again only where its other uses are not (`effect_uses_overlap`; a
    use with no span covers the whole part). The part's length is not known here, so an
    open end runs to the end of everything.

    How many times EACH effect may be used is the library's (`max_per_part`, v2), which
    this module does not read: the backend refuses past it (`too_many_of_effect`), so the
    screen offers a second use only of an effect the library lets repeat."""
    problems: list[str] = []
    if len(recipe.effects) > EFFECTS_MAX:
        problems.append("too_many_effects")
    if len(recipe.segments) > SEGMENTS_MAX:
        problems.append("too_many_segments")
    uses_of: dict[str, list[tuple[float, float]]] = {}
    for use in recipe.effects:
        if not _EFFECT_ID.match(use.effect_id):
            problems.append("bad_effect_id")
        if use.version < 1:
            problems.append("bad_effect_version")
        if (use.start_s is None) != (use.end_s is None) or (
            use.start_s is not None and use.end_s is not None and use.end_s <= use.start_s
        ):
            problems.append("effect_span")
        span = (
            0.0 if use.start_s is None else float(use.start_s),
            math.inf if use.end_s is None else float(use.end_s),
        )
        uses_of.setdefault(use.effect_id, []).append(span)
    if any(_overlaps(spans) for spans in uses_of.values()):
        problems.append("effect_uses_overlap")
    if len(recipe.text_layers) > TEXT_LAYERS_MAX:
        problems.append("too_many_texts")
    texts_at: dict[str, list[tuple[float, float]]] = {}
    for layer in recipe.text_layers:
        end = math.inf if layer.end_s is None else float(layer.end_s)
        texts_at.setdefault(layer.place, []).append((float(layer.start_s), end))
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
        if has_id and layer.layout_id not in VIDEO_TEXT_LAYOUTS:
            problems.append("bad_text_layout")  # the backend's `unknown_layout`
        if not VIDEO_TEXT_FADE_MIN_S <= layer.fade_s <= VIDEO_TEXT_FADE_MAX_S:
            problems.append("bad_text_fade")
        if (
            layer.motion_in not in VIDEO_TEXT_MOTIONS_IN
            or layer.motion_out not in VIDEO_TEXT_MOTIONS_OUT
        ):
            problems.append("unknown_text_motion")
        if layer.motion_in == "typewriter" and not typewriter_fits(layer.text):
            problems.append("typewriter_text_too_long")
        if layer.box_color is not None and not is_box_color(layer.box_color):
            problems.append("bad_text_box_color")
        if layer.text_color is not None and not is_box_color(layer.text_color):
            problems.append("bad_text_color")
        if layer.text_size not in VIDEO_TEXT_SIZES:
            problems.append("unknown_text_size")
        elif layer.text_size == "large" and not large_fits(layer.text):
            problems.append("text_too_long_for_large")
    if any(_overlaps(spans) for spans in texts_at.values()):
        problems.append("texts_overlap")
    return list(dict.fromkeys(problems))


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


def _layer_dict(layer: VideoTextLayer) -> dict[str, object]:
    data: dict[str, object] = {
        "text": layer.text,
        "place": layer.place,
        "start_s": _round(layer.start_s),
        "end_s": _opt_num(layer.end_s),
        "layout_id": layer.layout_id,
        "layout_version": layer.layout_version,
    }
    # EF-05: the fade travels when the owner chose one; the default is left out, so a text
    # without a choice keeps v1's exact shape (as a video stretch writes no `kind`, ED-15)
    if _round(layer.fade_s) != VIDEO_TEXT_FADE_DEFAULT_S:
        data["fade_s"] = _round(layer.fade_s)
    # ED-13: the same for how it enters and leaves (the schema's defaults are left out)
    if layer.motion_in != VIDEO_TEXT_MOTION_IN_DEFAULT:
        data["motion_in"] = layer.motion_in
    if layer.motion_out != VIDEO_TEXT_MOTION_OUT_DEFAULT:
        data["motion_out"] = layer.motion_out
    # ED-13: the colour the owner picked, only when there is one
    if layer.box_color is not None:
        data["box_color"] = layer.box_color
    if layer.text_color is not None:
        data["text_color"] = layer.text_color
    # ED-13 round 4: the size, only when not «Mediana»
    if layer.text_size != VIDEO_TEXT_SIZE_DEFAULT:
        data["text_size"] = layer.text_size
    return data


def _transition_dict(use: EffectUse) -> dict[str, object]:
    """A block's `transition_in` as the server reads it (m-25114465): its library entry
    and parameters — no span (a join has none)."""
    return {
        "effect_id": use.effect_id,
        "version": int(use.version),
        "params": {name: _param(value) for name, value in use.params},
    }


def _transition_of(raw: object) -> EffectUse | None:
    """`_transition_dict` back; None (a cut) for nothing or `corte`."""
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("a transition is an object")
    effect_id = str(raw.get("effect_id") or "")
    if not effect_id or effect_id == CUT_EFFECT_ID:
        return None
    params = raw.get("params") or {}
    if not isinstance(params, Mapping):
        raise ValueError("a transition's params are an object")
    return EffectUse(
        effect_id=effect_id,
        version=int(_num(raw.get("version", 1))),
        params=tuple(sorted((str(k), _param(v)) for k, v in params.items())),
    )


def to_dict(recipe: PartRecipe) -> dict[str, object]:
    """The recipe as JSON-ready data, in EF-02's shape (seconds rounded to 0.01). ED-15:
    `text_layers` carries every text; `text_layer` (the first, or None) stays for v1
    readers — the backend reads both and counts a text once."""
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
        "text_layer": None if layer is None else _layer_dict(layer),
        "segments": [
            {
                "key": segment.key,
                "start_s": _round(segment.start_s),
                "end_s": _round(segment.end_s),
                "speed": _round(segment.speed),
                "rotate": int(segment.rotate),
                # a video's stretch keeps v1's exact shape (no `kind`: video by default)
                **({} if segment.kind == "video" else {"kind": segment.kind}),
                # m-25114465: the join into this block, last — and only when it blends (a
                # cut is no key: the digest of a Clip with only cuts does not change)
                **(
                    {}
                    if segment.transition_in is None
                    else {"transition_in": _transition_dict(segment.transition_in)}
                ),
            }
            for segment in recipe.segments
        ],
        "text_layers": [_layer_dict(each) for each in recipe.text_layers],
    }


def from_dict(data: Mapping[str, object]) -> PartRecipe:
    """The recipe back from `to_dict`'s data (rounded the same way). Raises ValueError on
    a shape it does not know; the limits are `recipe_problems`'s. ED-15: a v1 recipe's
    `text_layer` reads as `text_layers` of one (with both, it is kept first unless
    `text_layers` holds it); a stretch without `kind` is a video."""
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
                kind=str(item.get("kind") or "video"),
                transition_in=_transition_of(item.get("transition_in")),
            )
        )
    layer_raw = data.get("text_layer")
    layer = None if layer_raw is None else _layer_of(layer_raw)
    layers_raw = data.get("text_layers") or []
    if not isinstance(layers_raw, list | tuple):
        raise ValueError("the texts are a list")
    return PartRecipe(
        effects=tuple(effects),
        text_layer=layer,
        segments=tuple(segments),
        text_layers=tuple(_layer_of(item) for item in layers_raw),
    )


def _layer_of(raw: object) -> VideoTextLayer:
    if not isinstance(raw, Mapping):
        raise ValueError("the text layer is an object")
    return VideoTextLayer(
        text=str(raw.get("text") or ""),
        place=str(raw.get("place") or "bottom"),
        # EF-02: a missing or null start is the start of the part
        start_s=_round(_num(raw.get("start_s") or 0.0)),
        end_s=_opt_num(raw.get("end_s")),
        layout_id=_opt_layout_id(raw.get("layout_id")),
        layout_version=_opt_layout_version(raw.get("layout_version")),
        # EF-05: a text stored before the fade was chosen reads with the default
        fade_s=_round(
            _num(raw.get("fade_s") if raw.get("fade_s") is not None else VIDEO_TEXT_FADE_DEFAULT_S)
        ),
        # ED-13: a text stored before them enters with a fade and leaves at once
        motion_in=str(raw.get("motion_in") or VIDEO_TEXT_MOTION_IN_DEFAULT),
        motion_out=str(raw.get("motion_out") or VIDEO_TEXT_MOTION_OUT_DEFAULT),
        # ED-13: a text without a picked colour has its background's default
        box_color=str(raw["box_color"]) if raw.get("box_color") is not None else None,
        # ED-13 round 3: «Sin fondo» without a picked colour has white letters
        text_color=str(raw["text_color"]) if raw.get("text_color") is not None else None,
        # ED-13 round 4: a text stored before the size was chosen is «Mediana»
        text_size=str(raw.get("text_size") or VIDEO_TEXT_SIZE_DEFAULT),
    )


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

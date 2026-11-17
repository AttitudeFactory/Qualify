"""BrandVisualSystem v0 — a brand's visual identity as DATA (spike m-25042530).

One JSON document per (system id, version). A brand may keep several systems (the AI proposals
it was shown, the one it chose, its later edits); every edit is a new ``version`` with
``parent_version`` pointing back, so going back is "make version N current again", never an
in-place edit. The Remotion template ``brand_still`` draws any recipe of a system from
(system JSON + slot data): a new brand never needs new React, only a new document.

The JSON Schema in ``brand_visual_system.v0.schema.json`` is exported from these models
(``python -m qualify_creative.brand_system.model``) — this file is the single source.

Spike quality: nothing here is wired to the app, the database or R2.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

HEX = r"^#[0-9a-fA-F]{6}$"
Hex = Annotated[str, Field(pattern=HEX)]
ColorRole = Literal[
    "background",
    "background_alt",
    "surface",
    "on_surface",
    "ink",
    "accent",
    "on_accent",
    "shadow",
    "pop",
]
Format = Literal["4:5", "1:1", "9:16"]
# A colour is a role of the system or, where a brand uses a one-off tone (Bianki's ticker ink
# #a80c1c, its darker rays #d4000e), a literal hex.
ColorRef = ColorRole | Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Colors(_Strict):
    """Colour ROLES, not a palette: every component paints with a role."""

    background: Hex = Field(description="Main canvas colour.")
    background_alt: Hex = Field(description="Second background tone (glow centre, gradient end).")
    surface: Hex = Field(description="Cards, stamps, chips.")
    on_surface: Hex = Field(description="Text on surface.")
    ink: Hex = Field(description="Text directly on the background.")
    accent: Hex = Field(description="Highlight: second headline line, price flag, tag.")
    on_accent: Hex = Field(description="Text on accent.")
    shadow: Hex = Field(description="Hard/soft shadow colour.")
    pop: Hex = Field(description="Secondary colour for decorations (rays, dots, sun).")
    background_edge: Hex | None = Field(default=None, description="Third stop of a radial base.")
    shadow_deep: Hex | None = Field(
        default=None, description="Blurred shadows (defaults to shadow)."
    )


class TypeFace(_Strict):
    family: str = Field(description="Google Fonts family name, exactly as in the catalogue.")
    weight: int = Field(ge=100, le=900)
    letter_spacing_em: float = Field(default=0.0, ge=-0.12, le=0.3)
    line_height: float = Field(default=1.0, ge=0.8, le=1.6)
    uppercase: bool = False
    src: str | None = Field(
        default=None, description="Brand font file (asset path) used instead of Google Fonts."
    )


class Typography(_Strict):
    display: TypeFace = Field(description="Headlines and prices.")
    body: TypeFace = Field(description="Descriptions, addresses.")
    label: TypeFace = Field(description="Tags, small caps labels, ticker.")


BackgroundKind = Literal[
    "rays",
    "rings",
    "dots",
    "stripes",
    "grid",
    "waves",
    "pattern_image",
    "blobs",
    "grain",
    "confetti",
]


class BackgroundLayer(_Strict):
    kind: BackgroundKind
    color: ColorRef = "pop"
    opacity: float = Field(default=0.3, ge=0.0, le=1.0)
    scale: float = Field(default=1.0, ge=0.2, le=5.0, description="Size multiplier of the motif.")
    angle_deg: float = Field(default=0.0, ge=-180, le=180)
    center: tuple[float, float] = Field(
        default=(0.5, 0.42), description="rays/rings/blobs centre, canvas fractions."
    )
    image: str | None = Field(default=None, description="pattern_image only: a brand asset path.")


class Background(_Strict):
    base: Literal["solid", "radial", "linear"] = "radial"
    layers: list[BackgroundLayer] = Field(default_factory=list, max_length=4)


class Shapes(_Strict):
    radius_px: int = Field(default=24, ge=0, le=80, description="Corner radius at 1080 px wide.")
    tilt_deg: float = Field(
        default=0.0, ge=-8, le=8, description="Default tilt of tags/flags/cards."
    )
    shadow: Literal["hard", "soft", "none"] = "hard"
    shadow_offset_px: int = Field(default=10, ge=0, le=30)
    stroke_px: int = Field(default=0, ge=0, le=12, description="Outline of cards/chips (0 = none).")


class TagSpec(_Strict):
    variant: Literal["tilted_block", "pill", "outline", "underline", "plain"] = "tilted_block"
    fill: ColorRef = "accent"
    ink: ColorRef = "on_accent"


class HeadlineSpec(_Strict):
    variant: Literal["two_tone_stacked", "single_color", "outline_second", "highlight_second"] = (
        "two_tone_stacked"
    )
    split: Literal["first_word", "last_word", "none"] = Field(
        default="first_word",
        description="first_word: «Shawarma|mixto»; last_word: «¡Abrimos|hoy!»; none: one group.",
    )
    first_color: ColorRef = "ink"
    second_color: ColorRef = "accent"
    shadow: bool = True


class PriceSpec(_Strict):
    variant: Literal["flag", "badge", "circle", "ticket", "plain"] = "flag"
    fill: ColorRef = "accent"
    ink: ColorRef = "on_accent"
    show_code: bool = Field(default=True, description="Print the currency code (COP, USD) small.")


class StampSpec(_Strict):
    variant: Literal["circle_ring", "starburst", "scallop", "none"] = "circle_ring"
    fill: ColorRef = "surface"
    ink: ColorRef = "background"
    ring: ColorRef = "accent"


class TickerSpec(_Strict):
    enabled: bool = True
    fill: ColorRef = "accent"
    ink: ColorRef = "background"
    separator: str = Field(default="✦", max_length=3)


class ProductFrameSpec(_Strict):
    variant: Literal["cutout_glow", "cutout_sun", "disc", "arch", "rounded", "blob"] = "cutout_glow"
    ring: ColorRef = "surface"
    glow: ColorRef = "accent"


class CardSpec(_Strict):
    variant: Literal["card", "chip", "outline", "plain"] = "card"
    fill: ColorRef = "surface"
    ink: ColorRef = "on_surface"


class LogoSpec(_Strict):
    variant: Literal["plain", "on_badge"] = "plain"
    badge: ColorRef = "surface"


class SparkleSpec(_Strict):
    enabled: bool = True
    glyph: str = Field(default="✦", max_length=2)
    color: ColorRef = "surface"


class BodySpec(_Strict):
    strong_color: ColorRef = "accent"
    strong_uppercase: bool = True
    chip_fill: ColorRef = "surface"
    chip_ink: ColorRef = "background"


class Components(_Strict):
    body: BodySpec = Field(default_factory=BodySpec)
    tag: TagSpec = Field(default_factory=TagSpec)
    headline: HeadlineSpec = Field(default_factory=HeadlineSpec)
    price: PriceSpec = Field(default_factory=PriceSpec)
    stamp: StampSpec = Field(default_factory=StampSpec)
    ticker: TickerSpec = Field(default_factory=TickerSpec)
    product_frame: ProductFrameSpec = Field(default_factory=ProductFrameSpec)
    info_card: CardSpec = Field(default_factory=CardSpec)
    logo: LogoSpec = Field(default_factory=LogoSpec)
    sparkle: SparkleSpec = Field(default_factory=SparkleSpec)


class Tone(_Strict):
    voice: str = Field(max_length=200, description="One line, Spanish: how this brand talks.")
    exclamations: bool = True


StackItemType = Literal["tag", "headline", "body", "price", "flag", "note", "chips"]
FlagShape = Literal["pennant", "double", "arrow", "rect"]


class StackItem(_Strict):
    type: StackItemType
    slot: str | None = Field(default=None, description="Dotted path into the slot data.")
    text: str | None = Field(default=None, max_length=60, description="Literal short text (a tag).")
    size: int = Field(default=0, ge=0, le=220, description="Max font size at 1080 px; 0 = default.")
    space_before: int = Field(default=-1, ge=-1, le=200, description="px above; -1 = default gap.")
    shape: FlagShape | None = Field(default=None, description="flag/price: outline of the banner.")
    line_height: float | None = Field(
        default=None, ge=0.8, le=1.8, description="body/note override."
    )
    small_em: float = Field(
        default=0.45, ge=0.2, le=1.0, description="flag: size of <<small>> parts."
    )


class VeilStop(_Strict):
    color: ColorRef
    alpha: float = Field(ge=0, le=1)
    at: float = Field(ge=0, le=100, description="Percent from the top of the canvas.")


BlockType = Literal[
    "photo",
    "logo",
    "product",
    "stamp",
    "text_stack",
    "ticker",
    "info_list",
    "icon_feature",
    "sparkle",
    "glow",
    "sun",
]
IconName = Literal["clock", "pin", "card", "chat", "bag", "star", "heart"]


class Block(_Strict):
    type: BlockType
    box: tuple[float, float, float, float] = Field(
        description="x, y, w, h in canvas fractions; may bleed outside [0,1]."
    )
    align: Literal["left", "center", "right"] = "left"
    valign: Literal["top", "center", "bottom"] = "top"
    rotate_deg: float = Field(default=0.0, ge=-30, le=30)
    z: int = Field(default=0, ge=0, le=20)
    slot: str | None = None
    text: str | None = Field(default=None, max_length=60)
    items: list[StackItem] = Field(default_factory=list, max_length=8)
    icon: IconName | None = None
    fade: Literal["none", "bottom", "full"] = Field(default="none", description="photo: veil.")
    mirror: bool = False
    focus: tuple[float, float] = Field(default=(0.5, 0.5), description="photo: focal point.")
    zoom: float | None = Field(
        default=None, ge=0.5, le=4, description="photo: image height / box height (None = cover)."
    )
    veil: list[VeilStop] = Field(
        default_factory=list, max_length=8, description="photo: gradient over the whole canvas."
    )
    saturate: float = Field(default=1.0, ge=0.5, le=1.6)
    contrast: float = Field(default=1.0, ge=0.5, le=1.6)
    framed: bool = Field(default=False, description="photo: card with border, radius and tilt.")
    colors: list[ColorRef] = Field(
        default_factory=list, max_length=3, description="glow/sun/sparkle: colour overrides."
    )


class Recipe(_Strict):
    format: Format
    background: Background | None = Field(default=None, description="Overrides the system one.")
    blocks: list[Block] = Field(min_length=1, max_length=14)


RecipeId = Literal["product_hero", "combo", "hours", "payments", "contact", "story"]


class Provenance(_Strict):
    source: Literal["transcribed", "ai_proposal", "owner_edit"]
    model: str | None = None
    prompt_version: str | None = None
    created_at: str = Field(description="ISO 8601.")
    notes: str | None = None


class BrandVisualSystem(_Strict):
    schema_version: Literal[0] = 0
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,60}$", description="Stable across versions.")
    version: int = Field(ge=1)
    parent_version: int | None = None
    brand: str
    name: str = Field(max_length=40, description="Spanish, shown to the owner («Rojo trompo»).")
    style_family: str = Field(max_length=60)
    rationale: str = Field(max_length=600, description="Spanish: why this fits the brand.")
    provenance: Provenance
    colors: Colors
    typography: Typography
    background: Background
    shapes: Shapes = Field(default_factory=Shapes)
    components: Components = Field(default_factory=Components)
    tone: Tone
    recipes: dict[RecipeId, Recipe]


SCHEMA_PATH = Path(__file__).with_name("brand_visual_system.v0.schema.json")


def export_schema() -> dict:
    return BrandVisualSystem.model_json_schema()


if __name__ == "__main__":
    SCHEMA_PATH.write_text(json.dumps(export_schema(), ensure_ascii=False, indent=2) + "\n")
    print(f"wrote {SCHEMA_PATH}")

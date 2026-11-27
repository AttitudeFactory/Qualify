"""BrandVisualSystem v1 — the CONSTRAINED proposal an AI may write (spike m-25042530, SISVIS-002).

v0 let the model write geometry (pixel boxes), literal hex anywhere, asset paths and text. v1 keeps
the team in charge of everything that can break a piece:

- geometry is a versioned library (``recipe_library.v1.json``): a proposal picks ONE variant id per
  piece type, compatible with the piece's format;
- colours: hex only in the role palette; every component colour is a role;
- typography: a family from the closed list (``fonts.v1.json``) and one of its published weights;
- background: one of the team's variants + bounded parameters;
- copy: a voice line, one short tag per piece type and up to 3 ticker phrases — nothing else.
  Product names, prices, descriptions, hours, address and photos come from the business data at
  compose time (``compile_to_v0``), never from the model; assets are ``asset://<id>`` references.

A proposal that fails ``validate_proposal`` (schema, bounds, unknown ids, contrast) is discarded and
counted; so is one whose render reports an overflow or a dropped price.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

HERE = Path(__file__).parent
FONTS: dict[str, list[int]] = json.loads((HERE / "fonts.v1.json").read_text())["families"]
LIBRARY: dict = json.loads((HERE / "recipe_library.v1.json").read_text())
VARIANTS: dict[str, dict] = {v["id"]: v for v in LIBRARY["variants"]}

Hex = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]
Role = Literal[
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
ShortCopy = Annotated[str, Field(min_length=2, max_length=26)]

#: Pieces of SISVIS-002 and the format each must be drawn in.
PIECES: dict[str, tuple[str, str]] = {
    "product_hero": ("product_hero", "4:5"),
    "product_alt": ("product_hero", "4:5"),
    "hours": ("hours", "4:5"),
    "story": ("story", "9:16"),
}
BACKGROUND_VARIANTS = (
    "solid",
    "gradient",
    "rays",
    "rays_rings",
    "rings",
    "dots",
    "stripes",
    "grid",
    "waves",
    "blobs",
    "confetti",
    "pattern",
)


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Colors(_S):
    background: Hex
    background_alt: Hex
    surface: Hex
    on_surface: Hex
    ink: Hex
    accent: Hex
    on_accent: Hex
    shadow: Hex
    pop: Hex


class Face(_S):
    family: str
    weight: int = Field(ge=100, le=900)
    letter_spacing_em: float = Field(default=0.0, ge=-0.08, le=0.2)
    uppercase: bool = False

    @model_validator(mode="after")
    def _closed(self) -> Face:
        if self.family not in FONTS:
            raise ValueError(f"family {self.family!r} not in the closed list")
        if self.weight not in FONTS[self.family]:
            raise ValueError(
                f"{self.family} has no weight {self.weight} (has {FONTS[self.family]})"
            )
        return self


class Typography(_S):
    display: Face
    body: Face
    label: Face


class BackgroundChoice(_S):
    variant: Literal[BACKGROUND_VARIANTS]  # type: ignore[valid-type]
    color: Role = "pop"
    opacity: float = Field(default=0.25, ge=0.05, le=0.6)
    scale: float = Field(default=1.0, ge=0.5, le=2.0)
    angle_deg: float = Field(default=0.0, ge=-45, le=45)


class Shapes(_S):
    radius_px: int = Field(default=24, ge=0, le=60)
    tilt_deg: float = Field(default=-2.0, ge=-6, le=6)
    shadow: Literal["hard", "soft", "none"] = "hard"
    shadow_offset_px: int = Field(default=8, ge=0, le=16)


class Tag(_S):
    variant: Literal["tilted_block", "pill", "outline", "underline", "plain"]
    fill: Role = "accent"
    ink: Role = "on_accent"


class Headline(_S):
    variant: Literal["two_tone_stacked", "single_color", "outline_second", "highlight_second"]
    split: Literal["first_word", "last_word", "none"] = "first_word"
    first_color: Role = "ink"
    second_color: Role = "accent"
    shadow: bool = True


class Price(_S):
    variant: Literal["flag", "badge", "circle", "ticket", "plain"]
    fill: Role = "accent"
    ink: Role = "on_accent"
    show_code: bool = True


class Stamp(_S):
    variant: Literal["circle_ring", "starburst", "scallop", "none"]
    fill: Role = "surface"
    ink: Role = "background"
    ring: Role = "accent"


class Ticker(_S):
    enabled: bool = True
    fill: Role = "accent"
    ink: Role = "background"


class ProductFrame(_S):
    variant: Literal["cutout_glow", "cutout_sun", "disc", "arch", "rounded", "blob"]
    ring: Role = "surface"
    glow: Role = "accent"


class Card(_S):
    variant: Literal["card", "chip", "outline", "plain"] = "chip"
    fill: Role = "surface"
    ink: Role = "on_surface"


class Logo(_S):
    variant: Literal["plain", "on_badge"] = "plain"
    badge: Role = "surface"


class Sparkle(_S):
    enabled: bool = True
    color: Role = "surface"


class Components(_S):
    tag: Tag
    headline: Headline
    price: Price
    stamp: Stamp
    ticker: Ticker
    product_frame: ProductFrame
    info_card: Card = Field(default_factory=Card)
    logo: Logo = Field(default_factory=Logo)
    sparkle: Sparkle = Field(default_factory=Sparkle)


class Tone(_S):
    voice: str = Field(min_length=10, max_length=160)
    tags: dict[Literal["product_hero", "product_alt", "hours", "story"], ShortCopy]
    ticker: list[Annotated[str, Field(min_length=2, max_length=28)]] = Field(
        default_factory=list, max_length=3
    )


class ProposalV1(_S):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,50}$")
    name: str = Field(min_length=3, max_length=32)
    style_family: str = Field(min_length=3, max_length=60)
    rationale: str = Field(min_length=20, max_length=400)
    colors: Colors
    typography: Typography
    background: BackgroundChoice
    shapes: Shapes = Field(default_factory=Shapes)
    components: Components
    tone: Tone
    recipes: dict[Literal["product_hero", "product_alt", "hours", "story"], str]

    @model_validator(mode="after")
    def _recipes(self) -> ProposalV1:
        for piece, (kind, fmt) in PIECES.items():
            vid = self.recipes.get(piece)
            if vid is None:
                if piece == "hours":  # only drawn when the business stored its hours
                    continue
                raise ValueError(f"recipes.{piece} missing")
            v = VARIANTS.get(vid)
            if v is None:
                raise ValueError(f"recipes.{piece}: unknown variant {vid!r}")
            if v["piece"] != kind or v["format"] != fmt:
                raise ValueError(
                    f"recipes.{piece}: {vid} is a {v['piece']} {v['format']}, needs {kind} {fmt}"
                )
        return self


# ------------------------------------------------------------------ contrast (WCAG 2.1)
def _lum(h: str) -> float:
    def ch(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (int(h[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


#: (what, ink role, ground role, minimum). Large display text (≥ 30 px bold) uses the 3:1 WCAG
#: large-text bar; body text sits on the background, so ink/background also gets 3:1 because the
#: renderer adds a text shadow — Bianki's cream on red (4.6:1) passes, a pastel on white does not.
def contrast_problems(p: ProposalV1) -> list[str]:
    c = p.colors.model_dump()
    k = p.components
    pairs = [
        ("ink/background", "ink", "background", 3.0),
        ("on_surface/surface", "on_surface", "surface", 4.5),
        ("on_accent/accent", "on_accent", "accent", 3.0),
        (
            "tag",
            k.tag.ink if k.tag.variant in ("tilted_block", "pill") else k.tag.fill,
            k.tag.fill if k.tag.variant in ("tilted_block", "pill") else "background",
            3.0,
        ),
        ("headline 1", k.headline.first_color, "background", 3.0),
        (
            "price",
            k.price.ink if k.price.variant != "plain" else k.price.fill,
            k.price.fill if k.price.variant != "plain" else "background",
            3.0,
        ),
        ("ticker", k.ticker.ink, k.ticker.fill, 3.0),
        ("info card", k.info_card.ink, k.info_card.fill, 4.5),
    ]
    if k.headline.variant in ("two_tone_stacked", "outline_second"):
        pairs.append(("headline 2", k.headline.second_color, "background", 3.0))
    out = []
    for what, ink, ground, minimum in pairs:
        r = contrast(c[ink], c[ground])
        if r < minimum:
            out.append(f"{what}: {ink} on {ground} = {r:.2f} < {minimum}")
    return out


def validate_proposal(raw: dict) -> tuple[ProposalV1 | None, list[str]]:
    try:
        p = ProposalV1.model_validate(raw)
    except ValidationError as e:
        return None, [f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()]
    problems = contrast_problems(p)
    return (None, problems) if problems else (p, [])


# ------------------------------------------------------------------ compile to the v0 document
def _background(b: BackgroundChoice, has_pattern: bool) -> dict:
    lay = {
        "color": b.color,
        "opacity": b.opacity,
        "scale": b.scale,
        "angle_deg": b.angle_deg,
        "center": [0.5, 0.42],
    }
    v = b.variant
    if v == "solid":
        return {"base": "solid", "layers": []}
    if v == "gradient":
        return {"base": "linear", "layers": []}
    if v == "rays_rings":
        return {
            "base": "radial",
            "layers": [
                {**lay, "kind": "rays"},
                {**lay, "kind": "rings", "color": "accent", "opacity": round(b.opacity * 0.4, 3)},
            ],
        }
    if v == "pattern" and not has_pattern:
        return {"base": "radial", "layers": [{**lay, "kind": "dots"}]}
    kind = {"pattern": "pattern_image"}.get(v, v)
    return {"base": "radial", "layers": [{**lay, "kind": kind}]}


def _fill_tags(obj: object, tag: str) -> object:
    if isinstance(obj, dict):
        return {k: (tag if v == "{{tag}}" else _fill_tags(v, tag)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_fill_tags(x, tag) for x in obj]
    return obj


def compile_to_v0(
    p: ProposalV1,
    *,
    brand: str,
    model: str,
    prompt_version: str,
    created_at: str,
    has_pattern: bool = False,
) -> dict:
    """The v0 document `brand_still` draws. Every recipe comes from the library."""
    t = p.typography
    def face(f: Face, lh: float) -> dict:
        return {
            "family": f.family,
            "weight": f.weight,
            "letter_spacing_em": f.letter_spacing_em,
            "line_height": lh,
            "uppercase": f.uppercase,
        }

    recipes = {}
    for piece, vid in p.recipes.items():
        rec = VARIANTS[vid]["recipe"]
        recipes[piece] = _fill_tags(rec, p.tone.tags.get(piece, ""))
    comp = p.components.model_dump()
    comp["ticker"]["separator"] = "✦"
    comp["sparkle"]["glyph"] = "✦"
    comp["body"] = {
        "strong_color": "accent",
        "strong_uppercase": True,
        "chip_fill": "surface",
        "chip_ink": "on_surface",
    }
    return {
        "schema_version": 0,
        "id": p.id,
        "version": 1,
        "parent_version": None,
        "brand": brand,
        "name": p.name,
        "style_family": p.style_family,
        "rationale": p.rationale,
        "provenance": {
            "source": "ai_proposal",
            "model": model,
            "prompt_version": prompt_version,
            "created_at": created_at,
            "notes": f"schema v1, library v{LIBRARY['library_version']}: {p.recipes}",
        },
        "colors": {**p.colors.model_dump(), "background_edge": None, "shadow_deep": None},
        "typography": {
            "display": face(t.display, 0.98),
            "body": face(t.body, 1.35),
            "label": face(t.label, 1.0),
        },
        "background": _background(p.background, has_pattern),
        "shapes": {**p.shapes.model_dump(), "stroke_px": 0},
        "components": comp,
        "tone": {"voice": p.tone.voice, "exclamations": True},
        "recipes": recipes,
    }


def prompt_reference() -> str:
    """Compact reference of the closed choices, for the prompt."""
    lines = ["Familias tipográficas permitidas (familia: pesos):"]
    lines += [f"- {f}: {', '.join(map(str, w))}" for f, w in FONTS.items()]
    lines.append("\nVariantes de receta (id · formato · bloques):")
    for v in LIBRARY["variants"]:
        lines.append(
            f"- {v['id']} · {v['format']} · {v['summary']}"
            + (f" · necesita {', '.join(v['requires'])}" if v["requires"] else "")
        )
    lines.append(
        "\nVariantes de fondo: "
        + ", ".join(BACKGROUND_VARIANTS)
        + " (pattern solo si la marca trae una trama)"
    )
    return "\n".join(lines)

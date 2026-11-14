"""`LayerSpec`: the text layer of one image or carousel slide — the contract between the
layer stage (Claude, `qualify_api.creative.image_pipeline.layer`, m-25017283) and the
Remotion composition (`packages/render`, m-25017285).

Everything here comes from the closed catalog (`docs/catalogo-disenos-imagen-carrusel.md`,
approved by the founder 2026-11-14), read from ONE data file, `catalog_v1.json`, that the
composition reads too: layout ids, the parameters each layout takes (§1.6), the text slots
and their character limits per layout and format (§1.5, §2), the fixed info-block labels
(§1.5), the carousel roles (§6) and the writing rules a free text must pass (§1.8).

Validation is deterministic and strict: a spec that breaks any rule raises
`pydantic.ValidationError`, never gets trimmed or guessed. What it cannot see — whether a
product id is one of the business's catalog products, whether an info value is the saved
datum — the layer stage checks before it builds the spec (the model never writes a value
or a price, only which block or product).

The JSON Schema of this model is committed next to it (`layer_spec_v1.schema.json`,
`export_json_schema`); a test keeps the two equal. `spec_version` changes when this shape
changes; `layout_version` when the catalog's numbers change (it enters the render key,
ADR 49 §2.2).
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from enum import StrEnum
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SPEC_VERSION = 1
CATALOG_FILE = "catalog_v1.json"
SCHEMA_FILE = "layer_spec_v1.schema.json"

Format = Literal["4:5", "1:1", "9:16"]


@cache
def catalog() -> dict[str, Any]:
    """The catalog data file (the same one `packages/render` reads)."""
    text = resources.files(__package__).joinpath(CATALOG_FILE).read_text(encoding="utf-8")
    return json.loads(text)


LAYOUT_VERSION: int = catalog()["layout_version"]


class LayoutId(StrEnum):
    PHOTO_ONLY = "photo_only"
    PLATE = "plate"
    SCRIM = "scrim"
    BAND = "band"
    INFO_CARD = "info_card"
    BRAND_FILL = "brand_fill"
    HIGHLIGHT_CIRCLE = "highlight_circle"


class Anchor(StrEnum):
    TOP_LEFT = "top_left"
    TOP_RIGHT = "top_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_RIGHT = "bottom_right"
    TOP_CENTER = "top_center"
    BOTTOM_CENTER = "bottom_center"
    TOP = "top"
    BOTTOM = "bottom"


class ContainerColor(StrEnum):
    SURFACE = "surface"
    ACCENT = "accent"


class InfoKind(StrEnum):
    LOCATION = "location"
    HOURS = "hours"
    PAYMENT = "payment"
    PRODUCTS = "products"
    CONTACT = "contact"


class CarouselRole(StrEnum):
    COVER = "cover"  # portada
    BODY = "body"  # desarrollo
    CLOSING = "closing"  # cierre


class HighlightKind(StrEnum):
    ICON = "icon"
    WORD = "word"
    PHOTO = "photo"


#: Layouts that are drawn over the photo (they need what Claude saw in it).
PHOTO_LAYOUTS = frozenset({LayoutId.PHOTO_ONLY, LayoutId.PLATE, LayoutId.SCRIM, LayoutId.BAND})
#: Layouts with text, where a title is mandatory (catalog §1.5: without it → `photo_only`).
TITLED_LAYOUTS = frozenset({LayoutId.PLATE, LayoutId.SCRIM, LayoutId.BAND, LayoutId.BRAND_FILL})

_STEP = 0.05


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PhotoReading(_Strict):
    """What Claude reports about the photo BEFORE choosing a layout (catalog §1.2)."""

    #: [x0, y0, x1, y1], fractions 0-1 in steps of 0.05: the rectangle no text may cover.
    subject_box: tuple[float, float, float, float]
    #: The photo already shows the business's real logo: no logo is drawn.
    logo_in_photo: bool
    #: ADR 49 §8.2: the Seedream base shows invented letters, buttons or a logo — the
    #: base is regenerated once. Always false for the owner's own photo.
    base_has_invented_text: bool

    @field_validator("subject_box")
    @classmethod
    def _box(cls, box: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        for value in box:
            if not 0.0 <= value <= 1.0:
                raise ValueError("subject_box values are fractions between 0 and 1")
            if abs(value / _STEP - round(value / _STEP)) > 1e-6:
                raise ValueError("subject_box values are rounded to 0.05")
        x0, y0, x1, y1 = box
        if not (x0 < x1 and y0 < y1):
            raise ValueError("subject_box must be [x0, y0, x1, y1] with x0 < x1 and y0 < y1")
        return tuple(round(v, 2) for v in box)  # type: ignore[return-value]


class InfoBlock(_Strict):
    """A data block: Claude chooses the kind and the order; the label is fixed (catalog
    §1.5) and the value is the business's SAVED datum, filled by the layer stage."""

    kind: InfoKind
    label: str
    value: str = Field(min_length=1)

    @model_validator(mode="after")
    def _fixed_label(self) -> InfoBlock:
        expected = catalog()["info_blocks"][self.kind.value]["label"]
        if self.label != expected:
            raise ValueError(f"the label of a {self.kind.value} block is «{expected}»")
        return self


class PriceRef(_Strict):
    """A catalog product whose price the composition prints (founder 2026-11-14: a text
    line inside the plate or the band, never a pill). Only the id: the price itself is
    read from the catalog, whole or not at all — never written by the model."""

    product_id: UUID


class HighlightContent(_Strict):
    kind: HighlightKind
    icon_id: str | None = None
    word: str | None = None

    @model_validator(mode="after")
    def _one_kind(self) -> HighlightContent:
        layout = catalog()["layouts"]["highlight_circle"]
        if self.kind is HighlightKind.ICON:
            if self.icon_id not in layout["icon_ids"] or self.word is not None:
                raise ValueError("an icon highlight takes one icon_id of the closed set")
        elif self.kind is HighlightKind.WORD:
            max_chars, _lines = layout["highlight_word"]
            if not self.word or len(self.word) > max_chars or " " in self.word.strip():
                raise ValueError(f"a word highlight is one word of at most {max_chars} chars")
            if self.icon_id is not None:
                raise ValueError("a word highlight has no icon_id")
        elif self.icon_id is not None or self.word is not None:
            raise ValueError("a photo highlight has neither icon_id nor word")
        return self


class CarouselPlace(_Strict):
    """Where a slide sits in its carousel (catalog §6)."""

    role: CarouselRole
    index: int = Field(ge=0, le=9)
    count: int = Field(ge=2, le=10)

    @model_validator(mode="after")
    def _consistent(self) -> CarouselPlace:
        if self.index >= self.count:
            raise ValueError("index must be below count")
        expected = (
            CarouselRole.COVER
            if self.index == 0
            else CarouselRole.CLOSING
            if self.index == self.count - 1
            else CarouselRole.BODY
        )
        if self.role is not expected:
            raise ValueError(f"slide {self.index + 1} of {self.count} is the {expected.value}")
        return self


# -- free-text rules (catalog §1.8) -------------------------------------------------------

#: a currency symbol, anywhere
_CURRENCY_SYMBOL = re.compile(r"[$€£¥₡₲₱]")
#: an amount word: a currency code or name, or «mil»/«k»/«lucas», glued or next to a digit
#: («15 mil», «15mil», «A 20bs», «Por 5usd», «12 lucas», «20 soles», «USD 5»). Written-out
#: numbers («Por veinte mil») are out of reach of a rule and left to the prompt.
_AMOUNT_WORD = (
    r"(?:cop|usd|us\$|ves|uyu|bs\.?|bsf|bss|eur|euros?|pesos?|soles?|bol[ií]vares|"
    r"d[oó]lares?|lucas|mil|k)"
)
_AMOUNT = re.compile(
    rf"\d\s*{_AMOUNT_WORD}(?![a-záéíóúñ])|(?<![a-záéíóúñ]){_AMOUNT_WORD}\s*\d",
    re.IGNORECASE,
)
#: a price figure: a number with a thousands separator or with cents
_SEPARATED = re.compile(r"\b\d{1,3}(?:[.,]\d{3})+\b|\b\d+[.,]\d{2}\b")
#: what a number of 3+ digits may be without being a price: a year, or a quantity with
#: its unit or a percentage («Desde 1998», «Novedades 2026», «500 g», «100% natural»)
_YEAR = re.compile(r"^(?:19|20)\d{2}$")
_UNIT = re.compile(
    r"\s*(?:%|g\b|gr\b|grs\b|gramos\b|kg\b|kilos?\b|ml\b|l\b|litros?\b|cc\b|cm\b|m\b|"
    r"metros?\b|m2\b|m²|unidades\b|piezas\b|porciones\b)",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"\d{3,}")
_PHONE = re.compile(r"(?:\d[\s.-]?){7,}")


def _price_figure(text: str) -> bool:
    if _SEPARATED.search(text):
        return True
    for match in _NUMBER.finditer(text):
        if _YEAR.match(match.group()) or _UNIT.match(text, match.end()):
            continue
        return True
    return False


_HOUR = re.compile(
    r"\b\d{1,2}(?::\d{2})?\s*(?:a\.?\s*m\.?|p\.?\s*m\.?|hrs?\b|h\b)|\b\d{1,2}:\d{2}\b",
    re.IGNORECASE,
)
_SHOUTING = re.compile(r"\b[A-ZÁÉÍÓÚÑÜ]{4,}\b")


def _is_emoji(char: str) -> bool:
    return unicodedata.category(char) == "So" or 0x1F000 <= ord(char) <= 0x1FAFF


def _fold(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text.strip().lower())
    return " ".join("".join(c for c in plain if c.isalnum() or c.isspace()).split())


def free_text_problems(text: str) -> list[str]:
    """Why a title, subtitle or call phrase breaks catalog §1.8 (empty: it passes). No
    datum travels in free text: prices, phones and hours enter only by reference."""
    problems = []
    if _CURRENCY_SYMBOL.search(text) or _AMOUNT.search(text):
        problems.append("currency")
    if _PHONE.search(text):
        problems.append("phone number")
    elif _price_figure(text):
        problems.append("price figure")
    if _HOUR.search(text):
        problems.append("hour")
    if "#" in text:
        problems.append("hashtag")
    if any(_is_emoji(c) for c in text):
        problems.append("emoji")
    if _SHOUTING.search(text):
        problems.append("sustained capitals")
    if text != text.strip() or "\n" in text:
        problems.append("surrounding blanks or line breaks")
    return problems


def _forbidden_title(title: str) -> bool:
    return _fold(title) in {_fold(t) for t in catalog()["forbidden_titles"]}


class LayerSpec(_Strict):
    """The text layer of one image or slide. See the module docstring."""

    spec_version: Literal[1] = SPEC_VERSION
    layout_id: LayoutId
    layout_version: int = LAYOUT_VERSION
    format: Format
    #: What Claude saw in the photo; None only for a layout drawn without one.
    photo: PhotoReading | None = None
    anchor: Anchor | None = None
    container_color: ContainerColor | None = None
    #: Index of ONE word of the title drawn in the brand's accent, or None.
    accent_word: int | None = Field(default=None, ge=0)
    title: str | None = None
    subtitle: str | None = None
    call_phrase: str | None = None
    info_blocks: tuple[InfoBlock, ...] = ()
    price_ref: PriceRef | None = None
    highlight_content: HighlightContent | None = None
    #: `info_card` only: a strip of photo on top (fewer blocks fit, catalog §2.5).
    photo_strip: bool = False
    carousel: CarouselPlace | None = None
    #: What the composition fell back to (catalog §1.7); written by the compositor.
    fallbacks: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _catalog_rules(self) -> LayerSpec:
        layout = catalog()["layouts"][self.layout_id.value]
        problems: list[str] = []
        if self.layout_version != LAYOUT_VERSION:
            problems.append(f"layout_version {self.layout_version} is not {LAYOUT_VERSION}")
        if self.format not in layout["formats"]:
            problems.append(f"{self.layout_id.value} has no {self.format} format")
        # what Claude saw
        needs_photo = (
            self.layout_id in PHOTO_LAYOUTS
            or self.photo_strip
            or (
                self.highlight_content is not None
                and self.highlight_content.kind is HighlightKind.PHOTO
            )
        )
        if needs_photo and self.photo is None:
            problems.append(f"{self.layout_id.value} over a photo needs what was seen in it")
        if self.photo_strip and self.layout_id is not LayoutId.INFO_CARD:
            problems.append("only info_card takes a photo strip")
        # parameters (catalog §1.6)
        anchors = layout["anchors"]
        if anchors and self.anchor is None:
            problems.append(f"{self.layout_id.value} needs an anchor")
        if self.anchor is not None and self.anchor.value not in anchors:
            problems.append(f"{self.layout_id.value} takes no anchor {self.anchor.value}")
        if self.container_color is not None and not layout["container_color"]:
            problems.append(f"{self.layout_id.value} takes no container_color")
        if self.accent_word is not None:
            words = (self.title or "").split()
            if not layout["accent_word"]:
                problems.append(f"{self.layout_id.value} takes no accent_word")
            elif self.accent_word >= len(words):
                problems.append("accent_word is not a word of the title")
        # text slots and their limits (catalog §1.5, §2)
        slots = layout["slots"]
        for name in ("title", "subtitle", "call_phrase"):
            text = getattr(self, name)
            if text is None:
                continue
            limit = (slots.get(name) or {}).get(self.format)
            if limit is None:
                problems.append(f"{self.layout_id.value} {self.format} has no {name}")
                continue
            if not text:
                problems.append(f"{name} is empty: leave it out instead")
            elif len(text) > limit[0]:
                problems.append(f"{name} has {len(text)} chars, at most {limit[0]}")
            problems.extend(f"{name}: {p}" for p in free_text_problems(text))
        if self.layout_id in TITLED_LAYOUTS and not self.title:
            problems.append(f"{self.layout_id.value} needs a title (without one: photo_only)")
        if self.layout_id is LayoutId.INFO_CARD and len(self.info_blocks) != 1 and not self.title:
            problems.append("info_card needs a title unless it shows a single block")
        if self.title and _forbidden_title(self.title):
            problems.append(f"«{self.title}» is a label, not a title")
        if (
            self.layout_id is LayoutId.BAND
            and self.format == "1:1"
            and self.subtitle
            and self.call_phrase
        ):
            problems.append("band 1:1 takes a call_phrase only without a subtitle")
        exclamations = sum(
            (t or "").count("¡") for t in (self.title, self.subtitle, self.call_phrase)
        )
        if exclamations > 1:
            problems.append("at most one «¡…!» per piece")
        # info blocks
        kinds = [b.kind.value for b in self.info_blocks]
        if self.info_blocks and not layout["info_kinds"]:
            problems.append(f"{self.layout_id.value} takes no info blocks")
        elif self.info_blocks or "info_blocks" in layout:
            bounds = layout["info_blocks"][self.format]
            most = bounds["max_with_photo"] if self.photo_strip else bounds["max"]
            if not bounds["min"] <= len(self.info_blocks) <= most:
                problems.append(
                    f"{self.layout_id.value} {self.format} takes {bounds['min']}-{most} blocks"
                )
            for kind in kinds:
                if kind not in layout["info_kinds"]:
                    problems.append(f"{self.layout_id.value} takes no {kind} block")
            if len(set(kinds)) != len(kinds):
                problems.append("an info block kind appears twice")
            value_limit = layout["info_value"][self.format][0]
            for block in self.info_blocks:
                if len(block.value) > value_limit:
                    problems.append(f"{block.kind.value} value over {value_limit} chars")
        # price (founder 2026-11-14: a text line inside the plate or the band only)
        if self.price_ref is not None and not layout["price"]:
            problems.append(f"{self.layout_id.value} prints no price")
        # highlight
        if (self.highlight_content is not None) != (self.layout_id is LayoutId.HIGHLIGHT_CIRCLE):
            problems.append("highlight_content goes with highlight_circle, and only there")
        # carousel roles (catalog §6)
        if self.carousel is not None:
            allowed = catalog()["carousel_roles"][self.carousel.role.value]
            if self.layout_id.value not in allowed:
                problems.append(f"a {self.carousel.role.value} slide takes {', '.join(allowed)}")
            if (
                self.layout_id is LayoutId.INFO_CARD
                and self.carousel.role is CarouselRole.BODY
                and len(self.info_blocks) != 1
            ):
                problems.append("a body slide's info_card shows one block")
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def canonical_json(self) -> str:
        """The spec as stable JSON (sorted keys, no spaces): what is stored and hashed."""
        return json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )

    def spec_sha256(self) -> str:
        """`piece_layers.spec_sha256`: the fingerprint the render key uses (ADR 49 §2.2)."""
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def json_schema() -> dict[str, Any]:
    schema = LayerSpec.model_json_schema()
    schema["$id"] = f"https://qualify.la/schemas/layer_spec_v{SPEC_VERSION}.json"
    schema["description"] = (
        "Qualify LayerSpec v1 (m-25017283). Limits per layout and format live in "
        "catalog_v1.json; this schema states the shape, the Python model enforces the rules."
    )
    return schema


def export_json_schema(path: Path | None = None) -> Path:
    """Write the committed JSON Schema (`layer_spec_v1.schema.json`)."""
    target = path or Path(__file__).with_name(SCHEMA_FILE)
    target.write_text(
        json.dumps(json_schema(), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


if __name__ == "__main__":  # pragma: no cover - `python -m qualify_creative.layer_spec.schema`
    print(export_json_schema())

"""Stage `layer` of the image and carousel pipeline (ADR 49 §2 item 2, §2.3, §2.5;
m-25017283): Claude looks at the stored base photo(s) and writes the text layer — one
`LayerSpec` (`qualify_creative.layer_spec`) per image or slide.

**One call per piece** (ADR 49 §2.5): a single image is one call with its photo; a
carousel is ONE call with its N photos that returns the N layers, so the slides are
written together (one story: cover, body, closing — catalog §6) and the photo tokens are
paid once. Estimated [H] US$0.01-0.02 and 3-8 s per photo (m-25017292 measures).

**Model:** Claude Sonnet 5.5 at low effort (`LAYER_MODEL`): ADR 49 §2.5 prices the layer on
Sonnet, it reads images, and it is the house's current Sonnet (`context_ai`). It thinks,
so — the house rule of `claude_tools` — the tool is offered with `tool_choice: auto` and
the answer must call it (one nudge); no sampling parameters are sent.

**What Claude writes and what it never writes.** It reports what it sees FIRST
(`subject_box`, `logo_in_photo`, `base_has_invented_text`, catalog §1.2), then chooses a
layout from the closed catalog with its parameters and writes the free texts (title,
subtitle, invitation phrase). It never writes a datum: an info block is a KIND, its label
is fixed and its value is the business's saved datum filled here (`BusinessFacts`); a
price is a catalog product id, accepted only if that product has a price, and the
composition prints the catalog's price whole (founder 2026-11-14). Every free text passes
the catalog's rules (§1.8) in `LayerSpec`'s own validation.

**Repair.** A slide whose answer breaks a rule gets ONE repair turn naming exactly the
problems (like the copy adapter's length repair). Still broken: the invitation phrase,
then the subtitle, are dropped (catalog §1.7: the title is never dropped); still broken,
that slide has no layer (`LayerResult.failed`), never a guessed one.

**The base check folded in** (ADR 49 §8.2, founder decision 2): `base_has_invented_text`
is part of this same answer. `LayerResult.invented_text` lists the positions whose
Seedream base shows invented letters, buttons or a logo; the caller regenerates that base
ONCE — the cap is a unique key in the database (`piece_base_regenerations`, 0168), not an
`if` — and asks for that slide's layer again.

**Data:** the photos travel as base64 image blocks, never a public URL; `claude_tools`
replaces every image block with a marker before Langfuse sees the request (ADR 49 §2.5).
Every call is booked to the business in the consumption ledger (`Attribution`), and a
`DollarMeter` caps what one piece may spend on it (`LAYER_BUDGET_USD`).

**Off by default.** Nothing consumes a layer until the Remotion composition ships
(m-25017285): `layer_enabled()` reads `QUALIFY_IMAGE_LAYER` and is false unless it is
`on`. Off, the pipeline does not call this module at all.
"""

from __future__ import annotations

import base64
import logging
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from qualify_creative.layer_spec import (
    LAYOUT_VERSION,
    SPEC_VERSION,
    CarouselRole,
    InfoKind,
    LayerSpec,
    LayoutId,
    catalog,
)
from qualify_shared import observability

from qualify_api.claude_tools import (
    Attribution,
    CallStats,
    ClaudeToolError,
    ClientFactory,
    DollarMeter,
    Meter,
    ModelConfig,
    create_turn,
    default_client,
    forced_or_auto,
    strict_tool,
    tool_uses,
)

logger = logging.getLogger(__name__)

#: The switch (ADR 49, m-25017283): `on` turns the layer stage on; anything else, off.
LAYER_SWITCH_ENV = "QUALIFY_IMAGE_LAYER"
LAYER_MODEL = ModelConfig("claude-sonnet-5-5", effort="low")
#: Prompt provenance (`piece_layers.prompt_version`, the ledger's prompt version).
LAYER_PROMPT_VERSION = "capa-v1"
#: The pipeline that writes `piece_layers` rows (`piece_layers.pipeline_version`).
LAYER_PIPELINE_VERSION = "image-pipeline-layer-v1"
LAYER_TOOL = "escribir_capa"
FEATURE = "capa-de-texto"
#: What one piece may spend on its layer calls, repair and regeneration included [H].
LAYER_BUDGET_USD = Decimal("0.25")
MAX_OUTPUT_TOKENS = 4000
#: The API's per-image limit is 5 MB; a base above it is not sent (no re-encoding here).
MAX_IMAGE_BYTES = 4_500_000
#: [H] tokens of one ~2 MP photo, for the budget's input bound (ADR 49 §2.5: ~1,600).
TOKENS_PER_PHOTO = 1_800


def layer_enabled(env: dict[str, str] | None = None) -> bool:
    """Whether the layer stage runs (`QUALIFY_IMAGE_LAYER=on`). Off by default."""
    value = (env if env is not None else os.environ).get(LAYER_SWITCH_ENV, "")
    return value.strip().lower() == "on"


class LayerError(ClaudeToolError):
    """The layer could not be written at all (refusal, no tool call, budget, no photo)."""


# -- inputs -------------------------------------------------------------------------------


@dataclass(frozen=True)
class BusinessFacts:
    """The business's SAVED data an info block may show (catalog §1.5): only what is here
    can become a block, and its value is exactly this text. None = not saved."""

    location: str | None = None
    hours: str | None = None
    payment: str | None = None
    products: str | None = None
    contact: str | None = None

    def value(self, kind: InfoKind) -> str | None:
        text = getattr(self, kind.value)
        return " ".join(text.split()) if text and text.strip() else None

    def available(self) -> list[InfoKind]:
        return [kind for kind in InfoKind if self.value(kind)]


@dataclass(frozen=True)
class CatalogProduct:
    """A catalog product the piece may reference by id (its price is printed only if it
    has one; the model never sees nor writes the amount)."""

    product_id: UUID
    name: str
    has_price: bool


@dataclass(frozen=True)
class SlideInput:
    """One image of the piece: its position and its base photo (None: drawn without a
    photo, `brand_fill`). `owner_photo` — the owner's own photo, never «invented»."""

    position: int
    photo: bytes | None
    content_type: str = "image/jpeg"
    owner_photo: bool = False


#: The piece types of the catalog's coverage table (§3) this stage serves today.
PRODUCT_PROMOTION = "product_promotion"
FREE_IDEA = "free_idea"
CAROUSEL = "carousel"

#: catalog §3: which layouts a piece type may take (carousel slides: by role, §6).
_COVERAGE: dict[str, tuple[str, ...]] = {
    PRODUCT_PROMOTION: ("plate", "band", "scrim"),
    FREE_IDEA: ("plate", "band", "scrim", "brand_fill", "info_card"),
}


@dataclass(frozen=True)
class LayerRequest:
    """Everything one layer call needs (no network objects)."""

    tenant_id: UUID
    brand_id: UUID
    format: str  # "4:5" | "1:1" | "9:16"
    piece_type: str  # PRODUCT_PROMOTION | FREE_IDEA | CAROUSEL
    slides: tuple[SlideInput, ...]
    brand_name: str = ""
    topic: str = ""
    scene: str = ""
    hook: str = ""
    cta: str = ""
    tone: str = ""
    facts: BusinessFacts = field(default_factory=BusinessFacts)
    products: tuple[CatalogProduct, ...] = ()
    #: A gallery's number of slides when only some are sent (its generated ones): the
    #: roles (cover, body, closing) follow the whole gallery. None: `len(slides)`.
    slide_count: int | None = None

    @property
    def is_carousel(self) -> bool:
        return self.piece_type == CAROUSEL

    @property
    def count(self) -> int:
        return self.slide_count or len(self.slides)


@dataclass
class LayerResult:
    """The layers by position, the positions whose base shows invented text, the
    positions with no valid layer, and the run's cost/provenance."""

    specs: dict[int, LayerSpec]
    invented_text: list[int]
    failed: dict[int, str]
    stats: CallStats | None
    model_id: str = LAYER_MODEL.model_id
    prompt_version: str = LAYER_PROMPT_VERSION
    repairs: int = 0


# -- the tool -----------------------------------------------------------------------------

_LAYOUTS = [layout.value for layout in LayoutId]
_ANCHORS = [
    "none",
    "top_left",
    "top_right",
    "bottom_left",
    "bottom_right",
    "top_center",
    "bottom_center",
    "top",
    "bottom",
]


def _slide_properties(info_kinds: Sequence[str]) -> dict[str, Any]:
    icon_ids = ["none", *catalog()["layouts"]["highlight_circle"]["icon_ids"]]
    return {
        "position": {"type": "integer", "description": "La posición de la imagen (0, 1…)."},
        "foto": {
            "type": "object",
            "description": "Lo que ves en la foto, ANTES de elegir el diseño.",
            "properties": {
                "subject_box": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "[x0, y0, x1, y1] en fracciones de 0 a 1, redondeadas a "
                    "0,05: el rectángulo del producto, la persona o el plato que no se tapa.",
                },
                "logo_in_photo": {"type": "boolean"},
                "base_has_invented_text": {"type": "boolean"},
            },
            "required": ["subject_box", "logo_in_photo", "base_has_invented_text"],
            "additionalProperties": False,
        },
        "layout_id": {"type": "string", "enum": _LAYOUTS},
        "anchor": {"type": "string", "enum": _ANCHORS},
        "container_color": {"type": "string", "enum": ["none", "surface", "accent"]},
        "accent_word": {
            "type": "integer",
            "description": "Índice (desde 0) de UNA palabra del título en color de acento, o -1.",
        },
        "title": {"type": "string"},
        "subtitle": {"type": "string", "description": "Vacío si no lleva."},
        "call_phrase": {"type": "string", "description": "Vacío si no lleva."},
        "info_blocks": {
            "type": "array",
            "items": {"type": "string", "enum": list(info_kinds) or ["none"]},
            "description": "Solo tipos de la lista de datos guardados, en orden.",
        },
        "price_product_id": {
            "type": "string",
            "description": "El id de un producto con precio de la lista, o vacío.",
        },
        "highlight_kind": {"type": "string", "enum": ["none", "icon", "word", "photo"]},
        "highlight_icon_id": {"type": "string", "enum": icon_ids},
        "highlight_word": {"type": "string"},
    }


def layer_tool(info_kinds: Sequence[str]) -> dict[str, Any]:
    slide = {
        "type": "object",
        "properties": _slide_properties(info_kinds),
        "additionalProperties": False,
    }
    slide["required"] = list(slide["properties"])
    return strict_tool(
        LAYER_TOOL,
        "Entrega la capa de texto de cada imagen: primero lo que ves en la foto, después el "
        "diseño del catálogo, sus parámetros y los textos.",
        {"slides": {"type": "array", "items": slide}},
    )


# -- the prompt ---------------------------------------------------------------------------

SYSTEM = """\
Escribes la capa de texto de las publicaciones de pequeños negocios (comida, tiendas, \
inmobiliarias, viajes) de Colombia, Venezuela y Uruguay. Ves la foto y eliges UN diseño de \
un catálogo cerrado; después escribes textos cortos. Un programa compone la imagen final: \
tú no decides colores, tamaños, tipografías ni posiciones en píxeles. Entregas todo con la \
herramienta escribir_capa, una sola vez, con un elemento por imagen.

Primero mira la foto y reporta:
- subject_box: el rectángulo [x0, y0, x1, y1] (fracciones de 0 a 1, redondeadas a 0,05) \
del producto, el plato o la persona: lo que el texto NO puede tapar. Si hay varios, la unión.
- logo_in_photo: true solo si la foto ya muestra el logo real del negocio.
- base_has_invented_text: true si la foto trae letras, palabras, números, botones, \
etiquetas o un logo que no son del producto real ni del logo entregado (letras sin \
sentido, carteles inventados). Si la foto es del dueño, siempre false.

Después elige el diseño (layout_id) según la foto:
- plate (texto en recuadro): hay una zona tranquila (pared lisa, cielo, mesa vacía, fondo \
desenfocado) en una esquina o un borde, de ~45 % del ancho y ~25 % del alto, que no toca \
el sujeto. anchor: top_left, top_right, bottom_left, bottom_right, top_center o \
bottom_center (donde está esa zona). No lo uses si el sujeto llena el cuadro o está en el \
centro sin esquina libre.
- scrim (texto sobre sombra): la mitad de abajo o de arriba es de poca importancia y el \
sujeto termina antes del 55 % del alto (anchor bottom: subject_box y1 <= 0,55; anchor top: \
y0 >= 0,45). Títulos cortos, sin precio. Sin container_color ni accent_word.
- band (franja de color): no hay zona tranquila, el sujeto llena el cuadro, el texto es \
largo o hace falta precio. anchor: top o bottom (el borde más lejos del sujeto). Es la \
opción segura.
- brand_fill (fondo de color, sin foto): un aviso o una frase sin producto que mostrar; \
el cierre de un carrusel.
- info_card (datos del negocio): la pieza es para mostrar datos guardados (dónde, horario, \
formas de pago, lo más pedido, pedidos).
- photo_only (solo la foto): solo en una diapositiva de desarrollo de carrusel donde la \
foto cuenta todo.
- highlight_circle: solo portadas e íconos de historias destacadas.

Parámetros: container_color "surface" o "accent" (en plate, band, info_card y brand_fill; \
"none" en los demás); accent_word: el índice de una palabra del título que va en color de \
acento, o -1 (nunca en scrim ni photo_only); anchor "none" donde el diseño no lleva.

Cómo escribir:
- El título dice qué gana el cliente o qué es el producto («Tu shawarma, recién hecho»), \
nunca una etiqueta: prohibido como título completo «Ubicación», «Horario», «Métodos de \
pago», «Productos», «Promoción», «Información», «Menú».
- Español neutro, sin anglicismos ni modismos de un solo país; sin emojis, sin «#», sin \
palabras en MAYÚSCULAS sostenidas; a lo sumo un «¡…!» en toda la pieza.
- NINGÚN dato en el texto libre: ni precios, ni símbolos de moneda, ni teléfonos, ni horas, \
ni direcciones. Esos datos entran solo por info_blocks (eliges el tipo; el valor sale de \
lo que el negocio guardó) y por price_product_id (eliges el producto; el precio lo pone \
el catálogo). Un «2x1» sí puede ir en el título.
- call_phrase es una invitación en forma de frase («Pídelo por WhatsApp», «Te esperamos \
hoy»), no la etiqueta de un botón. Vacío si no aporta.
- No repitas el nombre del negocio: el logo ya va en la pieza.
- Respeta los límites de caracteres del diseño y el formato que elijas (te los damos)."""


def _limits_text(fmt: str) -> str:
    lines = []
    for layout_id, layout in catalog()["layouts"].items():
        if fmt not in layout["formats"]:
            continue
        parts = []
        for slot in ("title", "subtitle", "call_phrase"):
            limit = (layout["slots"].get(slot) or {}).get(fmt)
            if limit:
                parts.append(f"{slot} ≤ {limit[0]}")
        if layout["price"]:
            parts.append("precio sí")
        if layout.get("info_blocks"):
            bounds = layout["info_blocks"][fmt]
            parts.append(
                f"info_blocks {bounds['min']}-{bounds['max']} ({', '.join(layout['info_kinds'])})"
            )
        lines.append(f"- {layout_id}: {', '.join(parts) or 'sin texto'}")
    return "\n".join(lines)


def _coverage_text(request: LayerRequest) -> str:
    if request.is_carousel:
        roles = catalog()["carousel_roles"]
        return (
            "Es un carrusel de {n} imágenes, en orden. La 1 es la portada (título que da ganas "
            "de deslizar, sin datos: {cover}); las del medio son desarrollo (un producto, un paso "
            "o un dato por imagen, título corto: {body}); la última es el cierre (la invitación y "
            "cómo pedir: {closing}). Paleta y container_color iguales en todas."
        ).format(
            n=request.count,
            cover=", ".join(roles["cover"]),
            body=", ".join(roles["body"]),
            closing=", ".join(roles["closing"]),
        )
    allowed = _COVERAGE.get(request.piece_type, _COVERAGE[FREE_IDEA])
    return f"Es una sola imagen. Diseños posibles, del preferido al último: {', '.join(allowed)}."


def _facts_text(request: LayerRequest) -> str:
    kinds = request.facts.available()
    labels = catalog()["info_blocks"]
    data = (
        "\n".join(f"- {k.value}: «{labels[k.value]['label']}»" for k in kinds)
        if kinds
        else "- (el negocio no tiene datos guardados: no uses info_blocks)"
    )
    products = (
        "\n".join(
            f"- {p.product_id}: {p.name}{' (tiene precio)' if p.has_price else ' (sin precio)'}"
            for p in request.products
        )
        if request.products
        else "- (ninguno: price_product_id vacío)"
    )
    return f"Datos guardados del negocio que puedes mostrar:\n{data}\n\nProductos:\n{products}"


def _brief_text(request: LayerRequest) -> str:
    rows = [
        ("Negocio", request.brand_name),
        ("De qué trata la publicación", request.topic),
        ("Escena pedida", request.scene),
        ("Gancho del texto de la publicación", request.hook),
        ("Invitación del texto de la publicación", request.cta),
        ("Tono de la marca", request.tone),
    ]
    return "\n".join(f"- {name}: {value}" for name, value in rows if value and value.strip())


def _instructions(request: LayerRequest) -> str:
    positions = ", ".join(
        f"{s.position}{' (sin foto)' if s.photo is None else ''}"
        f"{' (foto del dueño)' if s.owner_photo else ''}"
        for s in request.slides
    )
    return (
        f"Formato: {request.format}. Imágenes, en el orden de arriba: {positions}.\n\n"
        f"{_coverage_text(request)}\n\nLímites por diseño en {request.format}:\n"
        f"{_limits_text(request.format)}\n\n{_facts_text(request)}\n\n"
        f"La publicación:\n{_brief_text(request)}\n\nEntrega la capa con {LAYER_TOOL}."
    )


def _image_block(slide: SlideInput) -> dict[str, Any]:
    assert slide.photo is not None
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": slide.content_type,
            "data": base64.standard_b64encode(slide.photo).decode("ascii"),
        },
    }


# -- answer → LayerSpec -------------------------------------------------------------------


def _role(position: int, count: int) -> CarouselRole:
    if position == 0:
        return CarouselRole.COVER
    return CarouselRole.CLOSING if position == count - 1 else CarouselRole.BODY


def _text(value: object) -> str | None:
    text = " ".join(str(value or "").split())
    return text or None


def spec_from_answer(raw: dict[str, Any], request: LayerRequest, slide: SlideInput) -> LayerSpec:
    """One slide of the tool's answer → a validated `LayerSpec`. Raises `ValueError` (a
    `ValidationError` included) naming every broken rule."""
    layout = str(raw.get("layout_id") or "")
    problems: list[str] = []
    allowed = (
        catalog()["carousel_roles"][_role(slide.position, request.count).value]
        if request.is_carousel
        else _COVERAGE.get(request.piece_type, _COVERAGE[FREE_IDEA])
    )
    if layout not in allowed:
        problems.append(f"{layout} is not one of {', '.join(allowed)} for this image")
    info_blocks = []
    for kind_value in raw.get("info_blocks") or []:
        if kind_value == "none":
            continue
        try:
            kind = InfoKind(kind_value)
        except ValueError:
            problems.append(f"unknown info block {kind_value}")
            continue
        value = request.facts.value(kind)
        if value is None:
            problems.append(f"the business has no saved {kind.value}")
            continue
        info_blocks.append(
            {
                "kind": kind.value,
                "label": catalog()["info_blocks"][kind.value]["label"],
                "value": value,
            }
        )
    price_ref = None
    product_id = str(raw.get("price_product_id") or "").strip()
    if product_id:
        priced = {str(p.product_id) for p in request.products if p.has_price}
        if product_id not in priced:
            problems.append(f"{product_id} is not a catalog product with a price")
        else:
            price_ref = {"product_id": product_id}
    highlight = None
    kind = raw.get("highlight_kind")
    if kind and kind != "none":
        highlight = {
            "kind": kind,
            "icon_id": raw.get("highlight_icon_id")
            if raw.get("highlight_icon_id") not in (None, "", "none")
            else None,
            "word": _text(raw.get("highlight_word")),
        }
    photo = raw.get("foto") if slide.photo is not None else None
    if photo is not None and slide.owner_photo:
        photo = {**photo, "base_has_invented_text": False}
    if photo is not None:
        photo = {**photo, "subject_box": [round(float(v) * 20) / 20 for v in photo["subject_box"]]}
    fields: dict[str, Any] = {
        "spec_version": SPEC_VERSION,
        "layout_id": layout,
        "layout_version": LAYOUT_VERSION,
        "format": request.format,
        "photo": photo,
        "anchor": None if raw.get("anchor") in (None, "", "none") else raw["anchor"],
        "container_color": None
        if raw.get("container_color") in (None, "", "none")
        else raw["container_color"],
        "accent_word": None if raw.get("accent_word") in (None, -1) else int(raw["accent_word"]),
        "title": _text(raw.get("title")),
        "subtitle": _text(raw.get("subtitle")),
        "call_phrase": _text(raw.get("call_phrase")),
        "info_blocks": info_blocks,
        "price_ref": price_ref,
        "highlight_content": highlight,
        "photo_strip": layout == "info_card" and slide.photo is not None,
        "carousel": {
            "role": _role(slide.position, request.count).value,
            "index": slide.position,
            "count": request.count,
        }
        if request.is_carousel
        else None,
    }
    try:
        spec = LayerSpec.model_validate(fields)
    except ValidationError as exc:
        problems.extend(str(e["msg"]).removeprefix("Value error, ") for e in exc.errors())
        raise ValueError("; ".join(problems)) from exc
    if problems:
        raise ValueError("; ".join(problems))
    return spec


def _trimmed(raw: dict[str, Any], request: LayerRequest, slide: SlideInput) -> LayerSpec | None:
    """catalog §1.7 on a slide still broken after its repair: drop the invitation phrase,
    then the subtitle; the title is never dropped. None when even that fails."""
    attempt = dict(raw)
    for slot in ("call_phrase", "subtitle"):
        attempt[slot] = ""
        try:
            return spec_from_answer(attempt, request, slide)
        except ValueError:
            continue
    return None


# -- the call -----------------------------------------------------------------------------


def _answer_slides(response: Any) -> tuple[Any, list[dict[str, Any]]] | None:
    calls = [u for u in tool_uses(response) if u.name == LAYER_TOOL]
    if not calls:
        return None
    payload = calls[0].input or {}
    slides = payload.get("slides") if isinstance(payload, dict) else None
    return calls[0], [s for s in slides or [] if isinstance(s, dict)]


@observability.traced("capa de texto", tags=("creative", "image_pipeline"))
def write_layers(
    request: LayerRequest,
    *,
    api_key: str,
    config: ModelConfig = LAYER_MODEL,
    client_factory: ClientFactory | None = None,
    budget: DollarMeter | None = None,
) -> LayerResult:
    """One call for the piece's images → a `LayerSpec` per position (see the module
    docstring). Raises `LayerError` when there is no answer at all."""
    for slide in request.slides:
        if slide.photo is not None and len(slide.photo) > MAX_IMAGE_BYTES:
            raise LayerError(f"the photo of position {slide.position} is over 5 MB")
    client = (client_factory or default_client)(api_key)
    meter = Meter(config)
    budget = budget or DollarMeter(LAYER_BUDGET_USD)
    attribution = Attribution(
        tenant_id=request.tenant_id,
        brand_id=request.brand_id,
        feature=FEATURE,
        prompt_version=LAYER_PROMPT_VERSION,
    )
    kinds = [k.value for k in request.facts.available()]
    tool = layer_tool(kinds)
    content: list[dict[str, Any]] = []
    for slide in request.slides:
        if slide.photo is not None:
            content.append({"type": "text", "text": f"Imagen {slide.position}:"})
            content.append(_image_block(slide))
    content.append({"type": "text", "text": _instructions(request)})
    messages: list[dict[str, Any]] = [{"role": "user", "content": content}]
    photos = sum(1 for s in request.slides if s.photo is not None)
    ceiling = photos * TOKENS_PER_PHOTO + (len(SYSTEM) + len(_instructions(request))) // 2 + 3000

    def turn() -> Any:
        try:
            return create_turn(
                client,
                config,
                meter,
                system=SYSTEM,
                messages=messages,
                tools=[tool],
                tool_choice=forced_or_auto(config, LAYER_TOOL),
                max_tokens=MAX_OUTPUT_TOKENS,
                attribution=attribution,
                budget=budget,
                input_ceiling=ceiling + 2000 * (len(messages) - 1),
            )
        except ClaudeToolError as exc:
            raise LayerError(str(exc), stats=exc.stats or meter.stats()) from exc

    response = turn()
    answer = _answer_slides(response)
    if answer is None:
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": f"Entrega la capa con {LAYER_TOOL}."})
        response = turn()
        answer = _answer_slides(response)
        if answer is None:
            raise LayerError(f"{config.model_id} did not call {LAYER_TOOL}", stats=meter.stats())
    meter.tool_calls += 1
    use, raws = answer
    by_position = {s.position: s for s in request.slides}
    raw_of: dict[int, dict[str, Any]] = {}
    for raw in raws:
        position = raw.get("position")
        if isinstance(position, int) and position in by_position and position not in raw_of:
            raw_of[position] = raw
    result = LayerResult(specs={}, invented_text=[], failed={}, stats=None)
    broken: dict[int, str] = {}
    for position, slide in by_position.items():
        raw = raw_of.get(position)
        if raw is None:
            broken[position] = "no layer for this image"
            continue
        try:
            result.specs[position] = spec_from_answer(raw, request, slide)
        except ValueError as exc:
            broken[position] = str(exc)
    if broken:
        result.repairs = 1
        messages.append({"role": "assistant", "content": response.content})
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": use.id,
                        "is_error": True,
                        "content": "Corrige SOLO estas imágenes y vuelve a entregar la capa "
                        f"completa con {LAYER_TOOL}:\n"
                        + "\n".join(f"- imagen {p}: {why}" for p, why in sorted(broken.items())),
                    }
                ],
            }
        )
        try:
            repaired = _answer_slides(turn())
        except LayerError as exc:
            logger.warning("layer repair failed: %s", exc)
            repaired = None
        fixed = {
            r.get("position"): r
            for r in (repaired[1] if repaired else [])
            if isinstance(r.get("position"), int)
        }
        for position, why in broken.items():
            slide = by_position[position]
            raw = fixed.get(position) or raw_of.get(position)
            spec = None
            if raw is not None:
                try:
                    spec = spec_from_answer(raw, request, slide)
                except ValueError as exc:
                    why = str(exc)
                    spec = _trimmed(raw, request, slide)
            if spec is None:
                result.failed[position] = why[:500]
            else:
                result.specs[position] = spec
    result.invented_text = sorted(
        position
        for position, spec in result.specs.items()
        if spec.photo is not None
        and spec.photo.base_has_invented_text
        and not by_position[position].owner_photo
    )
    result.stats = meter.stats()
    return result


__all__ = [
    "CAROUSEL",
    "FEATURE",
    "FREE_IDEA",
    "LAYER_MODEL",
    "LAYER_PIPELINE_VERSION",
    "LAYER_PROMPT_VERSION",
    "LAYER_SWITCH_ENV",
    "PRODUCT_PROMOTION",
    "BusinessFacts",
    "CatalogProduct",
    "LayerError",
    "LayerRequest",
    "LayerResult",
    "SlideInput",
    "layer_enabled",
    "layer_tool",
    "spec_from_answer",
    "write_layers",
]

#: For the caller's type hints: what builds a `LayerResult` from a request.
LayerWriter = Callable[[LayerRequest], LayerResult]

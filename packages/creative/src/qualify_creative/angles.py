"""The visual angles engine — pure: shapes, prompts, parsing and checks, no I/O.

Ticket 24803289 (Meegle): from ONE catalog product and a creative preset, ten proposals
that differ in what the picture SHOWS — scenario, composition, focus — not merely in the
words. This is a different thing from the five copy angles of `brand.render.VARIANT_ANGLES`
(those rotate the opening of the text) and from ADR 32's earned-media angle engine (which
starts from what the category is saying; gated on the analytical plane). This one starts
from the product the brand sells and the brand kit it already has.

What lives here:

- `AnglePreset` — the "template or preset" the operator picks: which engine composes
  the piece (a Seedream scene with the words and the price laid over locally, or the
  Remotion `promo_producto` template fed with the generated scene), the format and the
  style words the prompt carries.
- `CreativeAngle` — one structured angle as Claude returns it, bounded field by field.
- `angles_tool` / `angles_system_prompt` / `angles_user_prompt` — the strict tool call
  the API layer makes (`qualify_api.creative.angles_ai`); the prompt names the price
  as data to keep exact, never to invent.
- `parse_angles` + `distinct_problems` — a sloppy answer is bounded, duplicates are
  dropped, and an answer that is not ten distinct scenarios is reported, not accepted.
- `price_conflicts` / `price_problem` — the guard that catches a copy quoting a price
  other than the catalog's (the piece's price is drawn from the catalog, never from the
  model), and the one sentence every approval path refuses with.
- `angle_brief` — the `ContentBrief` ONE angle becomes, so each proposal rides the
  existing generation pipeline (`ContentService.create_draft` → `MediaProducer`)
  unchanged: one draft per angle, retried alone, reviewed in `/drafts`.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from qualify_creative.adapters.anthropic_copy import strict_schema
from qualify_creative.enums import (
    AdImageMode,
    AwarenessLevel,
    BriefIntent,
    BriefObjective,
    ContentFormat,
    ContentKind,
    ContentType,
    ImageRoute,
)
from qualify_creative.schemas import (
    HIGHLIGHT_KEY_MAX,
    HIGHLIGHT_VALUE_MAX,
    HIGHLIGHTS_MAX,
    MAX_PRODUCT_IMAGES,
    PRICE_LINE_MAX,
    SCENE_PROMPT_MAX,
    BriefConstraints,
    ContentBrief,
    MediaInputs,
)

#: How many angles a set asks for by default, and the bounds a caller may move within.
DEFAULT_ANGLE_COUNT = 10
MIN_ANGLE_COUNT = 3
MAX_ANGLE_COUNT = 12

#: Field caps — what a card can show and what a scene prompt may carry.
TITLE_MAX = 60
SCENE_MAX = 400
COMPOSITION_MAX = 200
HOOK_MAX = 80
CTA_MAX = 40
RATIONALE_MAX = 200

#: The highlight name the price travels under in «Datos clave» — the copy prompt tells
#: the model to state every highlight exactly as written.
PRICE_HIGHLIGHT = "precio"

#: Two scenes closer than this (token Jaccard) are the same scenario twice.
_SIMILARITY_LIMIT = 0.6


# -- presets -----------------------------------------------------------------------------


@dataclass(frozen=True)
class AnglePreset:
    """What the operator picks before the angles: which engine composes the piece, in
    which format, with which style words in the scene prompt.

    `engine`:
    - ``ad_image`` — `ContentKind.STATIC_FLYER`: Seedream photographs the product (the
      catalog's photos as references) in the angle's scene; the hook, the CTA, the real
      logo and the price are laid over locally (`compose.render_ad_slides`). The default:
      it is what makes ten pictures ten different scenarios.
    - ``template`` — `ContentKind.TEMPLATE`: the same generated scene, handed to the
      Remotion template as its first photo, with the price in the template's own
      `price_line` port. Needs the render service (`QUALIFY_RENDER_URL`).
    """

    key: str
    name: str
    description: str
    engine: str
    format: ContentFormat
    style: str
    icon: str = "image"
    template_id: str | None = None

    @property
    def kind(self) -> ContentKind:
        return ContentKind.TEMPLATE if self.engine == "template" else ContentKind.STATIC_FLYER

    @property
    def needs_render_service(self) -> bool:
        return self.engine == "template"


PRESETS: tuple[AnglePreset, ...] = (
    AnglePreset(
        key="escena_producto",
        name="Escena fotográfica",
        description=(
            "Tu producto real fotografiado en diez escenarios distintos, con tu texto y "
            "tu logo encima. Feed 4:5."
        ),
        engine="ad_image",
        format=ContentFormat.FEED_4_5,
        style=(
            "professional advertising photograph, photorealistic, natural light, premium, "
            "the product sharp and the hero of the frame"
        ),
        icon="image",
    ),
    AnglePreset(
        key="historia_vertical",
        name="Historia vertical",
        description=(
            "Las mismas diez escenas pensadas para historia 9:16: encuadre vertical, "
            "producto grande y texto corto."
        ),
        engine="ad_image",
        format=ContentFormat.STORY_9_16,
        style=(
            "vertical social story photograph, photorealistic, bold close framing, the "
            "product large and centred, clean calm areas top and bottom"
        ),
        icon="smartphone",
    ),
    AnglePreset(
        key="plantilla_promo",
        name="Plantilla de marca",
        description=(
            "Cada escena generada entra en la plantilla «Promo de producto» (Remotion) con "
            "tus fotos reales, el gancho, el CTA y el precio como texto de la plantilla."
        ),
        engine="template",
        format=ContentFormat.FEED_4_5,
        style=(
            "clean advertising photograph for a branded template, photorealistic, soft "
            "natural light, uncluttered background, the product centred"
        ),
        icon="layout-template",
        template_id="promo_producto",
    ),
)
PRESETS_BY_KEY: Mapping[str, AnglePreset] = {preset.key: preset for preset in PRESETS}
DEFAULT_PRESET_KEY = PRESETS[0].key


class UnknownPreset(KeyError):
    """No preset with that key."""


def preset_by_key(key: str) -> AnglePreset:
    try:
        return PRESETS_BY_KEY[key]
    except KeyError:
        raise UnknownPreset(key) from None


# -- inputs ------------------------------------------------------------------------------


@dataclass(frozen=True)
class AngleProduct:
    """What the catalog knows about the product the set is about. `price_label` is the
    catalog's formatted price ("" when the product has none — then NO price is shown
    anywhere and the operator is told so); `photo_keys` are store keys, hero first."""

    product_id: UUID
    name: str
    description: str = ""
    category: str = ""
    tags: tuple[str, ...] = ()
    price_label: str = ""
    photo_keys: tuple[str, ...] = ()

    @property
    def has_price(self) -> bool:
        return bool(self.price_label.strip())


@dataclass(frozen=True)
class AngleBrand:
    """The brand as the prompt needs it — a few strings, every one optional."""

    name: str = ""
    positioning: str = ""
    audience: str = ""
    sector: str = ""
    location: str = ""
    palette: tuple[str, ...] = ()
    #: The Brand Kit's one type face (`BrandKit.typeface`; "" = not declared).
    typeface: str = ""
    #: The owner's business perks (`BrandKit.business_perks`), already normalized: the
    #: only venue facts (parking, hours, combos…) an angle may state. Empty = none.
    perks: tuple[str, ...] = ()


# -- the angle ---------------------------------------------------------------------------


def _clean(text: object, limit: int) -> str:
    joined = " ".join(str(text or "").split())
    return joined[:limit].strip()


def awareness_level_or_none(value: object) -> AwarenessLevel | None:
    """A level as stored or answered: a member, its value (any case/spacing), or None —
    a missing or unknown level never sinks an angle (or a whole set)."""
    if isinstance(value, AwarenessLevel):
        return value
    try:
        return AwarenessLevel(str(value or "").strip().lower())
    except ValueError:
        return None


def level_plan(
    count: int, existing: Iterable[AwarenessLevel | None] = ()
) -> tuple[tuple[AwarenessLevel, int], ...]:
    """How many of `count` NEW angles go to each level so the whole set — `existing`
    plus the new ones — is spread across the five levels as evenly as possible: the
    total split in equal shares, the remainder going to the first levels from
    `UNAWARE` on (10 → 2 each; 3 → unaware, problem_aware, solution_aware), minus what
    `existing` already covers. Levels with nothing to add are left out."""
    if count <= 0:
        return ()
    levels = tuple(AwarenessLevel)
    have = list(existing)
    total = len(have) + count
    base, extra = divmod(total, len(levels))
    need = {
        level: max(0, base + (1 if i < extra else 0) - have.count(level))
        for i, level in enumerate(levels)
    }
    # existing angles without a level (or crowding one level) leave the sum off by a
    # few: trim from the last levels, or top up from the first, until it is `count`
    while sum(need.values()) > count:
        level = next(lv for lv in reversed(levels) if need[lv] > 0)
        need[level] -= 1
    i = 0
    while sum(need.values()) < count:
        need[levels[i % len(levels)]] += 1
        i += 1
    return tuple((level, need[level]) for level in levels if need[level] > 0)


class CreativeAngle(BaseModel):
    """One visual angle: what the picture shows (`scene`), how it is framed
    (`composition`), the line it opens with (`hook`), the call to action and why this
    angle sells this product (`rationale`). `position` is 1-based, the order Claude
    proposed them in."""

    model_config = ConfigDict(frozen=True)

    position: int = Field(ge=1, le=MAX_ANGLE_COUNT)
    title: str = Field(min_length=1, max_length=TITLE_MAX)
    scene: str = Field(min_length=1, max_length=SCENE_MAX)
    composition: str = Field(default="", max_length=COMPOSITION_MAX)
    hook: str = Field(default="", max_length=HOOK_MAX)
    cta: str = Field(default="", max_length=CTA_MAX)
    rationale: str = Field(default="", max_length=RATIONALE_MAX)
    #: Which reader this angle speaks to (Schwartz); None on angles proposed before the
    #: levels existed, or when the answer named none (or an unknown one).
    awareness_level: AwarenessLevel | None = None

    @field_validator("title", "scene", "composition", "hook", "cta", "rationale", mode="before")
    @classmethod
    def _single_spaced(cls, value: object) -> str:
        return " ".join(str(value or "").split())

    @field_validator("awareness_level", mode="before")
    @classmethod
    def _known_level(cls, value: object) -> AwarenessLevel | None:
        return awareness_level_or_none(value)

    @property
    def scene_prompt(self) -> str:
        """The scene as `MediaInputs.scene_prompt` carries it: the scenario, then the
        framing, within the prompt's own cap."""
        text = self.scene
        if self.composition:
            text = f"{text}. Composición: {self.composition}"
        return text[:SCENE_PROMPT_MAX].strip()


#: Appended to the scene prompt of every take after the first: the SAME scenario, shot
#: differently — what «Regenerar» promises. Image generation is stochastic already; the
#: note keeps the model from landing on the same framing twice.
TAKE_NOTE = (
    "Toma alternativa nº {take}: el mismo escenario, pero con otro ángulo de cámara, otra "
    "disposición de los elementos y otra luz que en la toma anterior."
)


def take_scene_prompt(angle: CreativeAngle, take: int = 1) -> str:
    """`angle.scene_prompt` for the first take; from the second on, the scene with
    `TAKE_NOTE` — the scene trimmed first so the note is never the part that gets cut."""
    if take <= 1:
        return angle.scene_prompt
    note = TAKE_NOTE.format(take=take)
    room = SCENE_PROMPT_MAX - len(note) - 1
    return f"{angle.scene_prompt[:room].rstrip()} {note}"


def _tokens(text: str) -> frozenset[str]:
    folded = unicodedata.normalize("NFKD", text.casefold())
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return frozenset(tok for tok in re.findall(r"[a-z0-9]+", folded) if len(tok) > 2)


def _similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def parse_angles(
    payload: Any,
    *,
    count: int = DEFAULT_ANGLE_COUNT,
    existing: Sequence[CreativeAngle] = (),
) -> tuple[CreativeAngle, ...]:
    """The tool's arguments into bounded `CreativeAngle`s, in order, duplicates (same
    title, or near-identical scene — among themselves and against `existing`) dropped,
    at most `count` in total counting `existing` (and never more than
    `MAX_ANGLE_COUNT`); positions continue after it. Tolerates a sloppy payload: wrong
    types, empty rows and extra keys are skipped, never raised on."""
    rows = payload.get("angles") if isinstance(payload, Mapping) else payload
    if not isinstance(rows, list):
        return ()
    # positions are bounded (`CreativeAngle.position`): a set never exceeds the cap
    count = min(count, MAX_ANGLE_COUNT)
    out: list[CreativeAngle] = list(existing)
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        title = _clean(row.get("title"), TITLE_MAX)
        scene = _clean(row.get("scene"), SCENE_MAX)
        if not title or not scene:
            continue
        if any(
            a.title.casefold() == title.casefold()
            or _similarity(a.scene, scene) >= _SIMILARITY_LIMIT
            for a in out
        ):
            continue
        out.append(
            CreativeAngle(
                position=len(out) + 1,
                title=title,
                scene=scene,
                composition=_clean(row.get("composition"), COMPOSITION_MAX),
                hook=_clean(row.get("hook"), HOOK_MAX),
                cta=_clean(row.get("cta"), CTA_MAX),
                rationale=_clean(row.get("rationale"), RATIONALE_MAX),
                awareness_level=awareness_level_or_none(row.get("awareness_level")),
            )
        )
        if len(out) == count:
            break
    return tuple(out[len(existing) :])


def distinct_problems(angles: Sequence[CreativeAngle], *, minimum: int) -> tuple[str, ...]:
    """Why a set of angles is not acceptable: fewer than `minimum`, or two that show the
    same scenario. Empty when the set is fine."""
    problems: list[str] = []
    if len(angles) < minimum:
        problems.append(f"only {len(angles)} distinct angles, {minimum} needed")
    for i, a in enumerate(angles):
        for b in angles[i + 1 :]:
            if a.title.casefold() == b.title.casefold():
                problems.append(f"angles {a.position} and {b.position} share the title")
            elif _similarity(a.scene, b.scene) >= _SIMILARITY_LIMIT:
                problems.append(f"angles {a.position} and {b.position} show the same scene")
    return tuple(problems)


# -- the Claude call's shape -------------------------------------------------------------

ANGLES_TOOL = "proponer_angulos_visuales"

SYSTEM_PROMPT = """\
Eres director creativo de publicidad para redes sociales de negocios locales. Recibes UN \
producto real de un negocio (con su nombre, descripción, categoría y, si existe, su \
precio registrado) y una breve descripción de la marca, y propones ángulos creativos \
VISUALES: escenarios y composiciones distintas en las que fotografiar ese mismo producto \
para anunciarlo. Entregas la respuesta con la herramienta proponer_angulos_visuales, una \
sola vez.

Reglas:
- Cada ángulo es una ESCENA diferente: cambia el lugar, la superficie, la luz, el momento, \
la compañía o el enfoque (uso, ingrediente, regalo, rutina, contraste, detalle macro…). \
Dos ángulos nunca comparten escenario ni composición. No vale cambiar solo el texto.
- El producto es el protagonista y debe reconocerse tal cual es: nunca propongas \
cambiar su forma, color, etiqueta ni envase. Describe lo que lo rodea, no el producto.
- scene: la escena en español, concreta y fotografiable, 1 o 2 frases: dónde está el \
producto, sobre qué, con qué luz, qué lo acompaña. Sin texto dibujado dentro de la \
imagen, sin personas reconocibles, sin marcas ajenas.
- composition: encuadre y disposición (plano, ángulo de cámara, dónde queda el \
producto, qué zona queda limpia para el texto), una frase.
- hook: una línea de apertura en español, corta, en el tono de la marca, coherente con \
la escena.
- cta: una llamada a la acción breve.
- rationale: por qué este ángulo vende este producto a este público, una frase.
- El precio es un DATO del catálogo: si te lo dan, puedes mencionarlo tal cual, sin \
redondear, sin cambiar la moneda, sin inventar descuentos (nunca en el nivel unaware). Si \
no te lo dan, no inventes ninguno ni insinúes una cifra.
- No inventes atributos del producto que no estén en su descripción. No prometas \
resultados ni hagas afirmaciones de salud.
- Títulos únicos, de pocas palabras, que distingan cada ángulo de un vistazo.

Niveles de consciencia (Eugene Schwartz): cada ángulo le habla a UNO de estos cinco \
públicos y lo declaras en awareness_level. Reparte los ángulos entre los niveles \
exactamente como lo indica el pedido; dentro de un mismo nivel, las escenas siguen siendo \
distintas.
- unaware: todavía no piensa en el producto. Muestra el lugar y la experiencia (el \
ambiente, el momento, con quién se comparte), no el precio. Usa solo las ventajas de la \
experiencia (el lugar, el ambiente, las mesas, las mascotas, el parqueadero como \
comodidad); los horarios, las formas de pago, los precios y todo lo que hable de costo \
quedan para product_aware y most_aware. Nunca menciones el precio ni una oferta.
- problem_aware: ya siente la necesidad («¿qué cenamos hoy?»). Nombra ese dilema en el \
hook y presenta la propuesta como la respuesta.
- solution_aware: sabe qué tipo de cosa quiere, pero no dónde. Muestra lo que distingue \
a este negocio con al menos un dato concreto de la descripción del producto o una ventaja \
de la lista, dicho tal cual. No basta con repetir qué es el producto, ni con frases \
genéricas (fresco, de calidad, expertos, pensado para ti), ni con atributos que no estén \
en los datos; los precios, las formas de pago y los horarios quedan para product_aware.
- product_aware: conoce el negocio pero duda. Quita la fricción: el precio claro si existe, \
el horario, cómo pagar, dónde queda — solo con los datos que te dieron.
- most_aware: está listo para comprar. El camino más corto a la compra: hook y cta muy \
breves y directos, sin explicaciones largas. El cta usa solo una forma de comprar que esté \
en los datos (la lista, el producto o la marca); si no hay ninguna, invita a venir o a \
escribir, sin nombrar un servicio: ni reservar, ni para llevar, ni recoger, ni domicilio.

Datos reales del negocio:
- La lista «Lo que ofrece el negocio» son hechos que escribió el dueño. Úsalos tal cual, \
cada ángulo los que encajen con su nivel; no hace falta usarlos todos. El nivel manda: \
una ventaja que no encaja con el nivel del ángulo se deja fuera aunque sea cierta.
- Nunca inventes un dato que no esté en esa lista, en los datos del producto o en la \
marca: ni horarios, ni precios, ni formas de pago, ni direcciones, ni domicilios, ni \
descuentos, ni promociones. Si un nivel pediría un dato que no tienes, apóyate en lo que \
sí está.
- Cada ventaja se repite con su propio significado: nunca la conviertas en gratis, regalo, \
incluido, descuento ni promoción si su texto no lo dice.
- No ofrezcas ningún servicio que no esté en la lista, en el producto o en la marca (ni \
reservas, ni domicilios, ni apartar)."""


def angles_tool(count: int = DEFAULT_ANGLE_COUNT) -> dict[str, Any]:
    """The strict tool: `count` angles asked for, every field required. Structured
    outputs reject array bounds other than `minItems` 0 or 1, so `strict_schema` moves
    the exact count into the schema's description (as the SDK's own transform does) and
    `parse_angles` enforces it on the answer."""
    return {
        "name": ANGLES_TOOL,
        "description": (
            f"Entrega exactamente {count} ángulos creativos visuales, todos distintos entre sí."
        ),
        "strict": True,
        "input_schema": strict_schema(
            {
                "type": "object",
                "properties": {
                    "angles": {
                        "type": "array",
                        "minItems": count,
                        "maxItems": count,
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "scene": {"type": "string"},
                                "composition": {"type": "string"},
                                "hook": {"type": "string"},
                                "cta": {"type": "string"},
                                "rationale": {"type": "string"},
                                "awareness_level": {
                                    "type": "string",
                                    "enum": [level.value for level in AwarenessLevel],
                                },
                            },
                            "required": [
                                "title",
                                "scene",
                                "composition",
                                "hook",
                                "cta",
                                "rationale",
                                "awareness_level",
                            ],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["angles"],
            }
        ),
    }


def angles_system_prompt() -> str:
    return SYSTEM_PROMPT


def angles_user_prompt(
    product: AngleProduct,
    brand: AngleBrand,
    preset: AnglePreset,
    *,
    count: int = DEFAULT_ANGLE_COUNT,
    avoid: Sequence[CreativeAngle] = (),
) -> str:
    """The volatile half: the product, the brand and the preset, then the ask. `avoid`
    lists angles already proposed (a top-up call after duplicates were dropped): the
    new ones must differ from every one of them."""
    lines = [
        "== Producto (del catálogo del negocio) ==",
        f"Nombre: {product.name}",
        f"Descripción: {product.description or '(sin descripción)'}",
        f"Categoría: {product.category or '(sin categoría)'}",
        f"Etiquetas: {', '.join(product.tags) if product.tags else '(ninguna)'}",
        (
            f"Precio registrado: {product.price_label} (dato exacto del catálogo)"
            if product.has_price
            else "Precio registrado: NO HAY. No menciones ningún precio ni cifra."
        ),
        f"Fotos reales disponibles: {len(product.photo_keys)}",
        "",
        "== Marca ==",
        f"Nombre: {brand.name or '(sin nombre)'}",
        f"Rubro: {brand.sector or '(sin rubro)'}",
        f"Ubicación: {brand.location or '(sin ubicación)'}",
        f"Posicionamiento: {brand.positioning or '(sin posicionamiento)'}",
        f"Público: {brand.audience or '(sin público definido)'}",
        f"Paleta: {', '.join(brand.palette[:4]) if brand.palette else '(sin paleta)'}",
        f"Tipografía: {brand.typeface or '(sin tipografía)'}",
        "",
        "== Lo que ofrece el negocio (datos reales escritos por el dueño) ==",
        *(
            (f"- {perk}" for perk in brand.perks)
            if brand.perks
            else ("(el dueño no anotó ninguno: usa solo los datos del producto y de la marca)",)
        ),
        "",
        "== Preset creativo ==",
        f"{preset.name}: {preset.description}",
        f"Formato: {preset.format.aspect_ratio}. Estilo fotográfico: {preset.style}.",
        "",
    ]
    if avoid:
        lines.append("== Ángulos ya propuestos (NO los repitas ni los parafrasees) ==")
        lines.extend(
            f"- [{a.awareness_level.value if a.awareness_level else 'sin nivel'}] "
            f"{a.title}: {a.scene}"
            for a in avoid
        )
        lines.append("")
    plan = level_plan(count, (a.awareness_level for a in avoid))
    if plan:
        lines.append("== Reparto por nivel de consciencia ==")
        lines.extend(f"- {level.value}: {n}" for level, n in plan)
        lines.append("")
    lines.append(
        f"Propón {count} ángulos visuales distintos para anunciar este producto con {ANGLES_TOOL}."
    )
    return "\n".join(lines)


# -- the price guard ---------------------------------------------------------------------

_MONEY = re.compile(
    r"(?:(?:USD|US\$|COP|MXN|EUR|ARS|CLP|PEN|VES|Bs\.?|S/\.?|\$|€)\s?\d[\d.,]*"
    r"|\d[\d.,]*\s?(?:USD|COP|MXN|EUR|ARS|CLP|PEN|VES|Bs\.?|€|pesos|dólares|dolares|soles"
    # a suffix ends the word: "6 copas" or "2 pendientes" are not prices
    r"|bolívares|bolivares)(?![^\W\d_]))",
    re.IGNORECASE,
)
_DIGITS = re.compile(r"\d[\d.,]*")


def _amount(text: str) -> Decimal | None:
    """The number inside a money token, tolerant of thousands separators written either
    way ("12.500", "12,500", "12.50")."""
    match = _DIGITS.search(text)
    if match is None:
        return None
    raw = match.group(0).rstrip(".,")
    if "," in raw and "." in raw:
        # the last separator is the decimal one
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        head, _, tail = raw.rpartition(",")
        raw = f"{head.replace(',', '')}.{tail}" if len(tail) in (1, 2) else raw.replace(",", "")
    elif raw.count(".") > 1 or ("." in raw and len(raw.rpartition(".")[2]) == 3):
        raw = raw.replace(".", "")
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def price_mentions(text: str) -> tuple[str, ...]:
    """Every money-looking token in `text`, as written (a trailing comma or full stop
    belongs to the sentence, not to the figure)."""
    return tuple(m.group(0).strip().rstrip(".,") for m in _MONEY.finditer(text or ""))


def price_conflicts(texts: Iterable[str], price_label: str) -> tuple[str, ...]:
    """The money tokens in `texts` whose amount is NOT the catalog's. With no catalog
    price, every money token is a conflict (the model had none to quote). What a piece
    prints is drawn from the catalog regardless; this guard is for the copy."""
    # the label's own money token ("2x $10" is 10, not 2); its first number otherwise
    label_tokens = price_mentions(price_label)
    expected = (
        _amount(label_tokens[0] if label_tokens else price_label) if price_label.strip() else None
    )
    conflicts: list[str] = []
    for text in texts:
        for token in price_mentions(text):
            amount = _amount(token)
            if amount is None:
                continue
            if expected is None or amount != expected:
                conflicts.append(token)
    return tuple(dict.fromkeys(conflicts))


def price_problem(texts: Iterable[str], price_label: str) -> str | None:
    """Why a copy may not be approved under requirement 8, in the operator's Spanish —
    None when it may: no figure at all, or only the catalog's price. The two refusals are
    told apart: a figure other than the catalog's, and any figure for a product the
    catalog has no price for (the model had none to quote, so it invented one). Only a
    money token counts (`price_mentions`): "6 copas" or "2x1" are not prices."""
    conflicts = price_conflicts(texts, price_label)
    if not conflicts:
        return None
    shown = ", ".join(conflicts)
    if price_label.strip():
        return (
            f"El texto menciona {shown}, que no es el precio del catálogo ({price_label}). "
            "Corrígelo antes de aprobar."
        )
    return (
        f"El producto no tiene precio en el catálogo, así que el texto no puede mencionar "
        f"uno ({shown}). Quítalo antes de aprobar."
    )


# -- one angle → one brief ---------------------------------------------------------------


def preset_problem(preset: AnglePreset, product: AngleProduct) -> str | None:
    """Why `preset` cannot make pieces of `product`, in the operator's Spanish — checked
    BEFORE the angles are paid for; None when it can. A template composes the product's
    real photos (`ContentBrief` refuses a template without one)."""
    if preset.kind is ContentKind.TEMPLATE and not product.photo_keys:
        return (
            f"La plantilla «{preset.name}» necesita al menos una foto real del producto. "
            "Súbela en el catálogo o elige otro preset."
        )
    return None


def _extra_facts(facts: Sequence[tuple[str, str]], *, room: int) -> list[tuple[str, str]]:
    """The caller's extra highlights a brief can carry: trimmed, never blank, never past
    the schema's lengths (skipped, not cut), never a second «precio» (the catalog's is the
    only one), at most `room` of them."""
    kept: list[tuple[str, str]] = []
    for name, fact in facts:
        name, fact = " ".join(str(name).split()), " ".join(str(fact).split())
        if not name or not fact or name.casefold() == PRICE_HIGHLIGHT:
            continue
        if len(name) > HIGHLIGHT_KEY_MAX or len(fact) > HIGHLIGHT_VALUE_MAX:
            continue
        kept.append((name, fact))
        if len(kept) >= room:
            break
    return kept


def angle_brief(
    *,
    angle: CreativeAngle,
    preset: AnglePreset,
    product: AngleProduct,
    brand_id: UUID,
    brand_logo_key: str | None = None,
    extra_highlights: Sequence[tuple[str, str]] = (),
    take: int = 1,
) -> ContentBrief:
    """The `ContentBrief` this angle becomes — one draft of the existing pipeline.

    The product's photos are the references (`product_keys`), the angle's scene is the
    `scene_prompt`, and the price travels twice, both times from the catalog: as the
    «precio» highlight (the copy prompt states highlights exactly as written) and as
    `price_line`, the text the composition prints — so the picture never shows a price
    the model made up. No catalog price → neither is set and nothing is printed.
    `take` numbers the attempt: from the second on the scene asks for a different shot
    of the same scenario (`take_scene_prompt`).

    The angle's awareness level rides the brief and sets its objective
    (`AwarenessLevel.objective`; an angle without one stays a SALE, as before the
    levels). An `UNAWARE` angle shows the place, not the price: its brief carries no
    price at all — nothing to mention, nothing printed (whole or not at all).
    """
    level = angle.awareness_level
    shows_price = product.has_price and level is not AwarenessLevel.UNAWARE
    photos = tuple(product.photo_keys[:MAX_PRODUCT_IMAGES])
    highlights: list[tuple[str, str]] = []
    if shows_price:
        highlights.append((PRICE_HIGHLIGHT, product.price_label.strip()))
    highlights.extend(_extra_facts(extra_highlights, room=HIGHLIGHTS_MAX - len(highlights)))
    label = product.price_label.strip() if shows_price else ""
    topic_parts = [product.name.strip(), angle.title]
    if angle.rationale:
        topic_parts.append(angle.rationale)
    media: dict[str, Any] = {
        "product_keys": photos,
        "scene_prompt": take_scene_prompt(angle, take),
        # whole or not at all: a label too long for `price_line` is not printed (the copy
        # still states it, through the highlight) — a cut figure is a different price
        "price_line": label if len(label) <= PRICE_LINE_MAX else "",
        "brand_logo_key": brand_logo_key,
    }
    if preset.kind is ContentKind.STATIC_FLYER:
        media["ad_mode"] = AdImageMode.PRODUCT if photos else AdImageMode.SCENE
    else:
        media["template_id"] = preset.template_id
    return ContentBrief(
        brand_id=brand_id,
        objective=level.objective if level is not None else BriefObjective.SALE,
        content_type=ContentType.PRODUCT,
        topic=" — ".join(part for part in topic_parts if part),
        product_ref=product.name.strip() or None,
        intent=BriefIntent.ORGANIC,
        image_route=ImageRoute.FROM_UPLOAD if photos else ImageRoute.TEMPLATE_ONLY,
        source_media_key=photos[0] if photos else None,
        constraints=BriefConstraints(
            must_mention=(product.price_label.strip(),) if shows_price else (),
            highlights=tuple(highlights),
        ),
        variants_requested=1,
        kind=preset.kind,
        format=preset.format,
        media=MediaInputs.model_validate(media),
        awareness_level=level,
    )


@dataclass(frozen=True)
class AngleSetPlan:
    """What a set would cost before anything is paid: one Claude call for the angles,
    then one image per angle. `image_unit_usd` is the pricing table's per-piece rate."""

    count: int
    image_unit_usd: Decimal
    extras: tuple[str, ...] = field(default=())

    @property
    def images_usd(self) -> Decimal:
        return self.image_unit_usd * self.count


__all__ = [
    "ANGLES_TOOL",
    "DEFAULT_ANGLE_COUNT",
    "DEFAULT_PRESET_KEY",
    "MAX_ANGLE_COUNT",
    "MIN_ANGLE_COUNT",
    "PRESETS",
    "PRESETS_BY_KEY",
    "PRICE_HIGHLIGHT",
    "TAKE_NOTE",
    "AngleBrand",
    "AnglePreset",
    "AngleProduct",
    "AngleSetPlan",
    "CreativeAngle",
    "UnknownPreset",
    "angle_brief",
    "angles_system_prompt",
    "angles_tool",
    "angles_user_prompt",
    "awareness_level_or_none",
    "distinct_problems",
    "level_plan",
    "parse_angles",
    "preset_by_key",
    "price_conflicts",
    "price_mentions",
    "price_problem",
    "take_scene_prompt",
]

"""«Proponerme las partes» (VE-14 m-24921071, ADR 44 / ADR 32): a video by parts WITHOUT a
reel — Claude proposes 3 to `PARTS_MAX` parts from what the owner wants to tell.

- `propose_parts(brief, angle)` makes ONE paid call (plus at most one corrective turn)
  with a strict tool (`proponer_partes_video`) and returns `PartsProposal`: the plan as
  `VideoPartPlan`s, every one in mode `reference` (new, from the product's photos; no reel
  to edit or extend), and its `PartsProvenance` (model, revision, prompt version and
  fingerprint, pricing version, cost) for the parent's `MediaInputs.parts_provenance`.
- Nothing is written and no video is asked for here: the plan is a proposal the owner
  edits (UI-5); Seedance is reached only by `PartsService.create_parts` («Crear las n
  partes», VE-08), never from this module.
- Price guard: before anything is sent the model must be priced in the versioned table
  (`PRICING_VERSION`) and the first turn's worst case must fit `PROPOSE_BUDGET_USD`; every
  turn then goes through `claude_tools.DollarMeter` with that same ceiling.
- The prompt is GENERAL (founder rule): no business category, no example of a business.
  The parts are visual — no text on screen, no prices (a catalog price is printed whole by
  the template or not at all, never by a generated clip), no gender or age assumed
  (`parts.neutral_people`), nobody talking to the camera (presenters are VE-17).

Model: Claude Sonnet 5 at medium effort, the same judgement tier as the visual angles
(`angles_ai`). Measured on 20 real briefs (PARTES-001 in `docs/modelos-generativos/
pruebas.md`, v1, v2, v3 then v3.1): v2 set the plan's rules; v3 (m-24973463) asks for
them in everyday words — no film vocabulary («toma», «primer plano», «cenital»…), which
`film_words` also checks in code; v3.1 closes on the customer getting the product, keeps
each description to one sentence of `DESCRIPTION_WORDS_MAX` words (checked in code) and
describes no sound (`sound_words` checks it in code since m-24975762, same corrective
turn, same prompt). Invented components are left to fuller catalog descriptions.
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from qualify_creative.adapters.anthropic_copy import strict_schema
from qualify_creative.angles import AngleBrand, AngleProduct, CreativeAngle, price_mentions
from qualify_creative.enums import AwarenessLevel
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.schemas import (
    PART_DESCRIPTION_MAX,
    PART_GENERATION_MIN_SECONDS,
    PART_SECONDS,
    PARTS_MAX,
    PartsProvenance,
    VideoPartPlan,
)
from qualify_shared import observability

from ..claude_tools import (
    Attribution,
    BudgetExhausted,
    CallStats,
    ClaudeToolError,
    ClientFactory,
    DollarMeter,
    Meter,
    ModelConfig,
    api_key_from_env,
    create_turn,
    default_client,
    forced_or_auto,
    tool_uses,
    turn_input_ceiling,
)
from .angles_ai import _provider_error
from .parts import neutral_people

logger = logging.getLogger(__name__)

#: Bump on ANY change of the system prompt, the user prompt or the tool (provenance).
PROPOSE_PARTS_PROMPT_VERSION = "proponer-partes-v3.2"
PROPOSE_TOOL = "proponer_partes_video"

PROPOSE_MODEL = "claude-sonnet-5"
PROPOSE_EFFORT = "medium"
#: Six short descriptions are a few hundred tokens; the rest is room for thinking.
MAX_TOKENS = 4000
#: The pricing table the guard reads — the generator's current one
#: (`composition.PRICING_VERSION`; a test pins they agree).
PRICING_VERSION = "v8"
#: What one proposal may spend, both turns together (≈ USD 0.03-0.05 expected, [H]).
PROPOSE_BUDGET_USD = Decimal("0.12")

#: The fewest parts a proposal has (UX §3a: «la IA arma 3 o 4»; ticket: 3-6).
PARTS_MIN = 3
#: A proposed part lasts at least what Seedance makes (no 1-3 s part to trim) and at most
#: a part's ceiling.
PROPOSED_SECONDS = range(PART_GENERATION_MIN_SECONDS, PART_SECONDS.stop)
#: What the owner's sentence may carry into the prompt.
STORY_MAX = 600
#: English FUNCTION words that are never Spanish (PARTES-001 v2: «also flota»). Function
#: words, not nouns: a product or brand name in English («smash», «burger») is the
#: owner's and stays. A hit sends the plan back in the one corrective turn; the prompt
#: (v2, measured) is not touched.
_ENGLISH_WORDS = frozenset(
    "also and are being but from into is it its of onto over that the then these this "
    "those through very was were where which while with without".split()
)
_WORDS = re.compile(r"[^\W\d_]+")
#: A part's description is one sentence of at most this many words: the owner reads it on
#: a phone (UX review of v3, m-24973463: median 212 characters). Over it, the plan goes
#: back in the one corrective turn.
DESCRIPTION_WORDS_MAX = 25


def word_count(text: str) -> int:
    """Words in `text` (letters only: a figure or a dash is not a word)."""
    return len(_WORDS.findall(text))


def brief_words(brief: PartsBrief) -> frozenset[str]:
    """Every word of the names and the sentence the owner gave, lowercased — and, for the
    film-word check, also without accents."""
    names = (brief.product.name if brief.product else "", brief.brand.name, brief.story)
    words = {w for text in names for w in _WORDS.findall(text.lower())}
    return frozenset(words | {_plain(w) for w in words})


def english_words(text: str, allowed: frozenset[str] = frozenset()) -> tuple[str, ...]:
    """The English function words in `text`, in order, once each — except `allowed`
    (the words of the product's and the brand's names and of the owner's sentence: «The
    Burger House» is a name, not a slip)."""
    found = [w for w in _WORDS.findall(text.lower()) if w in _ENGLISH_WORDS and w not in allowed]
    return tuple(dict.fromkeys(found))


#: Film and photography vocabulary a small-business owner does not use (m-24973463), as
#: patterns over accent-free, lowercased text, whole words. «toma» alone is also the verb
#: («unas manos la toman», «Toma esa taza»), so only its noun uses count: after a
#: determiner («una toma») or before a shot qualifier («toma cenital»). A bare «Toma…» at
#: the start of a sentence is left alone, noun or verb. «picado» alone is also «chopped»,
#: «plano» alone is also «flat», «macro» alone is also «big» and «enfoque» alone is also
#: «approach»: they count only with what makes them a shot. «en segundo plano» and «en
#: cámara lenta» are everyday Spanish and are not on the list.
_SHOT = (
    "general|medio|cercano|cercana|detalle|cerrado|cerrada|abierto|abierta|americano"
    "|secuencia|entero|corto|largo|fijo|fija|lateral|frontal|amplio|picado|picada"
    "|contrapicado|contrapicada|holandes|cenital|aereo|aerea|giratoria|giratorio|continua"
    "|continuo"
)
#: Feminine/plural qualifiers that make a shot only after a determiner + «toma(s)» («una
#: toma media»): right after a bare «toma» they are the verb («toma media porción», «se
#: toma entera la bebida»), and alone they are everyday Spanish («la caja entera»).
_TOMA_ONLY = "cortas?|largas?|medias?|enteras?|amplias?"
_FILM_PATTERNS = (
    r"(?:primerisimo )?primer(?:isimo)? planos?",
    rf"planos? (?:{_SHOT})",
    r"contraplanos?",
    # the longest reading first: the regex takes the first alternative that matches
    r"(?:toma|plano|lente|modo|camara|foto|fotografia|vista) macro",
    rf"(?:una|unas|esta|estas|esa|esas|cada|otra|otras|misma|sola|primera|segunda|tercera"
    rf"|ultima|nueva|unica|varias) tomas?(?: (?:{_SHOT}|{_TOMA_ONLY}))?",
    rf"tomas? (?:{_SHOT}|de detalle)",
    r"cenital(?:es)?",
    r"contrapicad[oa]s?",
    r"(?:camara|toma|angulo|plano) picad[oa]",
    r"angulo (?:bajo|alto|holandes)",
    r"travell?ing|travelin",
    r"pane(?:o|os|a|an|ando)",
    r"tilt|dolly|zoom|bokeh|steadicam|gimbal",
    r"close[- ]?up|slow motion|time[- ]?lapse|timelapse",
    r"encuadr(?:e|es|a|an|ado|ada|ados|adas|ando)",
    r"desenfoques?|desenfoc(?:ad[oa]s?|a|an|ando|andose)",
    r"enfoc(?:a|an|ad[oa]s?|ando|andose)",
    r"(?:cambio de|fuera de|sin|con poco) enfoque|(?:camara|imagen|lente) con enfoque en",
    r"fuera de foco|foco selectivo|profundidad de campo|gran angular",
    r"camara (?:fija|cerrada|subjetiva|en mano)",
    r"fotogramas?",
)
_FILM = re.compile(r"(?<![^\W\d_])(?:" + "|".join(_FILM_PATTERNS) + r")(?![^\W\d_])")


def _plain(text: str) -> str:
    """`text` lowercased, without accents and single-spaced (the film-word check's view)."""
    folded = unicodedata.normalize("NFKD", text.casefold())
    return " ".join("".join(c for c in folded if not unicodedata.combining(c)).split())


def film_words(text: str, allowed: frozenset[str] = frozenset()) -> tuple[str, ...]:
    """The film vocabulary in `text` (accent- and case-insensitive, whole words), in order,
    once each — except a term whose every word the owner wrote himself (`allowed`, see
    `brief_words`): if he asked for a «zoom», it is his word."""
    found = [
        m.group(0)
        for m in _FILM.finditer(_plain(text))
        if not all(w in allowed for w in m.group(0).split())
    ]
    return tuple(dict.fromkeys(found))


#: Sounds a part cannot have — every part is generated without audio (m-24975762). A
#: general list, no business category; patterns over `_sound_view` text, whole words.
#: Left out on purpose, because they are things one SEES or say something else:
#: «escucha» alone («la asesora escucha a la clienta»: only «se escuch…» counts, any
#: tense), «oye» alone (only «se oy…/se oí…» and «oímos»), «suena bien/mal/a…» (an
#: opinion), bare «voz» and «grito» («le habla en voz baja», «la voz de la marca», «el
#: último grito de la moda»: only «voz en off», «voces», «gritos», «grita(n)»), «ruido»
#: alone and «hace ruido en redes/internet» (only «ruido(s) de…» and «hace(n) ruido»
#: count), «música» alone and «musical» («un
#: cartel de música en vivo»: only «música de fondo/suave/alta…», «al ritmo de la
#: música» and «suena música»), «crujiente(s)» (a texture), «sonrisa»/«sonríe»,
#: «sueña» (kept apart from «suena» by keeping the «ñ»), «zumba» and «zumo» (a dance
#: class, a juice), the verbs «aplauden», «canta», «habla», «se ríe» (a gesture on
#: screen; only the noun «aplausos» is a sound).
_SOUND_PATTERNS = (
    r"se (?:escuch[^\W\d_]*|o[iy][^\W\d_]*)|oimos",
    r"sonidos?",
    r"(?:suenan?|sonando)(?! (?:bien|mal|raro|rara|a|como)(?![^\W\d_]))",
    r"ruidos? de|(?:hacen?|haciendo) ruidos?(?! en (?:redes|internet)(?![^\W\d_]))",
    r"musica (?:de fondo|suave|alta|fuerte|a todo volumen)|al ritmo de (?:la )?musica",
    r"melodias?|canciones|cancion",
    r"voz en off|voces|gritos|grit(?:a|an|ando)|chirridos?",
    r"chisporrote(?:o|os|a|an|ando|ante|antes)",
    r"crepit(?:a|an|ando|ante|antes|ar)",
    r"crujidos?|cruj(?:e|en|ir|iendo)",
    r"zumbidos?|zumbando",
    r"silbidos?|silb(?:a|an|ando)",
    r"aplausos?",
    r"chasquidos?|tintineos?|pitidos?|estruendos?|murmullos?|susurr(?:o|os|a|an|ando)",
)
_SOUND = re.compile(r"(?<![^\W\d_])(?:" + "|".join(_SOUND_PATTERNS) + r")(?![^\W\d_])")


def _sound_view(text: str) -> str:
    """`_plain`, except the «ñ» stays: «sueña» is not «suena»."""
    composed = unicodedata.normalize("NFC", text).casefold()  # a decomposed «n» + tilde → «ñ» first
    return _plain(composed.replace("ñ", "\0")).replace("\0", "ñ")


def sound_words(text: str, allowed: frozenset[str] = frozenset()) -> tuple[str, ...]:
    """The sounds described in `text` (accent- and case-insensitive, whole words), in
    order, once each — except a term whose every word the owner wrote himself (`allowed`,
    see `brief_words`): a brand called «Música y Café» is a name, not a sound."""
    found = [
        m.group(0)
        for m in _SOUND.finditer(_sound_view(text))
        if not all(w in allowed for w in m.group(0).split())
    ]
    return tuple(dict.fromkeys(found))


#: The total length asked for when the owner did not say one, and its bounds.
DEFAULT_TARGET_SECONDS = 20
TARGET_SECONDS = range(PARTS_MIN * PART_GENERATION_MIN_SECONDS, PARTS_MAX * 10 + 1)
#: How far under the requested total the prompt lets the plan fall (v2). Over it is
#: never accepted: `fit_to_target` trims the longest parts, and a plan that cannot fit
#: even with every part at 4 s is a problem the corrective turn names.
TARGET_SLACK_SECONDS = 3


class PartsProposalUnavailable(ClaudeToolError):
    """No usable proposal: no key, the price guard refused, Anthropic did not answer, a
    refusal or truncation, or the answer broke a rule twice. `retryable` says whether the
    same request may work later. Nothing was written either way."""

    def __init__(
        self, message: str, *, retryable: bool = False, stats: CallStats | None = None
    ) -> None:
        super().__init__(message, stats=stats)
        self.retryable = retryable


#: What the owner reads when no proposal came (qualify-copy-es, UX review of VE-14): a
#: retry is promised only when the same request may work later (`retryable`).
PROPOSE_RETRY_TEXT = "No pudimos armar tu propuesta esta vez. Vuelve a intentarlo en un minuto."

#: Not retryable now (no key, the price guard): it may work later, never «en un minuto».
#: It sends the owner to no other option: «Prefiero armarlas yo» stays hidden until UI-4's
#: sheet lets him describe a part (Deivid, 2026-11-10, m-24921079).
PROPOSE_UNAVAILABLE_TEXT = "Hoy no podemos proponerte las partes. Inténtalo más tarde."


def unavailable_text(error: PartsProposalUnavailable) -> str:
    """The owner's words for a proposal that did not come."""
    return PROPOSE_RETRY_TEXT if error.retryable else PROPOSE_UNAVAILABLE_TEXT


@dataclass(frozen=True)
class PartsBrief:
    """What the proposal starts from: the owner's one sentence («¿De qué trata tu
    video?»), the product chosen (if any), the brand, and the total length wanted."""

    story: str
    brand: AngleBrand = field(default_factory=AngleBrand)
    product: AngleProduct | None = None
    target_seconds: int = DEFAULT_TARGET_SECONDS


@dataclass(frozen=True)
class PartsProposal:
    """The proposed plan, in order, and who proposed it."""

    parts: tuple[VideoPartPlan, ...]
    provenance: PartsProvenance

    @property
    def total_seconds(self) -> int:
        return sum(part.seconds for part in self.parts)


# --------------------------------------------------------------------------------------
# The prompt (pure)
# --------------------------------------------------------------------------------------

SYSTEM_PROMPT = f"""\
Eres director creativo de videos cortos verticales (9:16) para las redes sociales de \
negocios pequeños. Recibes lo que el dueño quiere contar en su video, el producto que \
quiere mostrar (si lo hay), una breve descripción de su marca y, a veces, un ángulo \
creativo ya elegido. Propones el video PARTE POR PARTE: entre {PARTS_MIN} y {PARTS_MAX} \
partes en orden. Cada parte se crea por separado con inteligencia artificial a partir de \
las fotos reales del producto, y luego se unen en un solo video. Entregas la respuesta con \
la herramienta {PROPOSE_TOOL}, una sola vez.

Reglas:
- Arco del video: la primera parte engancha desde el primer segundo; las del medio \
muestran el producto y lo que lo hace valioso; la última parte muestra cómo el cliente \
consigue el producto: lo pide, lo recibe o se lo lleva, como el dueño lo pide. Usarlo, \
probarlo o disfrutarlo no es el cierre, y el producto solo, girando o cada vez más de \
cerca, tampoco.
- Comienzo: elige el gancho que mejor cuente lo que pide el dueño (un momento de uso, un \
detalle que sorprende, una reacción, una forma llamativa de mirar, una situación \
cotidiana…). No empieces por costumbre con la elaboración del producto: solo si el dueño \
habla de cómo se hace.
- description: lo que se VE en la parte, en español, concreto, UNA sola frase de \
{DESCRIPTION_WORDS_MAX} palabras como máximo (se lee en un teléfono), con palabras de \
todos los días, como se lo contarías al dueño del negocio: dónde pasa, qué pasa y desde \
dónde se mira («de cerca», «desde arriba», «de lado», «se ve todo el lugar», «la imagen \
se acerca despacio»). Cada parte es un solo momento seguido, sin saltos dentro.
- Las partes no tienen sonido: nunca describas lo que se escucha, ni ruidos, ni música.
- Nada de palabras técnicas de cine, video o fotografía: ni «toma», «plano», «primer \
plano», «cenital», «picado», «encuadre», «paneo», «travelling», «zoom», «enfoque», \
«desenfocado» ni «profundidad de campo». Quien lo lee no sabe de video y debe entenderlo \
a la primera.
- Las partes son distintas entre sí: cambia lo que pasa, desde dónde se mira o el \
momento; nunca repitas la misma escena.
- El producto se muestra tal cual es: nunca cambies su forma, color, etiqueta ni envase, \
y nunca le agregues componentes, partes, materiales, accesorios ni funciones que no estén \
en su nombre, en su descripción o en lo que cuenta el dueño. Si no sabes de qué está \
hecho o qué contiene, no lo describas por dentro: muéstralo entero.
- Sin texto escrito en la imagen, sin precios ni cifras, sin logotipos ni marcas ajenas. \
El texto, el precio y el logo se agregan después, fuera de las partes.
- Si aparece alguien, que no sea una persona reconocible y no digas su edad ni su \
género: «una persona», «unas manos». Nadie habla a la cámara: la voz se agrega después.
- seconds: duración de la parte, un número entero de {PROPOSED_SECONDS.start} a \
{PROPOSED_SECONDS.stop - 1}. La suma de todas NUNCA supera la duración total pedida y \
queda a lo sumo {TARGET_SLACK_SECONDS} segundos por debajo.
- No prometas resultados ni hagas afirmaciones de salud."""


def propose_system_prompt() -> str:
    return SYSTEM_PROMPT


def _story(text: str) -> str:
    return " ".join((text or "").split())[:STORY_MAX].strip()


#: v3.2: what the video tells, per awareness level of the chosen angle — the parts never
#: show a price or a figure, so the levels that lean on one tell the moment instead.
_LEVEL_GUIDANCE: dict[AwarenessLevel, str] = {
    AwarenessLevel.UNAWARE: (
        "todavía no piensa en el producto: muestra el lugar y la experiencia (el ambiente, "
        "el momento, con quién se comparte)"
    ),
    AwarenessLevel.PROBLEM_AWARE: (
        "ya siente la necesidad: abre con ese dilema y muestra el producto como la respuesta"
    ),
    AwarenessLevel.SOLUTION_AWARE: (
        "sabe qué quiere pero no dónde: muestra lo que hace mejor a este producto (porción, "
        "ingredientes, variedad, según su descripción)"
    ),
    AwarenessLevel.PRODUCT_AWARE: (
        "conoce el negocio pero duda: muestra lo fácil que es venir o pedir (el lugar, la "
        "atención), sin precios ni cifras"
    ),
    AwarenessLevel.MOST_AWARE: (
        "está listo para comprar: pocas partes, cortas y directas al producto"
    ),
}


def propose_user_prompt(brief: PartsBrief, angle: CreativeAngle | None = None) -> str:
    """The volatile half: the owner's sentence, the product, the brand, the angle and the
    length, then the ask. The price is never given: a part shows no figure."""
    product = brief.product
    brand = brief.brand
    lines = [
        "== Lo que el dueño quiere contar ==",
        _story(brief.story),
        "",
        "== Producto (del catálogo del negocio) ==",
    ]
    if product is None:
        lines.append("(no eligió un producto: muestra lo que cuenta el dueño)")
    else:
        lines.extend(
            [
                f"Nombre: {product.name}",
                f"Descripción: {product.description or '(sin descripción)'}",
                f"Categoría: {product.category or '(sin categoría)'}",
                f"Fotos reales disponibles: {len(product.photo_keys)}",
            ]
        )
    lines.extend(
        [
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
        ]
    )
    if brand.perks:
        lines.append(
            "== Lo que ofrece el negocio (datos reales escritos por el dueño; muestra solo "
            "estos, nunca inventes otros) =="
        )
        lines.extend(f"- {perk}" for perk in brand.perks)
        lines.append("")
    if angle is not None:
        lines.extend(
            [
                "== Ángulo creativo elegido (el hilo del video) ==",
                f"{angle.title}: {angle.scene}",
                f"Gancho: {angle.hook or '(sin gancho)'}",
                f"Invitación: {angle.cta or '(sin invitación)'}",
            ]
        )
        if angle.awareness_level is not None:
            lines.append(
                f"Nivel de consciencia del público: {angle.awareness_level.value} — "
                f"{_LEVEL_GUIDANCE[angle.awareness_level]}."
            )
        lines.append("")
    target = _target(brief.target_seconds)
    lines.append(
        f"Duración total: como máximo {target} segundos, y no menos de "
        f"{max(target - TARGET_SLACK_SECONDS, TARGET_SECONDS.start)}."
    )
    lines.append("")
    lines.append(
        f"Propón entre {PARTS_MIN} y {PARTS_MAX} partes para este video con {PROPOSE_TOOL}."
    )
    return "\n".join(lines)


def _target(seconds: int) -> int:
    return min(max(int(seconds), TARGET_SECONDS.start), TARGET_SECONDS.stop - 1)


def propose_tool() -> dict[str, Any]:
    """The strict tool. Array and integer bounds the API refuses move into descriptions
    (`strict_schema`); `parse_parts` enforces them on the answer."""
    return {
        "name": PROPOSE_TOOL,
        "description": (
            f"Entrega las partes del video en orden, de {PARTS_MIN} a {PARTS_MAX}, "
            "todas distintas entre sí."
        ),
        "strict": True,
        "input_schema": strict_schema(
            {
                "type": "object",
                "properties": {
                    "parts": {
                        "type": "array",
                        "minItems": PARTS_MIN,
                        "maxItems": PARTS_MAX,
                        "items": {
                            "type": "object",
                            "properties": {
                                "description": {"type": "string"},
                                "seconds": {
                                    "type": "integer",
                                    "minimum": PROPOSED_SECONDS.start,
                                    "maximum": PROPOSED_SECONDS.stop - 1,
                                },
                            },
                            "required": ["description", "seconds"],
                        },
                    }
                },
                "required": ["parts"],
            }
        ),
    }


def prompt_fingerprint(system: str, user: str) -> str:
    """What identifies the exact prompt a proposal was asked with (provenance)."""
    return hashlib.sha256(f"{system}\n\n{user}".encode()).hexdigest()[:16]


# --------------------------------------------------------------------------------------
# The answer (pure)
# --------------------------------------------------------------------------------------


def _seconds(value: object) -> int:
    try:
        seconds = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        seconds = 5
    return min(max(seconds, PROPOSED_SECONDS.start), PROPOSED_SECONDS.stop - 1)


def fit_to_target(seconds: list[int], target: int) -> list[int] | None:
    """The parts' seconds with a total of at most `target`: one second off the longest
    part (the latest of equals) at a time, never below `PROPOSED_SECONDS.start`. None
    when even that cannot fit (too many parts for the length asked)."""
    fitted = list(seconds)
    while sum(fitted) > target:
        longest = max(range(len(fitted)), key=lambda i: (fitted[i], i))
        if fitted[longest] <= PROPOSED_SECONDS.start:
            return None
        fitted[longest] -= 1
    return fitted


def parse_parts(
    payload: Mapping[str, Any],
    *,
    target_seconds: int | None = None,
    allowed_words: frozenset[str] = frozenset(),
) -> tuple[tuple[VideoPartPlan, ...], tuple[str, ...]]:
    """The answer as plan entries (mode `reference`, no reel, seconds bounded to 4-10,
    descriptions single-spaced, without an assumed gender or age, within
    `PART_DESCRIPTION_MAX`; empty or repeated ones dropped; past `PARTS_MAX` cut; with a
    `target_seconds`, a total over it trimmed by `fit_to_target` — the prompt asks for it,
    the code guarantees it) and the problems a corrective turn should name — an empty
    tuple when the plan is usable."""
    rows = payload.get("parts")
    if not isinstance(rows, list):
        rows = []
    parts: list[VideoPartPlan] = []
    seen: set[str] = set()
    problems: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        raw = " ".join(str(row.get("description") or "").split())
        text = neutral_people(raw)
        if raw[:1].isupper():  # «Un hombre…» → «Una persona…», not «una persona…»
            text = text[:1].upper() + text[1:]
        text = text[:PART_DESCRIPTION_MAX].strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        if price_mentions(text):
            problems.append(
                f"La parte {len(parts) + 1} menciona un precio o una cifra: quítalo, "
                "las partes no muestran precios."
            )
        english = english_words(text, allowed_words)
        if english:
            problems.append(
                f"La parte {len(parts) + 1} tiene palabras en inglés "
                f"({', '.join(f'«{w}»' for w in english)}): escríbela solo en español."
            )
        film = film_words(text, allowed_words)
        if film:
            problems.append(
                f"La parte {len(parts) + 1} usa palabras de cine "
                f"({', '.join(f'«{w}»' for w in film)}): cuéntala con palabras de todos los "
                "días («de cerca», «desde arriba», «se ve todo el lugar»)."
            )
        sounds = sound_words(text, allowed_words)
        if sounds:
            problems.append(
                f"La parte {len(parts) + 1} describe sonidos "
                f"({', '.join(f'«{w}»' for w in sounds)}): las partes no tienen sonido, "
                "cuenta solo lo que se ve («la carne se dora en la plancha»)."
            )
        words = word_count(text)
        if words > DESCRIPTION_WORDS_MAX:
            problems.append(
                f"La parte {len(parts) + 1} tiene {words} palabras: dila en una sola frase "
                f"de {DESCRIPTION_WORDS_MAX} palabras como máximo."
            )
        parts.append(
            VideoPartPlan(mode="reference", seconds=_seconds(row.get("seconds")), description=text)
        )
    parts = parts[:PARTS_MAX]
    if target_seconds is not None and parts:
        target = _target(target_seconds)
        fitted = fit_to_target([p.seconds for p in parts], target)
        if fitted is None:
            problems.append(
                f"Tus partes no caben en {target} segundos ni con {PROPOSED_SECONDS.start} "
                "segundos cada una: propón menos partes."
            )
        else:
            parts = [
                p.model_copy(update={"seconds": s}) for p, s in zip(parts, fitted, strict=True)
            ]
    if len(parts) < PARTS_MIN:
        problems.append(
            f"Entregaste {len(parts)} partes distintas; propón entre {PARTS_MIN} y {PARTS_MAX}."
        )
    return tuple(parts), tuple(problems)


# --------------------------------------------------------------------------------------
# The price guard
# --------------------------------------------------------------------------------------


def guard_price(
    config: ModelConfig,
    *,
    input_tokens: int,
    max_tokens: int,
    limit_usd: Decimal = PROPOSE_BUDGET_USD,
    pricing: JsonPricingTable | None = None,
) -> Decimal:
    """The worst the first turn can bill, from the versioned pricing table: every input
    token at the cache-WRITE rate (the dearest) and `max_tokens` of output. Raises
    `PartsProposalUnavailable` — nothing is sent — when the model is not in the table or
    the worst case does not fit `limit_usd`."""
    table = pricing or JsonPricingTable(PRICING_VERSION)
    try:
        write = table.unit_price(model_id=config.model_id, unit="per_mtok_cache_write")
        out = table.unit_price(model_id=config.model_id, unit="per_mtok_out")
    except KeyError as exc:
        raise PartsProposalUnavailable(f"price guard: {exc}") from exc
    worst = (Decimal(input_tokens) * write + Decimal(max_tokens) * out) / Decimal(1_000_000)
    if worst > limit_usd:
        raise PartsProposalUnavailable(
            f"price guard: a turn may bill {worst} USD, over the {limit_usd} USD cap"
        )
    return worst


# --------------------------------------------------------------------------------------
# The call
# --------------------------------------------------------------------------------------


def _provenance(stats: CallStats, fingerprint: str, version: str) -> PartsProvenance:
    return PartsProvenance(
        model_id=stats.model_id,
        model_revision=stats.model_revision,
        prompt_version=PROPOSE_PARTS_PROMPT_VERSION,
        prompt_fingerprint=fingerprint,
        pricing_version=version,
        cost_usd=Decimal(str(round(stats.cost_usd, 6))),
        input_tokens=stats.input_tokens,
        output_tokens=stats.output_tokens,
        turns=stats.turns,
    )


@observability.traced("proponer partes de video", tags=("creative", "parts"))
def propose_parts(
    brief: PartsBrief,
    angle: CreativeAngle | None = None,
    *,
    attribution: Attribution,
    api_key: str | None = None,
    config: ModelConfig = ModelConfig(PROPOSE_MODEL, PROPOSE_EFFORT),
    client_factory: ClientFactory | None = None,
    pricing: JsonPricingTable | None = None,
    budget_usd: Decimal = PROPOSE_BUDGET_USD,
) -> PartsProposal:
    """Claude's plan for a video by parts without a reel. Raises `ValueError` without a
    sentence to tell, `PartsProposalUnavailable` when no usable plan came (see there).
    Makes no video call and writes nothing."""
    if not _story(brief.story):
        raise ValueError("a proposal needs what the owner wants to tell")
    table = pricing or JsonPricingTable(PRICING_VERSION)
    system = propose_system_prompt()
    user = propose_user_prompt(brief, angle)
    tool = propose_tool()
    messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
    ceiling, _ = turn_input_ceiling(system, messages, [tool])
    guard_price(
        config, input_tokens=ceiling, max_tokens=MAX_TOKENS, limit_usd=budget_usd, pricing=table
    )
    try:
        key = api_key or api_key_from_env()
    except ClaudeToolError as exc:
        raise PartsProposalUnavailable(str(exc)) from exc
    client = (client_factory or default_client)(key)
    meter = Meter(config)
    budget = DollarMeter(budget_usd)
    fingerprint = prompt_fingerprint(system, user)
    problems: tuple[str, ...] = ()
    for attempt in range(2):
        try:
            response = create_turn(
                client,
                config,
                meter,
                system=system,
                messages=messages,
                tools=[tool],
                tool_choice=forced_or_auto(config, PROPOSE_TOOL),
                max_tokens=MAX_TOKENS,
                budget=budget,
                attribution=attribution.versioned(PROPOSE_PARTS_PROMPT_VERSION),
            )
        except BudgetExhausted as exc:
            raise PartsProposalUnavailable(str(exc), stats=exc.stats) from exc
        except ClaudeToolError as exc:
            raise PartsProposalUnavailable(str(exc), stats=exc.stats) from exc
        except Exception as exc:
            typed = _provider_error(exc)
            if typed is None:
                raise
            logger.warning("parts proposal failed: %s (retryable=%s)", typed, typed.retryable)
            raise PartsProposalUnavailable(
                str(typed), retryable=typed.retryable, stats=meter.stats()
            ) from exc
        calls = [u for u in tool_uses(response) if u.name == PROPOSE_TOOL]
        if calls:
            meter.tool_calls += 1
            parts, problems = parse_parts(
                calls[0].input or {},
                target_seconds=brief.target_seconds,
                allowed_words=brief_words(brief),
            )
            if not problems:
                return PartsProposal(parts, _provenance(meter.stats(), fingerprint, table.version))
            if attempt == 0:
                messages.append({"role": "assistant", "content": response.content})
                # every tool call of the turn gets its result (the API demands it); the
                # problems ride on them as an error the model corrects
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": use.id,
                                "is_error": True,
                                "content": "Corrige esto:\n" + "\n".join(problems),
                            }
                            for use in tool_uses(response)
                        ],
                    }
                )
            continue
        if attempt == 0:
            messages.append({"role": "assistant", "content": response.content})
            messages.append(
                {"role": "user", "content": f"Entrega la respuesta con {PROPOSE_TOOL}."}
            )
    reason = "; ".join(problems) if problems else f"{config.model_id} did not call {PROPOSE_TOOL}"
    raise PartsProposalUnavailable(reason, stats=meter.stats())


__all__ = [
    "DEFAULT_TARGET_SECONDS",
    "MAX_TOKENS",
    "PARTS_MIN",
    "PRICING_VERSION",
    "PROPOSE_BUDGET_USD",
    "PROPOSE_EFFORT",
    "PROPOSE_MODEL",
    "PROPOSE_PARTS_PROMPT_VERSION",
    "PROPOSE_TOOL",
    "PROPOSE_RETRY_TEXT",
    "PROPOSE_UNAVAILABLE_TEXT",
    "unavailable_text",
    "english_words",
    "film_words",
    "sound_words",
    "word_count",
    "DESCRIPTION_WORDS_MAX",
    "PartsBrief",
    "PartsProposal",
    "PartsProposalUnavailable",
    "guard_price",
    "parse_parts",
    "propose_parts",
    "propose_system_prompt",
    "propose_tool",
    "propose_user_prompt",
]

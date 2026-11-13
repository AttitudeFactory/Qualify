"""A video by parts (ADR 44, VE-08 m-24921065): its plan from a reel's analysis, its parts
as child drafts, and «Crear otra versión» of one part.

- `plan_from_analysis` is PURE: the analysed cuts (`ReelAnalysis`, VE-04c) become 1 to
  `PARTS_MAX` parts of 1-10 s — the mode by who is seen (F6), short cuts joined (P2), a cut
  longer than 10 s split with `extend` (design §3), a source that is not 9:16 always made
  new (N5) — with what the owner should read about each part (`PartNotice`).
- `PartsService.create_parts` makes the children of a parent not made yet — every one, or
  those of `part_indexes` (m-24921081: the first, one, the ones left) — at once: briefs
  and drafts, their vistas previas charged all or nothing (`charge_many`, D7) and one
  `preview` job each, in ONE `tenant_unit_of_work` — a shortfall leaves no child and no
  charge. A child
  asks Claude nothing: its text is one of its parent's (`ContentService._inherited_copy`).
- `PartsService.regenerate_part` writes a new brief for that one part (description and
  photos; the mode stays) and regenerates it through `reject(regenerate=True)`: 1 vista
  previa at `revision + 1`, the siblings untouched, the earlier versions keep their own
  brief (`piece_versions.brief_id`).
- `check_parent_text_cap` keeps the parent's texts — the first one at creation
  (m-24921081) and each new one (Claude, paid by the platform, 0 creations) — to
  `PARENT_TEXT_DAILY_CAP` per business per day.
- `mark_parent_dirty` tells the parent's `join` run (VE-10a) that a part changed.

Seconds of video (D29, VE-21) are charged when the owner approves the whole video
(VE-10b), never here: creating parts uses only vistas previas.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID, uuid4

from qualify_creative.creations import CreationWeights, load_weights, weight_for
from qualify_creative.enums import ContentFormat, ContentKind
from qualify_creative.schemas import (
    CLIP_IMAGE_ROLES,
    CLIP_MAX_IMAGES,
    PART_DESCRIPTION_MAX,
    PART_GENERATION_MIN_SECONDS,
    PARTS_MAX,
    ContentBrief,
    MediaInputs,
    PartNotice,
    PartRef,
    VideoPartPlan,
)
from qualify_shared.db.session import tenant_unit_of_work
from sqlalchemy import text
from sqlalchemy.orm import Session

from qualify_api.creative.creations import PreviewCharge, summed_price
from qualify_api.creative.draft_mode import draft_state
from qualify_api.creative.fsm import (
    APPROVED,
    DRAFTING,
    FAILED,
    PUBLISHED,
    STAGED,
    DraftTrigger,
    apply_transition,
)
from qualify_api.creative.media import PartWindowRefused
from qualify_api.creative.part_join import PART_FINAL
from qualify_api.creative.queue_dispatch import queue_enabled
from qualify_api.creative.service import (
    ContentService,
    DraftRecord,
    PostgresContentRepository,
    UnknownDraft,
)
from qualify_api.referentes.reel_analysis_types import (
    NOT_OBSERVED,
    OBSERVED,
    UNKNOWN,
    ReelAnalysis,
    ShotAnalysis,
)

# ---------------------------------------------------------------------------
# What the owner reads (qualify-copy-es). `PartNotice` codes → their words (UI-3).

NOTICE_TEXTS: Mapping[str, str] = {
    "people_unclear": (
        "No pudimos ver bien si en esta parte aparece alguien. "
        "La crearemos de cero con las fotos de tu producto."
    ),
    "describe_it": (
        "No pudimos ver qué pasa en esta parte. Cuéntanos en una frase qué quieres que muestre."
    ),
}

#: Decided 2026-11-05: a business asks for a new text of its videos by parts at most this
#: many times a day — each is a Claude call the platform pays and costs 0 creations.
PARENT_TEXT_DAILY_CAP = 20
PARENT_TEXT_CAP_TEXT = (
    f"Hoy ya pediste {PARENT_TEXT_DAILY_CAP} textos nuevos para tu negocio. "
    f"Mañana puedes pedir otros {PARENT_TEXT_DAILY_CAP}."
)
PARTS_NEED_TEXT_TEXT = "Espera a que esté listo el texto de tu video para crear sus partes."
PARTS_UNAVAILABLE_TEXT = "Por ahora no podemos crear las partes de tu video. Inténtalo más tarde."
PARTS_OVER_BUDGET_TEXT = (
    "No pudimos crear las partes: tu negocio llegó a su límite de este mes. "
    "Escríbenos y lo revisamos contigo."
)


def part_label(index: int, total: int) -> str:
    """«Parte 2 de 4» — where a part sits in its video."""
    return f"Parte {index} de {total}"


def describe_part_text(index: int) -> str:
    return f"Antes de crear la parte {index}, cuéntanos qué quieres que muestre."


class PartsUnavailable(Exception):
    """The parts cannot be made now (the generation queue is off: the parent would never
    be joined again). Nothing was written."""

    def __init__(self) -> None:
        super().__init__(PARTS_UNAVAILABLE_TEXT)
        self.text = PARTS_UNAVAILABLE_TEXT


class ParentTextMissing(Exception):
    """The parent has no text that passed yet — its parts would have none to carry."""

    def __init__(self) -> None:
        super().__init__(PARTS_NEED_TEXT_TEXT)
        self.text = PARTS_NEED_TEXT_TEXT


class PartNeedsDescription(Exception):
    """A part the analysis could not see (`describe_it`) still has no description."""

    def __init__(self, index: int) -> None:
        self.text = describe_part_text(index)
        super().__init__(self.text)
        self.index = index


class PartRemoved(Exception):
    """m-24985192: a part the owner removed («Quitar parte») asked for by number: it is
    never made again. Nothing written."""

    reason = "removed"

    def __init__(self, index: int) -> None:
        super().__init__(f"part {index} was removed from its video")
        self.index = index


class PartNeedsPrevious(Exception):
    """m-24921081: a «Sigue a la anterior» part asked for alone while the part it
    continues is not created (nor asked for with it). Nothing written."""

    reason = "needs_previous"

    def __init__(self, index: int) -> None:
        super().__init__(f"part {index} continues part {index - 1}, which is not created")
        self.index = index


class PartsOverBudget(Exception):
    """The team's dollar cap of the brand cannot pay the parts together (N9): checked
    once on their estimated total, before anything exists."""

    def __init__(self, *, estimated_usd: Decimal, remaining_usd: Decimal) -> None:
        super().__init__(PARTS_OVER_BUDGET_TEXT)
        self.text = PARTS_OVER_BUDGET_TEXT
        self.estimated_usd = estimated_usd
        self.remaining_usd = remaining_usd


class ParentTextCapReached(Exception):
    """Criterion 7: today's new texts of this business's videos by parts are spent."""

    def __init__(self, used: int) -> None:
        super().__init__(PARENT_TEXT_CAP_TEXT)
        self.text = PARENT_TEXT_CAP_TEXT
        self.used = used


class ExtendOutOfOrder(ValueError):
    """m-24984421: an `extend` part that is first in the plan, or with cuts and not
    right after the part whose last cut it continues — an order problem, never a cut
    length one (that is `ExtendTooShort`)."""


class ExtendTooShort(ValueError):
    """Criterion 8: an `extend` part that shares the previous part's last cut is only for
    a cut of the analysis longer than 10 s (one generation cannot hold it)."""


# ---------------------------------------------------------------------------
# The plan from an analysis (pure)

#: A part of a video holds at most this many seconds (D5's per-video ceiling).
PART_MAX_SECONDS = 10
#: 9:16 within this relative tolerance (720×1280, 1080×1920, 1080×1918…).
_VERTICAL_TOLERANCE = 0.02

#: Words that assume a person's gender or age (VE-04c's prompt already forbids them, the
#: model may still slip): «un hombre» → «una persona». Never who someone is.
_PERSON_WORDS = (
    "hombre",
    "mujer",
    "chico",
    "chica",
    "muchacho",
    "muchacha",
    "niño",
    "niña",
    "señor",
    "señora",
    "joven",
    "anciano",
    "anciana",
    "abuelo",
    "abuela",
    "adolescente",
    "caballero",
    "dama",
)
_PERSON_PLURALS = (
    "hombres",
    "mujeres",
    "chicos",
    "chicas",
    "muchachos",
    "muchachas",
    "niños",
    "niñas",
    "señores",
    "señoras",
    "jóvenes",
    "ancianos",
    "ancianas",
    "abuelos",
    "abuelas",
    "adolescentes",
    "caballeros",
    "damas",
)
_ARTICLE = r"(?:(?P<art>un|una|el|la|los|las|unos|unas|dos|tres|cuatro|varios|varias)\s+)?"
_AGE_ADJECTIVES = r"(?:\s+(?:joven|jóvenes|mayor|mayores|adulto|adulta|adultos|adultas))?"
_SINGULAR = re.compile(
    rf"\b{_ARTICLE}(?P<noun>{'|'.join(_PERSON_WORDS)}){_AGE_ADJECTIVES}\b", re.IGNORECASE
)
_PLURAL = re.compile(
    rf"\b{_ARTICLE}(?P<noun>{'|'.join(_PERSON_PLURALS)}){_AGE_ADJECTIVES}\b", re.IGNORECASE
)
_PLURAL_ARTICLES = {"los": "las", "unos": "unas", "varios": "varias"}
#: Words after which a person word is still a NOUN («con jóvenes», «para niños»); after
#: any other word it qualifies the word before it («unas manos jóvenes», «un vaso chico»).
_NOUN_INTRODUCERS = frozenset(
    "a al ante como con de del e entre hacia ni o para por que sin sobre u y".split()
)
_WORD_BEFORE = re.compile(r"(\w+)\s+$")
#: Plural nouns a plural age or gender word QUALIFIES («unas manos jóvenes», «sus caras
#: adolescentes»). After any other word a bare plural is a noun, often a subject after its
#: verb («Llegan niños corriendo»), and becomes «personas».
_PLURAL_HOSTS = frozenset(
    "manos personas caras rostros pieles voces amigos amigas clientes parejas grupos "
    "figuras siluetas".split()
)


def _qualifies_previous_word(match: re.Match[str], *, plural: bool) -> bool:
    """An adjective, so dropped, not a person to rename: no article, and right after a
    word that does not introduce a noun (singular: a bare singular person noun after a
    word is never a subject in Spanish — «un vaso chico», «una persona joven»), or, for a
    plural, right after a noun it can qualify (`_PLURAL_HOSTS`)."""
    if match.group("art"):
        return False
    before = _WORD_BEFORE.search(match.string[: match.start()])
    if before is None:
        return False
    word = before.group(1).lower()
    if plural:
        return word in _PLURAL_HOSTS
    return word not in _NOUN_INTRODUCERS


def neutral_people(text_: str) -> str:
    """The description without a person's assumed gender or age: «un hombre joven
    muerde…» → «una persona muerde…», «dos mujeres» → «dos personas». Used as an
    adjective after another word, the age or gender word is dropped instead: «unas manos
    jóvenes» → «unas manos», never «unas manos personas»."""

    def cased(match: re.Match[str], words: str) -> str:
        # «Los niños…» opens a sentence as «Las personas…», not «las personas…»
        return words[:1].upper() + words[1:] if match.group(0)[:1].isupper() else words

    def singular(match: re.Match[str]) -> str:
        if _qualifies_previous_word(match, plural=False):
            return ""
        article = (match.group("art") or "").lower()
        if article in ("el", "la"):
            return cased(match, "la persona")
        return cased(match, "una persona")

    def plural(match: re.Match[str]) -> str:
        if _qualifies_previous_word(match, plural=True):
            return ""
        article = (match.group("art") or "").lower()
        article = _PLURAL_ARTICLES.get(article, article)
        return cased(match, f"{article} personas" if article else "personas")

    out = _SINGULAR.sub(singular, _PLURAL.sub(plural, text_))
    if out == text_:
        return out
    # a dropped adjective leaves a double space or a space before punctuation
    return re.sub(r"\s+([,.;:!?)])", r"\1", re.sub(r"[ \t]{2,}", " ", out)).strip()


def _observed_value(families: Mapping[str, Any], name: str) -> str:
    family = families.get(name) or {}
    if not isinstance(family, Mapping) or family.get("status") != OBSERVED:
        return ""
    value = family.get("value")
    return value.strip() if isinstance(value, str) else ""


def _with_products(value: str, products: Sequence[str]) -> str:
    """The analysis never knows the brand: its «el producto» becomes the owner's own
    product when the piece is about one."""
    name = next((p.strip() for p in products if p and p.strip()), "")
    if not name:
        return value
    value = re.sub(r"\bdel producto\b", f"de {name}", value, flags=re.IGNORECASE)
    value = re.sub(r"\bal producto\b", f"a {name}", value, flags=re.IGNORECASE)
    return re.sub(r"\b(?:el|un) producto\b", name, value, flags=re.IGNORECASE)


# m-24992913: the reel's own product («sliders de pescado») named in a cut's description
# becomes the owner's product. The noun comes from the analysis's `product` family (no new
# model call): of the cut the reel's hook happens in, else of the first cut that names one.
# Never each cut's own product: in a recipe reel those are the ingredients («Huevo y agua
# en harina» → «Manos cascan super smash» would be wrong). It is replaced only in a cut
# whose own `product` value names it too, so a word the noun shares with something else
# («deliciosa», a person) never moves.

#: Words that open a product value without being its noun (articles, numbers, quantities).
_PRODUCT_OPENERS = frozenset(
    "un una unos unas el la los las lo dos tres cuatro cinco varios varias algunos algunas "
    "muchos muchas mucho mucha otro otra otros otras su sus".split()
)
#: Containers and details: «Vaso de batido» is about the «batido», «Bolsillo de la
#: chaqueta» about the «chaqueta»; alone, they name no product of the reel.
_PRODUCT_HOLDERS = frozenset(
    "vaso vasos taza tazas plato platos bol boles cuenco cuencos bolsa bolsas caja cajas "
    "bandeja bandejas frasco frascos bote botes olla ollas estuche estuches envase envases "
    "empaque empaques recipiente recipientes jarra jarras bolsillo bolsillos puño puños "
    "cierre cierres capucha capuchas forro forros pieza piezas trozo trozos rodaja rodajas "
    "porción porciones bocado bocados detalle detalles lista listas".split()
)
#: Never a product noun of the reel (generic words; «producto» is `_with_products`').
_NOT_PRODUCT_NOUNS = (
    frozenset(
        "producto productos marca marcas logo logos objeto objetos cosa cosas ninguno ninguna "
        "ningún nada sin con mano manos persona personas texto textos gente cliente clientes "
        "cocinero cocinera cocineros cocineras chef chefs modelo modelos".split()
    )
    | frozenset(_PERSON_WORDS)
    | frozenset(_PERSON_PLURALS)
)
#: Adjectives a `product` value may open with («Deliciosa hamburguesa doble»): skipped.
_PRODUCT_ADJECTIVES = frozenset(
    "delicioso deliciosa deliciosos deliciosas rico rica ricos ricas gran grande grandes "
    "nuevo nueva nuevos nuevas mejor mejores clásico clásica clásicos clásicas casero casera "
    "caseros caseras típico típica típicos típicas fresco fresca frescos frescas famoso "
    "famosa famosos famosas exquisito exquisita exquisitos exquisitas sabroso sabrosa "
    "sabrosos sabrosas jugoso jugosa jugosos jugosas crujiente crujientes enorme enormes "
    "pequeño pequeña pequeños pequeñas auténtico auténtica auténticos auténticas "
    "tradicional tradicionales primer primera primeros primeras último última doble triple "
    "mini super súper".split()
)
#: «Mujer con vestido rojo»: the product is what comes after the person and «con».
_PERSON_WITH = frozenset("con que lleva viste usa sostiene".split())
#: Words that end a product noun phrase («Sliders de pescado rebozado CON salsa»).
_PHRASE_STOPS = frozenset("con y e o u en a al para sin sobre junto entre".split())
_ARTICLES_AFTER_DE = frozenset("el la los las".split())
#: Determiners and prepositions before the reel's noun, dropped with it: the owner's
#: product is a name and goes bare («los sliders» → «super smash», «del slider» → «de super
#: smash»), the way `_with_products` already treats «el producto».
_NOUN_LEAD = (
    r"(?P<lead>\b(?:(?P<de>del|de\s+(?:los|las|la|el|unos|unas|un|una|sus|su))"
    r"|(?P<a>al|a\s+(?:los|las|la|el|unos|unas|un|una|sus|su))"
    r"|un|una|unos|unas|el|la|los|las|sus|su|tus|tu|este|esta|estos|estas|ese|esa|esos|"
    r"esas|aquel|aquella|dos|tres|cuatro|varios|varias)\s+)?"
)


@dataclass(frozen=True)
class ReelProductNoun:
    """The noun the reel's analysis gives its own product («sliders»), and the words of
    that `product` value («de pescado rebozado») a description may add right after it."""

    noun: str
    phrase_words: frozenset[str]


def _value_words(value: str) -> list[str]:
    # the value's first item: «Sliders de pescado, salsa» → «Sliders de pescado»
    first = re.split(r"[,;:()/]", value, maxsplit=1)[0]
    return [w.casefold() for w in re.findall(r"[^\W\d_]+", first)]


def product_noun(value: str) -> ReelProductNoun | None:
    """The product noun of a `product` value: its first noun after any article or number,
    a container's content («Vaso de batido» → «batido»), past opening adjectives
    («Deliciosa hamburguesa» → «hamburguesa») and a person who has it («Mujer con vestido»
    → «vestido»). None for a list of three or more things (ingredients: «Pan, queso,
    pescado frito, salsa», also with «;») or a generic word or a person."""
    if value.count(",") + value.count(";") >= 2:
        return None
    words = _value_words(value)
    at = 0

    def skip_openers(at: int) -> int:
        while at < len(words) and (
            words[at] in _PRODUCT_OPENERS or words[at] in _PRODUCT_ADJECTIVES
        ):
            at += 1
        return at

    at = skip_openers(at)
    if (
        at + 1 < len(words)
        and (words[at] in _PERSON_WORDS or words[at] in _PERSON_PLURALS or words[at] == "persona")
        and words[at + 1] in _PERSON_WITH
    ):
        at = skip_openers(at + 2)
    while at < len(words) and words[at] in _PRODUCT_HOLDERS:
        rest = words[at + 1 :]
        if not rest or rest[0] not in ("de", "del"):
            return None
        at = skip_openers(at + 2)
    if at >= len(words):
        return None
    noun = words[at]
    if len(noun) < 3 or noun in _NOT_PRODUCT_NOUNS or noun in _PHRASE_STOPS:
        return None
    phrase: set[str] = set()
    for word in words[at + 1 :]:
        if word in _PHRASE_STOPS:
            break
        phrase.add(word)
    phrase -= {"de", "del"} | _ARTICLES_AFTER_DE
    return ReelProductNoun(noun=noun, phrase_words=frozenset(phrase))


def reel_product_noun(analysis: ReelAnalysis) -> ReelProductNoun | None:
    """The reel's own product: the `product` noun of the cut its hook happens in
    (`reel_sheet.hook.shot`), else of the first cut whose `product` names one."""
    shots = sorted(analysis.shots, key=lambda s: s.shot_index)
    hook = analysis.reel_sheet.get("hook") if isinstance(analysis.reel_sheet, Mapping) else None
    hook_shot = hook.get("shot") if isinstance(hook, Mapping) else None
    if isinstance(hook_shot, int) and not isinstance(hook_shot, bool):
        shots = [s for s in shots if s.shot_index == hook_shot] + shots
    for shot in shots:
        found = product_noun(_observed_value(shot.families, "product"))
        if found is not None:
            return found
    return None


def _noun_forms(noun: str) -> list[str]:
    """Singular and plural of the noun, the way Spanish (and the loanwords the analysis
    uses) make them: «slider» ↔ «sliders», «hamburguesa» ↔ «hamburguesas», «pan» ↔
    «panes»."""
    bases = {noun}
    if noun.endswith("es") and len(noun) > 4:
        bases.add(noun[:-2])
    if noun.endswith("s") and len(noun) > 3:
        bases.add(noun[:-1])
    forms = set(bases)
    for base in bases:
        forms.update((base + "s", base + "es"))
    return sorted(forms, key=len, reverse=True)


def _names_reel_product(value: str, reel: ReelProductNoun | None) -> bool:
    """The cut's own `product` value names the reel's product noun too (any number)."""
    if reel is None or not value:
        return False
    forms = set(_noun_forms(reel.noun))
    return any(word.casefold() in forms for word in re.findall(r"[^\W\d_]+", value))


def _with_reel_product(value: str, reel: ReelProductNoun | None, products: Sequence[str]) -> str:
    """The reel's own product noun, with its article and the words of its `product` value
    that follow it («los sliders de pescado»), becomes the owner's product name, whole
    words only; nothing else of the text moves."""
    name = next((p.strip() for p in products if p and p.strip()), "")
    if not name or reel is None:
        return value
    nouns = "|".join(re.escape(form) for form in _noun_forms(reel.noun))
    words = "|".join(re.escape(w) for w in sorted(reel.phrase_words, key=len, reverse=True))
    tail = rf"(?:\s+(?:(?:de|del)\s+(?:(?:el|la|los|las)\s+)?)?(?:{words})\b)*" if words else ""
    pattern = re.compile(rf"{_NOUN_LEAD}\b(?:{nouns})\b{tail}", re.IGNORECASE)

    def named(match: re.Match[str]) -> str:
        if match.group("de"):
            lead = match.group("de")[:1]  # «De los…» keeps its capital
            return f"{lead}e {name}"
        if match.group("a"):
            return f"{match.group('a')[:1]} {name}"
        return name

    return pattern.sub(named, value)


def _sentence(value: str) -> str:
    value = value.strip().rstrip(".")
    if not value:
        return ""
    return value[0].upper() + value[1:] + "."


def _description_key(text_: str) -> str:
    """How two cut descriptions are compared: case, spaces and the final period ignored."""
    return " ".join(text_.split()).rstrip(".").strip().casefold()


def join_unique(texts: Iterable[str]) -> str:
    """The texts (one per cut) joined by a space, each one that repeats an earlier one
    (case, spaces and final period aside) left out whole; the first one's own text and
    order kept. Texts are never cut apart, so no word is ever lost."""
    seen: set[str] = set()
    kept: list[str] = []
    for value in texts:
        key = _description_key(value)
        if key and key not in seen:
            seen.add(key)
            kept.append(value.strip())
    return " ".join(kept)


def shot_description(
    shot: ShotAnalysis,
    products: Sequence[str] = (),
    reel_product: ReelProductNoun | None = None,
) -> str:
    """What the cut shows, from its sheet: the subject (what is seen and what happens),
    never who someone is. Empty when the analysis could not see it. In a cut whose own
    `product` family names the reel's product (`reel_product`) too, it becomes the
    owner's (m-24992913); any other cut keeps its text."""
    subject = _observed_value(shot.families, "subject")
    if not subject:
        return ""
    value = _with_products(subject, products)
    if _names_reel_product(_observed_value(shot.families, "product"), reel_product):
        value = _with_reel_product(value, reel_product, products)
    return _sentence(neutral_people(value))


def clip_description(text_: str, limit: int = PART_DESCRIPTION_MAX) -> str:
    """The description within `limit` characters, never cut inside a word: up to its last
    whole sentence that fits when that keeps over half of it, else its last whole word."""
    text_ = text_.strip()
    if len(text_) <= limit:
        return text_
    head = text_[: limit + 1]
    end = head.rfind(". ")
    if end > limit // 2:
        return head[: end + 1]
    space = head.rfind(" ")
    return head[:space].rstrip(" ,;:") if space > 0 else text_[:limit]


def _edit_allowed(shot: ShotAnalysis) -> bool:
    """F6: «Igual al original» only when no person and no face was seen."""
    return shot.people_presence == NOT_OBSERVED and shot.visible_faces == NOT_OBSERVED


def _people_unclear(shot: ShotAnalysis) -> bool:
    """The analysis could not tell whether someone is in the cut."""
    return shot.people_presence == UNKNOWN or (
        shot.people_presence == NOT_OBSERVED and shot.visible_faces == UNKNOWN
    )


def _talks(shot: ShotAnalysis) -> bool:
    """Someone seems to talk to the camera: speech falls in the cut and a face is seen."""
    return bool(shot.spoken_text.strip()) and shot.visible_faces == OBSERVED


def is_vertical(width: int, height: int) -> bool:
    if width <= 0 or height <= 0:
        return False
    return abs(width / height - 9 / 16) <= (9 / 16) * _VERTICAL_TOLERANCE


def _seconds(duration: float) -> int:
    return max(1, min(PART_MAX_SECONDS, round(duration)))


def _group_seconds(group: Sequence[ShotAnalysis]) -> float:
    return sum(max(shot.seconds, 0.0) for shot in group)


def _parts_needed(group: Sequence[ShotAnalysis]) -> int:
    seconds = _group_seconds(group)
    return max(1, math.ceil(seconds / PART_MAX_SECONDS)) if len(group) == 1 else 1


def _consecutive(a: Sequence[ShotAnalysis], b: Sequence[ShotAnalysis]) -> bool:
    return b[0].shot_index == a[-1].shot_index + 1


def _can_join(a: Sequence[ShotAnalysis], b: Sequence[ShotAnalysis]) -> bool:
    return _consecutive(a, b) and _group_seconds(a) + _group_seconds(b) <= PART_MAX_SECONDS


def _same_mode(a: Sequence[ShotAnalysis], b: Sequence[ShotAnalysis], editable: bool) -> bool:
    """P2: a cut where someone is (or may be) seen never joins an «Igual al original»
    part — joining across that line would make it new and lose the original's look."""
    if not editable:
        return True
    return all(_edit_allowed(s) for s in a) == all(_edit_allowed(s) for s in b)


def _groups(shots: Sequence[ShotAnalysis], editable: bool) -> list[list[ShotAnalysis]]:
    """Consecutive cuts joined while the part is shorter than Seedance's 4 s and the sum
    stays within 10 s (P2), never across the edit/new line; a cut over 10 s stays alone
    (it is split later). Past `PARTS_MAX` parts, the shortest neighbours that fit are
    joined — of the same mode first, then any."""
    groups: list[list[ShotAnalysis]] = []
    for shot in shots:
        last = groups[-1] if groups else None
        if (
            last is not None
            and _group_seconds(last) < PART_GENERATION_MIN_SECONDS
            and _can_join(last, [shot])
            and _same_mode(last, [shot], editable)
        ):
            last.append(shot)
        else:
            groups.append([shot])
    # a short last part leans on the one before it when it fits
    if (
        len(groups) > 1
        and _group_seconds(groups[-1]) < PART_GENERATION_MIN_SECONDS
        and _can_join(groups[-2], groups[-1])
        and _same_mode(groups[-2], groups[-1], editable)
    ):
        groups[-2].extend(groups.pop())
    while sum(_parts_needed(g) for g in groups) > PARTS_MAX:
        pairs = [
            (
                not _same_mode(groups[i], groups[i + 1], editable),
                _group_seconds(groups[i]) + _group_seconds(groups[i + 1]),
                i,
            )
            for i in range(len(groups) - 1)
            if _can_join(groups[i], groups[i + 1])
        ]
        if not pairs:
            break
        *_, at = min(pairs)
        groups[at].extend(groups.pop(at + 1))
    return groups


def _split(seconds: float) -> list[int]:
    """A cut over 10 s as consecutive parts of at most 10 s, as even as whole seconds go."""
    total = round(seconds)
    count = max(2, math.ceil(total / PART_MAX_SECONDS))
    base, extra = divmod(total, count)
    return [base + (1 if i < extra else 0) for i in range(count)]


def plan_from_analysis(
    analysis: ReelAnalysis, *, products: Sequence[str] = ()
) -> tuple[VideoPartPlan, ...]:
    """The parts a reel's analysis proposes, in order (pure; no I/O, no model call).

    - mode by people (F6): `edit` («Igual al original») only for cuts where no person and
      no face was seen, the source is 9:16 (N5) and can be edited; anything else
      `reference` (new, inspired by the original). People the analysis could not tell
      about → `people_unclear`, never `edit`;
    - consecutive cuts shorter than 4 s are joined up to 10 s (P2), and, past
      `PARTS_MAX` parts, the shortest neighbours that fit; past that, the first six;
    - a cut longer than 10 s becomes parts of at most 10 s, every one after the first an
      `extend` («Sigue a la anterior») that starts on that same cut;
    - `talks_to_camera` = speech in the cut and a face seen; a part whose cuts show
      nothing the analysis could see → `describe_it`, no description;
    - descriptions never assume age or gender (`neutral_people`).
    - a part's description says once what its cuts repeat (`join_unique`);
    - the reel's own product («sliders de pescado») becomes the owner's (`products`) in
      the cuts that show a product (`reel_product_noun`, m-24992913).
    """
    shots = sorted(analysis.shots, key=lambda s: s.shot_index)
    if not shots:
        return ()
    editable = (
        analysis.edit_eligible
        and analysis.source_available
        and is_vertical(analysis.width, analysis.height)
    )
    reel_product = reel_product_noun(analysis)
    plan: list[VideoPartPlan] = []
    for group in _groups(shots, editable):
        unclear = any(_people_unclear(shot) for shot in group)
        mode = "edit" if editable and all(_edit_allowed(s) for s in group) else "reference"
        description = join_unique(shot_description(s, products, reel_product) for s in group)
        notices: list[PartNotice] = []
        if unclear:
            notices.append("people_unclear")
        if not description:
            notices.append("describe_it")
        common: dict[str, Any] = {
            "analysis_id": analysis.id,
            "shot_indexes": tuple(s.shot_index for s in group),
            "description": clip_description(description),
            "talks_to_camera": any(_talks(s) for s in group),
            "notices": tuple(notices),
        }
        if len(group) == 1 and group[0].seconds > PART_MAX_SECONDS:
            for at, seconds in enumerate(_split(group[0].seconds)):
                made = mode if at == 0 else "extend"
                plan.append(VideoPartPlan(mode=made, original_mode=made, seconds=seconds, **common))
        else:
            seconds = _seconds(_group_seconds(group))
            plan.append(VideoPartPlan(mode=mode, original_mode=mode, seconds=seconds, **common))
    return tuple(plan[:PARTS_MAX])


def check_extend_parts(parts: Sequence[VideoPartPlan], analysis: ReelAnalysis | None) -> None:
    """Criterion 8 (VE-06's schema cannot see cut lengths): an `extend` part that starts
    on the previous part's last cut is accepted only when that cut of the analysis lasts
    more than 10 s. An `extend` without cuts (no reel) continues freely — but never as
    the first part (m-24984421: an edited plan can put it there), and one WITH cuts
    starts on the last cut of the part right before it (a reorder must not tear it from
    the part it continues)."""
    previous: VideoPartPlan | None = None
    for part in parts:
        if part.mode == "extend" and previous is None:
            raise ExtendOutOfOrder("the first part cannot continue a previous one")
        if (
            part.mode == "extend"
            and part.shot_indexes
            and (
                previous is None
                or not previous.shot_indexes
                or previous.analysis_id != part.analysis_id
                or part.shot_indexes[0] != previous.shot_indexes[-1]
            )
        ):
            raise ExtendOutOfOrder("an extend part starts on the last cut of the part before it")
        shares = (
            part.mode == "extend"
            and part.shot_indexes
            and previous is not None
            and previous.shot_indexes
            and part.shot_indexes[0] == previous.shot_indexes[-1]
        )
        if shares:
            if analysis is None or analysis.id != part.analysis_id:
                raise ExtendTooShort("an extend part on a reel's cut needs that reel's analysis")
            shot = next((s for s in analysis.shots if s.shot_index == part.shot_indexes[0]), None)
            if shot is None or shot.seconds <= PART_MAX_SECONDS:
                raise ExtendTooShort(
                    "«Sigue a la anterior» shares a cut only when that cut lasts over 10 s"
                )
        previous = part


#: A neighbour cut sharing less than this with a window does not count as «in» it (the
#: cut times are the detector's, a frame apart).
_WINDOW_SLACK_S = 0.05


def _window_clean(shots: Sequence[ShotAnalysis], own: set[int], start: int, end: int) -> bool:
    """No cut of someone else's (a person or a face seen, or unknown) inside the window."""
    for shot in shots:
        inside = min(shot.end_s, end) - max(shot.start_s, start)
        if shot.shot_index not in own and inside > _WINDOW_SLACK_S and not _edit_allowed(shot):
            return False
    return True


def part_window(
    part: VideoPartPlan | PartRef,
    shots: Sequence[ShotAnalysis],
    *,
    source_seconds: float | None,
) -> tuple[int, int, float]:
    """VE-09: the window of the original an «Igual al original» part edits, `(start_s,
    end_s, offset_s)` — whole seconds (`source_window` cuts whole seconds), as long as
    the part's `generation_seconds` (what the child asks Seedance for, so the edit's
    ±0.5 s check holds) and within the source. It starts on the part's first cut and,
    when its cuts are shorter, takes the rest from the next cut; if that one shows
    someone (or might), from the cut before; if both do, it is refused
    (`not_edit_eligible`: never put a person of the original in an edit, F6).
    `offset_s` is where the part's own cuts start inside the window, SIGNED (the join
    trims there): positive = the window opens that many seconds before the part's
    first cut (a cut at 3.2 s in a window from 3 s → 0.2); negative = the window opens
    after it, so the part's first `-offset_s` seconds are not in it. Pure."""
    own = set(part.shot_indexes)
    covered = sorted((s for s in shots if s.shot_index in own), key=lambda s: s.shot_index)
    if not covered or len(covered) != len(own):
        raise PartWindowRefused("window_unavailable")
    length = part.generation_seconds
    source_end = source_seconds if source_seconds is not None else max(s.end_s for s in shots)
    limit = math.floor(source_end + 1e-3)
    if limit < length:
        raise PartWindowRefused("window_unavailable")
    first, last = covered[0].start_s, covered[-1].end_s
    # whole seconds that keep the part's first cut whole (the lead before it is checked
    # like any neighbour), or that end where its last cut ends
    forward = min(max(0, math.floor(first + _WINDOW_SLACK_S)), limit - length)
    backward = max(0, min(math.ceil(last - _WINDOW_SLACK_S), limit) - length)
    for start in dict.fromkeys((forward, backward)):
        if _window_clean(shots, own, start, start + length):
            return start, start + length, round(first - start, 3)
    raise PartWindowRefused("not_edit_eligible")


# ---------------------------------------------------------------------------
# Children: create, regenerate, read


@dataclass(frozen=True)
class PartChanges:
    """What «Crear otra versión» of a part may change (provisional decision 2026-11-05):
    its description and its photos — never its mode. None keeps what it had."""

    description: str | None = None
    photo_keys: tuple[str, ...] | None = None


@dataclass(frozen=True)
class PartSummary:
    """One part as the parent's screen shows it: «Parte 2 de 4», its state and the
    description its current version was made from."""

    index: int
    total: int
    draft_id: UUID | None  # None while the part is only planned
    status: str  # the child's status, or «planned»
    mode: str
    seconds: int
    description: str
    notices: tuple[str, ...]
    #: m-24985192: its number on screen, counting only the parts kept (a removed part
    #: leaves no gap); 0 = `index`
    number: int = 0

    @property
    def label(self) -> str:
        return part_label(self.number or self.index, self.total)


PLANNED = "planned"


class PartsRepository(Protocol):
    """What parts need of the content repository besides the `ContentRepository` seam."""

    def parts_of(self, *, tenant_id: UUID, parent_id: UUID) -> tuple[DraftRecord, ...]: ...

    def replace_brief(
        self, *, tenant_id: UUID, draft_id: UUID, user_id: UUID, brief: ContentBrief
    ) -> UUID: ...


def removed_part_indexes(repository: Any, *, tenant_id: UUID, parent_id: UUID) -> frozenset[int]:
    """m-24985192: the places in the plan of the parts the owner removed («Quitar
    parte»). A repository that cannot tell (test doubles without it) has none."""
    reader: Callable[..., frozenset[int]] | None = getattr(repository, "removed_part_indexes", None)
    if reader is None:
        return frozenset()
    return frozenset(reader(tenant_id=tenant_id, parent_id=parent_id))


def check_parent_text_cap(repository: Any, *, tenant_id: UUID) -> None:
    """Criterion 7: refuse a new parent text once today's are spent. A repository that
    cannot count (test doubles without it) is not capped."""
    counter: Callable[..., int] | None = getattr(repository, "parent_texts_regenerated_today", None)
    if counter is None:
        return
    used = counter(tenant_id=tenant_id)
    if used >= PARENT_TEXT_DAILY_CAP:
        raise ParentTextCapReached(used)


def mark_parent_dirty(session: Session, child_id: UUID) -> None:
    """A part was made, failed or got another version back: the parent's `join` run (at
    the parent's current revision) must join again — the creative worker's
    `PipelinePreparation` runs it (VE-10a, `part_join.run_join`). In the caller's
    transaction. VE-10a: OPENS the run when there is none yet (the first part to settle
    does), so the parent never waits in `drafting` for its parts (risk N1); a run
    already there is dirtied. Two parts settling together only bump the same row: the
    run's lease (`PipelineStore.acquire`) gives one join."""
    session.execute(
        text("""
        INSERT INTO creative_pipeline_runs AS r
            (tenant_id, draft_id, revision, phase, pipeline_version)
        SELECT p.tenant_id, p.id, p.revision, 'join', p.pipeline_version
        FROM content_drafts c
        JOIN content_drafts p ON p.tenant_id = c.tenant_id AND p.id = c.parent_draft_id
        WHERE c.id = :child
        ON CONFLICT (tenant_id, draft_id, revision, phase)
        DO UPDATE SET dirty_version = r.dirty_version + 1
        """),
        {"child": child_id},
    )


def open_parent_join(session: Session, parent_id: UUID) -> None:
    """VE-10a: a video by parts got a new version of its own (another text, a restored
    version): its parts did not change, but the joined preview lives on the parent's
    ACTIVE version — open (or dirty) the `join` run at its new revision so the worker
    joins them again for it. Only for a parent that already has parts."""
    session.execute(
        text("""
        INSERT INTO creative_pipeline_runs AS r
            (tenant_id, draft_id, revision, phase, pipeline_version)
        SELECT p.tenant_id, p.id, p.revision, 'join', p.pipeline_version
        FROM content_drafts p JOIN content_briefs b ON b.id = p.brief_id
        WHERE p.id = :parent AND p.parent_draft_id IS NULL AND b.kind = 'shot_video'
          AND EXISTS (SELECT 1 FROM content_drafts c WHERE c.parent_draft_id = p.id)
        ON CONFLICT (tenant_id, draft_id, revision, phase)
        DO UPDATE SET dirty_version = r.dirty_version + 1
        """),
        {"parent": parent_id},
    )


def open_parent_join_final(session: Session, draft_id: UUID) -> None:
    """VE-10b: a part's final was kept (`part_final`), or the whole video was approved
    with every part's final already kept: open (or dirty) the parent's `join_final` run
    at its current revision — the creative worker joins the raw finals once ALL of them
    are there (`part_final.join_final`). `draft_id` is a part or the parent itself. In
    the caller's transaction; idempotent (the same row is only dirtied)."""
    session.execute(
        text("""
        INSERT INTO creative_pipeline_runs AS r
            (tenant_id, draft_id, revision, phase, pipeline_version)
        SELECT p.tenant_id, p.id, p.revision, 'join_final', p.pipeline_version
        FROM content_drafts d
        JOIN content_drafts p ON p.tenant_id = d.tenant_id
            AND p.id = COALESCE(d.parent_draft_id, d.id) AND p.parent_draft_id IS NULL
        WHERE d.id = :d
        ON CONFLICT (tenant_id, draft_id, revision, phase)
        DO UPDATE SET dirty_version = r.dirty_version + 1
        """),
        {"d": draft_id},
    )


#: The parent is being published right now: no part changes until it ends.
PART_PUBLISHING_TEXT = (
    "Tu video se está publicando ahora. Cuando termine, podrás cambiar sus partes."
)
#: The parent is on the calendar, staged or published: its parts can no longer change.
PART_SCHEDULED_TEXT = "Este video ya está programado. Sácalo del calendario para cambiar una parte."
#: The part's 1080p is being made by the vendor right now (paid, in flight).
PART_FINAL_IN_FLIGHT_TEXT = (
    "La versión final de esta parte se está preparando ahora. Cuando termine, podrás cambiarla."
)
#: m-24921069 (founder's text, 2026-11-09): the video's files were purged (ADR 39).
PURGED_PARENT_TEXT = (
    "Los archivos de este video ya se borraron, así que ya no puedes cambiar sus partes. "
    "Crea un video nuevo para empezar otra vez."
)


class PartChangeRefused(ValueError):
    """A part of this video by parts cannot change now (the text says why and what to
    do). Nothing written."""


def refuse_if_parent_purged(session: Session, parent_id: UUID) -> None:
    """m-24921069: no part is made, made again or restored under a video whose files the
    retention purge removed («Contenido eliminado», `media_purged_at`): it would be a
    part with no video, swept by the next purge without any warning
    (`PURGED_PARENT_TEXT`). Call it with the parent's row locked (the purge marks under
    that lock too). Nothing written."""
    purged = session.execute(
        text("SELECT media_purged_at IS NOT NULL FROM content_drafts WHERE id = :p"),
        {"p": parent_id},
    ).scalar()
    if purged:
        raise PartChangeRefused(PURGED_PARENT_TEXT)


def lock_parent_for_part_change(session: Session, parent_id: UUID) -> str:
    """Lock the parent the way `versions.restore` locks a piece (its calendar events in
    id order, then its row) and refuse when a part may not change: a publication in
    progress, a scheduled event, or a staged/published parent — and (m-24921069) a parent
    whose files the retention purge removed. The parent's status."""
    events = (
        session.execute(
            text("SELECT status FROM calendar_events WHERE post_id = :p ORDER BY id FOR UPDATE"),
            {"p": parent_id},
        )
        .scalars()
        .all()
    )
    status = session.execute(
        text("SELECT status FROM content_drafts WHERE id = :p FOR UPDATE"), {"p": parent_id}
    ).scalar()
    refuse_if_parent_purged(session, parent_id)
    if "publishing" in events:
        raise PartChangeRefused(PART_PUBLISHING_TEXT)
    if "scheduled" in events or status in (STAGED, PUBLISHED):
        raise PartChangeRefused(PART_SCHEDULED_TEXT)
    return str(status)


def retire_unmade_final(session: Session, child_id: UUID, reason: str) -> tuple[UUID, ...]:
    """An APPROVED part is about to change (another version, a restored one): its final
    that was ordered but not made will never be the video's. In the caller's transaction
    — the order of `queue_visibility._cancel_queued` (its runs, its jobs, then its row):
    refused while the vendor makes it (`claimed`/`submitted`: paid, in flight); else its
    queued night jobs are cancelled, its `final:` runs fenced off, its blocks marked
    failed, and its seconds given back on the charge that paid them (each block's
    `charge_revision`, D9). A final already kept (`part_final`) was delivered: untouched.
    The retired assets."""
    from qualify_api.creative.creations import refund_final_in_session  # noqa: PLC0415

    revision = session.execute(
        text("SELECT revision FROM content_drafts WHERE id = :c"), {"c": child_id}
    ).scalar()
    session.execute(
        text("""
        SELECT phase FROM creative_pipeline_runs
        WHERE draft_id = :c AND revision = :r AND phase LIKE 'final:%' FOR UPDATE
    """),
        {"c": child_id, "r": revision},
    )
    jobs = session.execute(
        text("""
        SELECT id, status, vendor_task_id FROM creative_jobs
        WHERE draft_id = :c AND revision = :r AND kind = 'final' FOR UPDATE
    """),
        {"c": child_id, "r": revision},
    ).all()
    status = session.execute(
        text("SELECT status FROM content_drafts WHERE id = :c FOR UPDATE"), {"c": child_id}
    ).scalar()
    if status != APPROVED:
        return ()
    rendering = session.execute(
        text("""
        SELECT 1 FROM image_assets a JOIN content_drafts d ON d.id = a.draft_id
        WHERE a.draft_id = :c AND a.params->'draft'->>'status' = 'rendering'
          AND (a.version_id IS NULL OR a.version_id = d.active_version_id)
        LIMIT 1
    """),
        {"c": child_id},
    ).scalar()
    if rendering or any(
        job.status in ("claimed", "submitted")
        or (job.vendor_task_id and job.status not in ("succeeded", "failed", "cancelled"))
        for job in jobs
    ):
        # in flight — the queue's executor took it, or (inline/thread mode, no job) its
        # block says `rendering`: paid or about to be, never retired under it
        raise PartChangeRefused(PART_FINAL_IN_FLIGHT_TEXT)
    now = datetime.now(UTC)
    session.execute(
        text("""
        UPDATE creative_jobs SET status = 'cancelled', finished_at = :now
        WHERE draft_id = :c AND revision = :r AND kind = 'final' AND status = 'queued'
    """),
        {"c": child_id, "r": revision, "now": now},
    )
    session.execute(
        text("""
        UPDATE creative_pipeline_runs
        SET prepared_version = dirty_version, lease_token = NULL, lease_until = NULL
        WHERE draft_id = :c AND revision = :r AND phase LIKE 'final:%'
    """),
        {"c": child_id, "r": revision},
    )
    rows = session.execute(
        text("""
        SELECT a.id, a.params->'draft' AS block FROM image_assets a
        JOIN content_drafts d ON d.id = a.draft_id
        WHERE a.draft_id = :c AND a.params ? 'draft'
          AND (a.version_id IS NULL OR a.version_id = d.active_version_id)
        FOR UPDATE OF a
    """),
        {"c": child_id},
    ).all()
    retired: dict[int, list[UUID]] = {}
    for row in rows:
        block = dict(row.block or {})
        if block.get("status") == PART_FINAL:
            continue
        paid_at = block.get("charge_revision")
        retired.setdefault(int(paid_at) if isinstance(paid_at, int) else int(revision), []).append(
            row.id
        )
        if block.get("status") != "failed":
            session.execute(
                text("""
                UPDATE image_assets SET params = jsonb_set(jsonb_set(params, '{draft,status}',
                    '"failed"'), '{draft,failure_reason}', to_jsonb(CAST(:why AS text)))
                WHERE id = :a
            """),
                {"a": row.id, "why": reason},
            )
    for paid_at, ids in retired.items():
        refund_final_in_session(
            session, draft_id=child_id, revision=paid_at, reason=reason, asset_ids=ids, now=now
        )
    return tuple(i for ids in retired.values() for i in ids)


@contextmanager
def part_changing(
    session: Session, tenant_id: UUID, parent_id: UUID, child_id: UUID, reason: str
) -> Iterator[None]:
    """Around a change of one part (another version made or restored), in the caller's
    transaction: the parent's fence (`lock_parent_for_part_change`), the part's unmade
    final retired (`retire_unmade_final`), and — once the change is written — an
    APPROVED parent back to the gate (`DraftTrigger.PART_CHANGED`): its new joined
    preview is approved again, charging only the parts made again."""
    status = lock_parent_for_part_change(session, parent_id)
    back = apply_transition(status, DraftTrigger.PART_CHANGED) if status == APPROVED else None
    retire_unmade_final(session, child_id, reason)
    yield
    if back is not None:
        session.execute(
            text("UPDATE content_drafts SET status = :s WHERE id = :p AND tenant_id = :t"),
            {"s": back, "p": parent_id, "t": tenant_id},
        )


def parent_picture(session: Session, parent_id: UUID) -> None:
    """VE-10a: the picture of a video by parts is the poster of its joined preview
    (`params.thumbnail_key`, else the joined video) — of its ACTIVE version's join, else
    of its latest one, so a new text never leaves it without a picture while its parts
    are joined again. Untouched when it has no join (any other piece: a no-op)."""
    session.execute(
        text("""
        UPDATE content_drafts p SET preview_key = j.picture
        FROM (
            SELECT COALESCE(a.params->>'thumbnail_key', a.object_key) AS picture
            FROM image_assets a JOIN content_drafts d ON d.id = a.draft_id
            WHERE a.draft_id = :parent AND a.params->'draft'->>'finish' = 'join'
            ORDER BY (a.version_id IS NOT DISTINCT FROM d.active_version_id) DESC,
                     a.updated_at DESC
            LIMIT 1
        ) j
        WHERE p.id = :parent AND j.picture IS NOT NULL
        """),
        {"parent": parent_id},
    )


#: What each part mode takes of its parent's images (m-24984421). The BytePlus adapter
#: sends any image as a `reference_image` in all three task types (the role travels in
#: the prompt, which names product, place and style for both the clip and the reel
#: edit), so every mode takes all three — an «Igual al original» part too (Deivid's
#: decision, 2026-11-09). Kept as a table so one mode can be narrowed in one line.
PART_MODE_IMAGE_ROLES: Mapping[str, frozenset[str]] = {
    "reference": frozenset(CLIP_IMAGE_ROLES),
    "extend": frozenset(CLIP_IMAGE_ROLES),
    "edit": frozenset(CLIP_IMAGE_ROLES),
}


def parent_images(media: MediaInputs) -> tuple[tuple[str, str], ...]:
    """The parent's images as `(key, role)`, in the owner's order: its `clip_image_keys`
    with `clip_image_roles` (no roles = every one the product), else — a parent from
    before m-24984421 — its `product_keys` as products."""
    if media.clip_image_keys:
        keys = media.clip_image_keys
        roles = media.clip_image_roles
        if len(roles) != len(keys):
            roles = ("product",) * len(keys)
        return tuple(zip(keys, roles, strict=True))
    return tuple((key, "product") for key in media.product_keys)


def part_images(media: MediaInputs, mode: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The images a part in `mode` takes from its parent, `(keys, roles)`: the roles its
    mode admits (`PART_MODE_IMAGE_ROLES`), each key once, at most `CLIP_MAX_IMAGES`."""
    admitted = PART_MODE_IMAGE_ROLES[mode]
    pairs = [(key, role) for key, role in parent_images(media) if role in admitted]
    unique = list(dict(pairs).items())[:CLIP_MAX_IMAGES]
    return tuple(k for k, _ in unique), tuple(r for _, r in unique)


def part_brief_with(parent: ContentBrief, old: ContentBrief, changes: PartChanges) -> ContentBrief:
    """A part's brief with `changes` applied — its description and its photos, never its
    mode: what «Crear otra versión» writes, and (m-24921082) «Cambiar» of a part that did
    not come out. A photo keeps the role the part (else its parent) gave it; a new one is
    the product. Pure."""
    part = old.media.part
    if part is None:
        raise ValueError("not the brief of a part")
    description = part.description if changes.description is None else changes.description
    description = description.strip()[:PART_DESCRIPTION_MAX]
    notices = tuple(n for n in part.notices if not (n == "describe_it" and description))
    media_update: dict[str, Any] = {
        "part": part.model_copy(update={"description": description, "notices": notices})
    }
    if changes.photo_keys is not None:
        photos = tuple(dict.fromkeys(changes.photo_keys))[:CLIP_MAX_IMAGES]
        had = {
            **dict(parent_images(parent.media)),
            **dict(zip(old.media.clip_image_keys, old.media.clip_image_roles, strict=False)),
        }
        media_update["clip_image_keys"] = photos
        media_update["clip_image_roles"] = tuple(had.get(key, "product") for key in photos)
    return ContentBrief.model_validate(
        {**old.model_dump(), "media": {**old.media.model_dump(), **media_update}}
    )


def _child_brief(
    parent: ContentBrief, plan: VideoPartPlan, index: int, window: str | None
) -> ContentBrief:
    """A part's own brief: a `CLIP` of the part's generation length in the part's mode,
    with the parent's product photos as its references (its words come from the
    parent's text, not from Claude). No logo, no brand resource and no subtitles: a
    part is one shot of a video joined later, which carries them once (VE-09).

    An `edit` part edits a window of the original reel. VE-09: the creative worker cuts
    it into the part's own folder when the part is made (`source_window` needs the
    part's draft id), so none is needed here; a `window` cut beforehand is kept (it is
    a key of the piece like any other, checked by `_key_problems` before any read)."""
    media = parent.media
    photos, roles = part_images(media, plan.mode)
    part = PartRef(index=index, **plan.model_dump())
    video_keys: tuple[str, ...] = ()
    if plan.mode == "edit" and window:
        video_keys = (window,)
    child_media = media.model_dump()
    child_media.update(
        parts=(),
        parts_removed=(),
        parts_provenance=None,  # the plan's (VE-14), the parent's alone
        parts_request=None,  # the owner's ask (m-24921081), the parent's alone
        part=part,
        duration_seconds=part.generation_seconds,
        clip_reference_mode={"reference": "motion", "edit": "edit", "extend": "extend"}[plan.mode],
        clip_image_keys=photos,
        clip_image_roles=roles,
        clip_video_keys=video_keys,
        clip_first_frame_key=None,
        clip_last_frame_key=None,
        clip_audio_keys=(),
        clip_subtitles=False,
        brand_logo_key=None,
        brand_logo_reference_keys=(),
        brand_logo_placement=None,
        brand_logo_in_scene=True,
        brand_element_keys=(),
    )
    return ContentBrief.model_validate(
        {
            **parent.model_dump(),
            "kind": ContentKind.CLIP,
            "format": ContentFormat.REELS_9_16,
            "variants_requested": 1,
            "media": child_media,
        }
    )


#: m-24984421: how many times `create_parts` starts again on a plan saved meanwhile.
_PLAN_MOVED_RETRIES = 3


class _PlanMoved(Exception):
    """The parent's plan changed between `create_parts`' first read and its lock."""


class PartsPlanBusy(Exception):
    """m-24984421: the parent's plan was saved again on each of `create_parts`'
    `_PLAN_MOVED_RETRIES` attempts. Nothing was written and asking again is safe. No
    client text yet: the screen chooses its words (`reason` = "plan_busy")."""

    reason = "plan_busy"


class PartsService:
    """The parts of a video by parts, over the content service's own collaborators."""

    def __init__(
        self,
        content: ContentService,
        *,
        weights: CreationWeights | None = None,
        require_queue: Callable[[], bool] = queue_enabled,
    ) -> None:
        self._content = content
        self._weights = weights or load_weights()
        self._queue_enabled = require_queue

    @property
    def _repo(self) -> Any:
        return self._content.repository

    def _unit(self, tenant_id: UUID) -> AbstractContextManager[Any]:
        """One transaction across every repository, ledger and outbox call (Postgres);
        the in-memory doubles have no transaction to share."""
        if isinstance(self._repo, PostgresContentRepository):
            return tenant_unit_of_work(tenant_id)
        return nullcontext()

    def _parent(self, tenant_id: UUID, parent_id: UUID) -> tuple[DraftRecord, ContentBrief]:
        parent = self._repo.get_draft(tenant_id=tenant_id, draft_id=parent_id)
        if parent is None or parent.parent_draft_id is not None:
            raise UnknownDraft(str(parent_id))  # another business's reads the same (RLS)
        brief = self._repo.get_brief(tenant_id=tenant_id, brief_id=parent.brief_id)
        if brief is None or not brief.kind.is_parts_parent:
            raise UnknownDraft(str(parent_id))
        return parent, brief

    def _has_text(self, tenant_id: UUID, parent: DraftRecord) -> bool:
        if parent.status in (DRAFTING, FAILED):
            return False
        variants = self._repo.variants_for(tenant_id=tenant_id, draft_id=parent.id)
        return any((v.fidelity or {}).get("passed") for v in variants)

    def estimated_usd(self, briefs: Sequence[ContentBrief]) -> Decimal:
        """N9: what the parts may cost the team together (preview + final at p95)."""
        total = Decimal(0)
        for brief in briefs:
            media = brief.media
            total += self._weights.generated_video_usd(
                media.duration_seconds,
                reference_videos=len(media.clip_video_keys),
                audio=media.clip_audio,
            )
        return total

    def create_parts(
        self,
        *,
        tenant_id: UUID,
        parent_id: UUID,
        user_id: UUID,
        analysis: ReelAnalysis | None = None,
        windows: Mapping[int, str] | None = None,
        part_indexes: Sequence[int] | None = None,
    ) -> list[UUID]:
        """Create the parts of the parent's plan that do not exist yet — every one, or
        those of `part_indexes` (m-24921081: «Probar solo la parte 1» is `(1,)`, «Crear
        esta parte» `(n,)`) — all of them or none: the ids of the parts asked for (every
        part of the plan when `part_indexes` is None), in plan order.

        Refused (nothing written) without the generation queue (`PartsUnavailable`), while
        the parent has no text (`ParentTextMissing`), with a part asked for still to
        describe (`PartNeedsDescription`), an `extend` on a cut of 10 s or less
        (`ExtendTooShort`) or out of order (`ExtendOutOfOrder`), an `extend` asked for
        while the part it continues is neither created nor asked for (`PartNeedsPrevious`),
        when the dollar cap cannot pay their estimate (`PartsOverBudget`, checked once),
        when the month cannot pay their vistas previas (`NotEnoughCreations`), and under a
        video whose files were purged (`PartChangeRefused`, m-24921069). An index outside
        the plan is `UnknownDraft`.
        Idempotent: a part that exists is returned, never made (nor charged) twice.

        m-24984421: the plan is read again under the parent's lock; one saved meanwhile
        (`parts_plan.save_parts_plan`, same lock) restarts the whole preparation, so the
        children always follow the plan the parent keeps (`planned` of the join). Saved
        again on every attempt: `PartsPlanBusy`, nothing written."""
        for _ in range(_PLAN_MOVED_RETRIES):
            try:
                return self._create_parts_once(
                    tenant_id=tenant_id,
                    parent_id=parent_id,
                    user_id=user_id,
                    analysis=analysis,
                    windows=windows,
                    part_indexes=part_indexes,
                )
            except _PlanMoved:
                continue
        raise PartsPlanBusy("the parts plan kept changing while the parts were made")

    def _create_parts_once(
        self,
        *,
        tenant_id: UUID,
        parent_id: UUID,
        user_id: UUID,
        analysis: ReelAnalysis | None,
        windows: Mapping[int, str] | None,
        part_indexes: Sequence[int] | None = None,
    ) -> list[UUID]:
        if not self._queue_enabled():
            raise PartsUnavailable()
        parent, brief = self._parent(tenant_id, parent_id)
        plan = brief.media.parts
        # m-24985192: a part the owner removed is never made again — «Crear las que
        # faltan» is the plan minus the parts made minus the parts removed
        removed = removed_part_indexes(self._repo, tenant_id=tenant_id, parent_id=parent_id)
        asked = (
            [index for index in range(1, len(plan) + 1) if index not in removed]
            if part_indexes is None
            else sorted(set(part_indexes))
        )
        if not asked or any(not 1 <= index <= len(plan) for index in asked):
            raise UnknownDraft(f"{parent_id}#{asked}")
        taken_out = [index for index in asked if index in removed]
        if taken_out:
            raise PartRemoved(taken_out[0])
        existing = self._repo.parts_of(tenant_id=tenant_id, parent_id=parent_id)
        made_before = {child.part_index: child.id for child in existing}
        wanted = [index for index in asked if index not in made_before]
        if not wanted:
            return [made_before[index] for index in asked]
        if not self._has_text(tenant_id, parent):
            raise ParentTextMissing()
        for index in wanted:
            part = plan[index - 1]
            if "describe_it" in part.notices and not part.description.strip():
                raise PartNeedsDescription(index)
        check_extend_parts(plan, analysis)
        for index in wanted:
            # «Sigue a la anterior» continues the part before it: never made alone
            follows = index - 1
            if (
                plan[index - 1].mode == "extend"
                and follows not in removed
                and follows not in made_before
                and follows not in wanted
            ):
                raise PartNeedsPrevious(index)
        children: list[ContentBrief] = []
        voice_version, pipeline_version = 0, ""
        for index in wanted:
            part = plan[index - 1]
            if part.mode == "extend" and index - 1 in removed:
                # m-24985192: the part it continued was removed — made «Nueva, inspirada
                # en el original», as `PartRecovery.remove_part` does to a made one
                part = part.model_copy(update={"mode": "reference"})
            child = _child_brief(brief, part, index, (windows or {}).get(index))
            child, voice_version, pipeline_version = self._content.prepare_new_generation(
                tenant_id=tenant_id, brand_id=parent.brand_id, brief=child
            )
            children.append(child)
        budget = self._repo.budget_state(tenant_id=tenant_id, brand_id=parent.brand_id)
        if budget is not None and budget.hard_stop:
            estimate = self.estimated_usd(children)
            if estimate > budget.remaining_usd:
                raise PartsOverBudget(estimated_usd=estimate, remaining_usd=budget.remaining_usd)
        ids = [uuid4() for _ in children]
        creations = self._content.creations
        charges = [
            PreviewCharge(draft_id=child_id, revision=1, price=weight_for(child))
            for child_id, child in zip(ids, children, strict=True)
        ]
        dispatcher = self._content.dispatcher
        with self._unit(tenant_id) as session:
            if session is not None:
                # two concurrent asks: the parent's row lock serializes them, and the
                # second one finds the first one's parts (never a duplicate part_index)
                session.execute(
                    text("SELECT id FROM content_drafts WHERE id = :p FOR UPDATE"),
                    {"p": parent_id},
                )
                refuse_if_parent_purged(session, parent_id)  # m-24921069
            made = {
                child.part_index: child.id
                for child in self._repo.parts_of(tenant_id=tenant_id, parent_id=parent_id)
            }
            if all(index in made for index in asked):
                return [made[index] for index in asked]  # a concurrent ask made them
            if set(made) != set(made_before):
                raise _PlanMoved()  # parts made meanwhile: prepare again from them
            # m-24984421: the owner may have saved another plan between the first read
            # and the lock — never make children of a plan the parent no longer keeps.
            # This read sees a save committed before we got the lock because
            # `tenant_session`/`tenant_unit_of_work` run at READ COMMITTED (the Postgres
            # default; `qualify_shared.db` never changes it — `SHOW transaction_isolation`
            # measured 2026-11-09): each statement takes a new snapshot, and
            # `save_parts_plan` holds this same row lock until it commits.
            _, locked = self._parent(tenant_id, parent_id)
            if locked.media.parts != plan:
                raise _PlanMoved()
            if creations is not None:
                # before any row: all of them or none (the ledger checks again under the
                # brand's lock when it charges)
                short = creations.balance(tenant_id=tenant_id, brand_id=parent.brand_id).shortfall(
                    summed_price(charges)
                )
                if short is not None:
                    raise short
            for index, child_id, child in zip(wanted, ids, children, strict=True):
                self._repo.insert_brief_and_draft(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    brief=child,
                    voice_profile_version=voice_version,
                    pipeline_version=pipeline_version,
                    draft_id=child_id,
                    parent_draft_id=parent_id,
                    part_index=index,
                )
            if creations is not None:
                creations.charge_many(
                    tenant_id=tenant_id, brand_id=parent.brand_id, charges=charges
                )
            if dispatcher is not None:
                for child_id in ids:
                    dispatcher.dispatch_generation(tenant_id=tenant_id, draft_id=child_id)
        made_now = {**made_before, **dict(zip(wanted, ids, strict=True))}
        return [made_now[index] for index in asked]

    def regenerate_part(
        self,
        *,
        tenant_id: UUID,
        parent_id: UUID,
        part_index: int,
        changes: PartChanges,
        user_id: UUID,
    ) -> UUID:
        """«Crear otra versión» of ONE part: a new brief with the new description and
        photos (the mode stays), then `reject(regenerate=True)` — 1 vista previa at the
        part's `revision + 1`. The siblings are not touched; the versions made before
        keep their own brief. Returns the part's draft id.

        VE-10b: a part of an APPROVED whole video sends the parent back to the gate
        (`DraftTrigger.PART_CHANGED`) in the same transaction: its new joined preview is
        approved again, which charges only the parts made again (the others' seconds
        were charged at their own revision). A staged or published parent refuses it
        (`InvalidTransition`), with nothing written."""
        parent, parent_brief = self._parent(tenant_id, parent_id)
        child = next(
            (
                c
                for c in self._repo.parts_of(tenant_id=tenant_id, parent_id=parent_id)
                if c.part_index == part_index
            ),
            None,
        )
        if child is None:
            raise UnknownDraft(f"{parent_id}#{part_index}")
        old = self._repo.get_brief(tenant_id=tenant_id, brief_id=child.brief_id)
        if old is None or old.media.part is None:
            raise UnknownDraft(str(child.id))
        new = part_brief_with(parent_brief, old, changes)
        with self._unit(tenant_id) as session:
            if session is not None:
                fence: AbstractContextManager[Any] = part_changing(
                    session, tenant_id, parent_id, child.id, "part_redone"
                )
            else:
                fence = self._changing_in_memory(tenant_id, parent, child)
            with fence:
                self._change_part(tenant_id, child, new, part_index, user_id)
        return child.id

    def _change_part(
        self, tenant_id: UUID, child: DraftRecord, new: ContentBrief, part_index: int, user_id: UUID
    ) -> None:
        self._repo.replace_brief(tenant_id=tenant_id, draft_id=child.id, user_id=user_id, brief=new)
        # a refusal (no vista previa left, a piece mid-generation) rolls the new brief back
        # with it: the part keeps the brief it had
        self._content.reject(
            tenant_id=tenant_id,
            draft_id=child.id,
            reason=f"Pediste otra versión de la parte {part_index}",
            user_id=user_id,
            regenerate=True,
        )

    @contextmanager
    def _changing_in_memory(
        self, tenant_id: UUID, parent: DraftRecord, child: DraftRecord
    ) -> Iterator[None]:
        """`part_changing` for the in-memory doubles (no transaction, no queue)."""
        if parent.status in (STAGED, PUBLISHED):
            raise PartChangeRefused(PART_SCHEDULED_TEXT)
        back = (
            apply_transition(parent.status, DraftTrigger.PART_CHANGED)
            if parent.status == APPROVED
            else None
        )
        if child.status == APPROVED:
            unmade = tuple(
                asset.id
                for asset in self._repo.draft_videos_for(tenant_id=tenant_id, draft_id=child.id)
                if (draft_state(asset.params) or {}).get("status") != PART_FINAL
            )
            if unmade:
                self._content._refund_final_part(tenant_id, child.id, "part_redone", unmade)
        yield
        if back is not None:
            self._repo.update_status(
                tenant_id=tenant_id, draft_id=parent.id, new_status=back, failure_reason=None
            )

    def parts(self, *, tenant_id: UUID, parent_id: UUID) -> tuple[PartSummary, ...]:
        """«Parte N de M» for the parent's screen: every planned part with its child's
        state (planned before `create_parts`)."""
        _, brief = self._parent(tenant_id, parent_id)
        plan = brief.media.parts
        children = {
            c.part_index: c for c in self._repo.parts_of(tenant_id=tenant_id, parent_id=parent_id)
        }
        removed = removed_part_indexes(self._repo, tenant_id=tenant_id, parent_id=parent_id)
        kept = [(index, entry) for index, entry in enumerate(plan, start=1) if index not in removed]
        out: list[PartSummary] = []
        for number, (index, entry) in enumerate(kept, start=1):
            child = children.get(index)
            shown: Any = entry
            if child is not None:
                child_brief = self._repo.get_brief(tenant_id=tenant_id, brief_id=child.brief_id)
                if child_brief is not None and child_brief.media.part is not None:
                    shown = child_brief.media.part
            out.append(
                PartSummary(
                    index=index,
                    total=len(kept),
                    draft_id=None if child is None else child.id,
                    status=PLANNED if child is None else child.status,
                    mode=shown.mode,
                    seconds=shown.seconds,
                    description=shown.description,
                    notices=tuple(shown.notices),
                    number=number,
                )
            )
        return tuple(out)


__all__ = [
    "NOTICE_TEXTS",
    "PART_MODE_IMAGE_ROLES",
    "PARENT_TEXT_CAP_TEXT",
    "PARENT_TEXT_DAILY_CAP",
    "PART_MAX_SECONDS",
    "PLANNED",
    "ExtendOutOfOrder",
    "ExtendTooShort",
    "ParentTextCapReached",
    "ParentTextMissing",
    "PartChanges",
    "PartNeedsDescription",
    "PartNeedsPrevious",
    "PartRemoved",
    "PartSummary",
    "PartsOverBudget",
    "PartsPlanBusy",
    "PartsRepository",
    "PartsService",
    "PartsUnavailable",
    "check_extend_parts",
    "check_parent_text_cap",
    "is_vertical",
    "mark_parent_dirty",
    "open_parent_join_final",
    "PART_FINAL_IN_FLIGHT_TEXT",
    "PART_PUBLISHING_TEXT",
    "PART_SCHEDULED_TEXT",
    "PURGED_PARENT_TEXT",
    "PartChangeRefused",
    "lock_parent_for_part_change",
    "refuse_if_parent_purged",
    "removed_part_indexes",
    "part_changing",
    "retire_unmade_final",
    "neutral_people",
    "parent_images",
    "part_images",
    "part_brief_with",
    "part_label",
    "part_window",
    "join_unique",
    "plan_from_analysis",
    "shot_description",
    "clip_description",
    "product_noun",
    "reel_product_noun",
    "ReelProductNoun",
]

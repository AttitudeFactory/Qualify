"""Pure rules of «Te faltan 3 cosas que solo tú sabes» (m-24854331, OL2-6 of the epic
m-24852192, docs/epica-prellenado-brand-kit-alta.md §7.8; texts §7.10 T16–T28).

After «Aprobar» on the Alta's proposal (`brand_proposal.py`), the owner who was left with
rubro, logo and colours filled no longer lands on «Paso 2 de 5»: they see what is done
and the three things only they know, answer them one per screen («{n} de 3»), and end on
«Tu marca está lista». Every other owner keeps the five steps (`brand_minimal.py`).

This module holds what can be decided without Reflex or a database:

- the literal copy the founder approved on 2026-10-25 (do not reword it);
- whether an owner takes this path (`applies`) and where a returning one opens
  (`resume_screen`);
- the rubro's example for each question (help text only, never a saved answer);
- the B1 drafts (`prefill.proposal.borradores`, OL2-3 — off until OL2-4 approves them),
  read defensively (`drafts_from`).

No new storage: the three answers are the kit's own fields — «¿Qué te hace distinto?»
→ `positioning`, «¿Quién te compra?» → `audience`, the third → the first line of
`do_examples` (+ the optional tone sliders). Finishing is `brand_finish.save_brand_kit`.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from qualify_api.privacy import mask_phones

# -- copy (literal, docs/epica-prellenado-brand-kit-alta.md §7.10) ----------------------

#: T16 — the screen after «Aprobar».
MISSING_TITLE = "Te faltan 3 cosas que solo tú sabes"
#: T16b / T16c (approved 2026-10-26): the title counts down as questions get answered.
MISSING_TITLES: dict[int, str] = {
    3: MISSING_TITLE,
    2: "Te faltan 2 cosas que solo tú sabes",
    1: "Te falta 1 cosa que solo tú sabes",
}
ANSWER_NOW_LABEL = "Responder ahora"
LATER_LABEL = "Lo hago después"
#: PB-5's literal notice, on top of that screen.
APPROVED_NOTICE = "Listo. Guardamos tu identidad de marca."
#: T18 — what the approval already did, then the three that are left.
DONE_ITEMS: tuple[str, ...] = (
    "Tu cuenta",
    "A qué te dedicas",
    "Tu logo y tus colores",
    "Tus etiquetas",
)
TAGS_ITEM = "Tus etiquetas"
DONE_MARK = "(hecho)"
#: T20 — a B1 draft.
DRAFT_HINT = "Lo escribimos leyendo tus publicaciones. Cámbialo si no es así."
DRAFT_CONFIRM_LABEL = "Sí, así es"
DRAFT_CORRECT_LABEL = "Corregir"
#: T21 — the third question's optional sliders.
TONE_LABEL = "Ajustar el tono (opcional)"
#: T26 — the end.
READY_TITLE = "Tu marca está lista"
READY_BODY = (
    "Cada publicación que crees va a salir con tu logo, tus colores y tu forma de hablar. "
    "Nada se publica sin que lo apruebes."
)
READY_CREATE_LABEL = "Crear mi primera publicación"
READY_BRAND_LABEL = "Ver mi identidad de marca"
#: T27 (approved 2026-10-25) — under a disabled «Continuar» / «Terminar mi marca».
EMPTY_ANSWER_HINT = "Para seguir, escribe tu respuesta."
#: T28 (approved 2026-10-25) — «Lo hago después», once what is written is saved.
SAVED_FOR_LATER = "Guardamos lo que llevas. Cuando vuelvas, sigues con lo que te falta."
SAVE_LATER_FAILED = "No pudimos guardar lo que llevas. Revisa tu conexión e inténtalo de nuevo."
#: The buttons the five steps already use (`creative_wizard_pages`).
BACK_LABEL = "Atrás"
CONTINUE_LABEL = "Continuar"

#: «/create» and «/brand/kit»: where «Tu marca está lista» leads.
CREATE_ROUTE = "/create"
BRAND_ROUTE = "/brand/kit"

# -- the screens ------------------------------------------------------------------------

SCREEN_MISSING = "faltan"
Q_DISTINCT = "distinto"
Q_BUYERS = "quien_compra"
Q_PHRASE = "frase_ejemplo"
SCREEN_READY = "lista"

#: (key, question — T19, the item in the checklist — T18), in order. The key is also
#: the B1 draft's key in `borradores` (OL2-3 contract, epic §7.5).
QUESTIONS: tuple[tuple[str, str, str], ...] = (
    (Q_DISTINCT, "¿Qué te hace distinto?", "Qué te hace distinto"),
    (Q_BUYERS, "¿Quién te compra?", "Quién te compra"),
    (
        Q_PHRASE,
        "¿Cómo le dirías a un cliente que llegó algo nuevo?",
        "Cómo le hablas a tus clientes",
    ),
)
QUESTION_KEYS: tuple[str, ...] = tuple(key for key, _q, _i in QUESTIONS)
TOTAL_QUESTIONS = len(QUESTIONS)
SCREENS: tuple[str, ...] = (SCREEN_MISSING, *QUESTION_KEYS, SCREEN_READY)


def missing_title(left: int) -> str:
    """T16 / T16b / T16c by how many questions are still empty (clamped to 1..3: with
    the three answered, finishing is the one thing left)."""
    return MISSING_TITLES[max(1, min(left, TOTAL_QUESTIONS))]


def counter(key: str) -> str:
    """T17 — «{n} de 3» above a question; "" elsewhere."""
    if key not in QUESTION_KEYS:
        return ""
    return f"{QUESTION_KEYS.index(key) + 1} de {TOTAL_QUESTIONS}"


def clamp_screen(name: object) -> str:
    """A screen name from the client, or the checklist."""
    return name if isinstance(name, str) and name in SCREENS else SCREEN_MISSING


def next_screen(name: str) -> str:
    """Continuar: the next question; the last one has «Terminar mi marca» instead."""
    name = clamp_screen(name)
    if name == SCREEN_MISSING:
        return QUESTION_KEYS[0]
    if name in QUESTION_KEYS:
        index = QUESTION_KEYS.index(name)
        return QUESTION_KEYS[min(index + 1, TOTAL_QUESTIONS - 1)]
    return name


def previous_screen(name: str) -> str:
    """Atrás: the question before; the first one goes back to the checklist."""
    name = clamp_screen(name)
    if name in QUESTION_KEYS:
        index = QUESTION_KEYS.index(name)
        return QUESTION_KEYS[index - 1] if index else SCREEN_MISSING
    return SCREEN_MISSING


# -- who takes this path ----------------------------------------------------------------

#: `brand_prefill_review.STATE_APPROVED` — the proposal document's state after «Aprobar».
PREFILL_APPROVED = "approved"


def prefill_state(connect: Mapping[str, Any] | None, key: str = "prefill") -> str:
    """`connect.prefill.state` ("" when there is no proposal document)."""
    document = (connect or {}).get(key)
    if not isinstance(document, Mapping):
        return ""
    return str(document.get("state") or "")


def applies(*, state: str, rubro: str, has_logo: bool, palette: str) -> bool:
    """This path is for the owner whose «Aprobar» left the rubro, the logo and the
    colours filled. «Cambiar», «Empezar de cero», an account that could not be read, or
    an approval that left one of the three empty: the five steps, unchanged."""
    return state == PREFILL_APPROVED and bool(rubro.strip()) and has_logo and bool(palette.strip())


@dataclass(frozen=True)
class Answers:
    """The three answers as the kit holds them."""

    distinct: str = ""
    buyers: str = ""
    phrase: str = ""

    def of(self, key: str) -> str:
        return {Q_DISTINCT: self.distinct, Q_BUYERS: self.buyers, Q_PHRASE: self.phrase}.get(
            key, ""
        )

    def answered(self) -> tuple[bool, bool, bool]:
        return (bool(self.distinct.strip()), bool(self.buyers.strip()), bool(self.phrase.strip()))

    @property
    def left(self) -> int:
        return sum(1 for done in self.answered() if not done)


def first_unanswered(answers: Answers) -> str | None:
    """The first question still empty; None when the three are answered."""
    for key, done in zip(QUESTION_KEYS, answers.answered(), strict=True):
        if not done:
            return key
    return None


def resume_screen(answers: Answers) -> str:
    """Where /brand opens on this path: the checklist while nothing is answered (right
    after «Aprobar», or an owner who left from there); otherwise the first question
    still empty — or the last one, with «Terminar mi marca», when the three are."""
    if answers.left == TOTAL_QUESTIONS:
        return SCREEN_MISSING
    return first_unanswered(answers) or QUESTION_KEYS[-1]


# -- the rubro's example (T22–T25) --------------------------------------------------------

EXAMPLE_FOOD = "comida"
EXAMPLE_ICE_CREAM = "heladeria"
EXAMPLE_REAL_ESTATE = "inmobiliaria"
EXAMPLE_TRAVEL = "viajes"

#: One example per question, by rubro (T22–T25), literal.
EXAMPLES: dict[str, tuple[str, str, str]] = {
    EXAMPLE_FOOD: (
        "Hacemos todo el mismo día, con receta de la casa.",
        "Familias y oficinas de la zona que piden a domicilio.",
        "Llegó el combo nuevo: pruébalo esta semana.",
    ),
    EXAMPLE_ICE_CREAM: (
        "Helados de yogur sin azúcar añadida.",
        "Gente que cuida lo que come y quiere darse un gusto.",
        "Llegó un sabor nuevo: ven a probarlo.",
    ),
    EXAMPLE_REAL_ESTATE: (
        "Te acompañamos desde la visita hasta la firma.",
        "Familias que buscan su primera casa.",
        "Tenemos un apartamento nuevo en la zona que buscabas.",
    ),
    EXAMPLE_TRAVEL: (
        "Armamos el viaje completo, tú solo haces la maleta.",
        "Parejas y familias que viajan en vacaciones.",
        "Abrimos cupos para un destino nuevo.",
    ),
}

#: Words of the rubro written by the owner (or read by the Alta) → example set. Checked
#: before the niche: «heladería» is food by niche, but has its own examples.
_RUBRO_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (EXAMPLE_ICE_CREAM, ("helad", "yogur", "gelato", "paleta")),
    (EXAMPLE_REAL_ESTATE, ("inmobiliari", "bienes raices", "finca raiz", "apartament", "arriendo")),
    (EXAMPLE_TRAVEL, ("viaje", "turism", "agencia de viaj", "tour")),
)
#: The niches (`discovery_seed.NICHE_LABELS` keys) with their own examples.
_SECTOR_EXAMPLES: dict[str, str] = {
    "real_estate": EXAMPLE_REAL_ESTATE,
    "travel_lifestyle": EXAMPLE_TRAVEL,
}


def _plain(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


def example_set(*, sector: str, rubro: str) -> str:
    """The rubro's examples: by the words of the rubro first, then by its niche; any
    other rubro uses the food ones (the epic's fallback, §7.12 question 3)."""
    plain = _plain(rubro)
    for key, words in _RUBRO_WORDS:
        if any(word in plain for word in words):
            return key
    return _SECTOR_EXAMPLES.get(sector.strip(), EXAMPLE_FOOD)


def example_hint(set_key: str, question: str) -> str:
    """«Por ejemplo: «…»» under a question's field: help text, never the answer."""
    examples = EXAMPLES.get(set_key, EXAMPLES[EXAMPLE_FOOD])
    if question not in QUESTION_KEYS:
        return ""
    return f"Por ejemplo: «{examples[QUESTION_KEYS.index(question)]}»"


def example_hints(set_key: str) -> dict[str, str]:
    return {key: example_hint(set_key, key) for key in QUESTION_KEYS}


# -- B1 drafts (OL2-3 contract, epic §7.5) -----------------------------------------------

#: Where the drafts live inside the proposal document.
DRAFTS_KEY = "borradores"


def _draft_text(raw: Any) -> str:
    """One draft: `{"texto": str, "fuente": str}` (the contract), or a bare string."""
    if isinstance(raw, Mapping):
        raw = raw.get("texto")
    return mask_phones(raw.strip()) if isinstance(raw, str) else ""


def tone_draft_from(connect: Mapping[str, Any] | None) -> dict[str, int]:
    """A sourced proposal's four axes; never the owner's voice before confirmation."""
    document = (connect or {}).get("prefill")
    if not isinstance(document, Mapping) or document.get("state") != PREFILL_APPROVED:
        return {}
    proposal = document.get("proposal")
    drafts = proposal.get(DRAFTS_KEY) if isinstance(proposal, Mapping) else None
    tone = drafts.get("tono") if isinstance(drafts, Mapping) else None
    if not isinstance(tone, Mapping) or not str(tone.get("fuente") or "").strip():
        return {}
    fields = ("formal_casual", "sober_enthusiastic", "technical_plain", "brief_elaborate")
    if not all(type(tone.get(key)) is int and 0 <= tone[key] <= 100 for key in fields):
        return {}
    return {key: tone[key] for key in fields}


def drafts_from(connect: Mapping[str, Any] | None, key: str = "prefill") -> dict[str, str]:
    """The B1 drafts of an APPROVED proposal (`prefill.proposal.borradores`), by
    question key, only those with text. Nothing else in the document is read; anything
    malformed is no draft (the question then shows the rubro's example)."""
    document = (connect or {}).get(key)
    if not isinstance(document, Mapping) or document.get("state") != PREFILL_APPROVED:
        return {}
    proposal = document.get("proposal")
    if not isinstance(proposal, Mapping):
        return {}
    drafts = proposal.get(DRAFTS_KEY)
    if not isinstance(drafts, Mapping):
        return {}
    out: dict[str, str] = {}
    for question in QUESTION_KEYS:
        text = _draft_text(drafts.get(question))
        if text:
            out[question] = text
    return out


def shows_draft(*, drafts: Mapping[str, str], question: str, answer: str, correcting: bool) -> bool:
    """A draft card stands while the question is still unanswered and the owner has not
    chosen «Corregir»: it never sits over an answer the owner already gave."""
    return bool(drafts.get(question)) and not answer.strip() and not correcting

"""Deterministic Spanish surface analysis of the opening's words.

Tier: lexical. Regex over the ASR transcript and the on-screen text. Exact given its
input, free, and — this is the point — **independent of the VLM**. If the VLM tier turns
out unreliable on the golden set, the Fase D analysis still has a signal layer that
stands on its own, and the two can be compared against each other for free (§B.4).

It is not a language model and does not pretend to be one: `classify_lexical` returns
`None` when no rule fires, rather than falling back to a catch-all category. A catch-all
would quietly become the largest bucket in the corpus and make every later statistic
about it meaningless.
"""

from __future__ import annotations

import re
import unicodedata

from qualify_models.hooks.schema import SpokenHook
from qualify_models.hooks.spec import HookType

_WORD_RE = re.compile(r"\w+", re.UNICODE)

# --- surface markers (reported as features regardless of hook type) ---
# Spanish is pro-drop: "¿Estás cansado de la ciudad?" addresses the viewer directly with no
# pronoun anywhere. A pronoun-only detector would miss most second-person hooks, and that
# is the single marker most worth measuring here ("does the opening talk TO the viewer?").
#
# Two patterns instead of one, because accent-folding creates homographs. "estás" (verb,
# second person) folds onto "estas" (demonstrative, "estas casas"), and counting the
# demonstrative would invent second-person address that is not there. The accent-sensitive
# forms are therefore matched against the *unfolded* text.
_SECOND_PERSON_FOLDED_RE = re.compile(
    r"\b(tu|tus|te|ti|contigo|usted|ustedes|vosotros|vuestr[oa]s?|os"
    r"|tienes|quieres|puedes|sabes|buscas|necesitas|vives|pagas|vas|eres"
    r"|sigues|piensas|crees|conoces|sientes|imaginas|recuerdas|entiendes)\b"
)
_SECOND_PERSON_ACCENTED_RE = re.compile(
    r"\b(estás|serás|harás|verás|podrás|tendrás|dejarás|deberías|podrías|querrías)\b"
)
_NEGATION_RE = re.compile(r"\b(no|nunca|jamas|ni|tampoco)\b")
_NUMERAL_RE = re.compile(r"\b(\d[\d.,]*|un|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\b")
_PRICE_RE = re.compile(r"(€|\beuros?\b|\beur\b|\bd[oó]lares?\b|\$)|\b\d{1,3}[.\s]\d{3}\b")
_IMPERATIVES = (
    "mira|mirad|escucha|fijate|atencion|ven|vente|guarda|apunta|espera|para|dime|"
    "imagina|piensa|comparte|sigueme|entra|descubre"
)
_IMPERATIVE_RE = re.compile(rf"\b({_IMPERATIVES})\b")

# --- hook-type rules, applied in this order (see NOTES §A.4 / §B.2 for the precedence) ---
_RULES: tuple[tuple[HookType, re.Pattern[str]], ...] = (
    (
        HookType.NUMERIC_LIST,
        re.compile(r"^\W*(\d{1,2}|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+\w{3,}"),
    ),
    (
        HookType.CURIOSITY_GAP,
        re.compile(
            r"\b(no (te )?(vas a )?(creer|imaginas)|espera a ver|adivina|lo que (hay )?detras|"
            r"no te esperas|nadie te (dice|cuenta)|el secreto)\b"
        ),
    ),
    (
        HookType.NEGATION_WARNING,
        re.compile(
            r"^\W*(no|nunca|jamas|cuidado|ojo)\b|\b(antes de (comprar|firmar|alquilar)"
            r"|no (compres|firmes|alquiles|hagas))\b"
        ),
    ),
    (
        HookType.PAIN_POINT,
        re.compile(
            r"\b(cansad[oa]s? de|hart[oa]s? de|estas pagando|pagas \d|te cuesta|"
            r"no puedes permitirte|atrapad[oa])\b"
        ),
    ),
    (
        HookType.SOCIAL_PROOF,
        re.compile(
            r"\b(mis clientes|esta familia|un cliente|se vendio en|vendimos|"
            r"lo compraron|ya han? (comprado|confiado))\b"
        ),
    ),
    (
        HookType.PERSONAL_STORY,
        re.compile(r"\b(hace \w+ (anos|meses)|yo vivia|cuando yo|me mude|mi primer[a]? )\b"),
    ),
    (
        HookType.LOCATION_REVEAL,
        re.compile(r"\b(a \d+ (minutos|km|kilometros) de|esto esta en|en pleno|a las afueras)\b"),
    ),
    (HookType.PRICE_REVEAL, _PRICE_RE),
    # Imperative only counts as the hook when it *opens* the window; "mira" halfway
    # through a sentence is not a command hook.
    (HookType.COMMAND_CTA, re.compile(rf"^\W*({_IMPERATIVES})\b")),
)


def strip_accents(text: str) -> str:
    """Fold accents so 'fíjate' and 'fijate' match the same rule. ASR output is
    inconsistent about accents and a rule that only fires on the accented spelling
    silently under-counts."""
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", strip_accents(text.lower())).strip()


def analyze_speech(text: str, window_seconds: float) -> SpokenHook:
    """Build the spoken channel's feature block from the window's transcript."""
    raw = text.strip()
    norm = _normalize(raw)
    words = _WORD_RE.findall(norm)
    word_count = len(words)
    return SpokenHook(
        has_speech=word_count > 0,
        text=raw,
        word_count=word_count,
        words_per_second=(word_count / window_seconds) if window_seconds > 0 else 0.0,
        # '?'/'¿' are checked on the raw string: accent-folding keeps them, but lowering
        # does not create them, and ASR often emits only the closing '?'.
        has_question_mark="?" in raw or "¿" in raw,
        has_numeral=bool(_NUMERAL_RE.search(norm)),
        has_second_person=(
            bool(_SECOND_PERSON_FOLDED_RE.search(norm))
            or bool(_SECOND_PERSON_ACCENTED_RE.search(raw.lower()))
        ),
        has_negation=bool(_NEGATION_RE.search(norm)),
        has_imperative_marker=bool(_IMPERATIVE_RE.search(norm)),
        has_price_token=bool(_PRICE_RE.search(norm)),
    )


def classify_lexical(spoken_text: str, on_screen_text: str | None = None) -> HookType | None:
    """Type the hook from its words alone, or `None` if no rule fires.

    Both channels are read together — a video whose gancho is burned into the screen with
    no voiceover has a hook, and reading only the transcript would score it as silent.

    Precedence, deliberate and worth knowing when reading results: **an opening that both
    asks a question and names a pain is typed `question`**. The founder's own example
    ("¿estás cansado de la ciudad?") is exactly that case. The question mark is the more
    reliable signal (it is punctuation, not semantics), so it wins; `pain_point` is left
    for openings that state the pain without asking.
    """
    combined_raw = " ".join(part for part in (spoken_text, on_screen_text or "") if part).strip()
    if not combined_raw:
        return None

    if "?" in combined_raw or "¿" in combined_raw:
        return HookType.QUESTION

    norm = _normalize(combined_raw)
    if not norm:
        return None

    for hook_type, pattern in _RULES:
        if pattern.search(norm):
            return hook_type
    # There are words but no rule matched. Returning None (rather than `direct_claim`)
    # keeps the catch-all from swallowing the corpus; the caller records the honest state.
    return None

"""Deterministic Spanish surface analysis of the opening's words.

Tier: lexical. Regex over the ASR transcript and the on-screen text. Exact given its
input, free, and — this is the point — **independent of the VLM**. If the VLM tier turns
out unreliable on the golden set, the Fase D analysis still has a signal layer that
stands on its own, and the two can be compared against each other for free (§B.4).

It is not a language model and does not pretend to be one: `classify_lexical` returns
`None` when no rule fires, rather than falling back to a catch-all category. A catch-all
would quietly become the largest bucket in the corpus and make every later statistic
about it meaningless.

**Dialect scope (widened 2026-08-06).** This file was written in peninsular Spanish. The
chosen corpus is the Venezuela-Colombia border — San Cristóbal/Táchira and
Cúcuta/Norte de Santander — so every rule now has to hold for three registers at once:
peninsular *tú*, LatAm *tú*, and *usted*, which is dominant in Santander and common in
Táchira. The failure mode being fixed is the dangerous kind: none of this errored, it
returned confident, plausible, wrong values (`has_second_person=False` on an opening that
addresses the viewer in every sentence). Peninsular forms are kept, not replaced — the
extractor handles all three or it cannot compare accounts across the border.
"""

from __future__ import annotations

import re
import unicodedata

from qualify_models.hooks.schema import SecondPersonRegister, SpokenHook
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
    r"\b(tu|tus|te|ti|contigo|vosotros|vuestr[oa]s?|os"
    r"|tienes|quieres|puedes|sabes|buscas|necesitas|vives|pagas|vas|eres"
    r"|sigues|piensas|crees|conoces|sientes|imaginas|recuerdas|entiendes)\b"
)
_SECOND_PERSON_ACCENTED_RE = re.compile(
    r"\b(estás|serás|harás|verás|podrás|tendrás|dejarás|deberías|podrías|querrías)\b"
)

# --- usted: the register this file originally could not see -------------------------
# *usted* is not symmetrical with *tú*. Its verb forms are identical to the third person,
# so "¿Está cansado?" (addresses the viewer) and "El apartamento está listo" (does not)
# are the same shape. Detection therefore needs evidence, in three tiers, and where there
# is none the honest answer is "ambiguous" — never a guess in either direction.
_USTED_PRONOUN_RE = re.compile(r"\b(usted|ustedes)\b")
"""Tier 1: explicit and unambiguous. This much already worked; the pronoun was in the
folded pattern above and has been moved here so the register can be named."""

# Tier 2: usted imperatives. Unambiguous as commands, so they count with no interrogative.
# Two deliberate omissions, both of which would poison a real-estate corpus: `entre` is far
# more often the preposition ("entre 200 y 300 millones") than the imperative of "entrar",
# and `pare` collides with the ubiquitous "para".
_USTED_IMPERATIVES = (
    "mire|vea|escuche|fijese|venga|vengase|guarde|apunte|espere|digame|"
    "imaginese|piense|comparta|sigame|descubra|aproveche|revise|pregunte|muestre"
)
# _ENCLITICS is appended below, where it is defined alongside the tú imperatives.

# Negative imperatives are the other half of the command register and are *only*
# distinguishable by register: "no firmes" is tú, "no firme" is usted. Neither spelling was
# detected as address before, so "No firme nada sin ver esto" — a textbook warning hook —
# reported that nobody was being addressed. Both are listed, in their own patterns, because
# collapsing them would throw away exactly the distinction this corpus needs.
# Split by conjugation class rather than lumped together, and not for tidiness: -ar verbs
# take -e for usted and -er/-ir verbs take -a, so a single "[ea]" pattern would match "no
# espera" (third-person indicative, "he is not waiting") as if it were "no espere" (an
# usted command). Conjugating properly costs one extra constant and removes the collision.
_NEG_IMP_AR = "compr|firm|alquil|arriend|dej|olvid|esper"
_NEG_IMP_ER_IR = "hag|pierd|inviert"
_TU_NEG_IMPERATIVE_RE = re.compile(rf"\bno\s+(({_NEG_IMP_AR})es|({_NEG_IMP_ER_IR})as)\b")
_USTED_NEG_IMPERATIVE_RE = re.compile(rf"\bno\s+(({_NEG_IMP_AR})e|({_NEG_IMP_ER_IR})a)\b")

# Tier 3: usted indicative — identical to the third person, so it counts as address ONLY
# inside an interrogative. Hooks that address the viewer this way are overwhelmingly
# questions ("¿Está pagando arriendo?"), while the third-person reading is overwhelmingly
# declarative ("Mi cliente quiere comprar"). That asymmetry is the entire discriminator;
# outside a question the same verb yields "ambiguous", not True.
_USTED_INDICATIVE_RE = re.compile(
    r"\b(tiene|quiere|puede|sabe|busca|necesita|vive|paga|sigue|piensa|cree|"
    r"conoce|siente|recuerda|entiende)\b"
)
# Accent-sensitive half, matched against the *unfolded* text for the same reason the tú
# patterns are: folded "esta" is the demonstrative in "esta casa", which opens a large
# fraction of real-estate hooks. Folding it would have swept most of the corpus into the
# "ambiguous" bucket and made that bucket useless as a diagnostic. Same exposure the tú
# path already accepts: if ASR drops the accent, this misses rather than over-fires.
_USTED_INDICATIVE_ACCENTED_RE = re.compile(r"\b(está|debería|podría|querría|gustaría)\b")

_NEGATION_RE = re.compile(r"\b(no|nunca|jamas|ni|tampoco)\b")
_NUMERAL_RE = re.compile(r"\b(\d[\d.,]*|un|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\b")

# Prices, in the three currencies this corpus actually speaks:
# * Venezuela quotes real estate in US dollars ("$", "dólares", slang "verdes") — which is
#   why the euro-shaped detector already scored 3/4 there, and why the claim that it fails
#   region-wide is only half true.
# * Colombia quotes in millions of pesos, usually with no symbol and no thousands
#   separator: "250 millones", "300 palos". The old pattern scored 0/4 on exactly those.
# * The peninsular forms stay. Swapping one regionalism for another just moves the hole.
# `millones`/`palos`/`verdes` require a preceding numeral, so "un millón de razones" and
# "las paredes verdes" do not become prices.
_PRICE_RE = re.compile(
    r"(€|\beuros?\b|\beur\b|\bd[oó]lares?\b|\$|\busd\b"
    r"|\bpesos?\b|\bcop\b|\bbol[ií]var(es)?\b|\bbs\b|\bves\b)"
    r"|\b\d[\d.,]*\s*(mil\s+)?(millon(es)?|palos|verdes)\b"
    r"|\b\d{1,3}[.\s]\d{3}\b"
)

# `para` used to be in this list and is deliberately gone: it matched the preposition in
# "ideal para comprar", so has_imperative_marker fired on openings with no command at all.
_IMPERATIVES = (
    "mira|mirad|escucha|fijate|atencion|ven|vente|guarda|apunta|espera|dime|"
    "imagina|piensa|comparte|sigueme|entra|descubre|muestra"
)

# Spanish attaches object pronouns to the end of an imperative, and the result is one
# word: "mírala", "mírela", "cómprela", "muéstrame", "véalo". Without this, every such
# opening scored as having no command at all — "Mírala bien" and "Mírela bien" both
# returned hook_type=None. The gap was symmetric across registers, so it is a plain bug
# that the dialect work surfaced rather than a dialect issue of its own.
_ENCLITICS = "me|te|se|le|lo|la|les|los|las|nos|melo|mela|selo|sela|selos|selas"

# Verbs whose bare imperative collides with a common noun or preposition ("la compra de tu
# casa", "una llamada") but which are unambiguous once a pronoun is attached, because nouns
# do not take enclitics. Requiring the clitic buys "cómprela"/"cómprala" with no false
# positives. Listed per register so neither side gains an advantage over the other.
_TU_IMPERATIVES_CLITIC_ONLY = "compra|llama|escribe"
_USTED_IMPERATIVES_CLITIC_ONLY = "compre|llame|escriba"


def _address_pattern(imperatives: str, clitic_only: str) -> re.Pattern[str]:
    """An imperative counts as *addressing the viewer* only with real evidence: it opens
    the window, or it carries an attached pronoun.

    Bare imperatives are homographs of the third-person indicative in both registers —
    "espera" is equally "wait!" and "he waits", "mira" equally "look!" and "she looks at".
    Matching them anywhere in the text made "El vendedor no espera respuesta" report that
    the video addresses the viewer. Opening position is the same evidence the COMMAND_CTA
    rule already demanded, and an enclitic ("mírela") is unambiguous on its own.

    Deliberately stricter than `has_imperative_marker`, which stays a loose anywhere-match:
    that one is a coarse feature, while this feeds the register column that F5 uses to test
    whether address tracks country. A confounder detector has to be the conservative one.
    """
    return re.compile(
        rf"^\W*({imperatives})\b"
        rf"|\b({imperatives})({_ENCLITICS})\b"
        rf"|\b({clitic_only})({_ENCLITICS})\b"
    )


_TU_IMPERATIVE_RE = _address_pattern(_IMPERATIVES, _TU_IMPERATIVES_CLITIC_ONLY)
_USTED_IMPERATIVE_RE = _address_pattern(_USTED_IMPERATIVES, _USTED_IMPERATIVES_CLITIC_ONLY)
_ALL_IMPERATIVES = f"{_IMPERATIVES}|{_USTED_IMPERATIVES}"
_ALL_IMPERATIVES_CLITIC_ONLY = f"{_TU_IMPERATIVES_CLITIC_ONLY}|{_USTED_IMPERATIVES_CLITIC_ONLY}"
_IMPERATIVE_PATTERN = (
    rf"(({_ALL_IMPERATIVES})({_ENCLITICS})?|({_ALL_IMPERATIVES_CLITIC_ONLY})({_ENCLITICS}))"
)
_IMPERATIVE_RE = re.compile(rf"\b{_IMPERATIVE_PATTERN}\b")

# --- hook-type rules, applied in this order (see NOTES §A.4 / §B.2 for the precedence) ---
_RULES: tuple[tuple[HookType, re.Pattern[str]], ...] = (
    (
        HookType.NUMERIC_LIST,
        re.compile(r"^\W*(\d{1,2}|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+\w{3,}"),
    ),
    (
        HookType.CURIOSITY_GAP,
        re.compile(
            r"\b(no (te |se )?(vas? a )?(creer|imaginas?)|espera a ver|adivina|"
            r"lo que (hay )?detras|no (te|se) espera|nadie (te|le) (dice|cuenta)|"
            r"el secreto)\b"
        ),
    ),
    (
        HookType.NEGATION_WARNING,
        # "arrendar" is the Colombian verb; "alquilar" the peninsular/Venezuelan one. Both,
        # because the corpus straddles the border and an advisor uses one or the other.
        re.compile(
            r"^\W*(no|nunca|jamas|cuidado|ojo)\b"
            r"|\b(antes de (comprar|firmar|alquilar|arrendar|invertir)"
            r"|no (compres|firmes|alquiles|arriendes|hagas)"
            r"|no (compre|firme|alquile|arriende|haga))\b"
        ),
    ),
    (
        HookType.PAIN_POINT,
        re.compile(
            r"\b(cansad[oa]s? de|hart[oa]s? de|estas pagando|esta pagando|pagas \d|paga \d|"
            r"te cuesta|le cuesta|no puedes permitirte|no puede permitirse|atrapad[oa])\b"
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
        # "queda" is how distance is stated on both sides of the border ("queda a 10
        # minutos"); the peninsular "está a" alone missed it.
        re.compile(
            r"\b(a \d+ (minutos|km|kilometros) de|queda a \d+|esto (esta|queda) en|"
            r"en pleno|a las afueras|via a |vereda )\b"
        ),
    ),
    (HookType.PRICE_REVEAL, _PRICE_RE),
    # Imperative only counts as the hook when it *opens* the window; "mira" halfway
    # through a sentence is not a command hook. Both registers open windows here: an
    # usted-speaking advisor's "Mire este apartamento" is the same hook as "Mira este
    # apartamento", and before this it fell out of the taxonomy entirely.
    (HookType.COMMAND_CTA, re.compile(rf"^\W*{_IMPERATIVE_PATTERN}\b")),
)


def strip_accents(text: str) -> str:
    """Fold accents so 'fíjate' and 'fijate' match the same rule. ASR output is
    inconsistent about accents and a rule that only fires on the accented spelling
    silently under-counts."""
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", strip_accents(text.lower())).strip()


def second_person_register(text: str) -> SecondPersonRegister:
    """Which register the opening uses to address the viewer, if any.

    Order matters. *tú* wins when both appear, because *tú* forms are unambiguous while
    *usted* forms are shared with the third person: given conflicting evidence, believe
    the half that cannot be misread.

    The `"ambiguous"` outcome is the point of this function. An opening like "El
    apartamento tiene tres cuartos" carries an *usted*-shaped verb and addresses nobody;
    resolving that to `"usted"` would invent direct address, and resolving it to `"none"`
    would hide that the corpus is full of undecidable cases. Fase D can then ask how big
    that bucket is instead of inheriting a silent assumption.
    """
    raw_lower = text.lower()
    norm = _normalize(text)
    # Imperatives count as address in BOTH registers, and the symmetry is load-bearing:
    # an earlier version of this function fed only the usted imperatives into the register,
    # which made usted-speaking accounts look like they addressed the viewer more often
    # than tú-speaking ones. That is a bias planted directly in the F5 variable — the one
    # column meant to detect whether register tracks country.
    if (
        _SECOND_PERSON_FOLDED_RE.search(norm)
        or _SECOND_PERSON_ACCENTED_RE.search(raw_lower)
        or _TU_NEG_IMPERATIVE_RE.search(norm)
        or _TU_IMPERATIVE_RE.search(norm)
    ):
        return "tu"
    if (
        _USTED_PRONOUN_RE.search(norm)
        or _USTED_IMPERATIVE_RE.search(norm)
        or _USTED_NEG_IMPERATIVE_RE.search(norm)
    ):
        return "usted"
    if _USTED_INDICATIVE_RE.search(norm) or _USTED_INDICATIVE_ACCENTED_RE.search(raw_lower):
        # Interrogative is the disambiguator; see the Tier 3 note above.
        return "usted" if ("?" in text or "¿" in text) else "ambiguous"
    return "none"


def analyze_speech(text: str, window_seconds: float) -> SpokenHook:
    """Build the spoken channel's feature block from the window's transcript."""
    raw = text.strip()
    norm = _normalize(raw)
    words = _WORD_RE.findall(norm)
    word_count = len(words)
    register = second_person_register(raw)
    return SpokenHook(
        has_speech=word_count > 0,
        text=raw,
        word_count=word_count,
        words_per_second=(word_count / window_seconds) if window_seconds > 0 else 0.0,
        # '?'/'¿' are checked on the raw string: accent-folding keeps them, but lowering
        # does not create them, and ASR often emits only the closing '?'.
        has_question_mark="?" in raw or "¿" in raw,
        has_numeral=bool(_NUMERAL_RE.search(norm)),
        # "ambiguous" deliberately does NOT set this flag: an usted-shaped verb with no
        # disambiguating evidence is not evidence of address.
        has_second_person=register in ("tu", "usted"),
        second_person_register=register,
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

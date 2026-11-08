"""«Sugerir con IA» on the WhatsApp automatic-reply menu (m-24936838).

In `/whatsapp` → Respuesta automática the owner writes a greeting and the «respuestas de
siempre» (Horario, Domicilio, Dónde estamos…). One tap and Claude proposes that text in the
brand's voice, using ONLY the facts the owner already typed (spec:
`docs/ux-whatsapp-respuestas-de-siempre.md` §5). Assisted, never autonomous: the proposal
replaces the field on screen, the owner can undo it, nothing is stored or published here.

Mirrors `qualify_api.creative.context_ai` («Potenciar con IA»): one strict tool
(`propose_text`), the `claude_tools` plumbing (key, Langfuse trace, `Meter`), plus the
per-turn dollar meter (`DollarMeter`, m-24854322): every suggestion has a hard budget
(`SUGGEST_BUDGET_USD`) that covers the first turn and the one retry at their worst.

**No new facts.** A schedule, price, zone, promotion, address or payment method that is not
in the input never comes back as true: where a fact is missing the text keeps (or gets) a
gap in brackets — `starter.find_gaps`'s convention, `[hora de abrir]` — which the editor
refuses to publish. What the code enforces after the model answers:

- every gap of `current_text` whose fact the owner has not given stays in the text (it is
  added back, before the closing line, when the model dropped it) and is listed in
  `missing`; a gap may only go when the model names the fact of that same name, the fact
  has a value free of gaps, and that value is in the proposed text;
- banned words and forbidden claims of the kit: **one retry** naming them, then
  `SuggestUnavailable` (stripping a word mid-sentence could change what the text says);
- «Otra versión» (`previous_text`): a proposal equal to it (whitespace and case folded)
  gets the same one retry, then `SuggestUnavailable`;
- facts the model reports as added (`added_facts`): part of the one retry; whatever is
  still reported after it reaches the owner as a warning to check;
- WhatsApp plain text: Markdown links and headings removed, `**x**` → `*x*`; emoji removed
  when the kit says «none» or there is no kit;
- cut to `max_chars` at a sentence end, never mid-word (as context_ai).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Final, Protocol
from uuid import UUID

from qualify_creative.enums import EmojiPolicy
from qualify_creative.schemas import BrandKit
from qualify_shared import observability

from qualify_api.claude_tools import (
    Attribution,
    ClaudeToolError,
    ClientFactory,
    DollarMeter,
    Meter,
    ModelConfig,
    api_key_from_env,
    create_turn,
    default_client,
    forced_or_auto,
    strict_tool,
    tool_uses,
)
from qualify_api.whatsapp.menus.starter import find_gaps

logger = logging.getLogger("qualify_api.whatsapp.menus.suggest_ai")

try:  # the SDK is an optional dependency (`qualify-creative[llm]`)
    import anthropic

    #: Transport failures `create_turn` re-raises as they are (429, 5xx, connection, timeout).
    _TRANSPORT_ERRORS: tuple[type[BaseException], ...] = (
        anthropic.APIError,
        ConnectionError,
        TimeoutError,
    )
except ImportError:  # pragma: no cover — offline installs without the SDK
    _TRANSPORT_ERRORS = (ConnectionError, TimeoutError)

SUGGEST_MODEL: Final = ModelConfig("claude-sonnet-5-5", effort="low")
TOOL_NAME: Final = "propose_text"
#: Prompt version, for provenance in logs and the model card (bump on any prompt change).
PROMPT_VERSION: Final = "wa-suggest-1"
#: The function the consumption ledger books these calls to (m-24955649).
FEATURE: Final = "wa-suggest"
#: Room for low-effort thinking plus a short tool call (thinking counts against it).
MAX_TOKENS: Final = 3072
#: The hard dollar bound of ONE suggestion (both turns): twice the worst turn of the
#: largest input the caps below allow, rounded up (pinned by a test).
SUGGEST_BUDGET_USD: Final = Decimal("0.17")

KINDS: Final = ("greeting", "answer")
MIN_CHARS: Final = 80
MAX_CHARS: Final = 1024  # an interactive WhatsApp body
DEFAULT_MAX_CHARS: Final = 400

# Input caps: they bound the prompt, hence the turn's worst price.
MAX_FACTS: Final = 20
MAX_OTHER_ANSWERS: Final = 12  # starter.MAX_ANSWERS
NAME_MAX: Final = 60
FACT_MAX: Final = 160
OTHER_TEXT_MAX: Final = 300
FIELD_MAX: Final = 1024
KIT_LINE_MAX: Final = 120

#: The menu's real way back: the starter's keyword «menú» opens the products.
MENU_CLOSING: Final = "Para pedir, escribe *menú*."

# Owner-facing warnings (Spanish, qualify-copy-es).
WARN_ADDED_FACT: Final = "Revisa este dato: «{fact}». Tú no lo escribiste; bórralo si no es cierto."
WARN_CUT: Final = "Lo acortamos para que quepa en un mensaje corto."
#: A claimed fill was rejected: the gap is back, and the value the model wrote may be invented.
WARN_REJECTED_FILL: Final = "Quitamos un dato que no escribiste; revisa el texto."

SYSTEM_PROMPT: Final = (
    "Escribes los mensajes automáticos de WhatsApp de un negocio pequeño: el SALUDO con el "
    "que contesta y sus RESPUESTAS DE SIEMPRE (horario, domicilio, dónde están, formas de "
    "pago, reservas…). Los lee un cliente en su teléfono. Te llega qué escribir, el texto que "
    "hay ahora en el campo, los DATOS que el dueño ya escribió, las otras respuestas del menú "
    "y la IDENTIDAD DE LA MARCA (o que no hay).\n\n"
    "Escribe en español, con la forma de hablar de la marca y la variante del español que se "
    "indica; sin identidad de marca, con un tono amable y neutro. El trato al cliente («tú», «vos» "
    "o «usted») sigue los ejemplos de la marca («Así sí escribe»); sin ejemplos, «tú». "
    "Frases cortas, sin palabras en inglés ni modismos de un solo país.\n\n"
    "Reglas sin excepción:\n"
    "- NO inventes hechos: ningún horario, día, precio, costo de envío, zona, barrio, tiempo, "
    "dirección, forma de pago, promoción, descuento, premio ni afirmación que no esté en los "
    "DATOS, en el texto actual, en las otras respuestas o en la identidad de la marca.\n"
    "- Si te falta un dato, deja un hueco entre corchetes con el nombre del dato, por ejemplo "
    "[hora de cerrar], y nómbralo en «missing». Conserva todo hueco del texto actual cuyo "
    "dato no te dieron. Solo puedes quitar un hueco si lo completas con un dato que te dieron: "
    "dilo en «filled_gaps» con el nombre exacto de ese dato.\n"
    "- Respeta las palabras prohibidas y las afirmaciones prohibidas de la marca.\n"
    "- Texto plano de WhatsApp: sin títulos, sin viñetas, sin enlaces con formato; puedes "
    "usar *negrita* (un asterisco a cada lado) para una o dos palabras como mucho.\n"
    "- SALUDO: una o dos líneas cortas que saludan y dicen qué puede hacer el cliente. No "
    "enumeres las opciones: WhatsApp muestra los botones debajo.\n"
    "- RESPUESTA: la respuesta en sí, de una a tres líneas cortas, coherente con las otras "
    "respuestas. Si sirve para seguir, cierra con la forma real del menú: «" + MENU_CLOSING + "»\n"
    "- Si te dan una VERSIÓN ANTERIOR, escribe una distinta (otras palabras, otro orden), con "
    "los mismos datos.\n"
    "- Respeta el largo máximo que se indica.\n\n"
    "Responde ÚNICAMENTE llamando a la herramienta " + TOOL_NAME + "."
)


class SuggestUnavailable(RuntimeError):
    """No proposal: no key, a refusal, an unusable answer, a banned word or a repeated
    version after the retry, or the suggestion's dollar budget exhausted."""


@dataclass(frozen=True)
class SuggestInput:
    """What is on screen: the only facts the proposal may use."""

    kind: str  # "greeting" | "answer"
    answer_name: str  # e.g. "Horario"; "" for the greeting
    current_text: str  # the field now (may be empty, may contain [gaps])
    #: (name, value) the owner already typed; values may be empty or contain [gaps].
    facts: tuple[tuple[str, str], ...] = ()
    #: (name, text) of the other answers, for consistency.
    other_answers: tuple[tuple[str, str], ...] = ()
    previous_text: str = ""  # the last proposal, for «Otra versión»
    max_chars: int = DEFAULT_MAX_CHARS


@dataclass(frozen=True)
class SuggestProposal:
    text: str  # keeps every [gap] whose fact is missing
    missing: tuple[str, ...]  # gap names / facts the text still needs («Falta: …»)
    warnings: tuple[str, ...]  # Spanish, owner-facing
    neutral_voice: bool  # no brand identity → the screen points to «Tu marca»
    model_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    prompt_version: str = PROMPT_VERSION


class KitStore(Protocol):
    def get_kit(self, *, tenant_id: UUID, brand_id: UUID) -> BrandKit | None: ...


# --- Text helpers ------------------------------------------------------------------------


def _fold(value: str) -> str:
    """Case- and accent-insensitive form for comparisons."""
    decomposed = unicodedata.normalize("NFKD", value or "")
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(plain.casefold().split())


def _line(value: str, limit: int) -> str:
    return " ".join((value or "").split())[:limit].rstrip()


def _block(value: str, limit: int) -> str:
    """Multi-line text with its lines kept, at most `limit` characters."""
    lines = [" ".join(ln.split()) for ln in (value or "").strip().splitlines()]
    return "\n".join(ln for ln in lines if ln)[:limit].rstrip()


_EMOJI_RE = re.compile(
    "["
    "\U0001f000-\U0001faff"  # pictographs, emoticons, transport, symbols & pictographs ext.
    "\u2600-\u27bf"  # misc symbols, dingbats
    "\u2b00-\u2bff"  # arrows, stars
    "\ufe0f\u200d"  # variation selector, zero-width joiner
    "]"
)
_MD_LINK_RE = re.compile(r"\[([^\[\]\n]+)\]\((?:[^()\s]+)\)")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_BULLET_RE = re.compile(r"^\s*(?:[-•]|\d+[.)])\s+", re.MULTILINE)
_DOUBLE_STAR_RE = re.compile(r"\*\*([^*\n]+)\*\*")
_DANGLING_GAP_RE = re.compile(r"\s*\[[^\]\n]*$")


def _whatsapp_plain(text: str, *, emoji: bool) -> str:
    out = _MD_LINK_RE.sub(r"\1", text)
    out = _HEADING_RE.sub("", out)
    out = _BULLET_RE.sub("", out)
    out = _DOUBLE_STAR_RE.sub(r"*\1*", out)
    if not emoji:
        out = _EMOJI_RE.sub("", out)
    lines = [" ".join(ln.split()) for ln in out.strip().splitlines()]
    return "\n".join(ln for ln in lines if ln)


def _cut(text: str, limit: int) -> str:
    """At the last sentence end that fits, else the last whole word — never mid-word, and
    never leaving half a gap («[hora de»)."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(p) for p in (". ", ".\n", "! ", "!\n", "? ", "?\n"))
    if end > limit // 2:
        out = cut[: end + 1]
    elif len(text) > limit and text[limit] not in " \n":
        out = cut.rsplit(" ", 1)[0] if " " in cut else cut
    else:
        out = cut
    return _DANGLING_GAP_RE.sub("", out).strip()


def _usable(value: str) -> bool:
    return bool(value.strip()) and not find_gaps(value)


def _forbidden_hits(text: str, kit: BrandKit | None) -> list[str]:
    """Banned words (whole words) and forbidden claims (phrases) found in `text`."""
    if kit is None:
        return []
    folded = _fold(text)
    hits: list[str] = []
    for word in kit.banned_words:
        w = _fold(word)
        if w and re.search(rf"(?<!\w){re.escape(w)}(?!\w)", folded):
            hits.append(word.strip())
    for claim in kit.forbidden_claims:
        c = _fold(claim)
        if c and c in folded:
            hits.append(claim.strip())
    return hits


# --- The request -------------------------------------------------------------------------


def _clamp_chars(data: SuggestInput) -> int:
    return max(MIN_CHARS, min(MAX_CHARS, int(data.max_chars or DEFAULT_MAX_CHARS)))


def _facts(data: SuggestInput) -> list[tuple[str, str]]:
    return [
        (_line(name, NAME_MAX), _line(value, FACT_MAX))
        for name, value in data.facts[:MAX_FACTS]
        if _line(name, NAME_MAX)
    ]


def _brand_lines(kit: BrandKit | None) -> list[str]:
    if kit is None:
        return ["IDENTIDAD DE LA MARCA: (no hay) — tono amable y neutro, sin emojis"]
    axes = kit.tone_axes
    emoji = {
        EmojiPolicy.NONE: "ninguno",
        EmojiPolicy.SPARSE: "como mucho uno, si suma",
        EmojiPolicy.FREE: "pocos, si suman",
    }[kit.emoji_policy]
    lines = [
        "IDENTIDAD DE LA MARCA:",
        f"- Posicionamiento: {_line(kit.positioning, 240) or '-'}",
        f"- Público: {_line(kit.audience, 240) or '-'}",
        f"- Variante del español: {kit.regional_variant}",
        "- Tono (0-100): formal→casual "
        f"{axes.formal_casual}, sobrio→entusiasta {axes.sober_enthusiastic}, "
        f"técnico→llano {axes.technical_plain}, breve→extenso {axes.brief_elaborate}",
        f"- Emojis: {emoji}",
    ]
    for label, values in (
        ("Así sí escribe", kit.do_examples),
        ("Así no", kit.dont_examples),
        ("Palabras prohibidas", kit.banned_words),
        ("Afirmaciones prohibidas", kit.forbidden_claims),
        ("Llamados a la acción habituales", kit.cta_patterns),
    ):
        if values:
            lines.append(f"- {label}: " + " | ".join(_line(v, KIT_LINE_MAX) for v in values[:6]))
    return lines


def render_request(data: SuggestInput, kit: BrandKit | None, *, correction: str = "") -> str:
    """The user message: what to write, the facts, the other answers, the brand, the field."""
    if data.kind == "greeting":
        what = "el SALUDO del menú"
    else:
        what = f"la RESPUESTA «{_line(data.answer_name, NAME_MAX) or 'sin nombre'}»"
    facts = _facts(data)
    lines = [
        f"QUÉ ESCRIBIR: {what}",
        f"LARGO MÁXIMO: {_clamp_chars(data)} caracteres",
        "DATOS QUE EL DUEÑO YA ESCRIBIÓ:" if facts else "DATOS QUE EL DUEÑO YA ESCRIBIÓ: (ninguno)",
        *(f"- {name}: {value or '(vacío)'}" for name, value in facts),
    ]
    others = [
        (_line(name, NAME_MAX), _block(text, OTHER_TEXT_MAX))
        for name, text in data.other_answers[:MAX_OTHER_ANSWERS]
        if _line(name, NAME_MAX)
    ]
    if others:
        lines.append("OTRAS RESPUESTAS DEL MENÚ:")
        lines += [f"- {name}: {text or '(vacía)'}" for name, text in others]
    lines += ["", *_brand_lines(kit), "", "TEXTO ACTUAL DEL CAMPO:"]
    lines.append(_block(data.current_text, FIELD_MAX) or "(vacío)")
    if data.previous_text.strip():
        lines += ["", "VERSIÓN ANTERIOR (escribe una distinta):"]
        lines.append(_block(data.previous_text, FIELD_MAX))
    if correction:
        lines += ["", "CORRIGE ESTO DE TU PROPUESTA ANTERIOR:", correction]
    return "\n".join(lines)


def _tool() -> dict[str, Any]:
    return strict_tool(
        TOOL_NAME,
        "Propone el texto del saludo o de la respuesta.",
        {
            "text": {"type": "string", "description": "El texto propuesto, listo para enviar."},
            "missing": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Cada dato que necesitabas y no tenías (el nombre de su hueco).",
            },
            "filled_gaps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "gap": {"type": "string", "description": "El hueco, sin corchetes."},
                        "fact": {"type": "string", "description": "El nombre del dato usado."},
                    },
                    "required": ["gap", "fact"],
                    "additionalProperties": False,
                },
                "description": "Cada hueco del texto actual que completaste, y con qué dato.",
            },
            "added_facts": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Cada hecho (horario, precio, zona, dato) de tu texto que NO esté en los "
                    "datos, el texto actual, las otras respuestas ni la identidad de la marca. "
                    "Vacío si no añadiste ninguno."
                ),
            },
        },
    )


# --- The call ----------------------------------------------------------------------------


@dataclass
class _Answer:
    text: str
    missing: list[str] = field(default_factory=list)
    filled: list[tuple[str, str]] = field(default_factory=list)
    added: list[str] = field(default_factory=list)


def _ask(
    client: Any,
    meter: Meter,
    budget: DollarMeter,
    data: SuggestInput,
    kit: BrandKit | None,
    correction: str,
    attribution: Attribution,
) -> _Answer:
    # Each attempt is a fresh single-turn request whose bytes carry everything it sends:
    # its bound starts from them, not from the previous turn's (that is a growing chat).
    meter.last_bound = None
    try:
        response = create_turn(
            client,
            SUGGEST_MODEL,
            meter,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": render_request(data, kit, correction=correction)}
            ],
            tools=[_tool()],
            tool_choice=forced_or_auto(SUGGEST_MODEL, TOOL_NAME),
            max_tokens=MAX_TOKENS,
            budget=budget,
            attribution=attribution.versioned(PROMPT_VERSION),
        )
    except ClaudeToolError as exc:
        raise SuggestUnavailable(str(exc)) from exc
    except _TRANSPORT_ERRORS as exc:
        raise SuggestUnavailable(f"transport error: {type(exc).__name__}") from exc
    calls = [use for use in tool_uses(response) if use.name == TOOL_NAME]
    if not calls:
        raise SuggestUnavailable(f"{SUGGEST_MODEL.model_id} did not call {TOOL_NAME}")
    raw = calls[0].input or {}
    text = str(raw.get("text") or "").strip()
    if not text:
        raise SuggestUnavailable("empty text proposed")

    def strings(key: str) -> list[str]:
        return [str(v).strip() for v in raw.get(key) or () if str(v).strip()]

    filled = [
        (str(item.get("gap") or "").strip(), str(item.get("fact") or "").strip())
        for item in raw.get("filled_gaps") or ()
        if isinstance(item, dict)
    ]
    return _Answer(text, strings("missing"), filled, strings("added_facts"))


def _problems(
    answer: _Answer, data: SuggestInput, kit: BrandKit | None
) -> tuple[list[str], list[str]]:
    """(Spanish corrections for the retry, codes of the fatal ones — counts only, never
    model text, so they can go in an exception message)."""
    notes: list[str] = []
    fatal: list[str] = []
    hits = _forbidden_hits(answer.text, kit)
    if hits:
        notes.append("- Usaste palabras o afirmaciones prohibidas: " + " | ".join(hits) + ".")
        fatal.append(f"forbidden={len(hits)}")
    if data.previous_text.strip() and _fold(answer.text) == _fold(data.previous_text):
        notes.append("- Repetiste la versión anterior: escribe una distinta.")
        fatal.append("repeated_previous")
    if answer.added:
        notes.append(
            "- Añadiste hechos que no te dieron; quítalos o deja un hueco: "
            + " | ".join(answer.added)
            + "."
        )
    return notes, fatal


def _required_gaps(data: SuggestInput, answer: _Answer, text: str) -> list[str]:
    """Gaps of the current text the proposal must keep. The model's `filled_gaps` claim is
    never trusted alone: a gap may go only when the fact it names IS that gap (same name,
    folded — the screen names facts after their gaps), has a value free of gaps, and that
    value appears in the proposed `text`. Anything else — «de 7:00 a 23:00» «filled» from
    «qué días» — keeps the gap, so the editor still refuses to publish."""
    usable = {_fold(name): _fold(value) for name, value in data.facts if _usable(value)}
    folded_text = _fold(text)
    filled_ok = {
        _fold(gap)
        for gap, fact in answer.filled
        if _fold(gap) == _fold(fact)
        and usable.get(_fold(fact))
        and usable[_fold(fact)] in folded_text
    }
    return [g for g in find_gaps(data.current_text) if _fold(g) not in filled_ok]


def _with_gaps(body: str, suffix: str) -> str:
    """`body` plus the re-added gaps: before the menu's closing line when it ends with it,
    else at the end."""
    if not suffix:
        return body
    at = body.rfind(MENU_CLOSING)
    if at != -1 and not body[at + len(MENU_CLOSING) :].strip():
        return f"{body[:at].rstrip()} {suffix} {MENU_CLOSING}".lstrip()
    return f"{body} {suffix}"


def _fit(text: str, required: Sequence[str], limit: int) -> tuple[str, bool]:
    """`text` with every required gap present and at most `limit` characters; a dropped
    gap is added back (before the closing line). Returns (text, was_cut)."""
    body, was_cut = text, False
    for _ in range(len(required) + 2):
        present = {_fold(g) for g in find_gaps(body)}
        lost = [g for g in required if _fold(g) not in present]
        suffix = " ".join(f"[{g}]" for g in lost)
        room = limit - (len(suffix) + 1 if suffix else 0)
        if len(body) <= room:
            return _with_gaps(body, suffix), was_cut
        body, was_cut = _cut(body, max(room, 0)), True
    return _with_gaps(body, suffix).strip()[:limit], was_cut


def _validate(data: SuggestInput) -> None:
    if data.kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, not {data.kind!r}")
    if data.kind == "answer" and not data.answer_name.strip():
        raise ValueError("an answer needs its name")


@observability.traced("sugerir respuesta whatsapp", tags=("whatsapp",))
def suggest_text(
    data: SuggestInput,
    kit: BrandKit | None,
    *,
    attribution: Attribution,
    client_factory: ClientFactory = default_client,
) -> SuggestProposal:
    """Claude's proposal for the greeting or one answer (booked to `attribution`).
    `SuggestUnavailable` with no key, on a transport error (429, 5xx, connection, timeout), on a
    refusal, an unusable answer, a banned word or a repeated version after the one retry, or
    when the suggestion's budget is spent; `ValueError` for a bad `kind`."""
    _validate(data)
    limit = _clamp_chars(data)
    try:
        client = client_factory(api_key_from_env())
    except ClaudeToolError as exc:
        raise SuggestUnavailable(str(exc)) from exc
    meter = Meter(SUGGEST_MODEL)
    budget = DollarMeter(SUGGEST_BUDGET_USD)

    answer = _ask(client, meter, budget, data, kit, "", attribution)
    notes, _ = _problems(answer, data, kit)
    if notes:
        answer = _ask(client, meter, budget, data, kit, "\n".join(notes), attribution)
        notes, fatal = _problems(answer, data, kit)
        if fatal:
            raise SuggestUnavailable("the retry still breaks a rule: " + ",".join(fatal))

    emoji = kit is not None and kit.emoji_policy != EmojiPolicy.NONE
    text = _whatsapp_plain(answer.text, emoji=emoji)
    if not text:
        raise SuggestUnavailable("nothing left after cleaning the text")
    required = _required_gaps(data, answer, text)
    present = {_fold(g) for g in find_gaps(text)}
    # The model said it filled a gap of the field, the check refused it and the gap is
    # not in its text: whatever it wrote there was not the owner's — say so. (The
    # invented words are not removed: which ones they are is not known reliably.)
    rejected = any(
        _fold(gap) in {_fold(g) for g in required} and _fold(gap) not in present
        for gap, _fact in answer.filled
    )
    text, was_cut = _fit(text, required, limit)

    missing = list(find_gaps(text))
    folded = {_fold(m) for m in missing}
    for name in answer.missing:
        name = name.strip("[] ")
        if name and _fold(name) not in folded:
            missing.append(name)
            folded.add(_fold(name))
    warnings = [WARN_ADDED_FACT.format(fact=fact) for fact in answer.added]
    if was_cut:
        warnings.append(WARN_CUT)
    if rejected:
        warnings.append(WARN_REJECTED_FILL)

    stats = meter.stats()
    logger.info(
        "whatsapp suggestion: kind=%s model=%s prompt=%s turns=%s in=%s out=%s usd=%s "
        "missing=%s added_facts=%s neutral=%s",
        data.kind,
        stats.model_id,
        PROMPT_VERSION,
        stats.turns,
        stats.input_tokens,
        stats.output_tokens,
        budget.spent_usd,
        len(missing),
        len(answer.added),
        kit is None,
    )
    return SuggestProposal(
        text=text,
        missing=tuple(missing),
        warnings=tuple(warnings),
        neutral_voice=kit is None,
        model_id=stats.model_id,
        input_tokens=stats.input_tokens,
        output_tokens=stats.output_tokens,
    )


def _default_store() -> KitStore:
    # The generator's own loader (tenant_session door), imported lazily.
    from qualify_api.creative.brand_service import BrandKitService  # noqa: PLC0415

    return BrandKitService()


def suggest_for_brand(
    tenant_id: UUID,
    brand_id: UUID,
    data: SuggestInput,
    *,
    client_factory: ClientFactory = default_client,
    kit_store: KitStore | None = None,
) -> SuggestProposal:
    """Load the brand's kit through `BrandKitService.get_kit` (the tenant door) and
    propose; `neutral_voice` when the brand has no kit yet. `kit_store` is for tests."""
    store = kit_store if kit_store is not None else _default_store()
    kit = store.get_kit(tenant_id=tenant_id, brand_id=brand_id)
    attribution = Attribution(tenant_id=tenant_id, brand_id=brand_id, feature=FEATURE)
    return suggest_text(data, kit, attribution=attribution, client_factory=client_factory)


__all__ = [
    "FEATURE",
    "MENU_CLOSING",
    "PROMPT_VERSION",
    "SUGGEST_BUDGET_USD",
    "SUGGEST_MODEL",
    "SuggestInput",
    "SuggestProposal",
    "SuggestUnavailable",
    "render_request",
    "suggest_for_brand",
    "suggest_text",
]

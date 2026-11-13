"""«Mejorar mi texto» on the generator's context (§ request 2026-10-20): the operator's
own words about the piece, rewritten by Claude into a fuller brief BEFORE anything is
generated — what it is about, who it speaks to, what it must make them feel and do —
grounded only in what the operator wrote, the piece's «Datos clave» and the Brand Kit.

m-25017274 (founder, 2026-11-13): one press returns THREE versions with different
approaches (`APPROACHES`), shown as cards; the operator's original stays and choosing a
card fills the field. «Otra versión» asks again from the ORIGINAL text and sends the
versions already shown (`ContextInput.previous_versions`) so they are not repeated — the
old single rewrite replaced the field and a second press rewrote its own output, which
came back the same (measured: `docs/modelos-generativos/pruebas.md`, 2026-11-13).

Nothing is generated or stored here and no creación is consumed. One call, one strict tool
(`propose_context`), the shared plumbing of `claude_tools` (key, Langfuse trace, metered
cost booked to the consumption ledger in dollars only).

The one rule that matters: **no new facts.** A price, a promotion, a date, a place or a
claim that is not in the input must not appear in the output — the copy model downstream
treats the context as the operator's word, so an invented «20 % de descuento» here would
be published as true. The model reports what it added beyond style; anything it flags is
dropped back to the operator as a warning.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from qualify_creative.prompt_text import visual_text
from qualify_creative.schemas import BrandKit
from qualify_shared import observability

from qualify_api.claude_tools import (
    Attribution,
    ClaudeToolError,
    ClientFactory,
    Meter,
    ModelConfig,
    api_key_from_env,
    create_turn,
    default_client,
    forced_or_auto,
    strict_tool,
    tool_uses,
)

logger = logging.getLogger("qualify_api.creative.context_ai")

CONTEXT_MODEL: Final = ModelConfig("claude-sonnet-5-5", effort="low")
TOOL_NAME: Final = "propose_context"
CONTEXT_PROMPT_VERSION: Final = "context-v4-three-versions"
#: The function the consumption ledger books these calls to (m-24955649).
FEATURE: Final = "potenciar-contexto"
PROPOSAL_MAX_CHARS: Final = 300
OUTPUT_MARGIN_CHARS: Final = 50
#: Room for low-effort thinking plus the three-version tool call.
MAX_TOKENS: Final = 6144
#: How many earlier versions «Otra versión» sends back (the newest ones), to bound the prompt.
PREVIOUS_VERSIONS_SENT: Final = 9

#: The three approaches of one press, in the order the cards show them: the tool's property
#: names, what the model is told each one is, and nothing on screen beyond a short label.
APPROACHES: Final[tuple[tuple[str, str], ...]] = (
    (
        "directa",
        "MÁS DIRECTA: corta y al grano; lo esencial primero y la acción que se pide clara.",
    ),
    (
        "descriptiva",
        "MÁS DESCRIPTIVA: lo que se ve, se huele y se saborea; detalles sensoriales del "
        "producto o del lugar (sin datos nuevos).",
    ),
    (
        "cercana",
        "MÁS CERCANA: como le hablaría el dueño a un cliente de confianza; cálida, con "
        "emoción y un momento cotidiano.",
    ),
)
#: For a flyer's SCENE the three approaches are three ways of framing the picture.
SCENE_APPROACHES: Final[tuple[tuple[str, str], ...]] = (
    ("producto", "EL PRODUCTO DE CERCA: plano cerrado, el producto llena el encuadre."),
    ("lugar", "EL LUGAR: plano más abierto, el ambiente del local o la mesa alrededor."),
    (
        "momento",
        "UN MOMENTO: una mano o una persona disfrutándolo, sin mostrar caras reconocibles.",
    ),
)
#: Manual field capacities stay separate from the automatic proposal's 300-character cap.
SCENE_MAX_CHARS: Final = 600
CONTEXT_MAX_CHARS: Final = 1200
#: Shortest input worth enhancing — fewer words than this give the model nothing to keep.
MIN_INPUT_CHARS: Final = 8

SYSTEM_PROMPT: Final = (
    "Eres el estratega creativo de una marca. Te llega el CONTEXTO que una persona de la "
    "marca escribió para una publicación en redes sociales (a veces breve o desordenado), "
    "el tipo de pieza, el tipo de publicación, el formato, el producto, sus DATOS CLAVE y "
    "el BRAND KIT.\n\n"
    "Escribe TRES versiones distintas del texto, una por cada ENFOQUE que se indica, breves, "
    "claras y accionables, en español y en la voz de esa persona (primera persona del "
    "negocio: «quiero…»), para que el equipo que genera la pieza entienda: de qué trata, a "
    "quién le habla, qué debe sentir esa persona, qué se debe ver o decir y cómo cierra (la "
    "acción que se pide). Cada versión conserva TODO lo que la persona pidió, con sus "
    "palabras cuando importan; lo que cambia entre ellas es el enfoque.\n\n"
    "Que de verdad sean distintas: cada una empieza de otra manera, ordena las ideas de otra "
    "forma y usa otras palabras; no cambies solo un par de palabras. Si se te dan VERSIONES "
    "YA MOSTRADAS, la persona ya las vio y pidió otras: no repitas ninguna ni su manera de "
    "empezar; busca otro ángulo dentro del mismo enfoque.\n\n"
    "El tipo de pieza, el tipo de publicación y el formato son para que elijas qué contar y "
    "cómo; el equipo ya los conoce: no los nombres en el texto (nada de «reel 9:16» ni "
    "«galería 4:5»).\n\n"
    "Reglas sin excepción:\n"
    "- NO inventes hechos: ningún precio, promoción, descuento, fecha, horario, lugar, "
    "dato, cifra, ingrediente, premio ni afirmación que no esté en el contexto, en los "
    "datos clave o en el brand kit. Puedes añadir dirección creativa (encuadre, ambiente, "
    "ritmo, emoción), no hechos.\n"
    "- Respeta las palabras prohibidas y las afirmaciones prohibidas del brand kit.\n"
    "- Español claro y neutro, también en la versión cercana: sin jerga, sin palabras de "
    "una sola región ni diminutivos de cariño, sin palabras en inglés.\n"
    "- No añadas hashtags, emojis, títulos, viñetas, markdown ni frases de introducción. "
    "Describe los símbolos solicitados CON PALABRAS, sin usar pictogramas emoji. "
    "Conserva hashtags y citas literales; si una cita exige un glifo, no la omitas. "
    "Una sola línea, un espacio entre palabras; sin saltos, espacios repetidos o adornos.\n"
    "- Conserva cada petición, prohibición, cifra, horario y referencia literal, incluidos "
    "los espacios dentro del texto que se pide reproducir exactamente. No añadas "
    "relleno ni repitas contexto del brand kit que no haga falta. No cortes ni omitas "
    "instrucciones importantes para cumplir el largo.\n"
    "- Si te piden una ESCENA (una imagen), describe solo lo que se ve: sujeto, lugar, luz, "
    "encuadre y sensación, en pocas frases; los enfoques son entonces maneras de encuadrar.\n"
    "- Respeta el largo máximo que se indica, en cada versión.\n\n"
    "Responde ÚNICAMENTE llamando a la herramienta propose_context."
)


class ContextUnavailable(RuntimeError):
    """The enhancement could not run (no key, a refusal, no usable answer)."""


class ContextTooLong(ContextUnavailable):
    """A complete normalized proposal does not fit; the caller must keep the original."""

    def __init__(self, actual_chars: int, max_chars: int) -> None:
        self.actual_chars = actual_chars
        self.max_chars = max_chars
        super().__init__(
            # the counts stay on the exception for logs; the owner reads no numbers (UX B3)
            "La versión mejorada salió demasiado larga, así que dejamos tu texto como estaba. "
            "Puedes crear así o intentarlo de nuevo."
        )


class ContextMeaningUncertain(ContextUnavailable):
    """Cleanup cannot safely preserve an explicit literal/symbol request."""

    def __init__(self) -> None:
        super().__init__(
            "No pudimos conservar todas tus indicaciones en la propuesta. "
            "Conservamos tu texto para que puedas ajustarlo manualmente."
        )


_SOURCE_LITERALS = re.compile(r'"[^"\n]*"|«[^»]*»|“[^”]*”|(?<!\w)\'[^\'\n]*\'')


def normalize_context_proposal(text: str, *, source_text: str = "") -> str:
    """Remove only layout/decorations; never summarize or cut the proposed instructions.

    Requested literal CONTENT remains exact independently of output quote delimiters.
    Emoji-bearing proposals are refused rather than cleaned into a different instruction.
    This is scoped to this tool's output; the stored/manual original is never modified.
    """
    text = text.strip()
    # General format guard: a removed glyph may carry meaning that we cannot prove
    # decorative. The model must express symbols in words; never guess their meaning.
    if visual_text(text) != text:
        raise ContextMeaningUncertain()
    contents = [literal[1:-1] for literal in _SOURCE_LITERALS.findall(source_text)]
    if any(content and content not in text for content in contents):
        raise ContextMeaningUncertain()
    # Strip only wrappers absent from the source before locating literal intervals.
    # No placeholder is inserted into user text: a literal may itself contain another
    # literal or text resembling an internal marker.
    if "```" not in source_text:
        fenced = re.fullmatch(r"```(?:text|plaintext)?[ \t]*\r?\n(.*?)\r?\n```", text, re.S)
        if fenced:
            text = fenced.group(1)
    for marker in ("**", "__"):
        if marker not in source_text and text.startswith(marker) and text.endswith(marker):
            text = text[len(marker) : -len(marker)]
    intervals: list[tuple[int, int]] = []
    for content in contents:
        if not content:
            continue
        start = text.find(content)
        if start < 0:
            raise ContextMeaningUncertain()
        while start >= 0:
            intervals.append((start, start + len(content)))
            start = text.find(content, start + 1)
    spans: list[tuple[int, int]] = []
    for start, end in sorted(intervals):
        if spans and start <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(end, spans[-1][1]))
        else:
            spans.append((start, end))
    pieces: list[str] = []
    cursor = 0
    for start, end in spans:
        pieces.append(re.sub(r"\s+", " ", unicodedata.normalize("NFC", text[cursor:start])))
        pieces.append(text[start:end])
        cursor = end
    pieces.append(re.sub(r"\s+", " ", unicodedata.normalize("NFC", text[cursor:])))
    cleaned = "".join(pieces).strip()
    if any(content and content not in cleaned for content in contents):
        raise ContextMeaningUncertain()

    return cleaned


def validate_context_proposal(text: str, *, max_chars: int, source_text: str = "") -> str:
    """Validate the final normalized text; never silently discard an overlength tail."""
    text = normalize_context_proposal(text, source_text=source_text)
    if not text:
        raise ContextUnavailable("empty context proposed")
    if len(text) > max_chars:
        raise ContextTooLong(len(text), max_chars)
    return text


@dataclass(frozen=True)
class ContextInput:
    """What the operator has written and chosen so far — the only facts allowed."""

    text: str
    #: What the piece is, in the operator's words («Clip», «Galería», «Avatar animado»).
    piece: str
    #: True for a flyer: its context is the scene the image shows.
    scene: bool = False
    product: str = ""
    highlights: Sequence[tuple[str, str]] = ()
    must_mention: str = ""
    must_avoid: str = ""
    #: The kind of publication («Promoción», «Producto nuevo»…) and its format, as the
    #: screen labels them (m-25017274): context for the approaches, never new facts.
    content_type: str = ""
    format: str = ""
    #: «Otra versión»: the versions already shown for this same text, not to be repeated.
    previous_versions: Sequence[str] = ()

    @property
    def max_chars(self) -> int:
        return PROPOSAL_MAX_CHARS

    @property
    def field_max_chars(self) -> int:
        return SCENE_MAX_CHARS if self.scene else CONTEXT_MAX_CHARS

    @property
    def approaches(self) -> tuple[tuple[str, str], ...]:
        return SCENE_APPROACHES if self.scene else APPROACHES


@dataclass(frozen=True)
class ContextVersion:
    """One card: the approach it was written with (`APPROACHES` key) and its text."""

    approach: str
    text: str


@dataclass(frozen=True)
class ContextProposal:
    #: One to three distinct versions, in the order of the approaches; never empty.
    versions: tuple[ContextVersion, ...]
    #: What the model says it added beyond style — empty when it added no facts.
    added_facts: tuple[str, ...] = ()
    model_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    prompt_version: str = CONTEXT_PROMPT_VERSION


def _brand_lines(kit: BrandKit | None) -> list[str]:
    if kit is None:
        return ["BRAND KIT: (no hay)"]
    lines = [
        "BRAND KIT:",
        f"- Posicionamiento: {kit.positioning.strip() or '-'}",
        f"- Público: {kit.audience.strip() or '-'}",
        f"- Variante del español: {kit.regional_variant}",
    ]
    if kit.typeface:
        lines.append(f"- Tipografía de la marca: {kit.typeface}")
    axes = kit.tone_axes
    lines.append(
        "- Tono (0-100): formal→casual "
        f"{axes.formal_casual}, sobrio→entusiasta {axes.sober_enthusiastic}, "
        f"técnico→llano {axes.technical_plain}, breve→extenso {axes.brief_elaborate}"
    )
    for label, values in (
        ("Así sí escribe", kit.do_examples),
        ("Así no", kit.dont_examples),
        ("Palabras prohibidas", kit.banned_words),
        ("Afirmaciones prohibidas", kit.forbidden_claims),
        ("Llamados a la acción habituales", kit.cta_patterns),
    ):
        if values:
            lines.append(f"- {label}: " + " | ".join(v.strip() for v in values[:6]))
    return lines


def _same(a: str, b: str) -> bool:
    """Two versions that only differ in case, spacing or final punctuation are one."""
    key = lambda t: re.sub(r"[\s.,;:!¡?¿]+", " ", t.casefold()).strip()  # noqa: E731
    return key(a) == key(b)


def render_request(data: ContextInput, kit: BrandKit | None) -> str:
    """The user message: the piece, its facts, the approaches, the brand, the versions
    already shown, then the text to rewrite."""
    facts = [f"- {name}: {value}" for name, value in data.highlights if name and value]
    what = "una ESCENA (lo que se ve en la imagen)" if data.scene else "el CONTEXTO de la pieza"
    lines = [
        f"TIPO DE PIEZA: {data.piece}",
        f"TIPO DE PUBLICACIÓN: {data.content_type.strip() or '-'}",
        f"FORMATO: {data.format.strip() or '-'}",
        f"QUÉ ESCRIBIR: {what}, en tres versiones",
        f"LARGO MÁXIMO: {data.max_chars} caracteres por versión, incluidos espacios y signos.",
        f"OBJETIVO: hasta {data.max_chars - OUTPUT_MARGIN_CHARS} caracteres por versión; "
        "usa solo las palabras necesarias y conserva todas las indicaciones.",
        "ENFOQUES (uno por versión):",
        *(f"- {key}: {description}" for key, description in data.approaches),
        f"PRODUCTO: {data.product.strip() or '(sin producto)'}",
        "DATOS CLAVE:" if facts else "DATOS CLAVE: (ninguno)",
        *facts,
    ]
    if data.must_mention.strip():
        lines.append(f"DEBE MENCIONAR: {data.must_mention.strip()}")
    if data.must_avoid.strip():
        lines.append(f"DEBE EVITAR: {data.must_avoid.strip()}")
    lines += ["", *_brand_lines(kit)]
    previous = [v.strip() for v in data.previous_versions if v.strip()]
    if previous:
        lines += [
            "",
            "VERSIONES YA MOSTRADAS (la persona pidió otras; no repitas ninguna):",
            *(f"- {v}" for v in previous[-PREVIOUS_VERSIONS_SENT:]),
        ]
    lines += ["", "CONTEXTO ESCRITO POR LA PERSONA:", data.text.strip()]
    return "\n".join(lines)


def _tool(
    max_chars: int = PROPOSAL_MAX_CHARS, approaches: tuple[tuple[str, str], ...] = APPROACHES
) -> dict[str, Any]:
    properties: dict[str, Any] = {
        key: {
            "type": "string",
            "description": (
                f"Versión con el enfoque {description.split(':')[0]}, de hasta {max_chars} "
                "caracteres contando espacios y signos. Una línea, sin formato ni relleno; "
                "conserva todas las indicaciones."
            ),
        }
        for key, description in approaches
    }
    properties["added_facts"] = {
        "type": "array",
        "items": {"type": "string"},
        "description": (
            "Cada hecho (precio, fecha, promoción, dato) que aparezca en alguna versión y NO "
            "esté en el contexto, los datos clave ni el brand kit. Vacío si no "
            "añadiste ninguno: lo que sale del brand kit no se lista."
        ),
    }
    return strict_tool(TOOL_NAME, "Propone tres versiones del contexto reescrito.", properties)


@observability.traced("potenciar contexto", tags=("generador",))
def enhance_context(
    data: ContextInput,
    kit: BrandKit | None,
    *,
    attribution: Attribution,
    client_factory: ClientFactory = default_client,
) -> ContextProposal:
    """Claude's three versions of `data.text`, booked to `attribution` (m-24955649).

    Each version is validated on its own; one that is too long, loses a literal, repeats
    another, repeats a version already shown or is the original text again is dropped.
    When none survives the first refusal is raised (`ContextTooLong`,
    `ContextMeaningUncertain`) or `ContextUnavailable`, so the caller keeps the text as it
    was. Raises `ContextUnavailable` with no key, on a refusal or when the answer is
    unusable; `ValueError` for a text too short to keep."""
    if len(data.text.strip()) < MIN_INPUT_CHARS:
        raise ValueError("the context is too short to enhance")
    try:
        client = client_factory(api_key_from_env())
        meter = Meter(CONTEXT_MODEL)
        response = create_turn(
            client,
            CONTEXT_MODEL,
            meter,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": render_request(data, kit)}],
            tools=[_tool(data.max_chars, data.approaches)],
            tool_choice=forced_or_auto(CONTEXT_MODEL, TOOL_NAME),
            max_tokens=MAX_TOKENS,
            attribution=attribution.versioned(CONTEXT_PROMPT_VERSION),
        )
    except ClaudeToolError as exc:
        raise ContextUnavailable(str(exc)) from exc
    calls = [use for use in tool_uses(response) if use.name == TOOL_NAME]
    if not calls:
        raise ContextUnavailable(f"{CONTEXT_MODEL.model_id} did not call {TOOL_NAME}")
    answer = calls[0].input or {}
    literal_source = "\n".join(
        (
            data.text,
            data.product,
            data.must_mention,
            data.must_avoid,
            *(str(value) for _, value in data.highlights),
        )
    )
    seen = [data.text, *data.previous_versions]
    versions: list[ContextVersion] = []
    refusals: list[ContextUnavailable] = []
    for key, _ in data.approaches:
        raw_text = answer.get(key)
        if not isinstance(raw_text, str):
            refusals.append(ContextUnavailable(f"version {key} is not text"))
            continue
        try:
            text = validate_context_proposal(
                raw_text, max_chars=data.max_chars, source_text=literal_source
            )
        except ContextUnavailable as exc:
            refusals.append(exc)
            continue
        if any(_same(text, other) for other in seen):
            refusals.append(ContextUnavailable(f"version {key} repeats a text already shown"))
            continue
        seen.append(text)
        versions.append(ContextVersion(approach=key, text=text))
    if not versions:
        # the most specific reason the owner can act on: too long, then a lost literal
        for kind in (ContextTooLong, ContextMeaningUncertain):
            for exc in refusals:
                if isinstance(exc, kind):
                    raise exc
        raise ContextUnavailable("no usable version proposed")
    added = tuple(
        str(fact).strip() for fact in answer.get("added_facts") or () if str(fact).strip()
    )
    stats = meter.stats()
    logger.info(
        "context enhanced: model=%s in=%s out=%s versions=%s dropped=%s added_facts=%s "
        "previous=%s version=%s",
        stats.model_id,
        stats.input_tokens,
        stats.output_tokens,
        len(versions),
        len(refusals),
        len(added),
        len(data.previous_versions),
        CONTEXT_PROMPT_VERSION,
    )
    return ContextProposal(
        versions=tuple(versions),
        added_facts=added,
        model_id=stats.model_id,
        input_tokens=stats.input_tokens,
        output_tokens=stats.output_tokens,
    )

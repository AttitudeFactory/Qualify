"""«Potenciar con IA» on the generator's context (§ request 2026-10-20): the operator's
own words about the piece, rewritten by Claude into a fuller brief BEFORE anything is
generated — what it is about, who it speaks to, what it must make them feel and do —
grounded only in what the operator wrote, the piece's «Datos clave» and the Brand Kit.

Nothing is generated or stored here: the proposal replaces the text in the form, the
operator reads it (and can undo it) and Generar sends whatever is in the box. One call,
one strict tool (`propose_context`), the shared plumbing of `claude_tools` (key, Langfuse
trace, metered cost).

The one rule that matters: **no new facts.** A price, a promotion, a date, a place or a
claim that is not in the input must not appear in the output — the copy model downstream
treats the context as the operator's word, so an invented «20 % de descuento» here would
be published as true. The model reports what it added beyond style; anything it flags is
dropped back to the operator as a warning.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from qualify_creative.schemas import BrandKit
from qualify_shared import observability

from qualify_api.claude_tools import (
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
#: Room for low-effort thinking plus the tool call (thinking counts against it).
MAX_TOKENS: Final = 4096
#: The longest context proposed: a flyer's scene is a scene (its field takes 600), every
#: other kind's context is a brief of a few short paragraphs.
SCENE_MAX_CHARS: Final = 600
CONTEXT_MAX_CHARS: Final = 1200
#: Shortest input worth enhancing — fewer words than this give the model nothing to keep.
MIN_INPUT_CHARS: Final = 8

SYSTEM_PROMPT: Final = (
    "Eres el estratega creativo de una marca. Te llega el CONTEXTO que una persona de la "
    "marca escribió para una pieza de redes sociales (a veces breve o desordenado), qué "
    "tipo de pieza es, el producto, sus DATOS CLAVE y el BRAND KIT.\n\n"
    "Reescríbelo como un brief claro y accionable, en español y en la voz de esa persona "
    "(primera persona del negocio: «quiero…»), para que el equipo que genera la pieza "
    "entienda: de qué trata, a quién le habla, qué debe sentir esa persona, qué se debe "
    "ver o decir y cómo cierra (la acción que se pide). Conserva TODO lo que la persona "
    "pidió, con sus palabras cuando importan.\n\n"
    "Reglas sin excepción:\n"
    "- NO inventes hechos: ningún precio, promoción, descuento, fecha, horario, lugar, "
    "dato, cifra, ingrediente, premio ni afirmación que no esté en el contexto, en los "
    "datos clave o en el brand kit. Puedes añadir dirección creativa (encuadre, ambiente, "
    "ritmo, emoción), no hechos.\n"
    "- Respeta las palabras prohibidas y las afirmaciones prohibidas del brand kit.\n"
    "- Sin hashtags, sin emojis, sin títulos ni viñetas: texto corrido, párrafos cortos.\n"
    "- Si te piden una ESCENA (una imagen), describe solo lo que se ve: sujeto, lugar, luz, "
    "encuadre y sensación, en pocas frases.\n"
    "- Respeta el largo máximo que se indica.\n\n"
    "Responde ÚNICAMENTE llamando a la herramienta propose_context."
)


class ContextUnavailable(RuntimeError):
    """The enhancement could not run (no key, a refusal, no usable answer)."""


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

    @property
    def max_chars(self) -> int:
        return SCENE_MAX_CHARS if self.scene else CONTEXT_MAX_CHARS


@dataclass(frozen=True)
class ContextProposal:
    text: str
    #: What the model says it added beyond style — empty when it added no facts.
    added_facts: tuple[str, ...] = ()
    model_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


def _brand_lines(kit: BrandKit | None) -> list[str]:
    if kit is None:
        return ["BRAND KIT: (no hay)"]
    lines = [
        "BRAND KIT:",
        f"- Posicionamiento: {kit.positioning.strip() or '-'}",
        f"- Público: {kit.audience.strip() or '-'}",
        f"- Variante del español: {kit.regional_variant}",
    ]
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


def render_request(data: ContextInput, kit: BrandKit | None) -> str:
    """The user message: the piece, its facts, the brand, then the text to rewrite."""
    facts = [f"- {name}: {value}" for name, value in data.highlights if name and value]
    what = "una ESCENA (lo que se ve en la imagen)" if data.scene else "el CONTEXTO de la pieza"
    lines = [
        f"TIPO DE PIEZA: {data.piece}",
        f"QUÉ ESCRIBIR: {what}",
        f"LARGO MÁXIMO: {data.max_chars} caracteres",
        f"PRODUCTO: {data.product.strip() or '(sin producto)'}",
        "DATOS CLAVE:" if facts else "DATOS CLAVE: (ninguno)",
        *facts,
    ]
    if data.must_mention.strip():
        lines.append(f"DEBE MENCIONAR: {data.must_mention.strip()}")
    if data.must_avoid.strip():
        lines.append(f"DEBE EVITAR: {data.must_avoid.strip()}")
    lines += ["", *_brand_lines(kit), "", "CONTEXTO ESCRITO POR LA PERSONA:", data.text.strip()]
    return "\n".join(lines)


def _tool() -> dict[str, Any]:
    return strict_tool(
        TOOL_NAME,
        "Propone el contexto reescrito.",
        {
            "context": {
                "type": "string",
                "description": "El contexto (o la escena) reescrito, listo para usar.",
            },
            "added_facts": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Cada hecho (precio, fecha, promoción, dato) que aparezca en tu texto y NO "
                    "esté en el contexto, los datos clave ni el brand kit. Vacío si no "
                    "añadiste ninguno: lo que sale del brand kit no se lista."
                ),
            },
        },
    )


@observability.traced("potenciar contexto", tags=("generador",))
def enhance_context(
    data: ContextInput,
    kit: BrandKit | None,
    *,
    client_factory: ClientFactory = default_client,
) -> ContextProposal:
    """Claude's rewrite of `data.text`. Raises `ContextUnavailable` with no key, on a
    refusal or when the answer is unusable; `ValueError` for a text too short to keep."""
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
            tools=[_tool()],
            tool_choice=forced_or_auto(CONTEXT_MODEL, TOOL_NAME),
            max_tokens=MAX_TOKENS,
        )
    except ClaudeToolError as exc:
        raise ContextUnavailable(str(exc)) from exc
    calls = [use for use in tool_uses(response) if use.name == TOOL_NAME]
    if not calls:
        raise ContextUnavailable(f"{CONTEXT_MODEL.model_id} did not call {TOOL_NAME}")
    answer = calls[0].input or {}
    text = str(answer.get("context") or "").strip()
    if not text:
        raise ContextUnavailable("empty context proposed")
    if len(text) > data.max_chars:
        # cut at the last sentence that fits — never mid-word
        cut = text[: data.max_chars]
        end = max(cut.rfind(". "), cut.rfind(".\n"))
        text = (cut[: end + 1] if end > data.max_chars // 2 else cut.rsplit(" ", 1)[0]).strip()
    added = tuple(
        str(fact).strip() for fact in answer.get("added_facts") or () if str(fact).strip()
    )
    stats = meter.stats()
    logger.info(
        "context enhanced: model=%s in=%s out=%s added_facts=%s",
        stats.model_id,
        stats.input_tokens,
        stats.output_tokens,
        len(added),
    )
    return ContextProposal(
        text=text,
        added_facts=added,
        model_id=stats.model_id,
        input_tokens=stats.input_tokens,
        output_tokens=stats.output_tokens,
    )

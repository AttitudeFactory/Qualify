"""Hashtags for one caption (draft review, QUA-118 v2 polish).

The operator writes a caption and wants hashtags that fit ALL of it — not the words one by
one. Claude reads the whole text and proposes a mix:

- **popular** — broad tags people keep using (what makes a post discoverable);
- **nicho** — specific to what the caption is about (where the right audience is);
- **marca** — local or brand tags the text itself names (a city, a product, the brand).

It is grounded in the tenant's hashtag catalog (`HashtagRepository`): tags actually seen on
Instagram/TikTok posts, with how often (`seen_count`). Those are shown to the model first
and flagged as such, so «popular» is backed by what we observed, not by a guess about
today's trends — the model has no live trend feed, and the prompt says so.

Pure orchestration: the client comes from `claude_tools.default_client` with an explicit
`api_key` (`QUALIFY_ANTHROPIC_API_KEY`), injectable for tests.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ..claude_tools import (
    ClientFactory,
    Meter,
    ModelConfig,
    create_turn,
    default_client,
    forced_or_auto,
    strict_tool,
    tool_uses,
)
from .repository import fold

CAPTION_MODEL = ModelConfig("claude-haiku-4-5")
SUGGEST_TOOL = "sugerir_hashtags"
KINDS: tuple[str, ...] = ("popular", "nicho", "marca")
MAX_PICKS = 12
CAPTION_MAX_CHARS = 4000  # what the model is shown — a caption is at most 2,200


@dataclass(frozen=True)
class SeenTag:
    """A catalog tag offered to the model: the tag and how often it was seen."""

    tag: str
    seen_count: int


@dataclass(frozen=True)
class CaptionHashtag:
    tag: str  # without «#», lowercase, no accents or spaces
    kind: str  # popular / nicho / marca
    reason: str  # one short line, in Spanish, for the chip's tooltip
    seen_count: int = 0  # > 0 when the catalog has seen it on real posts


SYSTEM = """Eres estratega de redes sociales para marcas de Latinoamérica.
Lees el texto COMPLETO de una publicación de Instagram/TikTok y recomiendas hashtags que
encajen con TODO lo que dice (tema, producto, ocasión, lugar, tono), no con palabras sueltas.

Devuelve una mezcla:
- popular: hashtags amplios que mucha gente usa y sigue en ese tema.
- nicho: hashtags específicos del tema de la publicación, donde está la audiencia correcta.
- marca: hashtags locales o de marca que el propio texto nombra (ciudad, producto, marca).

Reglas:
- Prefiere los hashtags del catálogo (vistos en publicaciones reales, con su conteo) cuando
  encajen; puedes proponer otros si el texto lo pide.
- No tienes datos de tendencias en vivo: no digas que algo es «tendencia hoy». «popular»
  significa amplio y muy usado.
- Formato: sin «#», en minúsculas, sin tildes ni espacios (ej. heladoartesanal).
- Nada genérico sin relación con el texto (#love, #instagood) ni repetidos.
- El motivo es una frase corta en español."""


def _tool(max_picks: int) -> dict[str, Any]:
    return strict_tool(
        SUGGEST_TOOL,
        f"Entrega hasta {max_picks} hashtags para el texto, el mejor primero.",
        {
            "hashtags": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "tag": {"type": "string"},
                        "tipo": {"type": "string", "enum": list(KINDS)},
                        "motivo": {"type": "string"},
                    },
                    "required": ["tag", "tipo", "motivo"],
                    "additionalProperties": False,
                },
            }
        },
    )


def _message(caption: str, seen: Sequence[SeenTag], current: Sequence[str]) -> str:
    lines = [f"Texto de la publicación:\n«{caption[:CAPTION_MAX_CHARS]}»", ""]
    if seen:
        lines.append("Hashtags del catálogo (vistos en publicaciones reales, veces vistos):")
        lines.extend(f"- {t.tag} ({t.seen_count})" for t in seen)
    else:
        lines.append("El catálogo no tiene hashtags para este tema todavía.")
    if current:
        lines.append("")
        lines.append("Ya elegidos (no los repitas): " + ", ".join(current))
    return "\n".join(lines)


def _clean(tag: str) -> str:
    return "".join(ch for ch in fold(tag.strip().lstrip("#")) if ch.isalnum() or ch == "_")


def suggest_for_caption(
    caption: str,
    *,
    seen: Sequence[SeenTag] = (),
    current: Sequence[str] = (),
    api_key: str,
    max_picks: int = MAX_PICKS,
    client_factory: ClientFactory | None = None,
) -> list[CaptionHashtag]:
    """Up to `max_picks` hashtags for the whole caption, best first, none already in
    `current`. Raises `ClaudeToolError` (via `create_turn`) on a refusal or truncation."""
    if not caption.strip():
        return []
    client = (client_factory or default_client)(api_key)
    meter = Meter(CAPTION_MODEL)
    response = create_turn(
        client,
        CAPTION_MODEL,
        meter,
        system=SYSTEM,
        messages=[{"role": "user", "content": _message(caption, seen, current)}],
        tools=[_tool(max_picks)],
        tool_choice=forced_or_auto(CAPTION_MODEL, SUGGEST_TOOL),
        max_tokens=2048,
    )
    use = next((u for u in tool_uses(response) if u.name == SUGGEST_TOOL), None)
    if use is None:
        return []
    counts = {fold(t.tag): t.seen_count for t in seen}
    taken = {fold(t) for t in current}
    picks: list[CaptionHashtag] = []
    for item in (use.input or {}).get("hashtags", []):
        tag = _clean(str(item.get("tag", "")))
        kind = str(item.get("tipo", ""))
        if len(tag) < 3 or tag in taken or kind not in KINDS:
            continue
        taken.add(tag)
        picks.append(
            CaptionHashtag(
                tag=tag,
                kind=kind,
                reason=str(item.get("motivo", "")).strip(),
                seen_count=counts.get(tag, 0),
            )
        )
        if len(picks) >= max_picks:
            break
    return picks

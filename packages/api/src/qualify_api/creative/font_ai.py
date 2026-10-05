"""Reading a brand's typography off its logo (§ request 2026-10-05: "que se pueda extraer
la tipografía desde las opciones del brandboard").

Tu brandboard's typography tiles ask for two family names (headlines, body copy). When
the operator has already dropped a logo version, the same Claude vision path the brand
documents use (`brief_ai`) can propose them: the model looks at the mark's lettering and
names the family it most resembles, with alternatives — through one strict tool call,
`identificar_tipografia`, so the answer has a shape the wizard can write into fields.

What this is NOT: font identification is a resemblance judgement, not a lookup. Even a
specialist service answers "looks like" for a logotype, and a logo's lettering is often
customised. The result is therefore a *suggestion* the wizard writes into the editable
name fields (the operator keeps the last word), and the note returned with it says
"parece", never "es".

Only raster images go to the model (an SVG logo cannot be sent as an image block); with
nothing usable `NoUsableImage` is raised before any network call.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any

from ..claude_tools import (
    CallStats,
    ClaudeToolError,
    ClientFactory,
    Meter,
    ModelConfig,
    create_turn,
    default_client,
    forced_or_auto,
    strict_tool,
    tool_uses,
)
from .brief_ai import _IMAGE_TYPES, _image_block

logger = logging.getLogger(__name__)

FONT_MODEL = "claude-sonnet-5"
FONT_EFFORT = "medium"
DETECT_TOOL = "identificar_tipografia"
#: How many logo versions travel with one request — the fullest mark and one more is
#: plenty for a lettering judgement; every image costs tokens.
MAX_IMAGES = 2
#: Caps on what the model returns, so a verbose answer cannot flood a one-line field.
MAX_NAME_CHARS = 60
MAX_ALTERNATIVES = 3
MAX_NOTE_CHARS = 240
#: An answer the model may use for the body face when the logo shows no second face.
STYLES = ("sans-serif", "serif", "script", "display", "monospace", "")


class NoUsableImage(ValueError):
    """None of the given files is an image the model can look at (e.g. only SVGs)."""


@dataclass(frozen=True)
class FontGuess:
    """What the model read off the logo. `heading` is the family the lettering most
    resembles ("" when the mark has no text); `body` a face for running copy — the
    brand's own if a second face is visible, else one the model pairs with `heading`."""

    heading: str
    body: str
    heading_alternatives: tuple[str, ...]
    style: str
    note: str

    @property
    def found_anything(self) -> bool:
        return bool(self.heading or self.body)


SYSTEM = """\
Eres un tipógrafo. Miras el logo de una marca (una o varias versiones) e identificas la \
tipografía de su texto para rellenar el Brand Kit de Qualify. Entregas la respuesta con \
la herramienta identificar_tipografia, una sola vez.

Reglas:
- heading_font: el nombre de la familia tipográfica que MÁS se parece a las letras del \
logo (p. ej. "Montserrat", "Playfair Display", "Futura"). Prefiere familias disponibles \
en Google Fonts cuando el parecido es equivalente, porque la marca podrá usarlas de \
inmediato. Si el logo no tiene texto, déjalo vacío ("").
- heading_alternatives: hasta 3 familias alternativas con un parecido razonable, de \
mayor a menor parecido. Vacío si no hay texto.
- body_font: una familia para el texto corrido (párrafos, descripciones). Si el logo o el \
material muestra una segunda tipografía, esa; si no, una que combine bien con \
heading_font y sea legible en tamaños pequeños. Vacío solo si no puedes proponer nada.
- style: la clasificación de las letras del logo: sans-serif, serif, script, display, \
monospace, o "" si no hay texto.
- note: una frase en español, máximo 30 palabras, que diga en qué te basas (remates, \
contraste, geometría…) y aclare que es un parecido, no una identificación exacta. Si las \
letras parecen dibujadas a medida (lettering), dilo.
- No inventes nombres de familias que no existan. Si dudas entre dos, la más probable va \
en heading_font y la otra en heading_alternatives."""


def _tool() -> dict[str, Any]:
    return strict_tool(
        DETECT_TOOL,
        "Entrega la tipografía identificada en el logo para el Brand Kit.",
        {
            "heading_font": {"type": "string"},
            "heading_alternatives": {"type": "array", "items": {"type": "string"}},
            "body_font": {"type": "string"},
            "style": {"type": "string", "enum": list(STYLES)},
            "note": {"type": "string"},
        },
    )


def image_blocks(files: Sequence[tuple[str, bytes]]) -> list[dict[str, Any]]:
    """The image blocks for `files` ((name, bytes), fullest mark first) — up to
    `MAX_IMAGES`, skipping anything that is not a raster image the API accepts."""
    blocks: list[dict[str, Any]] = []
    for name, data in files:
        suffix = PurePath(name).suffix.lower()
        media_type = _IMAGE_TYPES.get(suffix)
        if media_type is None or not data:
            continue
        try:
            blocks.append(_image_block(data, media_type))
        except Exception as exc:  # noqa: BLE001 — one unreadable file must not void the rest
            logger.warning("font_ai: %s skipped: %s", name, type(exc).__name__)
            continue
        if len(blocks) == MAX_IMAGES:
            break
    if not blocks:
        raise NoUsableImage("no raster image among the logo versions")
    return blocks


def _name(value: object) -> str:
    text = " ".join(str(value or "").split())
    return text[:MAX_NAME_CHARS].strip()


def parse_guess(payload: Any) -> FontGuess:
    """The tool's arguments into a `FontGuess`, trimmed and bounded. Tolerates a sloppy
    payload (wrong types, duplicates, the heading repeated among its alternatives)."""
    if not isinstance(payload, dict):
        payload = {}
    heading = _name(payload.get("heading_font"))
    raw_alternatives = payload.get("heading_alternatives")
    alternatives: list[str] = []
    if isinstance(raw_alternatives, list):
        for item in raw_alternatives:
            name = _name(item)
            if name and name.casefold() != heading.casefold() and name not in alternatives:
                alternatives.append(name)
            if len(alternatives) == MAX_ALTERNATIVES:
                break
    style = str(payload.get("style") or "").strip().lower()
    if style not in STYLES:
        style = ""
    note = " ".join(str(payload.get("note") or "").split())[:MAX_NOTE_CHARS]
    return FontGuess(
        heading=heading,
        body=_name(payload.get("body_font")),
        heading_alternatives=tuple(alternatives),
        style=style,
        note=note,
    )


def identify_fonts(
    files: Sequence[tuple[str, bytes]],
    *,
    api_key: str,
    config: ModelConfig = ModelConfig(FONT_MODEL, FONT_EFFORT),
    client_factory: ClientFactory | None = None,
) -> tuple[FontGuess, CallStats]:
    """Ask Claude which type faces the logo's lettering resembles. Raises
    `NoUsableImage` (nothing to look at), `ClaudeToolError` (refusal, truncation, no
    tool call)."""
    blocks = image_blocks(files)
    client = (client_factory or default_client)(api_key)
    meter = Meter(config)
    tool = _tool()
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [
                *blocks,
                {
                    "type": "text",
                    "text": (
                        "Estas son versiones del logo de la marca, la más completa primero. "
                        f"Identifica su tipografía con {DETECT_TOOL}."
                    ),
                },
            ],
        }
    ]
    for attempt in range(2):
        response = create_turn(
            client,
            config,
            meter,
            system=SYSTEM,
            messages=messages,
            tools=[tool],
            tool_choice=forced_or_auto(config, DETECT_TOOL),
            max_tokens=2000,
        )
        calls = [u for u in tool_uses(response) if u.name == DETECT_TOOL]
        if calls:
            meter.tool_calls += 1
            return parse_guess(calls[0].input or {}), meter.stats()
        if attempt == 0:
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": f"Entrega la respuesta con {DETECT_TOOL}."})
    raise ClaudeToolError(f"{config.model_id} did not call {DETECT_TOOL}")


def describe(guess: FontGuess) -> str:
    """The one-line note the wizard shows under the tiles — always hedged ("parece"),
    with the alternatives so the operator can pick another by hand."""
    if not guess.heading:
        return guess.note or "No encontramos texto en tu logo del que leer la tipografía."
    text = f"Parece {guess.heading}"
    if guess.heading_alternatives:
        text += f" (o {', '.join(guess.heading_alternatives)})"
    text += "."
    if guess.note:
        text += f" {guess.note}"
    return text

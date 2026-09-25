"""A brand document (a brief, a brand manual, a brandboard) → proposed Brand Kit changes,
through Claude's `proponer_brand_kit` TOOL, then VERIFIED here before anyone sees them.

The model reads the document natively — a PDF or an image goes in as a document/image
block (so a brandboard's swatches and typography are seen, not just its text layer), a
DOCX/TXT/MD as text — and answers with one strict tool call: per Brand Kit field, the
value the document supports and the literal quote (`evidence`) it comes from.

Nothing is applied here. `propose_kit_changes` returns `FieldProposal`s that already
passed four checks, and the wizard shows them as a reviewable diff:

1. Shape — hex colours normalised (#RGB → #RRGGBB, invalid dropped), tone axes within
   0–100 (anything else means "not stated"), lists stripped, de-duplicated and capped,
   free text capped.
2. Change — a proposal equal to what the kit already holds is dropped: only real
   changes are offered.
3. Evidence — when the document's text is available (DOCX/TXT/MD), the quote must
   actually be in it (accents/case/punctuation folded); a proposal whose quote is not
   found is kept but flagged `verified=False`, so the UI offers it unticked. For a PDF or
   an image there is no text to check against: `verified=None`.
4. Provenance — the caller stores which model proposed what (`CallStats`).

Model: Claude Sonnet 5 at medium effort — the same judgement tier the hashtag selection
earned in its eval; a brief is read once per brand, so cost is a few cents.
"""

from __future__ import annotations

import base64
import html
import io
import re
import unicodedata
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any

from ..claude_tools import (
    MAX_NON_STREAMING_TOKENS,
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

BRIEF_MODEL = "claude-sonnet-5"
BRIEF_EFFORT = "medium"
PROPOSE_TOOL = "proponer_brand_kit"

#: Upload ceiling. A PDF travels base64 (×4/3) and the request limit is 32 MB.
MAX_DOCUMENT_BYTES = 15 * 1024 * 1024
#: The API's per-image limit is 5 MB; larger images are re-encoded below it.
MAX_IMAGE_BYTES = 4_500_000
#: The longest side an oversized image is scaled to.
IMAGE_MAX_SIDE = 2000

MAX_TEXT_CHARS = 800
MAX_LIST_ITEMS = 10
MAX_ITEM_CHARS = 300
MAX_COLOURS = 8

SOURCES = ("brief", "brandboard")

_IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
_TEXT_TYPES = (".txt", ".md", ".markdown")
#: What the upload widgets accept — the one list both the UI and `read_document` use.
ACCEPTED_EXTENSIONS: tuple[str, ...] = (".pdf", ".docx", *_TEXT_TYPES, *_IMAGE_TYPES)


class UnsupportedDocument(ValueError):
    """A file this reader cannot hand to the model (type, size, or unreadable)."""


@dataclass(frozen=True)
class DocumentInput:
    """What the model is shown, plus the plain text evidence is verified against
    (`None` for a PDF or an image — nothing to check a quote against)."""

    blocks: tuple[dict[str, Any], ...]
    text: str | None
    kind: str  # "pdf" | "image" | "text"


@dataclass(frozen=True)
class KitSnapshot:
    """The Brand Kit as the wizard holds it now — what a proposal is compared to."""

    positioning: str = ""
    audience: str = ""
    tone_formal_casual: int = 50
    tone_sober_enthusiastic: int = 50
    tone_technical_plain: int = 50
    tone_brief_elaborate: int = 50
    do_examples: tuple[str, ...] = ()
    dont_examples: tuple[str, ...] = ()
    cta_patterns: tuple[str, ...] = ()
    banned_words: tuple[str, ...] = ()
    forbidden_claims: tuple[str, ...] = ()
    palette: tuple[str, ...] = ()


@dataclass(frozen=True)
class FieldProposal:
    """One verified change. `proposed`/`current` are in the wizard state's own string
    format (lists one per line, palette comma-separated, tone as a number) so applying
    is an assignment."""

    field: str
    label: str
    current: str
    proposed: str
    evidence: str
    #: True: the quote is in the document's text. False: it is not (offer unticked).
    #: None: the document has no text layer to check against (PDF, image).
    verified: bool | None


# --------------------------------------------------------------------------------------
# reading the document
# --------------------------------------------------------------------------------------


def _docx_text(data: bytes) -> str:
    """The text of a .docx without a dependency: it is a zip whose
    `word/document.xml` holds the paragraphs (`w:p`) and runs (`w:t`)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise UnsupportedDocument("el archivo .docx está dañado o no es un Word") from exc
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", "\t", xml)
    xml = re.sub(r"<w:br/>", "\n", xml)
    text = html.unescape(re.sub(r"<[^>]+>", "", xml))
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _image_block(data: bytes, media_type: str) -> dict[str, Any]:
    if len(data) > MAX_IMAGE_BYTES:
        try:
            from PIL import Image
        except ImportError as exc:  # pragma: no cover — pillow ships with qualify-creative
            raise UnsupportedDocument("la imagen es demasiado grande") from exc
        with Image.open(io.BytesIO(data)) as image:
            image = image.convert("RGB")
            image.thumbnail((IMAGE_MAX_SIDE, IMAGE_MAX_SIDE))
            out = io.BytesIO()
            image.save(out, format="JPEG", quality=85)
        data, media_type = out.getvalue(), "image/jpeg"
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": base64.standard_b64encode(data).decode("ascii"),
        },
    }


def read_document(filename: str, data: bytes) -> DocumentInput:
    """The model's view of an uploaded file. Raises `UnsupportedDocument` for a type
    outside `ACCEPTED_EXTENSIONS`, an empty file, or one over `MAX_DOCUMENT_BYTES`."""
    if not data:
        raise UnsupportedDocument("el archivo está vacío")
    if len(data) > MAX_DOCUMENT_BYTES:
        raise UnsupportedDocument("el archivo pesa más de 15 MB")
    suffix = PurePath(filename.lower()).suffix
    if suffix == ".pdf":
        block = {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": base64.standard_b64encode(data).decode("ascii"),
            },
        }
        return DocumentInput((block,), None, "pdf")
    if suffix in _IMAGE_TYPES:
        return DocumentInput((_image_block(data, _IMAGE_TYPES[suffix]),), None, "image")
    if suffix == ".docx":
        text = _docx_text(data)
    elif suffix in _TEXT_TYPES:
        text = data.decode("utf-8", errors="replace").strip()
    else:
        raise UnsupportedDocument(f"no leemos archivos {suffix or 'sin extensión'}")
    if not text:
        raise UnsupportedDocument("el documento no tiene texto")
    return DocumentInput(
        ({"type": "text", "text": f"<documento>\n{text}\n</documento>"},), text, "text"
    )


# --------------------------------------------------------------------------------------
# the tool
# --------------------------------------------------------------------------------------

#: (field, label, kind) in the order the wizard walks them.
FIELDS: tuple[tuple[str, str, str], ...] = (
    ("positioning", "Posicionamiento", "text"),
    ("audience", "Audiencia", "text"),
    ("tone_formal_casual", "Tono: formal ↔ coloquial", "tone"),
    ("tone_sober_enthusiastic", "Tono: sobrio ↔ entusiasta", "tone"),
    ("tone_technical_plain", "Tono: técnico ↔ llano", "tone"),
    ("tone_brief_elaborate", "Tono: breve ↔ elaborado", "tone"),
    ("do_examples", "Así sí habla la marca", "list"),
    ("dont_examples", "Así no habla la marca", "list"),
    ("cta_patterns", "Llamados a la acción", "list"),
    ("banned_words", "Palabras prohibidas", "list"),
    ("forbidden_claims", "Afirmaciones prohibidas", "list"),
    ("palette", "Paleta de colores", "palette"),
)
_TONE_AXES = ("formal_casual", "sober_enthusiastic", "technical_plain", "brief_elaborate")

SYSTEM = """\
Lees documentos de marca (briefs, manuales de marca, brandboards) y propones cómo \
rellenar el Brand Kit de Qualify: la configuración con la que la plataforma escribe \
contenido en la voz de la marca. Entregas la propuesta con la herramienta \
proponer_brand_kit, una sola vez.

Reglas:
- Solo lo que el documento dice o muestra. Si un campo no aparece, déjalo vacío ("", [] \
o -1). Un campo vacío es mejor que uno inventado o "razonable".
- evidence: copia LITERAL, de 5 a 30 palabras, del fragmento del documento que respalda \
el campo, sin comillas añadidas. Si el dato es visual (una muestra de color, el estilo de \
una imagen), describe en pocas palabras dónde está ("muestras de color de la página 2").
- Escribe en español; los ejemplos de frases van tal como aparecen en el documento.
- positioning: qué es la marca y por qué importa, de 1 a 3 frases. audience: a quién le \
habla, 1 o 2 frases.
- tone: cada eje de 0 a 100, solo si el documento describe el tono; -1 si no. \
formal_casual: 0 formal, 100 coloquial. sober_enthusiastic: 0 sobrio, 100 entusiasta. \
technical_plain: 0 técnico, 100 llano. brief_elaborate: 0 breve, 100 elaborado. Una sola \
evidence para los cuatro.
- do_examples: frases de ejemplo de cómo sí escribe la marca. dont_examples: cómo NO debe \
escribir. cta_patterns: llamados a la acción que usa. banned_words: palabras que no debe \
usar. forbidden_claims: afirmaciones que no puede hacer (promesas, comparaciones, temas \
legales o de salud). Máximo 10 por lista.
- palette: colores de la marca en hexadecimal #RRGGBB, del más importante al menos, \
máximo 8. Si el documento da códigos (HEX, RGB, CMYK, Pantone), conviértelos a HEX; si \
solo hay muestras, estima el HEX de la muestra.
- Si un valor coincide con lo que la marca ya tiene (te lo damos), déjalo vacío: solo \
propones cambios."""


def _text_prop() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"value": {"type": "string"}, "evidence": {"type": "string"}},
        "required": ["value", "evidence"],
        "additionalProperties": False,
    }


def _list_prop() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "values": {"type": "array", "items": {"type": "string"}},
            "evidence": {"type": "string"},
        },
        "required": ["values", "evidence"],
        "additionalProperties": False,
    }


def _tool() -> dict[str, Any]:
    tone = {
        "type": "object",
        "properties": {
            **{axis: {"type": "integer"} for axis in _TONE_AXES},
            "evidence": {"type": "string"},
        },
        "required": [*_TONE_AXES, "evidence"],
        "additionalProperties": False,
    }
    properties: dict[str, Any] = {
        "positioning": _text_prop(),
        "audience": _text_prop(),
        "tone": tone,
    }
    for field, _label, kind in FIELDS:
        if kind in ("list", "palette"):
            properties[field] = _list_prop()
    return strict_tool(
        PROPOSE_TOOL,
        "Entrega los valores del Brand Kit que el documento respalda, cada uno con su "
        "evidencia literal. Deja vacío lo que el documento no dice.",
        properties,
    )


def _current_lines(current: KitSnapshot) -> str:
    rows = [
        ("Posicionamiento", current.positioning),
        ("Audiencia", current.audience),
        (
            "Tono (formal_casual, sober_enthusiastic, technical_plain, brief_elaborate)",
            ", ".join(
                str(v)
                for v in (
                    current.tone_formal_casual,
                    current.tone_sober_enthusiastic,
                    current.tone_technical_plain,
                    current.tone_brief_elaborate,
                )
            ),
        ),
        ("Así sí habla", " | ".join(current.do_examples)),
        ("Así no habla", " | ".join(current.dont_examples)),
        ("Llamados a la acción", " | ".join(current.cta_patterns)),
        ("Palabras prohibidas", ", ".join(current.banned_words)),
        ("Afirmaciones prohibidas", " | ".join(current.forbidden_claims)),
        ("Paleta", ", ".join(current.palette)),
    ]
    return "\n".join(f"- {name}: {value or '(vacío)'}" for name, value in rows)


def _instructions(source: str, current: KitSnapshot) -> str:
    what = (
        "un brandboard (la hoja visual de identidad: logo, colores, tipografía, estilo)"
        if source == "brandboard"
        else "un brief o manual de marca"
    )
    return (
        f"El documento de arriba es {what}.\n\nLo que la marca ya tiene en su Brand Kit:\n"
        f"{_current_lines(current)}\n\nPropón los cambios con {PROPOSE_TOOL}."
    )


# --------------------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------------------


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9#]+", " ", plain).split())


#: A quote fragment shorter than this proves nothing (it matches half of any text).
_MIN_QUOTE = 12


def quote_in_text(evidence: str, text: str) -> bool:
    """Whether the model's quote is really in the document: every fragment of it
    (split where the model elided with "…") must appear, folded, in the folded text."""
    haystack = _fold(text)
    fragments = [_fold(f) for f in re.split(r"…|\.\.\.", evidence)]
    fragments = [f for f in fragments if len(f) >= _MIN_QUOTE]
    return bool(fragments) and all(f in haystack for f in fragments)


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").split())[:MAX_TEXT_CHARS]


def _clean_list(values: object) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values if isinstance(values, list) else []:
        item = " ".join(str(raw or "").split())[:MAX_ITEM_CHARS]
        key = _fold(item)
        if item and key not in seen:
            seen.add(key)
            out.append(item)
        if len(out) >= MAX_LIST_ITEMS:
            break
    return out


_HEX = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def normalize_hex(value: str) -> str | None:
    match = _HEX.match(value.strip())
    if match is None:
        return None
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    return f"#{digits.upper()}"


def _clean_palette(values: object) -> list[str]:
    out: list[str] = []
    for raw in values if isinstance(values, list) else []:
        colour = normalize_hex(str(raw or ""))
        if colour and colour not in out:
            out.append(colour)
        if len(out) >= MAX_COLOURS:
            break
    return out


def _verify(evidence: str, document: DocumentInput) -> bool | None:
    if document.text is None:
        return None
    return quote_in_text(evidence, document.text)


def verify_proposal(
    payload: dict[str, Any], current: KitSnapshot, document: DocumentInput
) -> list[FieldProposal]:
    """The tool's raw arguments → the changes worth showing, in `FIELDS` order."""
    out: list[FieldProposal] = []
    tone = payload.get("tone") if isinstance(payload.get("tone"), dict) else {}
    for field, label, kind in FIELDS:
        if kind == "tone":
            axis = field.removeprefix("tone_")
            value = tone.get(axis)
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100:
                continue
            now = getattr(current, field)
            if value == now:
                continue
            evidence = _clean_text(tone.get("evidence"))
            out.append(
                FieldProposal(
                    field, label, str(now), str(value), evidence, _verify(evidence, document)
                )
            )
            continue
        entry = payload.get(field) if isinstance(payload.get(field), dict) else {}
        evidence = _clean_text(entry.get("evidence"))
        if kind == "text":
            value_text = _clean_text(entry.get("value"))
            now_text = getattr(current, field)
            if not value_text or _fold(value_text) == _fold(now_text):
                continue
            out.append(
                FieldProposal(
                    field, label, now_text, value_text, evidence, _verify(evidence, document)
                )
            )
        elif kind == "list":
            values = _clean_list(entry.get("values"))
            now_list = getattr(current, field)
            if not values or {_fold(v) for v in values} == {_fold(v) for v in now_list}:
                continue
            out.append(
                FieldProposal(
                    field,
                    label,
                    "\n".join(now_list),
                    "\n".join(values),
                    evidence,
                    _verify(evidence, document),
                )
            )
        else:  # palette
            colours = _clean_palette(entry.get("values"))
            if not colours or set(colours) == {c.upper() for c in current.palette}:
                continue
            # A palette is seen, not quoted: its evidence is only checkable when the
            # document spelled the codes out in text.
            verified = (
                None
                if document.text is None
                else all(c.lower() in document.text.lower() for c in colours)
            )
            out.append(
                FieldProposal(
                    field, label, ",".join(current.palette), ",".join(colours), evidence, verified
                )
            )
    return out


def propose_kit_changes(
    document: DocumentInput,
    current: KitSnapshot,
    *,
    source: str = "brief",
    api_key: str,
    config: ModelConfig = ModelConfig(BRIEF_MODEL, BRIEF_EFFORT),
    client_factory: ClientFactory | None = None,
) -> tuple[list[FieldProposal], CallStats]:
    """Ask Claude, through `proponer_brand_kit`, what the document supports, then keep
    only verified real changes (`verify_proposal`). Raises `ClaudeToolError` when the
    model refuses, truncates, or never calls the tool."""
    if source not in SOURCES:
        raise ValueError(f"source must be one of {SOURCES}, got {source!r}")
    client = (client_factory or default_client)(api_key)
    meter = Meter(config)
    tool = _tool()
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [*document.blocks, {"type": "text", "text": _instructions(source, current)}],
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
            tool_choice=forced_or_auto(config, PROPOSE_TOOL),
            max_tokens=MAX_NON_STREAMING_TOKENS,
        )
        calls = [u for u in tool_uses(response) if u.name == PROPOSE_TOOL]
        if calls:
            meter.tool_calls += 1
            return verify_proposal(calls[0].input or {}, current, document), meter.stats()
        if attempt == 0:
            messages.append({"role": "assistant", "content": response.content})
            messages.append(
                {"role": "user", "content": f"Entrega la propuesta con {PROPOSE_TOOL}."}
            )
    raise ClaudeToolError(f"{config.model_id} did not call {PROPOSE_TOOL}")


def snapshot_lists(text: str) -> tuple[str, ...]:
    """The wizard's one-per-line fields as a tuple (blank lines dropped)."""
    return tuple(line.strip() for line in text.splitlines() if line.strip())


def snapshot_palette(text: str) -> tuple[str, ...]:
    return tuple(c.strip() for c in text.split(",") if c.strip())


__all__: Sequence[str] = (
    "ACCEPTED_EXTENSIONS",
    "BRIEF_EFFORT",
    "BRIEF_MODEL",
    "FIELDS",
    "PROPOSE_TOOL",
    "DocumentInput",
    "FieldProposal",
    "KitSnapshot",
    "UnsupportedDocument",
    "normalize_hex",
    "propose_kit_changes",
    "quote_in_text",
    "read_document",
    "snapshot_lists",
    "snapshot_palette",
    "verify_proposal",
)

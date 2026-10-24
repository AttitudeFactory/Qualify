"""A brand document (a brief, a brand manual, a brandboard) → proposed Brand Kit changes,
through Claude's `proponer_brand_kit` TOOL, then VERIFIED here before anyone sees them.

The model reads the document natively — a PDF or an image goes in as a document/image
block (so a brandboard's swatches and typography are seen, not just its text layer), a
DOCX/TXT/MD as text — and answers with one strict tool call: per Brand Kit field, the
value the document supports and the literal quote (`evidence`) it comes from.

Neither the palette nor the tone axes are among those fields (§ requests 2026-09-29,
"descartar la paleta de colores en las sugerencias" and "no quiero los tonos en el
brief"): colours reach the kit from the logo and the palette step, and the tone from its
own sliders on ¿Cómo suena?, never from a document.

Nothing is applied here. `propose_kit_changes` returns `FieldProposal`s that already
passed four checks, and the wizard shows them as a reviewable diff:

1. Shape — lists stripped, de-duplicated and capped, free text capped.
2. Change — a proposal equal to what the kit already holds is dropped: only real
   changes are offered.
3. Evidence — a proposal with NO quote is dropped (§ request 2026-09-29, "solo quiero
   los citados"). When the document's text is available (DOCX/TXT/MD), the quote must
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
import logging
import re
import unicodedata
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any

from qualify_shared import observability

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

logger = logging.getLogger(__name__)

BRIEF_MODEL = "claude-sonnet-5"
BRIEF_EFFORT = "medium"
PROPOSE_TOOL = "proponer_brand_kit"

#: Upload ceiling. Brandboards are image-heavy PDFs; the Files API takes up to 500 MB per
#: file, and what really bounds a PDF for the model is its page count (600 per request on
#: the 1M-context models), not its bytes.
MAX_DOCUMENT_BYTES = 100 * 1024 * 1024
#: Up to here a PDF travels inline, base64 (×4/3) — the request limit is 32 MB. Above it
#: the PDF is uploaded to the Files API and referenced by `file_id` (`propose_kit_changes`).
INLINE_PDF_MAX_BYTES = 15 * 1024 * 1024
#: The API's per-image limit is 5 MB; larger images are re-encoded below it.
MAX_IMAGE_BYTES = 4_500_000
#: The longest side an oversized image is scaled to.
IMAGE_MAX_SIDE = 2000

MAX_TEXT_CHARS = 800
MAX_LIST_ITEMS = 10
MAX_ITEM_CHARS = 300

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
    #: A PDF too heavy to travel inline: (filename, bytes). `propose_kit_changes`
    #: uploads it to the Files API, puts a `file_id` document block in place of
    #: `blocks`, and deletes the file once the call is done.
    upload: tuple[str, bytes] | None = None


@dataclass(frozen=True)
class KitSnapshot:
    """The Brand Kit as the wizard holds it now — what a proposal is compared to."""

    positioning: str = ""
    audience: str = ""
    do_examples: tuple[str, ...] = ()
    dont_examples: tuple[str, ...] = ()
    cta_patterns: tuple[str, ...] = ()
    banned_words: tuple[str, ...] = ()
    forbidden_claims: tuple[str, ...] = ()


@dataclass(frozen=True)
class FieldProposal:
    """One verified change. `proposed`/`current` are in the wizard state's own string
    format (lists one per line) so applying is an assignment."""

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
        raise UnsupportedDocument(
            f"el archivo pesa más de {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB"
        )
    suffix = PurePath(filename.lower()).suffix
    if suffix == ".pdf":
        if len(data) > INLINE_PDF_MAX_BYTES:
            return DocumentInput((), None, "pdf", upload=(PurePath(filename).name, data))
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

#: (field, label, kind) in the order the wizard walks them. The label is what the owner
#: reads in «Completamos desde tu documento: …» (`Qualify/brand_documents.py`), so it is
#: the field's name on the brand screens (`_KIT_LISTS` and «¿Todo correcto?» in
#: `Qualify/creative_wizard_pages.py`; MARCA-2, m-24842966; NAV-11, m-24849129) — never
#: sent to the model, which reads `_current_lines` instead.
FIELDS: tuple[tuple[str, str, str], ...] = (
    ("positioning", "Qué te hace distinto", "text"),
    ("audience", "Quién te compra", "text"),
    ("do_examples", "Ejemplos que SÍ suenan a la marca", "list"),
    ("dont_examples", "Ejemplos que NO suenan a la marca", "list"),
    ("cta_patterns", "Cómo invitas a comprar", "list"),
    ("banned_words", "Palabras vetadas", "list"),
    ("forbidden_claims", "Promesas que no puedes hacer", "list"),
)

SYSTEM = """\
Lees documentos de marca (briefs, manuales de marca, brandboards) y propones cómo \
rellenar el Brand Kit de Qualify: la configuración con la que la plataforma escribe \
contenido en la voz de la marca. Entregas la propuesta con la herramienta \
proponer_brand_kit, una sola vez.

Reglas:
- Solo lo que el documento dice o muestra. Si un campo no aparece, déjalo vacío ("" o \
[]). Un campo vacío es mejor que uno inventado o "razonable".
- evidence: copia LITERAL, de 5 a 30 palabras, del fragmento del documento que respalda \
el campo, sin comillas añadidas. Si el dato es visual (una muestra de color, el estilo de \
una imagen), describe en pocas palabras dónde está ("muestras de color de la página 2").
- Escribe en español; los ejemplos de frases van tal como aparecen en el documento.
- positioning: qué es la marca y por qué importa, de 1 a 3 frases. audience: a quién le \
habla, 1 o 2 frases.
- Todo campo necesita su evidence: un valor sin cita se descarta, así que si no puedes \
citarlo, déjalo vacío.
- do_examples: frases de ejemplo de cómo sí escribe la marca. dont_examples: cómo NO debe \
escribir. cta_patterns: llamados a la acción que usa. banned_words: palabras que no debe \
usar. forbidden_claims: afirmaciones que no puede hacer (promesas, comparaciones, temas \
legales o de salud). Máximo 10 por lista.
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
    properties: dict[str, Any] = {
        "positioning": _text_prop(),
        "audience": _text_prop(),
    }
    for field, _label, kind in FIELDS:
        if kind == "list":
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
        ("Así sí habla", " | ".join(current.do_examples)),
        ("Así no habla", " | ".join(current.dont_examples)),
        ("Llamados a la acción", " | ".join(current.cta_patterns)),
        ("Palabras prohibidas", ", ".join(current.banned_words)),
        ("Afirmaciones prohibidas", " | ".join(current.forbidden_claims)),
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


def _verify(evidence: str, document: DocumentInput) -> bool | None:
    if document.text is None:
        return None
    return quote_in_text(evidence, document.text)


def verify_proposal(
    payload: dict[str, Any], current: KitSnapshot, document: DocumentInput
) -> list[FieldProposal]:
    """The tool's raw arguments → the changes worth showing, in `FIELDS` order."""
    out: list[FieldProposal] = []
    for field, label, kind in FIELDS:
        entry = payload.get(field) if isinstance(payload.get(field), dict) else {}
        evidence = _clean_text(entry.get("evidence"))
        if not evidence:
            continue
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
        else:  # list
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
    file_id = _upload_pdf(client, *document.upload) if document.upload else None
    try:
        return _propose(client, document, current, source, config, file_id)
    finally:
        if file_id:
            _delete_file(client, file_id)


def _upload_pdf(client: Any, filename: str, data: bytes) -> str:
    """A heavy PDF to the Files API; the returned `file_id` stands in for its bytes."""
    uploaded = client.beta.files.upload(file=(filename or "documento.pdf", data, "application/pdf"))
    return str(uploaded.id)


def _delete_file(client: Any, file_id: str) -> None:
    """Uploaded files persist until deleted; a brand document is read once."""
    try:
        client.beta.files.delete(file_id)
    except Exception as exc:  # never let cleanup mask the call's own outcome
        logger.warning("brand document file %s not deleted: %s", file_id, exc)


@observability.traced("leer documento", tags=("brand_kit",))
def _propose(
    client: Any,
    document: DocumentInput,
    current: KitSnapshot,
    source: str,
    config: ModelConfig,
    file_id: str | None,
) -> tuple[list[FieldProposal], CallStats]:
    meter = Meter(config)
    tool = _tool()
    blocks = (
        [{"type": "document", "source": {"type": "file", "file_id": file_id}}]
        if file_id
        else list(document.blocks)
    )
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [*blocks, {"type": "text", "text": _instructions(source, current)}],
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
    "propose_kit_changes",
    "quote_in_text",
    "read_document",
    "snapshot_lists",
    "verify_proposal",
)

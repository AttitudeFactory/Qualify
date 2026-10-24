"""`qualify_api.creative.brief_ai` without the network: reading each file type, the
shape of the `proponer_brand_kit` call, and above all the verification that stands
between a model answer and the wizard — only real, well-formed changes, with the quote
checked against the document when it has text."""

from __future__ import annotations

import base64
import io
import json
import zipfile
from types import SimpleNamespace
from typing import Any

import pytest

from qualify_api.claude_tools import ClaudeToolError, ModelConfig
from qualify_api.creative.brief_ai import (
    BRIEF_EFFORT,
    BRIEF_MODEL,
    FIELDS,
    INLINE_PDF_MAX_BYTES,
    MAX_DOCUMENT_BYTES,
    MAX_IMAGE_BYTES,
    PROPOSE_TOOL,
    DocumentInput,
    KitSnapshot,
    UnsupportedDocument,
    propose_kit_changes,
    quote_in_text,
    read_document,
    snapshot_lists,
    verify_proposal,
)

BRIEF = (
    "Somos Casa Olivo, cocina de autor colombiana en la Zona G de Bogotá.\n"
    "Hablamos con cercanía pero sin perder la elegancia.\n"
    "Nunca decimos 'barato' ni prometemos 'el mejor restaurante de Bogotá'.\n"
    "Colores: verde oliva #556B2F y crema #F5F0E1."
)


def _docx(paragraphs: list[str]) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    xml = f'<?xml version="1.0"?><w:document><w:body>{body}</w:body></w:document>'
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return out.getvalue()


# -- reading -------------------------------------------------------------------------------


def test_a_pdf_goes_to_the_model_as_a_document_block() -> None:
    doc = read_document("Brief.PDF", b"%PDF-1.7 fake")
    assert doc.kind == "pdf" and doc.text is None
    block = doc.blocks[0]
    assert block["type"] == "document"
    assert block["source"]["media_type"] == "application/pdf"
    assert base64.standard_b64decode(block["source"]["data"]) == b"%PDF-1.7 fake"


def test_a_docx_is_read_as_text_without_a_dependency() -> None:
    doc = read_document("brief.docx", _docx(["Somos Casa Olivo", "Tono &amp; estilo"]))
    assert doc.kind == "text"
    assert doc.text == "Somos Casa Olivo\nTono & estilo"
    assert "Somos Casa Olivo" in doc.blocks[0]["text"]


def test_plain_text_and_markdown_are_read_as_text() -> None:
    assert read_document("b.md", b"# Marca\nHola").text == "# Marca\nHola"
    assert read_document("b.txt", BRIEF.encode()).kind == "text"


def test_an_image_goes_as_an_image_block_and_a_big_one_is_shrunk() -> None:
    from PIL import Image

    small = read_document("board.png", b"\x89PNG small")
    assert small.blocks[0]["source"]["media_type"] == "image/png"
    noisy = Image.effect_noise((1600, 1600), 100).convert("RGB")
    raw = io.BytesIO()
    noisy.save(raw, format="PNG")
    assert len(raw.getvalue()) > MAX_IMAGE_BYTES
    big = read_document("board.png", raw.getvalue())
    source = big.blocks[0]["source"]
    assert source["media_type"] == "image/jpeg"
    assert len(base64.standard_b64decode(source["data"])) <= MAX_IMAGE_BYTES


@pytest.mark.parametrize(
    ("name", "data"),
    [("brief.pptx", b"x"), ("brief.pdf", b""), ("brief.docx", b"not a zip"), ("b.txt", b"   ")],
)
def test_what_cannot_be_read_is_refused(name: str, data: bytes) -> None:
    with pytest.raises(UnsupportedDocument):
        read_document(name, data)


# -- verification --------------------------------------------------------------------------


TEXT_DOC = DocumentInput(({"type": "text", "text": BRIEF},), BRIEF, "text")
PDF_DOC = DocumentInput(({"type": "document"},), None, "pdf")
CURRENT = KitSnapshot(
    positioning="Restaurante en Bogotá",
    do_examples=("Te esperamos",),
)


def _payload(**overrides: Any) -> dict[str, Any]:
    empty_list = {"values": [], "evidence": ""}
    base: dict[str, Any] = {
        "positioning": {"value": "", "evidence": ""},
        "audience": {"value": "", "evidence": ""},
        "do_examples": empty_list,
        "dont_examples": empty_list,
        "cta_patterns": empty_list,
        "banned_words": empty_list,
        "forbidden_claims": empty_list,
    }
    base.update(overrides)
    return base


def test_quote_in_text_folds_accents_case_and_elisions() -> None:
    assert quote_in_text("cocina de autor colombiana en la zona g", BRIEF)
    assert quote_in_text("Somos Casa Olivo… Zona G de Bogotá", BRIEF)
    assert not quote_in_text("el restaurante más barato de la ciudad", BRIEF)
    assert not quote_in_text("Somos", BRIEF)  # too short to prove anything


def test_the_palette_is_not_proposed() -> None:
    """§ request 2026-09-29: colours never come from a document — not asked of the model,
    and a palette it sends anyway is ignored."""
    assert "palette" not in {field for field, _label, _kind in FIELDS}
    stray = _payload(palette={"values": ["#556B2F"], "evidence": "Colores: verde oliva"})
    assert verify_proposal(stray, CURRENT, TEXT_DOC) == []


def test_the_tone_is_not_proposed() -> None:
    """§ request 2026-09-29, "no quiero los tonos en el brief": the tone axes are neither
    asked of the model nor accepted from it — the sliders on ¿Cómo suena? own them."""
    from qualify_api.creative import brief_ai

    assert not any(field.startswith("tone") for field, _label, _kind in FIELDS)
    assert "tone" not in json.dumps(brief_ai._tool()["input_schema"])
    stray = _payload(
        tone={"formal_casual": 80, "evidence": "Hablamos con cercanía pero sin perder la elegancia"}
    )
    assert verify_proposal(stray, CURRENT, TEXT_DOC) == []


def test_only_real_changes_survive_and_quotes_are_checked() -> None:
    proposals = verify_proposal(
        _payload(
            positioning={
                "value": "Cocina de autor  colombiana en la Zona G",
                "evidence": "cocina de autor colombiana en la Zona G de Bogotá",
            },
            audience={
                "value": "Gente que celebra",
                "evidence": "una frase que no está en el brief",
            },
            banned_words={
                "values": ["barato", " Barato ", ""],
                "evidence": "Nunca decimos 'barato'",
            },
            do_examples={"values": ["Te esperamos"], "evidence": "x"},  # same as current
        ),
        CURRENT,
        TEXT_DOC,
    )
    by_field = {p.field: p for p in proposals}
    assert list(by_field) == [
        "positioning",
        "audience",
        "banned_words",
    ]
    assert by_field["positioning"].proposed == "Cocina de autor colombiana en la Zona G"
    assert by_field["positioning"].current == "Restaurante en Bogotá"
    assert by_field["positioning"].verified is True
    assert by_field["audience"].verified is False  # the quote is not in the brief
    assert by_field["banned_words"].proposed == "barato"


def test_a_document_without_text_cannot_be_verified() -> None:
    proposals = verify_proposal(
        _payload(audience={"value": "Familias", "evidence": "página 3"}), CURRENT, PDF_DOC
    )
    assert [(p.field, p.verified) for p in proposals] == [("audience", None)]


def test_a_proposal_without_a_quote_is_dropped() -> None:
    """§ request 2026-09-29, "solo quiero los citados": no evidence, no proposal."""
    proposals = verify_proposal(
        _payload(
            audience={"value": "Familias", "evidence": "  "},
            banned_words={"values": ["barato"], "evidence": ""},
        ),
        CURRENT,
        TEXT_DOC,
    )
    assert proposals == []


def test_an_empty_answer_proposes_nothing() -> None:
    assert verify_proposal(_payload(), CURRENT, TEXT_DOC) == []
    assert verify_proposal({}, CURRENT, TEXT_DOC) == []


def test_snapshot_helpers() -> None:
    assert snapshot_lists("a\n\n b \n") == ("a", "b")


# -- the call ------------------------------------------------------------------------------


class ScriptedClient:
    def __init__(self, *turns: list[Any]) -> None:
        self.turns = list(turns)
        self.calls: list[dict[str, Any]] = []
        self.messages = self

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        content = self.turns.pop(0)
        return SimpleNamespace(
            stop_reason="tool_use" if any(b.type == "tool_use" for b in content) else "end_turn",
            content=content,
            model=kwargs["model"],
            usage=SimpleNamespace(input_tokens=3000, output_tokens=500, cache_read_input_tokens=0),
        )


def _tool_call(payload: dict[str, Any]) -> list[Any]:
    return [SimpleNamespace(type="tool_use", id="tu_1", name=PROPOSE_TOOL, input=payload)]


def test_the_call_sends_the_document_the_current_kit_and_one_strict_tool() -> None:
    client = ScriptedClient(
        _tool_call(_payload(audience={"value": "Familias", "evidence": "Zona G de Bogotá"}))
    )
    proposals, stats = propose_kit_changes(
        TEXT_DOC, CURRENT, source="brandboard", api_key="k", client_factory=lambda _k: client
    )
    call = client.calls[0]
    assert call["model"] == BRIEF_MODEL
    assert call["output_config"] == {"effort": BRIEF_EFFORT}
    assert call["tool_choice"] == {"type": "auto"}  # a thinking model is never forced
    assert call["max_tokens"] <= 16000
    tool = call["tools"][0]
    assert tool["name"] == PROPOSE_TOOL and tool["strict"] is True
    content = call["messages"][0]["content"]
    assert content[0] == TEXT_DOC.blocks[0]
    assert "brandboard" in content[-1]["text"] and "Restaurante en Bogotá" in content[-1]["text"]
    assert [p.field for p in proposals] == ["audience"]
    assert (stats.turns, stats.tool_calls) == (1, 1)


def test_a_model_that_answers_in_prose_is_asked_once_more() -> None:
    prose = [SimpleNamespace(type="text", text="Aquí va mi análisis…")]
    client = ScriptedClient(prose, _tool_call(_payload()))
    proposals, stats = propose_kit_changes(
        TEXT_DOC, CURRENT, api_key="k", client_factory=lambda _k: client
    )
    assert proposals == [] and stats.turns == 2
    assert PROPOSE_TOOL in client.calls[1]["messages"][-1]["content"]

    with pytest.raises(ClaudeToolError):
        propose_kit_changes(
            TEXT_DOC, CURRENT, api_key="k", client_factory=lambda _k: ScriptedClient(prose, prose)
        )


def test_haiku_would_be_forced_to_call_the_tool() -> None:
    client = ScriptedClient(_tool_call(_payload()))
    propose_kit_changes(
        TEXT_DOC,
        CURRENT,
        api_key="k",
        config=ModelConfig("claude-haiku-4-5"),
        client_factory=lambda _k: client,
    )
    assert client.calls[0]["tool_choice"] == {"type": "tool", "name": PROPOSE_TOOL}


class _Files:
    def __init__(self) -> None:
        self.uploaded: list[tuple[str, int, str]] = []
        self.deleted: list[str] = []

    def upload(self, *, file: tuple[str, bytes, str]) -> SimpleNamespace:
        name, data, mime = file
        self.uploaded.append((name, len(data), mime))
        return SimpleNamespace(id="file_brandboard")

    def delete(self, file_id: str) -> None:
        self.deleted.append(file_id)


def _with_files(client: ScriptedClient) -> tuple[ScriptedClient, _Files]:
    files = _Files()
    client.beta = SimpleNamespace(files=files)  # type: ignore[attr-defined]
    return client, files


def test_a_heavy_pdf_is_not_inlined_but_marked_for_upload() -> None:
    heavy = b"%PDF-1.7 " + b"x" * INLINE_PDF_MAX_BYTES
    doc = read_document("Brandboard.pdf", heavy)
    assert doc.kind == "pdf" and doc.blocks == ()
    assert doc.upload == ("Brandboard.pdf", heavy)
    # up to the inline ceiling the PDF still travels base64, as before
    assert read_document("b.pdf", b"%PDF-1.7 small").upload is None
    with pytest.raises(UnsupportedDocument, match="100 MB"):
        read_document("b.pdf", b"x" * (MAX_DOCUMENT_BYTES + 1))


def test_a_heavy_pdf_goes_through_the_files_api_and_is_deleted_after() -> None:
    client, files = _with_files(ScriptedClient(_tool_call(_payload())))
    heavy = DocumentInput((), None, "pdf", upload=("board.pdf", b"%PDF big"))
    propose_kit_changes(heavy, CURRENT, api_key="k", client_factory=lambda _k: client)
    assert files.uploaded == [("board.pdf", 8, "application/pdf")]
    first = client.calls[0]["messages"][0]["content"][0]
    assert first == {"type": "document", "source": {"type": "file", "file_id": "file_brandboard"}}
    assert files.deleted == ["file_brandboard"]


def test_the_uploaded_pdf_is_deleted_even_when_the_model_fails() -> None:
    prose = [SimpleNamespace(type="text", text="no")]
    client, files = _with_files(ScriptedClient(prose, prose))
    heavy = DocumentInput((), None, "pdf", upload=("board.pdf", b"%PDF big"))
    with pytest.raises(ClaudeToolError):
        propose_kit_changes(heavy, CURRENT, api_key="k", client_factory=lambda _k: client)
    assert files.deleted == ["file_brandboard"]


def test_an_unknown_source_is_refused() -> None:
    with pytest.raises(ValueError):
        propose_kit_changes(TEXT_DOC, CURRENT, source="otro", api_key="k")


def test_the_labels_the_owner_reads_are_the_brand_screens_names() -> None:
    """NAV-11 (m-24849129): «Completamos desde tu documento: …» names each field as the
    brand screens do (MARCA-2, m-24842966)."""
    labels = {field: label for field, label, _kind in FIELDS}
    assert labels["positioning"] == "Qué te hace distinto"
    assert labels["audience"] == "Quién te compra"
    assert not {"Posicionamiento", "Audiencia"} & set(labels.values())

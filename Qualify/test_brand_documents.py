"""The brief / brandboard review (§ request 2026-09-25): verified proposals become rows,
an unverified one starts unticked, and only what the operator ticks reaches the Brand
Kit fields in `CreativeState`. Offline — the Claude call itself is covered in
`packages/api/tests/test_brief_ai.py`."""

from __future__ import annotations

from typing import Any

import pytest
from qualify_api.creative.brief_ai import FieldProposal

from .brand_documents import BrandDocumentState, assign, kit_snapshot, proposal_rows
from .creative_state import CreativeState


def _proposals() -> list[FieldProposal]:
    return [
        FieldProposal("positioning", "Posicionamiento", "", "Cocina de autor", "cita", True),
        FieldProposal("audience", "Audiencia", "", "Familias", "otra cita", False),
        FieldProposal("dont_examples", "Así no habla la marca", "", "¡Oferta!", "", None),
        FieldProposal("banned_words", "Palabras prohibidas", "", "barato\ngratis", "", True),
        FieldProposal("cta_patterns", "Llamados a la acción", "", "Reserva hoy", "", None),
    ]


def test_rows_carry_the_verification_and_an_unverified_quote_starts_unticked() -> None:
    rows = proposal_rows("brief", _proposals())
    assert [(r["field"], r["verified"], r["accepted"]) for r in rows] == [
        ("positioning", "si", "1"),
        ("audience", "no", "0"),
        ("dont_examples", "na", "1"),
        ("banned_words", "si", "1"),
        ("cta_patterns", "na", "1"),
    ]
    assert all(r["source"] == "brief" for r in rows)


def test_assign_writes_each_field_in_the_wizards_own_format() -> None:
    creative = CreativeState()
    assign(creative, "positioning", "Cocina de autor")
    assign(creative, "banned_words", "barato\ngratis")
    assign(creative, "cta_patterns", "Reserva hoy")
    assert creative.kit_positioning == "Cocina de autor"
    assert creative.kit_banned_words == "barato\ngratis"
    assert creative.kit_cta_patterns == "Reserva hoy"


def test_the_snapshot_reads_the_kit_as_the_wizard_holds_it() -> None:
    creative = CreativeState()
    creative.kit_do_examples = "Te esperamos\n\n¡Ven hoy!"
    snap = kit_snapshot(creative)
    assert snap.do_examples == ("Te esperamos", "¡Ven hoy!")


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> tuple[BrandDocumentState, CreativeState]:
    docs = BrandDocumentState()
    creative = CreativeState()

    async def get_state(_self: Any, state_cls: type) -> Any:
        assert state_cls is CreativeState
        return creative

    monkeypatch.setattr(BrandDocumentState, "get_state", get_state)
    docs.proposals = proposal_rows("brief", _proposals()) + proposal_rows(
        "brandboard", [FieldProposal("audience", "Audiencia", "", "Parejas", "", None)]
    )
    return docs, creative


async def test_only_ticked_proposals_of_that_document_are_applied(session) -> None:
    docs, creative = session
    BrandDocumentState.toggle_proposal.fn(docs, "brief", "banned_words")  # untick
    await BrandDocumentState.apply_proposals.fn(docs, "brief")
    assert creative.kit_positioning == "Cocina de autor"
    assert creative.kit_audience == ""  # unverified, left unticked
    assert creative.kit_dont_examples == "¡Oferta!"
    assert creative.tone_formal_casual == 50  # a brief never moves the tone sliders
    assert creative.kit_banned_words == ""  # unticked by the operator
    assert creative.kit_cta_patterns == "Reserva hoy"
    assert [r["source"] for r in docs.proposals] == ["brandboard"]  # the other doc waits
    assert docs.brief_message.startswith("Aplicamos 3 cambios")
    assert docs.brief_tone == "ok"


async def test_applying_nothing_says_so(session) -> None:
    docs, creative = session
    for row in list(docs.proposals):
        if row["source"] == "brief" and row["accepted"] == "1":
            BrandDocumentState.toggle_proposal.fn(docs, "brief", row["field"])
    await BrandDocumentState.apply_proposals.fn(docs, "brief")
    assert creative.kit_positioning == ""
    assert "No aplicamos nada" in docs.brief_message


def test_discarding_and_removing_the_brandboard(session) -> None:
    docs, _ = session
    BrandDocumentState.discard_proposals.fn(docs, "brief")
    assert [r["source"] for r in docs.proposals] == ["brandboard"]
    docs.brandboard_key = "uploads/t/brandboard/x_board.png"
    docs.brandboard_name = "board.png"
    BrandDocumentState.clear_brandboard.fn(docs)
    assert (docs.brandboard_key, docs.brandboard_name, docs.proposals) == ("", "", [])


# -- the brief behind a progress screen (2026-10-01) -----------------------------------------


def test_the_brief_read_reports_its_stages() -> None:
    docs = BrandDocumentState()
    assert docs.brief_percent == 0
    assert [row["status"] for row in docs.brief_steps] == ["pending"] * 3
    docs._set_stage("brief", "reading")
    assert docs.brief_percent == 30
    assert [row["status"] for row in docs.brief_steps] == ["done", "running", "pending"]
    docs._set_stage("brief", "sorting")
    assert [row["title"] for row in docs.brief_steps][-1] == "Ordenamos lo encontrado"
    assert [row["status"] for row in docs.brief_steps] == ["done", "done", "running"]
    docs._set_stage("brandboard", "reading")  # the brandboard has no screen of its own
    assert docs.brief_stage == "sorting"

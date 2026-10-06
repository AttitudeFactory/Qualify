"""/brand/kit — the Brand Kit inside a session, from the sidebar's "Negocio" block.
Since 2026-10-02 it is the ONLY Brand Kit inside a session ("Marca" is the pre-login
entry). Since 2026-10-05: what is still to configure (Tu voz y tono) first, else
Resultados e insights with "Editar Brand Kit", and editing as ONE view of sections, each
saved on its own."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from . import brand_finish
from . import creative_wizard_pages as wiz
from .brand_kit_editor import SECTIONS, BrandEditState, brand_edit_index, needs_voice
from .creative_state import CreativeState
from .ui.layout import NAV_BUSINESS, NAV_ITEMS
from .voice_lab import VoiceLabState


def test_the_editor_is_in_the_business_block_before_settings() -> None:
    labels = [label for label, _icon, _route, _enabled in NAV_BUSINESS]
    assert ("Brand Kit", "swatch-book", "/brand/kit", True) in NAV_BUSINESS
    assert labels.index("Brand Kit") < labels.index("Configuración")


def test_marca_is_not_in_the_session_rail() -> None:
    assert "/brand" not in {route for _label, _icon, route, _enabled in NAV_ITEMS}


def _states() -> dict[type, Any]:
    return {
        BrandEditState: BrandEditState(),
        CreativeState: CreativeState(),
        wiz.BrandWizardState: wiz.BrandWizardState(),
        wiz.BrandConnectState: wiz.BrandConnectState(),
    }


def _bind(states: dict[type, Any], monkeypatch) -> BrandEditState:
    async def get_state(_self: Any, cls: type) -> Any:
        return states[cls]

    monkeypatch.setattr(BrandEditState, "get_state", get_state)
    return states[BrandEditState]


def test_the_page_is_one_view_of_sections_not_steps() -> None:
    rendered = str(brand_edit_index())
    assert "Paso" not in rendered and "Continuar" not in rendered
    for _key, title, _icon, _blurb in SECTIONS:
        assert json.dumps(title)[1:-1] in rendered
    assert "Editar Brand Kit" in rendered and "Ver resultados" in rendered
    assert "Guardar voz" in rendered and "Ahora no" in rendered
    # the stale "not saved yet" notice of the brandboard is gone: it IS saved since 10-01
    assert "todav\\u00eda no se guardan" not in rendered


def test_the_voice_comes_first_until_it_is_saved_or_cloned() -> None:
    expression = str(needs_voice())
    for part in ("voice_configured", "clone_status", "voice_skipped"):
        assert part in expression


def test_a_visit_starts_on_the_first_screen_and_waits_for_the_details(monkeypatch) -> None:
    states = _states()
    editor = _bind(states, monkeypatch)
    editor.editing, editor.open_section, editor.voice_skipped = True, "marca", True
    states[wiz.BrandConnectState].details_loaded = True
    asyncio.run(BrandEditState.restart.fn(editor))
    assert (editor.editing, editor.open_section, editor.voice_skipped) == (False, "", False)
    assert states[wiz.BrandConnectState].details_loaded is False


def test_cancel_puts_back_what_the_section_had(monkeypatch) -> None:
    states = _states()
    editor = _bind(states, monkeypatch)
    creative, wizard = states[CreativeState], states[wiz.BrandWizardState]
    creative.kit_positioning = "Antes"
    wizard.logo_versions = {"isotipo": "uploads/t/iso.png"}
    asyncio.run(BrandEditState.open.fn(editor, "marca"))
    assert editor.open_section == "marca"
    creative.kit_positioning = "Después"
    wizard.logo_versions = {}
    asyncio.run(BrandEditState.cancel.fn(editor))
    assert creative.kit_positioning == "Antes"
    assert wizard.logo_versions == {"isotipo": "uploads/t/iso.png"}
    assert editor.open_section == ""


def test_opening_another_section_drops_the_unsaved_changes_of_the_first(monkeypatch) -> None:
    states = _states()
    editor = _bind(states, monkeypatch)
    creative = states[CreativeState]
    creative.kit_palette = "#111111"
    asyncio.run(BrandEditState.open.fn(editor, "paleta"))
    creative.kit_palette = "#111111,#222222"
    asyncio.run(BrandEditState.open.fn(editor, "tipografia"))
    assert creative.kit_palette == "#111111" and editor.open_section == "tipografia"
    asyncio.run(BrandEditState.open.fn(editor, "nope"))
    assert editor.open_section == "tipografia"


def test_leaving_the_editing_view_puts_back_an_open_section(monkeypatch) -> None:
    states = _states()
    editor = _bind(states, monkeypatch)
    BrandEditState.start_editing.fn(editor)
    states[CreativeState].kit_audience = "Antes"
    asyncio.run(BrandEditState.open.fn(editor, "marca"))
    states[CreativeState].kit_audience = "Después"
    asyncio.run(BrandEditState.show_results.fn(editor))
    assert states[CreativeState].kit_audience == "Antes" and editor.editing is False


def test_the_voice_mark_is_saved_with_the_connect_answers() -> None:
    connect = wiz.BrandConnectState()
    connect.voice_configured = True
    document = brand_finish._connect_document(connect)
    assert document is not None and document["voice_configured"] is True


def test_skipping_the_voice_lasts_this_visit_only(monkeypatch) -> None:
    states = _states()
    editor = _bind(states, monkeypatch)
    BrandEditState.skip_voice.fn(editor)
    assert editor.voice_skipped is True
    asyncio.run(BrandEditState.restart.fn(editor))
    assert editor.voice_skipped is False
    assert VoiceLabState().clone_status == ""  # a brand without a clone is asked

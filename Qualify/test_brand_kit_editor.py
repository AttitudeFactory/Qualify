"""/brand/kit — the Brand Kit inside a session, from the sidebar's "Negocio" block.
Since 2026-10-02 it is the ONLY Brand Kit inside a session ("Marca" is the pre-login
entry). Since 2026-10-05: what is still to configure (Tu voz y tono) first, else
Resultados e insights with "Editar Brand Kit", and editing as ONE view of sections, each
saved on its own."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from . import brand_finish
from . import creative_wizard_pages as wiz
from .brand_kit_editor import SECTIONS, BrandEditState, brand_edit_index, needs_voice
from .creative_state import CreativeState
from .ui.layout import NAV_BUSINESS, NAV_ITEMS
from .voice_lab import VoiceLabState


def test_the_editor_is_in_the_business_block_before_settings() -> None:
    labels = [label for label, _icon, _route, _enabled in NAV_BUSINESS]
    assert ("Tu marca", "swatch-book", "/brand/kit", True) in NAV_BUSINESS
    assert labels.index("Tu marca") < labels.index("Configuración")


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
    assert "Editar mi marca" in rendered and "Ver resultados" in rendered
    assert "Guardar voz" in rendered and "Ahora no" in rendered
    # the stale "not saved yet" notice of the brandboard is gone: it IS saved since 10-01
    assert "todav\\u00eda no se guardan" not in rendered


def test_the_voice_comes_first_until_it_is_saved_or_cloned() -> None:
    expression = str(needs_voice())
    for part in ("voice_configured", "clone_status", "tone_saved_custom", "voice_skipped"):
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


def test_no_side_index_and_the_results_take_accounts_by_hand() -> None:
    """§ request 2026-10-05: "quita los botones laterales" and a way to add referentes,
    competencia y detractores by hand on Resultados e insights."""
    from . import brand_kit_editor as editor

    assert not hasattr(editor, "_section_index")
    rendered = str(editor._results_view())
    assert json.dumps("¿Falta alguien? Agrégalo a mano")[1:-1] in rendered
    assert 'href:"#seccion-' not in str(editor._edit_view())


def test_a_tone_moved_off_its_defaults_counts_as_configured() -> None:
    """§ request 2026-10-05: cloning the voice is not required — a kit whose tone was
    moved off the defaults does not open on Voz y tono again."""
    from .creative_state import TONE_DEFAULT

    state = CreativeState()
    assert state.tone_is_custom() is False
    state.tone_sober_enthusiastic = TONE_DEFAULT + 20
    assert state.tone_is_custom() is True


def test_no_pills_over_the_manual_button_and_an_x_on_each_ranked_card() -> None:
    """§ request 2026-10-05: no pills above "Agrégalo a mano" in the Brand Kit; a ✕ on the
    ranking's cards takes an account out instead."""
    from . import brand_kit_editor as editor

    assert "remove_manual" not in str(wiz._manual_section(with_chips=False))
    assert "remove_manual" in str(wiz._manual_section())  # the wizard keeps its pills
    assert "Quitar del ranking" in str(wiz._ranking_panel())
    assert "with_chips=False" in Path(editor.__file__).read_text(encoding="utf-8")


def test_the_x_takes_a_searched_account_out_of_its_bucket() -> None:
    state = wiz.BrandConnectState()
    state.account_buckets = {"TikTok:@a": "referente", "TikTok:@b": "competencia"}
    fired = wiz.BrandConnectState.remove_manual.fn(state, "TikTok:@a")
    assert state.account_buckets == {"TikTok:@b": "competencia"}
    assert "sync_labels" in str(fired)


def test_a_manual_add_says_what_happened_in_a_toast_only() -> None:
    """§ request 2026-10-05: "quita el mensaje… solo un pop up y ya"."""
    assert "manual_message" not in wiz.BrandConnectState.__fields__
    assert "Agregamos" not in str(wiz._manual_section())
    source = Path(wiz.__file__).read_text(encoding="utf-8")
    body = source.split("async def add_manual_account", 1)[1].split("@rx.event", 1)[0]
    assert "brand_documents.notify(message, tone)" in body


def test_voz_y_tono_is_never_pending_while_editing() -> None:
    """§ request 2026-10-05: past the first check, the section does not say "Pendiente"."""
    from . import brand_kit_editor as editor

    summary = str(editor._voice_summary())
    assert "Pendiente" not in summary and "Sin voz clonada" in summary

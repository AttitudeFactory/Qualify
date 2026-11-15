"""«Tu rubro y tus etiquetas» in Tu marca (m-25029206): an existing brand sees and changes
its rubro and up to 5 etiquetas; «Cancelar» saves nothing; «Guardar» writes only those two
keys of `connect`, in the wizard's pill shape, with no search and no AI call."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID

import pytest

from . import brand_finish
from . import brand_kit_editor as editor_module
from . import brand_rubro_vm as vm
from . import creative_wizard_pages as wiz
from .brand_kit_editor import (
    RUBRO_HELP,
    RUBRO_SAVE_FAILED,
    RUBRO_TAGS_EMPTY,
    SECTIONS,
    BrandEditState,
)
from .creative_state import CreativeState

TENANT = UUID("c0000000-0000-4000-8000-00000000e206")
BRAND = UUID("b0000000-0000-4000-8000-00000000e206")
USER = UUID("a0000000-0000-4000-8000-00000000e206")


def _esc(text: str) -> str:
    return json.dumps(text)[1:-1]


# -- the pure part --------------------------------------------------------------------


def test_a_typed_tag_is_stored_as_the_catalog_reads_it() -> None:
    assert vm.typed_tag("  #CaféDeEspecialidad ") == ("cafédeespecialidad", "")
    assert vm.typed_tag("pan_de_bono") == ("pan_de_bono", "")
    assert vm.typed_tag("") == ("", "") and vm.typed_tag("#") == ("", "")


@pytest.mark.parametrize(
    ("raw", "note"),
    [
        ("pan de bono", vm.NOTE_SPACES),
        ("c++", vm.NOTE_CHARACTERS),
        ("café-bar", vm.NOTE_CHARACTERS),
        ("🍔", vm.NOTE_CHARACTERS),
        ("___", vm.NOTE_CHARACTERS),
        ("a" * 51, vm.NOTE_TOO_LONG),
    ],
)
def test_an_invalid_tag_is_refused_with_what_to_fix(raw: str, note: str) -> None:
    pills, shown, taken = vm.add_typed([], raw)
    assert pills == [] and shown == note and not taken


def test_duplicates_collapse_and_the_cap_is_five() -> None:
    pills, note, taken = vm.add_typed([], "Arepas")
    assert pills == [{"tag": "arepas", "origin": "manual", "reason": "", "model": ""}]
    assert taken and note == ""
    again, note, taken = vm.add_typed(pills, "#arepás")  # accents and case folded
    assert again == pills and note == vm.NOTE_REPEATED and taken
    for word in ("uno", "dos", "tres", "cuatro"):
        pills, _note, _taken = vm.add_typed(pills, word)
    assert len(pills) == 5 and not vm.can_add(pills)
    full, note, taken = vm.add_typed(pills, "seis")
    assert full == pills and "Caben 5 etiquetas" in note and not taken


def test_only_tags_the_catalog_accepts_are_saved_keeping_each_pill_as_written() -> None:
    suggested = {"tag": "Smashburger", "origin": "ai", "reason": "Lo usan", "model": "haiku"}
    pills = [
        suggested,
        {"tag": "c++", "origin": "manual", "reason": "", "model": ""},
        {"tag": "smashburger", "origin": "manual", "reason": "", "model": ""},
        *({"tag": f"t{i}", "origin": "manual"} for i in range(6)),
    ]
    saved = vm.pills_for_save(pills)
    assert saved[0] == {**suggested, "tag": "smashburger"}
    assert [p["tag"] for p in saved] == ["smashburger", "t0", "t1", "t2", "t3"]
    assert all(set(p) == {"tag", "origin", "reason", "model"} for p in saved)


def test_the_rubro_is_one_short_line() -> None:
    assert vm.clean_rubro("  cafetería \n de   barrio ") == "cafetería de barrio"
    assert len(vm.clean_rubro("x" * 500)) == vm.RUBRO_MAX_LENGTH


# -- the state ------------------------------------------------------------------------


def _states() -> dict[type, Any]:
    connect = wiz.BrandConnectState()
    connect.rubro_text = "hamburguesería"
    connect.rubro_hashtags = [
        {"tag": "smashburger", "origin": "ai", "reason": "Lo usan", "model": "haiku"}
    ]
    return {
        BrandEditState: BrandEditState(),
        CreativeState: CreativeState(),
        wiz.BrandWizardState: wiz.BrandWizardState(),
        wiz.BrandConnectState: connect,
    }


def _bind(states: dict[type, Any], monkeypatch: pytest.MonkeyPatch) -> BrandEditState:
    async def get_state(_self: Any, cls: type) -> Any:
        return states[cls]

    monkeypatch.setattr(BrandEditState, "get_state", get_state)
    return states[BrandEditState]


def _type(editor: BrandEditState, text: str) -> None:
    BrandEditState.open_tag_input.fn(editor)
    BrandEditState.set_tag_input.fn(editor, text)
    BrandEditState.add_tag.fn(editor)


def test_cambiar_edits_drafts_and_cancelar_saves_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    states = _states()
    editor = _bind(states, monkeypatch)
    connect = states[wiz.BrandConnectState]
    asyncio.run(BrandEditState.open.fn(editor, vm.RUBRO_SECTION))
    assert editor.open_section == vm.RUBRO_SECTION
    assert editor.rubro_draft == "hamburguesería"
    assert [p["tag"] for p in editor.tags_draft] == ["smashburger"]

    BrandEditState.set_rubro_draft.fn(editor, "hamburguesas a domicilio")
    _type(editor, "#Domicilios")
    assert not editor.adding_tag and editor.tag_input == ""
    _type(editor, "con espacios")
    assert editor.tag_note == vm.NOTE_SPACES and editor.tag_input == "con espacios"
    BrandEditState.tag_input_key.fn(editor, "Escape")
    BrandEditState.remove_tag.fn(editor, "smashburger")
    assert [p["tag"] for p in editor.tags_draft] == ["domicilios"]

    saved: list[Any] = []
    monkeypatch.setattr(brand_finish, "save_rubro", lambda *a, **k: saved.append(a))
    asyncio.run(BrandEditState.cancel.fn(editor))
    assert saved == [] and editor.open_section == ""
    assert editor.rubro_draft == "" and editor.tags_draft == []
    assert connect.rubro_text == "hamburguesería"
    assert [p["tag"] for p in connect.rubro_hashtags] == ["smashburger"]


class _Editor:
    """A background handler's `self`: the state's attributes and `async with`."""

    def __init__(self, states: dict[type, Any]) -> None:
        self._states = states
        source = states[BrandEditState]
        self.open_section = vm.RUBRO_SECTION
        self._before: dict = {}
        self.rubro_draft = source.rubro_draft
        self.tags_draft = source.tags_draft
        self.tag_input = ""
        self.adding_tag = False
        self.tag_note = ""
        self.rubro_error = ""
        self.rubro_saving = False

    async def __aenter__(self) -> _Editor:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def get_state(self, cls: type) -> Any:
        return self._states[cls]

    def _clear_rubro_drafts(self) -> None:
        BrandEditState._clear_rubro_drafts(self)  # type: ignore[arg-type]


def _save(editor: _Editor) -> list[Any]:
    async def run() -> list[Any]:
        return [event async for event in BrandEditState.save_rubro.fn(editor)]

    return asyncio.run(run())


def _no_paid_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """The kit's whole save, the search and Claude's suggestions must never run."""

    def boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a paid or whole-kit call ran")

    monkeypatch.setattr(brand_finish, "save_brand_kit", boom)
    monkeypatch.setattr(wiz.BrandConnectState, "suggest_hashtags", boom)
    monkeypatch.setattr(wiz.BrandConnectState, "run_discovery", boom)
    monkeypatch.setattr(wiz.BrandConnectState, "refresh_discovery", boom)


def test_guardar_writes_only_the_rubro_and_its_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_paid_calls(monkeypatch)
    states = _states()
    connect = states[wiz.BrandConnectState]
    editor = _Editor(states)
    editor.rubro_draft = "  hamburguesas   a domicilio "
    editor.tags_draft = [*connect.rubro_hashtags, {"tag": "c++", "origin": "manual"}]
    editor.tag_input = "Domicilios"  # still in its input: it counts

    async def ids(_state: Any) -> tuple[UUID, UUID, UUID]:
        return TENANT, BRAND, USER

    written: list[dict[str, Any]] = []

    class Store:
        def update_document_keys(self, **kwargs: Any) -> None:
            written.append(kwargs)

    monkeypatch.setattr(brand_finish, "session_ids", ids)
    monkeypatch.setattr(brand_finish, "BrandKitStore", Store)
    events = _save(editor)

    assert len(written) == 1
    call = written[0]
    assert (call["tenant_id"], call["brand_id"], call["user_id"]) == (TENANT, BRAND, USER)
    assert call["document"] == "connect"
    assert set(call["values"]) == {"rubro_text", "hashtags"}
    assert call["values"]["rubro_text"] == "hamburguesas a domicilio"
    assert call["values"]["hashtags"] == [
        {"tag": "smashburger", "origin": "ai", "reason": "Lo usan", "model": "haiku"},
        {"tag": "domicilios", "origin": "manual", "reason": "", "model": ""},
    ]
    # the session follows, so another section's save writes the new ones
    assert connect.rubro_text == "hamburguesas a domicilio"
    assert connect.hashtags_rubro == "hamburguesas a domicilio"
    assert brand_finish._connect_document(connect)["hashtags"] == call["values"]["hashtags"]
    assert editor.open_section == "" and editor.tags_draft == []
    assert len(events) == 1  # the toast


def test_the_wizard_writes_the_same_pill_shape() -> None:
    connect = wiz.BrandConnectState()
    connect.rubro_hashtags = [{"tag": "arepas", "origin": "manual", "reason": "", "model": ""}]
    document = brand_finish._connect_document(connect)
    assert document is not None
    assert document["hashtags"] == brand_finish.hashtags_document(connect.rubro_hashtags)


def test_an_invalid_tag_in_the_input_blocks_the_save(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_paid_calls(monkeypatch)
    editor = _Editor(_states())
    editor.rubro_draft = "hamburguesería"
    editor.tag_input = "pan de bono"
    monkeypatch.setattr(brand_finish, "save_rubro", lambda *a, **k: pytest.fail("saved"))
    assert _save(editor) == []
    assert editor.tag_note == vm.NOTE_SPACES and editor.open_section == vm.RUBRO_SECTION


def test_an_empty_rubro_is_asked_for(monkeypatch: pytest.MonkeyPatch) -> None:
    editor = _Editor(_states())
    editor.rubro_draft = "   "
    monkeypatch.setattr(brand_finish, "save_rubro", lambda *a, **k: pytest.fail("saved"))
    assert _save(editor) == []
    assert editor.rubro_error == vm.RUBRO_MISSING


def test_a_failed_save_keeps_the_drafts_and_says_what_to_do(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    states = _states()
    editor = _Editor(states)
    editor.rubro_draft = "panadería"

    async def ids(_state: Any) -> tuple[UUID, UUID, UUID]:
        return TENANT, BRAND, USER

    def broken(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("database down")

    monkeypatch.setattr(brand_finish, "session_ids", ids)
    monkeypatch.setattr(brand_finish, "save_rubro", broken)
    assert _save(editor) == []
    assert editor.rubro_error == RUBRO_SAVE_FAILED and not editor.rubro_saving
    assert editor.open_section == vm.RUBRO_SECTION and editor.rubro_draft == "panadería"
    assert states[wiz.BrandConnectState].rubro_text == "hamburguesería"


# -- the screen -----------------------------------------------------------------------


def test_the_section_is_on_the_page_with_its_invitation_and_help() -> None:
    keys = [key for key, *_ in SECTIONS]
    assert vm.RUBRO_SECTION in keys
    title = next(t for k, t, *_ in SECTIONS if k == vm.RUBRO_SECTION)
    section = str(editor_module._section(*SECTIONS[keys.index(vm.RUBRO_SECTION)]))
    assert _esc(title) in section and "Cambiar" in section
    assert _esc(RUBRO_TAGS_EMPTY) in section
    assert _esc(RUBRO_HELP) in section and "Agregar etiqueta" in section
    assert "save_rubro" in section
    # no suggestions here: the wizard's Claude-backed handlers are not wired
    assert "suggest_hashtags" not in section and "rubro_input_blur" not in section


def test_the_copy_is_plain_spanish_and_promises_nothing_extra() -> None:
    copy = " ".join(
        (
            RUBRO_HELP,
            editor_module.RUBRO_NO_SEARCH,
            RUBRO_TAGS_EMPTY,
            *(t for k, t, *_ in SECTIONS if k == vm.RUBRO_SECTION),
        )
    ).lower()
    for word in ("hashtag", "tiktok", "tendencia", "semana", "post", "brand"):
        assert word not in copy

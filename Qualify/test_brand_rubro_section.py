"""«Tu rubro y tus etiquetas» in Tu marca (m-25029206): an existing brand sees and changes
its rubro and up to 5 etiquetas; «Cancelar» saves nothing; «Guardar» writes only those two
keys of `connect`, in the wizard's pill shape, with no search and no AI call."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
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


def test_words_typed_apart_are_joined_into_one_tag() -> None:
    assert vm.typed_tag("comida árabe") == ("comidaárabe", "")
    assert vm.typed_tag(" #Pan de Bono ") == ("pandebono", "")


def test_a_stored_pill_without_a_tag_is_ignored_not_an_error() -> None:
    pills = [{"origin": "ai"}, "x", {"tag": "arepas", "origin": "manual"}]
    assert vm.stored_pills(pills) == [{"tag": "arepas", "origin": "manual"}]
    out, note, taken = vm.add_typed(pills, "pizzeria")  # type: ignore[arg-type]
    assert [p["tag"] for p in out] == ["arepas", "pizzeria"] and taken and note == ""


def test_a_typed_tag_is_stored_as_the_catalog_reads_it() -> None:
    assert vm.typed_tag("  #CaféDeEspecialidad ") == ("cafédeespecialidad", "")
    assert vm.typed_tag("pan_de_bono") == ("pan_de_bono", "")
    assert vm.typed_tag("") == ("", "") and vm.typed_tag("#") == ("", "")


@pytest.mark.parametrize(
    ("raw", "note"),
    [
        ("c++", vm.NOTE_CHARACTERS),
        ("cafe#bar", vm.NOTE_CHARACTERS),
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
    _type(editor, "c++")
    assert editor.tag_note == vm.NOTE_CHARACTERS and editor.tag_input == "c++"
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
        self.invalid_tags: list[str] = []

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
    editor.tags_draft = [*connect.rubro_hashtags, {"origin": "manual"}]  # no tag: ignored
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
    editor.tag_input = "c++"
    monkeypatch.setattr(brand_finish, "save_rubro", lambda *a, **k: pytest.fail("saved"))
    assert _save(editor) == []
    assert editor.tag_note == vm.NOTE_CHARACTERS and editor.open_section == vm.RUBRO_SECTION


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


def test_an_old_invalid_tag_is_marked_and_blocks_the_save_until_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    states = _states()
    states[wiz.BrandConnectState].rubro_hashtags.append({"tag": "c++", "origin": "manual"})
    editor = _bind(states, monkeypatch)
    asyncio.run(BrandEditState.open.fn(editor, vm.RUBRO_SECTION))
    assert editor.invalid_tags == ["c++"]
    fake = _Editor(states)
    fake.invalid_tags = list(editor.invalid_tags)
    monkeypatch.setattr(brand_finish, "save_rubro", lambda *a, **k: pytest.fail("saved"))
    assert _save(fake) == []
    assert fake.rubro_error == vm.NOTE_INVALID_STORED and fake.open_section == vm.RUBRO_SECTION
    BrandEditState.remove_tag.fn(editor, "c++")
    assert editor.invalid_tags == []


def test_a_blur_after_enter_or_escape_adds_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    editor = _bind(_states(), monkeypatch)
    asyncio.run(BrandEditState.open.fn(editor, vm.RUBRO_SECTION))
    _type(editor, "arepas")
    BrandEditState.tag_input_blur.fn(editor, "arepas")  # the closed input's late blur
    assert editor.tag_note == ""
    assert [p["tag"] for p in editor.tags_draft] == ["smashburger", "arepas"]
    BrandEditState.open_tag_input.fn(editor)
    BrandEditState.set_tag_input.fn(editor, "pizzeria")
    BrandEditState.tag_input_key.fn(editor, "Escape")
    BrandEditState.tag_input_blur.fn(editor, "pizzeria")
    assert len(editor.tags_draft) == 2 and editor.tag_note == ""


def test_a_visit_resets_the_section_and_a_stuck_spinner(monkeypatch: pytest.MonkeyPatch) -> None:
    editor = _bind(_states(), monkeypatch)
    editor.rubro_saving = True
    editor.adding_tag = True
    editor.tag_input = "c++"
    editor.tag_note = vm.NOTE_CHARACTERS
    editor.rubro_error = RUBRO_SAVE_FAILED
    asyncio.run(BrandEditState.restart.fn(editor))
    assert not editor.rubro_saving and not editor.adding_tag
    assert (editor.tag_input, editor.tag_note, editor.rubro_error) == ("", "", "")


def test_the_spinner_ends_whatever_the_session_lookup_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    editor = _Editor(_states())
    editor.rubro_draft = "panadería"

    async def boom(_state: Any) -> None:
        raise KeyError("anything")

    monkeypatch.setattr(brand_finish, "session_ids", boom)
    assert _save(editor) == []
    assert not editor.rubro_saving and editor.rubro_error == RUBRO_SAVE_FAILED


def test_search_again_line_only_when_the_brand_can_search() -> None:
    rendered = " ".join(str(part) for part in editor_module._rubro_editor())
    assert _esc(editor_module.RUBRO_NO_SEARCH) in rendered
    assert "profile_username" in str(editor_module._can_search_again())
    assert "Agregar etiqueta" in rendered


# -- a stale session never puts old etiquetas back (code review, should-fix 1) --------


class _Store:
    """`BrandKitStore`'s save semantics over one in-memory `connect` document."""

    def __init__(self, connect: dict[str, Any]) -> None:
        self.connect = dict(connect)

    def save_details(self, *, documents: Any, keep: Any = None, **_kw: Any) -> None:
        document = dict(documents["connect"])
        for key in (keep or {}).get("connect", ()):
            if key not in document and key in self.connect:
                document[key] = self.connect[key]
        self.connect = document

    def update_document_keys(self, *, values: Any, **_kw: Any) -> None:
        self.connect = {**self.connect, **values}

    def replace_assets(self, **_kw: Any) -> None:
        pass


class _Lock:
    def __init__(self, states: dict[type, Any]) -> None:
        self.states = states

    async def get_state(self, cls: type) -> Any:
        return self.states[cls]


def test_a_stale_session_saving_another_section_keeps_the_new_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = [{"tag": "smashburger", "origin": "ai", "reason": "", "model": ""}]
    store = _Store({"rubro_text": "hamburguesería", "hashtags": old, "city": "Cúcuta"})
    monkeypatch.setattr(brand_finish, "save_kit", lambda *a, **k: None)

    # session A loaded the brand earlier: it holds the old rubro and etiquetas
    session_a = _states()
    session_a[wiz.BrandConnectState].city = "Cúcuta"
    # session B saves new ones from «Tu rubro y tus etiquetas»
    new = [{"tag": "domicilios", "origin": "manual", "reason": "", "model": ""}]
    brand_finish.save_rubro(TENANT, BRAND, USER, "hamburguesas a domicilio", new, store=store)

    # session A saves Colores: Tu marca's whole-kit save, no wizard flow
    snapshot = asyncio.run(brand_finish.snapshot_states(_Lock(session_a), None))
    assert snapshot.connect is not None and "hashtags" not in snapshot.connect
    brand_finish.persist_brand_kit(
        TENANT,
        BRAND,
        USER,
        snapshot,
        upload_dir=Path("."),
        store=store,  # type: ignore[arg-type]
    )
    assert store.connect["hashtags"] == new
    assert store.connect["rubro_text"] == "hamburguesas a domicilio"
    assert store.connect["city"] == "Cúcuta"


def test_the_wizards_document_is_unchanged() -> None:
    """A wizard's save (any flow: `progress` given) writes the whole document, the rubro
    and its etiquetas included — byte for byte what it wrote before m-25029206."""
    connect = wiz.BrandConnectState()
    connect.network = "instagram"
    connect.username = "areperacarmen"
    connect.rubro_text = "arepera"
    connect.city = "Cúcuta"
    connect.country_code = "CO"
    connect.rubro_hashtags = [{"tag": "arepas", "origin": "ai", "reason": "r", "model": "m"}]
    progress = {"flow": "connect", "completed": True}
    expected = {
        "network": "instagram",
        "username": "areperacarmen",
        "account_kind": "",
        "has_maps": "",
        "sector": "",
        "rubro_text": "arepera",
        "country_code": "CO",
        "city": "Cúcuta",
        "hashtags": [{"tag": "arepas", "origin": "ai", "reason": "r", "model": "m"}],
        "voice_configured": False,
        brand_finish.PROGRESS_KEY: progress,
    }
    assert json.dumps(brand_finish._connect_document(connect, progress)) == json.dumps(expected)
    states = {**_states(), wiz.BrandConnectState: connect}
    snapshot = asyncio.run(brand_finish.snapshot_states(_Lock(states), progress))
    assert json.dumps(snapshot.connect) == json.dumps(expected)
    assert snapshot.connect_keep == ()

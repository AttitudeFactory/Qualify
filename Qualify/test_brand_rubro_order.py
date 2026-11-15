"""The order of the etiquetas in «Tu rubro y tus etiquetas» (m-25029206, founder's report
of 2026-11-15: «no me deja reordenar… yo ingreso un orden separado por comas pero se
visualizan con otro orden»). The typed order wins, the owner can move a tag without
typing, the order is numbered, and what is saved — and shown after a reload — is exactly
the order on screen."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID

import pytest
from qualify_api.hashtags.weekly import readable_tag

from . import brand_finish
from . import brand_kit_editor as editor_module
from . import brand_rubro_vm as vm
from . import creative_wizard_pages as wiz
from .brand_kit_editor import BrandEditState
from .creative_state import CreativeState

TENANT = UUID("c0000000-0000-4000-8000-00000000e207")
BRAND = UUID("b0000000-0000-4000-8000-00000000e207")
USER = UUID("a0000000-0000-4000-8000-00000000e207")

#: What production stored (read-only query, 2026-11-15 04:49 UTC) …
STORED = ["shawarma", "sancristobaltachira", "tachira", "ensaladas", "comidaarabe"]
#: … and what the founder typed and wanted.
WANTED = ["shawarma", "comidaarabe", "sancristobaltachira", "tachira", "ensaladas"]


def _pills(tags: list[str]) -> list[dict[str, str]]:
    return [{"tag": t, "origin": "manual", "reason": "", "model": ""} for t in tags]


def _tags(pills: list[dict[str, str]]) -> list[str]:
    return [p["tag"] for p in pills]


# -- the reproduction: what the code did before ---------------------------------------


def test_the_reported_order_is_how_the_old_rule_appended_a_retyped_list() -> None:
    """Before: with four already there, retyping the whole list in order skipped the four
    as repeats and appended the missing one at the end — exactly the stored order. Now
    the same input gives the typed order."""
    four = _pills([t for t in STORED if t != "comidaarabe"])
    out, _note, left = vm.add_typed_parts(four, ", ".join(WANTED))
    assert _tags(out) == WANTED and left == ""


# -- 1. the typed order wins ------------------------------------------------------------


def test_his_exact_case_five_present_retyped_in_his_order() -> None:
    out, note, left = vm.add_typed_parts(_pills(STORED), ", ".join(WANTED))
    assert _tags(out) == WANTED  # nothing deleted first, nothing refused
    assert left == "" and note == vm.NOTE_REORDERED


def test_typed_ones_go_first_and_the_rest_keep_their_order() -> None:
    out, _note, left = vm.add_typed_parts(_pills(STORED), "tachira, Comida Arabe")
    assert _tags(out) == [
        "tachira",
        "comidaarabe",
        "shawarma",
        "sancristobaltachira",
        "ensaladas",
    ]
    assert left == ""


def test_only_new_ones_are_added_at_the_end() -> None:
    out, note, left = vm.add_typed_parts(_pills(["a", "b"]), "c, d")
    assert _tags(out) == ["a", "b", "c", "d"] and note == "" and left == ""


def test_a_new_one_that_does_not_fit_is_kept_in_the_input_never_dropping_another() -> None:
    out, note, left = vm.add_typed_parts(_pills(STORED), "falafel, tachira")
    assert _tags(out) == [
        "tachira",
        "shawarma",
        "sancristobaltachira",
        "ensaladas",
        "comidaarabe",
    ]
    assert left == "falafel" and "Caben 5 etiquetas" in note
    assert set(_tags(out)) == set(STORED)  # nothing removed without the owner's ✕


def test_typed_twice_in_one_go_counts_once() -> None:
    out, _note, _left = vm.add_typed_parts(_pills(["a", "b"]), "b, b, a")
    assert _tags(out) == ["b", "a"]


def test_every_tag_kept_still_passes_the_weekly_read() -> None:
    out, _n, _l = vm.add_typed_parts(_pills(STORED), "Ñandú, café_bar, c++, 🍔")
    saved = vm.pills_for_save(out)
    assert all(readable_tag(p["tag"]) == p["tag"] for p in saved) and len(saved) <= 5


# -- 2. reorder without typing -----------------------------------------------------------


def test_move_tag_moves_and_ignores_what_is_out_of_range() -> None:
    pills = _pills(STORED)
    assert _tags(vm.move_tag(pills, "comidaarabe", 1)) == WANTED
    assert _tags(vm.move_tag(pills, "comidaarabe", 9)) == STORED
    assert _tags(vm.move_tag(pills, "nope", 0)) == STORED


def test_rows_number_the_tags_and_say_where_they_can_go() -> None:
    rows = vm.tag_rows(_pills(["a", "b", "c"]), ["b"])
    assert [r["number"] for r in rows] == ["1", "2", "3"]
    assert (rows[0]["can_up"], rows[0]["can_down"]) == ("", "1")
    assert (rows[2]["can_up"], rows[2]["can_down"]) == ("1", "")
    assert rows[1]["invalid"] == "1" and rows[1]["up"] == "0" and rows[1]["down"] == "2"
    assert rows[2]["handle_label"] == "Mover «#c», posición 3 de 3"


def _states() -> dict[type, Any]:
    connect = wiz.BrandConnectState()
    connect.rubro_text = "shawarma y ensaladas"
    connect.rubro_hashtags = _pills(STORED)
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


def _open(monkeypatch: pytest.MonkeyPatch) -> tuple[BrandEditState, dict[type, Any]]:
    states = _states()
    editor = _bind(states, monkeypatch)
    asyncio.run(BrandEditState.open.fn(editor, vm.RUBRO_SECTION))
    return editor, states


def test_the_menu_moves_up_down_and_to_the_top(monkeypatch: pytest.MonkeyPatch) -> None:
    editor, _ = _open(monkeypatch)
    BrandEditState.move_tag.fn(editor, "comidaarabe", "3")
    BrandEditState.move_tag.fn(editor, "comidaarabe", "2")
    BrandEditState.move_tag.fn(editor, "comidaarabe", "1")
    assert _tags(editor.tags_draft) == WANTED
    BrandEditState.move_tag.fn(editor, "ensaladas", "0")
    assert _tags(editor.tags_draft)[0] == "ensaladas"
    assert editor.tag_announce == "#ensaladas, posición 1 de 5"


def test_dragging_one_onto_another_takes_its_place(monkeypatch: pytest.MonkeyPatch) -> None:
    editor, _ = _open(monkeypatch)
    BrandEditState.pick_tag.fn(editor, "comidaarabe")
    BrandEditState.drop_tag.fn(editor, "sancristobaltachira")
    assert _tags(editor.tags_draft) == WANTED


def test_the_keyboard_lifts_moves_drops_and_escape_puts_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    editor, _ = _open(monkeypatch)
    BrandEditState.tag_key.fn(editor, "comidaarabe", " ")
    assert editor.tag_lifted == "comidaarabe" and "Levantaste" in editor.tag_announce
    for _ in range(3):
        BrandEditState.tag_key.fn(editor, "comidaarabe", "ArrowUp")
    BrandEditState.tag_key.fn(editor, "comidaarabe", "Enter")
    assert _tags(editor.tags_draft) == WANTED and editor.tag_lifted == ""
    BrandEditState.tag_key.fn(editor, "shawarma", " ")
    BrandEditState.tag_key.fn(editor, "shawarma", "ArrowDown")
    BrandEditState.tag_key.fn(editor, "shawarma", "Escape")
    assert _tags(editor.tags_draft) == WANTED and editor.tag_lifted == ""
    # arrows without a lift do nothing
    BrandEditState.tag_key.fn(editor, "shawarma", "ArrowDown")
    assert _tags(editor.tags_draft) == WANTED


def test_typing_all_five_again_reorders_in_the_section(monkeypatch: pytest.MonkeyPatch) -> None:
    editor, _ = _open(monkeypatch)
    BrandEditState.open_tag_input.fn(editor)
    BrandEditState.set_tag_input.fn(editor, ", ".join(WANTED))
    BrandEditState.add_tag.fn(editor)
    assert _tags(editor.tags_draft) == WANTED and not editor.adding_tag
    assert editor.tag_note == vm.NOTE_REORDERED


# -- 3. the order is visible -------------------------------------------------------------


def test_the_order_is_numbered_open_and_closed_and_says_why() -> None:
    closed = str(editor_module._rubro_summary())
    assert '". #"' in closed and "i_rx_state_ + 1" in closed
    assert json.dumps(vm.ORDER_HELP)[1:-1] in closed
    opened = " ".join(str(part) for part in editor_module._rubro_editor())
    assert "tag_rows" in opened and "number" in opened
    assert json.dumps(editor_module.RUBRO_ORDER_HINT)[1:-1] in opened
    for words in ("Subir", "Bajar", "Mover al principio", "Quitar"):
        assert words in opened
    assert "rubro-tags" in opened and "q-sort-handle" in opened
    assert "hashtag" not in (vm.ORDER_HELP + editor_module.RUBRO_ORDER_HINT).lower()


# -- 4. what is saved is the order shown, and a reload shows it ---------------------------


class _Store:
    def __init__(self) -> None:
        self.connect: dict[str, Any] = {"hashtags": _pills(STORED), "city": "San Cristóbal"}

    def update_document_keys(self, *, values: Any, **_kw: Any) -> None:
        self.connect = json.loads(json.dumps({**self.connect, **values}))  # as jsonb

    def load_details(self, **_kw: Any) -> Any:
        return type("D", (), {"connect": json.loads(json.dumps(self.connect))})()


class _Editor:
    def __init__(self, states: dict[type, Any]) -> None:
        self._states = states
        source = states[BrandEditState]
        for name in (
            "open_section",
            "rubro_draft",
            "tags_draft",
            "tag_input",
            "adding_tag",
            "tag_note",
            "rubro_error",
            "rubro_saving",
            "invalid_tags",
        ):
            setattr(self, name, getattr(source, name))
        self._before: dict = {}

    async def __aenter__(self) -> _Editor:
        return self

    async def __aexit__(self, *a: Any) -> None:
        return None

    async def get_state(self, cls: type) -> Any:
        return self._states[cls]

    def _clear_rubro_drafts(self) -> None:
        self.rubro_draft, self.tags_draft, self.tag_input = "", [], ""


def test_input_to_state_to_save_to_reload_keeps_one_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _Store()
    editor, states = _open(monkeypatch)
    BrandEditState.open_tag_input.fn(editor)
    BrandEditState.set_tag_input.fn(editor, ", ".join(WANTED))
    BrandEditState.add_tag.fn(editor)
    BrandEditState.move_tag.fn(editor, "ensaladas", "3")  # and one move by hand
    shown = _tags(editor.tags_draft)
    assert shown == ["shawarma", "comidaarabe", "sancristobaltachira", "ensaladas", "tachira"]

    async def ids(_state: Any) -> tuple[UUID, UUID, UUID]:
        return TENANT, BRAND, USER

    monkeypatch.setattr(brand_finish, "session_ids", ids)
    monkeypatch.setattr(brand_finish, "BrandKitStore", lambda: store)
    fake = _Editor(states)

    async def save() -> None:
        async for _ in BrandEditState.save_rubro.fn(fake):
            pass

    asyncio.run(save())
    assert _tags(store.connect["hashtags"]) == shown  # what is written
    assert store.connect["city"] == "San Cristóbal"
    assert _tags(states[wiz.BrandConnectState].rubro_hashtags) == shown  # the closed card
    _rubro, reloaded = brand_finish.load_rubro(TENANT, BRAND)  # the next visit
    assert _tags(reloaded) == shown
    assert _tags(vm.stored_pills(reloaded)) == shown and _tags(vm.pills_for_save(reloaded)) == shown

"""m-24955644 — ordering the answers of step 2 by dragging, keyboard or «⋯».

Every way in goes through ONE handler (`_move_answer`): ids travel with the answers, a
stale id or an index out of range is refused, the draft goes dirty, the open answer
follows its answer, and a move that changes which answers are buttons says so. The row
is the design system's `DragCard` + `sort_handle` (no other drag implementation).
"""

from __future__ import annotations

import json

from qualify_api.whatsapp.menus.schema import MenuDefinition

from . import whatsapp_tab_menu
from .test_whatsapp_menu_answers import _layout, _state
from .whatsapp_menu_vm import (
    ANSWERS_DRAG_HELP,
    ANSWERS_DRAG_HELP_FEW,
    MOVE_TO_TOP,
    answers_remove,
    drag_help,
)


def _order(state) -> list[str]:  # type: ignore[no-untyped-def]
    return [a.label for a in [*state.answers.buttons, *state.answers.rows]]


def _id(state, label: str) -> str:  # type: ignore[no-untyped-def]
    return next(
        a.option_id for a in [*state.answers.buttons, *state.answers.rows] if a.label == label
    )


def test_a_drop_moves_the_answer_to_the_targets_place() -> None:
    state = _state()
    start = _order(state)
    fifth, first = start[4], start[0]
    state.pick_answer(_id(state, fifth))
    toast = state.drop_answer(_id(state, first))  # answer 5 → position 1
    assert _order(state)[0] == fifth and state.dirty
    assert f"«{fifth}» ahora es botón" in json.dumps(str(toast), ensure_ascii=False)
    state.pick_answer(_id(state, first))
    state.drop_answer(_id(state, _order(state)[3]))  # answer → position 4
    assert _order(state)[3] == first


def test_a_stale_or_unknown_move_is_refused_never_a_crash() -> None:
    state = _state()
    before = _order(state)
    state.drop_answer(_id(state, before[1]))  # nothing lifted
    state.move_answer_to("ya-no-existe", 0)
    state.move_answer_to(_id(state, before[1]), 99)
    state.move_answer_to(_id(state, before[1]), -1)
    state.pick_answer("ya-no-existe")
    state.drop_answer(_id(state, before[0]))
    assert _order(state) == before and not state.dirty


def test_the_menu_moves_one_place_or_to_the_top() -> None:
    state = _state()
    last = _order(state)[-1]
    state.move_answer_to(_id(state, last), 0)  # «Mover al principio»
    assert _order(state)[0] == last
    state.move_answer_to(_id(state, last), 1)  # «Bajar»
    assert _order(state)[1] == last


def test_the_keyboard_lifts_moves_drops_and_escape_puts_it_back() -> None:
    state = _state()
    start = _order(state)
    target = start[3]
    oid = _id(state, target)
    assert state.answer_key(oid, "ArrowUp") is None  # not lifted: nothing moves
    state.answer_key(oid, " ")
    assert state.answer_lifted == oid and "Levantaste" in state.answers_announce
    state.answer_key(oid, "ArrowUp")
    state.answer_key(oid, "ArrowUp")
    assert _order(state)[1] == target
    assert state.answers_announce.startswith(f"{target}, posición 2 de {len(start)}")
    events = state.answer_key(oid, "Enter")  # drop
    assert state.answer_lifted == "" and "data-sort-key" in str(events)
    assert _order(state)[1] == target and state.dirty
    # Escape: back to the order before the lift, and the draft as clean as it was
    state2 = _state()
    oid2 = _id(state2, start[4])
    state2.answer_key(oid2, "Enter")
    state2.answer_key(oid2, "ArrowUp")
    state2.answer_key(oid2, "Escape")
    assert _order(state2) == start and not state2.dirty


def test_the_open_answer_follows_its_answer() -> None:
    state = _state()
    label = _order(state)[4]
    state.open_answer_panel(4)
    state.move_answer_to(_id(state, label), 0)
    assert state.answer_open == 0 and state.open_answer.label == label


def test_a_drop_in_third_place_goes_to_mas_preguntas_in_the_preview() -> None:
    state = _state()
    moved = _order(state)[0]
    state.move_answer_to(_id(state, moved), 2)
    definition = MenuDefinition.model_validate(state._valid_payload)
    buttons, rows = _layout(definition)
    assert moved not in buttons and rows[0] == moved
    assert "en «Más preguntas»" in state.answers_announce


def test_the_row_is_the_design_systems_drag_card_with_its_handle() -> None:
    rendered = str(whatsapp_tab_menu.menu_tab())
    compact = rendered.replace(" ", "")
    for marker in (
        '"data-rank-group":"menu-answers"',
        "data-rank-key",
        "data-rank-handle",
        "data-sort-key",
        "q-sort-handle",
        "q-rank-card q-answer-row".replace(" ", ""),
        "answer_key",
        "pick_answer",
        "drop_answer",
        "move_answer_to",
    ):
        assert marker in compact, marker
    assert 'style:"' not in compact  # never a string `style` (the Orbit lesson)
    for words in (MOVE_TO_TOP, "handle_label", "more_label", "drag_help"):
        assert json.dumps(words)[1:-1] in rendered, words
    state = _state()
    first = state.answers.buttons[0]
    assert first.handle_label == f"Mover «{first.label}», posición 1 de {state.answers.count}"
    assert first.more_label == f"Más opciones para «{first.label}»"
    assert "move_answer(" not in rendered and "limit_move_down" not in rendered


def test_a_move_that_keeps_the_same_two_buttons_says_nothing() -> None:
    """Compared with the DRAFT's order before the move, never what the browser showed."""
    state = _state()
    rows = state.answers.rows
    assert state.move_answer_to(rows[2].option_id, len(_order(state)) - 1) is None
    assert "Listo:" not in state.answers_announce
    # the second button down one place swaps with the first row: that one DOES say it
    second = state.answers.buttons[1]
    assert state.move_answer_to(second.option_id, 2) is not None


def test_drag_out_and_back_to_the_same_place_says_nothing() -> None:
    state = _state()
    oid = _id(state, _order(state)[4])
    state.pick_answer(oid)
    assert state.drop_answer(oid) is None  # released on its own place
    state.answer_key(oid, " ")  # keyboard: lift, up, down, drop
    state.answer_key(oid, "ArrowUp")
    state.answer_key(oid, "ArrowDown")
    events = state.answer_key(oid, " ")
    assert "Listo:" not in json.dumps(str(events), ensure_ascii=False)


def test_deshacer_restores_the_order_and_the_drafts_state() -> None:
    state = _state()
    start = _order(state)
    state.move_answer_to(_id(state, start[4]), 0)
    assert state.dirty
    state.undo_answers_move()
    assert _order(state) == start and not state.dirty
    assert state.answers_announce == "Listo: volvió el orden que tenías."
    # something else changed after the move: the order comes back, the draft stays dirty
    state.move_answer_to(_id(state, start[4]), 0)
    state.set_guided_question("¿Qué necesitas?")
    state.undo_answers_move()
    assert _order(state) == start and state.dirty
    state.undo_answers_move()  # one level only: nothing more to undo
    assert _order(state) == start


def test_the_help_line_follows_how_many_answers_there_are() -> None:
    assert drag_help(1) == "" and drag_help(0) == ""
    assert drag_help(2) == drag_help(3) == ANSWERS_DRAG_HELP_FEW
    assert ANSWERS_DRAG_HELP_FEW == (
        "Arrastra para cambiar el orden. Así salen los botones en WhatsApp."
    )
    assert drag_help(4) == ANSWERS_DRAG_HELP
    state = _state()
    for _ in range(state.answers.count - 2):
        state._apply(answers_remove(state._form(), state.answers.count - 1))
    assert state.drag_help == ANSWERS_DRAG_HELP_FEW


def test_escape_after_another_edit_keeps_that_edit() -> None:
    state = _state()
    start = _order(state)
    oid = _id(state, start[4])
    state.answer_key(oid, " ")
    state.answer_key(oid, "ArrowUp")
    state.set_guided_question("¿Qué necesitas hoy?")  # an edit meanwhile ends the lift
    assert state.answer_lifted == ""
    state.answer_key(oid, "Escape")
    assert state.guided.question == "¿Qué necesitas hoy?"
    assert _order(state)[3] == start[4]  # the move made before the edit stays too


def test_escape_puts_only_the_order_back() -> None:
    state = _state()
    start = _order(state)
    oid = _id(state, start[4])
    state.answer_key(oid, "Enter")
    state.answer_key(oid, "ArrowUp")
    state.answer_key(oid, "ArrowUp")
    state.answer_key(oid, "Escape")
    assert _order(state) == start and not state.dirty


def test_deshacer_after_an_edit_keeps_the_edit() -> None:
    state = _state()
    start = _order(state)
    state.move_answer_to(_id(state, start[4]), 0)
    state.set_guided_question("¿Qué necesitas hoy?")
    state.undo_answers_move()
    assert _order(state) == start and state.guided.question == "¿Qué necesitas hoy?"
    assert state.dirty


# --- «Deshacer» / Escape and saving (re-review of cc2b4b0e) --------------------------


def _savable(monkeypatch):  # type: ignore[no-untyped-def]
    from uuid import UUID

    from . import whatsapp_menu_state as module
    from .test_whatsapp_menu_publish import CONNECTION, TENANT, _fake_save
    from .whatsapp_menu_state import WhatsAppMenuState

    async def session(self: object) -> tuple[str, UUID | None, str]:
        return str(TENANT), TENANT, "duena@example.com"

    async def connection_id(self: object) -> str:
        return CONNECTION

    monkeypatch.setattr(WhatsAppMenuState, "_session", session)
    monkeypatch.setattr(WhatsAppMenuState, "_connection_id", connection_id)
    monkeypatch.setattr(module, "user_id_for", lambda *a: None)
    monkeypatch.setattr(module, "save_version", _fake_save([]))
    return _state()


async def _save(state) -> None:  # type: ignore[no-untyped-def]
    from .test_whatsapp_menu_publish import _run_plain
    from .whatsapp_menu_state import WhatsAppMenuState

    await _run_plain(WhatsAppMenuState.save_current_version, state)


async def test_deshacer_after_a_save_does_nothing(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    state = _savable(monkeypatch)
    start = _order(state)
    assert state.move_answer_to(_id(state, start[4]), 0) is not None  # a toast
    moved = _order(state)
    await _save(state)
    assert not state.dirty
    state.undo_answers_move()  # within the 6 s: a silent no-op now
    assert _order(state) == moved and not state.dirty


async def test_escape_after_a_save_leaves_the_order_as_saved(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    state = _savable(monkeypatch)
    oid = _id(state, _order(state)[4])
    state.answer_key(oid, " ")
    state.answer_key(oid, "ArrowUp")
    moved = _order(state)
    await _save(state)
    assert state.answer_lifted == ""
    state.answer_key(oid, "Escape")
    assert _order(state) == moved and not state.dirty


def test_deshacer_while_saving_is_ignored() -> None:
    state = _state()
    start = _order(state)
    state.move_answer_to(_id(state, start[4]), 0)
    moved = _order(state)
    state.saving = True
    state.undo_answers_move()
    assert _order(state) == moved
    state.saving = False
    state.undo_answers_move()  # the undo is still there once the save is over
    assert _order(state) == start


def test_undo_with_other_unsaved_edits_keeps_the_draft_unsaved() -> None:
    state = _state()
    state.set_guided_question("¿Qué necesitas hoy?")  # unsaved before the move
    start = _order(state)
    state.move_answer_to(_id(state, start[4]), 0)
    state.undo_answers_move()
    assert _order(state) == start and state.dirty

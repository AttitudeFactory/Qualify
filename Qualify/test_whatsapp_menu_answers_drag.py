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
from .whatsapp_menu_vm import ANSWERS_DRAG_HELP, MOVE_TO_TOP


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
    state.drop_answer(_id(state, first))  # answer 5 → position 1
    assert _order(state)[0] == fifth and state.dirty
    assert f"ahora «{fifth}» es botón" in state.order_note
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
    for words in (ANSWERS_DRAG_HELP, MOVE_TO_TOP, "handle_label", "more_label"):
        assert json.dumps(words)[1:-1] in rendered, words
    state = _state()
    first = state.answers.buttons[0]
    assert first.handle_label == f"Mover «{first.label}», posición 1 de {state.answers.count}"
    assert first.more_label == f"Más opciones para «{first.label}»"
    assert "move_answer(" not in rendered and "limit_move_down" not in rendered

"""The Brand Kit's list fields as pills: each list stays the newline-joined `kit_*`
string the kit form and the brief/brandboard proposals already use, and the pills
read and write it."""

from __future__ import annotations

from .creative_state import CreativeState


def test_a_typed_value_joins_its_list_once_and_the_input_clears() -> None:
    state = CreativeState()
    state.kit_banned_words = "barato\n"
    state.set_kit_pill_draft("banned", "  el   mejor ")
    state.add_kit_pill("banned")
    assert state.kit_banned_words == "barato\nel mejor"
    assert state.kit_banned_items == ["barato", "el mejor"]
    assert state.kit_pill_drafts["banned"] == ""

    state.set_kit_pill_draft("banned", "BARATO")  # already there, ignoring case
    state.add_kit_pill("banned")
    assert state.kit_banned_items == ["barato", "el mejor"]


def test_an_empty_draft_adds_nothing() -> None:
    state = CreativeState()
    state.set_kit_pill_draft("cta", "   ")
    state.add_kit_pill("cta")
    assert state.kit_cta_patterns == ""


def test_removing_a_pill_drops_that_value_only() -> None:
    state = CreativeState()
    state.kit_do_examples = "Hola, vecino\n\nTe esperamos\nReserva ya"
    assert state.kit_do_items == ["Hola, vecino", "Te esperamos", "Reserva ya"]
    state.remove_kit_pill("do", 1)
    assert state.kit_do_examples == "Hola, vecino\nReserva ya"
    state.remove_kit_pill("do", 9)  # out of range: nothing happens
    assert state.kit_do_items == ["Hola, vecino", "Reserva ya"]


def test_each_list_has_its_own_pills() -> None:
    state = CreativeState()
    for field, attr in (
        ("do", "kit_do_examples"),
        ("dont", "kit_dont_examples"),
        ("cta", "kit_cta_patterns"),
        ("banned", "kit_banned_words"),
        ("claims", "kit_forbidden_claims"),
    ):
        state.set_kit_pill_draft(field, f"valor {field}")
        state.add_kit_pill(field)
        assert getattr(state, attr) == f"valor {field}"
    state.set_kit_pill_draft("nope", "x")  # unknown field: ignored
    state.add_kit_pill("nope")
    assert "nope" not in state.kit_pill_drafts


def test_objective_and_intent_take_only_known_values() -> None:
    state = CreativeState()
    state.set_objective(["lead"])  # a segmented control may send a list
    assert state.brief_objective == "lead"
    state.set_objective("invented")
    assert state.brief_objective == "lead"
    state.set_intent("ads")
    state.set_intent("nope")
    assert state.brief_intent == "ads"

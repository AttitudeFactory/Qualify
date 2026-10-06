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


# -- edited in place on ¿Todo correcto? (§ request 2026-09-30) ---------------------------


def test_editing_a_pill_replaces_only_that_value() -> None:
    state = CreativeState()
    state.kit_banned_words = "barato\nel mejor\ngratis"
    state.start_kit_pill_edit("banned", 1)
    assert (state.kit_pill_edit_field, state.kit_pill_edit_index) == ("banned", 1)
    assert state.kit_pill_edit_value == "el mejor"
    state.set_kit_pill_edit_value("  el   número uno ")
    state.save_kit_pill_edit()
    assert state.kit_banned_items == ["barato", "el número uno", "gratis"]
    assert (state.kit_pill_edit_field, state.kit_pill_edit_index) == ("", -1)


def test_emptying_a_pill_removes_it_and_a_duplicate_merges() -> None:
    state = CreativeState()
    state.kit_cta_patterns = "Reserva ya\nEscríbenos\nVen hoy"
    state.start_kit_pill_edit("cta", 0)
    state.set_kit_pill_edit_value("   ")
    state.save_kit_pill_edit()
    assert state.kit_cta_items == ["Escríbenos", "Ven hoy"]
    state.start_kit_pill_edit("cta", 1)
    state.set_kit_pill_edit_value("ESCRÍBENOS")  # already in the list, ignoring case
    state.save_kit_pill_edit()
    assert state.kit_cta_items == ["Escríbenos"]


def test_escape_and_a_second_save_change_nothing() -> None:
    state = CreativeState()
    state.kit_do_examples = "Hola, vecino"
    state.start_kit_pill_edit("do", 0)
    state.set_kit_pill_edit_value("otra cosa")
    state.kit_pill_edit_key("Enter")  # only Escape cancels
    assert state.kit_pill_edit_field == "do"
    state.kit_pill_edit_key("Escape")
    assert state.kit_pill_edit_field == ""
    state.save_kit_pill_edit()  # e.g. the input's blur right after Enter or Escape
    assert state.kit_do_items == ["Hola, vecino"]


def test_an_edit_can_only_start_on_a_real_value() -> None:
    state = CreativeState()
    state.start_kit_pill_edit("claims", 0)
    state.start_kit_pill_edit("nope", 0)
    assert state.kit_pill_edit_field == ""


def test_removing_a_pill_closes_an_open_edit() -> None:
    state = CreativeState()
    state.kit_dont_examples = "a\nb\nc"
    state.start_kit_pill_edit("dont", 2)
    state.remove_kit_pill("dont", 0)
    assert state.kit_pill_edit_field == "" and state.kit_dont_items == ["b", "c"]


# -- the "+" that opens a list's input (§ request 2026-10-06) ----------------------------


def test_the_plus_opens_one_list_input_and_enter_closes_it() -> None:
    state = CreativeState()
    state.open_kit_pill_input("do")
    assert state.kit_pill_adding == "do"
    state.set_kit_pill_draft("do", "¡Te esperamos!")
    state.add_kit_pill("do")
    assert state.kit_do_items == ["¡Te esperamos!"]
    assert state.kit_pill_adding == ""  # back to "+"
    state.open_kit_pill_input("nope")  # unknown list: nothing opens
    assert state.kit_pill_adding == ""


def test_leaving_the_input_adds_and_leaving_it_empty_just_closes() -> None:
    state = CreativeState()
    state.open_kit_pill_input("cta")
    state.kit_pill_add_blur("  Escríbenos por WhatsApp ")
    assert state.kit_cta_items == ["Escríbenos por WhatsApp"]
    assert state.kit_pill_adding == ""

    state.open_kit_pill_input("cta")
    state.kit_pill_add_blur("   ")
    assert state.kit_cta_items == ["Escríbenos por WhatsApp"]
    assert state.kit_pill_adding == ""


def test_escape_closes_the_input_and_forgets_the_draft() -> None:
    state = CreativeState()
    state.open_kit_pill_input("banned")
    state.set_kit_pill_draft("banned", "barato")
    state.kit_pill_add_key("a")  # any other key: still open
    assert state.kit_pill_adding == "banned"
    state.kit_pill_add_key("Escape")
    assert state.kit_pill_adding == "" and state.kit_pill_drafts["banned"] == ""
    assert state.kit_banned_words == ""


def test_the_example_is_a_pill_only_while_the_list_is_empty() -> None:
    """The example pill renders under `items.length() == 0`, and no input is mounted
    until the "+" is pressed."""
    from . import creative_wizard_pages as wiz

    rendered = str(wiz._kit_list_editor(*wiz._KIT_LISTS[0]))
    assert "Ej.: " in rendered
    assert "kit_do_items" in rendered and "length" in rendered
    assert "kit_pill_adding" in rendered  # the input sits behind the "+"

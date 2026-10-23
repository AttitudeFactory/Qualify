"""CREAR-6 (m-24842980): on a phone every kind of /create shows with its explanation, and
«Datos clave» is typed without commas."""

from __future__ import annotations

import json
from pathlib import Path

from .creative_state import CreativeState
from .creative_vm import CATEGORY_OPTIONS, add_phrase, phrase_list, remove_phrase

_CSS = Path(__file__).resolve().parent.parent / "assets" / "qualify-creative.css"


def _has(rendered: str, text: str) -> bool:
    return text in rendered or json.dumps(text)[1:-1] in rendered


def test_every_option_shows_its_blurb_in_the_panel() -> None:
    from .content_generator import _DISCOVER_HEADING, _VARIATIONS_HEADING, _kind_picker

    picker = str(_kind_picker())
    for _key, title, blurb, _icon in CATEGORY_OPTIONS:
        assert _has(picker, title) and _has(picker, blurb)
    for title, blurb, _icon in (_VARIATIONS_HEADING, _DISCOVER_HEADING):
        assert _has(picker, title) and _has(picker, blurb)
    assert _DISCOVER_HEADING[0] == "Descubrir ideas de videos"
    assert "q-cr-option-blurb" in picker


def test_no_explanation_lives_only_in_a_tooltip() -> None:
    from .content_generator import _kind_picker

    picker = str(_kind_picker())
    assert "Tooltip" not in picker
    # the longer explanations are a «?» opened by a click or a tap
    assert "Popover" in picker


def test_the_phone_panel_is_one_column_not_a_sideways_row() -> None:
    css = _CSS.read_text(encoding="utf-8")
    assert ".q-cr-options-list { flex-direction: row" not in css
    assert ".q-cr-option-blurb { display: block; }" in css


def test_no_field_says_separated_by_commas() -> None:
    from .content_generator import _section_rules

    rendered = str(_section_rules()).lower()
    assert "separado por comas" not in rendered
    for label in ("¿Qué dato?", "¿Cuánto o cuál?", "Debe mencionar", "Debe evitar"):
        assert _has(str(_section_rules()), label)


def test_phrases_are_added_one_at_a_time_and_joined_for_the_brief() -> None:
    assert phrase_list("envío gratis,  reserva por WhatsApp , ,Envío gratis") == [
        "envío gratis",
        "reserva por WhatsApp",
    ]
    text = add_phrase("", "envío gratis")
    text = add_phrase(text, "Envío Gratis")  # a repeat, in other case
    text = add_phrase(text, "2x1 los jueves")
    assert text == "envío gratis, 2x1 los jueves"
    assert remove_phrase(text, "envío gratis") == "2x1 los jueves"
    assert phrase_list(add_phrase("", ", ".join(f"f{i}" for i in range(20)))) == [
        f"f{i}" for i in range(12)
    ]


def test_the_state_turns_the_draft_into_a_chip() -> None:
    state = CreativeState()
    state.set_brief_must_mention_draft("envío gratis")
    state.add_must_mention()
    state.set_brief_must_mention_draft("reserva por WhatsApp")
    state.add_must_mention()
    assert state.brief_must_mention == "envío gratis, reserva por WhatsApp"
    assert state.brief_must_mention_draft == ""
    state.remove_must_mention("envío gratis")
    assert state.brief_must_mention == "reserva por WhatsApp"
    state.set_brief_must_avoid_draft("barato")
    state.add_must_avoid()
    assert state.brief_must_avoid == "barato"
    state.remove_must_avoid("barato")
    assert state.brief_must_avoid == ""

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
    # the ticket's sentence, keeping #307's precision about what the filter keeps
    assert _DISCOVER_HEADING[1] == (
        "Los videos con más vistas de las cuentas que tomas de referencia, solo de tu "
        "producto o su categoría, para inspirarte o hacer uno parecido."
    )
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


# -- the UX review of CREAR-6 ------------------------------------------------------------


def test_a_phrase_typed_but_not_added_still_reaches_the_brief() -> None:
    state = CreativeState()
    state.brief_topic = "Promo del viernes"
    state.set_brief_must_mention_draft("envío gratis")
    state.set_brief_must_avoid_draft("barato")
    state.next_view()  # leaving the step flushes both drafts
    assert state.brief_must_mention == "envío gratis"
    assert state.brief_must_avoid == "barato"
    assert state.brief_must_mention_draft == state.brief_must_avoid_draft == ""
    assert state._generator_form()["must_mention"] == "envío gratis"


def test_the_keyboard_enter_adds_the_phrase() -> None:
    state = CreativeState()
    state.set_brief_must_mention_draft("envío gratis")
    state.add_must_mention_on_key("a")
    assert state.brief_must_mention == ""
    state.add_must_mention_on_key("Enter")
    assert state.brief_must_mention == "envío gratis"
    state.set_brief_must_avoid_draft("barato")
    state.add_must_avoid_on_key("Enter")
    assert state.brief_must_avoid == "barato"


def test_the_phrase_field_says_when_it_is_full_and_the_chip_is_not_the_remove_button() -> None:
    from .content_generator import _section_rules
    from .creative_vm import PHRASE_LIMIT_HINT

    rendered = str(_section_rules())
    assert _has(rendered, PHRASE_LIMIT_HINT)
    assert _has(rendered, "Para quitarla, toca la ✕.")
    assert "enterKeyHint" in rendered or "enter_key_hint" in rendered
    assert "<button" not in rendered.split("q-cr-phrase-chip")[0][-80:]


def test_choosing_an_option_brings_the_view_into_sight_on_a_phone() -> None:
    from .content_generator import _workspace
    from .creative_state import CreativeState as S

    assert "q-cr-view" in str(_workspace(S.readiness))
    state = S()
    for events in (state.open_discover(), state.open_variations()):
        assert "q-cr-view" in str(events) and "max-width: 899px" in str(events)
    assert "q-cr-view" in str(state.choose_category("image"))


def test_replicate_says_soon_with_its_help_always_visible() -> None:
    """m-24842980 hallazgo 6: «Pronto» like the menu, and the help written under the
    button — not only in a tooltip, which a phone never shows."""
    from .discover_reels import REPLICATE_HELP, discover_view

    rendered = str(discover_view().render())
    assert _has(rendered, "Replicar con mi marca") and "Muy pronto" not in rendered
    assert REPLICATE_HELP == "Pronto podrás hacer tu versión de este video con tu marca."
    assert "q-dr-replicate-help" in rendered and "Pronto podr" in rendered

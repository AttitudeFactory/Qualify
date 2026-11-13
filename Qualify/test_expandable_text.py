"""`ui.expandable_text` (m-24921079, Deivid 2026-11-10): a text cut at N lines with
«Ver más» / «Ver menos» — and its first use, the part cards of «Orden del clip»."""

from __future__ import annotations

import reflex as rx

from .creative_state import CreativeState
from .ui import expandable_text
from .ui.expandable_text import LESS_LABEL, MORE_LABEL

LONG = "De cerca, una arepa caliente se parte por la mitad y deja ver el queso derretido."
ESCAPED_A = chr(92) + "u00e1"


class _Demo(rx.State):
    open_keys: list[str] = []

    @rx.event
    def toggle(self, key: str) -> None:
        self.open_keys = [k for k in self.open_keys if k != key] or [key]


def _render(**kw: object) -> str:
    # the compiled JS writes the accented letter as a backslash-u escape
    return str(expandable_text(**kw)).replace(ESCAPED_A, "á")  # type: ignore[arg-type]


def test_the_labels_are_spanish_and_plain() -> None:
    assert (MORE_LABEL, LESS_LABEL) == ("Ver más", "Ver menos")


def test_a_long_text_is_cut_and_gets_an_accessible_button() -> None:
    out = _render(
        text=LONG,
        expanded=_Demo.open_keys.contains("a"),
        on_toggle=_Demo.toggle("a"),
        id="t-a",
        lines=3,
    )
    assert "q-expandable--cut" in out and '["--q-lines"] : "3"' in out
    assert 'jsx("button"' in out and 'type:"button"' in out
    assert '"aria-expanded":' in out and '"aria-controls":"t-a"' in out
    assert "Ver más" in out and "Ver menos" in out
    # the tap stops at the button: it never reaches the drag card around it
    assert '["stopPropagation"] : true' in out


def test_a_short_static_text_never_shows_the_button() -> None:
    out = _render(text="Corto.", expanded=False, on_toggle=_Demo.toggle("b"))
    # the button sits behind a condition that is the literal `false`
    assert '(false?(jsx(Fragment,{},jsx("button"' in out


def test_the_rule_is_a_character_threshold() -> None:
    from .ui.expandable_text import DEFAULT_MIN_CHARS, _long_enough

    assert DEFAULT_MIN_CHARS == 60
    assert str(_long_enough("x" * 61, 60)) == "true"
    assert str(_long_enough("x" * 60, 60)) == "false"


def test_a_part_card_opens_by_its_key_and_keeps_it_when_moved() -> None:
    creative = CreativeState()
    plan = {"mode": "reference", "seconds": 5, "description": LONG}
    creative._set_reel_plan([{"key": k, "plan": dict(plan)} for k in ("k2", "k5")])
    CreativeState.toggle_reel_part_text.fn(creative, "k2")
    assert creative.reel_expanded == ["k2"]
    CreativeState.toggle_reel_part_text.fn(creative, "k5")
    CreativeState.toggle_reel_part_text.fn(creative, "k2")
    assert creative.reel_expanded == ["k5"]


def test_the_part_card_uses_the_component_for_the_description() -> None:
    import inspect

    from . import content_generator

    source = inspect.getsource(content_generator._part_item)
    assert "expandable_text(" in source
    assert "CreativeState.reel_expanded.contains(key)" in source
    assert "toggle_reel_part_text(key)" in source


def test_a_key_that_is_not_a_part_is_ignored() -> None:
    creative = CreativeState()
    CreativeState.toggle_reel_part_text.fn(creative, "no-such-part")
    assert creative.reel_expanded == []


def test_a_new_plan_keeps_only_its_own_open_parts() -> None:
    creative = CreativeState()
    plan = {"mode": "reference", "seconds": 5, "description": LONG}
    creative._set_reel_plan([{"key": k, "plan": dict(plan)} for k in ("a", "b")])
    CreativeState.toggle_reel_part_text.fn(creative, "a")
    CreativeState.toggle_reel_part_text.fn(creative, "b")
    creative._set_reel_plan([{"key": "b", "plan": dict(plan)}])  # «a» was taken out
    assert creative.reel_expanded == ["b"]
    creative._set_reel_plan([])
    assert creative.reel_expanded == []


def test_a_new_piece_closes_every_open_part() -> None:
    from .parts_start_state import apply_to_creative
    from .parts_start_vm import entries_from_proposal
    from .test_parts_start import _clip, _proposal

    creative = _clip()
    apply_to_creative(
        creative, story="", entries=entries_from_proposal(_proposal(2)), provenance=None
    )
    CreativeState.toggle_reel_part_text.fn(creative, creative.reel_part_rows[0]["key"])
    assert len(creative.reel_expanded) == 1
    CreativeState.start_new_piece.fn(creative)
    assert creative.reel_expanded == []

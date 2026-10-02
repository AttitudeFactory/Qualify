"""/brand/kit — the Brand Kit editor in the sidebar's "Negocio" block (§ request
2026-09-30)."""

from __future__ import annotations

from .brand_kit_editor import EDIT_LAST, EDIT_STEPS, BrandEditState
from .ui.layout import NAV_BUSINESS


def test_the_editor_is_in_the_business_block_before_settings() -> None:
    labels = [label for label, _icon, _route, _enabled in NAV_BUSINESS]
    assert ("Brand Kit", "swatch-book", "/brand/kit", True) in NAV_BUSINESS
    assert labels.index("Brand Kit") < labels.index("Configuración")


def test_the_editor_walks_its_views_and_stops_at_both_ends() -> None:
    state = BrandEditState()
    state.prev_step()
    assert state.step == 0
    for _ in range(len(EDIT_STEPS) + 3):
        state.next_step()
    assert state.step == EDIT_LAST
    assert EDIT_STEPS[EDIT_LAST][0] == "Resultados e insights"
    assert EDIT_STEPS[EDIT_LAST - 1][0] == "¿Todo correcto?"
    state.prev_step()
    assert state.step == EDIT_LAST - 1
    state.restart()
    assert state.step == 0

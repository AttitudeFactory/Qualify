"""/brand/kit — the Brand Kit editor (§ request 2026-09-30). Since 2026-10-02 it is a
pre-login tool: the guest rail links it, the session's "Negocio" block does not."""

from __future__ import annotations

import inspect

from .brand_kit_editor import EDIT_LAST, EDIT_STEPS, BrandEditState
from .ui import layout
from .ui.layout import NAV_BUSINESS, NAV_ITEMS


def test_the_editor_is_out_of_the_session_rail_and_in_the_guest_one() -> None:
    assert "/brand/kit" not in {route for _label, _icon, route, _enabled in NAV_ITEMS}
    assert [label for label, *_ in NAV_BUSINESS] == ["Clarity", "Vitrina", "Configuración"]
    assert '"/brand/kit"' in inspect.getsource(layout._guest_islands)


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

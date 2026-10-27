"""PASOS-8: fixed menu steps, session resume, and the existing explicit confirmation."""

from __future__ import annotations

from collections.abc import Iterator
from urllib.parse import parse_qs, urlsplit

import pytest
import reflex as rx

from .home_page import home_index
from .test_whatsapp_menu_guided import _state
from .whatsapp_menu_state import WhatsAppMenuState
from .whatsapp_page import whatsapp_index
from .whatsapp_tab_menu import _guided_card, menu_step_frame


def _walk(component: rx.Component) -> Iterator[rx.Component]:
    yield component
    for child in component.children:
        yield from _walk(child)


def test_guided_menu_uses_the_page_frame_and_one_route_history_listener() -> None:
    frame = menu_step_frame()
    assert "q-step-head" in str(frame.children[0])
    assert "q-step-foot" in str(frame.children[2])
    assert "q-step-count-page" in str(frame.children[0])
    # The module-level condition puts the frame straight in the shell, never in page_body.
    page = whatsapp_index()
    markers = [c for c in _walk(page) if "q-route-pop" in str(c.class_name)]
    assert len(markers) == 1
    assert "q-step-head" not in str(_guided_card())


def test_next_and_back_settle_the_panel_without_publishing(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _state(monkeypatch)
    state.set_guided_greeting("Mi saludo sin publicar")
    forward = state.guided_next()
    assert state.guided_step == 2
    assert state.guided_direction == "next"
    backward = state.guided_back()
    assert state.guided_step == 1
    assert state.guided_direction == "back"
    assert state.guided.greeting == "Mi saludo sin publicar"
    assert "main.q-panel" in str(forward)
    assert "main.q-panel" in str(backward)
    assert not state.publish_confirm_open


def test_last_step_primary_opens_confirmation_and_never_publishes_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)
    state.guided_go(4)
    assert state.can_publish
    assert state.guided_primary() is None
    assert state.publish_confirm_open
    assert not state.publishing and not state.saving
    state.set_publish_confirm_open(False)
    assert not state.publish_confirm_open
    state.error_count = 1
    state.guided_primary()
    assert not state.publish_confirm_open


def test_later_goes_to_inicio_and_resumes_an_incomplete_session_without_a_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)
    state.loaded_for = "a0000000-0000-4000-8000-000000000001"
    state.set_guided_greeting("")
    state.guided_go(3)
    draft_nodes = list(state.nodes)
    event = state.save_for_later()
    assert '"/"' in str(event)
    assert state.resume_pending
    assert state.nodes == draft_nodes
    assert not state.publishing and not state.saving
    assert not state.flow_ready
    params = {key: value[0] for key, value in parse_qs(urlsplit(state.resume_href).query).items()}
    monkeypatch.setattr(WhatsAppMenuState, "_flow_params", lambda self: params)
    state.restore_flow()
    assert state.guided_step == 3
    assert state.guided.greeting == ""
    assert not state.resume_pending
    assert "/whatsapp" in str(home_index())
    state.reset()
    assert not state.resume_pending and not state.publish_confirm_open


def test_navigation_and_leaving_do_not_interrupt_an_in_flight_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)
    state.guided_step = 4
    state.publishing = True
    assert state.guided_back() is None
    assert state.save_for_later() is None
    assert state.leave_guided() is None
    assert state.guided_step == 4


def test_menu_motion_animates_existing_panel_and_keeps_editor_key_constant() -> None:
    import inspect

    script = str(WhatsAppMenuState()._guided_settle())
    assert "prefers-reduced-motion" in script
    assert "panel.animate" in script
    assert "--q-dur-slow" in script and "--q-ease" in script
    assert "data-dir" in str(_guided_card())
    source = inspect.getsource(menu_step_frame)
    assert "step=1" in source
    assert "direction=S.guided_direction" in source


@pytest.mark.parametrize("reduced", [False, True])
@pytest.mark.parametrize("duration", ["380ms", "0.38s"])
def test_menu_animation_uses_direction_and_honors_reduced_motion(reduced, duration) -> None:
    from .test_route_history import _node

    event = WhatsAppMenuState()._guided_settle()
    script = event.args[0][1]._var_value
    harness = """
let seen=[];
const panel={dataset:{dir:'back'},getAnimations:()=>[],
 animate:(frames,options)=>seen.push({frames,options})};
const document={querySelector:s=>s==='.q-menu-guided-panel'?panel:null};
const window={requestAnimationFrame:fn=>fn(),addEventListener:()=>{},
 matchMedia:()=>({matches:REDUCED})};
const getComputedStyle=()=>({getPropertyValue:name=>name==='--q-dur-slow'?'DURATION':'ease'});
""".replace("REDUCED", str(reduced).lower()).replace("DURATION", duration)
    result = _node(harness + script + "console.log(JSON.stringify(seen));")
    if reduced:
        assert result == []
    else:
        assert result[0]["frames"] == [{"transform": "translateX(-8px)"}, {"transform": "none"}]
        assert result[0]["options"]["duration"] == 380

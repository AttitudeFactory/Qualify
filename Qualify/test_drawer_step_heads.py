"""PASOS-7: fixed drawer progress, honest step counts and session-only promotion drafts."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
import reflex as rx

from . import whatsapp_campaigns_state as campaigns
from .catalog_page import _new_product_drawer
from .planner_drawer import assign_drawer
from .planner_state import MODE_RESCHEDULE, PlannerState
from .ui.primitives import drawer
from .ui.steps import step_progress
from .whatsapp_tab_campaigns import campaign_wizard
from .whatsapp_tab_chats import _templates_drawer
from .whatsapp_tab_templates import template_form


def _walk(component: rx.Component) -> Iterator[rx.Component]:
    yield component
    for child in component.children:
        yield from _walk(child)


def _with_class(component: rx.Component, name: str) -> rx.Component:
    return next(node for node in _walk(component) if name in str(node.class_name))


@pytest.mark.parametrize(
    "factory",
    [
        _new_product_drawer,
        assign_drawer,
        campaign_wizard,
        template_form,
        _templates_drawer,
    ],
)
def test_step_counter_is_inside_the_fixed_head_and_outside_the_scrolling_body(
    factory: Callable[[], rx.Component],
) -> None:
    component = factory()
    head = _with_class(component, "q-drawer-head")
    body = _with_class(component, "q-drawer-body")
    assert "q-step-progress" in str(head)
    assert "q-step-count-drawer" in str(head)
    assert "q-step-progress" not in str(body)


def test_drawer_title_sends_heading_props_to_radix_instead_of_css() -> None:
    component = drawer(
        open=True,
        on_open_change=PlannerState.set_form_open,
        title="Agregar producto",
        icon="package",
        step=step_progress(1, 3),
    )
    title = next(node for node in _walk(component) if node.tag == "Dialog.Title")
    props = title.render()["props"]
    assert 'as:"h2"' in props
    assert 'size:"5"' in props
    css = next((prop for prop in props if prop.startswith("css:")), "")
    assert '"size"' not in css and '"asChild"' not in css
    assert '"aria-describedby":"q-step-count-drawer"' in props


@pytest.mark.parametrize(
    ("reschedule", "step", "number", "total", "name"),
    [
        (False, 0, 1, 3, "Contenido"),
        (False, 2, 3, 3, "Confirmar"),
        (True, 1, 1, 2, "Cuándo sale"),
        (True, 2, 2, 2, "Confirmar"),
    ],
)
def test_planner_head_counts_only_the_steps_the_owner_walks(
    reschedule: bool,
    step: int,
    number: int,
    total: int,
    name: str,
) -> None:
    state = PlannerState()
    if reschedule:
        state.form_mode = MODE_RESCHEDULE
    state.form_step = step
    assert state.form_flow_step == number
    assert state.form_step_total == total
    assert state.form_step_name == name
    assert state.form_step_counter == f"Paso {number} de {total}"


class _Wizard:
    def __init__(self, state: campaigns.WhatsAppCampaignsState) -> None:
        object.__setattr__(self, "state", state)

    def __getattr__(self, key: str) -> Any:
        return getattr(self.state, key)

    def __setattr__(self, key: str, value: Any) -> None:
        setattr(self.state, key, value)

    async def __aenter__(self) -> _Wizard:
        return self

    async def __aexit__(self, *_args: object) -> bool:
        return False


async def test_closing_and_reopening_a_promotion_keeps_message_audience_and_step_without_sending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scope(_state: object) -> tuple[str, UUID, str]:
        return "a0000000-0000-4000-8000-000000000001", UUID(int=2), ""

    async def count(_state: object) -> None:
        return None

    def refuse_write(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Closing or reopening a draft must never create or launch a promotion")

    monkeypatch.setattr(campaigns.WhatsAppCampaignsState, "_scope", scope)
    monkeypatch.setattr(campaigns.WhatsAppCampaignsState, "_count", count)
    monkeypatch.setattr(campaigns, "wizard_templates", lambda *_args: [])
    monkeypatch.setattr(campaigns, "brands_for", lambda *_args: [])
    monkeypatch.setattr(campaigns, "count_audience", lambda *_args: 7)
    monkeypatch.setattr(campaigns.inbox_provider, "tenant_zone", lambda *_args: ZoneInfo("UTC"))
    monkeypatch.setattr(campaigns, "create_draft", refuse_write)
    monkeypatch.setattr(campaigns, "launch", refuse_write)
    state = campaigns.WhatsAppCampaignsState()
    state.wizard_open = True
    state.step = 1
    state.w_name = "Promo que sigo después"
    state.w_template_id = "template-local"
    state.w_values = {"1": "Nuestro menú de hoy"}
    state.w_scope = "since"
    state.w_from = "2026-10-01"
    state.w_sources = ["web"]
    state._close_wizard()
    assert not state.wizard_open
    await campaigns.WhatsAppCampaignsState.open_wizard.fn(_Wizard(state))
    assert state.wizard_open
    assert state.step == 1
    assert state.w_name == "Promo que sigo después"
    assert state.w_template_id == "template-local"
    assert state.w_values == {"1": "Nuestro menú de hoy"}
    assert state.w_from == "2026-10-01" and state.w_sources == ["web"]
    state.reset()
    assert not state.wizard_open
    assert state.w_name == "" and state.w_values == {} and state.w_sources == []

"""PASOS-3: restoring an address only restores valid session state; it never acts."""

from __future__ import annotations

from uuid import uuid4

import pytest

from . import catalog_state as catalog
from . import planner_state as planner
from . import whatsapp_campaigns_state as campaigns
from . import whatsapp_chats_state as chats
from . import whatsapp_templates_state as templates
from .nav_url import flow_param


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({}, 0),
        ({"flujo": "other", "paso": "2"}, 0),
        ({"flujo": "producto"}, 1),
        ({"flujo": "producto", "paso": "3"}, 3),
        ({"flujo": "producto", "paso": "99"}, 3),
        ({"flujo": "producto", "paso": "-4"}, 1),
        ({"flujo": "producto", "paso": ["2", "3"]}, 1),
        ({"flujo": ["producto"], "paso": "2"}, 0),
    ],
)
def test_flow_reader_handles_valid_absent_repeated_and_out_of_range(params, expected) -> None:
    assert flow_param(params, "producto", 3) == expected


def test_product_restore_cannot_claim_a_save_and_browser_back_keeps_the_draft(monkeypatch) -> None:
    requested = [3]
    monkeypatch.setattr(catalog, "flow_param", lambda *_args: requested[0])
    state = catalog.CatalogState()
    state.new_name = "Almuerzo"
    state.restore_flow()
    assert state.form_open and state.new_step == catalog.STEP_NAME
    assert state.created_product_id == ""
    requested[0] = 0
    state.restore_flow()
    assert not state.form_open
    assert state.new_name == "Almuerzo"
    requested[0] = 2
    state.restore_flow()
    assert state.form_open and state.new_step == catalog.STEP_NAME
    assert state.new_name == "Almuerzo"


def test_empty_planner_restores_first_missing_step_without_scheduling(monkeypatch) -> None:
    monkeypatch.setattr(planner, "flow_param", lambda *_args: 3)
    state = planner.PlannerState()
    state.restore_flow()
    assert state.form_open and state.form_step == planner.STEP_POST
    assert not state.plan_items
    assert not state.saving


def test_a_foreign_reschedule_id_can_only_request_a_scoped_provider_read(monkeypatch) -> None:
    event_id = str(uuid4())
    monkeypatch.setattr(planner, "scalar_param", lambda *_args: "reprogramar")
    monkeypatch.setattr(planner, "uuid_param", lambda *_args: event_id)
    monkeypatch.setattr(planner, "flow_param", lambda *_args: 2)
    state = planner.PlannerState()
    event = state.restore_flow()
    assert not state.form_open
    assert "open_reschedule" in str(event) and event_id in str(event)
    assert not state.form_event_id


def test_approved_message_restore_stops_at_missing_body_without_sending(monkeypatch) -> None:
    requested = [4]
    monkeypatch.setattr(templates, "flow_param", lambda *_args: requested[0])
    state = templates.WhatsAppTemplatesState()
    state.restore_flow()
    assert state.form_open and state.step == templates.STEP_KIND + 1
    assert not state.submitting and not state.form_done
    state.form_body = "Hola, tenemos novedades."
    state.restore_flow()
    assert state.step == templates.STEP_REVIEW
    requested[0] = 0
    state.restore_flow()
    assert not state.form_open
    assert state.form_body == "Hola, tenemos novedades."


def test_campaign_restore_never_creates_a_draft_or_launches_it(monkeypatch) -> None:
    monkeypatch.setattr(campaigns, "flow_param", lambda *_args: 3)
    state = campaigns.WhatsAppCampaignsState()
    state._apply_flow_step()
    assert state.step == campaigns.STEP_MESSAGE
    assert not state.w_campaign_id and not state.launching
    state.w_name = "Para el viernes"
    state.wizard_open = True
    state._close_wizard()
    assert state.w_name == "Para el viernes"  # closing is not a restart


def test_chat_message_restore_cannot_skip_the_picker_or_send(monkeypatch) -> None:
    monkeypatch.setattr(chats, "flow_param", lambda *_args: 2)
    state = chats.WhatsAppChatsState()
    state._apply_flow_step()
    assert state.tpl_open and not state.tpl_reviewing
    assert not state.tpl_selected and not state.tpl_sending

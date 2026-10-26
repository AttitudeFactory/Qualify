"""PASOS-5: product + creation steps, guarded history and session-only resume."""

from __future__ import annotations

from uuid import UUID

import pytest
from reflex.istate.data import ReflexURL, RouterData

from . import creative_state as module
from .creative_state import CreativeState
from .creative_vm import DraftVM
from .ui.steps_vm import DIR_BACK


def _chosen() -> CreativeState:
    state = CreativeState()
    state.selected_product_id = "catalog-product"
    state.brief_topic = "El almuerzo de hoy"
    return state


def test_product_is_counted_and_first_form_step_can_go_back_without_losing_inputs() -> None:
    state = _chosen()
    assert state.create_step_n == 1
    assert state.create_step_m == len(state._gen_steps()) + 1
    state.confirm_product()
    assert state.create_step_n == 2
    state.create_back()
    assert state.create_step_n == 1
    assert state.brief_topic == "El almuerzo de hoy"
    assert state.selected_product_id == "catalog-product"
    state._show_create_step(2)  # browser forward after going back to the product
    assert state.product_confirmed
    assert state.create_step_n == 2


def test_an_unanswered_product_cannot_be_skipped_by_an_address_or_continue() -> None:
    state = CreativeState()
    state._show_create_step(5)
    assert state.create_step_n == 1
    assert state.create_continue() is None
    assert not state.product_confirmed


def test_step_navigation_and_summary_edit_preserve_the_brief() -> None:
    state = _chosen()
    state.confirm_product()
    state.next_view()
    assert state.create_step_n == 3
    event = state.prev_view()
    assert state.create_step_n == 2
    assert state.gen_direction == DIR_BACK
    assert "qStepGo" in str(event)
    state.gen_step = len(state._gen_steps()) - 1
    state.edit_view("topic")
    assert state.gen_direction == DIR_BACK
    assert state.brief_topic == "El almuerzo de hoy"


def test_result_back_reopens_review_and_create_another_restarts_the_form() -> None:
    state = _chosen()
    state.confirm_product()
    state.generator_view = "result"
    assert state.create_step_n == state.create_step_m
    state.create_back()
    assert state.generator_view == "form"
    assert state.gen_is_last_view
    state.generator_view = "result"
    event = state.new_generation()
    assert state.create_step_n == 2
    assert "main.q-panel" in str(event)
    assert "window.scrollTo" not in str(event)
    assert state.brief_topic == "El almuerzo de hoy"


def test_later_leaves_for_inicio_without_resetting_the_session_draft() -> None:
    state = _chosen()
    state.confirm_product()
    state.next_view()
    event = state.save_for_later()
    assert '"/"' in str(event)
    assert state.create_resume_pending
    state.leave_create_frame()
    assert not state.create_entered
    assert state.create_step_n == 3
    assert state.brief_topic == "El almuerzo de hoy"


def test_going_back_while_a_draft_generates_does_not_enable_a_second_paid_call() -> None:
    state = _chosen()
    state.confirm_product()
    state.generator_view = "result"
    state.gen_draft_id = "pending-draft"
    state.gen_draft = DraftVM(
        draft_id="pending-draft",
        status="drafting",
        status_label="",
        status_tone="",
        is_drafting=True,
    )
    state.create_back()
    assert state.generator_view == "form"
    assert state.gen_generating
    assert state.create_primary_disabled
    assert state.create_continue() is None


async def test_pending_draft_keeps_polling_after_returning_to_the_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _chosen()
    state.confirm_product()
    state.generator_view = "result"
    state.gen_draft_id = "b0000000-0000-4000-8000-000000000001"
    state.create_back()
    done = DraftVM(draft_id=state.gen_draft_id, status="generated", status_label="", status_tone="")

    async def ids(_state):
        return (UUID("a0000000-0000-4000-8000-000000000001"), None, None)

    monkeypatch.setattr(CreativeState, "_session_ids", ids)
    monkeypatch.setattr(module, "draft_detail", lambda *_args: done)
    monkeypatch.setattr(module, "_generation_done_events", lambda _outcome: [])
    assert [event async for event in CreativeState.poll_generator.fn(state)] == []
    assert state.gen_draft == done
    assert not state.gen_generating
    assert not state.create_primary_disabled


def test_mobile_kind_picker_opens_on_demand_and_closes_after_a_choice() -> None:
    state = _chosen()
    state.confirm_product()
    assert not state.create_options_open
    state.toggle_create_options()
    assert state.create_options_open
    state.choose_category("image")
    assert state.gen_category == "image"
    assert not state.create_options_open
    assert state.selected_product_id == "catalog-product"
    assert state.brief_topic == "El almuerzo de hoy"
    state.toggle_create_options()
    state.open_variations()
    assert not state.create_options_open


def test_cancelled_generation_cannot_be_opened_from_the_sticky_review_action() -> None:
    from .creative_vm import queue_vm

    state = _chosen()
    state.confirm_product()
    state.generator_view = "result"
    state.gen_draft_id = "cancelled-draft"
    state.gen_draft = DraftVM(
        draft_id=state.gen_draft_id,
        status="failed",
        status_label="Cancelado",
        status_tone="gray",
        is_failed=True,
        queue=queue_vm(cancelled=True),
    )
    assert state.create_primary_disabled
    assert state.create_reason == "Cancelamos tu video. Te devolvimos la creación."
    assert state.create_continue() is None


def test_invalid_cold_step_without_a_product_returns_guarded_entry_ack() -> None:
    state = CreativeState()
    state.router = RouterData(url=ReflexURL("http://localhost:3000/create?paso=99"))
    event = state.enter_create_step()
    assert state.create_step_n == 1
    assert state.create_entry_epoch == 1
    assert "__qStepEntry" in str(event)
    assert "99" in str(event)
    assert state.create_entered

"""Owner-facing queue facts: estimates, cancellation and ordinary generation."""

from qualify_api.creative.queue_visibility import estimate_minutes

from Qualify.creative_vm import queue_vm


def test_six_minutes_from_real_load() -> None:
    vm = queue_vm(queued=True, can_cancel=True, estimated_minutes=estimate_minutes(12, 4, 120))
    assert vm.note == "Tu video está en fila. Estará listo en unos 6 minutos."
    assert vm.can_cancel


def test_singular_and_under_a_minute() -> None:
    assert queue_vm(queued=True, estimated_minutes=1).note == (
        "Tu video está en fila. Estará listo en 1 minuto."
    )
    assert queue_vm(queued=True, estimated_minutes=estimate_minutes(1, 4, 120)).note == ""
    assert queue_vm(queued=True).note == ""


def test_cancelled_and_sent() -> None:
    assert queue_vm(cancelled=True).note == "Cancelamos tu video. Te devolvimos la creación."
    assert not queue_vm().can_cancel
    assert queue_vm(estimated_minutes=6).note == ""


def test_unknown_capacity_does_not_make_up_wait() -> None:
    assert estimate_minutes(12, 0, 120) is None
    assert estimate_minutes(12, 4, float("nan")) is None
    assert estimate_minutes(12, 4, -10) is None


def test_notice_compiles_with_actual_state_vars() -> None:
    from Qualify.creative_state import CreativeState
    from Qualify.queue_notice import queue_notice

    component = str(queue_notice(CreativeState.draft.queue, CreativeState.draft.draft_id))
    assert "Cancelar" in component
    assert "44px" in component
    assert "cancel_queue" in component


def test_cancelled_is_not_labelled_as_a_generation_failure() -> None:
    from Qualify.creative_vm import build_draft_summary_vm

    vm = build_draft_summary_vm(
        draft_id="d", topic="t", status="failed", created_label="", failure_reason="cancelled"
    )
    assert vm.status == "failed"  # backend FSM remains unchanged
    assert vm.status_label == "Cancelado" and vm.status_tone == "gray"

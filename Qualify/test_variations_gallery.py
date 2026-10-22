"""Tests for the «Variaciones» gallery (m-24803289): generating the pieces, polling
while they are made, retrying one and approving one.

Same harness as `test_variations_state.py`: no DB and no providers — the provider
functions are replaced with stand-ins and `_session_ids` is monkeypatched on the CLASS.

Pins:
1. «Generar» sends the batch ONCE, keeps the service's outcome (queued, failed and
   warnings) and refuses before any call when nothing is pending.
2. Only a piece that is still being made keeps the gallery polling: a `generated` draft
   waits for the operator and a `failed` one waits for a retry — neither is in flight.
3. The poll re-reads the set and stops by itself when nothing is in flight any more.
4. A retry goes through the service and the screen says so.
5. A refused approval shows the service's own sentence AND re-reads the set, so the
   card shows the price conflict that refused it instead of going quiet.
6. Reopening a set from the list loads it and resumes the poll when something is still
   being made.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from . import variations_state as module
from .variations_state import VariationsState
from .variations_vm import AngleVM, OutcomeVM, SetSummaryVM, SetVM, any_in_flight

_TENANT_ID = UUID("a0000000-0000-4000-8000-000000000001")
_BRAND_ID = UUID("b0000000-0000-4000-8000-000000000001")
_USER_ID = UUID("c0000000-0000-4000-8000-000000000001")
_SET_ID = "e0000000-0000-4000-8000-000000000001"
_ANGLE_ID = "f0000000-0000-4000-8000-000000000001"


def _angle(**kw: Any) -> AngleVM:
    base: dict[str, Any] = {
        "id": _ANGLE_ID,
        "position": 1,
        "title": "En la mesa del almuerzo",
        "scene": "Mesa de madera",
        "composition": "Plano cenital",
        "hook": "Tu almuerzo, resuelto",
        "cta": "Pídelo hoy",
        "rationale": "El momento de consumo real",
        "status": "queued",
        "status_label": "En generación",
        "status_tone": "info",
        "draft_id": "d0000000-0000-4000-8000-000000000001",
        "draft_status": "drafting",
        "draft_label": "Generando",
        "draft_tone": "info",
        "preview_key": "",
        "preview_url": "",
        "copy_hook": "",
        "copy_caption": "",
        "price_conflicts": (),
        "warnings": (),
        "failure_text": "",
        "can_discard": False,
        "can_restore": False,
        "can_retry": False,
        "can_approve": False,
        "can_edit": False,
        "can_regenerate": False,
    }
    base.update(kw)
    return AngleVM(**base)


def _set_vm(*angles: AngleVM, pending: int = 0) -> SetVM:
    kept = angles or (_angle(),)
    return SetVM(
        id=_SET_ID,
        product_name="Shawarma mixto",
        preset_key="escena_producto",
        status="generating",
        status_label="Generando piezas",
        status_tone="info",
        price_label="$18.000",
        price_missing=False,
        price_note="",
        failure_text="",
        campaign_id="",
        pending_count=pending,
        kept_count=len(kept),
        angles=tuple(kept),
    )


async def _fake_session_ids(self: VariationsState) -> tuple[UUID, UUID, UUID]:
    return (_TENANT_ID, _BRAND_ID, _USER_ID)


def _state(monkeypatch: pytest.MonkeyPatch) -> VariationsState:
    monkeypatch.setattr(VariationsState, "_session_ids", _fake_session_ids)
    monkeypatch.setattr(module, "_POLL_SECONDS", 0.0)
    return VariationsState()


async def _drain(events: Any) -> list[Any]:
    return [event async for event in events]


# ---------------------------------------------------------------------------
# 1. generating the batch


async def test_generate_sends_the_batch_once_and_keeps_the_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)
    state.set_id, state.pending_count = _SET_ID, 2
    calls: list[tuple[Any, ...]] = []
    outcome = OutcomeVM(
        queued=1,
        failed=1,
        unresolved=0,
        message="1 en generación · 1 no se pudieron enviar",
        tone="warn",
        details=("El ángulo 2 no tiene foto utilizable.",),
    )

    def _generate(*args: Any) -> OutcomeVM:
        calls.append(args)
        return outcome

    monkeypatch.setattr(module, "generate_variation_pieces", _generate)
    monkeypatch.setattr(module, "variation_set_detail", lambda *_: _set_vm())
    yielded = await _drain(VariationsState.generate_pieces.fn(state))
    assert calls == [(_TENANT_ID, _SET_ID, _USER_ID, None)]
    assert state.outcome_message == outcome.message and state.outcome_tone == "warn"
    assert state.outcome_details == list(outcome.details)
    assert not state.generating
    # something is still being made, so the gallery keeps polling
    assert len(yielded) == 1


async def test_generate_refuses_before_paying_when_nothing_is_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)
    state.set_id, state.pending_count = _SET_ID, 0
    calls: list[Any] = []
    monkeypatch.setattr(module, "generate_variation_pieces", lambda *a: calls.append(a))
    await _drain(VariationsState.generate_pieces.fn(state))
    assert calls == [] and state.error == "No queda ningún ángulo por generar."


async def test_a_second_generate_while_one_is_in_flight_sends_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)
    state.set_id, state.pending_count, state.generating = _SET_ID, 3, True
    calls: list[Any] = []
    monkeypatch.setattr(module, "generate_variation_pieces", lambda *a: calls.append(a))
    await _drain(VariationsState.generate_pieces.fn(state))
    assert calls == []


# ---------------------------------------------------------------------------
# 2. what counts as "still being made"


def test_only_a_piece_still_being_made_keeps_the_gallery_polling() -> None:
    assert any_in_flight([_angle(status="queued", draft_status="drafting")])
    assert any_in_flight([_angle(status="reserved", draft_status="")])
    # waiting for the operator, not for the provider
    assert not any_in_flight([_angle(status="queued", draft_status="generated")])
    # waiting for a retry
    assert not any_in_flight([_angle(status="failed", draft_status="failed")])
    assert not any_in_flight([_angle(status="approved", draft_status="approved")])
    assert not any_in_flight([])


# ---------------------------------------------------------------------------
# 3. the poll


async def test_the_poll_re_reads_and_stops_when_nothing_is_in_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)
    state.set_id = _SET_ID
    state.angles = [_angle()]
    reads: list[Any] = []
    landed = _angle(status="queued", draft_status="generated", can_approve=True)

    def _detail(*args: Any) -> SetVM:
        reads.append(args)
        return _set_vm(landed)

    monkeypatch.setattr(module, "variation_set_detail", _detail)
    await VariationsState.poll_set.fn(state)
    assert len(reads) == 1  # one read was enough: the piece had landed
    assert state.angles[0].can_approve and not state.in_flight


async def test_the_poll_gives_up_when_the_operator_left_the_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)
    state.set_id = ""
    calls: list[Any] = []
    monkeypatch.setattr(module, "variation_set_detail", lambda *a: calls.append(a))
    await VariationsState.poll_set.fn(state)
    assert calls == []


# ---------------------------------------------------------------------------
# 4 and 5. one angle at a time


async def test_retry_goes_through_the_service_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)
    state.set_id = _SET_ID
    retried: list[tuple[Any, ...]] = []
    monkeypatch.setattr(module, "retry_variation_angle", lambda *a: retried.append(a) or "draft-id")
    monkeypatch.setattr(module, "variation_set_detail", lambda *_: _set_vm())
    yielded = await _drain(VariationsState.retry_angle.fn(state, _ANGLE_ID))
    assert retried == [(_TENANT_ID, _ANGLE_ID, _USER_ID)]
    assert state.outcome_message == "Reintentando esa pieza." and state.busy_angle_id == ""
    assert len(yielded) == 1  # the piece is being made again: keep polling


async def test_a_refused_approval_shows_the_reason_and_re_reads_the_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.creative.angle_sets import AngleNotActionable

    state = _state(monkeypatch)
    state.set_id = _SET_ID
    state.angles = [_angle()]
    refusal = "El texto menciona $15.000, que no es el precio del catálogo ($18.000)."
    reads: list[Any] = []

    def _raise(*_: Any) -> None:
        raise AngleNotActionable(refusal)

    conflicted = _angle(failure_text=refusal, price_conflicts=("$15.000",))
    monkeypatch.setattr(module, "approve_variation_angle", _raise)
    monkeypatch.setattr(
        module, "variation_set_detail", lambda *a: reads.append(a) or _set_vm(conflicted)
    )
    await VariationsState.approve_angle.fn(state, _ANGLE_ID)
    assert state.error == refusal and state.busy_angle_id == ""
    assert len(reads) == 1 and state.angles[0].failure_text == refusal


async def test_an_approval_that_lands_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _state(monkeypatch)
    state.set_id = _SET_ID
    approved: list[tuple[Any, ...]] = []
    monkeypatch.setattr(module, "approve_variation_angle", lambda *a: approved.append(a))
    monkeypatch.setattr(
        module,
        "variation_set_detail",
        lambda *_: _set_vm(_angle(status="approved", draft_status="approved")),
    )
    await VariationsState.approve_angle.fn(state, _ANGLE_ID)
    assert approved == [(_TENANT_ID, _ANGLE_ID, _USER_ID)]
    assert state.outcome_message == "Pieza aprobada." and state.error == ""


async def test_regenerate_goes_through_the_service_and_resumes_the_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)
    state.set_id = _SET_ID
    regenerated: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        module, "regenerate_variation_angle", lambda *a: regenerated.append(a) or "draft-id"
    )
    monkeypatch.setattr(module, "variation_set_detail", lambda *_: _set_vm())
    yielded = await _drain(VariationsState.regenerate_angle.fn(state, _ANGLE_ID))
    assert regenerated == [(_TENANT_ID, _ANGLE_ID, _USER_ID)]
    assert state.outcome_message == "Generando otra toma de ese escenario."
    assert state.busy_angle_id == "" and len(yielded) == 1


async def test_a_refused_regeneration_shows_the_reason_and_pays_nothing_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.creative.angle_sets import AngleNotActionable

    state = _state(monkeypatch)
    state.set_id = _SET_ID
    refusal = "Solo se regenera una pieza que ya está lista para revisar."

    def _raise(*_: Any) -> None:
        raise AngleNotActionable(refusal)

    monkeypatch.setattr(module, "regenerate_variation_angle", _raise)
    yielded = await _drain(VariationsState.regenerate_angle.fn(state, _ANGLE_ID))
    assert state.error == refusal and state.busy_angle_id == "" and yielded == []


# ---------------------------------------------------------------------------
# 6. the lightbox and the scene editor


def _landed(**kw: Any) -> AngleVM:
    base: dict[str, Any] = {
        "draft_status": "generated",
        "draft_label": "Listo para revisar",
        "draft_tone": "warn",
        "preview_key": "uploads/t/p.jpg",
        "can_edit": True,
        "can_discard": True,
        "can_regenerate": True,
        "can_approve": True,
    }
    base.update(kw)
    return _angle(**base)


def test_the_lightbox_shows_the_states_own_preview_never_one_the_browser_passes() -> None:
    state = VariationsState()
    state.angles = [_landed(preview_url="/r2media/x", preview_key="")]
    state.open_lightbox("not-an-angle")
    assert not state.lightbox_open
    state.open_lightbox(_ANGLE_ID)
    assert state.lightbox_open and state.lightbox_url == "/r2media/x"
    assert state.lightbox_title == "1. En la mesa del almuerzo"
    state.set_lightbox_open(False)
    assert not state.lightbox_open and state.lightbox_url == ""
    # an angle without a piece opens nothing
    state.angles = [_angle(preview_key="", preview_url="")]
    state.open_lightbox(_ANGLE_ID)
    assert not state.lightbox_open


def test_the_editor_opens_with_the_angles_words_and_only_when_it_may_edit() -> None:
    state = VariationsState()
    state.angles = [_landed(can_edit=False)]
    state.open_editor(_ANGLE_ID)
    assert not state.editor_open
    state.angles = [_landed()]
    state.open_editor(_ANGLE_ID)
    assert state.editor_open and state.editor_scene == "Mesa de madera"
    assert state.editor_composition == "Plano cenital" and state.editor_can_regenerate
    state.set_editor_open(False)
    assert not state.editor_open and state.editor_scene == ""


async def test_saving_the_scene_edits_through_the_service_and_closes_the_editor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)
    state.set_id = _SET_ID
    state.angles = [_landed()]
    state.open_editor(_ANGLE_ID)
    state.set_editor_scene("  Barra del local,\n plancha encendida ")
    state.set_editor_composition("Plano frontal")
    edits: list[tuple[Any, ...]] = []
    monkeypatch.setattr(module, "edit_variation_angle", lambda *a: edits.append(a))
    monkeypatch.setattr(
        module,
        "variation_set_detail",
        lambda *_: _set_vm(_landed(scene="Barra del local, plancha encendida")),
    )
    await VariationsState.save_edit.fn(state)
    assert edits == [(_TENANT_ID, _ANGLE_ID, "Barra del local, plancha encendida", "Plano frontal")]
    assert not state.editor_open and not state.saving
    assert state.angles[0].scene == "Barra del local, plancha encendida"
    assert state.outcome_tone == "ok"


async def test_an_empty_scene_is_refused_before_any_call(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _state(monkeypatch)
    state.set_id = _SET_ID
    state.angles = [_landed()]
    state.open_editor(_ANGLE_ID)
    state.set_editor_scene("   ")
    calls: list[Any] = []
    monkeypatch.setattr(module, "edit_variation_angle", lambda *a: calls.append(a))
    await VariationsState.save_edit.fn(state)
    assert calls == [] and state.error == "Escribe la escena antes de guardar."
    assert state.editor_open  # still open, with the words to fix


async def test_save_and_regenerate_edits_first_then_asks_for_another_take(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)
    state.set_id = _SET_ID
    state.angles = [_landed()]
    state.open_editor(_ANGLE_ID)
    state.set_editor_scene("Otra escena")
    monkeypatch.setattr(module, "edit_variation_angle", lambda *a: None)
    monkeypatch.setattr(module, "variation_set_detail", lambda *_: _set_vm(_landed()))
    yielded = await _drain(VariationsState.save_edit_and_regenerate.fn(state))
    assert len(yielded) == 1 and not state.editor_open


# ---------------------------------------------------------------------------
# 7. reopening a set


async def test_reopening_a_set_loads_it_and_resumes_the_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)
    monkeypatch.setattr(module, "variation_set_detail", lambda *_: _set_vm())
    yielded = await _drain(VariationsState.open_set.fn(state, _SET_ID))
    assert state.set_id == _SET_ID and state.product_name == "Shawarma mixto"
    assert state.has_set and len(yielded) == 1


async def test_the_set_list_is_read_with_the_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _state(monkeypatch)
    summary = SetSummaryVM(
        id=_SET_ID,
        product_name="Shawarma mixto",
        preset_key="escena_producto",
        count=10,
        status="completed",
        status_label="Piezas listas",
        status_tone="ok",
        created_label="21/10 14:05",
    )
    monkeypatch.setattr(module, "catalog_products", lambda *_: ({"id": "1", "name": "x"},))
    monkeypatch.setattr(module, "list_variation_sets", lambda *_: (summary,))
    await VariationsState.load.fn(state)
    assert state.has_sets and state.sets[0].status_label == "Piezas listas"


async def test_a_failing_set_list_does_not_break_the_picker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)

    def _raise(*_: Any) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(module, "catalog_products", lambda *_: ({"id": "1", "name": "x"},))
    monkeypatch.setattr(module, "list_variation_sets", _raise)
    await VariationsState.load.fn(state)
    assert state.has_products and not state.has_sets and state.error == ""

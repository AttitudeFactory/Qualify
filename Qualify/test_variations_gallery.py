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
from .creative_vm import NO_VIDEO_DRAFT, video_draft_vm
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
        "saved": False,
        "can_save": False,
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
    # the outcome is also a toast; something is still being made, so the poll follows
    assert len(yielded) == 2 and "warning" in str(yielded[0])


async def test_an_outcome_with_nothing_wrong_is_a_toast_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Request 2026-10-22: «10 en generación» sat on the page for good. What went
    right is a toast; only failures stay, with their details."""
    state = _state(monkeypatch)
    state.set_id, state.pending_count = _SET_ID, 2
    outcome = OutcomeVM(
        queued=2, failed=0, unresolved=0, message="2 en generación", tone="ok", details=()
    )
    monkeypatch.setattr(module, "generate_variation_pieces", lambda *_: outcome)
    monkeypatch.setattr(module, "variation_set_detail", lambda *_: _set_vm())
    yielded = await _drain(VariationsState.generate_pieces.fn(state))
    assert state.outcome_message == "" and state.outcome_details == []
    assert "success" in str(yielded[0]) and "2 en generación" in str(yielded[0])


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
    assert state.busy_angle_id == "" and state.outcome_message == ""
    # said in a toast, then the piece is being made again: keep polling
    assert len(yielded) == 2 and "Reintentando esa pieza." in str(yielded[0])


async def test_discard_rest_discards_every_open_angle_and_keeps_the_approved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Request 2026-10-22: «elijo 2 o 3 y las demás no las quiero» — one gesture."""
    state = _state(monkeypatch)
    state.set_id = _SET_ID
    kept = _angle(id="a-kept", status="approved", draft_status="approved", can_discard=False)
    open_1 = _angle(id="a-1", status="queued", draft_status="generated", can_discard=True)
    open_2 = _angle(id="a-2", status="proposed", draft_status="", draft_id="", can_discard=True)
    gone = _angle(id="a-3", status="discarded", can_discard=False, can_restore=True)
    # one put aside is never swept (review 2026-10-22: deleting is final here)
    aside = _angle(
        id="a-4", status="proposed", draft_status="", draft_id="", can_discard=True, saved=True
    )
    state.angles = [kept, open_1, open_2, gone, aside]
    assert state.discardable_count == 2 and "(2)" in state.discard_rest_label
    discarded: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        module, "discard_variation_angles", lambda *a: discarded.append(a) or len(a[1])
    )
    monkeypatch.setattr(module, "variation_set_detail", lambda *_: _set_vm(kept))
    yielded = await _drain(VariationsState.discard_rest.fn(state))
    assert discarded == [(_TENANT_ID, ("a-1", "a-2"), _USER_ID)]
    assert state.busy_angle_id == "" and len(yielded) == 1
    assert "2 propuestas eliminadas" in str(yielded[0]) and "success" in str(yielded[0])


def test_deleted_angles_never_show_and_saved_ones_only_when_asked() -> None:
    """Request 2026-10-22: «eliminar es eliminar» — a deleted proposal never shows again;
    one put aside («guardar para después») shows only behind «Ver guardadas»."""
    state = VariationsState()
    kept = _angle(id="a-1", status="queued", draft_status="generated", can_save=True)
    gone = _angle(id="a-2", status="discarded")
    aside = _angle(id="a-3", status="proposed", draft_status="", draft_id="", saved=True)
    state.angles = [kept, gone, aside]
    assert [a.id for a in state.visible_angles] == ["a-1"]
    assert state.saved_count == 1 and state.saved_toggle_label == "Ver guardadas (1)"
    assert state.savable_count == 1 and state.save_rest_label == "Guardar las demás (1)"
    state.toggle_saved()
    assert [a.id for a in state.visible_angles] == ["a-1", "a-3"]  # never a-2
    assert state.saved_toggle_label == "Ocultar guardadas"
    state._clear_set()
    assert not state.show_saved


async def test_save_rest_puts_every_open_angle_aside(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _state(monkeypatch)
    state.set_id = _SET_ID
    state.angles = [
        _angle(id="a-1", status="approved", draft_status="approved"),
        _angle(id="a-2", status="queued", draft_status="generated", can_save=True),
        _angle(id="a-3", status="proposed", draft_status="", draft_id="", can_save=True),
    ]
    saved: list[tuple[Any, ...]] = []
    monkeypatch.setattr(module, "save_variation_angles", lambda *a: saved.append(a) or len(a[1]))
    monkeypatch.setattr(module, "variation_set_detail", lambda *_: _set_vm())
    yielded = await _drain(VariationsState.save_rest.fn(state))
    assert saved == [(_TENANT_ID, ("a-2", "a-3"))]
    assert len(yielded) == 1 and "2 propuestas guardadas" in str(yielded[0])


async def test_saving_one_angle_goes_through_the_service_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)
    state.set_id = _SET_ID
    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(module, "save_variation_angle", lambda *a: calls.append(a))
    monkeypatch.setattr(module, "variation_set_detail", lambda *_: _set_vm())
    yielded = await _drain(VariationsState.save_angle.fn(state, _ANGLE_ID))
    assert calls == [(_TENANT_ID, _ANGLE_ID, True)] and "Guardada" in str(yielded[0])
    yielded = await _drain(VariationsState.unsave_angle.fn(state, _ANGLE_ID))
    assert calls[-1] == (_TENANT_ID, _ANGLE_ID, False) and "revisión" in str(yielded[0])


async def test_deleting_the_last_proposal_leaves_the_group_and_the_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Request 2026-10-22: a group with nothing standing is not kept around."""
    state = _state(monkeypatch)
    state.set_id, state.product_id = _SET_ID, "p-1"
    state.angles = [_angle(id="a-1", status="queued", draft_status="generated", can_discard=True)]
    emptied = SetVM(
        id=_SET_ID,
        product_name="Shawarma mixto",
        preset_key="escena_producto",
        status="completed",
        status_label="Piezas listas",
        status_tone="ok",
        price_label="$18.000",
        price_missing=False,
        price_note="",
        failure_text="",
        campaign_id="",
        pending_count=0,
        kept_count=0,
        angles=(_angle(id="a-1", status="discarded"),),
    )
    monkeypatch.setattr(module, "discard_variation_angles", lambda *a: len(a[1]))
    monkeypatch.setattr(module, "variation_set_detail", lambda *_: emptied)
    monkeypatch.setattr(module, "list_variation_sets", lambda *_: ())
    yielded = await _drain(VariationsState.discard_rest.fn(state))
    assert state.set_id == "" and state.sets == []
    assert len(yielded) == 2 and "ya no aparece" in str(yielded[1])


async def test_deleting_a_group_takes_it_off_the_list_and_closes_it_if_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Request 2026-10-22: a group can be deleted from the list (after a dialog)."""
    state = _state(monkeypatch)
    state.set_id = _SET_ID
    archived: list[tuple[Any, ...]] = []
    monkeypatch.setattr(module, "archive_variation_set", lambda *a: archived.append(a) or 3)
    monkeypatch.setattr(module, "list_variation_sets", lambda *_: ())
    state.ask_archive_set(_SET_ID, "Shawarma mixto")
    assert state.archive_set_name == "Shawarma mixto"
    yielded = await _drain(VariationsState.confirm_archive_set.fn(state))
    assert archived == [(_TENANT_ID, _SET_ID, _USER_ID)]
    assert state.set_id == "" and state.sets == [] and state.archive_set_id == ""
    assert len(yielded) == 1 and "Grupo eliminado" in str(yielded[0])


async def test_closing_a_set_goes_back_to_the_list_with_the_product_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)
    state.set_id, state.product_id = _SET_ID, "p-1"
    state.angles = [_angle()]
    summary = SetSummaryVM(
        id=_SET_ID,
        product_name="Shawarma mixto",
        preset_key="escena_producto",
        count=10,
        status="completed",
        status_label="Piezas listas",
        status_tone="ok",
        created_label="22/10 02:47",
    )
    monkeypatch.setattr(module, "list_variation_sets", lambda *_: (summary,))
    await VariationsState.close_set.fn(state)
    assert state.set_id == "" and state.angles == [] and state.product_id == "p-1"
    assert state.sets == [summary]


async def test_discard_rest_with_nothing_open_only_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(monkeypatch)
    state.set_id = _SET_ID
    state.angles = [_angle(status="approved", draft_status="approved", can_discard=False)]
    calls: list[Any] = []
    monkeypatch.setattr(module, "discard_variation_angles", lambda *a: calls.append(a))
    yielded = await _drain(VariationsState.discard_rest.fn(state))
    assert calls == [] and len(yielded) == 1 and "info" in str(yielded[0])


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
    assert await _drain(VariationsState.approve_angle.fn(state, _ANGLE_ID)) == []
    assert state.error == refusal and state.busy_angle_id == ""
    assert len(reads) == 1 and state.angles[0].failure_text == refusal


async def test_an_approval_that_lands_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _state(monkeypatch)
    state.set_id = _SET_ID
    approved: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        module,
        "approve_variation_angle",
        lambda *a: approved.append(a) or NO_VIDEO_DRAFT,
    )
    monkeypatch.setattr(
        module,
        "variation_set_detail",
        lambda *_: _set_vm(_angle(status="approved", draft_status="approved")),
    )
    yielded = await _drain(VariationsState.approve_angle.fn(state, _ANGLE_ID))
    assert approved == [(_TENANT_ID, _ANGLE_ID, _USER_ID)]
    assert state.error == "" and state.outcome_message == ""
    assert len(yielded) == 1 and "Pieza aprobada." in str(yielded[0])


async def test_an_approval_whose_final_is_rendering_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """m-24820142: approving a piece with a 480p draft video orders its 1080p final."""
    state = _state(monkeypatch)
    state.set_id = _SET_ID
    monkeypatch.setattr(
        module, "approve_variation_angle", lambda *_: video_draft_vm("rendering", None)
    )
    monkeypatch.setattr(
        module,
        "variation_set_detail",
        lambda *_: _set_vm(_angle(status="approved", draft_status="approved")),
    )
    yielded = await _drain(VariationsState.approve_angle.fn(state, _ANGLE_ID))
    assert len(yielded) == 1 and "video final a 1080p" in str(yielded[0])


async def test_an_approval_whose_final_could_not_be_ordered_never_says_approved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review round 3: the final could not be ordered (the piece offers «Reintentar»):
    the toast says so — the shared `approval_notice` — instead of «Pieza aprobada.»."""
    state = _state(monkeypatch)
    state.set_id = _SET_ID
    failed = video_draft_vm("failed", None, "El video final no se llegó a pedir.", approved=True)
    monkeypatch.setattr(module, "approve_variation_angle", lambda *_: failed)
    monkeypatch.setattr(
        module,
        "variation_set_detail",
        lambda *_: _set_vm(_angle(status="approved", draft_status="approved")),
    )
    yielded = await _drain(VariationsState.approve_angle.fn(state, _ANGLE_ID))
    assert len(yielded) == 1 and "reintentarlo" in str(yielded[0])
    assert "Pieza aprobada." not in str(yielded[0])


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
    assert state.busy_angle_id == "" and state.outcome_message == ""
    assert len(yielded) == 2 and "otra toma" in str(yielded[0])


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
    state.set_editor_hook("  Sabor de barrio ")
    state.set_editor_cta("Pide hoy")
    edits: list[tuple[Any, ...]] = []
    monkeypatch.setattr(module, "edit_variation_angle", lambda *a, **kw: edits.append((a, kw)))
    monkeypatch.setattr(
        module,
        "variation_set_detail",
        lambda *_: _set_vm(_landed(scene="Barra del local, plancha encendida")),
    )
    yielded = await _drain(VariationsState.save_edit.fn(state))
    # every field Claude proposed travels (request 2026-10-22), whitespace folded
    assert edits == [
        (
            (_TENANT_ID, _ANGLE_ID, "Barra del local, plancha encendida", "Plano frontal"),
            {
                "title": "En la mesa del almuerzo",
                "hook": "Sabor de barrio",
                "cta": "Pide hoy",
                "rationale": "El momento de consumo real",
            },
        )
    ]
    assert not state.editor_open and not state.saving
    assert state.angles[0].scene == "Barra del local, plancha encendida"
    assert len(yielded) == 1 and "Propuesta guardada" in str(yielded[0])


async def test_an_empty_scene_is_refused_before_any_call(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _state(monkeypatch)
    state.set_id = _SET_ID
    state.angles = [_landed()]
    state.open_editor(_ANGLE_ID)
    state.set_editor_scene("   ")
    calls: list[Any] = []
    monkeypatch.setattr(module, "edit_variation_angle", lambda *a: calls.append(a))
    assert await _drain(VariationsState.save_edit.fn(state)) == []  # nothing to confirm
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
    monkeypatch.setattr(module, "edit_variation_angle", lambda *a, **kw: None)
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

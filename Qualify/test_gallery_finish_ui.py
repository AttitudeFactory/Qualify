"""m-24820842 (live test 2026-11-03, draft 320257e3): a failed gallery that kept the
slides it finished offers «Crear las que faltan» — on «Crear pieza»'s result and on the
piece's page — and the reason it cannot, in the owner's words."""

from __future__ import annotations

import json
from uuid import UUID, uuid4

from qualify_api.creative.fsm import InvalidTransition
from qualify_api.creative.service import NOTHING_TO_FINISH_TEXT, NothingToFinish

from . import creative_state as module
from .creative_pages import FINISH_GALLERY_LABEL, _generation_failed_panel
from .creative_state import CreativeState
from .creative_vm import DraftVM

TENANT = UUID("a0000000-0000-4000-8000-000000000001")


def _js(text: str) -> str:
    return json.dumps(text)[1:-1]


def test_both_failure_views_offer_the_button() -> None:
    from .content_generator import _failed

    generated = str(_failed())
    assert _js(FINISH_GALLERY_LABEL) in generated
    assert "finish_gallery_generated" in generated and "can_finish_gallery" in generated
    page = str(_generation_failed_panel())
    assert _js(FINISH_GALLERY_LABEL) in page
    assert "finish_gallery_current" in page and "can_finish_gallery" in page


def test_the_vm_offers_nothing_by_default() -> None:
    assert DraftVM.__dataclass_fields__["can_finish_gallery"].default is False


async def _finish(monkeypatch, outcome: object) -> tuple[CreativeState, object]:  # noqa: ANN001
    async def session_ids(self: CreativeState) -> tuple[UUID, UUID, UUID]:
        return (TENANT, TENANT, TENANT)

    async def refresh(self: CreativeState, tenant_id: UUID, brand_id: UUID) -> None:
        return None

    def finish(tenant_id: UUID, draft_id: UUID, user_id: UUID) -> object:
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(CreativeState, "_session_ids", session_ids)
    monkeypatch.setattr(CreativeState, "_refresh_creations", refresh)
    monkeypatch.setattr(module, "finish_gallery", finish)
    state = CreativeState()
    return state, await state._finish_gallery(uuid4())


async def test_nothing_to_finish_is_said_as_written(monkeypatch) -> None:  # noqa: ANN001
    state, vm = await _finish(monkeypatch, NothingToFinish())
    assert vm is None and state.action_error == NOTHING_TO_FINISH_TEXT


async def test_a_gallery_already_moving_on_is_explained(monkeypatch) -> None:  # noqa: ANN001
    state, vm = await _finish(monkeypatch, InvalidTransition("generated"))
    assert vm is None and state.action_error.startswith("Esta galería ya se está creando")


async def test_the_retried_piece_is_returned(monkeypatch) -> None:  # noqa: ANN001
    made = DraftVM(
        draft_id=str(uuid4()),
        status="drafting",
        status_label="Creando",
        status_tone="gray",
        is_drafting=True,
    )
    state, vm = await _finish(monkeypatch, made)
    assert vm is made and state.action_error == ""

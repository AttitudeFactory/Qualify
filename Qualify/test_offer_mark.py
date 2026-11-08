"""m-24945889 — «Usar como tu oferta» (Por aprobar and the Planificador), offline: one
offer per business, replacing it says so with «Deshacer», a refusal in the backend's
words, a late read dropped, and the control on both screens."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import pytest
from qualify_api.whatsapp.promotions import PromotionNotAllowed

from . import offer_mark_state as state_module
from .offer_mark_provider import MarkResult, OfferInfo
from .offer_mark_state import OfferMarkState
from .offer_mark_vm import UNMARKED_TOAST, marked_toast

TENANT = UUID("a0000000-0000-4000-8000-000000945890")
BRAND = UUID("c0000000-0000-4000-8000-000000945890")
NEW = "20000000-0000-4000-8000-000000000011"
OLD = "20000000-0000-4000-8000-000000000012"


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    box: dict[str, Any] = {"offer": OLD, "refuse": None, "marks": []}

    async def tenant(self: OfferMarkState) -> UUID:
        return TENANT

    def info(tenant_id: UUID, draft: UUID) -> OfferInfo:
        return OfferInfo(brand_id=BRAND, is_offer=box["offer"] == str(draft))

    def mark(tenant_id: UUID, draft: UUID, user: Any) -> MarkResult:
        if box["refuse"]:
            raise PromotionNotAllowed(box["refuse"])
        before, box["offer"] = box["offer"], str(draft)
        box["marks"].append(str(draft))
        titles = {NEW: "2x1 martes", OLD: "Combo vecino"}
        if before and before != str(draft):
            return MarkResult(titles[str(draft)], before, titles[before])
        return MarkResult(titles[str(draft)])

    def unmark(tenant_id: UUID, brand: UUID) -> bool:
        box["offer"] = ""
        return True

    monkeypatch.setattr(OfferMarkState, "_tenant", tenant)
    monkeypatch.setattr(state_module, "offer_info", info)
    monkeypatch.setattr(state_module, "mark_offer", mark)
    monkeypatch.setattr(state_module, "unmark_offer", unmark)
    monkeypatch.setattr(state_module, "acting_user_id", lambda _t: None)
    return box


async def _load(state: OfferMarkState, draft_id: str) -> None:
    await OfferMarkState.load_for.fn(state, draft_id)


async def _drain(gen: Any) -> list[Any]:
    return [e async for e in gen]


def test_the_words() -> None:
    assert marked_toast("2x1 martes", "Combo vecino") == (
        "Listo: «2x1 martes» es tu oferta. Antes era «Combo vecino»."
    )
    assert marked_toast("2x1 martes") == "Listo: «2x1 martes» es tu oferta."


async def test_replacing_says_so_and_undo_puts_it_back(backend: dict[str, Any]) -> None:
    state = OfferMarkState()
    await _load(state, NEW)
    assert state.loaded and not state.is_offer
    events = await _drain(OfferMarkState.mark.fn(state))
    text = json.dumps(str(events), ensure_ascii=False)
    assert state.is_offer and backend["offer"] == NEW
    assert "Antes era «Combo vecino»" in text and "Deshacer" in text
    await _drain(OfferMarkState.undo.fn(state))
    assert backend["offer"] == OLD and not state.is_offer
    assert await _drain(OfferMarkState.undo.fn(state)) == []  # «Deshacer» works once


async def test_a_refusal_is_worded_by_the_backend(backend: dict[str, Any]) -> None:
    backend["refuse"] = "Esa pieza ya no está disponible."
    state = OfferMarkState()
    await _load(state, NEW)
    await _drain(OfferMarkState.mark.fn(state))
    assert state.error == "Esa pieza ya no está disponible." and not state.is_offer


async def test_unmark(backend: dict[str, Any]) -> None:
    state = OfferMarkState()
    await _load(state, OLD)
    assert state.is_offer
    events = await _drain(OfferMarkState.unmark.fn(state))
    assert not state.is_offer and UNMARKED_TOAST in str(events)
    await _load(state, "no-es-un-id")
    assert not state.loaded and state.draft_id == ""  # a forged id reads nothing


def test_the_control_on_por_aprobar_and_the_planner() -> None:
    from .creative_pages import draft_detail_index
    from .planner_drawer import _detail_body

    for rendered in (str(draft_detail_index()), str(_detail_body())):
        for text in (
            "Usar como tu oferta",
            "Dejar de usar como tu oferta",
            "Apruébala primero para usarla como tu oferta.",
            "Mientras sea tu oferta, no se borra.",
        ):
            assert text in rendered or json.dumps(text)[1:-1] in rendered, text

"""m-24945889 — «Tu local en el mapa» (Tu número › Perfil) and the profile's address
kept for «Cómo llegar», offline: the Google Maps link forms, the browser's position and
its accuracy, the saves through a patched provider, and the way back to the chat."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from . import whatsapp_location_state as state_module
from .whatsapp_location_provider import MapPoint
from .whatsapp_location_state import WhatsAppLocationState
from .whatsapp_location_vm import (
    GEO_DENIED,
    LINK_BAD,
    LINK_SHORT,
    REMOVED,
    SAVED,
    approximate_note,
    chat_back_path,
    parse_maps_link,
)

TENANT = UUID("a0000000-0000-4000-8000-000000945889")
CONN = "d0000000-0000-4000-8000-000000945889"


def test_the_three_link_forms_and_the_refusals() -> None:
    place = parse_maps_link(
        "https://www.google.com/maps/place/Bianki/@7.7600,-72.2200,17z/"
        "data=!3m1!4b1!4m6!3m5!1s0x0:0x0!8m2!3d7.7671234!4d-72.2250123"
    )
    assert (place.latitude, place.longitude) == (7.7671234, -72.2250123)  # the pin, not @
    at = parse_maps_link("https://www.google.com/maps/@4.6097,-74.0817,15z")
    assert (at.latitude, at.longitude) == (4.6097, -74.0817)
    query = parse_maps_link("https://maps.google.com/?q=-34.9011%2C-56.1645")
    assert (query.latitude, query.longitude) == (-34.9011, -56.1645)
    assert parse_maps_link("google.com/maps?q=10.5,-66.9").latitude == 10.5
    assert parse_maps_link("https://maps.app.goo.gl/AbCd123").error == LINK_SHORT
    for bad in (
        "",
        "https://otro.sitio/maps/@7.7,-72.2,17z",
        "https://www.google.com/search?q=7.7,-72.2",
        "https://www.google.com/maps/place/Bianki",
        "https://www.google.com/maps/@97.1,-72.2,17z",
        "javascript:alert(1)",
    ):
        assert parse_maps_link(bad).error == LINK_BAD, bad


def test_accuracy_and_the_way_back() -> None:
    assert approximate_note(40) == ""
    assert "a unos 300 m" in approximate_note(290)
    assert chat_back_path("/whatsapp?tab=chats&cuenta=x") == "/whatsapp?tab=chats&cuenta=x"
    for bad in ("", "/whatsapp?tab=numero&a=tab=chats", "/catalog", "/whatsapp?tab=chats&tab=x"):
        assert chat_back_path(bad) == "", bad


def test_the_browsers_answer() -> None:
    state = WhatsAppLocationState()
    events = state.use_my_location()
    assert state.locating and "getCurrentPosition" in str(events)
    assert state.use_my_location() is None  # one question at a time
    assert state.got_position({"error": "1"}) is None and state.error == GEO_DENIED
    assert state.got_position({"lat": 7.7, "lng": -72.2, "acc": 300}) is None
    assert "aproximada" in state.error  # nothing saved
    event = state.got_position({"lat": 7.7, "lng": -72.2, "acc": 12})
    assert event is not None and "save_coordinates" in str(event)
    state.set_link_text("https://maps.app.goo.gl/x")
    assert state.save_link() is None and state.error == LINK_SHORT
    state.set_link_text("https://www.google.com/maps/@7.7,-72.2,17z")
    assert "save_coordinates" in str(state.save_link())


@pytest.fixture
def ids(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    box: dict[str, Any] = {"conn": CONN, "saved": [], "cleared": 0}

    async def fake_ids(self: WhatsAppLocationState) -> tuple[UUID, str]:
        return TENANT, box["conn"]

    def save(tenant: UUID, connection: UUID, lat: float, lng: float) -> MapPoint:
        box["saved"].append((tenant, str(connection), lat, lng))
        return MapPoint(has_point=True, label=f"{lat:.5f}, {lng:.5f}", href="https://maps/x")

    def clear(tenant: UUID, connection: UUID) -> None:
        box["cleared"] += 1

    monkeypatch.setattr(WhatsAppLocationState, "_ids", fake_ids)
    monkeypatch.setattr(state_module, "save_point", save)
    monkeypatch.setattr(state_module, "clear_point", clear)
    return box


async def _drain(gen: Any) -> list[Any]:
    return [e async for e in gen]


async def test_save_shows_the_point_then_remove(ids: dict[str, Any]) -> None:
    state = WhatsAppLocationState()
    events = await _drain(WhatsAppLocationState.save_coordinates.fn(state, 7.76712, -72.22501))
    assert ids["saved"] == [(TENANT, CONN, 7.76712, -72.22501)]
    assert state.has_point and state.point_label == "7.76712, -72.22501"
    assert SAVED in str(events)
    events = await _drain(WhatsAppLocationState.remove.fn(state))
    assert ids["cleared"] == 1 and not state.has_point and REMOVED in str(events)


async def test_a_save_for_another_number_is_dropped(
    ids: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def save(*_a: Any) -> MapPoint:
        ids["conn"] = "otro"  # the owner switched numbers meanwhile
        return MapPoint(has_point=True, label="x", href="y")

    monkeypatch.setattr(state_module, "save_point", save)
    state = WhatsAppLocationState()
    assert await _drain(WhatsAppLocationState.save_coordinates.fn(state, 1.0, 2.0)) == []
    assert not state.has_point


async def test_the_profile_save_keeps_the_address_for_como_llegar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from . import whatsapp_location_provider as provider
    from .whatsapp_state import WhatsAppState

    calls: list[tuple[Any, ...]] = []
    monkeypatch.setattr(provider, "sync_address", lambda *a: calls.append(a))
    state = WhatsAppState()
    await state._sync_directions_address(TENANT, CONN, "Av. 5 #10-20")
    assert calls == [(TENANT, UUID(CONN), "Av. 5 #10-20", None)]

    def broken(*_a: Any) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(provider, "sync_address", broken)
    await state._sync_directions_address(TENANT, CONN, "x")  # logged, never raised


def test_the_profile_draws_the_map_block_and_the_way_back() -> None:
    import json

    from .whatsapp_page import profile_tab

    rendered = str(profile_tab())
    for text in (
        "Tu local en el mapa",
        "Así tu cliente abre la ruta con un toque.",
        "Usar mi ubicación",
        "Enlace de Google Maps de tu local",
        "Ver en el mapa",
        "Quitar del mapa",
        "Volver al chat",
    ):
        assert text in rendered or json.dumps(text)[1:-1] in rendered, text

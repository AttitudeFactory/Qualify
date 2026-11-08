"""m-24945889 — «Tu local en el mapa» (Tu número › Perfil) and the profile's address
kept for «Cómo llegar», offline: the Google Maps link forms, the browser's position and
its accuracy, the saves through a patched provider, and the way back to the chat."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from . import whatsapp_location_state as state_module
from .whatsapp_location_provider import LinkPoint, MapPoint
from .whatsapp_location_state import WhatsAppLocationState
from .whatsapp_location_vm import (
    GEO_DENIED,
    LINK_BAD,
    LINK_NO_POINT,
    LINK_NOT_MAPS,
    LINK_UNREACHABLE,
    REMOVED,
    SAVED,
    approximate_note,
    position_point,
)

TENANT = UUID("a0000000-0000-4000-8000-000000945889")
CONN = "d0000000-0000-4000-8000-000000945889"


def test_accuracy_and_the_way_back() -> None:
    assert approximate_note(40) == ""
    assert "a unos 300 m" in approximate_note(290)
    from .whatsapp_payments_state import chat_return_path  # #542's one rule

    good = "/whatsapp?tab=chats&cuenta=x"
    assert chat_return_path({"volver": good}) == good
    for bad in ("", "/whatsapp?tab=numero&a=tab=chats", "/catalog", "/whatsapp?tab=chats&tab=x"):
        assert chat_return_path({"volver": bad}) == "", bad


def test_the_browsers_answer() -> None:
    assert position_point({"error": "1"}) == GEO_DENIED
    assert position_point({"lat": "x", "lng": 1}) == GEO_DENIED
    assert position_point({"lat": 97, "lng": 1, "acc": 5}) == GEO_DENIED
    assert "aproximada" in str(position_point({"lat": 7.7, "lng": -72.2, "acc": 300}))
    assert position_point({"lat": 7.7, "lng": -72.2, "acc": 12}) == (7.7, -72.2)
    # the save is not an event: nothing from the browser reaches it unchecked
    assert "save_coordinates" not in WhatsAppLocationState.event_handlers
    assert "_save" not in WhatsAppLocationState.event_handlers


@pytest.fixture
def ids(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    box: dict[str, Any] = {"conn": CONN, "saved": [], "cleared": 0}

    async def fake_ids(self: WhatsAppLocationState) -> tuple[UUID, str]:
        return TENANT, box["conn"]

    def save(
        tenant: UUID, connection: UUID, lat: float, lng: float, name: str | None = None
    ) -> MapPoint:
        box["saved"].append((tenant, str(connection), lat, lng, name))
        return MapPoint(has_point=True, label=f"{lat:.5f}, {lng:.5f}", href="https://maps/x")

    def clear(tenant: UUID, connection: UUID) -> None:
        box["cleared"] += 1

    monkeypatch.setattr(WhatsAppLocationState, "_ids", fake_ids)
    monkeypatch.setattr(state_module, "save_point", save)
    monkeypatch.setattr(state_module, "clear_point", clear)
    return box


async def _drain(gen: Any) -> list[Any]:
    return [e async for e in gen]


async def test_the_position_saves_then_remove(ids: dict[str, Any]) -> None:
    state = WhatsAppLocationState()
    events = await state.use_my_location()
    assert state.locating and "getCurrentPosition" in str(events)
    assert await state.use_my_location() is None  # one question at a time
    far = {"lat": 7.7, "lng": -72.2, "acc": 400}
    assert await _drain(WhatsAppLocationState.got_position.fn(state, far)) == []
    assert ids["saved"] == [] and "aproximada" in state.error
    near = {"lat": 7.76712, "lng": -72.22501, "acc": 10}
    await state.use_my_location()
    events = await _drain(WhatsAppLocationState.got_position.fn(state, near))
    assert ids["saved"] == [(TENANT, CONN, 7.76712, -72.22501, None)]
    assert state.has_point and state.point_label == "7.76712, -72.22501"
    assert SAVED in str(events)
    events = await _drain(WhatsAppLocationState.remove.fn(state))
    assert ids["cleared"] == 1 and not state.has_point and REMOVED in str(events)


async def test_a_pasted_link_is_read_by_the_backend(
    ids: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The four reasons in the owner's words, then success with the place's name."""
    answers = {
        "a": LinkPoint(reason="not_a_maps_link"),
        "b": LinkPoint(reason="unsafe_redirect"),
        "c": LinkPoint(reason="no_point"),
        "d": LinkPoint(reason="unreachable"),
        "ok": LinkPoint(latitude=7.7671, longitude=-72.2250, name="Bianki"),
    }
    monkeypatch.setattr(state_module, "resolve_link", lambda text: answers[text])
    state = WhatsAppLocationState()
    for text, words in (
        ("a", LINK_NOT_MAPS),
        ("b", LINK_BAD),
        ("c", LINK_NO_POINT),
        ("d", LINK_UNREACHABLE),
    ):
        state.set_link_text(text)
        assert await _drain(WhatsAppLocationState.save_link.fn(state)) == []
        assert state.error == words and not state.reading and ids["saved"] == []
    assert "Compartir" in LINK_NOT_MAPS and "Compartir" in LINK_NO_POINT

    def broken(_text: str) -> LinkPoint:
        raise OSError("dns")

    monkeypatch.setattr(state_module, "resolve_link", broken)
    state.set_link_text("x")
    await _drain(WhatsAppLocationState.save_link.fn(state))
    assert state.error == LINK_UNREACHABLE

    monkeypatch.setattr(state_module, "resolve_link", lambda text: answers[text])
    state.set_link_text("ok")
    events = await _drain(WhatsAppLocationState.save_link.fn(state))
    assert ids["saved"] == [(TENANT, CONN, 7.7671, -72.2250, "Bianki")]
    assert SAVED in str(events) and state.link_text == ""


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


def test_the_address_is_written_only_when_it_changed(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from . import whatsapp_location_provider as provider

    writes: list[tuple[Any, ...]] = []
    stored = SimpleNamespace(address="Av. 5 #10-20", name="Bianki")

    class Service:
        def get_location(self, **_kw: Any) -> Any:
            return stored

        def set_address(self, **kw: Any) -> None:
            writes.append((kw["address"], kw["name"]))

    monkeypatch.setattr(provider, "_service", Service)
    assert provider.sync_address(TENANT, UUID(CONN), " Av. 5  #10-20 ", "Bianki") is False
    assert provider.sync_address(TENANT, UUID(CONN), "Av. 5 #10-20", None) is False
    assert writes == []
    assert provider.sync_address(TENANT, UUID(CONN), "Calle 9", "Bianki") is True
    assert provider.sync_address(TENANT, UUID(CONN), "", None) is True  # emptied: clears
    assert provider.sync_address(TENANT, UUID(CONN), "Av. 5 #10-20", "Otro") is True
    assert writes == [("Calle 9", "Bianki"), ("", None), ("Av. 5 #10-20", "Otro")]


def test_a_pin_links_to_the_map_only_from_its_numbers() -> None:
    from types import SimpleNamespace

    from .whatsapp_chats_vm import _pin_href

    assert _pin_href(SimpleNamespace(latitude=7.7671, longitude=-72.225)) == (
        "https://www.google.com/maps/search/?api=1&query=7.767100,-72.225000"
    )
    assert _pin_href(SimpleNamespace(text="https://evil.example")) == ""
    assert _pin_href(SimpleNamespace(latitude="7.7; alert(1)", longitude=1)) == ""
    assert _pin_href(SimpleNamespace(latitude=97, longitude=1)) == ""


async def test_switching_numbers_mid_read_saves_on_neither(
    ids: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-review of 0323fe04: the number is the one on screen when the owner STARTED."""

    def slow_resolve(_text: str) -> LinkPoint:
        ids["conn"] = "otro"  # the owner switched numbers during the network read
        return LinkPoint(latitude=7.7, longitude=-72.2)

    monkeypatch.setattr(state_module, "resolve_link", slow_resolve)
    state = WhatsAppLocationState()
    state.set_link_text("https://maps.app.goo.gl/x")
    assert await _drain(WhatsAppLocationState.save_link.fn(state)) == []
    assert ids["saved"] == [] and not state.has_point and not state.busy

    ids["conn"] = CONN
    await state.use_my_location()  # asked for CONN
    ids["conn"] = "otro"  # switched while the browser asked
    near = {"lat": 7.7, "lng": -72.2, "acc": 10}
    assert await _drain(WhatsAppLocationState.got_position.fn(state, near)) == []
    assert ids["saved"] == []
    # an answer nobody asked for («Usar mi ubicación» not tapped) saves nothing either
    assert await _drain(WhatsAppLocationState.got_position.fn(state, near)) == []
    assert ids["saved"] == []

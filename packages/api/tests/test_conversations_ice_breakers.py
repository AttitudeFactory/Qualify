"""`IceBreakerService` offline (m-24789472, PR 3): validation and its Spanish messages, the
lazy seed, the capability gate, and the publish / read-back / remove sequence — over the
in-memory repository with both the in-memory client and the REAL client on a mocked
transport.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from qualify_api.connections.resolver import _InjectedAuthClient
from qualify_api.conversations.choices import DEFAULT_ICE_BREAKERS
from qualify_api.conversations.contracts import SourceConnection
from qualify_api.conversations.ice_breakers import (
    DEFAULT_ITEMS,
    MAX_QUESTION_CHARS,
    MESSAGES,
    STATUS_LABELS,
    STATUSES,
    IceBreakerError,
    IceBreakerNotFound,
    IceBreakerRemoteError,
    IceBreakerService,
    IceBreakerUnavailable,
    MemoryIceBreakerRepository,
    clean_items,
)
from qualify_api.conversations.ice_breakers_client import (
    IceBreakerItem,
    IceBreakersApiError,
    InstagramIceBreakersClient,
    MemoryIceBreakersClient,
)
from qualify_api.conversations.models import ICE_BREAKER_STATUSES
from qualify_api.followups.capabilities import Capabilities, Capability

TENANT = UUID("a0000000-0000-4000-8000-000000000001")
OTHER = UUID("a0000000-0000-4000-8000-000000000002")
CONN = UUID("c0000000-0000-4000-8000-000000000001")
USER = UUID("d0000000-0000-4000-8000-000000000001")
TOKEN = "PAGE_TOKEN_SECRET_456"
SOURCE = SourceConnection(
    tenant_id=TENANT, connection_id=CONN, external_account_id="1784", linked_page_id="page-1"
)
ON = Capabilities.from_env({"QUALIFY_ICE_BREAKERS": "on"}).availability(Capability.ICE_BREAKERS)
OFF = Capabilities.from_env({}).availability(Capability.ICE_BREAKERS)


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


def _service(
    client: Any | None = None,
    *,
    availability=ON,
    connections: dict[UUID, SourceConnection] | None = None,
    degraded: list[UUID] | None = None,
) -> tuple[IceBreakerService, MemoryIceBreakerRepository, Any]:
    clock = Clock()
    repo = MemoryIceBreakerRepository(connections={CONN: TENANT}, clock=clock)
    client = client if client is not None else MemoryIceBreakersClient()
    sources = {CONN: SOURCE} if connections is None else connections

    def degrade(*, tenant_id: UUID, connection_id: UUID) -> None:
        if degraded is not None:
            degraded.append(connection_id)

    service = IceBreakerService(
        repository=repo,
        client=client,
        connections=lambda tenant_id, connection_id: (
            sources.get(connection_id) if tenant_id == TENANT else None
        ),
        availability=availability,
        degrade=degrade,
        clock=clock,
    )
    return service, repo, client


def test_statuses_match_the_migration() -> None:
    assert STATUSES == ICE_BREAKER_STATUSES == ("draft", "published", "failed", "removed")
    assert set(STATUS_LABELS) == set(STATUSES)


# --- validation --------------------------------------------------------------------------


def _items(*questions: str) -> list[dict[str, str]]:
    return [{"question": q, "payload": f"QF_P{i}"} for i, q in enumerate(questions)]


@pytest.mark.parametrize(
    ("items", "code", "index"),
    [
        (_items("a", "b", "c", "d", "e"), "too_many", None),
        (_items("¿Precio?", "  ¿precio?  "), "question_repeated", 1),
        (_items("¿Hola?", "x" * (MAX_QUESTION_CHARS + 1)), "question_too_long", 1),
        (_items("   ", "b"), "question_empty", 0),
        ([{"question": "¿Hola?", "payload": "QFB_HOLA"}], "payload_invalid", 0),
        ([{"question": "¿Hola?", "payload": "qf_hola"}], "payload_invalid", 0),
        ([{"question": "¿Hola?", "payload": "QF_" + "A" * 62}], "payload_invalid", 0),
        (
            [{"question": "a", "payload": "QF_A"}, {"question": "b", "payload": "QF_A"}],
            "payload_repeated",
            1,
        ),
    ],
)
def test_invalid_drafts_are_refused_with_a_code_and_a_spanish_message(
    items: list[dict[str, str]], code: str, index: int | None
) -> None:
    with pytest.raises(IceBreakerError) as caught:
        clean_items(items)
    assert caught.value.code == code
    assert caught.value.index == index
    assert str(caught.value) == MESSAGES[code]


def test_the_spanish_messages() -> None:
    assert MESSAGES["too_many"] == "Puedes tener hasta 4 preguntas iniciales."
    assert MESSAGES["question_too_long"] == "Cada pregunta puede tener hasta 80 caracteres."
    assert (
        MESSAGES["question_repeated"] == "Hay dos preguntas iguales. Cambia o quita una de ellas."
    )
    assert MESSAGES["question_empty"] == "Escribe la pregunta o quítala de la lista."
    assert MESSAGES["unavailable"] == (
        "Publicar las preguntas iniciales en Instagram no está disponible todavía."
    )
    for message in MESSAGES.values():
        assert "payload" not in message.lower() and "http" not in message.lower()


def test_clean_items_collapses_spaces_keeps_order_and_names_new_questions() -> None:
    cleaned = clean_items(
        [
            {"question": "  ¿Hacen   envíos?\n", "payload": ""},
            IceBreakerItem("¿Quieres consultar un precio?", "QF_PRECIO"),
            {"question": "¿Tienen domicilio?"},
        ]
    )
    assert cleaned == (
        IceBreakerItem("¿Hacen envíos?", "QF_PREGUNTA_1"),
        IceBreakerItem("¿Quieres consultar un precio?", "QF_PRECIO"),
        IceBreakerItem("¿Tienen domicilio?", "QF_PREGUNTA_2"),
    )
    # A generated payload never collides with one the draft already uses.
    again = clean_items([{"question": "a", "payload": "QF_PREGUNTA_1"}, {"question": "b"}])
    assert [i.payload for i in again] == ["QF_PREGUNTA_1", "QF_PREGUNTA_2"]
    assert clean_items([]) == ()
    with pytest.raises(IceBreakerError) as caught:
        clean_items([], require_one=True)
    assert caught.value.code == "nothing_to_publish"


def test_the_defaults_are_valid_and_the_tickets_four() -> None:
    assert clean_items(DEFAULT_ITEMS) == DEFAULT_ITEMS
    assert [i.payload for i in DEFAULT_ITEMS] == [ib.payload for ib in DEFAULT_ICE_BREAKERS]
    assert DEFAULT_ITEMS[0].question == "¿Qué producto te interesa?"


# --- local editing -----------------------------------------------------------------------


def test_get_config_seeds_once_and_editing_works_with_the_capability_off() -> None:
    service, repo, client = _service(availability=OFF)
    first = service.get_config(tenant_id=TENANT, connection_id=CONN)
    assert first.items == DEFAULT_ITEMS and first.is_default
    assert first.status == "draft" and first.status_label == "Sin publicar"
    assert first.has_unpublished_changes is True
    assert repo.ensure(tenant_id=TENANT, connection_id=CONN) is False

    saved = service.save_draft(
        tenant_id=TENANT,
        connection_id=CONN,
        items=[{"question": "¿Hacen envíos?", "payload": ""}],
        user_id=USER,
    )
    assert saved.items == (IceBreakerItem("¿Hacen envíos?", "QF_PREGUNTA_1"),)
    assert saved.updated_by_user_id == USER and not saved.is_default
    restored = service.restore_defaults(tenant_id=TENANT, connection_id=CONN, user_id=USER)
    assert restored.items == DEFAULT_ITEMS
    assert client.calls == []  # nothing reached Instagram


def test_another_tenant_sees_nothing() -> None:
    service, _, _ = _service()
    service.get_config(tenant_id=TENANT, connection_id=CONN)
    with pytest.raises(IceBreakerNotFound) as caught:
        service.get_config(tenant_id=OTHER, connection_id=CONN)
    assert caught.value.code == "connection_not_found"
    with pytest.raises(IceBreakerNotFound):
        service.save_draft(tenant_id=OTHER, connection_id=CONN, items=[], user_id=None)


# --- the capability ----------------------------------------------------------------------


async def test_with_the_capability_off_publish_and_remove_never_call_meta() -> None:
    service, repo, client = _service(availability=OFF)
    for action in (service.publish, service.remove):
        with pytest.raises(IceBreakerUnavailable) as caught:
            await action(tenant_id=TENANT, connection_id=CONN, user_id=USER)
        assert caught.value.code == "unavailable"
        assert str(caught.value) == MESSAGES["unavailable"]
        assert "QUALIFY_ICE_BREAKERS" in caught.value.reason
        assert caught.value.state_label == "Por verificar"
    assert client.calls == []
    assert service.availability.enabled is False
    # Reading back is not a change on Instagram: it works with the capability off.
    config = await service.refresh_remote(tenant_id=TENANT, connection_id=CONN)
    assert config.remote is not None and config.remote.is_empty
    assert client.calls == [("fetch", CONN)]


# --- publish / refresh / remove ----------------------------------------------------------


async def test_publish_sends_reads_back_and_records_who_and_what() -> None:
    service, _, client = _service()
    config = await service.publish(tenant_id=TENANT, connection_id=CONN, user_id=USER)
    assert client.calls == [("publish", CONN), ("fetch", CONN)]
    assert config.status == "published" and config.status_label == "Publicadas en Instagram"
    assert config.published_items == DEFAULT_ITEMS
    assert config.published_by_user_id == USER and config.published_at is not None
    assert config.remote is not None and config.remote.default_items == DEFAULT_ITEMS
    assert config.remote_verified is True
    assert config.has_unpublished_changes is False
    assert config.last_error_code is None and config.error_message is None

    edited = service.save_draft(
        tenant_id=TENANT,
        connection_id=CONN,
        items=[*DEFAULT_ITEMS[:3]],
        user_id=USER,
    )
    # Editing does not touch what Instagram shows.
    assert edited.status == "published" and edited.has_unpublished_changes is True


async def test_publishing_an_empty_draft_is_refused_before_meta() -> None:
    service, _, client = _service()
    service.save_draft(tenant_id=TENANT, connection_id=CONN, items=[], user_id=USER)
    with pytest.raises(IceBreakerError) as caught:
        await service.publish(tenant_id=TENANT, connection_id=CONN, user_id=USER)
    assert caught.value.code == "nothing_to_publish"
    assert client.calls == []


async def test_a_refused_publish_is_failed_with_a_code_and_degrades_on_auth() -> None:
    degraded: list[UUID] = []
    client = MemoryIceBreakersClient(
        fail_next=[IceBreakersApiError("x", http_status=401, platform_code=190)]
    )
    service, _, _ = _service(client, degraded=degraded)
    with pytest.raises(IceBreakerRemoteError) as caught:
        await service.publish(tenant_id=TENANT, connection_id=CONN, user_id=USER)
    assert caught.value.code == "auth_expired"
    config = caught.value.config
    assert config.status == "failed"
    assert config.last_error_code == "auth_expired"
    assert config.last_error_detail == "http_401_code_190"
    assert config.published_items is None
    assert config.error_message == (
        "Instagram pidió volver a conectar la cuenta. Conéctala de nuevo en Cuentas conectadas."
    )
    assert degraded == [CONN]
    assert client.calls == [("publish", CONN)]  # no read-back after a definitive refusal


async def test_an_ambiguous_publish_is_settled_by_reading_back() -> None:
    landed = MemoryIceBreakersClient(
        fail_next=[IceBreakersApiError("x", is_transport=True, is_ambiguous=True)],
        ambiguous_landed=True,
    )
    service, _, _ = _service(landed)
    config = await service.publish(tenant_id=TENANT, connection_id=CONN, user_id=USER)
    assert config.status == "published" and config.remote_verified

    lost = MemoryIceBreakersClient(
        fail_next=[IceBreakersApiError("x", is_transport=True, is_ambiguous=True)]
    )
    service, _, _ = _service(lost)
    with pytest.raises(IceBreakerRemoteError) as caught:
        await service.publish(tenant_id=TENANT, connection_id=CONN, user_id=USER)
    assert caught.value.code == "ambiguous"
    assert caught.value.config.status == "failed"
    assert lost.calls == [("publish", CONN), ("fetch", CONN)]


async def test_a_failed_read_back_does_not_undo_a_confirmed_publish() -> None:
    client = MemoryIceBreakersClient()
    service, _, _ = _service(client)

    async def broken_fetch(connection: SourceConnection):
        raise IceBreakersApiError("x", http_status=500)

    client.fetch = broken_fetch  # type: ignore[method-assign]
    config = await service.publish(tenant_id=TENANT, connection_id=CONN, user_id=USER)
    assert config.status == "published"
    assert config.remote is None and config.remote_verified is False


async def test_an_account_that_is_not_active_fails_without_calling_meta() -> None:
    service, _, client = _service(connections={})
    with pytest.raises(IceBreakerRemoteError) as caught:
        await service.publish(tenant_id=TENANT, connection_id=CONN, user_id=USER)
    assert caught.value.code == "connection_unavailable"
    assert caught.value.config.status == "failed"
    assert client.calls == []


async def test_a_credential_that_cannot_be_read_is_an_unexpected_failure() -> None:
    async def factory(tenant_id: UUID, connection_id: UUID):
        raise RuntimeError("no credential")

    client = InstagramIceBreakersClient(client_factory=factory, graph_url="https://g/v25.0")
    service, _, _ = _service(client)
    with pytest.raises(IceBreakerRemoteError) as caught:
        await service.publish(tenant_id=TENANT, connection_id=CONN, user_id=USER)
    assert caught.value.code == "unexpected"
    assert caught.value.config.last_error_detail == "runtimeerror"


async def test_remove_deletes_reads_back_and_keeps_the_draft() -> None:
    service, _, client = _service()
    await service.publish(tenant_id=TENANT, connection_id=CONN, user_id=USER)
    config = await service.remove(tenant_id=TENANT, connection_id=CONN, user_id=USER)
    assert client.calls[-2:] == [("remove", CONN), ("fetch", CONN)]
    assert config.status == "removed" and config.status_label == "Quitadas de Instagram"
    assert config.published_items is None and config.removed_by_user_id == USER
    assert config.remote is not None and config.remote.is_empty
    assert config.items == DEFAULT_ITEMS  # the draft stays, ready to publish again


async def test_refresh_failure_records_nothing() -> None:
    client = MemoryIceBreakersClient()
    service, _, _ = _service(client)
    await service.publish(tenant_id=TENANT, connection_id=CONN, user_id=USER)
    client.fail_next.append(IceBreakersApiError("x", http_status=400, platform_code=613))
    with pytest.raises(IceBreakerRemoteError) as caught:
        await service.refresh_remote(tenant_id=TENANT, connection_id=CONN)
    assert caught.value.code == "rate_limited"
    assert caught.value.config.status == "published"


# --- the real client on a mocked transport -----------------------------------------------


def _real_client(handler) -> InstagramIceBreakersClient:
    async def factory(tenant_id: UUID, connection_id: UUID) -> _InjectedAuthClient:
        return _InjectedAuthClient(TOKEN, scheme="Bearer", transport=httpx.MockTransport(handler))

    return InstagramIceBreakersClient(client_factory=factory, graph_url="https://g/v25.0")


async def test_end_to_end_publish_over_the_wire() -> None:
    sent: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            sent["body"] = json.loads(request.content)
            return httpx.Response(200, json={"result": "success"})
        return httpx.Response(200, json={"data": sent["body"]["ice_breakers"]})

    service, _, _ = _service(_real_client(handler))
    config = await service.publish(tenant_id=TENANT, connection_id=CONN, user_id=USER)
    assert sent["body"]["ice_breakers"][0]["locale"] == "default"
    assert config.status == "published" and config.remote_verified


async def test_a_failed_publish_logs_codes_only(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": {"code": 100, "message": f"bad {DEFAULT_ITEMS[0].question} {TOKEN}"}},
        )

    service, repo, _ = _service(_real_client(handler))
    with pytest.raises(IceBreakerRemoteError) as caught:
        await service.publish(tenant_id=TENANT, connection_id=CONN, user_id=uuid4())
    assert caught.value.code == "rejected"
    stored = repo.get(tenant_id=TENANT, connection_id=CONN)
    assert stored is not None
    assert (stored.status, stored.last_error_code, stored.last_error_detail) == (
        "failed",
        "rejected",
        "http_400_code_100",
    )
    logged = caplog.text
    assert "code=rejected" in logged
    assert TOKEN not in logged
    for item in DEFAULT_ITEMS:
        assert item.question not in logged
        assert item.payload not in logged

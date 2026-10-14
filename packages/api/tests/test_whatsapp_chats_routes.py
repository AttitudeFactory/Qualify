"""WA-10 — the HTTP contract of the WhatsApp chats API.

Fully offline: `ChatService` over `MemoryChatRepository` + WA-08's `MemoryOutboxRepository`,
a frozen clock, and the dev principal resolver fed from `QUALIFY_DEV_PRINCIPALS` (the same
road production takes, so the 401 path is the real one). `test_whatsapp_chat_service.py`
covers the service rules; `test_whatsapp_chat_repository_db.py` the Postgres SQL.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from qualify_api.http import deps, whatsapp_routes
from qualify_api.http.app import create_app
from qualify_api.whatsapp.chats import (
    ChatService,
    MemoryChatRepository,
    MemoryThreadState,
    NotCapturedMediaLocator,
)
from qualify_api.whatsapp.outbox import MemoryOutboxRepository

NOW = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)
TENANT_A = UUID("a1000000-0000-4000-8000-00000000000a")
TENANT_B = UUID("b1000000-0000-4000-8000-00000000000b")
USER_A = UUID("a2000000-0000-4000-8000-00000000000a")
AGENT_A = UUID("a3000000-0000-4000-8000-00000000000a")
USER_B = UUID("b2000000-0000-4000-8000-00000000000b")
CONN_A = UUID("a4000000-0000-4000-8000-00000000000a")
CONN_A2 = UUID("a5000000-0000-4000-8000-00000000000a")
CONN_B = UUID("b4000000-0000-4000-8000-00000000000b")
WA_ID = "573001234567"

AUTH_A = {"Authorization": "Bearer token-a"}
AUTH_B = {"Authorization": "Bearer token-b"}


class FixedLocator:
    def __init__(self, url: str | None) -> None:
        self.url = url
        self.calls: list[tuple[UUID, UUID]] = []

    def locate(self, *, tenant_id: UUID, message_id: UUID) -> str | None:
        self.calls.append((tenant_id, message_id))
        return self.url


class Harness:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "QUALIFY_DEV_PRINCIPALS",
            f"token-a:{TENANT_A}:{USER_A},token-b:{TENANT_B}:{USER_B}",
        )
        self.repo = MemoryChatRepository()
        self.outbox = MemoryOutboxRepository(clock=lambda: NOW)
        self.service = ChatService(self.repo, self.outbox, clock=lambda: NOW)
        self.locator: object = NotCapturedMediaLocator()
        app = create_app(configure_production=False)
        app.dependency_overrides[deps.current_principal] = deps.build_dev_principal_dependency()
        app.dependency_overrides[whatsapp_routes.get_chat_service] = lambda: self.service
        app.dependency_overrides[whatsapp_routes.get_media_locator] = lambda: self.locator
        self.http = TestClient(app)
        self.repo.add_user(tenant_id=TENANT_A, user_id=USER_A)
        self.repo.add_user(tenant_id=TENANT_A, user_id=AGENT_A)
        self.repo.add_user(tenant_id=TENANT_B, user_id=USER_B)

    def thread(
        self,
        *,
        tenant_id: UUID = TENANT_A,
        connection_id: UUID = CONN_A,
        inbound_ago: timedelta | None = timedelta(hours=1),
        status: str = "open",
    ) -> UUID:
        thread_id = self.repo.add_thread(
            tenant_id=tenant_id, connection_id=connection_id, wa_id=WA_ID, status=status
        )
        if inbound_ago is not None:
            self.repo.add_message(
                thread_id=thread_id,
                direction="inbound",
                text_value="Hola, quiero pedir",
                posted_at=NOW - inbound_ago,
                author_username="Ana",
            )
        return thread_id


@pytest.fixture
def h(monkeypatch: pytest.MonkeyPatch) -> Harness:
    return Harness(monkeypatch)


# --- identity ---------------------------------------------------------------------------


def test_every_chat_route_requires_a_principal(h: Harness) -> None:
    thread_id = h.thread()
    for method, path in (
        ("get", "/api/whatsapp/threads"),
        ("get", f"/api/whatsapp/threads/{thread_id}/messages"),
        ("post", f"/api/whatsapp/threads/{thread_id}/close"),
        ("get", f"/api/whatsapp/media/{uuid4()}"),
    ):
        response = getattr(h.http, method)(path)
        assert response.status_code == 401, path


# --- listing ----------------------------------------------------------------------------


def test_list_threads_carries_preview_unread_window_and_assignment(h: Harness) -> None:
    thread_id = h.thread(inbound_ago=timedelta(hours=3))
    h.repo.add_message(
        thread_id=thread_id,
        direction="outbound",
        text_value="Claro, ¿qué deseas?",
        posted_at=NOW - timedelta(hours=2),
    )
    h.repo.add_message(
        thread_id=thread_id,
        direction="inbound",
        text_value=None,  # a photo: WA-07 stores no text and no type
        posted_at=NOW - timedelta(minutes=30),
        author_username="Ana María",
    )
    h.repo.add_message(
        thread_id=thread_id,
        direction="inbound",
        text_value=None,
        posted_at=NOW - timedelta(minutes=20),
    )

    response = h.http.get("/api/whatsapp/threads", headers=AUTH_A)

    assert response.status_code == 200
    body = response.json()
    assert body["next_before"] is None
    [thread] = body["threads"]
    assert thread["id"] == str(thread_id)
    assert thread["connection_id"] == str(CONN_A)
    assert thread["wa_id"] == WA_ID
    assert thread["contact_name"] == "Ana María"  # latest inbound author
    assert thread["last_message_preview"] == "[mensaje]"
    assert thread["last_message_direction"] == "inbound"
    assert thread["unread_count"] == 2  # inbound after the last outbound
    assert thread["status"] == "open"
    assert thread["assigned_agent_id"] is None
    assert thread["automation_paused"] is False
    closes_at = NOW - timedelta(minutes=20) + timedelta(hours=24)
    assert thread["window"] == {
        "open": True,
        "closes_at": closes_at.isoformat().replace("+00:00", "Z"),
    }
    assert set(thread) == {
        "id",
        "connection_id",
        "wa_id",
        "contact_name",
        "last_message_preview",
        "last_message_direction",
        "last_message_at",
        "last_inbound_at",
        "unread_count",
        "status",
        "assigned_agent_id",
        "automation_paused",
        "window",
    }


def test_closed_window_lists_as_closed_without_an_instant(h: Harness) -> None:
    h.thread(inbound_ago=timedelta(hours=30))
    [thread] = h.http.get("/api/whatsapp/threads", headers=AUTH_A).json()["threads"]
    assert thread["window"] == {"open": False, "closes_at": None}


def test_list_threads_filters_by_connection_and_status(h: Harness) -> None:
    open_a = h.thread()
    closed_a = h.thread(status="closed", inbound_ago=timedelta(hours=2))
    other_conn = h.thread(connection_id=CONN_A2, inbound_ago=timedelta(hours=3))

    def ids(query: str) -> list[str]:
        response = h.http.get(f"/api/whatsapp/threads{query}", headers=AUTH_A)
        assert response.status_code == 200
        return [t["id"] for t in response.json()["threads"]]

    assert ids("") == [str(open_a), str(closed_a), str(other_conn)]
    assert ids("?status=closed") == [str(closed_a)]
    assert ids(f"?connection_id={CONN_A2}") == [str(other_conn)]
    assert h.http.get("/api/whatsapp/threads?status=pending", headers=AUTH_A).status_code == 422


def test_list_threads_pages_with_next_before(h: Harness) -> None:
    newest = h.thread(inbound_ago=timedelta(hours=1))
    older = h.thread(inbound_ago=timedelta(hours=2))
    oldest = h.thread(inbound_ago=timedelta(hours=3))

    page = h.http.get("/api/whatsapp/threads?limit=2", headers=AUTH_A).json()
    assert [t["id"] for t in page["threads"]] == [str(newest), str(older)]
    assert page["next_before"] is not None

    page2 = h.http.get(
        "/api/whatsapp/threads", params={"limit": 2, "before": page["next_before"]}, headers=AUTH_A
    ).json()
    assert [t["id"] for t in page2["threads"]] == [str(oldest)]
    assert page2["next_before"] is None


def test_list_threads_is_tenant_scoped(h: Harness) -> None:
    h.thread()
    theirs = h.thread(tenant_id=TENANT_B, connection_id=CONN_B)
    body = h.http.get("/api/whatsapp/threads", headers=AUTH_B).json()
    assert [t["id"] for t in body["threads"]] == [str(theirs)]


def test_list_messages_chronological_with_delivery_fields(h: Harness) -> None:
    thread_id = h.thread(inbound_ago=timedelta(hours=2))
    h.repo.add_message(
        thread_id=thread_id,
        direction="outbound",
        text_value=None,
        posted_at=NOW - timedelta(hours=1),
        media_kind="image",
        delivery_status="read",
    )

    response = h.http.get(f"/api/whatsapp/threads/{thread_id}/messages", headers=AUTH_A)

    assert response.status_code == 200
    body = response.json()
    assert body["next_before"] is None
    first, second = body["messages"]
    assert (first["direction"], first["text"]) == ("inbound", "Hola, quiero pedir")
    assert first["media_kind"] is None
    assert (second["direction"], second["delivery_status"]) == ("outbound", "read")
    assert second["media_kind"] == "image"
    assert second["external_message_id"].startswith("wamid.")
    assert set(second) == {
        "id",
        "direction",
        "text",
        "posted_at",
        "delivery_status",
        "delivery_error_code",
        "external_message_id",
        "media_kind",
    }


def test_list_messages_pages_backwards(h: Harness) -> None:
    thread_id = h.thread(inbound_ago=timedelta(hours=5))
    for hours in (4, 3, 2):
        h.repo.add_message(
            thread_id=thread_id,
            direction="inbound",
            text_value=f"m{hours}",
            posted_at=NOW - timedelta(hours=hours),
        )
    url = f"/api/whatsapp/threads/{thread_id}/messages"
    page = h.http.get(url, params={"limit": 2}, headers=AUTH_A).json()
    assert [m["text"] for m in page["messages"]] == ["m3", "m2"]
    page2 = h.http.get(
        url, params={"limit": 2, "before": page["next_before"]}, headers=AUTH_A
    ).json()
    assert [m["text"] for m in page2["messages"]] == ["Hola, quiero pedir", "m4"]


def test_messages_of_unknown_or_foreign_thread_are_404(h: Harness) -> None:
    theirs = h.thread(tenant_id=TENANT_B, connection_id=CONN_B)
    for thread_id in (theirs, uuid4()):
        response = h.http.get(f"/api/whatsapp/threads/{thread_id}/messages", headers=AUTH_A)
        assert response.status_code == 404
        assert response.json()["detail"] == {"code": "thread_not_found"}


# --- sending ----------------------------------------------------------------------------


def test_send_text_queues_a_reply_and_pauses_automation(h: Harness) -> None:
    thread_id = h.thread()

    response = h.http.post(
        f"/api/whatsapp/threads/{thread_id}/messages",
        json={"type": "text", "text": "Tu pedido sale en 20 min"},
        headers=AUTH_A,
    )

    assert response.status_code == 201
    outbox_id = UUID(response.json()["outbox_id"])
    row = h.outbox.rows[outbox_id]
    assert (row.kind, row.thread_id, row.connection_id) == ("reply", thread_id, CONN_A)
    assert row.created_by_user_id == USER_A
    assert row.payload["to"] == WA_ID
    assert row.payload["text"]["body"] == "Tu pedido sale en 20 min"
    state = h.repo.states[thread_id]
    assert (state.automation_paused_at, state.paused_by_user_id) == (NOW, USER_A)
    [thread] = h.http.get("/api/whatsapp/threads", headers=AUTH_A).json()["threads"]
    assert thread["automation_paused"] is True


def test_send_image_and_buttons_build_cloud_api_bodies(h: Harness) -> None:
    thread_id = h.thread()
    url = f"/api/whatsapp/threads/{thread_id}/messages"

    image = h.http.post(
        url,
        json={"type": "image", "link": "https://cdn.example.com/menu.jpg", "caption": "Menú"},
        headers=AUTH_A,
    )
    buttons = h.http.post(
        url,
        json={
            "type": "buttons",
            "text": "¿Confirmas?",
            "buttons": [{"id": "yes", "title": "Sí"}, {"id": "no", "title": "No"}],
        },
        headers=AUTH_A,
    )

    assert image.status_code == buttons.status_code == 201
    image_payload = h.outbox.rows[UUID(image.json()["outbox_id"])].payload
    assert image_payload["type"] == "image"
    assert image_payload["image"] == {
        "link": "https://cdn.example.com/menu.jpg",
        "caption": "Menú",
    }
    buttons_payload = h.outbox.rows[UUID(buttons.json()["outbox_id"])].payload
    assert buttons_payload["interactive"]["action"]["buttons"][1] == {
        "type": "reply",
        "reply": {"id": "no", "title": "No"},
    }


def test_send_outside_the_window_is_409_and_writes_nothing(h: Harness) -> None:
    thread_id = h.thread(inbound_ago=timedelta(hours=25))

    response = h.http.post(
        f"/api/whatsapp/threads/{thread_id}/messages",
        json={"type": "text", "text": "¿Sigues ahí?"},
        headers=AUTH_A,
    )

    assert response.status_code == 409
    closed_at = NOW - timedelta(hours=25) + timedelta(hours=24)
    assert response.json()["detail"] == {
        "code": "window_closed",
        "closes_at": closed_at.isoformat(),
    }
    assert h.outbox.rows == {}
    assert thread_id not in h.repo.states


def test_send_with_no_inbound_ever_is_409_with_null_instant(h: Harness) -> None:
    thread_id = h.thread(inbound_ago=None)
    response = h.http.post(
        f"/api/whatsapp/threads/{thread_id}/messages",
        json={"type": "text", "text": "Hola"},
        headers=AUTH_A,
    )
    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "window_closed", "closes_at": None}


@pytest.mark.parametrize(
    "body",
    [
        {"type": "text", "text": ""},
        {"type": "sticker", "text": "x"},
        {"type": "image", "link": "not a url"},
        {
            "type": "buttons",
            "text": "x",
            "buttons": [{"id": str(i), "title": str(i)} for i in range(4)],
        },
    ],
)
def test_send_rejects_malformed_bodies_with_422(h: Harness, body: dict[str, object]) -> None:
    thread_id = h.thread()
    response = h.http.post(f"/api/whatsapp/threads/{thread_id}/messages", json=body, headers=AUTH_A)
    assert response.status_code == 422
    assert h.outbox.rows == {}


def test_send_over_a_cloud_api_limit_is_422_invalid_message(h: Harness) -> None:
    thread_id = h.thread()
    response = h.http.post(
        f"/api/whatsapp/threads/{thread_id}/messages",
        json={"type": "buttons", "text": "x", "buttons": [{"id": "a", "title": "t" * 21}]},
        headers=AUTH_A,
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_message"
    assert h.outbox.rows == {}
    assert thread_id not in h.repo.states


def test_send_to_a_foreign_thread_is_404(h: Harness) -> None:
    theirs = h.thread(tenant_id=TENANT_B, connection_id=CONN_B)
    response = h.http.post(
        f"/api/whatsapp/threads/{theirs}/messages",
        json={"type": "text", "text": "hola"},
        headers=AUTH_A,
    )
    assert response.status_code == 404
    assert h.outbox.rows == {}


# --- thread actions ---------------------------------------------------------------------


def test_assign_and_unassign(h: Harness) -> None:
    thread_id = h.thread()
    url = f"/api/whatsapp/threads/{thread_id}/assign"

    assigned = h.http.post(url, json={"agent_user_id": str(AGENT_A)}, headers=AUTH_A)
    assert assigned.status_code == 200
    assert assigned.json()["assigned_agent_id"] == str(AGENT_A)

    cleared = h.http.post(url, json={"agent_user_id": None}, headers=AUTH_A)
    assert cleared.json()["assigned_agent_id"] is None


def test_assign_to_another_tenants_user_is_422(h: Harness) -> None:
    thread_id = h.thread()
    response = h.http.post(
        f"/api/whatsapp/threads/{thread_id}/assign",
        json={"agent_user_id": str(USER_B)},
        headers=AUTH_A,
    )
    assert response.status_code == 422
    assert response.json()["detail"] == {"code": "unknown_agent"}
    assert h.repo.threads[thread_id].assigned_agent_id is None


def test_close_and_reopen(h: Harness) -> None:
    thread_id = h.thread()
    closed = h.http.post(f"/api/whatsapp/threads/{thread_id}/close", headers=AUTH_A)
    assert (closed.status_code, closed.json()["status"]) == (200, "closed")
    reopened = h.http.post(f"/api/whatsapp/threads/{thread_id}/reopen", headers=AUTH_A)
    assert (reopened.status_code, reopened.json()["status"]) == (200, "open")


def test_takeover_then_resume(h: Harness) -> None:
    thread_id = h.thread()
    # The menu engine left the conversation mid-order.
    h.repo.states[thread_id] = MemoryThreadState(
        tenant_id=TENANT_A, node_id="products", attempts=2, context={"order": [{"sku": "x"}]}
    )

    taken = h.http.post(f"/api/whatsapp/threads/{thread_id}/takeover", headers=AUTH_A)
    assert (taken.status_code, taken.json()["automation_paused"]) == (200, True)
    assert h.repo.states[thread_id].paused_by_user_id == USER_A

    resumed = h.http.post(f"/api/whatsapp/threads/{thread_id}/resume", headers=AUTH_A)
    assert (resumed.status_code, resumed.json()["automation_paused"]) == (200, False)
    state = h.repo.states[thread_id]
    assert (state.node_id, state.attempts, state.paused_by_user_id) == (None, 0, None)
    assert state.context == {"order": [{"sku": "x"}]}


@pytest.mark.parametrize("action", ["close", "reopen", "takeover", "resume"])
def test_actions_on_foreign_or_unknown_thread_are_404(h: Harness, action: str) -> None:
    theirs = h.thread(tenant_id=TENANT_B, connection_id=CONN_B)
    for thread_id in (theirs, uuid4()):
        response = h.http.post(f"/api/whatsapp/threads/{thread_id}/{action}", headers=AUTH_A)
        assert response.status_code == 404
    assert h.repo.threads[theirs].status == "open"
    assert theirs not in h.repo.states


def test_assign_on_foreign_thread_is_404(h: Harness) -> None:
    theirs = h.thread(tenant_id=TENANT_B, connection_id=CONN_B)
    response = h.http.post(
        f"/api/whatsapp/threads/{theirs}/assign",
        json={"agent_user_id": str(AGENT_A)},
        headers=AUTH_A,
    )
    assert response.status_code == 404


# --- media ------------------------------------------------------------------------------


def test_media_is_501_until_media_ids_are_captured(h: Harness) -> None:
    response = h.http.get(f"/api/whatsapp/media/{uuid4()}", headers=AUTH_A)
    assert response.status_code == 501
    assert response.json()["detail"] == {"code": "media_not_captured"}


def test_media_redirects_when_a_locator_finds_it(h: Harness) -> None:
    locator = FixedLocator("https://media.example.com/signed/abc")
    h.locator = locator
    message_id = uuid4()
    response = h.http.get(
        f"/api/whatsapp/media/{message_id}", headers=AUTH_A, follow_redirects=False
    )
    assert response.status_code == 307
    assert response.headers["location"] == "https://media.example.com/signed/abc"
    assert locator.calls == [(TENANT_A, message_id)]


def test_production_app_wires_the_chat_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUALIFY_DEV_PRINCIPALS", "")
    app = create_app(configure_production=True)
    assert whatsapp_routes.get_chat_service in app.dependency_overrides
    locator = app.dependency_overrides[whatsapp_routes.get_media_locator]()
    assert isinstance(locator, NotCapturedMediaLocator)

"""`qualify_api.support` (QUA-202): "Pedir ayuda 1:1" becomes a ticket the tenant owns, then
a notification to the global channel — in that order, so a channel that is down never
loses a request.

Validation and the notification payload run offline; the row and its RLS run `db`-marked."""

from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.support import (
    InvalidSupportRequest,
    NullSupportNotifier,
    SupportNotification,
    WebhookSupportNotifier,
    create_support_request,
)
from qualify_api.support.models import SupportRequest
from qualify_api.tenancy.models import Tenant

TENANT_A = UUID("c0000000-0000-4000-8000-0000000000f2")
TENANT_B = UUID("d0000000-0000-4000-8000-0000000000f2")


class RecordingNotifier:
    def __init__(self, *, accept: bool = True) -> None:
        self.accept = accept
        self.sent: list[SupportNotification] = []

    def notify(self, notification: SupportNotification) -> bool:
        self.sent.append(notification)
        return self.accept


# -- offline ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"topic": "billing", "contact_email": "a@b.co"},
        {"topic": "connect_accounts", "contact_email": ""},
        {"topic": "connect_accounts", "contact_email": "not-an-email"},
        {"topic": "connect_accounts", "contact_email": "a@b.co", "context": {"page_id": "1"}},
    ],
)
def test_invalid_input_is_refused_before_anything_is_written(kwargs: dict) -> None:
    notifier = RecordingNotifier()
    with pytest.raises(InvalidSupportRequest):
        create_support_request(tenant_id=TENANT_A, notifier=notifier, **kwargs)
    assert notifier.sent == []


def test_notification_text_reads_like_a_ticket_and_carries_only_counts() -> None:
    text = SupportNotification(
        reference="A1B2C3",
        business_name="Bianki",
        contact_email="dueno@bianki.co",
        contact_whatsapp="+58 412 000 0000",
        topic="connect_accounts",
        message="No me deja conectar",
        context={"outcome": "link_required", "pages": 2, "linked": 0},
    ).as_text()
    assert text.startswith("🆘 Nueva solicitud de ayuda 1:1 · #A1B2C3")
    assert "Negocio: Bianki" in text
    assert "WhatsApp: +58 412 000 0000" in text
    assert "linked=0, outcome=link_required, pages=2" in text
    assert "Mensaje: No me deja conectar" in text


def test_webhook_payload_fits_lark_slack_and_cliq_at_once() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.append(json.loads(request.content))
        return httpx.Response(200)

    notifier = WebhookSupportNotifier(
        "https://hooks.example/x", transport=httpx.MockTransport(handler)
    )
    note = SupportNotification("REF001", "B", "a@b.co", "", "other", "", {})
    assert notifier.notify(note) is True
    (payload,) = seen
    assert payload["text"] == note.as_text()
    assert payload["msg_type"] == "text"
    assert payload["content"] == {"text": note.as_text()}


@pytest.mark.parametrize("failure", ["http_500", "transport_error"])
def test_webhook_failures_are_reported_as_not_notified_never_raised(failure: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "transport_error":
            raise httpx.ConnectError("down")
        return httpx.Response(500)

    notifier = WebhookSupportNotifier(
        "https://hooks.example/x", transport=httpx.MockTransport(handler)
    )
    assert notifier.notify(SupportNotification("R", "B", "a@b.co", "", "other", "", {})) is False


def test_no_channel_configured_means_not_notified() -> None:
    assert (
        NullSupportNotifier().notify(SupportNotification("R", "B", "a@b.co", "", "other", "", {}))
        is False
    )


# -- database -----------------------------------------------------------------------------


@pytest.fixture
def tenants() -> None:
    with admin_session() as session:
        for tid, name in ((TENANT_A, "A"), (TENANT_B, "B")):
            if session.get(Tenant, tid) is None:
                session.add(
                    Tenant(
                        id=tid,
                        name=f"support-{name}",
                        country="CO",
                        timezone="America/Bogota",
                        currency="COP",
                    )
                )
        session.commit()


@pytest.mark.db
def test_ticket_is_saved_then_notified_and_stamped(tenants: None) -> None:
    notifier = RecordingNotifier(accept=True)
    marker = f"ticket-{uuid4()}"
    ticket = create_support_request(
        tenant_id=TENANT_A,
        topic="connect_accounts",
        contact_email="dueno@bianki.co",
        contact_whatsapp=" +58 412 000 0000 ",
        message=marker,
        context={"outcome": "page_access_required", "pages": 0, "linked": 0},
        notifier=notifier,
    )
    assert len(ticket.reference) == 6 and ticket.notified is True
    (sent,) = notifier.sent
    assert (sent.reference, sent.business_name) == (ticket.reference, "support-A")
    assert sent.contact_whatsapp == "+58 412 000 0000"

    with tenant_session(TENANT_A) as session:
        row = session.get(SupportRequest, ticket.id)
        assert row is not None
        assert (row.status, row.topic, row.message) == ("open", "connect_accounts", marker)
        assert row.context == {"outcome": "page_access_required", "pages": 0, "linked": 0}
        assert row.notified_at is not None


@pytest.mark.db
def test_a_channel_that_is_down_still_leaves_a_ticket(tenants: None) -> None:
    ticket = create_support_request(
        tenant_id=TENANT_A,
        topic="other",
        contact_email="dueno@bianki.co",
        notifier=RecordingNotifier(accept=False),
    )
    assert ticket.notified is False
    with tenant_session(TENANT_A) as session:
        row = session.get(SupportRequest, ticket.id)
        assert row is not None and row.notified_at is None


@pytest.mark.db
def test_another_tenant_cannot_see_the_ticket(tenants: None) -> None:
    ticket = create_support_request(
        tenant_id=TENANT_A,
        topic="other",
        contact_email="dueno@bianki.co",
        notifier=RecordingNotifier(),
    )
    with tenant_session(TENANT_B) as session:
        assert session.get(SupportRequest, ticket.id) is None
        assert session.scalars(select(SupportRequest.id)).all() == []

"""`db`-marked: the Resend delivery trail against live Postgres (migration 0064 columns).

- `mark_delivery` sets `delivered_at` / `opened_at` / `bounced_at` the first time only,
  reports the invite and its Meegle item, and knows nothing about an unknown email id;
- a signed event recorded through the real INSERT-only door lands as one `resend` change,
  a byte-identical redelivery adds nothing, and the real queue + the real handler settle
  it with the column written.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.webhook import webhook_worker_session
from sqlalchemy import select, text

from qualify_api.auth.invites import create_invite, mark_delivery, send_invite_email
from qualify_api.mail import FakeMailer
from qualify_api.mail.handlers import resend_handlers
from qualify_api.mail.webhook import SvixHeaders, record_resend_delivery
from qualify_api.tenancy.models import SignupInvite
from qualify_api.webhooks.processor import Processor
from qualify_api.webhooks.repository import WebhookQueue

pytestmark = pytest.mark.db

AT = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


def _email() -> str:
    return f"hlrd1993+resend-{uuid4().hex[:8]}@gmail.com"


def _sent_invite(work_item: int | None) -> tuple[str, SignupInvite]:
    invite = create_invite(_email(), meegle_work_item_id=work_item)
    mailer = FakeMailer()
    email_id = f"resend-test-{uuid4().hex}"  # unique per run; FakeMailer's `fake-1` is not
    send_invite_email(mailer, invite, "http://localhost:3100")
    with admin_session() as session:
        session.execute(
            text("UPDATE signup_invites SET resend_email_id = :e WHERE id = :id"),
            {"e": email_id, "id": invite.id},
        )
    with admin_session() as session:
        row = session.get(SignupInvite, invite.id)
        assert row is not None
        session.expunge(row)
    return email_id, row


def _columns(invite_id) -> tuple[datetime | None, datetime | None, datetime | None]:  # noqa: ANN001
    with admin_session() as session:
        row = session.execute(
            select(
                SignupInvite.delivered_at, SignupInvite.opened_at, SignupInvite.bounced_at
            ).where(SignupInvite.id == invite_id)
        ).one()
        return tuple(row)  # type: ignore[return-value]


def test_mark_delivery_sets_each_column_once() -> None:
    work_item = int(uuid4().int % 10**12)
    email_id, invite = _sent_invite(work_item)

    first = mark_delivery(email_id, kind="delivered", at=AT)
    assert first is not None
    assert (first.invite_id, first.meegle_work_item_id, first.first) == (invite.id, work_item, True)
    assert first.delivered_at == AT and first.opened_at is None and first.bounced_at is None

    again = mark_delivery(email_id, kind="delivered", at=AT.replace(hour=13))
    assert again is not None and again.first is False and again.delivered_at == AT

    opened = mark_delivery(email_id, kind="opened")  # `at` defaults to now
    assert opened is not None and opened.first is True and opened.opened_at is not None
    assert opened.delivered_at == AT

    bounced = mark_delivery(email_id, kind="bounced", at=AT)
    assert bounced is not None and bounced.first is True
    assert _columns(invite.id) == (AT, opened.opened_at, AT)

    assert mark_delivery(f"unknown-{uuid4().hex}", kind="delivered", at=AT) is None


def test_a_plain_invite_has_no_meegle_item() -> None:
    email_id, invite = _sent_invite(None)
    mark = mark_delivery(email_id, kind="opened", at=AT)
    assert mark is not None and mark.meegle_work_item_id is None and mark.invite_id == invite.id


async def test_a_recorded_event_is_settled_by_the_real_queue_and_handler() -> None:
    email_id, invite = _sent_invite(None)
    body = json.dumps(
        {
            "type": "email.delivered",
            "created_at": "2026-10-16T12:00:00.000Z",
            "data": {"email_id": email_id, "to": [invite.email], "subject": "Invitación"},
        }
    ).encode()
    headers = SvixHeaders(message_id=f"msg_{uuid4().hex[:8]}", timestamp="1", signature="v1,x")

    first = record_resend_delivery(body=body, headers=headers)
    assert (first.duplicate_delivery, first.parse_status, first.changes_new) == (False, "parsed", 1)
    second = record_resend_delivery(body=body, headers=headers)
    assert second.duplicate_delivery is True

    with webhook_worker_session() as session:
        row = (
            session.execute(
                text(
                    "SELECT object, entry_id, field, status, entry_time FROM meta_webhook_events"
                    " WHERE object = 'resend' AND entry_id = :e"
                ),
                {"e": email_id},
            )
            .mappings()
            .one()
        )
    assert (row["object"], row["field"], row["status"]) == ("resend", "email.delivered", "pending")
    assert row["entry_time"] == int(AT.timestamp() * 1000)

    processor = Processor(
        queue=WebhookQueue(), handlers=resend_handlers(None), worker_id=f"test-{uuid4().hex[:6]}"
    )

    def status() -> str:
        with webhook_worker_session() as session:
            return session.execute(
                text(
                    "SELECT status FROM meta_webhook_events WHERE object = 'resend'"
                    " AND entry_id = :e"
                ),
                {"e": email_id},
            ).scalar_one()

    # Other tests may leave pending rows; drain until ours is settled.
    for _ in range(20):
        await processor.run_once(limit=50)
        if status() != "pending":
            break
    assert status() == "processed"
    delivered_at, opened_at, bounced_at = _columns(invite.id)
    assert delivered_at == AT and opened_at is None and bounced_at is None

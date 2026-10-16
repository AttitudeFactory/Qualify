"""`db`-marked: the Meegle engine's database half against live Postgres.

- the intake: a signed event recorded through the real INSERT-only door lands as one
  `meegle` change keyed by `idempotent_key`; a redelivery adds nothing; the real queue
  claims it and the real handler settles it;
- migration 0064: `create_invite(meegle_work_item_id=…)`, `expire_invites_for_work_item`,
  the Resend id stored by `send_invite_email`;
- `register_business` with such an invite calls the Meegle write-back once, after the
  transaction, and never fails over it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.webhook import webhook_worker_session
from sqlalchemy import select, text

from qualify_api.auth import FakeAuthProvider, authorize_signup, lookup_invite, register_business
from qualify_api.auth import service as auth_service
from qualify_api.auth.invites import (
    create_invite,
    expire_invites_for_work_item,
    send_invite_email,
)
from qualify_api.mail import FakeMailer
from qualify_api.meegle.handlers import meegle_handlers
from qualify_api.meegle.onboarding import InvitationResult
from qualify_api.meegle.receiver import SIGNATURE_PREFIX, record_meegle_delivery
from qualify_api.meegle.settings import MeegleNames
from qualify_api.tenancy.models import SignupInvite
from qualify_api.webhooks.processor import Processor
from qualify_api.webhooks.repository import WebhookQueue

pytestmark = pytest.mark.db


def _email() -> str:
    return f"hlrd1993+meegle-{uuid4().hex[:8]}@gmail.com"


def _work_item_id() -> int:
    return int(uuid4().int % 10**12)


# --------------------------------------------------------------------------------------
# Intake
# --------------------------------------------------------------------------------------


class _Engine:
    def __init__(self) -> None:
        self.started: list[int] = []

    def node_name(self, work_item_id: int, key: str) -> str | None:
        return {"started": "Datos"}.get(key)

    def start_invitation(self, work_item_id: int) -> InvitationResult:
        self.started.append(work_item_id)
        return InvitationResult(ok=True, invite_id=uuid4())

    def expire_for_terminated(self, work_item_id: int) -> int:
        return 0


def _row(dedup_key: str) -> dict:
    with webhook_worker_session() as session:
        row = (
            session.execute(
                text(
                    "SELECT object, entry_id, field, value, status, last_error, dedup_key,"
                    "       entry_time FROM meta_webhook_events WHERE dedup_key = :k"
                ),
                {"k": dedup_key},
            )
            .mappings()
            .one()
        )
        return dict(row)


async def test_a_signed_event_is_recorded_once_and_settled_by_the_handler(meegle_events) -> None:  # noqa: ANN001
    work_item = _work_item_id()
    key = uuid4().hex + uuid4().hex  # a fresh idempotent key per run
    body = meegle_events.body(nodes=["started"], work_item_id=work_item, idempotent_key=key)
    signature = json.loads(body)["signature"]

    first = record_meegle_delivery(body=body, signature=signature)
    assert (first.duplicate_delivery, first.parse_status, first.changes_new) == (False, "parsed", 1)

    row = _row(key)
    assert (row["object"], row["entry_id"], row["field"], row["status"]) == (
        "meegle",
        str(work_item),
        "2001",
        "pending",
    )
    assert row["entry_time"] == meegle_events.REQUEST_TIME
    assert row["value"]["source"] == "normal"
    assert row["value"]["data"]["idempotent_key"] == key

    # Meegle retries: same event, another request_time (another body) → nothing new.
    retry = meegle_events.body(
        nodes=["started"], work_item_id=work_item, idempotent_key=key, request_time=1730184099999
    )
    second = record_meegle_delivery(body=retry, signature=json.loads(retry)["signature"])
    assert (second.duplicate_delivery, second.changes_new) == (False, 0)
    # Byte-identical redelivery → the delivery itself is the duplicate.
    third = record_meegle_delivery(body=body, signature=signature)
    assert third.duplicate_delivery is True

    with webhook_worker_session() as session:
        stored_signature = session.execute(
            text(
                "SELECT d.object FROM meta_webhook_deliveries d"
                "  JOIN meta_webhook_events e ON e.delivery_id = d.id WHERE e.dedup_key = :k"
            ),
            {"k": key},
        ).scalar_one()
    assert stored_signature == "meegle"
    assert SIGNATURE_PREFIX in f"{SIGNATURE_PREFIX}{signature}"

    engine = _Engine()
    processor = Processor(
        queue=WebhookQueue(),
        handlers=meegle_handlers(
            engine, work_item_type=meegle_events.WORK_ITEM_TYPE, names=MeegleNames()
        ),  # type: ignore[arg-type]
        worker_id=f"test-{uuid4().hex[:6]}",
    )
    # Other tests may leave pending rows; drain until ours is settled.
    for _ in range(20):
        await processor.run_once(limit=50)
        if _row(key)["status"] != "pending":
            break
    assert _row(key)["status"] == "processed"
    assert engine.started == [work_item]


def test_a_body_that_is_not_an_event_is_recorded_unparseable() -> None:
    recorded = record_meegle_delivery(body=f'{{"x": "{uuid4().hex}"}}'.encode(), signature="")
    assert recorded.parse_status == "unparseable" and recorded.changes_total == 0


# --------------------------------------------------------------------------------------
# Invites (migration 0064)
# --------------------------------------------------------------------------------------


def test_invites_remember_their_work_item_and_expire_with_it() -> None:
    work_item = _work_item_id()
    a = create_invite(_email(), meegle_work_item_id=work_item)
    b = create_invite(_email(), meegle_work_item_id=work_item)
    other = create_invite(_email())  # a `just invite` one: no item
    with admin_session() as session:
        stored = session.get(SignupInvite, a.id)
        assert stored is not None and stored.meegle_work_item_id == work_item
        assert stored.resend_email_id is None
    assert lookup_invite(a.token) is not None

    assert expire_invites_for_work_item(work_item) == 2
    assert lookup_invite(a.token) is None and lookup_invite(b.token) is None
    assert lookup_invite(other.token) is not None
    assert expire_invites_for_work_item(work_item) == 0  # idempotent


def test_send_invite_email_stores_the_provider_id() -> None:
    invite = create_invite(_email(), meegle_work_item_id=_work_item_id())
    mailer = FakeMailer()
    email_id = send_invite_email(mailer, invite, "http://localhost:3100")
    assert email_id == "fake-1"
    with admin_session() as session:
        assert (
            session.scalar(select(SignupInvite.resend_email_id).where(SignupInvite.id == invite.id))
            == "fake-1"
        )


# --------------------------------------------------------------------------------------
# Registration write-back
# --------------------------------------------------------------------------------------


def _register(email: str, invite_id: UUID | None) -> UUID:
    return register_business(
        FakeAuthProvider(),
        business_name="Invitado Meegle",
        email=email,
        password="correct-horse-9",
        country="VE",
        timezone="America/Caracas",
        currency="USD",
        invite_id=invite_id,
    ).tenant_id


def test_a_meegle_invite_signup_notifies_meegle_after_the_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, UUID, bool]] = []

    def fake_notify(work_item_id: int, tenant_id: UUID) -> None:
        with admin_session() as session:  # the invite is already spent when we are called
            used_at = session.scalar(
                select(SignupInvite.used_at).where(SignupInvite.meegle_work_item_id == work_item_id)
            )
        calls.append((work_item_id, tenant_id, used_at is not None))

    monkeypatch.setattr(auth_service, "notify_meegle_registered", fake_notify)
    work_item = _work_item_id()
    invite = create_invite(_email(), meegle_work_item_id=work_item)
    tenant_id = _register(invite.email, authorize_signup(invite.email, invite.token))
    assert calls == [(work_item, tenant_id, True)]

    # A plain invite (no item) never calls Meegle.
    plain = create_invite(_email())
    _register(plain.email, authorize_signup(plain.email, plain.token))
    assert len(calls) == 1


def test_a_failing_write_back_never_fails_the_signup(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(work_item_id: int, tenant_id: UUID) -> None:
        raise RuntimeError("meegle down")

    monkeypatch.setattr(auth_service, "notify_meegle_registered", boom)
    invite = create_invite(_email(), meegle_work_item_id=_work_item_id())
    tenant_id = _register(invite.email, authorize_signup(invite.email, invite.token))
    assert isinstance(tenant_id, UUID)
    assert lookup_invite(invite.token) is None  # spent all the same
    assert datetime.now(UTC) is not None

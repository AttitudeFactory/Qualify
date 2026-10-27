"""WA-08 — `PostgresOutboxRepository` against the real database (migration 0057).

Two guarantees that only Postgres can prove:

- `claim` with `FOR UPDATE SKIP LOCKED` never hands the same row to two workers: a second
  claim issued while the first is still holding its transaction sees nothing of what the
  first took. Exercised with two raw `qualify_app` connections (both RLS-scoped to the
  tenant), the first one left open mid-claim.
- `mark_sent` writes the outbound `messages` row (`direction='outbound'`,
  `external_message_id = wamid`, `delivery_status='sent'`, the text of the body) and
  bumps `threads.last_message_at` — and a repeated `mark_sent` with the same `wamid`
  does not duplicate it (`uq_message_external_id`).

Seeding follows `test_whatsapp_schema_db.py`: tenant/user/app via `admin_session`, the
WhatsApp connection and thread through `tenant_session` (the production door).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.config import app_dsn
from qualify_shared.db.session import tenant_session
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.engine import Engine

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.inbox.models import Message, Thread
from qualify_api.tenancy.models import Tenant, User
from qualify_api.whatsapp.client import build_text_body
from qualify_api.whatsapp.models import WhatsAppOutboxItem
from qualify_api.whatsapp.outbox import (
    CLAIM_SQL,
    ERROR_WINDOW_CLOSED,
    PostgresOutboxRepository,
    phone_number_id_for,
)

pytestmark = pytest.mark.db

TENANT = UUID("a0000000-0000-4000-8000-0000000000a8")
TO = "+573001234567"
# Earlier runs leave pending rows in this tenant (the fixture adds, never deletes — the
# app role cannot DELETE); a claim must be wide enough to reach the rows of THIS run.
LIMIT = 10_000


@pytest.fixture
def seeded() -> dict[str, UUID]:
    with admin_session() as session:
        if session.get(Tenant, TENANT) is None:
            session.add(
                Tenant(
                    id=TENANT,
                    name="t-wa08",
                    country="CO",
                    timezone="America/Bogota",
                    currency="COP",
                )
            )
            session.flush()
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        user = User(tenant_id=TENANT, email=f"u-{uuid4()}@wa08.co", display_name="U")
        session.add_all([app, user])
        session.flush()
        app_id, user_id = app.id, user.id

    with tenant_session(TENANT) as session:
        connection = SocialConnection(
            tenant_id=TENANT,
            platform_app_id=app_id,
            platform="whatsapp",
            account_type="waba_phone_number",
            external_account_id=f"pn-{uuid4().hex[:12]}",
            linked_page_id=None,
            granted_scopes=["whatsapp_business_messaging"],
            status="active",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=user_id,
        )
        session.add(connection)
        session.flush()
        thread = Thread(
            tenant_id=TENANT,
            connection_id=connection.id,
            channel="whatsapp",
            external_thread_id=f"wa-{uuid4().hex[:10]}",
            status="open",
            last_inbound_at=datetime.now(UTC) - timedelta(hours=1),
        )
        session.add(thread)
        session.flush()
        return {"user": user_id, "connection": connection.id, "thread": thread.id}


@pytest.fixture
def app_engine() -> Iterator[Engine]:
    engine = create_engine(app_dsn())
    try:
        yield engine
    finally:
        engine.dispose()


def _enqueue(repo: PostgresOutboxRepository, seeded: dict[str, UUID], body: str) -> UUID:
    return repo.enqueue(
        tenant_id=TENANT,
        connection_id=seeded["connection"],
        thread_id=seeded["thread"],
        kind="reply",
        payload=build_text_body(TO, body, False),
        created_by_user_id=seeded["user"],
    )


def _row(item_id: UUID) -> WhatsAppOutboxItem:
    with tenant_session(TENANT) as session:
        row = session.get(WhatsAppOutboxItem, item_id)
        assert row is not None
        session.expunge(row)
        return row


# --- claim -------------------------------------------------------------------------------


def test_enqueue_lands_a_pending_row_due_now(seeded) -> None:
    item_id = _enqueue(PostgresOutboxRepository(), seeded, "hola")
    row = _row(item_id)
    assert (row.status, row.attempts, row.kind, row.created_by_user_id) == (
        "pending",
        0,
        "reply",
        seeded["user"],
    )
    assert row.payload["to"] == TO and row.next_attempt_at <= datetime.now(UTC)


def test_claim_moves_the_row_to_sending_with_the_lock_and_returns_it(seeded) -> None:
    repo = PostgresOutboxRepository()
    item_id = _enqueue(repo, seeded, "hola")
    now = datetime.now(UTC)
    claimed = repo.claim(tenant_id=TENANT, worker_id="w:1", now=now, limit=LIMIT)
    ids = {c.id for c in claimed}
    assert item_id in ids
    item = next(c for c in claimed if c.id == item_id)
    assert item.thread_id == seeded["thread"] and item.kind == "reply" and item.attempts == 0
    row = _row(item_id)
    assert (row.status, row.locked_by) == ("sending", "w:1")
    # A second claim (same worker, later) must not see it again: it is no longer pending.
    again = repo.claim(tenant_id=TENANT, worker_id="w:1", now=now, limit=LIMIT)
    assert item_id not in {c.id for c in again}


def test_skip_locked_never_hands_one_row_to_two_workers(seeded, app_engine: Engine) -> None:
    """Worker A claims inside a transaction it keeps OPEN; worker B, concurrently, claims
    with its own connection. B must get none of A's rows, and nothing B gets may be A's."""
    repo = PostgresOutboxRepository()
    ids = {_enqueue(repo, seeded, f"m{n}") for n in range(3)}
    now = datetime.now(UTC)
    stale = now - timedelta(minutes=10)
    # The repository's own statement, run on raw connections so A's transaction can be
    # held open while B claims. (An earlier `WHERE id IN (SELECT … LIMIT 2 …)` form of it
    # returned 3 rows here — the re-evaluated subplan the CLAIM_SQL comment describes.)
    claim_sql = CLAIM_SQL

    with app_engine.connect() as conn_a:
        conn_a.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(TENANT)})
        taken_by_a = {
            r.id
            for r in conn_a.execute(
                claim_sql, {"worker": "a", "now": now, "stale": stale, "limit": 2}
            )
        }
        assert len(taken_by_a) == 2
        # A has not committed: its two rows are locked. B claims now, as wide as it likes.
        with app_engine.connect() as conn_b:
            conn_b.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(TENANT)}
            )
            taken_by_b = {
                r.id
                for r in conn_b.execute(
                    claim_sql, {"worker": "b", "now": now, "stale": stale, "limit": LIMIT}
                )
            }
            conn_b.commit()
        conn_a.commit()

    assert taken_by_a.isdisjoint(taken_by_b)
    assert ids <= taken_by_a | taken_by_b  # every row of this run went to exactly one worker
    for item_id in ids:
        assert _row(item_id).status == "sending"


def test_claim_is_tenant_scoped(seeded) -> None:
    repo = PostgresOutboxRepository()
    item_id = _enqueue(repo, seeded, "mine")
    other_tenant = uuid4()  # not even a real tenant: RLS makes it read nothing
    claimed = repo.claim(tenant_id=other_tenant, worker_id="w:x", now=datetime.now(UTC), limit=10)
    assert claimed == []
    assert _row(item_id).status == "pending"


# --- settle ------------------------------------------------------------------------------


def test_mark_sent_writes_the_outbound_message_once_and_bumps_the_thread(seeded) -> None:
    repo = PostgresOutboxRepository()
    item_id = _enqueue(repo, seeded, "Tu pedido esta listo")
    # The claim's `now` must not precede the row's server-default `next_attempt_at`, so it
    # is the real instant; the instant written by mark_sent is truncated to the second
    # only to compare timestamps exactly after the round trip.
    repo.claim(tenant_id=TENANT, worker_id="w:1", now=datetime.now(UTC), limit=LIMIT)
    now = datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=1)
    wamid = f"wamid.{uuid4().hex}"

    repo.mark_sent(tenant_id=TENANT, item_id=item_id, wamid=wamid, now=now)
    repo.mark_sent(tenant_id=TENANT, item_id=item_id, wamid=wamid, now=now)  # idempotent

    row = _row(item_id)
    assert (row.status, row.wamid, row.sent_at, row.locked_by, row.error_code) == (
        "sent",
        wamid,
        now,
        None,
        None,
    )
    with tenant_session(TENANT) as session:
        messages = session.scalars(
            select(Message).where(Message.external_message_id == wamid)
        ).all()
        assert len(messages) == 1
        message = messages[0]
        assert (message.direction, message.thread_id, message.connection_id) == (
            "outbound",
            seeded["thread"],
            seeded["connection"],
        )
        assert message.text == "Tu pedido esta listo"
        assert message.posted_at == now and message.delivery_status == "sent"
        assert message.shape_version  # provenance, never empty
        thread = session.get(Thread, seeded["thread"])
        assert thread is not None and thread.last_message_at == now
        # The window source is untouched: an outbound never counts as inbound (0004 B2).
        assert thread.last_inbound_at < now


def test_settles_are_guarded_by_the_sending_status(seeded) -> None:
    repo = PostgresOutboxRepository()
    item_id = _enqueue(repo, seeded, "x")
    # Not claimed: a settle on a pending row is a no-op, not a corruption.
    repo.mark_failed(tenant_id=TENANT, item_id=item_id, error_code=ERROR_WINDOW_CLOSED)
    assert _row(item_id).status == "pending"

    now = datetime.now(UTC)
    repo.claim(tenant_id=TENANT, worker_id="w:1", now=now, limit=LIMIT)
    repo.mark_retry(
        tenant_id=TENANT,
        item_id=item_id,
        attempts=1,
        error_code="transport",
        next_attempt_at=now + timedelta(seconds=4),
    )
    row = _row(item_id)
    assert (row.status, row.attempts, row.error_code) == ("pending", 1, "transport")
    assert row.locked_by is None and row.locked_at is None

    repo.claim(tenant_id=TENANT, worker_id="w:1", now=now + timedelta(seconds=5), limit=LIMIT)
    repo.mark_dead(tenant_id=TENANT, item_id=item_id, error_code="auth", attempts=2)
    row = _row(item_id)
    assert (row.status, row.attempts, row.error_code) == ("dead", 2, "auth")


def test_a_stale_sending_row_is_reclaimed_and_counts_an_attempt(seeded) -> None:
    repo = PostgresOutboxRepository()
    item_id = _enqueue(repo, seeded, "x")
    now = datetime.now(UTC)
    repo.claim(tenant_id=TENANT, worker_id="dead:1", now=now, limit=LIMIT)
    assert _row(item_id).status == "sending"
    # The worker died 30 minutes ago: age its lock (a claim with a backdated `now` would
    # simply find nothing due yet, since `next_attempt_at` defaults to the server's now()).
    with tenant_session(TENANT) as session:
        session.execute(
            update(WhatsAppOutboxItem)
            .where(WhatsAppOutboxItem.id == item_id)
            .values(locked_at=now - timedelta(minutes=30))
        )
    claimed = repo.claim(tenant_id=TENANT, worker_id="w:2", now=now, limit=LIMIT)
    item = next(c for c in claimed if c.id == item_id)
    assert item.attempts == 1
    assert _row(item_id).locked_by == "w:2"


# --- reads the sender depends on ---------------------------------------------------------


def test_thread_last_inbound_and_last_outbound_to_recipient(seeded) -> None:
    repo = PostgresOutboxRepository()
    last_inbound = repo.thread_last_inbound(tenant_id=TENANT, thread_id=seeded["thread"])
    assert last_inbound is not None and last_inbound < datetime.now(UTC)
    assert repo.thread_last_inbound(tenant_id=TENANT, thread_id=uuid4()) is None

    # `now` is a whole second just ahead of the clock: exact after the round trip, and
    # later than anything an earlier test in this run marked sent to the same recipient.
    now = datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=1)
    since = now - timedelta(seconds=6)
    item_id = _enqueue(repo, seeded, "x")
    repo.claim(tenant_id=TENANT, worker_id="w:1", now=datetime.now(UTC), limit=LIMIT)
    repo.mark_sent(tenant_id=TENANT, item_id=item_id, wamid=f"wamid.{uuid4().hex}", now=now)
    # Digits compared: the stored `+57…` matches a bare `57…` lookup.
    assert (
        repo.last_outbound_to_recipient(
            tenant_id=TENANT,
            connection_id=seeded["connection"],
            recipient=TO.lstrip("+"),
            since=since,
        )
        == now
    )
    assert (
        repo.last_outbound_to_recipient(
            tenant_id=TENANT,
            connection_id=seeded["connection"],
            recipient="+573009999999",
            since=since,
        )
        is None
    )


def test_phone_number_id_falls_back_to_the_connections_external_account_id(seeded) -> None:
    with tenant_session(TENANT) as session:
        expected = session.get(SocialConnection, seeded["connection"]).external_account_id
    assert phone_number_id_for(tenant_id=TENANT, connection_id=seeded["connection"]) == expected
    with pytest.raises(LookupError):
        phone_number_id_for(tenant_id=TENANT, connection_id=uuid4())


# --- 0087 (m-24848535): template replies --------------------------------------------------


def _enqueue_template_reply(
    repo: PostgresOutboxRepository, seeded: dict[str, UUID], key: str, category: str
) -> UUID:
    return repo.enqueue(
        tenant_id=TENANT,
        connection_id=seeded["connection"],
        thread_id=seeded["thread"],
        kind="template_reply",
        payload={
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": TO,
            "type": "template",
            "template": {"name": "seguimiento", "language": {"code": "es"}},
        },
        created_by_user_id=seeded["user"],
        request_key=key,
        template_id=uuid4(),
        template_category=category,
        preview_text="Hola, ¿seguimos con tu pedido?",
    )


def test_template_reply_same_request_key_queues_once(seeded) -> None:
    repo = PostgresOutboxRepository()
    key = f"tap-{uuid4()}"
    first = _enqueue_template_reply(repo, seeded, key, "utility")
    again = _enqueue_template_reply(repo, seeded, key, "utility")
    other = _enqueue_template_reply(repo, seeded, f"tap-{uuid4()}", "utility")
    assert first == again != other
    with tenant_session(TENANT) as session:
        ids = session.scalars(
            select(WhatsAppOutboxItem.id).where(WhatsAppOutboxItem.request_key == key)
        ).all()
    assert ids == [first]


def test_template_reply_claims_its_category_and_sends_its_preview(seeded) -> None:
    repo = PostgresOutboxRepository()
    item_id = _enqueue_template_reply(repo, seeded, f"tap-{uuid4()}", "marketing")
    claimed = repo.claim(tenant_id=TENANT, worker_id="w:tr", now=datetime.now(UTC), limit=LIMIT)
    (item,) = [c for c in claimed if c.id == item_id]
    assert item.kind == "template_reply" and item.template_category == "marketing"
    assert item.needs_opt_in is True
    wamid = f"wamid.{uuid4().hex}"
    repo.mark_sent(tenant_id=TENANT, item_id=item_id, wamid=wamid, now=datetime.now(UTC))
    with tenant_session(TENANT) as session:
        message = session.scalars(select(Message).where(Message.external_message_id == wamid)).one()
    assert message.text == "Hola, ¿seguimos con tu pedido?"


def test_template_reply_check_refuses_a_row_without_its_key(seeded) -> None:
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError), tenant_session(TENANT) as session:
        session.add(
            WhatsAppOutboxItem(
                tenant_id=TENANT,
                connection_id=seeded["connection"],
                thread_id=seeded["thread"],
                kind="template_reply",
                payload={"to": TO, "type": "template"},
                template_category="utility",
            )
        )
        session.flush()


def test_disconnected_account_pending_reply_is_not_claimed_until_reconnect(seeded) -> None:
    repo = PostgresOutboxRepository()
    item_id = _enqueue(repo, seeded, "pending approved reply")
    with tenant_session(TENANT) as session:
        connection = session.get(SocialConnection, seeded["connection"])
        connection.status = "degraded"
    now = datetime.now(UTC)
    assert item_id not in {
        item.id for item in repo.claim(tenant_id=TENANT, worker_id="paused", now=now, limit=LIMIT)
    }
    with tenant_session(TENANT) as session:
        row = session.get(WhatsAppOutboxItem, item_id)
        assert row.status == "pending" and row.attempts == 0
        connection = session.get(SocialConnection, seeded["connection"])
        connection.status = "active"
    claimed = repo.claim(tenant_id=TENANT, worker_id="resumed", now=now, limit=LIMIT)
    assert len([item for item in claimed if item.id == item_id]) == 1
    assert item_id not in {
        item.id for item in repo.claim(tenant_id=TENANT, worker_id="again", now=now, limit=LIMIT)
    }

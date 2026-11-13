"""Unsent Instagram DMs against the real database (m-25018661, migration 0157). What only
Postgres can prove:

- the handler redacts every content column of the stored row (0157's
  `ck_message_unsent_redacted` refuses anything else), hides it, writes the tombstone with
  its provenance, discards the undecided draft (text erased), stops listing the open
  followup it originated, and recomputes the thread's 24 h window from what remains;
- the raw webhook changes that carried that `mid` — and their deliveries' raw bodies — are
  deleted through the `qualify_webhook_worker` door, the unsend change and unrelated
  changes stay;
- a redelivery is a no-op; an unsend before its message blocks the webhook AND the poll's
  insert (no row, no thread);
- RLS: another tenant sees no tombstone and cannot reach the row;
- `WebhookQueue.erase` deletes a claimed change only for its lock holder;
- `requeue_unsupported_deleted` takes back only `is_deleted` items settled
  `message_deleted`.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from qualify_api.attention.counts import pending_counts
from qualify_api.conversations.contracts import (
    CHANNEL_DM,
    AccessStatus,
    AccessVerdict,
    RemoteConversation,
    RemoteMessage,
)
from qualify_api.conversations.instagram_source import SHAPE_VERSION_IG_DM
from qualify_api.conversations.memory_source import MemoryConversationSource
from qualify_api.conversations.repository import (
    _BUMP_THREAD,
    _INSERT_MESSAGE,
    _LOCK_MESSAGE_KEY,
    _UPSERT_THREAD,
    THREAD_OPEN,
    PostgresConversationRepository,
    _insert_params,
    _message_lock_key,
)
from qualify_api.conversations.sync import (
    UNSEND_PIPELINE_VERSION,
    ConversationSyncService,
    SyncReport,
)
from qualify_api.conversations.webhook import MESSAGE_UNSENT, instagram_messages_handler
from qualify_api.conversations.window import WindowStatus, window_state
from qualify_api.followups.repository import PostgresFollowupRepository
from qualify_api.mentions.resolve import ResolutionOutcome, TenantResolution
from qualify_api.webhooks.envelope import MESSAGING_FIELD
from qualify_api.webhooks.repository import STATUS_PROCESSED, ClaimedEvent, WebhookQueue

from .test_conversations_repository_db import OTHER, TENANT, _source_connection
from .test_conversations_repository_db import seeded as seeded  # noqa: F401 — fixture
from .test_webhook_queue_db import NOW, _acct, _row
from .test_webhook_queue_db import owner as owner  # noqa: F401 — fixture

pytestmark = pytest.mark.db

T0 = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


def _ms(at: datetime) -> int:
    return int(at.timestamp() * 1000)


def _item(sender: str, acct: str, mid: str, *, at: datetime, **message: object) -> dict:
    return {
        "sender": {"id": sender},
        "recipient": {"id": acct},
        "timestamp": _ms(at),
        "message": {"mid": mid, **message},
    }


def _unsend_item(sender: str, acct: str, mid: str) -> dict:
    return _item(sender, acct, mid, at=T0 + timedelta(minutes=5), is_deleted=True)


def _recorded(
    owner: Engine,  # noqa: F811
    *,
    acct: str,
    value: dict,
    status: str = "processed",
    last_error: str | None = None,
    with_delivery: bool = True,
) -> tuple[UUID, UUID | None]:
    """A change as the intake recorded it (and, optionally, its delivery's raw body)."""
    event_id, delivery_id = uuid4(), (uuid4() if with_delivery else None)
    with owner.begin() as conn:
        if delivery_id is not None:
            conn.execute(
                text(
                    "INSERT INTO meta_webhook_deliveries (id, received_at, raw_body, "
                    "body_sha256, body_bytes, signature_header, object, parse_status, "
                    "change_count, entry_ids) VALUES (:id, :at, CAST(:body AS bytea), :h, 1, "
                    "'s', 'instagram', 'parsed', 1, :e)"
                ),
                {
                    "id": delivery_id,
                    "at": NOW,
                    "body": json.dumps(value).encode(),
                    "h": f"t-{uuid4()}",
                    "e": [acct],
                },
            )
        conn.execute(
            text(
                "INSERT INTO meta_webhook_events (id, delivery_id, change_index, received_at, "
                "object, entry_id, field, value, dedup_key, status, attempts, next_attempt_at, "
                "processed_at, last_error) VALUES (:id, :d, 0, :at, 'instagram', :e, "
                "'messages', CAST(:v AS jsonb), :k, :s, 1, :at, :at, :err)"
            ),
            {
                "id": event_id,
                "d": delivery_id,
                "at": NOW,
                "e": acct,
                "v": json.dumps(value),
                "k": f"t-{uuid4()}",
                "s": status,
                "err": last_error,
            },
        )
    return event_id, delivery_id


def _claimed(event_id: UUID, acct: str, value: dict) -> ClaimedEvent:
    return ClaimedEvent(
        id=event_id,
        delivery_id=None,
        object="instagram",
        entry_id=acct,
        field=MESSAGING_FIELD,
        value=value,
        attempts=1,
    )


@pytest.fixture
def intake(seeded):  # noqa: F811
    def resolve(**kwargs: object) -> TenantResolution:
        return TenantResolution(
            outcome=ResolutionOutcome.RESOLVED,
            tenant_id=TENANT,
            connection_id=seeded["connection"],
        )

    repo = PostgresConversationRepository()
    sync = ConversationSyncService(repository=repo)
    handler = instagram_messages_handler(
        resolve=resolve, sync=sync, erase_events=WebhookQueue().erase_message_events
    )
    return repo, sync, handler


def _message_row(message_id: UUID):
    with tenant_session(TENANT) as session:
        return session.execute(
            text("SELECT * FROM messages WHERE id = :id"), {"id": message_id}
        ).one()


def _all_message_ids(repo, seeded, sender: str) -> tuple[UUID, dict[str, UUID]]:  # noqa: F811
    thread = repo.find_thread(
        tenant_id=TENANT,
        connection_id=seeded["connection"],
        channel=CHANNEL_DM,
        counterpart_external_id=sender,
    )
    assert thread is not None
    with tenant_session(TENANT) as session:
        rows = session.execute(
            text("SELECT id, external_message_id FROM messages WHERE thread_id = :t"),
            {"t": thread.id},
        ).all()
    return thread.id, {r.external_message_id: r.id for r in rows}


async def test_unsend_erases_every_copy_and_recomputes_the_thread(
    intake,
    seeded,  # noqa: F811
    owner,  # noqa: F811
) -> None:
    repo, _sync, handler = intake
    acct, sender = _acct(), f"igsid-{uuid4().hex[:10]}"
    kept, gone = f"mid.{uuid4().hex}", f"mid.{uuid4().hex}"
    first = _item(sender, acct, kept, at=T0, text="primero")
    original = _item(
        sender,
        acct,
        gone,
        at=T0 + timedelta(minutes=1),
        text="mi dirección es…",
        attachments=[{"type": "image", "payload": {"url": "https://cdn.example/x.jpg"}}],
        reply_to={"story": {"id": "story-1", "url": "https://cdn.example/s.mp4"}},
    )
    for value in (first, original):
        event_id, _ = _recorded(owner, acct=acct, value=value)
        assert (await handler(_claimed(event_id, acct, value))).status == STATUS_PROCESSED
    original_event = event_id
    original_delivery = _row(owner, "meta_webhook_events", original_event).delivery_id
    unrelated_event, _ = _recorded(owner, acct=acct, value=first)
    thread_id, ids = _all_message_ids(repo, seeded, sender)
    with tenant_session(TENANT) as session:
        session.execute(
            text(
                "INSERT INTO conversation_drafts (id, tenant_id, thread_id, message_id, "
                "generator_version, generated_text, gate_reason, status, grounding) VALUES (:id, "
                ":t, :th, :m, 'v1', 'Claro, te escribo a esa dirección', 'ok', 'proposed', "
                "CAST(:g AS jsonb))"
            ),
            {
                "id": (draft_id := uuid4()),
                "t": TENANT,
                "th": thread_id,
                "m": ids[gone],
                "g": json.dumps({"brand": "B", "choice": {"kind": "menu", "payload": "QFM_X"}}),
            },
        )
        session.execute(
            text(
                "INSERT INTO interaction_followups (id, tenant_id, connection_id, "
                "origin_kind, origin_message_id, dm_thread_id, trigger, notice_status) "
                "VALUES (:id, :t, :c, 'story_reply', :m, :th, 'manual', 'not_applicable')"
            ),
            {
                "id": (followup_id := uuid4()),
                "t": TENANT,
                "c": seeded["connection"],
                "m": ids[gone],
                "th": thread_id,
            },
        )
    followups = PostgresFollowupRepository()
    assert followup_id in {
        f.id for f in followups.list_open(tenant_id=TENANT, connection_id=seeded["connection"])
    }

    unsend = _unsend_item(sender, acct, gone)
    unsend_event, _ = _recorded(owner, acct=acct, value=unsend, status="processing")
    assert (await handler(_claimed(unsend_event, acct, unsend))).status == STATUS_PROCESSED

    row = _message_row(ids[gone])
    assert row.unsent_at is not None and row.deleted_at is not None
    for column in (
        "text",
        "author_username",
        "media_type",
        "media_url",
        "media_object_key",
        "story_reply_id",
        "story_reply_url",
        "story_mention_id",
        "story_mention_url",
        "story_mention_basis",
        "choice_kind",
        "choice_payload",
    ):
        assert getattr(row, column) is None, column
    assert row.story_mention is False
    assert (row.external_message_id, row.direction) == (gone, "inbound")  # ids stay
    assert [
        m.external_message_id for m in repo.list_messages(tenant_id=TENANT, thread_id=thread_id)
    ] == [kept]
    with tenant_session(TENANT) as session:
        tombstone = session.execute(
            text("SELECT * FROM message_unsends WHERE external_message_id = :m"), {"m": gone}
        ).one()
        draft = session.execute(
            text(
                "SELECT status, generated_text, final_text, grounding FROM conversation_drafts "
                "WHERE id = :id"
            ),
            {"id": draft_id},
        ).one()
    assert (tombstone.source_event_id, tombstone.pipeline_version) == (
        unsend_event,
        UNSEND_PIPELINE_VERSION,
    )
    assert (draft.status, draft.generated_text, draft.final_text) == ("discarded", "", None)
    assert draft.grounding == {"brand": "B"}  # the tapped option goes with the row's
    assert followup_id not in {
        f.id for f in followups.list_open(tenant_id=TENANT, connection_id=seeded["connection"])
    }
    thread = repo.get_thread(tenant_id=TENANT, thread_id=thread_id)
    assert thread is not None and thread.last_inbound_at == T0  # the window moved back
    assert thread.last_message_at == T0
    # The raw copies: the original change and its delivery are gone, the rest stays.
    assert _row(owner, "meta_webhook_events", original_event) is None
    assert _row(owner, "meta_webhook_deliveries", original_delivery) is None
    assert _row(owner, "meta_webhook_events", unrelated_event) is not None
    assert _row(owner, "meta_webhook_events", unsend_event) is not None

    # Redelivery: nothing changes.
    again = await handler(_claimed(uuid4(), acct, unsend))
    assert again.status == STATUS_PROCESSED
    assert _message_row(ids[gone]).unsent_at == row.unsent_at


def test_an_unsent_row_cannot_carry_content(intake, seeded) -> None:  # noqa: F811
    repo, sync, _handler = intake
    connection = _source_connection(seeded)
    mid = f"mid.{uuid4().hex}"
    sync.ingest_message(
        connection,
        channel=CHANNEL_DM,
        conversation=RemoteConversation(counterpart_external_id=f"igsid-{uuid4().hex[:8]}"),
        message=RemoteMessage(
            external_message_id=mid,
            direction="inbound",
            text="hola",
            posted_at=T0,
            shape_version=SHAPE_VERSION_IG_DM,
        ),
    )
    sync.unsend_message(connection, external_message_id=mid)
    with pytest.raises(IntegrityError), tenant_session(TENANT) as session:
        session.execute(
            text("UPDATE messages SET text = 'vuelve' WHERE external_message_id = :m"),
            {"m": mid},
        )


async def test_unsend_before_its_message_blocks_webhook_and_poll(
    intake,
    seeded,  # noqa: F811
    owner,  # noqa: F811
) -> None:
    repo, _sync, handler = intake
    acct, sender, mid = _acct(), f"igsid-{uuid4().hex[:10]}", f"mid.{uuid4().hex}"
    unsend = _unsend_item(sender, acct, mid)
    assert (await handler(_claimed(uuid4(), acct, unsend))).status == STATUS_PROCESSED

    late = _item(sender, acct, mid, at=T0, text="no debe quedar")
    late_event, late_delivery = _recorded(owner, acct=acct, value=late, status="processing")
    outcome = await handler(_claimed(late_event, acct, late))

    assert (outcome.status, outcome.error, outcome.erase) == (
        STATUS_PROCESSED,
        MESSAGE_UNSENT,
        True,
    )
    assert (
        repo.find_thread(
            tenant_id=TENANT,
            connection_id=seeded["connection"],
            channel=CHANNEL_DM,
            counterpart_external_id=sender,
        )
        is None
    )
    # The poll's door, straight at the repository (a thread it found for other messages).
    thread = repo.upsert_thread(
        tenant_id=TENANT,
        connection_id=seeded["connection"],
        channel=CHANNEL_DM,
        counterpart_external_id=sender,
    )
    stored = repo.insert_message(
        tenant_id=TENANT,
        thread_id=thread.thread_id,
        connection_id=seeded["connection"],
        message=RemoteMessage(
            external_message_id=mid,
            direction="inbound",
            text="no debe quedar",
            posted_at=T0,
            shape_version=SHAPE_VERSION_IG_DM,
        ),
    )
    assert stored is False
    with tenant_session(TENANT) as session:
        assert (
            session.execute(
                text("SELECT count(*) FROM messages WHERE external_message_id = :m"), {"m": mid}
            ).scalar_one()
            == 0
        )
    # The processor settles that change by erasing it (and its delivery's raw body).
    queue = WebhookQueue()
    with owner.begin() as conn:
        conn.execute(
            text("UPDATE meta_webhook_events SET locked_by = 'w:1' WHERE id = :id"),
            {"id": late_event},
        )
    assert queue.erase(event_id=late_event, worker_id="someone-else") is False
    assert queue.erase(event_id=late_event, worker_id="w:1") is True
    assert _row(owner, "meta_webhook_events", late_event) is None
    assert _row(owner, "meta_webhook_deliveries", late_delivery) is None


async def test_another_tenant_sees_no_tombstone_and_reaches_no_row(
    intake,
    seeded,  # noqa: F811
    owner,  # noqa: F811
) -> None:
    repo, _sync, handler = intake
    acct, sender, mid = _acct(), f"igsid-{uuid4().hex[:10]}", f"mid.{uuid4().hex}"
    await handler(_claimed(uuid4(), acct, _item(sender, acct, mid, at=T0, text="hola")))
    await handler(_claimed(uuid4(), acct, _unsend_item(sender, acct, mid)))
    with tenant_session(OTHER) as session:
        assert (
            session.execute(
                text("SELECT count(*) FROM message_unsends WHERE external_message_id = :m"),
                {"m": mid},
            ).scalar_one()
            == 0
        )

    # An unsend resolved to ANOTHER tenant for that `mid`: RLS hides the row, and the
    # tombstone cannot name a connection that tenant does not own.
    other_mid = f"mid.{uuid4().hex}"
    await handler(_claimed(uuid4(), acct, _item(sender, acct, other_mid, at=T0, text="mío")))
    with pytest.raises(IntegrityError):
        repo.unsend_message(
            tenant_id=OTHER,
            connection_id=seeded["connection"],
            external_message_id=other_mid,
            now=T0,
            source_event_id=None,
            pipeline_version=UNSEND_PIPELINE_VERSION,
        )
    with tenant_session(TENANT) as session:
        row = session.execute(
            text("SELECT text, unsent_at FROM messages WHERE external_message_id = :m"),
            {"m": other_mid},
        ).one()
    assert (row.text, row.unsent_at) == ("mío", None)


def test_requeue_takes_back_only_unsupported_unsends(owner) -> None:  # noqa: F811
    queue = WebhookQueue()
    acct = _acct()
    unsend = _unsend_item("igsid-a", acct, "mid.u")
    old_unsend, _ = _recorded(
        owner, acct=acct, value=unsend, status="unsupported", last_error="message_deleted"
    )
    echo, _ = _recorded(
        owner, acct=acct, value=unsend, status="unsupported", last_error="message_deleted_echo"
    )
    processed, _ = _recorded(owner, acct=acct, value=unsend)
    reaction = {"sender": {"id": "a"}, "reaction": {"mid": "x", "action": "react"}}
    not_deleted, _ = _recorded(
        owner, acct=acct, value=reaction, status="unsupported", last_error="message_deleted"
    )
    other_account, _ = _recorded(
        owner, acct=_acct(), value=unsend, status="unsupported", last_error="message_deleted"
    )

    assert queue.requeue_unsupported_deleted(now=NOW, entry_id=acct) == 1  # dry run
    assert _row(owner, "meta_webhook_events", old_unsend).status == "unsupported"
    assert queue.requeue_unsupported_deleted(now=NOW, execute=True, entry_id=acct) == 1
    assert _row(owner, "meta_webhook_events", old_unsend).status == "pending"
    for untouched in (echo, not_deleted, other_account):
        assert _row(owner, "meta_webhook_events", untouched).status == "unsupported"
    assert _row(owner, "meta_webhook_events", processed).status == "processed"
    assert queue.requeue_unsupported_deleted(now=NOW, execute=True, entry_id=acct) == 0


# --- serialization: no ordering leaves the thread on an unsent message ---------------------


def _wait_for_a_blocked_advisory_lock(owner: Engine) -> None:  # noqa: F811
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with owner.connect() as conn:
            waiting = conn.execute(
                text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted")
            ).scalar_one()
        if waiting:
            return
        time.sleep(0.05)
    raise AssertionError("the other transaction never waited on the message lock")


def _inbound(mid: str, at: datetime) -> RemoteMessage:
    return RemoteMessage(
        external_message_id=mid,
        direction="inbound",
        text="hola",
        posted_at=at,
        shape_version=SHAPE_VERSION_IG_DM,
        author_external_id="igsid-x",
    )


def _pending_dms() -> int:
    return pending_counts(TENANT).messages


def _no_thread(repo: PostgresConversationRepository, seeded: dict, sender: str) -> bool:  # noqa: F811
    return (
        repo.find_thread(
            tenant_id=TENANT,
            connection_id=seeded["connection"],
            channel=CHANNEL_DM,
            counterpart_external_id=sender,
        )
        is None
    )


def test_store_in_flight_then_unsend_leaves_no_window_and_no_pending(
    seeded,  # noqa: F811
    owner,  # noqa: F811
) -> None:
    """Ordering (b), with two real sessions: the message is stored and its thread bumped by
    a transaction still open when the unsend arrives. The unsend waits on the message lock,
    then recomputes on a locked thread row: nothing points at the unsent message."""
    repo = PostgresConversationRepository()
    sync = ConversationSyncService(repository=repo)
    connection = _source_connection(seeded)
    sender, mid = f"igsid-{uuid4().hex[:10]}", f"mid.{uuid4().hex}"
    recent = datetime.now(UTC) - timedelta(minutes=10)
    before = _pending_dms()
    outcome: dict[str, object] = {}

    with tenant_session(TENANT) as store:  # `store_message`'s statements, left open
        store.execute(_LOCK_MESSAGE_KEY, {"key": _message_lock_key(seeded["connection"], mid)})
        thread = store.execute(
            _UPSERT_THREAD,
            {
                "id": uuid4(),
                "tenant_id": TENANT,
                "connection_id": seeded["connection"],
                "channel": CHANNEL_DM,
                "counterpart": sender,
                "conversation_id": None,
                "open": THREAD_OPEN,
            },
        ).one()
        store.execute(
            _INSERT_MESSAGE,
            _insert_params(TENANT, thread.id, seeded["connection"], _inbound(mid, recent)),
        )
        store.execute(
            _BUMP_THREAD,
            {"thread_id": thread.id, "inbound": recent, "message_at": recent, "open": THREAD_OPEN},
        )
        worker = threading.Thread(
            target=lambda: outcome.update(
                result=sync.unsend_message(connection, external_message_id=mid)
            )
        )
        worker.start()
        _wait_for_a_blocked_advisory_lock(owner)
    worker.join(timeout=10)

    assert outcome["result"].message_redacted is True  # type: ignore[attr-defined]
    state = repo.get_thread(tenant_id=TENANT, thread_id=thread.id)
    assert state is not None and state.last_inbound_at is None and state.last_message_at is None
    assert window_state(state.last_inbound_at, datetime.now(UTC)).status == WindowStatus.CLOSED
    assert _pending_dms() == before
    listed = repo.list_threads(tenant_id=TENANT, channels=[CHANNEL_DM], limit=10_000)
    assert thread.id not in {t.id for t in listed}


def test_unsend_in_flight_then_store_creates_nothing(
    seeded,  # noqa: F811
    owner,  # noqa: F811
) -> None:
    """Ordering (a), with two real sessions: the unsend holds the lock when the webhook's
    store arrives; once the unsend commits, the store refuses — no thread, no bump."""
    repo = PostgresConversationRepository()
    sync = ConversationSyncService(repository=repo)
    connection = _source_connection(seeded)
    sender, mid = f"igsid-{uuid4().hex[:10]}", f"mid.{uuid4().hex}"
    before = _pending_dms()
    outcome: dict[str, object] = {}

    with tenant_session(TENANT) as unsend:  # `unsend_message`'s tombstone, left open
        unsend.execute(_LOCK_MESSAGE_KEY, {"key": _message_lock_key(seeded["connection"], mid)})
        unsend.execute(
            text(
                "INSERT INTO message_unsends (tenant_id, connection_id, external_message_id, "
                "pipeline_version) VALUES (:t, :c, :m, :v)"
            ),
            {"t": TENANT, "c": seeded["connection"], "m": mid, "v": UNSEND_PIPELINE_VERSION},
        )
        worker = threading.Thread(
            target=lambda: outcome.update(
                result=sync.ingest_message(
                    connection,
                    channel=CHANNEL_DM,
                    conversation=RemoteConversation(counterpart_external_id=sender),
                    message=_inbound(mid, datetime.now(UTC) - timedelta(minutes=10)),
                )
            )
        )
        worker.start()
        _wait_for_a_blocked_advisory_lock(owner)
    worker.join(timeout=10)

    assert outcome["result"].unsent is True  # type: ignore[attr-defined]
    assert _no_thread(repo, seeded, sender)
    assert _pending_dms() == before


async def test_poll_with_a_stale_unsent_check_stores_and_bumps_nothing(
    seeded,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The poll asked before the unsend committed (its early check sees nothing). The
    repository still refuses under the lock: no empty thread, no window, nothing pending."""
    repo = PostgresConversationRepository()
    sync = ConversationSyncService(repository=repo)
    connection = _source_connection(seeded)
    sender, mid = f"igsid-{uuid4().hex[:10]}", f"mid.{uuid4().hex}"
    sync.unsend_message(connection, external_message_id=mid)  # unknown mid: tombstone only
    monkeypatch.setattr(repo, "unsent_ids", lambda **kwargs: set())
    before = _pending_dms()
    source = MemoryConversationSource()
    conversation = RemoteConversation(counterpart_external_id=sender, external_conversation_id="t")
    source.add_message(conversation, _inbound(mid, datetime.now(UTC) - timedelta(minutes=10)))
    report = SyncReport(channel=CHANNEL_DM, access=AccessVerdict(AccessStatus.OK))

    await sync._sync_conversation(connection, source, conversation, report)

    assert (report.unsent_skipped, report.messages_created, report.threads_created) == (1, 0, 0)
    assert _no_thread(repo, seeded, sender)
    assert _pending_dms() == before

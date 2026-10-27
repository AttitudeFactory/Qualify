"""`PostgresConversationRepository` + `PostgresConversationOutboxRepository` against the
real database (QUA-226, E1). What only Postgres can prove:

- the SAME `mid` arriving by the single-message door (webhook path) and by the poll is
  one `messages` row (`uq_message_external_id`), and the poll fills the thread's
  conversation id the webhook could not know;
- `bump_thread_activity` never moves `last_inbound_at` backwards and reopens a closed
  thread only on a NEWER inbound;
- the sync state is three narrow upserts that compose into one row;
- `enqueue` writes the approver; `claim` with `FOR UPDATE SKIP LOCKED` never hands the
  same row to two workers; `mark_sent` writes the outbound `messages` row once and bumps
  `last_message_at` only;
- RLS: another tenant reads nothing of any of it.

Seeding follows `test_whatsapp_outbox_repository_db.py`: tenant/user/app via
`admin_session`, the Instagram connection through `tenant_session` (the production door).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.config import app_dsn
from qualify_shared.db.session import tenant_session
from sqlalchemy import create_engine, text

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.conversations.contracts import (
    CHANNEL_DM,
    AccessStatus,
    AccessVerdict,
    RemoteConversation,
    RemoteMessage,
    RemoteProfile,
    SourceConnection,
)
from qualify_api.conversations.drafts import (
    DraftPending,
    DraftStatus,
    InvalidDraftTransition,
    PostgresDraftRepository,
    UnknownDraft,
    new_draft,
)
from qualify_api.conversations.memory_source import (
    SHAPE_VERSION_MEMORY,
    MemoryConversationSource,
)
from qualify_api.conversations.outbox import (
    CLAIM_SQL,
    OUTBOX_SHAPE_VERSION,
    STALE_AFTER,
    HumanApproval,
    PostgresConversationOutboxRepository,
)
from qualify_api.conversations.repository import PostgresConversationRepository
from qualify_api.conversations.sync import ConversationSyncService
from qualify_api.tenancy.models import Tenant, User

pytestmark = pytest.mark.db

TENANT = UUID("a0000000-0000-4000-8000-0000000000c3")
OTHER = UUID("a0000000-0000-4000-8000-0000000000c4")
T0 = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
# Earlier runs leave pending rows in this tenant (the app role cannot DELETE); a claim must
# be wide enough to reach the rows of THIS run.
LIMIT = 10_000


@pytest.fixture
def seeded() -> dict[str, UUID]:
    with admin_session() as session:
        for tenant_id, name in ((TENANT, "conv-repo"), (OTHER, "conv-repo-other")):
            if session.get(Tenant, tenant_id) is None:
                session.add(
                    Tenant(
                        id=tenant_id,
                        name=f"t-{name}",
                        country="CO",
                        timezone="America/Bogota",
                        currency="COP",
                    )
                )
                session.flush()
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        user = User(tenant_id=TENANT, email=f"u-{uuid4()}@conv.co", display_name="U")
        session.add_all([app, user])
        session.flush()
        app_id, user_id = app.id, user.id

    with tenant_session(TENANT) as session:
        connection = SocialConnection(
            tenant_id=TENANT,
            platform_app_id=app_id,
            platform="instagram",
            account_type="business",
            external_account_id=f"ig-{uuid4().hex[:12]}",
            linked_page_id="page-1",
            granted_scopes=["instagram_manage_messages"],
            status="active",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=user_id,
        )
        session.add(connection)
        session.flush()
        return {"connection": connection.id, "user": user_id}


def _source_connection(seeded: dict[str, UUID]) -> SourceConnection:
    return SourceConnection(
        tenant_id=TENANT,
        connection_id=seeded["connection"],
        external_account_id="ig-1",
        linked_page_id="page-1",
    )


def _msg(mid: str, *, at: datetime, direction: str = "inbound") -> RemoteMessage:
    return RemoteMessage(
        external_message_id=mid,
        direction=direction,  # type: ignore[arg-type]
        text="hola",
        posted_at=at,
        shape_version=SHAPE_VERSION_MEMORY,
        author_external_id="igsid-x",
    )


def _counterpart() -> str:
    return f"igsid-{uuid4().hex[:10]}"


# --- threads / messages --------------------------------------------------------------------


async def test_webhook_and_poll_converge_on_one_thread_and_one_message(seeded) -> None:
    repo = PostgresConversationRepository()
    service = ConversationSyncService(repository=repo, clock=lambda: T0 + timedelta(hours=1))
    connection = _source_connection(seeded)
    counterpart = _counterpart()
    mid = f"mid.{uuid4().hex[:8]}"
    message = _msg(mid, at=T0)

    first = service.ingest_message(
        connection,
        channel=CHANNEL_DM,
        conversation=RemoteConversation(counterpart_external_id=counterpart),
        message=message,
    )
    assert first.thread_created and first.message_created

    source = MemoryConversationSource()
    source.add_message(
        RemoteConversation(counterpart_external_id=counterpart, external_conversation_id="t_1"),
        message,
    )
    report = await service.sync_connection(connection, source)
    assert report.threads_created == 0 and report.messages_created == 0 and report.duplicates == 1

    thread = repo.get_thread(tenant_id=TENANT, thread_id=UUID(first.thread_id))
    assert thread is not None
    assert thread.external_conversation_id == "t_1"
    assert thread.last_inbound_at == T0 and thread.status == "open"
    messages = repo.list_messages(tenant_id=TENANT, thread_id=thread.id)
    assert [m.external_message_id for m in messages] == [mid]

    with tenant_session(TENANT) as session:
        count = session.execute(
            text(
                "SELECT count(*) FROM messages "
                "WHERE connection_id = :c AND external_message_id = :m"
            ),
            {"c": seeded["connection"], "m": mid},
        ).scalar_one()
    assert count == 1


def test_bump_is_monotonic_and_reopens_only_on_newer_inbound(seeded) -> None:
    repo = PostgresConversationRepository()
    upsert = repo.upsert_thread(
        tenant_id=TENANT,
        connection_id=seeded["connection"],
        channel=CHANNEL_DM,
        counterpart_external_id=_counterpart(),
    )
    tid = upsert.thread_id
    repo.bump_thread_activity(
        tenant_id=TENANT, thread_id=tid, last_inbound_at=T0, last_message_at=T0
    )
    with tenant_session(TENANT) as session:
        session.execute(text("UPDATE threads SET status = 'closed' WHERE id = :t"), {"t": tid})

    # An OLDER inbound: nothing moves, the thread stays closed.
    repo.bump_thread_activity(
        tenant_id=TENANT,
        thread_id=tid,
        last_inbound_at=T0 - timedelta(hours=1),
        last_message_at=T0 - timedelta(hours=1),
    )
    thread = repo.get_thread(tenant_id=TENANT, thread_id=tid)
    assert thread is not None and thread.last_inbound_at == T0 and thread.status == "closed"

    # An outbound only: `last_message_at` moves, `last_inbound_at` does not, still closed.
    repo.bump_thread_activity(
        tenant_id=TENANT,
        thread_id=tid,
        last_inbound_at=None,
        last_message_at=T0 + timedelta(hours=1),
    )
    thread = repo.get_thread(tenant_id=TENANT, thread_id=tid)
    assert thread is not None
    assert thread.last_inbound_at == T0 and thread.last_message_at == T0 + timedelta(hours=1)
    assert thread.status == "closed"

    # A NEWER inbound reopens.
    repo.bump_thread_activity(
        tenant_id=TENANT,
        thread_id=tid,
        last_inbound_at=T0 + timedelta(hours=2),
        last_message_at=T0 + timedelta(hours=2),
    )
    thread = repo.get_thread(tenant_id=TENANT, thread_id=tid)
    assert thread is not None and thread.status == "open"
    assert thread.last_inbound_at == T0 + timedelta(hours=2)


def test_list_threads_filters_by_channel_and_connection_and_marks_read(seeded) -> None:
    repo = PostgresConversationRepository()
    counterpart = _counterpart()
    tid = repo.upsert_thread(
        tenant_id=TENANT,
        connection_id=seeded["connection"],
        channel=CHANNEL_DM,
        counterpart_external_id=counterpart,
    ).thread_id
    repo.insert_message(
        tenant_id=TENANT,
        thread_id=tid,
        connection_id=seeded["connection"],
        message=_msg(f"mid.{uuid4().hex[:8]}", at=T0),
    )
    repo.bump_thread_activity(
        tenant_id=TENANT, thread_id=tid, last_inbound_at=T0, last_message_at=T0
    )

    listed = repo.list_threads(
        tenant_id=TENANT, channels=[CHANNEL_DM], connection_id=seeded["connection"], limit=LIMIT
    )
    assert any(t.id == tid for t in listed)
    assert all(t.channel == CHANNEL_DM for t in listed)
    assert (
        repo.list_threads(
            tenant_id=TENANT, channels=["whatsapp"], connection_id=seeded["connection"]
        )
        == []
    )
    assert (
        repo.list_threads(tenant_id=TENANT, channels=[], connection_id=seeded["connection"]) == []
    )

    assert repo.mark_read(tenant_id=TENANT, thread_id=tid, now=T0 + timedelta(minutes=1))
    thread = repo.get_thread(tenant_id=TENANT, thread_id=tid)
    assert thread is not None and thread.last_read_at == T0 + timedelta(minutes=1)
    # Monotonic too.
    repo.mark_read(tenant_id=TENANT, thread_id=tid, now=T0)
    thread = repo.get_thread(tenant_id=TENANT, thread_id=tid)
    assert thread is not None and thread.last_read_at == T0 + timedelta(minutes=1)


def test_sync_state_composes_from_three_upserts(seeded) -> None:
    repo = PostgresConversationRepository()
    cid = seeded["connection"]
    assert repo.get_sync_state(tenant_id=TENANT, connection_id=cid, channel=CHANNEL_DM) is None

    repo.sync_started(tenant_id=TENANT, connection_id=cid, channel=CHANNEL_DM, now=T0)
    state = repo.get_sync_state(tenant_id=TENANT, connection_id=cid, channel=CHANNEL_DM)
    assert state is not None and state.access_status == "unknown"
    assert state.last_sync_started_at == T0 and state.last_sync_finished_at is None

    repo.save_access(
        tenant_id=TENANT,
        connection_id=cid,
        channel=CHANNEL_DM,
        verdict=AccessVerdict(AccessStatus.ACCESS_DISABLED, detail="toggle_off"),
        now=T0 + timedelta(seconds=1),
    )
    repo.sync_finished(
        tenant_id=TENANT,
        connection_id=cid,
        channel=CHANNEL_DM,
        now=T0 + timedelta(seconds=2),
        status="failed",
        error="access_disabled",
        cursor=None,
    )
    state = repo.get_sync_state(tenant_id=TENANT, connection_id=cid, channel=CHANNEL_DM)
    assert state is not None
    assert state.access_status == "access_disabled" and state.access_detail == "toggle_off"
    assert state.last_sync_started_at == T0
    assert state.last_sync_finished_at == T0 + timedelta(seconds=2)
    assert state.last_sync_status == "failed" and state.last_sync_error == "access_disabled"

    with pytest.raises(ValueError):
        repo.sync_finished(
            tenant_id=TENANT,
            connection_id=cid,
            channel=CHANNEL_DM,
            now=T0,
            status="running",
            error=None,
            cursor=None,
        )


# --- outbox ---------------------------------------------------------------------------


def _thread_with_inbound(repo: PostgresConversationRepository, seeded: dict[str, UUID]) -> UUID:
    tid = repo.upsert_thread(
        tenant_id=TENANT,
        connection_id=seeded["connection"],
        channel=CHANNEL_DM,
        counterpart_external_id=_counterpart(),
    ).thread_id
    repo.bump_thread_activity(
        tenant_id=TENANT, thread_id=tid, last_inbound_at=T0, last_message_at=T0
    )
    return tid


def _payload(text_: str) -> dict:
    return {"recipient": {"id": "igsid-x"}, "message": {"text": text_}}


def _claim_now() -> datetime:
    """An instant a claim may use. `enqueue` leaves `next_attempt_at` to the database's
    own `now()` (the row is due immediately), so a claim must pass a `now` AFTER the real
    clock — a fixed `T0 + 1 min` was due only while the wall clock was before it, which
    made these tests pass on the morning of 2026-10-16 and fail that same afternoon."""
    return datetime.now(UTC) + timedelta(minutes=1)


def test_enqueue_records_the_approver_and_claim_marks_sent_once(seeded) -> None:
    repo = PostgresConversationRepository()
    outbox = PostgresConversationOutboxRepository()
    tid = _thread_with_inbound(repo, seeded)
    approval = HumanApproval(user_id=seeded["user"], approved_at=T0, draft_id=uuid4())

    item_id = outbox.enqueue(
        tenant_id=TENANT,
        connection_id=seeded["connection"],
        thread_id=tid,
        channel=CHANNEL_DM,
        payload=_payload("Sí, tenemos M."),
        approval=approval,
    )
    [row] = outbox.list_for_thread(tenant_id=TENANT, thread_id=tid)
    assert row.id == item_id and row.status == "pending"
    assert row.approved_by_user_id == seeded["user"] and row.draft_id == approval.draft_id

    now = _claim_now()
    claimed = outbox.claim(tenant_id=TENANT, worker_id="w1", now=now, limit=LIMIT)
    mine = [c for c in claimed if c.id == item_id]
    assert len(mine) == 1 and mine[0].payload == _payload("Sí, tenemos M.")
    assert mine[0].thread_id == tid and mine[0].channel == CHANNEL_DM

    mid = f"mid.{uuid4().hex[:8]}"
    outbox.mark_sent(tenant_id=TENANT, item_id=item_id, external_message_id=mid, now=now)
    outbox.mark_sent(tenant_id=TENANT, item_id=item_id, external_message_id=mid, now=now)  # no-op

    [row] = outbox.list_for_thread(tenant_id=TENANT, thread_id=tid)
    assert row.status == "sent" and row.external_message_id == mid and row.sent_at == now

    messages = repo.list_messages(tenant_id=TENANT, thread_id=tid)
    outbound = [m for m in messages if m.direction == "outbound"]
    assert len(outbound) == 1
    assert outbound[0].external_message_id == mid and outbound[0].text == "Sí, tenemos M."
    assert outbound[0].delivery_status == "sent"
    with tenant_session(TENANT) as session:
        shape = session.execute(
            text("SELECT shape_version FROM messages WHERE external_message_id = :m"), {"m": mid}
        ).scalar_one()
    assert shape == OUTBOX_SHAPE_VERSION

    thread = repo.get_thread(tenant_id=TENANT, thread_id=tid)
    assert thread is not None
    assert thread.last_message_at == now  # bumped
    assert thread.last_inbound_at == T0  # never by a send (0004's B2 condition)
    assert thread.last_outbound_at == now


def test_claim_skips_rows_locked_by_another_worker(seeded) -> None:
    repo = PostgresConversationRepository()
    outbox = PostgresConversationOutboxRepository()
    tid = _thread_with_inbound(repo, seeded)
    approval = HumanApproval(user_id=seeded["user"], approved_at=T0)
    ids = {
        outbox.enqueue(
            tenant_id=TENANT,
            connection_id=seeded["connection"],
            thread_id=tid,
            channel=CHANNEL_DM,
            payload=_payload(f"m{i}"),
            approval=approval,
        )
        for i in range(3)
    }
    now = _claim_now()
    engine = create_engine(app_dsn())
    try:
        with engine.connect() as held:
            trans = held.begin()
            held.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(TENANT)})
            first = held.execute(
                CLAIM_SQL, {"now": now, "stale": now - STALE_AFTER, "limit": LIMIT, "worker": "w1"}
            ).all()
            first_ids = {r.id for r in first}
            # The first worker's transaction is still open: a second claim must see none of them.
            second = outbox.claim(tenant_id=TENANT, worker_id="w2", now=now, limit=LIMIT)
            assert first_ids & {c.id for c in second} == set()
            assert ids <= first_ids
            trans.rollback()
    finally:
        engine.dispose()


def test_retry_failed_dead_are_status_guarded(seeded) -> None:
    repo = PostgresConversationRepository()
    outbox = PostgresConversationOutboxRepository()
    tid = _thread_with_inbound(repo, seeded)
    approval = HumanApproval(user_id=seeded["user"], approved_at=T0)
    item_id = outbox.enqueue(
        tenant_id=TENANT,
        connection_id=seeded["connection"],
        thread_id=tid,
        channel=CHANNEL_DM,
        payload=_payload("x"),
        approval=approval,
    )
    # Not claimed yet: settles are no-ops.
    outbox.mark_failed(tenant_id=TENANT, item_id=item_id, error_code="nope")
    [row] = outbox.list_for_thread(tenant_id=TENANT, thread_id=tid)
    assert row.status == "pending"

    now = _claim_now()
    outbox.claim(tenant_id=TENANT, worker_id="w1", now=now, limit=LIMIT)
    outbox.mark_retry(
        tenant_id=TENANT,
        item_id=item_id,
        attempts=1,
        error_code="transport",
        next_attempt_at=now + timedelta(seconds=4),
    )
    [row] = outbox.list_for_thread(tenant_id=TENANT, thread_id=tid)
    assert row.status == "pending" and row.attempts == 1 and row.error_code == "transport"

    # Not due yet, so not claimed; due afterwards.
    assert item_id not in {
        c.id for c in outbox.claim(tenant_id=TENANT, worker_id="w1", now=now, limit=LIMIT)
    }
    later = now + timedelta(seconds=5)
    assert item_id in {
        c.id for c in outbox.claim(tenant_id=TENANT, worker_id="w1", now=later, limit=LIMIT)
    }
    outbox.mark_dead(tenant_id=TENANT, item_id=item_id, error_code="auth", attempts=2)
    [row] = outbox.list_for_thread(tenant_id=TENANT, thread_id=tid)
    assert row.status == "dead" and row.attempts == 2 and row.error_code == "auth"


def test_other_tenant_reads_nothing(seeded) -> None:
    repo = PostgresConversationRepository()
    outbox = PostgresConversationOutboxRepository()
    tid = _thread_with_inbound(repo, seeded)
    outbox.enqueue(
        tenant_id=TENANT,
        connection_id=seeded["connection"],
        thread_id=tid,
        channel=CHANNEL_DM,
        payload=_payload("x"),
        approval=HumanApproval(user_id=seeded["user"], approved_at=T0),
    )
    repo.sync_started(
        tenant_id=TENANT, connection_id=seeded["connection"], channel=CHANNEL_DM, now=T0
    )

    assert repo.get_thread(tenant_id=OTHER, thread_id=tid) is None
    assert repo.list_messages(tenant_id=OTHER, thread_id=tid) == []
    assert all(
        t.id != tid for t in repo.list_threads(tenant_id=OTHER, channels=[CHANNEL_DM], limit=LIMIT)
    )
    assert outbox.list_for_thread(tenant_id=OTHER, thread_id=tid) == []
    assert all(
        c.thread_id != tid
        for c in outbox.claim(
            tenant_id=OTHER, worker_id="w", now=T0 + timedelta(days=1), limit=LIMIT
        )
    )
    assert (
        repo.get_sync_state(tenant_id=OTHER, connection_id=seeded["connection"], channel=CHANNEL_DM)
        is None
    )
    assert not repo.mark_read(tenant_id=OTHER, thread_id=tid, now=T0)


# --- second pass: the counterpart's profile and the drafts table ------------------------------


def test_profile_is_saved_without_erasing_what_a_previous_one_knew(seeded) -> None:
    repo = PostgresConversationRepository()
    tid = _thread_with_inbound(repo, seeded)
    assert repo.get_thread(tenant_id=TENANT, thread_id=tid).counterpart_profile_at is None

    repo.save_profile(
        tenant_id=TENANT,
        thread_id=tid,
        profile=RemoteProfile(name="Yesika Roa", username="yesii_roa", avatar_url="https://p/1"),
        now=T0,
    )
    thread = repo.get_thread(tenant_id=TENANT, thread_id=tid)
    assert (thread.counterpart_name, thread.counterpart_username) == ("Yesika Roa", "yesii_roa")
    assert thread.counterpart_avatar_url == "https://p/1" and thread.counterpart_profile_at == T0

    # A later fetch that knows less (no picture) keeps the old picture, moves the instant.
    repo.save_profile(
        tenant_id=TENANT,
        thread_id=tid,
        profile=RemoteProfile(username="yesii_roa"),
        now=T0 + timedelta(days=1),
    )
    thread = repo.get_thread(tenant_id=TENANT, thread_id=tid)
    assert (
        thread.counterpart_name == "Yesika Roa" and thread.counterpart_avatar_url == "https://p/1"
    )
    assert thread.counterpart_profile_at == T0 + timedelta(days=1)
    # Another tenant neither sees nor changes it.
    repo.save_profile(tenant_id=OTHER, thread_id=tid, profile=RemoteProfile(name="X"), now=T0)
    assert repo.get_thread(tenant_id=TENANT, thread_id=tid).counterpart_name == "Yesika Roa"


def _inbound_message_id(repo: PostgresConversationRepository, tid: UUID, seeded) -> UUID:
    repo.insert_message(
        tenant_id=TENANT,
        thread_id=tid,
        connection_id=seeded["connection"],
        message=_msg(f"mid.{uuid4().hex[:8]}", at=T0),
    )
    return repo.list_messages(tenant_id=TENANT, thread_id=tid)[-1].id


def test_drafts_one_proposed_per_message_decided_once_under_rls(seeded) -> None:
    repo = PostgresConversationRepository()
    drafts = PostgresDraftRepository()
    tid = _thread_with_inbound(repo, seeded)
    mid = _inbound_message_id(repo, tid, seeded)

    draft = drafts.create(
        new_draft(
            tenant_id=TENANT,
            thread_id=tid,
            message_id=mid,
            generator_version="qua226.1:claude-haiku-5-5",
            generated_text="¡Hola! Sí, hay talla M.",
            gate_reason="inbound_text",
            needs_review=True,
            now=T0,
            model_id="claude-haiku-5-5",
            model_revision="claude-haiku-5-5-20260901",
            input_tokens=300,
            output_tokens=40,
            cost_usd=0.00005,
            grounding={"business_name": "Bianki", "products": [], "unsupported_claims": ["env"]},
        )
    )
    stored = drafts.get(tenant_id=TENANT, draft_id=draft.id)
    assert stored is not None and stored.status is DraftStatus.PROPOSED
    assert stored.needs_review and stored.grounding["unsupported_claims"] == ["env"]
    assert (stored.model_id, stored.input_tokens, stored.output_tokens) == (
        "claude-haiku-5-5",
        300,
        40,
    )
    assert stored.cost_usd == pytest.approx(0.00005)
    assert [d.id for d in drafts.list_pending(tenant_id=TENANT, thread_id=tid)] == [draft.id]

    with pytest.raises(DraftPending):
        drafts.create(
            new_draft(
                tenant_id=TENANT,
                thread_id=tid,
                message_id=mid,
                generator_version="v",
                generated_text="otra",
                gate_reason="inbound_text",
            )
        )

    edited = drafts.decide(
        tenant_id=TENANT,
        draft_id=draft.id,
        status=DraftStatus.EDITED,
        final_text="¡Hola! Sí, hay M.",
        decided_by_user_id=seeded["user"],
        now=T0 + timedelta(minutes=1),
    )
    assert edited.status is DraftStatus.EDITED and edited.final_text == "¡Hola! Sí, hay M."
    again = drafts.get(tenant_id=TENANT, draft_id=draft.id)
    assert again is not None and again.decided_by_user_id == seeded["user"]
    with pytest.raises(InvalidDraftTransition):
        drafts.decide(
            tenant_id=TENANT,
            draft_id=draft.id,
            status=DraftStatus.ACCEPTED,
            final_text=None,
            decided_by_user_id=seeded["user"],
            now=T0,
        )
    assert drafts.list_pending(tenant_id=TENANT, thread_id=tid) == []
    # Discarded → a new suggestion for the same message is allowed again.
    second = drafts.create(
        new_draft(
            tenant_id=TENANT,
            thread_id=tid,
            message_id=mid,
            generator_version="v",
            generated_text="v2",
            gate_reason="inbound_text",
        )
    )
    assert second.id != draft.id

    # RLS: the other tenant sees nothing and cannot decide.
    assert drafts.get(tenant_id=OTHER, draft_id=draft.id) is None
    assert drafts.list_pending(tenant_id=OTHER, thread_id=tid) == []
    with pytest.raises(UnknownDraft):
        drafts.decide(
            tenant_id=OTHER,
            draft_id=second.id,
            status=DraftStatus.DISCARDED,
            final_text=None,
            decided_by_user_id=seeded["user"],
            now=T0,
        )


def test_hide_message_is_per_tenant_and_idempotent(seeded) -> None:
    repo = PostgresConversationRepository()
    tid = _thread_with_inbound(repo, seeded)
    mid = _inbound_message_id(repo, tid, seeded)
    assert repo.hide_message(tenant_id=OTHER, thread_id=tid, message_id=mid, now=T0) is False
    assert [m.id for m in repo.list_messages(tenant_id=TENANT, thread_id=tid)] == [mid]
    assert repo.hide_message(tenant_id=TENANT, thread_id=tid, message_id=mid, now=T0) is True
    assert repo.list_messages(tenant_id=TENANT, thread_id=tid) == []
    assert repo.hide_message(tenant_id=TENANT, thread_id=tid, message_id=mid, now=T0) is False


def test_disconnected_connection_preserves_approved_pending_reply_until_reconnect(seeded) -> None:
    repo = PostgresConversationRepository()
    outbox = PostgresConversationOutboxRepository()
    tid = _thread_with_inbound(repo, seeded)
    item_id = outbox.enqueue(
        tenant_id=TENANT,
        connection_id=seeded["connection"],
        thread_id=tid,
        channel=CHANNEL_DM,
        payload=_payload("approved before disconnect"),
        approval=HumanApproval(user_id=seeded["user"], approved_at=T0),
    )
    with tenant_session(TENANT) as session:
        session.get(SocialConnection, seeded["connection"]).status = "degraded"
    now = _claim_now()
    assert item_id not in {
        item.id for item in outbox.claim(tenant_id=TENANT, worker_id="paused", now=now, limit=LIMIT)
    }
    [row] = outbox.list_for_thread(tenant_id=TENANT, thread_id=tid)
    assert row.status == "pending" and row.approved_by_user_id == seeded["user"]
    with tenant_session(TENANT) as session:
        session.get(SocialConnection, seeded["connection"]).status = "active"
    claimed = outbox.claim(tenant_id=TENANT, worker_id="resumed", now=now, limit=LIMIT)
    assert len([item for item in claimed if item.id == item_id]) == 1
    assert item_id not in {
        item.id for item in outbox.claim(tenant_id=TENANT, worker_id="again", now=now, limit=LIMIT)
    }

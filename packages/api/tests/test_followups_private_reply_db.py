"""The private reply against Postgres (m-24789646, PR 2): migration 0072's CHECK and
one-live-reply-per-comment index, the Postgres outbox carrying the comment, the deadline
and Meta's recipient, the origin reader, and the followup service end to end.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from psycopg.errors import CheckViolation
from qualify_shared.db.session import tenant_session
from sqlalchemy.exc import IntegrityError

from qualify_api.conversations.contracts import CHANNEL_DM, ChannelRegistry
from qualify_api.conversations.memory_source import MemoryConversationSender
from qualify_api.conversations.models import ConversationOutboxItem
from qualify_api.conversations.outbox import (
    KIND_PRIVATE_REPLY,
    HumanApproval,
    PostgresConversationOutboxRepository,
    PrivateReplyExists,
    PrivateReplyTarget,
)
from qualify_api.conversations.repository import PostgresConversationRepository
from qualify_api.followups import (
    Capabilities,
    Capability,
    FollowupService,
    FollowupStatus,
    FollowupTrigger,
    InvalidFollowupTransition,
    OriginKind,
    PostgresFollowupRepository,
    PostgresOriginReader,
    SendRoute,
    new_followup,
)

from .test_followups_schema_db import NOW, seed_world

pytestmark = pytest.mark.db

# A tenant of its own: the claims below take every due row of the tenant, and must not
# take (and flip to `sending`) the rows other test modules seeded.
TENANT = UUID("a0000000-0000-4000-8000-0000000000d1")
OTHER = UUID("a0000000-0000-4000-8000-0000000000d2")

DEADLINE = NOW + timedelta(days=7)


@pytest.fixture
def seeded() -> dict[str, UUID]:
    return seed_world(TENANT, OTHER)


def _due() -> datetime:
    """`next_attempt_at` defaults to the database's real `now()`, so a claim must look
    past the wall clock, not past the fixed `NOW` of these rows."""
    return datetime.now(UTC) + timedelta(hours=1)


def _row(seeded: dict[str, UUID], **overrides: object) -> ConversationOutboxItem:
    values = dict(
        tenant_id=TENANT,
        connection_id=seeded["connection"],
        thread_id=seeded["dm_thread"],
        channel="dm",
        kind="private_reply",
        payload={"recipient": {"comment_id": "c"}, "message": {"text": "hola"}},
        approved_by_user_id=seeded["user"],
        approved_at=NOW,
        comment_id=f"c-{uuid4().hex[:8]}",
        reply_deadline=DEADLINE,
    )
    values.update(overrides)
    return ConversationOutboxItem(**values)


@pytest.mark.parametrize(
    "overrides",
    [
        {"comment_id": None},
        {"reply_deadline": None},
        {"kind": "reply"},  # a normal reply carries no comment
        {"kind": "automation"},
    ],
)
def test_a_private_reply_row_is_complete_and_only_a_private_reply_has_one(
    seeded: dict[str, UUID],
    overrides: dict[str, object],
) -> None:
    with pytest.raises(IntegrityError) as exc, tenant_session(TENANT) as session:
        session.add(_row(seeded, **overrides))
        session.flush()
    assert isinstance(exc.value.orig, CheckViolation)


def _enqueue(
    outbox: PostgresConversationOutboxRepository, seeded: dict[str, UUID], comment_id: str
) -> UUID:
    return outbox.enqueue(
        tenant_id=TENANT,
        connection_id=seeded["connection"],
        thread_id=seeded["dm_thread"],
        channel=CHANNEL_DM,
        payload={"recipient": {"comment_id": comment_id}, "message": {"text": "hola"}},
        approval=HumanApproval(user_id=seeded["user"], approved_at=NOW),
        private_reply=PrivateReplyTarget(comment_id, DEADLINE),
    )


def test_postgres_outbox_round_trips_a_private_reply(seeded: dict[str, UUID]) -> None:
    outbox = PostgresConversationOutboxRepository()
    comment_id = f"c-{uuid4().hex[:8]}"
    item_id = _enqueue(outbox, seeded, comment_id)
    with pytest.raises(PrivateReplyExists):
        _enqueue(outbox, seeded, comment_id)

    claimed = [
        i
        for i in outbox.claim(tenant_id=TENANT, worker_id="t", now=_due(), limit=10_000)
        if i.id == item_id
    ]
    assert [(i.kind, i.reply_deadline) for i in claimed] == [(KIND_PRIVATE_REPLY, DEADLINE)]
    outbox.mark_sent(
        tenant_id=TENANT,
        item_id=item_id,
        external_message_id=f"aWdf-{uuid4().hex[:6]}",
        now=NOW + timedelta(hours=1),
        recipient_external_id="igsid-ana",
    )
    [record] = [
        r
        for r in outbox.list_for_thread(tenant_id=TENANT, thread_id=seeded["dm_thread"])
        if r.id == item_id
    ]
    assert (record.status, record.kind, record.comment_id) == (
        "sent",
        KIND_PRIVATE_REPLY,
        comment_id,
    )
    assert (record.reply_deadline, record.recipient_external_id) == (DEADLINE, "igsid-ana")
    # Sent: Meta took its one reply for this comment, so nothing more is accepted.
    with pytest.raises(PrivateReplyExists):
        _enqueue(outbox, seeded, comment_id)


def test_a_failed_private_reply_does_not_block_another(seeded: dict[str, UUID]) -> None:
    outbox = PostgresConversationOutboxRepository()
    comment_id = f"c-{uuid4().hex[:8]}"
    item_id = _enqueue(outbox, seeded, comment_id)
    outbox.claim(tenant_id=TENANT, worker_id="t", now=_due(), limit=10_000)
    outbox.mark_failed(tenant_id=TENANT, item_id=item_id, error_code="private_reply_expired")
    assert _enqueue(outbox, seeded, comment_id) != item_id


def test_the_origin_reader_reads_a_comment_with_its_channel(seeded: dict[str, UUID]) -> None:
    origin = PostgresOriginReader().get(tenant_id=TENANT, message_id=seeded["comment"])
    assert origin is not None
    assert (origin.channel, origin.direction, origin.deleted) == ("comment", "inbound", False)
    assert origin.author_external_id and origin.author_external_id.startswith("igsid-")
    assert origin.posted_at == NOW
    assert PostgresOriginReader().get(tenant_id=OTHER, message_id=seeded["comment"]) is None


def test_the_service_opens_and_queues_a_private_reply_in_postgres(seeded: dict[str, UUID]) -> None:
    registry = ChannelRegistry()
    registry.register(sender=MemoryConversationSender())
    service = FollowupService(
        followups=PostgresFollowupRepository(),
        origins=PostgresOriginReader(),
        conversations=PostgresConversationRepository(),
        outbox=PostgresConversationOutboxRepository(),
        registry=registry,
        capabilities=Capabilities(frozenset({Capability.COMMENT_PRIVATE_REPLY})),
        clock=lambda: NOW + timedelta(hours=1),
    )
    opening = service.open_for_interaction(
        tenant_id=TENANT,
        origin_message_id=seeded["comment"],
        trigger=FollowupTrigger.INTENT,
        intent_result_id=seeded["intent"],
    )
    assert opening.followup.dm_thread_id is None  # nothing created before a decision
    approved = service.approve_and_queue(
        tenant_id=TENANT,
        followup_id=opening.followup.id,
        text="Hola, cuesta 50.000",
        approval=HumanApproval(user_id=seeded["user"], approved_at=NOW + timedelta(hours=1)),
    )
    assert approved.status is FollowupStatus.APPROVED
    assert approved.send_route is SendRoute.PRIVATE_REPLY
    # The author already had a DM thread (keyed by the comment's `from.id`): it is reused.
    assert approved.dm_thread_id == seeded["dm_thread"]
    stored = PostgresFollowupRepository().get(tenant_id=TENANT, followup_id=approved.id)
    assert stored is not None and stored.outbox_id == approved.outbox_id
    assert stored.dm_thread_id == seeded["dm_thread"]
    [record] = [
        r
        for r in PostgresConversationOutboxRepository().list_for_thread(
            tenant_id=TENANT, thread_id=seeded["dm_thread"]
        )
        if r.id == approved.outbox_id
    ]
    assert record.kind == KIND_PRIVATE_REPLY
    assert record.reply_deadline == DEADLINE
    assert record.payload["recipient"]["comment_id"] == record.comment_id


def test_a_lost_race_rolls_the_queued_send_back(seeded: dict[str, UUID]) -> None:
    """The guarded transition runs inside the outbox insert's transaction: when it loses
    (the followup was decided meanwhile), the insert is rolled back with it."""
    outbox = PostgresConversationOutboxRepository()
    followups = PostgresFollowupRepository()
    followup = followups.open(
        new_followup(
            tenant_id=TENANT,
            connection_id=seeded["connection"],
            origin_kind=OriginKind.COMMENT,
            origin_message_id=seeded["comment"],
            trigger=FollowupTrigger.MANUAL,
            now=NOW,
        )
    ).followup
    followups.discard(
        tenant_id=TENANT, followup_id=followup.id, decided_by_user_id=seeded["user"], now=NOW
    )
    comment_id = f"c-{uuid4().hex[:8]}"

    def approve(session: object, outbox_id: UUID) -> None:
        followups.approve(
            tenant_id=TENANT,
            followup_id=followup.id,
            outbox_id=outbox_id,
            send_route=SendRoute.PRIVATE_REPLY,
            dm_thread_id=seeded["dm_thread"],
            decided_by_user_id=seeded["user"],
            now=NOW,
            session=session,
        )

    with pytest.raises(InvalidFollowupTransition):
        outbox.enqueue(
            tenant_id=TENANT,
            connection_id=seeded["connection"],
            thread_id=seeded["dm_thread"],
            channel=CHANNEL_DM,
            payload={"recipient": {"comment_id": comment_id}, "message": {"text": "hola"}},
            approval=HumanApproval(user_id=seeded["user"], approved_at=NOW),
            private_reply=PrivateReplyTarget(comment_id, DEADLINE),
            on_enqueued=approve,
        )
    assert not [
        r
        for r in outbox.list_for_thread(tenant_id=TENANT, thread_id=seeded["dm_thread"])
        if r.comment_id == comment_id
    ]

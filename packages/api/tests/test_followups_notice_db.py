"""The public notice against Postgres (m-24789646, PR 4): migration 0074's `posting` state
and lock, the guarded claim and settles of `PostgresNoticeRepository`, 0071's unique
`(connection_id, notice_external_id)` and its CHECK «posted ⇔ notice_external_id».
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from psycopg.errors import CheckViolation, UniqueViolation
from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from qualify_api.conversations.contracts import CHANNEL_DM
from qualify_api.conversations.outbox import (
    HumanApproval,
    PostgresConversationOutboxRepository,
    PrivateReplyTarget,
)
from qualify_api.followups import (
    FollowupTrigger,
    NoticeStatus,
    OriginKind,
    PostgresFollowupRepository,
    SendRoute,
    new_followup,
)
from qualify_api.followups.notice import (
    DEFAULT_NOTICE_TEXT,
    ERROR_NOTICE_AMBIGUOUS,
    NOTICE_STALE_AFTER,
    MemoryCommentReplyClient,
    MemoryNoticeClientFactory,
    PostgresNoticeRepository,
    PublicNoticePoster,
)
from qualify_api.inbox.models import Message

from .test_followups_schema_db import NOW, seed_world

pytestmark = pytest.mark.db

# A tenant of its own: the claims below take every due notice of the tenant.
TENANT = UUID("a0000000-0000-4000-8000-0000000000f1")
OTHER = UUID("a0000000-0000-4000-8000-0000000000f2")


@pytest.fixture
def seeded() -> dict[str, UUID]:
    return seed_world(TENANT, OTHER)


def _wall() -> datetime:
    """`next_attempt_at` of the outbox defaults to the database's real `now()`."""
    return datetime.now(UTC) + timedelta(hours=1)


def _comment(seeded: dict[str, UUID]) -> tuple[UUID, str]:
    """Another comment in the seeded comment thread (one followup per interaction)."""
    external = f"c-{uuid4().hex[:10]}"
    with tenant_session(TENANT) as session:
        thread_id = session.execute(
            text("SELECT thread_id FROM messages WHERE id = :id"), {"id": seeded["comment"]}
        ).scalar_one()
        message = Message(
            tenant_id=TENANT,
            thread_id=thread_id,
            connection_id=seeded["connection"],
            external_message_id=external,
            direction="inbound",
            author_external_id="igsid-x",
            text="¿precio?",
            posted_at=NOW,
            shape_version="test",
        )
        session.add(message)
        session.flush()
        return message.id, external


def _approved_with_notice(
    seeded: dict[str, UUID], *, sent: bool = True, message_id: UUID | None = None
) -> UUID:
    """A comment's followup approved with a notice, its private reply queued and — when
    `sent` — delivered by a claim + `mark_sent`. Returns the followup id."""
    message_id = message_id or _comment(seeded)[0]
    followups = PostgresFollowupRepository()
    outbox = PostgresConversationOutboxRepository()
    followup = followups.open(
        new_followup(
            tenant_id=TENANT,
            connection_id=seeded["connection"],
            origin_kind=OriginKind.COMMENT,
            origin_message_id=message_id,
            trigger=FollowupTrigger.MANUAL,
            now=NOW,
        )
    ).followup
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
            notice_text=DEFAULT_NOTICE_TEXT,
            session=session,
        )

    item_id = outbox.enqueue(
        tenant_id=TENANT,
        connection_id=seeded["connection"],
        thread_id=seeded["dm_thread"],
        channel=CHANNEL_DM,
        payload={"recipient": {"comment_id": comment_id}, "message": {"text": "hola"}},
        approval=HumanApproval(user_id=seeded["user"], approved_at=NOW),
        private_reply=PrivateReplyTarget(comment_id, NOW + timedelta(days=7)),
        on_enqueued=approve,
    )
    if sent:
        claimed = outbox.claim(tenant_id=TENANT, worker_id="t", now=_wall(), limit=10_000)
        assert item_id in {i.id for i in claimed}
        outbox.mark_sent(
            tenant_id=TENANT,
            item_id=item_id,
            external_message_id=f"aWdf-{uuid4().hex[:8]}",
            now=NOW + timedelta(minutes=1),
        )
    return followup.id


def _get(followup_id: UUID):
    row = PostgresFollowupRepository().get(tenant_id=TENANT, followup_id=followup_id)
    assert row is not None
    return row


def _drain(repo: PostgresNoticeRepository) -> None:
    """Settle whatever another test of this module left claimable, so each test counts
    only its own rows."""
    for item in repo.claim(tenant_id=TENANT, worker_id="drain", now=_wall(), limit=10_000):
        repo.mark_failed(
            tenant_id=TENANT, followup_id=item.followup_id, attempts=0, error_code="x", now=NOW
        )


def test_the_claim_takes_a_confirmed_notice_once(seeded: dict[str, UUID]) -> None:
    repo = PostgresNoticeRepository()
    _drain(repo)
    message_id, comment_external = _comment(seeded)
    followup_id = _approved_with_notice(seeded, message_id=message_id)
    waiting = _approved_with_notice(seeded, sent=False)

    first = repo.claim(tenant_id=TENANT, worker_id="a", now=_wall())
    assert [(c.followup_id, c.comment_external_id, c.text) for c in first] == [
        (followup_id, comment_external, DEFAULT_NOTICE_TEXT)
    ]
    assert repo.claim(tenant_id=TENANT, worker_id="b", now=_wall()) == []
    assert repo.claim(tenant_id=OTHER, worker_id="c", now=_wall()) == []
    row = _get(followup_id)
    assert row.notice_status is NoticeStatus.POSTING and row.notice_locked_at is not None
    # The message not yet sent stays waiting.
    assert _get(waiting).notice_status is NoticeStatus.PENDING

    assert repo.mark_posted(
        tenant_id=TENANT, followup_id=followup_id, external_id="1789-a", attempts=1, now=NOW
    )
    # A late or duplicate settle is a no-op.
    assert not repo.mark_failed(
        tenant_id=TENANT, followup_id=followup_id, attempts=2, error_code="x", now=NOW
    )
    posted = _get(followup_id)
    assert (posted.notice_status, posted.notice_external_id) == (NoticeStatus.POSTED, "1789-a")
    assert posted.notice_locked_at is None and posted.notice_attempts == 1


def test_a_failed_message_skips_its_notice(seeded: dict[str, UUID]) -> None:
    repo = PostgresNoticeRepository()
    outbox = PostgresConversationOutboxRepository()
    followup_id = _approved_with_notice(seeded, sent=False)
    outbox_id = _get(followup_id).outbox_id
    assert outbox.claim(tenant_id=TENANT, worker_id="t", now=_wall(), limit=10_000)
    outbox.mark_failed(tenant_id=TENANT, item_id=outbox_id, error_code="send_ambiguous")

    assert repo.skip_unsent(tenant_id=TENANT, now=NOW) >= 1
    row = _get(followup_id)
    assert (row.notice_status, row.notice_error_code) == (
        NoticeStatus.SKIPPED,
        "dm_failed:send_ambiguous",
    )
    assert followup_id not in {
        c.followup_id for c in repo.claim(tenant_id=TENANT, worker_id="t", now=_wall())
    }


def test_retry_waits_for_its_backoff_and_a_stale_claim_is_ambiguous(
    seeded: dict[str, UUID],
) -> None:
    repo = PostgresNoticeRepository()
    _drain(repo)
    followup_id = _approved_with_notice(seeded)
    now = _wall()
    [item] = repo.claim(tenant_id=TENANT, worker_id="a", now=now)
    assert repo.mark_retry(
        tenant_id=TENANT,
        followup_id=item.followup_id,
        attempts=1,
        error_code="http_503_code_None",
        next_attempt_at=now + timedelta(minutes=5),
        now=now,
    )
    assert repo.claim(tenant_id=TENANT, worker_id="a", now=now + timedelta(minutes=4)) == []
    later = now + timedelta(minutes=5)
    [again] = repo.claim(tenant_id=TENANT, worker_id="a", now=later)
    assert again.attempts == 1

    # The worker dies mid-post: past the stale limit the row is failed, never re-claimed.
    stale = later + NOTICE_STALE_AFTER + timedelta(seconds=1)
    assert repo.claim(tenant_id=TENANT, worker_id="b", now=stale) == []
    row = _get(followup_id)
    assert (row.notice_status, row.notice_error_code) == (
        NoticeStatus.FAILED,
        ERROR_NOTICE_AMBIGUOUS,
    )


async def test_the_poster_end_to_end_posts_once(seeded: dict[str, UUID]) -> None:
    repo = PostgresNoticeRepository()
    _drain(repo)
    message_id, comment_external = _comment(seeded)
    followup_id = _approved_with_notice(seeded, message_id=message_id)
    client = MemoryCommentReplyClient()

    def poster() -> PublicNoticePoster:
        return PublicNoticePoster(
            notices=repo,
            clients=MemoryNoticeClientFactory(client),
            enabled=True,
            worker_id="t",
            clock=_wall,
        )

    first = await poster().run_once(TENANT)
    second = await poster().run_once(TENANT)
    assert (first.posted, second.claimed) == (1, 0)
    assert [(c, t) for c, t, _id in client.posted] == [(comment_external, DEFAULT_NOTICE_TEXT)]
    row = _get(followup_id)
    assert row.notice_status is NoticeStatus.POSTED
    assert row.notice_external_id == client.posted[0][2]


def test_meta_id_is_unique_per_connection(seeded: dict[str, UUID]) -> None:
    repo = PostgresNoticeRepository()
    _drain(repo)
    a = _approved_with_notice(seeded)
    b = _approved_with_notice(seeded)
    claimed = {c.followup_id for c in repo.claim(tenant_id=TENANT, worker_id="t", now=_wall())}
    assert {a, b} <= claimed
    external = f"1789-{uuid4().hex[:6]}"
    assert repo.mark_posted(
        tenant_id=TENANT, followup_id=a, external_id=external, attempts=1, now=NOW
    )
    with pytest.raises(IntegrityError) as exc:
        repo.mark_posted(tenant_id=TENANT, followup_id=b, external_id=external, attempts=1, now=NOW)
    assert isinstance(exc.value.orig, UniqueViolation)


@pytest.mark.parametrize(
    "assignments",
    [
        # posted ⇔ Meta's id
        "notice_status = 'posted', notice_external_id = NULL",
        "notice_external_id = '1789-z'",
        # a claim is a lock, and only a claim holds one (0074)
        "notice_status = 'posting', notice_locked_at = NULL",
        "notice_locked_at = now()",
        "notice_status = 'queued'",
    ],
)
def test_notice_checks(seeded: dict[str, UUID], assignments: str) -> None:
    followup_id = _approved_with_notice(seeded, sent=False)
    with pytest.raises(IntegrityError) as exc, tenant_session(TENANT) as session:
        session.execute(
            text(f"UPDATE interaction_followups SET {assignments} WHERE id = :id"),
            {"id": followup_id},
        )
    assert isinstance(exc.value.orig, CheckViolation)


def test_a_posting_row_with_its_lock_is_valid(seeded: dict[str, UUID]) -> None:
    followup_id = _approved_with_notice(seeded, sent=False)
    with tenant_session(TENANT) as session:
        session.execute(
            text(
                "UPDATE interaction_followups SET notice_status = 'posting', "
                "notice_locked_at = now(), notice_locked_by = 'w' WHERE id = :id"
            ),
            {"id": followup_id},
        )
    assert _get(followup_id).notice_status is NoticeStatus.POSTING

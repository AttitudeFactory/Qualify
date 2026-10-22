"""The public notice «Te enviamos la información por DM 💬» (m-24789646, PR 4, B4), offline.

Pins:
1. It is posted only after the private message is CONFIRMED sent (`sent` with Meta's id);
   a message that failed or whose result is uncertain (`send_ambiguous`, an expired or
   disabled private reply, `dead`) settles the notice `skipped` without calling Meta.
2. One notice per interaction: retries and two concurrent passes post it once.
3. A transient error retries with backoff; a definitive one (or an ambiguous post) is
   `failed` — and neither touches the followup's decision nor the outbox row.
4. With `public_notice` off nothing is posted; a story reply never has a notice.
5. ADR 21c: only a notice a person approved (`pending`, written by the approval) is ever
   posted.
6. The conversations worker runs the notices after the sender, even when it raised.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import pytest

from qualify_api.conversations.outbox import ApprovalRequired
from qualify_api.conversations.sender import (
    ERROR_PRIVATE_REPLY_DISABLED,
    ERROR_PRIVATE_REPLY_EXPIRED,
    ERROR_SEND_AMBIGUOUS,
)
from qualify_api.conversations.worker import ConversationsTick, NoSender, ScopedTenants
from qualify_api.followups import (
    Capabilities,
    Capability,
    Followup,
    FollowupStatus,
    FollowupTrigger,
    InvalidFollowupTransition,
    NoticeStatus,
    OriginKind,
    OriginMessage,
    SendRoute,
    approve_followup,
    new_followup,
)
from qualify_api.followups.notice import (
    DEFAULT_NOTICE_TEXT,
    ERROR_NOTICE_AMBIGUOUS,
    ERROR_NOTICE_DISABLED,
    MAX_NOTICE_ATTEMPTS,
    NOTICE_STALE_AFTER,
    MemoryCommentReplyClient,
    MemoryNoticeClientFactory,
    MemoryNoticeRepository,
    NoticeReport,
    PublicNoticePoster,
    notice_backoff,
)
from qualify_api.replies.client import CommentReplyError

from .test_followups_service import COMMENT_ID, CONNECTION_ID, TENANT, World

ALL_ON = Capabilities(frozenset({Capability.COMMENT_PRIVATE_REPLY, Capability.PUBLIC_NOTICE}))


class SendFailure(Exception):
    def __init__(self, *, auth: bool = False, ambiguous: bool = False) -> None:
        super().__init__("send failed")
        self.is_auth_error = auth
        self.is_retryable = False
        self.is_ambiguous = ambiguous
        self.http_status = 401 if auth else None
        self.platform_code = 190 if auth else None


def _meta_error(status: int | None, code: int | None = None, **kw: bool) -> CommentReplyError:
    return CommentReplyError("failed", http_status=status, platform_code=code, **kw)


class NoticeWorld(World):
    def __init__(self, capabilities: Capabilities = ALL_ON) -> None:
        super().__init__(capabilities)
        self.replies = MemoryCommentReplyClient()
        self.notices = MemoryNoticeRepository(
            followups=self.followups, outbox=self.outbox, origins=self.origins
        )

    def poster(self, *, enabled: bool = True, client: object = None) -> PublicNoticePoster:
        return PublicNoticePoster(
            notices=self.notices,
            clients=MemoryNoticeClientFactory(client or self.replies),  # type: ignore[arg-type]
            enabled=enabled,
            worker_id="test",
            clock=self.clock,
        )

    def add_comment(self, external_id: str) -> OriginMessage:
        return self.origins.add(replace(self.comment, id=uuid4(), external_message_id=external_id))

    def approved(
        self, message_id: UUID | None = None, notice: str | None = DEFAULT_NOTICE_TEXT
    ) -> Followup:
        followup = self.open(message_id).followup
        if notice is None:
            return self.approve(followup.id)
        return self.approve(followup.id, notice_text=notice)

    async def send(self, **kw: bool) -> None:
        await self.sender_loop(**kw).run_once(TENANT)

    def row(self, followup_id: UUID):
        return self.followups.rows[followup_id]


@pytest.fixture
def world() -> NoticeWorld:
    return NoticeWorld()


# --- 1. only after a CONFIRMED send ---------------------------------------------------------


async def test_the_notice_waits_for_the_confirmed_send_then_posts_once(world) -> None:
    followup = world.approved()
    assert world.row(followup.id).notice_status is NoticeStatus.PENDING

    # The private message is still queued: nothing to announce yet.
    early = await world.poster().run_once(TENANT)
    assert (early.claimed, early.posted) == (0, 0)
    assert world.replies.posted == []

    await world.send()
    sent = world.outbox.rows[followup.outbox_id]
    assert sent.status == "sent" and sent.external_message_id

    report = await world.poster().run_once(TENANT)
    assert (report.claimed, report.posted) == (1, 1)
    [(comment_id, text, reply_id)] = world.replies.posted
    assert (comment_id, text) == (COMMENT_ID, DEFAULT_NOTICE_TEXT)
    row = world.row(followup.id)
    assert row.notice_status is NoticeStatus.POSTED
    assert (row.notice_external_id, row.notice_attempts) == (reply_id, 1)
    assert row.notice_posted_at == world.clock() and row.notice_error_code is None

    again = await world.poster().run_once(TENANT)
    assert again.claimed == 0 and len(world.replies.posted) == 1


async def test_the_edited_text_is_what_gets_posted(world) -> None:
    world.approved(notice="  ¡Te escribimos por DM! 💬  ")
    await world.send()
    await world.poster().run_once(TENANT)
    assert [text for _c, text, _id in world.replies.posted] == ["¡Te escribimos por DM! 💬"]


async def _fail_ambiguous(world: NoticeWorld) -> None:
    world.channel.fail_with = SendFailure(ambiguous=True)
    await world.send()


async def _fail_expired(world: NoticeWorld) -> None:
    world.clock.now = world.comment.posted_at + timedelta(days=7, minutes=1)  # type: ignore[operator]
    await world.send()


async def _fail_disabled(world: NoticeWorld) -> None:
    await world.send(private_replies=False)


async def _fail_dead(world: NoticeWorld) -> None:
    world.channel.fail_with = SendFailure(auth=True)
    await world.send()


@pytest.mark.parametrize(
    ("fail", "code"),
    [
        (_fail_ambiguous, f"dm_failed:{ERROR_SEND_AMBIGUOUS}"),
        (_fail_expired, f"dm_failed:{ERROR_PRIVATE_REPLY_EXPIRED}"),
        (_fail_disabled, f"dm_failed:{ERROR_PRIVATE_REPLY_DISABLED}"),
        (_fail_dead, "dm_dead:auth_error"),
    ],
)
async def test_a_message_not_confirmed_never_gets_its_notice(world, fail, code: str) -> None:
    followup = world.approved()
    await fail(world)
    assert world.outbox.rows[followup.outbox_id].status in ("failed", "dead")

    report = await world.poster().run_once(TENANT)
    assert (report.skipped, report.claimed) == (1, 0)
    assert world.replies.posted == []
    row = world.row(followup.id)
    assert (row.notice_status, row.notice_error_code) == (NoticeStatus.SKIPPED, code)
    assert row.notice_attempts == 0
    # Settled once: a later pass has nothing left to skip.
    assert (await world.poster().run_once(TENANT)).skipped == 0


# --- 2. one notice per interaction ------------------------------------------------------------


async def test_a_transient_error_retries_with_backoff_and_posts_once(world) -> None:
    followup = world.approved()
    await world.send()
    world.replies.fail_with = [_meta_error(503)]

    first = await world.poster().run_once(TENANT)
    assert (first.claimed, first.retried, first.posted) == (1, 1, 0)
    row = world.row(followup.id)
    assert row.notice_status is NoticeStatus.PENDING
    assert (row.notice_attempts, row.notice_error_code) == (1, "http_503_code_None")
    assert row.notice_next_attempt_at == world.clock() + notice_backoff(1)

    # Before the backoff elapses nothing is claimed.
    assert (await world.poster().run_once(TENANT)).claimed == 0

    world.clock.now = row.notice_next_attempt_at
    second = await world.poster().run_once(TENANT)
    assert second.posted == 1
    assert len(world.replies.posted) == 1
    assert world.row(followup.id).notice_attempts == 2
    assert (await world.poster().run_once(TENANT)).claimed == 0


@pytest.mark.parametrize("code", [4, 17, 32, 613])
async def test_meta_throttling_is_transient(world, code: int) -> None:
    followup = world.approved()
    await world.send()
    world.replies.fail_with = [_meta_error(400, code)]
    assert (await world.poster().run_once(TENANT)).retried == 1
    assert world.row(followup.id).notice_status is NoticeStatus.PENDING


class SlowClient(MemoryCommentReplyClient):
    """Yields to the loop mid-post, so two passes really interleave."""

    async def post_reply(self, *, ig_comment_id: str, message: str) -> str:
        await asyncio.sleep(0)
        return await super().post_reply(ig_comment_id=ig_comment_id, message=message)


async def test_two_concurrent_passes_post_each_notice_once(world) -> None:
    others = [world.add_comment(f"1789000000000010{i}") for i in range(3)]
    ids = [world.approved().id] + [world.approved(c.id).id for c in others]
    await world.send()
    client = SlowClient()

    a, b = await asyncio.gather(
        world.poster(client=client).run_once(TENANT), world.poster(client=client).run_once(TENANT)
    )
    assert a.posted + b.posted == len(ids)
    assert a.claimed + b.claimed == len(ids)
    posted_comments = [comment for comment, _t, _id in client.posted]
    assert sorted(posted_comments) == sorted([COMMENT_ID] + [c.external_message_id for c in others])
    assert {world.row(i).notice_status for i in ids} == {NoticeStatus.POSTED}


async def test_a_stale_posting_row_is_never_posted_again(world) -> None:
    """A worker that died mid-post may have published it: `notice_ambiguous`, no retry."""
    followup = world.approved()
    await world.send()
    world.notices.claim(tenant_id=TENANT, worker_id="dead", now=world.clock())
    assert world.row(followup.id).notice_status is NoticeStatus.POSTING

    world.clock.now = world.clock() + NOTICE_STALE_AFTER + timedelta(seconds=1)
    report = await world.poster().run_once(TENANT)
    assert report.claimed == 0 and world.replies.posted == []
    row = world.row(followup.id)
    assert (row.notice_status, row.notice_error_code) == (
        NoticeStatus.FAILED,
        ERROR_NOTICE_AMBIGUOUS,
    )


async def test_a_late_settle_is_a_no_op(world) -> None:
    followup = world.approved()
    await world.send()
    await world.poster().run_once(TENANT)
    assert not world.notices.mark_failed(
        tenant_id=TENANT, followup_id=followup.id, attempts=9, error_code="x", now=world.clock()
    )
    assert world.row(followup.id).notice_status is NoticeStatus.POSTED


# --- 3. failures stay the notice's own ------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "code", "attempts"),
    [
        (_meta_error(400, 100), "http_400_code_100", 1),
        (_meta_error(401, 190), "http_401_code_190", 1),
        (_meta_error(None, is_ambiguous=True), ERROR_NOTICE_AMBIGUOUS, 1),
        # A 200 without an id: the reply may be public already.
        (_meta_error(None), ERROR_NOTICE_AMBIGUOUS, 1),
    ],
)
async def test_a_definitive_or_ambiguous_error_fails_the_notice_alone(
    world, error: CommentReplyError, code: str, attempts: int
) -> None:
    followup = world.approved()
    await world.send()
    outbox_before = replace(world.outbox.rows[followup.outbox_id])
    world.replies.fail_with = [error]

    report = await world.poster().run_once(TENANT)
    assert report.failed == 1
    row = world.row(followup.id)
    assert (row.notice_status, row.notice_error_code) == (NoticeStatus.FAILED, code)
    assert row.notice_attempts == attempts
    # The decision and the message are untouched.
    assert row.status is FollowupStatus.APPROVED
    assert (row.outbox_id, row.send_route) == (followup.outbox_id, followup.send_route)
    assert world.outbox.rows[followup.outbox_id] == outbox_before
    assert len(world.outbox.messages) == 1
    # Not retried.
    world.clock.now = world.clock() + timedelta(days=1)
    assert (await world.poster().run_once(TENANT)).claimed == 0


async def test_retries_end_in_failed_after_max_attempts(world) -> None:
    followup = world.approved()
    await world.send()
    world.replies.fail_with = [_meta_error(500) for _ in range(MAX_NOTICE_ATTEMPTS)]
    for _ in range(MAX_NOTICE_ATTEMPTS):
        await world.poster().run_once(TENANT)
        world.clock.now = world.clock() + timedelta(hours=2)
    row = world.row(followup.id)
    assert row.notice_status is NoticeStatus.FAILED
    assert row.notice_error_code == "max_attempts:http_500_code_None"
    assert row.notice_attempts == MAX_NOTICE_ATTEMPTS
    assert world.replies.posted == []


async def test_a_client_that_cannot_be_built_is_retried_without_posting(world) -> None:
    class Broken:
        async def client_for(self, *, tenant_id: UUID, connection_id: UUID) -> object:
            raise LookupError("no credential")

    followup = world.approved()
    await world.send()
    poster = PublicNoticePoster(
        notices=world.notices, clients=Broken(), enabled=True, worker_id="t", clock=world.clock
    )
    assert (await poster.run_once(TENANT)).retried == 1
    row = world.row(followup.id)
    assert (row.notice_status, row.notice_error_code) == (NoticeStatus.PENDING, "LookupError")


# --- 4. capability and origin -----------------------------------------------------------------


async def test_with_public_notice_off_nothing_is_posted(world) -> None:
    followup = world.approved()
    await world.send()
    report = await world.poster(enabled=False).run_once(TENANT)
    assert report.failed == 1 and world.replies.posted == []
    row = world.row(followup.id)
    assert (row.notice_status, row.notice_error_code) == (
        NoticeStatus.FAILED,
        ERROR_NOTICE_DISABLED,
    )


def test_a_story_reply_never_has_a_notice() -> None:
    story = new_followup(
        tenant_id=TENANT,
        connection_id=CONNECTION_ID,
        origin_kind=OriginKind.STORY_REPLY,
        origin_message_id=uuid4(),
        dm_thread_id=uuid4(),
        trigger=FollowupTrigger.MANUAL,
    )
    assert story.notice_status is NoticeStatus.NOT_APPLICABLE
    with pytest.raises(InvalidFollowupTransition):
        approve_followup(
            story,
            outbox_id=uuid4(),
            send_route=SendRoute.DM,
            dm_thread_id=story.dm_thread_id,  # type: ignore[arg-type]
            decided_by_user_id=uuid4(),
            now=story.created_at,
            notice_text=DEFAULT_NOTICE_TEXT,
        )


async def test_the_poster_never_claims_a_story_reply(world) -> None:
    """Even a row forced into `pending` (the CHECK forbids it in Postgres) is ignored."""
    followup = world.approved()
    await world.send()
    world.followups.rows[followup.id] = replace(
        world.row(followup.id), origin_kind=OriginKind.STORY_REPLY
    )
    assert (await world.poster().run_once(TENANT)).claimed == 0
    assert world.replies.posted == []


# --- 5. ADR 21c: only what a person approved ---------------------------------------------------


async def test_a_message_approved_without_notice_never_gets_one(world) -> None:
    followup = world.approved(notice=None)
    assert world.row(followup.id).notice_status is NoticeStatus.NOT_REQUESTED
    await world.send()
    report = await world.poster().run_once(TENANT)
    assert (report.claimed, report.skipped) == (0, 0)
    assert world.replies.posted == []


@pytest.mark.parametrize(
    "status",
    [s for s in NoticeStatus if s is not NoticeStatus.PENDING],
)
async def test_only_a_pending_notice_is_ever_claimed(world, status: NoticeStatus) -> None:
    followup = world.approved()
    await world.send()
    external = "17999" if status is NoticeStatus.POSTED else None
    world.followups.rows[followup.id] = replace(
        world.row(followup.id),
        notice_status=status,
        notice_external_id=external,
        notice_locked_at=world.clock() if status is NoticeStatus.POSTING else None,
    )
    assert (await world.poster().run_once(TENANT)).claimed == 0
    assert world.replies.posted == []


def test_pending_is_reached_only_through_a_human_approval(world) -> None:
    """The one writer of `pending` is the approval, which demands a `HumanApproval`."""
    followup = world.open().followup
    with pytest.raises(ApprovalRequired):
        world.service.approve_and_queue(
            tenant_id=TENANT,
            followup_id=followup.id,
            text="hola",
            approval=None,  # type: ignore[arg-type]
            notice_text=DEFAULT_NOTICE_TEXT,
        )
    assert world.row(followup.id).notice_status is NoticeStatus.NOT_REQUESTED
    assert world.outbox.rows == {}
    approved = world.approve(followup.id, notice_text=DEFAULT_NOTICE_TEXT)
    assert approved.notice_status is NoticeStatus.PENDING
    assert world.outbox.rows[approved.outbox_id].approved_by_user_id == approved.decided_by_user_id


def test_an_overlong_notice_is_refused_before_anything_is_queued(world) -> None:
    followup = world.open().followup
    with pytest.raises(ValueError, match="notice"):
        world.approve(followup.id, notice_text="x" * 301)
    assert world.outbox.rows == {}
    assert world.row(followup.id).status is FollowupStatus.OPEN


def test_the_card_offers_the_notice_only_for_a_comment_with_the_capability(world) -> None:
    followup = world.open().followup
    assert world.service.public_notice_available(followup) is True
    off = NoticeWorld(Capabilities(frozenset({Capability.COMMENT_PRIVATE_REPLY})))
    assert off.service.public_notice_available(off.open().followup) is False


# --- 6. the worker --------------------------------------------------------------------------


class _Notices:
    def __init__(self) -> None:
        self.calls: list[UUID] = []

    async def run_once(self, tenant_id: UUID, *, limit: int = 50) -> NoticeReport:
        self.calls.append(tenant_id)
        return NoticeReport(tenant_id=tenant_id, claimed=1, posted=1)


class _BrokenSender:
    async def run_once(self, tenant_id: UUID, *, limit: int = 50):  # noqa: ANN201
        raise RuntimeError("db down")


async def test_the_worker_posts_notices_after_sending_even_if_the_send_raised() -> None:
    a = uuid4()
    notices = _Notices()
    report = await ConversationsTick(
        tenants=ScopedTenants([a]), sender=_BrokenSender(), notices=notices
    ).run_once()
    assert notices.calls == [a]
    [tenant] = report.tenants
    assert tenant.errors == ["send:RuntimeError"]
    assert tenant.notices is not None and tenant.notices.posted == 1


async def test_a_failing_notice_pass_is_reported_and_the_next_tenant_runs() -> None:
    a, b = uuid4(), uuid4()

    class Flaky(_Notices):
        async def run_once(self, tenant_id: UUID, *, limit: int = 50) -> NoticeReport:
            self.calls.append(tenant_id)
            if tenant_id == a:
                raise RuntimeError("boom")
            return NoticeReport(tenant_id=tenant_id)

    notices = Flaky()
    report = await ConversationsTick(
        tenants=ScopedTenants([a, b]), sender=NoSender(), notices=notices
    ).run_once()
    assert notices.calls == [a, b]
    assert [t.errors for t in report.tenants] == [["notice:RuntimeError"], []]

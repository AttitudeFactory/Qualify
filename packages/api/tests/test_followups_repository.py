"""The followup contract (m-24789646), offline: the pure transitions and the memory
store. `test_followups_schema_db.py` runs the same contract against Postgres.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qualify_api.followups import (
    Followup,
    FollowupStatus,
    FollowupTrigger,
    InvalidFollowupTransition,
    MemoryFollowupRepository,
    NoticeStatus,
    OriginKind,
    SendRoute,
    UnknownFollowup,
    approve_followup,
    discard_followup,
    new_followup,
)

TENANT = UUID("a0000000-0000-4000-8000-0000000000f1")
OTHER = UUID("a0000000-0000-4000-8000-0000000000f2")
CONNECTION = uuid4()
USER = uuid4()
THREAD = uuid4()
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


def _followup(
    *,
    origin_kind: OriginKind = OriginKind.COMMENT,
    trigger: FollowupTrigger = FollowupTrigger.INTENT,
    tenant_id: UUID = TENANT,
    message_id: UUID | None = None,
    now: datetime = NOW,
) -> Followup:
    return new_followup(
        tenant_id=tenant_id,
        connection_id=CONNECTION,
        origin_kind=origin_kind,
        origin_message_id=message_id or uuid4(),
        # A story reply is already a DM; a comment gets its thread when approved.
        dm_thread_id=uuid4() if origin_kind is OriginKind.STORY_REPLY else None,
        trigger=trigger,
        intent_result_id=uuid4() if trigger is FollowupTrigger.INTENT else None,
        now=now,
    )


# --- new_followup -------------------------------------------------------------------------


def test_a_new_followup_is_open_and_undecided() -> None:
    followup = _followup()
    assert followup.status is FollowupStatus.OPEN
    assert followup.send_route is None and followup.outbox_id is None
    assert followup.decided_at is None and followup.decided_by_user_id is None
    assert followup.created_at == followup.updated_at == NOW


def test_a_comment_starts_with_no_notice_requested_and_a_story_reply_with_none_possible() -> None:
    assert _followup().notice_status is NoticeStatus.NOT_REQUESTED
    story = _followup(origin_kind=OriginKind.STORY_REPLY)
    assert story.notice_status is NoticeStatus.NOT_APPLICABLE


def test_an_intent_followup_names_its_analysis_and_a_manual_one_does_not() -> None:
    common = dict(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        origin_kind=OriginKind.COMMENT,
        origin_message_id=uuid4(),
    )
    with pytest.raises(ValueError):
        new_followup(**common, trigger=FollowupTrigger.INTENT)
    with pytest.raises(ValueError):
        new_followup(**common, trigger=FollowupTrigger.MANUAL, intent_result_id=uuid4())
    assert new_followup(**common, trigger=FollowupTrigger.MANUAL).intent_result_id is None


def test_a_comment_opens_without_a_thread_and_a_story_reply_needs_its_own() -> None:
    assert _followup().dm_thread_id is None
    with pytest.raises(ValueError):
        new_followup(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            origin_kind=OriginKind.STORY_REPLY,
            origin_message_id=uuid4(),
            trigger=FollowupTrigger.MANUAL,
        )


# --- transitions --------------------------------------------------------------------------


def test_approve_records_the_person_the_route_and_the_queued_send() -> None:
    outbox_id = uuid4()
    later = NOW + timedelta(minutes=5)
    approved = approve_followup(
        _followup(),
        outbox_id=outbox_id,
        send_route=SendRoute.PRIVATE_REPLY,
        dm_thread_id=THREAD,
        decided_by_user_id=USER,
        now=later,
    )
    assert approved.status is FollowupStatus.APPROVED
    assert approved.outbox_id == outbox_id
    assert approved.send_route is SendRoute.PRIVATE_REPLY
    assert approved.dm_thread_id == THREAD
    assert (approved.decided_by_user_id, approved.decided_at, approved.updated_at) == (
        USER,
        later,
        later,
    )
    # No notice was asked for: it stays not requested.
    assert approved.notice_status is NoticeStatus.NOT_REQUESTED
    assert approved.notice_text is None


def test_approve_with_a_notice_leaves_it_pending_for_the_confirmed_send() -> None:
    approved = approve_followup(
        _followup(),
        outbox_id=uuid4(),
        send_route=SendRoute.DM,
        dm_thread_id=THREAD,
        decided_by_user_id=USER,
        now=NOW,
        notice_text="  Te enviamos la información por DM 💬  ",
    )
    assert approved.notice_status is NoticeStatus.PENDING
    assert approved.notice_text == "Te enviamos la información por DM 💬"


def test_a_blank_notice_is_no_notice() -> None:
    approved = approve_followup(
        _followup(),
        outbox_id=uuid4(),
        send_route=SendRoute.DM,
        dm_thread_id=THREAD,
        decided_by_user_id=USER,
        now=NOW,
        notice_text="   ",
    )
    assert approved.notice_status is NoticeStatus.NOT_REQUESTED
    assert approved.notice_text is None


def test_a_story_reply_admits_neither_a_private_reply_nor_a_notice() -> None:
    story = _followup(origin_kind=OriginKind.STORY_REPLY)
    own = story.dm_thread_id
    assert own is not None
    with pytest.raises(InvalidFollowupTransition):
        approve_followup(
            story,
            outbox_id=uuid4(),
            send_route=SendRoute.PRIVATE_REPLY,
            dm_thread_id=own,
            decided_by_user_id=USER,
            now=NOW,
        )
    with pytest.raises(InvalidFollowupTransition):
        approve_followup(
            story,
            outbox_id=uuid4(),
            send_route=SendRoute.DM,
            dm_thread_id=own,
            decided_by_user_id=USER,
            now=NOW,
            notice_text="Te enviamos la información por DM 💬",
        )
    approved = approve_followup(
        story,
        outbox_id=uuid4(),
        send_route=SendRoute.DM,
        dm_thread_id=own,
        decided_by_user_id=USER,
        now=NOW,
    )
    assert approved.notice_status is NoticeStatus.NOT_APPLICABLE


def test_a_story_reply_is_answered_in_its_own_thread() -> None:
    with pytest.raises(InvalidFollowupTransition):
        approve_followup(
            _followup(origin_kind=OriginKind.STORY_REPLY),
            outbox_id=uuid4(),
            send_route=SendRoute.DM,
            dm_thread_id=uuid4(),
            decided_by_user_id=USER,
            now=NOW,
        )


def test_only_an_open_followup_can_be_decided() -> None:
    discarded = discard_followup(_followup(), decided_by_user_id=USER, now=NOW)
    assert discarded.status is FollowupStatus.DISCARDED
    assert discarded.decided_by_user_id == USER
    with pytest.raises(InvalidFollowupTransition):
        discard_followup(discarded, decided_by_user_id=USER, now=NOW)
    with pytest.raises(InvalidFollowupTransition):
        approve_followup(
            discarded,
            outbox_id=uuid4(),
            send_route=SendRoute.DM,
            dm_thread_id=THREAD,
            decided_by_user_id=USER,
            now=NOW,
        )


# --- memory store -------------------------------------------------------------------------


def test_opening_is_idempotent_per_interaction_and_the_first_trigger_wins() -> None:
    repo = MemoryFollowupRepository()
    message_id = uuid4()
    manual = _followup(trigger=FollowupTrigger.MANUAL, message_id=message_id)
    first = repo.open(manual)
    again = repo.open(_followup(trigger=FollowupTrigger.INTENT, message_id=message_id))
    assert first.created is True and again.created is False
    assert again.followup == manual
    assert len(repo.rows) == 1


def test_another_tenant_cannot_open_the_same_interaction() -> None:
    repo = MemoryFollowupRepository()
    message_id = uuid4()
    repo.open(_followup(message_id=message_id))
    with pytest.raises(PermissionError):
        repo.open(_followup(message_id=message_id, tenant_id=OTHER))


def test_reads_are_tenant_scoped() -> None:
    repo = MemoryFollowupRepository()
    followup = repo.open(_followup()).followup
    assert repo.get(tenant_id=TENANT, followup_id=followup.id) == followup
    assert repo.get(tenant_id=OTHER, followup_id=followup.id) is None
    assert (
        repo.get_for_message(tenant_id=TENANT, origin_message_id=followup.origin_message_id)
        == followup
    )
    assert repo.get_for_message(tenant_id=OTHER, origin_message_id=followup.origin_message_id) is (
        None
    )
    assert repo.list_open(tenant_id=OTHER) == []
    with pytest.raises(UnknownFollowup):
        repo.discard(tenant_id=OTHER, followup_id=followup.id, decided_by_user_id=USER, now=NOW)


def test_list_open_is_newest_first_and_drops_decided_ones() -> None:
    repo = MemoryFollowupRepository()
    older = repo.open(_followup(now=NOW)).followup
    newer = repo.open(_followup(now=NOW + timedelta(hours=1))).followup
    decided = repo.open(_followup(now=NOW + timedelta(hours=2))).followup
    repo.discard(tenant_id=TENANT, followup_id=decided.id, decided_by_user_id=USER, now=NOW)
    assert [f.id for f in repo.list_open(tenant_id=TENANT)] == [newer.id, older.id]
    assert [f.id for f in repo.list_open(tenant_id=TENANT, limit=1)] == [newer.id]
    assert repo.list_open(tenant_id=TENANT, connection_id=uuid4()) == []


def test_the_store_applies_the_same_transitions() -> None:
    repo = MemoryFollowupRepository()
    followup = repo.open(_followup()).followup
    approved = repo.approve(
        tenant_id=TENANT,
        followup_id=followup.id,
        outbox_id=uuid4(),
        send_route=SendRoute.PRIVATE_REPLY,
        dm_thread_id=THREAD,
        decided_by_user_id=USER,
        now=NOW,
    )
    assert repo.get(tenant_id=TENANT, followup_id=followup.id) == approved
    with pytest.raises(InvalidFollowupTransition):
        repo.discard(tenant_id=TENANT, followup_id=followup.id, decided_by_user_id=USER, now=NOW)

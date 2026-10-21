"""The followup contract and its store (m-24789646): `interaction_followups` (0071) read
and written through `PostgresFollowupRepository` under RLS, and `MemoryFollowupRepository`
— the same contract for the offline suite, same discipline as `conversations/drafts.py`.

A followup is the human lifecycle of ONE interaction continued in private:

    open ──approve──▶ approved      (a person approved a send; the outbox has it)
      └───discard──▶ discarded

The transitions are pure functions (`approve_followup`, `discard_followup`) and the
Postgres store writes a transition back only while the row is still `open`, so two people
deciding the same followup cannot both win. Opening is idempotent per interaction: the
automatic path (an intent analysis) and the manual one («Responder por DM») return the
same row, and the first one to open it keeps its `trigger`.

Approving here does NOT send. It records the decision next to the outbox row queued
with the person's `HumanApproval` (ADR 21c) — the one path to a send stays the outbox,
whose `approved_by_user_id` is NOT NULL. `approve` accepts the caller's open session so
the outbox insert and this guarded transition commit together or not at all: a lost race
(two approvals, or an approval against a discard) rolls the queued send back with it.

A comment's followup has no DM thread until it is approved (`dm_thread_id` is None):
the thread is created only when a person decides to write, never just because a
followup was opened.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID, uuid4

from qualify_shared.db.session import tenant_session
from sqlalchemy import text


class OriginKind(StrEnum):
    COMMENT = "comment"
    STORY_REPLY = "story_reply"


class FollowupTrigger(StrEnum):
    INTENT = "intent"
    MANUAL = "manual"


class FollowupStatus(StrEnum):
    OPEN = "open"
    APPROVED = "approved"
    DISCARDED = "discarded"


class SendRoute(StrEnum):
    # Meta's reply to a comment (`recipient.comment_id`): one message, within 7 days.
    PRIVATE_REPLY = "private_reply"
    # A normal DM to the author's thread, when its 24 h window is open.
    DM = "dm"


class NoticeStatus(StrEnum):
    # A story reply: there is no public comment to answer.
    NOT_APPLICABLE = "not_applicable"
    # A comment whose followup was not approved with a notice.
    NOT_REQUESTED = "not_requested"
    # Approved with a notice; waits for the private message's CONFIRMED send.
    PENDING = "pending"
    POSTED = "posted"
    FAILED = "failed"
    # The private message failed or its result is uncertain: the notice never goes out.
    SKIPPED = "skipped"


@dataclass(frozen=True)
class Followup:
    id: UUID
    tenant_id: UUID
    connection_id: UUID
    origin_kind: OriginKind
    # The comment, or the DM that replied to a story (`messages.id`).
    origin_message_id: UUID
    trigger: FollowupTrigger
    status: FollowupStatus
    notice_status: NoticeStatus
    created_at: datetime
    updated_at: datetime
    # The author's private thread in Conversaciones (channel `dm`): a story reply's from
    # the start, a comment's only once a send is approved.
    dm_thread_id: UUID | None = None
    # The versioned analysis that raised it (`comment_intent_results.id`); None if manual.
    intent_result_id: UUID | None = None
    send_route: SendRoute | None = None
    outbox_id: UUID | None = None
    decided_at: datetime | None = None
    decided_by_user_id: UUID | None = None
    notice_text: str | None = None
    notice_attempts: int = 0
    notice_external_id: str | None = None
    notice_error_code: str | None = None
    notice_posted_at: datetime | None = None


@dataclass(frozen=True)
class FollowupOpening:
    followup: Followup
    created: bool


class InvalidFollowupTransition(ValueError):
    """The followup is no longer `open`, or the decision does not fit its origin."""


class UnknownFollowup(LookupError):
    """No followup with that id is visible in this tenant."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _initial_notice(origin_kind: OriginKind) -> NoticeStatus:
    if origin_kind is OriginKind.COMMENT:
        return NoticeStatus.NOT_REQUESTED
    return NoticeStatus.NOT_APPLICABLE


def new_followup(
    *,
    tenant_id: UUID,
    connection_id: UUID,
    origin_kind: OriginKind,
    origin_message_id: UUID,
    trigger: FollowupTrigger,
    dm_thread_id: UUID | None = None,
    intent_result_id: UUID | None = None,
    now: datetime | None = None,
) -> Followup:
    """A fresh `open` followup — the only constructor callers should use. An
    intent-triggered followup must name its analysis; a manual one must not. A story
    reply carries its DM thread from the start."""
    if (trigger is FollowupTrigger.INTENT) != (intent_result_id is not None):
        raise ValueError("an intent followup needs its intent_result_id, a manual one none")
    if origin_kind is OriginKind.STORY_REPLY and dm_thread_id is None:
        raise ValueError("a story reply is already a DM: its thread is required")
    created_at = now or _utcnow()
    return Followup(
        id=uuid4(),
        tenant_id=tenant_id,
        connection_id=connection_id,
        origin_kind=origin_kind,
        origin_message_id=origin_message_id,
        dm_thread_id=dm_thread_id,
        trigger=trigger,
        status=FollowupStatus.OPEN,
        notice_status=_initial_notice(origin_kind),
        created_at=created_at,
        updated_at=created_at,
        intent_result_id=intent_result_id,
    )


def approve_followup(
    followup: Followup,
    *,
    outbox_id: UUID,
    send_route: SendRoute,
    dm_thread_id: UUID,
    decided_by_user_id: UUID,
    now: datetime,
    notice_text: str | None = None,
) -> Followup:
    """`open -> approved`, recording the DM thread the send went to. A private reply
    and a public notice both need a public comment to hang from, so a story reply admits
    neither. A non-empty `notice_text` leaves the
    notice `pending` — it still waits for the CONFIRMED send of the private message."""
    if followup.status is not FollowupStatus.OPEN:
        raise InvalidFollowupTransition(f"followup {followup.id} is {followup.status}, not open")
    if followup.dm_thread_id is not None and followup.dm_thread_id != dm_thread_id:
        raise InvalidFollowupTransition("a story reply is answered in its own thread")
    is_comment = followup.origin_kind is OriginKind.COMMENT
    if send_route is SendRoute.PRIVATE_REPLY and not is_comment:
        raise InvalidFollowupTransition("a private reply answers a comment, not a story reply")
    notice = (notice_text or "").strip() or None
    if notice is not None and not is_comment:
        raise InvalidFollowupTransition("a story reply has no public comment to notice")
    return replace(
        followup,
        status=FollowupStatus.APPROVED,
        send_route=send_route,
        outbox_id=outbox_id,
        dm_thread_id=dm_thread_id,
        decided_at=now,
        decided_by_user_id=decided_by_user_id,
        notice_status=NoticeStatus.PENDING if notice is not None else followup.notice_status,
        notice_text=notice,
        updated_at=now,
    )


def discard_followup(followup: Followup, *, decided_by_user_id: UUID, now: datetime) -> Followup:
    """`open -> discarded`. Kept, never erased: it explains why nobody answered."""
    if followup.status is not FollowupStatus.OPEN:
        raise InvalidFollowupTransition(f"followup {followup.id} is {followup.status}, not open")
    return replace(
        followup,
        status=FollowupStatus.DISCARDED,
        decided_at=now,
        decided_by_user_id=decided_by_user_id,
        updated_at=now,
    )


class FollowupRepository(Protocol):
    def open(self, followup: Followup) -> FollowupOpening:
        """Store a `new_followup`, or return the interaction's existing row unchanged
        (`created=False`) — never a second one for the same `origin_message_id`."""
        ...

    def get(self, *, tenant_id: UUID, followup_id: UUID) -> Followup | None: ...

    def get_for_message(self, *, tenant_id: UUID, origin_message_id: UUID) -> Followup | None: ...

    def list_open(
        self, *, tenant_id: UUID, connection_id: UUID | None = None, limit: int = 50
    ) -> list[Followup]:
        """`open` followups, newest first — «Consultas desde comentarios»."""
        ...

    def approve(
        self,
        *,
        tenant_id: UUID,
        followup_id: UUID,
        outbox_id: UUID,
        send_route: SendRoute,
        dm_thread_id: UUID,
        decided_by_user_id: UUID,
        now: datetime,
        notice_text: str | None = None,
        session: Any = None,
    ) -> Followup:
        """`open -> approved`. With `session` (the caller's open transaction, e.g. the
        outbox insert's) the guarded write joins it, so both commit or neither does."""
        ...

    def discard(
        self, *, tenant_id: UUID, followup_id: UUID, decided_by_user_id: UUID, now: datetime
    ) -> Followup: ...


class MemoryFollowupRepository:
    def __init__(self, *, clock: Callable[[], datetime] = _utcnow) -> None:
        self._clock = clock
        self.rows: dict[UUID, Followup] = {}

    def open(self, followup: Followup) -> FollowupOpening:
        for row in self.rows.values():
            if row.origin_message_id == followup.origin_message_id:
                if row.tenant_id != followup.tenant_id:
                    # The composite FK makes this unbuildable in Postgres; here it is a bug.
                    raise PermissionError("the interaction belongs to another tenant")
                return FollowupOpening(row, created=False)
        self.rows[followup.id] = followup
        return FollowupOpening(followup, created=True)

    def get(self, *, tenant_id: UUID, followup_id: UUID) -> Followup | None:
        row = self.rows.get(followup_id)
        return row if row is not None and row.tenant_id == tenant_id else None

    def get_for_message(self, *, tenant_id: UUID, origin_message_id: UUID) -> Followup | None:
        return next(
            (
                r
                for r in self.rows.values()
                if r.tenant_id == tenant_id and r.origin_message_id == origin_message_id
            ),
            None,
        )

    def list_open(
        self, *, tenant_id: UUID, connection_id: UUID | None = None, limit: int = 50
    ) -> list[Followup]:
        rows = [
            r
            for r in self.rows.values()
            if r.tenant_id == tenant_id
            and r.status is FollowupStatus.OPEN
            and (connection_id is None or r.connection_id == connection_id)
        ]
        return sorted(rows, key=lambda r: r.created_at, reverse=True)[:limit]

    def approve(
        self,
        *,
        tenant_id: UUID,
        followup_id: UUID,
        outbox_id: UUID,
        send_route: SendRoute,
        dm_thread_id: UUID,
        decided_by_user_id: UUID,
        now: datetime,
        notice_text: str | None = None,
        session: Any = None,
    ) -> Followup:
        approved = approve_followup(
            self._require(tenant_id, followup_id),
            outbox_id=outbox_id,
            send_route=send_route,
            dm_thread_id=dm_thread_id,
            decided_by_user_id=decided_by_user_id,
            now=now,
            notice_text=notice_text,
        )
        self.rows[followup_id] = approved
        return approved

    def discard(
        self, *, tenant_id: UUID, followup_id: UUID, decided_by_user_id: UUID, now: datetime
    ) -> Followup:
        discarded = discard_followup(
            self._require(tenant_id, followup_id), decided_by_user_id=decided_by_user_id, now=now
        )
        self.rows[followup_id] = discarded
        return discarded

    def _require(self, tenant_id: UUID, followup_id: UUID) -> Followup:
        row = self.get(tenant_id=tenant_id, followup_id=followup_id)
        if row is None:
            raise UnknownFollowup(str(followup_id))
        return row


# --- Postgres -----------------------------------------------------------------------------

_COLUMNS = """
    id, tenant_id, connection_id, origin_kind, origin_message_id, dm_thread_id, trigger,
    intent_result_id, status, send_route, outbox_id, decided_at, decided_by_user_id,
    notice_status, notice_text, notice_attempts, notice_external_id, notice_error_code,
    notice_posted_at, created_at, updated_at
"""

_INSERT = text(
    f"""
    INSERT INTO interaction_followups (
        id, tenant_id, connection_id, origin_kind, origin_message_id, dm_thread_id, trigger,
        intent_result_id, status, notice_status, created_at, updated_at
    ) VALUES (
        :id, :tenant_id, :connection_id, :origin_kind, :origin_message_id, :dm_thread_id,
        :trigger, :intent_result_id, 'open', :notice_status, :created_at, :created_at
    )
    ON CONFLICT (origin_message_id) DO NOTHING
    RETURNING {_COLUMNS}
    """
)

_GET = text(f"SELECT {_COLUMNS} FROM interaction_followups WHERE id = :id")

_GET_FOR_MESSAGE = text(
    f"SELECT {_COLUMNS} FROM interaction_followups WHERE origin_message_id = :message_id"
)

_LIST_OPEN = text(
    f"""
    SELECT {_COLUMNS} FROM interaction_followups
     WHERE status = 'open'
       AND (CAST(:connection_id AS uuid) IS NULL OR connection_id = :connection_id)
     ORDER BY created_at DESC
     LIMIT :limit
    """
)

# Decided in Python, written back only while the row is still `open`.
_APPROVE = text(
    """
    UPDATE interaction_followups
       SET status = 'approved', send_route = :send_route, outbox_id = :outbox_id,
           dm_thread_id = :dm_thread_id, decided_at = :now, decided_by_user_id = :user_id,
           notice_status = :notice_status, notice_text = :notice_text, updated_at = :now
     WHERE id = :id AND status = 'open'
    """
)

_DISCARD = text(
    """
    UPDATE interaction_followups
       SET status = 'discarded', decided_at = :now, decided_by_user_id = :user_id,
           updated_at = :now
     WHERE id = :id AND status = 'open'
    """
)


def _row_to_followup(r: Any) -> Followup:
    return Followup(
        id=r.id,
        tenant_id=r.tenant_id,
        connection_id=r.connection_id,
        origin_kind=OriginKind(r.origin_kind),
        origin_message_id=r.origin_message_id,
        dm_thread_id=r.dm_thread_id,
        trigger=FollowupTrigger(r.trigger),
        status=FollowupStatus(r.status),
        notice_status=NoticeStatus(r.notice_status),
        created_at=r.created_at,
        updated_at=r.updated_at,
        intent_result_id=r.intent_result_id,
        send_route=SendRoute(r.send_route) if r.send_route else None,
        outbox_id=r.outbox_id,
        decided_at=r.decided_at,
        decided_by_user_id=r.decided_by_user_id,
        notice_text=r.notice_text,
        notice_attempts=int(r.notice_attempts or 0),
        notice_external_id=r.notice_external_id,
        notice_error_code=r.notice_error_code,
        notice_posted_at=r.notice_posted_at,
    )


class PostgresFollowupRepository:
    """`interaction_followups` under RLS (`tenant_session`). Same contract as the memory
    repository; idempotent opening is `ON CONFLICT (origin_message_id) DO NOTHING`."""

    def open(self, followup: Followup) -> FollowupOpening:
        with tenant_session(followup.tenant_id) as session:
            row = session.execute(
                _INSERT,
                {
                    "id": followup.id,
                    "tenant_id": followup.tenant_id,
                    "connection_id": followup.connection_id,
                    "origin_kind": followup.origin_kind.value,
                    "origin_message_id": followup.origin_message_id,
                    "dm_thread_id": followup.dm_thread_id,
                    "trigger": followup.trigger.value,
                    "intent_result_id": followup.intent_result_id,
                    "notice_status": followup.notice_status.value,
                    "created_at": followup.created_at,
                },
            ).first()
            if row is not None:
                return FollowupOpening(_row_to_followup(row), created=True)
            existing = session.execute(
                _GET_FOR_MESSAGE, {"message_id": followup.origin_message_id}
            ).one()
        return FollowupOpening(_row_to_followup(existing), created=False)

    def get(self, *, tenant_id: UUID, followup_id: UUID) -> Followup | None:
        with tenant_session(tenant_id) as session:
            row = session.execute(_GET, {"id": followup_id}).first()
        return _row_to_followup(row) if row is not None else None

    def get_for_message(self, *, tenant_id: UUID, origin_message_id: UUID) -> Followup | None:
        with tenant_session(tenant_id) as session:
            row = session.execute(_GET_FOR_MESSAGE, {"message_id": origin_message_id}).first()
        return _row_to_followup(row) if row is not None else None

    def list_open(
        self, *, tenant_id: UUID, connection_id: UUID | None = None, limit: int = 50
    ) -> list[Followup]:
        with tenant_session(tenant_id) as session:
            rows = session.execute(
                _LIST_OPEN, {"connection_id": connection_id, "limit": limit}
            ).all()
        return [_row_to_followup(r) for r in rows]

    def approve(
        self,
        *,
        tenant_id: UUID,
        followup_id: UUID,
        outbox_id: UUID,
        send_route: SendRoute,
        dm_thread_id: UUID,
        decided_by_user_id: UUID,
        now: datetime,
        notice_text: str | None = None,
        session: Any = None,
    ) -> Followup:
        approved = approve_followup(
            self._require(tenant_id, followup_id),
            outbox_id=outbox_id,
            send_route=send_route,
            dm_thread_id=dm_thread_id,
            decided_by_user_id=decided_by_user_id,
            now=now,
            notice_text=notice_text,
        )
        self._write(
            tenant_id,
            _APPROVE,
            {
                "id": followup_id,
                "send_route": approved.send_route.value if approved.send_route else None,
                "outbox_id": outbox_id,
                "dm_thread_id": dm_thread_id,
                "now": now,
                "user_id": decided_by_user_id,
                "notice_status": approved.notice_status.value,
                "notice_text": approved.notice_text,
            },
            session=session,
        )
        return approved

    def discard(
        self, *, tenant_id: UUID, followup_id: UUID, decided_by_user_id: UUID, now: datetime
    ) -> Followup:
        discarded = discard_followup(
            self._require(tenant_id, followup_id), decided_by_user_id=decided_by_user_id, now=now
        )
        self._write(
            tenant_id, _DISCARD, {"id": followup_id, "now": now, "user_id": decided_by_user_id}
        )
        return discarded

    def _require(self, tenant_id: UUID, followup_id: UUID) -> Followup:
        row = self.get(tenant_id=tenant_id, followup_id=followup_id)
        if row is None:
            raise UnknownFollowup(str(followup_id))
        return row

    @staticmethod
    def _write(
        tenant_id: UUID, statement: Any, params: dict[str, Any], *, session: Any = None
    ) -> None:
        """The guarded write: exactly one `open` row must change. Inside the caller's
        `session` when given (raising rolls the caller's whole transaction back)."""
        if session is not None:
            if session.execute(statement, params).rowcount != 1:
                raise InvalidFollowupTransition(f"followup {params['id']} was decided concurrently")
            return
        with tenant_session(tenant_id) as own:
            if own.execute(statement, params).rowcount != 1:
                raise InvalidFollowupTransition(f"followup {params['id']} was decided concurrently")

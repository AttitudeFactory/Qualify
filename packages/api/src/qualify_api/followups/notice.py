"""The public notice «Te enviamos la información por DM 💬» (m-24789646, Fase C · PR 4,
criterion B4): a public reply to the comment, posted AFTER — and only after — the private
message it announces was confirmed sent.

It is an independent step with its own state on the followup row (`notice_*`, 0071 +
0074), never a part of the private message:

    pending ──claim──▶ posting ──▶ posted          (Meta answered with the reply's id)
       │                  ├──────▶ pending         (transient error: backoff, retried)
       │                  └──────▶ failed          (definitive error, ambiguous, or off)
       └── DM failed/dead ──────▶ skipped          (never announced: nothing was sent)

What it decides, and why:

- **Only after a CONFIRMED send.** The outbox row the followup points at
  (`interaction_followups.outbox_id`) must be `sent` with `external_message_id`. A row
  that is `failed` or `dead` — an ambiguous send (`send_ambiguous`), an expired or
  disabled private reply included — never gets its notice: the followup is settled
  `skipped` with the DM's status and code, and Meta is not called. A row still `pending`
  or `sending` is simply waited for.
- **Only what a person approved (ADR 21c).** `notice_status = 'pending'` is written in
  ONE place: the followup's approval (`approve_followup` with a `notice_text`), which in
  turn only runs inside `FollowupService.approve_and_queue` with a `HumanApproval`. This
  module never sets `pending`; it only takes `pending` rows forward.
- **One notice per interaction, whatever the retries.** The followup row is the
  idempotency key. A claim moves `pending → posting` under `FOR UPDATE SKIP LOCKED`, and
  every settle is guarded by `notice_status = 'posting'`, so two workers cannot both post
  and a late settle is a no-op. Meta's id is UNIQUE per connection (0071's partial index).
  Anything that might have reached Meta without an answer — a transport failure after
  the request went out, a 200 without an id, a `posting` row whose worker died — is
  `failed` with `notice_ambiguous`, never retried: a second public reply is worse than a
  missing one, and the person can see the comment.
- **Never touches the DM or the inbox.** It reads the outbox; it writes only the notice
  columns of `interaction_followups`. An auth error fails the notice and does NOT degrade
  the connection (the sender of private messages owns that).
- **Comments only** (`ck_followup_notice_comments_only`) and **only while
  `public_notice` is on**: a poster built with it off settles what reaches it as
  `failed` with `public_notice_disabled` instead of posting — the same rule the sender
  applies to a queued private reply whose capability was switched off.

Codes only in `notice_error_code` and in logs — Meta's numeric codes, never the text.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import Any, Final, Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.conversations.outbox import DEFAULT_BATCH, MemoryConversationOutboxRepository
from qualify_api.conversations.outbox import backoff as outbox_backoff
from qualify_api.conversations.sender import error_code_of
from qualify_api.followups.origins import MemoryOriginReader
from qualify_api.followups.repository import (
    FollowupStatus,
    MemoryFollowupRepository,
    NoticeStatus,
    OriginKind,
)
from qualify_api.replies.client import CommentReplyClient, CommentReplyError

logger = logging.getLogger("qualify_api.followups.notice")

#: What the card proposes; the person may edit it before approving.
DEFAULT_NOTICE_TEXT: Final = "Te enviamos la información por DM 💬"
#: A notice is one line under a comment, not a second message.
MAX_NOTICE_CHARS: Final = 300

MAX_NOTICE_ATTEMPTS: Final = 5
NOTICE_STALE_AFTER: Final = timedelta(minutes=10)

ERROR_NOTICE_AMBIGUOUS: Final = "notice_ambiguous"
ERROR_NOTICE_DISABLED: Final = "public_notice_disabled"
ERROR_NOTICE_MAX_ATTEMPTS: Final = "max_attempts"
#: Prefix of a skipped notice's code: `dm_<outbox status>[:<outbox error code>]`.
SKIPPED_PREFIX: Final = "dm_"

# Transient by Meta's error reference: throttling (4, 17, 32, 613), temporary/unknown (1,
# 2) and HTTP 429/5xx. Everything else Meta answers is definitive for this comment.
_TRANSIENT_HTTP: Final = frozenset({429, 500, 502, 503, 504})
_TRANSIENT_CODES: Final = frozenset({1, 2, 4, 17, 32, 341, 613})


def notice_backoff(attempts: int) -> timedelta:
    """Same curve as the outbox: `4^attempts` seconds."""
    return outbox_backoff(attempts)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def skipped_code(outbox_status: str, outbox_error: str | None) -> str:
    return f"{SKIPPED_PREFIX}{outbox_status}" + (f":{outbox_error}" if outbox_error else "")


@dataclass(frozen=True)
class ClaimedNotice:
    followup_id: UUID
    tenant_id: UUID
    connection_id: UUID
    # The comment it answers (`messages.external_message_id` of the origin).
    comment_external_id: str
    text: str
    attempts: int


@dataclass
class NoticeReport:
    """One tenant's pass. Counters only."""

    tenant_id: UUID
    skipped: int = 0
    claimed: int = 0
    posted: int = 0
    retried: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


class NoticeRepository(Protocol):
    def skip_unsent(self, *, tenant_id: UUID, now: datetime) -> int:
        """`pending → skipped` for every notice whose private message is `failed`/`dead`.
        Returns how many."""
        ...

    def claim(
        self, *, tenant_id: UUID, worker_id: str, now: datetime, limit: int = DEFAULT_BATCH
    ) -> list[ClaimedNotice]:
        """`pending → posting` for due notices whose private message is `sent` with its
        id; a stale `posting` row is first settled `failed` (`notice_ambiguous`)."""
        ...

    def mark_posted(
        self, *, tenant_id: UUID, followup_id: UUID, external_id: str, attempts: int, now: datetime
    ) -> bool: ...

    def mark_retry(
        self,
        *,
        tenant_id: UUID,
        followup_id: UUID,
        attempts: int,
        error_code: str,
        next_attempt_at: datetime,
        now: datetime,
    ) -> bool: ...

    def mark_failed(
        self, *, tenant_id: UUID, followup_id: UUID, attempts: int, error_code: str, now: datetime
    ) -> bool: ...


class NoticeClientFactory(Protocol):
    async def client_for(self, *, tenant_id: UUID, connection_id: UUID) -> CommentReplyClient: ...


# --- memory -------------------------------------------------------------------------------


class MemoryNoticeRepository:
    """Same contract over the memory followups, outbox and origins of the offline suite.
    Every method runs to completion without awaiting, so a claim is atomic between two
    concurrent passes exactly as `SKIP LOCKED` makes it in Postgres."""

    def __init__(
        self,
        *,
        followups: MemoryFollowupRepository,
        outbox: MemoryConversationOutboxRepository,
        origins: MemoryOriginReader,
    ) -> None:
        self._followups = followups
        self._outbox = outbox
        self._origins = origins

    def skip_unsent(self, *, tenant_id: UUID, now: datetime) -> int:
        skipped = 0
        for row in list(self._followups.rows.values()):
            if row.tenant_id != tenant_id or row.notice_status is not NoticeStatus.PENDING:
                continue
            sent = self._outbox.rows.get(row.outbox_id) if row.outbox_id else None
            if sent is None or sent.status not in ("failed", "dead"):
                continue
            self._followups.rows[row.id] = replace(
                row,
                notice_status=NoticeStatus.SKIPPED,
                notice_error_code=skipped_code(sent.status, sent.error_code),
                updated_at=now,
            )
            skipped += 1
        return skipped

    def claim(
        self, *, tenant_id: UUID, worker_id: str, now: datetime, limit: int = DEFAULT_BATCH
    ) -> list[ClaimedNotice]:
        stale = now - NOTICE_STALE_AFTER
        claimed: list[ClaimedNotice] = []
        for row in sorted(self._followups.rows.values(), key=lambda r: r.decided_at or now):
            if row.tenant_id != tenant_id:
                continue
            if (
                row.notice_status is NoticeStatus.POSTING
                and row.notice_locked_at is not None
                and row.notice_locked_at < stale
            ):
                self._followups.rows[row.id] = replace(
                    row,
                    notice_status=NoticeStatus.FAILED,
                    notice_error_code=ERROR_NOTICE_AMBIGUOUS,
                    notice_locked_at=None,
                    updated_at=now,
                )
                continue
            if len(claimed) >= limit or row.notice_status is not NoticeStatus.PENDING:
                continue
            if row.status is not FollowupStatus.APPROVED or row.origin_kind is not (
                OriginKind.COMMENT
            ):
                continue
            if row.notice_next_attempt_at is not None and row.notice_next_attempt_at > now:
                continue
            sent = self._outbox.rows.get(row.outbox_id) if row.outbox_id else None
            if sent is None or sent.status != "sent" or not sent.external_message_id:
                continue
            origin = self._origins.get(tenant_id=tenant_id, message_id=row.origin_message_id)
            if origin is None or not row.notice_text:
                continue
            self._followups.rows[row.id] = replace(
                row, notice_status=NoticeStatus.POSTING, notice_locked_at=now, updated_at=now
            )
            claimed.append(
                ClaimedNotice(
                    followup_id=row.id,
                    tenant_id=row.tenant_id,
                    connection_id=row.connection_id,
                    comment_external_id=origin.external_message_id,
                    text=row.notice_text,
                    attempts=row.notice_attempts,
                )
            )
        return claimed

    def _posting(self, tenant_id: UUID, followup_id: UUID) -> Any:
        row = self._followups.rows.get(followup_id)
        if row is None or row.tenant_id != tenant_id:
            return None
        return row if row.notice_status is NoticeStatus.POSTING else None

    def mark_posted(
        self, *, tenant_id: UUID, followup_id: UUID, external_id: str, attempts: int, now: datetime
    ) -> bool:
        row = self._posting(tenant_id, followup_id)
        if row is None:
            return False
        if any(
            r.connection_id == row.connection_id and r.notice_external_id == external_id
            for r in self._followups.rows.values()
        ):
            raise ValueError("notice_external_id is unique per connection")
        self._followups.rows[followup_id] = replace(
            row,
            notice_status=NoticeStatus.POSTED,
            notice_external_id=external_id,
            notice_posted_at=now,
            notice_attempts=attempts,
            notice_error_code=None,
            notice_next_attempt_at=None,
            notice_locked_at=None,
            updated_at=now,
        )
        return True

    def mark_retry(
        self,
        *,
        tenant_id: UUID,
        followup_id: UUID,
        attempts: int,
        error_code: str,
        next_attempt_at: datetime,
        now: datetime,
    ) -> bool:
        row = self._posting(tenant_id, followup_id)
        if row is None:
            return False
        self._followups.rows[followup_id] = replace(
            row,
            notice_status=NoticeStatus.PENDING,
            notice_attempts=attempts,
            notice_error_code=error_code,
            notice_next_attempt_at=next_attempt_at,
            notice_locked_at=None,
            updated_at=now,
        )
        return True

    def mark_failed(
        self, *, tenant_id: UUID, followup_id: UUID, attempts: int, error_code: str, now: datetime
    ) -> bool:
        row = self._posting(tenant_id, followup_id)
        if row is None:
            return False
        self._followups.rows[followup_id] = replace(
            row,
            notice_status=NoticeStatus.FAILED,
            notice_attempts=attempts,
            notice_error_code=error_code,
            notice_locked_at=None,
            updated_at=now,
        )
        return True


class MemoryCommentReplyClient:
    """A `CommentReplyClient` that publishes nothing: it records what it was asked and
    answers with a fresh id — or raises `fail_with` (once per entry). For the offline
    suite and for `QUALIFY_CONVERSATIONS_DM_CHANNEL=memory`."""

    def __init__(self) -> None:
        self.posted: list[tuple[str, str, str]] = []
        self.fail_with: list[BaseException] = []
        self._ids = count(1)

    async def post_reply(self, *, ig_comment_id: str, message: str) -> str:
        if self.fail_with:
            raise self.fail_with.pop(0)
        reply_id = f"memory-notice-{next(self._ids)}"
        self.posted.append((ig_comment_id, message, reply_id))
        return reply_id


class MemoryNoticeClientFactory:
    def __init__(self, client: MemoryCommentReplyClient | None = None) -> None:
        self.client = client or MemoryCommentReplyClient()

    async def client_for(self, *, tenant_id: UUID, connection_id: UUID) -> CommentReplyClient:
        return self.client


# --- Postgres -----------------------------------------------------------------------------

_SKIP_UNSENT = text(
    """
    UPDATE interaction_followups AS f
       SET notice_status = 'skipped',
           notice_error_code = :prefix || o.status || COALESCE(':' || o.error_code, ''),
           updated_at = :now
      FROM conversation_outbox AS o
     WHERE o.id = f.outbox_id AND o.tenant_id = f.tenant_id
       AND f.notice_status = 'pending' AND o.status IN ('failed', 'dead')
    """
)

_FAIL_STALE = text(
    """
    UPDATE interaction_followups
       SET notice_status = 'failed', notice_error_code = :error,
           notice_locked_at = NULL, notice_locked_by = NULL, updated_at = :now
     WHERE notice_status = 'posting' AND notice_locked_at < :stale
    """
)

# MATERIALIZED, for the reason measured in `whatsapp/outbox.py`; `FOR UPDATE OF f` locks
# only the followup (the outbox and the message are read, never locked).
NOTICE_CLAIM_SQL = text(
    """
    WITH due AS MATERIALIZED (
        SELECT f.id, m.external_message_id AS comment_external_id
          FROM interaction_followups AS f
          JOIN conversation_outbox AS o ON o.id = f.outbox_id AND o.tenant_id = f.tenant_id
          JOIN messages AS m ON m.id = f.origin_message_id AND m.tenant_id = f.tenant_id
         WHERE f.notice_status = 'pending' AND f.status = 'approved'
           AND f.origin_kind = 'comment' AND f.notice_text IS NOT NULL
           AND (f.notice_next_attempt_at IS NULL OR f.notice_next_attempt_at <= :now)
           AND o.status = 'sent' AND o.external_message_id IS NOT NULL
         ORDER BY f.decided_at, f.id
         LIMIT :limit
         FOR UPDATE OF f SKIP LOCKED)
    UPDATE interaction_followups AS f
       SET notice_status = 'posting', notice_locked_at = :now, notice_locked_by = :worker,
           updated_at = :now
      FROM due
     WHERE f.id = due.id AND f.notice_status = 'pending'
    RETURNING f.id, f.tenant_id, f.connection_id, f.notice_text, f.notice_attempts,
              due.comment_external_id
    """
)

_MARK_POSTED = text(
    """
    UPDATE interaction_followups
       SET notice_status = 'posted', notice_external_id = :external_id,
           notice_posted_at = :now, notice_attempts = :attempts, notice_error_code = NULL,
           notice_next_attempt_at = NULL, notice_locked_at = NULL, notice_locked_by = NULL,
           updated_at = :now
     WHERE id = :id AND notice_status = 'posting'
    """
)

_MARK_RETRY = text(
    """
    UPDATE interaction_followups
       SET notice_status = 'pending', notice_attempts = :attempts, notice_error_code = :error,
           notice_next_attempt_at = :next, notice_locked_at = NULL, notice_locked_by = NULL,
           updated_at = :now
     WHERE id = :id AND notice_status = 'posting'
    """
)

_MARK_FAILED = text(
    """
    UPDATE interaction_followups
       SET notice_status = 'failed', notice_attempts = :attempts, notice_error_code = :error,
           notice_locked_at = NULL, notice_locked_by = NULL, updated_at = :now
     WHERE id = :id AND notice_status = 'posting'
    """
)


class PostgresNoticeRepository:
    """The notice columns of `interaction_followups` under RLS (`tenant_session`). Reads
    `conversation_outbox` and `messages`; writes nothing but the notice."""

    def skip_unsent(self, *, tenant_id: UUID, now: datetime) -> int:
        with tenant_session(tenant_id) as session:
            return int(
                session.execute(_SKIP_UNSENT, {"prefix": SKIPPED_PREFIX, "now": now}).rowcount
            )

    def claim(
        self, *, tenant_id: UUID, worker_id: str, now: datetime, limit: int = DEFAULT_BATCH
    ) -> list[ClaimedNotice]:
        with tenant_session(tenant_id) as session:
            session.execute(
                _FAIL_STALE,
                {"error": ERROR_NOTICE_AMBIGUOUS, "stale": now - NOTICE_STALE_AFTER, "now": now},
            )
            rows = session.execute(
                NOTICE_CLAIM_SQL, {"now": now, "limit": limit, "worker": worker_id}
            ).all()
        return [
            ClaimedNotice(
                followup_id=r.id,
                tenant_id=r.tenant_id,
                connection_id=r.connection_id,
                comment_external_id=r.comment_external_id,
                text=r.notice_text,
                attempts=int(r.notice_attempts or 0),
            )
            for r in rows
        ]

    def _settle(self, tenant_id: UUID, statement: Any, params: dict[str, Any]) -> bool:
        with tenant_session(tenant_id) as session:
            changed = session.execute(statement, params).rowcount == 1
        if not changed:
            logger.warning("followups.notice.settle_skipped followup_id=%s", params["id"])
        return changed

    def mark_posted(
        self, *, tenant_id: UUID, followup_id: UUID, external_id: str, attempts: int, now: datetime
    ) -> bool:
        return self._settle(
            tenant_id,
            _MARK_POSTED,
            {"id": followup_id, "external_id": external_id, "attempts": attempts, "now": now},
        )

    def mark_retry(
        self,
        *,
        tenant_id: UUID,
        followup_id: UUID,
        attempts: int,
        error_code: str,
        next_attempt_at: datetime,
        now: datetime,
    ) -> bool:
        return self._settle(
            tenant_id,
            _MARK_RETRY,
            {
                "id": followup_id,
                "attempts": attempts,
                "error": error_code,
                "next": next_attempt_at,
                "now": now,
            },
        )

    def mark_failed(
        self, *, tenant_id: UUID, followup_id: UUID, attempts: int, error_code: str, now: datetime
    ) -> bool:
        return self._settle(
            tenant_id,
            _MARK_FAILED,
            {"id": followup_id, "attempts": attempts, "error": error_code, "now": now},
        )


# --- the poster ---------------------------------------------------------------------------


def _is_transient(exc: CommentReplyError) -> bool:
    return exc.http_status in _TRANSIENT_HTTP or exc.platform_code in _TRANSIENT_CODES


class PublicNoticePoster:
    """One tenant's pass: skip what will never be announced, claim what is due, post it
    through `CommentReplyClient.post_reply` and settle each one. Runs after the sender of
    private messages in the same worker pass (`ConversationsTick`)."""

    def __init__(
        self,
        *,
        notices: NoticeRepository,
        clients: NoticeClientFactory,
        enabled: bool,
        worker_id: str,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._notices = notices
        self._clients = clients
        self._enabled = enabled
        self._worker_id = worker_id
        self._clock = clock

    async def run_once(self, tenant_id: UUID, *, limit: int = DEFAULT_BATCH) -> NoticeReport:
        now = self._clock()
        report = NoticeReport(tenant_id=tenant_id)
        report.skipped = self._notices.skip_unsent(tenant_id=tenant_id, now=now)
        items = self._notices.claim(
            tenant_id=tenant_id, worker_id=self._worker_id, now=now, limit=limit
        )
        report.claimed = len(items)
        for item in items:
            try:
                await self._process(item, report)
            except Exception as exc:  # noqa: BLE001 — one bad row must not stop the batch
                logger.exception("followups.notice.item_error followup_id=%s", item.followup_id)
                report.errors.append(f"{item.followup_id}:{type(exc).__name__}")
        if report.claimed or report.skipped:
            logger.info(
                "followups.notice.batch tenant_id=%s skipped=%d claimed=%d posted=%d "
                "retried=%d failed=%d errors=%d",
                tenant_id,
                report.skipped,
                report.claimed,
                report.posted,
                report.retried,
                report.failed,
                len(report.errors),
            )
        return report

    async def _process(self, item: ClaimedNotice, report: NoticeReport) -> None:
        if not self._enabled:
            self._fail(item, item.attempts, ERROR_NOTICE_DISABLED, report)
            return
        attempts = item.attempts + 1
        try:
            client = await self._clients.client_for(
                tenant_id=item.tenant_id, connection_id=item.connection_id
            )
        except Exception as exc:  # noqa: BLE001 — nothing was sent: safe to retry
            logger.warning(
                "followups.notice.client_failed followup_id=%s code=%s",
                item.followup_id,
                type(exc).__name__,
            )
            self._retry(item, attempts, type(exc).__name__, report)
            return
        try:
            external_id = await client.post_reply(
                ig_comment_id=item.comment_external_id, message=item.text
            )
        except CommentReplyError as exc:
            code = error_code_of(exc)
            logger.warning(
                "followups.notice.post_failed followup_id=%s code=%s ambiguous=%s",
                item.followup_id,
                code,
                exc.is_ambiguous,
            )
            if exc.is_ambiguous or exc.http_status is None:
                # The request went out (or Meta answered 200 without an id): it may be
                # public already. Never post it a second time.
                self._fail(item, attempts, ERROR_NOTICE_AMBIGUOUS, report)
            elif _is_transient(exc):
                self._retry(item, attempts, code, report)
            else:
                self._fail(item, attempts, code, report)
            return
        except Exception:  # noqa: BLE001 — unknown outcome after the request: ambiguous
            logger.exception("followups.notice.post_error followup_id=%s", item.followup_id)
            self._fail(item, attempts, ERROR_NOTICE_AMBIGUOUS, report)
            return
        if self._notices.mark_posted(
            tenant_id=item.tenant_id,
            followup_id=item.followup_id,
            external_id=external_id,
            attempts=attempts,
            now=self._clock(),
        ):
            report.posted += 1

    def _retry(self, item: ClaimedNotice, attempts: int, code: str, report: NoticeReport) -> None:
        if attempts >= MAX_NOTICE_ATTEMPTS:
            self._fail(item, attempts, f"{ERROR_NOTICE_MAX_ATTEMPTS}:{code}", report)
            return
        now = self._clock()
        if self._notices.mark_retry(
            tenant_id=item.tenant_id,
            followup_id=item.followup_id,
            attempts=attempts,
            error_code=code,
            next_attempt_at=now + notice_backoff(attempts),
            now=now,
        ):
            report.retried += 1

    def _fail(self, item: ClaimedNotice, attempts: int, code: str, report: NoticeReport) -> None:
        if self._notices.mark_failed(
            tenant_id=item.tenant_id,
            followup_id=item.followup_id,
            attempts=attempts,
            error_code=code,
            now=self._clock(),
        ):
            report.failed += 1


__all__ = [
    "DEFAULT_NOTICE_TEXT",
    "ERROR_NOTICE_AMBIGUOUS",
    "ERROR_NOTICE_DISABLED",
    "ERROR_NOTICE_MAX_ATTEMPTS",
    "MAX_NOTICE_ATTEMPTS",
    "MAX_NOTICE_CHARS",
    "NOTICE_STALE_AFTER",
    "ClaimedNotice",
    "MemoryCommentReplyClient",
    "MemoryNoticeClientFactory",
    "MemoryNoticeRepository",
    "NoticeClientFactory",
    "NoticeReport",
    "NoticeRepository",
    "PostgresNoticeRepository",
    "PublicNoticePoster",
    "notice_backoff",
    "skipped_code",
]

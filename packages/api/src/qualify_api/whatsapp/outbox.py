"""The outbound side of WhatsApp (WA-08, QUA-208): the `whatsapp_outbox` queue and the
sender that drains it.

Backlog: `docs/backlog-modulo-whatsapp.md` §2 WA-08. Plan: `docs/plan-modulo-whatsapp-
cloud-api.md` §2.4 (pair rate limit 1 msg / 6 s, retry `4^X` s) and §5.2 (window as
policy). Schema: migration 0057 / `whatsapp/models.py`.

## Who writes the queue, who drains it

- **Producers** `enqueue` an already-built `/messages` body (one of `client.build_*_body`):
  the HTTP API for a person's reply (WA-10, `kind='reply'`), the inbound handler for what
  the menu engine answers (WA-07/WA-14, `kind='automation'`, running as
  `qualify_webhook_worker`, which holds INSERT only) and, later, campaigns (WA-18,
  `kind='campaign_send'`). Nothing sends inline: a send is a row.
- **The sender** (`OutboxSender`, this module, run by `whatsapp/worker.py` as `qualify_app`
  under `tenant_session`) claims due rows with `FOR UPDATE SKIP LOCKED`, applies the two
  policies that must hold for EVERY producer — the 24 h window (`window.py`) and the
  per-recipient pacing — sends, and records the outcome on the row AND as the outbound
  `messages` row the `statuses[]` webhook (WA-07) later updates by `wamid`.

## Outcomes, one per claimed row

- **sent** — Meta accepted (`wamid`): `status='sent'`, `wamid`, `sent_at`; plus the
  outbound `messages` row and `threads.last_message_at`.
- **deferred** — another message went to the same recipient < 6 s ago: back to
  `pending`, `next_attempt_at = last + 6 s`, **no attempt counted**.
- **failed** (terminal; a person decides, WA-11 shows it) — window closed for a
  free-form kind (`window_closed`), Meta's window codes `131047`/`131026`, any other 4xx.
- **retry** — transport failure (ambiguous: the message MAY have gone out), HTTP
  429/5xx, Meta's throttling codes: `pending`, `attempts+1`,
  `next_attempt_at = now + 4**attempts s`.
- **dead** (terminal; needs an operator) — auth failure (401 / code 190: the connection
  is degraded first, QUA-90), or the fifth failed attempt.

The backoff is Meta's own recommendation (`4^X` seconds, cloud-api/overview): 4 s, 16 s,
64 s, 256 s, then dead after the fifth failure (`MAX_ATTEMPTS`).

## Idempotency and crashes

A row is claimed by moving it to `sending` with a lock; a worker that dies mid-send leaves
it there and the next claim reclaims it after `STALE_AFTER` **counting an attempt**, so a
crash loop cannot resend forever. A reclaimed row MAY produce a duplicate on the
recipient's phone (the send might have gone through before the crash) — the same
ambiguity the transport retry accepts; `messages` cannot duplicate (`uq_message_external_
id` on `wamid`, insert is `ON CONFLICT DO NOTHING`). Two workers at once are safe: the
claim is `SKIP LOCKED`, every settle is guarded by `status = 'sending'`.

## No user text in logs

Log lines carry ids, kinds, status codes and Meta error codes — never `payload`
(backlog §1, the `CommentsReadError` / `WAChangeSummary` pattern).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import Any, Final, Protocol
from uuid import UUID, uuid4

from qualify_shared.db.session import tenant_session
from qualify_shared.social.wa_shapes import SHAPE_VERSION
from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from qualify_api.inbox.models import Message, Thread
from qualify_api.whatsapp.client import WhatsAppApiError, WhatsAppClient
from qualify_api.whatsapp.models import OUTBOX_KINDS, WhatsAppOutboxItem
from qualify_api.whatsapp.window import (
    FREE_FORM_KINDS,
    WINDOW_CLOSED_ERROR_CODES,
    is_free_form_allowed,
    window_state,
)

logger = logging.getLogger("qualify_api.whatsapp.outbox")

MAX_ATTEMPTS: Final = 5
BACKOFF_BASE_SECONDS: Final = 4
# cloud-api/overview: one message every 6 s to the same (number, user) pair (~600/h).
PACING: Final = timedelta(seconds=6)
# A `sending` row whose lock is older than this belongs to a dead worker.
STALE_AFTER: Final = timedelta(minutes=10)
DEFAULT_BATCH: Final = 50

ERROR_WINDOW_CLOSED: Final = "window_closed"
ERROR_AUTH: Final = "auth"
ERROR_TRANSPORT: Final = "transport"
ERROR_NO_RECIPIENT: Final = "no_recipient"
ERROR_STALE_EXHAUSTED: Final = "stale_lock_attempts_exhausted"

# Meta error codes that ride an HTTP 400 but mean "try later", from the Cloud API
# error-codes reference (support/error-codes, read 2026-10-14; not yet seen live):
# 4 / 80007 (Graph app-level throttling), 130429 (rate limit hit), 131056 (pair rate
# limit hit), 131016 (service unavailable), 131000 (something went wrong, generic).
RETRYABLE_ERROR_CODES: Final = frozenset({4, 80007, 130429, 131056, 131016, 131000})

_NON_DIGITS = re.compile(r"\D")


def backoff(attempts: int) -> timedelta:
    """Delay before the next try after `attempts` failures: `4^attempts` seconds."""
    return timedelta(seconds=BACKOFF_BASE_SECONDS**attempts)


def recipient_digits(to: str) -> str:
    """`to` may be stored as `+57300…` or `57300…` (Meta accepts both); the pair limit is
    about the same phone either way."""
    return _NON_DIGITS.sub("", to)


def payload_text(payload: dict[str, Any]) -> str | None:
    """The human-readable text of a stored body, for `messages.text`: a text message's
    body, or an interactive message's body text. Media captions and templates give
    `None` — WA-11 renders those from the payload kind, not from `text`."""
    kind = payload.get("type")
    if kind == "text":
        body = payload.get("text")
        value = body.get("body") if isinstance(body, dict) else None
    elif kind == "interactive":
        interactive = payload.get("interactive")
        body = interactive.get("body") if isinstance(interactive, dict) else None
        value = body.get("text") if isinstance(body, dict) else None
    else:
        value = None
    return value if isinstance(value, str) and value else None


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ======================================================================================
# Repository seam
# ======================================================================================


@dataclass(frozen=True)
class ClaimedOutboxItem:
    """What the sender needs of a claimed row — never the lock columns, never `status`."""

    id: UUID
    tenant_id: UUID
    connection_id: UUID
    thread_id: UUID | None
    kind: str
    payload: dict[str, Any]
    attempts: int

    @property
    def recipient(self) -> str | None:
        to = self.payload.get("to")
        return to if isinstance(to, str) and to else None


class OutboxRepository(Protocol):
    """Every method is tenant-scoped by `tenant_id` (the Postgres implementation opens
    `tenant_session(tenant_id)` per call, so RLS bounds every statement). Writes are
    guarded by the row's current status, so a late or duplicate settle is a no-op."""

    def enqueue(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        thread_id: UUID | None,
        kind: str,
        payload: dict[str, Any],
        created_by_user_id: UUID | None,
    ) -> UUID:
        """Queue an already-built `/messages` body. `kind` must be one of
        `models.OUTBOX_KINDS`; a free-form kind (`reply`, `automation`) needs `thread_id`
        — the window is decided from that thread. Returns the new row id."""
        ...

    def claim(
        self, *, tenant_id: UUID, worker_id: str, now: datetime, limit: int
    ) -> list[ClaimedOutboxItem]: ...

    def mark_sent(self, *, tenant_id: UUID, item_id: UUID, wamid: str, now: datetime) -> None:
        """`sending → sent`, plus the outbound `messages` row (when the item has a thread)
        and the thread's `last_message_at` bump."""
        ...

    def mark_retry(
        self,
        *,
        tenant_id: UUID,
        item_id: UUID,
        attempts: int,
        error_code: str | None,
        next_attempt_at: datetime,
    ) -> None:
        """`sending → pending`, due at `next_attempt_at`, with `attempts` set as given
        (the sender decides whether the try counted)."""
        ...

    def mark_failed(
        self, *, tenant_id: UUID, item_id: UUID, error_code: str, attempts: int | None = None
    ) -> None:
        """Terminal. `attempts`, when given, records the try that produced the verdict
        (a window refusal decided locally passes `None`: nothing was tried)."""
        ...

    def mark_dead(
        self, *, tenant_id: UUID, item_id: UUID, error_code: str, attempts: int | None = None
    ) -> None: ...

    def thread_last_inbound(self, *, tenant_id: UUID, thread_id: UUID) -> datetime | None: ...

    def last_outbound_to_recipient(
        self, *, tenant_id: UUID, connection_id: UUID, recipient: str, since: datetime
    ) -> datetime | None:
        """When this number last sent anything to `recipient` (digits compared), looking
        back no further than `since`. `None` = nothing in that span."""
        ...


def _validate_enqueue(kind: str, payload: dict[str, Any], thread_id: UUID | None) -> None:
    if kind not in OUTBOX_KINDS:
        raise ValueError(f"unknown outbox kind {kind!r}")
    if not isinstance(payload, dict) or not payload:
        raise ValueError("payload must be a non-empty /messages body")
    to = payload.get("to")
    if not isinstance(to, str) or not to:
        raise ValueError("payload must carry a recipient in 'to'")
    if kind in FREE_FORM_KINDS and thread_id is None:
        raise ValueError(f"a {kind!r} needs a thread: the 24 h window is decided from it")


# --------------------------------------------------------------------------------------
# Postgres
# --------------------------------------------------------------------------------------

_CLAIM_DEAD_STALE = text(
    """
    UPDATE whatsapp_outbox
       SET status = 'dead', error_code = :error, locked_at = NULL, locked_by = NULL
     WHERE status = 'sending' AND locked_at < :stale AND attempts >= :max
    """
)

# A reclaimed stale row counts an attempt (see the module docstring); a fresh claim does
# not — the sender counts attempts on the outcome, so pacing can defer for free.
#
# The pick is a MATERIALIZED CTE, not `WHERE id IN (SELECT … LIMIT n FOR UPDATE SKIP
# LOCKED)`. Measured on Postgres 16 (CI run 38548295477 and locally): in the `IN (…)`
# form the planner may re-run the locking subplan per outer row, and once the statement's
# own updates have turned the first picks into `sending`, the re-run picks the NEXT due
# rows — a `LIMIT 2` claim returned 3. A materialized CTE is evaluated exactly once, so
# the lock set and the update set are the same rows.
CLAIM_SQL = text(
    """
    WITH due AS MATERIALIZED (
        SELECT id FROM whatsapp_outbox
         WHERE (status = 'pending' AND next_attempt_at <= :now)
            OR (status = 'sending' AND locked_at < :stale)
         ORDER BY created_at, id
         LIMIT :limit
         FOR UPDATE SKIP LOCKED)
    UPDATE whatsapp_outbox AS o
       SET status = 'sending', locked_by = :worker, locked_at = :now,
           attempts = CASE WHEN o.status = 'sending' THEN o.attempts + 1 ELSE o.attempts END
      FROM due
     WHERE o.id = due.id
    RETURNING o.id, o.tenant_id, o.connection_id, o.thread_id, o.kind, o.payload, o.attempts,
              o.created_at
    """
)

_LAST_OUTBOUND = text(
    r"""
    SELECT max(sent_at) FROM whatsapp_outbox
     WHERE connection_id = :connection_id AND status = 'sent' AND sent_at >= :since
       AND regexp_replace(payload->>'to', '\D', '', 'g') = :digits
    """
)


class PostgresOutboxRepository:
    """The real queue, through `tenant_session` (the `qualify_app` role: SELECT, INSERT,
    UPDATE on `whatsapp_outbox`, `messages` and `threads` — never DELETE).

    `last_outbound_to_recipient` scans the tenant's `sent` rows for the connection in the
    last `since` span; there is no `(connection_id, sent_at)` index yet, which is fine at
    one number's volume and is the index to add (architect call) when it is not."""

    def enqueue(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        thread_id: UUID | None,
        kind: str,
        payload: dict[str, Any],
        created_by_user_id: UUID | None,
    ) -> UUID:
        _validate_enqueue(kind, payload, thread_id)
        with tenant_session(tenant_id) as session:
            row = WhatsAppOutboxItem(
                tenant_id=tenant_id,
                connection_id=connection_id,
                thread_id=thread_id,
                kind=kind,
                payload=payload,
                created_by_user_id=created_by_user_id,
            )
            session.add(row)
            session.flush()
            return row.id

    def claim(
        self, *, tenant_id: UUID, worker_id: str, now: datetime, limit: int
    ) -> list[ClaimedOutboxItem]:
        stale = now - STALE_AFTER
        with tenant_session(tenant_id) as session:
            session.execute(
                _CLAIM_DEAD_STALE,
                {"error": ERROR_STALE_EXHAUSTED, "stale": stale, "max": MAX_ATTEMPTS},
            )
            rows = session.execute(
                CLAIM_SQL, {"worker": worker_id, "now": now, "stale": stale, "limit": limit}
            ).all()
        rows = sorted(rows, key=lambda r: (r.created_at, str(r.id)))
        return [
            ClaimedOutboxItem(
                id=r.id,
                tenant_id=r.tenant_id,
                connection_id=r.connection_id,
                thread_id=r.thread_id,
                kind=r.kind,
                payload=dict(r.payload),
                attempts=int(r.attempts),
            )
            for r in rows
        ]

    def mark_sent(self, *, tenant_id: UUID, item_id: UUID, wamid: str, now: datetime) -> None:
        with tenant_session(tenant_id) as session:
            item = session.get(WhatsAppOutboxItem, item_id)
            if item is None or item.status != "sending":
                logger.warning("whatsapp.outbox.settle_skipped item_id=%s outcome=sent", item_id)
                return
            item.status = "sent"
            item.wamid = wamid
            item.sent_at = now
            item.error_code = None
            item.locked_by = None
            item.locked_at = None
            if item.thread_id is None:
                return
            session.execute(
                pg_insert(Message)
                .values(
                    tenant_id=tenant_id,
                    thread_id=item.thread_id,
                    connection_id=item.connection_id,
                    external_message_id=wamid,
                    direction="outbound",
                    text=payload_text(item.payload),
                    posted_at=now,
                    shape_version=SHAPE_VERSION,
                    delivery_status="sent",
                )
                .on_conflict_do_nothing(constraint="uq_message_external_id")
            )
            session.execute(
                update(Thread)
                .where(Thread.id == item.thread_id)
                .where((Thread.last_message_at.is_(None)) | (Thread.last_message_at < now))
                .values(last_message_at=now)
            )

    def _settle(self, tenant_id: UUID, item_id: UUID, outcome: str, **values: Any) -> None:
        with tenant_session(tenant_id) as session:
            result = session.execute(
                update(WhatsAppOutboxItem)
                .where(WhatsAppOutboxItem.id == item_id)
                .where(WhatsAppOutboxItem.status == "sending")
                .values(locked_by=None, locked_at=None, **values)
            )
            if result.rowcount == 0:
                logger.warning(
                    "whatsapp.outbox.settle_skipped item_id=%s outcome=%s", item_id, outcome
                )

    def mark_retry(
        self,
        *,
        tenant_id: UUID,
        item_id: UUID,
        attempts: int,
        error_code: str | None,
        next_attempt_at: datetime,
    ) -> None:
        self._settle(
            tenant_id,
            item_id,
            "retry",
            status="pending",
            attempts=attempts,
            error_code=error_code,
            next_attempt_at=next_attempt_at,
        )

    def mark_failed(
        self, *, tenant_id: UUID, item_id: UUID, error_code: str, attempts: int | None = None
    ) -> None:
        extra = {} if attempts is None else {"attempts": attempts}
        self._settle(tenant_id, item_id, "failed", status="failed", error_code=error_code, **extra)

    def mark_dead(
        self, *, tenant_id: UUID, item_id: UUID, error_code: str, attempts: int | None = None
    ) -> None:
        extra = {} if attempts is None else {"attempts": attempts}
        self._settle(tenant_id, item_id, "dead", status="dead", error_code=error_code, **extra)

    def thread_last_inbound(self, *, tenant_id: UUID, thread_id: UUID) -> datetime | None:
        with tenant_session(tenant_id) as session:
            return session.scalar(select(Thread.last_inbound_at).where(Thread.id == thread_id))

    def last_outbound_to_recipient(
        self, *, tenant_id: UUID, connection_id: UUID, recipient: str, since: datetime
    ) -> datetime | None:
        with tenant_session(tenant_id) as session:
            return session.scalar(
                _LAST_OUTBOUND,
                {
                    "connection_id": connection_id,
                    "since": since,
                    "digits": recipient_digits(recipient),
                },
            )


# --------------------------------------------------------------------------------------
# In-memory (tests)
# --------------------------------------------------------------------------------------


@dataclass
class MemoryOutboxRow:
    id: UUID
    tenant_id: UUID
    connection_id: UUID
    thread_id: UUID | None
    kind: str
    payload: dict[str, Any]
    created_at: datetime
    next_attempt_at: datetime
    status: str = "pending"
    attempts: int = 0
    locked_by: str | None = None
    locked_at: datetime | None = None
    wamid: str | None = None
    error_code: str | None = None
    created_by_user_id: UUID | None = None
    sent_at: datetime | None = None
    # Insertion order — the tie-break Postgres gets for free because every enqueue is its
    # own transaction with its own now(); a frozen test clock would otherwise leave two
    # rows tied on created_at and ordered by their random ids.
    seq: int = 0


@dataclass(frozen=True)
class MemoryOutboundMessage:
    tenant_id: UUID
    thread_id: UUID
    connection_id: UUID
    wamid: str
    text: str | None
    posted_at: datetime
    delivery_status: str


class MemoryOutboxRepository:
    """Same contract, in dictionaries. `threads` maps `thread_id -> last_inbound_at`
    (set it to open/close a window); `messages` is what `mark_sent` wrote."""

    def __init__(self, *, clock: Callable[[], datetime] = _utcnow) -> None:
        self._clock = clock
        self._seq = count()
        self.rows: dict[UUID, MemoryOutboxRow] = {}
        self.threads: dict[UUID, datetime | None] = {}
        self.thread_last_message_at: dict[UUID, datetime] = {}
        self.messages: list[MemoryOutboundMessage] = []

    def enqueue(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        thread_id: UUID | None,
        kind: str,
        payload: dict[str, Any],
        created_by_user_id: UUID | None,
    ) -> UUID:
        _validate_enqueue(kind, payload, thread_id)
        now = self._clock()
        row = MemoryOutboxRow(
            id=uuid4(),
            tenant_id=tenant_id,
            connection_id=connection_id,
            thread_id=thread_id,
            kind=kind,
            payload=dict(payload),
            created_at=now,
            next_attempt_at=now,
            created_by_user_id=created_by_user_id,
            seq=next(self._seq),
        )
        self.rows[row.id] = row
        return row.id

    def claim(
        self, *, tenant_id: UUID, worker_id: str, now: datetime, limit: int
    ) -> list[ClaimedOutboxItem]:
        stale = now - STALE_AFTER
        claimed: list[ClaimedOutboxItem] = []
        for row in sorted(self.rows.values(), key=lambda r: (r.created_at, r.seq)):
            if row.tenant_id != tenant_id or len(claimed) >= limit:
                continue
            is_stale = (
                row.status == "sending" and row.locked_at is not None and row.locked_at < stale
            )
            if is_stale and row.attempts >= MAX_ATTEMPTS:
                row.status, row.error_code = "dead", ERROR_STALE_EXHAUSTED
                row.locked_by = row.locked_at = None
                continue
            due = row.status == "pending" and row.next_attempt_at <= now
            if not (due or is_stale):
                continue
            if is_stale:
                row.attempts += 1
            row.status, row.locked_by, row.locked_at = "sending", worker_id, now
            claimed.append(
                ClaimedOutboxItem(
                    id=row.id,
                    tenant_id=row.tenant_id,
                    connection_id=row.connection_id,
                    thread_id=row.thread_id,
                    kind=row.kind,
                    payload=dict(row.payload),
                    attempts=row.attempts,
                )
            )
        return claimed

    def _sending(self, tenant_id: UUID, item_id: UUID) -> MemoryOutboxRow | None:
        row = self.rows.get(item_id)
        if row is None or row.tenant_id != tenant_id or row.status != "sending":
            return None
        row.locked_by = row.locked_at = None
        return row

    def mark_sent(self, *, tenant_id: UUID, item_id: UUID, wamid: str, now: datetime) -> None:
        row = self._sending(tenant_id, item_id)
        if row is None:
            return
        row.status, row.wamid, row.sent_at, row.error_code = "sent", wamid, now, None
        if row.thread_id is None:
            return
        if any(m.connection_id == row.connection_id and m.wamid == wamid for m in self.messages):
            return
        self.messages.append(
            MemoryOutboundMessage(
                tenant_id=tenant_id,
                thread_id=row.thread_id,
                connection_id=row.connection_id,
                wamid=wamid,
                text=payload_text(row.payload),
                posted_at=now,
                delivery_status="sent",
            )
        )
        previous = self.thread_last_message_at.get(row.thread_id)
        if previous is None or previous < now:
            self.thread_last_message_at[row.thread_id] = now

    def mark_retry(
        self,
        *,
        tenant_id: UUID,
        item_id: UUID,
        attempts: int,
        error_code: str | None,
        next_attempt_at: datetime,
    ) -> None:
        row = self._sending(tenant_id, item_id)
        if row is not None:
            row.status, row.attempts = "pending", attempts
            row.error_code, row.next_attempt_at = error_code, next_attempt_at

    def mark_failed(
        self, *, tenant_id: UUID, item_id: UUID, error_code: str, attempts: int | None = None
    ) -> None:
        row = self._sending(tenant_id, item_id)
        if row is not None:
            row.status, row.error_code = "failed", error_code
            row.attempts = row.attempts if attempts is None else attempts

    def mark_dead(
        self, *, tenant_id: UUID, item_id: UUID, error_code: str, attempts: int | None = None
    ) -> None:
        row = self._sending(tenant_id, item_id)
        if row is not None:
            row.status, row.error_code = "dead", error_code
            row.attempts = row.attempts if attempts is None else attempts

    def thread_last_inbound(self, *, tenant_id: UUID, thread_id: UUID) -> datetime | None:
        return self.threads.get(thread_id)

    def last_outbound_to_recipient(
        self, *, tenant_id: UUID, connection_id: UUID, recipient: str, since: datetime
    ) -> datetime | None:
        digits = recipient_digits(recipient)
        candidates = [
            row.sent_at
            for row in self.rows.values()
            if row.tenant_id == tenant_id
            and row.connection_id == connection_id
            and row.status == "sent"
            and row.sent_at is not None
            and row.sent_at >= since
            and recipient_digits(str(row.payload.get("to", ""))) == digits
        ]
        return max(candidates) if candidates else None


# ======================================================================================
# Sender
# ======================================================================================


class ClientFactory(Protocol):
    """Builds the client that sends from THIS connection's number. Production: the
    credential resolver (`ResolverClientFactory` below). Tests: a fake."""

    async def __call__(self, *, tenant_id: UUID, connection_id: UUID) -> WhatsAppClient: ...


class ConnectionDegrader(Protocol):
    """`connections.composition.degrade_connection_on_auth_error`'s shape (QUA-90)."""

    def __call__(self, *, tenant_id: UUID, connection_id: UUID) -> object: ...


@dataclass
class SendReport:
    """One tenant's pass. Counters only — no payloads, no recipients."""

    tenant_id: UUID
    claimed: int = 0
    sent: int = 0
    deferred: int = 0
    retried: int = 0
    failed: int = 0
    dead: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def settled(self) -> int:
        return self.sent + self.deferred + self.retried + self.failed + self.dead


def _error_code(exc: WhatsAppApiError) -> str:
    if exc.code is not None:
        return str(exc.code)
    if exc.status is not None:
        return f"http_{exc.status}"
    return ERROR_TRANSPORT if exc.is_transport else "unknown"


def _is_retryable(exc: WhatsAppApiError) -> bool:
    if exc.status == 429 or (exc.status is not None and exc.status >= 500):
        return True
    return exc.code in RETRYABLE_ERROR_CODES


class OutboxSender:
    """Drains one tenant's due outbox rows: claim → window → pacing → send → settle.

    `clock` is injected so the window boundary, the pacing and the backoff are testable
    to the second; `worker_id` names the lock holder (`hostname:pid` in production)."""

    def __init__(
        self,
        repository: OutboxRepository,
        client_factory: ClientFactory,
        degrade: ConnectionDegrader,
        *,
        worker_id: str,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._repo = repository
        self._clients = client_factory
        self._degrade = degrade
        self._worker_id = worker_id
        self._clock = clock

    async def run_once(self, tenant_id: UUID, *, limit: int = DEFAULT_BATCH) -> SendReport:
        now = self._clock()
        items = self._repo.claim(
            tenant_id=tenant_id, worker_id=self._worker_id, now=now, limit=limit
        )
        report = SendReport(tenant_id=tenant_id, claimed=len(items))
        clients: dict[UUID, WhatsAppClient] = {}
        degraded: set[UUID] = set()
        for item in items:
            try:
                await self._process(item, clients=clients, degraded=degraded, report=report)
            except Exception as exc:  # noqa: BLE001 — one bad row must not stop the batch
                logger.exception(
                    "whatsapp.outbox.item_error item_id=%s kind=%s", item.id, item.kind
                )
                report.errors.append(f"{item.id}:{type(exc).__name__}")
                self._retry(item, type(exc).__name__, report)
        if report.claimed:
            logger.info(
                "whatsapp.outbox.batch tenant_id=%s claimed=%d sent=%d deferred=%d retried=%d "
                "failed=%d dead=%d errors=%d",
                tenant_id,
                report.claimed,
                report.sent,
                report.deferred,
                report.retried,
                report.failed,
                report.dead,
                len(report.errors),
            )
        return report

    async def _process(
        self,
        item: ClaimedOutboxItem,
        *,
        clients: dict[UUID, WhatsAppClient],
        degraded: set[UUID],
        report: SendReport,
    ) -> None:
        tenant_id = item.tenant_id
        if item.connection_id in degraded:
            # An earlier row of this batch already proved the credential dead.
            self._repo.mark_dead(tenant_id=tenant_id, item_id=item.id, error_code=ERROR_AUTH)
            report.dead += 1
            return

        now = self._clock()
        last_inbound = (
            self._repo.thread_last_inbound(tenant_id=tenant_id, thread_id=item.thread_id)
            if item.thread_id is not None
            else None
        )
        if not is_free_form_allowed(item.kind, window_state(last_inbound, now)):
            self._repo.mark_failed(
                tenant_id=tenant_id, item_id=item.id, error_code=ERROR_WINDOW_CLOSED
            )
            report.failed += 1
            return

        recipient = item.recipient
        if recipient is None:
            self._repo.mark_failed(
                tenant_id=tenant_id, item_id=item.id, error_code=ERROR_NO_RECIPIENT
            )
            report.failed += 1
            return
        last_sent = self._repo.last_outbound_to_recipient(
            tenant_id=tenant_id,
            connection_id=item.connection_id,
            recipient=recipient,
            since=now - PACING,
        )
        if last_sent is not None and now - last_sent < PACING:
            self._repo.mark_retry(
                tenant_id=tenant_id,
                item_id=item.id,
                attempts=item.attempts,  # pacing is not a failure
                error_code=None,
                next_attempt_at=last_sent + PACING,
            )
            report.deferred += 1
            return

        client = clients.get(item.connection_id)
        if client is None:
            client = await self._clients(tenant_id=tenant_id, connection_id=item.connection_id)
            clients[item.connection_id] = client
        try:
            wamid = await client.send_payload(item.payload)
        except WhatsAppApiError as exc:
            self._settle_api_error(item, exc, degraded=degraded, report=report)
            return
        self._repo.mark_sent(tenant_id=tenant_id, item_id=item.id, wamid=wamid, now=self._clock())
        report.sent += 1

    def _settle_api_error(
        self,
        item: ClaimedOutboxItem,
        exc: WhatsAppApiError,
        *,
        degraded: set[UUID],
        report: SendReport,
    ) -> None:
        code = _error_code(exc)
        logger.warning(
            "whatsapp.outbox.send_failed item_id=%s kind=%s status=%s code=%s transport=%s",
            item.id,
            item.kind,
            exc.status,
            exc.code,
            exc.is_transport,
        )
        if exc.is_auth_error:
            degraded.add(item.connection_id)
            try:
                self._degrade(tenant_id=item.tenant_id, connection_id=item.connection_id)
            except Exception:  # noqa: BLE001 — the row must still settle
                logger.exception(
                    "whatsapp.outbox.degrade_failed connection_id=%s", item.connection_id
                )
            self._repo.mark_dead(
                tenant_id=item.tenant_id,
                item_id=item.id,
                error_code=ERROR_AUTH,
                attempts=item.attempts + 1,
            )
            report.dead += 1
        elif exc.is_transport:
            self._retry(item, ERROR_TRANSPORT, report)
        elif exc.code in WINDOW_CLOSED_ERROR_CODES:
            self._repo.mark_failed(tenant_id=item.tenant_id, item_id=item.id, error_code=code)
            report.failed += 1
        elif _is_retryable(exc):
            self._retry(item, code, report)
        else:
            self._repo.mark_failed(tenant_id=item.tenant_id, item_id=item.id, error_code=code)
            report.failed += 1

    def _retry(self, item: ClaimedOutboxItem, code: str, report: SendReport) -> None:
        attempts = item.attempts + 1
        if attempts >= MAX_ATTEMPTS:
            self._repo.mark_dead(
                tenant_id=item.tenant_id, item_id=item.id, error_code=code, attempts=attempts
            )
            report.dead += 1
            return
        self._repo.mark_retry(
            tenant_id=item.tenant_id,
            item_id=item.id,
            attempts=attempts,
            error_code=code,
            next_attempt_at=self._clock() + backoff(attempts),
        )
        report.retried += 1


# ======================================================================================
# Production wiring
# ======================================================================================


def phone_number_id_for(*, tenant_id: UUID, connection_id: UUID) -> str:
    """The Meta `phone_number_id` a connection sends from: `whatsapp_phone_numbers` first
    (WA-05 writes it), else `social_connections.external_account_id` (0057: the same
    value, the key the webhook resolves by). Read through RLS — another tenant's
    connection reads as missing."""
    from qualify_api.connections.models import SocialConnection  # noqa: PLC0415
    from qualify_api.whatsapp.models import WhatsAppPhoneNumber  # noqa: PLC0415

    with tenant_session(tenant_id) as session:
        phone_number_id = session.scalar(
            select(WhatsAppPhoneNumber.phone_number_id).where(
                WhatsAppPhoneNumber.connection_id == connection_id
            )
        )
        if not phone_number_id:
            phone_number_id = session.scalar(
                select(SocialConnection.external_account_id).where(
                    (SocialConnection.id == connection_id)
                    & (SocialConnection.platform == "whatsapp")
                )
            )
    if not phone_number_id:
        raise LookupError(f"no WhatsApp phone number for connection {connection_id}")
    return phone_number_id


class ResolverClientFactory:
    """`CredentialResolver.client_for(connection_id, scheme=…)` → `HttpWhatsAppClient`
    bound to the connection's number. The token never reaches this module: the resolver
    injects it into the HTTP client it returns (R3). Built per connection, like
    `inbox.composition.production_inbox_service_for`."""

    def __init__(self, settings: Any, encryptor: Any) -> None:
        self._settings = settings
        self._encryptor = encryptor

    async def __call__(self, *, tenant_id: UUID, connection_id: UUID) -> WhatsAppClient:
        from qualify_api.connections.credential_reader import DbCredentialReader  # noqa: PLC0415
        from qualify_api.connections.resolver import InjectingCredentialResolver  # noqa: PLC0415
        from qualify_api.whatsapp.client import HttpWhatsAppClient  # noqa: PLC0415

        resolver = InjectingCredentialResolver(DbCredentialReader(tenant_id), self._encryptor)
        graph = await resolver.client_for(connection_id, scheme=self._settings.graph_auth_scheme)
        return HttpWhatsAppClient(
            graph,
            self._settings.graph_url,
            phone_number_id=phone_number_id_for(tenant_id=tenant_id, connection_id=connection_id),
        )


def production_outbox_sender(*, worker_id: str) -> OutboxSender:
    """The real sender: Postgres queue, resolver-built clients, QUA-90's degrader.
    Imports resolved here so importing this module needs no Meta settings."""
    from qualify_api.config import MetaOAuthSettings  # noqa: PLC0415
    from qualify_api.connections.composition import (  # noqa: PLC0415
        degrade_connection_on_auth_error,
    )
    from qualify_api.connections.crypto import DevEncryptor  # noqa: PLC0415

    return OutboxSender(
        PostgresOutboxRepository(),
        ResolverClientFactory(MetaOAuthSettings.from_env(), DevEncryptor()),
        degrade_connection_on_auth_error,
        worker_id=worker_id,
    )

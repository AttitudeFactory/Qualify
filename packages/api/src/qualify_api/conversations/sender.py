"""The sender loop of private conversations (QUA-226, E5): drains `conversation_outbox`
for one tenant — claim → window (again) → channel sender → settle — channel-agnostic, on
the outbox E1 built and the `ConversationSender` the registry resolves.

Same mould as `whatsapp/outbox.OutboxSender` (WA-08), with the same guarantees inherited
from the repository (`SKIP LOCKED` claim, status-guarded settles, the outbound `messages`
row written by `mark_sent` under the channel's own message id). What this module decides:

- **The window is validated at the moment of sending**, not only when the reply was
  written (the ticket's criterion): a row whose thread's `last_inbound_at` is now more
  than 24 h old is settled `failed` with `window_closed` — waiting cannot reopen it.
- **A private reply** (m-24789646) has no 24 h window — the person may never have
  written — but Meta's own limit: its `reply_deadline` (the comment + 7 days) is
  revalidated the same way, and a row past it is `failed` with `private_reply_expired`.
  Private replies go out only while this sender was built with them enabled (the
  `comment_private_reply` capability, read by the composition): switching it off stops
  rows already queued too — they are `failed` with `private_reply_disabled`.
  The `recipient_id` Meta answers is recorded on the row; when it is not the thread's
  counterpart (the thread was chosen up front from the comment's `from.id`) the send is
  kept and `conversations.sender.recipient_mismatch` is logged — R1's evidence.
- **No sender for the channel** (`UnknownChannel`) is `failed` with `no_sender`: the row
  stays visible to the person as not sent, and nothing is retried that cannot succeed.
- **An auth failure** (HTTP 401 / code 190) settles the row `dead`, marks the rest of the
  batch for that connection `dead` too, and degrades the connection through QUA-90's
  published seam — the same path the inbox and publishing use.
- **A retryable failure** (transport, 429, 5xx) is `pending` again with the outbox's
  exponential backoff, `dead` after `MAX_ATTEMPTS`. Any other refusal from the channel
  (a policy error, a bad recipient) is `failed` with its numeric codes.
- **Nothing here reads a token.** The channel sender receives a `SourceConnection` (ids
  only) and obtains its own authenticated client.

Counters only in logs and reports — no payload, no recipient.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, Protocol
from uuid import UUID

from qualify_api.conversations.contracts import (
    ChannelRegistry,
    SourceConnection,
    UnknownChannel,
)
from qualify_api.conversations.outbox import (
    DEFAULT_BATCH,
    KIND_PRIVATE_REPLY,
    MAX_ATTEMPTS,
    ClaimedOutboxItem,
    ConversationOutboxRepository,
    backoff,
)
from qualify_api.conversations.repository import ConversationRepository
from qualify_api.conversations.window import window_state

logger = logging.getLogger("qualify_api.conversations.sender")

ERROR_WINDOW_CLOSED: Final = "window_closed"
ERROR_PRIVATE_REPLY_EXPIRED: Final = "private_reply_expired"
ERROR_PRIVATE_REPLY_DISABLED: Final = "private_reply_disabled"
ERROR_NO_SENDER: Final = "no_sender"
ERROR_THREAD_MISSING: Final = "thread_missing"
ERROR_CONNECTION_MISSING: Final = "connection_missing"
ERROR_AUTH: Final = "auth_error"
ERROR_MAX_ATTEMPTS: Final = "max_attempts"
#: The channel did not answer in time AFTER the request went out: the message may have
#: reached the person. Retrying blindly duplicated a photo on 2026-10-16, so the row is
#: settled as failed with this code and the person decides (the sync shows the echo if
#: it did go out).
ERROR_SEND_AMBIGUOUS: Final = "send_ambiguous"

ConnectionReader = Callable[[UUID, UUID], SourceConnection | None]
ConnectionDegrader = Callable[..., object]


class _Failure(Protocol):
    """What a channel's send error may expose; everything is optional and defaulted."""

    @property
    def is_auth_error(self) -> bool: ...

    @property
    def is_retryable(self) -> bool: ...


@dataclass
class SendReport:
    """One tenant's pass. Counters only."""

    tenant_id: UUID
    claimed: int = 0
    sent: int = 0
    retried: int = 0
    failed: int = 0
    dead: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def settled(self) -> int:
        return self.sent + self.retried + self.failed + self.dead


def _utcnow() -> datetime:
    return datetime.now(UTC)


def error_code_of(exc: BaseException) -> str:
    """A log-safe code for a channel failure: Meta's numeric codes when the error
    carries them, else the exception's type name. Never its message."""
    status = getattr(exc, "http_status", None)
    code = getattr(exc, "platform_code", None)
    if status is not None or code is not None:
        return f"http_{status}_code_{code}"
    return type(exc).__name__


class MediaLinker(Protocol):
    """QUA-68's `PublicMediaLinker`: an R2 object → the short-lived public URL the channel
    fetches (`/public/media/{token}`)."""

    def link(self, *, tenant_id: UUID, object_key: str, content_type: str) -> str: ...


ERROR_NO_MEDIA_LINKER: Final = "no_media_linker"


class ConversationOutboxSender:
    def __init__(
        self,
        *,
        outbox: ConversationOutboxRepository,
        repository: ConversationRepository,
        registry: ChannelRegistry,
        connections: ConnectionReader,
        degrade: ConnectionDegrader | None = None,
        media_linker: MediaLinker | None = None,
        private_replies: bool = False,
        worker_id: str,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._outbox = outbox
        self._repo = repository
        self._registry = registry
        self._connections = connections
        self._degrade = degrade
        self._media_linker = media_linker
        self._private_replies = private_replies
        self._worker_id = worker_id
        self._clock = clock

    async def run_once(self, tenant_id: UUID, *, limit: int = DEFAULT_BATCH) -> SendReport:
        now = self._clock()
        items = self._outbox.claim(
            tenant_id=tenant_id, worker_id=self._worker_id, now=now, limit=limit
        )
        report = SendReport(tenant_id=tenant_id, claimed=len(items))
        degraded: set[UUID] = set()
        for item in items:
            try:
                await self._process(item, degraded=degraded, report=report)
            except Exception as exc:  # noqa: BLE001 — one bad row must not stop the batch
                logger.exception(
                    "conversations.sender.item_error item_id=%s channel=%s", item.id, item.channel
                )
                report.errors.append(f"{item.id}:{type(exc).__name__}")
                self._retry(item, type(exc).__name__, report)
        if report.claimed:
            logger.info(
                "conversations.sender.batch tenant_id=%s claimed=%d sent=%d retried=%d "
                "failed=%d dead=%d errors=%d",
                tenant_id,
                report.claimed,
                report.sent,
                report.retried,
                report.failed,
                report.dead,
                len(report.errors),
            )
        return report

    async def _process(
        self, item: ClaimedOutboxItem, *, degraded: set[UUID], report: SendReport
    ) -> None:
        tenant_id = item.tenant_id
        if item.connection_id in degraded:
            self._outbox.mark_dead(tenant_id=tenant_id, item_id=item.id, error_code=ERROR_AUTH)
            report.dead += 1
            return

        thread = self._repo.get_thread(tenant_id=tenant_id, thread_id=item.thread_id)
        if thread is None:
            self._fail(item, ERROR_THREAD_MISSING, report)
            return
        if item.kind == KIND_PRIVATE_REPLY:
            if not self._private_replies:
                self._fail(item, ERROR_PRIVATE_REPLY_DISABLED, report)
                return
            if item.reply_deadline is None or self._clock() >= item.reply_deadline:
                self._fail(item, ERROR_PRIVATE_REPLY_EXPIRED, report)
                return
        elif not window_state(thread.last_inbound_at, self._clock()).is_open:
            self._fail(item, ERROR_WINDOW_CLOSED, report)
            return
        try:
            sender = self._registry.sender_for(item.channel)
        except UnknownChannel:
            self._fail(item, ERROR_NO_SENDER, report)
            return
        connection = self._connections(tenant_id, item.connection_id)
        if connection is None:
            self._fail(item, ERROR_CONNECTION_MISSING, report)
            return

        payload: Mapping[str, Any] = item.payload
        if item.media is not None and item.media.needs_link:
            # The public URL is minted NOW, so a row that waited longer than the token's
            # TTL still goes out; a sender without a linker cannot send media at all.
            if self._media_linker is None:
                self._fail(item, ERROR_NO_MEDIA_LINKER, report)
                return
            url = self._media_linker.link(
                tenant_id=tenant_id,
                object_key=item.media.object_key,
                content_type=item.media.content_type,
            )
            payload = sender.with_media_url(item.payload, url)
        try:
            result = await sender.send(connection, payload)
        except Exception as exc:  # noqa: BLE001 — classified below, never propagated
            self._settle_error(item, exc, degraded=degraded, report=report)
            return
        recipient = result.recipient_external_id
        if recipient is not None and recipient != thread.counterpart_external_id:
            logger.warning(
                "conversations.sender.recipient_mismatch item_id=%s kind=%s thread_id=%s",
                item.id,
                item.kind,
                thread.id,
            )
        self._outbox.mark_sent(
            tenant_id=tenant_id,
            item_id=item.id,
            external_message_id=result.external_message_id,
            now=self._clock(),
            recipient_external_id=recipient,
        )
        report.sent += 1

    def _settle_error(
        self,
        item: ClaimedOutboxItem,
        exc: BaseException,
        *,
        degraded: set[UUID],
        report: SendReport,
    ) -> None:
        code = error_code_of(exc)
        logger.warning(
            "conversations.sender.send_failed item_id=%s channel=%s code=%s",
            item.id,
            item.channel,
            code,
        )
        if getattr(exc, "is_auth_error", False):
            degraded.add(item.connection_id)
            if self._degrade is not None:
                try:
                    self._degrade(tenant_id=item.tenant_id, connection_id=item.connection_id)
                except Exception:  # noqa: BLE001 — the degrade seam never raises by contract
                    logger.exception(
                        "conversations.sender.degrade_failed connection=%s", item.connection_id
                    )
            self._outbox.mark_dead(tenant_id=item.tenant_id, item_id=item.id, error_code=ERROR_AUTH)
            report.dead += 1
            return
        if getattr(exc, "is_ambiguous", False):
            self._fail(item, ERROR_SEND_AMBIGUOUS, report)
            return
        if getattr(exc, "is_retryable", True):
            self._retry(item, code, report)
            return
        self._fail(item, code, report)

    def _retry(self, item: ClaimedOutboxItem, code: str, report: SendReport) -> None:
        attempts = item.attempts + 1
        if attempts >= MAX_ATTEMPTS:
            self._outbox.mark_dead(
                tenant_id=item.tenant_id,
                item_id=item.id,
                error_code=f"{ERROR_MAX_ATTEMPTS}:{code}",
                attempts=attempts,
            )
            report.dead += 1
            return
        self._outbox.mark_retry(
            tenant_id=item.tenant_id,
            item_id=item.id,
            attempts=attempts,
            error_code=code,
            next_attempt_at=self._clock() + backoff(attempts),
        )
        report.retried += 1

    def _fail(self, item: ClaimedOutboxItem, code: str, report: SendReport) -> None:
        self._outbox.mark_failed(tenant_id=item.tenant_id, item_id=item.id, error_code=code)
        report.failed += 1


__all__ = [
    "ERROR_AUTH",
    "ERROR_CONNECTION_MISSING",
    "ERROR_MAX_ATTEMPTS",
    "ERROR_NO_MEDIA_LINKER",
    "ERROR_NO_SENDER",
    "ERROR_PRIVATE_REPLY_DISABLED",
    "ERROR_PRIVATE_REPLY_EXPIRED",
    "ERROR_SEND_AMBIGUOUS",
    "ERROR_THREAD_MISSING",
    "ERROR_WINDOW_CLOSED",
    "ConnectionReader",
    "ConversationOutboxSender",
    "MediaLinker",
    "SendReport",
    "error_code_of",
]

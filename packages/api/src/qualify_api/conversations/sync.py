"""Reading a channel into the inbox (QUA-226, E1): the reconciliation poll and the
single-message door the webhook handler will use, both channel-agnostic and both landing
on the same repository rules, so a message that arrives twice — by webhook and by poll,
or by a replayed delivery — is one row.

## `sync_connection` — the periodic reconciliation (poll-first, QUA-20)

    sync_started → check_access → [list_conversations → upsert_thread →
    list_messages → insert_message… → bump_thread_activity]… → sync_finished

- The access verdict is saved BEFORE anything is listed, so a connection whose
  permission is missing or whose owner never enabled message access is recorded as such
  and the sync stops there with `last_sync_status = 'failed'` and the verdict as the
  error. No Meta budget is spent listing what cannot be read.
- `AccessStatus.UNKNOWN` does not stop the sync: the channel could not tell, so the
  listing itself is the probe. It stays stored as `unknown` — the UI must not render an
  empty result as "no DMs" while the verdict is unknown.
- Every page is followed (`next_cursor`), both of conversations and of messages. A
  source that caps history (Instagram returns ~20 recent messages per conversation) is
  simply a source whose pages end early; the webhook fills forward.
- `bump_thread_activity` is computed from what THIS sync saw: the newest inbound
  `posted_at` and the newest `posted_at` of any direction. `GREATEST` in the repository
  makes a replay harmless.
- A failure mid-way is recorded (`failed`, the exception class name) and re-raised: the
  caller decides whether to retry, the state row says how far it got.

## `ingest_message` — one message, now

The webhook path (E3) calls this per change: same upsert, same insert, same bump. It
returns whether the message was new, so the handler can skip work it already did.

`sync_connection` processes at most `max_conversations` per call when given — the hook
for the per-connection Meta call budget the comments sync already tracks
(`inbox.repository.calls_in_last_hour`); wiring that ledger in is E3's, with the real
client.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from qualify_api.conversations.contracts import (
    AccessStatus,
    AccessVerdict,
    ConversationSource,
    RemoteConversation,
    RemoteMessage,
    SourceConnection,
)
from qualify_api.conversations.repository import (
    SYNC_FAILED,
    SYNC_OK,
    ConversationRepository,
)

logger = logging.getLogger("qualify_api.conversations.sync")

# Verdicts that make listing pointless: the channel has already said no.
_BLOCKING_ACCESS = frozenset(
    {
        AccessStatus.PERMISSION_MISSING,
        AccessStatus.ACCESS_DISABLED,
        AccessStatus.AUTH_EXPIRED,
        AccessStatus.ERROR,
    }
)


@dataclass
class SyncReport:
    channel: str
    access: AccessVerdict
    conversations_seen: int = 0
    threads_created: int = 0
    messages_seen: int = 0
    messages_created: int = 0
    duplicates: int = 0
    status: str = SYNC_OK
    error: str | None = None
    # Set when `max_conversations` stopped the walk before the source ran out.
    truncated: bool = False
    errors_by_conversation: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class IngestResult:
    thread_id: str
    thread_created: bool
    message_created: bool


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _newer(current: datetime | None, candidate: datetime | None) -> datetime | None:
    if candidate is None:
        return current
    if current is None or _as_utc(candidate) > _as_utc(current):
        return candidate
    return current


class ConversationSyncService:
    def __init__(
        self, *, repository: ConversationRepository, clock: Callable[[], datetime] = _utcnow
    ) -> None:
        self._repo = repository
        self._clock = clock

    async def sync_connection(
        self,
        connection: SourceConnection,
        source: ConversationSource,
        *,
        max_conversations: int | None = None,
    ) -> SyncReport:
        channel = source.channel
        tenant_id, connection_id = connection.tenant_id, connection.connection_id
        self._repo.sync_started(
            tenant_id=tenant_id, connection_id=connection_id, channel=channel, now=self._clock()
        )
        verdict = await source.check_access(connection)
        self._repo.save_access(
            tenant_id=tenant_id,
            connection_id=connection_id,
            channel=channel,
            verdict=verdict,
            now=self._clock(),
        )
        report = SyncReport(channel=channel, access=verdict)
        if verdict.status in _BLOCKING_ACCESS:
            report.status, report.error = SYNC_FAILED, verdict.status.value
            self._finish(connection, channel, report, cursor=None)
            return report

        cursor: str | None = None
        try:
            while True:
                page = await source.list_conversations(connection, cursor=cursor)
                for conversation in page.items:
                    if (
                        max_conversations is not None
                        and report.conversations_seen >= max_conversations
                    ):
                        report.truncated = True
                        break
                    await self._sync_conversation(connection, source, conversation, report)
                if report.truncated or page.next_cursor is None:
                    break
                cursor = page.next_cursor
        except Exception as exc:
            report.status, report.error = SYNC_FAILED, type(exc).__name__
            self._finish(connection, channel, report, cursor=cursor)
            logger.warning(
                "conversations.sync failed connection=%s channel=%s error=%s",
                connection_id,
                channel,
                report.error,
            )
            raise
        self._finish(connection, channel, report, cursor=None)
        return report

    async def _sync_conversation(
        self,
        connection: SourceConnection,
        source: ConversationSource,
        conversation: RemoteConversation,
        report: SyncReport,
    ) -> None:
        report.conversations_seen += 1
        upsert = self._repo.upsert_thread(
            tenant_id=connection.tenant_id,
            connection_id=connection.connection_id,
            channel=source.channel,
            counterpart_external_id=conversation.counterpart_external_id,
            external_conversation_id=conversation.external_conversation_id,
        )
        if upsert.created:
            report.threads_created += 1
        newest_inbound: datetime | None = None
        newest_any: datetime | None = conversation.updated_at
        cursor: str | None = None
        while True:
            page = await source.list_messages(connection, conversation, cursor=cursor)
            for message in page.items:
                report.messages_seen += 1
                created = self._repo.insert_message(
                    tenant_id=connection.tenant_id,
                    thread_id=upsert.thread_id,
                    connection_id=connection.connection_id,
                    message=message,
                )
                if created:
                    report.messages_created += 1
                else:
                    report.duplicates += 1
                newest_any = _newer(newest_any, message.posted_at)
                if message.direction == "inbound":
                    newest_inbound = _newer(newest_inbound, message.posted_at)
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        self._repo.bump_thread_activity(
            tenant_id=connection.tenant_id,
            thread_id=upsert.thread_id,
            last_inbound_at=newest_inbound,
            last_message_at=newest_any,
        )

    def ingest_message(
        self,
        connection: SourceConnection,
        *,
        channel: str,
        conversation: RemoteConversation,
        message: RemoteMessage,
    ) -> IngestResult:
        """One message, from whichever path has it now. Idempotent by `(connection_id,
        external_message_id)`; the thread bump is harmless on a replay."""
        upsert = self._repo.upsert_thread(
            tenant_id=connection.tenant_id,
            connection_id=connection.connection_id,
            channel=channel,
            counterpart_external_id=conversation.counterpart_external_id,
            external_conversation_id=conversation.external_conversation_id,
        )
        created = self._repo.insert_message(
            tenant_id=connection.tenant_id,
            thread_id=upsert.thread_id,
            connection_id=connection.connection_id,
            message=message,
        )
        at = message.posted_at or self._clock()
        self._repo.bump_thread_activity(
            tenant_id=connection.tenant_id,
            thread_id=upsert.thread_id,
            last_inbound_at=at if message.direction == "inbound" else None,
            last_message_at=at,
        )
        return IngestResult(
            thread_id=str(upsert.thread_id), thread_created=upsert.created, message_created=created
        )

    def _finish(
        self,
        connection: SourceConnection,
        channel: str,
        report: SyncReport,
        *,
        cursor: str | None,
    ) -> None:
        self._repo.sync_finished(
            tenant_id=connection.tenant_id,
            connection_id=connection.connection_id,
            channel=channel,
            now=self._clock(),
            status=report.status,
            error=report.error,
            cursor=cursor,
        )

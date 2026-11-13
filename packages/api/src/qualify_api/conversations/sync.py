"""Reading a channel into the inbox (QUA-226, E1): the reconciliation poll and the
single-message door the webhook handler will use, both channel-agnostic and both landing
on the same repository rules, so a message that arrives twice — by webhook and by poll,
or by a replayed delivery — is one row.

## `sync_connection` — the periodic reconciliation (poll-first, QUA-20)

    sync_started → check_access → [list_conversations → list_messages… →
    store_message (upsert_thread + insert_message + bump, one transaction)…]… → sync_finished

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
- Each message bumps the thread with its own `posted_at` in the same transaction that
  stores it (m-25018661: an unsend can never land between the two). `GREATEST` in the
  repository makes a replay harmless. A conversation listed with no messages still gets
  its thread, ordered by the conversation's `updated_at`.
- A failure mid-way is recorded (`failed`, the exception class name) and re-raised: the
  caller decides whether to retry, the state row says how far it got.

## `ingest_message` — one message, now

The webhook path (E3) calls this per change: same upsert, same insert, same bump. It
returns whether the message was new, so the handler can skip work it already did.

## `unsend_message` — the person unsent a DM (m-25018661)

The webhook's `is_deleted` item lands here: the tombstone, the redacted row, its undecided
drafts and the thread's recomputed instants, in one transaction
(`ConversationRepository.unsend_message`). Both doors above then refuse that `mid` for
good: `ingest_message` stores nothing and creates no thread, the poll skips it before the
insert and leaves it out of the thread's bump (otherwise the unsent message would reopen
the 24 h window it no longer opens). The insert itself checks the tombstone again under a
per-message lock, so a race between the poll and the unsend cannot store it either.

`sync_connection` processes at most `max_conversations` per call when given — the hook
for the per-connection Meta call budget the comments sync already tracks
(`inbox.repository.calls_in_last_hour`); wiring that ledger in is E3's, with the real
client.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from qualify_api.conversations.contracts import (
    AccessStatus,
    AccessVerdict,
    ConversationSource,
    RemoteConversation,
    RemoteMessage,
    RemoteProfile,
    RemoteRead,
    SourceConnection,
)
from qualify_api.conversations.repository import (
    STORE_CREATED,
    STORE_UNSENT,
    SYNC_FAILED,
    SYNC_OK,
    ConversationRepository,
    UnsendResult,
)

logger = logging.getLogger("qualify_api.conversations.sync")

#: How long a fetched profile (and its expiring picture URL) is trusted before the next
#: sync asks the channel again. The User Profile API is one call per thread.
PROFILE_TTL = timedelta(hours=24)

#: Provenance of a `message_unsends` tombstone (m-25018661).
UNSEND_PIPELINE_VERSION = "ig-dm-unsend-1.0.0"

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
    # Messages the Graph API still listed although the person unsent them (m-25018661).
    unsent_skipped: int = 0
    status: str = SYNC_OK
    error: str | None = None
    # Set when `max_conversations` stopped the walk before the source ran out.
    truncated: bool = False
    errors_by_conversation: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class IngestResult:
    # None only when `unsent`: an unsent message touches no thread.
    thread_id: str | None
    thread_created: bool
    message_created: bool
    # m-25018661: the person unsent this `mid` — nothing was stored, nothing bumped.
    unsent: bool = False


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class ConversationSyncService:
    def __init__(
        self,
        *,
        repository: ConversationRepository,
        clock: Callable[[], datetime] = _utcnow,
        unavailable: Callable[..., object] | None = None,
        temporary_failure: Callable[..., object] | None = None,
        success: Callable[..., object] | None = None,
    ) -> None:
        self._repo = repository
        self._clock = clock
        self._unavailable = unavailable
        self._temporary_failure = temporary_failure
        self._success = success

    def _observe(
        self, callback: Callable[..., object] | None, connection: SourceConnection, **extra: str
    ) -> None:
        if callback is None:
            return
        kwargs: dict[str, object] = dict(
            tenant_id=connection.tenant_id, connection_id=connection.connection_id, **extra
        )
        if connection.credential_version is not None:
            kwargs["expected_credential_version"] = connection.credential_version
        try:
            callback(**kwargs)
        except Exception as exc:  # noqa: BLE001 - health must not hide the original outcome
            logger.warning("conversations.sync.health_failed error=%s", type(exc).__name__)

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
            cause = {
                AccessStatus.PERMISSION_MISSING: "permission_missing",
                AccessStatus.AUTH_EXPIRED: "auth_expired",
            }.get(verdict.status)
            if verdict.detail == "CredentialNotFound":
                cause = "missing_credential"
            if cause is not None and self._unavailable is not None:
                self._observe(self._unavailable, connection, cause=cause)
            elif verdict.status == AccessStatus.ERROR and self._temporary_failure is not None:
                self._observe(self._temporary_failure, connection)
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
            if self._unavailable is not None and (
                getattr(exc, "is_auth_error", False) or getattr(exc, "is_permission_error", False)
            ):
                self._observe(
                    self._unavailable,
                    connection,
                    cause="auth_expired"
                    if getattr(exc, "is_auth_error", False)
                    else "permission_missing",
                )
            elif self._temporary_failure is not None and getattr(exc, "is_retryable", False):
                self._observe(self._temporary_failure, connection)
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
        if self._success is not None:
            self._observe(self._success, connection)
        return report

    async def _sync_conversation(
        self,
        connection: SourceConnection,
        source: ConversationSource,
        conversation: RemoteConversation,
        report: SyncReport,
    ) -> None:
        report.conversations_seen += 1
        listed: list[RemoteMessage] = []
        cursor: str | None = None
        while True:
            page = await source.list_messages(connection, conversation, cursor=cursor)
            listed.extend(page.items)
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
        report.messages_seen += len(listed)
        # m-25018661: an unsent `mid` is never stored again and never bumps the thread. The
        # repository refuses it anyway (under the message's lock); asking first only spares
        # the work and keeps a conversation whose every listed message was unsent from
        # becoming an empty thread.
        unsent = self._repo.unsent_ids(
            tenant_id=connection.tenant_id,
            connection_id=connection.connection_id,
            external_message_ids=[m.external_message_id for m in listed],
        )
        thread_id: UUID | None = None
        thread_created = False
        for message in listed:
            if message.external_message_id in unsent:
                report.unsent_skipped += 1
                continue
            # Upsert + insert + bump in ONE transaction per message, so no unsend can land
            # between the insert and the bump (`ConversationRepository.store_message`).
            stored = self._repo.store_message(
                tenant_id=connection.tenant_id,
                connection_id=connection.connection_id,
                channel=source.channel,
                counterpart_external_id=conversation.counterpart_external_id,
                external_conversation_id=conversation.external_conversation_id,
                message=message,
                at=message.posted_at,
            )
            if stored.outcome == STORE_UNSENT:
                report.unsent_skipped += 1
                continue
            if stored.outcome == STORE_CREATED:
                report.messages_created += 1
            else:
                report.duplicates += 1
            thread_id = stored.thread_id
            thread_created = thread_created or stored.thread_created
        if not listed:
            # A conversation the channel lists with no messages: the thread exists anyway,
            # ordered by the conversation's own `updated_at` (no inbound: no window).
            upsert = self._repo.upsert_thread(
                tenant_id=connection.tenant_id,
                connection_id=connection.connection_id,
                channel=source.channel,
                counterpart_external_id=conversation.counterpart_external_id,
                external_conversation_id=conversation.external_conversation_id,
            )
            thread_id, thread_created = upsert.thread_id, upsert.created
            self._repo.bump_thread_activity(
                tenant_id=connection.tenant_id,
                thread_id=thread_id,
                last_inbound_at=None,
                last_message_at=conversation.updated_at,
            )
        if thread_id is None:
            return  # every listed message was unsent: no thread, no profile call
        if thread_created:
            report.threads_created += 1
        await self.refresh_profile(connection, source, thread_id, conversation)

    def ingest_message(
        self,
        connection: SourceConnection,
        *,
        channel: str,
        conversation: RemoteConversation,
        message: RemoteMessage,
    ) -> IngestResult:
        """One message, from whichever path has it now. Idempotent by `(connection_id,
        external_message_id)`; the thread bump is harmless on a replay. Thread upsert,
        insert and bump are one transaction under the message's lock
        (`ConversationRepository.store_message`): a `mid` the person unsent (m-25018661)
        stores nothing, creates no thread and moves no instant — `unsent=True`."""
        stored = self._repo.store_message(
            tenant_id=connection.tenant_id,
            connection_id=connection.connection_id,
            channel=channel,
            counterpart_external_id=conversation.counterpart_external_id,
            external_conversation_id=conversation.external_conversation_id,
            message=message,
            at=message.posted_at or self._clock(),
        )
        if stored.outcome == STORE_UNSENT or stored.thread_id is None:
            return IngestResult(
                thread_id=None, thread_created=False, message_created=False, unsent=True
            )
        return IngestResult(
            thread_id=str(stored.thread_id),
            thread_created=stored.thread_created,
            message_created=stored.outcome == STORE_CREATED,
        )

    def unsend_message(
        self,
        connection: SourceConnection,
        *,
        external_message_id: str,
        source_event_id: UUID | None = None,
    ) -> UnsendResult:
        """The person unsent `external_message_id`: erase it and keep it erased."""
        return self._repo.unsend_message(
            tenant_id=connection.tenant_id,
            connection_id=connection.connection_id,
            external_message_id=external_message_id,
            now=self._clock(),
            source_event_id=source_event_id,
            pipeline_version=UNSEND_PIPELINE_VERSION,
        )

    async def refresh_profile(
        self,
        connection: SourceConnection,
        source: ConversationSource,
        thread_id: UUID,
        conversation: RemoteConversation,
    ) -> bool:
        """Fetch the counterpart's profile when the thread has none or its picture is
        older than `PROFILE_TTL` (the channel's URL expires). Best-effort: a source without
        a profile API, or one that fails, changes nothing. Returns whether it saved."""
        thread = self._repo.get_thread(tenant_id=connection.tenant_id, thread_id=thread_id)
        if thread is None:
            return False
        fetched_at = thread.counterpart_profile_at
        if fetched_at is not None and _as_utc(self._clock()) - _as_utc(fetched_at) < PROFILE_TTL:
            return False
        fetch = getattr(source, "fetch_profile", None)
        profile: RemoteProfile | None = None
        if fetch is not None:
            try:
                profile = await fetch(connection, conversation.counterpart_external_id)
            except Exception as exc:  # noqa: BLE001 — a profile is decoration, never a failure
                logger.info(
                    "conversations.profile.skipped thread=%s reason=%s",
                    thread_id,
                    type(exc).__name__,
                )
                profile = None
        if profile is None and conversation.counterpart_username:
            # The listing already named them: keep at least the handle.
            profile = RemoteProfile(username=conversation.counterpart_username)
        if profile is None:
            return False
        self._repo.save_profile(
            tenant_id=connection.tenant_id, thread_id=thread_id, profile=profile, now=self._clock()
        )
        return True

    def ingest_read(self, connection: SourceConnection, *, channel: str, read: RemoteRead) -> int:
        """The counterpart read the conversation (Instagram's `messaging_seen`): every
        outbound of that thread at or before `read.last_read_at` becomes `read`. A thread
        the inbox never saw is ignored (0 rows): a receipt alone creates nothing. Returns
        how many messages changed."""
        thread = self._repo.find_thread(
            tenant_id=connection.tenant_id,
            connection_id=connection.connection_id,
            channel=channel,
            counterpart_external_id=read.counterpart_external_id,
        )
        if thread is None:
            return 0
        return self._repo.mark_outbound_read(
            tenant_id=connection.tenant_id, thread_id=thread.id, up_to=read.last_read_at
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

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
from dataclasses import dataclass, field, replace
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

#: m-25017852: a lookup that left the thread with neither a name nor a handle (Meta's 403
#: code 230 without consent, a profile carrying only `profile_pic`, an error) is retried
#: after this, not after `PROFILE_TTL`. Without a column for it, the backoff is written as
#: an older `counterpart_profile_at` (`now - PROFILE_TTL + NAMELESS_RETRY_AFTER`).
NAMELESS_RETRY_AFTER = timedelta(hours=1)

#: The hourly retry is a decay without a column: it applies only while the person wrote
#: within this window (`last_inbound_at`, else `created_at`); an older nameless thread
#: falls back to the daily `PROFILE_TTL`.
NAMELESS_RETRY_WINDOW = timedelta(days=7)

#: m-25017852: at most this many RETRIES of nameless threads per connection per sync
#: round, oldest stamp first (so no thread monopolises the slots). At the default
#: `--sync-interval` of 300 s (`QUALIFY_CONVERSATIONS_SYNC_INTERVAL`, configurable) that
#: is ≤ 60 retry calls/hour per connection; a shorter interval raises it. The bound covers
#: retries only: first lookups of new threads and the 24 h refresh stay unbounded, as
#: before, on top of one `list_messages` call per conversation per round.
MAX_NAMELESS_RETRIES_PER_SYNC = 5

#: Meta's answer when the person has not consented to share their profile (live, see
#: `docs/conversaciones-limitaciones-meta.md`): expected, not an incident.
CONSENT_REFUSAL_CODE = 230

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
    # Profile lookups this sync made, and how many of them retried a nameless thread
    # (bounded by `MAX_NAMELESS_RETRIES_PER_SYNC`).
    profile_lookups: int = 0
    profile_retries: int = 0
    # Nameless threads due for a retry, gathered during the walk and served after it,
    # oldest stamp first, up to `MAX_NAMELESS_RETRIES_PER_SYNC`.
    pending_retries: list[tuple[datetime, UUID, RemoteConversation]] = field(
        default_factory=list, repr=False
    )


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


def _lookup_outcome(exc: Exception) -> str:
    """What a failed profile lookup logs: Meta's status and codes, or for a transport
    failure the class of its cause (`ReadTimeout` vs `ConnectError`). Never message text."""
    if getattr(exc, "is_transport", False):
        cause = exc.__cause__ if exc.__cause__ is not None else exc
        return f"error_transport_{type(cause).__name__}"
    detail = getattr(exc, "access_detail", None)
    return detail() if callable(detail) else f"error_{type(exc).__name__}"


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
            # Retries are served only when the walk finishes: a connection whose walk
            # always raises (or always hits the tenant's deadline) never retries nameless
            # threads. Nothing is left inconsistent — queuing writes no state.
            await self._serve_retries(connection, source, report)
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
        await self.refresh_profile(connection, source, thread_id, conversation, report=report)

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
        *,
        report: SyncReport | None = None,
    ) -> bool:
        """Name the thread's counterpart. Best-effort: a profile is decoration, never a
        failure of the sync. Returns whether it saved anything.

        - The handle the conversations listing carries (`participants.username`) is used
          whenever the thread has none — on every round, with no Graph call, and merged
          into a fetched profile that lacks one (m-25017852: a webhook-created thread, or
          one whose lookup came back with only `profile_pic`, gets its @handle).
        - The profile itself (`fetch_profile`, one Graph call) is asked for when the thread
          never had one or its stamp is older than `PROFILE_TTL` (the picture expires).
        - A lookup that leaves the thread with neither name nor handle is logged once and
          retried after `NAMELESS_RETRY_AFTER`. With a `report`, those retries are queued
          and served after the walk, oldest stamp first, `MAX_NAMELESS_RETRIES_PER_SYNC`
          per round (`_serve_retries`)."""
        thread = self._repo.get_thread(tenant_id=connection.tenant_id, thread_id=thread_id)
        if thread is None:
            return False
        now = self._clock()
        listed = conversation.counterpart_username or None
        fetched_at = thread.counterpart_profile_at
        filled = False
        if thread.counterpart_username is None and listed is not None:
            # Only the handle, keeping the stored instant: no lookup happened.
            self._repo.save_profile(
                tenant_id=connection.tenant_id,
                thread_id=thread_id,
                profile=RemoteProfile(username=listed),
                now=fetched_at if fetched_at is not None else now,
            )
            filled = True
        if fetched_at is not None and _as_utc(now) - _as_utc(fetched_at) < PROFILE_TTL:
            return filled
        if getattr(source, "fetch_profile", None) is None:
            return filled
        stored_named = bool(thread.counterpart_name or thread.counterpart_username or filled)
        if fetched_at is not None and not stored_named and report is not None:
            report.pending_retries.append((_as_utc(fetched_at), thread_id, conversation))
            return filled
        return await self._lookup(connection, source, thread_id, conversation, report) or filled

    async def _serve_retries(
        self, connection: SourceConnection, source: ConversationSource, report: SyncReport
    ) -> None:
        pending = sorted(report.pending_retries, key=lambda item: (item[0], str(item[1])))
        report.pending_retries = []
        for _stamp, thread_id, conversation in pending[:MAX_NAMELESS_RETRIES_PER_SYNC]:
            report.profile_retries += 1
            await self._lookup(connection, source, thread_id, conversation, report)

    async def _lookup(
        self,
        connection: SourceConnection,
        source: ConversationSource,
        thread_id: UUID,
        conversation: RemoteConversation,
        report: SyncReport | None,
    ) -> bool:
        """One `fetch_profile` call and its save. Logs one line when the answer carries
        neither name nor handle: WARNING when the thread stays nameless or the error is
        unexpected, INFO for Meta's expected consent refusal (code 230) on a thread that
        already has a name or handle. Ids' prefix and codes only, never personal data."""
        thread = self._repo.get_thread(tenant_id=connection.tenant_id, thread_id=thread_id)
        if thread is None:
            return False
        if report is not None:
            report.profile_lookups += 1
        now = self._clock()
        listed = conversation.counterpart_username or None
        stored_named = bool(thread.counterpart_name or thread.counterpart_username)
        profile: RemoteProfile | None = None
        outcome = "none"
        expected = True
        try:
            profile = await source.fetch_profile(  # type: ignore[attr-defined]
                connection, conversation.counterpart_external_id
            )
        except Exception as exc:  # noqa: BLE001 — a profile is decoration, never a failure
            outcome = _lookup_outcome(exc)
            expected = (
                getattr(exc, "http_status", None) == 403
                and getattr(exc, "platform_code", None) == CONSENT_REFUSAL_CODE
            )
        if profile is not None and profile.username is None and listed is not None:
            profile = replace(profile, username=listed)
        elif profile is None and listed is not None:
            profile = RemoteProfile(username=listed)
        named = profile is not None and bool(profile.name or profile.username)
        nameless = not named and not stored_named
        stamp = now
        if nameless:
            last_heard = thread.last_inbound_at or thread.created_at
            if last_heard is None or _as_utc(now) - _as_utc(last_heard) <= NAMELESS_RETRY_WINDOW:
                stamp = now - PROFILE_TTL + NAMELESS_RETRY_AFTER
        if not named or outcome != "none":
            if profile is not None and not named:
                outcome = "avatar_only"
            level = logging.WARNING if nameless or not expected else logging.INFO
            logger.log(
                level,
                "conversations.profile.unnamed connection=%s thread=%s outcome=%s "
                "stored_named=%s retry_in=%s",
                str(connection.connection_id)[:8],
                str(thread_id)[:8],
                outcome,
                "yes" if stored_named or named else "no",
                f"{int((stamp + PROFILE_TTL - now).total_seconds())}s",
            )
        # COALESCE never erases: an avatar-only or empty answer only moves the stamp.
        self._repo.save_profile(
            tenant_id=connection.tenant_id,
            thread_id=thread_id,
            profile=profile or RemoteProfile(),
            now=stamp,
        )
        return profile is not None

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

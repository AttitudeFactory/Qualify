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
    SYNC_FAILED,
    SYNC_OK,
    ConversationRepository,
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
        upsert = self._repo.upsert_thread(
            tenant_id=connection.tenant_id,
            connection_id=connection.connection_id,
            channel=source.channel,
            counterpart_external_id=conversation.counterpart_external_id,
            external_conversation_id=conversation.external_conversation_id,
        )
        if upsert.created:
            report.threads_created += 1
        await self.refresh_profile(
            connection, source, upsert.thread_id, conversation, report=report
        )
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
            detail = getattr(exc, "access_detail", None)
            outcome = detail() if callable(detail) else f"error_{type(exc).__name__}"
            expected = getattr(exc, "platform_code", None) == CONSENT_REFUSAL_CODE
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

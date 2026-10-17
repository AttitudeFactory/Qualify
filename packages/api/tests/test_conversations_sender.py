"""The outbox loop (QUA-226, E5), offline over the in-memory repositories and the
in-memory channel: the window is validated again at send time, a sent row becomes an
outbound `messages` row under the channel's message id, failures are classified (auth →
dead + degrade; transport → retry with backoff, dead after MAX_ATTEMPTS; a definitive
refusal → failed), and a channel with no sender or a missing connection never retries.
Then the worker's tick: scope is explicit, one tenant's failure does not stop the others,
the poll runs at most every `sync_interval`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qualify_api.conversations.contracts import (
    CHANNEL_DM,
    ChannelRegistry,
    RemoteConversation,
    RemoteMessage,
    SourceConnection,
)
from qualify_api.conversations.memory_source import (
    SHAPE_VERSION_MEMORY,
    MemoryConversationSender,
    MemoryConversationSource,
)
from qualify_api.conversations.outbox import (
    MAX_ATTEMPTS,
    HumanApproval,
    MemoryConversationOutboxRepository,
    backoff,
)
from qualify_api.conversations.repository import MemoryConversationRepository
from qualify_api.conversations.sender import (
    ERROR_AUTH,
    ERROR_CONNECTION_MISSING,
    ERROR_MAX_ATTEMPTS,
    ERROR_NO_SENDER,
    ERROR_SEND_AMBIGUOUS,
    ERROR_WINDOW_CLOSED,
    ConversationOutboxSender,
    SendReport,
    error_code_of,
)
from qualify_api.conversations.service import ConversationService
from qualify_api.conversations.sync import ConversationSyncService, SyncReport
from qualify_api.conversations.worker import (
    ConversationsTick,
    NoSender,
    ScopedTenants,
    build_parser,
    main,
    run_worker,
)

T0 = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
TENANT = uuid4()
USER = uuid4()
CONNECTION = SourceConnection(
    tenant_id=TENANT, connection_id=uuid4(), external_account_id="ig-1", linked_page_id="p1"
)
ALICE = RemoteConversation(counterpart_external_id="igsid-alice")


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class SendFailure(Exception):
    def __init__(
        self,
        *,
        auth: bool = False,
        retryable: bool = True,
        code: int | None = None,
        ambiguous: bool = False,
    ):
        super().__init__("send failed")
        self.is_auth_error = auth
        self.is_retryable = retryable
        self.is_ambiguous = ambiguous
        self.http_status = 400 if code else None
        self.platform_code = code


@pytest.fixture
def world():
    clock = Clock(T0 + timedelta(minutes=5))
    repo = MemoryConversationRepository()
    outbox = MemoryConversationOutboxRepository(clock=clock)
    sender = MemoryConversationSender()
    registry = ChannelRegistry()
    registry.register(source=MemoryConversationSource(), sender=sender)
    service = ConversationService(repository=repo, outbox=outbox, registry=registry, clock=clock)
    sync = ConversationSyncService(repository=repo, clock=clock)
    sync.ingest_message(
        CONNECTION,
        channel=CHANNEL_DM,
        conversation=ALICE,
        message=RemoteMessage(
            external_message_id="mid.1",
            direction="inbound",
            text="hola",
            posted_at=T0,
            shape_version=SHAPE_VERSION_MEMORY,
            author_external_id="igsid-alice",
        ),
    )
    thread = repo.list_threads(tenant_id=TENANT, channels=[CHANNEL_DM])[0]
    degraded: list[UUID] = []

    def degrade(*, tenant_id: UUID, connection_id: UUID) -> None:
        degraded.append(connection_id)

    loop = ConversationOutboxSender(
        outbox=outbox,
        repository=repo,
        registry=registry,
        connections=lambda t, c: CONNECTION if c == CONNECTION.connection_id else None,
        degrade=degrade,
        worker_id="test:1",
        clock=clock,
    )
    return clock, repo, outbox, sender, service, thread, loop, degraded


def _queue(service: ConversationService, thread_id: UUID, text: str = "¡hola!") -> UUID:
    return service.reply(
        tenant_id=TENANT,
        thread_id=thread_id,
        text=text,
        approval=HumanApproval(user_id=USER, approved_at=T0),
    )


async def test_a_queued_reply_is_sent_and_becomes_an_outbound_message(world) -> None:
    clock, repo, outbox, sender, service, thread, loop, _d = world
    item_id = _queue(service, thread.id)

    report = await loop.run_once(TENANT)

    assert (report.claimed, report.sent, report.settled) == (1, 1, 1)
    row = outbox.rows[item_id]
    assert row.status == "sent" and row.external_message_id == "mid.memory.1"
    assert sender.sent[0].payload == {
        "recipient": {"id": "igsid-alice"},
        "message": {"text": "¡hola!"},
    }
    assert sender.sent[0].connection == CONNECTION
    assert [m.external_message_id for m in outbox.messages] == ["mid.memory.1"]
    assert outbox.thread_last_message_at[thread.id] == clock.now


async def test_the_window_is_validated_at_send_time(world) -> None:
    clock, _repo, outbox, sender, service, thread, loop, _d = world
    item_id = _queue(service, thread.id)  # queued inside the window…
    clock.now = T0 + timedelta(hours=24)  # …sent after it closed

    report = await loop.run_once(TENANT)

    assert (report.failed, report.sent) == (1, 0)
    assert outbox.rows[item_id].status == "failed"
    assert outbox.rows[item_id].error_code == ERROR_WINDOW_CLOSED
    assert sender.sent == []


async def test_no_sender_for_the_channel_fails_without_retry(world) -> None:
    clock, repo, outbox, _sender, service, thread, _loop, _d = world
    item_id = _queue(service, thread.id)
    registry = ChannelRegistry()
    registry.register(source=MemoryConversationSource())  # read-only channel
    loop = ConversationOutboxSender(
        outbox=outbox,
        repository=repo,
        registry=registry,
        connections=lambda t, c: CONNECTION,
        worker_id="test:1",
        clock=clock,
    )
    report = await loop.run_once(TENANT)
    assert report.failed == 1
    assert outbox.rows[item_id].error_code == ERROR_NO_SENDER


async def test_a_missing_connection_fails_without_retry(world) -> None:
    clock, repo, outbox, _sender, service, thread, _loop, _d = world
    item_id = _queue(service, thread.id)
    registry = ChannelRegistry()
    registry.register(sender=MemoryConversationSender())
    loop = ConversationOutboxSender(
        outbox=outbox,
        repository=repo,
        registry=registry,
        connections=lambda t, c: None,
        worker_id="test:1",
        clock=clock,
    )
    await loop.run_once(TENANT)
    assert outbox.rows[item_id].error_code == ERROR_CONNECTION_MISSING


async def test_an_auth_failure_is_dead_and_degrades_the_connection_once(world) -> None:
    _clock, _repo, outbox, sender, service, thread, loop, degraded = world
    first, second = _queue(service, thread.id, "uno"), _queue(service, thread.id, "dos")
    sender.fail_with = SendFailure(auth=True)

    report = await loop.run_once(TENANT)

    assert (report.dead, report.sent) == (2, 0)
    assert outbox.rows[first].error_code == ERROR_AUTH
    assert outbox.rows[second].error_code == ERROR_AUTH
    assert degraded == [CONNECTION.connection_id]  # the batch degrades once
    assert len(sender.sent) == 0


async def test_a_transport_failure_retries_with_backoff_then_dies(world) -> None:
    clock, _repo, outbox, sender, service, thread, loop, _d = world
    item_id = _queue(service, thread.id)
    sender.fail_with = SendFailure(retryable=True)

    report = await loop.run_once(TENANT)
    row = outbox.rows[item_id]
    assert (report.retried, row.status, row.attempts) == (1, "pending", 1)
    assert row.next_attempt_at == clock.now + backoff(1)

    # Not due yet: nothing claimed. Due: retried again, until MAX_ATTEMPTS.
    assert (await loop.run_once(TENANT)).claimed == 0
    for attempt in range(2, MAX_ATTEMPTS):
        clock.now = row.next_attempt_at
        await loop.run_once(TENANT)
        assert row.attempts == attempt and row.status == "pending"
    clock.now = row.next_attempt_at
    report = await loop.run_once(TENANT)
    assert report.dead == 1 and row.status == "dead"
    assert row.error_code.startswith(ERROR_MAX_ATTEMPTS)


async def test_an_ambiguous_send_is_settled_without_a_retry(world) -> None:
    """The channel timed out after the request went out: the message may have reached
    the person. One attempt, `send_ambiguous`, and the person decides."""
    _clock, _repo, outbox, sender, service, thread, loop, _d = world
    item_id = _queue(service, thread.id)
    sender.fail_with = SendFailure(retryable=False, ambiguous=True)
    report = await loop.run_once(TENANT)
    row = outbox.rows[item_id]
    assert (report.failed, report.retried, row.status) == (1, 0, "failed")
    assert row.error_code == ERROR_SEND_AMBIGUOUS
    assert (await loop.run_once(TENANT)).claimed == 0  # never picked up again


async def test_a_definitive_refusal_fails_with_its_codes(world) -> None:
    _clock, _repo, outbox, sender, service, thread, loop, _d = world
    item_id = _queue(service, thread.id)
    sender.fail_with = SendFailure(retryable=False, code=10)
    report = await loop.run_once(TENANT)
    assert report.failed == 1
    assert outbox.rows[item_id].error_code == "http_400_code_10"


async def test_an_unexpected_exception_is_a_retry_and_the_batch_goes_on(world) -> None:
    _clock, _repo, outbox, sender, service, thread, loop, _d = world
    item_id = _queue(service, thread.id)
    sender.fail_with = RuntimeError("boom")
    report = await loop.run_once(TENANT)
    assert report.retried == 1
    assert outbox.rows[item_id].error_code == "RuntimeError"


def test_error_code_never_carries_the_message() -> None:
    assert error_code_of(SendFailure(code=10)) == "http_400_code_10"
    assert error_code_of(RuntimeError("a secret")) == "RuntimeError"


async def test_another_tenant_sees_nothing_of_this_queue(world) -> None:
    _clock, _repo, _outbox, _sender, service, thread, loop, _d = world
    _queue(service, thread.id)
    other = await loop.run_once(uuid4())
    assert other.claimed == 0


# --- the worker tick --------------------------------------------------------------------


class _RecordingSender:
    def __init__(self, fail_for: UUID | None = None) -> None:
        self.calls: list[UUID] = []
        self.fail_for = fail_for

    async def run_once(self, tenant_id: UUID, *, limit: int = 50) -> SendReport:
        self.calls.append(tenant_id)
        if tenant_id == self.fail_for:
            raise RuntimeError("db down")
        return SendReport(tenant_id=tenant_id, claimed=1, sent=1)


async def test_tick_runs_every_tenant_in_scope_and_isolates_failures() -> None:
    a, b = uuid4(), uuid4()
    sender = _RecordingSender(fail_for=a)
    tick = ConversationsTick(tenants=ScopedTenants([a, b, a]), sender=sender)
    report = await tick.run_once()
    assert sender.calls == [a, b]
    assert [t.errors for t in report.tenants] == [["send:RuntimeError"], []]
    assert report.tenants[1].send is not None and report.tenants[1].send.sent == 1


async def test_tick_polls_at_most_every_sync_interval() -> None:
    tenant = uuid4()
    polls: list[UUID] = []
    now = [0.0]

    async def syncer(tenant_id: UUID) -> list[SyncReport]:
        polls.append(tenant_id)
        return []

    tick = ConversationsTick(
        tenants=ScopedTenants([tenant]),
        sender=NoSender(),
        syncer=syncer,
        sync_interval=300,
        monotonic=lambda: now[0],
    )
    await tick.run_once()
    await tick.run_once()
    assert polls == [tenant]
    now[0] = 301
    await tick.run_once()
    assert polls == [tenant, tenant]


def test_scope_is_mandatory_and_sync_only_drops_the_sender() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--once"])
    with pytest.raises(ValueError):
        ScopedTenants([])
    built: list[dict] = []

    def scoped(tenant_ids, **options):
        built.append({"tenants": list(tenant_ids), **options})
        return ConversationsTick(tenants=ScopedTenants(tenant_ids), sender=NoSender())

    tenant = uuid4()
    assert main(["--tenant", str(tenant), "--once", "--sync-only"], scoped=scoped) == 0
    assert built[0]["tenants"] == [tenant]
    assert built[0]["sync"] is True and built[0]["send"] is False


async def test_run_worker_once_returns_nonzero_when_discovery_fails() -> None:
    class Broken:
        def tenants(self, *, now: datetime) -> list[UUID]:
            raise RuntimeError("no db")

    tick = ConversationsTick(tenants=Broken(), sender=NoSender())
    assert await run_worker(lambda: tick, once=True) == 1
    ok = ConversationsTick(tenants=ScopedTenants([uuid4()]), sender=NoSender())
    assert await run_worker(lambda: ok, once=True) == 0

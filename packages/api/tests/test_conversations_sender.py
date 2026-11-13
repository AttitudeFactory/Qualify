"""The outbox loop (QUA-226, E5), offline over the in-memory repositories and the
in-memory channel: the window is validated again at send time, a sent row becomes an
outbound `messages` row under the channel's message id, failures are classified (auth →
dead + degrade; transport → retry with backoff, dead after MAX_ATTEMPTS; a definitive
refusal → failed), and a channel with no sender or a missing connection never retries.
Then the worker's tick: scope is explicit, one tenant's failure does not stop the others,
the poll runs at most every `sync_interval`.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
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
    BackgroundSync,
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


async def test_disconnected_account_keeps_approved_reply_pending_until_recovery(world) -> None:
    clock, _repo, outbox, sender, service, thread, loop, _d = world
    item_id = _queue(service, thread.id)
    loop._connection_available = lambda **kwargs: False
    report = await loop.run_once(TENANT)
    assert report.sent == 0 and not sender.sent
    assert outbox.rows[item_id].status == "pending"
    assert outbox.rows[item_id].attempts == 0
    clock.now += timedelta(seconds=61)
    loop._connection_available = lambda **kwargs: True
    assert (await loop.run_once(TENANT)).sent == 1
    assert (await loop.run_once(TENANT)).sent == 0
    assert len(sender.sent) == 1


async def test_health_store_failure_does_not_retry_an_accepted_reply(world) -> None:
    _clock, _repo, outbox, sender, service, thread, loop, _d = world
    item_id = _queue(service, thread.id)

    def health_failed(**kwargs):
        raise RuntimeError("health DB unavailable")

    loop._success = health_failed
    assert (await loop.run_once(TENANT)).sent == 1
    assert outbox.rows[item_id].status == "sent"
    assert (await loop.run_once(TENANT)).sent == 0
    assert len(sender.sent) == 1


# --- m-25017174: a send never waits for the poll ----------------------------------------


async def test_a_pending_reply_is_sent_while_a_background_poll_is_stuck(world) -> None:
    """A re-sync blocked on Graph (here: a thread blocked outright) must not hold the
    sender: the reply approved meanwhile leaves on the very next tick."""
    import threading

    _clock, _repo, outbox, sender, service, thread, loop, _d = world
    gate = threading.Event()
    started = threading.Event()
    polls: list[UUID] = []

    async def stuck_syncer(tenant_id: UUID) -> list[SyncReport]:
        polls.append(tenant_id)
        started.set()
        gate.wait(timeout=10)  # blocks its thread, not the sender's loop
        return []

    tick = ConversationsTick(
        tenants=ScopedTenants([TENANT]),
        sender=loop,
        syncer=stuck_syncer,
        sync_interval=0,
        sync_in_background=True,
    )
    try:
        await tick.run_once()  # nothing queued yet; the poll starts and gets stuck
        assert started.wait(timeout=5)
        outbox_id = _queue(service, thread.id)
        report = await tick.run_once()
        assert tick.background is not None and tick.background.busy
        assert report.tenants[0].send is not None and report.tenants[0].send.sent == 1
        assert outbox.rows[outbox_id].status == "sent"
        assert len(sender.sent) == 1
        assert polls == [TENANT]  # a second round is refused while the first one runs
    finally:
        gate.set()
        if tick.background is not None:
            tick.background.wait(timeout=5)
        tick.close()


async def test_a_background_round_runs_every_due_tenant_and_isolates_failures() -> None:
    a, b = uuid4(), uuid4()
    polls: list[UUID] = []

    async def syncer(tenant_id: UUID) -> list[SyncReport]:
        polls.append(tenant_id)
        if tenant_id == a:
            raise RuntimeError("graph down")
        return []

    tick = ConversationsTick(
        tenants=ScopedTenants([a, b]),
        sender=NoSender(),
        syncer=syncer,
        sync_interval=300,
        sync_in_background=True,
    )
    try:
        report = await tick.run_once()
        assert tick.background is not None
        tick.background.wait(timeout=5)
        assert polls == [a, b]
        assert all(t.sync == [] and t.errors == [] for t in report.tenants)
        await tick.run_once()  # inside the interval: no second round
        tick.background.wait(timeout=5)
        assert polls == [a, b]
    finally:
        tick.close()


async def test_an_inline_poll_runs_after_the_send() -> None:
    order: list[str] = []

    class Sender:
        async def run_once(self, tenant_id: UUID, *, limit: int = 50) -> SendReport:
            order.append("send")
            return SendReport(tenant_id=tenant_id)

    async def syncer(tenant_id: UUID) -> list[SyncReport]:
        order.append("sync")
        return []

    tick = ConversationsTick(
        tenants=ScopedTenants([uuid4()]), sender=Sender(), syncer=syncer, sync_interval=300
    )
    await tick.run_once()
    assert order == ["send", "sync"]
    assert tick.background is None


async def test_run_worker_closes_the_background_poll() -> None:
    closed: list[bool] = []

    class Runner:
        async def run_once(self):
            from qualify_api.conversations.worker import TickReport

            return TickReport(started_at=T0)

        def close(self) -> None:
            closed.append(True)

    async def no_sleep(_s: float) -> None:
        return None

    assert await run_worker(lambda: Runner(), once=False, sleep=no_sleep, max_ticks=2) == 0
    assert closed == [True]


def test_only_the_loop_polls_in_the_background() -> None:
    built: list[dict] = []

    def scoped(tenant_ids, **options):
        built.append(options)
        return ConversationsTick(tenants=ScopedTenants(tenant_ids), sender=NoSender())

    class StopAtOnce:
        async def run_once(self):
            raise KeyboardInterrupt

        def close(self) -> None:
            return None

    def looping(tenant_ids, **options):
        built.append(options)
        return StopAtOnce()

    tenant = str(uuid4())
    assert main(["--tenant", tenant, "--once", "--sync"], scoped=scoped) == 0
    assert main(["--tenant", tenant, "--once"], scoped=scoped) == 0
    assert main(["--tenant", tenant, "--sync"], scoped=looping) == 0
    assert main(["--tenant", tenant, "--sync-only"], scoped=looping) == 0
    assert [b["background_sync"] for b in built] == [False, False, True, False]


# --- m-25017174 review: stamps, deadlines, stuck rounds, shutdown -----------------------


async def test_a_tenant_late_in_a_slow_round_is_not_polled_twice_in_one_interval() -> None:
    """The interval counts from each tenant's own poll start, not the round's submission:
    a tenant that started 100 s into the round is not due again 60 s after it."""
    a, b = uuid4(), uuid4()
    now = [0.0]
    polls: list[UUID] = []

    async def syncer(tenant_id: UUID) -> list[SyncReport]:
        polls.append(tenant_id)
        if tenant_id == a:
            now[0] += 100  # a slow poll
        return []

    tick = ConversationsTick(
        tenants=ScopedTenants([a, b]),
        sender=NoSender(),
        syncer=syncer,
        sync_interval=150,
        sync_in_background=True,
        monotonic=lambda: now[0],
    )
    try:
        await tick.run_once()
        assert tick.background is not None
        tick.background.wait(timeout=5)
        assert polls == [a, b]
        now[0] = 160  # a started at 0 (due), b started at 100 (not due until 250)
        await tick.run_once()
        tick.background.wait(timeout=5)
        assert polls == [a, b, a]
    finally:
        tick.close()


async def test_a_second_round_runs_after_the_interval_once_the_first_finished() -> None:
    tenant = uuid4()
    now = [0.0]
    polls: list[UUID] = []

    async def syncer(tenant_id: UUID) -> list[SyncReport]:
        polls.append(tenant_id)
        return []

    tick = ConversationsTick(
        tenants=ScopedTenants([tenant]),
        sender=NoSender(),
        syncer=syncer,
        sync_interval=10,
        sync_in_background=True,
        monotonic=lambda: now[0],
    )
    try:
        await tick.run_once()
        assert tick.background is not None
        tick.background.wait(timeout=5)
        await tick.run_once()
        tick.background.wait(timeout=5)
        assert polls == [tenant]
        now[0] = 10
        await tick.run_once()
        tick.background.wait(timeout=5)
        assert polls == [tenant, tenant]
    finally:
        tick.close()


async def test_a_tenant_past_its_deadline_is_a_failure_and_the_round_goes_on(caplog) -> None:
    hung, quick = uuid4(), uuid4()
    finished: list[UUID] = []

    async def syncer(tenant_id: UUID) -> list[SyncReport]:
        if tenant_id == hung:
            await asyncio.sleep(30)  # a Graph read that never answers
        finished.append(tenant_id)
        return []

    tick = ConversationsTick(
        tenants=ScopedTenants([hung, quick]),
        sender=NoSender(),
        syncer=syncer,
        sync_interval=300,
        sync_in_background=True,
        sync_tenant_timeout=0.05,
    )
    caplog.set_level(logging.INFO, logger="qualify_api.conversations.worker")
    try:
        await tick.run_once()
        assert tick.background is not None
        tick.background.wait(timeout=5)
        assert not tick.background.busy
        assert finished == [quick]
        messages = [r.getMessage() for r in caplog.records]
        assert any(f"sync_timeout tenant_id={hung}" in m for m in messages)
        assert any("sync_round tenants=2 failed=1" in m for m in messages)
    finally:
        tick.close()


async def test_a_stuck_round_is_reported_at_most_once_per_interval(caplog) -> None:
    stuck, waiting = uuid4(), uuid4()
    now = [0.0]

    async def syncer(tenant_id: UUID) -> list[SyncReport]:
        await asyncio.sleep(30)
        return []

    tick = ConversationsTick(
        tenants=ScopedTenants([stuck, waiting]),
        sender=NoSender(),
        syncer=syncer,
        sync_interval=10,
        sync_in_background=True,
        monotonic=lambda: now[0],
    )
    caplog.set_level(logging.INFO, logger="qualify_api.conversations.worker")

    def warnings() -> list[str]:
        return [r.getMessage() for r in caplog.records if "sync_stuck" in r.getMessage()]

    try:
        await tick.run_once()  # the round starts and hangs on `stuck`
        assert tick.background is not None
        for _ in range(500):
            if tick.background.tenant_in_flight == stuck:
                break
            await asyncio.sleep(0.01)
        now[0] = 20  # refused, but younger than 3 intervals: no warning
        await tick.run_once()
        assert warnings() == []
        now[0] = 31
        await tick.run_once()
        now[0] = 35  # rate-limited
        await tick.run_once()
        assert len(warnings()) == 1
        assert f"tenant_in_flight={stuck}" in warnings()[0]
        assert "round_age_s=31" in warnings()[0]
        now[0] = 42
        await tick.run_once()
        assert len(warnings()) == 2
    finally:
        tick.close()


def test_close_with_a_round_in_flight_returns_within_its_bound() -> None:
    started = threading.Event()

    async def cancellable(tenant_id: UUID) -> list[SyncReport]:
        started.set()
        await asyncio.sleep(30)
        return []

    background = BackgroundSync(cancellable)
    assert background.submit([uuid4()])
    assert started.wait(timeout=5)
    t0 = time.monotonic()
    background.close(timeout=2)  # cancels the await: the thread ends cleanly
    assert time.monotonic() - t0 < 2
    assert not background._thread.is_alive()
    assert not background.submit([uuid4()])  # closed: nothing new starts

    gate = threading.Event()
    blocked = threading.Event()

    async def blocking(tenant_id: UUID) -> list[SyncReport]:
        blocked.set()
        gate.wait(timeout=10)  # a synchronous call that will not yield
        return []

    stuck = BackgroundSync(blocking)
    assert stuck.submit([uuid4()])
    assert blocked.wait(timeout=5)
    t0 = time.monotonic()
    stuck.close(timeout=0.2)  # cannot interrupt the thread; returns within the bound
    assert time.monotonic() - t0 < 1
    gate.set()
    stuck._thread.join(timeout=5)
    assert not stuck._thread.is_alive()


async def test_a_tenant_that_keeps_timing_out_backs_off_and_does_not_starve_the_others(
    caplog,
) -> None:
    """The reviewer's scenario: one tenant always hits its deadline, one is healthy.
    Without a backoff the bad one is due again the moment it times out (it was stamped
    at its start) and is retried back-to-back."""
    bad, good = uuid4(), uuid4()
    now = [0.0]
    polls: list[tuple[UUID, float]] = []

    async def syncer(tenant_id: UUID) -> list[SyncReport]:
        polls.append((tenant_id, now[0]))
        if tenant_id == bad:
            now[0] += 20  # the deadline passes on the (fake) clock…
            await asyncio.sleep(30)  # …and for real: wait_for cancels it
        return []

    tick = ConversationsTick(
        tenants=ScopedTenants([bad, good]),
        sender=NoSender(),
        syncer=syncer,
        sync_interval=10,
        sync_in_background=True,
        sync_tenant_timeout=0.02,
        monotonic=lambda: now[0],
    )
    caplog.set_level(logging.INFO, logger="qualify_api.conversations.worker")

    async def pass_at(t: float) -> None:
        now[0] = max(now[0], t)
        await tick.run_once()
        assert tick.background is not None
        tick.background.wait(timeout=5)

    try:
        await pass_at(0)  # bad: 0 → times out at 20; good: polled at 20
        assert polls == [(bad, 0), (good, 20)]
        await pass_at(20)  # right after the timeout: nobody is due
        assert polls == [(bad, 0), (good, 20)]
        await pass_at(30)  # one interval after the failure ENDED: both due again
        assert polls[2:] == [(bad, 30), (good, 50)]
        await pass_at(60)  # good is due (50 + 10); bad backs off 2 × 10 from 50
        assert polls[4:] == [(good, 60)]
        await pass_at(70)
        assert polls[5:] == [(bad, 70), (good, 90)]
        timeouts = [r.getMessage() for r in caplog.records if "sync_timeout" in r.getMessage()]
        assert [m.rsplit("next_due_s=", 1)[1] for m in timeouts] == ["10", "20", "40"]
    finally:
        tick.close()


async def test_a_success_resets_the_backoff() -> None:
    tenant = uuid4()
    now = [0.0]
    fail = [True]

    async def syncer(tenant_id: UUID) -> list[SyncReport]:
        if fail[0]:
            raise RuntimeError("graph down")
        return []

    tick = ConversationsTick(
        tenants=ScopedTenants([tenant]),
        sender=NoSender(),
        syncer=syncer,
        sync_interval=10,
        monotonic=lambda: now[0],
    )
    await tick.run_once()  # inline: fails at 0 → due at 10
    assert not tick._sync_due(tenant)
    now[0] = 10
    await tick.run_once()  # fails again → due at 10 + 20
    now[0] = 29
    assert not tick._sync_due(tenant)
    now[0] = 30
    fail[0] = False
    await tick.run_once()  # succeeds → due one plain interval later
    now[0] = 40
    assert tick._sync_due(tenant)
    fail[0] = True
    await tick.run_once()  # fails at 40: the count restarted, so factor 1 → due at 50
    now[0] = 50
    assert tick._sync_due(tenant)  # without the reset it would be factor 4 (due at 80)

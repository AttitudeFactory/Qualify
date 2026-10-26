"""m-24852492: billed BytePlus videos recovered by the worker, without any screen read.

Offline: the store, BytePlus's answers and the resumed run are fakes with a fixed
clock. What is pinned here is the pass itself — ask by id, resume only ended tasks,
claim before resuming, never twice — and its timing. The Postgres side (real reaper,
claim, `run_generation`) is `test_creative_vendor_recovery_db.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from qualify_api.creative import vendor_recovery as rec
from qualify_api.creative.vendor_recovery import (
    QUIET,
    UNKNOWN,
    PendingTask,
    WaitingDraft,
    recover_once,
)

T0 = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
TENANT_A = UUID("a0000000-0000-4000-8000-000000000001")
TENANT_B = UUID("b0000000-0000-4000-8000-000000000002")


@dataclass
class Draft:
    tenant_id: UUID
    stamp: datetime  # last sign of life (`content_drafts.updated_at`)
    tasks: dict[str, str]  # slot -> vendor task id
    status: str = "drafting"
    brand_id: UUID = field(default_factory=uuid4)
    pending: bool = True


class Store:
    """`RecoveryStore` over dicts; `now` is the shared fake clock. Tenant-scoped like
    RLS: a tenant only ever sees its own drafts."""

    def __init__(self) -> None:
        self.now = T0
        self.drafts: dict[UUID, Draft] = {}
        self.reaped: list[UUID] = []

    def add(self, tenant_id: UUID, *, stamp: datetime, tasks: dict[str, str]) -> UUID:
        draft_id = uuid4()
        self.drafts[draft_id] = Draft(tenant_id, stamp, dict(tasks))
        return draft_id

    def reap(self, *, tenant_id: UUID) -> int:
        self.reaped.append(tenant_id)
        return 0

    def waiting(self, *, tenant_id: UUID, now: datetime) -> list[WaitingDraft]:
        return [
            WaitingDraft(
                tenant_id,
                draft_id,
                d.brand_id,
                tuple(PendingTask(slot, task, "seedance") for slot, task in d.tasks.items()),
            )
            for draft_id, d in self.drafts.items()
            if d.tenant_id == tenant_id
            and d.status == "drafting"
            and d.pending
            and d.stamp < now - QUIET
        ]

    def claim(self, *, tenant_id: UUID, draft_id: UUID) -> bool:
        d = self.drafts.get(draft_id)
        if d is None or d.tenant_id != tenant_id:
            return False
        if d.status != "drafting" or not d.pending or d.stamp >= self.now - QUIET:
            return False
        d.stamp = self.now
        return True


class Vendor:
    """BytePlus's answer per task id; `delivered_at` makes a task succeed at that time."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self.states: dict[str, str] = {}
        self.delivered_at: dict[str, datetime] = {}
        self.asked: list[str] = []
        self.broken = False

    def status(self, task: PendingTask, *, tenant_id: UUID, brand_id: UUID) -> str:
        self.asked.append(task.vendor_task_id)
        if self.broken:
            raise ConnectionError("ark down")
        at = self.delivered_at.get(task.vendor_task_id)
        if at is not None:
            return "succeeded" if self.store.now >= at else "running"
        return self.states.get(task.vendor_task_id, UNKNOWN)


class Run:
    """The resumed run as `ContentService.run_generation` behaves: a draft still
    `drafting` settles once — the video and its cost on success, a refund on failure."""

    def __init__(self, store: Store, vendor: Vendor) -> None:
        self.store = store
        self.vendor = vendor
        self.calls: list[UUID] = []
        self.videos: list[UUID] = []
        self.costs: list[UUID] = []
        self.refunds: list[UUID] = []
        self.resumed_at: dict[UUID, datetime] = {}

    def __call__(self, tenant_id: UUID, draft_id: UUID) -> None:
        self.calls.append(draft_id)
        d = self.store.drafts[draft_id]
        if d.status != "drafting":
            return  # idempotent: already settled
        states = [
            self.vendor.status(
                PendingTask(s, t, "seedance"), tenant_id=tenant_id, brand_id=d.brand_id
            )
            for s, t in d.tasks.items()
        ]
        d.pending = False
        self.resumed_at[draft_id] = self.store.now
        if all(s == "succeeded" for s in states):
            d.status = "generated"
            self.videos.append(draft_id)
            self.costs.append(draft_id)
        else:
            d.status = "failed"
            self.refunds.append(draft_id)


def _pass(store: Store, vendor: Vendor, run: Run, tenants: list[UUID] | None = None) -> Any:
    return recover_once(
        tenants=lambda _now: tenants if tenants is not None else [TENANT_A],
        store=store,
        statuses=vendor,
        resume=run,
        now=store.now,
    )


def _world() -> tuple[Store, Vendor, Run]:
    store = Store()
    vendor = Vendor(store)
    return store, vendor, Run(store, vendor)


# -- acceptance criteria ------------------------------------------------------------------


def test_a_succeeded_task_is_settled_by_the_worker_without_any_screen_read() -> None:
    store, vendor, run = _world()
    draft = store.add(TENANT_A, stamp=T0 - timedelta(hours=2), tasks={"seedance-1": "cgt-1"})
    vendor.states["cgt-1"] = "succeeded"

    report = _pass(store, vendor, run)

    assert report.resumed == [draft]
    assert run.videos == [draft] and run.costs == [draft] and run.refunds == []
    assert store.drafts[draft].status == "generated"


def test_running_twice_or_beside_a_screen_read_never_duplicates_anything() -> None:
    store, vendor, run = _world()
    draft = store.add(TENANT_A, stamp=T0 - timedelta(hours=2), tasks={"seedance-1": "cgt-1"})
    vendor.states["cgt-1"] = "succeeded"

    # a screen read claimed it a moment ago (the stamp is fresh): the worker backs off
    assert store.claim(tenant_id=TENANT_A, draft_id=draft)
    first = _pass(store, vendor, run)
    assert first.resumed == [] and run.calls == []

    # quiet again later: the worker resumes it — once, however many passes follow
    store.now += timedelta(minutes=10)
    store.drafts[draft].stamp = store.now - timedelta(minutes=5)
    _pass(store, vendor, run)
    _pass(store, vendor, run)
    store.now += timedelta(minutes=10)
    _pass(store, vendor, run)
    assert run.calls == [draft]
    assert run.videos == [draft] and run.costs == [draft] and run.refunds == []


@pytest.mark.parametrize("state", ["failed", "expired", "cancelled", UNKNOWN])
def test_a_failed_expired_or_unknown_task_fails_the_piece_and_refunds(state: str) -> None:
    store, vendor, run = _world()
    draft = store.add(TENANT_A, stamp=T0 - timedelta(hours=2), tasks={"seedance-1": "cgt-1"})
    if state != UNKNOWN:
        vendor.states["cgt-1"] = state

    report = _pass(store, vendor, run)

    assert report.resumed == [draft]
    assert store.drafts[draft].status == "failed"
    assert run.videos == [] and run.costs == [] and run.refunds == [draft]


@pytest.mark.parametrize(
    "delivered_after",
    [timedelta(seconds=5), timedelta(minutes=2), timedelta(minutes=50), timedelta(hours=20)],
)
def test_a_delivered_video_is_recovered_within_ten_minutes(delivered_after: timedelta) -> None:
    """The generation thread dies (a deploy) right after BytePlus accepts the task; the
    worker passes every `RECOVERY_EVERY_SECONDS`. Whenever BytePlus delivers, the piece
    has its video less than 10 min later — far inside the 24 h `video_url` life."""
    store, vendor, run = _world()
    draft = store.add(TENANT_A, stamp=T0, tasks={"seedance-1": "cgt-1"})
    delivered = T0 + delivered_after
    vendor.delivered_at["cgt-1"] = delivered

    end = delivered + timedelta(hours=1)
    while store.now < end and draft not in run.resumed_at:
        _pass(store, vendor, run)
        store.now += timedelta(seconds=rec.RECOVERY_EVERY_SECONDS)

    assert run.videos == [draft]
    assert run.resumed_at[draft] - delivered < timedelta(minutes=10)


# -- the pass's own rules -----------------------------------------------------------------


def test_a_task_still_queued_or_running_is_left_for_the_next_pass() -> None:
    store, vendor, run = _world()
    draft = store.add(
        TENANT_A, stamp=T0 - timedelta(hours=1), tasks={"seedance-1": "a", "seedance-2": "b"}
    )
    vendor.states.update({"a": "succeeded", "b": "queued"})

    report = _pass(store, vendor, run)

    assert report.still_running == [draft] and run.calls == []
    assert store.drafts[draft].stamp == T0 - timedelta(hours=1)  # not claimed


def test_a_draft_whose_thread_is_alive_is_never_touched() -> None:
    store, vendor, run = _world()
    store.add(TENANT_A, stamp=T0 - timedelta(minutes=1), tasks={"seedance-1": "cgt-1"})
    vendor.states["cgt-1"] = "succeeded"

    report = _pass(store, vendor, run)

    assert vendor.asked == [] and run.calls == [] and report.resumed == []


def test_bytepluss_status_unreadable_skips_the_draft_and_keeps_going() -> None:
    store, vendor, run = _world()
    store.add(TENANT_A, stamp=T0 - timedelta(hours=1), tasks={"seedance-1": "cgt-1"})
    vendor.broken = True

    report = _pass(store, vendor, run)

    assert run.calls == [] and len(report.errors) == 1


def test_a_resumed_run_that_raises_does_not_stop_the_pass() -> None:
    store, vendor, _ = _world()
    first = store.add(TENANT_A, stamp=T0 - timedelta(hours=1), tasks={"seedance-1": "a"})
    second = store.add(TENANT_A, stamp=T0 - timedelta(hours=1), tasks={"seedance-1": "b"})
    vendor.states.update({"a": "succeeded", "b": "succeeded"})
    calls: list[UUID] = []

    def flaky(tenant_id: UUID, draft_id: UUID) -> None:
        calls.append(draft_id)
        if draft_id == first:
            raise RuntimeError("R2 down")

    report = recover_once(
        tenants=lambda _: [TENANT_A], store=store, statuses=vendor, resume=flaky, now=store.now
    )
    assert calls == [first, second]
    assert report.resumed == [second] and len(report.errors) == 1


def test_each_tenant_is_worked_on_its_own_and_one_failure_spares_the_others() -> None:
    store, vendor, run = _world()
    a = store.add(TENANT_A, stamp=T0 - timedelta(hours=1), tasks={"seedance-1": "a"})
    b = store.add(TENANT_B, stamp=T0 - timedelta(hours=1), tasks={"seedance-1": "b"})
    vendor.states.update({"a": "succeeded", "b": "succeeded"})

    # scoped to tenant B: tenant A's draft is never seen, asked about or claimed
    report = _pass(store, vendor, run, tenants=[TENANT_B])
    assert report.resumed == [b] and run.calls == [b] and vendor.asked == ["b", "b"]
    assert store.drafts[a].status == "drafting"
    # a claim across tenants is refused, as RLS would
    assert store.claim(tenant_id=TENANT_B, draft_id=a) is False

    original = store.waiting

    def failing(*, tenant_id: UUID, now: datetime) -> list[WaitingDraft]:
        if tenant_id == TENANT_B:
            raise RuntimeError("tenant B broken")
        return original(tenant_id=tenant_id, now=now)

    store.waiting = failing  # type: ignore[method-assign]
    report = _pass(store, vendor, run, tenants=[TENANT_B, TENANT_A])
    assert report.resumed == [a] and len(report.errors) == 1


def test_discovery_failing_reports_and_resumes_nothing() -> None:
    store, vendor, run = _world()

    def boom(_now: datetime) -> list[UUID]:
        raise RuntimeError("admin door down")

    report = recover_once(tenants=boom, store=store, statuses=vendor, resume=run, now=T0)
    assert report.tenants == 0 and report.errors == ["discovery: RuntimeError"]


def test_the_reaper_runs_for_every_tenant_in_scope() -> None:
    store, vendor, run = _world()
    _pass(store, vendor, run, tenants=[TENANT_A, TENANT_B, TENANT_A])
    assert store.reaped == [TENANT_A, TENANT_B]


def test_a_scoped_recovery_needs_a_tenant() -> None:
    with pytest.raises(ValueError):
        rec.scoped_tenants([])
    assert rec.scoped_tenants([TENANT_A, TENANT_A])(T0) == [TENANT_A]


@pytest.mark.parametrize(
    ("value", "on"), [("", True), ("on", True), ("off", False), ("0", False), ("OFF", False)]
)
def test_the_calendar_worker_switch(value: str, on: bool) -> None:
    """m-24852163: the pass moved to creative-worker; the calendar worker keeps it only
    while `QUALIFY_CALENDAR_VENDOR_RECOVERY` is not off (production sets it off)."""
    assert rec.runs_in_calendar_worker({rec.CALENDAR_SWITCH: value}) is on


@pytest.mark.parametrize(
    ("value", "on"), [("", True), ("on", True), ("off", False), ("0", False), ("OFF", False)]
)
def test_the_kill_switch(value: str, on: bool) -> None:
    assert rec.enabled({rec.ENV_SWITCH: value}) is on


def test_the_chore_does_nothing_when_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(rec.ENV_SWITCH, "off")

    def never() -> dict[str, Any]:
        raise AssertionError("nothing is built while switched off")

    monkeypatch.setattr(rec, "_production_parts", never)
    assert rec.recovery_chore([TENANT_A])() is None


def test_the_chore_builds_its_parts_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(rec.ENV_SWITCH, raising=False)
    store, vendor, run = _world()
    builds: list[int] = []

    def parts() -> dict[str, Any]:
        builds.append(1)
        return {"store": store, "statuses": vendor, "resume": run}

    monkeypatch.setattr(rec, "_production_parts", parts)
    chore = rec.recovery_chore([TENANT_A])
    chore()
    report = chore()
    assert builds == [1] and report is not None and report.tenants == 1


# -- the BytePlus status reader -----------------------------------------------------------


class _Key:
    api_key = "ark-key"


class _Credentials:
    def __init__(self) -> None:
        self.providers: list[str] = []

    def resolve(self, *, tenant_id: UUID, brand_id: UUID, provider: str) -> _Key:
        self.providers.append(provider)
        return _Key()


class _Adapter:
    def __init__(self, answer: Any) -> None:
        self.answer = answer
        self.asked: list[tuple[str, str]] = []

    def get_task(self, task_id: str, *, api_key: str) -> Any:
        self.asked.append((task_id, api_key))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def test_the_status_reader_asks_by_id_with_the_platform_key() -> None:
    adapter, credentials = _Adapter({"id": "cgt-1", "status": "Succeeded"}), _Credentials()
    reader = rec.SeedanceTaskStatus(adapter, credentials)
    task = PendingTask("seedance-1", "cgt-1", "seedance")
    assert reader.status(task, tenant_id=TENANT_A, brand_id=uuid4()) == "succeeded"
    assert adapter.asked == [("cgt-1", "ark-key")] and credentials.providers == ["seedance"]


def test_a_task_bytePlus_does_not_know_reads_unknown_and_other_errors_raise() -> None:
    from qualify_creative.adapters.byteplus_ark import ArkAPIError

    task = PendingTask("seedance-1", "cgt-1", "seedance")
    gone = rec.SeedanceTaskStatus(_Adapter(ArkAPIError(404, None, "no")), _Credentials())
    assert gone.status(task, tenant_id=TENANT_A, brand_id=uuid4()) == UNKNOWN
    named = rec.SeedanceTaskStatus(
        _Adapter(ArkAPIError(400, "ResourceNotFound", "no")), _Credentials()
    )
    assert named.status(task, tenant_id=TENANT_A, brand_id=uuid4()) == UNKNOWN
    down = rec.SeedanceTaskStatus(_Adapter(ArkAPIError(503, None, "busy")), _Credentials())
    with pytest.raises(ArkAPIError):
        down.status(task, tenant_id=TENANT_A, brand_id=uuid4())

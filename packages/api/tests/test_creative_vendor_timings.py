"""m-24852158: every vendor task leaves when it was submitted, started and ended.

Driven through the real Seedance adapter over a MockTransport (the answers ModelArk gives
while we wait) and the real run binding (`DraftVendorTasks`): the stamps come from the
same polls, never from an extra vendor call. A task resumed by id (m-24852154) is
stamped too — without inventing a wait it did not see."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

httpx = pytest.importorskip("httpx")

from qualify_creative.adapters import ArkTaskTimeout, SeedanceVideoAdapter  # noqa: E402
from qualify_creative.adapters.byteplus_ark import RESUME_TASK_PARAM  # noqa: E402
from qualify_creative.enums import GenerationTask  # noqa: E402
from qualify_creative.providers import GenerationRequest, RenderedPrompt  # noqa: E402

from qualify_api.creative.vendor_tasks import (  # noqa: E402
    DraftVendorTasks,
    FinalVendorTasks,
    VendorTaskRecord,
)
from qualify_api.creative.vendor_timings import (  # noqa: E402
    TaskWatch,
    normalize_status,
    phase_of,
)

T0 = datetime(2026, 10, 26, 14, 0, tzinfo=UTC)
MODEL = "dreamina-seedance-2-5-260628"
TENANT = UUID("00000000-0000-0000-0000-0000000000a1")


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def utc(self) -> datetime:
        return T0 + timedelta(seconds=self.now)


class TimedVendor:
    """ModelArk by the clock: `queued` for `queued_for` s after creation, `running` for
    `running_for` s, then `final`. `created_at` may predate the test (a resumed task)."""

    def __init__(
        self,
        clock: Clock,
        *,
        queued_for: float,
        running_for: float,
        final: str = "succeeded",
        created_at: float = 0.0,
    ) -> None:
        self.clock = clock
        self.queued_for = queued_for
        self.running_for = running_for
        self.final = final
        self.created_at = created_at
        self.posts = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            self.posts += 1
            self.created_at = self.clock.now
            return httpx.Response(200, json={"id": "cgt-1"})
        age = self.clock.now - self.created_at
        if age < self.queued_for:
            return httpx.Response(200, json={"id": "cgt-1", "status": "queued"})
        if age < self.queued_for + self.running_for:
            return httpx.Response(200, json={"id": "cgt-1", "status": "running"})
        if self.final != "succeeded":
            return httpx.Response(200, json={"id": "cgt-1", "status": self.final})
        return httpx.Response(
            200,
            json={
                "id": "cgt-1",
                "status": "succeeded",
                "model": MODEL,
                "content": {"video_url": "https://ark/v.mp4"},
                "usage": {"completion_tokens": 49673},
                "duration": 5,
            },
        )


@dataclass
class FakeStore:
    """The 0090 task store (no timings of its own) — the clock is passed apart."""

    records: list[dict[str, Any]] = field(default_factory=list)

    def record(self, **kw: Any) -> None:
        self.records.append(kw)

    def tasks(self, **_: Any) -> tuple[VendorTaskRecord, ...]:
        return ()

    def settle(self, **_: Any) -> None:
        return None

    def waiting(self, **_: Any) -> frozenset[UUID]:
        return frozenset()


@dataclass
class FakeClock:
    """`VendorTaskClock` in memory, with the same write-once rules as Postgres."""

    rows: dict[str, dict[str, Any]] = field(default_factory=dict)
    fail: bool = False

    def mark_submitted(self, **kw: Any) -> None:
        if self.fail:
            raise RuntimeError("db down")
        at = kw.pop("at")
        self.rows.setdefault(
            kw["vendor_task_id"],
            {
                **kw,
                "submitted_at": at,
                "running_at": None,
                "finished_at": None,
                "final_status": None,
                "late": False,
            },
        )

    def mark_running(self, *, tenant_id: UUID, vendor_task_id: str, at: datetime) -> None:
        if self.fail:
            raise RuntimeError("db down")
        row = self.rows[vendor_task_id]
        if row["running_at"] is None and row["finished_at"] is None:
            row["running_at"] = at

    def mark_finished(
        self, *, tenant_id: UUID, vendor_task_id: str, status: str, at: datetime, late: bool
    ) -> None:
        if self.fail:
            raise RuntimeError("db down")
        row = self.rows[vendor_task_id]
        if row["finished_at"] is None:
            row.update(finished_at=at, final_status=status, late=late)


def _adapter(vendor: TimedVendor, clock: Clock) -> SeedanceVideoAdapter:
    return SeedanceVideoAdapter(
        transport=httpx.MockTransport(vendor),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        poll_interval_seconds=5,
    )


def _binding(clock: Clock, timings: FakeClock, **kw: Any) -> DraftVendorTasks:
    return DraftVendorTasks(
        FakeStore(),
        tenant_id=TENANT,
        draft_id=uuid4(),
        revision=1,
        pipeline_version="creative-v9",
        context={},
        heartbeat=None,
        clock=timings,
        now=clock.utc,
        **kw,
    )


def _request(observer: Any, **params: object) -> GenerationRequest:
    return GenerationRequest(
        task=GenerationTask.SCENE_VIDEO,
        rendered_prompt=RenderedPrompt("", "", ""),
        params={"prompt": "Una hamburguesa girando.", "model": MODEL, **params},
        observer=observer,
    )


def test_a_queued_running_succeeded_task_leaves_its_three_stamps() -> None:
    clock, timings = Clock(), FakeClock()
    vendor = TimedVendor(clock, queued_for=30, running_for=80)
    binding = _binding(clock, timings)

    _adapter(vendor, clock).generate(
        _request(binding.observer("seedance-1", "seedance", MODEL)), api_key="k"
    )

    row = timings.rows["cgt-1"]
    assert row["submitted_at"] == T0
    # polls every 5 s: the first `running` answer is heard at 30 s
    assert row["running_at"] == T0 + timedelta(seconds=30)
    assert row["finished_at"] == T0 + timedelta(seconds=110)
    assert row["final_status"] == "succeeded" and row["late"] is False
    assert row["provider"] == "seedance" and row["model_id"] == MODEL
    assert row["slot"] == "seedance-1" and row["pipeline_version"] == "creative-v9"
    assert row["tenant_id"] == TENANT


def test_a_task_resumed_by_id_keeps_its_submission_and_is_stamped_while_waited() -> None:
    """m-24852154: the first run's wait ran out while the task was queued; the resumed
    run hears it go `running` and end — both stamps are real, never a second row."""
    clock, timings = Clock(), FakeClock()
    vendor = TimedVendor(clock, queued_for=10**6, running_for=60)
    first = _binding(clock, timings)
    adapter = SeedanceVideoAdapter(
        transport=httpx.MockTransport(vendor),
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        poll_interval_seconds=5,
        queue_timeout_seconds=60,
    )
    with pytest.raises(ArkTaskTimeout):
        adapter.generate(_request(first.observer("seedance-1", "seedance", MODEL)), api_key="k")
    assert timings.rows["cgt-1"]["running_at"] is None

    # BytePlus starts it 200 s after creation; the resumed run waits for the same id
    vendor.queued_for = 200
    resumed = _binding(
        clock,
        timings,
        existing=[VendorTaskRecord("seedance-1", "cgt-1", "seedance", MODEL, "pending", {})],
    )
    _adapter(vendor, clock).generate(
        _request(resumed.observer_for_wait("seedance-1"), **{RESUME_TASK_PARAM: "cgt-1"}),
        api_key="k",
    )

    row = timings.rows["cgt-1"]
    assert vendor.posts == 1
    assert row["submitted_at"] == T0
    assert row["running_at"] == T0 + timedelta(seconds=200)
    assert row["finished_at"] == T0 + timedelta(seconds=260)
    assert row["final_status"] == "succeeded" and row["late"] is False


def test_a_resumed_task_already_ended_is_finished_late_with_no_wait_invented() -> None:
    clock, timings = Clock(), FakeClock()
    timings.mark_submitted(
        tenant_id=TENANT,
        provider="seedance",
        model_id=MODEL,
        vendor_task_id="cgt-1",
        draft_id=None,
        revision=1,
        slot="seedance-1",
        pipeline_version=None,
        at=T0,
    )
    clock.now = 3600  # the thread died; the task ended long ago
    vendor = TimedVendor(clock, queued_for=10, running_for=60, created_at=0.0)
    resumed = _binding(clock, timings)
    _adapter(vendor, clock).generate(
        _request(resumed.observer_for_wait("seedance-1"), **{RESUME_TASK_PARAM: "cgt-1"}),
        api_key="k",
    )
    row = timings.rows["cgt-1"]
    assert row["running_at"] is None
    assert row["finished_at"] == T0 + timedelta(seconds=3600)
    assert row["late"] is True


def test_a_resumed_task_found_running_gets_no_running_stamp_but_a_real_end() -> None:
    watch_clock, timings = Clock(), FakeClock()
    timings.rows["cgt-9"] = {"running_at": None, "finished_at": None}
    watch = TaskWatch(
        timings,
        tenant_id=TENANT,
        draft_id=None,
        revision=1,
        slot="seedance-1",
        provider="",
        model_id="",
        pipeline_version=None,
        now=watch_clock.utc,
    )
    watch.polled("cgt-9", "running")
    watch_clock.now = 40
    watch.polled("cgt-9", "succeeded")
    assert timings.rows["cgt-9"]["running_at"] is None
    assert timings.rows["cgt-9"]["finished_at"] == T0 + timedelta(seconds=40)
    assert timings.rows["cgt-9"]["late"] is False


def test_omnihuman_words_and_a_failed_end_are_read_as_ours() -> None:
    clock, timings = Clock(), FakeClock()
    binding = _binding(clock, timings)
    observer = binding.observer("omnihuman-1", "omnihuman", "omnihuman-1.5")
    observer.created("oh-1")
    observer.polled("oh-1", "in_queue")
    clock.now = 90
    observer.polled("oh-1", "generating")
    clock.now = 1500
    observer.polled("oh-1", "generating")
    observer.polled("oh-1", "canceled")
    row = timings.rows["oh-1"]
    assert row["running_at"] == T0 + timedelta(seconds=90)
    assert row["finished_at"] == T0 + timedelta(seconds=1500)
    assert row["final_status"] == "cancelled"


def test_a_final_is_stamped_under_its_final_slot() -> None:
    clock, timings = Clock(), FakeClock()
    asset = uuid4()
    final = FinalVendorTasks(
        FakeStore(),
        tenant_id=TENANT,
        draft_id=uuid4(),
        revision=2,
        asset_id=asset,
        heartbeat=None,
        clock=timings,
        now=clock.utc,
    )
    final.observer("seedance-1", "seedance", MODEL).created("cgt-f")
    assert timings.rows["cgt-f"]["slot"] == f"final:{asset}"
    assert phase_of(timings.rows["cgt-f"]["slot"]) == "final"
    assert phase_of("seedance-2") == "draft"


def test_a_stamp_that_fails_never_breaks_the_generation() -> None:
    clock, timings = Clock(), FakeClock(fail=True)
    vendor = TimedVendor(clock, queued_for=10, running_for=20)
    binding = _binding(clock, timings)
    result = _adapter(vendor, clock).generate(
        _request(binding.observer("seedance-1", "seedance", MODEL)), api_key="k"
    )
    assert result.media_url == "https://ark/v.mp4"


def test_a_store_without_timings_and_no_clock_stamps_nothing() -> None:
    binding = DraftVendorTasks(
        FakeStore(),
        tenant_id=TENANT,
        draft_id=uuid4(),
        revision=1,
        pipeline_version=None,
        context={},
        heartbeat=None,
    )
    observer = binding.observer("seedance-1", "seedance", MODEL)
    observer.created("cgt-1")
    observer.polled("cgt-1", "succeeded")  # nothing to stamp, nothing raised


@pytest.mark.parametrize(
    ("vendor", "ours"),
    [
        ("queued", "queued"),
        ("in_queue", "queued"),
        ("running", "running"),
        ("generating", "running"),
        ("done", "succeeded"),
        ("expired", "expired"),
        ("not_found", "not_found"),
        ("weird", ""),
        ("", ""),
    ],
)
def test_vendor_statuses_are_normalized(vendor: str, ours: str) -> None:
    assert normalize_status(vendor) == ours

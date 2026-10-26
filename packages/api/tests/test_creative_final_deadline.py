"""The queue cannot outlive a paid preview, nor reset its seven-day clock (m-24852168)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from qualify_api.creative import job_queue as q
from qualify_api.creative.final_deadline import (
    FINAL_EXPIRED_TEXT,
    deadline_for_preview,
    final_is_urgent,
)
from qualify_api.creative.worker import lanes, runner

from .test_creative_worker_lanes import NOW, A, B, final, scheduled, standard
from .test_creative_worker_runner import (
    Clock,
    FakeBytePlus,
    Job,
    MemoryStore,
    make_worker,
    one,
)


def test_deadline_uses_preview_vendor_created_at_with_fifteen_minute_margin() -> None:
    created = datetime(2026, 10, 19, 11, 17, 42, tzinfo=UTC)
    expected = datetime(2026, 10, 26, 11, 2, 42, tzinfo=UTC)
    assert deadline_for_preview(created.timestamp()) == expected
    assert deadline_for_preview(created) == expected


@pytest.mark.parametrize("value", [None, True, float("nan"), float("inf"), "2026-10-19"])
def test_bad_preview_date_never_silently_gets_a_new_ttl(value: object) -> None:
    with pytest.raises(ValueError):
        deadline_for_preview(value)  # type: ignore[arg-type]


def test_urgent_final_beats_every_standard_even_one_aged_to_now() -> None:
    urgent = replace(final(B), deadline=NOW + timedelta(hours=23))
    old_final = final(A, waited=timedelta(hours=2))
    old_standard = standard(A, waited=timedelta(hours=2))
    assert lanes.pick_next([old_standard, old_final, urgent], [], size=10, now=NOW) is urgent
    assert (
        lanes.vendor_priority(
            lane=urgent.lane,
            kind=urgent.kind,
            priority=urgent.priority,
            queued_at=urgent.queued_at,
            now=NOW,
            deadline=urgent.deadline,
        )
        == 9
    )


def test_twenty_four_hours_is_not_yet_urgent() -> None:
    assert not final_is_urgent(NOW + timedelta(hours=24), NOW)
    assert final_is_urgent(NOW + timedelta(hours=24) - timedelta(microseconds=1), NOW)


def test_urgent_nightly_final_can_use_reserved_slot_without_exceeding_tenant_cap() -> None:
    urgent = replace(scheduled(B), deadline=NOW + timedelta(hours=23))
    occupied = [replace(standard(UUID(int=i + 1)), status=q.SUBMITTED) for i in range(7)]
    assert lanes.pick_next([urgent], occupied, size=10, now=NOW) is urgent
    occupied.extend([replace(scheduled(B), status=q.SUBMITTED)] * 2)
    assert lanes.pick_next([urgent], occupied, size=10, now=NOW) is None


class DeadlineStore(MemoryStore):
    deadline: datetime

    def _row(self, job: Job) -> q.QueueRow:
        return replace(super()._row(job), deadline=self.deadline)

    def load(self, claim: q.ClaimedJob) -> q.JobRow | None:
        row = super().load(claim)
        return replace(row, deadline=self.deadline) if row is not None else None


def test_expired_unsubmitted_final_fails_without_post_and_releases_slot() -> None:
    store, vendor, clock = DeadlineStore(), FakeBytePlus(), Clock()
    store.deadline = clock()
    job_id = store.add(A, kind=q.KIND_FINAL)
    worker = make_worker(store, vendor, clock)
    assert worker.process(one(worker)) == runner.FAILED_OUTCOME
    assert vendor.submits == []
    assert vendor.finished == [(job_id, None, "expired")]
    assert store.jobs[job_id].status == q.FAILED
    assert store.jobs[job_id].last_error == FINAL_EXPIRED_TEXT
    assert store.slot_of(job_id) is None


def test_expired_deadline_does_not_abandon_a_final_already_paid_for() -> None:
    store, vendor, clock = DeadlineStore(), FakeBytePlus(), Clock()
    store.deadline = clock() - timedelta(minutes=1)
    job_id = store.add(A, kind=q.KIND_FINAL, vendor_task_id="already-paid")
    worker = make_worker(store, vendor, clock)
    assert worker.process(one(worker)) == runner.SUCCEEDED_OUTCOME
    assert vendor.submits == []
    assert vendor.finished == [(job_id, "already-paid", "succeeded")]


def test_live_urgent_final_sends_vendor_priority_nine() -> None:
    store, vendor, clock = DeadlineStore(), FakeBytePlus(), Clock()
    store.deadline = clock() + timedelta(hours=23)
    store.add(A, kind=q.KIND_FINAL)
    worker = make_worker(store, vendor, clock)
    assert worker.process(one(worker)) == runner.SUCCEEDED_OUTCOME
    assert vendor.contexts[0].vendor_priority == 9


def test_night_maintenance_failure_does_not_skip_pipeline_preparation(monkeypatch):
    from qualify_api.creative.worker.__main__ import _night_preparation

    calls = []

    def fail(*args):
        calls.append("night")
        raise RuntimeError("synthetic maintenance failure")

    monkeypatch.setattr("qualify_api.creative.final_review.nightly_maintenance", fail)
    prepare = _night_preparation(lambda: calls.append("prepare"), ())
    prepare()
    prepare()
    assert calls == ["night", "prepare", "prepare"]

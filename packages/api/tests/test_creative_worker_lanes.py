"""m-24852163 — the fair pick of `creative-worker`, offline (`creative/worker/lanes.py`).

Pins the acceptance criteria of the ticket that are about ORDER (lanes, the 3 reserved
slots, 2 per business, aging) and the offline test of `docs/seguridad-creative-worker.md`
§6: «el reclamo no supera 10 cupos ni 2 por negocio con 50 trabajos de 5 negocios; el
reparto es por turnos».
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qualify_api.creative import job_queue as q
from qualify_api.creative.worker import lanes

NOW = datetime(2026, 10, 26, 15, 0, tzinfo=UTC)
A = UUID("a0000000-0000-4000-8000-00000000000a")
B = UUID("b0000000-0000-4000-8000-00000000000b")
TENANTS = [UUID(f"{i:08d}-0000-4000-8000-000000000000") for i in range(1, 9)]


def job(
    tenant: UUID,
    *,
    lane: str = q.LANE_IMMEDIATE,
    kind: str = q.KIND_PREVIEW,
    priority: int = 0,
    waited: timedelta = timedelta(minutes=1),
    status: str = q.QUEUED,
    holds_slot: bool = False,
) -> q.QueueRow:
    return q.QueueRow(
        job_id=uuid4(),
        tenant_id=tenant,
        kind=kind,
        lane=lane,
        priority=priority,
        queued_at=NOW - waited,
        status=status,
        holds_slot=holds_slot,
    )


def standard(tenant: UUID, **kw: object) -> q.QueueRow:
    return job(tenant, **kw)  # type: ignore[arg-type]


def now_job(tenant: UUID, **kw: object) -> q.QueueRow:
    return job(tenant, priority=lanes.NOW_PRIORITY, **kw)  # type: ignore[arg-type]


def final(tenant: UUID, **kw: object) -> q.QueueRow:
    return job(tenant, kind=q.KIND_FINAL, **kw)  # type: ignore[arg-type]


def scheduled(tenant: UUID, **kw: object) -> q.QueueRow:
    return job(tenant, lane=q.LANE_NIGHTLY, kind=q.KIND_FINAL, **kw)  # type: ignore[arg-type]


def running(row: q.QueueRow) -> q.QueueRow:
    return q.QueueRow(**{**row.__dict__, "status": q.SUBMITTED})


def drain(waiting: list[q.QueueRow], in_flight: list[q.QueueRow], size: int) -> list[q.QueueRow]:
    """Claim until the pick says nothing may start; returns the claims in order."""
    claimed: list[q.QueueRow] = []
    while (pick := lanes.pick_next(waiting, in_flight, size=size, now=NOW)) is not None:
        waiting.remove(pick)
        in_flight.append(running(pick))
        claimed.append(pick)
    return claimed


# -- lanes ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lane", "kind", "priority", "expected"),
    [
        (q.LANE_IMMEDIATE, q.KIND_PREVIEW, 0, lanes.STANDARD),
        (q.LANE_IMMEDIATE, q.KIND_PRESENTER, 3, lanes.STANDARD),
        (q.LANE_IMMEDIATE, q.KIND_CAROUSEL_SCENE, 0, lanes.STANDARD),
        (q.LANE_IMMEDIATE, q.KIND_FINAL, 0, lanes.FINAL),
        (q.LANE_IMMEDIATE, q.KIND_FINAL, 9, lanes.NOW),
        (q.LANE_IMMEDIATE, q.KIND_PREVIEW, lanes.NOW_PRIORITY, lanes.NOW),
        (q.LANE_NIGHTLY, q.KIND_FINAL, 0, lanes.SCHEDULED),
        (q.LANE_NIGHTLY, q.KIND_FINAL, 9, lanes.SCHEDULED),
    ],
)
def test_the_four_lanes_come_from_the_queue_columns(
    lane: str, kind: str, priority: int, expected: str
) -> None:
    assert lanes.base_lane(lane=lane, kind=kind, priority=priority) == expected


def test_lane_order_now_final_standard_scheduled() -> None:
    waiting = [scheduled(TENANTS[0]), standard(TENANTS[1]), final(TENANTS[2]), now_job(TENANTS[3])]
    claimed = drain(list(waiting), [], size=10)
    assert [lanes.lane_of(row) for row in claimed] == [
        lanes.NOW,
        lanes.FINAL,
        lanes.STANDARD,
        lanes.SCHEDULED,
    ]


def test_vendor_priority_follows_the_lane() -> None:
    assert lanes.VENDOR_PRIORITY[lanes.NOW] > lanes.VENDOR_PRIORITY[lanes.FINAL]
    assert lanes.VENDOR_PRIORITY[lanes.FINAL] > lanes.VENDOR_PRIORITY[lanes.STANDARD]
    assert lanes.VENDOR_PRIORITY[lanes.STANDARD] > lanes.VENDOR_PRIORITY[lanes.SCHEDULED]
    assert all(0 <= p <= 9 for p in lanes.VENDOR_PRIORITY.values())
    fresh = lanes.vendor_priority(
        lane=q.LANE_NIGHTLY, kind=q.KIND_FINAL, priority=0, queued_at=NOW, now=NOW
    )
    aged = lanes.vendor_priority(
        lane=q.LANE_NIGHTLY,
        kind=q.KIND_FINAL,
        priority=0,
        queued_at=NOW - timedelta(minutes=16),
        now=NOW,
    )
    assert (fresh, aged) == (
        lanes.VENDOR_PRIORITY[lanes.SCHEDULED],
        lanes.VENDOR_PRIORITY[lanes.STANDARD],
    )


# -- acceptance criteria -----------------------------------------------------------------


def test_ac_second_business_takes_the_first_free_slot() -> None:
    """10 slots, 30 `standard` jobs of one business + 1 of another: the second business
    enters in the first free slot, ahead of the first business's older jobs."""
    waiting = [standard(A, waited=timedelta(minutes=10, seconds=i)) for i in range(30)]
    waiting.append(standard(B, waited=timedelta(seconds=5)))
    in_flight: list[q.QueueRow] = []

    first = lanes.pick_next(waiting, in_flight, size=10, now=NOW)
    assert first is not None and first.tenant_id == A  # nobody in flight: oldest first
    waiting.remove(first)
    in_flight.append(running(first))

    second = lanes.pick_next(waiting, in_flight, size=10, now=NOW)
    assert second is not None and second.tenant_id == B  # B has fewer in flight
    waiting.remove(second)
    in_flight.append(running(second))

    claimed = drain(waiting, in_flight, size=10)
    by_tenant = Counter(row.tenant_id for row in in_flight)
    assert by_tenant == {A: 2, B: 1}
    assert len(claimed) == 1  # A's second job; then A waits for a slot of its own


def test_ac_reserved_slots_let_now_and_final_in_without_waiting() -> None:
    """7 slots held by `standard`: a `now` or `final` job enters; one more `standard`
    waits."""
    in_flight = [running(standard(t)) for t in TENANTS[:4] for _ in range(2)][:7]
    assert len(in_flight) == 7
    extra_standard = standard(TENANTS[5], waited=timedelta(minutes=5))
    assert lanes.pick_next([extra_standard], in_flight, size=10, now=NOW) is None

    for urgent in (now_job(TENANTS[6]), final(TENANTS[6])):
        pick = lanes.pick_next([extra_standard, urgent], in_flight, size=10, now=NOW)
        assert pick is urgent


def test_ac_a_business_never_runs_more_than_two_standard_jobs() -> None:
    waiting = [standard(A, waited=timedelta(minutes=14, seconds=i)) for i in range(20)]
    waiting += [scheduled(A, waited=timedelta(minutes=1, seconds=i)) for i in range(5)]
    drain(waiting, in_flight := [], size=10)
    assert sum(1 for row in in_flight if lanes.lane_of(row) == lanes.STANDARD) <= 2
    assert len(in_flight) == 2  # standard + scheduled share the cap of 2

    # aging does not open a third slot for the same business either
    aged = [standard(A, waited=timedelta(minutes=30))]
    assert lanes.pick_next(aged, in_flight, size=10, now=NOW) is None


def test_ac_a_scheduled_job_waiting_over_15_minutes_climbs_one_lane() -> None:
    fresh = scheduled(A, waited=timedelta(minutes=14, seconds=59))
    aged = scheduled(B, waited=timedelta(minutes=15))
    assert lanes.effective_lane(fresh, NOW) == lanes.SCHEDULED
    assert lanes.effective_lane(aged, NOW) == lanes.STANDARD
    # one lane only, not straight to the top
    very_old = scheduled(B, waited=timedelta(hours=5))
    assert lanes.effective_lane(very_old, NOW) == lanes.STANDARD

    # aged, it goes ahead of a fresh standard job of a business with more in flight
    other = standard(TENANTS[0], waited=timedelta(minutes=2))
    in_flight = [running(standard(TENANTS[0]))]
    assert lanes.pick_next([other, aged], in_flight, size=10, now=NOW) is aged


def test_aging_lets_a_standard_job_into_a_reserved_slot() -> None:
    """Nobody waits forever: with 7 `standard` in flight, a preview waiting 15 min climbs
    to `final` and takes a reserved slot."""
    in_flight = [running(standard(t)) for t in TENANTS[:4] for _ in range(2)][:7]
    waiting_long = standard(TENANTS[6], waited=timedelta(minutes=15))
    assert lanes.effective_lane(waiting_long, NOW) == lanes.FINAL
    assert lanes.pick_next([waiting_long], in_flight, size=10, now=NOW) is waiting_long


def test_security_review_fifty_jobs_five_businesses_by_turns() -> None:
    """`docs/seguridad-creative-worker.md` §6: never over 10 slots nor 2 per business, and
    the first five claims are one per business."""
    tenants = TENANTS[:5]
    waiting = [
        standard(t, waited=timedelta(minutes=10, seconds=50 - i))
        for i in range(10)
        for t in tenants
    ]
    claimed = drain(waiting, in_flight := [], size=10)
    assert len(in_flight) <= 10
    assert max(Counter(r.tenant_id for r in in_flight).values()) <= lanes.MAX_PER_TENANT
    assert {row.tenant_id for row in claimed[:5]} == set(tenants)
    # standard alone stops at size - reserved
    assert len(in_flight) == 10 - lanes.reserved_slots(10)


def test_priority_lanes_have_their_own_cap_per_business() -> None:
    waiting = [now_job(A, waited=timedelta(seconds=i)) for i in range(5)]
    drain(waiting, in_flight := [], size=10)
    assert len(in_flight) == lanes.MAX_PER_TENANT


def test_a_job_that_holds_a_slot_goes_first_even_when_the_pool_is_full() -> None:
    in_flight = [running(standard(t)) for t in TENANTS[:5] for _ in range(2)]
    held = standard(TENANTS[7], holds_slot=True, status=q.QUEUED)
    in_flight.append(held)
    urgent = now_job(TENANTS[6])
    assert lanes.pick_next([urgent, held], in_flight, size=10, now=NOW) is held
    assert lanes.pick_next([urgent], in_flight, size=10, now=NOW) is None


@pytest.mark.parametrize(("size", "reserved"), [(10, 3), (30, 3), (5, 1), (1, 0), (2, 0)])
def test_reserved_slots_scale_down_for_small_pools(size: int, reserved: int) -> None:
    assert lanes.reserved_slots(size) == reserved


def test_omnihuman_single_slot_still_runs_a_presenter() -> None:
    presenter = job(A, kind=q.KIND_PRESENTER)
    assert lanes.pick_next([presenter], [], size=1, now=NOW) is presenter
    assert lanes.pick_next([presenter], [running(job(B))], size=1, now=NOW) is None


def test_nothing_waiting_nothing_picked() -> None:
    assert lanes.pick_next([], [], size=10, now=NOW) is None

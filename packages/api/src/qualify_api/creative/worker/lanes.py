"""Which queued job goes next: lanes, reserved slots, fair share, aging (m-24852163).

Pure functions over what the worker door may see of the queue (`job_queue.QueueRow`), so
every rule is tested offline; `store.PostgresQueueStore.claim_fair` runs them inside one
transaction under the pool's advisory lock and claims the job they pick.

**Lanes** (ticket m-24852163, design of principal-architect, ADR 41 §2.3–2.4). The
schema keeps ADR 41's two queue lanes (`immediate`, `nightly`); the four lanes of the
worker are derived from the job's queue columns, without a new column:

- `now` — `immediate` with `priority >= NOW_PRIORITY`: «Publicar ahora», same-day
  finals and, in Fase 2, «Generar ya».
- `final` — `immediate`, kind `final`: a final asked from the piece.
- `standard` — any other `immediate` job: previews, regenerations, presenters, carousel
  scenes.
- `scheduled` — `nightly`: finals of approved previews, sent in their first night (the
  enqueuer sets `not_before` to the business's 00:00).

The enqueuer (m-24852166) sets `lane` and `priority`; this module only reads them.

**Rules, in order:**

1. A job that already holds a slot (requeued with a BytePlus task still to poll) goes
   first: its slot is already counted and it only needs polling.
2. `now` > `final` > `standard` > `scheduled`.
3. **Reserved slots:** `standard` and `scheduled` together never hold more than
   `size - reserved_slots(size)` slots (7 of 10): the last 3 are kept for `now` and
   `final`. A small pool (OmniHuman: 1 slot) reserves nothing — it would never run a
   preview.
4. **At most `MAX_PER_TENANT` (2) slots per business** in `standard` + `scheduled`, and
   2 more in `now` + `final` (so one business cannot take all the reserved slots either).
5. **Turns between businesses:** inside a lane, the business with the fewest jobs in
   flight goes first, then the job that has waited longest.
6. **Aging:** a job waiting `AGING_AFTER` (15 min) or more climbs ONE lane
   (`scheduled` → `standard` → `final` → `now`), so nobody waits forever. An aged
   `standard` job may then use a reserved slot — that is the point of aging.

In-flight jobs are counted by the lane they were enqueued in (not aged): an aged job
that took a reserved slot still counts as `standard` afterwards.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timedelta

from qualify_api.creative.final_deadline import final_is_urgent
from qualify_api.creative.job_queue import KIND_FINAL, LANE_NIGHTLY, QueueRow

NOW = "now"
FINAL = "final"
STANDARD = "standard"
SCHEDULED = "scheduled"
#: Best first.
LANES: tuple[str, ...] = (NOW, FINAL, STANDARD, SCHEDULED)
_RANK = {lane: rank for rank, lane in enumerate(LANES)}
#: The lanes the reserved slots are kept for.
PRIORITY_LANES: frozenset[str] = frozenset({NOW, FINAL})

#: `priority` from which an `immediate` job is in the `now` lane.
NOW_PRIORITY = 8
#: Slots of a pool that `standard` and `scheduled` may never take (ticket: 3 of 10).
RESERVED_SLOTS = 3
#: Slots one business may hold at once per pool, in `standard` + `scheduled`, and again
#: in `now` + `final`.
MAX_PER_TENANT = 2
#: Waiting this long climbs one lane.
AGING_AFTER = timedelta(minutes=15)

#: BytePlus's own queue `priority` (0–9, free) per lane, sent with the task: if we ever
#: pass the cap, BytePlus serves our lanes in the same order.
VENDOR_PRIORITY: dict[str, int] = {NOW: 9, FINAL: 7, STANDARD: 4, SCHEDULED: 0}


def base_lane(*, lane: str, kind: str, priority: int) -> str:
    """The worker lane a job was enqueued in (table above)."""
    if lane == LANE_NIGHTLY:
        return SCHEDULED
    if priority >= NOW_PRIORITY:
        return NOW
    if kind == KIND_FINAL:
        return FINAL
    return STANDARD


def lane_of(row: QueueRow) -> str:
    return base_lane(lane=row.lane, kind=row.kind, priority=row.priority)


def effective_lane(row: QueueRow, now: datetime) -> str:
    """The lane after aging: one lane up once the job has waited `AGING_AFTER`."""
    lane = lane_of(row)
    if row.kind == KIND_FINAL and final_is_urgent(row.deadline, now) and lane != NOW:
        return FINAL
    if now - row.queued_at >= AGING_AFTER and _RANK[lane] > 0:
        return LANES[_RANK[lane] - 1]
    return lane


def reserved_slots(size: int) -> int:
    """3 of 10; a third of a smaller pool, rounded down (OmniHuman's 1 slot: none)."""
    return min(RESERVED_SLOTS, size // 3)


def pick_next(
    waiting: Sequence[QueueRow], in_flight: Sequence[QueueRow], *, size: int, now: datetime
) -> QueueRow | None:
    """The job to claim next from `waiting`, or None when nothing may start now.

    `in_flight` is every job of the pool that holds a slot or is claimed (all businesses);
    `size` is the pool's configured number of slots."""
    held = [row for row in waiting if row.holds_slot]
    if held:
        return min(held, key=lambda row: (row.queued_at, str(row.job_id)))

    if len(in_flight) >= size:
        return None
    reserved = reserved_slots(size)
    common_in_use = 0
    common_by_tenant: Counter = Counter()
    priority_by_tenant: Counter = Counter()
    total_by_tenant: Counter = Counter()
    for row in in_flight:
        total_by_tenant[row.tenant_id] += 1
        if lane_of(row) in PRIORITY_LANES:
            priority_by_tenant[row.tenant_id] += 1
        else:
            common_in_use += 1
            common_by_tenant[row.tenant_id] += 1

    def order(row: QueueRow) -> tuple[int, int, datetime, int, datetime, str]:
        urgent = row.kind == KIND_FINAL and final_is_urgent(row.deadline, now)
        return (
            0 if lane_of(row) == NOW else (1 if urgent else 2),
            _RANK[effective_lane(row, now)] if not urgent else 0,
            row.deadline if urgent and row.deadline is not None else now,
            total_by_tenant[row.tenant_id],
            row.queued_at,
            str(row.job_id),
        )

    for row in sorted(waiting, key=order):
        # The per-business cap follows the lane the job was enqueued in (an aged preview
        # is still a preview: never a third one for the same business) ...
        if lane_of(row) in PRIORITY_LANES:
            if priority_by_tenant[row.tenant_id] >= MAX_PER_TENANT:
                continue
        elif common_by_tenant[row.tenant_id] >= MAX_PER_TENANT:
            continue
        # ... the reserved slots follow the aged lane (aging is what lets it in).
        if effective_lane(row, now) not in PRIORITY_LANES and common_in_use >= size - reserved:
            continue
        return row
    return None


def vendor_priority(
    *,
    lane: str,
    kind: str,
    priority: int,
    queued_at: datetime,
    now: datetime,
    deadline: datetime | None = None,
) -> int:
    """BytePlus's `priority` for a job about to be submitted: that of its aged lane."""
    if kind == KIND_FINAL and final_is_urgent(deadline, now):
        return 9
    row_lane = base_lane(lane=lane, kind=kind, priority=priority)
    if now - queued_at >= AGING_AFTER and _RANK[row_lane] > 0:
        row_lane = LANES[_RANK[row_lane] - 1]
    return VENDOR_PRIORITY[row_lane]

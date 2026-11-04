"""What the `reels-worker` reads across businesses (ADR 42 §4; slice R8, m-24854855): the
brands opened lately with their timezone, the weekly runs that already exist, the runs
left `running` by a dead process, and the next run to start. It only READS and DECIDES;
every write — enqueue, claim, release, the run itself — goes through
`tenant_session(tenant_id)` in `reel_runs` / `reel_store`.

`ReelQueue` is the seam; `MemoryReelQueue` is the offline twin the tests drive (over
`MemoryReelRunStore`, the same runs `reel_runs` writes), `PostgresReelQueue` the real
one, through the worker's own door `reels_worker_session()` (`qualify_reels_worker`,
NOBYPASSRLS, SELECT of a few columns; 0122 and the door's docstring). This module is the
only one allowed to import that door.

Scope: `tenants=None` is every business (`--all-tenants`, production); a list keeps every
read to those businesses (`--tenant`, local).

The next run: the oldest `queued` one, `manual` and `operator_90d` before `weekly` —
someone who asked for a search is waiting, a Monday run is not. (Today every run is
`weekly`, the first-run of option A included: the button of R9 and the operator's read of
R10 are what will enqueue the others.)
Taking it is `reel_runs.run`'s claim (`queued` → `running`, compare-and-set), so two
workers that pick the same run never both run it: the second gets `ran=False`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

from qualify_api.referentes.reel_schedule import ScheduledBrand, WeeklyDue
from qualify_api.referentes.reel_store import (
    STATUS_QUEUED,
    STATUS_RUNNING,
    TRIGGER_WEEKLY,
    MemoryReelRunStore,
)


@dataclass(frozen=True)
class StaleRun:
    """A run `running` since `started_at` (its claim's fencing token), claimed `attempts`
    times."""

    run_id: UUID
    tenant_id: UUID
    started_at: datetime
    attempts: int


@dataclass(frozen=True)
class NextRun:
    run_id: UUID
    tenant_id: UUID


class ReelQueue:
    """The reads the worker makes across businesses (`MemoryReelQueue`,
    `PostgresReelQueue`)."""

    def opened_brands(self, *, since: datetime) -> list[ScheduledBrand]:
        """The brands opened at or after `since` (`brand_reel_activity`), with their
        tenant's timezone."""
        raise NotImplementedError

    def existing_weekly(self, due: Sequence[WeeklyDue]) -> set[tuple[UUID, date]]:
        """The `(brand_id, run_date)` among `due` that already have a weekly run, in any
        status."""
        raise NotImplementedError

    def stale_runs(self, *, started_before: datetime) -> list[StaleRun]:
        """The runs `running` since before `started_before`, the oldest first."""
        raise NotImplementedError

    def next_run(self) -> NextRun | None:
        """The run to start now (see the module docstring), or None."""
        raise NotImplementedError


def _next_key(trigger: str, queued_at: datetime, run_id: UUID) -> tuple[bool, datetime, str]:
    return (trigger == TRIGGER_WEEKLY, queued_at, str(run_id))


# ======================================================================================
# In memory — the offline twin
# ======================================================================================


class MemoryReelQueue(ReelQueue):
    """`ReelQueue` over a `MemoryReelRunStore` (its runs, `activity` and `timezones`)."""

    def __init__(self, store: MemoryReelRunStore, *, tenants: Sequence[UUID] | None = None):
        self.store = store
        self._scope = frozenset(tenants) if tenants is not None else None

    def _in_scope(self, tenant_id: UUID) -> bool:
        return self._scope is None or tenant_id in self._scope

    def opened_brands(self, *, since: datetime) -> list[ScheduledBrand]:
        return sorted(
            (
                ScheduledBrand(tenant, brand, self.store.timezones[tenant], opened)
                for brand, (tenant, opened) in self.store.activity.items()
                if self._in_scope(tenant) and opened >= since
            ),
            key=lambda b: (str(b.tenant_id), str(b.brand_id)),
        )

    def existing_weekly(self, due: Sequence[WeeklyDue]) -> set[tuple[UUID, date]]:
        wanted = {(d.brand_id, d.run_date) for d in due}
        return {
            (r.brand_id, r.run_date)
            for r in self.store.runs.values()
            if r.trigger == TRIGGER_WEEKLY and (r.brand_id, r.run_date) in wanted
        }

    def stale_runs(self, *, started_before: datetime) -> list[StaleRun]:
        return sorted(
            (
                StaleRun(r.id, r.tenant_id, r.started_at, r.attempts)
                for r in self.store.runs.values()
                if r.status == STATUS_RUNNING
                and self._in_scope(r.tenant_id)
                and r.started_at is not None
                and r.started_at < started_before
            ),
            key=lambda s: (s.started_at, str(s.run_id)),
        )

    def next_run(self) -> NextRun | None:
        queued = [
            r
            for r in self.store.runs.values()
            if r.status == STATUS_QUEUED and self._in_scope(r.tenant_id)
        ]
        if not queued:
            return None
        first = min(queued, key=lambda r: _next_key(r.trigger, r.queued_at, r.id))
        return NextRun(first.id, first.tenant_id)


# ======================================================================================
# Postgres — through the reels-worker's own door
# ======================================================================================


class PostgresReelQueue(ReelQueue):
    """`ReelQueue` through `reels_worker_session()`; every statement names only the
    columns 0122 grants to `qualify_reels_worker`."""

    def __init__(self, *, tenants: Sequence[UUID] | None = None) -> None:
        self._tenants = list(dict.fromkeys(tenants)) if tenants is not None else None
        if self._tenants is not None and not self._tenants:
            raise ValueError("a scoped reels queue needs at least one tenant id")

    def _scoped(self, column: str) -> tuple[str, dict[str, Any]]:
        if self._tenants is None:
            return "", {}
        return f" AND {column} = ANY(:tenants)", {"tenants": self._tenants}

    def _rows(self, sql: str, params: dict[str, Any]) -> list[Any]:
        # Imported on use: the door opens no socket at import, and only this module
        # names it (`test_reels_worker_door_sanctity.py`).
        from qualify_shared.db.reels_worker import reels_worker_session  # noqa: PLC0415

        with reels_worker_session() as session:
            return list(session.execute(text(sql), params).all())

    def opened_brands(self, *, since: datetime) -> list[ScheduledBrand]:
        scope, params = self._scoped("a.tenant_id")
        rows = self._rows(
            "SELECT a.tenant_id, a.brand_id, a.last_opened_at, t.timezone "
            "FROM brand_reel_activity a JOIN tenants t ON t.id = a.tenant_id "
            f"WHERE a.last_opened_at >= :since{scope} ORDER BY a.tenant_id, a.brand_id",
            {"since": since, **params},
        )
        return [
            ScheduledBrand(row.tenant_id, row.brand_id, row.timezone, row.last_opened_at)
            for row in rows
        ]

    def existing_weekly(self, due: Sequence[WeeklyDue]) -> set[tuple[UUID, date]]:
        if not due:
            return set()
        rows = self._rows(
            "SELECT brand_id, run_date FROM brand_reel_runs WHERE trigger = :weekly "
            "AND brand_id = ANY(:brands) AND run_date = ANY(:dates)",
            {
                "weekly": TRIGGER_WEEKLY,
                "brands": sorted({d.brand_id for d in due}, key=str),
                "dates": sorted({d.run_date for d in due}),
            },
        )
        wanted = {(d.brand_id, d.run_date) for d in due}
        return {(r.brand_id, r.run_date) for r in rows if (r.brand_id, r.run_date) in wanted}

    def stale_runs(self, *, started_before: datetime) -> list[StaleRun]:
        scope, params = self._scoped("tenant_id")
        rows = self._rows(
            "SELECT id, tenant_id, started_at, attempts FROM brand_reel_runs "
            f"WHERE status = 'running' AND started_at < :before{scope} "
            "ORDER BY started_at, id",
            {"before": started_before, **params},
        )
        return [StaleRun(r.id, r.tenant_id, r.started_at, r.attempts) for r in rows]

    def next_run(self) -> NextRun | None:
        scope, params = self._scoped("tenant_id")
        rows = self._rows(
            f"SELECT id, tenant_id FROM brand_reel_runs WHERE status = 'queued'{scope} "
            "ORDER BY (trigger = 'weekly'), queued_at, id LIMIT 1",
            params,
        )
        return NextRun(rows[0].id, rows[0].tenant_id) if rows else None


__all__ = [
    "MemoryReelQueue",
    "NextRun",
    "PostgresReelQueue",
    "ReelQueue",
    "StaleRun",
]

"""One tick of the calendar executor (QUA-111): the work known at the start, done once.

`TickRunner.run_once()` is what a runtime (cron, worker, job — not chosen yet) calls
periodically. It never loops, never sleeps and never decides when it runs next; it
returns once the snapshot is processed. The recommended interval between calls is
60 s (`CONTAINER_POLL_INTERVAL_SECONDS`, Meta's poll cadence): each call advances every
in-flight attempt by one step, so the interval IS the poll cadence.

## The tick

1. The runner's `TenantSource` names the tenants — a scoped set (tests, localhost) or
   the production discovery (`discovery.py`), fixed when the runner is built.
2. Per tenant, in its own error boundary, a SNAPSHOT taken at the start of its block
   (each list read through `tenant_session`, RLS-scoped):
   a. `publishing` events linked to an attempt → `executor.progress_event` (F4 + F5);
   b. `publishing` events with no attempt → `executor.start_claimed` (F3 resume);
   c. due `scheduled` events → `executor.try_execute` (F3).
   Only these lists are processed. An event created, claimed or started during the tick
   waits for the next one — so an attempt started in (c) is not polled seconds after its
   upload. There is no transaction around the tick: every operation keeps its own lock
   or compare-and-set (claim CAS, event lock, attempt lock, settlement CAS), which is
   what decides whether a snapshot entry still needs acting on.
3. One event's exception is recorded and the next event runs; one tenant's failure is
   recorded and the next tenant runs. Nothing is retried within a tick.

This module only coordinates: it claims nothing, calls no publisher and settles nothing
by itself.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TypeVar
from uuid import UUID

from qualify_api.planner.discovery import TenantSource
from qualify_api.planner.executor import (
    AdvanceResult,
    EventExecutor,
    ExecutionResult,
    SettleResult,
)
from qualify_api.planner.repository import EventRecord, PlannerRepository

logger = logging.getLogger(__name__)

DEFAULT_LIMIT_PER_TENANT = 100

T = TypeVar("T")


@dataclass
class TenantReport:
    tenant_id: UUID
    advanced: list[tuple[AdvanceResult, SettleResult | None]] = field(default_factory=list)
    resumed: list[ExecutionResult] = field(default_factory=list)
    executed: list[ExecutionResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # "<event_id|snapshot>:<ExceptionType>"

    @property
    def operations(self) -> int:
        return len(self.advanced) + len(self.resumed) + len(self.executed)


@dataclass
class TickReport:
    started_at: datetime
    finished_at: datetime | None = None
    tenants: list[TenantReport] = field(default_factory=list)
    error: str = ""  # the tenant source itself failed: nothing ran


class TickRunner:
    def __init__(
        self,
        *,
        tenants: TenantSource,
        repository: PlannerRepository,
        executor: EventExecutor,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        limit_per_tenant: int = DEFAULT_LIMIT_PER_TENANT,
    ) -> None:
        self._tenants = tenants
        self._repo = repository
        self._executor = executor
        self._clock = clock
        self._limit = limit_per_tenant

    async def run_once(self) -> TickReport:
        now = self._clock()
        report = TickReport(started_at=now)
        try:
            tenant_ids = self._tenants.tenants(now=now)
        except Exception as exc:
            logger.error("calendar.tick_tenants_failed error=%s", type(exc).__name__)
            report.error = type(exc).__name__
            report.finished_at = self._clock()
            return report
        for tenant_id in tenant_ids:
            report.tenants.append(await self._run_tenant(tenant_id, now))
        report.finished_at = self._clock()
        logger.info(
            "calendar.tick tenants=%s operations=%s errors=%s",
            len(report.tenants),
            sum(t.operations for t in report.tenants),
            sum(len(t.errors) for t in report.tenants),
        )
        return report

    async def _run_tenant(self, tenant_id: UUID, now: datetime) -> TenantReport:
        report = TenantReport(tenant_id=tenant_id)
        try:
            in_flight = self._repo.list_in_flight(tenant_id=tenant_id, limit=self._limit)
            due = self._repo.list_due(tenant_id=tenant_id, now=now, limit=self._limit)
        except Exception as exc:
            logger.error(
                "calendar.tick_snapshot_failed tenant_id=%s error=%s",
                tenant_id,
                type(exc).__name__,
            )
            report.errors.append(f"snapshot:{type(exc).__name__}")
            return report
        linked = [e for e in in_flight if e.publish_attempt_id is not None]
        unlinked = [e for e in in_flight if e.publish_attempt_id is None]

        for event in linked:
            await self._each(report, event, report.advanced, self._executor.progress_event)
        for event in unlinked:
            await self._each(report, event, report.resumed, self._executor.start_claimed)
        for event in due:
            await self._each(report, event, report.executed, self._executor.try_execute)
        return report

    async def _each(
        self,
        report: TenantReport,
        event: EventRecord,
        into: list[T],
        step: Callable[[EventRecord], Awaitable[T]],
    ) -> None:
        try:
            into.append(await step(event))
        except Exception as exc:
            logger.error(
                "calendar.tick_event_failed tenant_id=%s event_id=%s error=%s",
                event.tenant_id,
                event.id,
                type(exc).__name__,
            )
            report.errors.append(f"{event.id}:{type(exc).__name__}")

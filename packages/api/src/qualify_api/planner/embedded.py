"""The calendar worker embedded in the app process (QUA-111 follow-up).

QUA-111 shipped the worker as a separate CLI (`python -m qualify_api.planner.worker`)
and left starting it to whoever runs the app. Nobody did, so due events stayed
`scheduled` forever. This module makes the app itself the runtime: the Reflex backend
starts ONE background thread at startup that runs the same `run_worker` loop over the
same `TickRunner` — so "the app is up" means "scheduled publications are being
processed". It adds no new guarantee and needs none: claim CAS, event/attempt advisory
locks and the publisher's idempotency key already make several workers (several app
processes, or the app plus a CLI/cron worker) safe together.

Why a thread with its own event loop, not an asyncio task on the server's loop: the
planner/publishing repositories are synchronous (SQLAlchemy sessions) and a tick can take
seconds (R2 + Meta calls). On the server's loop that would stall every websocket; in its
own thread it stalls nothing.

## Configuration (environment, read once at startup)

- `QUALIFY_CALENDAR_WORKER` — `embedded` (default) runs it in this process; `off` does
  not (use that when a dedicated `python -m qualify_api.planner.worker` runs instead).
- `QUALIFY_CALENDAR_WORKER_TENANTS` — OPTIONAL restriction. Unset, empty or `all` (the
  product default) = discovery: every tenant with a due event on an ACTIVE connection,
  or with a publication in flight (`discovery.DiscoveredTenants`), re-evaluated on every
  tick — so a newly connected account is covered with no configuration and no restart.
  A comma-separated list of tenant UUIDs restricts the worker to exactly those tenants
  (`ScopedTenants`) — a development/testing tool, never how an account gets enabled.
  An invalid value → the worker does not start and says so (log + Planificador).
- `QUALIFY_CALENDAR_WORKER_INTERVAL` — seconds between tick starts (default 60, min 30).

## Recovery of billed BytePlus videos (m-24852492)

Beside the ticks, the same loop runs `creative.vendor_recovery` every
`RECOVERY_EVERY_SECONDS` over the same scope: a Seedance task whose generation thread
went quiet (its wait ran out, or a deploy killed it) is asked to BytePlus by id and, once
ended, its draft is resumed — the video lands in the piece without anyone opening the
app. `QUALIFY_VENDOR_RECOVERY=off` turns it off everywhere;
`QUALIFY_CALENDAR_VENDOR_RECOVERY=off` only here, because `creative-worker` (m-24852163)
runs it — production sets that in `deploy/docker-compose.prod.yml`.

## Crash / restart

All state is in Postgres. If the process dies mid-tick, advisory locks die with its
connections; on the next start the first tick runs immediately and resumes: overdue
`scheduled` events are still due (`scheduled_at <= now`), `publishing` events are resumed
or advanced, and an attempt already started is re-linked by its idempotency key — never
sent twice.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from qualify_api.planner.heartbeat import HeartbeatStore, production_heartbeat_store, record_beat
from qualify_api.planner.tick import TickReport
from qualify_api.planner.worker import (
    DEFAULT_INTERVAL_SECONDS,
    MIN_INTERVAL_SECONDS,
    RECOVERY_EVERY_SECONDS,
    run_worker,
)

logger = logging.getLogger("qualify_api.planner.embedded")

ENV_MODE = "QUALIFY_CALENDAR_WORKER"
ENV_TENANTS = "QUALIFY_CALENDAR_WORKER_TENANTS"
ENV_INTERVAL = "QUALIFY_CALENDAR_WORKER_INTERVAL"
ALL_TENANTS = "all"
_STOP_JOIN_SECONDS = 5.0


class WorkerMode(StrEnum):
    EMBEDDED = "embedded"
    OFF = "off"


@dataclass(frozen=True)
class EmbeddedWorkerConfig:
    mode: WorkerMode
    all_tenants: bool = False
    tenant_ids: tuple[UUID, ...] = ()
    interval: int = DEFAULT_INTERVAL_SECONDS
    problem: str = ""  # why an `embedded` config cannot start; "" when it can

    @property
    def startable(self) -> bool:
        return self.mode is WorkerMode.EMBEDDED and not self.problem

    def covers(self, tenant_id: UUID) -> bool:
        return self.startable and (self.all_tenants or tenant_id in self.tenant_ids)

    @property
    def scope_label(self) -> str:
        return ALL_TENANTS if self.all_tenants else ",".join(str(t) for t in self.tenant_ids)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> EmbeddedWorkerConfig:
        env = os.environ if env is None else env
        raw_mode = env.get(ENV_MODE, "").strip().lower() or WorkerMode.EMBEDDED.value
        try:
            mode = WorkerMode(raw_mode)
        except ValueError:
            return cls(WorkerMode.EMBEDDED, problem=f"{ENV_MODE}={raw_mode!r} is not valid")
        if mode is WorkerMode.OFF:
            return cls(mode)

        interval = DEFAULT_INTERVAL_SECONDS
        raw_interval = env.get(ENV_INTERVAL, "").strip()
        if raw_interval:
            try:
                interval = int(raw_interval)
            except ValueError:
                return cls(mode, problem=f"{ENV_INTERVAL}={raw_interval!r} is not an integer")
            if interval < MIN_INTERVAL_SECONDS:
                return cls(mode, problem=f"{ENV_INTERVAL} must be >= {MIN_INTERVAL_SECONDS}")

        raw_scope = env.get(ENV_TENANTS, "").strip()
        if not raw_scope or raw_scope.lower() == ALL_TENANTS:
            return cls(mode, all_tenants=True, interval=interval)
        try:
            ids = tuple(
                dict.fromkeys(UUID(part.strip()) for part in raw_scope.split(",") if part.strip())
            )
        except ValueError:
            return cls(mode, interval=interval, problem=f"{ENV_TENANTS} has an invalid UUID")
        if not ids:
            return cls(mode, interval=interval, problem=f"{ENV_TENANTS} lists no tenant")
        return cls(mode, tenant_ids=ids, interval=interval)


@dataclass(frozen=True)
class WorkerStatus:
    config: EmbeddedWorkerConfig
    running: bool
    last_tick_at: datetime | None
    last_tick_error: str

    def covers(self, tenant_id: UUID) -> bool:
        return self.running and self.config.covers(tenant_id)


class _RecordingRunner:
    """Wraps the real runner to remember when the last tick finished, for the status."""

    def __init__(self, inner, on_tick: Callable[[TickReport | None, str], None]) -> None:
        self._inner = inner
        self._on_tick = on_tick

    async def run_once(self) -> TickReport:
        try:
            report = await self._inner.run_once()
        except Exception as exc:
            self._on_tick(None, type(exc).__name__)
            raise
        self._on_tick(report, report.error)
        return report


class EmbeddedCalendarWorker:
    """One background thread running `run_worker` until `stop()`."""

    def __init__(
        self,
        config: EmbeddedWorkerConfig,
        *,
        make_runner: Callable[[], object] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        heartbeat: HeartbeatStore | None = None,
        sidecar: Callable[[], object] | None = None,
    ) -> None:
        self._sidecar = sidecar
        self._config = config
        self._heartbeat = heartbeat
        self._make_runner = make_runner
        self._clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_tick_at: datetime | None = None
        self._last_tick_error = ""

    @property
    def config(self) -> EmbeddedWorkerConfig:
        return self._config

    def status(self) -> WorkerStatus:
        running = self._thread is not None and self._thread.is_alive()
        return WorkerStatus(self._config, running, self._last_tick_at, self._last_tick_error)

    def start(self) -> bool:
        """Start the thread if the config allows it. Returns whether it is running."""
        if self._config.mode is WorkerMode.OFF:
            logger.info("calendar.embedded.off — a dedicated worker must run elsewhere")
            return False
        if self._config.problem:
            logger.warning(
                "calendar.embedded.not_started problem=%s — scheduled posts will NOT be "
                "published by this process",
                self._config.problem,
            )
            return False
        if self._thread is not None and self._thread.is_alive():
            return True
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="qualify-calendar-worker", daemon=True
        )
        self._thread.start()
        logger.info(
            "calendar.embedded.started scope=%s interval=%ss",
            self._config.scope_label,
            self._config.interval,
        )
        return True

    def stop(self, timeout: float = _STOP_JOIN_SECONDS) -> None:
        self._stop.set()
        if self._thread is not None:
            # A tick in progress finishes first (it may be mid-Meta call); the thread is a
            # daemon, so a slow tick never blocks shutdown beyond `timeout`.
            self._thread.join(timeout)
        logger.info("calendar.embedded.stopped")

    # -- thread body ------------------------------------------------------------------

    def _record(self, report: TickReport | None, error: str) -> None:
        self._last_tick_at = self._clock()
        self._last_tick_error = error
        record_beat(
            self._heartbeat,
            all_tenants=self._config.all_tenants,
            tenant_ids=self._config.tenant_ids,
            interval=self._config.interval,
            error=error,
            now=self._last_tick_at,
        )

    def _build_runner(self):
        if self._make_runner is not None:
            inner = self._make_runner()
        else:
            from qualify_api.planner.composition import (  # noqa: PLC0415 — heavy, lazy
                production_tick_runner,
                scoped_tick_runner,
            )

            inner = (
                production_tick_runner()
                if self._config.all_tenants
                else scoped_tick_runner(self._config.tenant_ids)
            )
        return _RecordingRunner(inner, self._record)

    async def _sleep(self, seconds: float) -> None:
        # This loop only ever runs the worker, so blocking it is fine; waking on the
        # stop event is what makes shutdown prompt instead of up to `interval` late.
        self._stop.wait(seconds)

    def _recovery(self) -> Callable[[], object] | None:
        """m-24852492: the recovery of billed BytePlus videos runs beside the ticks, over
        the same scope — production wiring only (an injected runner means a test)."""
        if self._make_runner is not None:
            return self._sidecar
        from qualify_api.creative.vendor_recovery import (  # noqa: PLC0415
            recovery_chore,
            runs_in_calendar_worker,
        )

        if not runs_in_calendar_worker():  # m-24852163: creative-worker runs it instead
            return None
        return recovery_chore(None if self._config.all_tenants else self._config.tenant_ids)

    def _retention_retries(self) -> Callable[[], object] | None:
        if self._make_runner is not None:
            return None  # injected runner is an offline test, not a production worker
        from qualify_api.creative.retention_job import warning_retry_chore

        scope = None if self._config.all_tenants else self._config.tenant_ids
        return warning_retry_chore(scope)

    def _run(self) -> None:
        try:
            asyncio.run(
                run_worker(
                    self._build_runner,
                    once=False,
                    interval=self._config.interval,
                    sleep=self._sleep,
                    should_stop=self._stop.is_set,
                    sidecar=self._recovery(),
                    sidecar_every=RECOVERY_EVERY_SECONDS,
                    retry_chore=self._retention_retries(),
                )
            )
        except Exception:
            logger.exception("calendar.embedded.crashed")


_instance: EmbeddedCalendarWorker | None = None
_instance_lock = threading.Lock()


def calendar_worker() -> EmbeddedCalendarWorker:
    """The process-wide worker, configured from the environment on first use."""
    global _instance
    with _instance_lock:
        if _instance is None:
            config = EmbeddedWorkerConfig.from_env()
            _instance = EmbeddedCalendarWorker(
                config, heartbeat=production_heartbeat_store() if config.startable else None
            )
        return _instance

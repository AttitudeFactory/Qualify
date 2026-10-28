"""Automatic explicit-consent erasure every fifteen minutes (m-24789547).

Production: --all-tenants --execute. Local use requires --tenant UUID; omitting
--execute previews due work. No new intent is created here. The existing engine
owns grace, cancellation, durable retries, row fences and webhook/R2 boundaries.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from qualify_shared.db.config import connection_purge_dsn
from qualify_shared.db.connection_purge import (
    connection_purge_session,
    discover_due_purge_tenants,
)
from qualify_shared.objects.gate import ObjectGate
from sqlalchemy import text
from sqlalchemy.engine import make_url

from qualify_api.connections.purge import ConnectionPurgeBusy, PurgeBlocked, purge_connection

logger = logging.getLogger(__name__)
INTERVAL = 15 * 60
HEARTBEAT_PATH = Path(tempfile.gettempdir()) / "qualify-connection-purge.json"
DISCOVERY_BATCH = 100
DEADLINE_WARNING = timedelta(hours=6)


@dataclass(frozen=True)
class DueJob:
    connection_id: UUID
    deadline_at: datetime


@dataclass
class TickReport:
    tenants: int = 0
    attempted: int = 0
    completed: int = 0
    failed: int = 0
    urgent: int = 0
    pending: int = 0


class PurgeRepository:
    def discover(self, now: datetime, after: UUID | None) -> list[UUID]:
        return discover_due_purge_tenants(now=now, after=after, limit=DISCOVERY_BATCH)

    def due(self, tenant_id: UUID, now: datetime, limit: int) -> list[DueJob]:
        with connection_purge_session(tenant_id) as session:
            rows = session.execute(
                text("""SELECT connection_id,deadline_at FROM connection_purge_requests
                WHERE tenant_id=:tid AND status IN ('scheduled','running') AND due_at<=:now
                ORDER BY scheduler_attempted_at NULLS FIRST,deadline_at,connection_id
                LIMIT :limit"""),
                {"tid": tenant_id, "now": now, "limit": limit},
            ).all()
            return [DueJob(row.connection_id, row.deadline_at) for row in rows]

    def mark_attempt(self, tenant_id: UUID, connection_id: UUID, now: datetime) -> None:
        # Committed before the engine: even a manifest/DB failure rotates behind other
        # due requests next time. Retries cannot permanently occupy the first batch.
        with connection_purge_session(tenant_id) as session:
            session.execute(
                text("""UPDATE connection_purge_requests SET scheduler_attempted_at=:now
                WHERE tenant_id=:tid AND connection_id=:cid
                  AND status IN ('scheduled','running') AND due_at<=:now"""),
                {"tid": tenant_id, "cid": connection_id, "now": now},
            )

    def outstanding(self, tenant_id: UUID, now: datetime) -> tuple[int, int]:
        with connection_purge_session(tenant_id) as session:
            row = session.execute(
                text("""SELECT count(*) AS pending,
                    count(*) FILTER (WHERE deadline_at<=:warning) AS urgent
                FROM connection_purge_requests
                WHERE tenant_id=:tid AND status IN ('scheduled','running') AND due_at<=:now"""),
                {"tid": tenant_id, "now": now, "warning": now + DEADLINE_WARNING},
            ).one()
            return row.pending, row.urgent


class PurgeRunner:
    def __init__(
        self,
        *,
        tenants: Sequence[UUID] | None,
        execute: bool,
        limit: int = 100,
        objects: ObjectGate | None = None,
        repository: PurgeRepository | None = None,
        purge: Callable[..., object] = purge_connection,
    ) -> None:
        self.tenants = list(dict.fromkeys(tenants)) if tenants is not None else None
        self.execute = execute
        self.limit = limit
        self.objects = objects
        self.repository = repository or PurgeRepository()
        self.purge = purge

    def run_once(
        self, *, now: datetime | None = None, should_stop: Callable[[], bool] = lambda: False
    ) -> TickReport:
        moment = now or datetime.now(UTC)
        report = TickReport()
        after: UUID | None = None
        while not should_stop():
            # Discovery failure aborts this pass and makes the heartbeat unhealthy.
            # A tenant failure below never prevents processing the next tenant.
            tenants = (
                self.tenants
                if self.tenants is not None
                else self.repository.discover(moment, after)
            )
            for tenant_id in tenants:
                if should_stop():
                    return report
                report.tenants += 1
                try:
                    self._tenant(tenant_id, moment, report, should_stop)
                except Exception as exc:
                    report.failed += 1
                    logger.error(
                        "connection_purge.tenant_failed tenant=%s error=%s",
                        tenant_id,
                        type(exc).__name__,
                    )
            if self.tenants is not None or len(tenants) < DISCOVERY_BATCH:
                break
            after = tenants[-1]
        logger.info("connection_purge.tick %s", vars(report))
        return report

    def _tenant(
        self,
        tenant_id: UUID,
        now: datetime,
        report: TickReport,
        should_stop: Callable[[], bool],
    ) -> None:
        for job in self.repository.due(tenant_id, now, self.limit):
            if should_stop():
                return
            if not self.execute:
                logger.info(
                    "connection_purge.dry_run tenant=%s connection=%s deadline=%s",
                    tenant_id,
                    job.connection_id,
                    job.deadline_at.isoformat(),
                )
                continue
            report.attempted += 1
            try:
                self.repository.mark_attempt(tenant_id, job.connection_id, now)
                result = self.purge(
                    tenant_id=tenant_id,
                    connection_id=job.connection_id,
                    objects=self.objects,
                    now=now,
                )
                if result.status == "completed":
                    report.completed += 1
                logger.info(
                    "connection_purge.result tenant=%s connection=%s status=%s",
                    tenant_id,
                    job.connection_id,
                    result.status,
                )
            except ConnectionPurgeBusy:
                logger.info(
                    "connection_purge.busy tenant=%s connection=%s", tenant_id, job.connection_id
                )
            except Exception as exc:
                report.failed += 1
                code = str(exc) if isinstance(exc, PurgeBlocked) else type(exc).__name__
                logger.error(
                    "connection_purge.retry tenant=%s connection=%s error=%s deadline=%s",
                    tenant_id,
                    job.connection_id,
                    code,
                    job.deadline_at.isoformat(),
                )
        pending, urgent = self.repository.outstanding(tenant_id, now)
        report.pending += pending
        report.urgent += urgent
        if urgent:
            logger.error(
                "connection_purge.deadline_alert tenant=%s due=%s deadline_within_6h_or_overdue=%s",
                tenant_id,
                pending,
                urgent,
            )
        elif pending:
            logger.warning("connection_purge.pending tenant=%s due=%s", tenant_id, pending)


def configured() -> bool:
    """Compose builds an empty-password DSN when the optional secret is absent."""
    if os.environ.get("QUALIFY_DEPLOY_ENV") == "production" and not os.environ.get(
        "QUALIFY_CONNECTION_PURGE_DSN"
    ):
        return False
    try:
        return bool(make_url(connection_purge_dsn()).password)
    except Exception:
        return False


def write_heartbeat(path: Path, *, status: str, interval: int, **counts: int) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"at": time.time(), "status": status, "interval": interval, **counts}),
        encoding="utf-8",
    )
    temporary.replace(path)


def healthcheck(path: Path = HEARTBEAT_PATH) -> int:
    try:
        beat = json.loads(path.read_text(encoding="utf-8"))
        age = time.time() - beat["at"]
        if not 0 <= age <= beat["interval"] + 300:
            return 1
        # Inactive is explicit and deployment-compatible before the role secret is staged.
        # `--once` instead returns 2 so a disabled scheduled invocation cannot report success.
        return 0 if beat["status"] in {"ok", "inactive"} else 1
    except (OSError, ValueError, KeyError, TypeError):
        return 1


def run_worker(
    runner: PurgeRunner,
    *,
    once: bool,
    interval: int = INTERVAL,
    stop: threading.Event | None = None,
    heartbeat_path: Path = HEARTBEAT_PATH,
    is_configured: Callable[[], bool] = configured,
    max_ticks: int | None = None,
) -> int:
    shutdown = stop if stop is not None else threading.Event()
    ticks = 0
    inactive_logged = False
    while not shutdown.is_set():
        started = time.monotonic()
        if not is_configured():
            if not inactive_logged:
                logger.warning("connection_purge.inactive reason=missing_role_password")
                inactive_logged = True
            write_heartbeat(heartbeat_path, status="inactive", interval=interval)
            code = 2
        else:
            try:
                report = runner.run_once(should_stop=shutdown.is_set)
                code = 1 if report.failed or report.urgent else 0
                write_heartbeat(
                    heartbeat_path,
                    status="error" if code else "ok",
                    interval=interval,
                    **vars(report),
                )
            except Exception as exc:
                code = 1
                logger.error("connection_purge.tick_failed error=%s", type(exc).__name__)
                write_heartbeat(heartbeat_path, status="error", interval=interval)
        ticks += 1
        if once:
            return code
        if max_ticks is not None and ticks >= max_ticks:
            return 0
        shutdown.wait(max(0, interval - (time.monotonic() - started)))
    logger.info("connection_purge.stopped")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--healthcheck", action="store_true")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--tenant", action="append", type=UUID)
    scope.add_argument("--all-tenants", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--interval", type=int, default=INTERVAL)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args(argv)
    if args.healthcheck:
        return healthcheck()
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[5] / ".env", override=False)
    if not args.tenant and not args.all_tenants:
        parser.error("explicit scope required: --tenant UUID (local) or --all-tenants (production)")
    if args.all_tenants and os.environ.get("QUALIFY_DEPLOY_ENV") != "production":
        parser.error("--all-tenants requires QUALIFY_DEPLOY_ENV=production; use --tenant locally")
    if not 60 <= args.interval <= INTERVAL:
        parser.error("--interval must be between 60 and 900 seconds")
    if not 1 <= args.limit <= 1000:
        parser.error("--limit must be between 1 and 1000")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    shutdown = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: shutdown.set())
    logger.info(
        "connection_purge.start scope=%s execute=%s interval=%s limit_per_tenant=%s",
        "all-tenants" if args.all_tenants else ",".join(map(str, args.tenant)),
        args.execute,
        args.interval,
        args.limit,
    )
    return run_worker(
        PurgeRunner(tenants=args.tenant, execute=args.execute, limit=args.limit),
        once=args.once,
        interval=args.interval,
        stop=shutdown,
    )


if __name__ == "__main__":
    raise SystemExit(main())

"""The WhatsApp worker (WA-08): the process that drains `whatsapp_outbox` periodically.

    python -m qualify_api.whatsapp.worker --tenant <uuid> [--tenant <uuid> ...] [--once]
    python -m qualify_api.whatsapp.worker --all-tenants [--once] [--interval 5]

(`just whatsapp-tick …` runs one pass, `just whatsapp-worker …` keeps running.)

Each pass is `OutboxSender.run_once(tenant_id)` per tenant in scope — claim → window →
pacing → send → settle, with every guarantee the sender already carries (`SKIP LOCKED`
claim, status-guarded settles, `uq_message_external_id`). This module adds only WHEN and
FOR WHOM: it never sends, claims or settles by itself. Same mould as
`planner/worker.py` (QUA-111), and the SAME warning:

Scope is MANDATORY and explicit — there is no default that means "everyone":
- `--tenant <uuid>` (repeatable): exactly those tenants, no cross-tenant read. Use it
  locally: a development database holds test tenants a production pass would act on.
- `--all-tenants`: the production discovery (`DiscoveredTenants`, below).

Modes:
- `--once`: one pass, then exit (0, or 1 if the pass could not even list its tenants).
- default: a pass every `--interval` seconds (5 by default — a reply should leave within
  seconds of being written; at least 1), measured start-to-start, until SIGINT/Ctrl+C.

ADR 48 (m-25017356): the same process also drains the WhatsApp catalog uploads
(`catalog_sync/worker.py`, `CatalogSyncTick`) as a SEPARATE asyncio task every
`--catalog-interval` seconds (30 by default; `0` turns it off), so a slow Meta catalog call
never holds up the outbox. `--once` runs one outbox pass, then one catalog pass. No new
service and no compose change.

## Why discovery reads `whatsapp_phone_numbers`, not the outbox

`qualify_admin` holds SELECT on `whatsapp_phone_numbers` and NOT on `whatsapp_outbox`
(0057's grant table, pinned cell by cell by `test_whatsapp_schema_db.py`). So the
cross-tenant read that finds work cannot look at the queue itself; it lists the tenants
that have a WhatsApp number connected — ids only, read-only, the same narrow terms
`planner/discovery.py` sets — and each tenant's claim then runs through
`tenant_session(tenant_id)`, where an empty queue costs one indexed probe
(`ix_wa_outbox_claim`). A tenant without a number has no outbox to drain.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import socket
import time
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select

from qualify_api.whatsapp.outbox import DEFAULT_BATCH, SendReport

logger = logging.getLogger("qualify_api.whatsapp.worker")

DEFAULT_INTERVAL_SECONDS = 5
MIN_INTERVAL_SECONDS = 1
DEFAULT_CATALOG_INTERVAL_SECONDS = 30


def worker_id() -> str:
    """The lock holder written to `whatsapp_outbox.locked_by` (same shape as the webhook
    processor's)."""
    return f"{socket.gethostname()}:{os.getpid()}"


# --- which tenants ------------------------------------------------------------------------


class TenantSource(Protocol):
    def tenants(self, *, now: datetime) -> list[UUID]: ...


class ScopedTenants:
    """A fixed, non-empty set of tenants. No cross-tenant read ever happens."""

    def __init__(self, tenant_ids: Iterable[UUID]) -> None:
        self._tenant_ids = tuple(dict.fromkeys(tenant_ids))
        if not self._tenant_ids:
            raise ValueError("a scoped pass needs at least one tenant id")

    def tenants(self, *, now: datetime) -> list[UUID]:
        return list(self._tenant_ids)


class DiscoveredTenants:
    """Every tenant with a connected WhatsApp number — ids only, via `admin_session`
    (see the module docstring for why not the outbox). Only the production composition
    builds it."""

    def tenants(self, *, now: datetime) -> list[UUID]:
        from qualify_shared.db.admin import admin_session  # noqa: PLC0415

        from qualify_api.whatsapp.models import WhatsAppPhoneNumber  # noqa: PLC0415

        with admin_session() as session:
            return list(
                session.scalars(
                    select(WhatsAppPhoneNumber.tenant_id)
                    .distinct()
                    .order_by(WhatsAppPhoneNumber.tenant_id)
                )
            )


# --- one pass -----------------------------------------------------------------------------


@dataclass
class TickReport:
    started_at: datetime
    tenants: list[SendReport] = field(default_factory=list)
    error: str = ""  # set only when the pass could not list its tenants


class _Sender(Protocol):
    async def run_once(self, tenant_id: UUID, *, limit: int = DEFAULT_BATCH) -> SendReport: ...


class OutboxTick:
    """One pass over the tenants in scope. A tenant whose pass raises is reported and
    the next tenant still runs; only a failure to LIST tenants fails the pass."""

    def __init__(
        self,
        *,
        tenants: TenantSource,
        sender: _Sender,
        limit: int = DEFAULT_BATCH,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._tenants = tenants
        self._sender = sender
        self._limit = limit
        self._clock = clock

    async def run_once(self) -> TickReport:
        now = self._clock()
        report = TickReport(started_at=now)
        try:
            tenant_ids = self._tenants.tenants(now=now)
        except Exception as exc:  # noqa: BLE001 — reported, the loop goes on
            logger.exception("whatsapp.worker.discovery_failed")
            report.error = type(exc).__name__
            return report
        for tenant_id in tenant_ids:
            try:
                report.tenants.append(await self._sender.run_once(tenant_id, limit=self._limit))
            except Exception as exc:  # noqa: BLE001 — one tenant must not stop the others
                logger.exception("whatsapp.worker.tenant_failed tenant_id=%s", tenant_id)
                report.tenants.append(SendReport(tenant_id=tenant_id, errors=[type(exc).__name__]))
        return report


class _Runner(Protocol):
    async def run_once(self) -> TickReport: ...


# --- production wiring --------------------------------------------------------------------


def scoped_outbox_tick(tenant_ids: Iterable[UUID], *, limit: int = DEFAULT_BATCH) -> OutboxTick:
    """A pass over EXACTLY these tenants, on the real sender — localhost validation."""
    from qualify_api.whatsapp.outbox import production_outbox_sender  # noqa: PLC0415

    return OutboxTick(
        tenants=ScopedTenants(tenant_ids),
        sender=production_outbox_sender(worker_id=worker_id()),
        limit=limit,
    )


def production_outbox_tick(*, limit: int = DEFAULT_BATCH) -> OutboxTick:
    """The PRODUCTION pass: every tenant with a WhatsApp number. The one place
    multi-tenant discovery is switched on — do not run it against a database that holds
    test tenants."""
    from qualify_api.whatsapp.outbox import production_outbox_sender  # noqa: PLC0415

    return OutboxTick(
        tenants=DiscoveredTenants(),
        sender=production_outbox_sender(worker_id=worker_id()),
        limit=limit,
    )


# --- CLI ----------------------------------------------------------------------------------


def _load_dotenv() -> None:
    """Same convention as the planner and webhook workers: the repo-root `.env`, never
    overriding what the environment already sets."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(Path(__file__).resolve().parents[5] / ".env", override=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m qualify_api.whatsapp.worker",
        description="Drain the WhatsApp outbox (WA-08) once or periodically.",
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument(
        "--tenant",
        dest="tenants",
        action="append",
        type=UUID,
        metavar="UUID",
        help="Only this tenant (repeatable). Use this locally.",
    )
    scope.add_argument(
        "--all-tenants",
        action="store_true",
        help="Every tenant with a WhatsApp number (production discovery).",
    )
    parser.add_argument("--once", action="store_true", help="Run one pass and exit.")
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL_SECONDS,
        help=f"Seconds between pass starts (default {DEFAULT_INTERVAL_SECONDS}, "
        f"minimum {MIN_INTERVAL_SECONDS}).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_BATCH,
        help=f"Rows claimed per tenant per pass (default {DEFAULT_BATCH}).",
    )
    parser.add_argument(
        "--catalog-interval",
        type=int,
        default=DEFAULT_CATALOG_INTERVAL_SECONDS,
        help="Seconds between WhatsApp catalog upload passes (ADR 48; default "
        f"{DEFAULT_CATALOG_INTERVAL_SECONDS}, 0 = off).",
    )
    return parser


def _log_report(report: TickReport) -> None:
    for tenant in report.tenants:
        if tenant.claimed or tenant.errors:
            logger.info(
                "whatsapp.worker.tenant tenant_id=%s claimed=%d sent=%d deferred=%d retried=%d "
                "failed=%d dead=%d errors=%d",
                tenant.tenant_id,
                tenant.claimed,
                tenant.sent,
                tenant.deferred,
                tenant.retried,
                tenant.failed,
                tenant.dead,
                len(tenant.errors),
            )
    claimed = sum(t.claimed for t in report.tenants)
    if claimed or report.error:
        logger.info(
            "whatsapp.worker.pass tenants=%d claimed=%d sent=%d tick_error=%s",
            len(report.tenants),
            claimed,
            sum(t.sent for t in report.tenants),
            report.error or "none",
        )


async def run_worker(
    make_runner: Callable[[], _Runner],
    *,
    once: bool,
    interval: int = DEFAULT_INTERVAL_SECONDS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
    max_ticks: int | None = None,
    should_stop: Callable[[], bool] = lambda: False,
) -> int:
    """Pass, then wait until `interval` seconds after that pass STARTED, then pass again.
    The runner is built once, after `.env` is loaded. `max_ticks` exists for tests."""
    runner = make_runner()
    ticks = 0
    while not should_stop():
        started = clock()
        report: TickReport | None = None
        try:
            report = await runner.run_once()
            _log_report(report)
        except Exception:  # noqa: BLE001 — log and keep going
            logger.exception("whatsapp.worker.pass_failed")
        ticks += 1
        if once:
            return 0 if report is not None and not report.error else 1
        if max_ticks is not None and ticks >= max_ticks:
            return 0
        await sleep(max(0.0, interval - (clock() - started)))
    return 0


class _CatalogRunner(Protocol):
    async def run_once(self) -> Any: ...


async def run_catalog_loop(
    make_runner: Callable[[], _CatalogRunner],
    *,
    once: bool,
    interval: int = DEFAULT_CATALOG_INTERVAL_SECONDS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
    max_ticks: int | None = None,
    should_stop: Callable[[], bool] = lambda: False,
) -> int:
    """The catalog task: same cadence rules as `run_worker`, its own interval. A failing
    pass is logged and the loop goes on; it never touches the outbox loop."""
    from qualify_api.whatsapp.catalog_sync.worker import log_report  # noqa: PLC0415

    try:
        runner = make_runner()
    except Exception:  # noqa: BLE001 — a catalog misconfiguration must not stop the outbox
        logger.exception("whatsapp.catalog.start_failed")
        return 1
    ticks = 0
    while not should_stop():
        started = clock()
        error = "pass_failed"
        try:
            report = await runner.run_once()
            log_report(report)
            error = getattr(report, "error", "")
        except Exception:  # noqa: BLE001 — log and keep going
            logger.exception("whatsapp.catalog.pass_failed")
        ticks += 1
        if once:
            return 0 if not error else 1
        if max_ticks is not None and ticks >= max_ticks:
            return 0
        await sleep(max(0.0, interval - (clock() - started)))
    return 0


async def _run_all(
    make_runner: Callable[[], _Runner],
    make_catalog: Callable[[], _CatalogRunner] | None,
    *,
    once: bool,
    interval: int,
    catalog_interval: int,
) -> int:
    if make_catalog is None or catalog_interval == 0:
        return await run_worker(make_runner, once=once, interval=interval)
    if once:
        outbox = await run_worker(make_runner, once=True, interval=interval)
        catalog = await run_catalog_loop(make_catalog, once=True, interval=catalog_interval)
        return max(outbox, catalog)
    results = await asyncio.gather(
        run_worker(make_runner, once=False, interval=interval),
        run_catalog_loop(make_catalog, once=False, interval=catalog_interval),
    )
    return max(results)


def main(
    argv: Sequence[str] | None = None,
    *,
    scoped: Callable[[Iterable[UUID]], _Runner] | None = None,
    production: Callable[[], _Runner] | None = None,
    catalog_scoped: Callable[[Iterable[UUID]], _CatalogRunner] | None = None,
    catalog_production: Callable[[], _CatalogRunner] | None = None,
) -> int:
    """`scoped`/`production` build the outbox runner, `catalog_*` the catalog runner. When
    a test injects the outbox runners and not the catalog ones, the catalog task is off:
    a test never builds the real catalog tick by accident."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.interval < MIN_INTERVAL_SECONDS:
        parser.error(f"--interval must be at least {MIN_INTERVAL_SECONDS} second(s)")
    if args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.catalog_interval < 0:
        parser.error("--catalog-interval must be 0 (off) or more")
    _load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    injected = scoped is not None or production is not None
    limit = args.limit
    scoped = scoped or (lambda tenant_ids: scoped_outbox_tick(tenant_ids, limit=limit))
    production = production or (lambda: production_outbox_tick(limit=limit))
    if not injected:
        from qualify_api.whatsapp.catalog_sync.worker import (  # noqa: PLC0415
            production_catalog_tick,
            scoped_catalog_tick,
        )

        catalog_scoped = catalog_scoped or (
            lambda tenant_ids: scoped_catalog_tick(list(tenant_ids), worker_id=worker_id())
        )
        catalog_production = catalog_production or (
            lambda: production_catalog_tick(worker_id=worker_id())
        )

    make_catalog: Callable[[], _CatalogRunner] | None
    if args.all_tenants:
        make_runner: Callable[[], _Runner] = production
        make_catalog = catalog_production
        scope = "all-tenants"
    else:
        tenant_ids = list(dict.fromkeys(args.tenants))
        make_runner = lambda: scoped(tenant_ids)  # noqa: E731
        make_catalog = (lambda: catalog_scoped(tenant_ids)) if catalog_scoped is not None else None
        scope = ",".join(str(t) for t in tenant_ids)
    logger.info(
        "whatsapp.worker.start scope=%s mode=%s interval=%ss limit=%d catalog_interval=%s",
        scope,
        "once" if args.once else "loop",
        args.interval,
        limit,
        f"{args.catalog_interval}s" if make_catalog and args.catalog_interval else "off",
    )
    try:
        return asyncio.run(
            _run_all(
                make_runner,
                make_catalog,
                once=args.once,
                interval=args.interval,
                catalog_interval=args.catalog_interval,
            )
        )
    except KeyboardInterrupt:
        logger.info("whatsapp.worker.stopped")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

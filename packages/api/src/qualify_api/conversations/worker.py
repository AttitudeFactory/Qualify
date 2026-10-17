"""The Conversaciones worker (QUA-226, E5): the process that drains `conversation_outbox`
and, when asked, runs the reconciliation poll of every active Instagram connection.

    python -m qualify_api.conversations.worker --tenant <uuid> [--once] [--sync]
    python -m qualify_api.conversations.worker --all-tenants [--once] [--sync]

(`just conversations-tick …` runs one pass, `just conversations-worker …` keeps running,
`just conversations-sync …` is one pass of the poll only.)

Each pass is, per tenant in scope: [the poll, if `--sync`: `ConversationSyncService.
sync_connection` on each active Instagram connection, at most every `--sync-interval`
seconds] then `ConversationOutboxSender.run_once(tenant_id)`. Same mould and the SAME
warning as `whatsapp/worker.py` and `planner/worker.py`:

Scope is MANDATORY and explicit — there is no default that means "everyone":
- `--tenant <uuid>` (repeatable): exactly those tenants. Use it locally: a development
  database holds test tenants a production pass would act on.
- `--all-tenants`: the production discovery (`DiscoveredTenants`: every tenant with an
  active Instagram connection, ids only, through `admin_session` — `qualify_admin` holds
  SELECT on `social_connections` (0002) and nothing on the outbox).

In `memory` mode (`QUALIFY_CONVERSATIONS_DM_CHANNEL=memory`) the sender "delivers" to the
in-memory pair and the poll reads the seeded conversations: nothing reaches Instagram.
`--sync` against the real pair spends Meta calls — the development-mode budget is 200
calls per hour per Page/app pair (QUA-20), hence the default `--sync-interval` of 300 s.
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
from typing import Protocol
from uuid import UUID

from qualify_api.conversations.outbox import DEFAULT_BATCH
from qualify_api.conversations.sender import SendReport
from qualify_api.conversations.sync import SyncReport

logger = logging.getLogger("qualify_api.conversations.worker")

DEFAULT_INTERVAL_SECONDS = 5
DEFAULT_SYNC_INTERVAL_SECONDS = 300
MIN_INTERVAL_SECONDS = 1


def worker_id() -> str:
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
    """Every tenant with an active Instagram connection — ids only, via `admin_session`.
    Only the production composition builds it."""

    def tenants(self, *, now: datetime) -> list[UUID]:
        from qualify_shared.db.admin import admin_session  # noqa: PLC0415
        from sqlalchemy import select  # noqa: PLC0415

        from qualify_api.connections.models import SocialConnection  # noqa: PLC0415
        from qualify_api.conversations.composition import (  # noqa: PLC0415
            PLATFORM_INSTAGRAM,
            STATUS_ACTIVE,
        )

        with admin_session() as session:
            return list(
                session.scalars(
                    select(SocialConnection.tenant_id)
                    .where(
                        SocialConnection.platform == PLATFORM_INSTAGRAM,
                        SocialConnection.status == STATUS_ACTIVE,
                    )
                    .distinct()
                    .order_by(SocialConnection.tenant_id)
                )
            )


# --- one pass -----------------------------------------------------------------------------


@dataclass
class TenantPass:
    tenant_id: UUID
    sync: list[SyncReport] = field(default_factory=list)
    send: SendReport | None = None
    errors: list[str] = field(default_factory=list)


@dataclass
class TickReport:
    started_at: datetime
    tenants: list[TenantPass] = field(default_factory=list)
    error: str = ""  # set only when the pass could not list its tenants


class _Sender(Protocol):
    async def run_once(self, tenant_id: UUID, *, limit: int = DEFAULT_BATCH) -> SendReport: ...


class _Syncer(Protocol):
    async def __call__(self, tenant_id: UUID) -> list[SyncReport]: ...


class ConversationsTick:
    """One pass over the tenants in scope. A tenant whose pass raises is reported and
    the next tenant still runs; only a failure to LIST tenants fails the pass. The poll
    runs at most every `sync_interval` seconds per tenant (None = never)."""

    def __init__(
        self,
        *,
        tenants: TenantSource,
        sender: _Sender,
        syncer: _Syncer | None = None,
        sync_interval: float | None = None,
        limit: int = DEFAULT_BATCH,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._tenants = tenants
        self._sender = sender
        self._syncer = syncer
        self._sync_interval = sync_interval
        self._limit = limit
        self._clock = clock
        self._monotonic = monotonic
        self._last_sync: dict[UUID, float] = {}

    def _sync_due(self, tenant_id: UUID) -> bool:
        if self._syncer is None or self._sync_interval is None:
            return False
        last = self._last_sync.get(tenant_id)
        return last is None or self._monotonic() - last >= self._sync_interval

    async def run_once(self) -> TickReport:
        now = self._clock()
        report = TickReport(started_at=now)
        try:
            tenant_ids = self._tenants.tenants(now=now)
        except Exception as exc:  # noqa: BLE001 — reported, the loop goes on
            logger.exception("conversations.worker.discovery_failed")
            report.error = type(exc).__name__
            return report
        for tenant_id in tenant_ids:
            tenant_pass = TenantPass(tenant_id=tenant_id)
            report.tenants.append(tenant_pass)
            if self._sync_due(tenant_id) and self._syncer is not None:
                self._last_sync[tenant_id] = self._monotonic()
                try:
                    tenant_pass.sync = await self._syncer(tenant_id)
                except Exception as exc:  # noqa: BLE001 — the send still runs
                    logger.exception("conversations.worker.sync_failed tenant_id=%s", tenant_id)
                    tenant_pass.errors.append(f"sync:{type(exc).__name__}")
            try:
                tenant_pass.send = await self._sender.run_once(tenant_id, limit=self._limit)
            except Exception as exc:  # noqa: BLE001 — one tenant must not stop the others
                logger.exception("conversations.worker.tenant_failed tenant_id=%s", tenant_id)
                tenant_pass.errors.append(f"send:{type(exc).__name__}")
        return report


class _Runner(Protocol):
    async def run_once(self) -> TickReport: ...


# --- production wiring --------------------------------------------------------------------


async def sync_tenant(tenant_id: UUID) -> list[SyncReport]:
    """The reconciliation poll of every active Instagram connection of ONE tenant, on the
    registry's source for `dm` (the real adapter, or the in-memory pair in `memory`
    mode). A connection whose sync raises is logged; the others still run."""
    from qualify_api.conversations.composition import (  # noqa: PLC0415
        instagram_connections_for,
        production_registry,
        production_sync_service,
    )
    from qualify_api.conversations.contracts import CHANNEL_DM  # noqa: PLC0415

    source = production_registry().source_for(CHANNEL_DM)
    service = production_sync_service()
    reports: list[SyncReport] = []
    for connection in await asyncio.to_thread(instagram_connections_for, tenant_id):
        try:
            reports.append(await service.sync_connection(connection, source))
        except Exception:  # noqa: BLE001 — recorded on the sync state by the service
            logger.exception(
                "conversations.worker.connection_sync_failed connection=%s",
                connection.connection_id,
            )
    return reports


class NoSender:
    """`--sync-only`: the pass polls and claims nothing."""

    async def run_once(self, tenant_id: UUID, *, limit: int = DEFAULT_BATCH) -> SendReport:
        return SendReport(tenant_id=tenant_id)


def _tick(
    tenants: TenantSource, *, sync: bool, send: bool, sync_interval: float, limit: int
) -> ConversationsTick:
    from qualify_api.conversations.composition import production_sender  # noqa: PLC0415

    return ConversationsTick(
        tenants=tenants,
        sender=production_sender(worker_id=worker_id()) if send else NoSender(),
        syncer=sync_tenant if sync else None,
        sync_interval=sync_interval if sync else None,
        limit=limit,
    )


def scoped_tick(
    tenant_ids: Iterable[UUID],
    *,
    sync: bool = False,
    send: bool = True,
    sync_interval: float = DEFAULT_SYNC_INTERVAL_SECONDS,
    limit: int = DEFAULT_BATCH,
) -> ConversationsTick:
    """A pass over EXACTLY these tenants — localhost validation."""
    return _tick(
        ScopedTenants(tenant_ids), sync=sync, send=send, sync_interval=sync_interval, limit=limit
    )


def production_tick(
    *,
    sync: bool = False,
    send: bool = True,
    sync_interval: float = DEFAULT_SYNC_INTERVAL_SECONDS,
    limit: int = DEFAULT_BATCH,
) -> ConversationsTick:
    """The PRODUCTION pass: every tenant with an active Instagram connection. Do not run
    it against a database that holds test tenants."""
    return _tick(
        DiscoveredTenants(), sync=sync, send=send, sync_interval=sync_interval, limit=limit
    )


# --- CLI ----------------------------------------------------------------------------------


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(Path(__file__).resolve().parents[5] / ".env", override=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m qualify_api.conversations.worker",
        description="Drain the private-conversations outbox (QUA-226) once or periodically, "
        "optionally running the Instagram reconciliation poll first.",
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
        help="Every tenant with an active Instagram connection (production discovery).",
    )
    parser.add_argument("--once", action="store_true", help="Run one pass and exit.")
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Also run the reconciliation poll (spends Meta calls on the real channel).",
    )
    parser.add_argument(
        "--sync-only",
        action="store_true",
        help="Run the poll and skip the sender (implies --sync).",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL_SECONDS,
        help=f"Seconds between pass starts (default {DEFAULT_INTERVAL_SECONDS}, "
        f"minimum {MIN_INTERVAL_SECONDS}).",
    )
    parser.add_argument(
        "--sync-interval",
        type=int,
        default=DEFAULT_SYNC_INTERVAL_SECONDS,
        help=f"Minimum seconds between polls of the same tenant (default "
        f"{DEFAULT_SYNC_INTERVAL_SECONDS}).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_BATCH,
        help=f"Rows claimed per tenant per pass (default {DEFAULT_BATCH}).",
    )
    return parser


def _log_report(report: TickReport) -> None:
    for tenant in report.tenants:
        send = tenant.send
        synced = sum(r.messages_created for r in tenant.sync)
        if tenant.sync or tenant.errors or (send is not None and send.claimed):
            logger.info(
                "conversations.worker.tenant tenant_id=%s synced_connections=%d new_messages=%d "
                "claimed=%d sent=%d retried=%d failed=%d dead=%d errors=%s",
                tenant.tenant_id,
                len(tenant.sync),
                synced,
                send.claimed if send else 0,
                send.sent if send else 0,
                send.retried if send else 0,
                send.failed if send else 0,
                send.dead if send else 0,
                ",".join(tenant.errors) or "none",
            )
    if report.error:
        logger.info("conversations.worker.pass tick_error=%s", report.error)


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
    runner = make_runner()
    ticks = 0
    while not should_stop():
        started = clock()
        report: TickReport | None = None
        try:
            report = await runner.run_once()
            _log_report(report)
        except Exception:  # noqa: BLE001 — log and keep going
            logger.exception("conversations.worker.pass_failed")
        ticks += 1
        if once:
            return 0 if report is not None and not report.error else 1
        if max_ticks is not None and ticks >= max_ticks:
            return 0
        await sleep(max(0.0, interval - (clock() - started)))
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    scoped: Callable[..., _Runner] | None = None,
    production: Callable[..., _Runner] | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.interval < MIN_INTERVAL_SECONDS:
        parser.error(f"--interval must be at least {MIN_INTERVAL_SECONDS} second(s)")
    if args.limit < 1:
        parser.error("--limit must be at least 1")
    _load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    sync = args.sync or args.sync_only
    options = {
        "sync": sync,
        "send": not args.sync_only,
        "sync_interval": args.sync_interval,
        "limit": args.limit,
    }
    scoped = scoped or scoped_tick
    production = production or production_tick

    if args.all_tenants:
        make_runner: Callable[[], _Runner] = lambda: production(**options)  # noqa: E731
        scope = "all-tenants"
    else:
        tenant_ids = list(dict.fromkeys(args.tenants))
        make_runner = lambda: scoped(tenant_ids, **options)  # noqa: E731
        scope = ",".join(str(t) for t in tenant_ids)

    logger.info(
        "conversations.worker.start scope=%s mode=%s sync=%s interval=%ss limit=%d",
        scope,
        "once" if args.once else "loop",
        "only" if args.sync_only else sync,
        args.interval,
        args.limit,
    )
    try:
        return asyncio.run(run_worker(make_runner, once=args.once, interval=args.interval))
    except KeyboardInterrupt:
        logger.info("conversations.worker.stopped")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

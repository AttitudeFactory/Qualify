"""The Conversaciones worker (QUA-226, E5): the process that drains `conversation_outbox`
and, when asked, runs the reconciliation poll of every active Instagram connection.

    python -m qualify_api.conversations.worker --tenant <uuid> [--once] [--sync]
    python -m qualify_api.conversations.worker --all-tenants [--once] [--sync]

(`just conversations-tick …` runs one pass, `just conversations-worker …` keeps running,
`just conversations-sync …` is one pass of the poll only.)

Each pass is, per tenant in scope: `ConversationOutboxSender.run_once(tenant_id)`, then
the public notices of Fase C (`followups.notice.PublicNoticePoster.run_once(tenant_id)`,
m-24789646 PR 4: the «Te enviamos la información por DM 💬» reply under a comment whose
private message is now confirmed sent). The notice step runs even when the send step
raised — it is independent and never touches the outbox. Then, with `--sync`, the
reconciliation poll (`ConversationSyncService.sync_connection` on each active Instagram
connection) of every tenant whose last poll is at least `--sync-interval` seconds old.

**Sends never wait for the poll (m-25017174).** A full Graph re-sync of every tenant can
take minutes (no cap, each call may wait 30 s); when it ran inline before the sender, an
approved reply waited for it. In loop mode the poll runs on `BackgroundSync`: one thread
of this same process with its own event loop, at most one round in flight, while the
sender keeps its 5 s tick on the main loop. The two never share a DB session (every
repository call opens its own through `tenant_session`) nor an HTTP client (the poll uses
the channel's source, the sender its sender). `--once` (one pass,
`just conversations-tick`) and `--sync-only` still poll inline, after the send.

Same mould and the SAME warning as `whatsapp/worker.py` and `planner/worker.py`:

Scope is MANDATORY and explicit — there is no default that means "everyone":
- `--tenant <uuid>` (repeatable): exactly those tenants. Use it locally: a development
  database holds test tenants a production pass would act on.
- `--all-tenants`: the production discovery (`DiscoveredTenants`: every tenant with an
  active Instagram connection, ids only, through `admin_session` — `qualify_admin` holds
  SELECT on `social_connections` (0002) and nothing on the outbox).

In `memory` mode (`QUALIFY_CONVERSATIONS_DM_CHANNEL=memory`) the sender "delivers" to the
in-memory pair, the notices go to an in-memory client and the poll reads the seeded
conversations: nothing reaches Instagram.
`--sync` against the real pair spends Meta calls — the development-mode budget is 200
calls per hour per Page/app pair (QUA-20), hence the default `--sync-interval` of 300 s.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import socket
import threading
import time
from collections.abc import Awaitable, Callable, Iterable, Sequence
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from qualify_api.conversations.outbox import DEFAULT_BATCH
from qualify_api.conversations.sender import SendReport
from qualify_api.conversations.sync import SyncReport
from qualify_api.followups.notice import NoticeReport

logger = logging.getLogger("qualify_api.conversations.worker")

DEFAULT_INTERVAL_SECONDS = 5
DEFAULT_SYNC_INTERVAL_SECONDS = 300
MIN_INTERVAL_SECONDS = 1
# m-25017174: the longest one tenant's background poll may run before it is cancelled and
# counted as that tenant's failure (two default sync intervals; a full re-sync of a large
# account fits, a hung Graph read — 30 s each — does not pin the round forever).
SYNC_TENANT_TIMEOUT_SECONDS = 600.0
# m-25017174: a round older than this many sync intervals is reported as stuck, at most
# once per sync interval, each time a due round is refused because of it.
SYNC_STUCK_AFTER_INTERVALS = 3


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
    notices: NoticeReport | None = None
    errors: list[str] = field(default_factory=list)


@dataclass
class TickReport:
    started_at: datetime
    tenants: list[TenantPass] = field(default_factory=list)
    error: str = ""  # set only when the pass could not list its tenants


class _Sender(Protocol):
    async def run_once(self, tenant_id: UUID, *, limit: int = DEFAULT_BATCH) -> SendReport: ...


class _NoticePoster(Protocol):
    async def run_once(self, tenant_id: UUID, *, limit: int = DEFAULT_BATCH) -> NoticeReport: ...


class _Syncer(Protocol):
    async def __call__(self, tenant_id: UUID) -> list[SyncReport]: ...


def _log_sync(tenant_id: UUID, reports: Sequence[SyncReport], duration_s: float) -> None:
    logger.info(
        "conversations.worker.sync tenant_id=%s synced_connections=%d new_messages=%d "
        "duration_s=%.1f",
        tenant_id,
        len(reports),
        sum(r.messages_created for r in reports),
        duration_s,
    )


class BackgroundSync:
    """m-25017174: the reconciliation poll on its own thread and event loop, so a slow
    re-sync never delays a send. One loop for the life of the process (the channel source
    keeps per-connection HTTP clients bound to it); at most one round in flight — a round
    is refused while the previous one runs. A tenant whose poll raises, or runs longer than
    `tenant_timeout`, is logged and the round goes on. `on_start(tenant_id, at)` is called
    as each tenant's poll begins (the sync interval counts from there). `close()` cancels a
    round in flight and stops the thread.

    Cancelling a poll (timeout or `close()`) lands only on an `await`: every repository
    and credential call of the sync is a synchronous `with tenant_session(...)` /
    `credential_session(...)` block with no `await` inside, so a cancellation never
    interrupts an open session. The flip side: a synchronous call that blocks (a DB lock
    wait) blocks this loop and the timeout cannot fire — the stuck-round warning of
    `ConversationsTick` is what reports that case."""

    def __init__(
        self,
        syncer: _Syncer,
        *,
        name: str = "conversations-sync",
        monotonic: Callable[[], float] = time.monotonic,
        tenant_timeout: float = SYNC_TENANT_TIMEOUT_SECONDS,
        on_start: Callable[[UUID, float], None] | None = None,
    ) -> None:
        self._syncer = syncer
        self._monotonic = monotonic
        self._tenant_timeout = tenant_timeout
        self._on_start = on_start
        self._loop = asyncio.new_event_loop()
        self._pending: Future[None] | None = None
        self._closed = False
        # Written by the sync thread, read by the main one: single assignments (GIL-atomic).
        self.round_started: float | None = None
        self.tenant_in_flight: UUID | None = None
        self._thread = threading.Thread(target=self._serve, name=name, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_forever()
        finally:
            leftover = asyncio.all_tasks(self._loop)
            for task in leftover:
                task.cancel()
            if leftover:
                self._loop.run_until_complete(asyncio.gather(*leftover, return_exceptions=True))
            self._loop.close()

    @property
    def busy(self) -> bool:
        return self._pending is not None and not self._pending.done()

    def submit(self, tenant_ids: Sequence[UUID]) -> bool:
        """Start a round over `tenant_ids`; False (nothing started) while one is running."""
        if self._closed or self.busy:
            return False
        self._pending = asyncio.run_coroutine_threadsafe(self._round(list(tenant_ids)), self._loop)
        return True

    def submit_age(self) -> float | None:
        """Seconds the round in flight has been running; None when idle."""
        started = self.round_started
        return None if started is None or not self.busy else self._monotonic() - started

    async def _round(self, tenant_ids: list[UUID]) -> None:
        round_started = self.round_started = self._monotonic()
        failed = 0
        try:
            for tenant_id in tenant_ids:
                started = self._monotonic()
                self.tenant_in_flight = tenant_id
                if self._on_start is not None:
                    self._on_start(tenant_id, started)
                try:
                    reports = await asyncio.wait_for(
                        self._syncer(tenant_id), timeout=self._tenant_timeout
                    )
                except TimeoutError:
                    failed += 1
                    logger.warning(
                        "conversations.worker.sync_timeout tenant_id=%s timeout_s=%.0f",
                        tenant_id,
                        self._tenant_timeout,
                    )
                    continue
                except Exception:  # noqa: BLE001 — the next tenant still polls
                    failed += 1
                    logger.exception("conversations.worker.sync_failed tenant_id=%s", tenant_id)
                    continue
                _log_sync(tenant_id, reports, self._monotonic() - started)
        finally:
            self.tenant_in_flight = None
        logger.info(
            "conversations.worker.sync_round tenants=%d failed=%d duration_s=%.1f",
            len(tenant_ids),
            failed,
            self._monotonic() - round_started,
        )

    def wait(self, timeout: float | None = None) -> None:
        """Block until the round in flight (if any) ends — for tests."""
        if self._pending is not None:
            try:
                self._pending.result(timeout=timeout)
            except Exception:  # noqa: BLE001 — the round logged it; a timeout is the caller's
                pass

    def close(self, timeout: float = 5.0) -> None:
        if self._closed:
            return
        self._closed = True
        if self._pending is not None:
            self._pending.cancel()
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout)


class ConversationsTick:
    """One pass over the tenants in scope. A tenant whose pass raises is reported and
    the next tenant still runs; only a failure to LIST tenants fails the pass. The public
    notices run after the send, in their own `try`, when a poster is given. The poll runs
    after every tenant's send, at most every `sync_interval` seconds per tenant (None =
    never): inline, or — `sync_in_background` — submitted to a `BackgroundSync` and not
    awaited (m-25017174), in which case a tenant's interval counts from the moment its
    own poll starts in the round, and a due tenant waits for the next pass while a round
    is still running (a round older than `SYNC_STUCK_AFTER_INTERVALS` intervals is
    logged as `conversations.worker.sync_stuck`)."""

    def __init__(
        self,
        *,
        tenants: TenantSource,
        sender: _Sender,
        syncer: _Syncer | None = None,
        notices: _NoticePoster | None = None,
        sync_interval: float | None = None,
        sync_in_background: bool = False,
        sync_tenant_timeout: float = SYNC_TENANT_TIMEOUT_SECONDS,
        limit: int = DEFAULT_BATCH,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._tenants = tenants
        self._sender = sender
        self._syncer = syncer
        self._notices = notices
        self._sync_interval = sync_interval
        self._limit = limit
        self._clock = clock
        self._monotonic = monotonic
        self._last_sync: dict[UUID, float] = {}
        self._sync_in_background = sync_in_background
        self._sync_tenant_timeout = sync_tenant_timeout
        self._background: BackgroundSync | None = None
        self._stuck_warned_at: float | None = None

    @property
    def background(self) -> BackgroundSync | None:
        return self._background

    def close(self) -> None:
        """Stop the background poll, if one was started."""
        if self._background is not None:
            self._background.close()

    def _stamp(self, tenant_id: UUID, at: float) -> None:
        """Called by the sync thread as a tenant's poll starts (a single dict assignment)."""
        self._last_sync[tenant_id] = at

    def _warn_if_stuck(self, due: int) -> None:
        background, interval = self._background, self._sync_interval
        if background is None or interval is None:
            return
        age = background.submit_age()
        if age is None or age < SYNC_STUCK_AFTER_INTERVALS * interval:
            return
        now = self._monotonic()
        if self._stuck_warned_at is not None and now - self._stuck_warned_at < interval:
            return
        self._stuck_warned_at = now
        logger.warning(
            "conversations.worker.sync_stuck round_age_s=%.0f tenant_in_flight=%s due=%d",
            age,
            background.tenant_in_flight,
            due,
        )

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
        passes: list[TenantPass] = []
        for tenant_id in tenant_ids:
            tenant_pass = TenantPass(tenant_id=tenant_id)
            report.tenants.append(tenant_pass)
            passes.append(tenant_pass)
            try:
                tenant_pass.send = await self._sender.run_once(tenant_id, limit=self._limit)
            except Exception as exc:  # noqa: BLE001 — one tenant must not stop the others
                logger.exception("conversations.worker.tenant_failed tenant_id=%s", tenant_id)
                tenant_pass.errors.append(f"send:{type(exc).__name__}")
            if self._notices is None:
                continue
            try:
                tenant_pass.notices = await self._notices.run_once(tenant_id, limit=self._limit)
            except Exception as exc:  # noqa: BLE001 — a notice never stops a send or a tenant
                logger.exception("conversations.worker.notices_failed tenant_id=%s", tenant_id)
                tenant_pass.errors.append(f"notice:{type(exc).__name__}")
        await self._poll(passes)
        return report

    async def _poll(self, passes: list[TenantPass]) -> None:
        """m-25017174: the poll comes after every send of the pass, never before one."""
        if self._syncer is None:
            return
        due = [p for p in passes if self._sync_due(p.tenant_id)]
        if not due:
            return
        if self._sync_in_background:
            if self._background is None:
                self._background = BackgroundSync(
                    self._syncer,
                    monotonic=self._monotonic,
                    tenant_timeout=self._sync_tenant_timeout,
                    on_start=self._stamp,
                )
            if not self._background.submit([p.tenant_id for p in due]):
                self._warn_if_stuck(len(due))
            return
        for tenant_pass in due:
            self._last_sync[tenant_pass.tenant_id] = self._monotonic()
            try:
                tenant_pass.sync = await self._syncer(tenant_pass.tenant_id)
            except Exception as exc:  # noqa: BLE001 — reported, the next tenant still polls
                logger.exception(
                    "conversations.worker.sync_failed tenant_id=%s", tenant_pass.tenant_id
                )
                tenant_pass.errors.append(f"sync:{type(exc).__name__}")


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
    tenants: TenantSource,
    *,
    sync: bool,
    send: bool,
    sync_interval: float,
    limit: int,
    background_sync: bool = False,
) -> ConversationsTick:
    from qualify_api.conversations.composition import production_sender  # noqa: PLC0415
    from qualify_api.followups.composition import production_notice_poster  # noqa: PLC0415

    return ConversationsTick(
        tenants=tenants,
        sender=production_sender(worker_id=worker_id()) if send else NoSender(),
        syncer=sync_tenant if sync else None,
        # The notices are part of sending: `--sync-only` posts nothing either.
        notices=production_notice_poster(worker_id=worker_id()) if send else None,
        sync_interval=sync_interval if sync else None,
        sync_in_background=sync and background_sync,
        limit=limit,
    )


def scoped_tick(
    tenant_ids: Iterable[UUID],
    *,
    sync: bool = False,
    send: bool = True,
    sync_interval: float = DEFAULT_SYNC_INTERVAL_SECONDS,
    limit: int = DEFAULT_BATCH,
    background_sync: bool = False,
) -> ConversationsTick:
    """A pass over EXACTLY these tenants — localhost validation."""
    return _tick(
        ScopedTenants(tenant_ids),
        sync=sync,
        send=send,
        sync_interval=sync_interval,
        limit=limit,
        background_sync=background_sync,
    )


def production_tick(
    *,
    sync: bool = False,
    send: bool = True,
    sync_interval: float = DEFAULT_SYNC_INTERVAL_SECONDS,
    limit: int = DEFAULT_BATCH,
    background_sync: bool = False,
) -> ConversationsTick:
    """The PRODUCTION pass: every tenant with an active Instagram connection. Do not run
    it against a database that holds test tenants."""
    return _tick(
        DiscoveredTenants(),
        sync=sync,
        send=send,
        sync_interval=sync_interval,
        limit=limit,
        background_sync=background_sync,
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
        notices = tenant.notices
        synced = sum(r.messages_created for r in tenant.sync)
        noticed = notices is not None and (notices.claimed or notices.skipped)
        if tenant.sync or tenant.errors or (send is not None and send.claimed) or noticed:
            logger.info(
                "conversations.worker.tenant tenant_id=%s synced_connections=%d new_messages=%d "
                "claimed=%d sent=%d retried=%d failed=%d dead=%d notices_posted=%d "
                "notices_retried=%d notices_failed=%d notices_skipped=%d errors=%s",
                tenant.tenant_id,
                len(tenant.sync),
                synced,
                send.claimed if send else 0,
                send.sent if send else 0,
                send.retried if send else 0,
                send.failed if send else 0,
                send.dead if send else 0,
                notices.posted if notices else 0,
                notices.retried if notices else 0,
                notices.failed if notices else 0,
                notices.skipped if notices else 0,
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
    try:
        while not should_stop():
            started = clock()
            report: TickReport | None = None
            try:
                report = await runner.run_once()
                _log_report(report)
            except Exception:  # noqa: BLE001 — log and keep going
                logger.exception("conversations.worker.pass_failed")
            ticks += 1
            elapsed = clock() - started
            if elapsed > 2 * interval:
                # m-25017174: how long an approved reply could wait on top of the tick.
                logger.info("conversations.worker.slow_pass duration_s=%.1f", elapsed)
            if once:
                return 0 if report is not None and not report.error else 1
            if max_ticks is not None and ticks >= max_ticks:
                return 0
            await sleep(max(0.0, interval - elapsed))
        return 0
    finally:
        close = getattr(runner, "close", None)
        if close is not None:
            close()


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
        # m-25017174: in the loop the poll never holds a send; one pass polls inline.
        "background_sync": sync and not args.once and not args.sync_only,
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

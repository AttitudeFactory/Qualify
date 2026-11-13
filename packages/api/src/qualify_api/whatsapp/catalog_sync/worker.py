"""`CatalogSyncTick` — drains `whatsapp_catalog_sync_runs` (ADR 48 §4.4, §7).

Runs inside the existing `whatsapp-worker` process as a separate asyncio task
(`whatsapp/worker.py --catalog-interval`), never in a web request and never as a new
service. One pass, per tenant in scope:

1. **Claim** (`tenant_session`): `SELECT … FOR UPDATE SKIP LOCKED LIMIT 1` over runs with
   `next_attempt_at ≤ now()` and `status IN ('pending','sent')`, or `sending` whose claim is
   older than 10 minutes (a worker died mid-send).
2. **Send** a `pending` run: at most 10 sends per catalog per hour (`sent_at`), else it
   waits. The request `data` is rebuilt from the product as it is NOW (§5), each item
   goes `uploading` with its `pending_hash`, the transaction commits, and only then
   `POST /{catalog_id}/items_batch`. Re-sending after a crash is safe: `UPDATE` with
   `allow_upsert` and `DELETE` by id are idempotent in Meta.
3. **Poll** a `sent` run: `check_batch_request_status` until `finished` (30 s, 1, 2, 5,
   10 min; `failed` + `meta_unconfirmed` at 24 h).
4. **Settle** in a second transaction, guarded by `status` + `locked_by` so a run another
   worker re-claimed is never settled twice.

Errors (§7): 80014/80009 and Meta's generic throttles (4, 17, 32, 613) → `pending` +15
min (not counted as an attempt; a run not sent 24 h after it was requested fails);
transport or 5xx → `pending` after 1, 5, 15, 60 min, `failed` + `send_failed` at the 5th
attempt (also on a stale-claim re-send); a failed status poll waits longer each time
(`poll_error_wait`, ≤ 1 h) and a 4xx on it fails the run at once (`meta_unconfirmed`);
authorization (`is_auth_error` → `auth_error`; codes 10/200-299 → `missing_permission`) →
run `failed`, items `no_permission`, `whatsapp_catalogs.access_state` set; any other 4xx →
`failed` + `send_failed` at once (re-sending the same request cannot fix it).

Logs carry ids, counts, statuses and numeric codes only — never Meta's `message`, never a
product's text.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.orm import Session

from qualify_api.whatsapp.catalog_sync.client import (
    BatchAck,
    BatchStatus,
    WhatsAppCatalogClient,
)
from qualify_api.whatsapp.catalog_sync.mapping import (
    content_hash,
    delete_data,
    ineligibility,
    item_data,
)
from qualify_api.whatsapp.catalog_sync.media_url import CatalogMediaUnavailable
from qualify_api.whatsapp.catalog_sync.store import (
    CatalogRow,
    load_catalog_by_id,
    load_items,
    load_products,
)
from qualify_api.whatsapp.client import WhatsAppApiError
from qualify_api.whatsapp.models import (
    WhatsAppCatalog,
    WhatsAppCatalogItem,
    WhatsAppCatalogSyncRun,
)

logger = logging.getLogger("qualify_api.whatsapp.catalog_sync.worker")

DEFAULT_CATALOG_INTERVAL_SECONDS = 30
STALE_CLAIM = timedelta(minutes=10)
POLL_LEASE = timedelta(minutes=10)
HOURLY_CAP = 10
RATE_LIMIT_WAIT = timedelta(minutes=15)
TRANSIENT_BACKOFF = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(minutes=60),
)
MAX_ATTEMPTS = 5
UNCONFIRMED_AFTER = timedelta(hours=24)
FIRST_POLL = timedelta(seconds=30)
#: Catalog limits (80014 batch calls, 80009 status calls) and Meta's generic throttles
#: (4 app, 17 user, 32 page, 613 call rate): all waited out, never a failure by themselves.
RATE_LIMIT_CODES = frozenset({80014, 80009, 4, 17, 32, 613})
MAX_RUNS_PER_TENANT = 10
#: A run still not sent this long after it was requested is failed (a rate limit that never
#: lifts must not keep its items `queued` forever: the person could never resync them).
MAX_RUN_AGE = timedelta(hours=24)
#: Ceiling of the wait between status polls that FAILED (transient) — see `poll_error_wait`.
MAX_POLL_ERROR_WAIT = timedelta(minutes=60)
#: Bounds how long a claim or settle waits on a row lock (e.g. a person's `sync_all`
#: holding the run's items); past it the statement fails and the lease recovers the run.
LOCK_TIMEOUT = "5s"

ErrorKind = Literal["rate_limited", "auth_error", "missing_permission", "transient", "rejected"]


def classify(exc: BaseException) -> ErrorKind:
    """How a failed Meta call is handled (§7). Anything that is not a `WhatsAppApiError`
    (a resolver failure, a bug in a fake) is transient: retried with backoff, bounded."""
    if not isinstance(exc, WhatsAppApiError):
        return "transient"
    if exc.code in RATE_LIMIT_CODES:
        return "rate_limited"
    if exc.is_auth_error:
        return "auth_error"
    if exc.code is not None and (exc.code == 10 or 200 <= exc.code <= 299):
        return "missing_permission"
    if exc.is_transport or exc.status is None or exc.status >= 500:
        return "transient"
    return "rejected"


def poll_wait(elapsed: timedelta) -> timedelta:
    """30 s, 1, 2, 5, then 10 min between polls, by time since the batch was sent."""
    if elapsed < timedelta(minutes=1):
        return timedelta(seconds=30)
    if elapsed < timedelta(minutes=3):
        return timedelta(minutes=1)
    if elapsed < timedelta(minutes=5):
        return timedelta(minutes=2)
    if elapsed < timedelta(minutes=15):
        return timedelta(minutes=5)
    return timedelta(minutes=10)


def poll_error_wait(elapsed: timedelta) -> timedelta:
    """After a FAILED status poll: the normal poll wait or half the time since the batch
    was sent, whichever is longer, at most an hour — ~30 polls in 24 h, not ~1,400."""
    return min(max(poll_wait(elapsed), elapsed / 2), MAX_POLL_ERROR_WAIT)


def transient_wait(attempts: int) -> timedelta:
    return TRANSIENT_BACKOFF[min(max(attempts, 1), len(TRANSIENT_BACKOFF)) - 1]


# --- seams --------------------------------------------------------------------------------


class CatalogClientFactory(Protocol):
    async def __call__(
        self, *, tenant_id: UUID, connection_id: UUID, catalog_id: str
    ) -> WhatsAppCatalogClient: ...


class TenantSource(Protocol):
    def tenants(self, *, now: datetime) -> list[UUID]: ...


class CatalogTenants:
    """Every tenant with a registered catalog — ids only, via `admin_session` (0154 grants
    `qualify_admin` SELECT on `whatsapp_catalogs` for exactly this)."""

    def tenants(self, *, now: datetime) -> list[UUID]:
        from qualify_shared.db.admin import admin_session  # noqa: PLC0415

        with admin_session() as session:
            return list(
                session.scalars(
                    select(WhatsAppCatalog.tenant_id).distinct().order_by(WhatsAppCatalog.tenant_id)
                )
            )


@dataclass
class CatalogTenantReport:
    tenant_id: UUID
    claimed: int = 0
    sent: int = 0
    finished: int = 0
    partial: int = 0
    failed: int = 0
    deferred: int = 0
    retried: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class CatalogTickReport:
    started_at: datetime
    tenants: list[CatalogTenantReport] = field(default_factory=list)
    error: str = ""


_NOTHING = object()
_HANDLED = object()


@dataclass(frozen=True)
class _Work:
    kind: Literal["send", "poll"]
    run_id: UUID
    catalog_row_id: UUID
    catalog_id: str
    connection_id: UUID
    requests: tuple[dict[str, Any], ...] = ()
    handle: str = ""
    sent_at: datetime | None = None


# --- item transitions ---------------------------------------------------------------------


def _set_item_error(item: WhatsAppCatalogItem, code: str, now: datetime) -> None:
    item.state = "error"
    item.error_code = code
    item.pending_op = None
    item.pending_hash = None
    item.updated_at = now


def _requeue(item: WhatsAppCatalogItem, now: datetime) -> None:
    item.state = "queued"
    item.updated_at = now


def _run_items(session: Session, run: WhatsAppCatalogSyncRun) -> list[WhatsAppCatalogItem]:
    """The run's items still bound to it (an item's `last_run_id` names its latest run)."""
    return [
        i
        for i in load_items(
            session, run.catalog_row_id, item_ids=list(run.item_ids), for_update=True
        )
        if i.last_run_id == run.id
    ]


def _finish(run: WhatsAppCatalogSyncRun, status: str, now: datetime) -> None:
    run.status = status
    run.finished_at = now
    run.locked_by = None
    run.locked_at = None


def _fail_run(
    session: Session,
    run: WhatsAppCatalogSyncRun,
    *,
    error_code: str,
    item_error: str,
    now: datetime,
    meta_error_code: int | None = None,
    states: frozenset[str] = frozenset({"queued", "uploading"}),
) -> None:
    failed = 0
    for item in _run_items(session, run):
        if item.state in states:
            _set_item_error(item, item_error, now)
            item.meta_error_code = meta_error_code
        if item.state == "error":
            failed += 1
    run.error_code = error_code
    run.meta_error_code = meta_error_code
    run.items_failed = failed
    _finish(run, "failed", now)


def _record_access(
    session: Session, catalog_row_id: UUID, access_state: str, now: datetime
) -> None:
    catalog = session.get(WhatsAppCatalog, catalog_row_id)
    if catalog is not None:
        catalog.access_state = access_state
        catalog.access_checked_at = now
        catalog.updated_at = now


def _bounded_locks(session: Session) -> None:
    session.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))


# --- the tick -----------------------------------------------------------------------------


class CatalogSyncTick:
    """One pass over the tenants in scope. A tenant whose pass raises is reported and the
    next one still runs; only a failure to LIST tenants fails the pass."""

    def __init__(
        self,
        *,
        tenants: TenantSource,
        clients: CatalogClientFactory,
        worker_id: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        max_runs_per_tenant: int = MAX_RUNS_PER_TENANT,
    ) -> None:
        self._tenants = tenants
        self._clients = clients
        self._worker_id = worker_id
        self._clock = clock
        self._max_runs = max_runs_per_tenant

    async def run_once(self) -> CatalogTickReport:
        now = self._clock()
        report = CatalogTickReport(started_at=now)
        try:
            tenant_ids = self._tenants.tenants(now=now)
        except Exception as exc:  # noqa: BLE001 — reported, the loop goes on
            logger.exception("whatsapp.catalog.discovery_failed")
            report.error = type(exc).__name__
            return report
        for tenant_id in tenant_ids:
            tenant_report = CatalogTenantReport(tenant_id=tenant_id)
            try:
                await self.run_tenant(tenant_id, tenant_report)
            except Exception as exc:  # noqa: BLE001 — one tenant must not stop the others
                logger.exception("whatsapp.catalog.tenant_failed tenant_id=%s", tenant_id)
                tenant_report.errors.append(type(exc).__name__)
            report.tenants.append(tenant_report)
        return report

    async def run_tenant(self, tenant_id: UUID, report: CatalogTenantReport) -> None:
        """Up to `max_runs_per_tenant` claims; stops at the first empty claim.

        Every database step (claim, settle) runs in a worker thread (`asyncio.to_thread`)
        with a bounded `lock_timeout`: this task shares the event loop with the outbox
        sender, and a row lock held by a person's `sync_all` must never stall WhatsApp
        messages. (`OutboxTick` runs its short, `SKIP LOCKED` statements on the loop.)"""
        for _ in range(self._max_runs):
            work = await asyncio.to_thread(self._claim, tenant_id, report)
            if work is _NOTHING:
                return
            if work is _HANDLED:
                continue
            assert isinstance(work, _Work)
            if work.kind == "send":
                await self._send(tenant_id, work, report)
            else:
                await self._poll(tenant_id, work, report)

    # -- claim -----------------------------------------------------------------------

    @staticmethod
    def _due(now: datetime):  # noqa: ANN205 — a SQL expression
        return and_(
            WhatsAppCatalogSyncRun.next_attempt_at <= now,
            or_(
                WhatsAppCatalogSyncRun.status.in_(("pending", "sent")),
                and_(
                    WhatsAppCatalogSyncRun.status == "sending",
                    WhatsAppCatalogSyncRun.locked_at < now - STALE_CLAIM,
                ),
            ),
        )

    def _claim(self, tenant_id: UUID, report: CatalogTenantReport) -> _Work | object:
        """A `_Work` to do outside the transaction, `_HANDLED` when the claimed run was
        settled inside it (deferred, failed, finished), `_NOTHING` when nothing is due."""
        now = self._clock()
        with tenant_session(tenant_id) as session:
            _bounded_locks(session)
            run = session.scalar(
                select(WhatsAppCatalogSyncRun)
                .where(self._due(now))
                .order_by(WhatsAppCatalogSyncRun.next_attempt_at, WhatsAppCatalogSyncRun.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if run is None:
                return _NOTHING
            report.claimed += 1
            catalog = load_catalog_by_id(session, run.catalog_row_id)
            if run.status == "sent":
                if catalog is None or not run.handle:
                    _fail_run(
                        session, run, error_code="not_connected", item_error="send_failed", now=now
                    )
                    report.failed += 1
                    return _HANDLED
                run.locked_by = self._worker_id
                run.locked_at = now
                run.next_attempt_at = now + POLL_LEASE
                return _Work(
                    kind="poll",
                    run_id=run.id,
                    catalog_row_id=catalog.id,
                    catalog_id=catalog.catalog_id,
                    connection_id=catalog.connection_id,
                    handle=run.handle,
                    sent_at=run.sent_at,
                )
            work = self._prepare_send(session, run, catalog, now, report)
            return work if work is not None else _HANDLED

    def _prepare_send(
        self,
        session: Session,
        run: WhatsAppCatalogSyncRun,
        catalog: CatalogRow | None,
        now: datetime,
        report: CatalogTenantReport,
    ) -> _Work | None:
        if catalog is None or catalog.source != "qualify":
            _fail_run(session, run, error_code="not_connected", item_error="send_failed", now=now)
            report.failed += 1
            return None
        if catalog.access_state != "ok":
            _fail_run(
                session, run, error_code=catalog.access_state, item_error="no_permission", now=now
            )
            report.failed += 1
            return None
        if run.attempts >= MAX_ATTEMPTS:
            # E.g. a worker that keeps dying mid-send: the stale-claim path re-sends, and
            # without this check it would never stop.
            _fail_run(session, run, error_code="send_failed", item_error="send_failed", now=now)
            report.failed += 1
            return None
        if now - run.requested_at >= MAX_RUN_AGE:
            _fail_run(session, run, error_code="expired", item_error="send_failed", now=now)
            report.failed += 1
            return None
        window = session.execute(
            select(func.count(), func.min(WhatsAppCatalogSyncRun.sent_at)).where(
                WhatsAppCatalogSyncRun.catalog_row_id == catalog.id,
                WhatsAppCatalogSyncRun.sent_at > now - timedelta(hours=1),
            )
        ).one()
        if window[0] >= HOURLY_CAP:
            run.next_attempt_at = max(window[1] + timedelta(hours=1), now + timedelta(minutes=1))
            report.deferred += 1
            logger.info(
                "whatsapp.catalog.deferred tenant_id=%s run_id=%s catalog_row_id=%s "
                "sends_last_hour=%d",
                catalog.tenant_id,
                run.id,
                catalog.id,
                window[0],
            )
            return None

        items = _run_items(session, run)
        product_ids = [i.product_id for i in items if i.product_id is not None]
        products = load_products(session, catalog.brand_id, product_ids) if product_ids else {}
        ctx = catalog.mapping_context()
        requests: list[dict[str, Any]] = []
        try:
            for item in items:
                if item.state not in ("queued", "uploading"):
                    continue
                op = item.pending_op or "upsert"
                product = products.get(item.product_id) if item.product_id else None
                if op == "upsert" and (product is None or not product.is_active):
                    op = "delete"
                if op == "upsert":
                    assert product is not None
                    if ineligibility(product) is not None:
                        # Became ineligible after it was queued: leave it out, as it was.
                        item.state = "synced" if item.last_pushed_hash else "deleted"
                        item.pending_op = None
                        item.pending_hash = None
                        item.updated_at = now
                        continue
                    data = item_data(product, retailer_id=item.retailer_id, ctx=ctx)
                    item.pending_hash = content_hash(data)
                    requests.append({"method": "UPDATE", "data": data})
                else:
                    item.pending_hash = None
                    requests.append({"method": "DELETE", "data": delete_data(item.retailer_id)})
                item.pending_op = op
                item.state = "uploading"
                item.updated_at = now
        except CatalogMediaUnavailable:
            _fail_run(
                session, run, error_code="media_unavailable", item_error="send_failed", now=now
            )
            report.failed += 1
            return None
        if not requests:
            run.items_failed = 0
            _finish(run, "finished", now)
            report.finished += 1
            return None
        run.status = "sending"
        run.attempts += 1
        run.locked_by = self._worker_id
        run.locked_at = now
        return _Work(
            kind="send",
            run_id=run.id,
            catalog_row_id=catalog.id,
            catalog_id=catalog.catalog_id,
            connection_id=catalog.connection_id,
            requests=tuple(requests),
        )

    # -- calls -----------------------------------------------------------------------

    async def _client(self, tenant_id: UUID, work: _Work) -> WhatsAppCatalogClient:
        return await self._clients(
            tenant_id=tenant_id, connection_id=work.connection_id, catalog_id=work.catalog_id
        )

    @staticmethod
    async def _close(client: object) -> None:
        close = getattr(client, "aclose", None)
        if close is not None:
            try:
                await close()
            except Exception:  # noqa: BLE001 — closing must not change the outcome
                logger.warning("whatsapp.catalog.client_close_failed")

    async def _send(self, tenant_id: UUID, work: _Work, report: CatalogTenantReport) -> None:
        ack: BatchAck | None = None
        error: BaseException | None = None
        client: WhatsAppCatalogClient | None = None
        try:
            client = await self._client(tenant_id, work)
            ack = await client.items_batch(list(work.requests))
        except Exception as exc:  # noqa: BLE001 — classified and settled below
            error = exc
        finally:
            if client is not None:
                await self._close(client)
        await asyncio.to_thread(self._settle_send, tenant_id, work, ack, error, report)

    async def _poll(self, tenant_id: UUID, work: _Work, report: CatalogTenantReport) -> None:
        status: BatchStatus | None = None
        error: BaseException | None = None
        client: WhatsAppCatalogClient | None = None
        try:
            client = await self._client(tenant_id, work)
            status = await client.batch_status(work.handle)
        except Exception as exc:  # noqa: BLE001 — classified and settled below
            error = exc
        finally:
            if client is not None:
                await self._close(client)
        await asyncio.to_thread(self._settle_poll, tenant_id, work, status, error, report)

    # -- settle ----------------------------------------------------------------------

    def _locked_run(
        self, session: Session, work: _Work, status: str
    ) -> WhatsAppCatalogSyncRun | None:
        return session.scalar(
            select(WhatsAppCatalogSyncRun)
            .where(
                WhatsAppCatalogSyncRun.id == work.run_id,
                WhatsAppCatalogSyncRun.status == status,
                WhatsAppCatalogSyncRun.locked_by == self._worker_id,
            )
            .with_for_update()
        )

    def _settle_error(
        self,
        session: Session,
        run: WhatsAppCatalogSyncRun,
        error: BaseException,
        *,
        now: datetime,
        phase: Literal["send", "poll"],
        report: CatalogTenantReport,
    ) -> str:
        kind = classify(error)
        code = error.code if isinstance(error, WhatsAppApiError) else None
        if kind in ("auth_error", "missing_permission"):
            _record_access(session, run.catalog_row_id, kind, now)
            _fail_run(
                session,
                run,
                error_code=kind,
                item_error="no_permission",
                now=now,
                meta_error_code=code,
            )
            report.failed += 1
            return kind
        if phase == "poll":
            if run.sent_at is not None and now - run.sent_at >= UNCONFIRMED_AFTER:
                _fail_run(
                    session,
                    run,
                    error_code="meta_unconfirmed",
                    item_error="meta_unconfirmed",
                    now=now,
                    meta_error_code=code,
                    states=frozenset({"uploading"}),
                )
                report.failed += 1
                return "meta_unconfirmed"
            if kind == "rejected":
                # A 4xx on the status read (a handle Meta does not know): asking again
                # cannot help, and whether the batch was ingested is unknown.
                _fail_run(
                    session,
                    run,
                    error_code="meta_error",
                    item_error="meta_unconfirmed",
                    now=now,
                    meta_error_code=code,
                    states=frozenset({"uploading"}),
                )
                report.failed += 1
                return kind
            elapsed = now - (run.sent_at or now)
            wait = (
                max(RATE_LIMIT_WAIT, poll_error_wait(elapsed))
                if kind == "rate_limited"
                else poll_error_wait(elapsed)
            )
            run.next_attempt_at = now + wait
            run.locked_by = None
            run.locked_at = None
            run.meta_error_code = code
            report.retried += 1
            return kind
        # phase == "send"
        if kind == "rate_limited" and now + RATE_LIMIT_WAIT - run.requested_at >= MAX_RUN_AGE:
            _fail_run(
                session,
                run,
                error_code="rate_limited",
                item_error="send_failed",
                now=now,
                meta_error_code=code,
            )
            report.failed += 1
            return kind
        if kind == "rate_limited" or (kind == "transient" and run.attempts < MAX_ATTEMPTS):
            if kind == "rate_limited":
                run.attempts = max(run.attempts - 1, 0)  # Meta's pace, not our failure
                run.next_attempt_at = now + RATE_LIMIT_WAIT
            else:
                run.next_attempt_at = now + transient_wait(run.attempts)
            run.status = "pending"
            run.locked_by = None
            run.locked_at = None
            run.error_code = kind
            run.meta_error_code = code
            for item in _run_items(session, run):
                if item.state == "uploading":
                    _requeue(item, now)
            report.retried += 1
            return kind
        _fail_run(
            session,
            run,
            error_code="send_failed" if kind == "transient" else "meta_error",
            item_error="send_failed",
            now=now,
            meta_error_code=code,
        )
        report.failed += 1
        return kind

    def _settle_send(
        self,
        tenant_id: UUID,
        work: _Work,
        ack: BatchAck | None,
        error: BaseException | None,
        report: CatalogTenantReport,
    ) -> None:
        now = self._clock()
        outcome = ""
        with tenant_session(tenant_id) as session:
            _bounded_locks(session)
            run = self._locked_run(session, work, "sending")
            if run is None:
                logger.warning(
                    "whatsapp.catalog.lost_claim tenant_id=%s run_id=%s", tenant_id, work.run_id
                )
                return
            if error is not None or ack is None:
                outcome = self._settle_error(
                    session,
                    run,
                    error or RuntimeError("no answer"),
                    now=now,
                    phase="send",
                    report=report,
                )
            else:
                items = _run_items(session, run)
                rejected = 0
                for item in items:
                    if item.state == "uploading" and item.retailer_id in ack.rejected_ids:
                        _set_item_error(item, "meta_rejected", now)
                        rejected += 1
                if not ack.handles:
                    _fail_run(
                        session,
                        run,
                        error_code="nothing_ingested",
                        item_error="send_failed",
                        now=now,
                        states=frozenset({"uploading"}),
                    )
                    report.failed += 1
                    outcome = "nothing_ingested"
                else:
                    run.handle = ack.handles[0]
                    run.status = "sent"
                    run.sent_at = now
                    run.next_attempt_at = now + FIRST_POLL
                    run.locked_by = None
                    run.locked_at = None
                    run.error_code = None
                    run.meta_error_code = None
                    report.sent += 1
                    outcome = f"sent rejected={rejected}"
            logger.info(
                "whatsapp.catalog.send tenant_id=%s run_id=%s catalog_row_id=%s requests=%d "
                "status=%s attempts=%d outcome=%s",
                tenant_id,
                run.id,
                run.catalog_row_id,
                len(work.requests),
                run.status,
                run.attempts,
                outcome,
            )

    def _settle_poll(
        self,
        tenant_id: UUID,
        work: _Work,
        status: BatchStatus | None,
        error: BaseException | None,
        report: CatalogTenantReport,
    ) -> None:
        now = self._clock()
        with tenant_session(tenant_id) as session:
            _bounded_locks(session)
            run = self._locked_run(session, work, "sent")
            if run is None:
                logger.warning(
                    "whatsapp.catalog.lost_claim tenant_id=%s run_id=%s", tenant_id, work.run_id
                )
                return
            if error is not None or status is None:
                outcome = self._settle_error(
                    session,
                    run,
                    error or RuntimeError("no answer"),
                    now=now,
                    phase="poll",
                    report=report,
                )
            elif not status.finished:
                elapsed = now - (run.sent_at or now)
                if elapsed >= UNCONFIRMED_AFTER:
                    _fail_run(
                        session,
                        run,
                        error_code="meta_unconfirmed",
                        item_error="meta_unconfirmed",
                        now=now,
                        states=frozenset({"uploading"}),
                    )
                    report.failed += 1
                    outcome = "meta_unconfirmed"
                else:
                    run.next_attempt_at = now + poll_wait(elapsed)
                    run.locked_by = None
                    run.locked_at = None
                    report.retried += 1
                    outcome = "waiting"
            else:
                failed = 0
                for item in _run_items(session, run):
                    if item.state == "uploading":
                        if item.retailer_id in status.invalid_ids:
                            _set_item_error(item, "meta_rejected", now)
                        elif item.pending_op == "delete":
                            item.state = "deleted"
                            item.last_pushed_hash = None
                            item.last_pushed_at = now
                        else:
                            item.state = "synced"
                            item.last_pushed_hash = item.pending_hash
                            item.last_pushed_at = now
                        if item.state != "error":
                            item.pending_op = None
                            item.pending_hash = None
                            item.error_code = None
                            item.meta_error_code = None
                            item.updated_at = now
                    if item.state == "error":
                        failed += 1
                run.items_failed = failed
                _finish(run, "finished" if failed == 0 else "partial", now)
                if failed:
                    report.partial += 1
                else:
                    report.finished += 1
                outcome = run.status
            logger.info(
                "whatsapp.catalog.poll tenant_id=%s run_id=%s catalog_row_id=%s status=%s "
                "items_failed=%s outcome=%s",
                tenant_id,
                run.id,
                run.catalog_row_id,
                run.status,
                run.items_failed,
                outcome,
            )


# --- production wiring --------------------------------------------------------------------


class ResolverCatalogClientFactory:
    """`CredentialResolver.client_for(<the number's connection>)` → a catalog client. The
    token never reaches this module (same as `outbox.ResolverClientFactory`)."""

    def __init__(self, settings: Any, encryptor: Any) -> None:
        self._settings = settings
        self._encryptor = encryptor

    async def __call__(
        self, *, tenant_id: UUID, connection_id: UUID, catalog_id: str
    ) -> WhatsAppCatalogClient:
        from qualify_api.connections.credential_reader import DbCredentialReader  # noqa: PLC0415
        from qualify_api.connections.resolver import InjectingCredentialResolver  # noqa: PLC0415
        from qualify_api.whatsapp.catalog_sync.client import (  # noqa: PLC0415
            HttpWhatsAppCatalogClient,
        )

        resolver = InjectingCredentialResolver(DbCredentialReader(tenant_id), self._encryptor)
        graph = await resolver.client_for(connection_id, scheme=self._settings.graph_auth_scheme)
        return HttpWhatsAppCatalogClient(graph, self._settings.graph_url, catalog_id)


def production_catalog_factory() -> CatalogClientFactory:
    from qualify_api.config import MetaOAuthSettings  # noqa: PLC0415
    from qualify_api.connections.crypto import DevEncryptor  # noqa: PLC0415

    return ResolverCatalogClientFactory(MetaOAuthSettings.from_env(), DevEncryptor())


def scoped_catalog_tick(tenant_ids: Sequence[UUID], *, worker_id: str) -> CatalogSyncTick:
    """A pass over EXACTLY these tenants — localhost validation."""
    from qualify_api.whatsapp.worker import ScopedTenants  # noqa: PLC0415

    return CatalogSyncTick(
        tenants=ScopedTenants(tenant_ids),
        clients=production_catalog_factory(),
        worker_id=worker_id,
    )


def production_catalog_tick(*, worker_id: str) -> CatalogSyncTick:
    """The PRODUCTION pass: every tenant with a catalog."""
    return CatalogSyncTick(
        tenants=CatalogTenants(), clients=production_catalog_factory(), worker_id=worker_id
    )


def log_report(report: CatalogTickReport) -> None:
    for tenant in report.tenants:
        if tenant.claimed or tenant.errors:
            logger.info(
                "whatsapp.catalog.tenant tenant_id=%s claimed=%d sent=%d finished=%d partial=%d "
                "failed=%d deferred=%d retried=%d errors=%d",
                tenant.tenant_id,
                tenant.claimed,
                tenant.sent,
                tenant.finished,
                tenant.partial,
                tenant.failed,
                tenant.deferred,
                tenant.retried,
                len(tenant.errors),
            )
    if report.error:
        logger.info("whatsapp.catalog.pass tick_error=%s", report.error)

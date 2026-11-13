"""The three actions and the screen's read (ADR 48 §6, §9). Nothing here calls Meta: an
action writes a `whatsapp_catalog_sync_runs` row (the outbox) and its items in `queued`;
the worker (`catalog_sync/worker.py`) sends.

Contract with the Galería screen (m-25017357):

    plan_catalog_sync(*, tenant_id, brand_id) -> SyncPlan            # writes nothing
    upload_product(*, tenant_id, brand_id, product_id, requested_by) -> EnqueueResult
    resync_product(*, tenant_id, brand_id, product_id, requested_by) -> EnqueueResult
    sync_all(*, tenant_id, brand_id, requested_by, plan_key) -> EnqueueResult
    catalog_sync_view(*, tenant_id, brand_id) -> CatalogSyncView      # three fixed queries

Refusals are typed exceptions without user text (`CatalogSyncError` subclasses, plus
`CatalogMediaUnavailable`); the screen words them (`qualify-copy-es`).

**Idempotency.** Items are taken `SELECT … FOR UPDATE`; one in `queued`/`uploading` never
enters another run. A run is inserted `ON CONFLICT (tenant_id, request_key) DO NOTHING`
(key: `planning.request_key`). Asking twice without changes enqueues nothing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from qualify_api.whatsapp.catalog_sync.mapping import PIPELINE_VERSION, ineligibility
from qualify_api.whatsapp.catalog_sync.media_url import CatalogMediaUnavailable, media_ready
from qualify_api.whatsapp.catalog_sync.planning import (
    IN_FLIGHT,
    SYNCABLE,
    Decision,
    ItemSnapshot,
    ProductSyncState,
    compute_plan,
    decide_product,
    product_state,
    request_key,
)
from qualify_api.whatsapp.catalog_sync.store import (
    CatalogRow,
    load_catalog,
    load_catalog_with_last_run,
    load_items,
    load_products,
)
from qualify_api.whatsapp.models import (
    WhatsAppCatalogItem,
    WhatsAppCatalogSyncRun,
)

__all__ = [
    "CatalogMediaUnavailable",
    "CatalogNotConnected",
    "CatalogPermissionMissing",
    "CatalogSyncError",
    "CatalogSyncView",
    "EnqueueResult",
    "ItemNotUploaded",
    "PlanChanged",
    "ProductNotEligible",
    "ProductNotFound",
    "ProductSyncState",
    "RunSummary",
    "SyncPlan",
    "catalog_sync_view",
    "plan_catalog_sync",
    "resync_product",
    "sync_all",
    "upload_product",
]

MAX_ITEMS_PER_RUN = 1_000

Trigger = Literal["upload_one", "resync_one", "sync_all"]


# --- errors -------------------------------------------------------------------------------


class CatalogSyncError(Exception):
    """Base of the refusals the screen turns into Spanish copy. Carries no user text."""


class CatalogNotConnected(CatalogSyncError):
    """The brand has no catalog that Qualify writes (none, or `source='manual'`)."""


class CatalogPermissionMissing(CatalogSyncError):
    """The catalog's `access_state` is not `ok` (`missing_permission` or `auth_error`)."""

    def __init__(self, access_state: str) -> None:
        self.access_state = access_state
        super().__init__(f"catalog access_state={access_state}")


class ProductNotFound(CatalogSyncError):
    """No product with that id in this brand."""


class ProductNotEligible(CatalogSyncError):
    """`reason` ∈ `mapping.INELIGIBLE_REASONS`."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"product not eligible: {reason}")


class ItemNotUploaded(CatalogSyncError):
    """«Resincronizar» on a product that has no item in the catalog (use «Cargar»)."""


class PlanChanged(CatalogSyncError):
    """`sync_all`'s `plan_key` is not the current plan's: show the confirmation again."""


# --- results ------------------------------------------------------------------------------


@dataclass(frozen=True)
class SyncPlan:
    new: int
    changed: int
    deletes: int
    unchanged: int
    in_flight: int
    not_eligible: Mapping[str, int]
    plan_key: str


@dataclass(frozen=True)
class EnqueueResult:
    run_ids: tuple[UUID, ...]
    upserts: int
    deletes: int
    unchanged: int
    in_flight: int


@dataclass(frozen=True)
class RunSummary:
    id: UUID
    trigger: str
    status: str
    upserts: int
    deletes: int
    items_failed: int | None
    error_code: str | None
    requested_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True)
class CatalogSyncView:
    connection: Literal["none", "connected", "missing_permission", "auth_error"]
    last_run: RunSummary | None
    products: Mapping[UUID, ProductSyncState] = field(default_factory=dict)


# --- helpers ------------------------------------------------------------------------------


def _writable_catalog(session: Session, brand_id: UUID) -> CatalogRow:
    row = load_catalog(session, brand_id)
    if row is None or row.source != "qualify":
        raise CatalogNotConnected("no catalog Qualify writes for this brand")
    if row.access_state != "ok":
        raise CatalogPermissionMissing(row.access_state)
    return row


def _require_media() -> None:
    if not media_ready():
        raise CatalogMediaUnavailable("catalog photo URLs cannot be built here")


def _snapshot(item: WhatsAppCatalogItem) -> ItemSnapshot:
    return ItemSnapshot(
        id=item.id,
        product_id=item.product_id,
        retailer_id=item.retailer_id,
        state=item.state,
        last_pushed_hash=item.last_pushed_hash,
        error_code=item.error_code,
        sync_version=item.sync_version,
    )


class _Duplicate(Exception):
    """The run's request key already exists: the same request was already enqueued."""


def _chunks(decisions: Sequence[Decision], size: int) -> list[Sequence[Decision]]:
    return [decisions[i : i + size] for i in range(0, len(decisions), size)]


def _enqueue(
    session: Session,
    *,
    catalog: CatalogRow,
    trigger: Trigger,
    decisions: Sequence[Decision],
    requested_by: UUID,
    now: datetime,
) -> tuple[list[UUID], int]:
    """Write the runs and put their items in `queued`. Returns (run ids, decisions that
    lost a race to a concurrent request and were skipped)."""
    run_ids: list[UUID] = []
    skipped = 0
    for chunk in _chunks(decisions, MAX_ITEMS_PER_RUN):
        entries: list[tuple[UUID, Decision]] = []
        for decision in chunk:
            item_id = decision.item_id
            if item_id is None:
                item_id = session.scalar(
                    insert(WhatsAppCatalogItem)
                    .values(
                        tenant_id=catalog.tenant_id,
                        catalog_row_id=catalog.id,
                        product_id=decision.product_id,
                        retailer_id=decision.retailer_id,
                        state="queued",
                        pipeline_version=PIPELINE_VERSION,
                    )
                    .on_conflict_do_nothing()
                    .returning(WhatsAppCatalogItem.id)
                )
                if item_id is None:  # a concurrent request created it first
                    skipped += 1
                    continue
            entries.append((item_id, decision))
        if not entries:
            continue
        key = request_key(
            catalog.id,
            trigger,
            ((i, d.op, d.content_hash or "", d.sync_version) for i, d in entries),
        )
        upserts = sum(1 for _, d in entries if d.op == "upsert")
        run_id = session.scalar(
            insert(WhatsAppCatalogSyncRun)
            .values(
                tenant_id=catalog.tenant_id,
                catalog_row_id=catalog.id,
                request_key=key,
                trigger=trigger,
                status="pending",
                item_ids=[i for i, _ in entries],
                upserts=upserts,
                deletes=len(entries) - upserts,
                next_attempt_at=now,
                requested_by=requested_by,
                requested_at=now,
                pipeline_version=PIPELINE_VERSION,
            )
            .on_conflict_do_nothing(constraint="uq_wa_catalog_run_request_key")
            .returning(WhatsAppCatalogSyncRun.id)
        )
        if run_id is None:
            raise _Duplicate
        for item_id, decision in entries:
            session.execute(
                update(WhatsAppCatalogItem)
                .where(WhatsAppCatalogItem.id == item_id)
                .values(
                    state="queued",
                    pending_op=decision.op,
                    pending_hash=decision.content_hash,
                    sync_version=WhatsAppCatalogItem.sync_version + 1,
                    last_run_id=run_id,
                    error_code=None,
                    meta_error_code=None,
                    pipeline_version=PIPELINE_VERSION,
                    updated_at=now,
                )
            )
        run_ids.append(run_id)
    return run_ids, skipped


def _result(
    decisions: Sequence[Decision],
    run_ids: list[UUID],
    *,
    skipped: int = 0,
    unchanged: int = 0,
    in_flight: int = 0,
) -> EnqueueResult:
    if not run_ids:
        return EnqueueResult((), 0, 0, unchanged, in_flight + len(decisions))
    upserts = sum(1 for d in decisions if d.op == "upsert")
    deletes = len(decisions) - upserts
    # A skipped decision is one a concurrent request already took: counted as in flight.
    return EnqueueResult(
        tuple(run_ids),
        upserts - min(skipped, upserts),
        deletes,
        unchanged,
        in_flight + skipped,
    )


def _now() -> datetime:
    return datetime.now(UTC)


# --- the actions --------------------------------------------------------------------------


def plan_catalog_sync(*, tenant_id: UUID, brand_id: UUID) -> SyncPlan:
    """The dry run «Cargar o sincronizar todos» shows before confirming. Writes nothing."""
    _require_media()
    with tenant_session(tenant_id) as session:
        catalog = _writable_catalog(session, brand_id)
        plan = compute_plan(
            catalog_row_id=catalog.id,
            products=load_products(session, brand_id),
            items=[_snapshot(i) for i in load_items(session, catalog.id)],
            ctx=catalog.mapping_context(),
        )
    return SyncPlan(
        new=plan.count("new"),
        changed=plan.count("changed"),
        deletes=plan.count("delete"),
        unchanged=plan.unchanged,
        in_flight=plan.in_flight,
        not_eligible=plan.not_eligible,
        plan_key=plan.plan_key,
    )


def _one(
    *,
    tenant_id: UUID,
    brand_id: UUID,
    product_id: UUID,
    requested_by: UUID,
    trigger: Trigger,
) -> EnqueueResult:
    with tenant_session(tenant_id) as session:
        catalog = _writable_catalog(session, brand_id)
        product = load_products(session, brand_id, [product_id]).get(product_id)
        if product is None:
            raise ProductNotFound(str(product_id))
        row = session.scalar(
            select(WhatsAppCatalogItem)
            .where(
                WhatsAppCatalogItem.catalog_row_id == catalog.id,
                WhatsAppCatalogItem.product_id == product_id,
            )
            .with_for_update()
        )
        item = _snapshot(row) if row is not None else None
        live = item is not None and item.state in SYNCABLE
        if item is not None and item.state in IN_FLIGHT:
            return EnqueueResult((), 0, 0, 0, 1)
        if trigger == "resync_one" and not live:
            raise ItemNotUploaded(str(product_id))
        reason = ineligibility(product)
        if reason is not None and not (live and not product.is_active):
            raise ProductNotEligible(reason)
        if reason is None:
            _require_media()
        outcome = decide_product(product, item, catalog.mapping_context())
        if not isinstance(outcome, Decision):
            return EnqueueResult((), 0, 0, 1 if outcome == "unchanged" else 0, 0)
        run_ids, skipped = _enqueue(
            session,
            catalog=catalog,
            trigger=trigger,
            decisions=[outcome],
            requested_by=requested_by,
            now=_now(),
        )
        return _result([outcome], run_ids, skipped=skipped)


def _guarded_one(
    *,
    tenant_id: UUID,
    brand_id: UUID,
    product_id: UUID,
    requested_by: UUID,
    trigger: Trigger,
) -> EnqueueResult:
    """`_one`, where a duplicate request (raised out of the transaction, so everything it
    wrote is rolled back) is reported as already in flight."""
    try:
        return _one(
            tenant_id=tenant_id,
            brand_id=brand_id,
            product_id=product_id,
            requested_by=requested_by,
            trigger=trigger,
        )
    except _Duplicate:
        return EnqueueResult((), 0, 0, 0, 1)


def upload_product(
    *, tenant_id: UUID, brand_id: UUID, product_id: UUID, requested_by: UUID
) -> EnqueueResult:
    """«Cargar»: the product must be eligible. Creates its item (`retailer_id` = the
    product's id) or reuses its `deleted` one, and a run of 1. On a product already in the
    catalog it behaves as «Resincronizar» (an unchanged one enqueues nothing)."""
    return _guarded_one(
        tenant_id=tenant_id,
        brand_id=brand_id,
        product_id=product_id,
        requested_by=requested_by,
        trigger="upload_one",
    )


def resync_product(
    *, tenant_id: UUID, brand_id: UUID, product_id: UUID, requested_by: UUID
) -> EnqueueResult:
    """«Resincronizar»: the item must be `synced` or `error`. Unchanged and not in error →
    nothing (`unchanged=1`); product now inactive → its `DELETE`."""
    return _guarded_one(
        tenant_id=tenant_id,
        brand_id=brand_id,
        product_id=product_id,
        requested_by=requested_by,
        trigger="resync_one",
    )


def sync_all(
    *, tenant_id: UUID, brand_id: UUID, requested_by: UUID, plan_key: str
) -> EnqueueResult:
    """«Cargar o sincronizar todos», confirmed: re-plans under lock and refuses with
    `PlanChanged` when the plan is not the one the person saw."""
    try:
        return _sync_all(
            tenant_id=tenant_id, brand_id=brand_id, requested_by=requested_by, plan_key=plan_key
        )
    except _Duplicate:
        # Only reachable when an identical request committed first: nothing new to send.
        return EnqueueResult((), 0, 0, 0, 0)


def _sync_all(
    *, tenant_id: UUID, brand_id: UUID, requested_by: UUID, plan_key: str
) -> EnqueueResult:
    _require_media()
    with tenant_session(tenant_id) as session:
        catalog = _writable_catalog(session, brand_id)
        items = load_items(session, catalog.id, for_update=True)
        plan = compute_plan(
            catalog_row_id=catalog.id,
            products=load_products(session, brand_id),
            items=[_snapshot(i) for i in items],
            ctx=catalog.mapping_context(),
        )
        if plan.plan_key != plan_key:
            raise PlanChanged("the plan changed since it was shown")
        if not plan.decisions:
            return EnqueueResult((), 0, 0, plan.unchanged, plan.in_flight)
        run_ids, skipped = _enqueue(
            session,
            catalog=catalog,
            trigger="sync_all",
            decisions=plan.decisions,
            requested_by=requested_by,
            now=_now(),
        )
        return _result(
            plan.decisions,
            run_ids,
            skipped=skipped,
            unchanged=plan.unchanged,
            in_flight=plan.in_flight,
        )


# --- the screen's read --------------------------------------------------------------------


def _summary(run: WhatsAppCatalogSyncRun) -> RunSummary:
    return RunSummary(
        id=run.id,
        trigger=run.trigger,
        status=run.status,
        upserts=run.upserts,
        deletes=run.deletes,
        items_failed=run.items_failed,
        error_code=run.error_code,
        requested_at=run.requested_at,
        finished_at=run.finished_at,
    )


def catalog_sync_view(*, tenant_id: UUID, brand_id: UUID) -> CatalogSyncView:
    """Galería's per-product state (§4.2) in three fixed queries: catalog + last run;
    products with their primary photo; the catalog's items. Never raises for a missing
    catalog or an unconfigured photo URL (see `planning.product_state`)."""
    with tenant_session(tenant_id) as session:
        found = load_catalog_with_last_run(session, brand_id)
        products = load_products(session, brand_id)
        if found is None:
            return CatalogSyncView(
                connection="none",
                last_run=None,
                products={pid: product_state(p, None, None) for pid, p in products.items()},
            )
        catalog, last_run = found
        items = load_items(session, catalog.id)

    by_product = {i.product_id: _snapshot(i) for i in items if i.product_id is not None}
    ctx = catalog.mapping_context() if media_ready() else None
    if catalog.source != "qualify":
        connection: Literal["none", "connected", "missing_permission", "auth_error"] = "none"
    elif catalog.access_state == "ok":
        connection = "connected"
    elif catalog.access_state == "missing_permission":
        connection = "missing_permission"
    else:
        connection = "auth_error"
    return CatalogSyncView(
        connection=connection,
        last_run=_summary(last_run) if last_run is not None else None,
        products={pid: product_state(p, by_product.get(pid), ctx) for pid, p in products.items()},
    )

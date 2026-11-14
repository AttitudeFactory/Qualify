"""The seam between Galería's WhatsApp layer (m-25017357) and the catalog upload service
(ADR 48, `qualify_api.whatsapp.catalog_sync.service`) — thin, by design.

Every function wraps one service call and returns plain values (str ids, ints), never
ORM rows or UUID-keyed mappings, so the state only holds what Reflex can serialize. The
service's refusals (`CatalogSyncError` subclasses, `CatalogMediaUnavailable`) pass
through untouched: the state words them (`catalog_whatsapp_vm`).

Nothing here calls Meta: the actions only write the outbox the worker drains. Every
function blocks (Postgres) — callers on the event loop run them off-thread.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from qualify_api.catalog.models import BrandProduct
from qualify_api.support import SupportTicket, create_support_request
from qualify_api.whatsapp.catalog_sync import service
from qualify_api.whatsapp.catalog_sync.service import (
    CatalogMediaUnavailable,
    CatalogNotConnected,
    CatalogPermissionMissing,
    CatalogSyncError,
    ItemNotUploaded,
    PlanChanged,
    ProductNotEligible,
    ProductNotFound,
)
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

__all__ = [
    "CatalogMediaUnavailable",
    "CatalogNotConnected",
    "CatalogPermissionMissing",
    "CatalogSyncError",
    "ItemNotUploaded",
    "PlanChanged",
    "ProductNotEligible",
    "ProductNotFound",
    "RunVM",
    "SyncViewVM",
    "PlanVM",
    "SentVM",
    "load_view",
    "plan_all",
    "product_names",
    "request_team",
    "send_all",
    "upload_one",
    "update_one",
]


@dataclass(frozen=True)
class RunVM:
    id: str
    trigger: str
    status: str
    upserts: int
    deletes: int
    items_failed: int
    error_code: str


@dataclass(frozen=True)
class SyncViewVM:
    connection: str
    last_run: RunVM | None = None
    #: product id → (state, reason) for every product of the brand, deleted ones too.
    states: dict[str, tuple[str, str | None]] = field(default_factory=dict)


@dataclass(frozen=True)
class PlanVM:
    new: int
    changed: int
    deletes: int
    unchanged: int
    in_flight: int
    not_eligible: dict[str, int]
    plan_key: str


@dataclass(frozen=True)
class SentVM:
    run_ids: tuple[str, ...]
    upserts: int
    deletes: int
    unchanged: int
    in_flight: int


def _sent(result: service.EnqueueResult) -> SentVM:
    return SentVM(
        run_ids=tuple(str(r) for r in result.run_ids),
        upserts=result.upserts,
        deletes=result.deletes,
        unchanged=result.unchanged,
        in_flight=result.in_flight,
    )


def load_view(tenant_id: UUID, brand_id: UUID) -> SyncViewVM:
    """Galería's per-product state: three fixed queries, never raises for a brand without
    a catalog (`connection="none"`)."""
    view = service.catalog_sync_view(tenant_id=tenant_id, brand_id=brand_id)
    run = view.last_run
    return SyncViewVM(
        connection=view.connection,
        last_run=RunVM(
            id=str(run.id),
            trigger=run.trigger,
            status=run.status,
            upserts=run.upserts,
            deletes=run.deletes,
            items_failed=run.items_failed or 0,
            error_code=run.error_code or "",
        )
        if run is not None
        else None,
        states={str(pid): (s.state, s.reason) for pid, s in view.products.items()},
    )


def plan_all(tenant_id: UUID, brand_id: UUID) -> PlanVM:
    """The counts the confirmation shows. Writes nothing."""
    plan = service.plan_catalog_sync(tenant_id=tenant_id, brand_id=brand_id)
    return PlanVM(
        new=plan.new,
        changed=plan.changed,
        deletes=plan.deletes,
        unchanged=plan.unchanged,
        in_flight=plan.in_flight,
        not_eligible=dict(plan.not_eligible),
        plan_key=plan.plan_key,
    )


def send_all(tenant_id: UUID, brand_id: UUID, user_id: UUID, plan_key: str) -> SentVM:
    """«Sí, actualizar». Raises `PlanChanged` when the plan is not the one confirmed."""
    return _sent(
        service.sync_all(
            tenant_id=tenant_id, brand_id=brand_id, requested_by=user_id, plan_key=plan_key
        )
    )


def upload_one(tenant_id: UUID, brand_id: UUID, user_id: UUID, product_id: UUID) -> SentVM:
    """«Subir a WhatsApp» (on a product already there it behaves as «Actualizar»)."""
    return _sent(
        service.upload_product(
            tenant_id=tenant_id, brand_id=brand_id, product_id=product_id, requested_by=user_id
        )
    )


def update_one(tenant_id: UUID, brand_id: UUID, user_id: UUID, product_id: UUID) -> SentVM:
    """«Actualizar en WhatsApp» / «Intentar de nuevo». A product with no item there goes
    up as a new one instead of failing."""
    try:
        result = service.resync_product(
            tenant_id=tenant_id, brand_id=brand_id, product_id=product_id, requested_by=user_id
        )
    except ItemNotUploaded:
        result = service.upload_product(
            tenant_id=tenant_id, brand_id=brand_id, product_id=product_id, requested_by=user_id
        )
    return _sent(result)


def product_names(tenant_id: UUID, product_ids: Sequence[str]) -> dict[str, str]:
    """Names of products the grid no longer lists (deleted here), for the dialog's
    «Se quitan de WhatsApp…». Under the tenant's RLS."""
    ids = [UUID(p) for p in product_ids]
    if not ids:
        return {}
    with tenant_session(tenant_id) as session:
        rows = session.execute(
            select(BrandProduct.id, BrandProduct.name).where(BrandProduct.id.in_(ids))
        ).all()
    return {str(pid): name for pid, name in rows}


def request_team(
    tenant_id: UUID, *, contact_email: str, message: str, screen: str
) -> SupportTicket:
    """«Pedir mi catálogo de WhatsApp» / «Escribir al equipo»: the same support ticket as
    Configuración's «Escribir al equipo» (topic `other`, only the closed `screen` key).
    Raises `InvalidSupportRequest` on a bad email."""
    return create_support_request(
        tenant_id=tenant_id,
        topic="other",
        contact_email=contact_email,
        contact_whatsapp="",
        message=message,
        context={"screen": screen},
    )

"""The team's write path for the 90-day packs (m-24852129): add one of the three fixed
packs after the payment, list a business's packs, revoke one. Only through
`admin_session`, only from the team's CLI (`just add-pack`, `just packs`,
`just revoke-pack`) — later the Meegle Alta (m-24852131). Never the request path: the
owner can neither create a pack nor read what was paid (decision 8, D19).

`add_pack`, in ONE transaction:

1. resolves the pack by its name — «+2 videos», «+20 creaciones», «+10 vistas previas» —
   from `precios-planes-v1`; any other name or a free quantity is refused before
   anything is written (D23: no free quantities);
2. locks the tenant row and makes sure it has a subscription (ADR 43: a pack belongs to
   the subscription; until the pooled balance of S10 it is spent by the business and
   brand it was granted to);
3. appends the pack (`INSERT … ON CONFLICT (idempotency_key) DO NOTHING`): units read
   from the versioned table, `expires_at = granted_at + 90 days` (D12), who, why, origin;
4. records what was paid in `creation_payments` (default: the table's price, with its
   prices version), invisible to `qualify_app`;
5. closes the «Pedir más» support request it answers, if one is named.

Then it tells the team channel. With the same idempotency key, re-running is a no-op.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4

from qualify_shared.db.admin import admin_session
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from qualify_api.plans.catalog import (
    PACK_DAYS,
    PRICES_VERSION,
    PriceList,
    UnknownPack,
    load_prices,
    pack_by_name,
    pack_name,
)
from qualify_api.plans.models import CreationAllocation, CreationPack, CreationPayment
from qualify_api.plans.notify import TeamNotifier, production_team_notifier
from qualify_api.plans.packs import CREATIONS, DIMENSIONS, PREVIEWS, VIDEOS
from qualify_api.plans.schedule import month_of
from qualify_api.plans.service import TenantNotFound, ensure_subscription

SOURCES = ("manual", "support_request", "meegle_alta")


class PackRefused(ValueError):
    """The pack cannot be added or revoked as asked; nothing was written."""


@dataclass(frozen=True)
class AddPackResult:
    pack_id: UUID
    pack_code: str
    expires_at: datetime
    usd_paid: Decimal
    prices_version: str
    #: False when the idempotency key already existed (nothing new was written).
    changed: bool


@dataclass(frozen=True)
class PackRow:
    id: UUID
    pack_code: str
    granted_at: datetime
    expires_at: datetime
    units: dict[str, int]
    used: dict[str, int]
    source: str
    reason: str
    granted_by: str
    prices_version: str
    usd_paid: Decimal | None
    revoked_at: datetime | None

    def left(self, dimension: str, now: datetime) -> int:
        if self.revoked_at is not None or now >= self.expires_at:
            return 0
        return max(self.units.get(dimension, 0) - self.used.get(dimension, 0), 0)


def _usd(value: Decimal | str | None, default: Decimal) -> Decimal:
    if value is None:
        return default
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except InvalidOperation:
        raise PackRefused(f"{value!r} is not an amount in USD") from None
    if amount < 0:
        raise PackRefused("the amount paid cannot be negative")
    return amount


def _brand(session: Session, tenant_id: UUID, brand_id: UUID | None) -> UUID:
    """The brand the pack is spent by: the given one if it is the tenant's, else the
    tenant's only brand (D14: one business, one brand)."""
    brands = list(
        session.scalars(
            text("SELECT id FROM brands WHERE tenant_id = :tid ORDER BY created_at"),
            {"tid": tenant_id},
        )
    )
    if brand_id is not None:
        if brand_id not in brands:
            raise PackRefused(f"brand {brand_id} is not a brand of tenant {tenant_id}")
        return brand_id
    if not brands:
        raise PackRefused("that business has no brand yet: nothing to add the pack to")
    if len(brands) > 1:
        raise PackRefused("that business has several brands: say which with --brand")
    return brands[0]


def _check_request(session: Session, tenant_id: UUID, request_id: UUID) -> None:
    owner = session.scalar(
        text("SELECT tenant_id FROM support_requests WHERE id = :id"), {"id": request_id}
    )
    if owner != tenant_id:
        raise PackRefused(f"support request {request_id} is not one of tenant {tenant_id}")


def add_pack(
    *,
    tenant_id: UUID,
    pack: str,
    reason: str,
    granted_by: str,
    brand_id: UUID | None = None,
    support_request_id: UUID | None = None,
    meegle_work_item_id: int | None = None,
    usd_paid: Decimal | str | None = None,
    payment_ref: str = "",
    idempotency_key: str | None = None,
    now: datetime | None = None,
    prices: PriceList | None = None,
    notifier: TeamNotifier | None = None,
) -> AddPackResult:
    table = prices or load_prices(PRICES_VERSION)
    try:
        chosen = pack_by_name(pack, table)
    except UnknownPack as exc:
        raise PackRefused(str(exc)) from None
    if not reason.strip() or not granted_by.strip():
        raise PackRefused("a pack needs a reason and who added it")
    amount = _usd(usd_paid, chosen.price)
    source = (
        "support_request"
        if support_request_id is not None
        else "meegle_alta"
        if meegle_work_item_id is not None
        else "manual"
    )
    moment = now or datetime.now(UTC)
    expires = moment + timedelta(days=PACK_DAYS)
    key = idempotency_key or (
        f"support:{support_request_id}:{chosen.code}"
        if support_request_id is not None
        else f"cli:{uuid4()}"
    )
    with admin_session() as session:
        subscription_id = ensure_subscription(session, tenant_id)
        brand = _brand(session, tenant_id, brand_id)
        if support_request_id is not None:
            _check_request(session, tenant_id, support_request_id)
        pack_id = session.scalar(
            insert(CreationPack)
            .values(
                tenant_id=tenant_id,
                brand_id=brand,
                subscription_id=subscription_id,
                pack_code=chosen.code,
                prices_version=table.version,
                creations=chosen.creations,
                videos=chosen.videos,
                previews=chosen.previews,
                granted_at=moment,
                expires_at=expires,
                source=source,
                support_request_id=support_request_id,
                meegle_work_item_id=meegle_work_item_id,
                reason=reason.strip()[:500],
                granted_by=granted_by.strip()[:200],
                idempotency_key=key,
            )
            .on_conflict_do_nothing(constraint="uq_creation_packs_key")
            .returning(CreationPack.id)
        )
        if pack_id is None:
            existing = session.scalar(
                select(CreationPack).where(CreationPack.idempotency_key == key)
            )
            assert existing is not None  # the conflict says it exists
            paid = session.scalar(
                select(CreationPayment.usd_paid).where(CreationPayment.pack_id == existing.id)
            )
            return AddPackResult(
                pack_id=existing.id,
                pack_code=existing.pack_code,
                expires_at=existing.expires_at,
                usd_paid=paid if paid is not None else Decimal(0),
                prices_version=existing.prices_version,
                changed=False,
            )
        session.add(
            CreationPayment(
                tenant_id=tenant_id,
                pack_id=pack_id,
                period_month=month_of(moment),
                usd_paid=amount,
                prices_version=table.version,
                payment_ref=payment_ref.strip()[:200],
                paid_at=moment,
                recorded_by=granted_by.strip()[:200],
            )
        )
        if support_request_id is not None:
            session.execute(
                text("UPDATE support_requests SET status = 'closed' WHERE id = :id"),
                {"id": support_request_id},
            )
        business = session.scalar(
            text("SELECT name FROM tenants WHERE id = :id"), {"id": tenant_id}
        )
    (notifier or production_team_notifier()).notify(
        f"Paquete sumado · {business}: «{pack_name(chosen.code)}», vence el "
        f"{expires:%Y-%m-%d} (USD {amount} · {table.version}). Motivo: {reason.strip()[:200]} "
        f"· por {granted_by.strip()}"
    )
    return AddPackResult(
        pack_id=pack_id,
        pack_code=chosen.code,
        expires_at=expires,
        usd_paid=amount,
        prices_version=table.version,
        changed=True,
    )


def list_packs(tenant_id: UUID) -> list[PackRow]:
    """Every pack of a business, newest first, with what was spent and paid (team only)."""
    with admin_session() as session:
        packs = list(
            session.scalars(
                select(CreationPack)
                .where(CreationPack.tenant_id == tenant_id)
                .order_by(CreationPack.granted_at.desc())
            )
        )
        if not packs:
            return []
        ids = [p.id for p in packs]
        spent: dict[UUID, dict[str, int]] = {}
        for pack_id, dimension, units in session.execute(
            select(
                CreationAllocation.pack_id,
                CreationAllocation.dimension,
                func.sum(CreationAllocation.units - CreationAllocation.reversed_units),
            )
            .where(CreationAllocation.pack_id.in_(ids))
            .group_by(CreationAllocation.pack_id, CreationAllocation.dimension)
        ):
            spent.setdefault(pack_id, {})[dimension] = int(units or 0)
        paid = dict(
            session.execute(
                select(CreationPayment.pack_id, CreationPayment.usd_paid).where(
                    CreationPayment.pack_id.in_(ids)
                )
            ).all()
        )
        return [
            PackRow(
                id=p.id,
                pack_code=p.pack_code,
                granted_at=p.granted_at,
                expires_at=p.expires_at,
                units={CREATIONS: p.creations, VIDEOS: p.videos, PREVIEWS: p.previews},
                used={d: spent.get(p.id, {}).get(d, 0) for d in DIMENSIONS},
                source=p.source,
                reason=p.reason,
                granted_by=p.granted_by,
                prices_version=p.prices_version,
                usd_paid=paid.get(p.id),
                revoked_at=p.revoked_at,
            )
            for p in packs
        ]


def revoke_pack(
    pack_id: UUID,
    *,
    reason: str,
    revoked_by: str,
    now: datetime | None = None,
    notifier: TeamNotifier | None = None,
) -> bool:
    """Stop a pack counting from now on (never deleted). What was already spent of it
    stays spent; False when it does not exist or was already revoked."""
    if not reason.strip() or not revoked_by.strip():
        raise PackRefused("a revocation needs a reason and who made it")
    moment = now or datetime.now(UTC)
    with admin_session() as session:
        row = session.execute(
            text(
                "UPDATE creation_packs SET revoked_at = :at, revoked_by = :by, "
                "revoke_reason = :why WHERE id = :id AND revoked_at IS NULL "
                "RETURNING pack_code, tenant_id"
            ),
            {
                "at": moment,
                "by": revoked_by.strip()[:200],
                "why": reason.strip()[:500],
                "id": pack_id,
            },
        ).one_or_none()
        if row is None:
            return False
        business = session.scalar(
            text("SELECT name FROM tenants WHERE id = :id"), {"id": row.tenant_id}
        )
    (notifier or production_team_notifier()).notify(
        f"Paquete revocado · {business}: «{pack_name(row.pack_code)}». "
        f"Motivo: {reason.strip()[:200]} · por {revoked_by.strip()}"
    )
    return True


__all__ = [
    "SOURCES",
    "AddPackResult",
    "PackRefused",
    "PackRow",
    "TenantNotFound",
    "add_pack",
    "list_packs",
    "revoke_pack",
]

"""«Creaciones del mes» ledger (CREAR-5, m-24848531): the month's balance, the charge
when a generation is asked for, the refund when it does not come out.

The weights are `qualify_creative.creations` (versioned data). This module only keeps the
account: one `creation_charges` row per generation (`draft_id` + `revision`, unique), the
balance = the month's quota − the weights still `charged`, and a refund that turns a row
`refunded` (never deleted — provenance). «Este mes» is the calendar month in the tenant's
zone, the one the owner lives in.

- `charge` takes a per-brand advisory lock, re-reads the month and inserts in one
  transaction, so two asks at once cannot both spend the last creations; a generation
  already charged is not charged again (idempotent by its unique key).
- `refund` is idempotent too: only a `charged` row turns.
- The dollar cap of `creative_engine_config` stays as the team's safety net; the owner
  never sees money (decision 8).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from qualify_creative.creations import CreationPrice, CreationWeights, load_weights
from qualify_shared.db.session import tenant_session
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from qualify_api.creative.models import CreationCharge
from qualify_api.tenancy.models import Tenant

logger = logging.getLogger(__name__)

CHARGED = "charged"
REFUNDED = "refunded"


class NotEnoughCreations(Exception):
    """The month's balance cannot pay for the request: nothing was created."""

    def __init__(self, *, weight: int, left: int) -> None:
        super().__init__(f"needs {weight} creations, {left} left")
        self.weight = weight
        self.left = left

    @property
    def missing(self) -> int:
        return max(self.weight - self.left, 0)


def not_enough_text(missing: int) -> str:
    """What the owner reads when the month cannot pay (CREAR-5): never a half creation."""
    if missing == 1:
        return "Te falta 1 creación este mes."
    return f"Te faltan {missing} creaciones este mes."


@dataclass(frozen=True)
class CreationsBalance:
    """What the owner reads: «Te quedan {left} de {quota} este mes»."""

    quota: int
    used: int
    weights_version: str

    @property
    def left(self) -> int:
        return max(self.quota - self.used, 0)

    def can_pay(self, weight: int) -> bool:
        return weight <= self.left


class CreationsLedger(Protocol):
    def balance(self, *, tenant_id: UUID, brand_id: UUID) -> CreationsBalance: ...

    def charge(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        draft_id: UUID,
        revision: int,
        price: CreationPrice,
    ) -> bool:
        """Charge one generation; False when it was already charged. Raises
        `NotEnoughCreations` when the month cannot pay for it."""
        ...

    def refund(self, *, tenant_id: UUID, draft_id: UUID, revision: int, reason: str) -> bool:
        """Give back one generation's creations; False when nothing was charged."""
        ...


def month_start(now: datetime, zone: str) -> date:
    """The first day of `now`'s month in `zone` (UTC when the zone is unknown)."""
    try:
        tz = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("UTC")
    local = now.astimezone(tz)
    return date(local.year, local.month, 1)


def _brand_lock_key(brand_id: UUID) -> int:
    """A stable signed 64-bit key for `pg_advisory_xact_lock` (one per brand)."""
    return int.from_bytes(brand_id.bytes[:8], "big", signed=True)


class PostgresCreationsLedger:
    def __init__(
        self,
        *,
        weights: CreationWeights | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._weights = weights or load_weights()
        self._clock = clock or (lambda: datetime.now(UTC))

    def _period(self, session: Session, tenant_id: UUID) -> date:
        tenant = session.get(Tenant, tenant_id)
        zone = tenant.timezone if tenant is not None and tenant.timezone else "UTC"
        return month_start(self._clock(), zone)

    @staticmethod
    def _used(session: Session, tenant_id: UUID, brand_id: UUID, period: date) -> int:
        total = session.scalar(
            select(func.coalesce(func.sum(CreationCharge.weight), 0)).where(
                CreationCharge.tenant_id == tenant_id,
                CreationCharge.brand_id == brand_id,
                CreationCharge.period_month == period,
                CreationCharge.status == CHARGED,
            )
        )
        return int(total or 0)

    def balance(self, *, tenant_id: UUID, brand_id: UUID) -> CreationsBalance:
        with tenant_session(tenant_id) as session:
            period = self._period(session, tenant_id)
            used = self._used(session, tenant_id, brand_id, period)
        return CreationsBalance(
            quota=self._weights.monthly_quota, used=used, weights_version=self._weights.version
        )

    def charge(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        draft_id: UUID,
        revision: int,
        price: CreationPrice,
    ) -> bool:
        with tenant_session(tenant_id) as session:
            session.execute(
                text("SELECT pg_advisory_xact_lock(:key)"), {"key": _brand_lock_key(brand_id)}
            )
            already = session.scalar(
                select(CreationCharge.id).where(
                    CreationCharge.draft_id == draft_id, CreationCharge.revision == revision
                )
            )
            if already is not None:
                return False
            period = self._period(session, tenant_id)
            used = self._used(session, tenant_id, brand_id, period)
            left = max(self._weights.monthly_quota - used, 0)
            if price.weight > left:
                raise NotEnoughCreations(weight=price.weight, left=left)
            result = session.execute(
                insert(CreationCharge)
                .values(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    draft_id=draft_id,
                    revision=revision,
                    request_kind=price.request_kind,
                    weight=price.weight,
                    monthly_quota=self._weights.monthly_quota,
                    weights_version=self._weights.version,
                    pricing_table_version=self._weights.pricing_table_version,
                    period_month=period,
                    status=CHARGED,
                )
                .on_conflict_do_nothing(constraint="uq_creation_charges_generation")
            )
            return bool(result.rowcount)

    def refund(self, *, tenant_id: UUID, draft_id: UUID, revision: int, reason: str) -> bool:
        with tenant_session(tenant_id) as session:
            return refund_in_session(session, ((draft_id, revision),), reason, self._clock()) > 0


def refund_in_session(
    session: Session,
    generations: Iterable[tuple[UUID, int]],
    reason: str,
    now: datetime | None = None,
) -> int:
    """Refund generations inside a caller's transaction (the reaper's); returns how many
    rows turned. Only a `charged` row turns, so a second refund is a no-op."""
    turned = 0
    at = now or datetime.now(UTC)
    for draft_id, revision in generations:
        row = session.scalar(
            select(CreationCharge)
            .where(
                CreationCharge.draft_id == draft_id,
                CreationCharge.revision == revision,
                CreationCharge.status == CHARGED,
            )
            .with_for_update()
        )
        if row is None:
            continue
        row.status = REFUNDED
        row.refund_reason = reason[:200]
        row.refunded_at = at
        turned += 1
    return turned


@dataclass
class _MemoryRow:
    brand_id: UUID
    price: CreationPrice
    status: str = CHARGED
    reason: str | None = None


class InMemoryCreationsLedger:
    """The same contract without a database — for tests and local fakes."""

    def __init__(self, *, weights: CreationWeights | None = None, used: int = 0) -> None:
        self._weights = weights or load_weights()
        self._opening = used
        self.rows: dict[tuple[UUID, int], _MemoryRow] = {}

    def _used(self, brand_id: UUID) -> int:
        return self._opening + sum(
            row.price.weight
            for row in self.rows.values()
            if row.brand_id == brand_id and row.status == CHARGED
        )

    def balance(self, *, tenant_id: UUID, brand_id: UUID) -> CreationsBalance:
        return CreationsBalance(
            quota=self._weights.monthly_quota,
            used=self._used(brand_id),
            weights_version=self._weights.version,
        )

    def charge(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        draft_id: UUID,
        revision: int,
        price: CreationPrice,
    ) -> bool:
        if (draft_id, revision) in self.rows:
            return False
        left = max(self._weights.monthly_quota - self._used(brand_id), 0)
        if price.weight > left:
            raise NotEnoughCreations(weight=price.weight, left=left)
        self.rows[(draft_id, revision)] = _MemoryRow(brand_id=brand_id, price=price)
        return True

    def refund(self, *, tenant_id: UUID, draft_id: UUID, revision: int, reason: str) -> bool:
        row = self.rows.get((draft_id, revision))
        if row is None or row.status != CHARGED:
            return False
        row.status = REFUNDED
        row.reason = reason
        return True


__all__ = [
    "CHARGED",
    "REFUNDED",
    "CreationsBalance",
    "CreationsLedger",
    "InMemoryCreationsLedger",
    "NotEnoughCreations",
    "PostgresCreationsLedger",
    "month_start",
    "not_enough_text",
    "refund_in_session",
]

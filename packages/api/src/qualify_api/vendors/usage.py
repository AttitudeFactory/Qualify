"""Per-business usage of a paid vendor, and the caps summed over it (ADR 42 R5, the
generic half; m-24946121, `docs/diseno-modulo-creadores.md` §8.4).

`vendor_usage_events` (migration 0117, RLS) holds one row per paid call charged to the
tenant that triggered it. `record_usage` writes it idempotently on
`UNIQUE (tenant_id, request_key)` — a retry with the same key charges nothing twice —
and `credits_used` / `budget` sum it over the business's day and month, in the
business's own time zone (`tenants.timezone`). Every function takes an open
`tenant_session`, so a caller can put the charge in the same transaction as the work.

The Creators module is the first caller; «Ideas para tus reels» (R5) reuses the same
pieces with its own features and caps.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import text
from sqlalchemy.orm import Session

#: ScrapeCreators' price per credit on the Freelance plan (ADR 42 §1.3), and the name of
#: that price table — the provenance of `usd_estimate`.
SCRAPECREATORS_USD_PER_CREDIT = Decimal("0.00188")
SCRAPECREATORS_PRICING_VERSION = "scrapecreators-freelance-2026-10"


@dataclass(frozen=True)
class CreditBudget:
    """What a business has used of a cap, today and this month (its own time zone)."""

    day_used: int
    day_cap: int
    month_used: int
    month_cap: int

    def remaining(self) -> int:
        return max(min(self.day_cap - self.day_used, self.month_cap - self.month_used), 0)


def record_usage(
    session: Session,
    *,
    tenant_id: UUID,
    brand_id: UUID | None,
    vendor: str,
    feature: str,
    credits: int,
    request_key: str,
    payload_id: UUID | None,
    usd_per_credit: Decimal,
    pricing_table_version: str,
) -> bool:
    """Charge one paid call to the tenant. False when `request_key` was already charged
    (`ON CONFLICT DO NOTHING`): the retry of the same call costs the business nothing."""
    if credits < 0:
        raise ValueError("credits must not be negative")
    if not request_key:
        raise ValueError("request_key must not be empty")
    row = session.execute(
        text(
            "INSERT INTO vendor_usage_events (tenant_id, brand_id, vendor, feature, credits, "
            "usd_estimate, pricing_table_version, request_key, payload_id) VALUES "
            "(:tenant, :brand, :vendor, :feature, :credits, :usd, :pricing, :key, :payload) "
            "ON CONFLICT ON CONSTRAINT uq_vendor_usage_request DO NOTHING RETURNING id"
        ),
        {
            "tenant": tenant_id,
            "brand": brand_id,
            "vendor": vendor,
            "feature": feature,
            "credits": credits,
            "usd": usd_per_credit * credits,
            "pricing": pricing_table_version,
            "key": request_key,
            "payload": payload_id,
        },
    ).first()
    return row is not None


def credits_used(
    session: Session, *, tenant_id: UUID, features: Collection[str], since: datetime
) -> int:
    """Credits the tenant spent on `features` from `since` on."""
    value = session.execute(
        text(
            "SELECT COALESCE(SUM(credits), 0) FROM vendor_usage_events "
            "WHERE tenant_id = :tenant AND feature = ANY(:features) AND created_at >= :since"
        ),
        {"tenant": tenant_id, "features": list(features), "since": since},
    ).scalar_one()
    return int(value)


def zone(name: str | None) -> ZoneInfo:
    """The business's zone; UTC when it is unset or unknown (never the server's)."""
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def period_starts(now: datetime, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """`(start of today, start of this month)` in `tz`, as aware datetimes."""
    local = now.astimezone(tz)
    day = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return day, day.replace(day=1)


def tenant_zone(session: Session, tenant_id: UUID) -> ZoneInfo:
    name = session.execute(
        text("SELECT timezone FROM tenants WHERE id = :tenant"), {"tenant": tenant_id}
    ).scalar()
    return zone(name)


def budget(
    session: Session,
    *,
    tenant_id: UUID,
    features: Collection[str],
    now: datetime,
    day_cap: int,
    month_cap: int,
) -> CreditBudget:
    """The tenant's use of `features` against its day and month caps, the day and the
    month being those of the tenant's own zone."""
    day, month = period_starts(now, tenant_zone(session, tenant_id))
    return CreditBudget(
        day_used=credits_used(session, tenant_id=tenant_id, features=features, since=day),
        day_cap=day_cap,
        month_used=credits_used(session, tenant_id=tenant_id, features=features, since=month),
        month_cap=month_cap,
    )


__all__ = [
    "SCRAPECREATORS_PRICING_VERSION",
    "SCRAPECREATORS_USD_PER_CREDIT",
    "CreditBudget",
    "budget",
    "credits_used",
    "period_starts",
    "record_usage",
    "tenant_zone",
    "zone",
]

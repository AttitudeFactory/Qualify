"""Market size when creating a promotion (m-25091388, 0177).

Meta gives only the audience size range (`reachestimate`, already read by the wizard's
audience step: `audience_service.estimate_audience` → `ReachEstimate`); its spend→results
curve is gone (docs/discovery-asesor-inversion-meta.md §1), so nothing here reads
`delivery_estimate`. From that range we derive, with the versioned table
`data/mercado-v1.json` (PROVISIONAL hypotheses, not Meta's numbers):

- the market class on Meta's upper bound: `pequeno` / `mediano` / `grande`;
- people the budget may reach = min(budget / CPM × 1.000 / frequency, Meta's upper bound);
- `saturated` when that is ≥ 70 % of Meta's lower bound («ya llegarías a casi todo tu público»).

No range from Meta → no estimate at all (None): never our own uncapped number. Unpublished
pieces (whole-country audience) are out of scope for v1.

API for the Reflex layer (wrap each call in `acting_login(auth_user_id)`):

- `estimate_market(tenant_id=, brand_id=, reach=, country=, currency=, budget_minor=None,
  days=None)` → `MarketEstimate | None`. `reach` is the `ReachEstimate` the audience step
  already has (no second Meta call); `country` is `AudienceDraft.location.country_code`;
  `currency` the ad account's. None when Meta gave no range. `people` is None when the budget
  or days are missing or we have no CPM for that country and currency (UI: «Todavía no
  tenemos datos de anuncios en …»). Display rounding is the UI's.
- `record_market_estimate(tenant_id=, promotion_id=, estimate=)` → bool: keeps the estimate's
  provenance with the prepared promotion (call after `PromotionWizard.prepare` returns). The
  first record wins; repeating it is harmless.

Refusals are `MarketEstimateUnavailable` with a Spanish message to show as is.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads.audience import ReachEstimate
from qualify_api.tenancy.acting import current_acting_login, require_acting_member

TABLE_VERSION = "mercado-v1"
_DATA = Path(__file__).parent / "data"
CLASSES = ("pequeno", "mediano", "grande")

LOGIN_NEEDED = "Vuelve a iniciar sesión para ver a cuántas personas podrías llegar."
PROMOTION_GONE = "Esta promoción ya no está disponible en tu negocio."


class MarketEstimateUnavailable(ValueError):
    """A safe Spanish explanation for the owner."""


@dataclass(frozen=True)
class MarketTable:
    version: str
    cpm: dict[str, tuple[str, int]]  # country → (currency, CPM in hundredths)
    weekly_frequency: Decimal
    own_cpm_min_impressions: int
    pequeno_below: int
    grande_above: int
    saturation_share_of_lower: Decimal


@lru_cache(maxsize=4)
def load_table(version: str = TABLE_VERSION) -> MarketTable:
    raw = json.loads((_DATA / f"{version}.json").read_text(encoding="utf-8"))
    if raw["version"] != version:
        raise ValueError(f"market table declares {raw['version']!r}, expected {version!r}")
    table = MarketTable(
        version,
        {k: (v["currency"], int(v["cpm_minor"])) for k, v in raw["cpm"].items()},
        Decimal(raw["weekly_frequency"]),
        int(raw["own_cpm_min_impressions"]),
        int(raw["classes"]["pequeno_below"]),
        int(raw["classes"]["grande_above"]),
        Decimal(raw["saturation_share_of_lower"]),
    )
    if not (
        all(cpm > 0 for _, cpm in table.cpm.values())
        and table.weekly_frequency > 0
        and 0 < table.pequeno_below <= table.grande_above
        and 0 < table.saturation_share_of_lower <= 1
    ):
        raise ValueError(f"market table {version} is inconsistent")
    return table


@dataclass(frozen=True)
class Cpm:
    minor: int  # cost per 1.000 impressions, in hundredths of `currency`
    currency: str
    source: str  # "own" (the brand's measured Insights) | "table"


@dataclass(frozen=True)
class MarketEstimate:
    audience_lower: int
    audience_upper: int
    market_class: str
    people: int | None  # capped at audience_upper; None = no budget/days or no CPM
    saturated: bool
    currency: str
    cpm_minor: int | None
    cpm_source: str | None
    table_version: str
    audience_hash: str = ""

    def provenance(self) -> dict[str, Any]:
        return asdict(self)


def market_class(upper: int, table: MarketTable) -> str:
    if upper < table.pequeno_below:
        return "pequeno"
    return "grande" if upper > table.grande_above else "mediano"


def estimate(
    *,
    lower: int | None,
    upper: int | None,
    budget_minor: int | None,
    days: int | None,
    currency: str,
    cpm: Cpm | None,
    table: MarketTable,
    audience_hash: str = "",
) -> MarketEstimate | None:
    """Pure: Meta's range + budget → class and people reached. No range → None."""
    if type(lower) is not int or type(upper) is not int or not 0 <= lower <= upper:
        return None
    if cpm is not None and cpm.currency != currency:
        raise ValueError("CPM currency differs from the budget currency")
    people = None
    if cpm is not None and type(budget_minor) is int and budget_minor > 0:
        if type(days) is not int or days <= 0:
            raise ValueError("days must be a positive integer")
        frequency = max(Decimal(1), table.weekly_frequency * days / 7)
        impressions = Decimal(budget_minor) * 1000 / cpm.minor
        people = min(int(impressions / frequency), upper)
    saturated = people is not None and (
        people >= table.saturation_share_of_lower * lower if lower else people >= upper
    )
    return MarketEstimate(
        lower,
        upper,
        market_class(upper, table),
        people,
        saturated,
        currency,
        cpm.minor if cpm and people is not None else None,
        cpm.source if cpm and people is not None else None,
        table.version,
        audience_hash,
    )


def _member(tenant_id: UUID) -> None:
    if current_acting_login() is None:
        raise MarketEstimateUnavailable(LOGIN_NEEDED)
    require_acting_member(tenant_id)


def own_cpm(session: Any, brand_id: UUID, currency: str, table: MarketTable) -> Cpm | None:
    """The brand's measured CPM from its promotions' Insights (`ad_promotion_insights`, spend
    in major units as Meta reports it), once there are enough impressions to trust it."""
    spend, impressions = session.execute(
        text(
            "SELECT sum((i.metrics->>'spend')::numeric),sum((i.metrics->>'impressions')::numeric) "
            "FROM ad_promotion_insights i JOIN ad_promotions p "
            "ON p.id=i.promotion_id AND p.tenant_id=i.tenant_id "
            "WHERE p.brand_id=:brand AND i.currency=:currency "
            "AND i.metrics->>'spend' IS NOT NULL AND i.metrics->>'impressions' IS NOT NULL"
        ),
        {"brand": brand_id, "currency": currency},
    ).one()
    if not impressions or impressions < table.own_cpm_min_impressions or not spend:
        return None
    minor = int(Decimal(spend) * 100_000 / Decimal(impressions))
    return Cpm(minor, currency, "own") if minor > 0 else None  # a 0 CPM would divide by 0


def estimate_market(
    *,
    tenant_id: UUID,
    brand_id: UUID,
    reach: ReachEstimate,
    country: str,
    currency: str,
    budget_minor: int | None = None,
    days: int | None = None,
    table_version: str = TABLE_VERSION,
) -> MarketEstimate | None:
    """See the module docstring. Own CPM first, else the table's for that country only when
    its currency is the account's (never a currency conversion)."""
    _member(tenant_id)
    if not reach.ready:
        return None
    table = load_table(table_version)
    with tenant_session(tenant_id, independent=True) as session:
        cpm = own_cpm(session, brand_id, currency, table)
    if cpm is None and table.cpm.get(country, ("", 0))[0] == currency:
        cpm = Cpm(table.cpm[country][1], currency, "table")
    try:
        return estimate(
            lower=reach.lower,
            upper=reach.upper,
            budget_minor=budget_minor,
            days=days,
            currency=currency,
            cpm=cpm,
            table=table,
            audience_hash=reach.audience_hash,
        )
    except ValueError:
        raise MarketEstimateUnavailable(
            "Revisa las fechas para calcular a cuántas personas llegarías."
        ) from None


def record_market_estimate(
    *, tenant_id: UUID, promotion_id: UUID, estimate: MarketEstimate
) -> bool:
    """Keep the estimate shown before approval with the promotion. A separate row, not the
    approval snapshot: `ad_promotions` is immutable and its request hash names the Meta
    objects, while Meta's range moves between retries. True when this call stored it."""
    _member(tenant_id)
    with tenant_session(tenant_id, independent=True) as session:
        if (
            session.execute(
                text("SELECT 1 FROM ad_promotions WHERE id=:id"), {"id": promotion_id}
            ).scalar()
            is None
        ):
            raise MarketEstimateUnavailable(PROMOTION_GONE)
        return bool(
            session.execute(
                text(
                    "INSERT INTO ad_promotion_market_estimates "
                    "(tenant_id,promotion_id,market_class,table_version,cpm_source,estimate) "
                    "VALUES (:tenant,:id,:class,:version,:source,CAST(:estimate AS jsonb)) "
                    "ON CONFLICT (promotion_id) DO NOTHING"
                ),
                {
                    "tenant": tenant_id,
                    "id": promotion_id,
                    "class": estimate.market_class,
                    "version": estimate.table_version,
                    "source": estimate.cpm_source,
                    "estimate": json.dumps(estimate.provenance()),
                },
            ).rowcount
        )

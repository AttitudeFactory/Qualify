"""Suggested starting budget for a promotion (m-25091389, 0178).

Meta gives no spend curve and no budget per business size or niche
(docs/discovery-asesor-inversion-meta.md §1, §11): the suggestion comes from our versioned,
PROVISIONAL table `data/presupuesto-v1.json` (market class × business size → daily amount,
days, pieces), bounded by the only numbers that are not ours:

- floor: the ad account's daily minimum, read live from `act_<id>/minimum_budgets` before the
  promotion exists (same parser as the budget-edit floor, `live_management.meta_daily_minimum`;
  converted with `money.from_meta`, COP/USD/UYU); never hard-coded;
- ceiling: what is left of the owner's monthly cap this calendar month (cap − what the brand's
  promotions already spent this month per our Insights; unknown spend → not subtracted, said
  in the reasons). The suggested total never passes it (UX + Raul, 2026-11-22). Softer: the
  weekly capacity (weekly new clients × max cost per client / 7).

Rules (UX `.claude/ux-presupuesto-recomendado-2026-11-22.md`, Raul's decisions 2026-11-22):
days = the wizard's period, at least the table's 7 and at most 30; total = daily × days. When
Meta's minimum × days does not fit the cap, fewer days are suggested (≥ 1); when not even one
day fits, there is no amount (`daily_minor` None, `fits` False) and the first reason explains.
With previous promotions the suggestion is the TOTAL split across 2–3 pieces, each piece at or
above Meta's minimum (fewer pieces when it does not split).

Business size = the profile's weekly new clients (`business_size` in the table). Without a
profile (or with a profile in another currency) the small-business row is used and
`general_values` is True. shortcut: no rubro dimension — Tu marca keeps it as free text and
there are no sourced numbers per rubro; add one when we have measured cost per client per rubro.

API for the Reflex layer (wrap each call in `acting_login(auth_user_id)`):

- `await suggest_budget(tenant_id=, publish_attempt_id=, market=None, start_time=None,
  end_time=None, daily_minimum_minor=None)` → `BudgetSuggestion`. `market` is the
  `MarketEstimate` the wizard already has (or None); dates are the wizard's (aware), else the
  table's 7 days. Reads Meta's daily minimum once (one GET on the source's selected ad
  account, nothing created or spent); pass the previous suggestion's
  `meta_daily_minimum_minor` back as `daily_minimum_minor` when only the dates or the market
  change, so there is no second call. Phrase: «Te sugerimos {money(daily)} al día durante
  {days} días (total {money(total)})»; show the first two `reasons`, then `pieces_note`, and
  the «valores generales» line when `general_values`. The field gets `piece_total_minor`
  (this promotion's share; equal to `total_minor` with one piece). When `days` differs from
  the period on screen the button moves the end date. `cap_remaining_minor` lets the UI say
  «Este monto pasa tu tope…». The owner can always type another amount.
- `record_budget_suggestion(tenant_id=, promotion_id=, suggestion=)` → bool: keeps the
  suggestion shown, its inputs and whether the approved budget equals `piece_total_minor`
  (call after `PromotionWizard.prepare` returns). First record wins; repeating is harmless.
- `money(minor, currency)` → «$25.000 COP», «$10 USD», «$400 UYU» (the app-wide format).

Money is in hundredths of the account currency. Refusals are `BudgetSuggestionUnavailable`
with a Spanish message to show as is (UX: «No pudimos preparar una sugerencia…» instead of the
card; the wizard goes on without a suggestion).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads.errors import MarketingError
from qualify_api.ads.investment_profile import InvestmentProfile, load_investment_profile
from qualify_api.ads.market_size import CLASSES, MarketEstimate
from qualify_api.ads.money import from_meta, money_display
from qualify_api.ads.wizard import WizardUnavailable
from qualify_api.tenancy.acting import current_acting_login, require_acting_member

TABLE_VERSION = "presupuesto-v1"
_DATA = Path(__file__).parent / "data"
SIZES = ("pequeno", "grande")
BOUNDS = ("meta_min", "monthly_cap", "max_cost", "none")
MAX_DAYS = 30  # the cap is monthly: a suggestion never spans more than a month (UX §3)
# Round amounts (UX §3): COP to thousands, UYU to tens, everything else to the whole unit.
_STEP_MINOR = {"COP": 100_000, "UYU": 1_000}

LOGIN_NEEDED = "Vuelve a iniciar sesión para ver cuánto te sugerimos invertir."
PROMOTION_GONE = "Esta promoción ya no está disponible en tu negocio."
CURRENCY_UNSUPPORTED = "Todavía no tenemos una sugerencia de presupuesto para esta moneda."
MINIMUM_UNAVAILABLE = "No pudimos preparar una sugerencia. Escribe el monto que quieras."
DATES_INVALID = "Revisa las fechas: el final debe ser después del inicio."


class BudgetSuggestionUnavailable(ValueError):
    """A safe Spanish explanation for the owner."""


@dataclass(frozen=True)
class BudgetTable:
    version: str
    daily_minor: dict[str, dict[str, dict[str, int]]]  # currency → size → market class
    grande_from_weekly: int
    default_class: str
    days: int
    pieces_first: int
    pieces_with_history: int


@lru_cache(maxsize=4)
def load_table(version: str = TABLE_VERSION) -> BudgetTable:
    raw = json.loads((_DATA / f"{version}.json").read_text(encoding="utf-8"))
    if raw["version"] != version:
        raise ValueError(f"budget table declares {raw['version']!r}, expected {version!r}")
    daily = {c: v for c, v in raw["daily_minor"].items() if c != "source"}
    table = BudgetTable(
        version,
        daily,
        int(raw["business_size"]["grande_from_weekly_new_clients"]),
        raw["default_market_class"],
        int(raw["days"]),
        int(raw["pieces"]["first"]),
        int(raw["pieces"]["with_history"]),
    )
    if not (
        7 <= table.days <= MAX_DAYS
        and table.default_class in CLASSES
        and 0 < table.pieces_first <= table.pieces_with_history
        and table.grande_from_weekly > 0
        and all(
            set(sizes) == set(SIZES)
            and all(set(row) == set(CLASSES) for row in sizes.values())
            and all(type(v) is int and v > 0 for row in sizes.values() for v in row.values())
            for sizes in daily.values()
        )
    ):
        raise ValueError(f"budget table {version} is inconsistent")
    return table


@dataclass(frozen=True)
class BudgetSuggestion:
    daily_minor: int | None  # all pieces together; None = not even one day fits the cap
    days: int
    total_minor: int | None
    pieces: int
    piece_daily_minor: int | None
    piece_total_minor: int | None  # what «Usar este monto» puts in this promotion's field
    currency: str
    bounded_by: str  # BOUNDS
    fits: bool
    reasons: tuple[str, ...]  # most important first; the UI shows two
    pieces_note: str | None
    general_values: bool  # no profile: «Usamos valores generales…» + link to the profile
    cap_remaining_minor: int | None  # what is left of the monthly cap; None = no profile
    table_version: str
    meta_daily_minimum_minor: int
    inputs: dict[str, Any] = field(default_factory=dict)

    def provenance(self) -> dict[str, Any]:
        return asdict(self)


money = money_display  # the one app-wide format (ads/money.py); kept for callers


def schedule_days(start: datetime, end: datetime) -> int:
    """24-h blocks between the wizard's dates, rounded up (as the budget-edit floor counts)."""
    if end <= start:
        raise ValueError("end before start")
    return -(-(end - start) // timedelta(days=1))


def _down(amount: int, step: int) -> int:
    return amount // step * step


def _up(amount: int, step: int) -> int:
    return -(-amount // step) * step


def suggest(
    *,
    profile: InvestmentProfile | None,
    market: MarketEstimate | None,
    meta_daily_minimum_minor: int,
    currency: str,
    days: int | None = None,
    has_previous_promotions: bool = False,
    spent_this_month_minor: int | None = 0,
    table: BudgetTable | None = None,
) -> BudgetSuggestion:
    """Pure: table → bounded amount. `days` = the wizard's period (None: the table's).
    `spent_this_month_minor` None = unknown (not subtracted, said in the reasons)."""
    table = table or load_table()
    if currency not in table.daily_minor:
        raise ValueError(f"no budget row for {currency}")
    minimum = meta_daily_minimum_minor
    if type(minimum) is not int or minimum <= 0:
        raise ValueError("Meta's daily minimum must be a positive integer")
    if days is not None and (type(days) is not int or days <= 0):
        raise ValueError("days must be a positive integer")
    if profile is not None and profile.currency != currency:
        profile = None  # never mix currencies: general values instead
    step = _STEP_MINOR.get(currency, 100)
    days = min(max(days or table.days, table.days), MAX_DAYS)
    size = (
        "grande"
        if profile is not None and profile.weekly_new_clients >= table.grande_from_weekly
        else "pequeno"
    )
    market_class = market.market_class if market is not None else table.default_class
    daily: int | None = table.daily_minor[currency][size][market_class]
    bounded_by, fits = "none", True
    head: list[str] = []  # bound reasons, shown first
    remaining = None
    cap_label = ""
    if profile is not None:
        cap = profile.monthly_cap_minor
        spent = spent_this_month_minor or 0
        remaining = max(cap - spent, 0)
        cap_label = (
            f"lo que te queda de tu tope este mes ({money(remaining, currency)} de "
            f"{money(cap, currency)})"
            if spent
            else f"tu tope de {money(cap, currency)} al mes"
        )
        capacity = _down(profile.weekly_new_clients * profile.max_cost_per_client_minor // 7, step)
        if capacity < daily:
            daily, bounded_by = capacity, "max_cost"
        if daily * days > remaining:
            daily, bounded_by = _down(remaining // days, step), "monthly_cap"
    if daily < minimum:
        rounded = _up(minimum, step)
        if remaining is not None and minimum * days > remaining:
            fitting = remaining // minimum
            bounded_by = "monthly_cap"
            if fitting == 0:
                daily, fits = None, False
                head.append(
                    f"Meta pide al menos {money(minimum, currency)} al día en tu cuenta, y "
                    + (
                        f"te quedan {money(remaining, currency)} de tu tope este mes"
                        if spent_this_month_minor
                        else f"tu tope es de {money(remaining, currency)} al mes"
                    )
                    + ". Con ese tope no alcanza para un anuncio. Puedes cambiar tu tope o "
                    "escribir el monto que quieras."
                )
            else:
                days = fitting
                daily = rounded if rounded * days <= remaining else minimum
                head += [
                    "Es lo mínimo al día que Meta acepta en tu cuenta.",
                    f"Con {cap_label}, caben {days} día{'s' if days > 1 else ''}.",
                ]
        else:
            daily = rounded if remaining is None or rounded * days <= remaining else minimum
            bounded_by = "meta_min"
            head.append("Es lo mínimo al día que Meta acepta en tu cuenta.")
    elif bounded_by == "monthly_cap":
        head.append(f"Lo ajustamos a {cap_label}.")
    elif bounded_by == "max_cost":
        head.append(
            "Lo ajustamos a los clientes nuevos que puedes atender por semana y a lo máximo "
            "que te conviene pagar por cada uno."
        )
    reasons = head
    if daily is not None:
        if market is not None:
            reasons.append(
                "Tu público es pequeño: con más dinero solo repetirías el anuncio a las mismas "
                "personas."
                if market_class == "pequeno"
                else "Alcanza para una primera prueba sin gastar de más."
            )
        if profile is not None and bounded_by in {"none", "meta_min", "max_cost"}:
            reasons.append(f"Cabe en {cap_label}.")
        if market is None and profile is None:
            reasons.append("Es un monto prudente para una primera prueba.")
    if profile is not None and spent_this_month_minor is None:
        reasons.append(
            "Todavía no sabemos cuánto gastaron este mes tus otros anuncios, así que no lo "
            "restamos de tu tope."
        )
    # Split the total across pieces, each at least Meta's minimum (Raul, 2026-11-22).
    pieces = table.pieces_with_history if has_previous_promotions else table.pieces_first
    piece_daily = None
    if daily is not None:
        while pieces > 1 and _down(daily // pieces, step) < minimum:
            pieces -= 1
        piece_daily = daily if pieces == 1 else _down(daily // pieces, step)
        daily = piece_daily * pieces
    else:
        pieces = 1
    pieces_note = None
    if daily is not None and pieces > 1:
        pieces_note = (
            f"Como ya has hecho anuncios, prueba {pieces} publicaciones distintas para ver "
            f"cuál funciona mejor, unos {money(piece_daily, currency)} al día cada una. "
            "Después de esta, promociona las otras."
        )
    elif daily is not None and not has_previous_promotions:
        pieces_note = "Como es tu primer anuncio, empieza con esta sola publicación."
    return BudgetSuggestion(
        daily,
        days,
        None if daily is None else daily * days,
        pieces,
        piece_daily,
        None if piece_daily is None else piece_daily * days,
        currency,
        bounded_by,
        fits,
        tuple(reasons),
        pieces_note,
        profile is None,
        remaining,
        table.version,
        minimum,
        {
            "profile": None
            if profile is None
            else {
                "weekly_new_clients": profile.weekly_new_clients,
                "monthly_cap_minor": profile.monthly_cap_minor,
                "max_cost_per_client_minor": profile.max_cost_per_client_minor,
                "margin_is_estimated": profile.margin_is_estimated,
                "updated_at": profile.updated_at.isoformat(),
            },
            "spent_this_month_minor": spent_this_month_minor,
            "business_size": size,
            "market_class": market_class,
            "market_table_version": market.table_version if market else None,
            "audience_hash": market.audience_hash if market else None,
            "has_previous_promotions": has_previous_promotions,
        },
    )


def _member(tenant_id: UUID) -> UUID:
    login = current_acting_login()
    if login is None:
        raise BudgetSuggestionUnavailable(LOGIN_NEEDED)
    require_acting_member(tenant_id)
    return login


async def read_daily_minimum(*, tenant_id: UUID, publish_attempt_id: UUID) -> tuple[int, Any]:
    """Meta's daily minimum for the source's selected ad account, in hundredths, and the
    source — before any promotion exists. One GET `act_<id>/minimum_budgets`; spends nothing."""
    from qualify_api.ads.live_management import meta_daily_minimum
    from qualify_api.ads.live_wizard import (
        LiveWizardGateway,
        PersistedWizardSources,
        authorize_actor,
        production_currency_offset,
    )

    login = _member(tenant_id)
    with tenant_session(tenant_id, independent=True) as session:
        actor = session.scalar(
            text("SELECT id FROM users WHERE auth_user_id=:login"), {"login": login}
        )
    try:
        if actor is None:
            raise WizardUnavailable(LOGIN_NEEDED)
        authorize_actor(tenant_id, actor)
        sources = PersistedWizardSources()
        source = sources.get(tenant_id, publish_attempt_id)
        offset = production_currency_offset(source.currency)
        if offset is None:
            raise BudgetSuggestionUnavailable(CURRENCY_UNSUPPORTED)
        gateway = LiveWizardGateway(
            tenant_id=tenant_id, actor=actor, sources=sources, authorize=authorize_actor
        )
        async with gateway.client(source) as client:
            page = await client.minimum_budgets()
    except WizardUnavailable as error:
        raise BudgetSuggestionUnavailable(str(error)) from None
    except MarketingError:
        raise BudgetSuggestionUnavailable(MINIMUM_UNAVAILABLE) from None
    minimum = meta_daily_minimum(page.data, source.currency)
    if minimum is None:
        raise BudgetSuggestionUnavailable(MINIMUM_UNAVAILABLE)
    return from_meta(minimum, source.currency), source


def _history(tenant_id: UUID, brand_id: UUID, currency: str) -> tuple[bool, int | None]:
    """(the brand turned a promotion on before, what its promotions spent this calendar month
    in hundredths of `currency` — None when an activated promotion running this month has no
    Insights row this month yet). Insights `spend` is in major units, as Meta reports it.
    shortcut: the month is the database's (UTC) calendar month, not the tenant's timezone."""
    with tenant_session(tenant_id, independent=True) as session:
        previous, unknown, spend = session.execute(
            text(
                "WITH activated AS (SELECT DISTINCT p.id,p.start_time,p.end_time "
                "FROM ad_promotions p JOIN ad_promotion_activations a "
                "ON a.promotion_id=p.id AND a.tenant_id=p.tenant_id "
                "WHERE p.brand_id=:brand AND a.confirmed_at IS NOT NULL) "
                "SELECT EXISTS(SELECT 1 FROM activated),"
                "EXISTS(SELECT 1 FROM activated x WHERE x.start_time<now() "
                "AND x.end_time>=date_trunc('month',now()) AND NOT EXISTS(SELECT 1 "
                "FROM ad_promotion_insights i WHERE i.promotion_id=x.id "
                "AND i.day>=date_trunc('month',now())::date)),"
                "(SELECT coalesce(sum((i.metrics->>'spend')::numeric),0) "
                "FROM ad_promotion_insights i JOIN ad_promotions p "
                "ON p.id=i.promotion_id AND p.tenant_id=i.tenant_id WHERE p.brand_id=:brand "
                "AND i.currency=:currency AND i.day>=date_trunc('month',now())::date "
                "AND i.metrics->>'spend' IS NOT NULL)"
            ),
            {"brand": brand_id, "currency": currency},
        ).one()
    return bool(previous), None if unknown else int(Decimal(spend) * 100)


async def suggest_budget(
    *,
    tenant_id: UUID,
    publish_attempt_id: UUID,
    market: MarketEstimate | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    daily_minimum_minor: int | None = None,
) -> BudgetSuggestion:
    """See the module docstring."""
    _member(tenant_id)
    if (start_time is None) != (end_time is None):
        raise BudgetSuggestionUnavailable(DATES_INVALID)
    try:
        days = schedule_days(start_time, end_time) if start_time and end_time else None
    except (TypeError, ValueError):
        raise BudgetSuggestionUnavailable(DATES_INVALID) from None
    if daily_minimum_minor is None:
        daily_minimum_minor, source = await read_daily_minimum(
            tenant_id=tenant_id, publish_attempt_id=publish_attempt_id
        )
    else:
        from qualify_api.ads.live_wizard import PersistedWizardSources

        try:
            source = PersistedWizardSources().get(tenant_id, publish_attempt_id)
        except WizardUnavailable as error:
            raise BudgetSuggestionUnavailable(str(error)) from None
    profile = load_investment_profile(tenant_id=tenant_id, brand_id=source.brand_id)
    previous, spent = _history(tenant_id, source.brand_id, source.currency)
    try:
        return suggest(
            profile=profile,
            market=market,
            meta_daily_minimum_minor=daily_minimum_minor,
            currency=source.currency,
            days=days,
            has_previous_promotions=previous,
            spent_this_month_minor=spent,
        )
    except ValueError:
        raise BudgetSuggestionUnavailable(CURRENCY_UNSUPPORTED) from None


def record_budget_suggestion(
    *, tenant_id: UUID, promotion_id: UUID, suggestion: BudgetSuggestion
) -> bool:
    """Keep the suggestion shown before approval with the prepared promotion, and whether the
    approved budget equals its `piece_total_minor`. A separate row (not the immutable approval
    nor its request hash, as for the market estimate, 0177). True when this call stored it."""
    _member(tenant_id)
    with tenant_session(tenant_id, independent=True) as session:
        approved = session.execute(
            text("SELECT budget_minor FROM ad_promotions WHERE id=:id"),
            {"id": promotion_id},
        ).first()
        if approved is None:
            raise BudgetSuggestionUnavailable(PROMOTION_GONE)
        return bool(
            session.execute(
                text(
                    "INSERT INTO ad_promotion_budget_suggestions (tenant_id,promotion_id,"
                    "table_version,bounded_by,fits,suggested_total_minor,approved_budget_minor,"
                    "accepted,suggestion) VALUES (:tenant,:id,:version,:bounded,:fits,:total,"
                    ":approved,:accepted,CAST(:suggestion AS jsonb)) "
                    "ON CONFLICT (promotion_id) DO NOTHING"
                ),
                {
                    "tenant": tenant_id,
                    "id": promotion_id,
                    "version": suggestion.table_version,
                    "bounded": suggestion.bounded_by,
                    "fits": suggestion.fits,
                    "total": suggestion.piece_total_minor,
                    "approved": approved[0],
                    "accepted": approved[0] == suggestion.piece_total_minor,
                    "suggestion": json.dumps(suggestion.provenance()),
                },
            ).rowcount
        )

"""The business's investment profile: what a new client is worth to it (m-25091387, 0176).

The owner answers once per brand and can edit it; budget recommendations (m-25091389,
m-25091390) start from it. Owner manual input: provenance is the login that saved it.

API for the Reflex layer (wrap each call in `acting_login(auth_user_id)`, as other ads
screens do):

- `load_investment_profile(tenant_id=, brand_id=)` → `InvestmentProfile | None` (None: never
  answered).
- `default_currency(tenant_id=, brand_id=)` → the currency to show while it is unanswered
  (the brand's selected ad account's, else COP).
- `save_investment_profile(tenant_id=, brand_id=, average_ticket_minor=, margin_percent=,
  weekly_new_clients=, monthly_cap_minor=, objective=, currency=None)` → the saved profile.
  Re-saving the same answers changes nothing (idempotent); another answer replaces the row.
  The profile is optional: nothing else requires it.
- `InvestmentProfile.max_cost_per_client_minor` — ticket × margin (first purchase only),
  derived, never stored; rounded down to $1.000 in COP and to the whole unit otherwise.
  `margin_is_estimated` → label the result «aproximado».

Money is in hundredths of the currency (`WizardForm.budget_minor`, `money_label`):
COP 25.000 → `2_500_000` (the UI asks whole units and multiplies by 100).
`margin_percent` accepts 35, 35.5, "35,5" (up to 2 decimals), or None for «No lo sé
todavía» (stores `ESTIMATED_MARGIN_PERCENT`, `margin_is_estimated=True`). A margin asked
as a money range is converted to a percentage by the UI. `objective` is the wizard's
goal, `chat` | `website` | `lead` (`OBJECTIVES`), so the answer can pre-fill the wizard.
Every refusal is `InvestmentProfileUnavailable` with a Spanish message to show as is.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads.live_wizard import production_currency_offset
from qualify_api.tenancy.acting import current_acting_login, require_acting_member

# The promotion wizard's goals (`LiveWizard.goal`), so the answer pre-fills it. The
# Reflex wizard calls «website» `visit` (`PromotionState.choose_goal`): map it on pre-fill.
OBJECTIVES = ("chat", "website", "lead")
# «No lo sé todavía» (Raul, 2026-11-22): a fixed, prudent margin, flagged as estimated.
ESTIMATED_MARGIN_PERCENT = 30
# Shown amounts: COP rounds down to $1.000, every other currency to the whole unit.
_ROUND_MINOR = {"COP": 100_000}
MAX_MONEY_MINOR = 10**15  # same bound as the table's CHECK
MAX_WEEKLY_CLIENTS = 100_000

TICKET_INVALID = "Escribe cuánto te paga en promedio un cliente, con un valor mayor que cero."
MARGIN_INVALID = "Escribe tu ganancia aproximada como un porcentaje mayor que 0 y hasta 100."
CLIENTS_INVALID = "Escribe cuántos clientes nuevos puedes atender por semana, con un número entero."
CAP_INVALID = "Escribe cuánto te sientes cómodo invirtiendo al mes, con un valor mayor que cero."
OBJECTIVE_INVALID = "Elige qué quieres conseguir con tus anuncios."
CURRENCY_UNSUPPORTED = "Por ahora solo podemos guardar montos en pesos colombianos (COP)."
BRAND_GONE = "Esta marca ya no está disponible en este negocio."
LOGIN_NEEDED = "Vuelve a iniciar sesión para ver cuánto te conviene pagar por un cliente."


class InvestmentProfileUnavailable(ValueError):
    """A safe Spanish explanation for the owner."""


def max_cost_per_client_minor(average_ticket_minor: int, margin_basis_points: int) -> int:
    """Ticket × margin, rounded DOWN to the hundredth: never suggest paying more than the
    margin leaves."""
    return average_ticket_minor * margin_basis_points // 10_000


@dataclass(frozen=True)
class InvestmentProfile:
    brand_id: UUID
    currency: str
    average_ticket_minor: int
    margin_basis_points: int  # 3550 = 35,5 %
    margin_is_estimated: bool
    weekly_new_clients: int
    monthly_cap_minor: int
    objective: str
    updated_by: UUID
    created_at: datetime
    updated_at: datetime

    @property
    def margin_percent(self) -> Decimal:
        return Decimal(self.margin_basis_points) / 100

    @property
    def max_cost_per_client_minor(self) -> int:
        exact = max_cost_per_client_minor(self.average_ticket_minor, self.margin_basis_points)
        step = _ROUND_MINOR.get(self.currency, 100)
        # below one rounding step (a $3.000 ticket), round to the whole unit, never to 0
        step = step if exact >= step else 100
        return exact // step * step


def _money(value: object, message: str) -> int:
    if type(value) is not int or not 0 < value < MAX_MONEY_MINOR:
        raise InvestmentProfileUnavailable(message)
    return value


def margin_basis_points(value: object) -> int:
    """35 / 35.5 / "35,5" → 3500 / 3550 / 3550. More than 2 decimals or outside (0, 100]
    is refused rather than rounded."""
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal | str):
        raise InvestmentProfileUnavailable(MARGIN_INVALID)
    try:
        number = Decimal(value.strip().replace(",", ".") if isinstance(value, str) else str(value))
    except InvalidOperation:
        raise InvestmentProfileUnavailable(MARGIN_INVALID) from None
    if not number.is_finite():
        raise InvestmentProfileUnavailable(MARGIN_INVALID)
    points = number * 100
    if points != points.to_integral_value() or not 0 < points <= 10_000:
        raise InvestmentProfileUnavailable(MARGIN_INVALID)
    return int(points)


def clean(
    *,
    average_ticket_minor: object,
    margin_percent: object,
    weekly_new_clients: object,
    monthly_cap_minor: object,
    objective: object,
    currency: object,
) -> dict[str, Any]:
    """Validated column values; raises `InvestmentProfileUnavailable` on the first bad answer."""
    if not isinstance(currency, str) or production_currency_offset(currency) is None:
        raise InvestmentProfileUnavailable(CURRENCY_UNSUPPORTED)
    clients = weekly_new_clients
    if type(clients) is not int or not 0 < clients <= MAX_WEEKLY_CLIENTS:
        raise InvestmentProfileUnavailable(CLIENTS_INVALID)
    if objective not in OBJECTIVES:
        raise InvestmentProfileUnavailable(OBJECTIVE_INVALID)
    estimated = margin_percent is None
    return {
        "currency": currency,
        "ticket": _money(average_ticket_minor, TICKET_INVALID),
        "margin": margin_basis_points(ESTIMATED_MARGIN_PERCENT if estimated else margin_percent),
        "estimated": estimated,
        "clients": clients,
        "cap": _money(monthly_cap_minor, CAP_INVALID),
        "objective": objective,
    }


def _member(tenant_id: UUID) -> UUID:
    login = current_acting_login()
    if login is None:
        raise InvestmentProfileUnavailable(LOGIN_NEEDED)
    require_acting_member(tenant_id)
    return login


_COLUMNS = (
    "brand_id,currency,average_ticket_minor,margin_basis_points,margin_is_estimated,"
    "weekly_new_clients,"
    "monthly_cap_minor,objective,updated_by,created_at,updated_at"
)


def _select(session: Any, brand_id: UUID) -> InvestmentProfile | None:
    row = session.execute(
        text(f"SELECT {_COLUMNS} FROM ad_investment_profiles WHERE brand_id=:brand"),
        {"brand": brand_id},
    ).first()
    return InvestmentProfile(*row) if row else None


def load_investment_profile(*, tenant_id: UUID, brand_id: UUID) -> InvestmentProfile | None:
    """The brand's profile, or None when the owner has not answered yet."""
    _member(tenant_id)
    with tenant_session(tenant_id, independent=True) as session:
        return _select(session, brand_id)


def _account_currency(session: Any, brand_id: UUID) -> str:
    return (
        session.execute(
            text(
                "SELECT currency FROM ad_accounts WHERE brand_id=:brand AND selected AND available"
            ),
            {"brand": brand_id},
        ).scalar_one_or_none()
        or "COP"
    )


def default_currency(*, tenant_id: UUID, brand_id: UUID) -> str:
    """The brand's selected ad account currency, else COP. It may be one `save` still refuses
    (USD/UYU arrive with m-25091394): show `CURRENCY_UNSUPPORTED` instead of the form then."""
    _member(tenant_id)
    with tenant_session(tenant_id, independent=True) as session:
        return _account_currency(session, brand_id)


def save_investment_profile(
    *,
    tenant_id: UUID,
    brand_id: UUID,
    average_ticket_minor: int,
    margin_percent: int | float | Decimal | str | None,
    weekly_new_clients: int,
    monthly_cap_minor: int,
    objective: str,
    currency: str | None = None,
) -> InvestmentProfile:
    """Create or replace the brand's profile (last save wins). `currency=None` uses
    `default_currency`. Identical answers leave the row, its `updated_by` and `updated_at`
    untouched, so a double submit is harmless."""
    login = _member(tenant_id)
    with tenant_session(tenant_id, independent=True) as session:
        if (
            session.execute(
                text("SELECT id FROM brands WHERE id=:id FOR SHARE"), {"id": brand_id}
            ).scalar_one_or_none()
            is None
        ):
            raise InvestmentProfileUnavailable(BRAND_GONE)
        values = clean(
            average_ticket_minor=average_ticket_minor,
            margin_percent=margin_percent,
            weekly_new_clients=weekly_new_clients,
            monthly_cap_minor=monthly_cap_minor,
            objective=objective,
            currency=currency or _account_currency(session, brand_id),
        )
        session.execute(
            text(
                "INSERT INTO ad_investment_profiles AS p (tenant_id,brand_id,currency,"
                "average_ticket_minor,margin_basis_points,margin_is_estimated,"
                "weekly_new_clients,monthly_cap_minor,objective,updated_by) VALUES (:tenant,"
                ":brand,:currency,:ticket,:margin,:estimated,:clients,:cap,:objective,:login) "
                "ON CONFLICT (tenant_id,brand_id) DO UPDATE SET currency=EXCLUDED.currency,"
                "average_ticket_minor=EXCLUDED.average_ticket_minor,"
                "margin_basis_points=EXCLUDED.margin_basis_points,"
                "margin_is_estimated=EXCLUDED.margin_is_estimated,"
                "weekly_new_clients=EXCLUDED.weekly_new_clients,"
                "monthly_cap_minor=EXCLUDED.monthly_cap_minor,objective=EXCLUDED.objective,"
                "updated_by=EXCLUDED.updated_by,updated_at=now() "
                "WHERE (p.currency,p.average_ticket_minor,p.margin_basis_points,"
                "p.margin_is_estimated,p.weekly_new_clients,p.monthly_cap_minor,p.objective) "
                "IS DISTINCT FROM (EXCLUDED.currency,EXCLUDED.average_ticket_minor,"
                "EXCLUDED.margin_basis_points,EXCLUDED.margin_is_estimated,"
                "EXCLUDED.weekly_new_clients,"
                "EXCLUDED.monthly_cap_minor,EXCLUDED.objective)"
            ),
            {**values, "tenant": tenant_id, "brand": brand_id, "login": login},
        )
        saved = _select(session, brand_id)
    assert saved is not None  # the row was just written or already identical
    return saved

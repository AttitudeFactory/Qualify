"""The currencies Qualify's ads accept, their Meta unit and how an owner reads them (m-25091394).

Money is kept in hundredths of the currency (`budget_minor`). Meta takes budgets, spend caps
and minimums in the currency's own minimum denomination, its «offset» in the official table
https://developers.facebook.com/docs/marketing-api/currencies/ (read 2026-11-06 for COP,
2026-11-22 for USD/UYU: `docs/discovery-asesor-inversion-meta.md` §9): COP 1 (whole pesos),
USD 100 (cents), UYU 100 (centésimos). ISO decimals are NOT Meta offsets: COP has two ISO
decimals and offset 1. Meta unit = minor × offset / 100; minor = Meta unit × 100 / offset.

The currency is the selected ad account's (one account = one currency), never the owner's
choice. VES is absent on purpose: Venezuelan businesses are assumed to advertise from a USD
account (founder decision pending, ticket m-25091394). Minimum budgets are never kept here:
they come from `act_<id>/minimum_budgets`.

For the Reflex layer: `budget_field(currency)` labels the budget input (None = unsupported:
show `CURRENCY_UNSUPPORTED`); `money_display(minor, currency)` formats an amount in the one
app-wide format (Raul, 2026-11-22): «$25.000 COP», «$10 USD», «$400 UYU».
"""

from __future__ import annotations

from dataclasses import dataclass

META_CURRENCY_OFFSETS = {"COP": 1, "USD": 100, "UYU": 100}

CURRENCY_UNSUPPORTED = (
    "Por ahora los anuncios admiten cuentas publicitarias en pesos colombianos, dólares o "
    "pesos uruguayos. Elige una cuenta en una de esas monedas en Tus redes."
)


@dataclass(frozen=True)
class BudgetField:
    """What the budget input shows for an account's currency. The owner types whole units;
    the UI multiplies by 100 (`step_minor`). Meta's real minimum is checked at validation."""

    currency: str  # «COP»: the field shows «$» before the number and the code after it
    unit_name: str  # «pesos colombianos»: «Presupuesto total en {unit_name}»
    example_minor: int  # a placeholder amount, not a recommendation
    step_minor: int = 100  # whole units only (qualify-copy-es: prices whole)
    min_minor: int = 100


_FIELDS = {
    "COP": BudgetField("COP", "pesos colombianos", 2_500_000),
    "USD": BudgetField("USD", "dólares", 1_000),
    "UYU": BudgetField("UYU", "pesos uruguayos", 40_000),
}


def budget_field(currency: str) -> BudgetField | None:
    return _FIELDS.get(currency)


def money_display(minor: int, currency: str) -> str:
    """«$25.000 COP», «$10 USD», «$400 UYU»; cents only when present («$10,50 USD»), never
    rounded. Any currency code formats the same way; support is decided elsewhere."""
    whole, cents = divmod(minor, 100)
    number = f"{whole:,}".replace(",", ".") + (f",{cents:02d}" if cents else "")
    return f"${number} {currency}"


def to_meta(minor: int, currency: str) -> int:
    """Hundredths → Meta's unit. Raises ValueError when unsupported or not exact."""
    offset = META_CURRENCY_OFFSETS.get(currency)
    if offset is None or minor * offset % 100:
        raise ValueError("amount not representable in Meta's unit")
    return minor * offset // 100


def from_meta(amount: int, currency: str) -> int:
    """Meta's unit → hundredths. Raises ValueError when unsupported."""
    offset = META_CURRENCY_OFFSETS.get(currency)
    if offset is None:
        raise ValueError("unsupported currency")
    return amount * 100 // offset

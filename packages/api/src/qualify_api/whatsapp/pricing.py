"""Per-message cost estimate for WhatsApp template sends (WA-20).

**[RATE CARD PENDING] — every number in `_RATE_CARD` is a PLACEHOLDER.** Plan §2.5: since
2025-07-01 Meta charges per DELIVERED template message, by recipient country and category
(marketing / utility / authentication), volume-tiered; Colombia bills in COP since
2026-04-01 and prices only change on the first day of a quarter. The rate card is a file
downloaded from Meta's pricing page; the plan deliberately does not copy a figure, and
neither does this module pretend to: the values below are order-of-magnitude
placeholders so the campaign screen can show *a* number labelled as an estimate, until
someone with the current rate card calls `set_rate_override` (or replaces the table) for
the countries the tenant sends to. `Rate.placeholder` is True for every built-in entry and
False for an override; the UI must show the `[RATE CARD PENDING]` label while it is True.

What the estimate deliberately ignores (it is an upper bound, not an invoice):

- free sends: a utility template inside the 24 h service window, and conversations opened
  from a Click-to-WhatsApp ad or Page button (72 h) cost nothing;
- volume tiers;
- undelivered messages (Meta charges delivered ones only) — the campaign summary
  multiplies by the sends, not by the deliveries;
- marketing templates are not delivered to US numbers at all (per-user-limits page).

Meta's own verdict per message arrives later as `pricing.category` on the status webhook
(`whatsapp_campaign_sends.price_category`), which is what WA-21 reconciles against.

Key: `(country_prefix, category)`, where `country_prefix` is the E.164 country code
without `+` (`"57"`) — matched longest-first against the recipient's number.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from qualify_api.whatsapp.models import TEMPLATE_CATEGORIES

RATE_CARD_STATUS: Final = "[RATE CARD PENDING]"


@dataclass(frozen=True)
class Rate:
    amount: Decimal
    currency: str
    placeholder: bool = True


@dataclass(frozen=True)
class CostEstimate:
    amount: Decimal
    currency: str
    country_prefix: str
    category: str
    placeholder: bool


# [RATE CARD PENDING] Placeholders, USD per delivered message — NOT Meta's current rates.
_RATE_CARD: Final[dict[tuple[str, str], Rate]] = {
    ("57", "marketing"): Rate(Decimal("0.0125"), "USD"),  # [RATE CARD PENDING] Colombia
    ("57", "utility"): Rate(Decimal("0.0008"), "USD"),  # [RATE CARD PENDING] Colombia
    ("57", "authentication"): Rate(Decimal("0.0008"), "USD"),  # [RATE CARD PENDING] Colombia
    ("52", "marketing"): Rate(Decimal("0.0305"), "USD"),  # [RATE CARD PENDING] México
    ("52", "utility"): Rate(Decimal("0.0085"), "USD"),  # [RATE CARD PENDING] México
    ("52", "authentication"): Rate(Decimal("0.0085"), "USD"),  # [RATE CARD PENDING] México
}

_overrides: dict[tuple[str, str], Rate] = {}


def set_rate_override(
    country_prefix: str, category: str, amount: Decimal | str, currency: str
) -> None:
    """THE override: record a real rate (from the current rate card) for one country and
    category. Overrides win over the placeholder table and are not placeholders.
    Process-wide; a later call for the same key replaces it."""
    prefix = country_prefix.lstrip("+")
    if not prefix.isdigit() or not 1 <= len(prefix) <= 4:
        raise ValueError("country_prefix must be an E.164 country code like '57'")
    if category not in TEMPLATE_CATEGORIES:
        raise ValueError(f"category must be one of {TEMPLATE_CATEGORIES}")
    value = Decimal(amount)
    if value < 0:
        raise ValueError("amount must not be negative")
    if not currency or len(currency) != 3:
        raise ValueError("currency must be an ISO 4217 code")
    _overrides[(prefix, category)] = Rate(value, currency.upper(), placeholder=False)


def clear_rate_overrides() -> None:
    """For tests."""
    _overrides.clear()


def _rates() -> dict[tuple[str, str], Rate]:
    return {**_RATE_CARD, **_overrides}


def country_prefix_of(phone_e164: str) -> str | None:
    """The longest known country prefix the number starts with, or `None`."""
    digits = phone_e164.lstrip("+")
    known = {prefix for prefix, _ in _rates()}
    for length in range(4, 0, -1):
        if digits[:length] in known:
            return digits[:length]
    return None


def estimate_cost(phone_e164: str, category: str) -> CostEstimate | None:
    """The estimated price of ONE delivered template of `category` to `phone_e164`;
    `None` when the country or category is not in the table (the UI says "sin tarifa")."""
    prefix = country_prefix_of(phone_e164)
    if prefix is None:
        return None
    rate = _rates().get((prefix, category))
    if rate is None:
        return None
    return CostEstimate(
        amount=rate.amount,
        currency=rate.currency,
        country_prefix=prefix,
        category=category,
        placeholder=rate.placeholder,
    )


__all__ = [
    "RATE_CARD_STATUS",
    "CostEstimate",
    "Rate",
    "clear_rate_overrides",
    "country_prefix_of",
    "estimate_cost",
    "set_rate_override",
]

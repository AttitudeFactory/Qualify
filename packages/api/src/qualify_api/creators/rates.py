"""What a creator charges — the owner's rate card for a tracked creator (m-24955847,
`docs/diseno-modulo-creadores.md` «Lo que cobra el creador»).

Pure: no database, no network. The owner writes how the creator works and what he charges
as free text, plus the creator's lowest price («Desde») as an amount with its currency.
This module reads the amount the owner typed (`parse_rate_amount`) and validates the whole
rate (`validate_rate`) before anything opens a transaction. It is the creator's own price
list, NOT the per-campaign offer of E4 (m-24946141). Currencies are never converted
(design §6.5): comparisons only put side by side prices in the same currency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

#: The currencies a rate may be written in — the markets' own plus dollars (§6.5).
RATE_CURRENCIES: tuple[str, ...] = ("COP", "USD", "VES", "UYU")
#: `numeric(12,2)` holds up to this.
MAX_RATE = Decimal("9999999999.99")
#: `char_length(rate_notes) <= 1000` (migration 0130).
MAX_RATE_NOTES = 1000

_CENT = Decimal("0.01")

# InvalidRate.reason codes
NOT_A_NUMBER = "not_a_number"
NEGATIVE = "negative"
TOO_LARGE = "too_large"
NOTES_TOO_LONG = "notes_too_long"
CURRENCY_REQUIRED = "currency_required"
UNSUPPORTED_CURRENCY = "unsupported_currency"


class InvalidRate(ValueError):
    """A rate the owner cannot save. `reason` is one of: `not_a_number`, `negative`,
    `too_large`, `notes_too_long`, `currency_required`, `unsupported_currency` (the screen
    turns it into Spanish)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# A currency mark the owner may write before or after the amount: «$», «US$», «U$S»,
# «COP», «USD», «VES», «UYU», «Bs», «Bs.», «Bs.S», «Bs.F», «pesos», «dólares»,
# «bolívares». Stripped, never interpreted: the currency is its own field.
_MARK = r"(?:us\$|u\$s|\$|cop|usd|ves|uyu|bs\.?\s?[sf]\.?|bs\.?|pesos|d[oó]lares|bol[ií]vares)"
_PREFIX = re.compile(rf"^{_MARK}\s*", re.IGNORECASE)
_SUFFIX = re.compile(rf"\s*{_MARK}$", re.IGNORECASE)
# «mil» ×1,000; «millón», «millon», «millones» ×1,000,000; «k» ×1,000; «m» is NOT taken
# (it reads as «mil» to some and «millón» to others).
_MULTIPLIER = re.compile(r"^(?P<number>.*?)\s*(?P<word>mil|mill[oó]n(?:es)?|k)$", re.IGNORECASE)
_FACTORS = {"mil": 1_000, "k": 1_000}
_SPACED_THOUSANDS = re.compile(r"^\d{1,3}(?: \d{3})+(?:[.,]\d{1,2})?$")
_DIGITS = re.compile(r"^\d+$")
_GROUPED = re.compile(r"^\d{1,3}(?:[.,]\d{3})+$")


def _thousands(text: str, separator: str) -> str | None:
    """`text` as plain digits when it is digits grouped by `separator` in threes (the first
    group 1-3 digits); a bare run of digits passes as is. None otherwise."""
    if _DIGITS.match(text):
        return text
    if separator in text and _GROUPED.match(text) and not (set(".,") - {separator}) & set(text):
        return text.replace(separator, "")
    return None


def _plain_number(text: str) -> Decimal | None:
    """Digits with thousands and decimal separators → a Decimal; None when the text is not
    one unambiguous number. See `parse_rate_amount` for the rule."""
    if _SPACED_THOUSANDS.match(text):
        text = text.replace(" ", "")
    if not text or not text[0].isdigit() or not text[-1].isdigit():
        return None
    dots, commas = text.count("."), text.count(",")
    if dots and commas:
        # both: the last one is the decimal mark, the other groups thousands
        decimal_mark = "." if text.rfind(".") > text.rfind(",") else ","
        thousands_mark = "," if decimal_mark == "." else "."
        whole, _, fraction = text.rpartition(decimal_mark)
        if decimal_mark in whole or not 1 <= len(fraction) <= 2 or not _DIGITS.match(fraction):
            return None
        digits = _thousands(whole, thousands_mark)
        return Decimal(f"{digits}.{fraction}") if digits is not None else None
    if not dots and not commas:
        return Decimal(text) if _DIGITS.match(text) else None
    mark = "." if dots else ","
    if text.count(mark) > 1:
        digits = _thousands(text, mark)  # «1.500.000», «1,500,000»
        return Decimal(digits) if digits is not None else None
    whole, _, fraction = text.partition(mark)
    if not _DIGITS.match(whole) or not _DIGITS.match(fraction):
        return None
    if len(fraction) == 3:  # «150.000», «1,500»: thousands
        return Decimal(whole + fraction) if len(whole) <= 3 else None
    if len(fraction) <= 2:  # «150.5», «1,5», «150,50»: decimals
        return Decimal(f"{whole}.{fraction}")
    return None


def parse_rate_amount(text: str) -> Decimal | None:
    """The amount the owner typed, as a Decimal rounded to cents; None when blank.

    Spanish convention first — «.» groups thousands, «,» marks decimals — but an amount is
    read by its SHAPE, since owners in Venezuela often write the other way round:

    - **One separator, once:** followed by exactly 3 digits it groups thousands
      («150.000», «1,500» → 150000, 1500; the part before it must be 1-3 digits); followed
      by 1 or 2 digits it marks decimals («150.5» → 150.50, «1,5» → 1.50, «150,50»).
      Anything else («150.5555», «1234.567») is refused: money has at most 2 decimals.
    - **One separator, several times:** thousands in groups of three («1.500.000»,
      «1,500,000»); a bad grouping («1.50.000») is refused.
    - **Both separators:** the last one marks decimals (1-2 digits), the other groups
      thousands («1.500,50» and «1,500.50» → 1500.50).
    - **Spaces** may group thousands («150 000»).
    - A currency mark before or after is ignored («$ 150.000», «150.000 COP», «US$ 200»,
      «Bs. 300»): the currency is chosen apart.
    - A trailing «mil» / «k» multiplies by 1,000 and «millón» / «millones» by 1,000,000
      («150 mil» → 150000, «1,5 millones» → 1500000).

    Raises `InvalidRate("not_a_number")` for anything else (two amounts, letters, «.5»),
    `InvalidRate("negative")` for a leading «-», and `InvalidRate("too_large")` above
    9,999,999,999.99. Zero is accepted (a creator who works for products)."""
    value = (text or "").replace(" ", " ").strip()
    if not value:
        return None
    negative = value.startswith(("-", "−"))
    if negative:
        value = value[1:].strip()
    value = _SUFFIX.sub("", _PREFIX.sub("", value)).strip()
    if value.startswith(("-", "−")):  # «$ -150»
        negative = True
        value = value[1:].strip()
    factor = 1
    match = _MULTIPLIER.match(value)
    if match:
        word = match.group("word").lower()
        factor = _FACTORS.get(word, 1_000_000)
        value = match.group("number").strip()
    number = _plain_number(value)
    if number is None:
        raise InvalidRate(NOT_A_NUMBER)
    if negative and number != 0:
        raise InvalidRate(NEGATIVE)
    return check_amount(number * factor)


def check_amount(amount: Decimal) -> Decimal:
    """`amount` rounded to cents (half up). Raises `InvalidRate` when it is not a finite
    number (`not_a_number`), below zero (`negative`) or above `MAX_RATE` (`too_large`)."""
    try:
        value = Decimal(str(amount)) if not isinstance(amount, Decimal) else amount
        if not value.is_finite():
            raise InvalidRate(NOT_A_NUMBER)
        value = value.quantize(_CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise InvalidRate(NOT_A_NUMBER) from exc
    if value < 0:
        raise InvalidRate(NEGATIVE)
    if value > MAX_RATE:
        raise InvalidRate(TOO_LARGE)
    return value


@dataclass(frozen=True)
class Rate:
    """A validated rate, ready to store."""

    notes: str
    amount: Decimal | None
    currency: str | None


def validate_rate(notes: str, amount: Decimal | None, currency: str | None) -> Rate:
    """Strip the notes and check every rule; the currency is dropped when there is no
    amount. Raises `InvalidRate`."""
    clean = (notes or "").strip()
    if len(clean) > MAX_RATE_NOTES:
        raise InvalidRate(NOTES_TOO_LONG)
    if amount is None:
        return Rate(clean, None, None)
    value = check_amount(amount)
    code = (currency or "").strip().upper()
    if not code:
        raise InvalidRate(CURRENCY_REQUIRED)
    if code not in RATE_CURRENCIES:
        raise InvalidRate(UNSUPPORTED_CURRENCY)
    return Rate(clean, value, code)


__all__ = [
    "MAX_RATE",
    "MAX_RATE_NOTES",
    "RATE_CURRENCIES",
    "InvalidRate",
    "Rate",
    "check_amount",
    "parse_rate_amount",
    "validate_rate",
]

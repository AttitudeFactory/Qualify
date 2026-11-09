"""Minimal account observations, without payment instruments or provider payloads."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

# AccountStatus constants from the official Python Business SDK 26.0.0 helper.
# The helper calls 101 temporarily_unavailable; do not infer permanent closure.
ACCOUNT_STATUS_LABELS = {
    1: "Activa",
    2: "Deshabilitada",
    3: "Pago pendiente",
    7: "En revisión",
    9: "En período de gracia",
    100: "Cierre pendiente",
    101: "No disponible",
}
UNKNOWN_STATUS = "Estado pendiente de comprobar"
UNKNOWN_REASON = "Motivo pendiente de comprobar en Meta"
HEALTH_FIELDS = (
    "account_id,currency,account_status,disable_reason,funding_source,amount_spent,spend_cap"
)
SNAPSHOT_KEYS = frozenset(
    {
        "currency",
        "account_status",
        "disable_reason",
        "funding_present",
        "amount_spent_minor",
        "spend_cap_minor",
        "source_id",
        "api_version",
        "pipeline_version",
        "pending_billing",
        "amount_spent_raw",
        "spend_cap_raw",
        "money_units_verified",
    }
)


def account_status_label(code: int | None) -> str:
    return ACCOUNT_STATUS_LABELS.get(code, UNKNOWN_STATUS) if type(code) is int else UNKNOWN_STATUS


def disable_reason_label(code: int | None) -> str:
    # No authoritative current enum was accessible. Never diagnose policy violations
    # or compromised accounts from an unverified numeric mapping.
    if type(code) is not int or code < 0:
        return UNKNOWN_REASON
    if code == 0:
        return "Sin restricción informada por Meta"
    return "Meta informa una restricción. Revisa el motivo en Meta."


def ad_delivery_label(effective_status: str | None) -> str:
    return (
        "Falta información de pago"
        if effective_status == "PENDING_BILLING_INFO"
        else "Estado de entrega pendiente de comprobar"
    )


def minor_integer(value: Any) -> int | None:
    """Graph money is an integer string. No float, exponent or silent rounding."""
    if type(value) is int:
        return value if 0 <= value < 10**18 else None
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,18}", value):
        return int(value)
    return None


def money_label(value: int | None, currency: str) -> str:
    # These currencies are used by Qualify and have two minor-unit decimal places.
    # Other Meta currencies are not guessed or silently divided by 100.
    if value is None or currency not in {"COP", "USD", "UYU", "VES", "EUR"}:
        return "Importe pendiente de comprobar"
    whole, fraction = divmod(value, 100)
    return f"{whole:,}".replace(",", ".") + f",{fraction:02d} {currency}"


@dataclass(frozen=True)
class HealthObservation:
    currency: str
    account_status: int | None
    disable_reason: int | None
    funding_present: bool | None
    amount_spent_minor: int | None
    spend_cap_minor: int | None
    pending_billing: bool | None = False
    amount_spent_raw: str | None = None
    spend_cap_raw: str | None = None
    money_units_verified: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.currency, str) or not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise ValueError("invalid health currency")
        for value in (
            self.account_status,
            self.disable_reason,
            self.amount_spent_minor,
            self.spend_cap_minor,
        ):
            if value is not None and (type(value) is not int or not 0 <= value < 10**18):
                raise ValueError("invalid health integer")
        for value in (self.funding_present, self.pending_billing):
            if value is not None and type(value) is not bool:
                raise ValueError("invalid health observation")
        if type(self.money_units_verified) is not bool:
            raise ValueError("invalid monetary evidence")
        for value in (self.amount_spent_raw, self.spend_cap_raw):
            if value is not None and (
                not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,18}", value)
            ):
                raise ValueError("invalid numeric observation")

    @classmethod
    def from_graph(
        cls, payload: dict[str, Any], *, account_id: str, currency: str
    ) -> HealthObservation:
        if payload.get("account_id") != account_id or payload.get("currency") != currency:
            raise ValueError("account health identity mismatch")
        funding = minor_integer(payload.get("funding_source"))
        return cls(
            currency,
            payload.get("account_status") if type(payload.get("account_status")) is int else None,
            payload.get("disable_reason") if type(payload.get("disable_reason")) is int else None,
            True if funding is not None and funding > 0 else None,
            None,
            None,
            amount_spent_raw=str(value)
            if (value := minor_integer(payload.get("amount_spent"))) is not None
            else None,
            spend_cap_raw=str(value)
            if (value := minor_integer(payload.get("spend_cap"))) is not None
            else None,
        )


@dataclass(frozen=True)
class AccountHealth:
    """Account-only observation. can_promote is NOT VerifiedChecks.billing_ready.

    A positive result means no known account-health block was observed; it never
    proves a future charge, Meta delivery, eligibility, targeting or spend capacity.
    """

    account_id: UUID
    account_name: str
    currency: str
    status: str
    label: str
    tone: str
    reason: str
    can_promote: bool
    checked_at: datetime | None
    stale: bool
    funding_present: bool | None
    account_status_label: str
    disable_reason_label: str
    amount_spent_minor: int | None
    spend_cap_minor: int | None
    billing_url: str
    blocks_preparation: bool = False
    refresh_error: bool = False
    account_url: str = ""

    @property
    def action_label(self) -> str:
        return (
            "Revisar pagos"
            if self.status in {"payment_required", "payment_unverified"}
            else "Revisar cuenta"
        )

    @property
    def action_url(self) -> str:
        return (
            self.billing_url
            if self.status in {"payment_required", "payment_unverified"}
            else self.account_url
        )

    @property
    def amount_spent_label(self) -> str:
        return money_label(self.amount_spent_minor, self.currency)

    @property
    def spend_cap_label(self) -> str:
        return money_label(self.spend_cap_minor, self.currency)

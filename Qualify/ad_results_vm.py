"""Display-only observations: absent measurements never become a zero."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .ad_health_vm import checked_label

UNAVAILABLE = "Sin datos"
LOAD_FAILED = "No pudimos consultar tus anuncios. Vuelve a intentarlo."
REFRESH_FAILED = "No pudimos actualizar con Meta. Conservamos la última consulta disponible."
NO_SESSION = "Vuelve a iniciar sesión para consultar tus anuncios."
PAUSE_FAILED = (
    "No pudimos confirmar si el anuncio quedó en pausa. "
    "Actualiza su estado antes de volver a intentarlo."
)


@dataclass(frozen=True)
class AdResultVM:
    id: str = ""
    title: str = "Anuncio de tu publicación"
    account: str = "Cuenta por comprobar"
    status: str = "unknown"
    status_label: str = "Estado por comprobar"
    tone: str = "warn"
    approved_budget: str = "Presupuesto por comprobar"
    end_label: str = "Final por comprobar"
    checked_label: str = "Todavía no se ha comprobado"
    rejection_reason: str = ""
    can_pause: bool = False
    can_manage: bool = False
    management_reason: str = ""
    currency: str = ""
    timezone_name: str = ""
    stale: bool = True
    refresh_failed: bool = False


@dataclass(frozen=True)
class AdDayVM:
    day: str
    label: str
    spend: str
    clicks: str
    reach: str
    impressions: str
    ctr: str
    cpc: str
    cpm: str


@dataclass(frozen=True)
class AdDetailVM:
    promotion: AdResultVM = field(default_factory=AdResultVM)
    days: list[AdDayVM] = field(default_factory=list)
    notice: str = ""
    updated_label: str = "Todavía no se han consultado resultados"
    insights_stale: bool = True
    insights_refresh_failed: bool = False


def number_label(value: int | Decimal | None, *, decimals: int = 0) -> str:
    if value is None or isinstance(value, bool):
        return UNAVAILABLE
    try:
        amount = Decimal(value)
        if not amount.is_finite() or amount < 0:
            return UNAVAILABLE
        return format(amount, f",.{decimals}f").translate(str.maketrans({",": ".", ".": ","}))
    except (InvalidOperation, TypeError, ValueError):
        return UNAVAILABLE


def money_label(value: Decimal | None, currency: str) -> str:
    if (
        len(currency) != 3
        or not currency.isascii()
        or not currency.isalpha()
        or not currency.isupper()
    ):
        return "Moneda por comprobar"
    amount = number_label(value, decimals=2)
    return f"{amount} {currency}" if amount != UNAVAILABLE else UNAVAILABLE


def day_label(value: date, timezone_name: str, now: datetime | None = None) -> str:
    label = value.strftime("%d/%m/%Y")
    try:
        zone = ZoneInfo(timezone_name)
    except (ValueError, ZoneInfoNotFoundError):
        return label
    current = now or datetime.now(UTC)
    if current.tzinfo is not None and value == current.astimezone(zone).date() - timedelta(days=1):
        return "Ayer · " + label
    return label


def status_tone(status: str) -> str:
    value = status.upper()
    if value in {"DISAPPROVED", "REJECTED", "ERROR"}:
        return "error"
    if value in {"ACTIVE", "DELIVERING"}:
        return "ok"
    if value in {"PAUSED", "CAMPAIGN_PAUSED", "ADSET_PAUSED", "COMPLETED", "ARCHIVED"}:
        return "neutral"
    return "warn"


def date_label(value: datetime | None, timezone_name: str) -> str:
    return checked_label(value, timezone_name) if value is not None else "Por comprobar"

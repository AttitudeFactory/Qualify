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
EDIT_PREPARE_FAILED = "No pudimos comprobar este cambio. Vuelve a consultarlo antes de confirmar."
EDIT_UNKNOWN = (
    "No pudimos confirmar el cambio. Consulta el estado con Meta antes de hacer otro cambio."
)
URGENT_PAUSE = (
    "Si necesitas detener el gasto, pausa el anuncio directamente en el Administrador "
    "de anuncios de Meta."
)
EDIT_EXPIRED = "La comprobación venció. Vuelve a comprobar el cambio antes de confirmarlo."
EDIT_ACTION_LABELS = {
    "budget": "Aumentar presupuesto",
    "budget_down": "Bajar presupuesto",
    "end_time": "Cambiar fecha de fin",
    "resume": "Reanudar anuncio",
}
# Both budget directions are the backend's one "budget" edit; only the screen tells them apart.
BACKEND_ACTIONS = {"budget_down": "budget"}
NO_REJECTION_REASON = "Meta no dio el motivo. Revisa el texto y la imagen."
META_REASON_PREFIX = "Motivo informado por Meta: "
FLOOR_FAILED = "No pudimos consultar el mínimo ahora. Lo comprobaremos antes de guardar."
ALERTS_ON = "Listo. Te avisaremos aquí si Meta rechaza o detiene tu anuncio."
ALERTS_ALREADY_ON = "Los avisos ya estaban activos en esta cuenta."
ALERTS_FAILED = "No pudimos activar los avisos. Vuelve a intentarlo."


def backend_action(action: str) -> str:
    return BACKEND_ACTIONS.get(action, action)


def pesos(minor: int) -> str:
    return "$" + f"{minor // 100:,}".replace(",", ".")


def floor_label(floor_minor: int, spent_minor: int) -> str:
    return f"Mínimo: {pesos(floor_minor)} (ya gastaste {pesos(spent_minor)})"


def budget_down_summary(current_minor: int, new_minor: int) -> str:
    return (
        f"Tu anuncio podrá gastar hasta {pesos(new_minor)} en total, "
        f"en vez de {pesos(current_minor)}."
    )


def rejection_text(status: str, reason: str) -> str:
    """A rejection always says why, or says plainly that Meta did not."""
    if status != "DISAPPROVED" or reason.startswith(META_REASON_PREFIX):
        return reason
    return NO_REJECTION_REASON


@dataclass(frozen=True)
class AlertAccountVM:
    id: str
    name: str


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
    current_budget: str = "Presupuesto actual por comprobar"
    current_end_label: str = "Final actual por comprobar"
    current_budget_input: str = ""
    current_end_input: str = ""
    can_resume: bool = False
    operation_pending: bool = False
    rejected: bool = False
    fix_href: str = "/drafts"


@dataclass(frozen=True)
class AdEditReviewVM:
    action: str = ""
    title: str = "Revisa el cambio"
    summary: str = ""
    current_budget: str = "Por comprobar"
    new_budget: str = "Por comprobar"
    current_end: str = "Por comprobar"
    new_end: str = "Por comprobar"
    expires_label: str = ""
    ready: bool = False
    end_changed: bool = True
    budget_changed: bool = True


@dataclass(frozen=True)
class AdEditOutcomeVM:
    promotion_id: str
    action: str
    status: str
    message: str
    detail: AdDetailVM | None = None


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
    observed_conversations: str = "Sin datos"


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
    if currency == "COP":  # whole pesos, the same «$200.000» as everywhere else
        amount = number_label(value, decimals=0)
        return "$" + amount if amount != UNAVAILABLE else UNAVAILABLE
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


class EditInputError(ValueError):
    """Only local, fixed client instructions may be displayed from this exception."""


def budget_input(value: object, currency: str) -> str:
    if currency != "COP" or type(value) is not int or value <= 0 or value % 100:
        return ""
    return str(value // 100)


def end_input(value: datetime | None, timezone_name: str) -> str:
    try:
        if value is None or value.utcoffset() is None:
            return ""
        return value.astimezone(ZoneInfo(timezone_name)).strftime("%Y-%m-%dT%H:%M")
    except (ValueError, ZoneInfoNotFoundError):
        return ""


def edit_budget(value: str, current: str) -> int:
    if not value or not value.isascii() or not value.isdigit() or len(value) > 12:
        raise EditInputError("Escribe el presupuesto total en pesos enteros, sin puntos ni comas.")
    if not current or not current.isascii() or not current.isdigit():
        raise EditInputError("Actualiza con Meta para comprobar el presupuesto actual.")
    if int(value) <= int(current):
        raise EditInputError("El nuevo presupuesto total debe ser mayor que el actual.")
    return int(value) * 100


def edit_budget_down(value: str, current: str, floor: str) -> int:
    """A lower total, never under the floor read from Meta when it is known."""
    if not value or not value.isascii() or not value.isdigit() or len(value) > 12:
        raise EditInputError("Escribe el presupuesto total en pesos enteros, sin puntos ni comas.")
    if not current or not current.isascii() or not current.isdigit():
        raise EditInputError("Actualiza con Meta para comprobar el presupuesto actual.")
    if not 0 < int(value) < int(current):
        raise EditInputError("El nuevo presupuesto total debe ser menor que el actual.")
    if floor.isascii() and floor.isdigit() and int(value) < int(floor):
        raise EditInputError(
            f"Puedes bajarlo hasta {pesos(int(floor) * 100)}. Escribe ese monto o uno mayor."
        )
    return int(value) * 100


def edit_end(value: str, timezone_name: str) -> datetime:
    try:
        local = datetime.fromisoformat(value)
        if local.tzinfo is not None:
            raise ValueError("local time required")
        zone = ZoneInfo(timezone_name)
        first = local.replace(tzinfo=zone, fold=0)
        second = local.replace(tzinfo=zone, fold=1)
        if (
            first.utcoffset() != second.utcoffset()
            or first.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != local
        ):
            raise ValueError("ambiguous or missing local time")
        return first
    except (ValueError, ZoneInfoNotFoundError):
        raise EditInputError(
            "Elige una fecha y hora válidas según la zona horaria de esta cuenta."
        ) from None

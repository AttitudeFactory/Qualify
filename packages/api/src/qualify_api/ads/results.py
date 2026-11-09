"""Strict read models for promotion delivery and daily results (m-24828979)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

PIPELINE_VERSION = "ad-results-v1"
MANAGEMENT_REASON = (
    "Reanudar o cambiar el presupuesto y la fecha requiere comprobar primero "
    "los permisos, los pagos y las condiciones de la promoción."
)
NOTICE = (
    "Los resultados corresponden a la zona horaria de la cuenta publicitaria. "
    "Meta puede actualizar los datos después de mostrarlos. Los clics no equivalen a ventas."
)
STATUS_LABELS = {
    "ACTIVE": "Activo",
    "PAUSED": "Pausado",
    "ADSET_PAUSED": "Conjunto de anuncios pausado",
    "CAMPAIGN_PAUSED": "Campaña pausada",
    "PENDING_REVIEW": "En revisión de Meta",
    "IN_PROCESS": "Meta está procesando el anuncio",
    "PREAPPROVED": "Aprobado, pendiente de publicación",
    "DISAPPROVED": "Rechazado por Meta",
    "WITH_ISSUES": "Con problemas de entrega",
    "PENDING_BILLING_INFO": "Falta revisar los pagos",
    "ARCHIVED": "Archivado",
    "DELETED": "Eliminado",
}


class ResultsUnavailable(ValueError):
    """Safe client-readable failure; never contains remote response material."""


@dataclass(frozen=True)
class PromotionResultSummary:
    id: UUID
    brand_id: UUID
    status: str
    status_label: str
    currency: str
    budget_minor: int
    budget_kind: str
    end_time: datetime
    checked_at: datetime | None
    rejection_reason: str = ""
    can_manage: bool = False
    management_reason: str = MANAGEMENT_REASON
    caption: str = ""
    account_name: str = ""
    timezone_name: str = ""
    can_pause: bool = False
    stale: bool = True
    refresh_failed: bool = False
    current_budget_minor: int | None = None
    current_end_time: datetime | None = None
    can_resume: bool = False
    operation_pending: bool = False


@dataclass(frozen=True)
class DailyInsight:
    day: date
    currency: str
    spend: Decimal | None
    reach: int | None
    impressions: int | None
    clicks: int | None
    ctr: Decimal | None
    cpc: Decimal | None
    cpm: Decimal | None
    actions: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True)
class PromotionResults:
    promotion: PromotionResultSummary
    daily: tuple[DailyInsight, ...]
    updated_at: datetime | None
    notice: str = NOTICE
    insights_stale: bool = True
    insights_refresh_failed: bool = False
    observed_conversations: int | None = None


def nonnegative(value: Any, *, integer: bool = False) -> Decimal | int | None:
    """Missing/malformed observations remain unknown rather than becoming zero."""
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        return None
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    if (
        not number.is_finite()
        or number < 0
        or number > Decimal("1e30")
        or (integer and number != number.to_integral_value())
    ):
        return None
    return int(number) if integer else number


def parse_insight(
    row: dict[str, Any], *, ad_id: str, account_id: str, currency: str
) -> DailyInsight:
    if (
        row.get("ad_id") != ad_id
        or row.get("account_id") != account_id
        or row.get("account_currency") != currency
        or not isinstance(row.get("date_start"), str)
        or row.get("date_stop") != row.get("date_start")
    ):
        raise ResultsUnavailable("Meta devolvió resultados de otra cuenta o de otro período.")
    try:
        day = date.fromisoformat(row["date_start"])
    except ValueError:
        raise ResultsUnavailable("No pudimos comprobar la fecha de los resultados.") from None
    actions = []
    for action in row.get("actions", []) if isinstance(row.get("actions"), list) else []:
        if not isinstance(action, dict):
            continue
        kind, value = action.get("action_type"), nonnegative(action.get("value"))
        if (
            isinstance(kind, str)
            and re.fullmatch(r"[a-zA-Z0-9_.:]{1,150}", kind)
            and value is not None
        ):
            actions.append({"action_type": kind, "value": str(value)})
    return DailyInsight(
        day,
        currency,
        nonnegative(row.get("spend")),
        nonnegative(row.get("reach"), integer=True),
        nonnegative(row.get("impressions"), integer=True),
        nonnegative(row.get("clicks"), integer=True),
        nonnegative(row.get("ctr")),
        nonnegative(row.get("cpc")),
        nonnegative(row.get("cpm")),
        tuple(actions),
    )


def safe_review_text(issues: Any) -> str:
    """SDK26 issues_info text only, never codes, HTML, secrets or arbitrary objects."""
    if not isinstance(issues, list) or not 1 <= len(issues) <= 5:
        return ""
    candidates = []
    for issue in issues:
        if not isinstance(issue, dict):
            return ""
        values = []
        for key in ("error_summary", "error_message"):
            value = issue.get(key)
            if value is None or value == "":
                continue
            if not isinstance(value, str) or len(value) > 300:
                return ""
            if (
                any(unicodedata.category(char).startswith("C") for char in value)
                or any(char in value for char in "<>&{}[]`\\")
                or re.search(
                    r"https?://|www\.|(?:access[_ -]?)?token|secret|password|"
                    r"contraseñ|authorization|bearer|api[_ -]?key|cookie|session|private|"
                    r"eyJ[A-Za-z0-9_-]+|[0-9][0-9 -]{11,}[0-9]|"
                    r"[A-Za-z0-9_=-]{32,}",
                    value,
                    re.IGNORECASE,
                )
            ):
                return ""
            clean = " ".join(value.split())
            if clean:
                values.append(clean)
        if values:
            candidates.append(values[0])
    return candidates[0] if candidates else ""


def review_reason(status: str, specific: str = "") -> str:
    if status in {"DISAPPROVED", "WITH_ISSUES"} and specific:
        return "Motivo informado por Meta: " + specific
    return (
        "Meta rechazó este anuncio. Consulta el motivo detallado en el Administrador de anuncios."
        if status == "DISAPPROVED"
        else ""
    )

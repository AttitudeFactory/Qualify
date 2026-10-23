"""View-models for `/whatsapp` → Campañas (WA-20, QUA-219) — the security boundary.

`WhatsAppCampaignsState` only holds the frozen dataclasses below — never a
`whatsapp_campaigns`/`whatsapp_campaign_sends` row, never an outbox payload, never a
`wamid` (`test_whatsapp_campaigns_vm_has_no_credential_fields` pins the whitelist).
Dates, counts and money are pre-formatted here.

What the screen must say plainly (plan §2.5, the WA-20 docstring, Meta's pricing and
per-user-limits pages, read 2026-10-14):

- the cost is an ESTIMATE, and while any rate used is a `[RATE CARD PENDING]` placeholder
  it is only approximate (`RATE_CARD_NOTICE`, shown prominently);
- a send skipped with Meta code `131049` (per-user marketing limit) is retried no sooner
  than 24 h later — retrying sooner extends the block;
- sending templates needs a payment method on the WhatsApp Business account; when Meta
  refuses for that reason (`131042`) the send fails with that code and the campaign says
  so in one sentence.

Pure module: no Reflex, network or database import.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .whatsapp_contacts_vm import SOURCE_KEYS
from .whatsapp_templates_vm import SendVariable, TemplateVM, variable_id, variable_label
from .whatsapp_vm import format_timestamp

STEPS: tuple[str, ...] = ("Plantilla", "Variables", "Audiencia", "Ritmo", "Revisar")
STEP_TEMPLATE, STEP_VARIABLES, STEP_AUDIENCE, STEP_PACING, STEP_REVIEW = range(5)

DEFAULT_MAX_PER_MINUTE = 30
MAX_PER_MINUTE = 1000

RATE_CARD_NOTICE = "Tarifas de referencia pendientes: el costo es aproximado."
#: m-24842994: «opt-in» in the owner's words.
AUDIENCE_NONE = "Ningún contacto que aceptó recibir tus mensajes cumple estos filtros."
PAYMENT_NOTICE = (
    "Para enviar promociones, tu cuenta de WhatsApp Business necesita un método de pago. "
    "Agrégalo en la configuración de pagos de tu cuenta de Meta."
)
PAYMENT_FAILED = (
    "Meta no dejó salir algunos mensajes porque tu cuenta de WhatsApp Business no tiene un "
    "método de pago válido (código 131042). Agrégalo en la configuración de pagos de tu "
    "cuenta de Meta; "
    "los mensajes que no salieron no se vuelven a enviar solos, así que crea una campaña "
    "nueva para esos contactos."
)
SENDER_NOTICE = (
    "Los envíos salen en segundo plano al ritmo elegido; actualiza para ver cómo avanzan."
)

# --------------------------------------------------------------------------------------
# Status → (label, tone)
# --------------------------------------------------------------------------------------

_CAMPAIGN_STATUS: dict[str, tuple[str, str]] = {
    "draft": ("Borrador", "neutral"),
    "scheduled": ("Programada", "info"),
    "running": ("En curso", "info"),
    "paused": ("Pausada", "warn"),
    "done": ("Terminada", "ok"),
    "cancelled": ("Cancelada", "neutral"),
}
LAUNCHABLE = frozenset({"draft", "scheduled", "running"})
NOT_LAUNCHED = frozenset({"draft", "scheduled"})
FINAL = frozenset({"done", "cancelled"})

_SEND_STATUS: dict[str, tuple[str, str]] = {
    "pending": ("Pendiente", "neutral"),
    "queued": ("Por enviar", "info"),
    "sent": ("Enviado", "info"),
    "delivered": ("Entregado", "ok"),
    "read": ("Leído", "ok"),
    "failed": ("Falló", "error"),
    "skipped": ("Omitido", "warn"),
}

# Meta error codes a campaign send can carry (Cloud API error codes, read 2026-10-14),
# plus the two the campaign service writes itself.
ERROR_PER_USER_LIMIT = "131049"
ERROR_PAYMENT = "131042"
_SEND_ERRORS: dict[str, str] = {
    ERROR_PER_USER_LIMIT: "Meta limita cuántas promociones recibe cada persona: inténtalo en 24 h",
    ERROR_PAYMENT: "La cuenta de WhatsApp Business no tiene un método de pago válido",
    "131026": "No se pudo entregar: el número no usa WhatsApp o no aceptó sus términos",
    "131050": "La persona pidió no recibir promociones",
    "131047": "Pasaron más de 24 horas desde su último mensaje",
    "131048": "Límite de envío por calidad: Meta frenó los envíos de este número",
    "131056": "Demasiados mensajes seguidos a la misma persona",
    "132000": "Las variables no coinciden con la plantilla",
    "132001": "La plantilla no existe o no está aprobada en ese idioma",
    "132005": "El texto con variables es demasiado largo",
    "132007": "El contenido infringe las políticas de WhatsApp",
    "132012": "Las variables no tienen el formato que espera la plantilla",
    "132015": "Plantilla pausada por baja calidad",
    "132016": "Plantilla desactivada por baja calidad",
    "130472": "Meta no la entregó (una prueba de promociones de Meta)",
    "not_opted_in": "Ya no aceptaba recibir tus mensajes al enviar",
    "campaign_cancelled": "Campaña cancelada",
}


def campaign_status_display(status: str) -> tuple[str, str]:
    return _CAMPAIGN_STATUS.get(status, (status or "Sin dato", "neutral"))


def send_status_display(status: str) -> tuple[str, str]:
    return _SEND_STATUS.get(status, (status or "Sin dato", "neutral"))


def send_error_note(error_code: str | None, service_note: str | None = None) -> str:
    """One line for a failed/skipped send: Spanish meaning + the Meta code."""
    if not error_code:
        return service_note or ""
    meaning = _SEND_ERRORS.get(error_code) or service_note or "Meta rechazó el envío"
    return f"{meaning} (código {error_code})" if error_code.isdigit() else meaning


# --------------------------------------------------------------------------------------
# Numbers and money
# --------------------------------------------------------------------------------------


def format_count(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def format_money(amount: Decimal, currency: str) -> str:
    """«USD 1,50» / «USD 0,0125» (es-CO separators; up to 4 decimals under one unit —
    per-message rates need them — and never fewer than 2)."""
    places = Decimal("0.0001") if abs(amount) < 1 else Decimal("0.01")
    rounded = amount.quantize(places, rounding=ROUND_HALF_UP)
    whole, _, frac = f"{rounded:f}".partition(".")
    frac = frac.rstrip("0").ljust(2, "0")  # «0,0300» → «0,03»; «0,0125» stays
    sign = "-" if whole.startswith("-") else ""
    whole = f"{int(whole.lstrip('-') or 0):,}".replace(",", ".")
    return f"{currency} {sign}{whole}" + (f",{frac}" if frac else "")


def format_costs(lines: Iterable[tuple[str, Decimal, int]]) -> str:
    """`(currency, amount, sends)` lines → «USD 1,50 · COP 2.000,00»; «—» when none."""
    parts = [format_money(amount, currency) for currency, amount, _n in lines]
    return " · ".join(parts) if parts else "—"


# --------------------------------------------------------------------------------------
# The list and the detail
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CampaignRowVM:
    campaign_id: str
    name: str
    template_label: str
    status: str
    status_label: str
    status_tone: str
    sent: str  # cumulative: sent + delivered + read
    delivered: str  # delivered + read
    read: str
    failed: str
    skipped: str
    queued: str  # pending + queued
    cost_label: str
    created_at: str  # PRE-FORMATTED


def _counts(counts: Mapping[str, int]) -> dict[str, int]:
    read = counts.get("read", 0)
    delivered = counts.get("delivered", 0) + read
    return {
        "sent": counts.get("sent", 0) + delivered,
        "delivered": delivered,
        "read": read,
        "failed": counts.get("failed", 0),
        "skipped": counts.get("skipped", 0),
        "queued": counts.get("pending", 0) + counts.get("queued", 0),
    }


def build_campaign_row(
    *,
    campaign_id: str,
    name: str,
    template_label: str,
    status: str,
    counts: Mapping[str, int],
    costs: Sequence[tuple[str, Decimal, int]],
    created_at: datetime | None,
) -> CampaignRowVM:
    label, tone = campaign_status_display(status)
    c = _counts(counts)
    return CampaignRowVM(
        campaign_id=campaign_id,
        name=name,
        template_label=template_label,
        status=status,
        status_label=label,
        status_tone=tone,
        sent=format_count(c["sent"]),
        delivered=format_count(c["delivered"]),
        read=format_count(c["read"]),
        failed=format_count(c["failed"]),
        skipped=format_count(c["skipped"]),
        queued=format_count(c["queued"]),
        cost_label=format_costs(costs),
        created_at=format_timestamp(created_at, "Sin fecha"),
    )


@dataclass(frozen=True)
class SendVM:
    phone: str
    status_label: str
    status_tone: str
    note: str
    retry_after: str  # «reintentar desde 15 oct 2026, 10:20», "" when n/a
    cost_label: str


def build_send_vm(
    *,
    phone_e164: str,
    status: str,
    error_code: str | None,
    service_note: str | None,
    retry_not_before: datetime | None,
    cost_estimate: Decimal | None,
    currency: str | None,
) -> SendVM:
    label, tone = send_status_display(status)
    return SendVM(
        phone=phone_e164,
        status_label=label,
        status_tone=tone,
        note=send_error_note(error_code, service_note),
        retry_after=(
            f"Reintentar desde {format_timestamp(retry_not_before, '')}"
            if retry_not_before is not None
            else ""
        ),
        cost_label=(
            format_money(cost_estimate, currency)
            if cost_estimate is not None and currency
            else "Sin tarifa"
        ),
    )


@dataclass(frozen=True)
class EstimateVM:
    recipients: str
    cost_label: str
    unpriced: str  # «3 destinatarios sin tarifa conocida», "" when 0
    placeholder: bool
    rate_card_status: str  # the backend's raw marker, e.g. `[RATE CARD PENDING]`


EMPTY_ESTIMATE = EstimateVM(
    recipients="", cost_label="", unpriced="", placeholder=False, rate_card_status=""
)


def build_estimate_vm(
    *,
    recipients: int,
    costs: Sequence[tuple[str, Decimal, int]],
    unpriced: int,
    placeholder: bool,
    rate_card_status: str,
) -> EstimateVM:
    return EstimateVM(
        recipients=format_count(recipients),
        cost_label=format_costs(costs),
        unpriced=(
            f"{format_count(unpriced)} destinatario{'s' if unpriced != 1 else ''} sin tarifa "
            "conocida (no suma al costo)"
            if unpriced
            else ""
        ),
        placeholder=placeholder,
        rate_card_status=rate_card_status if placeholder else "",
    )


@dataclass(frozen=True)
class CampaignDetailVM:
    row: CampaignRowVM
    can_launch: bool
    can_cancel: bool
    retry_after_24h: str  # «4 envíos omitidos por el límite de marketing… », "" when 0
    payment_failed: bool  # any send failed with 131042
    rate_label: str  # «30 mensajes por minuto»


# --------------------------------------------------------------------------------------
# The wizard
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class VariableFieldVM:
    """One input of step 2: `id` = `"<component>:<key>"`, the value typed so far."""

    id: str
    label: str
    example: str
    value: str


def variable_fields(
    variables: Sequence[SendVariable], values: Mapping[str, str]
) -> list[VariableFieldVM]:
    return [
        VariableFieldVM(
            id=variable_id(v),
            label=variable_label(v),
            example=v.example,
            value=values.get(variable_id(v), ""),
        )
        for v in variables
    ]


def validate_basics(name: str, template: TemplateVM | None) -> str:
    if not name.strip():
        return "Ponle un nombre a la campaña (solo lo ve tu equipo)."
    if template is None:
        return "Elige una plantilla aprobada."
    if template.status.upper() != "APPROVED":
        return "La plantilla aún no está aprobada por Meta."
    if template.wizard_block:
        return template.wizard_block
    return ""


def validate_variables(variables: Sequence[SendVariable], values: Mapping[str, str]) -> str:
    for variable in variables:
        if not values.get(variable_id(variable), "").strip():
            return f"Escribe el valor de {variable_label(variable)}."
    return ""


@dataclass(frozen=True)
class AudienceForm:
    brand_id: str  # "" = every brand
    sources: tuple[str, ...]  # () = every source
    captured_from: str  # YYYY-MM-DD or ""
    captured_to: str  # YYYY-MM-DD (inclusive) or ""
    phone_prefixes: str  # «+57, +52» or ""


ALL_BRANDS = "todas"
_PREFIX = re.compile(r"\+[1-9]\d{0,13}")


def _day(value: str) -> date | None:
    return date.fromisoformat(value) if value else None


def audience_filter_json(form: AudienceForm) -> tuple[dict[str, Any], str]:
    """The form → `AudienceFilter.to_json()`'s shape, or ({}, problem). The date window is
    whole UTC days: «hasta» is inclusive (`captured_before` = the next midnight)."""
    out: dict[str, Any] = {}
    if form.brand_id and form.brand_id != ALL_BRANDS:
        out["brand_id"] = form.brand_id
    unknown = [s for s in form.sources if s not in SOURCE_KEYS]
    if unknown:
        return {}, "Elige orígenes de la lista."
    if form.sources:
        out["sources"] = sorted(form.sources)
    try:
        start, end = _day(form.captured_from), _day(form.captured_to)
    except ValueError:
        return {}, "Revisa las fechas: usa el selector de fecha."
    if start and end and start > end:
        return {}, "La fecha «desde» debe ser anterior a «hasta»."
    if start:
        out["captured_after"] = datetime.combine(start, time(), UTC).isoformat()
    if end:
        out["captured_before"] = datetime.combine(end + timedelta(days=1), time(), UTC).isoformat()
    prefixes = [p.strip() for p in form.phone_prefixes.replace(";", ",").split(",") if p.strip()]
    for prefix in prefixes:
        if not _PREFIX.fullmatch(prefix):
            return {}, f"«{prefix}» no es un prefijo válido: escríbelo como +57."
    if prefixes:
        out["phone_prefixes"] = prefixes
    return out, ""


def validate_pacing(raw: str) -> tuple[int, str]:
    try:
        value = int(raw.strip())
    except ValueError:
        return 0, "Escribe cuántos mensajes por minuto (un número)."
    if not 1 <= value <= MAX_PER_MINUTE:
        return 0, f"El ritmo va de 1 a {MAX_PER_MINUTE} mensajes por minuto."
    return value, ""


def rate_label(per_minute: int) -> str:
    return f"{format_count(per_minute)} mensaje{'s' if per_minute != 1 else ''} por minuto"


def pacing_hint(recipients: int, per_minute: int) -> str:
    if recipients <= 0 or per_minute <= 0:
        return ""
    minutes = math.ceil(recipients / per_minute)
    duration = f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60} min"
    return f"≈ {duration} para enviar a {format_count(recipients)} contactos."


def audience_count_label(count: int) -> str:
    if count < 0:
        return ""
    if count == 0:
        return AUDIENCE_NONE
    plural = "s" if count != 1 else ""
    verb = "aceptaron" if count != 1 else "aceptó"
    return f"{format_count(count)} contacto{plural} que {verb} recibir tus mensajes"


def launch_message(*, enqueued: int, skipped: int, audience: int) -> str:
    if audience == 0:
        return "La campaña está en curso, pero no quedó nadie por enviar."
    parts = [f"{format_count(enqueued)} mensajes por salir"]
    if skipped:
        parts.append(f"{format_count(skipped)} sin enviar (ya no aceptaban recibir tus mensajes)")
    return "Empezamos a enviar la campaña: " + ", ".join(parts) + ". " + SENDER_NOTICE


def retry_after_label(count: int) -> str:
    if count <= 0:
        return ""
    return (
        f"{format_count(count)} envío{'s' if count != 1 else ''} omitido"
        f"{'s' if count != 1 else ''} porque Meta limita cuántas promociones recibe cada "
        "persona (código 131049): no se vuelven a intentar antes de 24 horas."
    )


@dataclass(frozen=True)
class OptionVM:
    """A select item: an id and what the operator reads."""

    value: str
    label: str


EMPTY_TEMPLATE = TemplateVM(
    template_id="",
    name="",
    language="",
    language_label="",
    category="",
    category_label="",
    status="",
    status_label="",
    status_tone="neutral",
    quality_label="",
    quality_tone="neutral",
    rejected_reason="",
    header_text="",
    body_text="",
    footer_text="",
    buttons_label="",
    updated_at="",
    can_delete=False,
    sendable=False,
    wizard_block="",
    option_label="",
)

EMPTY_ROW = CampaignRowVM(
    campaign_id="",
    name="",
    template_label="",
    status="",
    status_label="",
    status_tone="neutral",
    sent="0",
    delivered="0",
    read="0",
    failed="0",
    skipped="0",
    queued="0",
    cost_label="—",
    created_at="",
)

EMPTY_DETAIL = CampaignDetailVM(
    row=EMPTY_ROW,
    can_launch=False,
    can_cancel=False,
    retry_after_24h="",
    payment_failed=False,
    rate_label="",
)

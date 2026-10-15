"""View-models for `/whatsapp` → Contactos (WA-19, QUA-218): who agreed to receive this
business's WhatsApp messages, and who said STOP.

`WhatsAppContactsState` only holds the frozen dataclasses below — never a
`whatsapp_opt_ins` ORM row; `proof` (the evidence JSON) never reaches the browser
(`test_whatsapp_contacts_vm_has_no_credential_fields` pins the whitelist). Dates are
pre-formatted here.

Meta's rule surfaced by the form (getting-opt-in, read 2026-10-14): the consent must say
the person agrees to receive messages **from this business**, naming it, and it is the
text the person actually agreed to — so it is required, must mention WhatsApp, and must
name the business when the session knows its name.

Pure module: no Reflex, network or database import.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from .whatsapp_vm import format_timestamp

SOURCES: tuple[tuple[str, str], ...] = (
    ("lead_form", "Formulario de leads"),
    ("menu", "Menú de WhatsApp"),
    ("import", "Importación"),
    ("manual", "Agregado a mano"),
)
SOURCE_KEYS: frozenset[str] = frozenset(key for key, _ in SOURCES)
_SOURCE_LABEL: dict[str, str] = dict(SOURCES)

_REVOKE_REASON: dict[str, str] = {
    "stop_keyword": "Escribió STOP",
    "manual": "Revocado a mano",
}

FILTER_ACTIVE = "activos"
FILTER_ALL = "todos"
FILTERS: tuple[tuple[str, str], ...] = ((FILTER_ACTIVE, "Activos"), (FILTER_ALL, "Todos"))

IMPORT_CONDITION = (
    "Solo si el texto de consentimiento del formulario incluye recibir mensajes de "
    "WhatsApp de tu negocio."
)
MIN_CONSENT_CHARS = 20
_E164 = re.compile(r"\+[1-9]\d{7,14}")


def source_label(source: str) -> str:
    return _SOURCE_LABEL.get(source, source)


@dataclass(frozen=True)
class OptInVM:
    phone: str  # E.164
    source_label: str
    captured_at: str  # PRE-FORMATTED
    is_active: bool
    status_label: str
    status_tone: str
    revoked_detail: str  # «Escribió STOP · 14 oct 2026, 10:20», "" while active
    consent_text: str
    brand: str


def build_opt_in_vm(
    *,
    phone_e164: str,
    source: str,
    captured_at: datetime,
    revoked_at: datetime | None,
    revoke_reason: str | None,
    consent_text: str,
    brand: str | None,
) -> OptInVM:
    active = revoked_at is None
    detail = ""
    if not active:
        reason = _REVOKE_REASON.get(revoke_reason or "", revoke_reason or "Revocado")
        detail = f"{reason} · {format_timestamp(revoked_at, '')}"
    return OptInVM(
        phone=phone_e164,
        source_label=source_label(source),
        captured_at=format_timestamp(captured_at, "Sin fecha"),
        is_active=active,
        status_label="Activo" if active else "Revocado",
        status_tone="ok" if active else "neutral",
        revoked_detail=detail,
        consent_text=consent_text,
        brand=brand or "",
    )


def normalize_phone_input(raw: str) -> str:
    """Spacing/punctuation collapsed; "" when it is not a full E.164 number (the same
    rule as `leads.repository.normalize_phone` and the 0060 CHECK)."""
    candidate = re.sub(r"[\s\-().]", "", raw)
    return candidate if _E164.fullmatch(candidate) else ""


def suggested_consent(business_name: str) -> str:
    name = business_name.strip() or "nuestro negocio"
    return f"Acepto recibir mensajes de WhatsApp de {name} con novedades, pedidos y promociones."


def validate_manual_opt_in(phone: str, consent_text: str, business_name: str) -> str:
    """Spanish copy for the first problem; "" when the opt-in can be recorded."""
    if not normalize_phone_input(phone):
        return "Escribe el número completo con el indicativo del país, por ejemplo +57 300 1234567."
    text = consent_text.strip()
    if not text:
        return "Escribe el texto que la persona aceptó: Meta exige guardarlo."
    if len(text) < MIN_CONSENT_CHARS:
        return "El texto de consentimiento es muy corto: di qué va a recibir y de quién."
    if "whatsapp" not in text.lower():
        return "El texto debe decir que la persona acepta recibir mensajes de WhatsApp."
    name = business_name.strip()
    if name and name.lower() not in text.lower():
        return f"El texto debe nombrar a tu negocio («{name}»), como pide Meta."
    return ""


RECORD_OUTCOME_COPY: dict[str, tuple[str, str]] = {
    "created": ("Contacto agregado con su consentimiento.", "ok"),
    "unchanged": (
        "Ese número ya tenía un consentimiento activo; se conserva el original.",
        "info",
    ),
    "reconsented": ("Consentimiento renovado: el número vuelve a estar activo.", "ok"),
    "suppressed": (
        "No se reactivó: ese número pidió no recibir mensajes después de este consentimiento.",
        "warn",
    ),
}


def import_report_message(
    *, leads: int, created: int, unchanged: int, reconsented: int, suppressed: int, skipped: int
) -> tuple[str, str]:
    """(message, tone) for `OptInService.import_from_leads`'s `ImportReport`."""
    if leads == 0:
        return "El formulario de leads aún no tiene contactos con consentimiento.", "info"
    parts = [f"{created} nuevos", f"{unchanged} ya estaban"]
    if reconsented:
        parts.append(f"{reconsented} reactivados")
    if suppressed:
        parts.append(f"{suppressed} no reactivados porque escribieron STOP después")
    if skipped:
        parts.append(f"{skipped} sin texto de consentimiento o con un número inválido")
    tone = "ok" if created or reconsented else "info"
    return f"Importados {leads} leads del formulario: " + ", ".join(parts) + ".", tone

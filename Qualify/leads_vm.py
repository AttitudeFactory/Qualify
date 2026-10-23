"""Pure view model of «Clientes interesados» (m-24842992).

No Reflex, no database: everything here is a function of plain values, so the words the
owner reads and the links they tap are tested offline (`test_leads_vm.py`).

- **Write to them:** «Escribirle por WhatsApp ↗» opens the owner's own WhatsApp on a
  `wa.me` chat with that person (N9: leaving Qualify is announced with ↗). Qualify sends
  nothing: the owner writes and presses send (N13). The person reached this list only by
  accepting, on the form, that the business contacts them (`leads.consent_at`, NOT NULL).
- **Who was already written to:** opening the chat marks the person «Ya le escribiste»
  (`leads.contacted_at`, migration 0086); «Marcar como pendiente» undoes it. The state is
  a word, never only a colour.
- **Empty list:** the real form link with «Copiar enlace» (N8) when the business has one.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PENDING_LABEL: Final = "Pendiente"
CONTACTED_LABEL: Final = "Ya le escribiste"
PENDING_TONE: Final = "warn"
CONTACTED_TONE: Final = "ok"

WRITE_LABEL: Final = "Escribirle por WhatsApp ↗"
MARK_PENDING_LABEL: Final = "Marcar como pendiente"

INTRO: Final = "Personas que te dejaron sus datos y aceptaron que las contactes."
HOW_IT_WORKS: Final = (
    "Al tocar «Escribirle por WhatsApp» se abre tu WhatsApp con esa persona. Tú escribes "
    "y envías; aquí la marcamos como «Ya le escribiste»."
)

EMPTY_TITLE: Final = "Todavía no hay interesados"
EMPTY_WITH_LINK: Final = (
    "Comparte este enlace en tu perfil o en tus historias para que te dejen sus datos."
)
EMPTY_NO_LINK: Final = (
    "Cuando alguien deje sus datos en tu formulario y acepte que lo contactes, aparecerá "
    "aquí. Pídenos el enlace de tu formulario para compartirlo en tu perfil o en tus "
    "historias."
)
COPY_LINK_LABEL: Final = "Copiar enlace"
LINK_COPIED: Final = "Enlace copiado. Pégalo en tu perfil o en una historia."

EXTRA_LABEL: Final = "Lo que te contaron:"

MARK_FAILED: Final = "No pudimos guardar el cambio. Inténtalo de nuevo en unos segundos."

_MONTHS: Final = (
    "ene",
    "feb",
    "mar",
    "abr",
    "may",
    "jun",
    "jul",
    "ago",
    "sep",
    "oct",
    "nov",
    "dic",
)


def zone_for(name: str | None) -> ZoneInfo:
    """The tenant's IANA zone, UTC when unknown or malformed."""
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def wa_href(phone: str) -> str:
    """`wa.me` wants the E.164 number without the leading '+'."""
    return f"https://wa.me/{phone.lstrip('+')}"


def contact_label(contacted_at: datetime | None) -> str:
    return CONTACTED_LABEL if contacted_at is not None else PENDING_LABEL


def contact_tone(contacted_at: datetime | None) -> str:
    return CONTACTED_TONE if contacted_at is not None else PENDING_TONE


def contacted_note(contacted_at: datetime | None, zone: ZoneInfo) -> str:
    """«Le escribiste el 23 oct.» in the tenant's zone; "" while pending."""
    if contacted_at is None:
        return ""
    local = contacted_at.astimezone(zone)
    return f"Le escribiste el {local.day} {_MONTHS[local.month - 1]}."


def registered_label(created_at: datetime, zone: ZoneInfo) -> str:
    """«Te dejó sus datos el 14 ago.» in the tenant's zone."""
    local = created_at.astimezone(zone)
    return f"Te dejó sus datos el {local.day} {_MONTHS[local.month - 1]}."


def extra_summary(extra: dict[str, str]) -> str:
    """«zona: oeste · turno: tarde» — the answers to the business's own questions."""
    return " · ".join(f"{k}: {v}" for k, v in sorted(extra.items()))


def form_url(template: str, tenant_id: str, *, form_active: bool) -> str:
    """The public form address to share, or "" when there is none to give.

    `template` is the deployment's `QUALIFY_LEAD_FORM_URL` with a `{tenant_id}`
    placeholder (e.g. `https://qualify.la/interes?e={tenant_id}`). No template, no
    placeholder or no active form → "": the empty state then never shows a link that
    leads nowhere.
    """
    template = template.strip()
    if not form_active or not template or "{tenant_id}" not in template:
        return ""
    return template.replace("{tenant_id}", tenant_id)


def empty_description(link: str) -> str:
    return EMPTY_WITH_LINK if link else EMPTY_NO_LINK

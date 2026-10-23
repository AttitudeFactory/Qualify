"""Pure helpers of the access gate (MARCA-5, m-24842968): the invitation code a visitor
types or pastes, and the Spanish sentence for each way the «Quiero que me contacten»
form can fail. No Reflex, no DB — tested in `test_access_gate.py`."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from qualify_api.auth import INVITE_PARAM, LEGACY_INVITE_PARAM
from qualify_api.leads.interest import INTEREST_CONSENT_TEXT

#: The notice every visitor reads before starting (founder decision 7b), verbatim.
ACCESS_NOTICE = (
    "Qualify es solo por invitación. Si tienes tu código, escríbelo y sigue. "
    "Si no lo tienes, déjanos tus datos y te escribimos."
)
INTEREST_SENT = "Listo. Te escribimos por WhatsApp cuando tu invitación esté lista."
#: The checkbox shows the very text stamped as the consent policy on every entry.
CONSENT_LABEL = INTEREST_CONSENT_TEXT

CODE_EMPTY = "Escribe o pega el código de tu invitación."
CODE_DEAD = (
    "Ese código no sirve: venció, ya se usó o le falta algo. Cópialo otra vez del correo "
    "de tu invitación o pide uno nuevo a quien te invitó."
)
ACCESS_DOWN = "No pudimos revisar tu código. Inténtalo de nuevo en un momento."

_INTEREST_ERRORS = {
    "consent": "Marca la casilla «Acepto que me escriban por WhatsApp» para que podamos "
    "escribirte.",
    "full_name": "Escribe tu nombre.",
    "business_name": "Escribe el nombre de tu negocio.",
    "whatsapp_phone": "Escribe tu WhatsApp con el código de tu país, por ejemplo +58 414 123 4567.",
    "rate_limited": "Ya recibimos varios envíos desde aquí. Espera unos minutos y vuelve a "
    "intentarlo.",
    "not_configured": "No pudimos guardar tus datos en este momento. Inténtalo de nuevo más tarde.",
    "down": "No pudimos guardar tus datos en este momento. Inténtalo de nuevo en un momento.",
}


def interest_error_message(reason: str) -> str:
    """The sentence the form shows for `reason` (an `InterestInvalid.field`, or
    `rate_limited` / `not_configured` / `down`): what happened and what to do."""
    return _INTEREST_ERRORS.get(reason, _INTEREST_ERRORS["down"])


def invite_token_from_text(text: str) -> str:
    """The invite token in what the visitor typed: the code alone, or the whole link of
    the invitation email pasted as is (`…/registro?invitacion=<code>`, or the older
    `?invite=`). Surrounding spaces and line breaks — what a phone's paste brings — go."""
    cleaned = "".join((text or "").split())
    if not cleaned:
        return ""
    if "?" in cleaned or "://" in cleaned:
        query = parse_qs(urlparse(cleaned).query)
        for name in (INVITE_PARAM, LEGACY_INVITE_PARAM):
            values = query.get(name)
            if values and values[0]:
                return values[0]
        return ""
    return cleaned

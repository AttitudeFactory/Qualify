"""The invitation email (2026-10-14): the first thing a client ever receives from Qualify.

Written for real mail clients, not browsers: table layout, inline styles only (Gmail
strips `<style>` in many contexts), a "bulletproof" button whose colour lives on the
table cell so Outlook still paints it, a hidden preheader (the grey line next to the
subject in the inbox), a light colour scheme declared so Apple Mail does not invert the
brand teal, and a plain-text twin for clients that show no HTML. Every value that comes
from a person — name, business, note, email — is HTML-escaped; the note keeps its line
breaks.

The mark is a hosted PNG (`/qualify-mark-email.png`, the light variant of the Q radar
isotype): mail clients do not render SVG.
"""

from __future__ import annotations

import html
from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from qualify_api.mail import OutgoingMail

if TYPE_CHECKING:  # pragma: no cover - typing only (invites imports this module)
    from qualify_api.auth.invites import CreatedInvite

#: The dates in the email read in the founder's market time, not UTC.
_TZ = ZoneInfo("America/Caracas")
_MONTHS = (
    "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre"
).split()
_LOGO_PATH = "/qualify-mark-email.png"

# Palette: the design system's teal (light scheme) and slate grays. Teal 11 for the button
# so white text clears WCAG AA (≈4.9:1); teal 9 would not.
_INK = "#1c2024"
_MUTED = "#60646c"
_FAINT = "#8b8d98"
_LINE = "#e4e6ea"
_PAGE = "#f4f5f7"
_CARD = "#ffffff"
_TEAL = "#008573"
_TEAL_SOFT = "#e6f7f4"
_FONT = (
    "'IBM Plex Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
)


def _date_es(moment: datetime) -> str:
    local = moment.astimezone(_TZ)
    return f"{local.day} de {_MONTHS[local.month - 1]}"


def _first_name(full: str) -> str:
    return full.split()[0] if full.split() else ""


def subject_for(invite: CreatedInvite, signer: str) -> str:
    first = _first_name(signer)
    if first and invite.business_name:
        return f"{first} te invitó a crear la cuenta de {invite.business_name} en Qualify"
    if first:
        return f"{first} te invitó a Qualify"
    if invite.business_name:
        return f"Tu invitación a Qualify para {invite.business_name}"
    return "Tu invitación a Qualify"


def _lead_text(invite: CreatedInvite, signer: str) -> tuple[str, str, str]:
    """(before, bold, after) of the opening sentence, unescaped."""
    who = f"{signer} te invitó" if signer else "Te invitamos"
    business = invite.business_name or "tu negocio"
    return f"{who} a crear la cuenta de ", business, " en Qualify."


# --------------------------------------------------------------------------------------
# Plain text
# --------------------------------------------------------------------------------------


def _text(invite: CreatedInvite, link: str, signer: str, expires: str, can_reply: bool) -> str:
    before, bold, after = _lead_text(invite, signer)
    lines = [f"Hola, {invite.recipient_name}:" if invite.recipient_name else "Hola:", ""]
    lines += [f"{before}{bold}{after}", ""]
    if invite.note:
        lines += [f"«{invite.note}»", *([f"— {signer}"] if signer else []), ""]
    lines += [
        "En Qualify armas el Brand Kit de tu marca y, desde ahí, creas, planificas y",
        "respondes en Instagram con la voz de tu negocio.",
        "",
        "Crea tu cuenta aquí:",
        link,
        "",
        "1. Crea tu contraseña.",
        "2. Arma tu Brand Kit en unos minutos.",
        "3. Empieza a crear contenido.",
        "",
        f"El enlace es personal: funciona solo para {invite.email}, una vez, hasta el {expires}.",
        "",
    ]
    if can_reply:
        lines += ["¿Dudas? Responde este correo y te ayudamos.", ""]
    lines += [
        "Si no esperabas esta invitación, ignora este correo: sin el enlace nadie puede",
        "crear una cuenta con tu dirección.",
        "",
        "— Qualify",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------------------

_TABLE = 'role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"'


def _p(text: str, *, size: int = 15, color: str = _INK, margin: str = "0 0 16px 0") -> str:
    style = f"margin:{margin};font-size:{size}px;line-height:1.6;color:{color};"
    return f'<p style="{style}">{text}</p>'


def _note_block(note: str, signer: str) -> str:
    body = html.escape(note).replace("\n", "<br>")
    cite = (
        f'<p style="margin:10px 0 0 0;font-size:13px;color:{_MUTED};">— {html.escape(signer)}</p>'
        if signer
        else ""
    )
    return (
        f'<table {_TABLE} style="margin:0 0 24px 0;">'
        f'<tr><td style="background:{_TEAL_SOFT};border-left:3px solid {_TEAL};'
        f'border-radius:0 10px 10px 0;padding:16px 18px;">'
        f'<p style="margin:0;font-size:15px;line-height:1.6;color:{_INK};font-style:italic;">'
        f"{body}</p>{cite}</td></tr></table>"
    )


def _button(link: str, label: str) -> str:
    href = html.escape(link, quote=True)
    anchor = (
        f'<a href="{href}" target="_blank" style="display:inline-block;padding:14px 28px;'
        f"font-family:{_FONT};font-size:16px;font-weight:600;color:#ffffff;"
        f'text-decoration:none;border-radius:10px;">{html.escape(label)}</a>'
    )
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:8px 0 28px 0;">'
        f'<tr><td align="center" bgcolor="{_TEAL}" style="border-radius:10px;">'
        f"{anchor}</td></tr></table>"
    )


def _steps() -> str:
    items = (
        ("1", "Crea tu contraseña"),
        ("2", "Arma tu Brand Kit en unos minutos"),
        ("3", "Empieza a crear contenido"),
    )
    rows = "".join(
        f'<tr><td width="28" valign="top" style="padding:0 0 10px 0;">'
        f'<div style="width:22px;height:22px;line-height:22px;border-radius:11px;'
        f"background:{_TEAL_SOFT};color:{_TEAL};font-size:12px;font-weight:700;"
        f'text-align:center;">{n}</div></td>'
        f'<td valign="top" style="padding:1px 0 10px 8px;font-size:14px;line-height:1.5;'
        f'color:{_INK};">{text}</td></tr>'
        for n, text in items
    )
    return f'<table {_TABLE} style="margin:0 0 24px 0;">{rows}</table>'


def _html(
    invite: CreatedInvite,
    link: str,
    base_url: str,
    signer: str,
    expires: str,
    can_reply: bool,
    preheader: str,
) -> str:
    esc = html.escape
    before, bold, after = _lead_text(invite, signer)
    greeting = f"Hola, {esc(invite.recipient_name)}:" if invite.recipient_name else "Hola:"
    lead = f"{esc(before)}<strong>{esc(bold)}</strong>{esc(after)}"
    logo = esc(f"{base_url.rstrip('/')}{_LOGO_PATH}", quote=True)
    reply = (
        _p("¿Dudas? Responde este correo y te ayudamos.", size=14, color=_MUTED)
        if can_reply
        else ""
    )
    fine = _p(
        f"El enlace es personal: funciona solo para <strong>{esc(invite.email)}</strong>, "
        f"una vez, hasta el <strong>{esc(expires)}</strong>. Si el botón no abre, copia "
        f'este enlace en tu navegador:<br><a href="{esc(link, quote=True)}" '
        f'style="color:{_TEAL};word-break:break-all;">{esc(link)}</a>',
        size=13,
        color=_MUTED,
        margin="0 0 12px 0",
    )
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
<title>{esc(subject_for(invite, signer))}</title>
</head>
<body style="margin:0;padding:0;background:{_PAGE};font-family:{_FONT};color:{_INK};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:{_PAGE};">
{esc(preheader)}&#8199;&#65279;&#847;&#8199;&#65279;&#847;&#8199;&#65279;&#847;
</div>
<table {_TABLE} style="background:{_PAGE};">
<tr><td align="center" style="padding:32px 16px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
 style="max-width:560px;">
<tr><td style="padding:0 4px 20px 4px;">
<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
<td valign="middle"><img src="{logo}" width="28" height="28" alt=""
 style="display:block;border:0;"></td>
<td valign="middle" style="padding-left:8px;font-size:19px;font-weight:700;
 letter-spacing:-0.01em;color:{_INK};">Qualify</td>
</tr></table>
</td></tr>
<tr><td style="background:{_CARD};border:1px solid {_LINE};border-radius:16px;
 padding:36px 36px 28px 36px;">
<h1 style="margin:0 0 16px 0;font-size:22px;line-height:1.3;font-weight:700;
 color:{_INK};">{greeting}</h1>
{_p(lead, size=16)}
{_note_block(invite.note, signer) if invite.note else ""}
{
        _p(
            "En Qualify armas el Brand Kit de tu marca y, desde ahí, creas, planificas y "
            "respondes en Instagram con la voz de tu negocio.",
            color=_MUTED,
            margin="0 0 24px 0",
        )
    }
{_button(link, "Crear mi cuenta")}
{_steps()}
<div style="border-top:1px solid {_LINE};margin:0 0 16px 0;"></div>
{fine}
{reply}
</td></tr>
<tr><td style="padding:20px 8px 0 8px;">
<p style="margin:0 0 6px 0;font-size:12px;line-height:1.6;color:{_FAINT};">
Si no esperabas esta invitación, ignora este correo: sin el enlace nadie puede crear una
cuenta con tu dirección.</p>
<p style="margin:0;font-size:12px;line-height:1.6;color:{_FAINT};">
Qualify · Attitude Factory</p>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>
"""


def invite_email(
    invite: CreatedInvite, base_url: str, *, signer: str = "", can_reply: bool = False
) -> OutgoingMail:
    """Build the invitation. `signer` is the inviting person's name ("Herwin Rey"); empty
    makes the email speak as Qualify. `can_reply` adds the "reply to this email" line —
    only true when the mailer has a Reply-To a person reads."""
    signer = signer.strip()
    link = invite.link(base_url)
    expires = _date_es(invite.expires_at)
    business = invite.business_name or "tu negocio"
    preheader = (
        f"Crea la cuenta de {business} en un minuto. El enlace es personal y vence el {expires}."
    )
    return OutgoingMail(
        to=invite.email,
        subject=subject_for(invite, signer),
        text=_text(invite, link, signer, expires, can_reply),
        html=_html(invite, link, base_url, signer, expires, can_reply, preheader),
    )

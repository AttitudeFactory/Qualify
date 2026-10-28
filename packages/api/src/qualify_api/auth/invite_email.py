"""The invitation email (2026-10-14): the first thing a client ever receives from Qualify.

Written for real mail clients, not browsers: table layout, inline styles for everything
that must survive (Gmail strips `<style>` in many contexts), a "bulletproof" button whose
colour lives on the table cell so Outlook still paints it, a hidden preheader (the grey
line next to the subject in the inbox), and a plain-text twin for clients that show no
HTML. Every value that comes from a person — name, business, note, email — is
HTML-escaped; the note keeps its line breaks.

Design system (2026-10-21, `docs/design-system.md`): the email is the app's login card
on the app's ground. Colours are the Radix steps the app resolves to — teal accent, slate
gray, light by default — named here by ROLE (§3.1, P7), never by hue. Shapes are the
kit's: 20px card, 12px controls; type is IBM Plex Sans with Plex Mono for identifiers
(the email address, the link; P6). The header is the auth card's lockup (`brand_mark`),
so the screen the link opens looks like the email that sent it.

Dark mode: the inline styles are the light theme; a `<style>` block re-maps the same
roles to Radix's dark steps for clients that honour `prefers-color-scheme` (Apple Mail,
iOS, Outlook for Mac). Clients that strip it get the light theme, intact. The mark is
the app icon (`/qualify-icon-email.png`, rendered from `assets/qualify-icon.svg`): a
dark tile with the teal Q, legible on both grounds, so no image swap is needed. Mail
clients do not render SVG.

Voice (2026-10-21): like a neighbour who knows you — name first, short sentences, "es
rapidito", "te echamos una mano", a sign-off from people. Still tú and Latin neutral (§7.1).

Readable secondary text uses slate 11, not the app's `TEXT_MUTED` (slate 10): on white,
slate 10 is ~3.9:1 and the 12-13px lines here need AA (4.5:1). The button is teal 11 for
the same reason — white on teal 9 is ~3.1:1.
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
_LOGO_PATH = "/qualify-icon-email.png"
_QUALIFY_SITE = "https://qualify.la"
# The company site has no Spanish version yet (2026-10-21: `/` redirects to `/en`, `/es`
# is a 404). Point this at the Spanish path the day it exists.
_ATTITUDE_SITE = "https://attitudefactory.co"
# The three "Cómo funciona" scenes of qualify.la (StepBrand, StepSchedule, StepInbox),
# captured with Playwright frame by frame at 2x (304 px for a ~152 px column). Each plays
# once; the second holds its first frame until the first is done, the third until the
# second is — so the row reads as one story, left to right.
_SCENE_PATH = "/qualify-paso{n}-{theme}.gif"
_SCENES = (
    (
        "Tu negocio",
        "Nos cuentas de tu logo, tus colores y cómo hablas.",
        "Tu logo, tus colores y tu forma de hablar, conectados a tus redes",
    ),
    (
        "Tus publicaciones",
        "Te las dejamos listas y salen cuando tú digas.",
        "Un calendario de la semana llenándose de publicaciones con su hora",
    ),
    (
        "Tu gente",
        "Les contestas a todos desde un solo lugar.",
        "Mensajes contestados que terminan en un cliente por WhatsApp",
    ),
)

# Roles → Radix light steps (slate gray, teal accent). The dark equivalents live in
# `_DARK_CSS`, keyed by the same role classes.
_GROUND = "#f0f0f3"  # slate 3 — the app ground under the card
_GROUND_EDGE = "#e8e8ec"  # slate 4 — where the ground's 140° run ends (one step, so the
# seam with the plain body under a short email stays invisible)
_PANEL = "#ffffff"  # panel-solid — the card
_LINE = "#e0e1e6"  # slate 5 — borders and the hairline
_INK = "#1c2024"  # slate 12 — text
_MUTED = "#60646c"  # slate 11 — secondary text that must be read
_ACCENT = "#008573"  # teal 11 — button fill, links, the step numbers
_ACCENT_SOFT = "#e0f8f3"  # teal 3 — the note's surface, the step chips
_ACCENT_LINE = "#a1ded2"  # teal 6 — the note's edge
_GLOW = "rgba(18,165,148,0.10)"  # teal a3-ish — the ground's top-left light
_GLOW_2 = "rgba(62,99,221,0.07)"  # iris a3-ish — the ground's bottom-right light

_RADIUS_CARD = "20px"
_RADIUS_CONTROL = "12px"
_SANS = (
    "'IBM Plex Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
)
_MONO = "'IBM Plex Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
_FONTS_URL = (
    "https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500"
    "&family=IBM+Plex+Sans:wght@400;600;700&display=swap"
)

# Same roles, Radix dark steps. `!important` beats the inline light values.
_DARK_CSS = """
@media (prefers-color-scheme: dark) {
  .q-ground { background: #111113 !important; background-image: none !important; }
  .q-panel { background: #18191b !important; border-color: #2e3135 !important; }
  .q-line { border-color: #2e3135 !important; }
  .q-ink { color: #edeef0 !important; }
  .q-muted { color: #b0b4ba !important; }
  .q-accent { color: #0bd8b6 !important; }
  .q-soft { background: #0d2d2a !important; border-color: #145750 !important; }
  .q-chip { background: #023b37 !important; color: #0bd8b6 !important; }
}
/* The app menu's glass shimmer (assets/qualify.css, q-glass-shimmer): a soft band that
   crosses the button every 5.2 s. Hidden inline, so clients without <style> (Gmail) keep
   the static gloss only; Apple Mail and iOS animate it. */
.q-shine {
  display: block !important;
  position: absolute; top: -60%; left: -60%; width: 40%; height: 220%;
  transform: rotate(25deg);
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.5), transparent);
  animation: q-shine 5.2s ease-in-out infinite;
  pointer-events: none;
}
@keyframes q-shine {
  0%, 100% { left: -60%; opacity: 0.4; }
  50% { left: 110%; opacity: 0.8; }
}
@media (prefers-reduced-motion: reduce) {
  .q-shine { animation: none !important; display: none !important; }
}
@media (max-width: 600px) {
  .q-panel-pad { padding: 28px 22px 22px 22px !important; }
  .q-btn-table { width: 100% !important; }
  .q-btn-cell, .q-btn-link { display: block !important; width: 100% !important; }
  .q-btn-link { box-sizing: border-box; text-align: center !important; }
}
"""


def _date_es(moment: datetime) -> str:
    local = moment.astimezone(_TZ)
    return f"{local.day} de {_MONTHS[local.month - 1]}"


#: Public alias: the Meegle comments use the same Spanish date as the email.
date_es = _date_es


def _first_name(full: str) -> str:
    return full.split()[0] if full.split() else ""


def subject_for(invite: CreatedInvite, signer: str) -> str:
    """Name first, like a message from someone you know (founder, 2026-10-21: "que se
    sienta como hablar con un vecino")."""
    if invite.is_add_business:
        return "Agrega otro negocio a tu cuenta"
    first = _first_name(signer)
    name = _first_name(invite.recipient_name)
    if name and first:
        return f"{name}, {first} te invitó a Qualify"
    if first:
        return f"{first} te invitó a Qualify"
    if name:
        return f"{name}, te invitamos a Qualify"
    if invite.business_name:
        return f"Tu invitación a Qualify para {invite.business_name}"
    return "Tienes una invitación a Qualify"


def _greeting(invite: CreatedInvite) -> str:
    """Unescaped."""
    return f"¡Hola, {invite.recipient_name}!" if invite.recipient_name else "¡Hola!"


def _lead_text(invite: CreatedInvite, signer: str) -> tuple[str, str, str]:
    """(before, bold, after) of the opening sentence, unescaped."""
    business = invite.business_name or "tu negocio"
    if invite.is_add_business:
        return (
            "Te invitaron a manejar ",
            business,
            " con tu misma cuenta. Escribe tu contraseña para confirmarlo.",
        )
    who = f"{signer} te invitó" if signer else "Te invitamos"
    return f"{who} a Qualify para que abras la cuenta de ", business, "."


_EASY = "Es rapidito: pones una contraseña y ya estás adentro."
_SCENE_TITLE = "Así de sencillo"
_REPLY = "¿Te quedó alguna duda? Responde este correo y te echamos una mano."
_SIGN_OFF = ("Nos vemos adentro,", "el equipo de Qualify")
_DISCLAIMER = (
    "¿No esperabas este correo? No pasa nada, puedes ignorarlo: sin este enlace nadie puede "
    "crear una cuenta con tu correo."
)


def _fine_print(email: str, expires: str) -> str:
    """Unescaped; the HTML builds its own with the email in mono."""
    return (
        f"Este enlace es solo para ti ({email}): sirve una sola vez y hasta el {expires}. "
        "Si el botón no te abre, copia esto en tu navegador:"
    )


# --------------------------------------------------------------------------------------
# Plain text
# --------------------------------------------------------------------------------------


def _text(invite: CreatedInvite, link: str, signer: str, expires: str, can_reply: bool) -> str:
    before, bold, after = _lead_text(invite, signer)
    easy = "" if invite.is_add_business else f" {_EASY}"
    lines = [_greeting(invite), "", f"{before}{bold}{after}{easy}", ""]
    if invite.note:
        lines += [f"«{invite.note}»", *([f"— {signer}"] if signer else []), ""]
    action_prompt = "Agrega tu negocio aquí:" if invite.is_add_business else "Crea tu cuenta aquí:"
    lines += [
        action_prompt,
        link,
        "",
        f"{_SCENE_TITLE}:",
        *(f"{n}. {title}: {line}" for n, (title, line, _) in enumerate(_SCENES, start=1)),
        "",
        *_SIGN_OFF,
        "",
        _fine_print(invite.email, expires),
        link,
        "",
    ]
    if can_reply:
        lines += [_REPLY, ""]
    lines += [_DISCLAIMER]
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------------------

_TABLE = 'role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"'
_TABLE_AUTO = 'role="presentation" cellpadding="0" cellspacing="0" border="0"'


def _p(
    text: str,
    *,
    size: int = 15,
    role: str = "ink",
    margin: str = "0 0 16px 0",
) -> str:
    color = _MUTED if role == "muted" else _INK
    style = f"margin:{margin};font-family:{_SANS};font-size:{size}px;line-height:1.6;color:{color};"
    return f'<p class="q-{role}" style="{style}">{text}</p>'


def _lockup(base_url: str, *, icon: int, word: int) -> str:
    """The auth card's `brand_mark`: the app icon and the wordmark, side by side, both
    linking to the public site."""
    src = html.escape(f"{base_url.rstrip('/')}{_LOGO_PATH}", quote=True)
    href = f'href="{_QUALIFY_SITE}" target="_blank"'
    return (
        f"<table {_TABLE_AUTO}><tr>"
        f'<td valign="middle"><a {href} style="text-decoration:none;">'
        f'<img src="{src}" width="{icon}" height="{icon}" alt="Qualify" '
        f'style="display:block;border:0;border-radius:{round(icon * 0.22)}px;"></a></td>'
        f'<td valign="middle" style="padding-left:10px;">'
        f'<a {href} class="q-ink" style="font-family:{_SANS};font-size:{word}px;'
        f"font-weight:700;letter-spacing:-0.012em;color:{_INK};text-decoration:none;"
        f'">Qualify</a></td>'
        "</tr></table>"
    )


def _badge(label: str) -> str:
    """A `surface` tag (P2: a category, not a state) — the kit's badge type."""
    return (
        f'<table {_TABLE_AUTO} style="margin:0 0 14px 0;"><tr>'
        f'<td class="q-chip" style="background:{_ACCENT_SOFT};border-radius:999px;'
        f"padding:4px 10px;font-family:{_SANS};font-size:12px;font-weight:600;"
        f'letter-spacing:0.03em;color:{_ACCENT};">{html.escape(label)}</td>'
        "</tr></table>"
    )


def _note_block(note: str, signer: str) -> str:
    """The personal line, as the app's soft accent callout."""
    body = html.escape(note).replace("\n", "<br>")
    cite = (
        f'<p class="q-muted" style="margin:10px 0 0 0;font-family:{_SANS};font-size:13px;'
        f'line-height:1.5;color:{_MUTED};">— {html.escape(signer)}</p>'
        if signer
        else ""
    )
    return (
        f'<table {_TABLE} style="margin:0 0 24px 0;">'
        f'<tr><td class="q-soft" style="background:{_ACCENT_SOFT};'
        f"border:1px solid {_ACCENT_LINE};border-radius:{_RADIUS_CONTROL};"
        f'padding:16px 18px;">'
        f'<p class="q-ink" style="margin:0;font-family:{_SANS};font-size:15px;line-height:1.6;'
        f'color:{_INK};">{body}</p>{cite}</td></tr></table>'
    )


def _button(link: str, label: str) -> str:
    """The one `solid` action (P3), in the kit's button type: 700, -0.01em — with the menu
    capsule's glass: a gloss on the top edge for every client (it fades out before the
    label, so white-on-teal stays AA) and the travelling shimmer where `<style>` lives."""
    href = html.escape(link, quote=True)
    anchor = (
        f'<a class="q-btn-link" href="{href}" target="_blank" style="position:relative;'
        f"display:inline-block;padding:14px 28px;font-family:{_SANS};font-size:16px;"
        f"font-weight:700;letter-spacing:-0.01em;color:#ffffff;text-decoration:none;"
        f'border-radius:{_RADIUS_CONTROL};">{html.escape(label)}</a>'
    )
    gloss = "linear-gradient(180deg,rgba(255,255,255,0.24) 0%,rgba(255,255,255,0) 38%)"
    return (
        f'<table {_TABLE_AUTO} align="center" class="q-btn-table" '
        f'style="margin:4px auto 28px auto;">'
        f'<tr><td class="q-btn-cell" align="center" bgcolor="{_ACCENT}" '
        f'style="background-color:{_ACCENT};background-image:{gloss};'
        f"border-radius:{_RADIUS_CONTROL};box-shadow:0 8px 20px rgba(0,133,115,0.28),"
        f'inset 0 1px 0 rgba(255,255,255,0.35);">'
        f'<div style="position:relative;overflow:hidden;border-radius:{_RADIUS_CONTROL};">'
        f'<span class="q-shine" style="display:none;"></span>{anchor}</div>'
        "</td></tr></table>"
    )


def _scene_cell(base: str, n: int, title: str, line: str, alt: str) -> str:
    esc = html.escape
    light = esc(f"{base}{_SCENE_PATH.format(n=n, theme='light')}", quote=True)
    dark = esc(f"{base}{_SCENE_PATH.format(n=n, theme='dark')}", quote=True)
    return (
        f'<td width="31%" valign="top" style="width:31%;">'
        f'<picture><source srcset="{dark}" media="(prefers-color-scheme: dark)">'
        f'<img src="{light}" width="152" alt="{esc(alt, quote=True)}" style="display:block;'
        f"width:100%;max-width:152px;height:auto;border:0;border-radius:10px;"
        f'margin:0 0 10px 0;"></picture>'
        f'<p class="q-ink" style="margin:0 0 2px 0;font-family:{_SANS};font-size:14px;'
        f'font-weight:600;line-height:1.35;color:{_INK};">'
        f'<span class="q-accent" style="font-family:{_MONO};color:{_ACCENT};">{n}</span> '
        f"{esc(title)}</p>"
        f'<p class="q-muted" style="margin:0;font-family:{_SANS};font-size:12px;'
        f'line-height:1.45;color:{_MUTED};">{esc(line)}</p></td>'
    )


def _scenes(base_url: str) -> str:
    """The landing's three "Cómo funciona" scenes in a row, joined by an accent chevron:
    what Qualify does for the business, shown rather than explained — in the customer's
    words, never the product's ("Brand Kit" means nothing to a shop owner)."""
    base = base_url.rstrip("/")
    joint = (
        '<td width="3%" valign="top" style="width:3%;padding-top:38px;">'
        f'<div class="q-accent" style="font-family:{_SANS};font-size:14px;line-height:1;'
        f'text-align:center;color:{_ACCENT};">&rsaquo;</div></td>'
    )
    cells = joint.join(
        _scene_cell(base, n, title, line, alt)
        for n, (title, line, alt) in enumerate(_SCENES, start=1)
    )
    title = (
        f'<p class="q-ink" style="margin:0 0 12px 0;font-family:{_SANS};font-size:15px;'
        f'font-weight:600;color:{_INK};">{html.escape(_SCENE_TITLE)}</p>'
    )
    return f'{title}<table {_TABLE} style="margin:0 0 24px 0;"><tr>{cells}</tr></table>'


def _mono(text: str, *, role: str = "ink") -> str:
    color = _ACCENT if role == "accent" else _INK
    return (
        f'<span class="q-{role}" style="font-family:{_MONO};font-size:0.92em;color:{color};">'
        f"{text}</span>"
    )


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
    easy = "" if invite.is_add_business else f" {esc(_EASY)}"
    lead = f'{esc(before)}<strong class="q-ink">{esc(bold)}</strong>{esc(after)}{easy}'
    action = "Agregar negocio" if invite.is_add_business else "Crear mi cuenta"
    reply = _p(esc(_REPLY), size=13, role="muted") if can_reply else ""
    header = _lockup(base_url, icon=36, word=24)
    attitude = (
        "Desarrollado por "
        f'<a class="q-muted" href="{_ATTITUDE_SITE}" target="_blank" '
        f'style="color:{_MUTED};text-decoration:underline;">Attitude Factory</a>'
    )
    disclaimer = _p(esc(_DISCLAIMER), size=12, role="muted", margin="0 0 14px 0")
    sign_off = _p("<br>".join(esc(line) for line in _SIGN_OFF), size=15, margin="0 0 24px 0")
    fallback = (
        f'<a class="q-accent" href="{esc(link, quote=True)}" style="color:{_ACCENT};'
        f'word-break:break-all;text-decoration:underline;">{_mono(esc(link), role="accent")}</a>'
    )
    fine = _p(
        f"Este enlace es solo para ti ({_mono(esc(invite.email))}): sirve una sola vez y "
        f'hasta el <strong class="q-ink" style="color:{_INK};">{esc(expires)}</strong>. '
        f"Si el botón no te abre, copia esto en tu navegador:<br>{fallback}",
        size=13,
        role="muted",
        margin="0 0 12px 0",
    )
    ground_bg = (
        f"background-color:{_GROUND};"
        f"background-image:radial-gradient(circle at 16% 8%,{_GLOW},transparent 32%),"
        f"radial-gradient(circle at 84% 86%,{_GLOW_2},transparent 34%),"
        f"linear-gradient(140deg,#fcfcfd,{_GROUND} 52%,{_GROUND_EDGE});"
    )
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>{esc(subject_for(invite, signer))}</title>
<link rel="stylesheet" href="{_FONTS_URL}">
<style>{_DARK_CSS}</style>
</head>
<body class="q-ground" style="margin:0;padding:0;background:{_GROUND_EDGE};font-family:{_SANS};
 color:{_INK};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:{_GROUND};">
{esc(preheader)}&#8199;&#65279;&#847;&#8199;&#65279;&#847;&#8199;&#65279;&#847;
</div>
<table {_TABLE} class="q-ground" bgcolor="{_GROUND}" style="{ground_bg}">
<tr><td align="center" style="padding:40px 16px 32px 16px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
 style="max-width:560px;">
<tr><td class="q-panel q-panel-pad" style="background:{_PANEL};border:1px solid {_LINE};
 border-radius:{_RADIUS_CARD};padding:36px 36px 28px 36px;
 box-shadow:0 14px 36px rgba(15,23,42,0.08);">
<table {_TABLE} style="margin:0 0 28px 0;"><tr><td>{header}</td></tr></table>
{_badge("Invitación para ti")}
<h1 class="q-ink" style="margin:0 0 12px 0;font-family:{_SANS};font-size:24px;line-height:1.3;
 font-weight:600;letter-spacing:-0.012em;color:{_INK};">{esc(_greeting(invite))}</h1>
{_p(lead, size=16, margin="0 0 20px 0")}
{_note_block(invite.note, signer) if invite.note else ""}
{_button(link, action)}
{_scenes(base_url)}
{sign_off}
<div class="q-line" style="border-top:1px solid {_LINE};margin:0 0 16px 0;"></div>
{fine}
{reply}
</td></tr>
<tr><td style="padding:24px 8px 0 8px;">
{disclaimer}
{_lockup(base_url, icon=20, word=13)}
{_p(attitude, size=12, role="muted", margin="6px 0 0 0")}
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
    preheader = f"{_EASY} El enlace es solo para ti y vence el {expires}."
    return OutgoingMail(
        to=invite.email,
        subject=subject_for(invite, signer),
        text=_text(invite, link, signer, expires, can_reply),
        html=_html(invite, link, base_url, signer, expires, can_reply, preheader),
    )

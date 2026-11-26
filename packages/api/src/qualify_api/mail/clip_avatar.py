"""«Uno de tus avatares no se pudo crear» — the email of a failed avatar (m-25120319).

Pure assembly, no external reads: the outbox (`creative.clip_avatar_mail`) passes in the
business name, the Clip's link and the date the Clip stops waiting. The words follow
`docs/contrato-avatar-primer-crear.md` §1.6 (the «video listo» email it sketched),
adapted to the failure. **Every client-facing string here is pending ux-designer review
(`qualify-copy-es`)** — see `TEXTS` below, the one place they live.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from uuid import UUID
from zoneinfo import ZoneInfo

from qualify_api.mail import OutgoingMail

#: Provenance of every staged row (`clip_avatar_failure_mails.source_version`): bump it
#: when a word or the layout changes.
TEMPLATE_VERSION = "clip-avatar-failed-v1"

# UX-REVIEW (m-25120319): all of these, for ux-designer with `qualify-copy-es`.
SUBJECT = "{business}: uno de tus avatares no se pudo crear"
HEADING = "Uno de tus avatares no se pudo crear"
LEAD = "Uno de tus avatares no se pudo crear. Entra para intentarlo de nuevo o quitarlo."
WAIT = (
    "Tu video de {business} te espera en Por aprobar hasta el {deadline} "
    "(hora de tu negocio). Si quitas el avatar, armamos tu video con lo demás."
)
BUTTON = "Ver mi video"
FOOTER = "Recibes este aviso porque creaste un video con avatar para {business} en Qualify."
TEXTS = (SUBJECT, HEADING, LEAD, WAIT, BUTTON, FOOTER)


def video_url(base_url: str, clip_id: UUID) -> str:
    """The Clip in «Por aprobar»: the app's `/drafts/[draft_id]` page."""
    return f"{base_url.rstrip('/')}/drafts/{clip_id}"


def failure_mail(
    *,
    to: str,
    business: str,
    clip_id: UUID,
    wait_until: datetime,
    timezone: str,
    base_url: str,
    idempotency_key: str,
) -> OutgoingMail:
    zone = ZoneInfo(timezone or "UTC")
    deadline = wait_until.astimezone(zone).strftime("%d/%m/%Y a las %H:%M")
    url = video_url(base_url, clip_id)
    subject = SUBJECT.format(business=business)
    wait = WAIT.format(business=business, deadline=deadline)
    footer = FOOTER.format(business=business)
    href = escape(url, quote=True)
    logo = escape(base_url.rstrip("/") + "/qualify-icon-email.png", quote=True)
    html = (
        '<!doctype html><html lang="es"><head><meta name="viewport" '
        'content="width=device-width, initial-scale=1"><meta name="color-scheme" '
        'content="light dark"><style>'
        "@media(prefers-color-scheme:dark){body,.ground{background:#18191b!important}"
        ".panel{background:#212225!important;color:#edeef0!important}"
        ".panel p{color:#b0b4ba!important}.panel .mail-cta{color:#fff!important}}"
        '</style></head><body style="margin:0;background:#f0f0f3;'
        'font-family:IBM Plex Sans,Arial,sans-serif;color:#1c2024">'
        f'<div style="display:none;max-height:0;overflow:hidden">{escape(LEAD)}</div>'
        '<table class="ground" role="presentation" width="100%" '
        'style="padding:20px 12px"><tr><td align="center">'
        '<table class="panel" role="presentation" width="100%" '
        'style="max-width:560px;background:#fff;border-radius:20px;padding:24px">'
        f'<tr><td><img src="{logo}" width="36" alt="Qualify" '
        'style="vertical-align:middle;border-radius:8px"> <strong>Qualify</strong>'
        f'<h1 style="font-size:26px">{escape(HEADING)}</h1>'
        f"<p>{escape(LEAD)}</p><p>{escape(wait)}</p>"
        '<table role="presentation" width="100%"><tr>'
        '<td align="center" style="background:#008573;border-radius:12px">'
        f'<a class="mail-cta" href="{href}" style="display:block;padding:14px;'
        "min-height:44px;box-sizing:border-box;color:#fff;text-decoration:none;"
        f'font-weight:bold">{escape(BUTTON)}</a></td></tr></table>'
        f'<p style="color:#60646c;font-size:13px">{escape(footer)}</p>'
        "</td></tr></table></td></tr></table></body></html>"
    )
    text = "\n\n".join([LEAD, wait, f"{BUTTON}: {url}", footer])
    return OutgoingMail(
        to=to, subject=subject, html=html, text=text, idempotency_key=idempotency_key
    )


__all__ = [
    "BUTTON",
    "FOOTER",
    "HEADING",
    "LEAD",
    "SUBJECT",
    "TEMPLATE_VERSION",
    "TEXTS",
    "WAIT",
    "failure_mail",
    "video_url",
]

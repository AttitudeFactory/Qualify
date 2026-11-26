"""The email of a Clip whose avatars need the owner (m-25120319): one or more avatars
could not be made (`block_failed`), or one was made but the Clip passes 60 s with it
(`clip_too_long`).

Pure assembly, no external reads: the outbox (`creative.clip_avatar_mail`) passes in the
business name, the Clip's link and the date the Clip stops waiting. The words follow
`docs/contrato-avatar-primer-crear.md` §1.6. The `block_failed` words were reviewed by
ux-designer on 2026-11-26 (`qualify-copy-es`); the plural subject/heading and every
`clip_too_long` word are NEW and marked `UX-REVIEW` below, pending that review.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from html import escape
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from qualify_api.mail import OutgoingMail

#: Provenance of every staged row (`clip_avatar_failure_mails.source_version`): bump it
#: when a word or the layout changes.
TEMPLATE_VERSION = "clip-avatar-failed-v1"

#: The two kinds of email (`clip_avatar_failure_mails.kind`).
BLOCK_FAILED = "block_failed"
CLIP_TOO_LONG = "clip_too_long"

# -- `block_failed`: reviewed by ux-designer on 2026-11-26 (`qualify-copy-es`) ----------
SUBJECT = "{business}: uno de tus avatares no se pudo crear"
HEADING = "Uno de tus avatares no se pudo crear"
#: The inbox preview line (the hidden div), apart from the body.
PREHEADER = "Elige antes del {deadline} o tu video se descarta."
LEAD = (
    "Tu video de {business} está esperando en Por aprobar. "
    "Elige «Intentar de nuevo» o «Quitar avatar»."
)
#: «Si quitas el avatar…» holds: a removed block wakes the Clip's run, which assembles
#: it without the block and leaves it `generated` («Por aprobar»); nothing is
#: published before the owner approves it (`clip_avatar._remove_block_once`).
WAIT = (
    "Tienes hasta el {deadline} (hora de {business}). Si no eliges antes, el video se "
    "descarta y habría que crearlo de nuevo. Si quitas el avatar, armamos tu video sin "
    "él y tú lo apruebas antes de publicar."
)
BUTTON = "Revisar mi video"
FOOTER = "Recibes este aviso porque hay un video con avatar de {business} esperando en Qualify."
# UX-REVIEW (m-25120319, new): when one pass sees more than one avatar fail (one email
# per Clip and pass, Deivid 2026-11-26).
SUBJECT_MANY = "{business}: algunos de tus avatares no se pudieron crear"
HEADING_MANY = "Algunos de tus avatares no se pudieron crear"

# -- `clip_too_long`: UX-REVIEW (m-25120319, new; Deivid's idea «Tu video quedó muy largo:
# acórtalo para poder aprobarlo»). While the Clip waits its photos and videos cannot be
# edited (`drafting` has no edit edge), so the owner's only ways out are «Intentar de
# nuevo» with shorter words for the avatar, or «Quitar avatar» (contract §1.4).
LONG_SUBJECT = "{business}: tu video con avatar quedó muy largo"
LONG_HEADING = "Tu video quedó muy largo"
LONG_PREHEADER = "Acórtalo antes del {deadline} o tu video se descarta."
LONG_LEAD = (
    "Con tu avatar, el video de {business} pasa de 60 segundos y así no se puede armar. "
    "Acórtalo para poder aprobarlo."
)
LONG_WAIT = (
    "Toca «Intentar de nuevo» y escribe un texto más corto para tu avatar, o toca "
    "«Quitar avatar». Tienes hasta el {deadline} (hora de {business}). Si no eliges "
    "antes, el video se descarta y habría que crearlo de nuevo. Si quitas el avatar, "
    "armamos tu video sin él y tú lo apruebas antes de publicar."
)
TEXTS = (
    SUBJECT,
    HEADING,
    PREHEADER,
    LEAD,
    WAIT,
    BUTTON,
    FOOTER,
    SUBJECT_MANY,
    HEADING_MANY,
    LONG_SUBJECT,
    LONG_HEADING,
    LONG_PREHEADER,
    LONG_LEAD,
    LONG_WAIT,
)


@dataclass(frozen=True)
class Words:
    subject: str
    heading: str
    preheader: str
    lead: str
    wait: str


def words_for(kind: str, count: int = 1) -> Words:
    """The words of one email: by its kind, and for `block_failed` how many avatars."""
    if kind == CLIP_TOO_LONG:
        return Words(LONG_SUBJECT, LONG_HEADING, LONG_PREHEADER, LONG_LEAD, LONG_WAIT)
    if kind != BLOCK_FAILED:
        raise ValueError(kind)
    if count > 1:
        return Words(SUBJECT_MANY, HEADING_MANY, PREHEADER, LEAD, WAIT)
    return Words(SUBJECT, HEADING, PREHEADER, LEAD, WAIT)

#: Spanish names from a table — never `strftime` or the process locale.
_WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
_MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def business_zone(timezone: str | None) -> tzinfo:
    """The business's zone; UTC when it is empty or not a valid zone name."""
    try:
        return ZoneInfo(timezone) if timezone else UTC
    except (ZoneInfoNotFoundError, ValueError, OSError):
        # OSError: a folder name such as "America" (PermissionError / IsADirectoryError)
        return UTC


def spanish_deadline(moment: datetime, zone: tzinfo) -> str:
    """«jueves 12 de noviembre, 6:30 p. m.» (on the hour: «6 p. m.»), 12-hour clock."""
    local = moment.astimezone(zone)
    hour = local.hour % 12 or 12
    clock = f"{hour}" if local.minute == 0 else f"{hour}:{local.minute:02d}"
    half = "a. m." if local.hour < 12 else "p. m."
    return f"{_WEEKDAYS[local.weekday()]} {local.day} de {_MONTHS[local.month - 1]}, {clock} {half}"


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
    kind: str = BLOCK_FAILED,
    count: int = 1,
) -> OutgoingMail:
    words = words_for(kind, count)
    deadline = spanish_deadline(wait_until, business_zone(timezone))
    url = video_url(base_url, clip_id)
    subject = words.subject.format(business=business)
    heading = words.heading
    preheader = words.preheader.format(deadline=deadline)
    lead = words.lead.format(business=business)
    wait = words.wait.format(business=business, deadline=deadline)
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
        f'<div style="display:none;max-height:0;overflow:hidden">{escape(preheader)}</div>'
        '<table class="ground" role="presentation" width="100%" '
        'style="padding:20px 12px"><tr><td align="center">'
        '<table class="panel" role="presentation" width="100%" '
        'style="max-width:560px;background:#fff;border-radius:20px;padding:24px">'
        f'<tr><td><img src="{logo}" width="36" alt="Qualify" '
        'style="vertical-align:middle;border-radius:8px"> <strong>Qualify</strong>'
        f'<h1 style="font-size:26px">{escape(heading)}</h1>'
        f"<p>{escape(lead)}</p><p>{escape(wait)}</p>"
        '<table role="presentation" width="100%"><tr>'
        '<td align="center" style="background:#008573;border-radius:12px">'
        f'<a class="mail-cta" href="{href}" style="display:block;padding:14px;'
        "min-height:44px;box-sizing:border-box;color:#fff;text-decoration:none;"
        f'font-weight:bold">{escape(BUTTON)}</a></td></tr></table>'
        f'<p style="color:#60646c;font-size:13px">{escape(footer)}</p>'
        "</td></tr></table></td></tr></table></body></html>"
    )
    text = "\n\n".join([heading, lead, wait, f"{BUTTON}: {url}", footer])
    return OutgoingMail(
        to=to, subject=subject, html=html, text=text, idempotency_key=idempotency_key
    )


__all__ = [
    "BLOCK_FAILED",
    "BUTTON",
    "CLIP_TOO_LONG",
    "FOOTER",
    "HEADING",
    "LEAD",
    "PREHEADER",
    "SUBJECT",
    "TEMPLATE_VERSION",
    "TEXTS",
    "WAIT",
    "Words",
    "business_zone",
    "failure_mail",
    "spanish_deadline",
    "video_url",
    "words_for",
]

"""The email of a Clip whose avatars need the owner (m-25120319): one or more avatars
could not be made (`block_failed`), or one was made but the Clip passes 60 s with it
(`clip_too_long`).

Pure assembly, no external reads: the outbox (`creative.clip_avatar_mail`) passes in the
business name, the Clip's link and the date the Clip stops waiting. The words follow
`docs/contrato-avatar-primer-crear.md` §1.6. Every word here was reviewed by
ux-designer on 2026-11-26 (`qualify-copy-es`), the plural and `clip_too_long` ones in a
second round the same day.
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
# -- two or more avatars seen failed in one pass (one email per Clip and pass, Deivid
# 2026-11-26). The owner chooses PER avatar: «Intentar de nuevo» and «Quitar avatar» each
# act on one block (`ClipAvatarService.retry_block` / `remove_block` take its `block_id`).
SUBJECT_MANY = "{business}: algunos de tus avatares no se pudieron crear"
HEADING_MANY = "Algunos de tus avatares no se pudieron crear"
LEAD_MANY = (
    "Tu video de {business} está esperando en Por aprobar. "
    "Con cada avatar, elige «Intentar de nuevo» o «Quitar avatar»."
)
WAIT_MANY = (
    "Tienes hasta el {deadline} (hora de {business}). Si no eliges antes, el video se "
    "descarta y habría que crearlo de nuevo. Si quitas un avatar, armamos tu video sin "
    "ese avatar y tú lo apruebas antes de publicar."
)

# -- `clip_too_long` (Deivid's idea, 2026-11-26). While the Clip waits its photos and
# videos cannot be edited (`drafting` has no edit edge): the owner can only change what
# the avatar says («Intentar de nuevo» with shorter words) or take it out (contract §1.4).
# How many seconds it passes by is not kept anywhere the sender reads, so it is not said.
LONG_SUBJECT = "{business}: tu video con avatar quedó muy largo"
LONG_HEADING = "Tu video quedó muy largo"
LONG_PREHEADER = "Acorta lo que dice tu avatar antes del {deadline}, o tu video se descarta."
LONG_LEAD = (
    "Con tu avatar, el video de {business} dura más de 60 segundos y así no se puede "
    "armar. Para aprobarlo, tu avatar tiene que decir menos."
)
LONG_WAIT = (
    "Entra a tu video con el botón de abajo. Ahí toca «Intentar de nuevo» y escribe un "
    "texto más corto para tu avatar, o toca «Quitar avatar». Tienes hasta el {deadline} "
    "(hora de {business}). Si no eliges antes, el video se descarta y habría que crearlo "
    "de nuevo. Si quitas el avatar, armamos tu video sin él y tú lo apruebas antes de "
    "publicar."
)

# -- m-25128784 PR 2 (ADR 50 §12.1): a character's scene of a Clip that could not be made
# sends this same email, in the scene's words. Its own template version: the avatar's
# words above are unchanged. A scene is never refused as too long (5 to 10 s, checked at
# «Crear»), so only `block_failed`. The owner chooses per scene: «Intentar de nuevo» and
# «Quitar escena» (the screen of m-25112921 offers them).
SCENE_TEMPLATE_VERSION = "clip-scene-failed-v1"
SCENE_SUBJECT = "{business}: una escena con tu personaje no se pudo crear"
SCENE_HEADING = "Una escena con tu personaje no se pudo crear"
SCENE_LEAD = (
    "Tu video de {business} está esperando en Por aprobar. "
    "Elige «Intentar de nuevo» o «Quitar escena»."
)
SCENE_WAIT = (
    "Tienes hasta el {deadline} (hora de {business}). Si no eliges antes, el video se "
    "descarta y habría que crearlo de nuevo. Si quitas la escena, en esos segundos se ven "
    "tus propias fotos y videos, y tú apruebas el video antes de publicar."
)
SCENE_SUBJECT_MANY = "{business}: algunas escenas con tu personaje no se pudieron crear"
SCENE_HEADING_MANY = "Algunas escenas con tu personaje no se pudieron crear"
SCENE_LEAD_MANY = (
    "Tu video de {business} está esperando en Por aprobar. "
    "Con cada escena, elige «Intentar de nuevo» o «Quitar escena»."
)
SCENE_WAIT_MANY = (
    "Tienes hasta el {deadline} (hora de {business}). Si no eliges antes, el video se "
    "descarta y habría que crearlo de nuevo. Si quitas una escena, en esos segundos se ven "
    "tus propias fotos y videos, y tú apruebas el video antes de publicar."
)
SCENE_FOOTER = (
    "Recibes este aviso porque hay un video con tu personaje de {business} esperando en Qualify."
)
TEXTS = (
    SCENE_SUBJECT,
    SCENE_HEADING,
    SCENE_LEAD,
    SCENE_WAIT,
    SCENE_SUBJECT_MANY,
    SCENE_HEADING_MANY,
    SCENE_LEAD_MANY,
    SCENE_WAIT_MANY,
    SCENE_FOOTER,
    SUBJECT,
    HEADING,
    PREHEADER,
    LEAD,
    WAIT,
    BUTTON,
    FOOTER,
    SUBJECT_MANY,
    HEADING_MANY,
    LEAD_MANY,
    WAIT_MANY,
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


def words_for(kind: str, count: int = 1, *, scene: bool = False) -> Words:
    """The words of one email: by its kind, and for `block_failed` how many avatars (or,
    with `scene`, how many character scenes — m-25128784)."""
    if scene:
        if kind != BLOCK_FAILED:
            raise ValueError(kind)
        if count > 1:
            return Words(
                SCENE_SUBJECT_MANY, SCENE_HEADING_MANY, PREHEADER, SCENE_LEAD_MANY, SCENE_WAIT_MANY
            )
        return Words(SCENE_SUBJECT, SCENE_HEADING, PREHEADER, SCENE_LEAD, SCENE_WAIT)
    if kind == CLIP_TOO_LONG:
        return Words(LONG_SUBJECT, LONG_HEADING, LONG_PREHEADER, LONG_LEAD, LONG_WAIT)
    if kind != BLOCK_FAILED:
        raise ValueError(kind)
    if count > 1:
        return Words(SUBJECT_MANY, HEADING_MANY, PREHEADER, LEAD_MANY, WAIT_MANY)
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
    scene: bool = False,
) -> OutgoingMail:
    words = words_for(kind, count, scene=scene)
    deadline = spanish_deadline(wait_until, business_zone(timezone))
    url = video_url(base_url, clip_id)
    subject = words.subject.format(business=business)
    heading = words.heading
    preheader = words.preheader.format(deadline=deadline)
    lead = words.lead.format(business=business)
    wait = words.wait.format(business=business, deadline=deadline)
    footer = (SCENE_FOOTER if scene else FOOTER).format(business=business)
    return render_mail(
        to=to,
        subject=subject,
        heading=heading,
        preheader=preheader,
        paragraphs=(lead, wait),
        footer=footer,
        url=url,
        base_url=base_url,
        idempotency_key=idempotency_key,
    )


def render_mail(
    *,
    to: str,
    subject: str,
    heading: str,
    preheader: str,
    paragraphs: tuple[str, ...],
    footer: str,
    url: str,
    base_url: str,
    idempotency_key: str,
) -> OutgoingMail:
    """The layout every Clip failure email shares (m-25142979 reuses it for an AI part):
    the logo, the heading, the paragraphs, «Revisar mi video» and the footer, HTML and
    plain text. Pure."""
    href = escape(url, quote=True)
    logo = escape(base_url.rstrip("/") + "/qualify-icon-email.png", quote=True)
    body = "".join(f"<p>{escape(p)}</p>" for p in paragraphs)
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
        f"{body}"
        '<table role="presentation" width="100%"><tr>'
        '<td align="center" style="background:#008573;border-radius:12px">'
        f'<a class="mail-cta" href="{href}" style="display:block;padding:14px;'
        "min-height:44px;box-sizing:border-box;color:#fff;text-decoration:none;"
        f'font-weight:bold">{escape(BUTTON)}</a></td></tr></table>'
        f'<p style="color:#60646c;font-size:13px">{escape(footer)}</p>'
        "</td></tr></table></td></tr></table></body></html>"
    )
    text = "\n\n".join([heading, *paragraphs, f"{BUTTON}: {url}", footer])
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
    "SCENE_TEMPLATE_VERSION",
    "SUBJECT",
    "TEMPLATE_VERSION",
    "TEXTS",
    "WAIT",
    "Words",
    "business_zone",
    "failure_mail",
    "render_mail",
    "spanish_deadline",
    "video_url",
    "words_for",
]

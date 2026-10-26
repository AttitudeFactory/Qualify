"""The prior UX-approved morning summary, HTML and plain text (m-24852235)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from html import escape
from urllib.parse import urlencode
from uuid import UUID
from zoneinfo import ZoneInfo

from qualify_api.mail import OutgoingMail

VERSION = "final-morning-v1"
WEEKDAYS = "lunes martes miércoles jueves viernes sábado domingo".split()
CALM = (
    "Nada sale sin tu confirmación. Si no confirmas un video, no se publica y lo verás en Inicio."
)
FAILED = "No pudimos preparar el video final. Ábrelo para intentarlo de nuevo; no usa otro video."
UNSUBSCRIBED = (
    "Listo. Ya no te enviaremos el correo de tus videos listos. "
    "Los verás igual en Inicio y en Tu semana."
)


@dataclass(frozen=True)
class FinalVideo:
    piece_id: UUID
    title: str
    failed: bool = False
    scheduled_at: datetime | None = None
    thumbnail: str = ""
    revision: int = 1
    source_job_id: str = ""


def review_url(base_url: str, piece_id: UUID | None = None) -> str:
    params = {"revisar": "videos"}
    if piece_id is not None:
        params["pieza"] = str(piece_id)
    return base_url.rstrip("/") + "/planner?" + urlencode(params)


def time_label(at: datetime) -> str:
    return f"{at.hour % 12 or 12}:{at.minute:02d} {'a. m.' if at.hour < 12 else 'p. m.'}"


def schedule_label(video: FinalVideo, day: date, zone: ZoneInfo) -> str:
    if video.scheduled_at is None:
        return "Todavía sin fecha"
    at = video.scheduled_at.astimezone(zone)
    prefix = "Sale hoy" if at.date() == day else f"Sale el {WEEKDAYS[at.weekday()]} {at.day}"
    return f"{prefix} a las {time_label(at)} · Instagram, reel"


def build_summary(
    *,
    to: str,
    name: str,
    business: str,
    videos: tuple[FinalVideo, ...],
    day: date,
    timezone: str,
    base_url: str,
    preference_url: str,
    idempotency_key: str,
) -> OutgoingMail:
    if not videos:
        raise ValueError("a summary needs new videos or failures")
    zone = ZoneInfo(timezone)
    ready = [v for v in videos if not v.failed]
    today = [v for v in ready if v.scheduled_at and v.scheduled_at.astimezone(zone).date() == day]
    n = len(ready) if ready else len(videos)
    if today:
        count = len(today)
        subject = (
            f"{business}: 1 video sale hoy y espera tu confirmación"
            if count == 1
            else f"{business}: {count} videos salen hoy y esperan tu confirmación"
        )
    elif ready:
        subject = (
            f"{business}: tu video está listo para revisar"
            if n == 1
            else f"{business}: tus {n} videos están listos para revisar"
        )
    else:
        subject = f"{business}: no pudimos preparar {n} {'video' if n == 1 else 'videos'}"
    if ready:
        preheader = (
            "Míralo y confírmalo para que salga. Sin tu confirmación, no se publica."
            if n == 1
            else "Míralos y confírmalos para que salgan. Sin tu confirmación, no se publican."
        )
        title = "Tu video está listo" if n == 1 else "Tus videos están listos"
        introduction = (
            f"Anoche preparamos el video final de {n} "
            f"{'publicación' if n == 1 else 'publicaciones'} de {business}. "
            + (
                "Míralo y confírmalo para que salga."
                if n == 1
                else "Míralos y confírmalos para que salgan."
            )
        )
    else:
        preheader = (
            "Ábrelo para intentarlo de nuevo; no usa otro video."
            if n == 1
            else "Ábrelos para intentarlo de nuevo; no usan otro video."
        )
        title = "No pudimos preparar tu video" if n == 1 else f"No pudimos preparar {n} videos"
        introduction = (
            f"Anoche no pudimos preparar el video final de {n} "
            f"{'publicación' if n == 1 else 'publicaciones'} de {business}."
        )
    greeting = f"Hola, {name}." if name.strip() else "Hola."
    ordered = sorted(
        videos,
        key=lambda v: (
            not (not v.failed and v.scheduled_at and v.scheduled_at.astimezone(zone).date() == day),
            v.scheduled_at.timestamp() if v.scheduled_at else float("inf"),
            str(v.piece_id),
        ),
    )
    lines = [title, f"{greeting} {introduction}"]
    rows = ["<tbody>"]
    in_today_group = bool(today)
    if today:
        lines.append("Sale hoy")
        rows.append('<tr><td colspan="2"><h2 style="font-size:18px">Sale hoy</h2></td></tr>')
    for video in ordered[:4]:
        if in_today_group and not (
            not video.failed
            and video.scheduled_at
            and video.scheduled_at.astimezone(zone).date() == day
        ):
            rows.append(
                '</tbody><tbody><tr><td colspan="2" style="padding:12px 0">'
                '<hr style="border:0;border-top:1px solid #e0e1e6"></td></tr>'
            )
            in_today_group = False
        url = review_url(base_url, video.piece_id)
        detail = FAILED if video.failed else schedule_label(video, day, zone)
        action = "Abrir ›" if video.failed else "Ver video ›"
        thumb = video.thumbnail or base_url.rstrip("/") + "/qualify-icon-email.png"
        rows.append(
            '<tr><td style="padding:12px 12px 12px 0;vertical-align:top;width:80px">'
            f'<a href="{escape(url, quote=True)}"><img src="{escape(thumb, quote=True)}" '
            f'alt="Video: {escape(video.title, quote=True)}" width="80" '
            'style="display:block;border-radius:8px;max-width:80px"></a></td>'
            '<td style="padding:12px 0;border-bottom:1px solid #e0e1e6">'
            f'<a href="{escape(url, quote=True)}" style="display:block;min-height:44px;'
            'color:#1c2024;text-decoration:none">'
            f"<strong>{escape(video.title)}</strong><br>"
            f'<span style="color:#60646c">{escape(detail)}</span><br>'
            f'<span class="mail-action" style="color:#008573">{action}</span></a></td></tr>'
        )
        lines.append(f"{video.title}\n{detail}\n{action} {url}")
    rows.append("</tbody>")
    more = len(videos) - 4
    more_text = f"y {more} {'más' if more == 1 else 'más'} en Tu semana" if more > 0 else ""
    if more_text:
        lines.append(more_text)
    footer = (
        f"Recibes este correo porque tienes videos por revisar en Qualify para {business}. "
        "Te escribimos como máximo una vez al día y solo cuando hay algo listo."
    )
    target = review_url(base_url, ordered[0].piece_id if not ready else None)
    lines.extend(
        [
            "Revisar mis videos: " + target,
            CALM,
            footer,
            "¿Prefieres no recibirlo? Deja de recibir estos correos: " + preference_url,
            "También puedes cambiarlo en Configuración.",
        ]
    )
    content = f'''<!doctype html><html lang="es"><head><meta name="viewport"
        content="width=device-width, initial-scale=1"><meta name="color-scheme" content="light
        dark">
        <style>@media(prefers-color-scheme:dark){{body,.ground{{background:#18191b!important}}
        .panel{{background:#212225!important;color:#edeef0!important}}
        .panel a,.panel strong{{color:#edeef0!important}}
        .panel p,.panel span{{color:#b0b4ba!important}}
        .panel .mail-action{{color:#0bd8b6!important}}
        .panel .mail-cta{{color:#fff!important}}}}</style></head>
        <body style="margin:0;background:#f0f0f3;
        font-family:'IBM Plex Sans',Arial,sans-serif;color:#1c2024">
        <div style="display:none;max-height:0;overflow:hidden">{escape(preheader)}</div>
        <table class="ground" role="presentation" width="100%" style="padding:20px
        12px"><tr><td align="center">
        <table class="panel" role="presentation" width="100%"
        style="max-width:560px;background:#fff;border-radius:20px;padding:24px">
        <tr><td><img src="{escape(base_url.rstrip("/"))}/qualify-icon-email.png" width="36"
        alt="Qualify"
        style="vertical-align:middle;border-radius:8px"> <strong>Qualify</strong>
        <h1 style="font-size:26px">{escape(title)}</h1><p>{escape(greeting)}
        {escape(introduction)}</p>
        <table role="presentation" width="100%">{"".join(rows)}</table>
        <p>{escape(more_text)}</p><table role="presentation" width="100%"><tr>
        <td align="center" style="background:#008573;border-radius:12px">
        <a class="mail-cta" href="{escape(target, quote=True)}"
        style="display:block;padding:14px;color:#fff;
        text-decoration:none;font-weight:bold">Revisar mis videos</a>
        </td></tr></table><p style="color:#60646c">{CALM}</p>
        <hr style="border:0;border-top:1px solid #e0e1e6"><p
        style="color:#60646c;font-size:13px">{escape(footer)}</p>
        <p style="color:#60646c;font-size:13px">¿Prefieres no recibirlo?
        <a href="{escape(preference_url, quote=True)}" style="color:#008573">Deja de recibir
        estos correos</a>.
        También puedes cambiarlo en
        Configuración.</p></td></tr></table></td></tr></table></body></html>'''
    return OutgoingMail(
        to,
        subject,
        content,
        "\n\n".join(lines),
        sender_name="Qualify",
        headers={
            "List-Unsubscribe": f"<{preference_url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
        idempotency_key=idempotency_key,
    )

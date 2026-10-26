"""Plain Spanish warning email; pure assembly, no external reads (m-24842840)."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from html import escape
from uuid import UUID
from zoneinfo import ZoneInfo

from qualify_api.mail import OutgoingMail


class WarningStage(StrEnum):
    WINDOW_15D = "window_15d"
    LAST_DAY = "last_day"


@dataclass(frozen=True)
class ExpiringPiece:
    draft_id: UUID
    title: str
    deadline: datetime
    thumbnail_url: str | None = None


def warning_mail(
    recipient: str,
    brand_id: UUID,
    brand_name: str,
    pieces: list[ExpiringPiece],
    *,
    pieces_url: str,
    timezone: str,
    stage: WarningStage = WarningStage.WINDOW_15D,
) -> OutgoingMail:
    zone = ZoneInfo(timezone)
    heading = f"Descarga los archivos de tus piezas de {brand_name} antes de que se borren"
    intro = (
        "Los archivos de esta pieza se borrarán pronto:"
        if len(pieces) == 1
        else f"Los archivos de estas {len(pieces)} piezas se borrarán pronto:"
    )
    if stage is WarningStage.LAST_DAY:
        heading = f"Último día: descarga los archivos de tus piezas de {brand_name}"
        intro = (
            "Los archivos de esta pieza se borrarán en las próximas 24 horas:"
            if len(pieces) == 1
            else f"Los archivos de estas {len(pieces)} piezas se borrarán en las próximas 24 horas:"
        )
    lines = []
    cards = []
    app_url = pieces_url.rstrip("/").removesuffix("/drafts")
    logo_url = escape(app_url + "/qualify-icon-email.png", quote=True)
    for piece in pieces:
        piece_url = f"{pieces_url.rstrip('/')}/{piece.draft_id}"
        href = escape(piece_url, quote=True)
        date = piece.deadline.astimezone(zone).strftime("%d/%m/%Y")
        if stage is WarningStage.LAST_DAY:
            date = (
                piece.deadline.astimezone(zone).strftime("%d/%m/%Y a las %H:%M")
                + " (hora de tu negocio)"
            )
        title = piece.title or "Pieza sin título"
        lines.append(
            f"- {title}: sus archivos se borran el {date}.\n  Ver pieza y descargar: {piece_url}"
        )
        thumbnail = (
            escape(piece.thumbnail_url, quote=True)
            if piece.thumbnail_url and piece.thumbnail_url.startswith("https://")
            else logo_url
        )
        cards.append(
            '<tr><td style="padding:12px 12px 12px 0;vertical-align:top;width:80px">'
            f'<a href="{href}"><img src="{thumbnail}" alt="" width="80" '
            'style="display:block;border-radius:8px;max-width:80px"></a></td>'
            '<td style="padding:12px 0;border-bottom:1px solid #e0e1e6">'
            f'<a href="{href}" style="color:#1c2024;text-decoration:none">'
            f'{escape(title)}</a><p style="color:#60646c;margin:8px 0">'
            f"Sus archivos se borran el {date}.</p>"
            f'<a class="mail-action" href="{href}" style="display:inline-block;'
            'min-height:44px;color:#008573;font-weight:bold">Ver pieza y descargar</a></td></tr>'
        )
    action = (
        "Abre cada pieza y descarga los archivos que quieras conservar. "
        "Si te pedimos iniciar sesión, entra con tu cuenta de Qualify."
    )
    identity = "|".join(
        f"{p.draft_id}:{p.deadline.isoformat()}"
        for p in sorted(pieces, key=lambda p: str(p.draft_id))
    )
    key = sha256(f"{brand_id}|{recipient.casefold()}|{stage.value}|{identity}".encode()).hexdigest()
    return OutgoingMail(
        to=recipient,
        subject=heading,
        text="\n".join([heading, intro, *lines, action, pieces_url]),
        html=(
            '<!doctype html><html lang="es"><head><meta name="viewport" '
            'content="width=device-width, initial-scale=1"><meta name="color-scheme" '
            'content="light dark"><style>'
            "@media(prefers-color-scheme:dark){body,.ground{background:#18191b!important}"
            ".panel{background:#212225!important;color:#edeef0!important}"
            ".panel a{color:#edeef0!important}.panel p{color:#b0b4ba!important}"
            ".panel .mail-action{color:#0bd8b6!important}"
            ".panel .mail-cta{color:#fff!important}}"
            '</style></head><body style="margin:0;background:#f0f0f3;'
            'font-family:IBM Plex Sans,Arial,sans-serif;color:#1c2024">'
            f'<div style="display:none;max-height:0;overflow:hidden">{escape(intro)}</div>'
            '<table class="ground" role="presentation" width="100%" '
            'style="padding:20px 12px"><tr><td align="center">'
            '<table class="panel" role="presentation" width="100%" '
            'style="max-width:560px;background:#fff;border-radius:20px;padding:24px">'
            f'<tr><td><img src="{logo_url}" width="36" alt="Qualify" '
            'style="vertical-align:middle;border-radius:8px"> <strong>Qualify</strong>'
            f'<h1 style="font-size:26px">{escape(heading)}</h1><p>{escape(intro)}</p>'
            f'<table role="presentation" width="100%">{"".join(cards)}</table>'
            f'<p>{action}</p><table role="presentation" width="100%"><tr>'
            '<td align="center" style="background:#008573;border-radius:12px">'
            f'<a class="mail-cta" href="{escape(pieces_url, quote=True)}" '
            'style="display:block;padding:14px;color:#fff;text-decoration:none;'
            'font-weight:bold">Ir a Piezas</a></td></tr></table>'
            '<p style="color:#60646c;font-size:13px">Recibes este aviso porque hay archivos '
            f"de {escape(brand_name)} que pronto se borrarán de Qualify.</p>"
            "</td></tr></table></td></tr></table></body></html>"
        ),
        idempotency_key=f"piece-warning/{key}",
    )

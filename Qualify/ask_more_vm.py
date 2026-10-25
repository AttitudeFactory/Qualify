"""Pure view models for «Pedir más a Qualify» (m-24852129): the zero state of Crear, the
button, the two confirmations and the balance with the 90-day extras. Never money.

Copy from the ticket (founder, 2026-10-24, decisions D13 and D16):

- in 0: «Ya usaste tus 4 videos de este mes. ¿Necesitas más? Pídelos y te enviamos el
  enlace de pago.» — the number is the business's real quota (plan + live extras);
- after the request: «Listo. Te escribimos por WhatsApp con el enlace de pago.» or, with
  no WhatsApp, «Listo. Te escribimos a tu correo con el enlace de pago.»;
- with extras: «Te quedan 5 de 6 videos este mes (2 extra, vencen el 22 de enero).»
"""

from __future__ import annotations

ASK_MORE_BUTTON = "Pedir más a Qualify"
ASK_MORE_SENT_BUTTON = "Pedido enviado"
ASK_MORE_BY_WHATSAPP = "Listo. Te escribimos por WhatsApp con el enlace de pago."
ASK_MORE_BY_EMAIL = "Listo. Te escribimos a tu correo con el enlace de pago."
ASK_MORE_FAILED = "No pudimos enviar tu pedido. Vuelve a intentarlo en un rato."

CREATIONS = "creations"
VIDEOS = "videos"
PREVIEWS = "previews"

# (singular, plural, the pronoun that asks for them: «Pídelos» / «Pídelas»)
_NOUNS: dict[str, tuple[str, str, str]] = {
    CREATIONS: ("creación", "creaciones", "Pídelas"),
    VIDEOS: ("video", "videos", "Pídelos"),
    PREVIEWS: ("vista previa", "vistas previas", "Pídelas"),
}


def ask_more_sent_text(by_whatsapp: bool) -> str:
    """What the owner reads once the request is saved (D13)."""
    return ASK_MORE_BY_WHATSAPP if by_whatsapp else ASK_MORE_BY_EMAIL


def exhausted_text(kind: str, quota: int) -> str:
    """The zero state of one counter: «Ya usaste tus 4 videos de este mes. ¿Necesitas
    más? Pídelos y te enviamos el enlace de pago.» ("" for an unknown kind)."""
    if kind not in _NOUNS:
        return ""
    one, many, ask = _NOUNS[kind]
    used = f"tu {one}" if quota == 1 else f"tus {quota} {many}"
    return f"Ya usaste {used} de este mes. ¿Necesitas más? {ask} y te enviamos el enlace de pago."


def exhausted_kind(
    *,
    weight: int,
    videos: int,
    creations_left: int,
    videos_left: int,
    video_quota: int,
    previews_left: int,
    preview_quota: int,
) -> str:
    """Which counter at 0 keeps THIS piece from being created ("" = none is at 0): a
    video (`videos` > 0: its vistas previas now, its videos when approved) needs both
    counters; an image only creations. A counter with some left is never «at 0» — a
    shortfall of a few keeps its own message."""
    if videos > 0 and video_quota > 0 and videos_left <= 0:
        return VIDEOS
    if videos > 0 and preview_quota > 0 and previews_left <= 0:
        return PREVIEWS
    if weight > 0 and creations_left <= 0:
        return CREATIONS
    return ""


def _extra(extra: int, expires: str) -> str:
    if extra <= 0:
        return ""
    verb = "vence" if extra == 1 else "vencen"
    return f" ({extra} extra, {verb} el {expires})" if expires else f" ({extra} extra)"


def _sentence(left: int, quota: int, noun: str, extra: int, expires: str) -> str:
    verb = "Te queda" if left == 1 else "Te quedan"
    return f"{verb} {left} de {quota} {noun} este mes{_extra(extra, expires)}."


def balance_with_extras(
    *,
    left: int,
    quota: int,
    videos_left: int,
    video_quota: int,
    previews_left: int,
    preview_quota: int,
    extra_left: int,
    extra_expires: str,
    extra_videos_left: int,
    extra_videos_expires: str,
    extra_previews_left: int,
    extra_previews_expires: str,
    previews_note: str = "",
) -> str:
    """D16: the total and the extras apart, one sentence per counter that has extras
    — «Te quedan 5 de 6 videos este mes (2 extra, vencen el 22 de enero).» — the date in
    the business's zone, the month in words. `previews_note` is the few-left sentence
    the vistas previas get without extras."""
    parts = [_sentence(left, quota, "creaciones", extra_left, extra_expires)]
    if video_quota > 0:
        parts.append(
            _sentence(videos_left, video_quota, "videos", extra_videos_left, extra_videos_expires)
        )
    if preview_quota > 0 and extra_previews_left > 0:
        parts.append(
            _sentence(
                previews_left,
                preview_quota,
                "vistas previas",
                extra_previews_left,
                extra_previews_expires,
            )
        )
    elif previews_note:
        parts.append(previews_note)
    return " ".join(parts)


__all__ = [
    "ASK_MORE_BUTTON",
    "ASK_MORE_BY_EMAIL",
    "ASK_MORE_BY_WHATSAPP",
    "ASK_MORE_FAILED",
    "ASK_MORE_SENT_BUTTON",
    "CREATIONS",
    "PREVIEWS",
    "VIDEOS",
    "ask_more_sent_text",
    "balance_with_extras",
    "exhausted_kind",
    "exhausted_text",
]

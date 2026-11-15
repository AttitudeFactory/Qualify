"""The one reply box both chats draw (m-25027374, BU-A7): what it may draw, per channel.

Pure data, no Reflex. The view (`reply_box.py` and each page's composer region) only asks
«¿se dibuja?» to the `can_*` flags here; the flags come from the channel's descriptor
(`qualify_api.inbox.channels.ChannelCapabilities`), so a channel never shows a tool it
cannot send. What is not allowed is not drawn — never drawn disabled (the `orbit_menu`
rule, `docs/design-system.md` §5.9).

Two layers, kept apart on purpose:

- `ReplyBoxVM` is the descriptor read as the box needs it (`reply_box_vm`). A test holds
  every flag against the descriptor (ticket criterion «los `can_*` coinciden con el
  descriptor»).
- `SEND_DOORS` says which of those things each screen can actually SEND today through
  its own provider. The descriptor says what the channel's API allows; a row is drawn
  only when both agree. Instagram's API takes an image, so the descriptor allows
  «Tus productos», but Qualify has no door yet that sends a catalog photo to an
  Instagram chat — drawing it would be a button that leads nowhere (N8). Each such gap
  is listed by `missing_doors()` so the next story can close it.

The «+» rows (`plus_rows`) are the same catalogue on every channel, in one order; the
channel only removes rows. With fewer than two rows (Instagram today) there is no «+».
Strings here are client-facing Spanish (`qualify-copy-es`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from qualify_api.inbox.channels import (
    CHANNEL_INSTAGRAM_DM,
    CHANNEL_WHATSAPP,
    ChannelCapabilities,
    capabilities_for,
)

# ======================================================================================
# Texts (the founder's names: D5 of docs/ux-chats-unificados.md, decision vi)
# ======================================================================================

SEND_LABEL: Final = "Enviar"
PLUS_LABEL: Final = "Enviar algo al cliente"
PHOTO_LABEL: Final = "Foto o video"
BUTTONS_LABEL: Final = "Botones"
SAVED_LABEL: Final = "Mensajes guardados"
FILE_LABEL: Final = "Archivo"
VOICE_LABEL: Final = "Nota de voz"
HEART_LABEL: Final = "Enviar un corazón"
SUGGEST_LABEL: Final = "Sugerir respuesta"
FIELD_LABEL: Final = "Tu respuesta"
#: U4 (UX review, 2026-11-15): short enough for one line at 360 px.
FIELD_PLACEHOLDER: Final = "Escribe aquí…"
#: U2: Instagram's closed window — no box; this line where the box was.
REPLY_LATER_LINE: Final = "Cuando vuelva a escribir, podrás responderle aquí."
#: U3: one wording for a send that did not go, on both channels.
SEND_FAILED_RETRY: Final = "El mensaje no salió. Vuelve a tocar «Enviar» para mandarlo."
#: Decision (vi), 2026-11-14: the menu bot is «Tu menú de bienvenida»; the note under
#: WhatsApp's box stops saying «respuesta automática». NEW TEXT awaiting the founder.
MENU_PAUSE_NOTE: Final = "Al responder, tu menú de bienvenida se pausa en esta conversación."

# ======================================================================================
# The descriptor, read as the box needs it
# ======================================================================================


@dataclass(frozen=True)
class ReplyBoxVM:
    """What one channel's reply box may draw (`docs/ux-chats-unificados.md` §5)."""

    channel: str
    can_photo: bool
    can_file: bool
    can_voice: bool
    can_heart: bool
    can_stickers: bool
    can_buttons: bool
    max_buttons: int
    can_saved: bool
    can_suggest: bool
    can_close: bool
    can_assign: bool
    has_menu_handoff: bool
    has_payments: bool
    can_send_approved: bool


def reply_box_vm(caps: ChannelCapabilities) -> ReplyBoxVM:
    return ReplyBoxVM(
        channel=caps.channel,
        can_photo=bool({"image", "video"} & caps.attachments),
        can_file="document" in caps.attachments,
        can_voice="audio" in caps.attachments,
        can_heart=caps.stickers == "heart_only",
        can_stickers=caps.stickers == "native",
        can_buttons=caps.max_buttons > 0,
        max_buttons=caps.max_buttons,
        can_saved=caps.saved_messages,
        can_suggest=caps.suggest_reply,
        can_close=caps.close_reopen,
        can_assign=caps.assign,
        has_menu_handoff=caps.menu_handoff,
        has_payments=caps.payments,
        can_send_approved=caps.after_window == "approved_template",
    )


def box_for(channel: str) -> ReplyBoxVM:
    """The box of a channel the inbox lists (`UnknownChannel` otherwise)."""
    return reply_box_vm(capabilities_for(channel))


# ======================================================================================
# What each screen can send today (beside what the API allows)
# ======================================================================================

TOOL_PHOTO: Final = "photo"
TOOL_BUTTONS: Final = "buttons"
TOOL_SAVED: Final = "saved"
TOOL_FILE: Final = "file"
TOOL_VOICE: Final = "voice"
TOOL_HEART: Final = "heart"
TOOL_SUGGEST: Final = "suggest"

#: The «+» rows, one catalogue for every channel and in this order (today's WhatsApp
#: order: m-24955785). Keys are WhatsApp's picker sources, so WhatsApp's `open_pick`
#: takes them as they are. (key, icon, text).
PLUS_PRODUCTS: Final = "products"
PLUS_OFFER: Final = "offer"
PLUS_MENU: Final = "menu"
PLUS_PAYMENTS: Final = "payments"
PLUS_DIRECTIONS: Final = "directions"
PLUS_MEDIA: Final = "media"
PLUS_CATALOGUE: Final[tuple[tuple[str, str, str], ...]] = (
    (PLUS_PRODUCTS, "package", "Tus productos"),
    (PLUS_OFFER, "tag", "Tu oferta"),
    (PLUS_MENU, "list", "Tu menú"),
    (PLUS_PAYMENTS, "wallet", "Formas de pago"),
    (PLUS_DIRECTIONS, "map-pin", "Cómo llegar"),
    (PLUS_MEDIA, "images", "Fotos y videos"),
)
#: Instagram's photo, file and voice note are TOOLS, not «+» rows (2026-11-15): picking a
#: file must be the owner's own tap on the file input (iOS Safari drops a scripted
#: `input.click()` that runs after the event queue), and `orbit_menu`'s rows cannot host
#: the input without a variant of the design system.

#: What each screen's provider sends today, by tool and «+» row. A row the descriptor
#: allows but this table lacks is a missing door (`MISSING_DOORS`), not a hidden bug.
SEND_DOORS: Final[dict[str, frozenset[str]]] = {
    CHANNEL_WHATSAPP: frozenset(
        {
            TOOL_BUTTONS,
            PLUS_PRODUCTS,
            PLUS_OFFER,
            PLUS_MENU,
            PLUS_PAYMENTS,
            PLUS_DIRECTIONS,
            PLUS_MEDIA,
        }
    ),
    CHANNEL_INSTAGRAM_DM: frozenset(
        {
            TOOL_BUTTONS,
            TOOL_SAVED,
            TOOL_HEART,
            TOOL_SUGGEST,
            TOOL_PHOTO,
            TOOL_FILE,
            TOOL_VOICE,
        }
    ),
}


def _allowed(box: ReplyBoxVM, key: str) -> bool:
    """What the channel's API allows for a tool or a «+» row (the descriptor alone)."""
    return {
        TOOL_BUTTONS: box.can_buttons,
        TOOL_SAVED: box.can_saved,
        TOOL_HEART: box.can_heart,
        TOOL_SUGGEST: box.can_suggest,
        TOOL_PHOTO: box.can_photo,
        TOOL_FILE: box.can_file,
        TOOL_VOICE: box.can_voice,
        PLUS_PRODUCTS: box.can_photo,
        PLUS_OFFER: box.can_photo,
        # WhatsApp's menu is a list message answered by the automatic menu.
        PLUS_MENU: box.has_menu_handoff,
        PLUS_PAYMENTS: box.has_payments,
        # A text with the place: any chat channel can carry it. Instagram's door arrives
        # with BU-A15 (SEND_DOORS), so today it is a missing door there, not a refusal.
        PLUS_DIRECTIONS: True,
        PLUS_MEDIA: box.can_photo,
    }[key]


def draws(box: ReplyBoxVM, key: str) -> bool:
    """«¿Se dibuja?»: the API allows it AND this screen can send it today."""
    return _allowed(box, key) and key in SEND_DOORS.get(box.channel, frozenset())


def missing_doors(box: ReplyBoxVM) -> tuple[str, ...]:
    """What the channel's API allows but no screen sends yet (for the PR and BU-A8/A15)."""
    keys = (
        TOOL_BUTTONS,
        TOOL_SAVED,
        TOOL_HEART,
        TOOL_SUGGEST,
        TOOL_PHOTO,
        TOOL_FILE,
        TOOL_VOICE,
        *(key for key, _icon, _text in PLUS_CATALOGUE),
    )
    doors = SEND_DOORS.get(box.channel, frozenset())
    return tuple(k for k in keys if _allowed(box, k) and k not in doors)


@dataclass(frozen=True)
class PlusRow:
    key: str
    icon: str
    text: str


def plus_rows(box: ReplyBoxVM) -> tuple[PlusRow, ...]:
    """The «+» rows this channel draws, in the catalogue's order. None is ever disabled:
    a row the channel cannot send is simply absent."""
    return tuple(
        PlusRow(key=key, icon=icon, text=text)
        for key, icon, text in PLUS_CATALOGUE
        if draws(box, key)
    )


WHATSAPP_BOX: Final = box_for(CHANNEL_WHATSAPP)
INSTAGRAM_BOX: Final = box_for(CHANNEL_INSTAGRAM_DM)

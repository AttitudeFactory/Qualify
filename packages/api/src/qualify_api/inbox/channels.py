"""What each chat channel can do, declared as data (m-25017843, BU-A1).

`docs/arquitectura-bandeja-unica.md` §2.1: the static half of the shared chat — what a
CHANNEL offers (attachments, buttons, stickers, approved messages after the window, the
hand-off to a person, payments, AI suggestions, closing a chat). The dynamic half (is the
window open, is the menu answering, the payment status) travels on each inbox row
(`inbox.unified.InboxRow`). This module holds no behaviour and reads no database: the
screens translate it into what they draw, and each channel's own sender/service still
decides what it actually sends.

The values are written out here, not imported, so `test_inbox_channels.py` can hold them
against the channel modules (`conversations.contracts.REPLY_MEDIA_TYPES`,
`conversations.interactive.MAX_QUICK_REPLIES`, `whatsapp.client.MediaKind`/`MAX_BUTTONS`,
`whatsapp.window.WINDOW`): a descriptor that drifts from what the channel can build would be
a lie the UI tells the owner.

`INBOX_CHANNELS` is also the allow-list of the inbox query: a channel filter that is not
in it is refused (`UnknownChannel`), never interpolated. Comment threads (`comment`) are
not chats and are not listed. TikTok will register its own descriptor here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal

CHANNEL_INSTAGRAM_DM: Final = "dm"
CHANNEL_WHATSAPP: Final = "whatsapp"

ButtonStyle = Literal["quick_replies", "reply_buttons"]
StickerSupport = Literal["native", "heart_only", "none"]
AfterWindow = Literal["approved_template", "none"]


class UnknownChannel(ValueError):
    """A channel the inbox does not list (not registered here)."""


@dataclass(frozen=True)
class ChannelCapabilities:
    """What one channel offers a chat. Pure data; see the module docstring.

    - `attachments`: the media kinds a reply can carry;
    - `max_buttons` / `button_style`: how many tappable options ride on a message, and
      whether they are quick replies (Instagram) or reply buttons (WhatsApp);
    - `stickers`: `native` (any sticker), `heart_only` (Instagram's like-heart) or `none`;
    - `saved_messages`: the owner can send a stored message (templates / shortcuts);
    - `window_hours` / `after_window`: the free-form window after the customer's last
      message, and what may still be sent once it closes;
    - `menu_handoff`: an automatic menu answers and can hand the chat to a person;
    - `payments`: payment methods and «Pago por revisar» exist for the chat;
    - `suggest_reply`: Qualify can draft a reply with AI;
    - `close_reopen`: the owner can close a chat and reopen it.
    """

    channel: str
    attachments: frozenset[str]
    max_buttons: int
    button_style: ButtonStyle
    stickers: StickerSupport
    saved_messages: bool
    window_hours: int
    after_window: AfterWindow
    menu_handoff: bool
    payments: bool
    suggest_reply: bool
    close_reopen: bool


INSTAGRAM_DM: Final = ChannelCapabilities(
    channel=CHANNEL_INSTAGRAM_DM,
    attachments=frozenset({"image", "audio", "video", "document"}),
    max_buttons=13,
    button_style="quick_replies",
    stickers="heart_only",
    saved_messages=True,
    window_hours=24,
    # The Human Agent tag (7 days) is not modelled (`conversations.window`).
    after_window="none",
    # No automatic menu on Instagram yet (epic m-25017839, part B).
    menu_handoff=False,
    payments=False,
    suggest_reply=True,
    # «Cerrar chat» on Instagram is slice C9.
    close_reopen=False,
)

WHATSAPP: Final = ChannelCapabilities(
    channel=CHANNEL_WHATSAPP,
    attachments=frozenset({"image", "video", "document", "audio"}),
    max_buttons=3,
    button_style="reply_buttons",
    stickers="native",
    saved_messages=True,
    window_hours=24,
    after_window="approved_template",
    menu_handoff=True,
    payments=True,
    # Not built for WhatsApp (BU-A17/A18); it costs money and waits on a flag per business.
    suggest_reply=False,
    close_reopen=True,
)

CHANNEL_CAPABILITIES: Final[Mapping[str, ChannelCapabilities]] = MappingProxyType(
    {caps.channel: caps for caps in (INSTAGRAM_DM, WHATSAPP)}
)

# The channels the inbox lists, in a stable order — the query's allow-list.
INBOX_CHANNELS: Final[tuple[str, ...]] = tuple(CHANNEL_CAPABILITIES)


def capabilities_for(channel: str) -> ChannelCapabilities:
    """The descriptor of `channel`; `UnknownChannel` if the inbox does not list it."""
    try:
        return CHANNEL_CAPABILITIES[channel]
    except KeyError:
        raise UnknownChannel(f"channel {channel!r} is not an inbox channel") from None


def resolve_channels(channel: str | None) -> tuple[str, ...]:
    """The allow-listed channels a query may read: all of them, or the one asked for."""
    if channel is None:
        return INBOX_CHANNELS
    return (capabilities_for(channel).channel,)

"""The channel descriptors hold against what each channel can actually build (m-25017843)."""

from __future__ import annotations

from typing import get_args

import pytest

from qualify_api.conversations.contracts import REPLY_MEDIA_TYPES, REPLY_STICKERS
from qualify_api.conversations.interactive import MAX_QUICK_REPLIES
from qualify_api.inbox.channels import (
    CHANNEL_CAPABILITIES,
    INBOX_CHANNELS,
    INSTAGRAM_DM,
    WHATSAPP,
    UnknownChannel,
    capabilities_for,
    resolve_channels,
)
from qualify_api.inbox.models import Thread
from qualify_api.whatsapp.client import MAX_BUTTONS, MediaKind
from qualify_api.whatsapp.window import WINDOW


def test_instagram_attachments_are_what_its_sender_builds() -> None:
    assert INSTAGRAM_DM.attachments == REPLY_MEDIA_TYPES


def test_instagram_buttons_and_stickers_match_the_channel() -> None:
    assert INSTAGRAM_DM.max_buttons == MAX_QUICK_REPLIES
    assert INSTAGRAM_DM.stickers == "heart_only" and REPLY_STICKERS == {"like_heart"}


def test_whatsapp_attachments_and_buttons_match_the_cloud_api_client() -> None:
    assert frozenset(get_args(MediaKind)) == WHATSAPP.attachments
    assert WHATSAPP.max_buttons == MAX_BUTTONS


def test_whatsapp_does_not_suggest_replies_yet() -> None:
    assert WHATSAPP.suggest_reply is False


def test_both_channels_close_and_reopen_chats() -> None:
    # m-25026457: Instagram gains «Cerrar» / «Reabrir» (`ConversationService.close`).
    assert INSTAGRAM_DM.close_reopen is True
    assert WHATSAPP.close_reopen is True


def test_both_windows_are_the_24_hour_window() -> None:
    for caps in CHANNEL_CAPABILITIES.values():
        assert caps.window_hours * 3600 == WINDOW.total_seconds()


def test_inbox_channels_are_chat_channels_of_threads_and_never_comments() -> None:
    assert INBOX_CHANNELS == ("dm", "whatsapp")
    check = next(
        c for c in Thread.__table__.constraints if getattr(c, "name", "") == "ck_thread_channel"
    )
    for channel in INBOX_CHANNELS:
        assert f"'{channel}'" in str(check.sqltext)
    assert "comment" not in INBOX_CHANNELS


def test_the_descriptor_is_frozen() -> None:
    with pytest.raises(AttributeError):
        WHATSAPP.payments = False  # type: ignore[misc]
    with pytest.raises(TypeError):
        CHANNEL_CAPABILITIES["tiktok_dm"] = WHATSAPP  # type: ignore[index]


def test_resolve_channels_is_an_allow_list() -> None:
    assert resolve_channels(None) == INBOX_CHANNELS
    assert resolve_channels("whatsapp") == ("whatsapp",)
    assert capabilities_for("dm") is INSTAGRAM_DM
    for bad in ("comment", "tiktok_dm", "dm' OR '1'='1", ""):
        with pytest.raises(UnknownChannel):
            resolve_channels(bad)

"""The 24-hour messaging window for private conversations (QUA-226).

The decision already exists, pure and channel-agnostic, in `qualify_api.whatsapp.window`
(WA-08): OPEN for exactly 24 h after the counterpart's last INBOUND message, decided from
`threads.last_inbound_at` and never from `last_message_at` (0004's B2 condition, which
Instagram Messaging and WhatsApp share — `overview.md:178`). This module re-exports it so
the Conversaciones module has ONE import for the window and does not reach into the
WhatsApp package from several places; the day WhatsApp joins the multichannel inbox
(QUA-39) the implementation moves here and `whatsapp.window` becomes the re-export.

The Human Agent tag (7-day window, `features/human-agent-escalation.md`) needs its own
permission and App Review and is deliberately NOT modelled.

The PRIVATE REPLY to a comment (m-24789646) has its own limit, decided here too: one
message within 7 days of the comment's creation (`features/private-replies.md`), whether
or not the person ever wrote. Same `WindowState`, so the UI shows «quedan …» the same way
for both, and the same boundary rule (closed AT the instant).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final

from qualify_api.whatsapp.window import WINDOW, WindowState, WindowStatus, window_state

PRIVATE_REPLY_WINDOW: Final = timedelta(days=7)


def private_reply_deadline(comment_posted_at: datetime) -> datetime:
    """The instant Meta stops accepting a private reply to a comment."""
    return comment_posted_at + PRIVATE_REPLY_WINDOW


def private_reply_window(comment_posted_at: datetime | None, now: datetime) -> WindowState:
    """OPEN until 7 days after the comment, CLOSED at that instant. A comment without a
    creation time cannot be proven to be inside the limit, so it is CLOSED."""
    if comment_posted_at is None:
        return WindowState(WindowStatus.CLOSED)
    # A 7-day window is a 24 h window that starts 6 days later.
    return window_state(private_reply_deadline(comment_posted_at) - WINDOW, now)


__all__ = [
    "PRIVATE_REPLY_WINDOW",
    "WINDOW",
    "WindowState",
    "WindowStatus",
    "private_reply_deadline",
    "private_reply_window",
    "window_state",
]

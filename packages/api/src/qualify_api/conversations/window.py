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
"""

from __future__ import annotations

from qualify_api.whatsapp.window import WINDOW, WindowState, WindowStatus, window_state

__all__ = ["WINDOW", "WindowState", "WindowStatus", "window_state"]

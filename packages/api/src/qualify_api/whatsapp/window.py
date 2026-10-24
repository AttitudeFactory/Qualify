"""The 24-hour customer-service window, as a POLICY (WA-08).

`docs/plan-modulo-whatsapp-cloud-api.md` §5.2 and `docs/backlog-modulo-whatsapp.md` §1:
the window is decided from `threads.last_inbound_at` — never from `last_message_at`
(0004's B2 condition) and never by a clock of its own. This module is the ONE place that
decides it; the sender (`outbox.py`), the HTTP API (WA-10, its 409) and the UI badge
(WA-11) all call `window_state` rather than re-deriving "24 h" anywhere else.

Pure: no I/O, no `datetime.now()` — the caller passes `now`, so every boundary is testable
and the sender and the UI agree on the same instant.

What Meta says (cloud-api/overview, read 2026-10-14): every message a user sends opens a
24-hour window in which the business may send any message (text, media, interactive,
Flows) for free; outside it only an approved **template** goes through — a free-form body
is refused with error `131047` (re-engagement required) and, for some number states,
`131026`. The sender treats those two codes as a `failed` outcome, not a retry: waiting
will not reopen the window, only the user can.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Final

WINDOW: Final = timedelta(hours=24)

# `whatsapp_outbox.kind` values (models.OUTBOX_KINDS) split by what they may carry. A
# `campaign_send` is template-only by construction (WA-18 builds it from an approved
# template), so the window never applies to it; a `reply` (a person, WA-10) and an
# `automation` (the menu engine, WA-14) are free-form bodies and need the window OPEN.
# A `template_reply` (m-24848535, 0087) is an approved template a person sends from an
# expired chat: template-only, so it is exactly what still goes through once the window
# has closed.
FREE_FORM_KINDS: Final = frozenset({"reply", "automation"})
TEMPLATE_ONLY_KINDS: Final = frozenset({"campaign_send", "template_reply"})

# Meta error codes that mean "outside the window / re-engagement needed".
WINDOW_CLOSED_ERROR_CODES: Final = frozenset({131047, 131026})


class WindowStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


@dataclass(frozen=True)
class WindowState:
    """`closes_at` is set only while OPEN: the instant the window shuts (the UI's
    "abierta hasta HH:MM"). A CLOSED window carries `None` — including the case where the
    user never wrote (`last_inbound_at is None`), which has no instant to show."""

    status: WindowStatus
    closes_at: datetime | None = None

    @property
    def is_open(self) -> bool:
        return self.status is WindowStatus.OPEN


def _as_utc(value: datetime) -> datetime:
    """The columns are `timestamptz` (0004), so values arrive aware; a naive value can only
    come from test code or a hand-built `now` and is taken as UTC rather than compared
    against an aware one (which would raise)."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def window_state(last_inbound_at: datetime | None, now: datetime) -> WindowState:
    """OPEN for exactly `WINDOW` after the user's last inbound message; CLOSED at the
    boundary itself (`now == last_inbound_at + 24 h` is closed — Meta refuses at that
    instant, and a send that leaves the queue a moment later would fail anyway)."""
    if last_inbound_at is None:
        return WindowState(WindowStatus.CLOSED)
    closes_at = _as_utc(last_inbound_at) + WINDOW
    if _as_utc(now) >= closes_at:
        return WindowState(WindowStatus.CLOSED)
    return WindowState(WindowStatus.OPEN, closes_at=closes_at)


def is_free_form_allowed(kind: str, window: WindowState) -> bool:
    """May an outbox item of this `kind` be sent under this window? Template-only kinds
    always may; free-form kinds only while OPEN. An unknown kind is refused — the CHECK on
    `whatsapp_outbox.kind` makes it unreachable from the database, so reaching it here is
    a programming error that must not turn into a send."""
    if kind in TEMPLATE_ONLY_KINDS:
        return True
    if kind in FREE_FORM_KINDS:
        return window.is_open
    return False

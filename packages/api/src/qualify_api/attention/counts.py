"""The pending counts of «Por responder» (m-24842990, ATENDER-1).

One number per channel, each defined exactly as the list it opens filters it, so the
figure the owner taps is the length of the list that opens (N11):

- **messages** and **whatsapp** — the chats of Instagram Direct (`dm`) and of WhatsApp
  that wait for a reply under the ONE «Por responder» rule (`inbox.awaiting`, story
  m-25017859): open, the customer wrote after the last reply a person sent, and nobody
  answered / handed to a person / an automatic send failed; on Instagram only while the
  reply window is open. Both are `inbox.awaiting.count_awaiting_sql`, judged at one bound
  instant, so they equal `inbox.unified.count_inbox(channel=…)` — the unified list's
  total — by construction (`test_inbox_counters_db.py`). Reading a chat does not clear
  it; closing it does.
- **buyers** — the commercial queries still `open` in `interaction_followups` whose
  origin comment is still visible (the «Quieren comprar» cards);
- **comments** — the assisted public replies waiting for the owner's approval
  (`comment_reply_drafts.status = 'proposed'`, «Respuestas listas para aprobar»).

The counts cover every connected account of the tenant, like the unified list.

Every statement runs through `tenant_session(tenant_id)`: RLS on each table scopes the
counts to the tenant, and another tenant's rows are invisible, not filtered by hand.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.inbox.awaiting import count_awaiting_sql
from qualify_api.inbox.channels import CHANNEL_INSTAGRAM_DM, CHANNEL_WHATSAPP

# Both chat counts judge the rule at ONE bound instant (`:now`), the one `inbox.unified`
# binds too — never two clocks.
_NOW_PARAM = "now"

_COUNTS_SQL = f"""
SELECT
  {count_awaiting_sql(CHANNEL_INSTAGRAM_DM, now_param=_NOW_PARAM)} AS messages,
  (SELECT count(*)
     FROM interaction_followups f
     JOIN messages m ON m.id = f.origin_message_id
    WHERE f.status = 'open' AND m.unsent_at IS NULL) AS buyers,
  (SELECT count(*)
     FROM comment_reply_drafts d
     JOIN messages m ON m.id = d.message_id
    WHERE d.status = 'proposed') AS comments,
  {count_awaiting_sql(CHANNEL_WHATSAPP, now_param=_NOW_PARAM)} AS whatsapp
"""

_COUNTS = text(_COUNTS_SQL)


@dataclass(frozen=True)
class PendingCounts:
    """How many people wait for the owner, per channel. Never negative."""

    messages: int = 0
    buyers: int = 0
    comments: int = 0
    whatsapp: int = 0

    @property
    def total(self) -> int:
        return self.messages + self.buyers + self.comments + self.whatsapp


class PendingCountsStore(Protocol):
    def read(self, tenant_id: UUID) -> PendingCounts: ...


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PostgresPendingCounts:
    """One round trip, one `tenant_session` — the only sanctioned door. `clock` is the
    instant the chat rule is judged at (tests pin it; default: the wall clock)."""

    def __init__(self, clock: Callable[[], datetime] = _utcnow) -> None:
        self._clock = clock

    def read(self, tenant_id: UUID) -> PendingCounts:
        with tenant_session(tenant_id) as session:
            row = session.execute(_COUNTS, {_NOW_PARAM: self._clock()}).one()
        return PendingCounts(
            messages=max(0, int(row.messages or 0)),
            buyers=max(0, int(row.buyers or 0)),
            comments=max(0, int(row.comments or 0)),
            whatsapp=max(0, int(row.whatsapp or 0)),
        )


def pending_counts(tenant_id: UUID, store: PendingCountsStore | None = None) -> PendingCounts:
    """The tenant's pending counts. Blocking (one DB round trip): call it off the event
    loop (`asyncio.to_thread`)."""
    return (store or PostgresPendingCounts()).read(tenant_id)

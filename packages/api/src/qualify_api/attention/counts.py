"""The pending counts of «Por responder» (m-24842990, ATENDER-1).

One number per channel:

- **messages** — Instagram private conversations (`threads.channel = 'dm'`) and
- **whatsapp** — WhatsApp chats (`threads.channel = 'whatsapp'`),

  both counted with the ONE «Por responder» rule of `qualify_api.inbox.awaiting`
  (m-25017843, founder's decision (ii) of 2026-11-13): an open chat whose customer wrote
  after the last reply a person sent, unless only the automatic menu answered it and
  nobody handed it to a person and no automatic send failed. The SQL fragment is the very
  one the unified inbox list (`qualify_api.inbox.unified`, filter `por_responder`)
  filters by, so this figure and that list cannot differ. Until the unified list ships,
  the per-channel screens keep their own filters: Instagram's «Pendientes» still drops a
  chat once it is opened, and WhatsApp's «Sin leer» still counts closed chats and leaves
  out a chat handed to a person after the menu's last message — the counts no longer do;
- **buyers** — the commercial queries still `open` in `interaction_followups` whose
  origin comment is still visible (the «Quieren comprar» cards);
- **comments** — the assisted public replies waiting for the owner's approval
  (`comment_reply_drafts.status = 'proposed'`, «Respuestas listas para aprobar»).

The counts cover every connected account of the tenant; the lists they open show one
account at a time (their own selector), so with several accounts a list can be shorter
than its figure until the owner switches account.

Every statement runs through `tenant_session(tenant_id)`: RLS on each table scopes the
counts to the tenant, and another tenant's rows are invisible, not filtered by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.inbox.awaiting import awaiting_reply_sql
from qualify_api.inbox.channels import CHANNEL_INSTAGRAM_DM, CHANNEL_WHATSAPP

_AWAITING = awaiting_reply_sql("t")

_COUNTS_SQL = f"""
SELECT
  (SELECT count(*)
     FROM threads t
    WHERE t.channel = '{CHANNEL_INSTAGRAM_DM}' AND {_AWAITING}) AS messages,
  (SELECT count(*)
     FROM interaction_followups f
     JOIN messages m ON m.id = f.origin_message_id
    WHERE f.status = 'open') AS buyers,
  (SELECT count(*)
     FROM comment_reply_drafts d
     JOIN messages m ON m.id = d.message_id
    WHERE d.status = 'proposed') AS comments,
  (SELECT count(*)
     FROM threads t
    WHERE t.channel = '{CHANNEL_WHATSAPP}' AND {_AWAITING}) AS whatsapp
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


class PostgresPendingCounts:
    """One round trip, one `tenant_session` — the only sanctioned door."""

    def read(self, tenant_id: UUID) -> PendingCounts:
        with tenant_session(tenant_id) as session:
            row = session.execute(_COUNTS).one()
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

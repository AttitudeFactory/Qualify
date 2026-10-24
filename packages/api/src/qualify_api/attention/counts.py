"""The pending counts of «Por responder» (m-24842990, ATENDER-1).

One number per channel, each defined exactly as the list it opens filters it, so the
figure the owner taps is the length of the list that opens (N11):

- **messages** — Instagram private conversations (`threads.channel = 'dm'`) in the
  `PENDING` attention state of `conversations.service.attention_state`: a last inbound
  message, no outbound at or after it, and not opened since (Conversaciones' filter
  «Pendientes»);
- **buyers** — the commercial queries still `open` in `interaction_followups` whose
  origin comment is still visible (the «Quieren comprar» cards);
- **comments** — the assisted public replies waiting for the owner's approval
  (`comment_reply_drafts.status = 'proposed'`, «Respuestas listas para aprobar»);
- **whatsapp** — WhatsApp chats with an inbound message after the last outbound one
  (WhatsApp › Chats' filter «Sin leer»).

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

# A message's instant: Meta's timestamp, else when we stored it — the same expression
# `conversations.repository` and `whatsapp.chats` order and compare by.
_INSTANT = "COALESCE({m}.posted_at, {m}.ingested_at)"

_COUNTS_SQL = """
SELECT
  (SELECT count(*)
     FROM threads t
    WHERE t.channel = 'dm'
      AND t.last_inbound_at IS NOT NULL
      AND (t.last_read_at IS NULL OR t.last_read_at < t.last_inbound_at)
      AND NOT EXISTS (
            SELECT 1 FROM messages o
             WHERE o.thread_id = t.id AND o.direction = 'outbound'
               AND {o_instant} >= t.last_inbound_at)) AS messages,
  (SELECT count(*)
     FROM interaction_followups f
     JOIN messages m ON m.id = f.origin_message_id
    WHERE f.status = 'open') AS buyers,
  (SELECT count(*)
     FROM comment_reply_drafts d
     JOIN messages m ON m.id = d.message_id
    WHERE d.status = 'proposed') AS comments,
  (SELECT count(*)
     FROM threads w
    WHERE w.channel = 'whatsapp'
      AND EXISTS (
            SELECT 1 FROM messages u
             WHERE u.thread_id = w.id AND u.direction = 'inbound'
               AND u.deleted_at IS NULL
               AND {u_instant} > COALESCE(
                     (SELECT max({x_instant}) FROM messages x
                       WHERE x.thread_id = w.id AND x.direction = 'outbound'
                         AND x.deleted_at IS NULL),
                     CAST('-infinity' AS timestamptz)))) AS whatsapp
""".format(
    o_instant=_INSTANT.format(m="o"),
    u_instant=_INSTANT.format(m="u"),
    x_instant=_INSTANT.format(m="x"),
)

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

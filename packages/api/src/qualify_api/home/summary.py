"""The counts behind Inicio (m-24842962, NAV-4) — ONE read-only query per visit.

Inicio answers two questions in the owner's words: «¿qué tengo que hacer hoy?» and
«¿cómo me fue esta semana?» (`docs/ux-guia-navegacion.md` §2, N2, N11). Every figure is
a count over tables other modules already own; nothing here is stored, so nothing can
drift from the screens the figures link to.

Each figure follows the rule of the screen it opens, so the number on Inicio is the
number the owner finds on arrival:

- `people_waiting` — Instagram Direct threads whose attention state is «pendiente»
  (`conversations.service.attention_state`): an inbound message newer than the last
  reply AND than the last time someone opened the thread. Same filter as
  Conversaciones › «Pendientes».
- `drafts_to_approve` — publications generated and waiting for the human gate
  (`content_drafts.status = 'generated'`, the creative FSM's HITL #2; the planner reads
  it as `ApprovalStatus.PENDING`). This is only the fallback: Inicio's provider
  (`Qualify/home_provider.py`) replaces it with the gallery's «Por completar» count
  (`planner.gallery.gallery_state`), which also includes approved publications that
  cannot go out yet — the list the card opens.
- `comments_unanswered` — comments on the business's own publications from the last
  7 days that no reply from Qualify has answered (`comment_reply_drafts.status =
  'sent'`) and that were not deleted. The window is the week: older comments are
  history, not a task for today.
- `messages_week_dm` / `messages_week_whatsapp` — inbound messages in the last 7 days.
- `comments_week` — comments received in the last 7 days.
- `mentions_week` — mentions received in the last 7 days, removed ones excluded.
- `instagram_connected` — an active Instagram connection exists.
- `has_publication` — the business has started at least one publication.

Tenant isolation: the query runs inside `tenant_session`, so every table's RLS policy
scopes it to the active tenant; there is no `tenant_id` filter to forget (proved by
`tests/test_home_summary_db.py` with two tenants).
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.orm import Session

#: «Así te fue esta semana» = the last 7 days, counted back from now.
WEEK = timedelta(days=7)


@dataclass(frozen=True)
class HomeCounts:
    people_waiting: int = 0
    drafts_to_approve: int = 0
    comments_unanswered: int = 0
    messages_week_dm: int = 0
    messages_week_whatsapp: int = 0
    comments_week: int = 0
    mentions_week: int = 0
    instagram_connected: bool = False
    has_publication: bool = False

    @property
    def messages_week(self) -> int:
        return self.messages_week_dm + self.messages_week_whatsapp


# `COALESCE(posted_at, ingested_at)`: the channel's own timestamp when it gave one, else
# when Qualify stored it — the same expression the conversations repository orders by.
HOME_COUNTS_SQL = text(
    """
    SELECT
      (SELECT count(*) FROM threads t
        WHERE t.channel = 'dm'
          AND t.last_inbound_at IS NOT NULL
          AND (t.last_read_at IS NULL OR t.last_read_at < t.last_inbound_at)
          AND NOT EXISTS (
                SELECT 1 FROM messages o
                 WHERE o.thread_id = t.id AND o.direction = 'outbound'
                   AND COALESCE(o.posted_at, o.ingested_at) >= t.last_inbound_at)
      ) AS people_waiting,
      (SELECT count(*) FROM content_drafts d WHERE d.status = 'generated')
        AS drafts_to_approve,
      (SELECT count(*) FROM messages m JOIN threads t ON t.id = m.thread_id
        WHERE t.channel = 'comment' AND m.direction = 'inbound' AND m.deleted_at IS NULL
          AND COALESCE(m.posted_at, m.ingested_at) >= :since
          AND NOT EXISTS (
                SELECT 1 FROM comment_reply_drafts r
                 WHERE r.message_id = m.id AND r.status = 'sent')
      ) AS comments_unanswered,
      (SELECT count(*) FROM messages m JOIN threads t ON t.id = m.thread_id
        WHERE t.channel = 'dm' AND m.direction = 'inbound'
          AND COALESCE(m.posted_at, m.ingested_at) >= :since
      ) AS messages_week_dm,
      (SELECT count(*) FROM messages m JOIN threads t ON t.id = m.thread_id
        WHERE t.channel = 'whatsapp' AND m.direction = 'inbound'
          AND COALESCE(m.posted_at, m.ingested_at) >= :since
      ) AS messages_week_whatsapp,
      (SELECT count(*) FROM messages m JOIN threads t ON t.id = m.thread_id
        WHERE t.channel = 'comment' AND m.direction = 'inbound' AND m.deleted_at IS NULL
          AND COALESCE(m.posted_at, m.ingested_at) >= :since
      ) AS comments_week,
      (SELECT count(*) FROM mentions n
        WHERE n.removed_at IS NULL AND n.received_at >= :since
      ) AS mentions_week,
      EXISTS (SELECT 1 FROM social_connections c
               WHERE c.platform = 'instagram' AND c.status = 'active'
      ) AS instagram_connected,
      EXISTS (SELECT 1 FROM content_drafts d WHERE d.status <> 'failed')
        AS has_publication
    """
)

SessionFactory = Callable[[UUID], AbstractContextManager[Session]]


def counts_from_row(row: Any) -> HomeCounts:
    """The query's one row as `HomeCounts` (pure — a `None` count reads as 0)."""
    return HomeCounts(
        people_waiting=int(row.people_waiting or 0),
        drafts_to_approve=int(row.drafts_to_approve or 0),
        comments_unanswered=int(row.comments_unanswered or 0),
        messages_week_dm=int(row.messages_week_dm or 0),
        messages_week_whatsapp=int(row.messages_week_whatsapp or 0),
        comments_week=int(row.comments_week or 0),
        mentions_week=int(row.mentions_week or 0),
        instagram_connected=bool(row.instagram_connected),
        has_publication=bool(row.has_publication),
    )


def read_home_counts(
    tenant_id: UUID,
    *,
    now: datetime | None = None,
    session_factory: SessionFactory = tenant_session,
) -> HomeCounts:
    """Every figure of Inicio for `tenant_id`. Blocking (DB) — run off the event loop."""
    since = (now or datetime.now(UTC)) - WEEK
    with session_factory(tenant_id) as session:
        row = session.execute(HOME_COUNTS_SQL, {"since": since}).one()
    return counts_from_row(row)


__all__ = ["HOME_COUNTS_SQL", "WEEK", "HomeCounts", "counts_from_row", "read_home_counts"]

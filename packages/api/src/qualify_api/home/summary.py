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
- `videos_expiring_soon` — publications waiting for approval whose vista previa can
  give its video final for 2 more days at most (a Seedance draft lasts 7 days from its
  `created_at`; founder, 2026-10-24): «{n} videos vencen pronto».
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

from qualify_creative.adapters.byteplus_ark import DRAFT_TTL_SECONDS
from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.orm import Session

#: «Así te fue esta semana» = the last 7 days, counted back from now.
WEEK = timedelta(days=7)
#: «{n} videos vencen pronto»: from 2 days before a vista previa expires (founder,
#: 2026-10-24).
EXPIRING_SOON = timedelta(days=2)


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
    #: Last, so positional construction keeps its meaning (founder, 2026-10-24).
    videos_expiring_soon: int = 0
    videos_to_confirm: int = 0
    videos_late: int = 0
    finals_failed: int = 0
    videos_ready_late: int | None = None

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
      (SELECT count(DISTINCT d.id) FROM content_drafts d
         JOIN image_assets a ON a.draft_id = d.id
        WHERE d.status = 'generated'
          AND a.params ? 'draft'
          AND COALESCE(a.params->'draft'->>'status', 'draft') IN ('draft', 'failed')
          AND NOT (a.params->'draft' ? 'raw_final')
          AND jsonb_typeof(a.params->'draft'->'created_at') = 'number'
          AND (a.params->'draft'->>'created_at')::double precision + :draft_ttl
              > extract(epoch FROM CAST(:now AS timestamptz))
          AND (a.params->'draft'->>'created_at')::double precision + :draft_ttl
              <= extract(epoch FROM CAST(:now AS timestamptz)) + :expiring_soon
      ) AS videos_expiring_soon,
      (SELECT count(DISTINCT d.id) FROM content_drafts d
         JOIN image_assets a ON a.draft_id = d.id
        WHERE d.status = 'approved' AND a.params->'draft'->>'status' IN ('final_ready','final')
          AND (a.params->'draft'->>'status' <> 'final'
               OR a.params->'draft'->>'confirmed_sha256' IS NULL
               OR a.params->'draft'->>'confirmed_sha256' IS DISTINCT FROM
                  a.params->'draft'->>'final_sha256'
               OR a.params->'draft'->>'confirmed_object_key' IS DISTINCT FROM a.object_key
               OR a.params->'draft'->>'final_object_key' IS DISTINCT FROM a.object_key
               OR a.params->'draft'->>'confirmed_revision' IS DISTINCT FROM d.revision::text
               OR a.params->'draft'->>'confirmed_by' IS NULL
               OR a.params->'draft'->>'confirmed_at' IS NULL)
          AND NOT EXISTS (SELECT 1 FROM image_assets pending
               WHERE pending.draft_id=d.id AND pending.params ? 'draft'
                 AND pending.params->'draft'->>'status' NOT IN ('final_ready','final'))
      ) AS videos_to_confirm,
      (SELECT count(DISTINCT d.id) FROM content_drafts d
         JOIN image_assets a ON a.draft_id = d.id
        WHERE d.status = 'approved' AND a.params->'draft'->>'status' IN ('final_ready','final')
          AND (a.params->'draft'->>'status' <> 'final'
               OR a.params->'draft'->>'confirmed_sha256' IS NULL
               OR a.params->'draft'->>'confirmed_sha256' IS DISTINCT FROM
                  a.params->'draft'->>'final_sha256'
               OR a.params->'draft'->>'confirmed_object_key' IS DISTINCT FROM a.object_key
               OR a.params->'draft'->>'final_object_key' IS DISTINCT FROM a.object_key
               OR a.params->'draft'->>'confirmed_revision' IS DISTINCT FROM d.revision::text
               OR a.params->'draft'->>'confirmed_by' IS NULL
               OR a.params->'draft'->>'confirmed_at' IS NULL)
          AND NOT EXISTS (SELECT 1 FROM image_assets pending
               WHERE pending.draft_id=d.id AND pending.params ? 'draft'
                 AND pending.params->'draft'->>'status' NOT IN ('final_ready','final'))

          AND EXISTS (SELECT 1 FROM calendar_events late WHERE late.post_id=d.id
              AND late.status='scheduled' AND late.scheduled_at <= CAST(:now AS timestamptz)
              AND late.scheduled_at > CAST(:now AS timestamptz)-interval '24 hours')
      ) AS videos_ready_late,
      (SELECT count(DISTINCT d.id) FROM content_drafts d
         JOIN image_assets a ON a.draft_id = d.id
        WHERE d.status = 'approved' AND a.params->'draft'->>'status' IN ('final_ready','final')
          AND (a.params->'draft'->>'status' <> 'final'
               OR a.params->'draft'->>'confirmed_sha256' IS NULL
               OR a.params->'draft'->>'confirmed_sha256' IS DISTINCT FROM
                  a.params->'draft'->>'final_sha256'
               OR a.params->'draft'->>'confirmed_object_key' IS DISTINCT FROM a.object_key
               OR a.params->'draft'->>'final_object_key' IS DISTINCT FROM a.object_key
               OR a.params->'draft'->>'confirmed_revision' IS DISTINCT FROM d.revision::text
               OR a.params->'draft'->>'confirmed_by' IS NULL
               OR a.params->'draft'->>'confirmed_at' IS NULL)
          AND NOT EXISTS (SELECT 1 FROM image_assets pending
               WHERE pending.draft_id=d.id AND pending.params ? 'draft'
                 AND pending.params->'draft'->>'status' NOT IN ('final_ready','final'))

          AND EXISTS (SELECT 1 FROM calendar_events late WHERE late.post_id=d.id
              AND late.status='scheduled' AND late.scheduled_at <= CAST(:now AS timestamptz)
              AND late.scheduled_at > CAST(:now AS timestamptz)-interval '24 hours')
      ) AS videos_late,
      (SELECT count(DISTINCT d.id) FROM content_drafts d
         JOIN image_assets a ON a.draft_id = d.id
        WHERE d.status = 'approved' AND a.params->'draft'->>'status' = 'failed'
      ) AS finals_failed,
      (SELECT count(*) FROM messages m JOIN threads t ON t.id = m.thread_id
        WHERE t.channel = 'comment'  AND m.direction = 'inbound' AND m.deleted_at IS NULL
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
        WHERE t.channel = 'comment'  AND m.direction = 'inbound' AND m.deleted_at IS NULL
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
        videos_to_confirm=int(getattr(row, "videos_to_confirm", 0) or 0),
        videos_late=int(getattr(row, "videos_late", 0) or 0),
        finals_failed=int(getattr(row, "finals_failed", 0) or 0),
        videos_ready_late=(
            int(row.videos_ready_late or 0) if hasattr(row, "videos_ready_late") else None
        ),
        drafts_to_approve=int(row.drafts_to_approve or 0),
        videos_expiring_soon=int(row.videos_expiring_soon or 0),
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
    moment = now or datetime.now(UTC)
    since = moment - WEEK
    params = {
        "since": since,
        "now": moment,
        "draft_ttl": DRAFT_TTL_SECONDS,
        "expiring_soon": EXPIRING_SOON.total_seconds(),
    }
    with session_factory(tenant_id) as session:
        row = session.execute(HOME_COUNTS_SQL, params).one()
    return counts_from_row(row)


__all__ = [
    "EXPIRING_SOON",
    "HOME_COUNTS_SQL",
    "WEEK",
    "HomeCounts",
    "counts_from_row",
    "read_home_counts",
]

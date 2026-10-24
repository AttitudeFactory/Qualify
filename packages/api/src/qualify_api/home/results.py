"""The counts behind Resultados (m-24843003, RESULTADOS-5) — ONE read-only query per visit.

Resultados answers «¿cómo me va?» in one place (`docs/ux-guia-navegacion.md` §2-3), with a
tab per channel: Redes · WhatsApp · Tu página web · Quién habla de ti. The last two keep
their own reads (Clarity's snapshot, the mentions listing); this query feeds the first two
and the one figure the mentions tab is entered by. It reuses Inicio's week (`WEEK`) and
Inicio's rules for every figure the two screens share, so the number on Inicio and the
number on Resultados never disagree:

- `messages_week_dm` / `messages_week_whatsapp` / `comments_week` / `mentions_week` —
  exactly as `summary.HOME_COUNTS_SQL` counts them (inbound in the last 7 days).
- `people_week_dm` / `people_week_whatsapp` — distinct conversations with at least one
  inbound message in the last 7 days («personas que te escribieron»).
- `published_week` — publications that came out on the business's accounts in the last
  7 days (`publish_attempts.status = 'published'`, settled in the window); a carousel is
  one publication, its children are not counted.
- `instagram_connected` — an active Instagram connection exists (same as Inicio).
- `whatsapp_connected` — a WhatsApp number is registered for the business.

Tenant isolation: the query runs inside `tenant_session`, so every table's RLS policy
scopes it to the active tenant; there is no `tenant_id` filter to forget (proved by
`tests/test_home_results_db.py` with two tenants).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.home.summary import WEEK, SessionFactory


@dataclass(frozen=True)
class ResultsCounts:
    messages_week_dm: int = 0
    people_week_dm: int = 0
    comments_week: int = 0
    published_week: int = 0
    messages_week_whatsapp: int = 0
    people_week_whatsapp: int = 0
    mentions_week: int = 0
    instagram_connected: bool = False
    whatsapp_connected: bool = False


_INBOUND_WEEK = """
    (SELECT count(*) FROM messages m JOIN threads t ON t.id = m.thread_id
      WHERE t.channel = '{channel}' AND m.direction = 'inbound'
        AND COALESCE(m.posted_at, m.ingested_at) >= :since)
"""
_PEOPLE_WEEK = """
    (SELECT count(DISTINCT t.id) FROM messages m JOIN threads t ON t.id = m.thread_id
      WHERE t.channel = '{channel}' AND m.direction = 'inbound'
        AND COALESCE(m.posted_at, m.ingested_at) >= :since)
"""

RESULTS_COUNTS_SQL = text(
    f"""
    SELECT
      {_INBOUND_WEEK.format(channel="dm")} AS messages_week_dm,
      {_PEOPLE_WEEK.format(channel="dm")} AS people_week_dm,
      (SELECT count(*) FROM messages m JOIN threads t ON t.id = m.thread_id
        WHERE t.channel = 'comment' AND m.direction = 'inbound' AND m.deleted_at IS NULL
          AND COALESCE(m.posted_at, m.ingested_at) >= :since
      ) AS comments_week,
      (SELECT count(*) FROM publish_attempts a
        WHERE a.status = 'published' AND a.settled_at >= :since
      ) AS published_week,
      {_INBOUND_WEEK.format(channel="whatsapp")} AS messages_week_whatsapp,
      {_PEOPLE_WEEK.format(channel="whatsapp")} AS people_week_whatsapp,
      (SELECT count(*) FROM mentions n
        WHERE n.removed_at IS NULL AND n.received_at >= :since
      ) AS mentions_week,
      EXISTS (SELECT 1 FROM social_connections c
               WHERE c.platform = 'instagram' AND c.status = 'active'
      ) AS instagram_connected,
      EXISTS (SELECT 1 FROM whatsapp_phone_numbers p) AS whatsapp_connected
    """
)


def results_from_row(row: Any) -> ResultsCounts:
    """The query's one row as `ResultsCounts` (pure — a `None` count reads as 0)."""
    return ResultsCounts(
        messages_week_dm=int(row.messages_week_dm or 0),
        people_week_dm=int(row.people_week_dm or 0),
        comments_week=int(row.comments_week or 0),
        published_week=int(row.published_week or 0),
        messages_week_whatsapp=int(row.messages_week_whatsapp or 0),
        people_week_whatsapp=int(row.people_week_whatsapp or 0),
        mentions_week=int(row.mentions_week or 0),
        instagram_connected=bool(row.instagram_connected),
        whatsapp_connected=bool(row.whatsapp_connected),
    )


def read_results_counts(
    tenant_id: UUID,
    *,
    now: datetime | None = None,
    session_factory: SessionFactory = tenant_session,
) -> ResultsCounts:
    """Every figure of Resultados for `tenant_id`. Blocking (DB) — run off the event loop."""
    since = (now or datetime.now(UTC)) - WEEK
    with session_factory(tenant_id) as session:
        row = session.execute(RESULTS_COUNTS_SQL, {"since": since}).one()
    return results_from_row(row)


__all__ = ["RESULTS_COUNTS_SQL", "ResultsCounts", "read_results_counts", "results_from_row"]

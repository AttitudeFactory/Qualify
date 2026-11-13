"""The unified chat inbox: one read over every chat channel (m-25017843, BU-A1).

`docs/arquitectura-bandeja-unica.md` §2.2, option C: the inbox converges the READ, not the
writes. One statement over `threads` lists the tenant's chats of every allow-listed channel
(`inbox.channels.INBOX_CHANNELS`: Instagram Direct `dm` and `whatsapp`; never `comment`),
newest activity first, one page per database round trip. Sending, outboxes, workers and
ingestion stay per channel; this module writes nothing.

**Not wired yet.** Nothing in production reads this module today; the unified-list
story m-25017859 wires the screens, the menu counters and Inicio to it together.

**Filters.** `por_responder` — the single rule of `inbox.awaiting` (the fragment the
counters will use, `count_awaiting_sql`), judged at the caller's `now` (an Instagram chat
counts only while its reply window is open); `todos` — every open chat, so an Instagram
chat whose window closed still shows there (`awaiting_reply` and `window_open` false);
`cerrados` — closed.
An optional channel narrows to one allow-listed channel (`UnknownChannel` otherwise).

**Order and pages.** `last_message_at DESC NULLS LAST, id DESC` with a composite keyset
cursor `(last_message_at, id)` — two chats with the same instant are both returned, the
`before`-only paging of `whatsapp.chats` could skip one. The page reads `limit + 1` rows to
know whether another page exists.

**One statement per page, page first.** A MATERIALIZED `page` CTE picks the page's rows
on `threads` alone in index order (see `_PAGE_DATED`); then, for those rows only, the
newest message comes from a `LEFT JOIN LATERAL`, the WhatsApp-only state
(`whatsapp_thread_state`: the owner's hand-over, the payment record) from a `LEFT JOIN`
that is NULL on Instagram, the outbound media kind from the matching `whatsapp_outbox`
row. No per-thread round trip.

**Tenant isolation.** Only `tenant_session(tenant_id)`: RLS scopes every table read here;
no tenant column is filtered by hand. Channels are bound as a parameter from the
allow-list, never interpolated.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Literal, Protocol, get_args
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.inbox.awaiting import awaiting_reply_sql
from qualify_api.inbox.channels import CHANNEL_INSTAGRAM_DM, CHANNEL_WHATSAPP, resolve_channels
from qualify_api.whatsapp.window import window_state

InboxFilter = Literal["por_responder", "todos", "cerrados"]
INBOX_FILTERS: Final[tuple[str, ...]] = get_args(InboxFilter)

DEFAULT_PAGE_SIZE: Final = 50
MAX_PAGE_SIZE: Final = 100

_INSTANT: Final = "COALESCE({m}.posted_at, {m}.ingested_at)"
# The rule's «now» is bound, not the database's `now()`: the list, the count, the rows'
# `window_*` and the Python twin all judge the same instant (`now=`).
_NOW_PARAM: Final = "now"

# What each filter keeps, over the `threads` row `t`; `_RULE` stands for the rule.
_RULE: Final = "<awaiting_reply>"
_FILTER_SQL: Final[dict[str, str]] = {
    "por_responder": _RULE,
    "todos": "t.status = 'open'",
    "cerrados": "t.status = 'closed'",
}


class InvalidCursor(ValueError):
    """A page cursor this module did not produce."""


@dataclass(frozen=True)
class InboxCursor:
    """Where the next page starts: strictly after `(last_message_at, thread_id)` in the
    list's order (`last_message_at DESC NULLS LAST, id DESC`)."""

    last_message_at: datetime | None
    thread_id: UUID

    def encode(self) -> str:
        """An opaque, URL-safe token for the UI to hand back."""
        at = "" if self.last_message_at is None else self.last_message_at.isoformat()
        raw = f"{at}|{self.thread_id}".encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @classmethod
    def decode(cls, token: str) -> InboxCursor:
        try:
            padded = token + "=" * (-len(token) % 4)
            at_text, _, id_text = base64.urlsafe_b64decode(padded).decode().partition("|")
            at = datetime.fromisoformat(at_text) if at_text else None
            if at is not None and at.tzinfo is None:
                raise ValueError("naive instant")
            return cls(last_message_at=at, thread_id=UUID(id_text))
        except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
            raise InvalidCursor("not an inbox cursor") from exc


@dataclass(frozen=True)
class InboxRow:
    """One chat, as a row of the unified list needs it.

    `counterpart_*` are display fields only (an Instagram IGSID is never exposed: it is
    not a portable identity); `counterpart_phone` is the WhatsApp `wa_id`. The newest
    message is `last_message_*` (`last_message_kind`: the media type, or the outbound
    payload type on WhatsApp; `None` for plain text). `awaiting_reply` is the
    «Por responder» rule; `unread` is set only where the channel tracks reads (Instagram:
    `last_read_at`), `None` elsewhere. `window_*` is the 24 h window from
    `last_inbound_at`. WhatsApp-only, `None` on other channels: `automation_paused` (the
    chat is in a person's hands) and `payment_status` (`whatsapp.payment_status`).
    """

    thread_id: UUID
    channel: str
    connection_id: UUID
    status: str
    counterpart_name: str | None
    counterpart_username: str | None
    counterpart_avatar_url: str | None
    counterpart_phone: str | None
    last_message_at: datetime | None
    last_inbound_at: datetime | None
    last_message_text: str | None
    last_message_kind: str | None
    last_message_direction: str | None
    awaiting_reply: bool
    unread: bool | None
    window_open: bool
    window_closes_at: datetime | None
    automation_paused: bool | None
    payment_status: str | None

    @property
    def cursor(self) -> InboxCursor:
        return InboxCursor(last_message_at=self.last_message_at, thread_id=self.thread_id)


@dataclass(frozen=True)
class InboxPage:
    rows: tuple[InboxRow, ...]
    next_cursor: InboxCursor | None


class InboxReader(Protocol):
    """The read seam (Postgres in production, a fake in offline tests)."""

    def list_page(
        self,
        tenant_id: UUID,
        *,
        filter: InboxFilter,
        channels: Sequence[str],
        cursor: InboxCursor | None,
        limit: int,
        now: datetime,
    ) -> InboxPage: ...

    def count(
        self, tenant_id: UUID, *, filter: InboxFilter, channels: Sequence[str], now: datetime
    ) -> int: ...


# --------------------------------------------------------------------------------------
# Postgres
# --------------------------------------------------------------------------------------

# The page is chosen FIRST, on `threads` alone, in the index's order: a backward scan of
# `ix_thread_inbox_order (tenant_id, last_message_at)` gives `last_message_at DESC` (the
# RLS tenant qual is its index condition), an Incremental Sort adds the `id DESC`
# tie-break, and LIMIT stops the scan as soon as the page is full. Chats with no
# `last_message_at` sort last; they are a second, `id DESC` branch. The page carries the
# thread columns the row needs (no join back to `threads`), and only then do the
# per-chat joins (newest message, WhatsApp state, the rule as a column) run, for the
# page's rows only. With `por_responder` the rule is the page's filter, evaluated chat by
# chat in that order until the page is full.
_PAGE_DATED: Final = """
  (SELECT t.id, t.channel, t.connection_id, t.status, t.last_message_at, t.last_inbound_at,
          t.last_read_at, t.external_thread_id, t.counterpart_name, t.counterpart_username,
          t.counterpart_avatar_url
     FROM threads t
    WHERE t.channel = ANY(:channels) AND t.last_message_at IS NOT NULL
      AND {filter} {after}
    ORDER BY t.last_message_at DESC, t.id DESC
    LIMIT :limit)"""

_PAGE_UNDATED: Final = """
  (SELECT t.id, t.channel, t.connection_id, t.status, t.last_message_at, t.last_inbound_at,
          t.last_read_at, t.external_thread_id, t.counterpart_name, t.counterpart_username,
          t.counterpart_avatar_url
     FROM threads t
    WHERE t.channel = ANY(:channels) AND t.last_message_at IS NULL
      AND {filter} {after}
    ORDER BY t.id DESC
    LIMIT :limit)"""

_SELECT: Final = """
WITH page AS MATERIALIZED ({page})
SELECT t.id, t.channel, t.connection_id, t.status, t.last_message_at, t.last_inbound_at,
       t.counterpart_username, t.counterpart_avatar_url,
       COALESCE(t.counterpart_name,
                CASE WHEN t.channel = '{whatsapp}' THEN (
                  SELECT n.author_username
                    FROM messages n
                   WHERE n.thread_id = t.id AND n.direction = 'inbound'
                     AND n.author_username IS NOT NULL AND n.deleted_at IS NULL
                   ORDER BY {n_instant} DESC, n.id DESC
                   LIMIT 1) END) AS counterpart_name,
       CASE WHEN t.channel = '{whatsapp}' THEN t.external_thread_id END AS counterpart_phone,
       CASE WHEN t.channel = '{dm}' THEN
              t.last_inbound_at IS NOT NULL
              AND (t.last_read_at IS NULL OR t.last_read_at < t.last_inbound_at)
       END AS unread,
       CASE WHEN t.channel = '{whatsapp}' THEN s.automation_paused_at IS NOT NULL
       END AS automation_paused,
       CASE WHEN t.channel = '{whatsapp}' THEN s.context->'_payment'->>'status'
       END AS payment_status,
       lm.text AS last_text, lm.direction AS last_direction, lm.kind AS last_kind,
       {awaiting} AS awaiting_reply
  FROM page t
  LEFT JOIN whatsapp_thread_state s ON s.thread_id = t.id
  LEFT JOIN LATERAL (
        SELECT m.text, m.direction,
               CASE WHEN m.direction = 'outbound' THEN ob.payload->>'type'
                    ELSE m.media_type END AS kind
          FROM messages m
          LEFT JOIN whatsapp_outbox ob
                 ON m.direction = 'outbound'
                AND ob.thread_id = m.thread_id
                AND ob.wamid = m.external_message_id
         WHERE m.thread_id = t.id AND m.deleted_at IS NULL
         ORDER BY {m_instant} DESC, m.id DESC
         LIMIT 1) lm ON true
 ORDER BY t.last_message_at DESC NULLS LAST, t.id DESC
 LIMIT :limit
"""

_COUNT: Final = """
SELECT count(*)
  FROM threads t
 WHERE t.channel = ANY(:channels) AND {filter}
"""

# Strictly after the cursor in `last_message_at DESC NULLS LAST, id DESC`: inside the
# dated branch for a dated cursor; inside the undated branch for an undated one (every
# undated chat is after every dated one, so a dated cursor leaves that branch whole).
_AFTER_DATED: Final = "AND (t.last_message_at < :at OR (t.last_message_at = :at AND t.id < :id))"
_AFTER_UNDATED: Final = "AND t.id < :id"


def _filter_sql(filter: str) -> str:
    try:
        rule = _FILTER_SQL[filter]
    except KeyError:
        raise ValueError(f"filter must be one of {INBOX_FILTERS}, not {filter!r}") from None
    return awaiting_reply_sql("t", now_param=_NOW_PARAM) if rule == _RULE else rule


def _page_sql(filter: str, cursor: InboxCursor | None) -> str:
    where = _filter_sql(filter)
    undated_cursor = cursor is not None and cursor.last_message_at is None
    undated = _PAGE_UNDATED.format(filter=where, after=_AFTER_UNDATED if undated_cursor else "")
    if undated_cursor:
        return undated
    dated = _PAGE_DATED.format(filter=where, after=_AFTER_DATED if cursor is not None else "")
    return f"{dated}\n  UNION ALL{undated}"


def _list_sql(filter: str, cursor: InboxCursor | None) -> str:
    return _SELECT.format(
        page=_page_sql(filter, cursor),
        whatsapp=CHANNEL_WHATSAPP,
        dm=CHANNEL_INSTAGRAM_DM,
        n_instant=_INSTANT.format(m="n"),
        m_instant=_INSTANT.format(m="m"),
        # Under `por_responder` the page already holds only waiting chats.
        awaiting="TRUE"
        if filter == "por_responder"
        else awaiting_reply_sql("t", now_param=_NOW_PARAM),
    )


def _count_sql(filter: str) -> str:
    return _COUNT.format(filter=_filter_sql(filter))


def _row(r: Any, now: datetime) -> InboxRow:
    window = window_state(r.last_inbound_at, now)
    return InboxRow(
        thread_id=r.id,
        channel=r.channel,
        connection_id=r.connection_id,
        status=r.status,
        counterpart_name=r.counterpart_name,
        counterpart_username=r.counterpart_username,
        counterpart_avatar_url=r.counterpart_avatar_url,
        counterpart_phone=r.counterpart_phone,
        last_message_at=r.last_message_at,
        last_inbound_at=r.last_inbound_at,
        last_message_text=r.last_text,
        last_message_kind=r.last_kind,
        last_message_direction=r.last_direction,
        awaiting_reply=bool(r.awaiting_reply),
        unread=r.unread,
        window_open=window.is_open,
        window_closes_at=window.closes_at,
        automation_paused=r.automation_paused,
        payment_status=r.payment_status,
    )


class PostgresInboxReader:
    """One `tenant_session` and one statement per call (`qualify_app`: SELECT on
    `threads`, `messages`, `whatsapp_thread_state`, `whatsapp_outbox`)."""

    def list_page(
        self,
        tenant_id: UUID,
        *,
        filter: InboxFilter,
        channels: Sequence[str],
        cursor: InboxCursor | None,
        limit: int,
        now: datetime,
    ) -> InboxPage:
        params: dict[str, Any] = {"channels": list(channels), "limit": limit + 1, "now": now}
        if cursor is not None:
            params["id"] = cursor.thread_id
            if cursor.last_message_at is not None:
                params["at"] = cursor.last_message_at
        sql = text(_list_sql(filter, cursor))
        with tenant_session(tenant_id) as session:
            records = session.execute(sql, params).all()
        rows = tuple(_row(r, now) for r in records[:limit])
        next_cursor = rows[-1].cursor if len(records) > limit and rows else None
        return InboxPage(rows=rows, next_cursor=next_cursor)

    def count(
        self, tenant_id: UUID, *, filter: InboxFilter, channels: Sequence[str], now: datetime
    ) -> int:
        params = {"channels": list(channels), "now": now}
        with tenant_session(tenant_id) as session:
            value = session.execute(text(_count_sql(filter)), params)
            return int(value.scalar_one() or 0)


# --------------------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------------------


def _aware_now(now: datetime | None) -> datetime:
    """The instant the rule and the rows' window are judged at. A naive `now` is refused:
    SQL would read it in the session's time zone and `window_state` as UTC."""
    if now is None:
        return datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return now


def list_inbox(
    tenant_id: UUID,
    *,
    filter: InboxFilter = "por_responder",
    channel: str | None = None,
    cursor: InboxCursor | str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    now: datetime | None = None,
    reader: InboxReader | None = None,
) -> InboxPage:
    """One page of the tenant's chats across channels, newest activity first.

    `channel` narrows to one allow-listed channel (`UnknownChannel` otherwise); `cursor`
    is the previous page's `next_cursor` (or its `encode()`d token). Blocking (one DB
    round trip): call it off the event loop (`asyncio.to_thread`)."""
    _filter_sql(filter)
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
    channels = resolve_channels(channel)
    if isinstance(cursor, str):
        cursor = InboxCursor.decode(cursor)
    return (reader or PostgresInboxReader()).list_page(
        tenant_id,
        filter=filter,
        channels=channels,
        cursor=cursor,
        limit=limit,
        now=_aware_now(now),
    )


def count_inbox(
    tenant_id: UUID,
    *,
    filter: InboxFilter = "por_responder",
    channel: str | None = None,
    now: datetime | None = None,
    reader: InboxReader | None = None,
) -> int:
    """How many chats the same filter lists (all pages), judged at `now` (default: the
    wall clock) like `list_inbox`. Blocking: one DB round trip."""
    _filter_sql(filter)
    channels = resolve_channels(channel)
    return (reader or PostgresInboxReader()).count(
        tenant_id, filter=filter, channels=channels, now=_aware_now(now)
    )

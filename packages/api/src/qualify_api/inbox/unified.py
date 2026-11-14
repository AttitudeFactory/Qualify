"""The unified chat inbox: one read over every chat channel (m-25017843, BU-A1).

`docs/arquitectura-bandeja-unica.md` §2.2, option C: the inbox converges the READ, not the
writes. One statement over `threads` lists the tenant's chats of every allow-listed channel
(`inbox.channels.INBOX_CHANNELS`: Instagram Direct `dm` and `whatsapp`; never `comment`),
newest activity first, one page per database round trip. Sending, outboxes, workers and
ingestion stay per channel; this module writes nothing.

**Wired with the counters** (m-25017859): the menu counters (`attention.counts`) and
Inicio (`home.summary`) count with the same `inbox.awaiting` fragment this list filters
by, so a number the owner taps is the length of the list it opens.

**Filters** (`INBOX_FILTERS`). `por_responder` — the single rule of `inbox.awaiting`,
judged at the caller's `now` (an Instagram chat counts only while its reply window is
open); `todos` — every open chat, so an Instagram chat whose window closed still shows
there (`awaiting_reply` and `window_open` false); `cerrados` — closed (neither lists an
Instagram chat whose every message was unsent: the Instagram screen hides it too);
`pago_por_revisar` — WhatsApp chats, open or closed, whose payment waits for the owner's
check («Pago por revisar · N», the WhatsApp screen's own definition);
`ventana_vencida` — open Instagram chats whose window closed without a reply from a
person, the window having closed within the last
`expired_within` (default `EXPIRED_UNANSWERED_WITHIN`; the rule is
`inbox.awaiting.expired_unanswered_sql`).
An optional channel narrows to one allow-listed channel (`UnknownChannel` otherwise).

**For the screens** (the Reflex providers call these in-process, off the event loop):
`list_inbox` (one page), `count_inbox` (one filter), `inbox_counts` (every filter per
channel in ONE statement — the chips, the channel filter, the expired notice),
`count_expired_unanswered` (the notice alone). Each is one database round trip.

**Order and pages.** `last_message_at DESC NULLS LAST, id DESC` with a composite keyset
cursor `(last_message_at, id)` — two chats with the same instant are both returned, the
`before`-only paging of `whatsapp.chats` could skip one. The page reads `limit + 1` rows to
know whether another page exists.

**One statement per page, page first.** A MATERIALIZED `page` CTE picks the page's rows
on `threads` alone in index order (see `_PAGE_DATED`); then, for those rows only, the
newest message comes from a `LEFT JOIN LATERAL`, the WhatsApp-only state
(`whatsapp_thread_state`: the owner's hand-over, the payment record) from a `LEFT JOIN`
that is NULL on Instagram, the outbound media kind from the matching `whatsapp_outbox`
row, and the rule's two verdicts (`awaiting_reply`, `window_expired_unanswered`) as
columns. No per-thread round trip.

**Tenant isolation.** Only `tenant_session(tenant_id)`: RLS scopes every table read here;
no tenant column is filtered by hand. Channels are bound as a parameter from the
allow-list, never interpolated.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any, Final, Literal, Protocol, get_args
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.conversations.repository import NOT_ONLY_UNSENT_SQL
from qualify_api.inbox.awaiting import awaiting_reply_sql, expired_unanswered_sql
from qualify_api.inbox.channels import (
    CHANNEL_INSTAGRAM_DM,
    CHANNEL_WHATSAPP,
    INBOX_CHANNELS,
    resolve_channels,
)
from qualify_api.whatsapp.window import WINDOW, window_state

InboxFilter = Literal["por_responder", "todos", "cerrados", "pago_por_revisar", "ventana_vencida"]
INBOX_FILTERS: Final[tuple[str, ...]] = get_args(InboxFilter)

DEFAULT_PAGE_SIZE: Final = 50
MAX_PAGE_SIZE: Final = 100

#: How long after an Instagram chat's window closed without an answer it is still worth
#: telling the owner about (`ventana_vencida`, `count_expired_unanswered`). ASSUMPTION of
#: m-25017859, not a founder decision: 7 days, the same «this week» Inicio uses.
EXPIRED_UNANSWERED_WITHIN: Final = timedelta(days=7)

#: `whatsapp.payment_status` statuses the row's pill reads (`STATUS_REVIEW`,
#: `STATUS_AWAITING`), stored in `whatsapp_thread_state.context->'_payment'`.
PAYMENT_REVIEW: Final = "review"
PAYMENT_AWAITING: Final = "awaiting"

_INSTANT: Final = "COALESCE({m}.posted_at, {m}.ingested_at)"
# The rule's «now» is bound, not the database's `now()`: the list, the count, the rows'
# `window_*` and the Python twin all judge the same instant (`now=`).
_NOW_PARAM: Final = "now"

_AWAITING_SQL: Final = awaiting_reply_sql("t", now_param=_NOW_PARAM)
_EXPIRED_SQL: Final = expired_unanswered_sql("t", now_param=_NOW_PARAM)

# A chat a screen can open (m-25017859): the Instagram list hides a chat whose every
# message the person unsent (m-25018661), so the unified list and its counts hide it
# too, with that list's OWN predicate. The rule (`por_responder`, `ventana_vencida`)
# cannot count such a chat anyway: an unsent message is also `deleted_at`, so it has no
# visible inbound; only `todos` and `cerrados` need the clause. WhatsApp has no unsends.
_VISIBLE_SQL: Final = f"(t.channel <> '{CHANNEL_INSTAGRAM_DM}' OR {NOT_ONLY_UNSENT_SQL})"

# What each filter keeps, over the `threads` row `t`. Each reads only `t` and correlated
# subqueries, so the SAME text filters the page, `count_inbox` and `inbox_counts`.
_FILTER_SQL: Final[Mapping[str, str]] = MappingProxyType(
    {
        "por_responder": _AWAITING_SQL,
        "todos": f"t.status = 'open' AND {_VISIBLE_SQL}",
        "cerrados": f"t.status = 'closed' AND {_VISIBLE_SQL}",
        # The WhatsApp screen's own «Pago por revisar» (`whatsapp_chats_vm.filter_threads`):
        # every WhatsApp chat, OPEN OR CLOSED, whose payment waits for the owner's check
        # (`_payment.status = 'review'`) — closing a chat does not settle its payment.
        "pago_por_revisar": (
            f"(t.channel = '{CHANNEL_WHATSAPP}' AND EXISTS ("
            "SELECT 1 FROM whatsapp_thread_state ps WHERE ps.thread_id = t.id "
            f"AND ps.context->'_payment'->>'status' = '{PAYMENT_REVIEW}'))"
        ),
        # Window closed within `expired_within`: `last_inbound_at + WINDOW > now - within`.
        "ventana_vencida": (
            f"(t.last_inbound_at > CAST(:expired_since AS timestamptz) AND {_EXPIRED_SQL})"
        ),
    }
)


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
    """One chat, as a row of the unified list needs it (`Qualify/chat_row_vm.ChatRowVM`).

    To open it: `thread_id` + `channel` (+ `connection_id`, the account). Title:
    `counterpart_name`, else `@counterpart_username`, else `counterpart_phone`, else
    «Cliente de …» (an Instagram IGSID is never exposed: it is not a portable identity;
    `counterpart_phone` is the WhatsApp `wa_id`). Picture: `counterpart_avatar_url`
    (Instagram only today). Preview: `last_message_*` — `last_message_kind` is the media
    type, or the outbound payload type on WhatsApp, `None` for plain text;
    `last_message_direction == 'outbound'` is «Tú: ». Time: `last_message_at`.

    `awaiting_reply` is the «Por responder» rule (the waiting dot); `unread` is set only
    where the channel tracks reads (Instagram: `last_read_at`), `None` elsewhere.
    `window_*` is the 24 h window from `last_inbound_at` (`window_closes_at` only while
    open — «Quedan N min»). `window_expired_unanswered`: an Instagram chat whose window
    closed while the customer still had the last word (`inbox.awaiting`), closed at
    `window_expired_at`; never set on WhatsApp. `assigned_agent_id`: the member who
    attends it (`threads.assigned_agent_id`; the screen maps it to a name and initials).
    WhatsApp-only, `None` on other channels: `automation_paused` (the chat is in a
    person's hands) and `payment_status` (`whatsapp.payment_status`; the pills read
    `payment_review` / `payment_awaiting`).
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
    # m-25017859 — optional so a row built by hand (fakes, the UI's tests) still works.
    assigned_agent_id: UUID | None = None
    window_expired_unanswered: bool = False
    window_expired_at: datetime | None = None

    @property
    def cursor(self) -> InboxCursor:
        return InboxCursor(last_message_at=self.last_message_at, thread_id=self.thread_id)

    @property
    def is_closed(self) -> bool:
        return self.status == "closed"

    @property
    def payment_review(self) -> bool:
        """«Pago por revisar»: the customer sent a receipt the owner has not checked."""
        return self.payment_status == PAYMENT_REVIEW

    @property
    def payment_awaiting(self) -> bool:
        """«Esperando el pago»: the payment card went out, nothing came back yet."""
        return self.payment_status == PAYMENT_AWAITING


@dataclass(frozen=True)
class InboxPage:
    rows: tuple[InboxRow, ...]
    next_cursor: InboxCursor | None


@dataclass(frozen=True)
class InboxCounts:
    """How many chats each filter lists, per channel (`by_channel[channel][filter]`);
    every allow-listed channel and filter is present, 0 when empty. `count(filter)` is
    the total over channels — exactly what `count_inbox(filter=…)` returns."""

    by_channel: Mapping[str, Mapping[str, int]]

    def count(self, filter: InboxFilter, channel: str | None = None) -> int:
        _filter_sql(filter)
        channels = resolve_channels(channel)
        return sum(self.by_channel.get(c, {}).get(filter, 0) for c in channels)

    @property
    def por_responder(self) -> int:
        return self.count("por_responder")

    @property
    def expired_unanswered(self) -> int:
        return self.count("ventana_vencida")

    @property
    def payment_review(self) -> int:
        return self.count("pago_por_revisar")


class InboxReader(Protocol):
    """The read seam (Postgres in production, a fake in offline tests). `expired_since`
    is the lower bound of `ventana_vencida` (`now - expired_within - WINDOW`)."""

    def list_page(
        self,
        tenant_id: UUID,
        *,
        filter: InboxFilter,
        channels: Sequence[str],
        cursor: InboxCursor | None,
        limit: int,
        now: datetime,
        expired_since: datetime,
    ) -> InboxPage: ...

    def count(
        self,
        tenant_id: UUID,
        *,
        filter: InboxFilter,
        channels: Sequence[str],
        now: datetime,
        expired_since: datetime,
    ) -> int: ...

    def counts(
        self, tenant_id: UUID, *, channels: Sequence[str], now: datetime, expired_since: datetime
    ) -> InboxCounts: ...


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
_PAGE_COLUMNS: Final = """t.id, t.channel, t.connection_id, t.status, t.last_message_at,
          t.last_inbound_at, t.last_read_at, t.external_thread_id, t.counterpart_name,
          t.counterpart_username, t.counterpart_avatar_url, t.assigned_agent_id"""

_PAGE_DATED: Final = f"""
  (SELECT {_PAGE_COLUMNS}
     FROM threads t
    WHERE t.channel = ANY(:channels) AND t.last_message_at IS NOT NULL
      AND {{filter}} {{after}}
    ORDER BY t.last_message_at DESC, t.id DESC
    LIMIT :limit)"""

_PAGE_UNDATED: Final = f"""
  (SELECT {_PAGE_COLUMNS}
     FROM threads t
    WHERE t.channel = ANY(:channels) AND t.last_message_at IS NULL
      AND {{filter}} {{after}}
    ORDER BY t.id DESC
    LIMIT :limit)"""

_SELECT: Final = """
WITH page AS MATERIALIZED ({page})
SELECT t.id, t.channel, t.connection_id, t.status, t.last_message_at, t.last_inbound_at,
       t.counterpart_username, t.counterpart_avatar_url, t.assigned_agent_id,
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
       {awaiting} AS awaiting_reply,
       {expired} AS window_expired_unanswered
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

# Every filter's count per channel in ONE statement: one `_COUNT` branch per filter,
# grouped by channel, glued with UNION ALL. Each branch is the filter's own text in a
# WHERE (`_FILTER_SQL`), so `InboxCounts.count(f)` and `count_inbox(filter=f)` are the
# same number by construction — and planned the same way: in a WHERE the rule's EXISTS
# becomes a join, whereas a single scan with `count(*) FILTER (WHERE …)` per filter keeps
# it a per-row subplan (measured 5x slower on 3,000 chats).
#: `inbox_counts` and the menu counters (`attention.counts`) are polled per open tab; JIT
#: compilation of these short, wide statements dominated their time. Transaction-local.
NO_JIT_SQL: Final = "SET LOCAL jit = off"
_NO_JIT: Final = text(NO_JIT_SQL)

_COUNTS_BRANCH: Final = """
SELECT '{name}' AS filter, t.channel, count(*) AS n
  FROM threads t
 WHERE t.channel = ANY(:channels) AND {filter}
 GROUP BY t.channel"""

# Strictly after the cursor in `last_message_at DESC NULLS LAST, id DESC`: inside the
# dated branch for a dated cursor; inside the undated branch for an undated one (every
# undated chat is after every dated one, so a dated cursor leaves that branch whole).
_AFTER_DATED: Final = "AND (t.last_message_at < :at OR (t.last_message_at = :at AND t.id < :id))"
_AFTER_UNDATED: Final = "AND t.id < :id"


def _filter_sql(filter: str) -> str:
    try:
        return _FILTER_SQL[filter]
    except KeyError:
        raise ValueError(f"filter must be one of {INBOX_FILTERS}, not {filter!r}") from None


def _page_sql(filter: str, cursor: InboxCursor | None) -> str:
    where = _filter_sql(filter)
    undated_cursor = cursor is not None and cursor.last_message_at is None
    undated = _PAGE_UNDATED.format(filter=where, after=_AFTER_UNDATED if undated_cursor else "")
    if undated_cursor:
        return undated
    dated = _PAGE_DATED.format(filter=where, after=_AFTER_DATED if cursor is not None else "")
    return f"{dated}\n  UNION ALL{undated}"


def _list_sql(filter: str, cursor: InboxCursor | None) -> str:
    # A filter that already decides a verdict does not evaluate it again per row: under
    # `por_responder` every row waits and none is expired (the window is open); under
    # `ventana_vencida` every row is expired and none waits.
    awaiting = {"por_responder": "TRUE", "ventana_vencida": "FALSE"}.get(filter, _AWAITING_SQL)
    expired = {"por_responder": "FALSE", "ventana_vencida": "TRUE"}.get(filter, _EXPIRED_SQL)
    return _SELECT.format(
        page=_page_sql(filter, cursor),
        whatsapp=CHANNEL_WHATSAPP,
        dm=CHANNEL_INSTAGRAM_DM,
        n_instant=_INSTANT.format(m="n"),
        m_instant=_INSTANT.format(m="m"),
        awaiting=awaiting,
        expired=expired,
    )


def _count_sql(filter: str) -> str:
    return _COUNT.format(filter=_filter_sql(filter))


def _counts_sql() -> str:
    return "\nUNION ALL".join(
        _COUNTS_BRANCH.format(name=f, filter=_FILTER_SQL[f]) for f in INBOX_FILTERS
    )


def _window_expired_at(r: Any) -> datetime | None:
    if not r.window_expired_unanswered or r.last_inbound_at is None:
        return None
    return r.last_inbound_at + WINDOW


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
        assigned_agent_id=r.assigned_agent_id,
        window_expired_unanswered=bool(r.window_expired_unanswered),
        window_expired_at=_window_expired_at(r),
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
        expired_since: datetime,
    ) -> InboxPage:
        params: dict[str, Any] = {
            "channels": list(channels),
            "limit": limit + 1,
            "now": now,
            "expired_since": expired_since,
        }
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
        self,
        tenant_id: UUID,
        *,
        filter: InboxFilter,
        channels: Sequence[str],
        now: datetime,
        expired_since: datetime,
    ) -> int:
        params = {"channels": list(channels), "now": now, "expired_since": expired_since}
        with tenant_session(tenant_id) as session:
            value = session.execute(text(_count_sql(filter)), params)
            return int(value.scalar_one() or 0)

    def counts(
        self, tenant_id: UUID, *, channels: Sequence[str], now: datetime, expired_since: datetime
    ) -> InboxCounts:
        params = {"channels": list(channels), "now": now, "expired_since": expired_since}
        with tenant_session(tenant_id) as session:
            # The UNION's summed cost crosses `jit_above_cost`, and compiling it costs far
            # more than running it (measured ~900 ms → ~50 ms on 3,000 chats); scoped to
            # this transaction only.
            session.execute(_NO_JIT)
            records = session.execute(text(_counts_sql()), params).all()
        found = {(r.filter, r.channel): int(r.n or 0) for r in records}
        return InboxCounts(
            by_channel=MappingProxyType(
                {
                    c: MappingProxyType({f: found.get((f, c), 0) for f in INBOX_FILTERS})
                    for c in channels
                }
            )
        )


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


def _expired_since(now: datetime, within: timedelta) -> datetime:
    """`ventana_vencida`'s bound on `last_inbound_at`: the window (`last_inbound_at +
    WINDOW`) closed less than `within` before `now`."""
    if within <= timedelta(0):
        raise ValueError("expired_within must be positive")
    return now - within - WINDOW


def list_inbox(
    tenant_id: UUID,
    *,
    filter: InboxFilter = "por_responder",
    channel: str | None = None,
    cursor: InboxCursor | str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    now: datetime | None = None,
    expired_within: timedelta = EXPIRED_UNANSWERED_WITHIN,
    reader: InboxReader | None = None,
) -> InboxPage:
    """One page of the tenant's chats across channels, newest activity first.

    `channel` narrows to one allow-listed channel (`UnknownChannel` otherwise); `cursor`
    is the previous page's `next_cursor` (or its `encode()`d token); `expired_within`
    bounds `ventana_vencida` only. Blocking (one DB round trip): call it off the event
    loop (`asyncio.to_thread`)."""
    _filter_sql(filter)
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
    channels = resolve_channels(channel)
    if isinstance(cursor, str):
        cursor = InboxCursor.decode(cursor)
    moment = _aware_now(now)
    return (reader or PostgresInboxReader()).list_page(
        tenant_id,
        filter=filter,
        channels=channels,
        cursor=cursor,
        limit=limit,
        now=moment,
        expired_since=_expired_since(moment, expired_within),
    )


def count_inbox(
    tenant_id: UUID,
    *,
    filter: InboxFilter = "por_responder",
    channel: str | None = None,
    now: datetime | None = None,
    expired_within: timedelta = EXPIRED_UNANSWERED_WITHIN,
    reader: InboxReader | None = None,
) -> int:
    """How many chats the same filter lists (all pages), judged at `now` (default: the
    wall clock) like `list_inbox`. Blocking: one DB round trip."""
    _filter_sql(filter)
    channels = resolve_channels(channel)
    moment = _aware_now(now)
    return (reader or PostgresInboxReader()).count(
        tenant_id,
        filter=filter,
        channels=channels,
        now=moment,
        expired_since=_expired_since(moment, expired_within),
    )


def inbox_counts(
    tenant_id: UUID,
    *,
    now: datetime | None = None,
    expired_within: timedelta = EXPIRED_UNANSWERED_WITHIN,
    reader: InboxReader | None = None,
) -> InboxCounts:
    """Every filter's count for every chat channel, in ONE statement: the filter chips
    («Por responder · N», «Pago por revisar · N»), the channel filter and the expired
    notice of one screen refresh. `.count(f, channel)` equals `count_inbox(filter=f,
    channel=channel)`. Blocking: one DB round trip."""
    moment = _aware_now(now)
    return (reader or PostgresInboxReader()).counts(
        tenant_id,
        channels=INBOX_CHANNELS,
        now=moment,
        expired_since=_expired_since(moment, expired_within),
    )


def count_expired_unanswered(
    tenant_id: UUID,
    *,
    within: timedelta = EXPIRED_UNANSWERED_WITHIN,
    now: datetime | None = None,
    reader: InboxReader | None = None,
) -> int:
    """How many Instagram chats left «Por responder» because their window closed — less
    than `within` ago — while the customer still had the last word (`ventana_vencida`).
    The «tell the owner once» memory is the screen's; this only counts. Blocking: one DB
    round trip."""
    return count_inbox(
        tenant_id,
        filter="ventana_vencida",
        now=now,
        expired_within=within,
        reader=reader,
    )

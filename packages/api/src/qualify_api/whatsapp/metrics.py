"""Conversation metrics of one WhatsApp number, computed from our own tables (WA-17,
QUA-216).

Backlog: `docs/backlog-modulo-whatsapp.md` §4 WA-17 — «contadores por entrada (hilos
abiertos por primer mensaje), pedidos confirmados por el menú, handoffs y tiempo medio
hasta la primera respuesta humana. Sin tablas nuevas: consultas sobre `threads`/
`messages`/`whatsapp_thread_state`». The HTTP surface is `GET /api/whatsapp/metrics`
(`http/whatsapp_routes.py`); the UI tab that renders it is a later story.

## Shape of the module

`MetricsRepository` loads plain rows (`MetricsRows`) for ONE connection and a range;
`aggregate` is a pure function from those rows to `ConversationMetrics`. The Postgres
repository runs under `tenant_session(tenant_id)` (`qualify_app`: SELECT on every table
read here — 0002/0004/0057/0058), so RLS bounds every statement and another tenant's
connection reads as missing (`ConnectionNotFound`, the route's 404).

All instants are a message's `COALESCE(posted_at, ingested_at)` — the same "instant" the
chats API pages on — and every range is half-open, `[since, until)`.

## Definitions (each one is what the field means, exactly)

- **`threads_opened`** — threads of the connection whose FIRST inbound message ever has
  its instant in range. A conversation that started last month and continues today is
  not "opened" today.
- **`threads_opened_by_entry`** — those same threads, classified by the text of that
  first inbound message against the entry points of the number's CURRENTLY published
  menu (`EntryConfig`), in this order, first match wins:
    1. `command` — text starting with `/` whose first word matches a menu command;
    2. `ice_breaker` — normalized text equal to an ice breaker's text;
    3. `qr` — normalized text starting with a QR code's normalized prefilled message
       (`qr_prefixes`, label → prefix, injected; the longest matching prefix wins);
    4. `keyword` — normalized text equal to an `entry.keywords` key;
    5. `directo` — anything else, including a first message with no text (media).
  Normalization is the menus' own `normalize_keyword` (case- and accent-insensitive), so
  "metrics say it came from X" and "the engine routed it as X" use one rule. QR comes
  before keyword on purpose: the backlog maps each QR's prefilled text to a keyword so
  the channel opens the right node — the same text is BOTH, and the channel is the more
  specific attribution. Known limit: the menu used is the one published NOW; a thread
  that entered through a keyword since removed counts as `directo`.
- **`orders_confirmed`** / **`orders_total`** — threads whose `context["_order"]`
  (WA-15, read with `orders.read_order`) has `confirmed_at` in range; totals summed per
  currency (`"XXX"`, ISO 4217's "no currency", when the order carries none). Known
  limit: `_order` holds the thread's CURRENT order only, so a thread that confirmed two
  orders counts the latest one.
- **`handoffs`** / **`handoffs_by_reason`** — threads whose `context["_handoff"]["at"]`
  is in range, split by `reason`. Same limit: `_handoff` is the latest handoff only.
- **`messages_in`** — inbound messages in range.
- **`messages_out_automation` / `_human` / `_campaign` / `_other`** — outbound messages in
  range, split by the `kind` of the `whatsapp_outbox` row that produced them (joined on
  `(connection_id, wamid)`, the chats API's join): `automation`, `reply` (a person),
  `campaign_send`, and no outbox row at all (`_other`).
- **`delivery_failed`** — outbound messages in range whose `delivery_status` is
  `failed` (Meta accepted the send, the status webhook later reported failure).
  **`send_failed`** — `whatsapp_outbox` rows created in range that ended `failed` or
  `dead` (never accepted by Meta, so they have no `messages` row to count).

## First human response — how the pairs are formed

One pair at most per thread, built from a START instant and a RESPONSE instant:

- **START**
  - thread with a `_handoff` whose `at` is in range: the instant of the last inbound
    message at or before `_handoff.at` — the message whose processing triggered the
    handoff (the handler stamps `at` with its own clock while processing it, so the
    customer has been waiting since that message, not since the stamp). If no such
    message is loaded, `_handoff.at` itself.
  - thread NEVER automated (`whatsapp_thread_state.menu_version_id IS NULL`, i.e. no
    menu ever ran on it): the first inbound message of the thread, if it is in range.
  - an automated thread with no handoff in range: no pair. A person who steps into a
    conversation the menu was handling did not answer a wait; that is a takeover.
- **RESPONSE** — the first outbound message whose outbox row has `kind = 'reply'` with
  instant ≥ START. Messages are loaded up to `until + RESPONSE_HORIZON` so a wait that
  starts just before `until` can still be answered after it; the horizon is the 24 h
  window, past which a free-form reply cannot be sent anyway.
- A START with no RESPONSE counts in `awaiting_human_response`, not in the statistics.

`median_first_human_response_seconds` is the median of the pairs' durations;
`p90_first_human_response_seconds` is the nearest-rank 90th percentile
(`sorted[ceil(0.9 · n) − 1]`). Both are `None` with no pairs.
"""

from __future__ import annotations

import logging
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Literal, Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.whatsapp.menus.schema import EntryConfig, MenuDefinition, normalize_keyword
from qualify_api.whatsapp.orders import read_order
from qualify_api.whatsapp.window import WINDOW

_LOGGER = logging.getLogger("qualify_api.whatsapp.metrics")

DEFAULT_RANGE: Final = timedelta(days=7)
MAX_RANGE: Final = timedelta(days=366)
RESPONSE_HORIZON: Final = WINDOW
NO_CURRENCY: Final = "XXX"
CTX_HANDOFF: Final = "_handoff"  # mirrors handler.CTX_HANDOFF (not imported: import cost)

EntryKind = Literal["command", "ice_breaker", "qr", "keyword", "directo"]
Sender = Literal["inbound", "automation", "human", "campaign", "other"]

# `whatsapp_outbox.kind` → who sent an outbound message.
_SENDER_BY_KIND: Final[dict[str, Sender]] = {
    "automation": "automation",
    "reply": "human",
    "campaign_send": "campaign",
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """Query strings may carry a naive instant; it is taken as UTC, never compared
    against an aware one (which would raise)."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


# ======================================================================================
# Errors
# ======================================================================================


class ConnectionNotFound(LookupError):
    """No WhatsApp connection with this id for this tenant (another tenant's included —
    RLS makes the two indistinguishable, and the route keeps it that way: 404)."""


class InvalidRange(ValueError):
    """`since >= until`, or a range longer than `MAX_RANGE`."""


def resolve_range(
    since: datetime | None,
    until: datetime | None,
    now: datetime,
    *,
    default: timedelta = DEFAULT_RANGE,
    maximum: timedelta = MAX_RANGE,
) -> tuple[datetime, datetime]:
    """`[since, until)` with defaults: `until` = now, `since` = until − `default`."""
    until_ = as_utc(until) if until is not None else as_utc(now)
    since_ = as_utc(since) if since is not None else until_ - default
    if since_ >= until_:
        raise InvalidRange("since must be before until")
    if until_ - since_ > maximum:
        raise InvalidRange(f"range must not exceed {maximum.days} days")
    return since_, until_


# ======================================================================================
# Rows (what the repository returns)
# ======================================================================================


@dataclass(frozen=True)
class ThreadFact:
    """One thread with activity in the loaded window. `first_inbound_*` are the thread's
    first inbound message EVER (not the first in range); `context` is
    `whatsapp_thread_state.context` (`{}` without a state row); `automated` is
    `menu_version_id IS NOT NULL`."""

    thread_id: UUID
    first_inbound_at: datetime | None
    first_inbound_text: str | None
    context: Mapping[str, Any] = field(default_factory=dict)
    automated: bool = False


@dataclass(frozen=True)
class MessageFact:
    thread_id: UUID
    direction: Literal["inbound", "outbound"]
    at: datetime
    # The producing outbox row's `kind` (outbound only; `None` = no outbox row).
    outbox_kind: str | None = None
    delivery_status: str | None = None

    @property
    def sender(self) -> Sender:
        if self.direction == "inbound":
            return "inbound"
        return _SENDER_BY_KIND.get(self.outbox_kind or "", "other")


@dataclass(frozen=True)
class MetricsRows:
    """Everything `aggregate` reads. `messages` covers `[since, until + horizon)` for the
    threads in `threads`; `send_failed` is already counted for `[since, until)`."""

    threads: Sequence[ThreadFact]
    messages: Sequence[MessageFact]
    send_failed: int = 0
    entry: EntryConfig | None = None


# ======================================================================================
# Result
# ======================================================================================


@dataclass(frozen=True)
class EntryCount:
    """`key` names the entry within its kind: the command name, the ice-breaker text,
    the QR label, the normalized keyword; `None` for `directo`."""

    kind: EntryKind
    key: str | None
    threads: int


@dataclass(frozen=True)
class ConversationMetrics:
    connection_id: UUID
    since: datetime
    until: datetime
    threads_opened: int
    threads_opened_by_entry: tuple[EntryCount, ...]
    orders_confirmed: int
    orders_total: Mapping[str, Decimal]
    handoffs: int
    handoffs_by_reason: Mapping[str, int]
    first_human_responses: int
    awaiting_human_response: int
    median_first_human_response_seconds: float | None
    p90_first_human_response_seconds: float | None
    messages_in: int
    messages_out_automation: int
    messages_out_human: int
    messages_out_campaign: int
    messages_out_other: int
    delivery_failed: int
    send_failed: int


# ======================================================================================
# Entry classification (pure)
# ======================================================================================


@dataclass(frozen=True)
class EntryMatch:
    kind: EntryKind
    key: str | None = None


DIRECT: Final = EntryMatch("directo")


def classify_entry(
    first_text: str | None,
    entry: EntryConfig | None,
    qr_prefixes: Mapping[str, str] | None = None,
) -> EntryMatch:
    """Which entry point a conversation came through, from its first inbound text. Order
    and rules: module docstring."""
    if not first_text or not first_text.strip():
        return DIRECT
    stripped = first_text.strip()
    norm = normalize_keyword(stripped)
    if entry is not None and stripped.startswith("/") and len(stripped) > 1:
        words = stripped[1:].split(maxsplit=1)
        name = normalize_keyword(words[0]) if words else ""
        for cmd in entry.commands:
            if normalize_keyword(cmd.name) == name:
                return EntryMatch("command", cmd.name)
    if entry is not None:
        for ib in entry.ice_breakers:
            if normalize_keyword(ib.text) == norm:
                return EntryMatch("ice_breaker", ib.text)
    best: tuple[int, str] | None = None
    for label, prefix in (qr_prefixes or {}).items():
        p = normalize_keyword(prefix)
        if p and norm.startswith(p) and (best is None or len(p) > best[0]):
            best = (len(p), label)
    if best is not None:
        return EntryMatch("qr", best[1])
    if entry is not None and norm in entry.keywords:
        return EntryMatch("keyword", norm)
    return DIRECT


# ======================================================================================
# Aggregation (pure)
# ======================================================================================


def _in_range(at: datetime | None, since: datetime, until: datetime) -> bool:
    return at is not None and since <= as_utc(at) < until


def _parse_instant(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return as_utc(value)
    if isinstance(value, str):
        try:
            return as_utc(datetime.fromisoformat(value))
        except ValueError:
            return None
    return None


def _handoff(context: Mapping[str, Any]) -> tuple[str, datetime] | None:
    raw = context.get(CTX_HANDOFF)
    if not isinstance(raw, Mapping):
        return None
    at = _parse_instant(raw.get("at"))
    if at is None:
        return None
    reason = raw.get("reason")
    return (reason if isinstance(reason, str) and reason else "unknown"), at


def p90_nearest_rank(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[math.ceil(0.9 * len(ordered)) - 1]


def _response_start(
    thread: ThreadFact,
    inbound: Sequence[datetime],
    handoff: tuple[str, datetime] | None,
    since: datetime,
    until: datetime,
) -> datetime | None:
    if handoff is not None and _in_range(handoff[1], since, until):
        before = [at for at in inbound if at <= handoff[1]]
        return max(before) if before else handoff[1]
    if not thread.automated and _in_range(thread.first_inbound_at, since, until):
        assert thread.first_inbound_at is not None
        return as_utc(thread.first_inbound_at)
    return None


def aggregate(
    rows: MetricsRows,
    *,
    connection_id: UUID,
    since: datetime,
    until: datetime,
    qr_prefixes: Mapping[str, str] | None = None,
) -> ConversationMetrics:
    since, until = as_utc(since), as_utc(until)
    by_thread: dict[UUID, list[MessageFact]] = defaultdict(list)
    for m in rows.messages:
        by_thread[m.thread_id].append(m)

    entries: Counter[tuple[EntryKind, str | None]] = Counter()
    orders_total: dict[str, Decimal] = defaultdict(Decimal)
    reasons: Counter[str] = Counter()
    threads_opened = orders_confirmed = awaiting = 0
    durations: list[float] = []

    for thread in rows.threads:
        if _in_range(thread.first_inbound_at, since, until):
            threads_opened += 1
            match = classify_entry(thread.first_inbound_text, rows.entry, qr_prefixes)
            entries[(match.kind, match.key)] += 1

        order = read_order(thread.context)
        if order is not None and _in_range(order.confirmed_at, since, until):
            orders_confirmed += 1
            orders_total[order.currency or NO_CURRENCY] += order.total

        handoff = _handoff(thread.context)
        if handoff is not None and _in_range(handoff[1], since, until):
            reasons[handoff[0]] += 1

        messages = sorted(by_thread.get(thread.thread_id, []), key=lambda m: as_utc(m.at))
        inbound = [as_utc(m.at) for m in messages if m.direction == "inbound"]
        start = _response_start(thread, inbound, handoff, since, until)
        if start is None:
            continue
        response = next(
            (as_utc(m.at) for m in messages if m.sender == "human" and as_utc(m.at) >= start),
            None,
        )
        if response is None:
            awaiting += 1
        else:
            durations.append((response - start).total_seconds())

    in_range = [m for m in rows.messages if _in_range(m.at, since, until)]
    senders = Counter(m.sender for m in in_range)
    return ConversationMetrics(
        connection_id=connection_id,
        since=since,
        until=until,
        threads_opened=threads_opened,
        threads_opened_by_entry=tuple(
            EntryCount(kind=kind, key=key, threads=n)
            for (kind, key), n in sorted(
                entries.items(), key=lambda item: (-item[1], item[0][0], item[0][1] or "")
            )
        ),
        orders_confirmed=orders_confirmed,
        orders_total=dict(orders_total),
        handoffs=sum(reasons.values()),
        handoffs_by_reason=dict(reasons),
        first_human_responses=len(durations),
        awaiting_human_response=awaiting,
        median_first_human_response_seconds=(
            float(statistics.median(durations)) if durations else None
        ),
        p90_first_human_response_seconds=p90_nearest_rank(durations),
        messages_in=senders["inbound"],
        messages_out_automation=senders["automation"],
        messages_out_human=senders["human"],
        messages_out_campaign=senders["campaign"],
        messages_out_other=senders["other"],
        delivery_failed=sum(
            1 for m in in_range if m.direction == "outbound" and m.delivery_status == "failed"
        ),
        send_failed=rows.send_failed,
    )


# ======================================================================================
# Repository seam
# ======================================================================================


class MetricsRepository(Protocol):
    def connection_exists(self, *, tenant_id: UUID, connection_id: UUID) -> bool:
        """A `platform = 'whatsapp'` connection visible to this tenant."""
        ...

    def load(
        self, *, tenant_id: UUID, connection_id: UUID, since: datetime, until: datetime
    ) -> MetricsRows:
        """Threads with any message in `[since, until + RESPONSE_HORIZON)`, those
        messages, the outbox failures created in `[since, until)` and the published
        menu's entry config (`None` without a published menu)."""
        ...


# --- Postgres ------------------------------------------------------------------------

_INSTANT = "COALESCE({m}.posted_at, {m}.ingested_at)"

_CONNECTION_EXISTS = text(
    "SELECT 1 FROM social_connections WHERE id = :connection_id AND platform = 'whatsapp'"
)

_THREADS = text(
    """
    SELECT t.id, s.context, s.menu_version_id, fi.at AS first_inbound_at,
           fi.text AS first_inbound_text
      FROM threads t
      LEFT JOIN whatsapp_thread_state s ON s.thread_id = t.id
      LEFT JOIN LATERAL (
            SELECT {f_instant} AS at, f.text
              FROM messages f
             WHERE f.thread_id = t.id AND f.direction = 'inbound' AND f.deleted_at IS NULL
             ORDER BY {f_instant} ASC, f.id ASC
             LIMIT 1) fi ON true
     WHERE t.connection_id = :connection_id AND t.channel = 'whatsapp'
       AND EXISTS (
            SELECT 1 FROM messages a
             WHERE a.thread_id = t.id AND a.deleted_at IS NULL
               AND {a_instant} >= :since AND {a_instant} < :horizon_end)
    """.format(f_instant=_INSTANT.format(m="f"), a_instant=_INSTANT.format(m="a"))
)

_MESSAGES = text(
    """
    SELECT m.thread_id, m.direction, {instant} AS at, m.delivery_status, ob.kind AS outbox_kind
      FROM messages m
      JOIN threads t ON t.id = m.thread_id
      LEFT JOIN whatsapp_outbox ob
             ON m.direction = 'outbound'
            AND ob.connection_id = m.connection_id
            AND ob.wamid = m.external_message_id
     WHERE t.connection_id = :connection_id AND t.channel = 'whatsapp'
       AND m.deleted_at IS NULL
       AND {instant} >= :since AND {instant} < :horizon_end
    """.format(instant=_INSTANT.format(m="m"))
)

_SEND_FAILED = text(
    """
    SELECT count(*) FROM whatsapp_outbox
     WHERE connection_id = :connection_id AND status IN ('failed', 'dead')
       AND created_at >= :since AND created_at < :until
    """
)

# The menu published on the connection's number (paused or not: its entries are what
# the number advertises, and what the classification compares against).
_PUBLISHED_DEFINITION = text(
    """
    SELECT v.definition
      FROM whatsapp_menus mn
      JOIN whatsapp_phone_numbers p ON p.id = mn.phone_number_row_id
      JOIN whatsapp_menu_versions v ON v.id = mn.published_version_id
     WHERE p.connection_id = :connection_id
     ORDER BY mn.updated_at DESC
     LIMIT 1
    """
)


def _entry_from_definition(definition: Any) -> EntryConfig | None:
    """A stored definition that no longer validates (an older editor) must not break the
    metrics: classification falls back to `directo` for everything."""
    if not isinstance(definition, Mapping):
        return None
    try:
        return MenuDefinition.model_validate(definition).entry
    except ValueError:
        return None


class PostgresMetricsRepository:
    """Reads only, each call in `tenant_session(tenant_id)` (`qualify_app`).

    Cost: one pass over the connection's messages in the window plus a per-thread
    first-inbound lateral. At one number's volume (hundreds of threads a week) that is
    cheap; the indexes 0004/0057 already carry (`messages (thread_id, …)`) serve both."""

    def connection_exists(self, *, tenant_id: UUID, connection_id: UUID) -> bool:
        with tenant_session(tenant_id) as session:
            row = session.execute(_CONNECTION_EXISTS, {"connection_id": connection_id}).first()
        return row is not None

    def load(
        self, *, tenant_id: UUID, connection_id: UUID, since: datetime, until: datetime
    ) -> MetricsRows:
        params = {
            "connection_id": connection_id,
            "since": since,
            "until": until,
            "horizon_end": until + RESPONSE_HORIZON,
        }
        with tenant_session(tenant_id) as session:
            thread_rows = session.execute(_THREADS, params).all()
            message_rows = session.execute(_MESSAGES, params).all()
            send_failed = session.execute(_SEND_FAILED, params).scalar_one()
            definition = session.execute(_PUBLISHED_DEFINITION, params).scalar_one_or_none()
        return MetricsRows(
            threads=[
                ThreadFact(
                    thread_id=r.id,
                    first_inbound_at=r.first_inbound_at,
                    first_inbound_text=r.first_inbound_text,
                    context=r.context or {},
                    automated=r.menu_version_id is not None,
                )
                for r in thread_rows
            ],
            messages=[
                MessageFact(
                    thread_id=r.thread_id,
                    direction=r.direction,
                    at=r.at,
                    outbox_kind=r.outbox_kind,
                    delivery_status=r.delivery_status,
                )
                for r in message_rows
            ],
            send_failed=int(send_failed),
            entry=_entry_from_definition(definition),
        )


# --- In memory (tests) ---------------------------------------------------------------


@dataclass
class MemoryMetricsRepository:
    """Rows per `(tenant_id, connection_id)`, filtered the way the SQL filters them."""

    connections: dict[tuple[UUID, UUID], MetricsRows] = field(default_factory=dict)

    def put(self, *, tenant_id: UUID, connection_id: UUID, rows: MetricsRows) -> None:
        self.connections[(tenant_id, connection_id)] = rows

    def connection_exists(self, *, tenant_id: UUID, connection_id: UUID) -> bool:
        return (tenant_id, connection_id) in self.connections

    def load(
        self, *, tenant_id: UUID, connection_id: UUID, since: datetime, until: datetime
    ) -> MetricsRows:
        rows = self.connections.get((tenant_id, connection_id))
        if rows is None:
            return MetricsRows(threads=[], messages=[])
        horizon_end = until + RESPONSE_HORIZON
        messages = [m for m in rows.messages if since <= as_utc(m.at) < horizon_end]
        active = {m.thread_id for m in messages}
        return MetricsRows(
            threads=[t for t in rows.threads if t.thread_id in active],
            messages=messages,
            send_failed=rows.send_failed,
            entry=rows.entry,
        )


# ======================================================================================
# Service
# ======================================================================================


class QrPrefixSource(Protocol):
    """`{label: prefilled_message}` of the number's QR codes, or `None` when they could
    not be listed (the metrics are still computed; QR entries then read as whatever
    else matches, usually `keyword` or `directo`)."""

    async def __call__(
        self, *, tenant_id: UUID, connection_id: UUID
    ) -> Mapping[str, str] | None: ...


class _QrLister(Protocol):
    async def list_qr_codes(self) -> Sequence[Any]: ...


class QrClientFactory(Protocol):
    async def __call__(self, *, tenant_id: UUID, connection_id: UUID) -> _QrLister: ...


async def no_qr_prefixes(*, tenant_id: UUID, connection_id: UUID) -> Mapping[str, str] | None:
    return {}


class ClientQrPrefixSource:
    """Lists the number's QR codes through the Cloud API (`client.list_qr_codes`, one
    Graph GET per metrics request). The label is the QR `code` — Meta stores no channel
    name; a human label («mostrador», «empaque») arrives with WA-12's QR registry, and
    this mapping is the one place to switch to it.

    Never fails the metrics: any error (Graph, transport, no credential) is logged by
    type only and answered with `None`."""

    def __init__(self, client_factory: QrClientFactory) -> None:
        self._clients = client_factory

    async def __call__(self, *, tenant_id: UUID, connection_id: UUID) -> Mapping[str, str] | None:
        try:
            client = await self._clients(tenant_id=tenant_id, connection_id=connection_id)
            codes = await client.list_qr_codes()
        except Exception as exc:  # noqa: BLE001 — metrics degrade, they do not fail
            _LOGGER.warning(
                "whatsapp metrics: QR codes not listed for connection=%s (%s)",
                connection_id,
                type(exc).__name__,
            )
            return None
        return {
            str(c.code): str(c.prefilled_message)
            for c in codes
            if getattr(c, "code", None) and getattr(c, "prefilled_message", None)
        }


class ConversationMetricsService:
    def __init__(
        self,
        repo: MetricsRepository,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._repo = repo
        self._clock = clock

    def ensure_connection(self, tenant_id: UUID, connection_id: UUID) -> None:
        """Raise `ConnectionNotFound` before anything costs a Graph call (the route asks
        Meta for QR codes only for a connection the caller can see)."""
        if not self._repo.connection_exists(tenant_id=tenant_id, connection_id=connection_id):
            raise ConnectionNotFound(str(connection_id))

    def compute(
        self,
        tenant_id: UUID,
        connection_id: UUID,
        since: datetime | None = None,
        until: datetime | None = None,
        qr_prefixes: Mapping[str, str] | None = None,
    ) -> ConversationMetrics:
        """Raises `InvalidRange` (422) or `ConnectionNotFound` (404)."""
        since_, until_ = resolve_range(since, until, self._clock())
        self.ensure_connection(tenant_id, connection_id)
        rows = self._repo.load(
            tenant_id=tenant_id, connection_id=connection_id, since=since_, until=until_
        )
        return aggregate(
            rows, connection_id=connection_id, since=since_, until=until_, qr_prefixes=qr_prefixes
        )


def production_metrics_service() -> ConversationMetricsService:
    return ConversationMetricsService(PostgresMetricsRepository())


def production_qr_prefix_source() -> ClientQrPrefixSource:
    """QR codes listed through WA-08's resolver-built client. Imports resolved here so
    importing this module needs no Meta settings."""
    from qualify_api.config import MetaOAuthSettings  # noqa: PLC0415
    from qualify_api.connections.crypto import DevEncryptor  # noqa: PLC0415
    from qualify_api.whatsapp.outbox import ResolverClientFactory  # noqa: PLC0415

    return ClientQrPrefixSource(ResolverClientFactory(MetaOAuthSettings.from_env(), DevEncryptor()))


__all__ = [
    "ClientQrPrefixSource",
    "production_qr_prefix_source",
    "DEFAULT_RANGE",
    "MAX_RANGE",
    "NO_CURRENCY",
    "RESPONSE_HORIZON",
    "ConnectionNotFound",
    "ConversationMetrics",
    "ConversationMetricsService",
    "EntryCount",
    "EntryMatch",
    "InvalidRange",
    "MemoryMetricsRepository",
    "MessageFact",
    "MetricsRepository",
    "MetricsRows",
    "PostgresMetricsRepository",
    "QrPrefixSource",
    "ThreadFact",
    "aggregate",
    "classify_entry",
    "no_qr_prefixes",
    "p90_nearest_rank",
    "production_metrics_service",
    "resolve_range",
]

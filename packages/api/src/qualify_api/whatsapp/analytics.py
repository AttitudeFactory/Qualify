"""WABA analytics read from Meta (WA-21, QUA-220): messages sent/delivered per day and
approximate cost per pricing category, for ONE connected number.

Backlog: `docs/backlog-modulo-whatsapp.md` §5 WA-21 («mensajes por día, costo por
categoría, comparado con lo que suma `whatsapp_campaign_sends`»). Plan §2.5: since
2025-07-01 Meta bills **per delivered message**, only templates (marketing / utility /
authentication) cost money, and service messages inside the 24 h window are free — so
the cost view is `pricing_analytics` (per message, by category and type), not the
legacy per-conversation `conversation_analytics`, which this module deliberately does not
read.

## Where the numbers come from

Two Graph reads on the WABA node, both filtered to this connection's display number
(`client.get_waba_analytics` → `fields=analytics…`, `client.get_pricing_analytics` →
`fields=currency,pricing_analytics…`; shapes `[DOC]`, see their parsers). They run
concurrently over one resolver-built client; the token never reaches this module
(`ClientFactory`, the WA-08 seam). Meta's own caveats carried through, not hidden:

- cost is **approximate** and in the WABA's currency (`currency`); it can differ from
  the invoice;
- a WABA billed through a Solution Partner gets **no cost** (`cost_available = False`,
  `cost_total = None`) — volumes still arrive;
- bucket edges are Meta's (its day boundary is not UTC midnight) and are passed through;
- lookback is one year (Meta, from 2025-12-01): an older `since` is Meta's error (502).

## Errors

Two failures mean "a person must reconnect the number" and become `ReconnectRequired`
(the route's 409 `reconnect_required`): the connection has no readable credential
(`CredentialNotFound` from the resolver) and Meta refused the token (`WhatsAppApiError.
is_auth_error`, 401 / code 190). Every other `WhatsAppApiError` propagates unchanged (the
route's 502, Meta's numeric code only). No connection degrade here: this is a read, and
the outbox sender / the health check are the paths that own QUA-90's degrade.

## Campaign reconciliation

`reconcile_with_campaigns` is a placeholder that returns `None`: the per-send ledger it
compares against (`whatsapp_campaign_sends`, WA-20) lands in migration 0060, which is not
on this branch. See its TODO.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final, Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.connections.credential_reader import CredentialNotFound
from qualify_api.whatsapp.client import (
    AnalyticsGranularity,
    PricingAnalytics,
    WabaAnalytics,
    WhatsAppApiError,
)
from qualify_api.whatsapp.metrics import ConnectionNotFound, resolve_range
from qualify_api.whatsapp.models import WhatsAppPhoneNumber

BILLED_PRICING_TYPE: Final = "REGULAR"
UNKNOWN_CATEGORY: Final = "UNKNOWN"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ReconnectRequired(Exception):
    """The number's credential is missing or Meta rejected it: only reconnecting the
    WhatsApp connection fixes it (module docstring, "Errors")."""


# ======================================================================================
# Seams
# ======================================================================================


class WabaAnalyticsReader(Protocol):
    """The two client methods this service needs (`HttpWhatsAppClient` has them)."""

    async def get_waba_analytics(
        self,
        waba_id: str,
        start: datetime,
        end: datetime,
        granularity: AnalyticsGranularity,
        phone_numbers: Sequence[str] | None = None,
    ) -> WabaAnalytics: ...

    async def get_pricing_analytics(
        self,
        waba_id: str,
        start: datetime,
        end: datetime,
        granularity: AnalyticsGranularity,
        phone_numbers: Sequence[str] | None = None,
    ) -> PricingAnalytics: ...


class AnalyticsClientFactory(Protocol):
    """`outbox.ClientFactory`'s shape: production passes `outbox.ResolverClientFactory`."""

    async def __call__(self, *, tenant_id: UUID, connection_id: UUID) -> WabaAnalyticsReader: ...


@dataclass(frozen=True)
class AnalyticsPhone:
    waba_id: str
    phone_number_id: str
    display_phone_number: str


class AnalyticsPhoneRepository(Protocol):
    def for_connection(self, *, tenant_id: UUID, connection_id: UUID) -> AnalyticsPhone | None:
        """The connection's `whatsapp_phone_numbers` row, `None` when there is none for
        this tenant (another tenant's included — RLS)."""
        ...


class PostgresAnalyticsPhoneRepository:
    """`tenant_session` (`qualify_app`: SELECT on `whatsapp_phone_numbers`, 0057)."""

    def for_connection(self, *, tenant_id: UUID, connection_id: UUID) -> AnalyticsPhone | None:
        with tenant_session(tenant_id) as session:
            row = session.execute(
                select(
                    WhatsAppPhoneNumber.waba_id,
                    WhatsAppPhoneNumber.phone_number_id,
                    WhatsAppPhoneNumber.display_phone_number,
                ).where(WhatsAppPhoneNumber.connection_id == connection_id)
            ).first()
        if row is None:
            return None
        return AnalyticsPhone(
            waba_id=row.waba_id,
            phone_number_id=row.phone_number_id,
            display_phone_number=row.display_phone_number,
        )


class MemoryAnalyticsPhoneRepository:
    def __init__(self) -> None:
        self.rows: dict[tuple[UUID, UUID], AnalyticsPhone] = {}

    def put(self, *, tenant_id: UUID, connection_id: UUID, phone: AnalyticsPhone) -> None:
        self.rows[(tenant_id, connection_id)] = phone

    def for_connection(self, *, tenant_id: UUID, connection_id: UUID) -> AnalyticsPhone | None:
        return self.rows.get((tenant_id, connection_id))


# ======================================================================================
# Result
# ======================================================================================


@dataclass(frozen=True)
class MessagesBucket:
    start: datetime
    end: datetime
    sent: int
    delivered: int


@dataclass(frozen=True)
class CategoryCost:
    """One pricing category over the whole range. `volume` = delivered messages,
    `billable_volume` = those with `pricing_type = REGULAR` (the rest were free: service
    window, free entry point). `cost` is `None` when Meta returned no cost for any of
    the category's points."""

    category: str
    volume: int
    billable_volume: int
    cost: Decimal | None


@dataclass(frozen=True)
class AnalyticsSummary:
    connection_id: UUID
    waba_id: str
    phone_number: str
    since: datetime
    until: datetime
    granularity: AnalyticsGranularity
    currency: str | None
    messages: tuple[MessagesBucket, ...]
    sent_total: int
    delivered_total: int
    cost_by_category: tuple[CategoryCost, ...]
    cost_total: Decimal | None
    cost_available: bool
    # WA-20 placeholder (`reconcile_with_campaigns`): always `None` today.
    campaign_reconciliation: None = None


def summarize_pricing(pricing: PricingAnalytics) -> tuple[tuple[CategoryCost, ...], bool]:
    """Fold the per-bucket, per-type points into one row per category, highest cost first
    (then highest volume, then name — a stable order for the UI)."""
    volume: dict[str, int] = defaultdict(int)
    billable: dict[str, int] = defaultdict(int)
    cost: dict[str, Decimal | None] = {}
    for point in pricing.data_points:
        category = point.pricing_category or UNKNOWN_CATEGORY
        volume[category] += point.volume
        if point.pricing_type == BILLED_PRICING_TYPE:
            billable[category] += point.volume
        previous = cost.get(category)
        if point.cost is not None:
            cost[category] = (previous or Decimal("0")) + point.cost
        else:
            cost.setdefault(category, None)
    rows = [
        CategoryCost(category=c, volume=volume[c], billable_volume=billable[c], cost=cost.get(c))
        for c in volume
    ]
    rows.sort(key=lambda r: (-(r.cost or Decimal("0")), -r.volume, r.category))
    available = any(p.cost is not None for p in pricing.data_points)
    return tuple(rows), available


# ======================================================================================
# Service
# ======================================================================================


class WabaAnalyticsService:
    def __init__(
        self,
        client_factory: AnalyticsClientFactory,
        phone_repo: AnalyticsPhoneRepository,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._clients = client_factory
        self._phones = phone_repo
        self._clock = clock

    async def summary(
        self,
        tenant_id: UUID,
        connection_id: UUID,
        since: datetime | None = None,
        until: datetime | None = None,
        granularity: AnalyticsGranularity = "DAY",
    ) -> AnalyticsSummary:
        """Raises `InvalidRange` (422), `ConnectionNotFound` (404), `ReconnectRequired`
        (409) or the client's non-auth `WhatsAppApiError` (502)."""
        since_, until_ = resolve_range(since, until, self._clock())
        phone = await asyncio.to_thread(
            self._phones.for_connection, tenant_id=tenant_id, connection_id=connection_id
        )
        if phone is None:
            raise ConnectionNotFound(str(connection_id))
        try:
            client = await self._clients(tenant_id=tenant_id, connection_id=connection_id)
        except CredentialNotFound:
            raise ReconnectRequired(str(connection_id)) from None
        numbers = [phone.display_phone_number]
        try:
            messaging, pricing = await asyncio.gather(
                client.get_waba_analytics(phone.waba_id, since_, until_, granularity, numbers),
                client.get_pricing_analytics(phone.waba_id, since_, until_, granularity, numbers),
            )
        except WhatsAppApiError as exc:
            if exc.is_auth_error:
                raise ReconnectRequired(str(connection_id)) from exc
            raise
        buckets = tuple(
            MessagesBucket(start=p.start, end=p.end, sent=p.sent, delivered=p.delivered)
            for p in messaging.data_points
        )
        categories, cost_available = summarize_pricing(pricing)
        return AnalyticsSummary(
            connection_id=connection_id,
            waba_id=phone.waba_id,
            phone_number=phone.display_phone_number,
            since=since_,
            until=until_,
            granularity=granularity,
            currency=pricing.currency,
            messages=buckets,
            sent_total=sum(b.sent for b in buckets),
            delivered_total=sum(b.delivered for b in buckets),
            cost_by_category=categories,
            cost_total=(
                sum((c.cost for c in categories if c.cost is not None), Decimal("0"))
                if cost_available
                else None
            ),
            cost_available=cost_available,
            campaign_reconciliation=self.reconcile_with_campaigns(
                tenant_id, connection_id, since_, until_
            ),
        )

    def reconcile_with_campaigns(
        self, tenant_id: UUID, connection_id: UUID, since: datetime, until: datetime
    ) -> None:
        """Placeholder — always `None`.

        TODO(WA-20, QUA-219): compare Meta's delivered volume/cost per category with what
        `whatsapp_campaign_sends` (migration 0060) records for the same connection and
        range — sends, estimated cost, and the `pricing.category` the status webhook
        confirms — and return the per-category differences. It must not be imported or
        queried before 0060 is on `main`."""
        return None


def production_analytics_service() -> WabaAnalyticsService:
    """Resolver-built clients (WA-08's `ResolverClientFactory`) and the Postgres phone
    lookup. Imports resolved here so importing this module needs no Meta settings."""
    from qualify_api.config import MetaOAuthSettings  # noqa: PLC0415
    from qualify_api.connections.crypto import DevEncryptor  # noqa: PLC0415
    from qualify_api.whatsapp.outbox import ResolverClientFactory  # noqa: PLC0415

    return WabaAnalyticsService(
        ResolverClientFactory(MetaOAuthSettings.from_env(), DevEncryptor()),
        PostgresAnalyticsPhoneRepository(),
    )


__all__ = [
    "AnalyticsClientFactory",
    "AnalyticsPhone",
    "AnalyticsPhoneRepository",
    "AnalyticsSummary",
    "CategoryCost",
    "MemoryAnalyticsPhoneRepository",
    "MessagesBucket",
    "PostgresAnalyticsPhoneRepository",
    "ReconnectRequired",
    "WabaAnalyticsReader",
    "WabaAnalyticsService",
    "production_analytics_service",
    "summarize_pricing",
]

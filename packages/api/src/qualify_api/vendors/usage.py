"""Per-business caps on paid vendor reads (ADR 42 §2.4, §3.2, slice R5, m-24854849).

Every paid ScrapeCreators call is charged to a business and leaves one row in
`vendor_usage_events` (0117, tenant RLS); a business's cap is a `SUM` over those rows:
**150 credits in its local day and 600 in its local month** (`tenants.timezone`). The
gate (`qualify_api.vendors.scrapecreators.metered_get`) books the row BEFORE the request
leaves; a booking that would cross a cap is refused and the call is not made
(`ScrapeCreatorsBlocked`, reason `tenant_daily_cap` / `tenant_monthly_cap`).

**Every paid read is some business's** (founder decision, 2026-11-04: «incluir todo»).
A call with no business to charge is not made (reason `no_tenant`): a worker or CLI that
reads must say for whom. Nothing is exempt from the cap — the operator's 90-day read,
trending and the avatar prefetch count like any other read.

**Who is charged.** The business that TRIGGERED the read — never every business that
later benefits from it: reading what is already stored (a fresh `reel_accounts` row, the
shared payload pool, a picture on disk) makes no call, so it books nothing. A caller says
who it reads for in one of two ways, both read by the gate:

- `bind(client, charge)` — the charge travels with the `httpx.Client`. This is the form
  for code that fans a run out to worker threads (the reels run, the referentes search):
  a `ThreadPoolExecutor` does not carry context variables, a client does;
- `with charge_to(tenant_id, brand_id):` — a context variable, for code that lets the
  vendor module build its own client (the Brand Kit read, trending, the avatar prefetch).
  `asyncio.to_thread` and `loop.create_task` copy it.

**Concurrency.** The check and the booking are one transaction under a per-tenant
advisory lock (`pg_advisory_xact_lock`), so two parallel calls at 149 cannot both pass:
the second waits for the first's commit and then sees 150. Inside one process a
per-tenant `threading.Lock` is taken BEFORE a connection is checked out, so a 12-thread
fan-out holds at most one pooled connection per tenant while it waits — it cannot drain
the pool into false `usage_unreadable` refusals. Neither lock is held across the HTTP
call.

**What a row may overstate.** A booking is one credit, made before the vendor answers,
and the table is append-only for `qualify_app` (0117): a call that then fails (network, a
404 the vendor may not charge, a cached answer it may not charge) keeps its credit. When
the vendor reports `credits_charged` > 1 the difference is booked after the answer
(`:extra` row), uncapped — it is already spent. So a cap can be crossed by at most one
call's extra credits, and never undercounted.

**Sub-caps of one module.** `spent(..., features=...)` sums only some features, so a
module can keep a tighter budget inside the business's cap without a second ledger: the
Creators read (m-24946121) stops itself at 50 credits a day and 300 a month over
`creator_profile` + `creator_reels`, before the gate's 150/600 would.

Provenance of `usd_estimate`: `pricing_table_version` (the creative pricing table,
`scrapecreators.per_credit`). `created_at` is the database's `now()`.

**What the owner reads** when a cap stops a read (`cap_notice`, UX review of R5): never
credits or money, only when they can search again.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from functools import lru_cache
from typing import Any, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.consumption import DEFAULT_PRICING_TABLE_VERSION

logger = logging.getLogger(__name__)

#: The `vendor_usage_events.vendor` of ScrapeCreators.
SCRAPECREATORS = "scrapecreators"
#: ADR 42 §2.4: a business's credits per local day and per local month.
DAILY_CAP = 150
MONTHLY_CAP = 600
#: Refusal reasons the gate raises with (`ScrapeCreatorsBlocked.reason`).
REASON_DAILY_CAP = "tenant_daily_cap"
REASON_MONTHLY_CAP = "tenant_monthly_cap"
REASON_USAGE_UNREADABLE = "usage_unreadable"
REASON_NO_TENANT = "no_tenant"
CAP_REASONS = frozenset({REASON_DAILY_CAP, REASON_MONTHLY_CAP})
#: The price sheet the `usd_estimate` is computed from (the consumption ledger's).
PRICING_TABLE_VERSION = DEFAULT_PRICING_TABLE_VERSION
_PRICING_MODEL = "scrapecreators"
_PRICING_UNIT = "per_credit"
#: Where a business with no readable zone counts its day.
DEFAULT_ZONE = "UTC"
#: The attribute `bind` leaves on a client.
CLIENT_ATTR = "qualify_usage_charge"


@dataclass(frozen=True)
class UsageCharge:
    """Who pays a read: the business, and the brand it was for when there is one."""

    tenant_id: UUID
    brand_id: UUID | None = None


@dataclass(frozen=True)
class UsageEvent:
    tenant_id: UUID
    brand_id: UUID | None
    vendor: str
    feature: str
    credits: int
    usd_estimate: Decimal
    pricing_table_version: str
    request_key: str
    #: None = the database's `now()` (the gate); tests pass a moment to place a row.
    created_at: datetime | None = None


@dataclass(frozen=True)
class Spent:
    """Credits a business already used in its current local day and month."""

    day: int
    month: int


def refusal(spent: Spent, credits: int) -> str | None:
    """The cap `credits` more would cross, or None when they fit."""
    if spent.day + credits > DAILY_CAP:
        return REASON_DAILY_CAP
    if spent.month + credits > MONTHLY_CAP:
        return REASON_MONTHLY_CAP
    return None


@lru_cache(maxsize=4)
def usd_per_credit(version: str = PRICING_TABLE_VERSION) -> Decimal:
    from qualify_creative.pricing import JsonPricingTable  # noqa: PLC0415 - data file

    return JsonPricingTable(version).unit_price(model_id=_PRICING_MODEL, unit=_PRICING_UNIT)


# ---------------------------------------------------------------------------------------
# Who pays: the context variable and the client binding


_current: ContextVar[UsageCharge | None] = ContextVar("vendor_usage_charge", default=None)


@contextmanager
def charge_to(tenant_id: UUID, brand_id: UUID | None = None) -> Iterator[UsageCharge]:
    """Charge every paid read made inside to this business."""
    charge = UsageCharge(tenant_id, brand_id)
    token = _current.set(charge)
    try:
        yield charge
    finally:
        _current.reset(token)


@contextmanager
def uncharged() -> Iterator[None]:
    """No business in scope inside (the gate then refuses every paid read)."""
    token = _current.set(None)
    try:
        yield
    finally:
        _current.reset(token)


def current() -> UsageCharge | None:
    return _current.get()


def bind(client: Any, charge: UsageCharge | None) -> Any:
    """Make every paid read through `client` charged to `charge` (None = leave it)."""
    if charge is not None:
        setattr(client, CLIENT_ATTR, charge)
    return client


def charge_of(client: Any) -> UsageCharge | None:
    """Who pays a read through `client`: its binding, else the context, else nobody."""
    bound = getattr(client, CLIENT_ATTR, None)
    return bound if isinstance(bound, UsageCharge) else _current.get()


# ---------------------------------------------------------------------------------------
# The business's clock


_warned_zones: set[tuple[str, str]] = set()
_warned_guard = threading.Lock()


def _warn_once(subject: str, zone: str) -> None:
    with _warned_guard:
        if (subject, zone) in _warned_zones:
            return
        _warned_zones.add((subject, zone))
    logger.warning("vendor usage of %s counted in UTC: time zone %r unreadable", subject, zone)


def zone_of(raw: object, *, subject: str = "?") -> ZoneInfo:
    """The business's zone; UTC (warned once per business and value) when unreadable."""
    if isinstance(raw, str) and raw:
        try:
            return ZoneInfo(raw)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    _warn_once(subject, repr(raw))
    return ZoneInfo(DEFAULT_ZONE)


def local_bounds(now: datetime, zone: ZoneInfo) -> tuple[datetime, datetime]:
    """Start of the local day and of the local month containing `now`, in UTC."""
    local = now.astimezone(zone)
    day = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return day.astimezone(UTC), day.replace(day=1).astimezone(UTC)


# ---------------------------------------------------------------------------------------
# What the owner reads when a cap stopped a read (UX review of R5)

_MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)

DAILY_CAP_NOTICE = "Ya hiciste todas las búsquedas de hoy. Mañana puedes buscar de nuevo."
MONTHLY_CAP_NOTICE = (
    "Este mes ya hiciste todas las búsquedas. Desde el {renewal} puedes buscar de nuevo."
)
PROFILE_DAILY_CAP_NOTICE = (
    "Hoy ya no podemos leer tu perfil. Completa tus datos tú mismo; mañana podremos leerlo."
)
PROFILE_MONTHLY_CAP_NOTICE = (
    "Este mes ya no podemos leer tu perfil. Completa tus datos tú mismo; "
    "desde el {renewal} podremos leerlo."
)
#: A screen's title when a cap stopped its search (the body is the notice above).
DAILY_CAP_TITLE = "Por hoy ya no hay más búsquedas"
MONTHLY_CAP_TITLE = "Este mes ya no hay más búsquedas"


def cap_title(reason: str | None) -> str | None:
    """The title for a screen a cap stopped, or None for any other reason."""
    return {REASON_DAILY_CAP: DAILY_CAP_TITLE, REASON_MONTHLY_CAP: MONTHLY_CAP_TITLE}.get(
        reason or ""
    )


def renewal_label(zone: ZoneInfo, now: datetime | None = None) -> str:
    """«1 de diciembre»: the first day of the business's next local month."""
    local = (now or datetime.now(UTC)).astimezone(zone)
    month = local.month % 12 + 1
    return f"1 de {_MONTHS[month - 1]}"


def tenant_zone(tenant_id: UUID) -> ZoneInfo:
    """The business's zone from `tenants.timezone` (UTC, warned, when unreadable)."""
    try:
        with tenant_session(tenant_id) as session:
            raw = session.execute(_ZONE, {"tenant": tenant_id}).scalar_one_or_none()
    except Exception as exc:  # noqa: BLE001 - copy must never break a screen
        logger.warning("tenant zone unreadable: %s", type(exc).__name__)
        raw = None
    return zone_of(raw, subject=str(tenant_id))


def cap_notice(
    reason: str | None,
    *,
    zone: ZoneInfo | None = None,
    tenant_id: UUID | None = None,
    profile: bool = False,
    now: datetime | None = None,
) -> str | None:
    """The owner's sentence for a cap refusal, or None for any other reason (which keeps
    its screen's own copy). `profile=True` is the Brand Kit's own-profile read. The
    monthly renewal date is in the business's zone (`zone`, else read for `tenant_id`)."""
    if reason == REASON_DAILY_CAP:
        return PROFILE_DAILY_CAP_NOTICE if profile else DAILY_CAP_NOTICE
    if reason != REASON_MONTHLY_CAP:
        return None
    if zone is None:
        zone = tenant_zone(tenant_id) if tenant_id is not None else ZoneInfo(DEFAULT_ZONE)
    template = PROFILE_MONTHLY_CAP_NOTICE if profile else MONTHLY_CAP_NOTICE
    return template.format(renewal=renewal_label(zone, now))


# ---------------------------------------------------------------------------------------
# Where the rows live


class UsageStore(Protocol):
    def book(self, event: UsageEvent, *, capped: bool) -> str | None:
        """Atomically check the caps (when `capped`) and append `event`. Returns None when
        booked, else the refusal reason (nothing written)."""
        ...

    def spent(
        self,
        tenant_id: UUID,
        vendor: str,
        now: datetime | None = None,
        *,
        features: Collection[str] | None = None,
    ) -> Spent:
        """Credits used today and this month (local); only `features` when given."""
        ...


class InMemoryUsageStore:
    """The offline fake: the same local-time sums and the same atomic check-and-book."""

    def __init__(self, zones: dict[UUID, str] | None = None) -> None:
        self._lock = threading.Lock()
        self.zones = dict(zones or {})
        self.events: list[UsageEvent] = []

    def _spent(
        self,
        tenant_id: UUID,
        vendor: str,
        now: datetime,
        features: Collection[str] | None = None,
    ) -> Spent:
        zone = zone_of(self.zones.get(tenant_id, DEFAULT_ZONE), subject=str(tenant_id))
        day, month = local_bounds(now, zone)
        rows = [
            e
            for e in self.events
            if e.tenant_id == tenant_id
            and e.vendor == vendor
            and (features is None or e.feature in features)
            and e.created_at is not None
            and month <= e.created_at
        ]
        return Spent(
            day=sum(e.credits for e in rows if e.created_at and e.created_at >= day),
            month=sum(e.credits for e in rows),
        )

    def spent(
        self,
        tenant_id: UUID,
        vendor: str,
        now: datetime | None = None,
        *,
        features: Collection[str] | None = None,
    ) -> Spent:
        with self._lock:
            return self._spent(tenant_id, vendor, now or datetime.now(UTC), features)

    def book(self, event: UsageEvent, *, capped: bool) -> str | None:
        with self._lock:
            at = event.created_at or datetime.now(UTC)
            if capped:
                reason = refusal(self._spent(event.tenant_id, event.vendor, at), event.credits)
                if reason is not None:
                    return reason
            if any(
                e.tenant_id == event.tenant_id and e.request_key == event.request_key
                for e in self.events
            ):
                return None  # the UNIQUE (tenant_id, request_key) of 0117
            self.events.append(UsageEvent(**{**event.__dict__, "created_at": at}))
            return None

    def of(self, tenant_id: UUID) -> list[UsageEvent]:
        return [e for e in self.events if e.tenant_id == tenant_id]


#: Serializes one tenant's bookings across every process (the app and each worker).
_LOCK = text("SELECT pg_advisory_xact_lock(hashtextextended('vendor_usage:' || :tenant, 0))")
_ZONE = text("SELECT timezone FROM tenants WHERE id = :tenant")
_NOW = text("SELECT now()")
_SPENT = text(
    """
    SELECT COALESCE(SUM(credits) FILTER (WHERE created_at >= :day), 0) AS day,
           COALESCE(SUM(credits), 0) AS month
    FROM vendor_usage_events
    WHERE tenant_id = :tenant AND vendor = :vendor AND created_at >= :month
      AND (CAST(:features AS text[]) IS NULL OR feature = ANY(CAST(:features AS text[])))
    """
)
_INSERT = text(
    """
    INSERT INTO vendor_usage_events
        (tenant_id, brand_id, vendor, feature, credits, usd_estimate,
         pricing_table_version, request_key, created_at)
    VALUES (:tenant, :brand, :vendor, :feature, :credits, :usd,
            :version, :request_key, COALESCE(CAST(:created_at AS timestamptz), now()))
    ON CONFLICT (tenant_id, request_key) DO NOTHING
    """
)


class PostgresUsageStore:
    """`vendor_usage_events` through `tenant_session` (RLS: a business sees and writes
    only its own rows). `independent=True`: a booking commits on its own, before the call,
    even inside a caller's unit of work — the credit is spent whatever that work does.

    `session_factory` is the seam the in-process serialisation test uses."""

    def __init__(self, session_factory: Any = None) -> None:
        self._session = session_factory or (lambda tenant: tenant_session(tenant, independent=True))
        self._guard = threading.Lock()
        self._tenant_locks: dict[UUID, threading.Lock] = {}

    def _tenant_lock(self, tenant_id: UUID) -> threading.Lock:
        with self._guard:
            return self._tenant_locks.setdefault(tenant_id, threading.Lock())

    def _spent(
        self,
        session: Any,
        tenant_id: UUID,
        vendor: str,
        now: datetime | None,
        features: Collection[str] | None = None,
    ) -> Spent:
        raw = session.execute(_ZONE, {"tenant": tenant_id}).scalar_one_or_none()
        at = now or session.execute(_NOW).scalar_one()
        day, month = local_bounds(at, zone_of(raw, subject=str(tenant_id)))
        row = session.execute(
            _SPENT,
            {
                "tenant": tenant_id,
                "vendor": vendor,
                "day": day,
                "month": month,
                "features": list(features) if features is not None else None,
            },
        ).one()
        return Spent(day=int(row.day), month=int(row.month))

    def spent(
        self,
        tenant_id: UUID,
        vendor: str,
        now: datetime | None = None,
        *,
        features: Collection[str] | None = None,
    ) -> Spent:
        with self._session(tenant_id) as session:
            return self._spent(session, tenant_id, vendor, now, features)

    def book(self, event: UsageEvent, *, capped: bool) -> str | None:
        # one waiter per tenant per process: taken BEFORE a pooled connection is
        # checked out, so a fan-out never drains the pool waiting on the advisory lock
        with self._tenant_lock(event.tenant_id), self._session(event.tenant_id) as session:
            session.execute(_LOCK, {"tenant": str(event.tenant_id)})
            if capped:
                spent = self._spent(session, event.tenant_id, event.vendor, event.created_at)
                reason = refusal(spent, event.credits)
                if reason is not None:
                    return reason
            session.execute(
                _INSERT,
                {
                    "tenant": event.tenant_id,
                    "brand": event.brand_id,
                    "vendor": event.vendor,
                    "feature": event.feature,
                    "credits": event.credits,
                    "usd": event.usd_estimate,
                    "version": event.pricing_table_version,
                    "request_key": event.request_key,
                    "created_at": event.created_at,
                },
            )
        return None


_store: UsageStore | None = None


def configure_store(store: UsageStore | None) -> None:
    """Install where bookings go (`None` = Postgres, the default). The repo-wide conftest
    installs an `InMemoryUsageStore` for every test, so no offline test reaches Postgres."""
    global _store
    _store = store


def store() -> UsageStore:
    global _store
    if _store is None:
        _store = PostgresUsageStore()
    return _store


__all__ = [
    "CAP_REASONS",
    "CLIENT_ATTR",
    "DAILY_CAP",
    "DAILY_CAP_NOTICE",
    "DAILY_CAP_TITLE",
    "DEFAULT_ZONE",
    "MONTHLY_CAP",
    "MONTHLY_CAP_NOTICE",
    "MONTHLY_CAP_TITLE",
    "PRICING_TABLE_VERSION",
    "PROFILE_DAILY_CAP_NOTICE",
    "PROFILE_MONTHLY_CAP_NOTICE",
    "REASON_DAILY_CAP",
    "REASON_MONTHLY_CAP",
    "REASON_NO_TENANT",
    "REASON_USAGE_UNREADABLE",
    "SCRAPECREATORS",
    "InMemoryUsageStore",
    "PostgresUsageStore",
    "Spent",
    "UsageCharge",
    "UsageEvent",
    "UsageStore",
    "bind",
    "cap_notice",
    "cap_title",
    "charge_of",
    "charge_to",
    "configure_store",
    "current",
    "local_bounds",
    "refusal",
    "renewal_label",
    "store",
    "tenant_zone",
    "uncharged",
    "usd_per_credit",
    "zone_of",
]

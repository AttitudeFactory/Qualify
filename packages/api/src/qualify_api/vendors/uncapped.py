"""Businesses whose paid ScrapeCreators reads skip Qualify's own caps (m-24956180).

Founder decision (Herwin, 2026-11-05): Bianki must have unlimited Creators revisions
(«Actualizar» a creator), switched on **from Meegle**. Two caps stop a business, and both
are Qualify's, not the vendor's: the Creators module's budget
(`creators.snapshots.CREATOR_DAY_CAP` / `CREATOR_MONTH_CAP`) and the business's cap in the
metered gate (`usage.DAILY_CAP` / `MONTHLY_CAP`, ADR 42 §2.4). An uncapped business skips
both.

**Where the switch lives.** One row per business in `business_read_limits` (0130, tenant
RLS; `qualify_app` may only read it, so a business can never uncap itself). It is written
by the «Alta de cliente» in Meegle: the optional select «Lecturas sin límite» (Sí / No),
read with «Plan» / «Paquete» when «Datos» or «Plan ampliado» is completed
(`qualify_api.meegle.plan_request`). Sí = uncapped, No = back to the caps, empty = no
change. Each row keeps its provenance: the Alta's work item id, who completed the node,
the Meegle event and when. No row = capped (today's behaviour). There is no wildcard:
every business is named by its own Alta.

**What an uncapped business still gets**, unchanged: every credit is booked in
`vendor_usage_events` before the call (accounting, provenance, idempotency), and every
other refusal stands — `no_tenant`, `usage_unreadable`, the paid switch, the global credit
floor and a 402. Only the per-business cap check is skipped.

**Reading it** costs one indexed `SELECT` per business, cached per process for
`CACHE_SECONDS`; a write through `set_uncapped_reads` forgets that business's entry in its
own process at once (others see it within the minute). A row that cannot be read reads
as **capped** (logged): an outage never lifts a cap.

It lives in `vendors` so the gate and `creators` both read it without an import cycle.
Offline tests get an `InMemoryUncappedStore` from the repo-wide conftest.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

logger = logging.getLogger(__name__)

CACHE_SECONDS = 60.0


@dataclass(frozen=True)
class ReadLimit:
    """The state of one business's switch and where it came from."""

    tenant_id: UUID
    uncapped_reads: bool
    set_by: str
    meegle_work_item_id: int | None = None
    event_key: str | None = None
    updated_at: datetime | None = None


class UncappedStore(Protocol):
    def uncapped(self, tenant_id: UUID) -> bool:
        """True when the business's row says its reads are uncapped (no row = False)."""
        ...

    def set(self, limit: ReadLimit) -> None:
        """Create or replace the business's row (idempotent: the same value twice is one
        state)."""
        ...


class InMemoryUncappedStore:
    """The offline fake."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.rows: dict[UUID, ReadLimit] = {}

    def uncapped(self, tenant_id: UUID) -> bool:
        with self._lock:
            row = self.rows.get(tenant_id)
            return bool(row and row.uncapped_reads)

    def set(self, limit: ReadLimit) -> None:
        with self._lock:
            stamped = limit.updated_at or datetime.now(UTC)
            self.rows[limit.tenant_id] = ReadLimit(**{**limit.__dict__, "updated_at": stamped})


_READ = text("SELECT uncapped_reads FROM business_read_limits WHERE tenant_id = :tenant")
_UPSERT = text(
    """
    INSERT INTO business_read_limits
        (tenant_id, uncapped_reads, meegle_work_item_id, set_by, event_key, updated_at)
    VALUES (:tenant, :uncapped, :item, :set_by, :event_key, now())
    ON CONFLICT (tenant_id) DO UPDATE
       SET uncapped_reads = EXCLUDED.uncapped_reads,
           meegle_work_item_id = EXCLUDED.meegle_work_item_id,
           set_by = EXCLUDED.set_by,
           event_key = EXCLUDED.event_key,
           updated_at = now()
    """
)


class PostgresUncappedStore:
    """Reads through `tenant_session` (RLS: a business sees only its own row; an
    independent transaction, so a read inside a caller's unit of work never joins it);
    writes through `admin_session` — only the Meegle path sets the switch."""

    def __init__(self, session_factory: Any = None) -> None:
        self._session = session_factory or (lambda tenant: tenant_session(tenant, independent=True))

    def uncapped(self, tenant_id: UUID) -> bool:
        with self._session(tenant_id) as session:
            return bool(session.execute(_READ, {"tenant": tenant_id}).scalar_one_or_none())

    def set(self, limit: ReadLimit) -> None:
        from qualify_shared.db.admin import admin_session  # noqa: PLC0415 - writes only

        with admin_session() as session:
            session.execute(
                _UPSERT,
                {
                    "tenant": limit.tenant_id,
                    "uncapped": limit.uncapped_reads,
                    "item": limit.meegle_work_item_id,
                    "set_by": limit.set_by,
                    "event_key": limit.event_key,
                },
            )


_store: UncappedStore | None = None
_lock = threading.Lock()
_cache: dict[UUID, tuple[float, bool]] = {}


def configure_store(store: UncappedStore | None) -> None:
    """Install where the switch is read and written (`None` = Postgres, the default).
    The repo-wide conftest installs an `InMemoryUncappedStore` for every test."""
    global _store
    _store = store
    reset_cache()


def store() -> UncappedStore:
    global _store
    if _store is None:
        _store = PostgresUncappedStore()
    return _store


def is_uncapped(tenant_id: UUID, *, clock: float | None = None) -> bool:
    """True when this business's ScrapeCreators reads skip Qualify's caps. Cached
    `CACHE_SECONDS` per business; unreadable = False (capped), logged."""
    now = time.monotonic() if clock is None else clock
    with _lock:
        hit = _cache.get(tenant_id)
        if hit is not None and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    try:
        value = store().uncapped(tenant_id)
    except Exception as exc:  # noqa: BLE001 - an outage must never lift a cap
        logger.warning(
            "read limit of tenant %s unreadable, capped: %s", tenant_id, type(exc).__name__
        )
        return False
    with _lock:
        _cache[tenant_id] = (now, value)
    return value


def set_uncapped_reads(
    tenant_id: UUID,
    uncapped_reads: bool,
    *,
    set_by: str,
    meegle_work_item_id: int | None = None,
    event_key: str | None = None,
) -> ReadLimit:
    """Turn the business's switch on or off, with its provenance; forget the cache."""
    limit = ReadLimit(
        tenant_id=tenant_id,
        uncapped_reads=uncapped_reads,
        set_by=set_by.strip()[:200] or "meegle",
        meegle_work_item_id=meegle_work_item_id,
        event_key=(event_key or "").strip()[:200] or None,
    )
    store().set(limit)
    with _lock:
        _cache.pop(tenant_id, None)
    logger.info("read limit of tenant %s: uncapped=%s by %s", tenant_id, uncapped_reads, set_by)
    return limit


def reset_cache() -> None:
    """Forget every cached value (tests)."""
    with _lock:
        _cache.clear()


__all__ = [
    "CACHE_SECONDS",
    "InMemoryUncappedStore",
    "PostgresUncappedStore",
    "ReadLimit",
    "UncappedStore",
    "configure_store",
    "is_uncapped",
    "reset_cache",
    "set_uncapped_reads",
    "store",
]

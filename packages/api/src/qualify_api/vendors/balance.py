"""Where the ScrapeCreators gate keeps the vendor's balance (ADR 42 R2, m-24854847).

The vendor reports `credits_remaining` in the body of every answer; the gate
(`qualify_api.vendors.scrapecreators.metered_get`) records it here for free and refuses to
call below the 500-credit floor. The row is global (`vendor_balance`, 0117: one row per
vendor, no tenant), so every process — the Reflex app, each worker — sees the same floor,
and a 402 written as `credits_remaining = 0` stops all of them, not only the one that met it.

`BalanceStore` is the seam: `PostgresBalanceStore` in production (through
`qualify_shared.db.session.global_session`, the tenant-less door), `InMemoryBalanceStore`
in tests (the repo-wide `conftest.py` installs one for every test, so no offline test ever
reaches Postgres through the gate).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from qualify_shared.db.session import global_session
from sqlalchemy import text

#: The `vendor_balance.vendor` key of ScrapeCreators.
SCRAPECREATORS = "scrapecreators"


@dataclass(frozen=True)
class Balance:
    """The vendor's last reported credits and when the answer that carried them arrived."""

    credits_remaining: int
    observed_at: datetime


class BalanceStore(Protocol):
    def read(self, vendor: str) -> Balance | None:
        """The last recorded balance, or None when the vendor never reported one."""
        ...

    def record(
        self,
        vendor: str,
        credits_remaining: int,
        observed_at: datetime,
        *,
        authoritative: bool = False,
    ) -> None:
        """Keep `credits_remaining`, unless an observation as new or newer is already
        stored. `authoritative=True` (the vendor's own balance route, read by the operator
        after a top-up) always wins and becomes the newest observation."""
        ...


class InMemoryBalanceStore:
    """The offline fake. Same monotonic rule as the Postgres upsert; `initial` balances
    count as observed a minute ago, before anything a test does."""

    def __init__(self, initial: dict[str, int] | None = None) -> None:
        self._lock = threading.Lock()
        self.rows: dict[str, Balance] = {
            vendor: Balance(credits, datetime.now(UTC) - timedelta(minutes=1))
            for vendor, credits in (initial or {}).items()
        }

    def read(self, vendor: str) -> Balance | None:
        with self._lock:
            return self.rows.get(vendor)

    def record(
        self,
        vendor: str,
        credits_remaining: int,
        observed_at: datetime,
        *,
        authoritative: bool = False,
    ) -> None:
        with self._lock:
            current = self.rows.get(vendor)
            if authoritative and current is not None:
                observed_at = max(observed_at, current.observed_at + _TICK)
            if authoritative or current is None or current.observed_at < observed_at:
                self.rows[vendor] = Balance(credits_remaining, observed_at)


#: How much newer than the stored row an authoritative read is made, at least.
_TICK = timedelta(microseconds=1)

# A late answer never overwrites a newer one (strictly newer wins: on a tie the row already
# there stays, so a 200 that left at the very instant of a 402 cannot reopen the floor) —
# two workers finishing out of order would otherwise put back a balance from before the
# other's charge. The operator's authoritative read always wins (`_AUTHORITATIVE`).
_UPSERT = text(
    """
    INSERT INTO vendor_balance (vendor, credits_remaining, observed_at)
    VALUES (:vendor, :credits, :observed_at)
    ON CONFLICT (vendor) DO UPDATE
        SET credits_remaining = EXCLUDED.credits_remaining,
            observed_at = EXCLUDED.observed_at
        WHERE vendor_balance.observed_at < EXCLUDED.observed_at
    """
)
_AUTHORITATIVE = text(
    """
    INSERT INTO vendor_balance (vendor, credits_remaining, observed_at)
    VALUES (:vendor, :credits, :observed_at)
    ON CONFLICT (vendor) DO UPDATE
        SET credits_remaining = EXCLUDED.credits_remaining,
            observed_at = GREATEST(
                EXCLUDED.observed_at, vendor_balance.observed_at + interval '1 microsecond'
            )
    """
)
_SELECT = text("SELECT credits_remaining, observed_at FROM vendor_balance WHERE vendor = :vendor")


class PostgresBalanceStore:
    """`vendor_balance` through the tenant-less door (`global_session`)."""

    def read(self, vendor: str) -> Balance | None:
        with global_session() as session:
            row = session.execute(_SELECT, {"vendor": vendor}).first()
        if row is None:
            return None
        return Balance(int(row.credits_remaining), row.observed_at)

    def record(
        self,
        vendor: str,
        credits_remaining: int,
        observed_at: datetime,
        *,
        authoritative: bool = False,
    ) -> None:
        with global_session() as session:
            session.execute(
                _AUTHORITATIVE if authoritative else _UPSERT,
                {"vendor": vendor, "credits": credits_remaining, "observed_at": observed_at},
            )


__all__ = [
    "SCRAPECREATORS",
    "Balance",
    "BalanceStore",
    "InMemoryBalanceStore",
    "PostgresBalanceStore",
]

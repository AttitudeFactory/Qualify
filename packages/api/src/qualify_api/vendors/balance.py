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

**Alerts (m-24854847).** Each write also decides, in the same transaction, whether the team
must be told something (`next_alert`): `low` under 2,000 credits, `floor` under the gate's
500-credit floor, `empty` on a 402. Each kind goes out once per episode: the kinds already
sent live in `vendor_balance.alerts_sent` (0121), read and updated under a per-vendor
advisory lock, so two processes never both claim one. The caller gets the claimed kind in
`BalanceChange.alert` and sends it (`qualify_api.vendors.balance_alert`).

A kind is re-armed only by evidence of a top-up: the operator's authoritative read at or
over its level, or any answer at least `REARM_MARGIN` over it. An ordinary answer is not
enough because a 200 is dated when its request LEFT while the vendor counts at charge time,
so near a level two answers can land out of order (1,999 then 2,000) — without the margin
that wobble would re-arm the alert and send it twice.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from qualify_shared.db.session import global_session
from sqlalchemy import text

#: The `vendor_balance.vendor` key of ScrapeCreators.
SCRAPECREATORS = "scrapecreators"

#: Alert kinds, mildest first (0121's CHECK lists the same three).
ALERT_LOW = "low"
ALERT_FLOOR = "floor"
ALERT_EMPTY = "empty"
#: Under this many credits: `low` (ADR 42 §2.4).
LOW_BALANCE_THRESHOLD = 2_000
#: The gate's floor (`scrapecreators.CREDIT_FLOOR`): under it, no call goes out — `floor`.
FLOOR_THRESHOLD = 500
#: How far over a level an ordinary (non-authoritative) answer must be to re-arm it.
REARM_MARGIN = 200
#: The level each kind re-arms at: an authoritative read at or over it, or any answer at
#: or over it plus `REARM_MARGIN`. `empty` re-arms as soon as credits are back.
_REARM_AT = {ALERT_LOW: LOW_BALANCE_THRESHOLD, ALERT_FLOOR: FLOOR_THRESHOLD, ALERT_EMPTY: 1}


@dataclass(frozen=True)
class Balance:
    """The vendor's last reported credits and when the answer that carried them arrived."""

    credits_remaining: int
    observed_at: datetime


@dataclass(frozen=True)
class BalanceChange:
    """What one applied `record` did: the credits stored before it (None = the vendor had
    never reported a balance), the credits it left, and the alert it claimed — at most one
    per write, the most severe — or None."""

    before: int | None
    after: int
    alert: str | None = None


def next_alert(
    sent: Iterable[str],
    after: int,
    *,
    authoritative: bool = False,
    exhausted: bool = False,
) -> tuple[str | None, frozenset[str]]:
    """The alert this applied write claims (or None) and the kinds sent afterwards.

    `exhausted` = the write is a 402. A claimed kind also silences the milder ones for the
    episode (after `empty`, no later `low`)."""
    claimed = set(sent)
    for kind, level in _REARM_AT.items():
        if after >= level + REARM_MARGIN or (authoritative and after >= level):
            claimed.discard(kind)
    if exhausted:
        kind, silences = ALERT_EMPTY, (ALERT_EMPTY, ALERT_FLOOR, ALERT_LOW)
    elif after < FLOOR_THRESHOLD:
        kind, silences = ALERT_FLOOR, (ALERT_FLOOR, ALERT_LOW)
    elif after < LOW_BALANCE_THRESHOLD:
        kind, silences = ALERT_LOW, (ALERT_LOW,)
    else:
        return None, frozenset(claimed)
    # Only the claimed set decides: a 200 reporting 0 (a `floor` alert) followed by an
    # in-flight call's 402 is still news — the `empty` alert goes out.
    fresh = kind not in claimed
    claimed.update(silences)
    return (kind if fresh else None), frozenset(claimed)


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
        exhausted: bool = False,
    ) -> BalanceChange | None:
        """Keep `credits_remaining`, unless an observation as new or newer is already
        stored. `authoritative=True` (the vendor's own balance route, read by the operator
        after a top-up) always wins and becomes the newest observation; `exhausted=True`
        marks a 402. Returns the change it made (with the alert it claimed), or None when
        nothing was written."""
        ...


class InMemoryBalanceStore:
    """The offline fake. Same monotonic and alert rules as the Postgres store; `initial`
    balances count as observed a minute ago, before anything a test does."""

    def __init__(self, initial: dict[str, int] | None = None) -> None:
        self._lock = threading.Lock()
        self.rows: dict[str, Balance] = {
            vendor: Balance(credits, datetime.now(UTC) - timedelta(minutes=1))
            for vendor, credits in (initial or {}).items()
        }
        self.alerts_sent: dict[str, frozenset[str]] = {}

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
        exhausted: bool = False,
    ) -> BalanceChange | None:
        with self._lock:
            current = self.rows.get(vendor)
            if authoritative and current is not None:
                observed_at = max(observed_at, current.observed_at + _TICK)
            if not (authoritative or current is None or current.observed_at < observed_at):
                return None
            self.rows[vendor] = Balance(credits_remaining, observed_at)
            before = None if current is None else current.credits_remaining
            alert, sent = next_alert(
                self.alerts_sent.get(vendor, frozenset()),
                credits_remaining,
                authoritative=authoritative,
                exhausted=exhausted,
            )
            self.alerts_sent[vendor] = sent
            return BalanceChange(before, credits_remaining, alert)


#: How much newer than the stored row an authoritative read is made, at least.
_TICK = timedelta(microseconds=1)

# A late answer never overwrites a newer one (strictly newer wins: on a tie the row already
# there stays, so a 200 that left at the very instant of a 402 cannot reopen the floor) —
# two workers finishing out of order would otherwise put back a balance from before the
# other's charge. The operator's authoritative read always wins (`_AUTHORITATIVE`). Both
# return the credits they wrote; no row back means the guard kept the stored one.
_UPSERT = text(
    """
    INSERT INTO vendor_balance (vendor, credits_remaining, observed_at)
    VALUES (:vendor, :credits, :observed_at)
    ON CONFLICT (vendor) DO UPDATE
        SET credits_remaining = EXCLUDED.credits_remaining,
            observed_at = EXCLUDED.observed_at
        WHERE vendor_balance.observed_at < EXCLUDED.observed_at
    RETURNING credits_remaining
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
    RETURNING credits_remaining
    """
)
# Serializes every writer of one vendor's row until commit — the very first insert too,
# when there is no row yet for FOR UPDATE to lock — so the credits and alerts read as
# "before" are exactly the ones this transaction replaces. Any role may take an advisory
# lock: no new grant.
_LOCK = text("SELECT pg_advisory_xact_lock(hashtextextended('vendor_balance:' || :vendor, 0))")
_SELECT_STATE = text(
    "SELECT credits_remaining, alerts_sent FROM vendor_balance WHERE vendor = :vendor"
)
_SET_ALERTS = text("UPDATE vendor_balance SET alerts_sent = :sent WHERE vendor = :vendor")
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
        exhausted: bool = False,
    ) -> BalanceChange | None:
        with global_session() as session:
            session.execute(_LOCK, {"vendor": vendor})
            row = session.execute(_SELECT_STATE, {"vendor": vendor}).first()
            after = session.execute(
                _AUTHORITATIVE if authoritative else _UPSERT,
                {"vendor": vendor, "credits": credits_remaining, "observed_at": observed_at},
            ).scalar_one_or_none()
            if after is None:  # an older observation: the monotonic guard kept the row
                return None
            before = None if row is None else int(row.credits_remaining)
            previous = frozenset(row.alerts_sent) if row is not None else frozenset()
            alert, sent = next_alert(
                previous,
                int(after),
                authoritative=authoritative,
                exhausted=exhausted,
            )
            if sent != previous:
                session.execute(_SET_ALERTS, {"vendor": vendor, "sent": sorted(sent)})
        return BalanceChange(before, int(after), alert)


__all__ = [
    "ALERT_EMPTY",
    "ALERT_FLOOR",
    "ALERT_LOW",
    "FLOOR_THRESHOLD",
    "LOW_BALANCE_THRESHOLD",
    "REARM_MARGIN",
    "SCRAPECREATORS",
    "Balance",
    "BalanceChange",
    "BalanceStore",
    "InMemoryBalanceStore",
    "PostgresBalanceStore",
    "next_alert",
]

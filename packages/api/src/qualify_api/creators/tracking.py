"""Where the Creators module keeps what it follows and what it read (m-24946121,
`docs/diseno-modulo-creadores.md` §7, §8).

`TrackedCreatorStore` is the one seam `snapshots.refresh_creator` and `service` talk to:

- **per business (RLS):** `tracked_creators` — the creators a brand follows. What each
  paid call cost the business is booked by the metered gate itself
  (`qualify_api.vendors.usage`, ADR 42 R5), not here;
- **global, public data:** `creator_snapshots` and `public_reel_reads` (the history of
  reads, migration 0125), plus — through their owners' own functions, never SQL of ours —
  `vendor_payloads` and `creators` (`creators.repository`, 0036), `public_reels` and the
  per-account lock of `reel_accounts` (`referentes.reel_store`, 0117).

`PostgresTrackedCreatorStore` runs every statement inside `tenant_session` (the RLS
policy scopes `tracked_creators`; the global tables have none
to scope) and writes a read in ONE transaction (`save_read`).
`MemoryTrackedCreatorStore` is the offline twin, with the same idempotency keys.
"""

from __future__ import annotations

import threading
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID, uuid4

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creators.metrics import ReelRead, SnapshotFacts
from qualify_api.creators.repository import (
    CachedPayload,
    CreatorFacts,
    MemoryCreatorPoolRepository,
    PostgresCreatorPoolRepository,
    upsert_creators_in,
)
from qualify_api.referentes.reel_store import (
    MemoryReelRunStore,
    PostgresReelRunStore,
    PublicReel,
    capture_reel_hashtags,
    upsert_reels_in,
)

TRACKED_ACTIVE = "active"
TRACKED_ARCHIVED = "archived"
REFRESH_NEVER = "never"
REFRESH_READING = "reading"
REFRESH_OK = "ok"
REFRESH_FAILED = "failed"

SNAPSHOT_OK = "ok"
SNAPSHOT_PARTIAL = "partial"
SNAPSHOT_PRIVATE = "private"
SNAPSHOT_MISSING = "missing"
SNAPSHOT_ERROR = "error"
#: A read that tells something true about the account (cached 24 h for every business).
SNAPSHOT_SETTLED = (SNAPSHOT_OK, SNAPSHOT_PARTIAL, SNAPSHOT_PRIVATE, SNAPSHOT_MISSING)
#: A read with figures in it.
SNAPSHOT_WITH_DATA = (SNAPSHOT_OK, SNAPSHOT_PARTIAL)

VENDOR = "scrapecreators"


@dataclass(frozen=True)
class TrackedCreator:
    """A creator a brand follows (`tracked_creators`)."""

    id: UUID
    brand_id: UUID
    network: str
    handle: str
    note: str
    status: str  # active | archived
    refresh_state: str  # never | reading | ok | failed
    refresh_error: str | None
    last_snapshot_id: UUID | None
    created_at: datetime
    #: When the last read started. A `reading` state older than `REFRESH_STUCK_AFTER`
    #: is a read that died (crash, restart): treat it as failed (`refresh_stuck`).
    refresh_started_at: datetime | None = None
    #: What the creator charges, as the owner wrote it (m-24955847, migration 0132):
    #: free text (one price or several packages) and the lowest price «Desde» with its
    #: currency — both set or both None. Manual owner input: no provenance.
    rate_notes: str = ""
    rate_from: Decimal | None = None
    rate_currency: str | None = None
    rate_updated_at: datetime | None = None


@dataclass(frozen=True)
class NewSnapshot:
    """One `creator_snapshots` row to write (global: nothing here names a business)."""

    id: UUID
    network: str
    handle: str
    read_at: datetime
    status: str
    parser_version: int
    reels_target: int
    followers: int | None = None
    following: int | None = None
    posts_count: int | None = None
    full_name: str = ""
    bio: str = ""
    category: str = ""
    external_url: str = ""
    avatar_url: str = ""
    is_verified: bool = False
    is_private: bool = False
    reels_read: int = 0
    pages_read: int = 0
    oldest_taken_at: datetime | None = None
    newest_taken_at: datetime | None = None
    credits: int = 0
    profile_payload_id: UUID | None = None
    profile_payload_fetched_at: datetime | None = None

    def facts(self) -> SnapshotFacts:
        return SnapshotFacts(
            snapshot_id=self.id,
            network=self.network,
            handle=self.handle,
            read_at=self.read_at,
            status=self.status,
            followers=self.followers,
            full_name=self.full_name,
            bio=self.bio,
            avatar_url=self.avatar_url,
            is_verified=self.is_verified,
            reels_read=self.reels_read,
        )


@dataclass(frozen=True)
class NewReelRead:
    """One `public_reel_reads` row: a reel's counters in one read."""

    snapshot_id: UUID
    network: str
    reel_id: str
    position: int
    taken_at: datetime
    parser_version: int
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    saves: int | None = None
    shares: int | None = None
    source_payload_id: UUID | None = None
    source_payload_fetched_at: datetime | None = None


#: A read holds the account for at most this long (`snapshots.LOCK_SECONDS`); a
#: `reading` state older than this never finished.
REFRESH_STUCK_AFTER = timedelta(seconds=120)


def refresh_stuck(creator: TrackedCreator, now: datetime) -> bool:
    """True when the creator says `reading` but its read started more than
    `REFRESH_STUCK_AFTER` ago (or never recorded a start): show it as failed."""
    if creator.refresh_state != REFRESH_READING:
        return False
    started = creator.refresh_started_at
    return started is None or now - started > REFRESH_STUCK_AFTER


def reel_url(network: str, handle: str, reel_id: str) -> str:
    if network == "tiktok":
        return f"https://www.tiktok.com/@{handle}/video/{reel_id}"
    return f"https://www.instagram.com/reel/{reel_id}/"


class TrackedCreatorStore(Protocol):
    # -- tracked_creators (per business) -------------------------------------------
    def add(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        *,
        network: str,
        handle: str,
        note: str,
        user_id: UUID | None,
        now: datetime,
    ) -> TrackedCreator:
        """Idempotent on `(brand_id, network, handle)`; reactivates an archived one and
        keeps its note unless a new one is given."""
        ...

    def get(self, tenant_id: UUID, brand_id: UUID, tracked_id: UUID) -> TrackedCreator | None: ...

    def list(
        self, tenant_id: UUID, brand_id: UUID, *, include_archived: bool = False
    ) -> list[TrackedCreator]: ...

    def archive(self, tenant_id: UUID, brand_id: UUID, tracked_id: UUID, *, now: datetime) -> bool:
        """True when the creator exists for this brand (archived now or already)."""
        ...

    def set_rate(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        tracked_id: UUID,
        *,
        notes: str,
        amount: Decimal | None,
        currency: str | None,
        now: datetime,
    ) -> TrackedCreator | None:
        """Replace the creator's rate (already validated by the service). Only an ACTIVE
        creator of this brand; None when there is none (absent, another brand's, or
        archived)."""
        ...

    def mark(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        tracked_id: UUID,
        *,
        state: str,
        error: str | None,
        now: datetime,
        snapshot_id: UUID | None = None,
        started: bool = False,
    ) -> None:
        """Set `refresh_state` / `refresh_error`; move `last_snapshot_id` only when a
        `snapshot_id` is given; stamp `refresh_started_at` when `started`."""
        ...

    # -- the read history (global) ---------------------------------------------------
    def latest_snapshot(
        self,
        tenant_id: UUID,
        network: str,
        handle: str,
        *,
        since: datetime,
        statuses: Collection[str],
    ) -> SnapshotFacts | None: ...

    def snapshots(self, tenant_id: UUID, ids: Collection[UUID]) -> dict[UUID, SnapshotFacts]: ...

    def reel_reads(
        self, tenant_id: UUID, snapshot_ids: Collection[UUID]
    ) -> dict[UUID, list[ReelRead]]: ...

    def save_read(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        tracked_id: UUID,
        *,
        snapshot: NewSnapshot,
        reads: Sequence[NewReelRead],
        reels: Sequence[PublicReel],
        creator: CreatorFacts,
        link: bool,
        state: str,
        error: str | None,
        now: datetime,
    ) -> None:
        """ONE transaction: the snapshot, its reel reads, the `public_reels` upsert
        (monotonic), the pool's `creators` row, and the tracked creator's state (its
        `last_snapshot_id` only when `link`)."""
        ...

    # -- the paid call's bookkeeping ---------------------------------------------------
    def put_payload(
        self,
        tenant_id: UUID,
        path: str,
        params: Mapping[str, Any],
        payload: Mapping[str, Any],
        *,
        status: int,
        credits: int,
        now: datetime,
    ) -> CachedPayload: ...

    def try_lock_account(
        self, tenant_id: UUID, network: str, handle: str, *, now: datetime, until: datetime
    ) -> bool: ...

    def finish_account(
        self,
        tenant_id: UUID,
        network: str,
        handle: str,
        *,
        now: datetime,
        status: str,
        http_status: int | None,
        credits: int,
        newest_taken_at: datetime | None,
        lock_until: datetime,
    ) -> None: ...

    def release_account(
        self, tenant_id: UUID, network: str, handle: str, *, lock_until: datetime
    ) -> None: ...


def _assemble(row: NewReelRead, reel: PublicReel | None, handle: str) -> ReelRead:
    return ReelRead(
        reel_id=row.reel_id,
        url=reel_url(row.network, handle, row.reel_id),
        taken_at=row.taken_at,
        duration_s=reel.duration_s if reel else None,
        views=row.views,
        likes=row.likes,
        comments=row.comments,
        counts_hidden=reel.counts_hidden if reel else False,
        is_paid_partnership=reel.is_paid_partnership if reel else False,
        coauthors=reel.coauthors if reel else None,
        sound_id=reel.sound_id if reel else None,
        sound_title=reel.sound if reel else "",
        sound_is_original=reel.sound_is_original if reel else None,
    )


# ======================================================================================
# In memory — the offline twin
# ======================================================================================


@dataclass
class _TrackedRow:
    tenant_id: UUID
    creator: TrackedCreator
    added_by_user_id: UUID | None
    archived_at: datetime | None = None


@dataclass
class MemoryTrackedCreatorStore:
    """`TrackedCreatorStore` in process memory. `fail_save` makes the next `save_read`
    raise (a lost write)."""

    pool: MemoryCreatorPoolRepository = field(default_factory=MemoryCreatorPoolRepository)
    reels: MemoryReelRunStore = field(default_factory=MemoryReelRunStore)
    tracked: dict[UUID, _TrackedRow] = field(default_factory=dict)
    snapshot_rows: dict[UUID, NewSnapshot] = field(default_factory=dict)
    read_rows: dict[UUID, list[NewReelRead]] = field(default_factory=dict)
    fail_save: int = 0

    def __post_init__(self) -> None:
        self._lock = threading.RLock()

    # tracked
    def _mine(self, tenant_id: UUID, brand_id: UUID, tracked_id: UUID) -> _TrackedRow | None:
        row = self.tracked.get(tracked_id)
        if row is None or row.tenant_id != tenant_id or row.creator.brand_id != brand_id:
            return None
        return row

    def add(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        *,
        network: str,
        handle: str,
        note: str,
        user_id: UUID | None,
        now: datetime,
    ) -> TrackedCreator:
        with self._lock:
            for row in self.tracked.values():
                c = row.creator
                if c.brand_id == brand_id and c.network == network and c.handle == handle:
                    if row.tenant_id != tenant_id:  # the composite FK would refuse it
                        raise ValueError("brand does not belong to this tenant")
                    row.creator = replace(c, status=TRACKED_ACTIVE, note=note or c.note)
                    row.archived_at = None
                    return row.creator
            creator = TrackedCreator(
                id=uuid4(),
                brand_id=brand_id,
                network=network,
                handle=handle,
                note=note,
                status=TRACKED_ACTIVE,
                refresh_state=REFRESH_NEVER,
                refresh_error=None,
                last_snapshot_id=None,
                created_at=now,
            )
            self.tracked[creator.id] = _TrackedRow(tenant_id, creator, user_id)
            return creator

    def get(self, tenant_id: UUID, brand_id: UUID, tracked_id: UUID) -> TrackedCreator | None:
        row = self._mine(tenant_id, brand_id, tracked_id)
        return row.creator if row else None

    def list(
        self, tenant_id: UUID, brand_id: UUID, *, include_archived: bool = False
    ) -> list[TrackedCreator]:
        rows = [
            r.creator
            for r in self.tracked.values()
            if r.tenant_id == tenant_id
            and r.creator.brand_id == brand_id
            and (include_archived or r.creator.status == TRACKED_ACTIVE)
        ]
        return sorted(rows, key=lambda c: (c.created_at, c.handle))

    def archive(self, tenant_id: UUID, brand_id: UUID, tracked_id: UUID, *, now: datetime) -> bool:
        with self._lock:
            row = self._mine(tenant_id, brand_id, tracked_id)
            if row is None:
                return False
            if row.creator.status != TRACKED_ARCHIVED:
                row.creator = replace(row.creator, status=TRACKED_ARCHIVED)
                row.archived_at = now
            return True

    def set_rate(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        tracked_id: UUID,
        *,
        notes: str,
        amount: Decimal | None,
        currency: str | None,
        now: datetime,
    ) -> TrackedCreator | None:
        with self._lock:
            row = self._mine(tenant_id, brand_id, tracked_id)
            if row is None or row.creator.status != TRACKED_ACTIVE:
                return None
            row.creator = replace(
                row.creator,
                rate_notes=notes,
                rate_from=amount,
                rate_currency=currency,
                rate_updated_at=now,
            )
            return row.creator

    def mark(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        tracked_id: UUID,
        *,
        state: str,
        error: str | None,
        now: datetime,
        snapshot_id: UUID | None = None,
        started: bool = False,
    ) -> None:
        with self._lock:
            row = self._mine(tenant_id, brand_id, tracked_id)
            if row is None:
                return
            row.creator = replace(
                row.creator,
                refresh_state=state,
                refresh_error=error,
                last_snapshot_id=snapshot_id or row.creator.last_snapshot_id,
                refresh_started_at=now if started else row.creator.refresh_started_at,
            )

    # history
    def latest_snapshot(
        self,
        tenant_id: UUID,
        network: str,
        handle: str,
        *,
        since: datetime,
        statuses: Collection[str],
    ) -> SnapshotFacts | None:
        found = [
            s
            for s in self.snapshot_rows.values()
            if s.network == network
            and s.handle == handle
            and s.read_at >= since
            and s.status in statuses
        ]
        if not found:
            return None
        return max(found, key=lambda s: s.read_at).facts()

    def snapshots(self, tenant_id: UUID, ids: Collection[UUID]) -> dict[UUID, SnapshotFacts]:
        return {i: self.snapshot_rows[i].facts() for i in ids if i in self.snapshot_rows}

    def reel_reads(
        self, tenant_id: UUID, snapshot_ids: Collection[UUID]
    ) -> dict[UUID, list[ReelRead]]:
        out: dict[UUID, list[ReelRead]] = {}
        for sid in snapshot_ids:
            snap = self.snapshot_rows.get(sid)
            if snap is None:
                continue
            rows = sorted(self.read_rows.get(sid, []), key=lambda r: r.position)
            out[sid] = [
                _assemble(r, self.reels.reels.get((r.network, r.reel_id)), snap.handle)
                for r in rows
            ]
        return out

    def save_read(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        tracked_id: UUID,
        *,
        snapshot: NewSnapshot,
        reads: Sequence[NewReelRead],
        reels: Sequence[PublicReel],
        creator: CreatorFacts,
        link: bool,
        state: str,
        error: str | None,
        now: datetime,
    ) -> None:
        with self._lock:
            if self.fail_save:
                self.fail_save -= 1
                raise RuntimeError("save_read failed (test)")
            if snapshot.id in self.snapshot_rows or any(
                s.network == snapshot.network
                and s.handle == snapshot.handle
                and s.read_at == snapshot.read_at
                for s in self.snapshot_rows.values()
            ):
                raise ValueError("duplicate creator snapshot")
            self.snapshot_rows[snapshot.id] = snapshot
            self.read_rows[snapshot.id] = list(reads)
            self.reels.upsert_reels(tenant_id, reels)
            self.pool.upsert_creators([creator])
            self.mark(
                tenant_id,
                brand_id,
                tracked_id,
                state=state,
                error=error,
                now=now,
                snapshot_id=snapshot.id if link else None,
            )

    # bookkeeping
    def put_payload(
        self,
        tenant_id: UUID,
        path: str,
        params: Mapping[str, Any],
        payload: Mapping[str, Any],
        *,
        status: int,
        credits: int,
        now: datetime,
    ) -> CachedPayload:
        return self.pool.put_payload(
            path, params, payload, status=status, credits_charged=credits, now=now
        )

    def try_lock_account(
        self, tenant_id: UUID, network: str, handle: str, *, now: datetime, until: datetime
    ) -> bool:
        return self.reels.try_lock_account(tenant_id, network, handle, now=now, until=until)

    def finish_account(
        self,
        tenant_id: UUID,
        network: str,
        handle: str,
        *,
        now: datetime,
        status: str,
        http_status: int | None,
        credits: int,
        newest_taken_at: datetime | None,
        lock_until: datetime,
    ) -> None:
        self.reels.finish_account(
            tenant_id,
            network,
            handle,
            now=now,
            status=status,
            http_status=http_status,
            page1=True,
            newest_taken_at=newest_taken_at,
            credits=credits,
            lock_until=lock_until,
        )

    def release_account(
        self, tenant_id: UUID, network: str, handle: str, *, lock_until: datetime
    ) -> None:
        self.reels.release_account(tenant_id, network, handle, lock_until=lock_until)


# ======================================================================================
# Postgres
# ======================================================================================

_TRACKED_COLUMNS = (
    "id, brand_id, network, handle, note, status, refresh_state, refresh_error, "
    "last_snapshot_id, created_at, refresh_started_at, rate_notes, rate_from, rate_currency, "
    "rate_updated_at"
)
_SNAPSHOT_COLUMNS = (
    "id, network, handle, read_at, status, followers, full_name, bio, avatar_url, "
    "is_verified, reels_read"
)


def _tracked(row: Any) -> TrackedCreator:
    return TrackedCreator(**dict(row._mapping))


def _facts(row: Any) -> SnapshotFacts:
    data = dict(row._mapping)
    data["snapshot_id"] = data.pop("id")
    return SnapshotFacts(**data)


class PostgresTrackedCreatorStore:
    """`TrackedCreatorStore` over migrations 0036, 0117 and 0125."""

    def __init__(self) -> None:
        self._reels = PostgresReelRunStore()

    def add(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        *,
        network: str,
        handle: str,
        note: str,
        user_id: UUID | None,
        now: datetime,
    ) -> TrackedCreator:
        with tenant_session(tenant_id) as session:
            row = session.execute(
                text(
                    "INSERT INTO tracked_creators (tenant_id, brand_id, network, handle, note, "
                    "added_by_user_id, created_at, updated_at) VALUES (:tenant, :brand, "
                    ":network, :handle, :note, :user, :now, :now) "
                    "ON CONFLICT ON CONSTRAINT uq_tracked_creator DO UPDATE SET "
                    "status = 'active', archived_at = NULL, updated_at = :now, "
                    "note = CASE WHEN EXCLUDED.note <> '' THEN EXCLUDED.note "
                    f"ELSE tracked_creators.note END RETURNING {_TRACKED_COLUMNS}"
                ),
                {
                    "tenant": tenant_id,
                    "brand": brand_id,
                    "network": network,
                    "handle": handle,
                    "note": note,
                    "user": user_id,
                    "now": now,
                },
            ).one()
            return _tracked(row)

    def get(self, tenant_id: UUID, brand_id: UUID, tracked_id: UUID) -> TrackedCreator | None:
        with tenant_session(tenant_id) as session:
            row = session.execute(
                text(
                    f"SELECT {_TRACKED_COLUMNS} FROM tracked_creators "
                    "WHERE id = :id AND brand_id = :brand"
                ),
                {"id": tracked_id, "brand": brand_id},
            ).first()
            return _tracked(row) if row is not None else None

    def list(
        self, tenant_id: UUID, brand_id: UUID, *, include_archived: bool = False
    ) -> list[TrackedCreator]:
        where = "" if include_archived else " AND status = 'active'"
        with tenant_session(tenant_id) as session:
            rows = session.execute(
                text(
                    f"SELECT {_TRACKED_COLUMNS} FROM tracked_creators WHERE brand_id = :brand"
                    f"{where} ORDER BY created_at, handle"
                ),
                {"brand": brand_id},
            ).all()
            return [_tracked(r) for r in rows]

    def archive(self, tenant_id: UUID, brand_id: UUID, tracked_id: UUID, *, now: datetime) -> bool:
        with tenant_session(tenant_id) as session:
            session.execute(
                text(
                    "UPDATE tracked_creators SET status = 'archived', archived_at = :now, "
                    "updated_at = :now WHERE id = :id AND brand_id = :brand "
                    "AND status = 'active'"
                ),
                {"id": tracked_id, "brand": brand_id, "now": now},
            )
            found = session.execute(
                text("SELECT 1 FROM tracked_creators WHERE id = :id AND brand_id = :brand"),
                {"id": tracked_id, "brand": brand_id},
            ).first()
            return found is not None

    def set_rate(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        tracked_id: UUID,
        *,
        notes: str,
        amount: Decimal | None,
        currency: str | None,
        now: datetime,
    ) -> TrackedCreator | None:
        with tenant_session(tenant_id) as session:
            row = session.execute(
                text(
                    "UPDATE tracked_creators SET rate_notes = :notes, rate_from = :amount, "
                    "rate_currency = :currency, rate_updated_at = :now, updated_at = :now "
                    "WHERE id = :id AND brand_id = :brand AND status = 'active' "
                    f"RETURNING {_TRACKED_COLUMNS}"
                ),
                {
                    "notes": notes,
                    "amount": amount,
                    "currency": currency,
                    "now": now,
                    "id": tracked_id,
                    "brand": brand_id,
                },
            ).first()
            return _tracked(row) if row is not None else None

    @staticmethod
    def _mark(
        session: Any,
        brand_id: UUID,
        tracked_id: UUID,
        *,
        state: str,
        error: str | None,
        now: datetime,
        snapshot_id: UUID | None,
        started: bool,
    ) -> None:
        session.execute(
            text(
                "UPDATE tracked_creators SET refresh_state = :state, refresh_error = :error, "
                "last_snapshot_id = COALESCE(CAST(:snapshot AS uuid), last_snapshot_id), "
                "refresh_started_at = CASE WHEN CAST(:started AS boolean) THEN :now "
                "ELSE refresh_started_at END, updated_at = :now "
                "WHERE id = :id AND brand_id = :brand"
            ),
            {
                "state": state,
                "error": error,
                "snapshot": snapshot_id,
                "started": started,
                "now": now,
                "id": tracked_id,
                "brand": brand_id,
            },
        )

    def mark(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        tracked_id: UUID,
        *,
        state: str,
        error: str | None,
        now: datetime,
        snapshot_id: UUID | None = None,
        started: bool = False,
    ) -> None:
        with tenant_session(tenant_id) as session:
            self._mark(
                session,
                brand_id,
                tracked_id,
                state=state,
                error=error,
                now=now,
                snapshot_id=snapshot_id,
                started=started,
            )

    def latest_snapshot(
        self,
        tenant_id: UUID,
        network: str,
        handle: str,
        *,
        since: datetime,
        statuses: Collection[str],
    ) -> SnapshotFacts | None:
        with tenant_session(tenant_id) as session:
            row = session.execute(
                text(
                    f"SELECT {_SNAPSHOT_COLUMNS} FROM creator_snapshots WHERE network = :network "
                    "AND handle = :handle AND read_at >= :since AND status = ANY(:statuses) "
                    "ORDER BY read_at DESC LIMIT 1"
                ),
                {
                    "network": network,
                    "handle": handle,
                    "since": since,
                    "statuses": list(statuses),
                },
            ).first()
            return _facts(row) if row is not None else None

    def snapshots(self, tenant_id: UUID, ids: Collection[UUID]) -> dict[UUID, SnapshotFacts]:
        if not ids:
            return {}
        with tenant_session(tenant_id) as session:
            rows = session.execute(
                text(f"SELECT {_SNAPSHOT_COLUMNS} FROM creator_snapshots WHERE id = ANY(:ids)"),
                {"ids": list(ids)},
            ).all()
            return {f.snapshot_id: f for f in (_facts(r) for r in rows)}

    def reel_reads(
        self, tenant_id: UUID, snapshot_ids: Collection[UUID]
    ) -> dict[UUID, list[ReelRead]]:
        if not snapshot_ids:
            return {}
        with tenant_session(tenant_id) as session:
            rows = session.execute(
                text(
                    "SELECT r.snapshot_id, r.network, r.reel_id, r.taken_at, r.views, r.likes, "
                    "r.comments, s.handle, p.duration_s, p.counts_hidden, "
                    "p.is_paid_partnership, p.coauthors, p.sound_id, p.sound, "
                    "p.sound_is_original FROM public_reel_reads r "
                    "JOIN creator_snapshots s ON s.id = r.snapshot_id "
                    "LEFT JOIN public_reels p ON p.network = r.network AND p.reel_id = r.reel_id "
                    "WHERE r.snapshot_id = ANY(:ids) ORDER BY r.snapshot_id, r.position"
                ),
                {"ids": list(snapshot_ids)},
            ).all()
        out: dict[UUID, list[ReelRead]] = {sid: [] for sid in snapshot_ids}
        for r in rows:
            sound = r.sound if isinstance(r.sound, dict) else {}
            coauthors = r.coauthors
            out.setdefault(r.snapshot_id, []).append(
                ReelRead(
                    reel_id=r.reel_id,
                    url=reel_url(r.network, r.handle, r.reel_id),
                    taken_at=r.taken_at,
                    duration_s=float(r.duration_s) if r.duration_s is not None else None,
                    views=r.views,
                    likes=r.likes,
                    comments=r.comments,
                    counts_hidden=bool(r.counts_hidden),
                    is_paid_partnership=bool(r.is_paid_partnership),
                    coauthors=tuple(str(c) for c in coauthors)
                    if isinstance(coauthors, list)
                    else None,
                    sound_id=r.sound_id,
                    sound_title=str(sound.get("title") or ""),
                    sound_is_original=r.sound_is_original,
                )
            )
        return out

    def save_read(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        tracked_id: UUID,
        *,
        snapshot: NewSnapshot,
        reads: Sequence[NewReelRead],
        reels: Sequence[PublicReel],
        creator: CreatorFacts,
        link: bool,
        state: str,
        error: str | None,
        now: datetime,
    ) -> None:
        with tenant_session(tenant_id) as session:
            session.execute(
                text(
                    "INSERT INTO creator_snapshots (id, network, handle, read_at, status, "
                    "followers, following, posts_count, full_name, bio, category, external_url, "
                    "avatar_url, is_verified, is_private, reels_target, reels_read, pages_read, "
                    "oldest_taken_at, newest_taken_at, credits, profile_payload_id, "
                    "profile_payload_fetched_at, parser_version) VALUES (:id, :network, "
                    ":handle, :read_at, :status, :followers, :following, :posts_count, "
                    ":full_name, :bio, :category, :external_url, :avatar_url, :is_verified, "
                    ":is_private, :reels_target, :reels_read, :pages_read, :oldest_taken_at, "
                    ":newest_taken_at, :credits, :profile_payload_id, "
                    ":profile_payload_fetched_at, :parser_version)"
                ),
                {name: getattr(snapshot, name) for name in NewSnapshot.__dataclass_fields__},
            )
            if reads:
                session.execute(
                    text(
                        "INSERT INTO public_reel_reads (snapshot_id, network, reel_id, position, "
                        "taken_at, views, likes, comments, saves, shares, source_payload_id, "
                        "source_payload_fetched_at, parser_version) VALUES (:snapshot_id, "
                        ":network, :reel_id, :position, :taken_at, :views, :likes, :comments, "
                        ":saves, :shares, :source_payload_id, :source_payload_fetched_at, "
                        ":parser_version)"
                    ),
                    [
                        {name: getattr(r, name) for name in NewReelRead.__dataclass_fields__}
                        for r in reads
                    ],
                )
            upsert_reels_in(session, reels)
            upsert_creators_in(session, [creator])
            self._mark(
                session,
                brand_id,
                tracked_id,
                state=state,
                error=error,
                now=now,
                snapshot_id=snapshot.id if link else None,
                started=False,
            )
        # m-25026377: the read has committed; the hashtag catalog runs in its own
        # transaction, best effort — as `PostgresReelRunStore.upsert_reels` does
        capture_reel_hashtags(tenant_id, reels, self._reels.hashtag_repository)

    def put_payload(
        self,
        tenant_id: UUID,
        path: str,
        params: Mapping[str, Any],
        payload: Mapping[str, Any],
        *,
        status: int,
        credits: int,
        now: datetime,
    ) -> CachedPayload:
        return PostgresCreatorPoolRepository(tenant_id).put_payload(
            path, params, payload, status=status, credits_charged=credits, now=now
        )

    def try_lock_account(
        self, tenant_id: UUID, network: str, handle: str, *, now: datetime, until: datetime
    ) -> bool:
        return self._reels.try_lock_account(tenant_id, network, handle, now=now, until=until)

    def finish_account(
        self,
        tenant_id: UUID,
        network: str,
        handle: str,
        *,
        now: datetime,
        status: str,
        http_status: int | None,
        credits: int,
        newest_taken_at: datetime | None,
        lock_until: datetime,
    ) -> None:
        self._reels.finish_account(
            tenant_id,
            network,
            handle,
            now=now,
            status=status,
            http_status=http_status,
            page1=True,
            newest_taken_at=newest_taken_at,
            credits=credits,
            lock_until=lock_until,
        )

    def release_account(
        self, tenant_id: UUID, network: str, handle: str, *, lock_until: datetime
    ) -> None:
        self._reels.release_account(tenant_id, network, handle, lock_until=lock_until)


__all__ = [
    "SNAPSHOT_SETTLED",
    "SNAPSHOT_WITH_DATA",
    "MemoryTrackedCreatorStore",
    "NewReelRead",
    "NewSnapshot",
    "PostgresTrackedCreatorStore",
    "TrackedCreator",
    "TrackedCreatorStore",
    "REFRESH_STUCK_AFTER",
    "reel_url",
    "refresh_stuck",
]

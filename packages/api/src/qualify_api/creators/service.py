"""The Creators module's facade — the ONLY module the Reflex screen imports
(m-24946121, m-24946127; `docs/diseno-modulo-creadores.md` §10).

Every function takes the `tenant_id` and `brand_id` of the server-side session (ADR 43:
the sealed business), never values from the browser, and raises `CreatorsDisabled` when
the business does not have the module (§11 — checked here again: the screen is not the
security boundary). Only `refresh_creator` reaches the network (and pays); the rest
read Postgres and are cheap enough to call when a screen opens.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from qualify_api.creators import access
from qualify_api.creators.metrics import (
    STALE_DAYS,
    AudioUse,
    ComparedCreator,
    CompareEntry,
    Comparison,
    ComparisonRow,
    CreatorSheet,
    DurationBucket,
    MetricStatus,
    MetricValue,
    ReelCard,
    ReelRead,
    build_sheet,
    compare,
    engagement_rate,
    freshness_days,
    median_views,
)
from qualify_api.creators.snapshots import (
    CreatorNotFound,
    RefreshOutcome,
    RefreshStatus,
)
from qualify_api.creators.snapshots import refresh_creator as _refresh
from qualify_api.creators.tracking import (
    PostgresTrackedCreatorStore,
    TrackedCreator,
    TrackedCreatorStore,
)


class CreatorsDisabled(Exception):
    """The business does not have the module (§11)."""


class InvalidHandle(ValueError):
    """Empty, with spaces, over 30 characters, or characters outside [a-z0-9._]."""


class UnsupportedNetwork(ValueError):
    """Delivery 1 reads Instagram only (TikTok waits for G-JOIN, ADR 33 (d))."""


class TooManyToCompare(ValueError):
    """Comparing takes 2 to 4 creators."""


class NotReadYet(CreatorNotFound):
    """A creator in a comparison has no read yet."""


@dataclass(frozen=True)
class CreatorCard:
    """One row of the list."""

    tracked: TrackedCreator
    full_name: str
    avatar_url: str
    followers: int | None
    median_views: MetricValue
    engagement_rate: MetricValue
    read_at: datetime | None
    stale: bool


NETWORKS = ("instagram",)
MAX_HANDLE = 30
COMPARE_MIN = 2
COMPARE_MAX = 4
_HANDLE_RE = re.compile(r"^[a-z0-9._]+$")
_INSTAGRAM_HOSTS = ("instagram.com", "www.instagram.com", "m.instagram.com")

_store: TrackedCreatorStore | None = None


def configure_store(store: TrackedCreatorStore | None) -> None:
    """Install where the module keeps its rows (`None` = Postgres, the default). Tests
    install a `MemoryTrackedCreatorStore`."""
    global _store
    _store = store


def _the_store() -> TrackedCreatorStore:
    global _store
    if _store is None:
        _store = PostgresTrackedCreatorStore()
    return _store


def _now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(UTC)
    return now if now.tzinfo else now.replace(tzinfo=UTC)


def creators_enabled(tenant_id: UUID) -> bool:
    return access.creators_enabled(tenant_id)


def _require(tenant_id: UUID) -> None:
    if not access.creators_enabled(tenant_id):
        raise CreatorsDisabled(str(tenant_id))


def normalize_handle(raw: str) -> str:
    """'@x', 'x' or the profile's URL (with or without scheme, query or trailing slash)
    → 'x', lowercase. Raises `InvalidHandle`."""
    value = (raw or "").strip()
    if "instagram.com" in value.lower():
        url = value if "://" in value else f"https://{value}"
        parts = urlsplit(url)
        if (parts.hostname or "").lower() not in _INSTAGRAM_HOSTS:
            raise InvalidHandle(raw)
        segments = [s for s in parts.path.split("/") if s]
        if len(segments) != 1:
            raise InvalidHandle(raw)
        value = segments[0]
    value = value.lstrip("@").lower()
    if not value or len(value) > MAX_HANDLE or not _HANDLE_RE.match(value):
        raise InvalidHandle(raw)
    return value


def add_creator(
    tenant_id: UUID,
    brand_id: UUID,
    handle: str,
    *,
    user_id: UUID,
    network: str = "instagram",
    note: str = "",
) -> TrackedCreator:
    """Normalize the handle (accepts '@x', 'x' and the profile URL), keep it (idempotent;
    reactivates an archived one) and do NOT pay: the screen calls `refresh_creator`
    right after, in the background."""
    _require(tenant_id)
    if network not in NETWORKS:
        raise UnsupportedNetwork(network)
    return _the_store().add(
        tenant_id,
        brand_id,
        network=network,
        handle=normalize_handle(handle),
        note=note.strip(),
        user_id=user_id,
        now=_now(None),
    )


def list_creators(
    tenant_id: UUID,
    brand_id: UUID,
    *,
    include_archived: bool = False,
    now: datetime | None = None,
) -> list[CreatorCard]:
    _require(tenant_id)
    at = _now(now)
    store = _the_store()
    tracked = store.list(tenant_id, brand_id, include_archived=include_archived)
    ids = [t.last_snapshot_id for t in tracked if t.last_snapshot_id is not None]
    snapshots = store.snapshots(tenant_id, ids)
    reads = store.reel_reads(tenant_id, list(snapshots))
    cards: list[CreatorCard] = []
    for t in tracked:
        snap = snapshots.get(t.last_snapshot_id) if t.last_snapshot_id else None
        if snap is None:
            cards.append(
                CreatorCard(
                    tracked=t,
                    full_name="",
                    avatar_url="",
                    followers=None,
                    median_views=MetricValue("median_views", None, "unknown", 0),
                    engagement_rate=MetricValue("engagement_rate", None, "unknown", 0),
                    read_at=None,
                    stale=False,
                )
            )
            continue
        reels = reads.get(snap.snapshot_id, [])
        cards.append(
            CreatorCard(
                tracked=t,
                full_name=snap.full_name,
                avatar_url=snap.avatar_url,
                followers=snap.followers,
                median_views=median_views(reels, snap.read_at),
                engagement_rate=engagement_rate(reels, snap.read_at),
                read_at=snap.read_at,
                stale=freshness_days(snap.read_at, at) >= STALE_DAYS,
            )
        )
    return cards


def archive_creator(tenant_id: UUID, brand_id: UUID, tracked_id: UUID) -> None:
    """«Quitar de la lista»: archive (idempotent). Raises `CreatorNotFound` for an id that
    is not this brand's."""
    _require(tenant_id)
    if not _the_store().archive(tenant_id, brand_id, tracked_id, now=_now(None)):
        raise CreatorNotFound(str(tracked_id))


def refresh_creator(
    tenant_id: UUID,
    brand_id: UUID,
    tracked_id: UUID,
    *,
    now: datetime | None = None,
    client: httpx.Client | None = None,
) -> RefreshOutcome:
    """The only paid call of the module (§8.3). Raises `CreatorNotFound` when the creator
    is not this brand's or is archived."""
    _require(tenant_id)
    return _refresh(
        tenant_id,
        brand_id,
        tracked_id,
        store=_the_store(),
        now=_now(now) if now is not None else None,
        client=client,
    )


def creator_sheet(
    tenant_id: UUID, brand_id: UUID, tracked_id: UUID, *, now: datetime | None = None
) -> CreatorSheet | None:
    """The creator's sheet from its current read; None = not read yet. Raises
    `CreatorNotFound` for an id that is not this brand's."""
    _require(tenant_id)
    store = _the_store()
    tracked = store.get(tenant_id, brand_id, tracked_id)
    if tracked is None:
        raise CreatorNotFound(str(tracked_id))
    if tracked.last_snapshot_id is None:
        return None
    snap = store.snapshots(tenant_id, [tracked.last_snapshot_id]).get(tracked.last_snapshot_id)
    if snap is None:
        return None
    reels = store.reel_reads(tenant_id, [snap.snapshot_id]).get(snap.snapshot_id, [])
    return build_sheet(tracked.id, snap, reels, now=_now(now))


def compare_creators(
    tenant_id: UUID,
    brand_id: UUID,
    tracked_ids: Sequence[UUID],
    *,
    now: datetime | None = None,
) -> Comparison:
    """2-4 creators side by side over one window (§9.3). Raises `TooManyToCompare`
    outside 2..4 (repeated ids count once), `CreatorNotFound` for an id that is not this
    brand's, and `NotReadYet` for one without a read."""
    _require(tenant_id)
    ids = list(dict.fromkeys(tracked_ids))
    if not COMPARE_MIN <= len(ids) <= COMPARE_MAX:
        raise TooManyToCompare(str(len(ids)))
    store = _the_store()
    tracked: list[TrackedCreator] = []
    for tracked_id in ids:
        found = store.get(tenant_id, brand_id, tracked_id)
        if found is None:
            raise CreatorNotFound(str(tracked_id))
        if found.last_snapshot_id is None:
            raise NotReadYet(str(tracked_id))
        tracked.append(found)
    snapshot_ids = [t.last_snapshot_id for t in tracked if t.last_snapshot_id is not None]
    snapshots = store.snapshots(tenant_id, snapshot_ids)
    reads = store.reel_reads(tenant_id, list(snapshots))
    entries: list[CompareEntry] = []
    for t in tracked:
        snap = snapshots.get(t.last_snapshot_id) if t.last_snapshot_id else None
        if snap is None:
            raise NotReadYet(str(t.id))
        entries.append(CompareEntry(t.id, snap, reads.get(snap.snapshot_id, [])))
    return compare(entries, now=_now(now))


__all__ = [
    "AudioUse",
    "Comparison",
    "ComparedCreator",
    "ComparisonRow",
    "CreatorCard",
    "CreatorNotFound",
    "CreatorSheet",
    "CreatorsDisabled",
    "DurationBucket",
    "InvalidHandle",
    "MetricStatus",
    "MetricValue",
    "NotReadYet",
    "ReelCard",
    "ReelRead",
    "RefreshOutcome",
    "RefreshStatus",
    "TooManyToCompare",
    "TrackedCreator",
    "UnsupportedNetwork",
    "add_creator",
    "archive_creator",
    "compare_creators",
    "configure_store",
    "creator_sheet",
    "creators_enabled",
    "list_creators",
    "normalize_handle",
    "refresh_creator",
]

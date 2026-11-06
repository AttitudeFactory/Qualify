"""The Creators module's facade — the ONLY module the Reflex screen imports
(m-24946121, m-24946127; `docs/diseno-modulo-creadores.md` §10).

Every function takes the `tenant_id` and `brand_id` of the server-side session (ADR 43:
the sealed business), never values from the browser, and raises `CreatorsDisabled` when
the business does not have the module (§11 — checked here again: the screen is not the
security boundary). Only `refresh_creator` reaches the network (and pays); the rest
read Postgres and are cheap enough to call when a screen opens. `set_creator_rate`
(m-24955847) only writes the owner's own words and prices: no vendor, no credits.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
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
from qualify_api.creators.rates import (
    RATE_CURRENCIES,
    InvalidRate,
    currency_mark_in,
    parse_rate_amount,
    validate_rate,
)
from qualify_api.creators.snapshots import (
    CreatorNotFound,
    RefreshOutcome,
    RefreshStatus,
)
from qualify_api.creators.snapshots import refresh_creator as _refresh
from qualify_api.creators.tracking import (
    REFRESH_FAILED,
    REFRESH_STUCK_AFTER,
    PostgresTrackedCreatorStore,
    TrackedCreator,
    TrackedCreatorStore,
    refresh_stuck,
)
from qualify_api.tenancy.locale import read_business_locale


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
    → 'x', lowercase. Raises `InvalidHandle`.

    A link is told by its SHAPE — a scheme, a "/" (a handle never has one) or a leading
    "www." — never by looking for "instagram.com" in the text (CodeQL «incomplete URL
    substring sanitization», m-24952459). Its host must then be one of
    `_INSTAGRAM_HOSTS` exactly, with exactly one path segment: the handle."""
    value = (raw or "").strip()
    if "://" in value or "/" in value or value.lower().startswith("www."):
        url = value if "://" in value else f"https://{value}"
        try:
            parts = urlsplit(url)
            host = (parts.hostname or "").lower()
        except ValueError as exc:  # a malformed netloc (e.g. a bad port or IPv6 literal)
            raise InvalidHandle(raw) from exc
        if parts.scheme.lower() not in ("http", "https") or host not in _INSTAGRAM_HOSTS:
            raise InvalidHandle(raw)
        segments = [s for s in parts.path.split("/") if s]
        if len(segments) != 1:
            raise InvalidHandle(raw)
        value = segments[0]
    value = value.lstrip("@").lower()
    # dots are legal in a handle: a bare «instagram.com» is a host, not someone to read
    if value in _INSTAGRAM_HOSTS:
        raise InvalidHandle(raw)
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
    # a read that died mid-way (crash, restart) is shown as failed, never «reading» forever
    tracked = [
        replace(t, refresh_state=REFRESH_FAILED, refresh_error="error")
        if refresh_stuck(t, at)
        else t
        for t in store.list(tenant_id, brand_id, include_archived=include_archived)
    ]
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
    return replace(
        build_sheet(tracked.id, snap, reels, now=_now(now)),
        rate_notes=tracked.rate_notes,
        rate_from=tracked.rate_from,
        rate_currency=tracked.rate_currency,
        rate_updated_at=tracked.rate_updated_at,
    )


def business_currency(tenant_id: UUID) -> str:
    """The business's own currency (Configuración, `tenants.currency`; Venezuela starts in
    dollars), to preselect when the owner writes a creator's price. «COP» when the
    business has none the rates accept."""
    _require(tenant_id)
    locale = read_business_locale(tenant_id)
    currency = (locale.currency if locale is not None else "").strip().upper()
    return currency if currency in RATE_CURRENCIES else "COP"


def set_creator_rate(
    tenant_id: UUID,
    brand_id: UUID,
    tracked_creator_id: UUID,
    *,
    notes: str,
    amount: Decimal | None,
    currency: str | None,
    currency_mark: str | None = None,
    now: datetime | None = None,
) -> TrackedCreator:
    """Save what the creator charges (m-24955847): the owner's notes (stripped, at most
    1,000 characters) and the «Desde» price with its currency — replaces the previous
    ones and stamps `rate_updated_at`. `amount=None` clears the price (the currency goes
    with it); empty notes clear the notes. Validates before opening a transaction:
    raises `InvalidRate` (`notes_too_long`, `currency_required`, `unsupported_currency`,
    `currency_mismatch`, `cents_not_allowed`, `negative`, `too_large`, `not_a_number`),
    and `CreatorNotFound` when the creator is not this brand's or is archived (like
    `refresh_creator`). ``currency_mark`` is `currency_mark_in(<what the owner typed>)`:
    a currency written next to the amount must be the chosen one. No vendor call, no
    credits.
    """
    _require(tenant_id)
    rate = validate_rate(notes, amount, currency, currency_mark=currency_mark)
    saved = _the_store().set_rate(
        tenant_id,
        brand_id,
        tracked_creator_id,
        notes=rate.notes,
        amount=rate.amount,
        currency=rate.currency,
        now=_now(now),
    )
    if saved is None:
        raise CreatorNotFound(str(tracked_creator_id))
    return saved


def compare_creators(
    tenant_id: UUID,
    brand_id: UUID,
    tracked_ids: Sequence[UUID],
    *,
    now: datetime | None = None,
) -> Comparison:
    """2-4 creators side by side, each on his own latest N reels (§9.3). Raises `TooManyToCompare`
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
        entries.append(
            CompareEntry(
                t.id,
                snap,
                reads.get(snap.snapshot_id, []),
                rate_from=t.rate_from,
                rate_currency=t.rate_currency,
                rate_notes=t.rate_notes,
            )
        )
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
    "InvalidRate",
    "MetricStatus",
    "MetricValue",
    "NotReadYet",
    "ReelCard",
    "RATE_CURRENCIES",
    "ReelRead",
    "REFRESH_STUCK_AFTER",
    "RefreshOutcome",
    "RefreshStatus",
    "TooManyToCompare",
    "TrackedCreator",
    "UnsupportedNetwork",
    "add_creator",
    "archive_creator",
    "business_currency",
    "compare_creators",
    "configure_store",
    "creator_sheet",
    "creators_enabled",
    "currency_mark_in",
    "list_creators",
    "normalize_handle",
    "parse_rate_amount",
    "refresh_creator",
    "refresh_stuck",
    "set_creator_rate",
]

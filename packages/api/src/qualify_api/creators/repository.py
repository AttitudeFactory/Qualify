"""The shared creator pool (migration 0036): the vendor's answers with a time to live,
every public account the searches have seen, and which search saw it. Read and written
through `tenant_session` — the sanctioned door — for its role and pooling only: none of
these tables carry a tenant, and one tenant's search serves the next."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from qualify_api.creators.models import (
    NETWORKS,
    SIGHTING_KINDS,
    Creator,
    CreatorSighting,
    VendorPayload,
)

VENDOR = "scrapecreators"
#: How long an answer serves the next search: a search page or a Google query for a
#: week (the same week a stored phase lives), a profile read for 30 days (what the
#: vendor's own cache keeps, and the window the follower count is good for).
SEARCH_TTL = timedelta(days=7)
PROFILE_TTL = timedelta(days=30)


def normalize_handle(handle: str) -> str:
    return handle.strip().lstrip("@").lower()


def params_key(params: Mapping[str, Any]) -> str:
    """One spelling of a call's parameters, whatever their order."""
    return json.dumps({k: str(v) for k, v in sorted(params.items())}, ensure_ascii=False)


def payload_ttl(path: str) -> timedelta:
    return PROFILE_TTL if "/profile" in path else SEARCH_TTL


def _moment(value: datetime | float | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.fromtimestamp(float(value), tz=UTC)


@dataclass(frozen=True)
class CachedPayload:
    path: str
    params_key: str
    status: int
    payload: dict[str, Any]
    fetched_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class CreatorFacts:
    """One account as the pool keeps it — what a search knows after seeing it."""

    network: str
    handle: str
    full_name: str = ""
    bio: str = ""
    external_url: str = ""
    profile_url: str = ""
    avatar_url: str = ""
    category: str = ""
    country_code: str = ""
    followers: int | None = None
    total_likes: int | None = None
    is_private: bool = False
    is_verified: bool = False
    missing: bool = False
    related: tuple[str, ...] = ()
    hashtags: tuple[str, ...] = ()
    posts_seen: int = 0
    ai_posts_seen: int = 0
    likes_seen: int = 0
    comments_seen: int = 0
    views_seen: int = 0
    #: When a profile read backed these facts; None for an account only seen on a feed.
    read_at: datetime | None = None
    seen_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.network not in NETWORKS:
            raise ValueError(f"network must be one of {NETWORKS}, got {self.network!r}")
        handle = normalize_handle(self.handle)
        if not handle:
            raise ValueError("handle must not be empty")
        if self.ai_posts_seen > self.posts_seen:
            raise ValueError("ai_posts_seen cannot exceed posts_seen")
        object.__setattr__(self, "handle", handle)
        object.__setattr__(self, "related", tuple(self.related))
        object.__setattr__(self, "hashtags", tuple(self.hashtags))
        object.__setattr__(self, "seen_at", _moment(self.seen_at))
        if self.read_at is not None:
            object.__setattr__(self, "read_at", _moment(self.read_at))


@dataclass(frozen=True)
class Sighting:
    network: str
    handle: str
    kind: str
    term: str
    country_code: str = ""
    city_slug: str = ""
    seen_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.network not in NETWORKS:
            raise ValueError(f"network must be one of {NETWORKS}, got {self.network!r}")
        if self.kind not in SIGHTING_KINDS:
            raise ValueError(f"kind must be one of {SIGHTING_KINDS}, got {self.kind!r}")
        handle = normalize_handle(self.handle)
        if not handle or not self.term:
            raise ValueError("handle and term must not be empty")
        object.__setattr__(self, "handle", handle)
        object.__setattr__(self, "seen_at", _moment(self.seen_at))


class CreatorPoolRepository(Protocol):
    def get_payload(
        self, path: str, params: Mapping[str, Any], *, now: datetime | float | None = None
    ) -> CachedPayload | None: ...

    def put_payload(
        self,
        path: str,
        params: Mapping[str, Any],
        payload: Mapping[str, Any],
        *,
        status: int = 200,
        credits_charged: int = 0,
        now: datetime | float | None = None,
    ) -> CachedPayload: ...

    def upsert_creators(self, rows: Sequence[CreatorFacts]) -> int: ...

    def record_sightings(self, rows: Sequence[Sighting]) -> int: ...

    def creator(self, network: str, handle: str) -> CreatorFacts | None: ...

    def seen_for(
        self, kind: str, term: str, *, since: datetime | float | None = None, limit: int = 200
    ) -> list[CreatorFacts]: ...


def _facts_from_row(row: Creator) -> CreatorFacts:
    return CreatorFacts(
        network=row.network,
        handle=row.handle,
        full_name=row.full_name,
        bio=row.bio,
        external_url=row.external_url,
        profile_url=row.profile_url,
        avatar_url=row.avatar_url,
        category=row.category,
        country_code=row.country_code,
        followers=row.followers,
        total_likes=row.total_likes,
        is_private=row.is_private,
        is_verified=row.is_verified,
        missing=row.missing,
        related=tuple(row.related or ()),
        hashtags=tuple(row.hashtags or ()),
        posts_seen=row.posts_seen,
        ai_posts_seen=row.ai_posts_seen,
        likes_seen=row.likes_seen,
        comments_seen=row.comments_seen,
        views_seen=row.views_seen,
        read_at=row.read_at,
        seen_at=row.seen_at,
    )


def _merge(old: CreatorFacts | None, new: CreatorFacts) -> CreatorFacts:
    """What the pool keeps when an account is seen again: a profile read refreshes
    everything it carries; a feed sighting only refreshes the feed figures and fills
    what was empty — it never blanks a bio a read brought."""
    if old is None:
        return new
    read = new.read_at is not None
    pick = lambda fresh, kept: fresh if (read or not kept) else kept  # noqa: E731
    return CreatorFacts(
        network=new.network,
        handle=new.handle,
        full_name=pick(new.full_name, old.full_name),
        bio=pick(new.bio, old.bio),
        external_url=pick(new.external_url, old.external_url),
        profile_url=new.profile_url or old.profile_url,
        avatar_url=pick(new.avatar_url, old.avatar_url),
        category=pick(new.category, old.category),
        country_code=new.country_code or old.country_code,
        # a count is never blanked: a read without one (a 404) keeps the last one known
        followers=new.followers if new.followers is not None else old.followers,
        total_likes=new.total_likes if new.total_likes is not None else old.total_likes,
        is_private=new.is_private if read else (old.is_private or new.is_private),
        is_verified=old.is_verified or new.is_verified,
        missing=new.missing if read else old.missing,
        related=new.related if (read or new.related) else old.related,
        hashtags=tuple(dict.fromkeys([*old.hashtags, *new.hashtags])),
        posts_seen=new.posts_seen or old.posts_seen,
        ai_posts_seen=new.ai_posts_seen if new.posts_seen else old.ai_posts_seen,
        likes_seen=new.likes_seen or old.likes_seen,
        comments_seen=new.comments_seen or old.comments_seen,
        views_seen=new.views_seen or old.views_seen,
        read_at=new.read_at or old.read_at,
        seen_at=max(new.seen_at or old.seen_at, old.seen_at),  # type: ignore[type-var]
    )


@dataclass
class MemoryCreatorPoolRepository:
    """The same contract in memory (tests, offline runs)."""

    payloads: dict[tuple[str, str], CachedPayload] = field(default_factory=dict)
    creators: dict[tuple[str, str], CreatorFacts] = field(default_factory=dict)
    sightings: dict[tuple[str, str, str, str, str, str], Sighting] = field(default_factory=dict)

    def get_payload(
        self, path: str, params: Mapping[str, Any], *, now: datetime | float | None = None
    ) -> CachedPayload | None:
        hit = self.payloads.get((path, params_key(params)))
        if hit is None or hit.expires_at <= _moment(now):
            return None
        return hit

    def put_payload(
        self,
        path: str,
        params: Mapping[str, Any],
        payload: Mapping[str, Any],
        *,
        status: int = 200,
        credits_charged: int = 0,
        now: datetime | float | None = None,
    ) -> CachedPayload:
        fetched = _moment(now)
        entry = CachedPayload(
            path, params_key(params), status, dict(payload), fetched, fetched + payload_ttl(path)
        )
        self.payloads[(path, entry.params_key)] = entry
        return entry

    def upsert_creators(self, rows: Sequence[CreatorFacts]) -> int:
        for row in rows:
            key = (row.network, row.handle)
            self.creators[key] = _merge(self.creators.get(key), row)
        return len(rows)

    def record_sightings(self, rows: Sequence[Sighting]) -> int:
        for row in rows:
            key = (row.network, row.handle, row.kind, row.term, row.country_code, row.city_slug)
            self.sightings[key] = row
        return len(rows)

    def creator(self, network: str, handle: str) -> CreatorFacts | None:
        return self.creators.get((network, normalize_handle(handle)))

    def seen_for(
        self, kind: str, term: str, *, since: datetime | float | None = None, limit: int = 200
    ) -> list[CreatorFacts]:
        floor = _moment(since) if since is not None else None
        keys = [
            (s.network, s.handle)
            for s in self.sightings.values()
            if s.kind == kind and s.term == term and (floor is None or s.seen_at >= floor)  # type: ignore[operator]
        ]
        found = [self.creators[k] for k in dict.fromkeys(keys) if k in self.creators]
        found.sort(key=lambda c: c.followers or 0, reverse=True)
        return found[:limit]


class PostgresCreatorPoolRepository:
    """`tenant_session` for the role and the pool; the tables themselves are global."""

    def __init__(self, tenant_id: UUID) -> None:
        self.tenant_id = tenant_id

    def get_payload(
        self, path: str, params: Mapping[str, Any], *, now: datetime | float | None = None
    ) -> CachedPayload | None:
        key = params_key(params)
        stmt = select(VendorPayload).where(
            VendorPayload.vendor == VENDOR,
            VendorPayload.path == path,
            VendorPayload.params_key == key,
            VendorPayload.expires_at > _moment(now),
        )
        with tenant_session(self.tenant_id) as session:
            row = session.scalars(stmt).first()
            if row is None:
                return None
            session.execute(
                update(VendorPayload)
                .where(VendorPayload.id == row.id)
                .values(hits=VendorPayload.hits + 1)
            )
            return CachedPayload(
                row.path,
                row.params_key,
                row.status,
                dict(row.payload),
                row.fetched_at,
                row.expires_at,
            )

    def put_payload(
        self,
        path: str,
        params: Mapping[str, Any],
        payload: Mapping[str, Any],
        *,
        status: int = 200,
        credits_charged: int = 0,
        now: datetime | float | None = None,
    ) -> CachedPayload:
        fetched = _moment(now)
        entry = CachedPayload(
            path, params_key(params), status, dict(payload), fetched, fetched + payload_ttl(path)
        )
        values = {
            "vendor": VENDOR,
            "path": path,
            "params_key": entry.params_key,
            "status": status,
            "payload": entry.payload,
            "credits_charged": credits_charged,
            "fetched_at": fetched,
            "expires_at": entry.expires_at,
            "hits": 0,
            "updated_at": fetched,
        }
        stmt = insert(VendorPayload).values(**values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_vendor_payload",
            set_={k: v for k, v in values.items() if k not in ("vendor", "path", "params_key")},
        )
        with tenant_session(self.tenant_id) as session:
            session.execute(stmt)
        return entry

    def upsert_creators(self, rows: Sequence[CreatorFacts]) -> int:
        if not rows:
            return 0
        with tenant_session(self.tenant_id) as session:
            for row in rows:
                existing = session.scalars(
                    select(Creator).where(
                        Creator.network == row.network, Creator.handle == row.handle
                    )
                ).first()
                merged = _merge(_facts_from_row(existing) if existing else None, row)
                values = {
                    "full_name": merged.full_name,
                    "bio": merged.bio,
                    "external_url": merged.external_url,
                    "profile_url": merged.profile_url,
                    "avatar_url": merged.avatar_url,
                    "category": merged.category,
                    "country_code": merged.country_code,
                    "followers": merged.followers,
                    "total_likes": merged.total_likes,
                    "is_private": merged.is_private,
                    "is_verified": merged.is_verified,
                    "missing": merged.missing,
                    "related": list(merged.related),
                    "hashtags": list(merged.hashtags),
                    "posts_seen": merged.posts_seen,
                    "ai_posts_seen": merged.ai_posts_seen,
                    "likes_seen": merged.likes_seen,
                    "comments_seen": merged.comments_seen,
                    "views_seen": merged.views_seen,
                    "read_at": merged.read_at,
                    "seen_at": merged.seen_at,
                    "updated_at": _moment(None),
                }
                if existing is None:
                    session.add(Creator(network=row.network, handle=row.handle, **values))
                else:
                    for name, value in values.items():
                        setattr(existing, name, value)
        return len(rows)

    def record_sightings(self, rows: Sequence[Sighting]) -> int:
        if not rows:
            return 0
        with tenant_session(self.tenant_id) as session:
            for row in rows:
                stmt = insert(CreatorSighting).values(
                    network=row.network,
                    handle=row.handle,
                    kind=row.kind,
                    term=row.term,
                    country_code=row.country_code,
                    city_slug=row.city_slug,
                    seen_at=row.seen_at,
                )
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_sighting",
                    set_={"seen_at": row.seen_at, "times": CreatorSighting.times + 1},
                )
                session.execute(stmt)
        return len(rows)

    def creator(self, network: str, handle: str) -> CreatorFacts | None:
        stmt = select(Creator).where(
            Creator.network == network, Creator.handle == normalize_handle(handle)
        )
        with tenant_session(self.tenant_id) as session:
            row = session.scalars(stmt).first()
            return _facts_from_row(row) if row else None

    def seen_for(
        self, kind: str, term: str, *, since: datetime | float | None = None, limit: int = 200
    ) -> list[CreatorFacts]:
        stmt = (
            select(Creator)
            .join(
                CreatorSighting,
                (CreatorSighting.network == Creator.network)
                & (CreatorSighting.handle == Creator.handle),
            )
            .where(CreatorSighting.kind == kind, CreatorSighting.term == term)
            .order_by(Creator.followers.desc().nulls_last())
            .limit(limit)
        )
        if since is not None:
            stmt = stmt.where(CreatorSighting.seen_at >= _moment(since))
        with tenant_session(self.tenant_id) as session:
            seen: dict[tuple[str, str], CreatorFacts] = {}
            for row in session.scalars(stmt):
                seen.setdefault((row.network, row.handle), _facts_from_row(row))
            return list(seen.values())

"""The creator read history: every profile and post read kept as a row (migration 0034),
so that a series exists to compute growth from. Append-only; the readers hand back the
series ordered by `fetched_at`."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.growth.models import PLATFORMS, SOURCES, CreatorPostRead, CreatorRead


def normalize_handle(handle: str) -> str:
    return handle.strip().lstrip("@").lower()


def _check(platform: str, handle: str) -> tuple[str, str]:
    if platform not in PLATFORMS:
        raise ValueError(f"platform must be one of {PLATFORMS}, got {platform!r}")
    normalized = normalize_handle(handle)
    if not normalized:
        raise ValueError("handle must not be empty")
    return platform, normalized


def _moment(value: datetime | float | int) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.fromtimestamp(float(value), tz=UTC)


@dataclass(frozen=True)
class ProfileRead:
    """A creator's figures at one moment."""

    platform: str
    handle: str
    fetched_at: datetime
    source: str = "profile"
    followers: int | None = None
    following: int | None = None
    posts_count: int | None = None
    total_likes: int | None = None

    def __post_init__(self) -> None:
        platform, handle = _check(self.platform, self.handle)
        if self.source not in SOURCES:
            raise ValueError(f"source must be one of {SOURCES}, got {self.source!r}")
        object.__setattr__(self, "platform", platform)
        object.__setattr__(self, "handle", handle)
        object.__setattr__(self, "fetched_at", _moment(self.fetched_at))


@dataclass(frozen=True)
class PostRead:
    """One post's counters at one moment, plus the platform's AI label as read then."""

    platform: str
    handle: str
    post_id: str
    taken_at: datetime
    fetched_at: datetime
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    ai_generated: bool | None = None
    ai_label: str = ""
    ai_source: str = ""

    def __post_init__(self) -> None:
        platform, handle = _check(self.platform, self.handle)
        if not self.post_id:
            raise ValueError("post_id must not be empty")
        object.__setattr__(self, "platform", platform)
        object.__setattr__(self, "handle", handle)
        object.__setattr__(self, "taken_at", _moment(self.taken_at))
        object.__setattr__(self, "fetched_at", _moment(self.fetched_at))

    @property
    def interactions(self) -> int:
        return (self.likes or 0) + (self.comments or 0) + (self.shares or 0)


@dataclass(frozen=True)
class FollowerPoint:
    at: datetime
    followers: int


class GrowthRepository(Protocol):
    def record(
        self, tenant_id: UUID, reads: Sequence[ProfileRead], posts: Sequence[PostRead] = ()
    ) -> None: ...

    def follower_series(
        self, tenant_id: UUID, platform: str, handle: str, *, since: datetime | None = None
    ) -> list[FollowerPoint]: ...

    def post_reads(
        self, tenant_id: UUID, platform: str, handle: str, *, since: datetime | None = None
    ) -> list[PostRead]: ...


@dataclass
class MemoryGrowthRepository:
    """The same contract in memory (tests, offline runs)."""

    reads: dict[UUID, list[ProfileRead]] = field(default_factory=dict)
    posts: dict[UUID, list[PostRead]] = field(default_factory=dict)

    def record(
        self, tenant_id: UUID, reads: Sequence[ProfileRead], posts: Sequence[PostRead] = ()
    ) -> None:
        self.reads.setdefault(tenant_id, []).extend(reads)
        self.posts.setdefault(tenant_id, []).extend(posts)

    def follower_series(
        self, tenant_id: UUID, platform: str, handle: str, *, since: datetime | None = None
    ) -> list[FollowerPoint]:
        platform, handle = _check(platform, handle)
        rows = [
            r
            for r in self.reads.get(tenant_id, [])
            if r.platform == platform
            and r.handle == handle
            and r.followers is not None
            and (since is None or r.fetched_at >= _moment(since))
        ]
        rows.sort(key=lambda r: r.fetched_at)
        return [FollowerPoint(r.fetched_at, r.followers or 0) for r in rows]

    def post_reads(
        self, tenant_id: UUID, platform: str, handle: str, *, since: datetime | None = None
    ) -> list[PostRead]:
        platform, handle = _check(platform, handle)
        rows = [
            p
            for p in self.posts.get(tenant_id, [])
            if p.platform == platform
            and p.handle == handle
            and (since is None or p.fetched_at >= _moment(since))
        ]
        rows.sort(key=lambda p: (p.post_id, p.fetched_at))
        return rows


class PostgresGrowthRepository:
    """All access through `tenant_session`: RLS scopes every statement."""

    def record(
        self, tenant_id: UUID, reads: Sequence[ProfileRead], posts: Sequence[PostRead] = ()
    ) -> None:
        if not reads and not posts:
            return
        with tenant_session(tenant_id) as session:
            session.add_all(
                CreatorRead(
                    tenant_id=tenant_id,
                    platform=r.platform,
                    handle=r.handle,
                    fetched_at=r.fetched_at,
                    source=r.source,
                    followers=r.followers,
                    following=r.following,
                    posts_count=r.posts_count,
                    total_likes=r.total_likes,
                )
                for r in reads
            )
            session.add_all(
                CreatorPostRead(
                    tenant_id=tenant_id,
                    platform=p.platform,
                    handle=p.handle,
                    post_id=p.post_id,
                    taken_at=p.taken_at,
                    fetched_at=p.fetched_at,
                    views=p.views,
                    likes=p.likes,
                    comments=p.comments,
                    shares=p.shares,
                    ai_generated=p.ai_generated,
                    ai_label=p.ai_label,
                    ai_source=p.ai_source,
                )
                for p in posts
            )

    def follower_series(
        self, tenant_id: UUID, platform: str, handle: str, *, since: datetime | None = None
    ) -> list[FollowerPoint]:
        platform, handle = _check(platform, handle)
        stmt = (
            select(CreatorRead.fetched_at, CreatorRead.followers)
            .where(
                CreatorRead.platform == platform,
                CreatorRead.handle == handle,
                CreatorRead.followers.is_not(None),
            )
            .order_by(CreatorRead.fetched_at)
        )
        if since is not None:
            stmt = stmt.where(CreatorRead.fetched_at >= _moment(since))
        with tenant_session(tenant_id) as session:
            return [FollowerPoint(at, int(count)) for at, count in session.execute(stmt)]

    def post_reads(
        self, tenant_id: UUID, platform: str, handle: str, *, since: datetime | None = None
    ) -> list[PostRead]:
        platform, handle = _check(platform, handle)
        stmt = (
            select(CreatorPostRead)
            .where(CreatorPostRead.platform == platform, CreatorPostRead.handle == handle)
            .order_by(CreatorPostRead.post_id, CreatorPostRead.fetched_at)
        )
        if since is not None:
            stmt = stmt.where(CreatorPostRead.fetched_at >= _moment(since))
        with tenant_session(tenant_id) as session:
            return [
                PostRead(
                    platform=row.platform,
                    handle=row.handle,
                    post_id=row.post_id,
                    taken_at=row.taken_at,
                    fetched_at=row.fetched_at,
                    views=row.views,
                    likes=row.likes,
                    comments=row.comments,
                    shares=row.shares,
                    ai_generated=row.ai_generated,
                    ai_label=row.ai_label,
                    ai_source=row.ai_source,
                )
                for row in session.scalars(stmt)
            ]

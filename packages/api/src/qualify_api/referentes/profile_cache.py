"""The brand's own account in Postgres (migration 0035, `creator_profile_cache`): what
`scrapecreators_client.fetch_profile_and_posts` read (profile + the week's posts + the
metrics' inputs), kept per tenant for `SNAPSHOT_TTL` — the metrics are "the last 7
days" anchored at the read, so an older snapshot would describe a week that is gone.
Replaces the one global JSON snapshot the Brand Kit used until 2026-10-01
(`fixtures/brand_connect_profile.json`, which every session wrote over).

One kind of entry today, `snapshot`, under the key `(tenant, network, handle, kind)`.
The profile reads the referentes SEARCH makes are public data and live in the shared
pool instead (`qualify_api.creators`, migration 0036). Expired rows are overwritten on
the next read; nothing is served past its TTL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from qualify_api.referentes.models import CreatorProfileCache

KINDS = ("snapshot",)
SNAPSHOT_TTL = timedelta(days=7)
TTL = {"snapshot": SNAPSHOT_TTL}
NETWORKS = ("tiktok", "instagram")


def normalize_handle(handle: str) -> str:
    return handle.strip().lstrip("@").lower()


def _check(network: str, handle: str, kind: str) -> tuple[str, str, str]:
    if network not in NETWORKS:
        raise ValueError(f"network must be one of {NETWORKS}, got {network!r}")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {kind!r}")
    normalized = normalize_handle(handle)
    if not normalized:
        raise ValueError("handle must not be empty")
    return network, normalized, kind


def _moment(value: datetime | float | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.fromtimestamp(float(value), tz=UTC)


@dataclass(frozen=True)
class CachedProfile:
    network: str
    handle: str
    kind: str
    document: dict[str, Any]
    missing: bool
    fetched_at: datetime
    expires_at: datetime


class ProfileCacheRepository(Protocol):
    def get(
        self,
        tenant_id: UUID,
        network: str,
        handle: str,
        kind: str,
        *,
        now: datetime | float | None = None,
    ) -> CachedProfile | None: ...

    def put(
        self,
        tenant_id: UUID,
        network: str,
        handle: str,
        kind: str,
        document: dict[str, Any] | None,
        *,
        missing: bool = False,
        now: datetime | float | None = None,
    ) -> CachedProfile: ...


def _entry(
    network: str,
    handle: str,
    kind: str,
    document: dict[str, Any] | None,
    missing: bool,
    now: datetime | float | None,
) -> CachedProfile:
    network, handle, kind = _check(network, handle, kind)
    fetched_at = _moment(now)
    return CachedProfile(
        network, handle, kind, dict(document or {}), missing, fetched_at, fetched_at + TTL[kind]
    )


@dataclass
class MemoryProfileCacheRepository:
    entries: dict[tuple[UUID, str, str, str], CachedProfile] = field(default_factory=dict)

    def get(
        self,
        tenant_id: UUID,
        network: str,
        handle: str,
        kind: str,
        *,
        now: datetime | float | None = None,
    ) -> CachedProfile | None:
        network, handle, kind = _check(network, handle, kind)
        hit = self.entries.get((tenant_id, network, handle, kind))
        if hit is None or hit.expires_at <= _moment(now):
            return None
        return hit

    def put(
        self,
        tenant_id: UUID,
        network: str,
        handle: str,
        kind: str,
        document: dict[str, Any] | None,
        *,
        missing: bool = False,
        now: datetime | float | None = None,
    ) -> CachedProfile:
        entry = _entry(network, handle, kind, document, missing, now)
        self.entries[(tenant_id, entry.network, entry.handle, entry.kind)] = entry
        return entry


class PostgresProfileCacheRepository:
    """All access through `tenant_session`: RLS scopes every statement."""

    def get(
        self,
        tenant_id: UUID,
        network: str,
        handle: str,
        kind: str,
        *,
        now: datetime | float | None = None,
    ) -> CachedProfile | None:
        network, handle, kind = _check(network, handle, kind)
        stmt = select(CreatorProfileCache).where(
            CreatorProfileCache.network == network,
            CreatorProfileCache.handle == handle,
            CreatorProfileCache.kind == kind,
            CreatorProfileCache.expires_at > _moment(now),
        )
        with tenant_session(tenant_id) as session:
            row = session.scalars(stmt).first()
            if row is None:
                return None
            return CachedProfile(
                row.network,
                row.handle,
                row.kind,
                dict(row.document or {}),
                bool(row.missing),
                row.fetched_at,
                row.expires_at,
            )

    def put(
        self,
        tenant_id: UUID,
        network: str,
        handle: str,
        kind: str,
        document: dict[str, Any] | None,
        *,
        missing: bool = False,
        now: datetime | float | None = None,
    ) -> CachedProfile:
        entry = _entry(network, handle, kind, document, missing, now)
        values = {
            "tenant_id": tenant_id,
            "network": entry.network,
            "handle": entry.handle,
            "kind": entry.kind,
            "document": entry.document,
            "missing": entry.missing,
            "fetched_at": entry.fetched_at,
            "expires_at": entry.expires_at,
        }
        stmt = insert(CreatorProfileCache).values(**values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_creator_profile_cache",
            set_={
                k: v
                for k, v in values.items()
                if k not in ("tenant_id", "network", "handle", "kind")
            },
        )
        with tenant_session(tenant_id) as session:
            session.execute(stmt)
        return entry

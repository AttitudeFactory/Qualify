"""The brand's own account, remembered in Postgres with a time to live
(`qualify_api.referentes.profile_cache`, migration 0035) — § request 2026-10-01: "no
quiero más json". Per tenant: what `scrapecreators_client.fetch_profile_and_posts` read
(`cached_snapshot` / `remember_snapshot`, 7 days), so re-analysing the same handle costs
no credit while the week it describes is still the current one. The profiles the
referentes SEARCH reads are public data and live in the shared pool instead
(`creator_pool_provider`, migration 0036).

Without a session (no tenant) nothing is remembered and nothing is served: the read
happens live, as it always did for a new handle.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from qualify_api.referentes.profile_cache import (
    PostgresProfileCacheRepository,
    ProfileCacheRepository,
)
from sqlalchemy.exc import SQLAlchemyError

from .scrapecreators_client import SNAPSHOT_SCHEMA

logger = logging.getLogger(__name__)

REPOSITORY: ProfileCacheRepository = PostgresProfileCacheRepository()

SNAPSHOT = "snapshot"


def cached_snapshot(
    tenant_id: UUID,
    network: str,
    handle: str,
    *,
    repository: ProfileCacheRepository | None = None,
) -> dict[str, Any] | None:
    """The brand's own account as last read, while its entry lives and was written by
    the current normalizer (`SNAPSHOT_SCHEMA`) — else None: go read it for real. A
    database failure is a miss too, never an error on the operator's screen."""
    try:
        hit = (repository or REPOSITORY).get(tenant_id, network, handle, SNAPSHOT)
    except (SQLAlchemyError, ValueError) as exc:
        logger.warning("creator cache: snapshot not read: %s", exc)
        return None
    if hit is None or hit.missing or hit.document.get("schema") != SNAPSHOT_SCHEMA:
        return None
    profile = hit.document.get("profile")
    return dict(profile) if isinstance(profile, dict) else None


def remember_snapshot(
    tenant_id: UUID,
    network: str,
    handle: str,
    profile: dict[str, Any],
    *,
    repository: ProfileCacheRepository | None = None,
) -> None:
    """Keep this read as the brand's account for `SNAPSHOT_TTL`; a failure here only
    means the next analysis pays the read again."""
    try:
        (repository or REPOSITORY).put(
            tenant_id,
            network,
            handle,
            SNAPSHOT,
            {"schema": SNAPSHOT_SCHEMA, "profile": profile},
            now=profile.get("fetchedAt") if isinstance(profile.get("fetchedAt"), float) else None,
        )
    except (SQLAlchemyError, ValueError) as exc:
        logger.warning("creator cache: snapshot not written: %s", exc)

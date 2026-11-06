"""The objects of a purged piece are absent for the app (m-24973446, ADR 39 amendment).

Until 2026-11-06 a purged piece (`content_drafts.media_purged_at`) had no bytes left in
R2, so any door that still held one of its keys answered 404 by itself. The production
bucket refuses deletes under `t/` (lock rule), so a piece can now be purged FOR THE APP
while its objects stay in R2 (`media_objects_pending_at`). Every screen already hides a
purged piece by the flag; this module closes the byte doors that relied on the bytes
being gone:

- `/r2media/{token}` (`Qualify/r2_media.py`) and `/public/media/{token}`
  (`http/public_media_routes.py`) answer their single 404;
- the server-side readers (`creative.media.R2ReadingMediaStore`, the WhatsApp
  `ProductionBlobStore`) raise `ObjectNotFound`, exactly what a deleted object raised —
  so regenerating with a purged piece as input, the piece download and a WhatsApp send
  fail the way they already failed after a real delete.

Only keys of the shape `t/{tenant}/generated/{draft_id}/…` are ever looked up — the
folder IS the piece (`retention.piece_prefix`); every other key costs nothing. The
lookup runs through `tenant_session(tenant_id)` (RLS), and a key of another tenant never
gets here (the gate's prefix check runs first, and the regex requires the same tenant).

Answers are cached for `CACHE_SECONDS` per process: the purge runs once a day, a video
player asks for dozens of ranges per minute. A lookup that fails answers «purged»
(fail closed): never serving a purged piece outweighs one failed preview.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from uuid import UUID

logger = logging.getLogger("qualify_api.creative.purged_media")

CACHE_SECONDS = 60.0

_PIECE_KEY = re.compile(
    r"^t/(?P<tenant>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
    r"/generated/(?P<draft>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/"
)

_cache: dict[tuple[UUID, UUID], tuple[bool, float]] = {}
_cache_lock = threading.Lock()


def piece_of_key(tenant_id: UUID, object_key: str) -> UUID | None:
    """The piece whose folder holds `object_key`, when it is THIS tenant's piece folder
    (`t/{tenant}/generated/{draft}/…`); None for any other key."""
    match = _PIECE_KEY.match(object_key or "")
    if match is None or match["tenant"] != str(tenant_id):
        return None
    return UUID(match["draft"])


def _lookup(tenant_id: UUID, draft_id: UUID) -> bool:
    from qualify_shared.db.session import tenant_session  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    from qualify_api.creative.models import ContentDraft  # noqa: PLC0415

    with tenant_session(tenant_id) as session:
        purged_at = session.scalar(
            select(ContentDraft.media_purged_at).where(ContentDraft.id == draft_id)
        )
    return purged_at is not None


#: Replaced in tests (offline) — `(tenant_id, draft_id) -> purged?`.
lookup: Callable[[UUID, UUID], bool] = _lookup


def is_purged_object(tenant_id: UUID, object_key: str) -> bool:
    """True when `object_key` belongs to a piece the retention rule purged — its bytes
    may still be in R2, and no door may serve them."""
    draft_id = piece_of_key(tenant_id, object_key)
    if draft_id is None:
        return False
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get((tenant_id, draft_id))
    if hit is not None and hit[1] > now:
        return hit[0]
    try:
        purged = bool(lookup(tenant_id, draft_id))
    except Exception as exc:  # noqa: BLE001 — fail closed, see the module docstring
        logger.warning("purged media lookup failed, refusing: %s", type(exc).__name__)
        return True
    with _cache_lock:
        _cache[(tenant_id, draft_id)] = (purged, now + CACHE_SECONDS)
    return purged


def refuse_if_purged(tenant_id: UUID, object_key: str) -> None:
    """Raise `ObjectNotFound` for an object of a purged piece — what the store raised
    once the object was really deleted, so every caller keeps its existing 404 path."""
    if is_purged_object(tenant_id, object_key):
        from qualify_shared.objects.gate import ObjectNotFound  # noqa: PLC0415

        raise ObjectNotFound(object_key)


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


__all__ = [
    "CACHE_SECONDS",
    "clear_cache",
    "is_purged_object",
    "piece_of_key",
    "refuse_if_purged",
]

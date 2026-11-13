"""Read-only duration hints for the part editor, before a generation is requested."""

from __future__ import annotations

import logging
from uuid import UUID

from qualify_shared.db.session import tenant_session
from qualify_shared.objects.config import R2ConfigurationError
from qualify_shared.objects.gate import ObjectNotFound
from qualify_shared.objects.keys import is_object_store_key
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from qualify_api.catalog.business_media_models import BusinessMedia
from qualify_api.catalog.models import ProductMedia
from qualify_api.creative.media import LocalMediaStore, _media_seconds, _video_dimensions, owned_by

# Uploads with fast-start MP4 headers can be probed cheaply. Larger files without
# catalog metadata stay unknown; the generation preflight remains authoritative.
_MAX_PROBE_BYTES = 32 * 1024 * 1024
logger = logging.getLogger(__name__)


def _saved_seconds(tenant_id: UUID, key: str) -> float | None:
    with tenant_session(tenant_id) as session:
        seconds = session.scalar(
            select(ProductMedia.duration_sec)
            .where(ProductMedia.object_key == key, ProductMedia.media_type == "video")
            .limit(1)
        )
        if seconds is not None:
            return float(seconds)
        milliseconds = session.scalar(
            select(BusinessMedia.duration_ms)
            .where(
                BusinessMedia.object_key == key,
                BusinessMedia.media_type == "video",
                BusinessMedia.deleted_at.is_(None),
            )
            .limit(1)
        )
        return float(milliseconds) / 1000 if milliseconds is not None else None


def _probe_bytes(tenant_id: UUID, key: str) -> bytes | None:
    from qualify_shared.objects.s3 import storage_read_errors  # noqa: PLC0415

    from qualify_api.creative.composition import media_root  # noqa: PLC0415
    from qualify_api.creative.owner_uploads import (  # noqa: PLC0415
        default_gate,
        resolve_moved_key,
    )
    from qualify_api.creative.purged_media import refuse_if_purged  # noqa: PLC0415

    if not is_object_store_key(key):
        path = LocalMediaStore(media_root())._path(key)
        if path.is_file():
            refuse_if_purged(tenant_id, key)  # a purged piece's file reads as gone here too
            if path.stat().st_size > _MAX_PROBE_BYTES:
                return None
            return path.read_bytes()
        key = resolve_moved_key(tenant_id, key) or ""
        if not key or not owned_by(tenant_id, key):
            return None
    refuse_if_purged(tenant_id, key)
    with storage_read_errors():
        gate = default_gate()
        if gate.object_size(tenant_id, key) > _MAX_PROBE_BYTES:
            return None
        with gate.open_object(tenant_id, key) as stream:
            data = stream.read(_MAX_PROBE_BYTES + 1)
    return data if len(data) <= _MAX_PROBE_BYTES else None


def part_video_seconds(*, tenant_id: UUID, key: str) -> float | None:
    """This tenant's video duration, or unknown. No generation, encoding or writes.

    Keys are checked before database access or media reads. Catalog metadata is a
    display hint; the generation path measures the actual video before any paid call.
    """
    if not owned_by(tenant_id, key) or not key.lower().endswith((".mp4", ".mov", ".webm", ".m4v")):
        return None
    try:
        seconds = _saved_seconds(tenant_id, key)
        if seconds is not None:
            return seconds if seconds > 0 else None
    except SQLAlchemyError as exc:
        logger.warning("part video duration metadata unavailable (%s)", type(exc).__name__)
    try:
        data = _probe_bytes(tenant_id, key)
        return _media_seconds(data) if data and _video_dimensions(data) else None
    except (
        OSError,
        ValueError,
        ObjectNotFound,
        SQLAlchemyError,
        R2ConfigurationError,
    ) as exc:
        logger.warning("part video duration probe unavailable (%s)", type(exc).__name__)
        return None

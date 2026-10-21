"""«Descargar todo» (m-24828908): one piece as a `.zip` — its files and `texto.txt` —
served by the backend.

Same door as `r2_media.py` (ADR 28e): `issue_download_path` mints a token — 256 random
bits, only its hash stored in Redis, never derived from the tenant or the draft — for ONE
draft, while the draft is read through RLS, so a token can only ever name a piece that
tenant could already see. `GET /piece-download/{token}` answers the archive, or a single
404 for every failure. Tokens live `DOWNLOAD_TTL_SECONDS` (1 h), like the media they
bundle; reloading the draft mints a fresh one.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
from functools import cache
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Response

logger = logging.getLogger(__name__)

DOWNLOAD_ROUTE = "/piece-download"
DOWNLOAD_TTL_SECONDS = 60 * 60
_KEY_PREFIX = "piece_download"


def _key(token: str) -> str:
    return f"{_KEY_PREFIX}:{hashlib.sha256(token.encode('ascii')).hexdigest()}"


class PieceTokenStore:
    """Mints and resolves «Descargar todo» tokens. One instance wraps one Redis."""

    def __init__(self, redis: Any, *, ttl_seconds: int = DOWNLOAD_TTL_SECONDS) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    def issue(self, *, tenant_id: UUID, draft_id: UUID) -> str:
        token = secrets.token_urlsafe(32)
        payload = json.dumps({"tenant_id": str(tenant_id), "draft_id": str(draft_id)})
        self._redis.set(_key(token), payload, ex=self._ttl)
        return token

    def resolve(self, token: str) -> tuple[UUID, UUID] | None:
        """(tenant, draft), or None for an unknown, expired or malformed token."""
        try:
            raw = self._redis.get(_key(token))
            if raw is None:
                return None
            data = json.loads(raw)
            return UUID(str(data["tenant_id"])), UUID(str(data["draft_id"]))
        except (ValueError, KeyError, TypeError, UnicodeEncodeError):
            return None


@cache
def _store() -> PieceTokenStore:
    import redis  # noqa: PLC0415
    from qualify_api.config import redis_url  # noqa: PLC0415

    return PieceTokenStore(redis.Redis.from_url(redis_url(), decode_responses=True))


def issue_download_path(
    tenant_id: UUID, draft_id: UUID, *, store: PieceTokenStore | None = None
) -> str:
    """`/piece-download/<token>` for one draft of `tenant_id` — call it only while that
    draft is being read for that tenant."""
    token = (store or _store()).issue(tenant_id=tenant_id, draft_id=draft_id)
    return f"{DOWNLOAD_ROUTE}/{token}"


router = APIRouter()


def _not_found() -> Response:
    return Response(status_code=404)


@router.get(DOWNLOAD_ROUTE + "/{token}")
async def piece_download(token: str) -> Response:
    from .creative_provider import piece_archive  # noqa: PLC0415 — the provider imports this

    target = _store().resolve(token)
    if target is None:
        return _not_found()
    tenant_id, draft_id = target
    try:
        archive = await asyncio.to_thread(piece_archive, tenant_id, draft_id)
    except Exception as exc:  # noqa: BLE001 — one 404 for every failure, the cause logged
        logger.warning("piece download failed: %s", type(exc).__name__)
        return _not_found()
    if archive is None:
        return _not_found()
    name, data = archive
    logger.info("piece-download.served bytes=%s", len(data))
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "private, no-store",
        },
    )

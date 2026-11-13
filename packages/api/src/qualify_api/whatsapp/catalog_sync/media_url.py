"""The stable, signed public URL of a catalog item's photo (ADR 48 §8, as amended).

    {QUALIFY_PUBLIC_MEDIA_BASE_URL}/public/catalog-media/{tenant_id}/{media_id}/{sig}.jpg

`sig = base64url(HMAC-SHA256(K, DOMAIN ‖ tenant_id ‖ 0x00 ‖ media_id))` without padding
(43 characters). `K` is `QUALIFY_OAUTH_STATE_SECRET`, domain-separated by `DOMAIN` — the
pattern of `ads/edit_review.py`, so no new variable has to be prepared in production. The
signature covers only ids, so the route checks it BEFORE any database access.

A missing secret, the development default, or one shorter than 32 characters makes every
URL unavailable: the service refuses to enqueue (`CatalogMediaUnavailable`) and the route
answers 404. A URL that Meta must download is never built on a guessable key.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from uuid import UUID

DOMAIN = b"qualify:wa-catalog-media:v1\x00"
SECRET_ENV = "QUALIFY_OAUTH_STATE_SECRET"
BASE_URL_ENV = "QUALIFY_PUBLIC_MEDIA_BASE_URL"
ROUTE_PREFIX = "/public/catalog-media"
SIGNATURE_LENGTH = 43
_MIN_SECRET = 32


class CatalogMediaUnavailable(Exception):
    """The photo URL cannot be built or verified here: the signing secret or the public
    base URL is not configured. Carries no value."""


def _secret() -> bytes:
    from qualify_api.config import _DEV_STATE_SECRET  # noqa: PLC0415

    secret = os.environ.get(SECRET_ENV, "")
    if not secret or secret == _DEV_STATE_SECRET or len(secret) < _MIN_SECRET:
        raise CatalogMediaUnavailable("the catalog media signing secret is not configured")
    return secret.encode()


def media_ready() -> bool:
    """Whether a photo URL can be built in this process (secret and base URL set)."""
    try:
        _secret()
        _base_url()
    except CatalogMediaUnavailable:
        return False
    return True


def sign(tenant_id: UUID, media_id: UUID) -> str:
    message = DOMAIN + str(tenant_id).encode() + b"\x00" + str(media_id).encode()
    digest = hmac.new(_secret(), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def verify(tenant_id: UUID, media_id: UUID, signature: str) -> bool:
    """Constant-time check; False (never an exception) when the secret is unusable."""
    if not isinstance(signature, str) or len(signature) != SIGNATURE_LENGTH:
        return False
    try:
        expected = sign(tenant_id, media_id)
    except CatalogMediaUnavailable:
        return False
    return hmac.compare_digest(expected.encode(), signature.encode())


def _base_url() -> str:
    base = os.environ.get(BASE_URL_ENV, "").strip().rstrip("/")
    if not base:
        raise CatalogMediaUnavailable("the public media base URL is not configured")
    return base


def catalog_media_url(tenant_id: UUID, media_id: UUID) -> str:
    """The URL the mapping puts in the item's `image[0].url` — the ONE place this path is
    assembled, so the route and the URL handed to Meta cannot drift apart."""
    return f"{_base_url()}{ROUTE_PREFIX}/{tenant_id}/{media_id}/{sign(tenant_id, media_id)}.jpg"

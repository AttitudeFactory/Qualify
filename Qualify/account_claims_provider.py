"""Tu cuenta's account, claimed for the session's brand before it is read
(`qualify_api.creative.account_claims`, migration 0044) — § request 2026-10-06: an
Instagram / TikTok account registered by one email is never read for another.

Blocking (SQLAlchemy is synchronous here): callers run these through
`asyncio.to_thread`. Database errors propagate — `BrandConnectState.analyze` refuses the
read when the claim cannot be checked, rather than reading an account it may not own.
"""

from __future__ import annotations

from uuid import UUID

from qualify_api.creative import account_claims
from qualify_api.creative.account_claims import AccountTaken

from .creative_provider import default_brand_id

__all__ = ["AccountTaken", "claim", "keep_only", "release"]


def claim(tenant_id: UUID, network: str, handle: str) -> tuple[UUID, bool]:
    """(the session's brand, whether this call took the account). Raises `AccountTaken`
    when another tenant holds it, `LookupError` when the tenant has no brand."""
    brand_id = default_brand_id(tenant_id)
    if brand_id is None:
        raise LookupError("the tenant has no brand to claim the account for")
    return brand_id, account_claims.claim(tenant_id, brand_id, network, handle)


def release(tenant_id: UUID, brand_id: UUID, network: str, handle: str) -> None:
    account_claims.release(tenant_id, brand_id, network, handle)


def keep_only(tenant_id: UUID, brand_id: UUID, network: str, handle: str) -> None:
    account_claims.keep_only(tenant_id, brand_id, network, handle)

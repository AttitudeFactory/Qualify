"""A brand's own Instagram / TikTok account belongs to that brand alone (0044, § request
2026-10-06): "a@gmail.com se registró con su user de Instagram y b@gmail.com quiere usar
el user de Instagram de a@gmail.com — no quiero que esto pase".

The Brand Kit's Tu cuenta reads the account it is given (profile, followers, the week's
posts and metrics). Before that read, the brand CLAIMS the account here; a claim held by
another tenant refuses the read, so its data never reaches a second tenant.

How "held by another tenant" is known without a cross-tenant read: `social_account_claims`
keeps the standard RLS policy (each tenant sees only its own rows) but its
`UNIQUE(network, handle_key)` is enforced by Postgres across ALL tenants. `claim` runs
`INSERT … ON CONFLICT DO NOTHING RETURNING id` inside `tenant_session`; when nothing comes
back and the tenant's own rows do not hold the account, someone else does. Nothing about
that someone — tenant, brand, email — is ever read or returned.

Lifecycle: `claim` before the read; `release` it again when that read fails (a typo must
not lock an account that was never shown); `keep_only` after a successful read, so a brand
holds one account per network — reading a new one frees the previous one."""

from __future__ import annotations

from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from qualify_api.creative.models import SocialAccountClaim

NETWORKS = ("instagram", "tiktok")


class AccountTaken(Exception):
    """The account is another tenant's own account. Carries nothing about that tenant."""


def handle_key(handle: str) -> str:
    """The lookup form of a handle: "@MiduDev " and "midudev" are one account."""
    return handle.strip().lstrip("@").strip().lower()


def _check(network: str, handle: str) -> str:
    if network not in NETWORKS:
        raise ValueError(f"network must be one of {NETWORKS}, got {network!r}")
    key = handle_key(handle)
    if not key:
        raise ValueError("handle must not be empty")
    return key


def claim(tenant_id: UUID, brand_id: UUID, network: str, handle: str) -> bool:
    """Take `(network, handle)` as `brand_id`'s own account. True when this call took it,
    False when the tenant already held it (nothing to undo on a failed read). Raises
    `AccountTaken` when another tenant holds it."""
    key = _check(network, handle)
    with tenant_session(tenant_id) as session:
        taken_id = session.scalar(
            insert(SocialAccountClaim)
            .values(
                tenant_id=tenant_id,
                brand_id=brand_id,
                network=network,
                handle_key=key,
                handle=handle.strip(),
            )
            .on_conflict_do_nothing(index_elements=["network", "handle_key"])
            .returning(SocialAccountClaim.id)
        )
        if taken_id is not None:
            return True
        # The conflicting row is ours (visible under RLS) or another tenant's (invisible).
        ours = session.scalar(
            select(SocialAccountClaim.id).where(
                SocialAccountClaim.network == network, SocialAccountClaim.handle_key == key
            )
        )
    if ours is None:
        raise AccountTaken(network)
    return False


def release(tenant_id: UUID, brand_id: UUID, network: str, handle: str) -> None:
    """Drop the brand's claim on this one account (a read that failed after `claim`)."""
    key = _check(network, handle)
    with tenant_session(tenant_id) as session:
        session.execute(
            delete(SocialAccountClaim).where(
                SocialAccountClaim.brand_id == brand_id,
                SocialAccountClaim.network == network,
                SocialAccountClaim.handle_key == key,
            )
        )


def keep_only(tenant_id: UUID, brand_id: UUID, network: str, handle: str) -> None:
    """After a successful read: the brand's claims on `network` other than this account
    go, so the account it read before is free again for whoever owns it."""
    key = _check(network, handle)
    with tenant_session(tenant_id) as session:
        session.execute(
            delete(SocialAccountClaim).where(
                SocialAccountClaim.brand_id == brand_id,
                SocialAccountClaim.network == network,
                SocialAccountClaim.handle_key != key,
            )
        )

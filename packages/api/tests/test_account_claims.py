"""`account_claims` (0044, § request 2026-10-06): a brand's own Instagram / TikTok
account belongs to that brand alone, and a second tenant learns "taken" from the global
unique index without ever reading the first tenant's row.

The normalization runs offline; the rest is `db`-marked, against real RLS."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.creative import account_claims
from qualify_api.creative.account_claims import AccountTaken, handle_key
from qualify_api.creative.models import SocialAccountClaim
from qualify_api.tenancy.models import Brand, Tenant

TENANT_A = UUID("c0000000-0000-4000-8000-0000000000e1")
TENANT_B = UUID("d0000000-0000-4000-8000-0000000000e1")


def test_one_account_has_one_key_however_it_is_typed() -> None:
    assert handle_key("  @MiduDev ") == handle_key("midudev") == "midudev"
    assert handle_key("@ marca.demo") == "marca.demo"


@pytest.mark.parametrize(("network", "handle"), [("myspace", "x"), ("instagram", " @ ")])
def test_an_unknown_network_or_an_empty_handle_claims_nothing(network: str, handle: str) -> None:
    with pytest.raises(ValueError):
        account_claims.claim(TENANT_A, uuid4(), network, handle)


# -- database ------------------------------------------------------------------------------


@pytest.fixture
def brands() -> tuple[UUID, UUID]:
    """Tenant A's brand and tenant B's brand; idempotent re-runs (fresh brands each time,
    and every test claims an account no earlier run used)."""
    with admin_session() as session:
        for tid, name in ((TENANT_A, "A"), (TENANT_B, "B")):
            if session.get(Tenant, tid) is None:
                session.add(
                    Tenant(
                        id=tid,
                        name=f"account-claims-{name}",
                        country="CO",
                        timezone="America/Bogota",
                        currency="COP",
                    )
                )
                session.flush()
        a = Brand(tenant_id=TENANT_A, name=f"account-claims-{uuid4()}")
        b = Brand(tenant_id=TENANT_B, name=f"account-claims-{uuid4()}")
        session.add_all([a, b])
        session.flush()
        return a.id, b.id


def _account() -> str:
    return f"marca.{uuid4().hex[:12]}"


def _visible(tenant_id: UUID, network: str, handle: str) -> list[UUID]:
    with tenant_session(tenant_id) as session:
        return list(
            session.scalars(
                select(SocialAccountClaim.tenant_id).where(
                    SocialAccountClaim.network == network,
                    SocialAccountClaim.handle_key == handle_key(handle),
                )
            )
        )


@pytest.mark.db
def test_an_account_registered_by_one_email_is_refused_to_another(
    brands: tuple[UUID, UUID],
) -> None:
    brand_a, brand_b = brands
    handle = _account()
    assert account_claims.claim(TENANT_A, brand_a, "instagram", handle) is True
    with pytest.raises(AccountTaken):
        account_claims.claim(TENANT_B, brand_b, "instagram", handle)
    # however B types it
    with pytest.raises(AccountTaken):
        account_claims.claim(TENANT_B, brand_b, "instagram", f"  @{handle.upper()} ")
    # B learned "taken" and nothing else: the row stays invisible to it
    assert _visible(TENANT_B, "instagram", handle) == []
    assert _visible(TENANT_A, "instagram", handle) == [TENANT_A]


@pytest.mark.db
def test_claiming_ones_own_account_again_is_not_a_new_claim(brands: tuple[UUID, UUID]) -> None:
    brand_a, _ = brands
    handle = _account()
    assert account_claims.claim(TENANT_A, brand_a, "tiktok", handle) is True
    assert account_claims.claim(TENANT_A, brand_a, "tiktok", f"@{handle}") is False


@pytest.mark.db
def test_the_same_name_on_the_other_network_is_another_account(
    brands: tuple[UUID, UUID],
) -> None:
    brand_a, brand_b = brands
    handle = _account()
    account_claims.claim(TENANT_A, brand_a, "instagram", handle)
    assert account_claims.claim(TENANT_B, brand_b, "tiktok", handle) is True


@pytest.mark.db
def test_a_released_account_is_free_for_its_owner(brands: tuple[UUID, UUID]) -> None:
    """A typo read by A (and failed) must not lock the account B really owns."""
    brand_a, brand_b = brands
    handle = _account()
    account_claims.claim(TENANT_A, brand_a, "instagram", handle)
    account_claims.release(TENANT_A, brand_a, "instagram", handle)
    assert account_claims.claim(TENANT_B, brand_b, "instagram", handle) is True


@pytest.mark.db
def test_reading_a_new_account_frees_the_previous_one(brands: tuple[UUID, UUID]) -> None:
    brand_a, brand_b = brands
    old, new, tiktok = _account(), _account(), _account()
    account_claims.claim(TENANT_A, brand_a, "instagram", old)
    account_claims.claim(TENANT_A, brand_a, "tiktok", tiktok)
    account_claims.claim(TENANT_A, brand_a, "instagram", new)
    account_claims.keep_only(TENANT_A, brand_a, "instagram", new)
    assert _visible(TENANT_A, "instagram", old) == []
    assert _visible(TENANT_A, "instagram", new) == [TENANT_A]
    assert _visible(TENANT_A, "tiktok", tiktok) == [TENANT_A]  # other network untouched
    assert account_claims.claim(TENANT_B, brand_b, "instagram", old) is True
    with pytest.raises(AccountTaken):
        account_claims.claim(TENANT_B, brand_b, "instagram", new)


@pytest.mark.db
def test_one_tenant_cannot_release_another_tenants_account(brands: tuple[UUID, UUID]) -> None:
    brand_a, brand_b = brands
    handle = _account()
    account_claims.claim(TENANT_A, brand_a, "instagram", handle)
    account_claims.release(TENANT_B, brand_b, "instagram", handle)
    account_claims.keep_only(TENANT_B, brand_b, "instagram", _account())
    assert _visible(TENANT_A, "instagram", handle) == [TENANT_A]

"""Tu cuenta never reads another email's own account (§ request 2026-10-06): "a@gmail.com
se registró con su user de Instagram y b@gmail.com quiere usar el user de Instagram de
a@gmail.com — no quiero que esto pase".

Offline: `analyze` runs against stubbed claims, cache and Scrape Creators; what is pinned
is the ORDER — claim first, then the cache or the vendor — and what each outcome leaves
behind. The claim itself (the global unique index under RLS) is `db`-tested in
`packages/api/tests/test_account_claims.py`."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from . import creative_wizard_pages as wiz
from .auth_state import AuthState
from .creative_wizard_pages import BrandConnectState

TENANT = UUID("a0000000-0000-4000-8000-0000000000d1")
BRAND = UUID("b0000000-0000-4000-8000-0000000000d1")
PROFILE = {"username": "marca.demo", "followers": 1_000, "profilePicUrl": ""}


class _World:
    """The session and every outside call `analyze` makes, recorded."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, tenant: UUID | None = TENANT):
        self.calls: list[tuple[str, Any]] = []
        self.taken = False
        self.read_fails = False
        self.already_ours = False
        auth = AuthState()
        auth.session_tenant_id = str(tenant) if tenant else ""

        async def get_state(_self: object, state_cls: type) -> object:
            assert state_cls is AuthState
            return auth

        monkeypatch.setattr(BrandConnectState, "get_state", get_state)
        claims = wiz.account_claims_provider

        def claim(tenant_id: UUID, network: str, handle: str) -> tuple[UUID, bool]:
            self.calls.append(("claim", (tenant_id, network, handle)))
            if self.taken:
                raise claims.AccountTaken(network)
            return BRAND, not self.already_ours

        monkeypatch.setattr(claims, "claim", claim)
        monkeypatch.setattr(claims, "release", lambda *a: self.calls.append(("release", a)))
        monkeypatch.setattr(claims, "keep_only", lambda *a: self.calls.append(("keep_only", a)))

        def cached(*a: Any) -> None:
            self.calls.append(("cache", a))

        def fetch(network: str, handle: str) -> dict[str, Any]:
            self.calls.append(("fetch", (network, handle)))
            if self.read_fails:
                raise wiz.scrapecreators_client.ScrapeCreatorsError("not found")
            return PROFILE

        monkeypatch.setattr(wiz.creator_cache_provider, "cached_snapshot", cached)
        monkeypatch.setattr(wiz.creator_cache_provider, "remember_snapshot", lambda *a: None)
        monkeypatch.setattr(wiz.scrapecreators_client, "fetch_profile_and_posts", fetch)
        monkeypatch.setattr(wiz.growth_provider, "record_profile_read", lambda *a: 0)
        monkeypatch.setattr(
            wiz.discovery_seed,
            "seed_from_profile",
            lambda _p: wiz.discovery_seed.DiscoverySeed(handle="marca.demo", niches=()),
        )

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


async def _analyze(handle: str = "@Marca.Demo") -> BrandConnectState:
    state = BrandConnectState()
    state.network = "instagram"
    state.username = handle
    async for _ in BrandConnectState.analyze.fn(state):
        pass
    return state


async def test_another_emails_account_is_refused_before_anything_is_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _World(monkeypatch)
    world.taken = True
    state = await _analyze()
    assert world.names() == ["claim"]  # no cache, no Scrape Creators, nothing to release
    assert state.error == wiz._ACCOUNT_TAKEN
    assert state.analyzing is False
    assert state.profile_username == "" and state.step != wiz._PROFILE_STEP


async def test_the_brands_own_account_is_claimed_first_then_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _World(monkeypatch)
    state = await _analyze()
    assert world.names() == ["claim", "cache", "fetch", "keep_only"]
    assert world.calls[0][1] == (TENANT, "instagram", "@Marca.Demo")
    # the account read becomes the brand's one account on Instagram
    assert world.calls[-1][1] == (TENANT, BRAND, "instagram", "@Marca.Demo")
    assert state.error == "" and state.profile_username == "marca.demo"
    assert state.step == wiz._PROFILE_STEP


async def test_a_failed_read_frees_the_account_it_just_claimed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _World(monkeypatch)
    world.read_fails = True
    state = await _analyze("marca.demoo")
    assert world.names() == ["claim", "cache", "fetch", "release"]
    assert world.calls[-1][1] == (TENANT, BRAND, "instagram", "marca.demoo")
    assert state.error == wiz._PROFILE_UNAVAILABLE


async def test_a_failed_read_keeps_an_account_the_brand_already_held(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _World(monkeypatch)
    world.read_fails = True
    world.already_ours = True
    await _analyze()
    assert "release" not in world.names()


async def test_without_a_brand_kit_session_nothing_is_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _World(monkeypatch, tenant=None)
    state = await _analyze()
    assert world.calls == []
    assert state.error == wiz._PROFILE_UNAVAILABLE and state.analyzing is False


async def test_a_claim_that_cannot_be_checked_refuses_the_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.exc import OperationalError

    world = _World(monkeypatch)

    def down(*_a: Any) -> None:
        world.calls.append(("claim", _a))
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    monkeypatch.setattr(wiz.account_claims_provider, "claim", down)
    state = await _analyze()
    assert world.names() == ["claim"]
    assert state.error == wiz._PROFILE_UNAVAILABLE


def test_the_refusal_names_nobody() -> None:
    """The message says the account is taken — never by whom."""
    assert "@" not in wiz._ACCOUNT_TAKEN
    assert "otro correo" in wiz._ACCOUNT_TAKEN

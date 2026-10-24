"""The wizard and the Alta run ONE implementation (`qualify_api.creative.brand_prefill`,
m-24852197): its constants stay the wizard's, the wizard hands it this app's hashtag
catalog, and `analyze` maps a vendor's 404 onto the same message as before."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from qualify_api.creative import brand_prefill
from qualify_api.hashtags import MemoryHashtagRepository
from qualify_api.hashtags import catalog as hashtag_catalog

from . import creative_wizard_pages as wiz
from . import creator_discovery
from .auth_state import AuthState
from .creative_wizard_pages import BrandConnectState

TENANT = UUID("a0000000-0000-4000-8000-0000000000e4")
BRAND = UUID("b0000000-0000-4000-8000-0000000000e4")


def test_the_backend_keeps_the_wizards_constants() -> None:
    assert brand_prefill.CHOSEN_HASHTAGS == creator_discovery.CHOSEN_HASHTAGS
    assert brand_prefill.LOGO_SOURCE_PROFILE == wiz.LOGO_SOURCE_PROFILE


def test_the_wizard_hands_the_prefill_its_hashtag_catalog() -> None:
    ports = wiz._prefill_ports()
    assert ports.catalog is wiz._HASHTAG_CATALOG
    assert isinstance(ports.store, brand_prefill.BrandKitStore)


def test_the_catalog_adapter_answers_in_the_backends_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("QUALIFY_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(hashtag_catalog, "REPOSITORY", MemoryHashtagRepository())
    monkeypatch.setattr(hashtag_catalog, "_seeded", False)
    seed = creator_discovery.DiscoverySeed(handle="nibbles", niches=("food_drink",))
    choice = wiz._HASHTAG_CATALOG.suggest(TENANT, seed, bio="", category="")
    assert isinstance(choice, brand_prefill.HashtagChoice)
    assert choice.by == "rule" and choice.tags  # the seeded taxonomy, no key


async def test_an_account_the_vendor_does_not_find_shows_the_same_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = AuthState()
    auth.session_tenant_id = str(TENANT)

    async def get_state(_self: object, state_cls: type) -> object:
        return auth

    monkeypatch.setattr(BrandConnectState, "get_state", get_state)
    monkeypatch.setattr(wiz, "default_brand_id", lambda _t: BRAND)

    class Claims:
        def claim(self, *_a: Any) -> bool:
            return True

        def release(self, *_a: Any) -> None:
            return None

        def keep_only(self, *_a: Any) -> None:
            return None

    class Cache:
        def get(self, *_a: Any) -> None:
            return None

        def put(self, *_a: Any) -> None:
            return None

    def not_found(*_a: Any) -> dict[str, Any]:
        raise wiz.scrapecreators_client.ScrapeCreatorsError("HTTP 404", status_code=404)

    monkeypatch.setattr(
        wiz,
        "_prefill_ports",
        lambda: brand_prefill.PrefillPorts(claims=Claims(), cache=Cache(), read_profile=not_found),
    )
    state = BrandConnectState()
    state.network = "instagram"
    state.username = "no.existe"
    async for _ in BrandConnectState.analyze.fn(state):
        pass
    assert state.error == wiz._PROFILE_UNAVAILABLE and state.analyzing is False
    assert state.profile_username == ""


async def test_a_session_whose_brand_cannot_be_read_reads_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.exc import OperationalError

    auth = AuthState()
    auth.session_tenant_id = str(TENANT)

    async def get_state(_self: object, state_cls: type) -> object:
        return auth

    def down(_t: UUID) -> UUID:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    monkeypatch.setattr(BrandConnectState, "get_state", get_state)
    monkeypatch.setattr(wiz, "default_brand_id", down)
    monkeypatch.setattr(
        wiz, "_prefill_ports", lambda: pytest.fail("no run without the session's brand")
    )
    state = BrandConnectState()
    state.network = "instagram"
    state.username = "marca.demo"
    async for _ in BrandConnectState.analyze.fn(state):
        pass
    assert state.error == wiz._PROFILE_UNAVAILABLE and state.analyzing is False

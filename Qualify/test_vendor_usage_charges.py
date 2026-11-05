"""ADR 42 R5 (m-24854849) on the Reflex side: every paid ScrapeCreators read a screen
makes is charged to the session's business — the referentes search (its worker threads
included), a referente added by hand, the Brand Kit's profile read, the avatar prefetch —
and a capped read says when the owner can search again. Offline: the gate's raw request
is a counting fake and the usage store is in memory; nothing reaches the vendor."""

from __future__ import annotations

import inspect
import json
import threading
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from qualify_api.vendors import scrapecreators as sc
from qualify_api.vendors import usage

from . import avatar_proxy as ap
from . import creative_wizard_pages as cwp
from . import creator_discovery as cd

TENANT = UUID("a0000000-0000-4000-8000-0000000000a1")


class Wire:
    def __init__(self) -> None:
        self.requests: list[str] = []

    def __call__(self, client: httpx.Client, path: str, params: dict[str, str]) -> httpx.Response:
        self.requests.append(path)
        return httpx.Response(
            200,
            json={"success": True, "credits_remaining": 5000, "user": {"username": "otra"}},
            request=httpx.Request("GET", f"https://vendor.test{path}"),
        )


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> Wire:
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "sk_test_reflex_paths")
    fake = Wire()
    monkeypatch.setattr(sc, "_vendor_request", fake)
    return fake


@pytest.fixture
def store() -> usage.InMemoryUsageStore:
    active = usage.InMemoryUsageStore()
    usage.configure_store(active)
    return active


def test_the_search_runner_binds_its_charge_for_its_worker_threads() -> None:
    brand = uuid4()
    runner = cd.PhasedDiscovery(
        cd.DiscoverySeed(handle="x", niches=()), charge=usage.UsageCharge(TENANT, brand)
    )
    try:
        seen: list[Any] = []
        worker = threading.Thread(target=lambda: seen.append(usage.charge_of(runner.client)))
        with usage.uncharged():  # no context anywhere: only the client carries it
            worker.start()
            worker.join()
        assert seen == [usage.UsageCharge(TENANT, brand)]
    finally:
        runner.close()


def test_the_wizard_search_charges_the_session_business() -> None:
    source = inspect.getsource(cwp.BrandConnectState._discovery)
    assert "charge=usage.UsageCharge(ids[0], ids[1])" in source


def test_a_referente_added_by_hand_is_charged_to_the_business(
    wire: Wire, store: usage.InMemoryUsageStore
) -> None:
    brand = uuid4()
    with usage.charge_to(TENANT, brand):  # what the wizard's add_manual_account opens
        cd.lookup_account("instagram", "otra")
    assert wire.requests
    assert {(e.tenant_id, e.brand_id) for e in store.events} == {(TENANT, brand)}
    source = inspect.getsource(cwp.BrandConnectState.add_manual_account.fn)
    assert "usage.charge_to(ids[0], ids[1])" in source


def test_without_a_business_the_manual_lookup_reads_nothing(
    wire: Wire, store: usage.InMemoryUsageStore
) -> None:
    with usage.uncharged():
        _candidate, _found, error = cd.lookup_account("instagram", "otra")
    assert wire.requests == [] and store.events == [] and error


def test_the_avatar_route_never_pays_and_the_prefetch_pays_for_its_business(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads: list[Any] = []

    def fetch_profile(network: str, handle: str, *, feature: str) -> dict[str, str]:
        reads.append(usage.current())
        return {"profilePicUrl": "https://scontent.cdninstagram.com/x.jpg"}

    monkeypatch.setattr(sc, "fetch_profile", fetch_profile)
    with usage.uncharged():  # the <img> request: no session, no business
        assert ap.fresh_vendor_url("instagram", "nadie", now=1.0) == ""
    assert reads == []
    with usage.charge_to(TENANT):  # the session's prefetch
        ap.fresh_vendor_url("instagram", "alguien", now=2.0)
    assert reads == [usage.UsageCharge(TENANT)]


def test_the_profile_read_cap_offers_the_manual_flow() -> None:
    source = inspect.getsource(cwp.BrandConnectState.analyze.fn)
    assert "profile=True" in source and "self.profile_capped" in source
    rendered = str(cwp._connect_step_account())
    assert cwp.MANUAL_ROUTE == "/brand/manual" and cwp.MANUAL_FLOW_LABEL in rendered


async def test_ver_transcripcion_charges_the_session_business(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from . import discover_reels as dr

    seen: list[Any] = []

    def transcript_for_card(card: dict[str, str]) -> str:
        seen.append(usage.current())  # what the gate would charge
        return "lo que se dice"

    monkeypatch.setattr(dr.reels_discovery, "transcript_for_card", transcript_for_card)
    state = dr.DiscoverReelsState()
    state._cards = {"week": [{"key": "instagram:R1", "transcript": ""}]}
    state._cards_tenant_id = str(TENANT)
    assert usage.current() is None  # no default business: the screen must open its own
    await dr.DiscoverReelsState.load_transcript.fn(state, "instagram:R1")
    assert seen == [usage.UsageCharge(TENANT)]


async def test_a_capped_transcript_says_when_to_come_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from . import discover_reels as dr

    def capped(card: dict[str, str]) -> str:
        raise sc.ScrapeCreatorsBlocked("cap", reason=usage.REASON_DAILY_CAP)

    monkeypatch.setattr(dr.reels_discovery, "transcript_for_card", capped)
    state = dr.DiscoverReelsState()
    state._cards = {"week": [{"key": "instagram:R1", "transcript": ""}]}
    state._cards_tenant_id = str(TENANT)
    await dr.DiscoverReelsState.load_transcript.fn(state, "instagram:R1")
    assert state.transcript_error == "instagram:R1"
    assert state.transcript_error_text == usage.DAILY_CAP_NOTICE


async def test_the_business_own_picture_is_prefetched_and_charged_to_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    calls: list[tuple[Any, Any, Any]] = []

    async def resolve_avatar(
        network: str, handle: str, vendor_url: str = "", **kwargs: Any
    ) -> None:
        calls.append(((network, handle, vendor_url), kwargs.get("refresh"), usage.current()))

    monkeypatch.setattr(ap, "resolve_avatar", resolve_avatar)
    brand = uuid4()
    url = "https://scontent.cdninstagram.com/own.jpg"
    ap.prefetch_business_picture("instagram", "@MiNegocio", url, tenant_id=TENANT, brand_id=brand)
    assert usage.current() is None  # the charge stays inside the prefetch task
    await asyncio.gather(*list(ap._background_tasks))
    assert calls == [
        (("instagram", "MiNegocio", url), ap.fresh_vendor_url, usage.UsageCharge(TENANT, brand))
    ]


async def test_the_alta_proposal_prefetches_its_picture_when_shown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real call path: `BrandMinimalState.enter` (an async event) calls the sync
    `show()` on the event loop, so the prefetch task is scheduled — not a no-op."""
    import asyncio

    from qualify_api.creative.brand_prefill_review import Notice, PrefillReview

    from .brand_proposal import BrandProposalState

    calls: list[tuple[Any, Any]] = []

    async def resolve_avatar(network: str, handle: str, vendor_url: str = "", **_: Any) -> None:
        calls.append(((network, handle, vendor_url), usage.current()))

    monkeypatch.setattr(ap, "resolve_avatar", resolve_avatar)
    url = "https://scontent.cdninstagram.com/alta.jpg"
    proposal = {
        "connect": {"network": "instagram", "username": "minegocio"},
        "profile": {"username": "minegocio", "pic": url},
    }
    brand = uuid4()
    BrandProposalState().show(
        PrefillReview(Notice.PROPOSAL, "minegocio", proposal), owner=(TENANT, brand)
    )
    await asyncio.gather(*list(ap._background_tasks))
    assert calls == [(("instagram", "minegocio", url), usage.UsageCharge(TENANT, brand))]


def test_a_capped_search_does_not_say_it_found_nothing() -> None:
    rendered = str(cwp._connect_step_sort())
    assert cwp.CAPPED_SORT_NOTE == "Puedes añadir negocios a mano abajo o continuar."
    escaped = json.dumps(cwp.CAPPED_SORT_NOTE)[1:-1]  # the compiled page escapes «ñ»
    assert escaped in rendered and "discovery_capped" in rendered
    assert "No hay nada para clasificar" in cwp.NOTHING_TO_SORT_NOTE


def test_the_brand_kit_read_and_the_alta_proposal_prefetch_the_own_picture() -> None:
    from . import brand_proposal as bp

    assert "avatar_proxy.prefetch_business_picture(" in inspect.getsource(
        cwp.BrandConnectState.analyze.fn
    )
    show = inspect.getsource(bp.BrandProposalState.show.fn)
    assert "avatar_proxy.prefetch_business_picture(" in show and "tenant_id=owner[0]" in show

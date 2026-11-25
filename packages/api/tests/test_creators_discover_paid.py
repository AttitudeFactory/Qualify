"""«Buscar más cuentas en TikTok», offline (RF-07b, m-25119482).

Every vendor answer comes from an `httpx.MockTransport`; the gate books in the in-memory
usage store the repo-wide conftest installs. Pins:

- the paid search runs only when RF-07a's free list has fewer than 8 accounts;
- only TikTok — Instagram answers its sentence and calls nothing;
- the query is built from the rubro catalog (no product search), the same search always
  has the same parameters;
- every credit is booked as `discover_accounts_search` to the business and brand; its
  own 50/day and 200/month stop it before any call, with the exact sentences; the
  business's 150/600 also stops it; an uncapped business skips only the own budget;
- the same search again (same day, double click, another business) costs nothing; an
  empty search is kept too;
- the accounts found join RF-07a's list and are never labeled by the search;
- two businesses: one's spend never counts against the other's budget, and one's labels
  never hide accounts from the other.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest

from qualify_api.creators import discover_paid as dp
from qualify_api.creators.discover_accounts import (
    DiscoveredAccount,
    DiscoverFilters,
    MemoryDiscoverStore,
)
from qualify_api.creators.repository import MemoryCreatorPoolRepository
from qualify_api.referentes.discovery_seed import NICHE_LABELS
from qualify_api.referentes.repository import MemoryReferentesRepository
from qualify_api.vendors import scrapecreators as sc
from qualify_api.vendors import uncapped, usage

#: Real time: the gate books at the clock's now, so the budget is read at the same moment.
NOW = datetime.now(UTC)
BOGOTA = ZoneInfo("America/Bogota")


def _video(handle: str, *, region: str = "CO", followers: int = 12_000) -> dict[str, Any]:
    """One `search_item_list[]` item in the shape of `/v1/tiktok/search/keyword`
    (`aweme_info` with `author`, `statistics`, `region`, `text_extra` — the fields
    `Qualify/creator_discovery.py` and `region_rubro` read, measured 2026-09-11 and
    2026-11-25). Synthetic handles: no real person."""
    return {
        "aweme_info": {
            "aweme_id": f"v-{handle}",
            "desc": f"probando #{handle}",
            "region": region,
            "author": {
                "unique_id": handle,
                "nickname": handle.title(),
                "signature": "comida casera",
                "follower_count": followers,
                "avatar_medium": {"url_list": [f"https://p16.tiktokcdn.com/{handle}.jpg"]},
            },
            "statistics": {"play_count": 5000, "digg_count": 300, "comment_count": 20},
            "text_extra": [{"hashtag_name": "Cucutafood"}],
        }
    }


def _answer(handles: list[str], *, cursor: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"success": True, "search_item_list": [_video(h) for h in handles]}
    if cursor:
        body["cursor"] = cursor
        body["has_more"] = True
    return body


class Vendor:
    """The keyword search, answered per (query, cursor)."""

    def __init__(
        self,
        pages: dict[tuple[str, str], dict[str, Any]] | None = None,
        *,
        status: int = 200,
    ) -> None:
        self.pages = pages or {}
        self.status = status
        self.requests: list[httpx.Request] = []
        self._lock = threading.Lock()

    def handler(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            self.requests.append(request)
        assert request.url.path == dp.PATH
        if self.status != 200:
            return httpx.Response(self.status, json={"success": False, "error": "not_found"})
        key = (request.url.params["query"], request.url.params.get("cursor", ""))
        # five accounts by default: the list stays under 8, so a repeat runs the search
        body = self.pages.get(key) or _answer([f"cuenta{i}" for i in range(5)])
        return httpx.Response(200, json={**body, "credits_charged": 1})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "test-key-not-real")


def _ledger() -> usage.InMemoryUsageStore:
    store = usage.store()
    assert isinstance(store, usage.InMemoryUsageStore)  # conftest installs it
    return store


class World:
    """One shared pool, one labels repository, any number of businesses."""

    def __init__(self) -> None:
        self.labels = MemoryReferentesRepository()
        self.discover = MemoryDiscoverStore(labels_repo=self.labels)
        self.pool = dp.MemoryPaidSearchPool(MemoryCreatorPoolRepository(), self.discover)

    def business(self) -> tuple[UUID, UUID]:
        tenant, brand = uuid4(), uuid4()
        self.labels.add_brand(tenant_id=tenant, brand_id=brand)
        self.discover.brands[brand] = tenant
        _ledger().zones[tenant] = "America/Bogota"
        return tenant, brand

    def search(
        self,
        tenant: UUID,
        brand: UUID,
        vendor: Vendor,
        *,
        network: str = "tiktok",
        rubro: str = "food_drink",
        city: str = "Cúcuta",
        filters: DiscoverFilters | None = None,
        now: datetime = NOW,
    ) -> dp.PaidSearchOutcome:
        return dp.search_more_accounts(
            tenant_id=tenant,
            brand_id=brand,
            requested_by=uuid4(),
            network=network,
            rubro=rubro,
            city=city,
            region_code="CO",
            filters=filters or DiscoverFilters(),
            store=self.discover,
            pool=self.pool,
            client=vendor.client(),
            zone=BOGOTA,
            now=now,
        )


def _events(tenant: UUID) -> list[usage.UsageEvent]:
    return [e for e in _ledger().of(tenant) if e.feature == dp.FEATURE]


def _spend(tenant: UUID, credits: int, *, feature: str = dp.FEATURE, at: datetime = NOW) -> None:
    event = usage.UsageEvent(
        tenant,
        None,
        usage.SCRAPECREATORS,
        feature,
        credits,
        usage.usd_per_credit() * credits,
        usage.PRICING_TABLE_VERSION,
        f"k:{uuid4()}",
        created_at=at,
    )
    assert _ledger().book(event, capped=False) is None


# --------------------------------------------------------------------------------------


def test_exact_client_texts() -> None:
    assert dp.DAILY_CAP_TEXT == (
        "Hoy ya se alcanzó el límite de búsquedas de tu negocio. Inténtalo mañana."
    )
    assert dp.INSTAGRAM_TEXT == "Por ahora la búsqueda de cuentas nuevas solo funciona en TikTok."
    assert dp.SEARCH_BUTTON == "Buscar más cuentas en TikTok"
    assert "{renewal}" in dp.MONTHLY_CAP_TEXT


def test_budget_constants_and_feature() -> None:
    assert (dp.SEARCH_DAY_CAP, dp.SEARCH_MONTH_CAP) == (50, 200)
    assert dp.FEATURE == "discover_accounts_search" == sc.FEATURE_DISCOVER_SEARCH
    assert dp.FEATURE in sc.FEATURES
    assert dp.SEARCH_MAX_CREDITS == 2


def test_rubro_words_cover_the_catalog_and_build_stable_queries() -> None:
    assert set(dp.RUBRO_QUERIES) == set(NICHE_LABELS)
    assert dp.build_query("food_drink", "  Cúcuta ") == "comida cúcuta"
    assert dp.build_query("fitness_health") == "gimnasio"
    assert dp.place_for("", "ve") == "Venezuela"
    assert dp.place_for(" San  Cristóbal ", "VE") == "San Cristóbal"
    assert dp.place_for("", "QQ") == ""  # a country the seed tables do not name
    with pytest.raises(ValueError):
        dp.build_query("otro", "Cúcuta")  # nothing to search for
    with pytest.raises(ValueError):
        dp.build_query("pizza hawaiana")  # never a product


def test_runs_only_when_the_free_list_has_fewer_than_eight() -> None:
    world = World()
    tenant, brand = world.business()
    for i in range(8):
        world.discover.add(DiscoveredAccount(network="tiktok", handle=f"libre{i}"))
    vendor = Vendor()
    outcome = world.search(tenant, brand, vendor)
    assert outcome.status == "enough_results" and outcome.credits == 0
    assert vendor.requests == [] and _events(tenant) == []
    assert outcome.page is not None and outcome.page.total == 8

    # seven free accounts: the search runs
    world2 = World()
    tenant2, brand2 = world2.business()
    for i in range(7):
        world2.discover.add(DiscoveredAccount(network="tiktok", handle=f"libre{i}"))
    outcome = world2.search(tenant2, brand2, vendor)
    assert outcome.status == "searched" and outcome.credits == 1
    assert len(vendor.requests) == 1


def test_instagram_answers_its_sentence_and_calls_nothing() -> None:
    world = World()
    tenant, brand = world.business()
    vendor = Vendor()
    outcome = world.search(tenant, brand, vendor, network="Instagram")
    assert outcome.status == "instagram_unsupported"
    assert outcome.message == dp.INSTAGRAM_TEXT
    assert vendor.requests == [] and _ledger().of(tenant) == []


def test_a_search_books_its_feature_and_its_accounts_join_the_free_list() -> None:
    world = World()
    tenant, brand = world.business()
    vendor = Vendor({("comida cúcuta", ""): _answer([f"local{i}" for i in range(9)])})
    outcome = world.search(tenant, brand, vendor)

    assert outcome.status == "searched" and outcome.credits == 1
    assert outcome.query == "comida cúcuta" and outcome.message is None
    request = vendor.requests[0]
    assert request.url.params["query"] == "comida cúcuta"
    assert request.url.params["region"] == "CO"
    (event,) = _events(tenant)
    assert (event.brand_id, event.credits) == (brand, 1)
    assert event.usd_estimate == usage.usd_per_credit()
    # the accounts are in RF-07a's list, with their source and the country TikTok gave
    assert outcome.page is not None and outcome.page.total == 9
    account = outcome.page.accounts[0]
    assert account.followers == 12_000 and account.followers_source == "search"
    assert account.region_code == "CO" and account.region_source == "tiktok_region"
    # provenance: the kept answer and the sighting of the query
    assert len(outcome.payload_ids) == 1 and outcome.version == dp.PAID_SEARCH_VERSION
    sightings = world.pool.repository.sightings.values()
    assert {(s.kind, s.term, s.country_code) for s in sightings} == {
        ("keyword", "comida cúcuta", "CO")
    }
    # assisted: nothing was labeled
    assert not world.labels.labels(tenant_id=tenant, brand_id=brand)


def test_the_same_search_again_costs_nothing() -> None:
    world = World()
    tenant, brand = world.business()
    vendor = Vendor()
    first = world.search(tenant, brand, vendor)
    second = world.search(tenant, brand, vendor, now=NOW + timedelta(hours=3))
    assert (first.status, first.credits) == ("searched", 1)
    assert (second.status, second.credits) == ("cached", 0)
    assert len(vendor.requests) == 1 and len(_events(tenant)) == 1
    assert second.found == first.found

    # another business, same search inside the week: also free, and books nothing
    other, other_brand = world.business()
    third = world.search(other, other_brand, vendor, now=NOW + timedelta(days=2))
    assert (third.status, third.credits) == ("cached", 0)
    assert _ledger().of(other) == []


def test_a_double_click_pays_once() -> None:
    world = World()
    tenant, brand = world.business()
    gate = threading.Event()

    class Slow(Vendor):
        def handler(self, request: httpx.Request) -> httpx.Response:
            gate.wait(2)
            return super().handler(request)

    vendor = Slow()
    results: list[dp.PaidSearchOutcome] = []

    def click() -> None:
        results.append(world.search(tenant, brand, vendor))

    threads = [threading.Thread(target=click) for _ in range(2)]
    for t in threads:
        t.start()
    gate.set()
    for t in threads:
        t.join(5)
    assert sorted(r.credits for r in results) == [0, 1]
    assert len(vendor.requests) == 1 and len(_events(tenant)) == 1


def test_an_empty_search_is_kept_and_not_paid_again() -> None:
    world = World()
    tenant, brand = world.business()
    vendor = Vendor(status=404)
    first = world.search(tenant, brand, vendor)
    assert (first.status, first.credits) == ("searched", 1)
    assert first.message == dp.NO_NEW_TEXT and first.found == ()
    second = world.search(tenant, brand, vendor)
    assert (second.status, second.credits, second.message) == ("cached", 0, dp.NO_NEW_TEXT)
    assert len(vendor.requests) == 1


def test_a_second_page_only_when_the_first_shows_few_accounts() -> None:
    world = World()
    tenant, brand = world.business()
    vendor = Vendor(
        {
            ("comida cúcuta", ""): _answer(["a1", "a2", "a3"], cursor="30"),
            ("comida cúcuta", "30"): _answer(["b1", "b2", "b3", "b4", "b5"], cursor="60"),
        }
    )
    outcome = world.search(tenant, brand, vendor)
    assert outcome.credits == 2 == dp.SEARCH_MAX_CREDITS  # never a third page
    assert [r.url.params.get("cursor") for r in vendor.requests] == [None, "30"]
    assert len(outcome.found) == 8


def test_daily_cap_of_the_search_stops_before_any_call() -> None:
    world = World()
    tenant, brand = world.business()
    _spend(tenant, dp.SEARCH_DAY_CAP)
    vendor = Vendor()
    outcome = world.search(tenant, brand, vendor)
    assert outcome.status == "daily_cap"
    assert outcome.message == dp.DAILY_CAP_TEXT
    assert vendor.requests == [] and len(_events(tenant)) == 1  # only the spend above


def test_monthly_cap_of_the_search_names_the_renewal_day() -> None:
    world = World()
    tenant, brand = world.business()
    assert dp.SearchBudget(day=0, month=dp.SEARCH_MONTH_CAP).reached == "monthly_cap"
    assert dp.cap_text("monthly_cap", zone=BOGOTA, now=datetime(2026, 11, 25, tzinfo=UTC)) == (
        "Este mes ya se alcanzó el límite de búsquedas de tu negocio. "
        "Desde el 1 de diciembre puedes buscar de nuevo."
    )
    local = NOW.astimezone(BOGOTA)
    if local.day == 1:
        pytest.skip("on the 1st every credit of the month is also today's")
    yesterday = (local - timedelta(days=1)).replace(hour=12).astimezone(UTC)
    _spend(tenant, dp.SEARCH_MONTH_CAP, at=yesterday)
    vendor = Vendor()
    outcome = world.search(tenant, brand, vendor)
    assert outcome.status == "monthly_cap"
    assert outcome.message == dp.MONTHLY_CAP_TEXT.format(renewal=usage.renewal_label(BOGOTA, NOW))
    assert vendor.requests == []


def test_own_budget_is_apart_from_the_other_features() -> None:
    world = World()
    tenant, brand = world.business()
    # the reels runs and the Creators module spent a lot today, under the business cap
    _spend(tenant, 60, feature=sc.FEATURE_REELS_LIST)
    _spend(tenant, 40, feature=sc.FEATURE_CREATOR_PROFILE)
    assert dp.budget(tenant, now=NOW) == dp.SearchBudget(0, 0)
    outcome = world.search(tenant, brand, Vendor())
    assert outcome.status == "searched"


def test_the_business_cap_of_the_gate_also_stops_it() -> None:
    world = World()
    tenant, brand = world.business()
    _spend(tenant, usage.DAILY_CAP, feature=sc.FEATURE_REELS_LIST)
    vendor = Vendor()
    outcome = world.search(tenant, brand, vendor)
    assert outcome.status == "daily_cap" and outcome.message == dp.DAILY_CAP_TEXT
    assert vendor.requests == [] and _events(tenant) == []


def test_an_uncapped_business_skips_only_the_own_budget() -> None:
    world = World()
    tenant, brand = world.business()
    uncapped.set_uncapped_reads(tenant, True, set_by="test")
    _spend(tenant, dp.SEARCH_DAY_CAP)
    assert dp.budget(tenant, now=NOW).uncapped
    outcome = world.search(tenant, brand, Vendor())
    assert outcome.status == "searched" and outcome.credits == 1
    assert len(_events(tenant)) == 2  # still booked
    # another business keeps its budget
    other, _ = world.business()
    _spend(other, dp.SEARCH_DAY_CAP)
    assert dp.budget(other, now=NOW).reached == "daily_cap"


def test_gate_refusal_is_unavailable_not_free(monkeypatch: pytest.MonkeyPatch) -> None:
    world = World()
    tenant, brand = world.business()
    monkeypatch.setenv(sc.PAID_SWITCH_ENV, "0")
    vendor = Vendor()
    outcome = world.search(tenant, brand, vendor)
    assert outcome.status == "unavailable" and outcome.message == dp.UNAVAILABLE_TEXT
    assert vendor.requests == [] and _ledger().of(tenant) == []


def test_vendor_failure_is_an_error_and_its_credit_stays_booked() -> None:
    world = World()
    tenant, brand = world.business()
    vendor = Vendor(status=500)
    outcome = world.search(tenant, brand, vendor)
    assert outcome.status == "error" and outcome.credits == 1
    assert outcome.message == dp.UNAVAILABLE_TEXT
    assert len(_events(tenant)) == 1


def test_needs_the_owner_and_an_owned_brand() -> None:
    world = World()
    tenant, brand = world.business()
    other, _ = world.business()
    with pytest.raises(ValueError):
        dp.search_more_accounts(
            tenant_id=tenant,
            brand_id=brand,
            requested_by=None,  # type: ignore[arg-type]
            network="tiktok",
            rubro="food_drink",
            filters=DiscoverFilters(),
            store=world.discover,
            pool=world.pool,
        )
    vendor = Vendor()
    with pytest.raises(ValueError):
        world.search(other, brand, vendor)  # B asks with A's brand
    assert vendor.requests == []


def test_two_businesses_budgets_and_labels_stay_apart() -> None:
    world = World()
    a, brand_a = world.business()
    b, brand_b = world.business()
    _spend(a, dp.SEARCH_DAY_CAP)
    vendor = Vendor()

    assert world.search(a, brand_a, vendor).status == "daily_cap"
    outcome_b = world.search(b, brand_b, vendor)
    assert outcome_b.status == "searched" and outcome_b.credits == 1
    assert [e.tenant_id for e in _ledger().events if e.feature == dp.FEATURE] == [a, b]
    assert dp.budget(b, now=NOW) == dp.SearchBudget(1, 1)

    # B follows one account: it leaves B's list only
    handle = outcome_b.found[0][1]
    world.labels.set_label(
        tenant_id=b, brand_id=brand_b, network="tiktok", handle=handle, label="competencia"
    )
    seen_b = world.discover.page(tenant_id=b, brand_id=brand_b, filters=DiscoverFilters())
    seen_a = world.discover.page(tenant_id=a, brand_id=brand_a, filters=DiscoverFilters())
    assert handle not in {acc.handle for acc in seen_b.accounts}
    assert handle in {acc.handle for acc in seen_a.accounts}


def test_accounts_from_pages_adds_up_per_author_and_reads_zero_followers_as_unknown() -> None:
    page = {
        "search_item_list": [
            _video("dueña"),
            _video("dueña"),
            _video("sin_seguidores", followers=0),
            {"aweme_info": {"author": {}}},
            "basura",
        ]
    }
    facts, sightings = dp.accounts_from_pages([page], query="comida cúcuta", region_code="CO")
    by = {f.handle: f for f in facts}
    assert set(by) == {"dueña", "sin_seguidores"}
    assert by["dueña"].posts_seen == 2 and by["dueña"].views_seen == 10_000
    assert by["dueña"].hashtags == ("cucutafood",)
    assert by["sin_seguidores"].followers is None
    assert by["dueña"].read_at is None  # a feed sighting, not a profile read
    assert {s.term for s in sightings} == {"comida cúcuta"}


def test_an_answer_not_kept_is_still_used_but_never_cited() -> None:
    world = World()
    tenant, brand = world.business()

    def broken_put(*_a: object, **_k: object) -> None:
        raise RuntimeError("vendor_payloads down")

    world.pool.put_payload = broken_put  # type: ignore[method-assign]
    outcome = world.search(tenant, brand, Vendor())
    assert outcome.status == "searched" and outcome.credits == 1
    assert len(outcome.found) == 5 and outcome.payload_ids == ()
    assert outcome.page is not None
    assert all(a.region_source == "" for a in outcome.page.accounts)  # no claim without a row


def test_accounts_not_recorded_is_an_error_with_the_credit_counted() -> None:
    world = World()
    tenant, brand = world.business()

    def broken_record(*_a: object, **_k: object) -> None:
        raise RuntimeError("creators down")

    world.pool.record = broken_record  # type: ignore[method-assign]
    outcome = world.search(tenant, brand, Vendor())
    assert (outcome.status, outcome.credits, outcome.message) == (
        "error",
        1,
        dp.UNAVAILABLE_TEXT,
    )
    assert len(outcome.payload_ids) == 1  # the answer is kept: a retry is free
    again = world.pool.get_payload(dp.PATH, dp.search_params(outcome.query, "CO"))
    assert again is not None


def test_an_unreadable_pool_pays_nothing() -> None:
    world = World()
    tenant, brand = world.business()

    def broken_get(*_a: object, **_k: object) -> None:
        raise RuntimeError("pool down")

    world.pool.get_payload = broken_get  # type: ignore[method-assign]
    vendor = Vendor()
    outcome = world.search(tenant, brand, vendor)
    assert outcome.status == "unavailable" and outcome.credits == 0
    assert vendor.requests == [] and _ledger().of(tenant) == []

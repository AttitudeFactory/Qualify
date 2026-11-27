"""«Buscar más cuentas en TikTok» against Postgres (RF-07b, m-25119482).

The vendor is an `httpx.MockTransport` (nothing leaves the process); the gate books in the
real `vendor_usage_events` (`PostgresUsageStore`), the answers go to the real
`vendor_payloads`, the accounts to `creators` / `creator_sightings`, and the list is
RF-07a's SQL read. Pins:

- migration 0185's CHECK admits `discover_accounts_search`;
- a search books one credit for its business and brand under that feature, keeps its
  answer, and its accounts appear in RF-07a's list with the country TikTok gave and that
  answer as the provenance; a repeat is served from the kept answer for 0 credits;
- two businesses: one at its own daily cap is refused without a call while the other
  searches; each one's budget and rows are its own through `tenant_session` (RLS with
  `NULLIF(current_setting('app.tenant_id', true), '')::uuid`).

The pool is global and kept between runs, so every test searches a city and filters on a
region no other test uses.
"""

from __future__ import annotations

import random
import string
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creators import discover_paid as dp
from qualify_api.creators.discover_accounts import DiscoverFilters, PostgresDiscoverStore
from qualify_api.tenancy.models import Brand, Tenant
from qualify_api.vendors import usage

pytestmark = pytest.mark.db

STORE = PostgresDiscoverStore()
BOGOTA = ZoneInfo("America/Bogota")


@pytest.fixture(autouse=True)
def _postgres_ledger(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "test-key-not-real")
    usage.configure_store(usage.PostgresUsageStore())  # conftest restores the fake after


def _business() -> tuple[UUID, UUID]:
    tenant, brand = uuid4(), uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant, name="RF-07b", country="CO", timezone="America/Bogota", currency="COP"
            )
        )
        session.flush()
        session.add(Brand(id=brand, tenant_id=tenant, name="RF-07b brand"))
    return tenant, brand


def _word(n: int = 10) -> str:
    return "".join(random.choice(string.ascii_lowercase) for _ in range(n))


def _region() -> str:
    """A two-letter code that is no real country and, with high odds, no other run's."""
    return "Z" + random.choice(string.ascii_uppercase)


class Vendor:
    def __init__(self, handles: list[str], region: str) -> None:
        self.handles = handles
        self.region = region
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.path == dp.PATH
        items: list[dict[str, Any]] = [
            {
                "aweme_info": {
                    "aweme_id": uuid4().hex,
                    "region": self.region,
                    "author": {"unique_id": h, "nickname": h, "follower_count": 4_200},
                    "statistics": {"play_count": 900, "digg_count": 40, "comment_count": 3},
                }
            }
            for h in self.handles
        ]
        return httpx.Response(
            200, json={"success": True, "search_item_list": items, "credits_charged": 1}
        )

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def _search(
    tenant: UUID, brand: UUID, vendor: Vendor, *, city: str, region: str
) -> dp.PaidSearchOutcome:
    return dp.search_more_accounts(
        tenant_id=tenant,
        brand_id=brand,
        requested_by=uuid4(),
        network="tiktok",
        rubro="food_drink",
        city=city,
        region_code=region,
        filters=DiscoverFilters(region_codes=(region,)),
        store=STORE,
        pool=dp.PostgresPaidSearchPool(tenant),
        client=vendor.client(),
        zone=BOGOTA,
    )


def _events(tenant: UUID) -> list[Any]:
    with tenant_session(tenant) as session:
        return session.execute(
            text(
                "SELECT tenant_id, brand_id, feature, credits FROM vendor_usage_events "
                "WHERE feature = :f"
            ),
            {"f": dp.FEATURE},
        ).all()


def test_check_admits_the_feature() -> None:
    tenant, brand = _business()
    event = usage.UsageEvent(
        tenant,
        brand,
        usage.SCRAPECREATORS,
        dp.FEATURE,
        1,
        usage.usd_per_credit(),
        usage.PRICING_TABLE_VERSION,
        f"check:{uuid4()}",
    )
    assert usage.PostgresUsageStore().book(event, capped=True) is None
    assert len(_events(tenant)) == 1


def test_search_books_keeps_and_lists_with_provenance_then_repeats_for_free() -> None:
    tenant, brand = _business()
    region, city = _region(), _word()
    handles = [f"rf07b{_word(8)}" for _ in range(3)]
    vendor = Vendor(handles, region)

    first = _search(tenant, brand, vendor, city=city, region=region)
    assert (first.status, first.credits) == ("searched", 1)
    assert [tuple(r[1:]) for r in _events(tenant)] == [(brand, dp.FEATURE, 1)]
    assert first.page is not None
    listed = {a.handle: a for a in first.page.accounts if a.handle in handles}
    assert set(listed) == set(handles)
    account = listed[handles[0]]
    assert (account.region_code, account.region_source) == (region, "tiktok_region")
    assert (account.followers, account.followers_source) == (4_200, "search")
    (payload_id,) = first.payload_ids
    with tenant_session(tenant) as session:
        ref = session.execute(
            text("SELECT region_source_ref, region_version FROM creators WHERE handle = :h"),
            {"h": handles[0]},
        ).one()
        sighting = session.execute(
            text("SELECT kind, term, country_code FROM creator_sightings WHERE handle = :h"),
            {"h": handles[0]},
        ).one()
        kept = session.execute(
            text("SELECT path, credits_charged FROM vendor_payloads WHERE id = :id"),
            {"id": payload_id},
        ).one()
        labels = session.execute(
            text("SELECT count(*) FROM brand_account_labels WHERE brand_id = :b"), {"b": brand}
        ).scalar_one()
    assert ref == (f"vendor_payloads:{payload_id}", "region-free-1")
    assert tuple(sighting) == ("keyword", first.query, region)
    assert tuple(kept) == (dp.PATH, 1)
    assert labels == 0  # the search never follows an account for the owner

    second = _search(tenant, brand, vendor, city=city, region=region)
    assert (second.status, second.credits) == ("cached", 0)
    assert len(vendor.requests) == 1 and len(_events(tenant)) == 1
    # the repeat was served from the kept answer: it is not a new sighting
    with tenant_session(tenant) as session:
        times = session.execute(
            text("SELECT times FROM creator_sightings WHERE handle = ANY(:h)"),
            {"h": handles},
        ).scalars()
        assert set(times) == {1}


def test_two_businesses_budgets_are_their_own() -> None:
    a, brand_a = _business()
    b, brand_b = _business()
    ledger = usage.PostgresUsageStore()
    full = usage.UsageEvent(
        a,
        brand_a,
        usage.SCRAPECREATORS,
        dp.FEATURE,
        dp.SEARCH_DAY_CAP,
        usage.usd_per_credit() * dp.SEARCH_DAY_CAP,
        usage.PRICING_TABLE_VERSION,
        f"full:{uuid4()}",
    )
    assert ledger.book(full, capped=False) is None

    region, city = _region(), _word()
    vendor = Vendor([f"rf07b{_word(8)}"], region)
    refused = _search(a, brand_a, vendor, city=city, region=region)
    assert refused.status == "daily_cap" and refused.message == dp.DAILY_CAP_TEXT
    assert vendor.requests == []

    done = _search(b, brand_b, vendor, city=city, region=region)
    assert (done.status, done.credits) == ("searched", 1)
    now = datetime.now(UTC)
    assert dp.budget(a, now=now) == dp.SearchBudget(dp.SEARCH_DAY_CAP, dp.SEARCH_DAY_CAP)
    assert dp.budget(b, now=now) == dp.SearchBudget(1, 1)

    # through RLS each business sees only its own bookings, whatever it asks for
    with tenant_session(b) as session:
        seen = session.execute(
            text("SELECT DISTINCT tenant_id FROM vendor_usage_events WHERE tenant_id = ANY(:t)"),
            {"t": [a, b]},
        ).scalars()
        assert set(seen) == {b}
    with tenant_session(a) as session:
        seen = session.execute(
            text("SELECT DISTINCT tenant_id FROM vendor_usage_events WHERE tenant_id = ANY(:t)"),
            {"t": [a, b]},
        ).scalars()
        assert set(seen) == {a}

    # A cannot search with B's brand
    with pytest.raises(ValueError):
        _search(a, brand_b, vendor, city=_word(), region=region)

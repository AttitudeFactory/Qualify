"""m-25026378 — the weekly TikTok read per hashtag of a business's rubro.

What it pins, offline (every vendor answer comes from an `httpx.MockTransport`; nothing
leaves the process):

- the switch is OFF by default; off — or the gate's switch off, or no vendor key — a tick
  reads nothing and books nothing, before it looks at any business;
- each read goes through the metered gate, charged to the business under the feature
  `hashtag_weekly`; the business's cap stops it, and above 2/3 of the daily cap or 5/6 of
  the monthly one the read waits (headroom for the owner);
- the week is a KEPT answer, never a booking: a hashtag kept in the last 7 days by ANY
  business is not read again, and what is shared records no business;
- a pass stops at its first failure, and a business is attempted at most once a day;
- two passes for the same business never read at once (the claim);
- only pills the catalog accepts are read, without spending a slot on the others;
- `--all-tenants` reads only the businesses the reels worker treats as active;
- only Spanish videos of the last 90 days count (a real answer, trimmed and anonymized);
- the raw answer is kept and re-parses to the same sightings;
- re-running the same tick writes no duplicate row and charges nothing twice;
- tags only this read brought stay out of the paid classification queue;
- the CLI needs an explicit scope.
"""

from __future__ import annotations

import json
import string
import threading
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from qualify_api.hashtags import MemoryHashtagRepository, weekly
from qualify_api.hashtags import catalog as hashtag_catalog
from qualify_api.hashtags import worker as weekly_worker
from qualify_api.hashtags.repository import NewPostSighting
from qualify_api.referentes.reel_schedule import ScheduledBrand
from qualify_api.vendors import scrapecreators as sc
from qualify_api.vendors import uncapped, usage

from .test_hashtag_sightings import _Account, _Post, _seed

FIXTURE = (
    Path(__file__).parent
    / "fixtures/scrapecreators/tiktok_search_hashtag_shawarma_co_20261113_anonymized.json"
)
#: The day the fixture was read (`just sc tiktok search-hashtag --hashtag shawarma
#: --region CO --trim`, 2026-11-13).
READ_DAY = datetime(2026, 11, 13, 18, 0, tzinfo=UTC)
ON = {weekly.SWITCH_ENV: "1"}


def _word() -> str:
    return "".join(string.ascii_lowercase[int(c, 16)] for c in uuid4().hex[:10])


def _video(
    post_id: str,
    *,
    days_ago: float,
    lang: str = "es",
    views: int = 1000,
    desc: str = "",
    is_ad: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    moment = (now or datetime.now(UTC)) - timedelta(days=days_ago)
    return {
        "aweme_id": post_id,
        "desc": desc,
        "desc_language": lang,
        "create_time": int(moment.timestamp()),
        "is_ad": is_ad,
        "statistics": {"play_count": views},
    }


def _answer(tag: str, *, co_tag: str = "") -> dict[str, Any]:
    return {
        "success": True,
        "credits_remaining": 9000,
        "credits_charged": 1,
        "cursor": 2,
        "aweme_list": [
            _video(f"{tag}-1", days_ago=3, views=5000, desc=f"rico #{tag} #{co_tag or tag}"),
            _video(f"{tag}-2", days_ago=10, views=200, desc=f"#{tag}"),
        ],
    }


class Vendor:
    """The fake ScrapeCreators: answers `search/hashtag` from `answers`, records every
    request it was sent; `status` != 200 answers every request with that status."""

    def __init__(
        self, answers: dict[str, Any] | None = None, status: int = 200, charge: int = 1
    ) -> None:
        self.answers = answers or {}
        self.status = status
        self.charge = charge
        self.requests: list[httpx.Request] = []
        self._lock = threading.Lock()

    def handler(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            self.requests.append(request)
        assert request.url.path == weekly.PATH
        tag = request.url.params["hashtag"]
        if self.status != 200:
            return httpx.Response(self.status, json={"success": False, "error": "nope"})
        body = self.answers.get(tag) or _answer(tag)
        return httpx.Response(200, json={**body, "credits_charged": self.charge})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))

    def tags(self) -> list[str]:
        return [r.url.params["hashtag"] for r in self.requests]


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(weekly.API_KEY_ENV, "test-key-not-real")


def _ledger() -> usage.InMemoryUsageStore:
    store = usage.store()
    assert isinstance(store, usage.InMemoryUsageStore)  # conftest installs it
    return store


def _business(*tags: str, country: str | None = "CO") -> weekly.BusinessRubro:
    return weekly.BusinessRubro(uuid4(), tuple(tags), country, uuid4())


def _tick(
    vendor: Vendor,
    rubros: list[weekly.BusinessRubro],
    *,
    log: weekly.MemoryReadLog | None = None,
    repo: MemoryHashtagRepository | None = None,
    now: datetime | None = None,
    env: dict[str, str] | None = None,
    source: weekly.MemoryRubroSource | None = None,
    claims: weekly.MemoryClaims | None = None,
) -> tuple[weekly.TickReport, weekly.MemoryReadLog, MemoryHashtagRepository]:
    log = log or weekly.MemoryReadLog(_ledger())
    repo = repo or MemoryHashtagRepository()
    source = source or weekly.MemoryRubroSource({r.tenant_id: r for r in rubros})
    report = weekly.run_tick(
        [r.tenant_id for r in rubros],
        source=source,
        log=log,
        repository=repo,
        claims=claims or weekly.MemoryClaims(),
        client_factory=vendor.client,
        now=now,
        env=ON if env is None else env,
    )
    return report, log, repo


def _weekly_events(tenant: UUID) -> list[usage.UsageEvent]:
    return [e for e in _ledger().of(tenant) if e.feature == sc.FEATURE_HASHTAG_WEEKLY]


def _spend(tenant: UUID, credits: int, at: datetime | None = None) -> None:
    event = usage.UsageEvent(
        tenant,
        None,
        usage.SCRAPECREATORS,
        sc.FEATURE_SEARCH,
        credits,
        usage.usd_per_credit() * credits,
        usage.PRICING_TABLE_VERSION,
        f"k:{uuid4()}",
        created_at=at,
    )
    assert _ledger().book(event, capped=False) is None


# -- the switches and the key (acceptance 6, review item 1) ------------------------------


@pytest.mark.parametrize("env", [{}, {weekly.SWITCH_ENV: ""}, {weekly.SWITCH_ENV: "0"}])
def test_with_the_switch_off_nothing_is_read_or_paid(env: dict[str, str]) -> None:
    vendor = Vendor()
    business = _business("shawarma")
    source = weekly.MemoryRubroSource({business.tenant_id: business})
    report, log, _ = _tick(vendor, [business], env=env, source=source)
    assert report.stopped == "switch_off" and report.outcomes == []
    assert vendor.requests == [] and source.reads == 0
    assert _ledger().of(business.tenant_id) == [] and log.answers == {}


def test_the_switch_is_off_unless_said_on() -> None:
    assert not weekly.switch_on({})
    assert not weekly.switch_on({weekly.SWITCH_ENV: "off"})
    assert weekly.switch_on({weekly.SWITCH_ENV: " TRUE "})


def test_with_the_gate_switch_off_nothing_is_looked_at_or_booked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(sc.PAID_SWITCH_ENV, "0")
    vendor = Vendor()
    business = _business("shawarma", "falafel")
    source = weekly.MemoryRubroSource({business.tenant_id: business})
    report, _, _ = _tick(vendor, [business], source=source)
    assert report.stopped == "paid_off" and report.outcomes == []
    assert vendor.requests == [] and source.reads == 0 and _ledger().events == []


def test_without_the_vendor_key_nothing_is_looked_at_or_booked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(weekly.API_KEY_ENV)
    vendor = Vendor()
    businesses = [_business("a1", "b1", "c1", "d1", "e1") for _ in range(3)]
    source = weekly.MemoryRubroSource({b.tenant_id: b for b in businesses})
    report, _, _ = _tick(vendor, businesses, source=source)
    assert report.stopped == "no_key" and report.outcomes == []
    assert vendor.requests == [] and source.reads == 0 and _ledger().events == []


# -- charged to the business, under its own feature (acceptance 1) -----------------------


def test_each_read_is_charged_to_its_business_under_hashtag_weekly() -> None:
    vendor = Vendor()
    business = _business("shawarma", "falafel", country="VE")
    report, _, _ = _tick(vendor, [business])
    (outcome,) = report.outcomes
    assert outcome.status == weekly.DONE and outcome.read == ["shawarma", "falafel"]
    assert vendor.tags() == ["shawarma", "falafel"]
    assert {r.url.params["region"] for r in vendor.requests} == {"VE"}
    events = _weekly_events(business.tenant_id)
    assert len(events) == 2 and {e.credits for e in events} == {1}
    assert {(e.tenant_id, e.brand_id, e.vendor) for e in events} == {
        (business.tenant_id, business.brand_id, usage.SCRAPECREATORS)
    }
    assert sc.FEATURE_HASHTAG_WEEKLY in sc.FEATURES


def test_without_a_country_no_region_is_sent() -> None:
    vendor = Vendor()
    _tick(vendor, [_business("shawarma", country=None)])
    assert "region" not in vendor.requests[0].url.params


def test_at_most_five_tags_are_read_per_business() -> None:
    vendor = Vendor()
    connect = {"hashtags": [{"tag": f"#Tag{i}"} for i in range(8)], "country_code": "co"}
    rubro = weekly.business_rubro(uuid4(), [(uuid4(), connect)])
    assert rubro.tags == ("tag0", "tag1", "tag2", "tag3", "tag4") and rubro.country_code == "CO"
    _tick(vendor, [rubro])
    assert len(vendor.requests) == weekly.MAX_TAGS


def test_the_business_cap_stops_its_read_before_any_call() -> None:
    vendor = Vendor()
    business = _business("shawarma", "falafel")
    uncapped.set_uncapped_reads(business.tenant_id, False, set_by="test")
    _spend(business.tenant_id, usage.DAILY_CAP - 1)
    # 149 spent is over the headroom; exempt only the headroom here to reach the cap
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(weekly, "has_headroom", lambda tenant, now: True)
        report, _, _ = _tick(vendor, [business])
    (outcome,) = report.outcomes
    # one credit left today: the first read fits, the second is refused before leaving
    assert vendor.tags() == ["shawarma"]
    assert outcome.status == weekly.CAPPED and outcome.reason == usage.REASON_DAILY_CAP
    assert len(_weekly_events(business.tenant_id)) == 1


# -- headroom for the owner (UX review) --------------------------------------------------


def test_the_thresholds_are_shares_of_the_caps() -> None:
    assert weekly.DAILY_HEADROOM == 100 and weekly.MONTHLY_HEADROOM == 500
    assert weekly.DAILY_HEADROOM == usage.DAILY_CAP * 2 // 3
    assert weekly.MONTHLY_HEADROOM == usage.MONTHLY_CAP * 5 // 6


@pytest.mark.parametrize(("spent", "reads"), [(100, True), (101, False)])
def test_more_than_two_thirds_of_the_daily_cap_spent_waits(spent: int, reads: bool) -> None:
    vendor = Vendor()
    business = _business("shawarma")
    _spend(business.tenant_id, spent)
    report, _, _ = _tick(vendor, [business])
    assert bool(vendor.requests) is reads
    if not reads:
        assert report.outcomes[0].status == weekly.NO_HEADROOM
        assert _weekly_events(business.tenant_id) == []  # a skip books nothing


@pytest.mark.parametrize(("spent", "reads"), [(500, True), (501, False)])
def test_more_than_five_sixths_of_the_monthly_cap_spent_waits(spent: int, reads: bool) -> None:
    business = _business("shawarma")
    mid_month = datetime(2030, 1, 20, 15, tzinfo=UTC)
    # spent ten days earlier in the same month: nothing of it today
    _spend(business.tenant_id, spent, at=datetime(2030, 1, 10, 15, tzinfo=UTC))
    assert weekly.has_headroom(business.tenant_id, mid_month) is reads
    if not reads:
        vendor = Vendor()
        report, _, _ = _tick(vendor, [business], now=mid_month)
        assert vendor.requests == [] and report.outcomes[0].status == weekly.NO_HEADROOM
        assert _weekly_events(business.tenant_id) == []


def test_a_business_exempt_from_the_cap_is_not_held_back_by_the_headroom() -> None:
    vendor = Vendor()
    business = _business("shawarma")
    uncapped.set_uncapped_reads(business.tenant_id, True, set_by="test")
    _spend(business.tenant_id, usage.DAILY_CAP + 50)
    report, _, _ = _tick(vendor, [business])
    assert vendor.tags() == ["shawarma"] and report.outcomes[0].status == weekly.DONE


def test_a_headroom_skip_does_not_stop_the_next_business() -> None:
    vendor = Vendor()
    busy, fine = _business("shawarma"), _business("falafel")
    _spend(busy.tenant_id, usage.DAILY_CAP)
    report, _, _ = _tick(vendor, [busy, fine])
    assert [o.status for o in report.outcomes] == [weekly.NO_HEADROOM, weekly.DONE]
    assert vendor.tags() == ["falafel"]


# -- shared across businesses (acceptance 2) ---------------------------------------------


def test_a_hashtag_read_this_week_by_another_business_is_not_read_again() -> None:
    vendor = Vendor()
    first, second = _business("shawarma"), _business("shawarma", "falafel", country="UY")
    report, _, _ = _tick(vendor, [first, second])
    assert vendor.tags() == ["shawarma", "falafel"]  # «shawarma» once, whatever the region
    assert report.outcomes[1].fresh == ["shawarma"] and report.outcomes[1].read == ["falafel"]
    assert len(_weekly_events(second.tenant_id)) == 1


def test_what_is_shared_names_no_business() -> None:
    vendor = Vendor()
    business = _business("shawarma")
    _, log, repo = _tick(vendor, [business])
    kept = next(iter(log.answers.values()))
    assert set(kept.params) == {"hashtag", "region"}
    assert str(business.tenant_id) not in json.dumps(kept.payload)
    assert {f.name for f in fields(weekly.KeptAnswer)} == {
        "params",
        "payload",
        "status",
        "credits",
        "fetched_at",
    }
    for sighting in repo._sightings.values():  # noqa: SLF001 - the stored rows themselves
        assert sighting.source == weekly.SOURCE and sighting.source_ref == weekly.SOURCE_REF
    assert not {"tenant", "tenant_id", "brand", "brand_id", "user"} & {
        f.name for f in fields(NewPostSighting)
    }


def test_a_hashtag_read_more_than_a_week_ago_is_read_again() -> None:
    vendor = Vendor()
    log = weekly.MemoryReadLog(_ledger())
    business = _business("shawarma")
    _tick(vendor, [business], log=log)
    later = datetime.now(UTC) + timedelta(days=8)
    report, _, _ = _tick(vendor, [business], log=log, now=later)
    assert vendor.tags() == ["shawarma", "shawarma"]
    assert report.outcomes[0].status == weekly.DONE


# -- failures: stop at the first, one attempt a day (review item 1) -----------------------


def test_a_failing_vendor_costs_one_credit_and_is_not_retried_the_same_day() -> None:
    vendor = Vendor(status=500)
    business = _business("a1", "b1", "c1", "d1", "e1")
    log = weekly.MemoryReadLog(_ledger())
    report, _, _ = _tick(vendor, [business], log=log)
    (outcome,) = report.outcomes
    assert vendor.tags() == ["a1"]  # stopped at the first failure
    assert outcome.status == weekly.FAILED and outcome.errors == 1 and log.answers == {}
    assert len(_weekly_events(business.tenant_id)) == 1

    for hours in (1, 12, 23):  # the hourly passes of the same day
        again, _, _ = _tick(
            vendor, [business], log=log, now=datetime.now(UTC) + timedelta(hours=hours)
        )
        assert again.outcomes[0].status == weekly.TRIED_TODAY
    assert len(vendor.requests) == 1

    _tick(vendor, [business], log=log, now=datetime.now(UTC) + timedelta(hours=25))
    assert vendor.tags() == ["a1", "a1"]  # the next day, one more attempt


def test_a_failure_mid_way_leaves_the_rest_for_the_next_day() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        tag = request.url.params["hashtag"]
        calls.append(tag)
        if tag == "roto":
            return httpx.Response(500, json={"error": "boom"})
        return httpx.Response(200, json=_answer(tag))

    business = _business("sano", "roto", "otro")
    log = weekly.MemoryReadLog(_ledger())

    def tick(now: datetime) -> weekly.TickReport:
        return weekly.run_tick(
            [business.tenant_id],
            source=weekly.MemoryRubroSource({business.tenant_id: business}),
            log=log,
            repository=MemoryHashtagRepository(),
            claims=weekly.MemoryClaims(),
            client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
            now=now,
            env=ON,
        )

    first = tick(datetime.now(UTC))
    assert calls == ["sano", "roto"]
    assert first.outcomes[0].read == ["sano"] and first.outcomes[0].status == weekly.FAILED
    second = tick(datetime.now(UTC) + timedelta(hours=25))
    assert calls == ["sano", "roto", "roto"]  # «sano» is kept for the week
    assert second.outcomes[0].fresh == ["sano"]


def test_a_booking_without_a_kept_answer_is_not_the_week() -> None:
    """A pass that died after paying: the booking holds the business for the day only;
    the hashtag is read the next day because no answer was kept."""
    business = _business("shawarma", "falafel")
    booked = usage.UsageEvent(
        business.tenant_id,
        business.brand_id,
        usage.SCRAPECREATORS,
        sc.FEATURE_HASHTAG_WEEKLY,
        1,
        usage.usd_per_credit(),
        usage.PRICING_TABLE_VERSION,
        f"k:{uuid4()}",
    )
    _ledger().book(booked, capped=True)
    vendor = Vendor()
    report, log, _ = _tick(vendor, [business])
    assert vendor.requests == [] and report.outcomes[0].status == weekly.TRIED_TODAY
    _tick(vendor, [business], log=log, now=datetime.now(UTC) + timedelta(hours=25))
    assert vendor.tags() == ["shawarma", "falafel"]


# -- one pass at a time per business (review item 2) -------------------------------------


def test_two_concurrent_passes_read_a_business_once() -> None:
    entered, release = threading.Event(), threading.Event()
    vendor = Vendor()

    def slow(request: httpx.Request) -> httpx.Response:
        entered.set()
        assert release.wait(5)
        return vendor.handler(request)

    business = _business("shawarma", "falafel")
    log, claims = weekly.MemoryReadLog(_ledger()), weekly.MemoryClaims()
    reports: list[weekly.TickReport] = []

    def one() -> None:
        reports.append(
            weekly.run_tick(
                [business.tenant_id],
                source=weekly.MemoryRubroSource({business.tenant_id: business}),
                log=log,
                repository=MemoryHashtagRepository(),
                claims=claims,
                client_factory=lambda: httpx.Client(transport=httpx.MockTransport(slow)),
                env=ON,
            )
        )

    first = threading.Thread(target=one)
    first.start()
    assert entered.wait(5)  # the first pass is inside its first request
    second = threading.Thread(target=one)
    second.start()
    second.join(5)
    release.set()
    first.join(5)
    assert sorted(r.outcomes[0].status for r in reports) == [weekly.BUSY, weekly.DONE]
    assert vendor.tags() == ["shawarma", "falafel"]
    assert len(_weekly_events(business.tenant_id)) == 2


# -- pills the catalog would refuse (review item 3) --------------------------------------


@pytest.mark.parametrize(
    "bad", ["🍔", "c++", "...", "x" * 300, "#", "dos palabras", "_", "a.b", "", None, 7]
)
def test_a_pill_the_catalog_would_refuse_is_never_read(bad: object) -> None:
    assert weekly.readable_tag(bad) is None
    connect = {"hashtags": [{"tag": bad}, *({"tag": f"t{i}"} for i in range(5))]}
    assert weekly.rubro_tags(connect) == ("t0", "t1", "t2", "t3", "t4")  # no slot taken
    vendor = Vendor()
    _tick(vendor, [weekly.business_rubro(uuid4(), [(uuid4(), connect)])])
    assert vendor.tags() == ["t0", "t1", "t2", "t3", "t4"]


def test_readable_tags_keep_accents_digits_and_the_length_cap() -> None:
    assert weekly.readable_tag("#Arepería") == "arepería"
    assert weekly.readable_tag("pizza_24h") == "pizza_24h"
    assert weekly.readable_tag("x" * weekly.MAX_TAG_LENGTH) == "x" * weekly.MAX_TAG_LENGTH
    assert weekly.readable_tag("x" * (weekly.MAX_TAG_LENGTH + 1)) is None


# -- only active businesses in production (review item 4) --------------------------------


class _Opened:
    def __init__(self, brands: list[ScheduledBrand]) -> None:
        self.brands = brands
        self.since: list[datetime] = []

    def opened_brands(self, *, since: datetime) -> list[ScheduledBrand]:
        self.since.append(since)
        return [b for b in self.brands if b.last_opened_at >= since]


def test_all_tenants_reads_only_businesses_the_reels_worker_treats_as_active() -> None:
    now = datetime(2026, 11, 13, 12, tzinfo=UTC)
    active, stale = uuid4(), uuid4()
    queue = _Opened(
        [
            ScheduledBrand(active, uuid4(), "America/Bogota", now - timedelta(days=3)),
            ScheduledBrand(active, uuid4(), "America/Bogota", now - timedelta(days=1)),
            ScheduledBrand(stale, uuid4(), "America/Bogota", now - timedelta(days=15)),
        ]
    )
    source = weekly.PostgresRubroSource(queue=queue)
    assert source.businesses(None, now=now) == [active]
    explicit = [stale, stale]
    assert source.businesses(explicit, now=now) == [stale]  # --tenant is the operator's


# -- the filter: Spanish, last 90 days (acceptance 3) ------------------------------------


def test_only_spanish_videos_of_the_last_90_days_count_in_a_real_answer() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert len(payload["aweme_list"]) == 20
    sightings = weekly.parse_videos("shawarma", payload, now=READ_DAY)
    posts = {s.post_id for s in sightings}
    # 14 of the 20 are in Spanish; 6 of those were posted after 2026-08-15
    assert posts == {f"7000000000000000{n:03d}" for n in (6, 9, 11, 12, 14, 16)}
    by_post = {s.post_id: s for s in sightings if s.tag == "shawarma"}
    assert set(by_post) == posts  # the read tag is on every counted video
    assert by_post["7000000000000000006"].views == 13712
    cutoff = READ_DAY - timedelta(days=90)
    assert all(s.posted_at is not None and s.posted_at >= cutoff for s in sightings)
    assert {s.parser_version for s in sightings} == {weekly.PARSER_VERSION}
    assert "comidarapida" in {s.tag for s in sightings}  # co-occurring tags ride along


def test_ads_undated_and_foreign_videos_do_not_count() -> None:
    now = datetime.now(UTC)
    payload = {
        "aweme_list": [
            _video("ok", days_ago=1, now=now),
            _video("ad", days_ago=1, is_ad=True, now=now),
            _video("en", days_ago=1, lang="en", now=now),
            _video("old", days_ago=91, now=now),
            {**_video("undated", days_ago=1, now=now), "create_time": None},
            {**_video("future", days_ago=-3, now=now)},
            {**_video("", days_ago=1, now=now)},
            "not a video",
        ]
    }
    assert {s.post_id for s in weekly.parse_videos("tag", payload, now=now)} == {"ok"}


def test_text_extra_hashtags_are_read_and_a_bad_tag_is_skipped() -> None:
    now = datetime.now(UTC)
    video = {**_video("v1", days_ago=1, desc="#Uno #", now=now)}
    video["text_extra"] = [{"hashtag_name": "Dos"}, {"hashtag_name": ""}, "x", {}]
    tags = {s.tag for s in weekly.parse_videos("leído", {"aweme_list": [video]}, now=now)}
    assert tags == {"leído", "uno", "dos"}


# -- the raw answer is kept (acceptance 4) -----------------------------------------------


def test_the_raw_answer_is_kept_and_re_parses_to_the_same_sightings() -> None:
    now = datetime.now(UTC)
    vendor = Vendor({"shawarma": _answer("shawarma", co_tag="arabe")})
    _, log, repo = _tick(vendor, [_business("shawarma")], now=now)
    (kept,) = log.answers.values()
    assert kept.status == 200 and kept.credits == 1 and kept.fetched_at == now
    assert kept.payload["aweme_list"] == vendor.answers["shawarma"]["aweme_list"]
    again = {(s.tag, s.post_id) for s in weekly.parse_videos("shawarma", kept.payload, now=now)}
    assert again == {(t, p) for (t, _n, p) in repo._sightings}  # noqa: SLF001


def test_an_empty_search_is_kept_as_read_and_writes_nothing() -> None:
    vendor = Vendor(status=404)
    log = weekly.MemoryReadLog(_ledger())
    business = _business("nadie")
    report, _, repo = _tick(vendor, [business], log=log)
    (kept,) = log.answers.values()
    assert kept.status == 404 and report.outcomes[0].read == ["nadie"]
    assert report.outcomes[0].status == weekly.DONE and repo._sightings == {}  # noqa: SLF001
    again, _, _ = _tick(vendor, [business], log=log, now=datetime.now(UTC) + timedelta(days=2))
    assert len(vendor.requests) == 1  # a 404 is an answer: not asked again this week
    assert again.outcomes[0].status == weekly.UP_TO_DATE


# -- idempotency (acceptance 5) ----------------------------------------------------------


def test_re_running_the_same_tick_writes_nothing_twice_and_charges_nothing_twice() -> None:
    now = datetime.now(UTC)
    vendor = Vendor()
    business = _business("shawarma", "falafel")
    log, repo = weekly.MemoryReadLog(_ledger()), MemoryHashtagRepository()
    first, _, _ = _tick(vendor, [business], log=log, repo=repo, now=now)
    rows, events = dict(repo._sightings), list(_ledger().events)  # noqa: SLF001
    second, _, _ = _tick(vendor, [business], log=log, repo=repo, now=now)
    assert len(vendor.requests) == 2  # the first tick's two reads, nothing more
    assert second.outcomes[0].status == weekly.UP_TO_DATE
    assert repo._sightings == rows and _ledger().events == events  # noqa: SLF001
    assert first.outcomes[0].sightings == len(rows)


def test_a_business_without_rubro_hashtags_is_never_read() -> None:
    vendor = Vendor()
    report, _, _ = _tick(vendor, [_business()])
    assert vendor.requests == [] and report.outcomes[0].status == weekly.NO_TAGS


# -- the paid classification queue (acceptance 7) ----------------------------------------


def test_tags_only_the_weekly_read_brought_stay_out_of_the_classification_queue() -> None:
    co_tag = _word()
    vendor = Vendor({"shawarma": _answer("shawarma", co_tag=co_tag)})
    _, _, repo = _tick(vendor, [_business("shawarma")])
    assert repo.get(uuid4(), co_tag) is not None
    queued = {t.tag for t in repo.needs_classification(uuid4(), limit=100_000)}
    assert co_tag not in queued and "shawarma" not in queued

    # the same tag later counted by a referentes search joins the queue
    accounts = [_Account("tiktok", "a", [co_tag], [_Post("v9", None, 1, (co_tag,))])]
    hashtag_catalog.capture(uuid4(), _seed(), "national", accounts, repository=repo)
    assert co_tag in {t.tag for t in repo.needs_classification(uuid4(), limit=100_000)}


# -- the rubro ---------------------------------------------------------------------------


def test_rubro_tags_are_the_pills_normalized_in_order() -> None:
    connect = {
        "hashtags": [
            {"tag": " #Shawarma "},
            {"tag": "shawarma"},
            {"tag": "dos palabras"},
            {"tag": 3},
            "suelto",
            {"tag": "Falafel", "origin": "ai"},
        ]
    }
    assert weekly.rubro_tags(connect) == ("shawarma", "falafel")
    assert weekly.rubro_tags({}) == () and weekly.rubro_tags({"hashtags": "x"}) == ()


def test_the_business_country_is_the_fallback_region() -> None:
    tenant, brand = uuid4(), uuid4()
    rubro = weekly.business_rubro(tenant, [(brand, {"hashtags": [{"tag": "x"}]})], "uy")
    assert rubro == weekly.BusinessRubro(tenant, ("x",), "UY", brand)
    assert weekly.business_rubro(tenant, [], "Colombia").country_code is None


# -- the CLI -----------------------------------------------------------------------------


def test_the_cli_needs_an_explicit_scope() -> None:
    with pytest.raises(SystemExit):
        weekly_worker.main(["--once"], tick=lambda ids: weekly.TickReport())


def test_the_cli_runs_one_pass_for_the_given_tenant() -> None:
    tenant = uuid4()
    seen: list[object] = []

    def tick(ids: object) -> weekly.TickReport:
        seen.append(ids)
        return weekly.TickReport(stopped="switch_off")

    assert weekly_worker.main(["--tenant", str(tenant), "--once"], tick=tick) == 0
    assert seen == [[tenant]]
    assert weekly_worker.main(["--all-tenants", "--once"], tick=tick) == 0
    assert seen[-1] is None


@pytest.mark.parametrize("stopped", ["below_floor", "no_key"])
def test_the_cli_fails_a_pass_with_errors_or_a_global_stop(stopped: str) -> None:
    tenant = str(uuid4())
    broken = weekly.TickReport([weekly.BusinessOutcome(uuid4(), weekly.DONE, errors=1)])
    assert weekly_worker.main(["--tenant", tenant, "--once"], tick=lambda ids: broken) == 1
    report = weekly.TickReport(stopped=stopped)
    assert weekly_worker.main(["--tenant", tenant, "--once"], tick=lambda ids: report) == 1


# -- five a week per business, hard (second review, item B) -------------------------------


class _Clock:
    """The simulated moment the gate's in-memory ledger stamps its bookings with."""

    at = datetime(2030, 3, 1, 9, tzinfo=UTC)


class _ClockedDatetime(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
        return _Clock.at


def _simulate_month(
    monkeypatch: pytest.MonkeyPatch,
    *,
    change_every: int,
    fails: Any = lambda day: False,
    charge: int = 1,
) -> list[usage.UsageEvent]:
    """31 days, a pass every 12 hours, the owner's five pills replaced every
    `change_every` days; the vendor answers 500 on the days `fails` says and charges
    `charge` credits per answer."""
    monkeypatch.setattr(usage, "datetime", _ClockedDatetime)
    business = _business("x")
    log, claims = weekly.MemoryReadLog(_ledger()), weekly.MemoryClaims()
    repo = MemoryHashtagRepository()
    start = datetime(2030, 3, 1, 9, tzinfo=UTC)
    for half_day in range(62):
        day = half_day // 2
        _Clock.at = start + timedelta(hours=12 * half_day)
        tags = tuple(f"p{day // change_every}x{i}" for i in range(5))
        rubro = weekly.BusinessRubro(business.tenant_id, tags, "CO", business.brand_id)
        vendor = Vendor(status=500 if fails(day) else 200, charge=charge)
        weekly.run_tick(
            [business.tenant_id],
            source=weekly.MemoryRubroSource({business.tenant_id: rubro}),
            log=log,
            repository=repo,
            claims=claims,
            client_factory=vendor.client,
            now=_Clock.at,
            env=ON,
        )
    return _weekly_events(business.tenant_id)


def _max_in_any_week(events: list[usage.UsageEvent]) -> int:
    """The most CREDITS (`:extra` rows included) booked in any rolling 7 days."""
    dated = [(e.created_at, e.credits) for e in events if e.created_at is not None]
    return max(
        (sum(c for t, c in dated if s <= t < s + timedelta(days=7)) for s, _ in dated),
        default=0,
    )


def test_a_vendor_charging_three_per_call_overshoots_a_week_by_at_most_two(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = _simulate_month(monkeypatch, change_every=1, charge=3)
    assert {e.credits for e in events} == {1, 2}  # the booked credit and its `:extra` row
    # two calls a week: 3, then 6 ≥ 5 stops the pass — never 5 calls × 3 = 15
    assert _max_in_any_week(events) == weekly.MAX_TAGS + 1
    assert sum(e.credits for e in events) <= 5 * (weekly.MAX_TAGS + 3 - 1)  # 5 windows


@pytest.mark.parametrize("change_every", [3, 1])
def test_changing_pills_never_buys_more_than_five_reads_a_week(
    monkeypatch: pytest.MonkeyPatch, change_every: int
) -> None:
    events = _simulate_month(monkeypatch, change_every=change_every)
    assert len(events) >= 20  # it keeps reading, within the bound
    assert _max_in_any_week(events) <= weekly.MAX_TAGS
    assert sum(e.credits for e in events) <= 25


def test_an_intermittently_failing_vendor_stays_inside_the_same_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = _simulate_month(monkeypatch, change_every=2, fails=lambda day: day % 3 == 1)
    assert events  # it did read and fail along the way
    assert _max_in_any_week(events) <= weekly.MAX_TAGS
    assert sum(e.credits for e in events) <= 25


def test_a_business_that_spent_its_week_waits_even_with_new_pills() -> None:
    business = _business("nuevo")
    for _ in range(weekly.MAX_TAGS):
        booked = usage.UsageEvent(
            business.tenant_id,
            business.brand_id,
            usage.SCRAPECREATORS,
            sc.FEATURE_HASHTAG_WEEKLY,
            1,
            usage.usd_per_credit(),
            usage.PRICING_TABLE_VERSION,
            f"k:{uuid4()}",
            created_at=datetime.now(UTC) - timedelta(days=2),
        )
        _ledger().book(booked, capped=False)
    vendor = Vendor()
    report, _, _ = _tick(vendor, [business])
    assert vendor.requests == [] and report.outcomes[0].status == weekly.WEEK_SPENT


# -- one reader per hashtag (second review, item C) --------------------------------------


def test_two_businesses_sharing_a_hashtag_at_once_pay_for_it_once() -> None:
    entered, release = threading.Event(), threading.Event()
    vendor = Vendor()

    def slow(request: httpx.Request) -> httpx.Response:
        entered.set()
        assert release.wait(5)
        return vendor.handler(request)

    first, second = _business("shawarma"), _business("shawarma")
    log, claims = weekly.MemoryReadLog(_ledger()), weekly.MemoryClaims()
    outcomes: dict[UUID, weekly.BusinessOutcome] = {}

    def one(rubro: weekly.BusinessRubro) -> None:
        report = weekly.run_tick(
            [rubro.tenant_id],
            source=weekly.MemoryRubroSource({rubro.tenant_id: rubro}),
            log=log,
            repository=MemoryHashtagRepository(),
            claims=claims,
            client_factory=lambda: httpx.Client(transport=httpx.MockTransport(slow)),
            env=ON,
        )
        outcomes[rubro.tenant_id] = report.outcomes[0]

    a = threading.Thread(target=one, args=(first,))
    a.start()
    assert entered.wait(5)
    b = threading.Thread(target=one, args=(second,))
    b.start()
    b.join(5)
    release.set()
    a.join(5)
    assert len(vendor.requests) == 1
    assert outcomes[second.tenant_id].busy == ["shawarma"]
    assert _weekly_events(second.tenant_id) == []
    # the next pass of the second business finds the first one's kept answer
    report, _, _ = _tick(vendor, [second], log=log, claims=claims)
    assert report.outcomes[0].status == weekly.UP_TO_DATE and len(vendor.requests) == 1


def test_a_hashtag_kept_while_waiting_for_its_claim_is_not_paid() -> None:
    """The re-check inside the claim: kept between the pass's first look and its read."""
    business = _business("shawarma")
    log = weekly.MemoryReadLog(_ledger())

    class _KeptMeanwhile(weekly.MemoryClaims):
        def claim_tag(self, tenant_id: UUID, tag: str) -> Any:
            log.keep(tenant_id, {"hashtag": tag}, {}, status=200, credits=1, now=datetime.now(UTC))
            return super().claim_tag(tenant_id, tag)

    vendor = Vendor()
    report, _, _ = _tick(vendor, [business], log=log, claims=_KeptMeanwhile())
    assert vendor.requests == [] and report.outcomes[0].fresh == ["shawarma"]

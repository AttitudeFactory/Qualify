"""m-25026378 — the weekly TikTok read per hashtag of a business's rubro.

What it pins, offline (every vendor answer comes from an `httpx.MockTransport`; nothing
leaves the process):

- the switch is OFF by default and, off, a tick reads nothing — no database, no vendor;
- each read goes through the metered gate, charged to the business under the feature
  `hashtag_weekly`, and the business's cap stops it;
- a hashtag read in the last 7 days by ANY business is not read again, and what is
  shared records no business;
- only Spanish videos of the last 90 days count (a real answer, trimmed and anonymized);
- the raw answer is kept and re-parses to the same sightings;
- re-running the same tick writes no duplicate row and charges nothing twice;
- tags only this read brought stay out of the paid classification queue;
- the CLI needs an explicit scope.
"""

from __future__ import annotations

import json
import string
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
from qualify_api.vendors import scrapecreators as sc
from qualify_api.vendors import usage

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
    request it was sent."""

    def __init__(self, answers: dict[str, Any] | None = None, status: int = 200) -> None:
        self.answers = answers or {}
        self.status = status
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.path == weekly.PATH
        tag = request.url.params["hashtag"]
        if self.status != 200:
            return httpx.Response(self.status, json={"success": False, "error": "not_found"})
        return httpx.Response(200, json=self.answers.get(tag) or _answer(tag))

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))

    def tags(self) -> list[str]:
        return [r.url.params["hashtag"] for r in self.requests]


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "test-key-not-real")


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
) -> tuple[weekly.TickReport, weekly.MemoryReadLog, MemoryHashtagRepository]:
    log = log or weekly.MemoryReadLog(_ledger())
    repo = repo or MemoryHashtagRepository()
    source = source or weekly.MemoryRubroSource({r.tenant_id: r for r in rubros})
    report = weekly.run_tick(
        [r.tenant_id for r in rubros],
        source=source,
        log=log,
        repository=repo,
        client_factory=vendor.client,
        now=now,
        env=ON if env is None else env,
    )
    return report, log, repo


def _weekly_events(tenant: UUID) -> list[usage.UsageEvent]:
    return [e for e in _ledger().of(tenant) if e.feature == sc.FEATURE_HASHTAG_WEEKLY]


# -- the switch (acceptance 6) -----------------------------------------------------------


@pytest.mark.parametrize("env", [{}, {weekly.SWITCH_ENV: ""}, {weekly.SWITCH_ENV: "0"}])
def test_with_the_switch_off_nothing_is_read_or_paid(env: dict[str, str]) -> None:
    vendor = Vendor()
    business = _business("shawarma")
    source = weekly.MemoryRubroSource({business.tenant_id: business})
    report, log, repo = _tick(vendor, [business], env=env, source=source)
    assert report.stopped == "switch_off" and report.outcomes == []
    assert vendor.requests == [] and source.reads == 0
    assert _ledger().of(business.tenant_id) == [] and log.answers == {}


def test_the_switch_is_off_unless_said_on() -> None:
    assert not weekly.switch_on({})
    assert not weekly.switch_on({weekly.SWITCH_ENV: "off"})
    assert weekly.switch_on({weekly.SWITCH_ENV: " TRUE "})


def test_the_gate_kill_switch_still_stops_the_weekly_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(sc.PAID_SWITCH_ENV, "0")
    vendor = Vendor()
    first, second = _business("shawarma"), _business("falafel")
    report, _, _ = _tick(vendor, [first, second])
    assert vendor.requests == []
    assert report.stopped == "switch_off"  # a global refusal stops the whole pass
    assert [o.status for o in report.outcomes] == [weekly.BLOCKED]


# -- charged to the business, under its own feature (acceptance 1) -----------------------


def test_each_read_is_charged_to_its_business_under_hashtag_weekly() -> None:
    vendor = Vendor()
    business = _business("shawarma", "falafel", country="VE")
    report, log, repo = _tick(vendor, [business])
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
    spent = usage.UsageEvent(
        business.tenant_id,
        None,
        usage.SCRAPECREATORS,
        sc.FEATURE_SEARCH,
        usage.DAILY_CAP - 1,
        usage.usd_per_credit(),
        usage.PRICING_TABLE_VERSION,
        f"k:{uuid4()}",
    )
    assert _ledger().book(spent, capped=True) is None
    report, _, _ = _tick(vendor, [business])
    (outcome,) = report.outcomes
    # one credit left today: the first read fits, the second is refused before leaving
    assert vendor.tags() == ["shawarma"]
    assert outcome.status == weekly.CAPPED and outcome.reason == usage.REASON_DAILY_CAP
    assert len(_weekly_events(business.tenant_id)) == 1


def test_a_capped_business_does_not_stop_the_next_one() -> None:
    vendor = Vendor()
    capped, fine = _business("shawarma"), _business("falafel")
    full = usage.UsageEvent(
        capped.tenant_id,
        None,
        usage.SCRAPECREATORS,
        sc.FEATURE_SEARCH,
        usage.DAILY_CAP,
        usage.usd_per_credit(),
        usage.PRICING_TABLE_VERSION,
        f"k:{uuid4()}",
    )
    _ledger().book(full, capped=True)
    report, _, _ = _tick(vendor, [capped, fine])
    assert [o.status for o in report.outcomes] == [weekly.CAPPED, weekly.DONE]
    assert vendor.tags() == ["falafel"]


# -- shared across businesses (acceptance 2) ---------------------------------------------


def test_a_hashtag_read_this_week_by_another_business_is_not_read_again() -> None:
    vendor = Vendor()
    first, second = _business("shawarma"), _business("shawarma", "falafel", country="UY")
    report, log, _ = _tick(vendor, [first, second])
    assert vendor.tags() == ["shawarma", "falafel"]  # «shawarma» once, whatever the region
    assert report.outcomes[1].shared == ["shawarma"] and report.outcomes[1].read == ["falafel"]
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
    _tick(vendor, [_business("shawarma")], log=log)
    later = datetime.now(UTC) + timedelta(days=8)
    _tick(vendor, [_business("shawarma")], log=log, now=later)
    assert vendor.tags() == ["shawarma", "shawarma"]


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
    report, _, repo = _tick(vendor, [_business("nadie")], log=log)
    (kept,) = log.answers.values()
    assert kept.status == 404 and report.outcomes[0].read == ["nadie"]
    assert repo._sightings == {}  # noqa: SLF001
    _tick(vendor, [_business("nadie")], log=log)
    assert len(vendor.requests) == 1  # a 404 is an answer: not asked again this week


def test_a_vendor_failure_is_counted_and_the_next_tag_still_runs() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        tag = request.url.params["hashtag"]
        calls.append(tag)
        if tag == "roto":
            return httpx.Response(500, json={"error": "boom"})
        return httpx.Response(200, json=_answer(tag))

    business = _business("roto", "sano")
    report = weekly.run_tick(
        [business.tenant_id],
        source=weekly.MemoryRubroSource({business.tenant_id: business}),
        log=weekly.MemoryReadLog(_ledger()),
        repository=MemoryHashtagRepository(),
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
        env=ON,
    )
    assert calls == ["roto", "sano"]
    assert report.outcomes[0].errors == 1 and report.outcomes[0].read == ["sano"]


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
    assert second.outcomes[0].status == weekly.READ_THIS_WEEK
    assert repo._sightings == rows and _ledger().events == events  # noqa: SLF001
    assert first.outcomes[0].sightings == len(rows)


def test_a_business_that_paid_this_week_is_skipped_even_after_a_crash() -> None:
    """The booking is written before the request leaves: a run that died after paying
    for the first tag charges nothing more that week."""
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
    report, _, _ = _tick(vendor, [business])
    assert vendor.requests == [] and report.outcomes[0].status == weekly.READ_THIS_WEEK


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


def test_the_cli_fails_a_pass_with_errors_or_a_global_stop() -> None:
    tenant = str(uuid4())
    broken = weekly.TickReport([weekly.BusinessOutcome(uuid4(), weekly.DONE, errors=1)])
    assert weekly_worker.main(["--tenant", tenant, "--once"], tick=lambda ids: broken) == 1
    stopped = weekly.TickReport(stopped="below_floor")
    assert weekly_worker.main(["--tenant", tenant, "--once"], tick=lambda ids: stopped) == 1

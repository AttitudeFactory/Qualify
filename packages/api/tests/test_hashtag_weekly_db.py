"""m-25026378 against the live schema (0036 + 0117 + 0162 + 0163): the weekly TikTok read
per rubro hashtag with the production stores — `PostgresRubroSource`, `PostgresReadLog`,
`PostgresHashtagRepository` and the gate's `PostgresUsageStore`. The vendor is an
`httpx.MockTransport`: nothing leaves the process.

- the rubro is the «Tu rubro» pills in `brand_kit_details.connect`, the region its
  country (else the business's);
- every read is booked as `hashtag_weekly` (0163's CHECK) to its business, its answer
  lands in `vendor_payloads`, its sightings as `hashtag_weekly` (0163's CHECK);
- re-running writes no row and books no credit; another business in another country does
  not read the same hashtag again, and a referentes page of it counts as read;
- the shared tables have no column that could name the business;
- two passes for one business never both read (advisory claim), and `--all-tenants`
  reads only businesses opened in the last 14 days (the reels worker's rule).
"""

from __future__ import annotations

import json
import string
import threading
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creators.repository import PostgresCreatorPoolRepository
from qualify_api.hashtags import PostgresHashtagRepository, weekly
from qualify_api.referentes.reel_store import PostgresReelRunStore
from qualify_api.tenancy.models import Brand, Tenant
from qualify_api.vendors import scrapecreators as sc
from qualify_api.vendors import usage

pytestmark = pytest.mark.db

ON = {weekly.SWITCH_ENV: "1"}


def _word() -> str:
    return "".join(string.ascii_lowercase[int(c, 16)] for c in uuid4().hex[:12])


@pytest.fixture(autouse=True)
def _postgres_ledger(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "test-key-not-real")
    usage.configure_store(usage.PostgresUsageStore())  # conftest restores the fake after


def _business(tags: list[str], *, country: str | None = "VE", tenant_country: str = "CO") -> UUID:
    tenant, brand = uuid4(), uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant,
                name="Weekly test",
                country=tenant_country,
                timezone="America/Bogota",
                currency="COP",
            )
        )
        session.flush()
        session.add(Brand(id=brand, tenant_id=tenant, name="Weekly brand"))
    connect: dict[str, Any] = {"hashtags": [{"tag": t, "origin": "manual"} for t in tags]}
    if country:
        connect["country_code"] = country
    with tenant_session(tenant) as session:
        session.execute(
            text(
                "INSERT INTO brand_kit_details (brand_id, tenant_id, connect) "
                "VALUES (:b, :t, CAST(:c AS jsonb))"
            ),
            {"b": brand, "t": tenant, "c": json.dumps(connect)},
        )
    return tenant


class Vendor:
    def __init__(self, co_tag: str) -> None:
        self.co_tag = co_tag
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        tag = request.url.params["hashtag"]
        now = datetime.now(UTC)
        items = [
            {
                "aweme_id": f"{tag}-{n}",
                "desc": f"#{tag} #{self.co_tag}",
                "desc_language": lang,
                "create_time": int((now - timedelta(days=days)).timestamp()),
                "is_ad": False,
                "statistics": {"play_count": 1000 * n},
            }
            for n, lang, days in ((1, "es", 2), (2, "es", 30), (3, "en", 2), (4, "es", 120))
        ]
        return httpx.Response(
            200,
            json={
                "success": True,
                "credits_remaining": 9000,
                "credits_charged": 1,
                "aweme_list": items,
            },
        )

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def _tick(vendor: Vendor, tenants: list[UUID]) -> weekly.TickReport:
    return weekly.run_tick(tenants, client_factory=vendor.client, env=ON)


def _weekly_rows(tenant: UUID) -> list[Any]:
    with tenant_session(tenant) as session:
        return session.execute(
            text(
                "SELECT brand_id, credits FROM vendor_usage_events "
                "WHERE feature = :f ORDER BY created_at"
            ),
            {"f": sc.FEATURE_HASHTAG_WEEKLY},
        ).all()


def _sightings(tenant: UUID, tags: list[str]) -> list[Any]:
    with tenant_session(tenant) as session:
        return session.execute(
            text(
                "SELECT h.tag, s.post_id, s.views, s.source, s.source_ref, s.parser_version "
                "FROM hashtag_post_sightings s JOIN hashtags h ON h.id = s.hashtag_id "
                "WHERE h.tag = ANY(:tags) ORDER BY h.tag, s.post_id"
            ),
            {"tags": tags},
        ).all()


def _payloads(tenant: UUID, tag: str) -> list[Any]:
    with tenant_session(tenant) as session:
        return session.execute(
            text(
                "SELECT params_key, status, payload, credits_charged FROM vendor_payloads "
                "WHERE path = :path AND CAST(params_key AS jsonb) ->> 'hashtag' = :tag"
            ),
            {"path": weekly.PATH, "tag": tag},
        ).all()


def test_the_rubro_is_read_from_the_tu_rubro_pills() -> None:
    tag = _word()
    tenant = _business([f"#{tag.upper()}", "dos palabras"], country=None, tenant_country="UY")
    rubro = weekly.PostgresRubroSource().rubro(tenant)
    assert rubro.tags == (tag,) and rubro.country_code == "UY" and rubro.brand_id is not None


def test_a_tick_books_keeps_and_records_and_a_re_run_does_nothing() -> None:
    tag, other, co_tag = _word(), _word(), _word()
    tenant = _business([tag, other])
    vendor = Vendor(co_tag)

    report = _tick(vendor, [tenant])
    (outcome,) = report.outcomes
    assert outcome.status == weekly.DONE and outcome.read == [tag, other], outcome
    assert {r.url.params["region"] for r in vendor.requests} == {"VE"}
    booked = _weekly_rows(tenant)
    assert len(booked) == 2 and {r.credits for r in booked} == {1}
    (kept,) = _payloads(tenant, tag)
    assert json.loads(kept.params_key) == {"hashtag": tag, "region": "VE"}
    assert kept.status == 200 and kept.credits_charged == 1
    assert len(kept.payload["aweme_list"]) == 4  # the raw answer, whole
    rows = _sightings(tenant, [tag, other, co_tag])
    # posts 1 and 2 of each read count (Spanish, inside 90 days); 3 is English, 4 is old
    assert {(r.tag, r.post_id) for r in rows} == {
        (t, f"{read}-{n}") for read in (tag, other) for n in (1, 2) for t in (read, co_tag)
    }
    assert {(r.source, r.source_ref, r.parser_version) for r in rows} == {
        (weekly.SOURCE, weekly.SOURCE_REF, weekly.PARSER_VERSION)
    }

    again = _tick(vendor, [tenant])
    assert again.outcomes[0].status == weekly.UP_TO_DATE
    assert len(vendor.requests) == 2
    assert len(_weekly_rows(tenant)) == 2 and _sightings(tenant, [tag, other, co_tag]) == rows
    assert len(_payloads(tenant, tag)) == 1


def test_another_business_elsewhere_does_not_read_the_same_hashtag_again() -> None:
    tag, co_tag = _word(), _word()
    first, second = _business([tag], country="VE"), _business([tag], country="UY")
    vendor = Vendor(co_tag)
    report = _tick(vendor, [first, second])
    assert len(vendor.requests) == 1
    assert report.outcomes[1].fresh == [tag] and _weekly_rows(second) == []


def test_a_referentes_page_of_the_hashtag_this_week_counts_as_read() -> None:
    tag = _word()
    tenant = _business([tag])
    PostgresCreatorPoolRepository(tenant).put_payload(
        weekly.PATH, {"hashtag": tag, "region": "CO", "cursor": "30"}, {"aweme_list": []}
    )
    vendor = Vendor(_word())
    report = _tick(vendor, [tenant])
    assert vendor.requests == [] and report.outcomes[0].fresh == [tag]


def test_co_occurring_tags_stay_out_of_the_classification_queue() -> None:
    tag, co_tag = _word(), _word()
    tenant = _business([tag])
    _tick(Vendor(co_tag), [tenant])
    queued = {
        t.tag for t in PostgresHashtagRepository().needs_classification(tenant, limit=100_000)
    }
    assert co_tag not in queued and tag not in queued


def test_the_shared_tables_cannot_name_a_business() -> None:
    with admin_session() as session:
        columns = session.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_name IN ('vendor_payloads', 'hashtag_post_sightings', 'hashtags')"
            )
        ).all()
    assert columns
    named = [c for c in columns if any(w in c.column_name for w in ("tenant", "brand", "user"))]
    assert named == []


def test_0163_checks_admit_the_weekly_read_and_nothing_new_besides() -> None:
    with admin_session() as session:
        checks = dict(
            session.execute(
                text(
                    "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname IN ('ck_vendor_usage_feature', 'ck_hashtag_sighting_source')"
                )
            ).all()
        )
    assert "'hashtag_weekly'" in checks["ck_vendor_usage_feature"]
    assert "'hashtag_weekly'" in checks["ck_hashtag_sighting_source"]
    for feature in sc.FEATURES:
        assert f"'{feature}'" in checks["ck_vendor_usage_feature"], feature


def test_two_concurrent_passes_read_a_business_once_across_connections() -> None:
    """`PostgresClaims`: the second pass finds the advisory lock taken and skips, while
    the first is inside its request — so 2 tags cost 2 credits, never 4."""
    tag, other = _word(), _word()
    tenant = _business([tag, other])
    vendor = Vendor(_word())
    entered, release = threading.Event(), threading.Event()

    def slow(request: httpx.Request) -> httpx.Response:
        entered.set()
        assert release.wait(10)
        return vendor.handler(request)

    reports: list[weekly.TickReport] = []

    def one() -> None:
        reports.append(
            weekly.run_tick(
                [tenant],
                client_factory=lambda: httpx.Client(transport=httpx.MockTransport(slow)),
                env=ON,
            )
        )

    first = threading.Thread(target=one)
    first.start()
    assert entered.wait(10)
    second = threading.Thread(target=one)
    second.start()
    second.join(10)
    release.set()
    first.join(10)
    assert sorted(r.outcomes[0].status for r in reports) == [weekly.BUSY, weekly.DONE]
    assert len(vendor.requests) == 2 and len(_weekly_rows(tenant)) == 2


def test_all_tenants_reads_only_businesses_opened_in_the_last_14_days() -> None:
    now = datetime.now(UTC)
    opened, stale, never = _business([_word()]), _business([_word()]), _business([_word()])
    store = PostgresReelRunStore()
    for tenant, when in ((opened, now - timedelta(days=2)), (stale, now - timedelta(days=20))):
        with tenant_session(tenant) as session:
            brand = session.execute(
                text("SELECT brand_id FROM brand_kit_details LIMIT 1")
            ).scalar_one()
        store.mark_opened(tenant, brand, now=when, every=timedelta(0))
    active = set(weekly.PostgresRubroSource().businesses(None, now=now))
    assert opened in active and stale not in active and never not in active

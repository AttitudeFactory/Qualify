"""RF-01 (m-25119458) against the live schema: `PostgresReviewedReelsStore` through
`tenant_session` — the SQL of every filter, and two businesses that follow the same public
account never seeing (nor counting) each other's verdicts, labels or ideas, even when one
names the other's brand. Opening the list adds no `vendor_usage_events` row."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.referentes import PostgresReferentesRepository
from qualify_api.referentes import reviewed_reels as rv
from qualify_api.referentes.reel_store import (
    STATUS_OK,
    NewIdea,
    NewVerdict,
    PostgresReelRunStore,
    PublicReel,
)
from qualify_api.tenancy.models import Brand, Tenant

pytestmark = pytest.mark.db

BRIEF = "rf01-brief"


def _business() -> tuple[UUID, UUID]:
    tenant, brand = uuid4(), uuid4()
    with admin_session() as session:
        session.add(
            Tenant(id=tenant, name="RF-01", country="CO", timezone="America/Bogota", currency="COP")
        )
        session.flush()
        session.add(Brand(id=brand, tenant_id=tenant, name="RF-01 brand"))
    return tenant, brand


def _usage_events() -> int:
    with admin_session() as session:
        return int(session.scalar(text("SELECT count(*) FROM vendor_usage_events")) or 0)


class Env:
    def __init__(self) -> None:
        self.token = uuid4().hex[:8]
        self.runs = PostgresReelRunStore()
        self.labels = PostgresReferentesRepository()
        self.library = rv.PostgresReviewedReelsStore()

    def handle(self, name: str) -> str:
        return f"{name}{self.token}"

    def rid(self, name: str) -> str:
        return f"rf01{self.token}{name}"

    def label(self, who: tuple[UUID, UUID], network: str, name: str, label: str) -> None:
        self.labels.set_label(
            tenant_id=who[0],
            brand_id=who[1],
            network=network,
            handle=self.handle(name),
            label=label,
            labeled_by=None,
        )

    def reels(self, *rows: tuple[str, str, str, int, float | None]) -> None:
        now = datetime.now(UTC)
        self.runs.upsert_reels(
            uuid4(),
            [
                PublicReel(
                    network=network,
                    reel_id=self.rid(name),
                    handle=self.handle(account),
                    taken_at=now - timedelta(days=2),
                    metrics_at=now,
                    parser_version=2,
                    views=views,
                    likes=1,
                    duration_s=seconds,
                )
                for network, name, account, views, seconds in rows
            ],
        )

    def verdict(
        self,
        who: tuple[UUID, UUID],
        network: str,
        name: str,
        affinity: str = "producto",
        *,
        fits: bool | None = None,
        brief: str = BRIEF,
    ) -> UUID:
        saved = self.runs.save_verdicts(
            who[0],
            who[1],
            [
                NewVerdict(
                    network=network,
                    reel_id=self.rid(name),
                    brief_hash=brief,
                    input_hash=f"in-{affinity}",
                    fits=affinity in ("producto", "categoria") if fits is None else fits,
                    affinity=affinity,
                    model_id="claude-haiku",
                    prompt_version="p1",
                )
            ],
        )
        return next(iter(saved.values())).id

    def ok_run(self, who: tuple[UUID, UUID], ideas: list[tuple[str, str, UUID]]) -> None:
        tenant, brand = who
        now = datetime.now(UTC)
        queued = self.runs.enqueue(
            tenant,
            brand,
            trigger="weekly",
            run_date=date.today(),
            days=30,
            pipeline_version="t",
            now=now - timedelta(minutes=10),
        )
        claimed = self.runs.claim(tenant, queued.id, now=now - timedelta(minutes=5))
        assert claimed is not None and claimed.started_at is not None
        assert self.runs.save_ideas(
            tenant,
            brand,
            queued.id,
            [
                NewIdea(network=n, reel_id=self.rid(r), rank=i, window_days=30, verdict_id=v)
                for i, (n, r, v) in enumerate(ideas, 1)
            ],
            started_at=claimed.started_at,
        )
        assert self.runs.finish(
            tenant,
            queued.id,
            status=STATUS_OK,
            now=now,
            credits=0,
            cost_usd=Decimal("0"),
            brief_hash=BRIEF,
            started_at=claimed.started_at,
        )

    def read(self, who: tuple[UUID, UUID], **kwargs: Any) -> rv.ReviewedReels:
        return rv.reviewed_reels(who[0], who[1], store=self.runs, library=self.library, **kwargs)

    def ids(self, result: rv.ReviewedReels) -> list[str]:
        return [item.reel.reel_id.removeprefix(f"rf01{self.token}") for item in result.more]


@pytest.fixture
def env() -> Iterator[tuple[Env, tuple[UUID, UUID], tuple[UUID, UUID]]]:
    e = Env()
    a, b = _business(), _business()
    e.label(a, "instagram", "inspira", "referente")
    e.label(a, "tiktok", "tiktoker", "referente")
    e.label(a, "instagram", "rival", "competencia")
    e.label(a, "instagram", "nada", "detractor")
    e.label(b, "instagram", "inspira", "referente")  # B follows the same public account
    e.reels(
        ("instagram", "idea", "inspira", 9000, 12.0),
        ("instagram", "short", "inspira", 700, 10.0),
        ("instagram", "mid", "inspira", 600, 15.0),
        ("tiktok", "long", "tiktoker", 500, 30.0),
        ("tiktok", "longest", "tiktoker", 400, 60.0),
        ("instagram", "comp", "rival", 800, 20.0),
        ("instagram", "hater", "nada", 99999, 20.0),
        ("instagram", "rubro", "inspira", 5000, 20.0),
        ("instagram", "only_b", "inspira", 50000, 20.0),
    )
    idea = e.verdict(a, "instagram", "idea")
    for name in ("short", "mid", "comp", "hater"):
        e.verdict(a, "instagram", name)
    for name in ("long", "longest"):
        e.verdict(a, "tiktok", name)
    e.verdict(a, "instagram", "rubro", affinity="rubro")
    e.ok_run(a, [("instagram", "idea", idea)])
    e.verdict(b, "instagram", "only_b")
    e.verdict(b, "instagram", "short", affinity="otro")  # B rejects what A keeps
    e.ok_run(b, [])
    yield e, a, b


def test_kept_reels_ordered_with_ideas_apart(env: Any) -> None:
    e, a, _ = env
    result = e.read(a)
    assert [i.reel.reel_id for i in result.ideas] == [e.rid("idea")]
    assert e.ids(result) == ["comp", "short", "mid", "long", "longest"]
    assert result.title == "Más reels revisados"
    assert all(item.verdict.model_id and item.verdict.prompt_version for item in result.more)


def test_each_filter_and_combined_in_sql(env: Any) -> None:
    e, a, _ = env
    of = rv.ReelFilters.of
    assert e.ids(e.read(a, filters=of(networks=["tiktok"]))) == ["long", "longest"]
    assert e.ids(e.read(a, filters=of(kinds=["competencia"]))) == ["comp"]
    two = of(
        accounts=[("instagram", "@" + e.handle("rival").upper()), ("tiktok", e.handle("tiktoker"))]
    )
    assert e.ids(e.read(a, filters=two)) == ["comp", "long", "longest"]
    assert e.ids(e.read(a, filters=of(durations=[rv.DURATION_UNDER_15]))) == ["short"]
    assert e.ids(e.read(a, filters=of(durations=[rv.DURATION_15_30]))) == ["comp", "mid"]
    assert e.ids(e.read(a, filters=of(durations=[rv.DURATION_30_60]))) == ["long"]
    assert e.ids(e.read(a, filters=of(durations=[rv.DURATION_OVER_60]))) == ["longest"]
    combined = of(networks=["instagram"], kinds=["referente"], durations=[rv.DURATION_15_30])
    assert e.ids(e.read(a, filters=combined)) == ["mid"]
    first, rest = e.read(a, limit=2), e.read(a, limit=10, offset=2)
    assert first.has_more and not rest.has_more
    assert e.ids(first) + e.ids(rest) == e.ids(e.read(a))


def test_two_businesses_never_see_or_count_each_other(env: Any) -> None:
    e, a, b = env
    result_b = e.read(b)
    assert e.ids(result_b) == ["only_b"]
    assert result_b.ideas == []
    assert set(result_b.accounts) == {("instagram", e.handle("inspira"))}
    assert "only_b" not in e.ids(e.read(a))
    # B naming A's brand: RLS hides every brand_* row of A
    assert e.library.account_kinds(b[0], a[1]) == {}
    assert (
        e.library.fitting(
            b[0], a[1], brief_hash=BRIEF, filters=rv.NO_FILTERS, exclude=[], offset=0, limit=50
        )
        == []
    )
    crossed = rv.reviewed_reels(b[0], a[1], store=e.runs, library=e.library)
    assert crossed.view.shown is None and crossed.more == [] and crossed.ideas == []


def test_detractors_never_appear(env: Any) -> None:
    e, a, _ = env
    assert "hater" not in e.ids(e.read(a))
    only_detractor = rv.ReelFilters.of(accounts=[("instagram", e.handle("nada"))])
    assert e.ids(e.read(a, filters=only_detractor)) == []


def test_opening_adds_no_usage_event(env: Any) -> None:
    e, a, _ = env
    before = _usage_events()
    e.read(a)
    e.read(a, filters=rv.ReelFilters.of(networks=["instagram"]), offset=1)
    assert _usage_events() == before


def test_newest_verdict_strict_fits_brief_and_unknown_duration_in_sql(env: Any) -> None:
    e, a, _ = env
    e.reels(
        ("instagram", "legacy", "inspira", 7000, 20.0),
        ("instagram", "oldbrief", "inspira", 6000, 20.0),
        ("instagram", "nodur", "inspira", 300, None),
    )
    e.verdict(a, "instagram", "legacy", affinity="rubro", fits=True)  # an older rule
    e.verdict(a, "instagram", "oldbrief", brief="rf01-older-brief")
    e.verdict(a, "instagram", "nodur")
    e.verdict(a, "instagram", "short", affinity="otro")  # judged again, later: rejected
    assert e.ids(e.read(a)) == ["comp", "mid", "long", "longest", "nodur"]
    short_ones = rv.ReelFilters.of(durations=[rv.DURATION_UNDER_15, rv.DURATION_15_30])
    assert e.ids(e.read(a, filters=short_ones)) == ["comp", "mid"]


# --------------------------------------------------------------------------------------
# RF-02b (m-25119463): region and niche over `creators` (0182)
# --------------------------------------------------------------------------------------


def _creator(
    tenant: UUID,
    network: str,
    handle: str,
    *,
    region: str = "",
    rubro: str = "",
    region_source: str = "",
) -> None:
    """A row of the global pool with RF-04's facts and their provenance. Written like
    RF-04 writes it: through `tenant_session` (the table is global; the door is the
    application role)."""
    now = datetime.now(UTC)
    with tenant_session(tenant) as session:
        session.execute(
            text(
                "INSERT INTO creators (network, handle, region_code, region_source, "
                "region_version, region_inferred_at, rubro, rubro_source, rubro_model, "
                "rubro_version, rubro_inferred_at, seen_at) VALUES (:n, :h, :rc, :rs, :rv, :rat, "
                ":ru, :rus, :rum, :ruv, :ruat, :seen)"
            ),
            {
                "n": network,
                "h": handle,
                "rc": region,
                "rs": (region_source or "sightings") if region else "",
                "rv": "region-free-1" if region else "",
                "rat": now if region else None,
                "ru": rubro,
                "rus": "ai" if rubro else "",
                "rum": "claude-haiku" if rubro else "",
                "ruv": "referentes-review-3" if rubro else "",
                "ruat": now if rubro else None,
                "seen": now,
            },
        )


@pytest.fixture
def placed(env: Any) -> Any:
    """`inspira` in Colombia (food), `tiktoker` in Venezuela (no rubro), `rival` with a
    rubro and no country, the detractor in Colombia; nothing else is in the pool."""
    e, a, b = env
    _creator(a[0], "instagram", e.handle("inspira"), region="CO", rubro="food_drink")
    _creator(a[0], "tiktok", e.handle("tiktoker"), region="VE", region_source="tiktok_region")
    _creator(a[0], "instagram", e.handle("rival"), rubro="food_drink")
    _creator(a[0], "instagram", e.handle("nada"), region="CO", rubro="food_drink")
    return e, a, b


def test_region_and_niche_filters_in_sql(placed: Any) -> None:
    e, a, _ = placed
    of = rv.ReelFilters.of
    everything = e.ids(e.read(a))
    assert everything == ["comp", "short", "mid", "long", "longest"]  # off: unknowns enter
    assert e.ids(e.read(a, filters=of(regions=["CO"]))) == ["short", "mid"]
    assert e.ids(e.read(a, filters=of(regions=["co", "VE"]))) == [
        "short",
        "mid",
        "long",
        "longest",
    ]
    assert e.ids(e.read(a, filters=of(regions=["UY"]))) == []
    assert e.ids(e.read(a, filters=of(niches=["food_drink"]))) == ["comp", "short", "mid"]
    both = of(regions=["CO"], niches=["food_drink"], durations=[rv.DURATION_15_30])
    assert e.ids(e.read(a, filters=both)) == ["mid"]
    assert [i.reel.reel_id for i in e.read(a, filters=of(regions=["CO"])).ideas] == [e.rid("idea")]
    assert e.read(a, filters=of(regions=["VE"])).ideas == []
    assert "hater" not in e.ids(e.read(a, filters=of(regions=["CO"])))
    by_id = {item.reel.reel_id.removeprefix(f"rf01{e.token}"): item for item in e.read(a).more}
    assert (by_id["short"].region_code, by_id["short"].rubro) == ("CO", "food_drink")
    assert (by_id["comp"].region_code, by_id["comp"].rubro) == ("", "food_drink")
    assert e.read(a).facts[("tiktok", e.handle("tiktoker"))].region_source == "tiktok_region"


def test_region_and_niche_never_cross_businesses(placed: Any) -> None:
    e, a, b = placed
    colombia = rv.ReelFilters.of(regions=["CO"])
    # B follows the same Colombian account: it sees its own kept reel, none of A's
    assert e.ids(e.read(b, filters=colombia)) == ["only_b"]
    assert set(e.read(b).facts) == {("instagram", e.handle("inspira"))}
    assert "only_b" not in e.ids(e.read(a, filters=colombia))
    # B naming A's brand with a region set: RLS still hides every brand_* row of A
    assert (
        e.library.fitting(
            b[0], a[1], brief_hash=BRIEF, filters=colombia, exclude=[], offset=0, limit=50
        )
        == []
    )
    crossed = rv.reviewed_reels(b[0], a[1], store=e.runs, library=e.library, filters=colombia)
    assert crossed.more == [] and crossed.ideas == [] and crossed.facts == {}
    before = _usage_events()
    e.read(a, filters=rv.ReelFilters.of(regions=["CO"], niches=["food_drink"]))
    assert _usage_events() == before


def test_brand_niche_reads_the_brand_kit_through_tenant_session(env: Any) -> None:
    from qualify_api.creative.brand_kit_store import BrandKitStore

    _, a, b = env
    store = BrandKitStore()
    store.save_details(
        tenant_id=a[0], brand_id=a[1], user_id=None, documents={"connect": {"sector": "food_drink"}}
    )
    store.save_details(
        tenant_id=b[0],
        brand_id=b[1],
        user_id=None,
        documents={"connect": {"sector": "real_estate"}},
    )
    assert rv.brand_niche(*a).text == "Nicho: Comida y bebida"
    assert rv.brand_niche(*b).text == "Nicho: Inmobiliaria"
    assert rv.brand_niche(b[0], a[1]) == rv.NO_NICHE  # RLS: A's kit is not B's to read


# --------------------------------------------------------------------------------------
# «Locales» (RF-02b, Deivid 2026-11-27): the SQL twin of `term_names_city`
# --------------------------------------------------------------------------------------

#: `(term, city words, names the city?)` — the offline cases of the Python rule.
CITY_CASES: list[tuple[str, str, bool]] = [
    ("comida cúcuta", "cucuta", True),
    ("Comida en CÚCUTA, Norte de Santander", "cucuta", True),
    ("cucuta", "cucuta", True),
    ("#CucutaFood", "cucuta", True),
    ("comidacucuta", "cucuta", True),
    ("restaurantes san cristóbal táchira", "san cristobal", True),
    ("sancristobalfood", "san cristobal", True),
    ("comida colombia", "cucuta", False),
    ("comida de calidad", "cali", False),
    ("#calidad", "cali", False),
    ("corona de flores", "coro", False),
    ("caramelos artesanales", "melo", False),
    ("asalto", "salto", False),
    ("#caliente", "cali", False),
    ("#calidadpremium", "cali", False),
    ("#coronavirus", "coro", False),
    ("#caramelo", "melo", False),
    ("#saltodealtura", "salto", False),
    ("#comidacali", "cali", True),
    ("cali", "cali", True),
]


@pytest.mark.parametrize(("term", "city", "names"), CITY_CASES)
def test_the_sql_folds_and_matches_terms_like_python(term: str, city: str, names: bool) -> None:
    """The same answer from Postgres (`_term_sql`) and Python (`term_names_city`)."""
    assert rv.term_names_city(term, city) is names
    with tenant_session(uuid4()) as session:
        got = session.execute(
            text(f"SELECT {rv._term_sql('CAST(:term AS text)')}"),
            {"term": term, **rv._city_params(city)},
        ).scalar_one()
    assert got is names, (term, city)


def _sighting(tenant: UUID, network: str, handle: str, term: str, city_slug: str = "") -> None:
    """A row of the global `creator_sightings`, written through the application role."""
    with tenant_session(tenant) as session:
        session.execute(
            text(
                "INSERT INTO creator_sightings (network, handle, kind, term, country_code, "
                "city_slug, seen_at) VALUES (:n, :h, 'keyword', :t, 'CO', :c, now())"
            ),
            {"n": network, "h": handle, "t": term, "c": city_slug},
        )


def test_locales_in_sql_keeps_accounts_seen_under_a_term_naming_the_city(placed: Any) -> None:
    """`inspira` was found by «comida cúcuta»; `tiktoker` by a national term in a search
    run FROM Cúcuta (`city_slug` = cucuta: not evidence); `rival` by «comida de calidad»
    for Cali. Only `inspira` is local to Cúcuta, in `fitting`, the ideas and
    `local_accounts`; nobody is local to Cali; nothing is written or paid."""
    e, a, _ = placed
    _sighting(a[0], "instagram", e.handle("inspira"), "comida cúcuta", "cucuta")
    _sighting(a[0], "tiktok", e.handle("tiktoker"), "comida venezolana", "cucuta")
    _sighting(a[0], "instagram", e.handle("rival"), "comida de calidad", "cali")
    before = _usage_events()
    local = e.read(a, filters=rv.ReelFilters.of(city="Cúcuta"))
    assert e.ids(local) == ["short", "mid"]
    assert [i.reel.reel_id for i in local.ideas] == [e.rid("idea")]
    keys = [("instagram", e.handle("inspira")), ("tiktok", e.handle("tiktoker"))]
    keys.append(("instagram", e.handle("rival")))
    assert e.library.local_accounts(a[0], keys, "Cúcuta") == {keys[0]}
    assert e.library.local_accounts(a[0], keys, "cali") == set()
    assert e.ids(e.read(a, filters=rv.ReelFilters.of(city="Cali"))) == []
    assert _usage_events() == before

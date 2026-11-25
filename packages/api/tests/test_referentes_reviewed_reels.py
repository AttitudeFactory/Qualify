"""RF-01 (m-25119458): the filterable read of reviewed reels, offline.

Pins the ticket's criteria over the in-memory twins: only reels the strict product check
kept, every filter alone and combined, the ideas unchanged and apart, pagination and its
heading, detractors never shown, two businesses never mixed, and no paid call nor write
when the list is opened."""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from qualify_api import claude_tools
from qualify_api.referentes import MemoryReferentesRepository, reel_runs, reels_ai
from qualify_api.referentes import reviewed_reels as rv
from qualify_api.referentes.reel_store import (
    STATUS_OK,
    MemoryReelRunStore,
    NewIdea,
    NewVerdict,
    PublicReel,
)
from qualify_api.vendors import scrapecreators, usage

NOW = datetime(2026, 11, 25, 12, tzinfo=UTC)
BRIEF = "brief-1"


class World:
    """One store pair holding any number of businesses."""

    def __init__(self) -> None:
        self.runs = MemoryReelRunStore()
        self.labels = MemoryReferentesRepository()
        self.library = rv.MemoryReviewedReelsStore(self.runs, self.labels)

    def business(self) -> tuple[UUID, UUID]:
        tenant, brand = uuid4(), uuid4()
        self.labels.add_brand(tenant_id=tenant, brand_id=brand)
        return tenant, brand

    def label(self, who: tuple[UUID, UUID], network: str, handle: str, label: str) -> None:
        self.labels.set_label(
            tenant_id=who[0],
            brand_id=who[1],
            network=network,
            handle=handle,
            label=label,
            labeled_by=None,
        )

    def reel(
        self,
        network: str,
        reel_id: str,
        handle: str,
        *,
        views: int,
        likes: int = 0,
        seconds: float | None = 20.0,
    ) -> None:
        self.runs.reels[(network, reel_id)] = PublicReel(
            network=network,
            reel_id=reel_id,
            handle=handle,
            taken_at=NOW - timedelta(days=3),
            metrics_at=NOW,
            parser_version=2,
            views=views,
            likes=likes,
            duration_s=seconds,
        )

    def verdict(
        self,
        who: tuple[UUID, UUID],
        network: str,
        reel_id: str,
        *,
        affinity: str = "producto",
        fits: bool | None = None,
        brief: str = BRIEF,
        input_hash: str = "in-1",
    ) -> UUID:
        saved = self.runs.save_verdicts(
            who[0],
            who[1],
            [
                NewVerdict(
                    network=network,
                    reel_id=reel_id,
                    brief_hash=brief,
                    input_hash=input_hash,
                    fits=(affinity in reels_ai.FITS) if fits is None else fits,
                    affinity=affinity,
                    model_id="claude-haiku",
                    prompt_version="p1",
                    reason="va con tu producto",
                    cost_usd=Decimal("0.001"),
                )
            ],
        )
        return next(iter(saved.values())).id

    def ok_run(self, who: tuple[UUID, UUID], ideas: list[tuple[str, str, UUID]]) -> None:
        tenant, brand = who
        queued = self.runs.enqueue(
            tenant,
            brand,
            trigger="weekly",
            run_date=date(2026, 11, 23),
            days=30,
            pipeline_version="t",
            now=NOW - timedelta(hours=2),
        )
        claimed = self.runs.claim(tenant, queued.id, now=NOW - timedelta(hours=1))
        assert claimed is not None and claimed.started_at is not None
        self.runs.save_ideas(
            tenant,
            brand,
            queued.id,
            [
                NewIdea(network=n, reel_id=r, rank=i, window_days=30, verdict_id=v)
                for i, (n, r, v) in enumerate(ideas, 1)
            ],
            started_at=claimed.started_at,
        )
        self.runs.finish(
            tenant,
            queued.id,
            status=STATUS_OK,
            now=NOW - timedelta(minutes=30),
            credits=0,
            cost_usd=Decimal("0"),
            brief_hash=BRIEF,
            started_at=claimed.started_at,
        )

    def read(self, who: tuple[UUID, UUID], **kwargs: Any) -> rv.ReviewedReels:
        return rv.reviewed_reels(
            who[0], who[1], store=self.runs, library=self.library, now=NOW, **kwargs
        )


def _ids(result: rv.ReviewedReels) -> list[str]:
    return [item.reel.reel_id for item in result.more]


@pytest.fixture
def world() -> tuple[World, tuple[UUID, UUID]]:
    """Brand A: an Instagram referente, a TikTok referente, a competidor and a detractor;
    two ideas plus a spread of reviewed reels."""
    w = World()
    a = w.business()
    w.label(a, "instagram", "inspira", "referente")
    w.label(a, "tiktok", "tiktoker", "referente")
    w.label(a, "instagram", "rival", "competencia")
    w.label(a, "instagram", "nada", "detractor")
    # ideas (from the run) — the two most viewed kept reels
    w.reel("instagram", "idea1", "inspira", views=9000, seconds=12)
    w.reel("tiktok", "idea2", "tiktoker", views=8000, seconds=45)
    v1 = w.verdict(a, "instagram", "idea1")
    v2 = w.verdict(a, "tiktok", "idea2")
    w.ok_run(a, [("instagram", "idea1", v1), ("tiktok", "idea2", v2)])
    # the rest of what the check reviewed
    w.reel("instagram", "short", "inspira", views=700, seconds=10)  # < 15
    w.reel("instagram", "mid", "inspira", views=600, likes=5, seconds=15)  # 15-30 (edge)
    w.reel("instagram", "mid_tie", "inspira", views=600, likes=9, seconds=29.9)  # 15-30
    w.reel("tiktok", "long", "tiktoker", views=500, seconds=30)  # 30-60 (edge)
    w.reel("tiktok", "longest", "tiktoker", views=400, seconds=60)  # 60+ (edge)
    w.reel("instagram", "nodur", "inspira", views=300, seconds=None)
    w.reel("instagram", "comp", "rival", views=800, seconds=20)  # competidor
    w.reel("instagram", "hater", "nada", views=99999, seconds=20)  # detractor
    w.reel("instagram", "rubro", "inspira", views=5000, seconds=20)  # niche only
    w.reel("instagram", "categoria", "inspira", views=200, seconds=20)  # same kind
    w.reel("instagram", "unlabelled", "nadie", views=4000, seconds=20)
    for reel_id in ("short", "mid", "mid_tie", "nodur", "comp", "hater", "unlabelled"):
        w.verdict(a, "instagram", reel_id)
    for reel_id in ("long", "longest"):
        w.verdict(a, "tiktok", reel_id)
    w.verdict(a, "instagram", "rubro", affinity="rubro")
    w.verdict(a, "instagram", "categoria", affinity="categoria")
    return w, a


# --------------------------------------------------------------------------------------
# the source: only what the strict check kept
# --------------------------------------------------------------------------------------


def test_only_kept_reels_ordered_by_views_then_likes(world: Any) -> None:
    w, a = world
    result = w.read(a)
    assert _ids(result) == [
        "comp",
        "short",
        "mid_tie",  # same views as «mid», more likes
        "mid",
        "long",
        "longest",
        "nodur",
        "categoria",
    ]
    assert all(item.verdict.fits for item in result.more)


def test_strict_product_filter_drops_a_stored_fits_outside_fits_affinities(world: Any) -> None:
    w, a = world
    # a verdict stored under an older rule: fits=True, affinity «rubro»
    w.reel("instagram", "legacy", "inspira", views=7000)
    w.verdict(a, "instagram", "legacy", affinity="rubro", fits=True)
    assert "legacy" not in _ids(w.read(a))


def test_the_newest_verdict_of_a_reel_decides(world: Any) -> None:
    w, a = world
    w.verdict(a, "instagram", "short", affinity="otro", input_hash="in-2")  # judged again
    assert "short" not in _ids(w.read(a))


def test_only_verdicts_of_the_shown_runs_brief_count(world: Any) -> None:
    w, a = world
    w.reel("instagram", "oldbrief", "inspira", views=7000)
    w.verdict(a, "instagram", "oldbrief", brief="brief-0")
    assert "oldbrief" not in _ids(w.read(a))


def test_no_ok_run_means_no_ideas_and_no_more_reels() -> None:
    w = World()
    a = w.business()
    w.label(a, "instagram", "inspira", "referente")
    w.reel("instagram", "x", "inspira", views=10)
    w.verdict(a, "instagram", "x")
    result = w.read(a)
    assert result.ideas == [] and result.more == [] and not result.has_more
    assert result.view.shown is None


def test_unlabelled_accounts_are_not_in_more_reels(world: Any) -> None:
    w, a = world
    assert "unlabelled" not in _ids(w.read(a))


# --------------------------------------------------------------------------------------
# ideas apart, unchanged
# --------------------------------------------------------------------------------------


def test_ideas_are_todays_ideas_in_their_order_and_not_repeated(world: Any) -> None:
    w, a = world
    today = reel_runs.view(a[0], a[1], store=w.runs, now=NOW).ideas
    result = w.read(a)
    assert [i.reel.reel_id for i in result.ideas] == [i.reel.reel_id for i in today]
    assert [i.rank for i in result.ideas] == [1, 2]
    assert not {"idea1", "idea2"} & set(_ids(result))


def test_filters_narrow_the_ideas_keeping_their_order(world: Any) -> None:
    w, a = world
    only_tiktok = w.read(a, filters=rv.ReelFilters.of(networks=["tiktok"]))
    assert [i.reel.reel_id for i in only_tiktok.ideas] == ["idea2"]
    competidores = w.read(a, filters=rv.ReelFilters.of(kinds=["competencia"]))
    assert competidores.ideas == []


# --------------------------------------------------------------------------------------
# each filter alone
# --------------------------------------------------------------------------------------


def test_filter_channel(world: Any) -> None:
    w, a = world
    assert _ids(w.read(a, filters=rv.ReelFilters.of(networks=["tiktok"]))) == [
        "long",
        "longest",
    ]


def test_filter_account_kind(world: Any) -> None:
    w, a = world
    assert _ids(w.read(a, filters=rv.ReelFilters.of(kinds=["competencia"]))) == ["comp"]
    referentes = _ids(w.read(a, filters=rv.ReelFilters.of(kinds=["referente"])))
    assert "comp" not in referentes and "short" in referentes


def test_filter_accounts_one_or_several(world: Any) -> None:
    w, a = world
    one = rv.ReelFilters.of(accounts=[("instagram", "@Rival")])
    assert _ids(w.read(a, filters=one)) == ["comp"]
    two = rv.ReelFilters.of(accounts=[("instagram", "rival"), ("tiktok", "tiktoker")])
    assert _ids(w.read(a, filters=two)) == ["comp", "long", "longest"]


@pytest.mark.parametrize(
    ("bucket", "expected"),
    [
        (rv.DURATION_UNDER_15, ["short"]),
        (rv.DURATION_15_30, ["comp", "mid_tie", "mid", "categoria"]),
        (rv.DURATION_30_60, ["long"]),
        (rv.DURATION_OVER_60, ["longest"]),
    ],
)
def test_filter_duration_bucket(world: Any, bucket: str, expected: list[str]) -> None:
    w, a = world
    assert _ids(w.read(a, filters=rv.ReelFilters.of(durations=[bucket]))) == expected


def test_filter_several_duration_buckets_and_unknown_duration(world: Any) -> None:
    w, a = world
    filters = rv.ReelFilters.of(durations=[rv.DURATION_UNDER_15, rv.DURATION_OVER_60])
    assert _ids(w.read(a, filters=filters)) == ["short", "longest"]  # «nodur» left out


# --------------------------------------------------------------------------------------
# combined
# --------------------------------------------------------------------------------------


def test_filters_combined(world: Any) -> None:
    w, a = world
    filters = rv.ReelFilters.of(
        networks=["instagram"], kinds=["referente"], durations=[rv.DURATION_15_30]
    )
    assert _ids(w.read(a, filters=filters)) == ["mid_tie", "mid", "categoria"]
    none = rv.ReelFilters.of(networks=["tiktok"], kinds=["competencia"])
    assert _ids(w.read(a, filters=none)) == []
    account_and_duration = rv.ReelFilters.of(
        accounts=[("tiktok", "tiktoker")], durations=[rv.DURATION_30_60]
    )
    assert _ids(w.read(a, filters=account_and_duration)) == ["long"]


# --------------------------------------------------------------------------------------
# detractors, region/niche, validation
# --------------------------------------------------------------------------------------


def test_detractors_never_appear(world: Any) -> None:
    w, a = world
    assert "hater" not in _ids(w.read(a))
    assert "hater" not in _ids(
        w.read(a, filters=rv.ReelFilters.of(accounts=[("instagram", "nada")]))
    )
    assert ("instagram", "nada") not in w.read(a).accounts
    with pytest.raises(ValueError, match="kind"):
        rv.ReelFilters.of(kinds=["detractor"])


def test_an_idea_of_an_account_now_labelled_detractor_is_dropped(world: Any) -> None:
    w, a = world
    w.label(a, "tiktok", "tiktoker", "detractor")
    result = w.read(a)
    assert [i.reel.reel_id for i in result.ideas] == ["idea1"]
    assert "long" not in _ids(result)


# --------------------------------------------------------------------------------------
# region and niche (RF-02b, m-25119463) — `creators.region_code` / `.rubro` of RF-04
# --------------------------------------------------------------------------------------


@pytest.fixture
def placed(world: Any) -> tuple[World, tuple[UUID, UUID]]:
    """The world with RF-04's facts: `inspira` in Colombia (food), `tiktoker` in
    Venezuela (no rubro yet), `rival` with a rubro but no country; `nada` (detractor) in
    Colombia. Nothing is known of any other account."""
    w, a = world
    w.library.set_facts("instagram", "inspira", region="CO", rubro="food_drink")
    w.library.set_facts("tiktok", "tiktoker", region="VE")
    w.library.set_facts("instagram", "rival", rubro="food_drink")
    w.library.set_facts("instagram", "nada", region="CO", rubro="food_drink")
    return w, a


def test_region_and_niche_are_on() -> None:
    assert rv.REGION_NICHE_READY is True
    chosen = rv.ReelFilters.of(regions=[" co", "VE"], niches=["Food_Drink"])
    assert chosen.regions == {"CO", "VE"} and chosen.niches == {"food_drink"}


def test_without_a_region_or_niche_filter_unknown_accounts_still_enter(placed: Any) -> None:
    w, a = placed
    known = w.read(a)
    w.library.creators.clear()  # the pool knows nothing
    unknown = w.read(a)
    assert _ids(unknown) == _ids(known)
    assert [i.reel.reel_id for i in unknown.ideas] == [i.reel.reel_id for i in known.ideas]
    assert "comp" in _ids(unknown) and "long" in _ids(unknown)


def test_filter_one_region(placed: Any) -> None:
    w, a = placed
    result = w.read(a, filters=rv.ReelFilters.of(regions=["CO"]))
    # only the Colombian referente; `rival` (no country) and the detractor stay out, and
    # the strict product check still drops the `rubro`-only reel
    assert _ids(result) == ["short", "mid_tie", "mid", "nodur", "categoria"]
    assert [i.reel.reel_id for i in result.ideas] == ["idea1"]
    assert {item.region_code for item in result.more} == {"CO"}


def test_filter_several_regions(placed: Any) -> None:
    w, a = placed
    result = w.read(a, filters=rv.ReelFilters.of(regions=["CO", "VE"]))
    assert "long" in _ids(result) and "comp" not in _ids(result)
    assert [i.reel.reel_id for i in result.ideas] == ["idea1", "idea2"]


def test_filter_region_of_nobody_empties_the_list(placed: Any) -> None:
    w, a = placed
    result = w.read(a, filters=rv.ReelFilters.of(regions=["UY"]))
    assert _ids(result) == [] and result.ideas == []


def test_filter_niche_leaves_out_accounts_without_rubro(placed: Any) -> None:
    w, a = placed
    result = w.read(a, filters=rv.ReelFilters.of(niches=["food_drink"]))
    assert "comp" in _ids(result) and "short" in _ids(result)
    assert "long" not in _ids(result)  # tiktoker: country, no rubro
    assert [i.reel.reel_id for i in result.ideas] == ["idea1"]


def test_region_and_niche_combine_with_the_other_filters(placed: Any) -> None:
    w, a = placed
    combined = rv.ReelFilters.of(
        regions=["CO"], niches=["food_drink"], durations=[rv.DURATION_UNDER_15]
    )
    result = w.read(a, filters=combined)
    assert _ids(result) == ["short"]
    assert [i.reel.reel_id for i in result.ideas] == ["idea1"]  # 12 s
    assert _ids(w.read(a, filters=rv.ReelFilters.of(regions=["CO"], kinds=["competencia"]))) == []


def test_a_detractor_in_the_chosen_region_never_appears(placed: Any) -> None:
    w, a = placed
    assert "hater" not in _ids(w.read(a, filters=rv.ReelFilters.of(regions=["CO"])))
    assert ("instagram", "nada") not in w.read(a).facts


def test_the_ideas_stay_six_to_eight_and_in_order_with_region_off(placed: Any) -> None:
    w, a = placed
    result = w.read(a)
    assert [i.reel.reel_id for i in result.ideas] == ["idea1", "idea2"]
    assert result.facts[("instagram", "inspira")].region_code == "CO"
    assert ("instagram", "nadie") not in result.facts


def test_each_reel_carries_its_accounts_region_and_rubro(placed: Any) -> None:
    w, a = placed
    by_id = {item.reel.reel_id: item for item in w.read(a).more}
    assert (by_id["short"].region_code, by_id["short"].rubro) == ("CO", "food_drink")
    assert (by_id["long"].region_code, by_id["long"].rubro) == ("VE", "")
    assert (by_id["comp"].region_code, by_id["comp"].rubro) == ("", "food_drink")


def test_region_options_are_the_three_markets_then_all() -> None:
    assert [(o.code, o.label) for o in rv.REGION_OPTIONS] == [
        ("CO", "Colombia"),
        ("VE", "Venezuela"),
        ("UY", "Uruguay"),
        ("", "Todas"),
    ]
    assert rv.REGION_TITLE == "Región" and rv.REGION_ALL_LABEL == "Todas"


@pytest.mark.parametrize(
    ("connect", "key", "text"),
    [
        ({"sector": "food_drink", "rubro_text": "arepas"}, "food_drink", "Nicho: Comida y bebida"),
        ({"sector": "", "rubro_text": "  peluquería   canina "}, "", "Nicho: peluquería canina"),
        ({"sector": "no_such"}, "", ""),
        ({}, "", ""),
    ],
)
def test_brand_niche_from_the_brand_kit(connect: dict[str, str], key: str, text: str) -> None:
    niche = rv.brand_niche(uuid4(), uuid4(), connect=lambda _t, _b: connect)
    assert (niche.key, niche.text) == (key, text)


def test_brand_niche_reads_only_its_own_business() -> None:
    a, b = (uuid4(), uuid4()), (uuid4(), uuid4())
    kits = {a: {"sector": "food_drink"}, b: {"sector": "real_estate"}}

    def scoped(tenant: UUID, brand: UUID) -> dict[str, str]:
        # the store's `tenant_session`: another business's brand reads as no kit
        return kits.get((tenant, brand), {})

    assert rv.brand_niche(*a, connect=scoped).key == "food_drink"
    assert rv.brand_niche(*b, connect=scoped).key == "real_estate"
    assert rv.brand_niche(b[0], a[1], connect=scoped) == rv.NO_NICHE


def test_an_unreadable_kit_only_hides_the_niche_label() -> None:
    def broken(_t: UUID, _b: UUID) -> dict[str, str]:
        raise RuntimeError("db down")

    assert rv.brand_niche(uuid4(), uuid4(), connect=broken) == rv.NO_NICHE


def test_two_businesses_share_public_facts_but_never_labels_or_verdicts(placed: Any) -> None:
    w, a = placed
    b = w.business()
    w.label(b, "instagram", "rival", "referente")  # B follows A's competitor
    w.reel("instagram", "only_b", "rival", views=50_000)
    w.verdict(b, "instagram", "only_b")
    w.ok_run(b, [])
    colombia = rv.ReelFilters.of(regions=["CO"])
    assert _ids(w.read(b, filters=colombia)) == []  # rival has no country
    assert _ids(w.read(b, filters=rv.ReelFilters.of(niches=["food_drink"]))) == ["only_b"]
    result_b = w.read(b)
    assert set(result_b.facts) == {("instagram", "rival")}  # none of A's accounts
    assert "only_b" not in _ids(w.read(a, filters=rv.ReelFilters.of(niches=["food_drink"])))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"networks": ["youtube"]},
        {"durations": ["90_120"]},
        {"accounts": [("x", "h")]},
        {"regions": ["Colombia"]},
        {"regions": ["C0"]},
        {"niches": ["comida"]},
    ],
)
def test_unknown_filter_values_are_refused(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        rv.ReelFilters.of(**kwargs)


def test_duration_buckets_are_half_open() -> None:
    assert rv.duration_bucket(14.999) == rv.DURATION_UNDER_15
    assert rv.duration_bucket(15) == rv.DURATION_15_30
    assert rv.duration_bucket(30) == rv.DURATION_30_60
    assert rv.duration_bucket(60) == rv.DURATION_OVER_60
    assert rv.duration_bucket(None) is None


# --------------------------------------------------------------------------------------
# pagination and heading
# --------------------------------------------------------------------------------------


def test_pagination(world: Any) -> None:
    w, a = world
    everything = _ids(w.read(a))
    first = w.read(a, limit=3)
    second = w.read(a, limit=3, offset=3)
    last = w.read(a, limit=3, offset=6)
    assert first.has_more and second.has_more and not last.has_more
    assert _ids(first) + _ids(second) + _ids(last) == everything
    assert w.read(a, limit=10_000).limit == rv.MAX_PAGE_SIZE
    with pytest.raises(ValueError):
        w.read(a, offset=-1)


def test_heading_is_exact(world: Any) -> None:
    w, a = world
    assert rv.MORE_REVIEWED_TITLE == "Más reels revisados"
    assert w.read(a).title == "Más reels revisados"


def test_accounts_offered_for_the_account_filter(world: Any) -> None:
    w, a = world
    assert w.read(a).accounts == {
        ("instagram", "inspira"): "referente",
        ("instagram", "rival"): "competencia",
        ("tiktok", "tiktoker"): "referente",
    }


# --------------------------------------------------------------------------------------
# tenant isolation (the Postgres twin is pinned in test_referentes_reviewed_reels_db.py)
# --------------------------------------------------------------------------------------


def test_two_businesses_never_mix(world: Any) -> None:
    w, a = world
    b = w.business()
    w.label(b, "instagram", "inspira", "referente")  # B follows the same public account
    w.reel("instagram", "only_b", "inspira", views=50_000)
    vb = w.verdict(b, "instagram", "only_b")
    w.ok_run(b, [])
    w.verdict(b, "instagram", "short", affinity="otro", input_hash="in-b")  # B rejects it
    result_a = w.read(a)
    result_b = w.read(b)
    assert "only_b" not in _ids(result_a) and "short" in _ids(result_a)
    assert _ids(result_b) == ["only_b"]  # none of A's verdicts, ideas or labels
    assert result_b.ideas == []
    assert set(result_b.accounts) == {("instagram", "inspira")}
    assert vb not in {item.verdict.id for item in result_a.more}


# --------------------------------------------------------------------------------------
# free and read-only
# --------------------------------------------------------------------------------------


def _forbidden(*_: Any, **__: Any) -> Any:
    raise AssertionError("opening the reviewed reels must not pay or call out")


def test_opening_the_list_pays_nothing_and_writes_nothing(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    w, a = world
    for name in dir(scrapecreators):
        if name.startswith("fetch_") and callable(getattr(scrapecreators, name)):
            monkeypatch.setattr(scrapecreators, name, _forbidden)
    monkeypatch.setattr(reels_ai, "review_reels", _forbidden)
    monkeypatch.setattr(claude_tools, "messages_create", _forbidden)
    monkeypatch.setattr(claude_tools, "create_turn", _forbidden)
    monkeypatch.setattr(httpx.Client, "send", _forbidden)
    monkeypatch.setattr(reel_runs, "run", _forbidden)
    monkeypatch.setattr(reel_runs, "_analyze", _forbidden)
    monkeypatch.setattr(reel_runs, "enqueue_run", _forbidden)
    ledger = usage.InMemoryUsageStore()
    usage.configure_store(ledger)
    try:
        writes = w.runs.writes
        result = w.read(a, filters=rv.ReelFilters.of(networks=["instagram"]), limit=2)
        w.read(a, offset=2)
    finally:
        usage.configure_store(None)
    assert result.more  # it did read
    assert w.runs.writes == writes
    assert ledger.events == []


def test_the_module_imports_no_paying_door() -> None:
    tree = ast.parse(inspect.getsource(rv))
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert not any("vendors" in module or "claude_tools" in module for module in imported)
    assert not {"scrapecreators", "usage", "httpx", "anthropic"} & (names | imported)

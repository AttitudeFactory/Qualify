"""RF-09 (m-25119466): the reel badges «En ascenso» and «Top 10 % de tu rubro», offline.

Pins the ticket's criteria over the in-memory twin: the exact labels, the thresholds and
minimum samples, an account without a known rubro never «Top 10 %», provenance on every
badge (source reel + formula versions + sample), no paid call nor write, and two
businesses never seeing each other's reels through the badges."""

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
from qualify_api.creators import metrics
from qualify_api.referentes import MemoryReferentesRepository, reels_ai
from qualify_api.referentes import reel_badges as rb
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
TENANT = uuid4()


def _reel(
    handle: str,
    reel_id: str,
    views: int | None,
    *,
    network: str = "instagram",
    age_days: float = 10.0,
    read_after_days: float | None = None,
    hidden: bool = False,
) -> PublicReel:
    taken = NOW - timedelta(days=age_days)
    read_at = NOW if read_after_days is None else taken + timedelta(days=read_after_days)
    return PublicReel(
        network=network,
        reel_id=reel_id,
        handle=handle,
        taken_at=taken,
        metrics_at=read_at,
        parser_version=2,
        views=views,
        likes=1,
        counts_hidden=hidden,
    )


def _account(handle: str, views: list[int], **kwargs: Any) -> list[PublicReel]:
    return [_reel(handle, f"{handle}-{i}", v, **kwargs) for i, v in enumerate(views)]


def _badges(
    reels: list[PublicReel],
    *,
    stored: list[PublicReel] | None = None,
    rubros: dict[tuple[str, str], str] | None = None,
    **kwargs: Any,
) -> dict[tuple[str, str], tuple[rb.Badge, ...]]:
    store = rb.MemoryReelBadgeStore(stored if stored is not None else reels, rubros)
    return rb.reel_badges(TENANT, reels, store=store, now=NOW, **kwargs)


def _keys(badges: dict[tuple[str, str], tuple[rb.Badge, ...]], reel_id: str) -> list[str]:
    return [b.key for b in badges.get(("instagram", reel_id), ())]


# --------------------------------------------------------------------------------------
# labels
# --------------------------------------------------------------------------------------


def test_the_labels_read_exactly_as_the_ticket_says() -> None:
    assert rb.LABEL_RISING == "En ascenso"
    assert rb.LABEL_TOP_RUBRO == "Top 10 % de tu rubro"
    assert rb.BADGE_LABELS == {"rising": "En ascenso", "top_rubro": "Top 10 % de tu rubro"}


# --------------------------------------------------------------------------------------
# «En ascenso»
# --------------------------------------------------------------------------------------


def test_rising_needs_twice_the_accounts_median() -> None:
    reels = _account("cafe", [100, 100, 100, 250, 199])
    badges = _badges(reels)
    # median of [100, 100, 100, 199, 250] = 100 → 250 is x2.5, 199 is x1.99
    assert _keys(badges, "cafe-3") == ["rising"]
    assert _keys(badges, "cafe-4") == []
    assert _keys(badges, "cafe-0") == []
    assert rb.RISING_LIFT == 2.0 == rv_lift_highlight()


def rv_lift_highlight() -> float:
    from qualify_api.referentes.reels import LIFT_HIGHLIGHT

    return LIFT_HIGHLIGHT


def test_rising_needs_three_measurable_reels_in_the_account() -> None:
    reels = _account("cafe", [100, 900])
    assert _badges(reels) == {}
    # hidden counts and young reads do not count toward the median
    young = _reel("cafe", "young", 100, age_days=10, read_after_days=1)
    hidden = _reel("cafe", "hidden", 100, hidden=True)
    assert _badges([*reels, young, hidden]) == {}
    # a third measurable reel makes it
    assert _keys(_badges([*reels, _reel("cafe", "third", 100)]), "cafe-1") == ["rising"]


def test_a_young_reel_may_be_rising_but_an_old_or_hidden_one_is_not() -> None:
    base = _account("cafe", [100, 100, 100])
    young = _reel("cafe", "young", 500, age_days=1)  # read the day after: young, still rising
    old = _reel("cafe", "old", 5000, age_days=rb.RISING_WINDOW_DAYS + 1)
    hidden = _reel("cafe", "hidden", 5000, hidden=True)
    badges = _badges([*base, young, old, hidden])
    assert _keys(badges, "young") == ["rising"]
    assert _keys(badges, "old") == []
    assert _keys(badges, "hidden") == []


def test_rising_uses_the_metrics_lift_of_cm1() -> None:
    reels = _account("cafe", [100, 100, 100, 300])
    badge = _badges(reels)[("instagram", "cafe-3")][0]
    median = rb.account_median(reels)
    assert badge.provenance.value == pytest.approx(
        metrics.lift(rb._read(reels[3]), median)  # noqa: SLF001
    )
    assert badge.provenance.baseline == 100.0
    assert badge.provenance.metrics_version == metrics.CREATOR_METRICS_VERSION


# --------------------------------------------------------------------------------------
# «Top 10 % de tu rubro»
# --------------------------------------------------------------------------------------


def _rubro_world(per_account: int = 10, accounts: int = 3) -> list[PublicReel]:
    """`accounts` accounts of `food_drink`, `per_account` reels each, views 100..; every
    account flat (so nobody is «rising»)."""
    out: list[PublicReel] = []
    for a in range(accounts):
        out += _account(f"food{a}", [1000 * (a + 1)] * per_account)
    return out


def _food_rubros(reels: list[PublicReel]) -> dict[tuple[str, str], str]:
    return {(r.network, r.handle): "food_drink" for r in reels}


def test_top_rubro_goes_to_reels_at_or_over_the_rubros_90th_percentile() -> None:
    pool = _rubro_world()  # 30 reels: 10x1000, 10x2000, 10x3000 → p90 = 3000
    badges = _badges(pool, rubros=_food_rubros(pool))
    assert _keys(badges, "food2-0") == ["top_rubro"]
    assert _keys(badges, "food1-0") == []
    badge = badges[("instagram", "food2-0")][0]
    assert badge.label == "Top 10 % de tu rubro"
    assert badge.provenance.rubro == "food_drink"
    assert badge.provenance.sample == 30
    assert badge.provenance.accounts == 3
    assert badge.provenance.baseline == 3000.0


def test_an_account_without_a_known_rubro_never_shows_top_rubro() -> None:
    pool = _rubro_world()
    rubros = _food_rubros(pool)
    star = _reel("mystery", "star", 10_000_000)
    other = _reel("otherish", "other", 10_000_000)
    rubros[("instagram", "otherish")] = "otro"  # «none of the catalog fits» is not a rubro
    rubros[("instagram", "blank")] = ""
    blank = _reel("blank", "blank", 10_000_000)
    badges = _badges([*pool, star, other, blank], rubros=rubros)
    for reel_id in ("star", "other", "blank"):
        assert "top_rubro" not in _keys(badges, reel_id)


def test_a_small_rubro_pool_gives_no_badge() -> None:
    too_few = _rubro_world(per_account=9)  # 27 reels < 30
    assert _badges(too_few, rubros=_food_rubros(too_few)) == {}
    two_accounts = _rubro_world(per_account=20, accounts=2)  # 40 reels, 2 accounts < 3
    assert _badges(two_accounts, rubros=_food_rubros(two_accounts)) == {}
    assert (rb.TOP_MIN_SAMPLE, rb.TOP_MIN_ACCOUNTS) == (30, 3)


def test_the_pool_counts_only_measurable_reels_in_the_window() -> None:
    pool = _rubro_world()
    extra = [
        _reel("food0", "young", 1_000_000, age_days=1),  # young read: out of the pool
        _reel("food0", "hidden", 1_000_000, hidden=True),
        _reel("food0", "old", 1_000_000, age_days=rb.TOP_WINDOW_DAYS + 5),
    ]
    rubros = _food_rubros(pool)
    store = rb.MemoryReelBadgeStore([*pool, *extra], rubros)
    pools = store.rubro_pools(
        TENANT, ["food_drink"], since=NOW - timedelta(days=rb.TOP_WINDOW_DAYS), until=NOW
    )
    assert pools["food_drink"].sample == 30
    assert pools["food_drink"].threshold == 3000.0
    # the young reel is still judged on its own views: it reaches the threshold
    badges = rb.reel_badges(TENANT, extra, store=store, now=NOW)
    assert "top_rubro" in _keys(badges, "young")
    assert _keys(badges, "hidden") == []
    assert _keys(badges, "old") == []


def test_brand_rubros_keep_the_label_true() -> None:
    pool = _rubro_world()
    rubros = _food_rubros(pool)
    assert _keys(_badges(pool, rubros=rubros, brand_rubros={"food_drink"}), "food2-0") == [
        "top_rubro"
    ]
    assert _badges(pool, rubros=rubros, brand_rubros={"real_estate"}) == {}
    assert _badges(pool, rubros=rubros, brand_rubros=set()) == {}


def test_percentile_cont_matches_postgres() -> None:
    assert rb.percentile_cont(list(range(1, 11)), 0.9) == pytest.approx(9.1)
    assert rb.percentile_cont([5], 0.9) == 5
    assert rb.percentile_cont([1, 2], 0.5) == 1.5
    with pytest.raises(ValueError):
        rb.percentile_cont([], 0.9)


# --------------------------------------------------------------------------------------
# provenance, cost
# --------------------------------------------------------------------------------------


def test_every_badge_carries_its_provenance() -> None:
    pool = _rubro_world()
    star = _reel("food2", "star", 9000)
    reels = [*pool, star]  # food2 is flat at 3000: the star is x3 and over p90
    badges = _badges(reels, rubros=_food_rubros(reels))
    earned = badges[("instagram", "star")]
    assert [b.key for b in earned] == ["rising", "top_rubro"]
    for badge in earned:
        p = badge.provenance
        assert (p.network, p.reel_id, p.metrics_at) == ("instagram", "star", star.metrics_at)
        assert p.version == rb.REEL_BADGES_VERSION == "rb-1"
        assert p.metrics_version == "cm-1"
        assert p.sample >= 3 and p.window_days == 90
    assert rb.badge_labels(earned) == ["En ascenso", "Top 10 % de tu rubro"]


def test_at_most_three_reads_whatever_the_list() -> None:
    pool = _rubro_world()
    store = rb.MemoryReelBadgeStore(pool, _food_rubros(pool))
    rb.reel_badges(TENANT, pool, store=store, now=NOW)
    assert store.calls == ["account_reels", "account_rubros", "rubro_pools"]
    assert rb.reel_badges(TENANT, [], store=store, now=NOW) == {}
    assert len(store.calls) == 3


def _forbidden(*_: Any, **__: Any) -> Any:
    raise AssertionError("computing badges must not pay or call out")


def test_computing_badges_pays_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in dir(scrapecreators):
        if name.startswith("fetch_") and callable(getattr(scrapecreators, name)):
            monkeypatch.setattr(scrapecreators, name, _forbidden)
    monkeypatch.setattr(reels_ai, "review_reels", _forbidden)
    monkeypatch.setattr(claude_tools, "messages_create", _forbidden)
    monkeypatch.setattr(claude_tools, "create_turn", _forbidden)
    monkeypatch.setattr(httpx.Client, "send", _forbidden)
    ledger = usage.InMemoryUsageStore()
    usage.configure_store(ledger)
    try:
        pool = _rubro_world()
        assert _badges(pool, rubros=_food_rubros(pool))
    finally:
        usage.configure_store(None)
    assert ledger.events == []


def test_the_module_imports_no_paying_door() -> None:
    tree = ast.parse(inspect.getsource(rb))
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


# --------------------------------------------------------------------------------------
# two businesses
# --------------------------------------------------------------------------------------


class World:
    """Two businesses over one reel pool, through RF-01's read."""

    def __init__(self) -> None:
        self.runs = MemoryReelRunStore()
        self.labels = MemoryReferentesRepository()
        self.library = rv.MemoryReviewedReelsStore(self.runs, self.labels)

    def business(self) -> tuple[UUID, UUID]:
        tenant, brand = uuid4(), uuid4()
        self.labels.add_brand(tenant_id=tenant, brand_id=brand)
        return tenant, brand

    def follow(self, who: tuple[UUID, UUID], handle: str) -> None:
        self.labels.set_label(
            tenant_id=who[0],
            brand_id=who[1],
            network="instagram",
            handle=handle,
            label="referente",
            labeled_by=None,
        )

    def add(self, reels: list[PublicReel]) -> None:
        for reel in reels:
            self.runs.reels[(reel.network, reel.reel_id)] = reel

    def judge(self, who: tuple[UUID, UUID], reels: list[PublicReel]) -> list[UUID]:
        saved = self.runs.save_verdicts(
            who[0],
            who[1],
            [
                NewVerdict(
                    network=r.network,
                    reel_id=r.reel_id,
                    brief_hash="brief",
                    input_hash="in",
                    fits=True,
                    affinity="producto",
                    model_id="claude-haiku",
                    prompt_version="p1",
                    reason="va con tu producto",
                    cost_usd=Decimal("0.001"),
                )
                for r in reels
            ],
        )
        return [v.id for v in saved.values()]

    def ok_run(self, who: tuple[UUID, UUID], idea: PublicReel, verdict: UUID) -> None:
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
                NewIdea(
                    network="instagram",
                    reel_id=idea.reel_id,
                    rank=1,
                    window_days=30,
                    verdict_id=verdict,
                )
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
            brief_hash="brief",
            started_at=claimed.started_at,
        )


def test_two_businesses_only_ever_get_badges_for_their_own_reels() -> None:
    w = World()
    a, b = w.business(), w.business()
    reels_a = _account("cafea", [100, 100, 100, 400])
    reels_b = _account("cafeb", [100, 100, 100, 900])
    w.add([*reels_a, *reels_b])
    w.follow(a, "cafea")
    w.follow(b, "cafeb")
    ids_a = w.judge(a, reels_a)
    ids_b = w.judge(b, reels_b)
    w.ok_run(a, reels_a[3], ids_a[3])
    w.ok_run(b, reels_b[3], ids_b[3])
    store = rb.MemoryReelBadgeStore([*reels_a, *reels_b])

    seen_a = rv.reviewed_reels(a[0], a[1], store=w.runs, library=w.library, now=NOW)
    badges_a = rb.badges_for_reviewed(a[0], seen_a, store=store, now=NOW)
    seen_b = rv.reviewed_reels(b[0], b[1], store=w.runs, library=w.library, now=NOW)
    badges_b = rb.badges_for_reviewed(b[0], seen_b, store=store, now=NOW)

    assert set(badges_a) == {("instagram", "cafea-3")}
    assert set(badges_b) == {("instagram", "cafeb-3")}
    # nothing of the other business leaks into a badge's provenance
    for badges, other in ((badges_a, "cafeb"), (badges_b, "cafea")):
        for earned in badges.values():
            for badge in earned:
                assert other not in repr(badge)
                assert str(a[0]) not in repr(badge) and str(b[0]) not in repr(badge)
    # the badges of a business's reels depend on public data only, never on who asks
    assert rb.badges_for_reviewed(b[0], seen_a, store=store, now=NOW) == badges_a

"""RF-02 (m-25119460) — tenant isolation of «Ideas para tus reels» filters, against the live
schema (`-m db`): the screen's own path (`reels_discovery.stored_ideas`, `load_ideas`,
`more_reviewed`, and the «Cuenta» options built from `reviewed.accounts`) with two real
businesses. A has its brand, labels, verdicts and an `ok` run with an idea; B follows one of
A's public accounts and has verdicts of its own. Whatever filters B applies — or whichever
brand B names — nothing of A reaches B, and filtering never writes `vendor_usage_events`.
B's own brand is also scoped by an explicit `brand_id` predicate; only the crossed-brand test
exercises RLS itself.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
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
from qualify_shared.db.admin import admin_session
from sqlalchemy import text

from . import reels_discovery, reels_filters_vm

pytestmark = pytest.mark.db

BRIEF = "rf02db-brief"
ZONE = "America/Bogota"
Business = tuple[UUID, UUID]

# Only A's: reels, handles and idea. B's own are `b_*` / `bpropio`, and B shares `inspira`.
A_ONLY_REELS = {"idea", "short", "mid", "long", "comp", "rival_long"}
A_ONLY_HANDLES = {"rival", "tiktoker"}


def _business(name: str) -> Business:
    tenant, brand = uuid4(), uuid4()
    with admin_session() as session:
        session.add(Tenant(id=tenant, name=name, country="CO", timezone=ZONE, currency="COP"))
        session.flush()
        session.add(Brand(id=brand, tenant_id=tenant, name=f"{name} brand"))
    return tenant, brand


def _usage_events(*tenants: UUID) -> int:
    with admin_session() as session:
        return int(
            session.scalar(
                text("SELECT count(*) FROM vendor_usage_events WHERE tenant_id = ANY(:t)"),
                {"t": list(tenants)},
            )
            or 0
        )


class Env:
    def __init__(self) -> None:
        self.token = uuid4().hex[:8]
        self.runs = PostgresReelRunStore()
        self.labels = PostgresReferentesRepository()
        self.library = rv.PostgresReviewedReelsStore()

    def handle(self, name: str) -> str:
        return f"{name}{self.token}"

    def rid(self, name: str) -> str:
        return f"rf02{self.token}{name}"

    def short(self, reel_id: str) -> str:
        return reel_id.removeprefix(f"rf02{self.token}")

    def label(self, who: Business, network: str, name: str, label: str) -> None:
        self.labels.set_label(
            tenant_id=who[0],
            brand_id=who[1],
            network=network,
            handle=self.handle(name),
            label=label,
            labeled_by=None,
        )

    def reels(self, *rows: tuple[str, str, str, int, float]) -> None:
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

    def verdict(self, who: Business, network: str, name: str) -> UUID:
        saved = self.runs.save_verdicts(
            who[0],
            who[1],
            [
                NewVerdict(
                    network=network,
                    reel_id=self.rid(name),
                    brief_hash=BRIEF,
                    input_hash="in-producto",
                    fits=True,
                    affinity="producto",
                    model_id="claude-haiku",
                    prompt_version="p1",
                )
            ],
        )
        return next(iter(saved.values())).id

    def ok_run(self, who: Business, ideas: list[tuple[str, str, UUID]]) -> None:
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

    # --- the screen's own doors, as `discover_reels.py` calls them --------------------

    def stored(self, who: Business, filters: rv.ReelFilters | None = None) -> Any:
        return reels_discovery.stored_ideas(
            who[0],
            who[1],
            store=self.runs,
            repository=self.labels,
            timezone=ZONE,
            filters=filters,
            library=self.library,
        )

    def load(self, who: Business, filters: rv.ReelFilters | None = None) -> Any:
        return reels_discovery.load_ideas(
            who[0],
            who[1],
            store=self.runs,
            repository=self.labels,
            timezone=ZONE,
            filters=filters,
            library=self.library,
        )

    def more(
        self, who: Business, filters: rv.ReelFilters | None = None, offset: int = 0
    ) -> tuple[list[dict[str, str]], bool]:
        return reels_discovery.more_reviewed(
            who[0],
            who[1],
            filters=filters,
            offset=offset,
            store=self.runs,
            library=self.library,
        )


@pytest.fixture
def world() -> Iterator[tuple[Env, Business, Business]]:
    e = Env()
    a, b = _business("RF-02 A"), _business("RF-02 B")
    e.label(a, "instagram", "inspira", "competencia")  # A and B disagree on its kind
    e.label(a, "tiktok", "tiktoker", "referente")
    e.label(a, "instagram", "rival", "competencia")
    e.label(b, "instagram", "inspira", "referente")  # the same public account as A
    e.label(b, "instagram", "bpropio", "competencia")
    e.reels(
        ("instagram", "idea", "inspira", 9000, 12.0),
        ("instagram", "short", "inspira", 700, 10.0),
        ("instagram", "mid", "inspira", 600, 15.0),
        ("tiktok", "long", "tiktoker", 500, 45.0),
        ("instagram", "comp", "rival", 800, 20.0),
        ("instagram", "rival_long", "rival", 450, 70.0),
        ("instagram", "b_mine", "inspira", 5000, 20.0),
        ("instagram", "b_comp", "bpropio", 4000, 25.0),
    )
    idea = e.verdict(a, "instagram", "idea")
    for network, name in (
        ("instagram", "short"),
        ("instagram", "mid"),
        ("tiktok", "long"),
        ("instagram", "comp"),
        ("instagram", "rival_long"),
    ):
        e.verdict(a, network, name)
    e.ok_run(a, [("instagram", "idea", idea)])
    e.verdict(b, "instagram", "b_mine")
    e.verdict(b, "instagram", "b_comp")
    e.ok_run(b, [])
    yield e, a, b


def _every_filter(e: Env) -> list[rv.ReelFilters | None]:
    """No filter, and every combination of network, kind, duration and account — A's
    accounts and B's own — as the bar can build them."""
    account_sets = [
        (),
        (("instagram", e.handle("inspira")),),
        (("instagram", e.handle("rival")),),
        (("tiktok", e.handle("tiktoker")),),
        (("instagram", e.handle("bpropio")),),
        (("instagram", e.handle("rival")), ("tiktok", e.handle("tiktoker"))),
    ]
    durations = [
        (),
        (rv.DURATION_UNDER_15,),
        (rv.DURATION_15_30,),
        (rv.DURATION_30_60,),
        (rv.DURATION_OVER_60,),
    ]
    found: list[rv.ReelFilters | None] = [None]
    for networks, kinds, duration, accounts in itertools.product(
        [(), ("instagram",), ("tiktok",)],
        [(), ("referente",), ("competencia",)],
        durations,
        account_sets,
    ):
        found.append(
            rv.ReelFilters.of(networks=networks, kinds=kinds, durations=duration, accounts=accounts)
        )
    return found


def _card_ids(cards: list[dict[str, str]], e: Env) -> set[str]:
    return {e.short(c["id"]) for c in cards}


def _everything_seen(
    e: Env, who: Business, filters: rv.ReelFilters | None, *, is_b: bool = True
) -> set[str]:
    """Every reel id the screen path hands `who` under `filters` (ideas, «Más reels
    revisados» pages, the loaded screen) — and, by the asserts, the accounts offered."""
    stored = e.stored(who, filters)
    reviewed = stored.reviewed
    seen = {e.short(i.reel.reel_id) for i in reviewed.ideas}
    seen |= {e.short(i.reel.reel_id) for i in reviewed.more}
    offered = {handle for _, handle in reviewed.accounts}
    assert not is_b or not offered & {e.handle(h) for h in A_ONLY_HANDLES}, (
        "A's account offered to B"
    )
    options = reels_filters_vm.account_options(reels_filters_vm.accounts_by_key(reviewed.accounts))
    assert not is_b or not any(h in str(options) for h in (e.handle(x) for x in A_ONLY_HANDLES))
    screen = e.load(who, filters)
    shown_options = str(reels_filters_vm.account_options(screen.accounts))
    a_only = [e.handle(x) for x in A_ONLY_HANDLES]
    assert not is_b or not any(h in shown_options or h in str(screen.accounts) for h in a_only)
    seen |= _card_ids(screen.cards, e) | _card_ids(screen.more_cards, e)
    offset = 0
    while True:
        page, has_more = e.more(who, filters, offset)
        seen |= _card_ids(page, e)
        if not has_more or not page:
            return seen
        offset += len(page)


def test_b_never_sees_a_under_any_filter(world: Any) -> None:
    e, a, b = world
    own = {"b_mine", "b_comp"}
    # positive control: the same path does hand A its own reels, so an empty B means something
    assert _everything_seen(e, a, None, is_b=False) == A_ONLY_REELS
    for filters in _every_filter(e):
        seen = _everything_seen(e, b, filters)
        assert not seen & A_ONLY_REELS, f"A's reels reached B with {filters}"
        assert seen <= own, f"unknown reels reached B with {filters}: {seen - own}"
    # B's own data is really read: the proof above is not an empty-list artifact
    assert _everything_seen(e, b, None) == own


def test_b_sees_no_idea_and_only_its_own_accounts(world: Any) -> None:
    e, a, b = world
    reviewed = e.stored(b).reviewed
    assert reviewed.ideas == []  # A's idea is A's
    assert reviewed.accounts[("instagram", e.handle("inspira"))] == "referente"  # B's kind, not A's
    assert set(reviewed.accounts) == {
        ("instagram", e.handle("inspira")),
        ("instagram", e.handle("bpropio")),
    }
    assert {e.short(i.reel.reel_id) for i in e.stored(a).reviewed.ideas} == {"idea"}
    assert set(e.stored(a).reviewed.accounts) == {
        ("instagram", e.handle("inspira")),
        ("tiktok", e.handle("tiktoker")),
        ("instagram", e.handle("rival")),
    }


def test_b_asking_for_a_brand_gets_nothing(world: Any) -> None:
    e, a, b = world
    crossed: Business = (b[0], a[1])
    asked = (
        None,
        rv.ReelFilters.of(networks=["instagram"], kinds=["referente"]),
        rv.ReelFilters.of(
            durations=[rv.DURATION_15_30], accounts=[("instagram", e.handle("rival"))]
        ),
    )
    for filters in asked:
        # no try/except: RLS hides A's brand rows, so the screen path answers empty, and a
        # harness error must fail the test instead of passing it
        stored = e.stored(crossed, filters)
        screen = e.load(crossed, filters)
        cards, has_more = e.more(crossed, filters)
        reviewed = stored.reviewed
        assert stored.view.shown is None and stored.view.latest is None
        assert reviewed.ideas == [] and reviewed.more == [] and reviewed.accounts == {}
        assert stored.accounts == 0 and not stored.has_brief
        assert screen.cards == [] and screen.more_cards == [] and screen.accounts == {}
        assert cards == [] and has_more is False


def test_filtering_writes_no_usage_event(world: Any) -> None:
    e, a, b = world
    before = _usage_events(a[0], b[0])
    combos = _every_filter(e)[::7]  # a spread over every axis
    for who in (a, b, (b[0], a[1])):
        for filters in combos:
            e.load(who, filters)
            e.more(who, filters, 1)
    assert _usage_events(a[0], b[0]) == before

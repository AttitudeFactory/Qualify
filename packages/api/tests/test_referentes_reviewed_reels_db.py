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

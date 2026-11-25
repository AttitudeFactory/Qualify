"""RF-05 (m-25119465) against the live schema of migration 0183: the owner's weekly picks
on `brand_account_labels`, the `competitor_now` runs of `brand_reel_runs` (one per brand,
account and day; never the run the screen shows), their competitor spend kept apart, the
competitor features of `vendor_usage_events` — and two businesses never seeing, choosing
or counting each other's, even when one names the other's brand. Everything through
`tenant_session` (RLS with the NULLIF policy)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from qualify_api.referentes import PostgresReferentesRepository, reels
from qualify_api.referentes.reel_store import (
    STATUS_OK,
    TRIGGER_COMPETITOR_NOW,
    TRIGGER_WEEKLY,
    PostgresReelRunStore,
)
from qualify_api.referentes.repository import AccountLabel
from qualify_api.tenancy.models import Brand, Tenant
from qualify_api.vendors import scrapecreators as sc
from qualify_api.vendors import usage

pytestmark = pytest.mark.db

DAY = date(2026, 11, 9)
NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


def _business() -> tuple[UUID, UUID]:
    tenant, brand = uuid4(), uuid4()
    with admin_session() as session:
        session.add(
            Tenant(id=tenant, name="RF-05", country="CO", timezone="America/Bogota", currency="COP")
        )
        session.flush()
        session.add(Brand(id=brand, tenant_id=tenant, name="RF-05 brand"))
    return tenant, brand


def _label(
    repo: PostgresReferentesRepository, who: tuple[UUID, UUID], handle: str, label: str
) -> AccountLabel:
    return repo.set_label(
        tenant_id=who[0], brand_id=who[1], network="instagram", handle=handle, label=label
    )


def test_the_weekly_picks_live_on_the_label_and_a_new_label_drops_them() -> None:
    repo = PostgresReferentesRepository()
    token = uuid4().hex[:8]
    who = _business()
    rivals = [f"rival{i}{token}" for i in range(8)]
    for handle in rivals:
        _label(repo, who, handle, "competencia")
    _label(repo, who, f"insp{token}", "referente")
    repo.set_positions(
        tenant_id=who[0],
        brand_id=who[1],
        positions={("instagram", h): i for i, h in enumerate(rivals)},
    )
    # nothing picked: the first six
    weekly = reels.brand_competitors(who[0], who[1], repository=repo)
    assert [r.handle for r in weekly] == rivals[:6]

    repo.set_weekly_picks(
        tenant_id=who[0],
        brand_id=who[1],
        picks=[("instagram", rivals[7]), ("instagram", f"insp{token}")],
    )
    picked = {lb.handle for lb in repo.labels(tenant_id=who[0], brand_id=who[1]) if lb.read_weekly}
    assert picked == {rivals[7]}  # a referente is never a pick
    assert [r.handle for r in reels.brand_competitors(who[0], who[1], repository=repo)] == [
        rivals[7]
    ]

    # relabelled: the pick goes; labelled back, it does not come back by itself
    assert _label(repo, who, rivals[7], "referente").read_weekly is False
    assert _label(repo, who, rivals[7], "competencia").read_weekly is False
    # the same label again keeps it
    repo.set_weekly_picks(tenant_id=who[0], brand_id=who[1], picks=[("instagram", rivals[1])])
    assert _label(repo, who, rivals[1], "competencia").read_weekly is True


def test_another_business_can_neither_see_nor_choose_the_picks() -> None:
    repo = PostgresReferentesRepository()
    token = uuid4().hex[:8]
    a, b = _business(), _business()
    _label(repo, a, f"rival{token}", "competencia")
    repo.set_weekly_picks(tenant_id=a[0], brand_id=a[1], picks=[("instagram", f"rival{token}")])
    assert repo.labels(tenant_id=b[0], brand_id=a[1]) == ()
    with pytest.raises(ValueError):  # B naming A's brand: RLS hides it
        repo.set_weekly_picks(tenant_id=b[0], brand_id=a[1], picks=[])
    assert [lb.read_weekly for lb in repo.labels(tenant_id=a[0], brand_id=a[1])] == [True]


def test_a_competitor_read_is_one_per_account_and_day_and_never_the_shown_run() -> None:
    store = PostgresReelRunStore()
    token = uuid4().hex[:8]
    a = _business()
    weekly = store.enqueue(
        a[0],
        a[1],
        trigger=TRIGGER_WEEKLY,
        run_date=DAY,
        days=30,
        pipeline_version="reels-run-2",
        now=NOW,
    )
    first = store.enqueue(
        a[0],
        a[1],
        trigger=TRIGGER_COMPETITOR_NOW,
        run_date=DAY,
        days=30,
        pipeline_version="reels-run-2",
        now=NOW + timedelta(minutes=1),
        account=("instagram", f"rival{token}"),
    )
    again = store.enqueue(
        a[0],
        a[1],
        trigger=TRIGGER_COMPETITOR_NOW,
        run_date=DAY,
        days=30,
        pipeline_version="reels-run-2",
        now=NOW + timedelta(minutes=2),
        account=("instagram", f"rival{token}"),
    )
    other = store.enqueue(
        a[0],
        a[1],
        trigger=TRIGGER_COMPETITOR_NOW,
        run_date=DAY,
        days=30,
        pipeline_version="reels-run-2",
        now=NOW + timedelta(minutes=3),
        account=("instagram", f"otro{token}"),
    )
    assert again.id == first.id and other.id != first.id
    # the weekly run is still one per day (NULLS NOT DISTINCT)
    same_weekly = store.enqueue(
        a[0],
        a[1],
        trigger=TRIGGER_WEEKLY,
        run_date=DAY,
        days=30,
        pipeline_version="reels-run-2",
        now=NOW + timedelta(minutes=4),
    )
    assert same_weekly.id == weekly.id
    latest = store.latest_run(a[0], a[1])
    assert latest is not None and latest.id == weekly.id
    reads = store.competitor_runs(a[0], a[1], run_date=DAY)
    assert {r.id for r in reads} == {first.id, other.id}
    assert {r.account_handle for r in reads} == {f"rival{token}", f"otro{token}"}


def test_the_competitor_spend_is_a_part_of_the_runs_spend() -> None:
    store = PostgresReelRunStore()
    a = _business()
    run = store.enqueue(
        a[0],
        a[1],
        trigger=TRIGGER_WEEKLY,
        run_date=DAY,
        days=30,
        pipeline_version="reels-run-2",
        now=NOW,
    )
    claimed = store.claim(a[0], run.id, now=NOW)
    assert claimed is not None and claimed.started_at is not None
    assert store.finish(
        a[0],
        run.id,
        status=STATUS_OK,
        now=NOW,
        credits=10,
        cost_usd=Decimal("0.05"),
        brief_hash="b",
        started_at=claimed.started_at,
        competitor_credits=4,
        competitor_cost_usd=Decimal("0.02"),
    )
    done = store.get_run(a[0], run.id)
    assert done is not None
    assert (done.credits, done.competitor_credits) == (10, 4)
    assert done.competitor_cost_usd == Decimal("0.02")
    # the schema refuses a competitor part larger than the whole
    with pytest.raises(IntegrityError), tenant_session(a[0]) as session:
        session.execute(
            text("UPDATE brand_reel_runs SET competitor_credits = 11 WHERE id = :id"),
            {"id": run.id},
        )
    # and a competitor read that names no account
    with pytest.raises(IntegrityError), tenant_session(a[0]) as session:
        session.execute(
            text(
                "INSERT INTO brand_reel_runs (tenant_id, brand_id, trigger, run_date, days, "
                "pipeline_version) VALUES (:t, :b, 'competitor_now', :d, 30, 'p')"
            ),
            {"t": a[0], "b": a[1], "d": DAY},
        )


def test_another_business_never_sees_a_competitor_read() -> None:
    store = PostgresReelRunStore()
    token = uuid4().hex[:8]
    a, b = _business(), _business()
    store.enqueue(
        a[0],
        a[1],
        trigger=TRIGGER_COMPETITOR_NOW,
        run_date=DAY,
        days=30,
        pipeline_version="reels-run-2",
        now=NOW,
        account=("instagram", f"rival{token}"),
    )
    assert store.competitor_runs(b[0], a[1], run_date=DAY) == []
    assert store.competitor_runs(b[0], b[1]) == []
    # B enqueuing on A's brand: the row is hidden (or the brand FK refuses it)
    with pytest.raises((PermissionError, IntegrityError)):
        store.enqueue(
            b[0],
            a[1],
            trigger=TRIGGER_COMPETITOR_NOW,
            run_date=DAY,
            days=30,
            pipeline_version="reels-run-2",
            now=NOW,
            account=("instagram", f"rival{token}"),
        )


def test_the_competitor_features_are_booked_and_summed_apart() -> None:
    ledger = usage.PostgresUsageStore()
    a, b = _business(), _business()
    for feature in (sc.FEATURE_COMPETITOR_REELS_LIST, sc.FEATURE_COMPETITOR_REELS_TRANSCRIPT):
        assert (
            ledger.book(
                usage.UsageEvent(
                    tenant_id=a[0],
                    brand_id=a[1],
                    vendor=usage.SCRAPECREATORS,
                    feature=feature,
                    credits=1,
                    usd_estimate=Decimal("0.0019"),
                    pricing_table_version=usage.PRICING_TABLE_VERSION,
                    request_key=f"{feature}:{uuid4()}",
                ),
                capped=True,
            )
            is None
        )
    rivals = ledger.spent(
        a[0],
        usage.SCRAPECREATORS,
        features=[sc.FEATURE_COMPETITOR_REELS_LIST, sc.FEATURE_COMPETITOR_REELS_TRANSCRIPT],
    )
    assert rivals.day == 2
    assert ledger.spent(a[0], usage.SCRAPECREATORS, features=[sc.FEATURE_REELS_LIST]).day == 0
    # inside the business's own cap, never another's
    assert ledger.spent(a[0], usage.SCRAPECREATORS).day == 2
    assert ledger.spent(b[0], usage.SCRAPECREATORS).day == 0

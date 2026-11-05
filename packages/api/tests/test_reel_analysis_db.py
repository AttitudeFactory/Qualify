"""The copy of each idea's video over the live schema (0119 + 0123; founder 2026-11-04,
the R8 slice of VE-04a/VE-12): `PostgresAnalysisStore` through `reels_worker_session()`
with every 0119 CHECK in force, what `qualify_app` may not write, the screen's
`source_available` (one EXISTS in `ideas()`) and «Replicar»'s tenant-less lookup. No R2,
no network: the rows only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from qualify_shared.objects import public_source_key
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from qualify_api.referentes import reel_analysis as ra
from qualify_api.referentes import reel_reference as ref
from qualify_api.referentes import reel_runs as rr
from qualify_api.referentes.reel_store import (
    STATUS_OK,
    NewIdea,
    PostgresReelRunStore,
    PublicReel,
)
from qualify_api.tenancy.models import Brand, Tenant

pytestmark = pytest.mark.db

NOW = datetime(2026, 11, 9, 11, 30, tzinfo=UTC)


def _post() -> str:
    return f"R8{uuid4().hex[:12]}"


def _stored(store: ra.PostgresAnalysisStore, post_id: str, *, at: datetime = NOW) -> ra.AnalysisRow:
    row = store.upsert("instagram", post_id, post_url="https://x/", video_url="https://y/z.mp4")
    token = uuid4()
    assert store.claim(row.id, token=token, now=at) is not None
    source = ra.StoredSource(
        key=public_source_key("instagram", post_id, row.id),
        sha256="ab" * 32,
        seconds=12.5,
        width=720,
        height=1280,
        fps=30.0,
        edit_eligible=True,
    )
    assert store.stored(row.id, token=token, source=source, now=at)
    return row


def test_stored_not_described_passes_every_check() -> None:
    store = ra.PostgresAnalysisStore()
    post_id = _post()
    first = store.upsert("instagram", post_id, post_url="https://x/", video_url="https://y/")
    again = store.upsert("instagram", post_id, post_url="https://x/", video_url="https://y/")
    assert first.id == again.id and first.status == "queued"  # one row per reel
    _stored(store, post_id)
    with admin_session() as session:
        row = session.execute(
            text(
                "SELECT status, stage, lease_token, lease_until, pending_video_url, "
                "error_code, attempts, source_key, covered_from_s, covered_to_s, "
                "source_purge_after FROM public_reel_analyses WHERE id = :id"
            ),
            {"id": first.id},
        ).one()
    assert (row.status, row.stage, row.attempts) == ("queued", "detecting", 1)
    assert row.lease_token is None and row.lease_until is None
    assert row.pending_video_url is None and row.error_code is None
    assert row.source_key.startswith("public/reel-analyses/instagram/")
    assert (row.covered_from_s, row.covered_to_s) == (0, Decimal("12.5"))
    assert row.source_purge_after == NOW + timedelta(days=30)


def test_failure_retry_lease_and_purge_over_postgres() -> None:
    store = ra.PostgresAnalysisStore()
    post_id = _post()
    row = store.upsert("instagram", post_id, post_url="https://x/", video_url="https://y/")
    token = uuid4()
    assert store.claim(row.id, token=token, now=NOW) is not None
    assert store.claim(row.id, token=uuid4(), now=NOW) is None  # the lease is live
    assert store.renew(row.id, token=token, until=NOW + ra.LEASE)
    assert not store.renew(row.id, token=uuid4(), until=NOW + ra.LEASE)
    assert store.fail(row.id, token=token, code="source_expired", now=NOW)
    assert store.requeue(row.id, video_url="https://fresh/")
    late = NOW + timedelta(hours=1)
    assert store.claim(row.id, token=uuid4(), now=late) is not None  # attempt 2
    # an expired lease is taken over by the next run that lists the reel
    taken = store.claim(row.id, token=uuid4(), now=late + ra.LEASE + timedelta(seconds=1))
    assert taken is not None and taken.attempts == 3
    spent = late + 2 * ra.LEASE + timedelta(seconds=2)
    assert store.claim(row.id, token=uuid4(), now=spent) is None  # 3 attempts spent

    kept = _stored(store, _post())
    due = NOW + timedelta(days=30)
    seen = {r.id for r in store.due_for_purge(now=due, limit=1000)}
    assert kept.id in seen
    assert store.mark_purged(kept.id, now=due) and not store.mark_purged(kept.id, now=due)
    assert kept.id not in {r.id for r in store.due_for_purge(now=due, limit=1000)}


def test_the_app_only_reads_the_analysis() -> None:
    tenant = uuid4()
    with pytest.raises(ProgrammingError), tenant_session(tenant) as session:
        session.execute(text("UPDATE public_reel_analyses SET source_key = 'public/x'"))


def _business() -> tuple:
    tenant, brand = uuid4(), uuid4()
    with admin_session() as session:
        session.add(
            Tenant(id=tenant, name="R8", country="CO", timezone="America/Bogota", currency="COP")
        )
        session.flush()
        session.add(Brand(id=brand, tenant_id=tenant, name="R8 brand"))
    return tenant, brand


def test_ideas_say_when_the_run_kept_the_video_and_replicar_finds_it() -> None:
    runs, analyses = PostgresReelRunStore(), ra.PostgresAnalysisStore()
    tenant, brand = _business()
    kept, fresh = _post(), _post()
    run = rr.enqueue_run(tenant, brand, "manual", store=runs, clock=NOW.timestamp)
    assert runs.claim(tenant, run.id, now=NOW) is not None
    now = datetime.now(UTC)
    runs.upsert_reels(
        tenant,
        [
            PublicReel(
                network="instagram",
                reel_id=post_id,
                handle="foodie",
                taken_at=NOW - timedelta(days=1),
                metrics_at=now,
                parser_version=1,
                video_url=f"https://scontent.cdninstagram.com/{post_id}.mp4",
                video_url_at=now,
            )
            for post_id in (kept, fresh)
        ],
    )
    ideas = [NewIdea("instagram", kept, 1, 7, None), NewIdea("instagram", fresh, 2, 7, None)]
    assert runs.save_ideas(tenant, brand, run.id, ideas, started_at=NOW)
    assert runs.finish(
        tenant,
        run.id,
        status=STATUS_OK,
        now=NOW,
        credits=0,
        cost_usd=Decimal("0"),
        brief_hash=None,
        started_at=NOW,
    )
    stored = _stored(analyses, kept)
    shown = {i.reel.reel_id: i for i in rr.view(tenant, brand, store=runs).ideas}
    assert shown[kept].source_available and shown[kept].can_replicate
    assert not shown[fresh].source_available and shown[fresh].can_replicate  # link < 20 h

    key, url = ref._idea_video("instagram", kept)
    assert key == public_source_key("instagram", kept, stored.id) and url is not None
    assert ref._idea_video("instagram", fresh)[0] is None
    assert ref._idea_video("instagram", _post()) == (None, None)

"""R8 over VE-04a's live schema (0119 + 0126; ADR 42 R8 m-24854855, the R8 slice of VE-12
m-24921060): the 30-day purge through `PostgresAnalysisQueue` as `qualify_reels_worker`
(the date written before the upload, the keyset, the live lease, the moved date), the
screen's `source_available` (one EXISTS in `ideas()`) and «Replicar»'s tenant-less lookup
(`reel_reference._idea_video`, `global_session`). No network: R2 is an in-memory store
behind the real `PublicObjectGate`."""

from __future__ import annotations

import io
import os
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.objects.gate import StoredObject
from qualify_shared.objects.public import PublicObjectGate, reel_source_key
from sqlalchemy import create_engine, text

from qualify_api.referentes import reel_reference as ref
from qualify_api.referentes import reel_retention as rt
from qualify_api.referentes import reel_runs as rr
from qualify_api.referentes.reel_analysis_queue import PostgresAnalysisQueue
from qualify_api.referentes.reel_analysis_store import SourceFacts
from qualify_api.referentes.reel_analysis_types import ANALYSIS_VERSION, ReelSource
from qualify_api.referentes.reel_store import (
    STATUS_OK,
    NewIdea,
    PostgresReelRunStore,
    PublicReel,
)
from qualify_api.tenancy.models import Brand, Tenant

pytestmark = pytest.mark.db

NOW = datetime.now(UTC).replace(microsecond=0)
LEASE = timedelta(minutes=2)
CDN = "https://scontent-bog1-1.cdninstagram.com/o1/v/t16/clip.mp4?efg=abc"


@pytest.fixture(autouse=True)
def empty_analyses() -> Iterator[None]:
    """A clean analysis table per test (the test database only — the guard refuses any
    other)."""
    engine = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM public_reel_analyses"))
    yield
    engine.dispose()


class DictStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, fileobj: Any, content_type: str) -> None:
        self.objects[key] = fileobj.read()

    def open(self, key: str) -> io.BytesIO:
        return io.BytesIO(self.objects[key])

    def list_prefix(self, prefix: str) -> Iterator[StoredObject]:
        for key, data in sorted(self.objects.items()):
            if key.startswith(prefix):
                yield StoredObject(key, len(data))

    def delete_keys(self, keys: Sequence[str]) -> None:
        for key in keys:
            self.objects.pop(key, None)


def _post() -> str:
    return f"R8{uuid4().hex[:12]}"


def _held(queue: PostgresAnalysisQueue, post_id: str, at: datetime) -> tuple[UUID, UUID]:
    """A row of the analysis queue, claimed at `at` with its purge date already written."""
    record, _ = queue.ensure(
        ReelSource(
            network="instagram",
            post_id=post_id,
            post_url=f"https://www.instagram.com/reel/{post_id}/",
            video_url=CDN,
        ),
        ANALYSIS_VERSION,
        at,
    )
    claimed = queue.claim(record.id, at, LEASE, max_attempts=3)
    assert claimed is not None
    assert queue.set_purge_date(record.id, claimed.token, at + timedelta(days=30))
    return record.id, claimed.token


def _facts(post_id: str, analysis_id: UUID) -> SourceFacts:
    return SourceFacts(
        source_key=reel_source_key("instagram", post_id, analysis_id),
        source_sha256="ab" * 32,
        source_seconds=12.5,
        width=720,
        height=1280,
        fps=30.0,
        covered_from_s=0.0,
        covered_to_s=12.5,
        edit_eligible=True,
    )


def _stored(queue: PostgresAnalysisQueue, post_id: str, at: datetime = NOW) -> UUID:
    analysis_id, token = _held(queue, post_id, at)
    assert queue.record_source(
        analysis_id, token, _facts(post_id, analysis_id), at + timedelta(days=30)
    )
    assert queue.release(analysis_id, token)
    return analysis_id


# --------------------------------------------------------------------------------------
# the 30-day purge
# --------------------------------------------------------------------------------------


def test_the_purge_reads_the_due_rows_and_marks_them_once() -> None:
    queue = PostgresAnalysisQueue()
    stored = _stored(queue, _post())
    orphan, _token = _held(queue, _post(), NOW)  # uploaded, never recorded; lease expires
    due = NOW + timedelta(days=30)

    assert queue.purge_due(NOW + timedelta(days=29), after=None, limit=10) == []
    listed = queue.purge_due(due, after=None, limit=10)
    assert {d.id for d in listed} == {stored, orphan}  # by the date, not by source_key
    first = min(listed, key=lambda d: (d.purge_after, d.id))
    rest = queue.purge_due(due, after=(first.purge_after, first.id), limit=10)
    assert [d.id for d in rest] == [d.id for d in listed if d.id != first.id]  # keyset

    seen = next(d for d in listed if d.id == stored).purge_after
    assert not queue.mark_purged(stored, seen + timedelta(seconds=1), due)  # date moved
    assert queue.mark_purged(stored, seen, due)
    assert not queue.mark_purged(stored, seen, due)  # once
    assert {d.id for d in queue.purge_due(due, after=None, limit=10)} == {orphan}


def test_a_live_lease_waits_and_a_new_date_clears_the_marks() -> None:
    queue = PostgresAnalysisQueue()
    post_id = _post()
    analysis_id, token = _held(queue, post_id, NOW - timedelta(days=30))
    due = NOW
    # the row is still held (its lease renewed up to now + 2 min): left for the next day
    assert queue.renew(analysis_id, token, NOW + LEASE)
    assert queue.purge_due(due, after=None, limit=10) == []
    assert queue.release(analysis_id, token)
    [row] = queue.purge_due(due, after=None, limit=10)
    assert queue.mark_purged(analysis_id, row.purge_after, due)

    # revived later (a failed download a new URL brings back): a new date, marks cleared
    claimed = queue.claim(analysis_id, NOW, LEASE, max_attempts=3)
    assert claimed is not None
    assert queue.set_purge_date(analysis_id, claimed.token, NOW + timedelta(days=30))
    record = queue.get(analysis_id)
    assert record is not None
    assert (record.source_purged_at, record.frames_purged_at) == (None, None)
    assert record.source_purge_after == NOW + timedelta(days=30)


def test_a_purged_queued_row_is_not_claimed_by_the_download_lane() -> None:
    """FN3 over Postgres: the download-only claim needs `pending_video_url`, which
    `record_source` cleared. VE-04c (m-24921058) must make its describe claim skip
    `source_purged_at` too."""
    queue = PostgresAnalysisQueue()
    analysis_id = _stored(queue, _post())
    due = NOW + timedelta(days=30)
    assert queue.mark_purged(analysis_id, due, due)
    later = due + timedelta(minutes=1)
    assert queue.claim_next(later, LEASE, download_only=True, max_attempts=3) is None


def test_purge_reel_sources_over_postgres_deletes_both_folders() -> None:
    queue, r2 = PostgresAnalysisQueue(), DictStore()
    post_id = _post()
    analysis_id = _stored(queue, post_id)
    key = reel_source_key("instagram", post_id, analysis_id)
    r2.objects[key] = b"mp4"
    r2.objects[key.replace("source/source.mp4", "frames/00-0.jpg")] = b"jpg"
    report = rt.purge_reel_sources(
        PublicObjectGate(r2), NOW + timedelta(days=30), True, store=queue
    )
    assert (report.due, report.purged, report.objects, report.failed) == (1, 1, 2, 0)
    assert r2.objects == {}
    record = queue.get(analysis_id)
    assert record is not None and record.source_purged_at is not None
    assert record.source_key == key  # the row and its sheet stay


# --------------------------------------------------------------------------------------
# the screen: source_available, and «Replicar»'s lookup
# --------------------------------------------------------------------------------------


def _business() -> tuple[UUID, UUID]:
    tenant, brand = uuid4(), uuid4()
    with admin_session() as session:
        session.add(
            Tenant(id=tenant, name="R8", country="CO", timezone="America/Bogota", currency="COP")
        )
        session.flush()
        session.add(Brand(id=brand, tenant_id=tenant, name="R8 brand"))
    return tenant, brand


def test_ideas_say_when_the_source_is_stored_and_replicar_finds_it() -> None:
    runs, queue = PostgresReelRunStore(), PostgresAnalysisQueue()
    tenant, brand = _business()
    kept, fresh, purged = _post(), _post(), _post()
    run = rr.enqueue_run(tenant, brand, "manual", store=runs, clock=NOW.timestamp)
    assert runs.claim(tenant, run.id, now=NOW) is not None
    read = datetime.now(UTC)
    runs.upsert_reels(
        tenant,
        [
            PublicReel(
                network="instagram",
                reel_id=post_id,
                handle="foodie",
                taken_at=NOW - timedelta(days=1),
                metrics_at=read,
                parser_version=1,
                video_url=f"https://scontent.cdninstagram.com/{post_id}.mp4",
                video_url_at=read,
            )
            for post_id in (kept, fresh, purged)
        ],
    )
    ideas = [NewIdea("instagram", p, n, 7, None) for n, p in enumerate((kept, fresh, purged), 1)]
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
    stored = _stored(queue, kept)
    gone = _stored(queue, purged)
    assert queue.mark_purged(gone, NOW + timedelta(days=30), NOW + timedelta(days=30))

    shown = {i.reel.reel_id: i for i in rr.view(tenant, brand, store=runs).ideas}
    assert shown[kept].source_available and shown[kept].can_replicate
    assert not shown[fresh].source_available and shown[fresh].can_replicate  # fresh link
    assert not shown[purged].source_available  # purged: only its link is left

    key, url = ref._idea_video("instagram", kept)
    assert key == reel_source_key("instagram", kept, stored) and url is not None
    assert ref._idea_video("instagram", fresh)[0] is None
    assert ref._idea_video("instagram", purged)[0] is None
    assert ref._idea_video("instagram", _post()) == (None, None)

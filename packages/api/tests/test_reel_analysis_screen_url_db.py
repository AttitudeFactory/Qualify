"""«Hacer uno parecido» on a reel whose first URL had expired (m-24984404), against the
live schema: the screen (`qualify_app`, `tenant_session`) hands an existing row a fresh
URL through 0142's `reel_analysis_offer_url`, with the real column grants, row lock and
quota lock.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

from qualify_api.referentes.reel_analysis import request_analysis
from qualify_api.referentes.reel_analysis_queue import PostgresAnalysisQueue
from qualify_api.referentes.reel_analysis_store import (
    AnalysisRecord,
    PostgresAnalysisRequests,
    pending_url_read_at,
)
from qualify_api.referentes.reel_analysis_types import (
    ANALYSIS_VERSION,
    STATUS_DAILY_LIMIT,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    ReelSource,
)

pytestmark = pytest.mark.db

NOW = datetime.now(UTC).replace(microsecond=0)
CDN = "https://scontent-bog1-1.cdninstagram.com/o1/v/t16/clip.mp4?efg=abc"
FRESH = CDN + "&fresh=1"
LEASE = timedelta(minutes=2)


@pytest.fixture(autouse=True)
def empty_tables() -> Iterator[None]:
    """A clean queue per test (the test database only — the guard refuses any other)."""
    engine = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM public_reel_analyses"))
    yield
    engine.dispose()


def _source(post_id: str | None = None, url: str = FRESH) -> ReelSource:
    post_id = post_id or f"P{uuid4().hex[:10]}"
    return ReelSource(
        network="instagram",
        post_id=post_id,
        post_url=f"https://www.instagram.com/reel/{post_id}/",
        video_url=url,
    )


def _failed(code: str = "source_expired", *, days_ago: int = 3) -> AnalysisRecord:
    """A row the weekly run made days ago whose download failed with `code`."""
    queue = PostgresAnalysisQueue()
    at = NOW - timedelta(days=days_ago)
    record, _ = queue.ensure(_source(url=CDN), ANALYSIS_VERSION, at)
    held = queue.claim(record.id, at, LEASE, max_attempts=3)
    assert held is not None
    assert queue.fail(record.id, held.token, code, at)
    row = queue.get(record.id)
    assert row is not None and row.status == STATUS_FAILED
    return row


def _ask(record: AnalysisRecord, url: str = FRESH, cap: int = 50):
    return request_analysis(
        uuid4(),
        _source(record.post_id, url),
        store=PostgresAnalysisRequests(),
        clock=lambda: NOW,
        daily_limit=cap,
    )


def _get(analysis_id: UUID) -> AnalysisRecord:
    row = PostgresAnalysisQueue().get(analysis_id)
    assert row is not None
    return row


def test_an_expired_row_goes_back_to_the_queue_with_the_fresh_url() -> None:
    failed = _failed()
    ref = _ask(failed)
    assert (ref.id, ref.status) == (failed.id, STATUS_QUEUED)
    row = _get(failed.id)
    assert row.status == STATUS_QUEUED and row.pending_video_url == FRESH
    assert row.wanted_at == NOW and row.error_code is None and row.finished_at is None
    assert row.pending_url_at == NOW
    # The worker claims it again (its attempts were not exhausted).
    claimed = PostgresAnalysisQueue().claim(failed.id, NOW, LEASE, max_attempts=3)
    assert claimed is not None and claimed.record.attempts == 2


def test_a_full_quota_answers_daily_limit_and_writes_nothing() -> None:
    failed = _failed()
    request_analysis(
        uuid4(), _source(), store=PostgresAnalysisRequests(), clock=lambda: NOW, daily_limit=1
    )
    ref = _ask(failed, cap=1)
    assert (ref.id, ref.status) == (None, STATUS_DAILY_LIMIT)
    assert _get(failed.id) == failed


@pytest.mark.parametrize("code", ["source_unavailable", "model_failed"])
def test_other_failures_are_not_retried(code: str) -> None:
    failed = _failed(code)
    ref = _ask(failed)
    assert (ref.id, ref.status) == (failed.id, STATUS_FAILED)
    assert _get(failed.id) == failed


def test_without_a_usable_url_the_row_stays_failed() -> None:
    failed = _failed()
    ref = _ask(failed, url="")
    assert (ref.id, ref.status) == (failed.id, STATUS_FAILED)
    assert _get(failed.id) == failed


def test_a_queued_row_with_a_stale_url_takes_the_fresh_one() -> None:
    queue = PostgresAnalysisQueue()
    record, _ = queue.ensure(_source(url=CDN), ANALYSIS_VERSION, NOW - timedelta(days=2))
    ref = _ask(record)
    assert (ref.id, ref.status) == (record.id, STATUS_QUEUED)
    row = _get(record.id)
    assert row.pending_video_url == FRESH and row.wanted_at == NOW


def test_joining_the_on_demand_lane_does_not_date_the_url() -> None:
    """`mark_wanted` moves `wanted_at` only: the stored URL keeps its creation as read
    time (`pending_url_read_at`), so the worker's 20 h guard still holds."""
    queue = PostgresAnalysisQueue()
    created = NOW - timedelta(hours=30)
    record, _ = queue.ensure(_source(url=CDN), ANALYSIS_VERSION, created)
    ref = _ask(record, url="")
    assert (ref.id, ref.status) == (record.id, STATUS_QUEUED)
    row = _get(record.id)
    assert row.wanted_at == NOW and row.pending_url_at is None
    assert pending_url_read_at(row) == created


def test_a_run_dates_the_url_it_hands_over() -> None:
    queue = PostgresAnalysisQueue()
    record, _ = queue.ensure(_source(url=CDN), ANALYSIS_VERSION, NOW - timedelta(hours=30))
    again, _ = queue.ensure(_source(record.post_id, FRESH), ANALYSIS_VERSION, NOW)
    assert again.pending_video_url == FRESH and again.pending_url_at == NOW


def test_a_running_row_is_never_touched() -> None:
    queue = PostgresAnalysisQueue()
    record, _ = queue.ensure(_source(url=CDN), ANALYSIS_VERSION, NOW - timedelta(days=2))
    held = queue.claim(record.id, NOW, LEASE, max_attempts=3)
    assert held is not None
    ref = _ask(record)
    assert (ref.id, ref.status) == (record.id, STATUS_RUNNING)
    row = _get(record.id)
    assert row.pending_video_url == CDN and row.lease_token == held.token


def test_the_screen_still_cannot_write_status_itself() -> None:
    """0142 adds a function, not a grant: `qualify_app` keeps only `wanted_at`."""
    failed = _failed()
    from qualify_shared.db.session import tenant_session

    with pytest.raises(ProgrammingError):
        with tenant_session(uuid4()) as session:
            session.execute(
                text("UPDATE public_reel_analyses SET status = 'queued' WHERE id = :id"),
                {"id": failed.id},
            )


def _race(fn, n: int) -> list:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    barrier = Barrier(n)

    def go(i: int):
        barrier.wait()
        return fn(i)

    with ThreadPoolExecutor(n) as pool:
        return list(pool.map(go, range(n)))


def test_two_screens_never_both_requeue_into_the_last_on_demand_place() -> None:
    rows = [_failed() for _ in range(5)]
    refs = _race(lambda i: _ask(rows[i], cap=1), 5)
    assert sorted(r.status for r in refs) == [STATUS_DAILY_LIMIT] * 4 + [STATUS_QUEUED]
    assert sum(_get(r.id).status == STATUS_QUEUED for r in rows) == 1

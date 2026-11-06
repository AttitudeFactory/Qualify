"""The shared reel analysis against the live schema of 0119 (ADR 44, m-24921056 VE-04a):
the screen's side as `qualify_app` through `tenant_session`, the worker's side as
`qualify_reels_worker` through its own door. Same behaviour as the in-memory store, now
with the real column grants, the `ON CONFLICT`, `FOR UPDATE SKIP LOCKED` and the CHECKs.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from qualify_api.referentes.reel_analysis import (
    analysis_badges,
    get_analysis,
    get_analysis_status,
    request_analysis,
)
from qualify_api.referentes.reel_analysis_queue import PostgresAnalysisQueue
from qualify_api.referentes.reel_analysis_store import (
    BADGE_LOOKING,
    BADGE_PERSON,
    CALL_FLEET_CAP,
    CALL_LOST,
    CALL_OK,
    CALL_ROW_CAP,
    DescribeResult,
    PostgresAnalysisRequests,
    SourceFacts,
    Spend,
)
from qualify_api.referentes.reel_analysis_types import (
    ANALYSIS_VERSION,
    OBSERVED,
    STATUS_DAILY_LIMIT,
    STATUS_FAILED,
    STATUS_OK,
    STATUS_QUEUED,
    ReelSource,
    ShotAnalysis,
)

pytestmark = pytest.mark.db

NOW = datetime.now(UTC).replace(microsecond=0)
CDN = "https://scontent-bog1-1.cdninstagram.com/o1/v/t16/clip.mp4?efg=abc"
LEASE = timedelta(minutes=2)


@pytest.fixture(autouse=True)
def empty_tables() -> Iterator[None]:
    """A clean queue per test (the test database only — the guard refuses any other)."""
    engine = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM public_reel_analyses"))
    yield
    engine.dispose()


def _source(post_id: str | None = None, url: str = CDN) -> ReelSource:
    post_id = post_id or f"P{uuid4().hex[:10]}"
    return ReelSource(
        network="instagram",
        post_id=post_id,
        post_url=f"https://www.instagram.com/reel/{post_id}/",
        video_url=url,
    )


def _facts(key: str) -> SourceFacts:
    return SourceFacts(
        source_key=key,
        source_sha256="c" * 64,
        source_seconds=70.0,
        width=720,
        height=1280,
        fps=30.0,
        covered_from_s=0.0,
        covered_to_s=60.0,
        edit_eligible=True,
    )


def _result() -> DescribeResult:
    return DescribeResult(
        shots=(
            ShotAnalysis(0, 0.0, 2.5, ("k0",), (0.4,), people_presence=OBSERVED),
            ShotAnalysis(1, 2.5, 60.0, families={"subject": {"status": "unknown"}}),
        ),
        reel_sheet={"hook": {"status": "observed"}},
        model_id="claude-haiku-5-5",
        model_revision="rev",
        prompt_version="p1",
        schema_version="s1",
        detector_version="d1",
        sampling_version="m1",
        sampling_params={"max_frames": 32},
        input_tokens=40_000,
        output_tokens=3_000,
        cost_usd=Decimal("0.0055"),
    )


def test_two_businesses_one_row_and_no_column_says_who() -> None:
    requests = PostgresAnalysisRequests()
    src = _source()
    a = request_analysis(uuid4(), src, store=requests, clock=lambda: NOW)
    b = request_analysis(uuid4(), src, store=requests, clock=lambda: NOW + timedelta(seconds=5))
    assert a.status == STATUS_QUEUED and a.id is not None and b.id == a.id
    row = requests.find(uuid4(), "instagram", src.post_id, ANALYSIS_VERSION)
    assert row is not None and row.wanted_at == NOW and row.pending_video_url == CDN


def test_the_daily_quota_refuses_without_inserting() -> None:
    requests = PostgresAnalysisRequests()
    tenant = uuid4()
    assert request_analysis(tenant, _source(), store=requests, clock=lambda: NOW).status == (
        STATUS_QUEUED
    )
    refused = _source()
    ref = request_analysis(tenant, refused, store=requests, clock=lambda: NOW, daily_limit=1)
    assert (ref.id, ref.status) == (None, STATUS_DAILY_LIMIT)
    assert requests.find(tenant, "instagram", refused.post_id, ANALYSIS_VERSION) is None


def test_on_demand_is_claimed_before_ten_older_weekly_rows() -> None:
    queue, requests = PostgresAnalysisQueue(), PostgresAnalysisRequests()
    for i in range(10):
        queue.ensure(_source(), ANALYSIS_VERSION, NOW - timedelta(hours=3, minutes=i))
    asked = request_analysis(uuid4(), _source(), store=requests, clock=lambda: NOW)
    claimed = queue.claim_next(NOW, LEASE, download_only=True, max_attempts=3)
    assert claimed is not None and claimed.record.id == asked.id
    assert claimed.record.attempts == 1
    status = get_analysis_status(uuid4(), asked.id, store=requests, clock=lambda: NOW)
    assert status is not None and status.status == "running" and status.queue_ahead == 0


def test_lease_fence_guard_and_one_transaction_result() -> None:
    queue, requests = PostgresAnalysisQueue(), PostgresAnalysisRequests()
    record, created = queue.ensure(_source(), ANALYSIS_VERSION, NOW)
    assert created
    held = queue.claim(record.id, NOW, LEASE, max_attempts=3)
    assert held is not None
    # Another process cannot take a live lease; after it expires it can.
    assert queue.claim(record.id, NOW + timedelta(seconds=30), LEASE, max_attempts=3) is None
    later = NOW + timedelta(minutes=3)
    taken = queue.claim(record.id, later, LEASE, max_attempts=3)
    assert taken is not None and taken.record.attempts == 2
    # The first process is fenced off from every write.
    key = f"public/reel-analyses/instagram/{record.post_id}/{record.id}/source/source.mp4"
    assert not queue.record_source(record.id, held.token, _facts(key), later)
    assert queue.add_model_call(
        record.id, held.token, now=later, since=later - timedelta(days=1), fleet_cap=99
    ) == (CALL_LOST)
    assert not queue.complete(record.id, held.token, _result(), later)
    # The holder writes.
    assert queue.record_source(record.id, taken.token, _facts(key), later + timedelta(days=30))
    since = later - timedelta(days=1)
    assert (
        queue.add_model_call(record.id, taken.token, now=later, since=since, fleet_cap=1) == CALL_OK
    )
    assert (
        queue.add_model_call(record.id, taken.token, now=later, since=since, fleet_cap=1)
        == CALL_FLEET_CAP
    )
    assert (
        queue.add_model_call(record.id, taken.token, now=later, since=since, fleet_cap=99)
        == CALL_OK
    )
    assert (
        queue.add_model_call(record.id, taken.token, now=later, since=since, fleet_cap=99)
        == CALL_ROW_CAP
    )
    assert queue.complete(record.id, taken.token, _result(), later)
    done = get_analysis(uuid4(), record.id, store=requests)
    assert done is not None and [s.shot_index for s in done.shots] == [0, 1]
    assert done.provenance.cost_usd == Decimal("0.0055") and done.covered_to_s == 60.0
    stored = queue.get(record.id)
    assert stored is not None and stored.status == STATUS_OK and stored.model_calls == 2
    assert stored.pending_video_url is None and stored.lease_token is None
    badges = analysis_badges(uuid4(), [("instagram", record.post_id)], store=requests)
    assert badges == {("instagram", record.post_id): BADGE_PERSON}
    # An ok row is never claimed again.
    assert queue.claim(record.id, later + timedelta(hours=1), LEASE, max_attempts=3) is None


def test_retry_backoff_failure_and_url_refresh() -> None:
    queue = PostgresAnalysisQueue()
    record, _ = queue.ensure(_source(), ANALYSIS_VERSION, NOW)
    held = queue.claim(record.id, NOW, LEASE, max_attempts=3)
    assert held is not None
    assert queue.retry_later(
        record.id, held.token, "source_unavailable", NOW + timedelta(minutes=1)
    )
    assert queue.claim(record.id, NOW + timedelta(seconds=30), LEASE, max_attempts=3) is None
    again = queue.claim(record.id, NOW + timedelta(minutes=2), LEASE, max_attempts=3)
    assert again is not None
    assert queue.fail(record.id, again.token, "source_expired", NOW + timedelta(minutes=2))
    failed = queue.get(record.id)
    assert failed is not None and failed.status == STATUS_FAILED and failed.finished_at
    refreshed = queue.refresh_url(record.id, CDN + "&new=1", NOW, 3)
    assert refreshed is not None and refreshed.status == STATUS_QUEUED
    assert refreshed.pending_video_url == CDN + "&new=1" and refreshed.finished_at is None


def test_failed_paid_calls_add_their_tokens_and_cost_to_the_row() -> None:
    """VE-04c: a paid call that came back unusable is still on the row (decision #10)."""
    queue = PostgresAnalysisQueue()
    record, _ = queue.ensure(_source(), ANALYSIS_VERSION, NOW)
    spent = Spend(input_tokens=40_300, output_tokens=3_000, cost_usd=Decimal("0.005588"))
    held = queue.claim(record.id, NOW, LEASE, max_attempts=3)
    assert held is not None
    assert queue.retry_later(
        record.id, held.token, "model_failed", NOW + timedelta(minutes=1), spent=spent
    )
    again = queue.claim(record.id, NOW + timedelta(minutes=2), LEASE, max_attempts=3)
    assert again is not None
    assert queue.fail(
        record.id, again.token, "model_failed", NOW + timedelta(minutes=2), spent=spent
    )
    row = queue.get(record.id)
    assert row is not None and row.status == STATUS_FAILED
    assert (row.input_tokens, row.output_tokens) == (80_600, 6_000)
    assert row.cost_usd == Decimal("0.011176")
    # a stale token writes nothing, spend included
    assert not queue.fail(record.id, again.token, "model_failed", NOW, spent=spent)
    assert queue.get(record.id).cost_usd == Decimal("0.011176")


def test_a_describing_claim_skips_rows_of_an_older_analysis_version() -> None:
    """VE-04c: a queued row of an older version is never described by today's prompt (it
    would be paid for and saved under a version nobody reads); downloads still take it."""
    queue = PostgresAnalysisQueue()
    old, _ = queue.ensure(_source(), ANALYSIS_VERSION - 1, NOW - timedelta(hours=1))
    assert queue.claim_next(NOW, LEASE, download_only=False, max_attempts=3) is None
    current, _ = queue.ensure(_source(), ANALYSIS_VERSION, NOW)
    claimed = queue.claim_next(NOW, LEASE, download_only=False, max_attempts=3)
    assert claimed is not None and claimed.record.id == current.id
    downloading = queue.claim_next(NOW, LEASE, download_only=True, max_attempts=3)
    assert downloading is not None and downloading.record.id == old.id


def test_rows_out_of_attempts_are_reaped_and_a_release_gives_back_the_attempt() -> None:
    queue, requests = PostgresAnalysisQueue(), PostgresAnalysisRequests()
    record, _ = queue.ensure(_source(), ANALYSIS_VERSION, NOW)
    held = queue.claim(record.id, NOW, LEASE, max_attempts=3)
    assert held is not None and queue.release(record.id, held.token)
    assert queue.get(record.id).attempts == 0  # type: ignore[union-attr]
    t = NOW
    for _ in range(3):
        t += timedelta(minutes=5)
        assert queue.claim(record.id, t, LEASE, max_attempts=3) is not None
    assert queue.claim(record.id, t + timedelta(minutes=5), LEASE, max_attempts=3) is None
    assert queue.reap_exhausted(t + timedelta(minutes=5), 3) == 1
    reaped = queue.get(record.id)
    assert reaped is not None and (reaped.status, reaped.error_code) == (
        STATUS_FAILED,
        "source_unavailable",
    )
    badges = analysis_badges(uuid4(), [("instagram", record.post_id)], store=requests)
    assert badges[("instagram", record.post_id)] != BADGE_LOOKING


def test_a_run_gives_a_screen_row_its_transcript_and_fresh_url() -> None:
    queue, requests = PostgresAnalysisQueue(), PostgresAnalysisRequests()
    src = _source(url=CDN + "&old=1")
    asked = request_analysis(uuid4(), src, store=requests, clock=lambda: NOW)
    fresh = ReelSource(
        network="instagram",
        post_id=src.post_id,
        post_url=src.post_url,
        video_url=CDN + "&new=1",
        transcript="hola",
    )
    record, created = queue.ensure(fresh, ANALYSIS_VERSION, NOW)
    assert not created and record.id == asked.id
    assert record.pending_video_url == CDN + "&new=1"
    assert record.transcript == {"text": "hola", "segments": []}
    assert record.transcript_source == "vendor_stt"


def _race(fn, n: int) -> list:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    barrier = Barrier(n)

    def go(i: int):
        barrier.wait()
        return fn(i)

    with ThreadPoolExecutor(n) as pool:
        return list(pool.map(go, range(n)))


def test_two_screens_never_both_take_the_last_on_demand_place() -> None:
    requests = PostgresAnalysisRequests()
    sources = [_source() for _ in range(6)]
    refs = _race(
        lambda i: request_analysis(
            uuid4(), sources[i], store=requests, clock=lambda: NOW, daily_limit=1
        ),
        6,
    )
    assert sorted(r.status for r in refs) == [STATUS_DAILY_LIMIT] * 5 + [STATUS_QUEUED]


def test_two_workers_never_both_charge_the_last_fleet_call() -> None:
    queue = PostgresAnalysisQueue()
    held = []
    for _ in range(6):
        record, _ = queue.ensure(_source(), ANALYSIS_VERSION, NOW)
        claimed = queue.claim(record.id, NOW, LEASE, max_attempts=3)
        assert claimed is not None
        held.append(claimed)
    since = NOW - timedelta(days=1)
    answers = _race(
        lambda i: queue.add_model_call(
            held[i].record.id, held[i].token, now=NOW, since=since, fleet_cap=1
        ),
        6,
    )
    assert sorted(answers) == [CALL_FLEET_CAP] * 5 + [CALL_OK]

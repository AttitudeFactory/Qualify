"""«Hacer uno parecido» on a reel whose first URL had expired (m-24984404), offline.

An existing row takes the screen's usable URL: a `failed` `source_expired` row goes back
to the queue (counted against the on-demand quota), a `queued` row with a missing or
stale pending URL gets it swapped in. Running rows, other failures, no usable URL and a
full quota leave the row as it is.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from qualify_api.referentes.reel_analysis import request_analysis
from qualify_api.referentes.reel_analysis_store import (
    MAX_ATTEMPTS,
    MAX_MODEL_CALLS,
    OFFER_DAILY_LIMIT,
    OFFER_REPLACED,
    OFFER_REQUEUED,
    OFFER_UNCHANGED,
    QUOTA_LOCK_KEY,
    AnalysisRecord,
    InMemoryAnalysisStore,
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

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
TENANT = uuid4()
CDN = "https://scontent-bog1-1.cdninstagram.com/o1/v/t16/f2/m86/clip.mp4?efg=x"
FRESH = CDN + "&fresh=1"
EXPIRED = CDN + "&oe=" + format(int((NOW - timedelta(minutes=1)).timestamp()), "x")
MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "migrations"
    / "postgres"
    / "versions"
    / "0142_reel_analysis_screen_url.py"
)


def _source(post_id: str = "DSCR1", url: str = FRESH, **kw: object) -> ReelSource:
    return ReelSource(
        network="instagram",
        post_id=post_id,
        post_url=f"https://www.instagram.com/reel/{post_id}/",
        video_url=url,
        **kw,  # type: ignore[arg-type]
    )


def _row(post_id: str = "DSCR1", **kw: object) -> AnalysisRecord:
    values: dict[str, object] = {
        "id": uuid4(),
        "network": "instagram",
        "post_id": post_id,
        "analysis_version": ANALYSIS_VERSION,
        "status": STATUS_FAILED,
        "post_url": f"https://www.instagram.com/reel/{post_id}/",
        "created_at": NOW - timedelta(days=2),
        "attempts": 1,
        "error_code": "source_expired",
        "wanted_at": NOW - timedelta(days=2),
        "pending_video_url": EXPIRED,
        "finished_at": NOW - timedelta(days=2),
        "stage": "downloading",
    }
    values.update(kw)
    return AnalysisRecord(**values)  # type: ignore[arg-type]


def _fill_quota(store: InMemoryAnalysisStore, n: int) -> None:
    for i in range(n):
        store.put(_row(f"DFILL{i}", status=STATUS_QUEUED, error_code=None, wanted_at=NOW))


def _ask(store: InMemoryAnalysisStore, source: ReelSource | None = None, cap: int = 50):
    return request_analysis(
        TENANT, source or _source(), store=store, clock=lambda: NOW, daily_limit=cap
    )


# -- criterion 1: a failed `source_expired` row goes back to the queue ---------------------


def test_an_expired_row_is_requeued_with_the_fresh_url() -> None:
    store = InMemoryAnalysisStore()
    failed = _row()
    store.put(failed)
    ref = _ask(store)
    assert (ref.id, ref.status) == (failed.id, STATUS_QUEUED)
    row = store.get(failed.id)
    assert row is not None and row.status == STATUS_QUEUED
    assert row.pending_video_url == FRESH and row.wanted_at == NOW
    assert row.error_code is None and row.finished_at is None and row.stage is None
    assert len(store.rows()) == 1


def test_a_full_quota_refuses_the_requeue_and_writes_nothing() -> None:
    store = InMemoryAnalysisStore()
    failed = _row()
    store.put(failed)
    _fill_quota(store, 2)
    ref = _ask(store, cap=2)
    assert (ref.id, ref.status) == (None, STATUS_DAILY_LIMIT)
    assert store.get(failed.id) == failed


def test_a_row_already_counted_today_does_not_count_twice() -> None:
    store = InMemoryAnalysisStore()
    failed = _row(wanted_at=NOW - timedelta(hours=1))
    store.put(failed)
    _fill_quota(store, 1)
    ref = _ask(store, cap=2)  # 2 asked today, this row one of them: still room
    assert (ref.id, ref.status) == (failed.id, STATUS_QUEUED)


def test_a_row_out_of_attempts_is_not_requeued() -> None:
    store = InMemoryAnalysisStore()
    failed = _row(attempts=3)
    store.put(failed)
    ref = _ask(store)
    assert (ref.id, ref.status) == (failed.id, STATUS_FAILED)
    assert store.get(failed.id) == failed


# -- criterion 3: no usable URL, nothing changes -------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        _source(url=""),
        _source(url=EXPIRED),
        _source(video_url_at=NOW - timedelta(hours=21)),
        _source(url="https://evil.example.com/clip.mp4"),
    ],
)
def test_without_a_usable_url_the_expired_row_stays_failed(source: ReelSource) -> None:
    store = InMemoryAnalysisStore()
    failed = _row()
    store.put(failed)
    ref = _ask(store, source)
    assert (ref.id, ref.status) == (failed.id, STATUS_FAILED)
    assert store.get(failed.id) == failed


# -- criterion 4: other failures are never retried by the screen ---------------------------


@pytest.mark.parametrize(
    "code", ["source_unavailable", "source_too_large", "source_unreadable", "model_failed"]
)
def test_other_failures_are_returned_as_they_are(code: str) -> None:
    store = InMemoryAnalysisStore()
    failed = _row(error_code=code)
    store.put(failed)
    ref = _ask(store)
    assert (ref.id, ref.status) == (failed.id, STATUS_FAILED)
    assert store.get(failed.id) == failed


def test_a_failed_row_with_a_stored_source_is_not_requeued() -> None:
    store = InMemoryAnalysisStore()
    failed = _row(source_key="public/reel-analyses/instagram/DSCR1/x/source/source.mp4")
    store.put(failed)
    assert _ask(store).status == STATUS_FAILED
    assert store.get(failed.id) == failed


# -- criterion 2: a queued row's stale URL is replaced ---------------------------------------


@pytest.mark.parametrize("pending", [EXPIRED, None])
def test_a_queued_row_with_a_stale_or_missing_url_takes_the_fresh_one(
    pending: str | None,
) -> None:
    store = InMemoryAnalysisStore()
    queued = _row(
        status=STATUS_QUEUED,
        error_code=None,
        finished_at=None,
        stage=None,
        wanted_at=None,
        pending_video_url=pending,
    )
    store.put(queued)
    ref = _ask(store)
    assert (ref.id, ref.status) == (queued.id, STATUS_QUEUED)
    row = store.get(queued.id)
    assert row is not None and row.pending_video_url == FRESH and row.wanted_at == NOW


def test_a_queued_row_with_an_old_unsigned_url_takes_the_fresh_one() -> None:
    """No signed expiry: the row's age (> 20 h) is what makes it stale."""
    store = InMemoryAnalysisStore()
    queued = _row(status=STATUS_QUEUED, error_code=None, finished_at=None, pending_video_url=CDN)
    store.put(queued)
    assert _ask(store).status == STATUS_QUEUED
    assert store.get(queued.id).pending_video_url == FRESH  # type: ignore[union-attr]


def test_a_queued_row_with_a_still_fresh_url_keeps_it() -> None:
    store = InMemoryAnalysisStore()
    other = CDN + "&other=1"
    queued = _row(
        status=STATUS_QUEUED,
        error_code=None,
        finished_at=None,
        created_at=NOW - timedelta(hours=1),
        wanted_at=NOW - timedelta(hours=1),
        pending_video_url=other,
    )
    store.put(queued)
    assert _ask(store).status == STATUS_QUEUED
    assert store.get(queued.id) == queued


def test_a_running_row_is_never_touched() -> None:
    store = InMemoryAnalysisStore()
    running = _row(
        status=STATUS_RUNNING,
        error_code=None,
        finished_at=None,
        lease_token=uuid4(),
        lease_until=NOW + timedelta(minutes=1),
    )
    store.put(running)
    ref = _ask(store)
    assert (ref.id, ref.status) == (running.id, STATUS_RUNNING)
    assert store.get(running.id) == running


def test_a_full_quota_leaves_a_queued_row_as_today() -> None:
    store = InMemoryAnalysisStore()
    queued = _row(status=STATUS_QUEUED, error_code=None, finished_at=None, wanted_at=None)
    store.put(queued)
    _fill_quota(store, 1)
    ref = _ask(store, cap=1)
    assert (ref.id, ref.status) == (queued.id, STATUS_QUEUED)
    row = store.get(queued.id)
    # As before m-24984404: it only joins the on-demand lane; its URL is not swapped.
    assert row is not None and row.pending_video_url == EXPIRED and row.wanted_at == NOW


# -- the store's step ----------------------------------------------------------------------


def test_offer_url_is_a_compare_and_swap_on_the_pending_url() -> None:
    store = InMemoryAnalysisStore()
    queued = _row(status=STATUS_QUEUED, error_code=None, finished_at=None)
    store.put(queued)
    quota = (NOW - timedelta(hours=24), 50)

    def offer(expected: str | None) -> str:
        return store.offer_url(
            TENANT,
            queued.id,
            video_url=FRESH,
            expected=expected,
            wanted_at=NOW,
            quota=quota,
        )

    assert offer(CDN + "&someone-else=1") == OFFER_UNCHANGED  # a run wrote in between
    assert store.get(queued.id) == queued
    assert offer(EXPIRED) == OFFER_REPLACED
    assert offer(FRESH) == OFFER_UNCHANGED  # already the same URL


def test_offer_url_answers_its_words() -> None:
    store = InMemoryAnalysisStore()
    failed = _row()
    store.put(failed)
    full = (NOW - timedelta(hours=24), 0)
    kw = {"video_url": FRESH, "expected": EXPIRED, "wanted_at": NOW}
    assert store.offer_url(TENANT, failed.id, quota=full, **kw) == OFFER_DAILY_LIMIT
    assert store.offer_url(TENANT, uuid4(), quota=full, **kw) == OFFER_UNCHANGED
    room = (NOW - timedelta(hours=24), 50)
    assert store.offer_url(TENANT, failed.id, quota=room, **kw) == OFFER_REQUEUED


def test_the_worker_judges_a_handed_over_url_from_the_hand_over() -> None:
    created = NOW - timedelta(days=3)
    assert pending_url_read_at(_row(created_at=created, wanted_at=None)) == created
    # `wanted_at` alone (mark_wanted) never makes an old URL look fresh.
    assert pending_url_read_at(_row(created_at=created, wanted_at=NOW)) == created
    handed = _row(created_at=created, wanted_at=NOW, pending_url_at=NOW)
    assert pending_url_read_at(handed) == NOW


def test_an_offer_records_when_the_url_was_handed_over() -> None:
    store = InMemoryAnalysisStore()
    failed = _row()
    store.put(failed)
    _ask(store)
    assert store.get(failed.id).pending_url_at == NOW  # type: ignore[union-attr]


def test_the_sql_function_speaks_the_same_words_and_takes_the_quota_lock() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert f"pg_advisory_xact_lock({QUOTA_LOCK_KEY})" in sql
    # The limits are fixed in SQL, and they are the store's.
    assert f"r.attempts < {MAX_ATTEMPTS} AND r.model_calls < {MAX_MODEL_CALLS}" in sql
    for word in (OFFER_REQUEUED, OFFER_REPLACED, OFFER_DAILY_LIMIT, OFFER_UNCHANGED):
        assert f"'{word}'" in sql
    assert "SECURITY DEFINER" in sql and "TO qualify_app" in sql

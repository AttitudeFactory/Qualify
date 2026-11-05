"""The run's lifecycle under the `reels-worker` (`reel_runs` + `reel_store`, ADR 42 R8,
m-24854855), offline over `MemoryReelRunStore`: the vendor and Claude are fakes that
count their calls (nothing reaches ScrapeCreators or Anthropic).

Pins the architect's R8 decisions: the claim counts `attempts` and «Intentar de nuevo»
resets them; `progress` and `finish` write only under the claim that set `started_at`
(fencing); `RunInterrupted` (the worker's SIGTERM) puts the run back in the queue, frees
the account lock and keeps the account's status; `mark_opened` writes only forward, at
most once an hour, and never raises; `ensure_first_run` queues this week's weekly run
(the LOCAL Monday) only for a brand with no run, a brief and accounts — and never pays.
Postgres is `test_reels_worker_db.py`."""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from qualify_api.claude_tools import CallStats
from qualify_api.referentes import (
    MemoryReferentesRepository,
    NewDiscoveredAccount,
    NewDiscoveryPhase,
    reels,
    reels_ai,
)
from qualify_api.referentes import ai as review_ai
from qualify_api.referentes import reel_runs as rr
from qualify_api.referentes.reel_queue import MemoryReelQueue
from qualify_api.referentes.reel_store import (
    ACCOUNT_OK,
    STATUS_CHECK_FAILED,
    STATUS_OK,
    STATUS_QUEUED,
    STATUS_RUNNING,
    MemoryReelRunStore,
    NewIdea,
)
from qualify_api.referentes.reel_worker import ReelsWorker
from qualify_api.referentes.reels_ai import ReelReview, ReelToReview
from qualify_api.vendors import scrapecreators as sc

TENANT = UUID("a0000000-0000-4000-8000-0000000000a1")
OTHER = UUID("b0000000-0000-4000-8000-0000000000b2")
BRIEF = review_ai.BrandBrief(handle="burgerco", rubro=("hamburguesería",))
#: Wednesday 2026-11-11 15:00 UTC = 10:00 in Bogotá: that week's Monday is 2026-11-09.
WEDNESDAY = datetime(2026, 11, 11, 15, 0, tzinfo=UTC)


def _epoch(moment: datetime = WEDNESDAY) -> float:
    return moment.timestamp()


def _brand_with_a_referente(repo: MemoryReferentesRepository, tenant: UUID) -> UUID:
    brand = uuid4()
    repo.add_brand(tenant_id=tenant, brand_id=brand)
    repo.save_phase(
        NewDiscoveryPhase(
            tenant_id=tenant,
            brand_id=brand,
            phase_key="sector",
            algorithm_version=1,
            seed_signature="s",
            seed={"handle": "burgerco", "terms": ["hamburguesería"], "hashtags": []},
            title="Sector",
            accounts=(
                NewDiscoveredAccount(network="instagram", handle="foodie", card={"kind": "c"}),
            ),
        )
    )
    repo.set_label(
        tenant_id=tenant,
        brand_id=brand,
        network="instagram",
        handle="foodie",
        label="referente",
        labeled_by=None,
    )
    return brand


def _feed(handle: str, n: int = 3) -> list[dict[str, Any]]:
    """`n` recent Instagram reels of `handle`, as the vendor's list read returns them."""
    return [
        {
            "id": f"{handle}{k}",
            "network": "instagram",
            "handle": handle,
            "url": f"https://www.instagram.com/reel/{handle}{k}/",
            "caption": f"la hamburguesa número {k}",
            "takenAt": _epoch(WEDNESDAY - timedelta(days=k + 1)),
            "views": 1000 * (n - k),
            "likes": 10,
            "comments": 1,
            "shares": None,
            "saves": None,
            "seconds": 12,
            "sound": "Audio original",
            "video": f"https://scontent.cdninstagram.com/{handle}{k}.mp4",
        }
        for k in range(n)
    ]


def _answers(batch: list[ReelToReview]) -> tuple[list[ReelReview], CallStats]:
    return (
        [
            ReelReview(
                id=r.id,
                fits=True,
                reason="ok",
                format="receta",
                hook="pregunta",
                affinity="producto",
            )
            for r in batch
        ],
        CallStats(reels_ai.REVIEW_MODEL, None, 1000, 100),
    )


def _queued(store: MemoryReelRunStore, trigger: str = "manual") -> Any:
    return rr.enqueue_run(TENANT, uuid4(), trigger, store=store, clock=_epoch)


# --------------------------------------------------------------------------------------
# attempts and the fence
# --------------------------------------------------------------------------------------


def test_the_claim_counts_attempts_and_a_retry_resets_them() -> None:
    store = MemoryReelRunStore()
    run = _queued(store)
    assert run.attempts == 0
    claimed = store.claim(TENANT, run.id, now=WEDNESDAY)
    assert claimed is not None and claimed.attempts == 1
    assert store.claim(TENANT, run.id, now=WEDNESDAY) is None  # only a queued run
    assert store.abandon(TENANT, run.id, started_at=WEDNESDAY, now=WEDNESDAY)
    retried = rr.enqueue_run(TENANT, run.brand_id, "manual", store=store, clock=_epoch, retry=True)
    assert retried.status == STATUS_QUEUED and retried.attempts == 0


def test_progress_and_finish_write_only_under_their_own_claim() -> None:
    store = MemoryReelRunStore()
    run = _queued(store)
    first = store.claim(TENANT, run.id, now=WEDNESDAY)
    assert first is not None and first.started_at == WEDNESDAY
    # the worker recovered it (its process looked dead) and another attempt took it
    assert store.release(TENANT, run.id, started_at=WEDNESDAY)
    later = WEDNESDAY + timedelta(minutes=31)
    assert store.claim(TENANT, run.id, now=later) is not None
    # the first process wakes up: none of its writes land
    assert not store.progress(
        TENANT, run.id, accounts_total=5, accounts_done=5, started_at=WEDNESDAY
    )
    assert not store.finish(
        TENANT,
        run.id,
        status=STATUS_OK,
        now=later,
        credits=40,
        cost_usd=Decimal("1"),
        brief_hash="h",
        started_at=WEDNESDAY,
    )
    record = store.runs[run.id]
    assert (record.status, record.accounts_done, record.credits) == (STATUS_RUNNING, 0, 0)
    # the current attempt's writes do
    assert store.progress(TENANT, run.id, accounts_total=2, accounts_done=1, started_at=later)
    assert store.finish(
        TENANT,
        run.id,
        status=STATUS_OK,
        now=later,
        credits=3,
        cost_usd=Decimal("0"),
        brief_hash=None,
        started_at=later,
    )
    assert store.runs[run.id].status == STATUS_OK
    # another tenant never reaches the run
    assert not store.release(OTHER, run.id, started_at=later)


def test_a_run_recovered_meanwhile_is_not_recorded_by_the_old_process() -> None:
    store = MemoryReelRunStore()
    run = _queued(store)

    def brief(tenant_id: UUID, brand_id: UUID) -> None:
        # while this attempt works, the worker recovers the run and starts it again
        assert store.release(TENANT, run.id, started_at=WEDNESDAY)
        assert store.claim(TENANT, run.id, now=WEDNESDAY + timedelta(minutes=31)) is not None
        return None

    outcome = rr.run(TENANT, run.id, store=store, brief=brief, clock=_epoch)
    assert outcome.status == STATUS_CHECK_FAILED and outcome.recorded is False
    record = store.runs[run.id]
    assert record.status == STATUS_RUNNING and record.attempts == 2  # the new attempt's


# --------------------------------------------------------------------------------------
# the stop: RunInterrupted
# --------------------------------------------------------------------------------------


def test_an_interrupted_read_releases_the_run_and_the_account_and_keeps_its_status() -> None:
    store, repo = MemoryReelRunStore(), MemoryReferentesRepository()
    brand = _brand_with_a_referente(repo, TENANT)
    run = rr.enqueue_run(TENANT, brand, "manual", store=store, clock=_epoch)
    reads: list[str] = []

    def fetch(network: str, handle: str, **_: Any) -> list[dict[str, Any]]:
        reads.append(handle)
        raise rr.RunInterrupted("signal 15")  # the SIGTERM lands during the vendor read

    with pytest.raises(rr.RunInterrupted):
        rr.run(
            TENANT,
            run.id,
            store=store,
            repository=repo,
            brief=lambda tenant, b: BRIEF,
            api_key="k",
            fetch=fetch,
            clock=_epoch,
            sleep=lambda seconds: None,
        )
    assert reads == ["foodie"]
    record = store.runs[run.id]
    assert record.status == STATUS_QUEUED and record.started_at is None
    assert record.attempts == 1 and record.accounts_done == 0
    account = store.accounts[("instagram", "foodie")]
    assert account.refresh_lock_until is None  # the next run does not wait 10 min
    assert account.status == ACCOUNT_OK and account.page1_at is None  # nothing faked


def test_a_stop_during_the_claude_check_releases_at_once_and_keeps_the_answer() -> None:
    """Review of R8: a SIGTERM while Claude answers. The run goes back to the queue AT
    ONCE (not after the call in flight, which could outlive the grace period), and the
    answer in flight — already paid — is stored when it arrives, so the next attempt
    reuses it instead of paying it again. A real signal, as the worker's handler sees it."""
    released = threading.Event()

    class Watching(MemoryReelRunStore):
        def release(self, *args: Any, **kwargs: Any) -> bool:
            done = super().release(*args, **kwargs)
            released.set()
            return done

    store, repo = Watching(), MemoryReferentesRepository()
    brand = _brand_with_a_referente(repo, TENANT)
    run = rr.enqueue_run(TENANT, brand, "manual", store=store, clock=_epoch)
    batches: list[int] = []
    released_first: list[bool] = []

    main = threading.main_thread()

    def waiting_for_the_answer() -> bool:
        frame = sys._current_frames().get(main.ident or 0)
        names = set()
        while frame is not None:
            names.add(frame.f_code.co_name)
            frame = frame.f_back
        return "result_iterator" in names

    def review(brief: Any, batch: list[ReelToReview], **_: Any) -> Any:
        batches.append(len(batch))
        # the stop must land while the run WAITS for this answer (not while the pool is
        # still starting its thread), the case where waiting for the call would hang
        deadline = time.monotonic() + 5
        while not waiting_for_the_answer() and time.monotonic() < deadline:
            time.sleep(0.005)
        os.kill(os.getpid(), signal.SIGTERM)  # the deploy's stop lands while Claude answers
        released_first.append(released.wait(5))  # the run is queued before this answer
        return _answers(batch)

    def stop(signum: int, frame: Any) -> None:
        raise rr.RunInterrupted(f"signal {signum}")  # what the worker's handler raises

    common: dict[str, Any] = {
        "store": store,
        "repository": repo,
        "brief": lambda tenant, b: BRIEF,
        "api_key": "k",
        "fetch": lambda network, handle, **_: _feed(handle),
        "transcribe_fetch": lambda reel, client: "dicen hamburguesa",
        "clock": _epoch,
        "sleep": lambda seconds: None,
    }
    previous = signal.signal(signal.SIGTERM, stop)
    try:
        with pytest.raises(rr.RunInterrupted):
            rr.run(TENANT, run.id, review=review, **common)
    finally:
        signal.signal(signal.SIGTERM, previous)
    record = store.runs[run.id]
    assert record.status == STATUS_QUEUED and record.started_at is None
    deadline = time.monotonic() + 5  # the answer in flight lands on its own thread
    while len(store.verdict_rows) < sum(batches) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert released_first == [True] and len(store.verdict_rows) == sum(batches) > 0

    asked: list[int] = []

    def not_again(brief: Any, batch: list[ReelToReview], **_: Any) -> Any:
        asked.append(len(batch))
        return _answers(batch)

    again = rr.run(TENANT, run.id, review=not_again, **common)
    assert again.status == STATUS_OK and asked == []  # nothing paid to Claude twice
    assert again.verdicts_reused == sum(batches) and again.ideas == sum(batches)


def test_ideas_replace_an_earlier_attempts_and_are_fenced() -> None:
    """Review of R8: the ideas of an attempt that died before `finish` must not mix with
    the next attempt's (duplicate ranks), and a recovered attempt cannot write them."""
    store = MemoryReelRunStore()
    run, other = _queued(store), _queued(store)
    assert store.claim(TENANT, other.id, now=WEDNESDAY) is not None
    kept = [NewIdea("instagram", "X", 1, 7, None)]
    assert store.save_ideas(TENANT, other.brand_id, other.id, kept, started_at=WEDNESDAY)

    assert store.claim(TENANT, run.id, now=WEDNESDAY) is not None
    first = [NewIdea("instagram", "A", 1, 7, None), NewIdea("instagram", "B", 2, 30, None)]
    assert store.save_ideas(TENANT, run.brand_id, run.id, first, started_at=WEDNESDAY)
    # the attempt dies before `finish`; the worker recovers the run and starts it again
    assert store.release(TENANT, run.id, started_at=WEDNESDAY)
    later = WEDNESDAY + timedelta(minutes=31)
    assert store.claim(TENANT, run.id, now=later) is not None
    assert not store.save_ideas(TENANT, run.brand_id, run.id, first, started_at=WEDNESDAY)
    second = [NewIdea("instagram", "C", 1, 7, None)]
    assert store.save_ideas(TENANT, run.brand_id, run.id, second, started_at=later)

    def ideas_of(run_id: UUID) -> list[tuple[str, int]]:
        return [(i.reel_id, i.rank) for _, _, r, i, _ in store.idea_rows if r == run_id]

    assert ideas_of(run.id) == [("C", 1)]  # no leftover, no duplicate rank
    assert ideas_of(other.id) == [("X", 1)]  # another run's ideas untouched


def test_a_failed_check_logs_its_cause_not_the_owners_sentence(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Review of R8: `check_failure_reason` is the owner's one plain sentence since R7;
    the log needs the cause (`check_failure_cause`)."""

    class RateLimited(Exception):
        status_code = 429

    store, repo = MemoryReelRunStore(), MemoryReferentesRepository()
    brand = _brand_with_a_referente(repo, TENANT)
    run = rr.enqueue_run(TENANT, brand, "manual", store=store, clock=_epoch)

    def review(*_: Any, **__: Any) -> Any:
        raise RateLimited("slow down")

    caplog.set_level(logging.WARNING)
    outcome = rr.run(
        TENANT,
        run.id,
        store=store,
        repository=repo,
        brief=lambda tenant, b: BRIEF,
        api_key="k",
        fetch=lambda network, handle, **_: _feed(handle),
        transcribe_fetch=lambda reel, client: "dicen hamburguesa",
        review=review,
        clock=_epoch,
        sleep=lambda seconds: None,
    )
    assert outcome.status == STATUS_CHECK_FAILED
    assert reels.check_failure_cause(RateLimited()) in caplog.text
    assert reels.check_failure_reason(RateLimited()) not in caplog.text


# --------------------------------------------------------------------------------------
# a failed check retries by itself (founder, 2026-11-04)
# --------------------------------------------------------------------------------------


def _no_vendor(*_: Any, **__: Any) -> Any:
    raise AssertionError("the vendor must never be called here")


class Moment:
    def __init__(self, now: datetime = WEDNESDAY) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def epoch(self) -> float:
        return self.now.timestamp()


def _retrying_worker(
    store: MemoryReelRunStore, clock: Moment, run: Any = None, **kwargs: Any
) -> ReelsWorker:
    def no_brief(tenant_id: UUID, run_id: UUID) -> rr.RunOutcome:
        return rr.run(
            tenant_id,
            run_id,
            store=store,
            brief=lambda tenant, brand: None,  # its check fails, before any paid call
            fetch=_no_vendor,
            transcribe_fetch=_no_vendor,
            review=_no_vendor,
            clock=clock.epoch,
        )

    return ReelsWorker(
        MemoryReelQueue(store),
        store,
        run=run or no_brief,
        ready=lambda tenant, brand: True,
        clock=clock,
        **kwargs,
    )


def test_a_failed_check_is_queued_again_fifteen_minutes_after_it_ended(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, clock = MemoryReelRunStore(), Moment()
    monkeypatch.setattr(rr, "time", SimpleNamespace(time=clock.epoch))  # view()'s clock
    run = _queued(store)
    worker = _retrying_worker(store, clock)
    worker.pass_once()
    failed = store.runs[run.id]
    assert (failed.status, failed.attempts, failed.finished_at) == (
        STATUS_CHECK_FAILED,
        1,
        WEDNESDAY,
    )
    retry_at = rr.view(TENANT, run.brand_id, store=store).next_retry_at
    assert retry_at == WEDNESDAY + timedelta(minutes=15)

    clock.now = WEDNESDAY + timedelta(minutes=14)
    assert worker.pass_once().retried == []  # not yet
    assert store.runs[run.id].attempts == 1

    clock.now = WEDNESDAY + timedelta(minutes=15)
    report = worker.pass_once()
    assert [r.run_id for r in report.retried] == [run.id]
    assert [o.run_id for o in report.outcomes] == [run.id]  # queued and run in the pass
    again = store.runs[run.id]
    assert (again.status, again.attempts, again.queued_at) == (
        STATUS_CHECK_FAILED,
        2,
        run.queued_at,
    )


def test_after_the_third_failed_check_no_retry_until_monday() -> None:
    store, clock = MemoryReelRunStore(), Moment()
    run = _queued(store)
    worker = _retrying_worker(store, clock)
    for minutes in (0, 15, 30, 45, 60, 75):
        clock.now = WEDNESDAY + timedelta(minutes=minutes)
        worker.pass_once()
    record = store.runs[run.id]
    assert (record.status, record.attempts) == (STATUS_CHECK_FAILED, rr.MAX_ATTEMPTS)
    assert record.finished_at == WEDNESDAY + timedelta(minutes=30)  # the third failure
    assert rr.view(TENANT, run.brand_id, store=store).next_retry_at is None


def _check_failed(store: MemoryReelRunStore, brand: UUID, at: datetime) -> Any:
    run = rr.enqueue_run(TENANT, brand, "manual", store=store, clock=at.timestamp)
    assert store.claim(TENANT, run.id, now=at) is not None
    assert store.finish(
        TENANT,
        run.id,
        status=STATUS_CHECK_FAILED,
        now=at,
        credits=0,
        cost_usd=Decimal("0"),
        brief_hash=None,
        started_at=at,
    )
    return run


def test_only_the_brands_latest_run_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """N1: a newer run of the brand (here the Monday one, queued after the failure)
    supersedes the failed check — neither the worker nor the screen retries it."""
    store, clock = MemoryReelRunStore(), Moment()
    monkeypatch.setattr(rr, "time", SimpleNamespace(time=clock.epoch))
    brand = uuid4()
    failed = _check_failed(store, brand, WEDNESDAY)
    newer = rr.enqueue_run(
        TENANT,
        brand,
        "weekly",
        run_date=date(2026, 11, 16),
        store=store,
        clock=(WEDNESDAY + timedelta(minutes=1)).timestamp,
    )
    clock.now = WEDNESDAY + timedelta(minutes=20)
    assert not store.retry_check(
        TENANT,
        failed.id,
        finished_before=clock.now - rr.CHECK_RETRY_AFTER,
        finished_after=clock.now - rr.CHECK_RETRY_WITHIN,
        max_attempts=rr.MAX_ATTEMPTS,
    )
    view = rr.view(TENANT, brand, store=store)
    assert view.latest is not None and view.latest.id == newer.id
    assert view.next_retry_at is None
    assert store.runs[failed.id].status == STATUS_CHECK_FAILED


def test_a_check_that_failed_a_day_ago_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """N1: a worker that was down past the retries never re-runs an old check on today's
    data; the screen stops promising the retry at the same moment."""
    store, clock = MemoryReelRunStore(), Moment()
    monkeypatch.setattr(rr, "time", SimpleNamespace(time=clock.epoch))
    brand = uuid4()
    failed = _check_failed(store, brand, WEDNESDAY)
    worker = _retrying_worker(store, clock)

    clock.now = WEDNESDAY + rr.CHECK_RETRY_WITHIN
    assert rr.view(TENANT, brand, store=store).next_retry_at is None
    assert worker.pass_once().retried == []
    assert store.runs[failed.id].status == STATUS_CHECK_FAILED

    clock.now = WEDNESDAY + rr.CHECK_RETRY_WITHIN - timedelta(minutes=1)
    assert rr.view(TENANT, brand, store=store).next_retry_at == (WEDNESDAY + rr.CHECK_RETRY_AFTER)
    report = _retrying_worker(store, clock).pass_once()
    assert [r.run_id for r in report.retried] == [failed.id]


def test_the_door_lists_only_failed_checks_started_in_the_window() -> None:
    store = MemoryReelRunStore()
    old = _check_failed(store, uuid4(), WEDNESDAY - timedelta(days=3))
    recent = _check_failed(store, uuid4(), WEDNESDAY)
    queue = MemoryReelQueue(store)
    listed = queue.failed_checks(max_attempts=3, started_after=WEDNESDAY - timedelta(hours=25))
    assert [r.run_id for r in listed] == [recent.id] and old.id not in {r.run_id for r in listed}


def test_view_schedules_no_retry_for_a_run_that_did_not_fail_its_check() -> None:
    store = MemoryReelRunStore()
    run = _queued(store)
    assert rr.view(TENANT, run.brand_id, store=store).next_retry_at is None  # queued
    assert store.claim(TENANT, run.id, now=WEDNESDAY) is not None
    assert store.finish(
        TENANT,
        run.id,
        status="budget_stopped",
        now=WEDNESDAY,
        credits=0,
        cost_usd=Decimal("0"),
        brief_hash=None,
        started_at=WEDNESDAY,
    )
    assert rr.view(TENANT, run.brand_id, store=store).next_retry_at is None


def test_the_first_run_of_option_a_is_retried_too(monkeypatch: pytest.MonkeyPatch) -> None:
    store, clock = MemoryReelRunStore(), Moment()
    store.timezones[TENANT] = "America/Bogota"
    brand = uuid4()
    monkeypatch.setattr(rr, "time", SimpleNamespace(time=clock.epoch))
    monkeypatch.setattr(rr.brief_builder, "brand_brief", lambda tenant, b, **_: BRIEF)
    monkeypatch.setattr(rr.reels, "brand_referentes", lambda tenant, b, **_: ["@foodie"])
    monkeypatch.setattr(rr.reels, "_env_key", lambda: None)  # no Anthropic key: check fails
    assert rr.ensure_first_run(TENANT, brand, store=store) is True
    [first] = store.runs.values()

    def no_key(tenant_id: UUID, run_id: UUID) -> rr.RunOutcome:
        return rr.run(
            tenant_id,
            run_id,
            store=store,
            api_key=None,
            fetch=_no_vendor,
            transcribe_fetch=_no_vendor,
            review=_no_vendor,
            clock=clock.epoch,
        )

    worker = _retrying_worker(store, clock, run=no_key)
    worker.pass_once()
    assert store.runs[first.id].status == STATUS_CHECK_FAILED
    clock.now += timedelta(minutes=15)
    assert [r.run_id for r in worker.pass_once().retried] == [first.id]
    assert (store.runs[first.id].trigger, store.runs[first.id].attempts) == ("weekly", 2)


def test_a_retry_that_fails_its_check_again_pays_no_vendor_call() -> None:
    """Claude is down: the first attempt read the account and paid the transcripts, then
    failed its check. The retry 15 min later re-reads nothing and pays no transcript: it
    only asks Claude again (down again)."""
    store, repo, clock = MemoryReelRunStore(), MemoryReferentesRepository(), Moment()
    brand = _brand_with_a_referente(repo, TENANT)
    run = rr.enqueue_run(TENANT, brand, "manual", store=store, clock=clock.epoch)
    lists: list[str] = []
    transcripts: list[str] = []
    asked: list[int] = []

    def fetch(network: str, handle: str, **_: Any) -> list[dict[str, Any]]:
        lists.append(handle)
        return _feed(handle)

    def transcribe(reel: dict[str, Any], client: Any) -> str:
        transcripts.append(reel["id"])
        return "dicen hamburguesa"

    def claude_down(brief: Any, batch: list[ReelToReview], **_: Any) -> Any:
        asked.append(len(batch))
        raise RuntimeError("anthropic is down")

    def paid_run(tenant_id: UUID, run_id: UUID) -> rr.RunOutcome:
        return rr.run(
            tenant_id,
            run_id,
            store=store,
            repository=repo,
            brief=lambda tenant, b: BRIEF,
            api_key="k",
            fetch=fetch,
            transcribe_fetch=transcribe,
            review=claude_down,
            clock=clock.epoch,
            sleep=lambda seconds: None,
        )

    worker = _retrying_worker(store, clock, run=paid_run)
    worker.pass_once()
    assert store.runs[run.id].status == STATUS_CHECK_FAILED
    paid_lists, paid_transcripts = list(lists), list(transcripts)
    assert paid_lists == ["foodie"] and paid_transcripts and len(asked) == 1

    clock.now += timedelta(minutes=15)
    report = worker.pass_once()
    assert [r.run_id for r in report.retried] == [run.id]
    assert store.runs[run.id].status == STATUS_CHECK_FAILED  # Claude still down
    assert lists == paid_lists and transcripts == paid_transcripts  # nothing paid again
    assert len(asked) == 2  # only the review was tried again


def test_run_interrupted_is_not_an_exception_run_swallows() -> None:
    assert issubclass(rr.RunInterrupted, BaseException)
    assert not issubclass(rr.RunInterrupted, Exception)


def test_a_gate_refusal_still_keeps_the_account_status() -> None:
    """R4's behaviour, unchanged by the R8 refactor of `_refresh_account`."""
    store, repo = MemoryReelRunStore(), MemoryReferentesRepository()
    brand = _brand_with_a_referente(repo, TENANT)
    run = rr.enqueue_run(TENANT, brand, "manual", store=store, clock=_epoch)

    def refused(*_: Any, **__: Any) -> Any:
        raise sc.ScrapeCreatorsBlocked("floor", reason="below_floor")

    outcome = rr.run(
        TENANT,
        run.id,
        store=store,
        repository=repo,
        brief=lambda tenant, b: BRIEF,
        api_key="k",
        fetch=refused,
        clock=_epoch,
        sleep=lambda seconds: None,
    )
    assert outcome.status == "budget_stopped"
    assert store.accounts[("instagram", "foodie")].status == ACCOUNT_OK


# --------------------------------------------------------------------------------------
# mark_opened
# --------------------------------------------------------------------------------------


def test_mark_opened_writes_forward_at_most_once_an_hour(monkeypatch: pytest.MonkeyPatch) -> None:
    store, brand = MemoryReelRunStore(), uuid4()
    moment = {"now": WEDNESDAY}
    monkeypatch.setattr(rr, "time", SimpleNamespace(time=lambda: _epoch(moment["now"])))

    rr.mark_opened(TENANT, brand, store=store)
    assert store.activity[brand] == (TENANT, WEDNESDAY)
    writes = store.writes
    moment["now"] = WEDNESDAY + timedelta(minutes=59)
    rr.mark_opened(TENANT, brand, store=store)
    assert store.activity[brand] == (TENANT, WEDNESDAY) and store.writes == writes
    moment["now"] = WEDNESDAY + timedelta(hours=1)
    rr.mark_opened(TENANT, brand, store=store)
    assert store.activity[brand] == (TENANT, WEDNESDAY + timedelta(hours=1))
    moment["now"] = WEDNESDAY - timedelta(days=1)  # a clock behind: never backwards
    rr.mark_opened(TENANT, brand, store=store)
    assert store.activity[brand] == (TENANT, WEDNESDAY + timedelta(hours=1))


def test_mark_opened_never_raises(caplog: pytest.LogCaptureFixture) -> None:
    class Down(MemoryReelRunStore):
        def mark_opened(self, *args: Any, **kwargs: Any) -> None:
            raise ConnectionError("database away")

    assert rr.mark_opened(TENANT, uuid4(), store=Down()) is None
    assert "was not recorded" in caplog.text


# --------------------------------------------------------------------------------------
# ensure_first_run (option A)
# --------------------------------------------------------------------------------------


@pytest.fixture
def first_run(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A brand with a brief and one account, a tenant in Bogotá, the clock on Wednesday;
    the brief builder and the accounts are fakes of the database reads."""
    env: dict[str, Any] = {"brief": BRIEF, "accounts": ["@foodie"], "store": MemoryReelRunStore()}
    env["store"].timezones[TENANT] = "America/Bogota"
    monkeypatch.setattr(rr, "time", SimpleNamespace(time=lambda: _epoch(WEDNESDAY)))
    monkeypatch.setattr(rr.brief_builder, "brand_brief", lambda tenant, brand: env["brief"])
    monkeypatch.setattr(rr.reels, "brand_referentes", lambda tenant, brand: env["accounts"])
    return env


def test_ensure_first_run_queues_this_weeks_weekly_run_on_the_local_monday(
    first_run: dict[str, Any],
) -> None:
    store, brand = first_run["store"], uuid4()
    assert rr.ensure_first_run(TENANT, brand, store=store) is True
    [record] = store.runs.values()
    assert (record.brand_id, record.trigger, record.status) == (brand, "weekly", STATUS_QUEUED)
    assert record.run_date == date(2026, 11, 9)  # Monday, local; never a UTC "today"
    # the Monday scheduler's run for that week is the same UNIQUE row: nothing is added
    again = rr.enqueue_run(
        TENANT, brand, "weekly", run_date=date(2026, 11, 9), store=store, clock=_epoch
    )
    assert again.id == record.id and len(store.runs) == 1
    # and a second opening does nothing: the brand has a run now
    assert rr.ensure_first_run(TENANT, brand, store=store) is False and len(store.runs) == 1


def test_ensure_first_run_needs_no_run_a_brief_and_accounts(first_run: dict[str, Any]) -> None:
    store = first_run["store"]
    had_one = uuid4()
    rr.enqueue_run(TENANT, had_one, "manual", store=store, clock=_epoch)
    assert rr.ensure_first_run(TENANT, had_one, store=store) is False

    first_run["brief"] = None
    assert rr.ensure_first_run(TENANT, uuid4(), store=store) is False
    first_run["brief"], first_run["accounts"] = BRIEF, []
    assert rr.ensure_first_run(TENANT, uuid4(), store=store) is False
    assert len(store.runs) == 1  # only the manual run above


def test_ensure_first_run_never_raises(first_run: dict[str, Any]) -> None:
    store = first_run["store"]
    store.timezones.clear()  # the tenant's timezone cannot be read
    assert rr.ensure_first_run(TENANT, uuid4(), store=store) is False
    assert store.runs == {}

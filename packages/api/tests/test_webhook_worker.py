"""`python -m qualify_api.webhooks.worker` argument handling (QUA-147) — offline: the
queue and the processor are replaced, so nothing touches a database."""

from __future__ import annotations

from datetime import timedelta

import pytest

from qualify_api.webhooks import worker
from qualify_api.webhooks.repository import RETENTION, PurgeReport


class RecordingQueue:
    calls: list[tuple] = []

    def purge_expired(self, *, now, older_than, execute):
        RecordingQueue.calls.append(("expired", older_than, execute))
        return PurgeReport(events=2, deliveries=1, executed=execute)

    def purge_by_entry_id(self, *, entry_id, execute):
        RecordingQueue.calls.append(("account", entry_id, execute))
        return PurgeReport(events=0, deliveries=0, executed=execute)

    def requeue_unsupported_comments(self, *, now, execute, entry_id=None):
        RecordingQueue.calls.append(("requeue", entry_id, execute))
        return 3

    def requeue_unsupported_postbacks(self, *, now, execute, entry_id=None):
        RecordingQueue.calls.append(("requeue-postbacks", entry_id, execute))
        return 4


@pytest.fixture(autouse=True)
def fake_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    RecordingQueue.calls = []
    monkeypatch.setattr(worker, "WebhookQueue", RecordingQueue)
    monkeypatch.setattr(worker, "_load_dotenv", lambda: None)


def test_purge_is_a_dry_run_by_default(capsys) -> None:
    assert worker.main(["--purge"]) == 0
    assert RecordingQueue.calls == [("expired", RETENTION, False)]
    assert "would delete (dry run)" in capsys.readouterr().out


def test_purge_execute_deletes(capsys) -> None:
    assert worker.main(["--purge", "--execute"]) == 0
    assert RecordingQueue.calls == [("expired", RETENTION, True)]
    assert "deleted events=2 deliveries=1" in capsys.readouterr().out


def test_account_purge_is_a_dry_run_by_default() -> None:
    assert worker.main(["--purge-account", "ig-1"]) == 0
    assert RecordingQueue.calls == [("account", "ig-1", False)]


def test_execute_without_a_purge_is_refused() -> None:
    assert worker.main(["--once", "--execute"]) == 2
    assert worker.main(["--execute"]) == 2
    assert RecordingQueue.calls == []


def test_modes_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        worker.main(["--once", "--purge"])
    with pytest.raises(SystemExit):
        worker.main(["--requeue-comments", "--purge"])


def test_requeue_comments_is_a_dry_run_by_default(capsys) -> None:
    assert worker.main(["--requeue-comments"]) == 0
    assert RecordingQueue.calls == [("requeue", None, False)]
    assert "would requeue (dry run) events=3" in capsys.readouterr().out


def test_requeue_comments_execute_for_one_account(capsys) -> None:
    assert worker.main(["--requeue-comments", "--account", "ig-1", "--execute"]) == 0
    assert RecordingQueue.calls == [("requeue", "ig-1", True)]
    assert "requeued events=3" in capsys.readouterr().out


def test_requeue_postbacks_is_a_dry_run_by_default(capsys) -> None:
    assert worker.main(["--requeue-postbacks"]) == 0
    assert RecordingQueue.calls == [("requeue-postbacks", None, False)]
    assert "instagram postbacks: would requeue (dry run) events=4" in capsys.readouterr().out


def test_requeue_postbacks_execute_for_one_account(capsys) -> None:
    assert worker.main(["--requeue-postbacks", "--account", "ig-1", "--execute"]) == 0
    assert RecordingQueue.calls == [("requeue-postbacks", "ig-1", True)]
    assert "instagram postbacks: requeued events=4" in capsys.readouterr().out


def test_the_two_requeues_are_exclusive() -> None:
    with pytest.raises(SystemExit):
        worker.main(["--requeue-postbacks", "--requeue-comments"])


def test_account_without_requeue_is_refused() -> None:
    assert worker.main(["--purge", "--account", "ig-1"]) == 2
    assert RecordingQueue.calls == []


def test_a_too_short_interval_is_refused() -> None:
    assert worker.main(["--interval", str(worker.MIN_INTERVAL_SECONDS - 1)]) == 2


def test_retention_plus_purge_cadence_stays_within_thirty_days() -> None:
    """The QUA-127 arithmetic: 29 days retention + one purge every 24 h ≤ 30 days."""
    assert RETENTION + worker.PURGE_EVERY <= timedelta(days=30)


# --- m-25017174: messages first, housekeeping on its own clocks ------------------------


class _Batches:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    async def run_once(self, *, limit: int = 100):
        self.log.append("batch")
        from qualify_api.webhooks.processor import ProcessReport

        return ProcessReport()


def _housekeeping(log: list[str], now: list[float], *, prefill: object = object()):
    async def sentiment() -> None:
        log.append("sentiment")

    async def comments() -> None:
        log.append("comments")

    async def prefill_pass(_runner) -> None:
        log.append("prefill")

    return worker._Housekeeping(
        queue=RecordingQueue(),
        prefill=prefill,  # type: ignore[arg-type]
        purge=lambda _queue: log.append("purge"),
        sentiment_sweep=sentiment,
        comment_sweep=comments,
        prefill_pass=prefill_pass,
        monotonic=lambda: now[0],
    )


async def test_the_message_batch_runs_before_the_sweeps_and_the_prefill() -> None:
    log: list[str] = []
    now = [0.0]
    await worker.run_loop(
        _Batches(log),
        _housekeeping(log, now),
        interval=5,
        limit=10,
        sleep=lambda _s: _noop(),
        monotonic=lambda: now[0],
        max_passes=1,
    )
    assert log == ["batch", "purge", "sentiment", "comments", "prefill"]


async def _noop() -> None:
    return None


async def test_a_five_second_tick_does_not_run_the_sweeps_or_the_prefill_more_often() -> None:
    log: list[str] = []
    now = [0.0]
    batches = _Batches(log)
    housekeeping = _housekeeping(log, now)

    async def advance(seconds: float) -> None:
        now[0] += 5  # one tick of the new default, whatever the computed sleep

    await worker.run_loop(
        batches,
        housekeeping,
        interval=5,
        limit=10,
        sleep=advance,
        monotonic=lambda: now[0],
        max_passes=121,  # t = 0 … 600 s
    )
    assert log.count("batch") == 121
    assert log.count("purge") == 1  # every 24 h
    assert log.count("sentiment") == log.count("comments") == 2  # t = 0 and t = 600 (10 min)
    assert log.count("prefill") == 21  # t = 0, 30, …, 600: every 30 s, as before


async def test_no_prefill_runner_means_no_prefill_pass() -> None:
    log: list[str] = []
    await _housekeeping(log, [0.0], prefill=None).run_due()
    assert "prefill" not in log


def test_the_default_interval_is_five_seconds_and_the_override_still_works(monkeypatch) -> None:
    assert worker.DEFAULT_INTERVAL_SECONDS == 5
    assert worker.build_parser().parse_args([]).interval == 5
    seen: list[int] = []

    async def fake_loop(*, interval: int, limit: int) -> None:
        seen.append(interval)

    monkeypatch.setattr(worker, "_run_loop", fake_loop)
    assert worker.main([]) == 0
    assert worker.main(["--interval", "30"]) == 0
    assert seen == [5, 30]

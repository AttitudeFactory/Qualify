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


def test_a_too_short_interval_is_refused() -> None:
    assert worker.main(["--interval", str(worker.MIN_INTERVAL_SECONDS - 1)]) == 2


def test_retention_plus_purge_cadence_stays_within_thirty_days() -> None:
    """The QUA-127 arithmetic: 29 days retention + one purge every 24 h ≤ 30 days."""
    assert RETENTION + worker.PURGE_EVERY <= timedelta(days=30)

"""Blocking mail never serializes worker maintenance; no queued task accumulation."""

from __future__ import annotations

import threading

from qualify_api.creative.worker.background import BackgroundChore
from qualify_api.creative.worker.operations import Snapshot


def test_many_observations_keep_only_one_live_daemon_and_stop_prevents_new_work():
    entered, release, stop = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def blocked():
        calls.append(True)
        entered.set()
        release.wait(3)

    chore = BackgroundChore(blocked, stop)
    try:
        assert chore.schedule()
        assert entered.wait(1)
        assert chore._thread.daemon
        for _ in range(25):
            assert not chore.schedule()
        assert calls == [True]
        stop.set()
        assert not chore.schedule()
    finally:
        release.set()
        chore._thread.join(1)
    assert not chore._thread.is_alive()
    assert not chore.schedule()


def test_background_exception_rearms_without_unhandled_error_or_payload_log(caplog):
    stop = threading.Event()
    calls = []

    def fail():
        calls.append(True)
        raise RuntimeError("recipient@example.invalid must not appear")

    chore = BackgroundChore(fail, stop)
    assert chore.schedule()
    chore._thread.join(1)
    assert chore.schedule()
    chore._thread.join(1)
    assert calls == [True, True]
    assert "RuntimeError" in caplog.text
    assert "recipient@example.invalid" not in caplog.text
    stop.set()
    assert not chore.schedule()


def test_slow_send_does_not_delay_recovery_load_or_monitor_and_no_submissions_accumulate(
    monkeypatch,
):
    from qualify_api.creative.worker import __main__ as cli

    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    calls = []
    mail_calls = []
    runners = []
    outcomes = []

    class TrackedChore(BackgroundChore):
        def __init__(self, task, stop):
            super().__init__(task, stop)
            runners.append(self)

    class Monitor:
        clock = staticmethod(lambda: None)
        beat = staticmethod(lambda: None)

        def check(self, snapshot):
            calls.append("monitor")

    def blocked_mail():
        mail_calls.append(True)
        entered.set()
        release.wait(3)

    monkeypatch.setattr(cli, "_load_dotenv", lambda: None)
    monkeypatch.setattr(cli, "BackgroundChore", TrackedChore)
    monkeypatch.setattr(cli, "production_executors", lambda: {})
    monkeypatch.setattr(
        "qualify_api.creative.composition.production_content_service", lambda: object()
    )
    monkeypatch.setattr(
        "qualify_api.creative.worker.pipeline.PipelinePreparation", lambda *args: lambda: None
    )
    monkeypatch.setattr("qualify_api.mail.final_summary.morning_chore", lambda scope: blocked_mail)
    monkeypatch.setattr(
        "qualify_api.creative.worker.operations.production_monitor", lambda ids: Monitor()
    )
    monkeypatch.setattr(
        "qualify_api.creative.worker.operations.read_snapshot", lambda **kw: Snapshot()
    )
    monkeypatch.setattr(
        "qualify_api.creative.worker.queue_load.production_load_chore",
        lambda **kw: lambda: calls.append("load"),
    )

    def loop(worker, **kwargs):
        for _ in range(5):
            kwargs["sidecar"]()
        worker.stop.set()
        kwargs["sidecar"]()
        done.set()
        return 0

    monkeypatch.setattr(cli, "run_loop", loop)
    thread = threading.Thread(
        target=lambda: outcomes.append(
            cli.main(
                ["--all-tenants", "--once"],
                recovery=lambda: calls.append("recover"),
                install_signals=False,
            )
        )
    )
    thread.start()
    try:
        assert entered.wait(1)
        assert done.wait(1), "maintenance waited for the blocked mail batch"
        assert not release.is_set()
        assert calls == ["recover", "load", "monitor"] * 6
        assert mail_calls == [True]
    finally:
        release.set()
        thread.join(1)
        for runner in runners:
            runner._thread.join(1)
    assert outcomes == [0]

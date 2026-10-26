"""m-24852167: real incident state transitions, external watchdog, safe notifier payloads."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest

from qualify_api.creative.worker.operations import QueueAlert, QueueMonitor, Snapshot, scope_key
from qualify_api.creative.worker.queue_cli import render
from qualify_api.support.notify import WebhookSupportNotifier

NOW = datetime(2026, 10, 26, 12, tzinfo=UTC)


class Redis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def set(self, key: str, value: str, **kwargs: Any) -> bool:
        if kwargs.get("nx") and key in self.data:
            return False
        self.data[key] = value
        return True

    def delete(self, key: str) -> None:
        self.data.pop(key, None)


class Notifier:
    def __init__(self) -> None:
        self.messages: list[QueueAlert] = []
        self.accept = True

    def notify(self, message: QueueAlert) -> bool:
        if self.accept:
            self.messages.append(message)
        return self.accept


@pytest.mark.parametrize("condition", ["wait", "capacity", "deadline", "quota"])
def test_incident_is_shared_across_processes_and_rearms_after_recovery(condition: str) -> None:
    redis = Redis()
    notifier = Notifier()
    now = [NOW]
    first = QueueMonitor(redis, notifier, clock=lambda: now[0])
    restarted = QueueMonitor(redis, notifier, clock=lambda: now[0])
    snapshot = Snapshot(
        waits=({"window": "hour", "p95": 301},) if condition == "wait" else (),
        weekly_capacity=({"p95": 5},) if condition == "capacity" else (),
        urgent_finals=1 if condition == "deadline" else 0,
    )
    if condition == "quota":
        first.quota_exceeded()
    first.check(snapshot)
    restarted.check(snapshot)
    assert [n.reference for n in notifier.messages] == [condition]
    now[0] += timedelta(minutes=6)
    restarted.check(Snapshot())
    if condition == "quota":
        restarted.quota_exceeded()
    restarted.check(snapshot)
    assert [n.reference for n in notifier.messages] == [condition, condition]


def test_heartbeat_is_checked_by_another_process_and_recovers() -> None:
    redis, notifier = Redis(), Notifier()
    now = [NOW]
    worker = QueueMonitor(redis, notifier, clock=lambda: now[0])
    calendar = QueueMonitor(redis, notifier, clock=lambda: now[0])
    worker.beat()
    now[0] += timedelta(minutes=5)
    calendar.watchdog()
    assert not notifier.messages
    now[0] += timedelta(seconds=1)
    calendar.watchdog()
    calendar.watchdog()
    assert [n.reference for n in notifier.messages] == ["heartbeat"]
    worker.beat()
    calendar.watchdog()
    now[0] += timedelta(minutes=6)
    calendar.watchdog()
    assert len(notifier.messages) == 2


def test_watchdog_detects_service_that_never_started_after_grace() -> None:
    notifier, now = Notifier(), [NOW]
    monitor = QueueMonitor(Redis(), notifier, clock=lambda: now[0])
    monitor.watchdog()
    assert not notifier.messages
    now[0] += timedelta(minutes=6)
    monitor.watchdog()
    assert notifier.messages[0].reference == "heartbeat"


def test_failed_delivery_does_not_silence_incident() -> None:
    redis, notifier = Redis(), Notifier()
    monitor = QueueMonitor(redis, notifier)
    notifier.accept = False
    monitor.publish("wait", QueueAlert("wait", "Espera 301 s"))
    notifier.accept = True
    monitor.publish("wait", QueueAlert("wait", "Espera 301 s"))
    assert len(notifier.messages) == 1


def test_delivery_lease_prevents_concurrent_notifiers() -> None:
    redis, notifier = Redis(), Notifier()
    monitor = QueueMonitor(redis, notifier)
    redis.set(monitor._key("incident:wait:delivery"), "pending")
    monitor.publish("wait", QueueAlert("wait", "301"))
    assert not notifier.messages


def test_thresholds_are_strict_and_empty_samples_never_alert() -> None:
    assert not Snapshot(waits=({"window": "hour", "p95": 300},)).conditions()
    assert not Snapshot(waits=({"window": "hour", "p95": None},)).conditions()
    assert not Snapshot(waits=({"window": "day", "p95": 400},)).conditions()
    assert not Snapshot(weekly_capacity=({"p95": 4.99},)).conditions()


def test_scope_keys_do_not_depend_on_tenant_order() -> None:
    a, b = uuid4(), uuid4()
    assert scope_key([a, b]) == scope_key([b, a])
    assert scope_key([a]) != scope_key([b]) != scope_key(None)


def test_existing_webhook_transport_receives_only_operational_text() -> None:
    payloads = []

    def respond(request: httpx.Request) -> httpx.Response:
        import json

        payloads.append(json.loads(request.content))
        return httpx.Response(200)

    notifier = WebhookSupportNotifier(
        "https://example.invalid/hook", transport=httpx.MockTransport(respond)
    )
    assert notifier.notify(QueueAlert("heartbeat", "creative-worker sin latido >5 min."))
    assert payloads[0]["text"] == payloads[0]["content"]["text"]
    assert "Correo:" not in payloads[0]["text"]
    assert "WhatsApp:" not in payloads[0]["text"]


def test_report_shows_unknown_wait_honestly_and_configured_slot_capacity(monkeypatch) -> None:
    monkeypatch.setenv("QUALIFY_VENDOR_POOLS", "byteplus:seedance-2-5=4")
    output = render(
        Snapshot(
            waits=({"window": "hour", "p50": None, "p95": None, "samples": 0},),
            slots=({"vendor_model": "byteplus:seedance-2-5", "occupied": 3},),
            top_tenants=({"tenant_id": uuid4(), "jobs": 12},),
        )
    )
    assert "p50=— p95=— muestras=0" in output
    assert "cupos ocupados=3/4" in output
    assert "12" in output


def test_redis_outage_does_not_block_calendar_recovery_or_publication(monkeypatch) -> None:
    from qualify_api.creative.worker import operations
    from qualify_api.planner import worker
    from qualify_api.planner.tick import TickReport

    class BrokenRedis(Redis):
        def get(self, key: str) -> str | None:
            raise ConnectionError("redis offline")

    monitor = QueueMonitor(BrokenRedis(), Notifier())
    monkeypatch.setattr(operations, "production_monitor", lambda ids=None: monitor)
    calls = []

    class Runner:
        async def run_once(self):
            calls.append("publish_tick")
            return TickReport(started_at=NOW)

    async def loop(make_runner, **kwargs):
        kwargs["sidecar"]()
        await make_runner().run_once()
        return 0

    monkeypatch.setattr(worker, "run_worker", loop)
    assert (
        worker.main(
            ["--all-tenants"],
            scoped=lambda ids: Runner(),
            production=Runner,
            chore=lambda: None,
            recovery=lambda: calls.append("recover"),
        )
        == 0
    )
    assert calls == ["recover", "publish_tick"]


def test_legacy_recovery_failure_does_not_silence_queue_monitor(monkeypatch) -> None:
    from qualify_api.creative.worker import __main__ as cli
    from qualify_api.creative.worker import operations

    calls = []

    class Monitor:
        clock = staticmethod(lambda: NOW)
        beat = staticmethod(lambda: None)

        def check(self, snapshot):
            calls.append("monitor")

    def failed_recovery():
        raise RuntimeError("legacy recovery failed")

    def loop(worker, **kwargs):
        kwargs["sidecar"]()
        return 0

    monkeypatch.setattr(operations, "production_monitor", lambda ids=None: Monitor())
    monkeypatch.setattr(operations, "read_snapshot", lambda **kwargs: Snapshot())
    monkeypatch.setattr(cli, "run_loop", loop)
    assert (
        cli.main(
            ["--all-tenants", "--once"],
            executors={},
            recovery=failed_recovery,
            install_signals=False,
        )
        == 0
    )
    assert calls == ["monitor"]


def test_vendor_quota_event_is_observed_and_monitor_failure_still_defers_job() -> None:
    from qualify_api.creative.worker import runner

    from .test_creative_worker_runner import A, Clock, FakeBytePlus, MemoryStore, make_worker, one

    monitor = QueueMonitor(Redis(), Notifier(), clock=lambda: NOW)
    store, clock = MemoryStore(), Clock()
    store.add(A)
    worker = make_worker(store, FakeBytePlus(busy=1), clock)
    worker.on_vendor_busy = lambda busy: monitor.quota_exceeded()
    assert worker.process(one(worker)) == runner.DEFERRED
    monitor.check(Snapshot())
    assert monitor.notifier.messages[0].reference == "quota"

    def broken_observer(busy):
        raise ConnectionError("redis offline")

    worker.on_vendor_busy = broken_observer
    clock.advance(timedelta(minutes=2))
    worker.executors[next(iter(worker.executors))] = FakeBytePlus(busy=1)
    assert worker.process(one(worker)) == runner.DEFERRED


def test_heartbeat_callback_failure_does_not_stop_claim_rounds() -> None:
    from qualify_api.creative.worker.runner import run_loop

    from .test_creative_worker_runner import Clock, FakeBytePlus, MemoryStore, make_worker

    worker = make_worker(MemoryStore(), FakeBytePlus(), Clock())

    def failed_beat():
        raise ConnectionError("redis offline")

    assert run_loop(worker, once=False, max_rounds=2, interval=0, on_round=failed_beat) == 0

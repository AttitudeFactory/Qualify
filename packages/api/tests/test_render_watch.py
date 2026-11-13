"""m-25017289: render health watch — probe criterion, grace, one alert per incident."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from qualify_api.creative.worker import render_watch
from qualify_api.creative.worker.render_watch import (
    GRACE_SECONDS,
    RenderAlert,
    RenderWatch,
    _ChannelNotifier,
    probe,
    production_channel,
    profile_enabled,
)

NOW = datetime(2026, 11, 13, 12, tzinfo=UTC)


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
        self.alerts: list[RenderAlert] = []

    def notify(self, alert: RenderAlert) -> bool:
        self.alerts.append(alert)
        return True


def _transport(status: int, body: object) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handle)


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (200, {"ok": True, "bundleReady": True, "templates": []}, None),
        (200, {"ok": True, "bundleReady": False}, "bundleReady=false"),
        (200, {"ok": False}, "ok=false"),
        (200, ["odd"], "ok=false"),
        (503, {"ok": False}, "HTTP 503"),
    ],
)
def test_probe_uses_the_sticker_criterion(status: int, body: object, expected: str | None) -> None:
    assert probe("http://render:3200", transport=_transport(status, body)) == expected


def test_probe_reports_connection_errors_by_type_only() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom http://render:3200", request=request)

    assert probe("http://render:3200", transport=httpx.MockTransport(refuse)) == "ConnectError"


def test_alerts_once_after_grace_and_rearms_after_recovery() -> None:
    redis, notifier = Redis(), Notifier()
    now = [NOW]
    health: list[str | None] = ["ConnectError"]
    watch = RenderWatch(redis, notifier, lambda: health[0], clock=lambda: now[0])
    # A second observer (e.g. a restarted calendar-worker) shares the Redis latch.
    restarted = RenderWatch(redis, notifier, lambda: health[0], clock=lambda: now[0])

    watch.check()
    now[0] += timedelta(seconds=GRACE_SECONDS - 1)
    watch.check()
    assert notifier.alerts == []

    now[0] += timedelta(seconds=1)
    watch.check()
    restarted.check()
    now[0] += timedelta(minutes=10)
    watch.check()
    assert [a.reference for a in notifier.alerts] == ["health"]
    assert "ConnectError" in notifier.alerts[0].as_text()
    assert "http" not in notifier.alerts[0].as_text()

    health[0] = None
    watch.check()
    health[0] = "HTTP 503"
    watch.check()
    assert len(notifier.alerts) == 1  # the grace starts over after a recovery
    now[0] += timedelta(seconds=GRACE_SECONDS)
    watch.check()
    assert len(notifier.alerts) == 2


def test_a_blip_inside_the_grace_never_alerts() -> None:
    redis, notifier = Redis(), Notifier()
    now = [NOW]
    health: list[str | None] = ["ConnectError"]
    watch = RenderWatch(redis, notifier, lambda: health[0], clock=lambda: now[0])
    watch.check()
    now[0] += timedelta(seconds=GRACE_SECONDS - 30)
    health[0] = None
    watch.check()
    health[0] = "ConnectError"
    now[0] += timedelta(seconds=60)
    watch.check()
    assert notifier.alerts == []


@pytest.mark.parametrize(
    ("profiles", "enabled"),
    [
        ("render", True),
        ("render,other", True),
        (" other , render ", True),
        ("", False),
        ("renderer", False),
    ],
)
def test_watch_only_runs_with_the_render_profile(profiles: str, enabled: bool) -> None:
    assert profile_enabled({"COMPOSE_PROFILES": profiles}) is enabled
    assert profile_enabled({}) is False


def test_chore_is_none_without_the_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COMPOSE_PROFILES", raising=False)
    assert render_watch.render_watch_chore(Redis()) is None


def test_chore_swallows_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COMPOSE_PROFILES", "render")

    def explode(*args: Any, **kwargs: Any) -> str | None:
        raise RuntimeError("redis down")

    monkeypatch.setattr(render_watch, "probe", explode)
    chore = render_watch.render_watch_chore(Redis())
    assert chore is not None
    chore()  # logged, never raised into the calendar-worker loop


def test_channel_prefers_the_devops_bot_then_support_then_none() -> None:
    devops = "https://open.larksuite.com/hook/devops"
    support = "https://open.larksuite.com/hook/support"
    both = {"QUALIFY_DEVOPS_WEBHOOK_URL": devops, "QUALIFY_SUPPORT_WEBHOOK_URL": support}
    assert production_channel(both)._url == devops  # type: ignore[union-attr]
    assert production_channel({"QUALIFY_SUPPORT_WEBHOOK_URL": support})._url == support  # type: ignore[union-attr]
    assert production_channel({}) is None
    assert _ChannelNotifier(None).notify(RenderAlert("health", "x")) is False

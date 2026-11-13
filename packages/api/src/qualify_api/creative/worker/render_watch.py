"""Render service health watch (m-25017289). Team-only; never import in request paths.

The calendar-worker's minute watchdog (the same pass that watches creative-worker's beat)
asks the Remotion render service `/health` — the endpoint and criterion the sticker path
and the image's HEALTHCHECK use: `ok` and `bundleReady`. When render stays unhealthy for
`GRACE_SECONDS` the team gets ONE message; recovery clears the incident and a recurrence
alerts again. Latches live in Redis, shared with the queue incidents (`operations.py`).

Destination: the Qualify-devs bot (`QUALIFY_DEVOPS_WEBHOOK_URL`, the server-side copy of
GitHub's `DEVOPS_WEBHOOK_URL`), else the internal channel (`QUALIFY_SUPPORT_WEBHOOK_URL`),
else the log only. Nothing new to configure: with neither variable the watch still logs.

Only watched while `render` is in `COMPOSE_PROFILES` (compose loads `.env.prod` into every
Python service): with the profile off the hostname does not exist and that is not an outage.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from qualify_api.creative.worker.operations import PREFIX, QueueMonitor, RedisStore

logger = logging.getLogger(__name__)

#: Same budget as the sticker path's probe (`sticker_c.HEALTH_TIMEOUT_SECONDS`).
HEALTH_TIMEOUT_SECONDS = 3.0
#: A deploy recreates render (~20 s until the bundle is ready) and one render can hold the
#: event loop briefly; three minutes of consecutive failures is an outage, not a blip.
GRACE_SECONDS = 180
PROFILE = "render"
DEFAULT_RENDER_URL = "http://render:3200"
_UNHEALTHY_SINCE = f"{PREFIX}render:unhealthy_since"


class TeamChannel(Protocol):
    def send(self, text: str) -> bool:
        """True when the channel accepted the message. Must not raise."""
        ...


@dataclass(frozen=True)
class RenderAlert:
    """No client content: only the service state the team needs to act."""

    reference: str
    message: str

    def as_text(self) -> str:
        return f"Servicio de render · {self.reference}\n{self.message}"


class _ChannelNotifier:
    """Adapts a text channel to the `notify(alert)` shape `QueueMonitor.publish` uses."""

    def __init__(self, channel: TeamChannel | None) -> None:
        self._channel = channel

    def notify(self, alert: RenderAlert) -> bool:
        if self._channel is None:
            logger.warning("render.watch.alert_not_sent no team channel configured")
            return False
        return self._channel.send(alert.as_text())


def profile_enabled(environ: Mapping[str, str] = os.environ) -> bool:
    profiles = environ.get("COMPOSE_PROFILES", "")
    return PROFILE in {p.strip() for p in profiles.split(",")}


def probe(base_url: str, *, transport: httpx.BaseTransport | None = None) -> str | None:
    """None when render is healthy; otherwise a short reason without URLs or bodies."""
    try:
        with httpx.Client(transport=transport, timeout=HEALTH_TIMEOUT_SECONDS) as client:
            response = client.get(f"{base_url.rstrip('/')}/health")
        if response.status_code != 200:
            return f"HTTP {response.status_code}"
        body: Any = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return type(exc).__name__
    if not isinstance(body, dict) or not body.get("ok"):
        return "ok=false"
    if not body.get("bundleReady"):
        return "bundleReady=false"
    return None


class RenderWatch:
    def __init__(
        self,
        store: RedisStore,
        notifier: Any,
        probe_health: Callable[[], str | None],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store = store
        self.probe_health = probe_health
        self.clock = clock
        self._incidents = QueueMonitor(store, notifier, scope="render", clock=clock)

    def check(self) -> None:
        reason = self.probe_health()
        if reason is None:
            self.store.delete(_UNHEALTHY_SINCE)
            self._incidents.publish("health", None)
            return
        now = self.clock().timestamp()
        self.store.set(_UNHEALTHY_SINCE, str(now), nx=True)
        since = float(self.store.get(_UNHEALTHY_SINCE) or now)
        minutes = int((now - since) // 60)
        logger.warning("render.watch.unhealthy reason=%s for_minutes=%d", reason, minutes)
        if now - since < GRACE_SECONDS:
            return
        self._incidents.publish(
            "health",
            RenderAlert(
                "health",
                f"render no responde sano hace {minutes} min ({reason}). La generación que "
                "compone con Remotion falla mientras tanto. Revisar `just deploy-status "
                "qualify-prod` y `just deploy-logs qualify-prod render`.",
            ),
        )


def production_channel(environ: Mapping[str, str] = os.environ) -> TeamChannel | None:
    """The Qualify-devs bot when configured, else the internal channel, else none."""
    from qualify_api.support.webhook import TextWebhook  # noqa: PLC0415

    for url_env, secret_env in (
        ("QUALIFY_DEVOPS_WEBHOOK_URL", "QUALIFY_DEVOPS_WEBHOOK_SECRET"),
        ("QUALIFY_SUPPORT_WEBHOOK_URL", "QUALIFY_SUPPORT_WEBHOOK_SECRET"),
    ):
        url = environ.get(url_env, "").strip()
        if url:
            return TextWebhook(url, secret=environ.get(secret_env, "").strip())
    return None


def render_watch_chore(store: RedisStore) -> Callable[[], None] | None:
    """The minute check, or None when the render profile is off on this server."""
    if not profile_enabled():
        return None
    base_url = os.environ.get("QUALIFY_RENDER_URL", "").strip() or DEFAULT_RENDER_URL
    watch = RenderWatch(store, _ChannelNotifier(production_channel()), lambda: probe(base_url))

    def check() -> None:
        try:
            watch.check()
        except Exception:
            logger.warning("render.watch.unavailable", exc_info=True)

    return check

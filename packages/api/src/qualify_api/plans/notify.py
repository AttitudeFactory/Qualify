"""The team's alert channel for plans (m-24852145): the same webhook as the support
requests (`QUALIFY_SUPPORT_WEBHOOK_URL`, Lark), so no new secret is needed.

A plan assignment and a crossed USD cap are told there. Nothing credential-adjacent is
ever in the message: a business or subscription name, a plan, a month, an amount.
"""

from __future__ import annotations

import logging
import os
from typing import Protocol

import httpx

from qualify_api.support.webhook import TextWebhook

_LOGGER = logging.getLogger(__name__)


class TeamNotifier(Protocol):
    def notify(self, text: str) -> bool:
        """True when the channel accepted it. Never raises."""
        ...


class NullTeamNotifier:
    def notify(self, text: str) -> bool:
        _LOGGER.warning("plans: no team channel configured (set QUALIFY_SUPPORT_WEBHOOK_URL)")
        return False


class WebhookTeamNotifier:
    def __init__(
        self,
        url: str,
        *,
        secret: str = "",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._webhook = TextWebhook(url, secret=secret, transport=transport)

    def notify(self, text: str) -> bool:
        return self._webhook.send(text)


class RecordingTeamNotifier:
    """In-memory notifier for tests and dry runs."""

    def __init__(self, *, accept: bool = True) -> None:
        self.sent: list[str] = []
        self._accept = accept

    def notify(self, text: str) -> bool:
        self.sent.append(text)
        return self._accept


def production_team_notifier() -> TeamNotifier:
    url = os.environ.get("QUALIFY_SUPPORT_WEBHOOK_URL", "").strip()
    secret = os.environ.get("QUALIFY_SUPPORT_WEBHOOK_SECRET", "").strip()
    return WebhookTeamNotifier(url, secret=secret) if url else NullTeamNotifier()


__all__ = [
    "NullTeamNotifier",
    "RecordingTeamNotifier",
    "TeamNotifier",
    "WebhookTeamNotifier",
    "production_team_notifier",
]

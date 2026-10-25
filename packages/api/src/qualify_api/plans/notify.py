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

_LOGGER = logging.getLogger(__name__)
_TIMEOUT_SECONDS = 5.0


class TeamNotifier(Protocol):
    def notify(self, text: str) -> bool:
        """True when the channel accepted it. Never raises."""
        ...


class NullTeamNotifier:
    def notify(self, text: str) -> bool:
        _LOGGER.warning("plans: no team channel configured (set QUALIFY_SUPPORT_WEBHOOK_URL)")
        return False


class WebhookTeamNotifier:
    def __init__(self, url: str, *, transport: httpx.BaseTransport | None = None) -> None:
        self._url = url
        self._transport = transport

    def notify(self, text: str) -> bool:
        payload = {"text": text, "msg_type": "text", "content": {"text": text}}
        try:
            with httpx.Client(transport=self._transport, timeout=_TIMEOUT_SECONDS) as client:
                response = client.post(self._url, json=payload)
        except httpx.HTTPError as exc:
            # type only: a transport error's text can carry the webhook URL (a secret)
            _LOGGER.error("plans: team channel unreachable (%s)", type(exc).__name__)
            return False
        if response.status_code >= 400:
            _LOGGER.error("plans: team channel answered HTTP %d", response.status_code)
            return False
        return True


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
    return WebhookTeamNotifier(url) if url else NullTeamNotifier()


__all__ = [
    "NullTeamNotifier",
    "RecordingTeamNotifier",
    "TeamNotifier",
    "WebhookTeamNotifier",
    "production_team_notifier",
]

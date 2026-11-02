"""Shared support/plan webhook transport; Lark acceptance is more than HTTP 200.

Protocol and optional bot signature:
https://open.larksuite.com/document/uAjLw4CM/ukTMukTMukTM/bot-v3/use-custom-bots-in-a-group
Other existing webhook destinations (Slack/Cliq) retain their HTTP 2xx contract.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
from contextvars import ContextVar

import httpx

logger = logging.getLogger(__name__)
_LARK_HOSTS = frozenset({"open.larksuite.com", "open.feishu.cn"})
_WEBHOOK_URL: ContextVar[str] = ContextVar("team_webhook_url", default="")


class _RedactWebhookURL(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # httpx logs the complete request URL at INFO. ContextVar scopes redaction to
        # this send; another thread/task keeps its ordinary HTTP diagnostics intact.
        url = _WEBHOOK_URL.get()
        if url:
            record.msg = record.getMessage().replace(url, "[webhook URL redacted]")
            record.args = ()
        return True


logging.getLogger("httpx").addFilter(_RedactWebhookURL())


class TextWebhook:
    def __init__(
        self,
        url: str,
        *,
        secret: str = "",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._url = url
        self._secret = secret
        self._transport = transport

    def send(self, text: str) -> bool:
        try:
            url = httpx.URL(self._url)
            is_lark = url.host in _LARK_HOSTS
            payload = {"text": text, "msg_type": "text", "content": {"text": text}}
            if is_lark and self._secret:
                timestamp = str(int(time.time()))
                key = f"{timestamp}\n{self._secret}".encode()
                payload["timestamp"] = timestamp
                payload["sign"] = base64.b64encode(
                    hmac.new(key, b"", hashlib.sha256).digest()
                ).decode()
            token = _WEBHOOK_URL.set(str(url))
            try:
                with httpx.Client(transport=self._transport, timeout=5.0) as client:
                    response = client.post(url, json=payload)
            finally:
                _WEBHOOK_URL.reset(token)
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            # Only the type: URLs, signatures and response bodies may contain secrets.
            logger.error("team webhook unreachable (%s)", type(exc).__name__)
            return False
        if not response.is_success:
            logger.error("team webhook answered HTTP %d", response.status_code)
            return False
        if not is_lark:
            return True
        try:
            body = response.json()
        except ValueError:
            logger.error("Lark webhook returned invalid JSON")
            return False
        if isinstance(body, dict):
            codes = [body[key] for key in ("code", "StatusCode") if key in body]
            if codes and all(type(code) is int and code == 0 for code in codes):
                return True
        logger.error("Lark webhook did not confirm acceptance")
        return False

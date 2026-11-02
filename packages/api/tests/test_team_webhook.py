"""m-24852167: accepted HTTP requests can still be rejected Lark messages."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from qualify_api.plans.notify import WebhookTeamNotifier, production_team_notifier
from qualify_api.support.notify import (
    SupportNotification,
    WebhookSupportNotifier,
    production_support_notifier,
)

LARK = "https://open.larksuite.com/open-apis/bot/v2/hook/fixture"
NOTE = SupportNotification("REF001", "B", "a@example.invalid", "", "other", "", {})


def send(
    kind: str,
    transport: httpx.BaseTransport,
    *,
    url: str = LARK,
    secret: str = "",
) -> bool:
    if kind == "support":
        return WebhookSupportNotifier(url, secret=secret, transport=transport).notify(NOTE)
    return WebhookTeamNotifier(url, secret=secret, transport=transport).notify("Alerta del plan")


@pytest.mark.parametrize("kind", ["support", "plans"])
@pytest.mark.parametrize(
    ("body", "accepted"),
    [
        ({"code": 0}, True),
        ({"StatusCode": 0}, True),
        ({"code": 0, "StatusCode": 0}, True),
        ({"code": 19021, "msg": "sign match fail"}, False),
        ({"StatusCode": 19024}, False),
        ({"code": 19021, "StatusCode": 0}, False),
        ({"code": 0, "StatusCode": 19021}, False),
        ({"code": "0"}, False),
        ({"code": False}, False),
        ({"code": None}, False),
        ({"code": 0.0}, False),
        ({"msg": "success"}, False),
        ([], False),
        (None, False),
    ],
)
def test_lark_acceptance_requires_an_explicit_integer_zero(
    kind: str, body: object, accepted: bool
) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    assert send(kind, transport) is accepted


@pytest.mark.parametrize("kind", ["support", "plans"])
@pytest.mark.parametrize("content", [b"", b"ok", b"{broken", b"<html>proxy error</html>"])
def test_lark_malformed_response_is_not_accepted(kind: str, content: bytes) -> None:
    assert not send(kind, httpx.MockTransport(lambda _: httpx.Response(200, content=content)))


@pytest.mark.parametrize("kind", ["support", "plans"])
@pytest.mark.parametrize("status", [301, 302, 400, 429, 500])
def test_http_failure_or_redirect_is_not_acceptance(kind: str, status: int) -> None:
    assert not send(kind, httpx.MockTransport(lambda _: httpx.Response(status, json={"code": 0})))


@pytest.mark.parametrize("kind", ["support", "plans"])
@pytest.mark.parametrize("host", ["open.larksuite.com", "open.feishu.cn"])
def test_signed_lark_message_uses_current_seconds_and_the_documented_signature(
    kind: str, host: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("qualify_api.support.webhook.time.time", lambda: 100.9)
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"code": 0})

    assert send(
        kind,
        httpx.MockTransport(handler),
        url=f"https://{host}/open-apis/bot/v2/hook/fixture",
        secret="demo",
    )
    assert seen[0]["timestamp"] == "100"
    assert seen[0]["sign"] == "jquNHnVOwmDRfw+vqTIrY5dooJAgi5EcRtLsQE4wfXg="
    assert "demo" not in seen[0].values()
    assert seen[0]["msg_type"] == "text"
    assert seen[0]["content"] == {"text": seen[0]["text"]}


@pytest.mark.parametrize("kind", ["support", "plans"])
@pytest.mark.parametrize("host", ["hooks.slack.com", "cliq.zoho.com", "hooks.example.invalid"])
def test_other_existing_webhooks_retain_plain_text_2xx_acceptance(kind: str, host: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert "sign" not in payload and "timestamp" not in payload
        assert payload["text"] == payload["content"]["text"]
        return httpx.Response(200, text="ok")

    assert send(kind, httpx.MockTransport(handler), url=f"https://{host}/hook", secret="unused")


@pytest.mark.parametrize("kind", ["support", "plans"])
def test_webhook_errors_do_not_log_credentials_or_response_body(
    kind: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="httpx")
    url = LARK + "-path-credential?token=url-credential"
    key = "signing-secret"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"failed {url} {key}")

    assert not send(kind, httpx.MockTransport(handler), url=url, secret=key)
    assert not send(
        kind,
        httpx.MockTransport(lambda _: httpx.Response(200, json={"code": 19021, "msg": key})),
        url=url,
        secret=key,
    )
    assert "url-credential" not in caplog.text
    assert "path-credential" not in caplog.text
    assert "signing-secret" not in caplog.text
    assert "open.larksuite.com" not in caplog.text


@pytest.mark.parametrize("kind", ["support", "plans"])
def test_successful_webhook_redaction_keeps_other_threads_http_diagnostics(
    kind: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="httpx")

    def ordinary_request() -> None:
        with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200))) as client:
            client.get("https://example.invalid/health")

    def handler(request: httpx.Request) -> httpx.Response:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(ordinary_request).result()
        return httpx.Response(200, json={"code": 0})

    assert send(
        kind,
        httpx.MockTransport(handler),
        url=LARK + "-path-credential?token=query-credential",
        secret="signing-credential",
    )
    # The webhook request keeps method/status but no URL or signing material. An HTTP
    # request made concurrently outside the send context still names its own URL.
    assert 'POST [webhook URL redacted] "HTTP/1.1 200 OK"' in caplog.text
    assert "GET https://example.invalid/health" in caplog.text
    assert "credential" not in caplog.text
    assert "open.larksuite.com" not in caplog.text
    ordinary_request()  # Context is also reset on the sending thread after success.
    assert caplog.text.count("GET https://example.invalid/health") == 2


@pytest.mark.parametrize("factory", [production_support_notifier, production_team_notifier])
def test_production_notifiers_read_the_shared_optional_signing_secret(
    factory: Callable, monkeypatch: pytest.MonkeyPatch
) -> None:
    from qualify_api.support.webhook import TextWebhook

    monkeypatch.setenv("QUALIFY_SUPPORT_WEBHOOK_URL", LARK)
    monkeypatch.setenv("QUALIFY_SUPPORT_WEBHOOK_SECRET", "fixture-secret")
    seen: list[str] = []

    def capture(webhook: TextWebhook, text: str) -> bool:
        seen.append(webhook._secret)
        return True

    monkeypatch.setattr(TextWebhook, "send", capture)
    notifier = factory()
    assert notifier.notify(NOTE if factory is production_support_notifier else "Alerta")
    assert seen == ["fixture-secret"]

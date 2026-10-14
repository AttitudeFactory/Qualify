"""HTTP/HMAC contract for the WhatsApp webhook receiver (WA-03).

Fully offline: no network, no Postgres. The sink is a fake that records what it was
handed. Mirrors `test_mentions_webhook.py`'s harness shape.
"""

from __future__ import annotations

import hmac
import json
from hashlib import sha256

import pytest
from fastapi.testclient import TestClient
from qualify_shared.social.wa_shapes import WANotification

from qualify_api.http import whatsapp_routes
from qualify_api.http.app import create_app
from qualify_api.whatsapp.config import WhatsAppWebhookSettings
from qualify_api.whatsapp.sink import log_only_sink

APP_SECRET = "test-app-secret"
VERIFY_TOKEN = "test-wa-verify-token"

TEST_WABA_ID = "2338576026889338"
TEST_PHONE_NUMBER_ID = "1393787420477981"


def _sign(body: bytes, *, secret: str = APP_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, sha256).hexdigest()


class Harness:
    def __init__(self) -> None:
        self.received: list[tuple[WANotification, bytes]] = []

        async def fake_sink(*, notification: WANotification, raw_body: bytes) -> None:
            self.received.append((notification, raw_body))

        app = create_app(configure_production=False)
        app.dependency_overrides[whatsapp_routes.get_webhook_settings] = lambda: (
            WhatsAppWebhookSettings(app_secret=APP_SECRET, verify_token=VERIFY_TOKEN)
        )
        app.dependency_overrides[whatsapp_routes.get_event_sink] = lambda: fake_sink
        self.http = TestClient(app)

    def post(self, body: bytes, *, headers: dict[str, str]):  # noqa: ANN201
        return self.http.post(
            "/api/whatsapp/webhook",
            content=body,
            headers={"Content-Type": "application/json", **headers},
        )


def _status_body(*, status: str = "delivered") -> bytes:
    """The live 2026-10-14 shape (see `packages/shared/tests/fixtures/
    whatsapp_status_read_live_2026-10-14.json`), trimmed to what the route asserts."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": TEST_WABA_ID,
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15556336018",
                                "phone_number_id": TEST_PHONE_NUMBER_ID,
                            },
                            "statuses": [
                                {
                                    "id": "wamid.TEST",
                                    "status": status,
                                    "timestamp": "1791953775",
                                    "recipient_id": "584240000000",
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    return json.dumps(payload).encode("utf-8")


# ---------------------------------------------------------------------------
# GET challenge
# ---------------------------------------------------------------------------


def test_get_with_correct_verify_token_echoes_the_challenge() -> None:
    harness = Harness()

    response = harness.http.get(
        "/api/whatsapp/webhook",
        params={"hub.mode": "subscribe", "hub.challenge": "4242", "hub.verify_token": VERIFY_TOKEN},
    )

    assert response.status_code == 200
    assert response.text == "4242"
    assert response.headers["content-type"].startswith("text/plain")


def test_get_with_wrong_verify_token_is_403() -> None:
    harness = Harness()

    response = harness.http.get(
        "/api/whatsapp/webhook",
        params={"hub.mode": "subscribe", "hub.challenge": "4242", "hub.verify_token": "wrong"},
    )

    assert response.status_code == 403


def test_get_with_the_mentions_verify_token_is_not_accepted_here() -> None:
    """The two webhooks have separate verify tokens by design (`whatsapp/config.py`);
    a token that happens to be valid for `/api/mentions/webhook` proves nothing here."""
    harness = Harness()

    response = harness.http.get(
        "/api/whatsapp/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.challenge": "4242",
            "hub.verify_token": "dev-only-webhook-verify-token",
        },
    )

    assert response.status_code == 403


def test_get_missing_verify_token_is_422_not_a_silent_pass() -> None:
    harness = Harness()

    response = harness.http.get(
        "/api/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.challenge": "4242"}
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST signature validation
# ---------------------------------------------------------------------------


def test_post_with_valid_signature_reaches_the_sink_with_the_parsed_notification() -> None:
    harness = Harness()
    body = _status_body(status="delivered")

    response = harness.post(body, headers={"X-Hub-Signature-256": _sign(body)})

    assert response.status_code == 200
    ((notification, raw_body),) = harness.received
    assert raw_body == body  # the sink gets the exact signed bytes, not a re-serialization
    (entry,) = notification.entry
    assert entry.id == TEST_WABA_ID
    value = entry.changes[0].messages_value()
    assert value is not None
    assert value.metadata.phone_number_id == TEST_PHONE_NUMBER_ID
    assert [s.status for s in value.statuses] == ["delivered"]


def test_post_with_missing_signature_is_403_and_never_reaches_the_sink() -> None:
    harness = Harness()

    response = harness.post(_status_body(), headers={})

    assert response.status_code == 403
    assert harness.received == []


def test_post_with_invalid_signature_is_403() -> None:
    harness = Harness()

    response = harness.post(_status_body(), headers={"X-Hub-Signature-256": "sha256=" + "0" * 64})

    assert response.status_code == 403
    assert harness.received == []


def test_post_signed_with_the_wrong_secret_is_403() -> None:
    harness = Harness()
    body = _status_body()

    response = harness.post(
        body, headers={"X-Hub-Signature-256": _sign(body, secret="not-the-real-secret")}
    )

    assert response.status_code == 403
    assert harness.received == []


def test_post_with_a_tampered_body_is_403() -> None:
    """Signature computed over one body, a different body delivered: the check runs on
    the raw bytes received, so the tamper is caught."""
    harness = Harness()
    signed = _status_body(status="delivered")
    tampered = _status_body(status="read")

    response = harness.post(tampered, headers={"X-Hub-Signature-256": _sign(signed)})

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Past HMAC: always 200, sink only for a real WhatsApp notification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        b"not json at all",
        json.dumps({"object": "instagram", "entry": []}).encode(),
        json.dumps({"object": "whatsapp_business_account"}).encode()[:-1],  # truncated
        json.dumps(["a", "list"]).encode(),
    ],
    ids=["not-json", "instagram-object", "truncated", "wrong-top-level-type"],
)
def test_post_signed_but_not_a_whatsapp_notification_is_200_and_skips_the_sink(
    body: bytes,
) -> None:
    harness = Harness()

    response = harness.post(body, headers={"X-Hub-Signature-256": _sign(body)})

    assert response.status_code == 200
    assert harness.received == []


def test_post_with_an_unknown_field_still_parses_and_reaches_the_sink() -> None:
    """`account_update` etc. have a different `value` shape; the receiver must accept
    them (Meta would otherwise retry for 7 days) and let the sink decide."""
    harness = Harness()
    body = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": TEST_WABA_ID,
                    "changes": [{"field": "account_update", "value": {"event": "VERIFIED"}}],
                }
            ],
        }
    ).encode()

    response = harness.post(body, headers={"X-Hub-Signature-256": _sign(body)})

    assert response.status_code == 200
    ((notification, _),) = harness.received
    assert notification.entry[0].changes[0].field == "account_update"
    assert notification.entry[0].changes[0].messages_value() is None


# ---------------------------------------------------------------------------
# The production sink (WA-03's own acceptance: it logs identifiers, nothing else)
# ---------------------------------------------------------------------------


async def test_log_only_sink_logs_identifiers_and_never_the_recipient(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from qualify_shared.social.wa_shapes import parse_whatsapp_notification

    body = _status_body(status="read")
    notification = parse_whatsapp_notification(json.loads(body))

    with caplog.at_level("INFO", logger="qualify_api.whatsapp.sink"):
        await log_only_sink(notification=notification, raw_body=body)

    (record,) = caplog.records
    assert TEST_WABA_ID in record.getMessage()
    assert TEST_PHONE_NUMBER_ID in record.getMessage()
    assert "statuses=read" in record.getMessage()
    assert "584240000000" not in record.getMessage()  # the recipient's number never logs


def test_production_app_wires_settings_and_sink(monkeypatch: pytest.MonkeyPatch) -> None:
    """`create_app()` (production mode) must override both dependencies — an app that
    forgot one would 500 on Meta's first call, which the panel reports as a failed
    verification with no useful detail."""
    monkeypatch.setenv("QUALIFY_META_APP_SECRET", APP_SECRET)
    monkeypatch.setenv("QUALIFY_WA_WEBHOOK_VERIFY_TOKEN", VERIFY_TOKEN)
    app = create_app(configure_production=True)

    assert whatsapp_routes.get_webhook_settings in app.dependency_overrides
    assert whatsapp_routes.get_event_sink in app.dependency_overrides
    settings = app.dependency_overrides[whatsapp_routes.get_webhook_settings]()
    assert settings == WhatsAppWebhookSettings(app_secret=APP_SECRET, verify_token=VERIFY_TOKEN)
    assert app.dependency_overrides[whatsapp_routes.get_event_sink]() is log_only_sink

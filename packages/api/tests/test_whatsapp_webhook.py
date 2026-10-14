"""HTTP/HMAC contract for the WhatsApp webhook receiver (WA-03).

Fully offline: no network, no Postgres. The delivery recorder is a fake here —
`test_webhook_receiver_db.py` covers `record_delivery` itself against real Postgres (it is
the same recorder the mentions route uses). Mirrors `test_mentions_webhook.py`'s harness.
"""

from __future__ import annotations

import hmac
import json
from hashlib import sha256
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from qualify_api.http import whatsapp_routes
from qualify_api.http.app import create_app
from qualify_api.webhooks.envelope import MAX_BODY_BYTES
from qualify_api.webhooks.receiver import RecordedDelivery, record_delivery
from qualify_api.whatsapp.config import WhatsAppWebhookSettings

APP_SECRET = "test-app-secret"
VERIFY_TOKEN = "test-wa-verify-token"

TEST_WABA_ID = "2338576026889338"
TEST_PHONE_NUMBER_ID = "1393787420477981"
DELIVERY_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def _sign(body: bytes, *, secret: str = APP_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, sha256).hexdigest()


class Harness:
    """The app with a fake recorder that remembers every call (and can be made to fail)."""

    def __init__(self, *, recorder_raises: Exception | None = None) -> None:
        self.recorded: list[tuple[bytes, str]] = []

        def fake_recorder(*, body: bytes, signature_header: str) -> RecordedDelivery:
            if recorder_raises is not None:
                raise recorder_raises
            self.recorded.append((body, signature_header))
            return RecordedDelivery(
                delivery_id=DELIVERY_ID,
                duplicate_delivery=False,
                parse_status="parsed",
                changes_total=1,
                changes_new=1,
            )

        app = create_app(configure_production=False)
        app.dependency_overrides[whatsapp_routes.get_webhook_settings] = lambda: (
            WhatsAppWebhookSettings(app_secret=APP_SECRET, verify_token=VERIFY_TOKEN)
        )
        app.dependency_overrides[whatsapp_routes.get_delivery_recorder] = lambda: fake_recorder
        self.http = TestClient(app)

    def post(self, body: bytes, *, headers: dict[str, str]):  # noqa: ANN201
        return self.http.post(
            "/api/whatsapp/webhook",
            content=body,
            headers={"Content-Type": "application/json", **headers},
        )


def _status_body(*, status: str = "delivered") -> bytes:
    """The live 2026-10-14 shape (`packages/shared/tests/fixtures/
    whatsapp_status_read_live_2026-10-14.json`), trimmed to what the route sees."""
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
# POST: a refused body is never recorded
# ---------------------------------------------------------------------------


def test_post_with_valid_signature_is_recorded_then_200() -> None:
    harness = Harness()
    body = _status_body(status="delivered")

    response = harness.post(body, headers={"X-Hub-Signature-256": _sign(body)})

    assert response.status_code == 200
    # The recorder gets the exact signed bytes and the header, never a re-serialization.
    assert harness.recorded == [(body, _sign(body))]


def test_post_with_missing_signature_is_403_and_nothing_is_recorded() -> None:
    harness = Harness()

    response = harness.post(_status_body(), headers={})

    assert response.status_code == 403
    assert harness.recorded == []


def test_post_with_invalid_signature_is_403_and_nothing_is_recorded() -> None:
    harness = Harness()

    response = harness.post(_status_body(), headers={"X-Hub-Signature-256": "sha256=" + "0" * 64})

    assert response.status_code == 403
    assert harness.recorded == []


def test_post_signed_with_the_wrong_secret_is_403_and_nothing_is_recorded() -> None:
    harness = Harness()
    body = _status_body()

    response = harness.post(
        body, headers={"X-Hub-Signature-256": _sign(body, secret="not-the-real-secret")}
    )

    assert response.status_code == 403
    assert harness.recorded == []


def test_post_with_a_tampered_body_is_403() -> None:
    """Signature computed over one body, a different body delivered: the check runs on
    the raw bytes received, so the tamper is caught."""
    harness = Harness()
    signed = _status_body(status="delivered")
    tampered = _status_body(status="read")

    response = harness.post(tampered, headers={"X-Hub-Signature-256": _sign(signed)})

    assert response.status_code == 403
    assert harness.recorded == []


def test_post_over_the_size_limit_is_413_and_nothing_is_recorded() -> None:
    harness = Harness()
    body = b"{" + b" " * MAX_BODY_BYTES + b"}"

    response = harness.post(body, headers={"X-Hub-Signature-256": _sign(body)})

    assert response.status_code == 413
    assert harness.recorded == []


# ---------------------------------------------------------------------------
# Past the signature: record first, then 200 — the recorder decides what a body IS
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        b"not json at all",
        json.dumps({"object": "instagram", "entry": []}).encode(),
        json.dumps(["a", "list"]).encode(),
    ],
    ids=["not-json", "instagram-object", "wrong-top-level-type"],
)
def test_post_signed_but_odd_bodies_are_still_recorded_then_200(body: bytes) -> None:
    """The route does not interpret the body: an unparseable one is recorded as such
    (a retry would not fix it) and a non-WhatsApp envelope is the processor's call."""
    harness = Harness()

    response = harness.post(body, headers={"X-Hub-Signature-256": _sign(body)})

    assert response.status_code == 200
    assert harness.recorded == [(body, _sign(body))]


def test_post_whose_record_fails_is_500_so_meta_retries() -> None:
    harness = Harness(recorder_raises=RuntimeError("database unavailable"))
    body = _status_body()

    response = harness.post(body, headers={"X-Hub-Signature-256": _sign(body)})

    assert response.status_code == 500


# ---------------------------------------------------------------------------
# Production wiring
# ---------------------------------------------------------------------------


def test_production_app_wires_settings_and_the_shared_recorder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`create_app()` (production mode) must override both dependencies — an app that
    forgot one would 500 on Meta's first call, which the panel reports as a failed
    verification with no useful detail. The recorder is the SAME `record_delivery` the
    mentions route uses: one intake log for every Meta product."""
    monkeypatch.setenv("QUALIFY_META_APP_SECRET", APP_SECRET)
    monkeypatch.setenv("QUALIFY_WA_WEBHOOK_VERIFY_TOKEN", VERIFY_TOKEN)
    app = create_app(configure_production=True)

    assert whatsapp_routes.get_webhook_settings in app.dependency_overrides
    assert whatsapp_routes.get_delivery_recorder in app.dependency_overrides
    settings = app.dependency_overrides[whatsapp_routes.get_webhook_settings]()
    assert settings == WhatsAppWebhookSettings(app_secret=APP_SECRET, verify_token=VERIFY_TOKEN)
    assert app.dependency_overrides[whatsapp_routes.get_delivery_recorder]() is record_delivery

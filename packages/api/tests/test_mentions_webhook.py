"""HTTP/HMAC contract for the Meta webhook receiver (QUA-49, QUA-147).

Fully offline: no network, no Postgres. The delivery recorder is a fake here —
`test_webhook_receiver_db.py` covers `record_delivery` itself against real Postgres, and
`test_webhook_processor.py` covers what happens to a recorded change afterwards
(resolution, ORPHAN/AMBIGUOUS, ingestion), which no longer runs in the request.
"""

from __future__ import annotations

import hmac
import json
from hashlib import sha256
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from qualify_api.http import mentions_routes
from qualify_api.http.app import create_app
from qualify_api.mentions.config import MentionsWebhookSettings
from qualify_api.webhooks.envelope import MAX_BODY_BYTES
from qualify_api.webhooks.receiver import RecordedDelivery

APP_SECRET = "test-app-secret"
VERIFY_TOKEN = "test-verify-token"
DELIVERY = UUID("99999999-9999-4999-8999-999999999999")


def _sign(body: bytes, *, secret: str = APP_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, sha256).hexdigest()


class Harness:
    """The app with a fake recorder that remembers every call (and can be made to fail).
    There is deliberately no resolver/ingestor to override any more: if the route ever
    reached for one again, these tests would hit the raise-until-wired dependency."""

    def __init__(self, *, fail_with: Exception | None = None) -> None:
        self.calls: list[tuple[bytes, str]] = []
        self._fail_with = fail_with

        def fake_recorder(*, body: bytes, signature_header: str) -> RecordedDelivery:
            self.calls.append((body, signature_header))
            if self._fail_with is not None:
                raise self._fail_with
            return RecordedDelivery(
                delivery_id=DELIVERY,
                duplicate_delivery=False,
                parse_status="parsed",
                changes_total=1,
                changes_new=1,
            )

        app = create_app(configure_production=False)
        app.dependency_overrides[mentions_routes.get_webhook_settings] = lambda: (
            MentionsWebhookSettings(app_secret=APP_SECRET, verify_token=VERIFY_TOKEN)
        )
        app.dependency_overrides[mentions_routes.get_delivery_recorder] = lambda: fake_recorder
        self.http = TestClient(app)

    def post(self, body: bytes, *, signature: str | None = "auto") -> int:
        headers = {"Content-Type": "application/json"}
        if signature == "auto":
            headers["X-Hub-Signature-256"] = _sign(body)
        elif signature is not None:
            headers["X-Hub-Signature-256"] = signature
        return self.http.post("/api/mentions/webhook", content=body, headers=headers).status_code


def _mentions_body(
    *, ig_user_id: str = "111", media_id: str = "aaa", comment_id: str | None = None
) -> bytes:
    value: dict[str, str] = {"media_id": media_id}
    if comment_id is not None:
        value["comment_id"] = comment_id
    payload = {
        "object": "instagram",
        "entry": [
            {
                "id": ig_user_id,
                "time": 1520622968,
                "changes": [{"field": "mentions", "value": value}],
            }
        ],
    }
    return json.dumps(payload).encode("utf-8")


# ---------------------------------------------------------------------------
# GET challenge — unchanged by QUA-147
# ---------------------------------------------------------------------------


def test_get_with_correct_verify_token_echoes_the_challenge() -> None:
    harness = Harness()

    response = harness.http.get(
        "/api/mentions/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.challenge": "12345",
            "hub.verify_token": VERIFY_TOKEN,
        },
    )

    assert response.status_code == 200
    assert response.text == "12345"


def test_get_with_wrong_verify_token_is_403() -> None:
    harness = Harness()

    response = harness.http.get(
        "/api/mentions/webhook",
        params={"hub.mode": "subscribe", "hub.challenge": "12345", "hub.verify_token": "wrong"},
    )

    assert response.status_code == 403


def test_get_missing_verify_token_is_422_not_a_silent_pass() -> None:
    """`hub.verify_token` is a required query param — an absent one must never fall
    through to comparing `None == settings.verify_token` (which a dev default could
    accidentally satisfy)."""
    harness = Harness()

    response = harness.http.get(
        "/api/mentions/webhook", params={"hub.mode": "subscribe", "hub.challenge": "12345"}
    )

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST signature validation — a refused body is never recorded
# ---------------------------------------------------------------------------


def test_post_with_valid_signature_is_recorded_then_200() -> None:
    harness = Harness()
    body = _mentions_body()

    assert harness.post(body) == 200
    # Exactly the bytes Meta signed, and the header itself (kept for later re-verification).
    assert harness.calls == [(body, _sign(body))]


def test_post_with_missing_signature_is_403_and_nothing_is_recorded() -> None:
    harness = Harness()

    assert harness.post(_mentions_body(), signature=None) == 403
    assert harness.calls == []


def test_post_with_invalid_signature_is_403_and_nothing_is_recorded() -> None:
    harness = Harness()

    assert harness.post(_mentions_body(), signature="sha256=" + "0" * 64) == 403
    assert harness.calls == []


def test_post_signed_with_the_wrong_secret_is_403_and_nothing_is_recorded() -> None:
    harness = Harness()
    body = _mentions_body()

    assert harness.post(body, signature=_sign(body, secret="not-the-real-secret")) == 403
    assert harness.calls == []


def test_post_over_the_size_limit_is_413_and_nothing_is_recorded() -> None:
    harness = Harness()
    body = b"{" + b" " * MAX_BODY_BYTES + b"}"

    assert harness.post(body) == 413
    assert harness.calls == []


# ---------------------------------------------------------------------------
# What the POST does past the signature: record, and only then 200
# ---------------------------------------------------------------------------


def test_a_failed_record_is_500_so_meta_retries(caplog: pytest.LogCaptureFixture) -> None:
    """The one behavior QUA-147 changes on purpose: a delivery that could not be recorded
    must never be acknowledged — a 200 here would lose the event for good."""
    harness = Harness(fail_with=RuntimeError("db down"))
    body = _mentions_body(ig_user_id="secret-looking-id")

    with caplog.at_level("INFO"):
        assert harness.post(body) == 500

    assert "NOT recorded" in caplog.text
    # The payload never reaches the logs, only the exception type.
    assert "secret-looking-id" not in caplog.text
    assert "db down" not in caplog.text


def test_malformed_payload_is_still_recorded_and_200() -> None:
    """Signature-valid but not an envelope: recorded (as `unparseable`, by the recorder),
    answered 200 — a retry would not fix the body."""
    harness = Harness()
    body = b'{"object": "instagram", "entry": [{"id": "111", "changes": "not-a-list"}]}'

    assert harness.post(body) == 200
    assert harness.calls == [(body, _sign(body))]


def test_a_comments_change_is_recorded_like_any_other_field() -> None:
    """The route does not filter by field: `comments` lands in the intake log too (the
    processor settles it as `unsupported` until its handler exists)."""
    harness = Harness()
    payload = {
        "object": "instagram",
        "entry": [
            {"id": "111", "changes": [{"field": "comments", "value": {"id": "c1", "text": "x"}}]}
        ],
    }
    body = json.dumps(payload).encode("utf-8")

    assert harness.post(body) == 200
    assert len(harness.calls) == 1


def test_the_request_never_resolves_a_tenant_or_ingests() -> None:
    """Structural: the mentions route module no longer exposes the inline resolver/
    ingestor seams it used before QUA-147."""
    assert not hasattr(mentions_routes, "get_tenant_resolver")
    assert not hasattr(mentions_routes, "get_mention_ingestor")
    assert not hasattr(mentions_routes, "_resolve_and_ingest")


def test_an_unconfigured_app_cannot_verify_webhooks() -> None:
    """Same posture `test_inbox_routes.test_an_unconfigured_app_cannot_talk_to_meta`
    establishes: an app nobody wired stays silent, never falls back to a real secret."""
    app = create_app(configure_production=False)
    http = TestClient(app)

    with pytest.raises(NotImplementedError, match="mentions webhook settings"):
        http.get(
            "/api/mentions/webhook",
            params={"hub.mode": "subscribe", "hub.challenge": "1", "hub.verify_token": "x"},
        )


def test_an_unwired_recorder_never_answers_200() -> None:
    app = create_app(configure_production=False)
    app.dependency_overrides[mentions_routes.get_webhook_settings] = lambda: (
        MentionsWebhookSettings(app_secret=APP_SECRET, verify_token=VERIFY_TOKEN)
    )
    http = TestClient(app)
    body = _mentions_body()

    with pytest.raises(NotImplementedError, match="delivery recorder"):
        http.post(
            "/api/mentions/webhook",
            content=body,
            headers={"X-Hub-Signature-256": _sign(body)},
        )

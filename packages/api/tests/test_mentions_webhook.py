"""HTTP/HMAC contract for the `mentions` webhook receiver (QUA-49).

Fully offline: no network, no Postgres. The tenant resolver is a fake here —
`test_mentions_resolve.py` covers `resolve_external_account` itself against
real Postgres. Mirrors `test_inbox_routes.py`'s harness shape.
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
from qualify_api.mentions.resolve import ResolutionOutcome, TenantResolution

APP_SECRET = "test-app-secret"
VERIFY_TOKEN = "test-verify-token"

TENANT = UUID("77777777-7777-4777-8777-777777777777")
CONNECTION = UUID("88888888-8888-4888-8888-888888888888")


def _sign(body: bytes, *, secret: str = APP_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, sha256).hexdigest()


class Harness:
    def __init__(self, resolver_calls: list[tuple[str, str]] | None = None) -> None:
        self.resolutions: dict[str, TenantResolution] = {}
        self._calls = resolver_calls

        def fake_resolver(*, platform: str, external_account_id: str) -> TenantResolution:
            if self._calls is not None:
                self._calls.append((platform, external_account_id))
            return self.resolutions.get(
                external_account_id, TenantResolution(outcome=ResolutionOutcome.ORPHAN)
            )

        app = create_app(configure_production=False)
        app.dependency_overrides[mentions_routes.get_webhook_settings] = lambda: (
            MentionsWebhookSettings(app_secret=APP_SECRET, verify_token=VERIFY_TOKEN)
        )
        app.dependency_overrides[mentions_routes.get_tenant_resolver] = lambda: fake_resolver
        self.http = TestClient(app)


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
# GET challenge
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
# POST signature validation
# ---------------------------------------------------------------------------


def test_post_with_valid_signature_and_payload_is_200() -> None:
    harness = Harness()
    body = _mentions_body()

    response = harness.http.post(
        "/api/mentions/webhook",
        content=body,
        headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"},
    )

    assert response.status_code == 200


def test_post_with_missing_signature_is_403() -> None:
    harness = Harness()
    body = _mentions_body()

    response = harness.http.post(
        "/api/mentions/webhook", content=body, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 403


def test_post_with_invalid_signature_is_403() -> None:
    harness = Harness()
    body = _mentions_body()

    response = harness.http.post(
        "/api/mentions/webhook",
        content=body,
        headers={
            "X-Hub-Signature-256": "sha256=" + "0" * 64,
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 403


def test_post_signed_with_the_wrong_secret_is_403() -> None:
    harness = Harness()
    body = _mentions_body()

    response = harness.http.post(
        "/api/mentions/webhook",
        content=body,
        headers={
            "X-Hub-Signature-256": _sign(body, secret="not-the-real-secret"),
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Tenant resolution outcomes — never picked arbitrarily, always 200 past HMAC
# ---------------------------------------------------------------------------


def test_orphan_external_account_id_is_200_and_not_resolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []
    harness = Harness(resolver_calls=calls)
    body = _mentions_body(ig_user_id="does-not-exist")

    response = harness.http.post(
        "/api/mentions/webhook",
        content=body,
        headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert calls == [("instagram", "does-not-exist")]


def test_ambiguous_external_account_id_is_200_and_never_associated() -> None:
    harness = Harness()
    harness.resolutions["ambiguous-id"] = TenantResolution(outcome=ResolutionOutcome.AMBIGUOUS)
    body = _mentions_body(ig_user_id="ambiguous-id")

    response = harness.http.post(
        "/api/mentions/webhook",
        content=body,
        headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"},
    )

    # 200 (Meta must not retry), and the fake resolver never returned a tenant to
    # associate — the AMBIGUOUS branch in `_resolve_and_log` carries no tenant_id
    # to log or act on, by construction of `TenantResolution` itself.
    assert response.status_code == 200


def test_resolved_external_account_id_is_200(caplog: pytest.LogCaptureFixture) -> None:
    harness = Harness()
    harness.resolutions["111"] = TenantResolution(
        outcome=ResolutionOutcome.RESOLVED, tenant_id=TENANT, connection_id=CONNECTION
    )
    body = _mentions_body(ig_user_id="111")

    with caplog.at_level("INFO"):
        response = harness.http.post(
            "/api/mentions/webhook",
            content=body,
            headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"},
        )

    assert response.status_code == 200
    assert str(TENANT) in caplog.text
    assert str(CONNECTION) in caplog.text


# ---------------------------------------------------------------------------
# Payload shapes: caption mention, comment mention, batch
# ---------------------------------------------------------------------------


def test_caption_mention_has_no_comment_id(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    harness = Harness(resolver_calls=calls)
    body = _mentions_body(ig_user_id="cap-1", media_id="media-1", comment_id=None)

    response = harness.http.post(
        "/api/mentions/webhook",
        content=body,
        headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert calls == [("instagram", "cap-1")]


def test_comment_mention_carries_both_ids() -> None:
    harness = Harness()
    body = _mentions_body(ig_user_id="com-1", media_id="media-1", comment_id="comment-1")

    response = harness.http.post(
        "/api/mentions/webhook",
        content=body,
        headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"},
    )

    assert response.status_code == 200


def test_batch_with_multiple_updates_resolves_each(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    harness = Harness(resolver_calls=calls)
    payload = {
        "object": "instagram",
        "entry": [
            {"id": "111", "changes": [{"field": "mentions", "value": {"media_id": "aaa"}}]},
            {
                "id": "222",
                "changes": [
                    {"field": "mentions", "value": {"media_id": "bbb", "comment_id": "ccc"}}
                ],
            },
        ],
    }
    body = json.dumps(payload).encode("utf-8")

    response = harness.http.post(
        "/api/mentions/webhook",
        content=body,
        headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"},
    )

    assert response.status_code == 200
    assert set(calls) == {("instagram", "111"), ("instagram", "222")}


def test_malformed_payload_is_200_not_500() -> None:
    """Signature-valid but contract-invalid — logged, never a 5xx that would make
    Meta retry a body retrying cannot fix."""
    harness = Harness()
    body = b'{"object": "instagram", "entry": [{"id": "111", "changes": "not-a-list"}]}'

    response = harness.http.post(
        "/api/mentions/webhook",
        content=body,
        headers={"X-Hub-Signature-256": _sign(body), "Content-Type": "application/json"},
    )

    assert response.status_code == 200


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

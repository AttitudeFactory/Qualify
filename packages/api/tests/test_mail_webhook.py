"""`qualify_api.mail.webhook` — the Svix signature, the settings, the envelope → intake
mapping (pure, offline) and the HTTP contract of `POST /api/mail/resend` with a fake
recorder. Plus the static guard: the signing secret is read nowhere but inside
`qualify_api/mail/`."""

from __future__ import annotations

import base64
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from qualify_api.http.app import create_app
from qualify_api.mail import routes as mail_routes
from qualify_api.mail.webhook import (
    HEADER_ID,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    MAX_EVENT_BYTES,
    OBJECT_RESEND,
    SECRET_ENV,
    ResendWebhookNotConfigured,
    ResendWebhookSettings,
    SvixHeaders,
    decode_secret,
    event_time_ms,
    expected_signature,
    parse_resend_delivery,
    resend_webhook_configured,
    verify_signature,
)
from qualify_api.webhooks.envelope import EnvelopeError
from qualify_api.webhooks.receiver import RecordedDelivery

# Low-entropy fakes on purpose (gitleaks): a 16-byte key of zeros, base64.
KEY = bytes(16)
SECRET = "whsec_" + base64.b64encode(KEY).decode()
OTHER_KEY = bytes([1]) * 16

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
TS = str(int(NOW.timestamp()))
MSG_ID = "msg_test_1"
EMAIL_ID = "11111111-1111-4111-8111-111111111111"

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MAIL_DIR = _REPO_ROOT / "packages" / "api" / "src" / "qualify_api" / "mail"
_SOURCE_DIRS = (
    _REPO_ROOT / "packages" / "api" / "src",
    _REPO_ROOT / "packages" / "shared" / "src",
    _REPO_ROOT / "packages" / "scraper" / "src",
    _REPO_ROOT / "packages" / "creative" / "src",
    _REPO_ROOT / "Qualify",
)


def body(event_type: str = "email.delivered", **data: object) -> bytes:
    payload = {
        "type": event_type,
        "created_at": "2026-10-16T12:00:00.000Z",
        "data": {
            "created_at": "2026-10-16T11:59:59.500+00:00",
            "email_id": EMAIL_ID,
            "from": "Qualify <no-reply@send.example.test>",
            "to": ["maria@example.test"],
            "subject": "Invitación",
            **data,
        },
    }
    return json.dumps(payload).encode()


def signed(raw: bytes, *, key: bytes = KEY, ts: str = TS, msg_id: str = MSG_ID) -> SvixHeaders:
    return SvixHeaders(
        message_id=msg_id,
        timestamp=ts,
        signature=f"v1,{expected_signature(key=key, message_id=msg_id, timestamp=ts, body=raw)}",
    )


# --------------------------------------------------------------------------------------
# Signature
# --------------------------------------------------------------------------------------


def test_a_valid_signature_passes() -> None:
    raw = body()
    assert verify_signature(key=KEY, headers=signed(raw), body=raw, now=NOW) is True


def test_a_rotation_with_several_entries_passes_when_any_matches() -> None:
    raw = body()
    good = signed(raw).signature
    rotated = SvixHeaders(MSG_ID, TS, f"v1,AAAA v1a,{good[3:]} {good}")
    assert verify_signature(key=KEY, headers=rotated, body=raw, now=NOW) is True
    only_bad = SvixHeaders(MSG_ID, TS, f"v1,AAAA v1a,{good[3:]} v2,{good[3:]}")
    assert verify_signature(key=KEY, headers=only_bad, body=raw, now=NOW) is False


def test_the_wrong_secret_fails() -> None:
    raw = body()
    assert verify_signature(key=OTHER_KEY, headers=signed(raw), body=raw, now=NOW) is False


def test_a_tampered_body_or_id_fails() -> None:
    raw = body()
    headers = signed(raw)
    assert verify_signature(key=KEY, headers=headers, body=raw + b" ", now=NOW) is False
    other_id = SvixHeaders("msg_other", headers.timestamp, headers.signature)
    assert verify_signature(key=KEY, headers=other_id, body=raw, now=NOW) is False


def test_a_stale_timestamp_fails_either_way() -> None:
    raw = body()
    headers = signed(raw)
    assert (
        verify_signature(key=KEY, headers=headers, body=raw, now=NOW + timedelta(minutes=5)) is True
    )
    assert (
        verify_signature(
            key=KEY, headers=headers, body=raw, now=NOW + timedelta(minutes=5, seconds=1)
        )
        is False
    )
    assert (
        verify_signature(key=KEY, headers=headers, body=raw, now=NOW - timedelta(minutes=6))
        is False
    )
    garbage = SvixHeaders(MSG_ID, "yesterday", headers.signature)
    assert verify_signature(key=KEY, headers=garbage, body=raw, now=NOW) is False


def test_missing_headers_are_none() -> None:
    assert SvixHeaders.from_headers({HEADER_ID: "a", HEADER_TIMESTAMP: TS}) is None
    assert (
        SvixHeaders.from_headers({HEADER_ID: "a", HEADER_TIMESTAMP: TS, HEADER_SIGNATURE: " "})
        is None
    )
    full = SvixHeaders.from_headers(
        {HEADER_ID: " a ", HEADER_TIMESTAMP: TS, HEADER_SIGNATURE: "v1,x"}
    )
    assert full == SvixHeaders("a", TS, "v1,x")
    assert full.for_log() == f"svix=a {TS} v1,x"


# --------------------------------------------------------------------------------------
# Settings / secret
# --------------------------------------------------------------------------------------


def test_the_secret_is_decoded_with_or_without_its_prefix() -> None:
    assert decode_secret(SECRET) == KEY
    assert decode_secret(" " + SECRET[len("whsec_") :] + "\n") == KEY
    for bad in ("", "whsec_", "whsec_not*base64", "whsec_===="):
        with pytest.raises(ResendWebhookNotConfigured):
            decode_secret(bad)


def test_settings_come_from_the_environment_and_are_loud_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SECRET_ENV, raising=False)
    assert resend_webhook_configured() is False
    with pytest.raises(ResendWebhookNotConfigured) as exc:
        ResendWebhookSettings.from_env()
    assert SECRET_ENV in str(exc.value)
    monkeypatch.setenv(SECRET_ENV, SECRET)
    assert resend_webhook_configured() is True
    settings = ResendWebhookSettings.from_env()
    raw = body()
    assert settings.verify(signed(raw), raw, now=NOW) is True
    assert settings.verify(signed(raw, key=OTHER_KEY), raw, now=NOW) is False


# --------------------------------------------------------------------------------------
# Envelope → intake
# --------------------------------------------------------------------------------------


def test_an_event_becomes_one_resend_change_keyed_by_email_id() -> None:
    parsed = parse_resend_delivery(body("email.opened"))
    assert parsed.object == OBJECT_RESEND and parsed.entry_ids == (EMAIL_ID,)
    (change,) = parsed.changes
    assert (change.object, change.entry_id, change.field) == (
        OBJECT_RESEND,
        EMAIL_ID,
        "email.opened",
    )
    assert change.entry_time == int(NOW.timestamp() * 1000)
    assert change.value["data"]["to"] == ["maria@example.test"]
    # Same body → same key (a Svix retry); another `created_at` → another change.
    assert parse_resend_delivery(body("email.opened")).changes[0].dedup_key == change.dedup_key
    later = json.loads(body("email.opened"))
    later["created_at"] = "2026-10-16T12:30:00.000Z"
    assert (
        parse_resend_delivery(json.dumps(later).encode()).changes[0].dedup_key != change.dedup_key
    )


def test_a_body_that_is_not_a_resend_event_is_an_envelope_error() -> None:
    for raw in (
        b"not json",
        b"[]",
        b'{"data": {"email_id": "x"}}',
        b'{"type": "email.sent"}',
        b'{"type": "email.sent", "data": {}}',
        b'{"type": "", "data": {"email_id": "x"}}',
    ):
        with pytest.raises(EnvelopeError):
            parse_resend_delivery(raw)


def test_event_time_reads_resend_timestamps() -> None:
    assert event_time_ms("2026-10-16T12:00:00.000Z") == int(NOW.timestamp() * 1000)
    assert event_time_ms("2026-10-16T09:00:00-03:00") == int(NOW.timestamp() * 1000)
    assert event_time_ms("2026-10-16T12:00:00") == int(NOW.timestamp() * 1000)  # naive = UTC
    assert event_time_ms("") is None and event_time_ms(None) is None
    assert event_time_ms("yesterday") is None


# --------------------------------------------------------------------------------------
# HTTP contract
# --------------------------------------------------------------------------------------

DELIVERY_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


class Harness:
    def __init__(
        self, *, recorder_raises: Exception | None = None, unconfigured: bool = False
    ) -> None:
        self.recorded: list[tuple[bytes, SvixHeaders]] = []

        def fake_recorder(*, body: bytes, headers: SvixHeaders) -> RecordedDelivery:
            if recorder_raises is not None:
                raise recorder_raises
            self.recorded.append((body, headers))
            return RecordedDelivery(
                delivery_id=DELIVERY_ID,
                duplicate_delivery=False,
                parse_status="parsed",
                changes_total=1,
                changes_new=1,
            )

        app = create_app(configure_production=False)
        if unconfigured:
            app.dependency_overrides[mail_routes.get_webhook_settings] = (
                mail_routes.build_production_resend_webhook_settings
            )
        else:
            app.dependency_overrides[mail_routes.get_webhook_settings] = lambda: (
                ResendWebhookSettings(key=KEY)
            )
        app.dependency_overrides[mail_routes.get_delivery_recorder] = lambda: fake_recorder
        self.http = TestClient(app)

    def post(self, raw: bytes, headers: SvixHeaders | None, *, drop: str | None = None):  # noqa: ANN201
        sent = {"Content-Type": "application/json"}
        if headers is not None:
            sent.update(
                {
                    HEADER_ID: headers.message_id,
                    HEADER_TIMESTAMP: headers.timestamp,
                    HEADER_SIGNATURE: headers.signature,
                }
            )
        if drop is not None:
            sent.pop(drop)
        return self.http.post("/api/mail/resend", content=raw, headers=sent)


def _fresh() -> tuple[bytes, SvixHeaders]:
    """Signed now: the route verifies against the real clock."""
    raw = body()
    ts = str(int(datetime.now(UTC).timestamp()))
    return raw, signed(raw, ts=ts)


def test_a_signed_event_is_recorded_and_answered_200() -> None:
    harness = Harness()
    raw, headers = _fresh()
    assert harness.post(raw, headers).status_code == 200
    assert harness.recorded == [(raw, headers)]


def test_bad_or_missing_signature_headers_are_401_and_write_nothing() -> None:
    harness = Harness()
    raw, headers = _fresh()
    assert harness.post(raw, signed(raw, key=OTHER_KEY, ts=headers.timestamp)).status_code == 401
    assert harness.post(raw, signed(raw)).status_code == 401  # NOW is not now: stale
    assert harness.post(raw, None).status_code == 401
    for name in (HEADER_ID, HEADER_TIMESTAMP, HEADER_SIGNATURE):
        assert harness.post(raw, headers, drop=name).status_code == 401
    assert harness.post(raw + b" ", headers).status_code == 401
    assert harness.recorded == []


def test_oversize_is_413_before_anything_else() -> None:
    harness = Harness()
    padding = b"x" * (MAX_EVENT_BYTES + 1)
    assert harness.post(padding, signed(padding)).status_code == 413
    assert harness.recorded == []


def test_a_failed_record_is_500_so_resend_retries() -> None:
    harness = Harness(recorder_raises=RuntimeError("db down"))
    raw, headers = _fresh()
    assert harness.post(raw, headers).status_code == 500


def test_an_unconfigured_secret_is_503_never_an_accepted_event(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv(SECRET_ENV, raising=False)
    harness = Harness(unconfigured=True)
    raw, headers = _fresh()
    with caplog.at_level("ERROR", logger="qualify_api.mail.routes"):
        assert harness.post(raw, headers).status_code == 503
    assert any(SECRET_ENV in rec.getMessage() for rec in caplog.records)
    assert harness.recorded == []
    # Configured → the same builder verifies for real.
    monkeypatch.setenv(SECRET_ENV, SECRET)
    assert harness.post(raw, headers).status_code == 200
    assert harness.post(raw, signed(raw, key=OTHER_KEY, ts=headers.timestamp)).status_code == 401


def test_the_default_dependencies_refuse_until_wired() -> None:
    app = create_app(configure_production=False)
    http = TestClient(app, raise_server_exceptions=False)
    raw, headers = _fresh()
    response = http.post(
        "/api/mail/resend",
        content=raw,
        headers={
            HEADER_ID: headers.message_id,
            HEADER_TIMESTAMP: headers.timestamp,
            HEADER_SIGNATURE: headers.signature,
        },
    )
    assert response.status_code == 500


# --------------------------------------------------------------------------------------
# Static guard: the signing secret is read nowhere but inside `qualify_api/mail/`.
# --------------------------------------------------------------------------------------


def _offenders(pattern: str) -> list[str]:
    regex = re.compile(pattern)
    found: list[str] = []
    for base in _SOURCE_DIRS:
        for path in base.rglob("*.py"):
            if _MAIL_DIR in path.parents:
                continue
            if regex.search(path.read_text(encoding="utf-8")):
                found.append(str(path.relative_to(_REPO_ROOT)))
    return found


def test_webhook_secret_env_var_stays_inside_mail() -> None:
    assert _offenders(r"QUALIFY_RESEND_WEBHOOK_SECRET") == []

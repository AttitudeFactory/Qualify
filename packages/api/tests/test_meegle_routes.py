"""HTTP contract of `POST /api/meegle/events` — offline, fake recorder (the real one is
`webhooks.receiver.record_delivery` with the Meegle parser, covered in
`test_meegle_intake_db.py`)."""

from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from qualify_api.http import meegle_routes
from qualify_api.http.app import create_app
from qualify_api.meegle.envelope import MAX_EVENT_BYTES
from qualify_api.meegle.receiver import SIGNATURE_PREFIX, MeegleEventSettings
from qualify_api.webhooks.receiver import RecordedDelivery

PLUGIN_ID = "MII_TEST"
TOKEN = "callback-token"

DELIVERY_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


class Harness:
    def __init__(self, *, recorder_raises: Exception | None = None) -> None:
        self.recorded: list[tuple[bytes, str]] = []

        def fake_recorder(*, body: bytes, signature: str) -> RecordedDelivery:
            if recorder_raises is not None:
                raise recorder_raises
            self.recorded.append((body, signature))
            return RecordedDelivery(
                delivery_id=DELIVERY_ID,
                duplicate_delivery=False,
                parse_status="parsed",
                changes_total=1,
                changes_new=1,
            )

        app = create_app(configure_production=False)
        app.dependency_overrides[meegle_routes.get_event_settings] = lambda: MeegleEventSettings(
            plugin_id=PLUGIN_ID, callback_token=TOKEN
        )
        app.dependency_overrides[meegle_routes.get_delivery_recorder] = lambda: fake_recorder
        self.http = TestClient(app)

    def post(self, body: bytes):  # noqa: ANN201
        return self.http.post(
            "/api/meegle/events", content=body, headers={"Content-Type": "application/json"}
        )


def test_a_signed_event_is_recorded_and_answered_200(meegle_events) -> None:  # noqa: ANN001
    harness = Harness()
    body = meegle_events.body(nodes=["state_0"])
    response = harness.post(body)
    assert response.status_code == 200
    assert harness.recorded == [(body, body.decode().split('"signature": "')[1].split('"')[0])]


def test_a_bad_signature_is_401_and_writes_nothing(meegle_events) -> None:  # noqa: ANN001
    harness = Harness()
    for body in (meegle_events.body(signature="0" * 64), b'{"data": {}}', b"not json"):
        assert harness.post(body).status_code == 401
    assert harness.recorded == []


def test_oversize_is_413_before_anything_else() -> None:
    harness = Harness()
    padding = b"x" * (MAX_EVENT_BYTES + 1)
    assert harness.post(padding).status_code == 413
    assert harness.recorded == []


def test_a_failed_record_is_500_so_meegle_retries(meegle_events) -> None:  # noqa: ANN001
    harness = Harness(recorder_raises=RuntimeError("db down"))
    assert harness.post(meegle_events.body()).status_code == 500


def test_the_default_dependencies_refuse_until_wired(meegle_events) -> None:  # noqa: ANN001
    app = create_app(configure_production=False)
    with pytest.raises(NotImplementedError):
        meegle_routes.get_event_settings()
    with pytest.raises(NotImplementedError):
        meegle_routes.get_delivery_recorder()
    # Not wired → FastAPI surfaces the NotImplementedError (no silent acceptance).
    client = TestClient(app, raise_server_exceptions=False)
    assert client.post("/api/meegle/events", content=meegle_events.body()).status_code == 500


def test_production_wiring_reads_the_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from qualify_api.http.app import (
        build_production_meegle_delivery_recorder,
        build_production_meegle_event_settings,
    )
    from qualify_api.meegle import MeegleNotConfigured
    from qualify_api.meegle.receiver import record_meegle_delivery

    for name in (
        "QUALIFY_MEEGLE_PLUGIN_ID",
        "QUALIFY_MEEGLE_PLUGIN_SECRET",
        "QUALIFY_MEEGLE_CALLBACK_TOKEN",
        "QUALIFY_MEEGLE_PROJECT_KEY",
        "QUALIFY_MEEGLE_WORK_ITEM_TYPE",
        "QUALIFY_MEEGLE_USER_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(MeegleNotConfigured):
        build_production_meegle_event_settings()
    assert build_production_meegle_delivery_recorder() is record_meegle_delivery
    assert SIGNATURE_PREFIX.startswith("meegle-")

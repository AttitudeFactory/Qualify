"""A7 — the three publishing routes, exercised end-to-end with zero network and zero DB.

The chain under test is the DEMO's chain: multipart upload → staged key → 202 attempt →
polled GET → published. Everything below the routes is real code (staging service, publish
service, in-memory attempt repository, object gate) — only the platform client, the
connection reader and the credential are fakes.
"""

from __future__ import annotations

import io
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from qualify_shared.objects.gate import ObjectGate

from qualify_api.http import deps, publishing_routes
from qualify_api.http.app import create_app
from qualify_api.publishing.client import ContainerStatus, ResumableContainer, UploadOutcome
from qualify_api.publishing.repository import MemoryPublishAttemptRepository
from qualify_api.publishing.service import ConnectionTarget, PublishService
from qualify_api.publishing.staging import MediaStagingService

TENANT = UUID("11111111-1111-4111-8111-111111111111")
USER = UUID("33333333-3333-4333-8333-333333333333")
CONNECTION = UUID("22222222-2222-4222-8222-222222222222")
AUTH = {"Authorization": "Bearer tok-pub"}


class MemoryStore:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put(self, key: str, fileobj: io.IOBase, content_type: str) -> None:
        self.objects[key] = (fileobj.read(), content_type)

    def open(self, key: str) -> io.BytesIO:
        return io.BytesIO(self.objects[key][0])


class FakePublishClient:
    def __init__(self) -> None:
        self.status_script: list[ContainerStatus] = []
        self.calls = {"create": 0, "upload": 0, "status": 0, "publish": 0}

    async def create_container(self, **kwargs: object) -> ResumableContainer:
        self.calls["create"] += 1
        return ResumableContainer(container_id="c-1", upload_uri="https://rupload/u")

    async def upload_bytes(self, **kwargs: object) -> UploadOutcome:
        self.calls["upload"] += 1
        return UploadOutcome(success=True)

    async def container_status(self, *, container_id: str) -> ContainerStatus:
        self.calls["status"] += 1
        return self.status_script.pop(0)

    async def publish_container(self, *, ig_user_id: str, creation_id: str) -> str:
        self.calls["publish"] += 1
        return "media-1"


class Harness:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("QUALIFY_DEV_PRINCIPALS", f"tok-pub:{TENANT}:{USER}")
        self.store = MemoryStore()
        self.client = FakePublishClient()
        self.repo = MemoryPublishAttemptRepository()
        gate = ObjectGate(self.store)
        harness = self

        class Connections:
            def read(self, *, tenant_id: UUID, connection_id: UUID) -> ConnectionTarget | None:
                if (tenant_id, connection_id) == (TENANT, CONNECTION):
                    return ConnectionTarget(ig_user_id="ig-9", status="active")
                return None

        class Factory:
            async def client_for(self, *, tenant_id: UUID, connection_id: UUID):
                return harness.client

        service = PublishService(
            repository=self.repo, gate=gate, connections=Connections(), client_factory=Factory()
        )
        app = create_app(configure_production=False)
        app.dependency_overrides[publishing_routes.get_publish_service] = lambda: service
        app.dependency_overrides[publishing_routes.get_staging_service] = lambda: (
            MediaStagingService(gate)
        )
        app.dependency_overrides[deps.current_principal] = deps.build_dev_principal_dependency()
        self.http = TestClient(app)

    def stage(self) -> str:
        response = self.http.post(
            "/api/media",
            files={"file": ("reel.mp4", b"reel-bytes", "video/mp4")},
            data={"connection_id": str(CONNECTION), "media_product_type": "REELS"},
            headers=AUTH,
        )
        assert response.status_code == 200, response.text
        return response.json()["media_object_key"]

    def start(self, key: str, media_key: str):
        return self.http.post(
            "/api/publishing/attempts",
            json={
                "connection_id": str(CONNECTION),
                "media_object_key": media_key,
                "media_product_type": "REELS",
                "idempotency_key": key,
            },
            headers=AUTH,
        )


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    return Harness(monkeypatch)


def test_the_demo_chain_upload_start_poll_published(harness: Harness) -> None:
    """The §1.1 sentence, minus the real platform: upload → 202 → GET until published."""
    media_key = harness.stage()
    assert media_key.startswith(f"t/{TENANT}/media/{CONNECTION}/")
    assert harness.store.objects[media_key] == (b"reel-bytes", "video/mp4")

    started = harness.start("op-demo", media_key)
    assert started.status_code == 202
    body = started.json()
    assert body["status"] == "processing" and not body["settled"]
    attempt_id = body["attempt_id"]

    harness.client.status_script = [ContainerStatus.IN_PROGRESS, ContainerStatus.FINISHED]

    first_poll = harness.http.get(f"/api/publishing/attempts/{attempt_id}", headers=AUTH).json()
    assert first_poll["container_status"] == "IN_PROGRESS" and not first_poll["settled"]
    assert first_poll["poll_interval_seconds"] == 60

    second_poll = harness.http.get(f"/api/publishing/attempts/{attempt_id}", headers=AUTH).json()
    assert second_poll["settled"] and second_poll["status"] == "published"
    assert second_poll["published_media_id"] == "media-1"


def test_each_get_is_exactly_one_status_check(harness: Harness) -> None:
    """The route never waits for the container — one advance per GET, cadence is the
    client's job."""
    media_key = harness.stage()
    attempt_id = harness.start("op-1", media_key).json()["attempt_id"]
    harness.client.status_script = [ContainerStatus.IN_PROGRESS]

    harness.http.get(f"/api/publishing/attempts/{attempt_id}", headers=AUTH)
    assert harness.client.calls["status"] == 1


def test_missing_idempotency_key_is_422_never_server_generated(harness: Harness) -> None:
    response = harness.http.post(
        "/api/publishing/attempts",
        json={
            "connection_id": str(CONNECTION),
            "media_object_key": f"t/{TENANT}/media/{CONNECTION}/m",
            "media_product_type": "REELS",
        },
        headers=AUTH,
    )
    assert response.status_code == 422
    assert harness.repo.rows == {}


def test_repeating_the_post_returns_the_same_attempt_and_publishes_nothing_new(
    harness: Harness,
) -> None:
    media_key = harness.stage()
    first = harness.start("op-same", media_key).json()
    second = harness.start("op-same", media_key).json()
    assert second["attempt_id"] == first["attempt_id"]
    assert harness.client.calls["create"] == 1
    assert harness.client.calls["upload"] == 1


def test_every_route_requires_the_principal(harness: Harness) -> None:
    unauth = [
        harness.http.post(
            "/api/media",
            files={"file": ("r.mp4", b"x", "video/mp4")},
            data={"connection_id": str(CONNECTION), "media_product_type": "REELS"},
        ),
        harness.http.post(
            "/api/publishing/attempts",
            json={
                "connection_id": str(CONNECTION),
                "media_object_key": "k",
                "media_product_type": "REELS",
                "idempotency_key": "k",
            },
        ),
        harness.http.get(f"/api/publishing/attempts/{uuid4()}"),
    ]
    assert [response.status_code for response in unauth] == [401, 401, 401]


def test_unknown_connection_and_attempt_are_404(harness: Harness) -> None:
    media_key = harness.stage()
    response = harness.http.post(
        "/api/publishing/attempts",
        json={
            "connection_id": str(uuid4()),
            "media_object_key": media_key,
            "media_product_type": "REELS",
            "idempotency_key": "k",
        },
        headers=AUTH,
    )
    assert response.status_code == 404
    assert harness.http.get(f"/api/publishing/attempts/{uuid4()}", headers=AUTH).status_code == 404


def test_request_models_carry_no_identity_fields() -> None:
    """Structural: no field through which a client could name its tenant or its user."""
    for model in (publishing_routes.StartAttemptRequest,):
        assert "tenant_id" not in model.model_fields
        assert "user_id" not in model.model_fields


def test_an_unconfigured_app_cannot_talk_to_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default dependency raises — a deployment nobody wired stays silent."""
    monkeypatch.setenv("QUALIFY_DEV_PRINCIPALS", f"tok-pub:{TENANT}:{USER}")
    app = create_app(configure_production=False)
    app.dependency_overrides[deps.current_principal] = deps.build_dev_principal_dependency()
    http = TestClient(app)
    with pytest.raises(NotImplementedError, match="publish service"):
        http.post(
            "/api/publishing/attempts",
            json={
                "connection_id": str(CONNECTION),
                "media_object_key": "k",
                "media_product_type": "REELS",
                "idempotency_key": "k",
            },
            headers=AUTH,
        )


def test_staging_rejections_map_to_client_errors(harness: Harness) -> None:
    """`PHOTO` is not a real `media_product_type` (QUA-68 legitimises `IMAGE`, not this) —
    still exactly the unpublishable-type rejection this test exists to exercise."""
    response = harness.http.post(
        "/api/media",
        files={"file": ("r.gif", b"x", "image/gif")},
        data={"connection_id": str(CONNECTION), "media_product_type": "PHOTO"},
        headers=AUTH,
    )
    assert response.status_code == 422

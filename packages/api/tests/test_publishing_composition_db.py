"""`db`-marked tests proving the write-ahead + idempotency invariants the Reflex publish
seam relies on, against REAL Postgres — R2 and Meta stay fake, local to this file (same
pattern `test_publishing_service.py`/`test_publishing_staging.py` already use).

This file does NOT go through `qualify_api.publishing.composition` — `production_publish_
service()`/`production_staging_service()` build a real `R2ObjectStore`, and there is no
R2 configured yet (Herwin has not handed over `QUALIFY_R2_*`). Instead it builds
`PublishService`/`MediaStagingService` directly, with `PostgresPublishAttemptRepository`
(real) and fake gate/client (local doubles) — proving the DB half of the chain the new
seam will rely on: idempotency and the settle-once trigger hold against the real table,
not just the `MemoryPublishAttemptRepository` double `test_publishing_service.py` proves
them against. The offline seam-wiring proof (staging happens, the platform is called
correctly) lives in `test_publishing_composition.py`.
"""

from __future__ import annotations

import io
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from qualify_shared.objects.gate import ObjectGate

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.publishing.client import ContainerStatus, ResumableContainer, UploadOutcome
from qualify_api.publishing.models import PublishAttempt
from qualify_api.publishing.repository import AlreadySettled, PostgresPublishAttemptRepository
from qualify_api.publishing.service import ConnectionTarget, PublishService
from qualify_api.publishing.staging import MediaStagingService
from qualify_api.tenancy.models import Tenant, User

pytestmark = pytest.mark.db

TENANT = UUID("90000000-0000-4000-8000-000000000009")


class MemoryStore:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put(self, key: str, fileobj: io.IOBase, content_type: str) -> None:
        self.objects[key] = (fileobj.read(), content_type)

    def open(self, key: str) -> io.BytesIO:
        return io.BytesIO(self.objects[key][0])


class FakePublishClient:
    def __init__(self, *, statuses: list[ContainerStatus] | None = None) -> None:
        self.container = ResumableContainer(container_id="c-db-1", upload_uri="https://rupload/u")
        # FINISHED (not PUBLISHED): `advance()` only calls `publish_container` — and
        # therefore only returns a media id — on FINISHED. PUBLISHED is reconciliation's
        # path, where the media id is already known from an earlier send.
        self.status_script = statuses or [ContainerStatus.FINISHED]
        self.calls = {"create": 0, "upload": 0, "status": 0, "publish": 0}

    async def create_container(self, **kwargs: object) -> ResumableContainer:
        self.calls["create"] += 1
        return self.container

    async def upload_bytes(
        self, *, upload_uri: str, fileobj: object, file_size: int
    ) -> UploadOutcome:
        self.calls["upload"] += 1
        return UploadOutcome(success=True)

    async def container_status(self, *, container_id: str) -> ContainerStatus:
        self.calls["status"] += 1
        return self.status_script.pop(0)

    async def publish_container(self, *, ig_user_id: str, creation_id: str) -> str:
        self.calls["publish"] += 1
        return "media-db-1"


@pytest.fixture
def connected_ig_account() -> UUID:
    """An `active` connection, provisioned like `test_connections_revoke_db.py`'s fixture:
    infra rows via `admin_session`, the connection itself via `tenant_session` — the door
    publishing really uses, so a grant/RLS defect surfaces here instead of being masked."""
    with admin_session() as session:
        if session.get(Tenant, TENANT) is None:
            session.add(
                Tenant(
                    id=TENANT,
                    name="t-publish",
                    country="CO",
                    timezone="America/Bogota",
                    currency="COP",
                )
            )
            session.flush()
        app = PlatformApp(app_id=f"app-publish-{uuid4()}", secret_ref="ref", api_version="v21.0")
        session.add(app)
        session.flush()
        user = User(tenant_id=TENANT, email=f"u-{uuid4()}@t.co", display_name="U")
        session.add(user)
        session.flush()
        app_id, user_id = app.id, user.id

    with tenant_session(TENANT) as session:
        connection = SocialConnection(
            tenant_id=TENANT,
            platform_app_id=app_id,
            platform="instagram",
            account_type="business",
            # Unique per fixture invocation — this is a real, persistent Postgres
            # (docker-compose), not a per-test transaction rollback, so a fixed literal
            # here would collide with `uq_conn_natural_key` on the second test.
            external_account_id=f"ig-{uuid4()}",
            linked_page_id="page-1",
            granted_scopes=["basic"],
            status="active",
            access_posture="development",
            current_credential_version=1,
            connected_by_user_id=user_id,
        )
        session.add(connection)
        session.flush()
        return connection.id


def _service(client: FakePublishClient, store: MemoryStore, connection_id: UUID) -> PublishService:
    class Connections:
        def read(self, *, tenant_id: UUID, connection_id: UUID) -> ConnectionTarget | None:
            # The fake client never checks this value against anything — only the
            # connection's `status` (checked by `PublishService.start`) matters here.
            return ConnectionTarget(ig_user_id="ig-fake-user", status="active")

    class Factory:
        async def client_for(self, *, tenant_id: UUID, connection_id: UUID) -> FakePublishClient:
            return client

    return PublishService(
        repository=PostgresPublishAttemptRepository(),
        gate=ObjectGate(store),
        connections=Connections(),
        client_factory=Factory(),
    )


@pytest.mark.asyncio
async def test_start_and_advance_persist_through_postgres_end_to_end(
    connected_ig_account: UUID,
) -> None:
    connection_id = connected_ig_account
    store = MemoryStore()
    staging = MediaStagingService(ObjectGate(store))
    staged = staging.stage_media(
        tenant_id=TENANT,
        connection_id=connection_id,
        media_id=uuid4().hex,
        fileobj=io.BytesIO(b"reel-bytes"),
        content_type="video/mp4",
        media_product_type="REELS",
    )
    client = FakePublishClient(statuses=[ContainerStatus.FINISHED])
    service = _service(client, store, connection_id)

    started = await service.start(
        tenant_id=TENANT,
        connection_id=connection_id,
        media_object_key=staged.media_object_key,
        media_product_type="REELS",
        idempotency_key=f"db-op-{uuid4()}",
    )
    assert started.status == "processing" and not started.settled

    settled = await service.advance(tenant_id=TENANT, attempt_id=started.attempt_id)
    assert settled.settled and settled.status == "published"
    assert settled.published_media_id == "media-db-1"


@pytest.mark.asyncio
async def test_idempotent_start_returns_the_same_row_against_postgres(
    connected_ig_account: UUID,
) -> None:
    connection_id = connected_ig_account
    store = MemoryStore()
    staging = MediaStagingService(ObjectGate(store))
    client = FakePublishClient()
    service = _service(client, store, connection_id)
    key = f"db-idem-{uuid4()}"

    def _stage() -> str:
        return staging.stage_media(
            tenant_id=TENANT,
            connection_id=connection_id,
            media_id=uuid4().hex,
            fileobj=io.BytesIO(b"reel-bytes"),
            content_type="video/mp4",
            media_product_type="REELS",
        ).media_object_key

    first = await service.start(
        tenant_id=TENANT,
        connection_id=connection_id,
        media_object_key=_stage(),
        media_product_type="REELS",
        idempotency_key=key,
    )
    second = await service.start(
        tenant_id=TENANT,
        connection_id=connection_id,
        media_object_key=_stage(),
        media_product_type="REELS",
        idempotency_key=key,
    )

    assert second.attempt_id == first.attempt_id
    assert client.calls["create"] == 1

    with tenant_session(TENANT) as session:
        rows = session.query(PublishAttempt).filter_by(idempotency_key=key).all()
        assert len(rows) == 1  # `uq_attempt_idempotency` — one row, not two


def test_settle_once_trigger_refuses_a_second_settle_against_real_postgres(
    connected_ig_account: UUID,
) -> None:
    """Proves the DB-owned invariant `service.py`'s module docstring leans on: the
    `publish_attempts_settle_once` trigger, not application code, is what makes a second
    settle impossible — even called directly against the repository, bypassing the
    service's own read-before-settle logic entirely."""
    connection_id = connected_ig_account
    repo = PostgresPublishAttemptRepository()
    start = repo.start_attempt(
        tenant_id=TENANT,
        connection_id=connection_id,
        idempotency_key=f"db-settle-{uuid4()}",
        media_product_type="REELS",
        adapter_version="qua19.1",
    )
    repo.settle(
        tenant_id=TENANT,
        attempt_id=start.record.id,
        status="published",
        published_media_id="media-once",
    )

    with pytest.raises(AlreadySettled):
        repo.settle(
            tenant_id=TENANT,
            attempt_id=start.record.id,
            status="failed",
            platform_error_code="should_never_land",
        )

    with tenant_session(TENANT) as session:
        row = session.get(PublishAttempt, start.record.id)
        assert row is not None
        assert row.status == "published"  # the first settle's outcome, untouched

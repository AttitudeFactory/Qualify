"""Only Instagram is publishable from «Publicar» (founder, 2026-11-12).

`PublishService.start` / `start_many` and the composition seams `stage_and_start_publish` /
`stage_and_start_many_publish` must refuse a WhatsApp or Facebook connection BEFORE any byte
is staged to R2, any `publish_attempts` row is written or any Graph client is built. Also
pins the one-source-of-truth contract between `publishing.platforms` and the Planificador,
and the retry / identical-files idempotency the sequential «Una por una» batch relies on.

Fully offline: in-memory repository, store and fakes; no Meta, no R2, no Postgres.
"""

from __future__ import annotations

import io
from uuid import UUID

import pytest
from qualify_shared.objects.gate import ObjectGate

from qualify_api import publishing
from qualify_api.planner import publishable as planner_publishable
from qualify_api.planner import service as planner_service
from qualify_api.publishing import composition
from qualify_api.publishing.client import ContainerStatus, ResumableContainer, UploadOutcome
from qualify_api.publishing.composition import PendingUpload
from qualify_api.publishing.platforms import (
    PLATFORM_INSTAGRAM,
    PUBLISHABLE_PLATFORMS,
    UnsupportedPlatform,
)
from qualify_api.publishing.repository import MemoryPublishAttemptRepository
from qualify_api.publishing.service import (
    ConnectionTarget,
    MediaItem,
    PublishService,
    UnknownConnection,
)
from qualify_api.publishing.staging import MediaStagingService

TENANT = UUID("12121212-1212-4212-8212-121212121212")
CONNECTION = UUID("34343434-3434-4343-8343-343434343434")
OTHER_CONNECTION = UUID("56565656-5656-4565-8565-565656565656")
IG_USER = "17840000000000099"
REJECTED_PLATFORMS = ("whatsapp", "facebook", "tiktok")


class MemoryStore:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put(self, key: str, fileobj: io.IOBase, content_type: str) -> None:
        self.objects[key] = (fileobj.read(), content_type)

    def open(self, key: str) -> io.BytesIO:
        return io.BytesIO(self.objects[key][0])


class FakePublishClient:
    def __init__(self) -> None:
        self.calls: dict[str, int] = {"create": 0, "upload": 0}

    async def create_container(self, **kwargs: object) -> ResumableContainer:
        self.calls["create"] += 1
        return ResumableContainer(
            container_id=f"c-{self.calls['create']}", upload_uri="https://rupload/u"
        )

    async def upload_bytes(
        self, *, upload_uri: str, fileobj: object, file_size: int
    ) -> UploadOutcome:
        self.calls["upload"] += 1
        return UploadOutcome(success=True)

    async def container_status(self, *, container_id: str) -> ContainerStatus:
        return ContainerStatus.IN_PROGRESS


class Wiring:
    """A real `PublishService` + `MediaStagingService` over fakes, with counters on every
    side effect the guard must prevent: client construction, R2 writes, attempt rows."""

    def __init__(self, platform: str) -> None:
        self.store = MemoryStore()
        self.repo = MemoryPublishAttemptRepository()
        self.client = FakePublishClient()
        self.client_for_calls = 0
        wiring = self

        class Connections:
            def read(self, *, tenant_id: UUID, connection_id: UUID) -> ConnectionTarget | None:
                if (tenant_id, connection_id) != (TENANT, CONNECTION):
                    return None
                return ConnectionTarget(ig_user_id=IG_USER, status="active", platform=platform)

        class Factory:
            async def client_for(
                self, *, tenant_id: UUID, connection_id: UUID
            ) -> FakePublishClient:
                wiring.client_for_calls += 1
                return wiring.client

        self.service = PublishService(
            repository=self.repo,
            gate=ObjectGate(self.store),
            connections=Connections(),
            client_factory=Factory(),
        )
        self.staging = MediaStagingService(ObjectGate(self.store))

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(composition, "production_publish_service", lambda: self.service)
        monkeypatch.setattr(composition, "production_staging_service", lambda: self.staging)

    def assert_untouched(self) -> None:
        assert self.store.objects == {}, "nothing may be staged to R2"
        assert self.repo.rows == {}, "no publish_attempts row may be written"
        assert self.client_for_calls == 0, "no Graph client may be built"
        assert self.client.calls == {"create": 0, "upload": 0}


def _media_key() -> str:
    return f"t/{TENANT}/media/{CONNECTION}/m-1"


# --- the shared constant ------------------------------------------------------------------


def test_publishable_platforms_is_instagram_only() -> None:
    assert PUBLISHABLE_PLATFORMS == frozenset({PLATFORM_INSTAGRAM})
    assert PLATFORM_INSTAGRAM == "instagram"


def test_planner_uses_the_same_set_object_not_a_copy() -> None:
    assert planner_publishable.SCHEDULABLE_PLATFORMS is PUBLISHABLE_PLATFORMS
    assert planner_service.SCHEDULABLE_PLATFORMS is PUBLISHABLE_PLATFORMS
    assert planner_publishable.PLATFORM_INSTAGRAM is PLATFORM_INSTAGRAM


def test_the_error_is_exported_from_the_package() -> None:
    assert publishing.UnsupportedPlatform is UnsupportedPlatform
    assert publishing.PUBLISHABLE_PLATFORMS is PUBLISHABLE_PLATFORMS


# --- PublishService ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_accepts_instagram() -> None:
    wiring = Wiring(PLATFORM_INSTAGRAM)
    wiring.store.objects[_media_key()] = (b"reel", "video/mp4")

    state = await wiring.service.start(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        media_object_key=_media_key(),
        media_product_type="REELS",
        idempotency_key="k-1",
    )

    assert state.status == "processing"
    assert wiring.client.calls["create"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", REJECTED_PLATFORMS)
async def test_start_rejects_a_non_instagram_connection_before_any_write(platform: str) -> None:
    wiring = Wiring(platform)

    with pytest.raises(UnsupportedPlatform) as raised:
        await wiring.service.start(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            media_object_key=_media_key(),
            media_product_type="REELS",
            idempotency_key="k-1",
        )

    assert raised.value.platform == platform
    assert raised.value.connection_id == CONNECTION
    wiring.assert_untouched()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["whatsapp", "facebook"])
async def test_start_many_rejects_a_non_instagram_connection_before_any_write(
    platform: str,
) -> None:
    wiring = Wiring(platform)
    items = [
        MediaItem(
            media_object_key=f"{_media_key()}-{i}", content_type="video/mp4", media_type="VIDEO"
        )
        for i in range(3)
    ]

    with pytest.raises(UnsupportedPlatform):
        await wiring.service.start_many(
            tenant_id=TENANT, connection_id=CONNECTION, items=items, idempotency_key="k-1"
        )

    wiring.assert_untouched()


def test_require_publishable_connection_keeps_unknown_connection_distinct() -> None:
    wiring = Wiring("whatsapp")

    with pytest.raises(UnknownConnection):
        wiring.service.require_publishable_connection(
            tenant_id=TENANT, connection_id=OTHER_CONNECTION
        )


# --- composition seams (the entry points the UI calls) ------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["whatsapp", "facebook"])
async def test_stage_and_start_publish_rejects_before_staging(
    monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    wiring = Wiring(platform)
    wiring.install(monkeypatch)

    with pytest.raises(UnsupportedPlatform):
        await composition.stage_and_start_publish(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            fileobj=io.BytesIO(b"\xff\xd8\xff\xe0jpeg"),
            content_type="image/jpeg",
            media_product_type="STORIES",
            idempotency_key="k-1",
        )

    wiring.assert_untouched()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["whatsapp", "facebook"])
async def test_stage_and_start_many_publish_rejects_before_staging(
    monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    wiring = Wiring(platform)
    wiring.install(monkeypatch)
    items = [
        PendingUpload(fileobj=io.BytesIO(b"v"), content_type="video/mp4", media_type="VIDEO")
        for _ in range(2)
    ]

    with pytest.raises(UnsupportedPlatform):
        await composition.stage_and_start_many_publish(
            tenant_id=TENANT, connection_id=CONNECTION, items=items, idempotency_key="k-1"
        )

    wiring.assert_untouched()


@pytest.mark.asyncio
async def test_stage_and_start_publish_accepts_instagram(monkeypatch: pytest.MonkeyPatch) -> None:
    wiring = Wiring(PLATFORM_INSTAGRAM)
    wiring.install(monkeypatch)

    state = await composition.stage_and_start_publish(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        fileobj=io.BytesIO(b"reel"),
        content_type="video/mp4",
        media_product_type="REELS",
        idempotency_key="k-1",
    )

    assert state.status == "processing"
    assert len(wiring.store.objects) == 1


# --- idempotency of a sequential, UI-driven batch («Una por una», one story per file) ----


@pytest.mark.asyncio
async def test_a_retried_item_is_neither_restaged_nor_republished(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wiring = Wiring(PLATFORM_INSTAGRAM)
    wiring.install(monkeypatch)

    async def call() -> object:
        return await composition.stage_and_start_publish(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            fileobj=io.BytesIO(b"reel"),
            content_type="video/mp4",
            media_product_type="REELS",
            idempotency_key="batch-1:item-0",
            caption="Hola",
        )

    first = await call()
    second = await call()

    assert second.attempt_id == first.attempt_id
    assert len(wiring.store.objects) == 1, "the retry must not upload the bytes again"
    assert len(wiring.repo.rows) == 1
    assert wiring.client.calls["create"] == 1


@pytest.mark.asyncio
async def test_identical_files_with_distinct_keys_are_two_publications(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Idempotency is keyed on the caller's key, never on content: two byte-identical
    files with the same caption in one batch are two separate publications."""
    wiring = Wiring(PLATFORM_INSTAGRAM)
    wiring.install(monkeypatch)

    states = [
        await composition.stage_and_start_publish(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            fileobj=io.BytesIO(b"same-bytes"),
            content_type="video/mp4",
            media_product_type="REELS",
            idempotency_key=f"batch-1:item-{k}",
            caption="Mismo texto",
        )
        for k in range(2)
    ]

    assert states[0].attempt_id != states[1].attempt_id
    assert len(wiring.repo.rows) == 2
    assert wiring.client.calls["create"] == 2

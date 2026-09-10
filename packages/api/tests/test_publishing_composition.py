"""Offline tests for the publishing composition seam added for the Reflex vertical slice
(`stage_and_start_publish`/`advance_publish` — the publishing analogue of
`connections/composition.py`'s `start_connect`/`revoke_connection`).

Fully offline: `production_publish_service`/`production_staging_service` are monkeypatched
to return real `PublishService`/`MediaStagingService` instances wired to in-memory fakes,
same doubles `test_publishing_service.py`/`test_publishing_staging.py` already use. This
file proves the NEW seam wires those real services together correctly — staging happens
before the platform is ever touched, the server mints the media id, idempotency survives
the extra layer — not their internal logic again (that is already covered).
"""

from __future__ import annotations

import io
from uuid import UUID

import pytest
from qualify_shared.objects.gate import ObjectGate

from qualify_api.publishing import composition
from qualify_api.publishing.client import ContainerStatus, ResumableContainer, UploadOutcome
from qualify_api.publishing.repository import MemoryPublishAttemptRepository
from qualify_api.publishing.service import ConnectionTarget, PublishService, TooManyItems
from qualify_api.publishing.staging import MediaStagingService

TENANT = UUID("77777777-7777-4777-8777-777777777777")
CONNECTION = UUID("88888888-8888-4888-8888-888888888888")
IG_USER = "17840000000000002"


class MemoryStore:
    """In-memory `(key, bytes, content_type)` sink — same double every publishing test
    file defines locally, deliberately not shared (see `staging.py`'s module docstring:
    each test doubles the store rather than this package growing a fallback)."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put(self, key: str, fileobj: io.IOBase, content_type: str) -> None:
        self.objects[key] = (fileobj.read(), content_type)

    def open(self, key: str) -> io.BytesIO:
        return io.BytesIO(self.objects[key][0])


class FakePublishClient:
    """Programmable platform double that counts calls — same shape as
    `test_publishing_service.py`'s, kept local rather than imported (that file's double
    is not part of any package's public surface)."""

    def __init__(self) -> None:
        self.container = ResumableContainer(container_id="c-1", upload_uri="https://rupload/u")
        # QUA-99 (5/6): distinct child containers, one per create_container call, so a
        # multi-item test can tell them apart — see test_publishing_service.py's own
        # `container_sequence` for the same reasoning.
        self.container_sequence: list[ResumableContainer] = [
            ResumableContainer(container_id=f"child-c-{i}", upload_uri=f"https://rupload/{i}")
            for i in range(10)
        ]
        self.calls = {"create": 0, "upload": 0, "status": 0, "publish": 0, "create_carousel": 0}
        self.carousel_calls: list[list[str]] = []
        self.carousel_caption_calls: list[str | None] = []

    async def create_container(self, **kwargs: object) -> ResumableContainer:
        self.calls["create"] += 1
        if kwargs.get("is_carousel_item"):
            return self.container_sequence.pop(0)
        return self.container

    async def create_carousel_container(
        self, *, ig_user_id: str, children: list[str], caption: str | None = None
    ) -> str:
        self.calls["create_carousel"] += 1
        self.carousel_calls.append(list(children))
        self.carousel_caption_calls.append(caption)
        return "carousel-1"

    async def upload_bytes(
        self, *, upload_uri: str, fileobj: object, file_size: int
    ) -> UploadOutcome:
        self.calls["upload"] += 1
        return UploadOutcome(success=True)

    async def container_status(self, *, container_id: str) -> ContainerStatus:
        self.calls["status"] += 1
        # FINISHED (not PUBLISHED) so `advance()` takes the path that calls
        # `publish_container` and returns a media id — matching what a fresh publish
        # actually looks like (PUBLISHED is reconciliation's path, media id already known).
        return ContainerStatus.FINISHED

    async def publish_container(self, *, ig_user_id: str, creation_id: str) -> str:
        self.calls["publish"] += 1
        return "media-1"


def _wire(
    monkeypatch: pytest.MonkeyPatch, *, connection_status: str = "active"
) -> tuple[MemoryStore, FakePublishClient]:
    store = MemoryStore()
    client = FakePublishClient()

    class Connections:
        def read(self, *, tenant_id: UUID, connection_id: UUID) -> ConnectionTarget | None:
            if (tenant_id, connection_id) != (TENANT, CONNECTION):
                return None
            return ConnectionTarget(ig_user_id=IG_USER, status=connection_status)

    class Factory:
        async def client_for(self, *, tenant_id: UUID, connection_id: UUID) -> FakePublishClient:
            return client

    service = PublishService(
        repository=MemoryPublishAttemptRepository(),
        gate=ObjectGate(store),
        connections=Connections(),
        client_factory=Factory(),
    )
    staging = MediaStagingService(ObjectGate(store))

    monkeypatch.setattr(composition, "production_publish_service", lambda: service)
    monkeypatch.setattr(composition, "production_staging_service", lambda: staging)
    return store, client


@pytest.mark.asyncio
async def test_stage_and_start_publish_stages_before_touching_the_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, client = _wire(monkeypatch)

    state = await composition.stage_and_start_publish(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        fileobj=io.BytesIO(b"reel-bytes"),
        content_type="video/mp4",
        media_product_type="REELS",
        idempotency_key="op-1",
    )

    assert state.status == "processing" and not state.settled
    assert len(store.objects) == 1
    assert client.calls["create"] == 1


@pytest.mark.asyncio
async def test_media_id_is_minted_by_the_seam_never_accepted_from_the_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same server-owns-the-identifier invariant `publishing_routes.py:105` enforces over
    HTTP: two separate calls stage under two DIFFERENT keys, so nothing the caller passed
    (there is nothing to pass — `stage_and_start_publish` has no `media_id` parameter)
    could ever collide two attempts' media."""
    store, _ = _wire(monkeypatch)

    await composition.stage_and_start_publish(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        fileobj=io.BytesIO(b"a"),
        content_type="video/mp4",
        media_product_type="REELS",
        idempotency_key="op-a",
    )
    await composition.stage_and_start_publish(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        fileobj=io.BytesIO(b"b"),
        content_type="video/mp4",
        media_product_type="REELS",
        idempotency_key="op-b",
    )

    assert len(store.objects) == 2


@pytest.mark.asyncio
async def test_stage_and_start_publish_is_idempotent_by_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`PublishService.start()`'s idempotency survives the extra staging step in front of
    it: a retry with the same key still touches the platform exactly once, even though
    this seam stages (wastefully, but harmlessly) before `start()` ever sees the key."""
    store, client = _wire(monkeypatch)

    first = await composition.stage_and_start_publish(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        fileobj=io.BytesIO(b"reel-bytes"),
        content_type="video/mp4",
        media_product_type="REELS",
        idempotency_key="same-key",
    )
    second = await composition.stage_and_start_publish(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        fileobj=io.BytesIO(b"reel-bytes-retry"),
        content_type="video/mp4",
        media_product_type="REELS",
        idempotency_key="same-key",
    )

    assert second.attempt_id == first.attempt_id
    assert client.calls["create"] == 1


@pytest.mark.asyncio
async def test_stage_and_start_publish_refuses_a_dead_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, client = _wire(monkeypatch, connection_status="revoked")

    state = await composition.stage_and_start_publish(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        fileobj=io.BytesIO(b"reel-bytes"),
        content_type="video/mp4",
        media_product_type="REELS",
        idempotency_key="op-1",
    )

    assert state.settled and state.status == "failed"
    assert client.calls == {
        "create": 0,
        "upload": 0,
        "status": 0,
        "publish": 0,
        "create_carousel": 0,
    }


@pytest.mark.asyncio
async def test_advance_publish_calls_the_wired_service(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(monkeypatch)

    started = await composition.stage_and_start_publish(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        fileobj=io.BytesIO(b"reel-bytes"),
        content_type="video/mp4",
        media_product_type="REELS",
        idempotency_key="op-1",
    )

    state = await composition.advance_publish(tenant_id=TENANT, attempt_id=started.attempt_id)

    assert state.settled and state.status == "published"
    assert state.published_media_id == "media-1"


# --------------------------------------------------------------------------------------
# QUA-99 (5/6) — stage_and_start_many_publish, the multi-video counterpart
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stage_and_start_many_publish_stages_every_item_before_the_carousel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, client = _wire(monkeypatch)

    state = await composition.stage_and_start_many_publish(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        items=[
            composition.PendingUpload(fileobj=io.BytesIO(b"video-a"), content_type="video/mp4"),
            composition.PendingUpload(
                fileobj=io.BytesIO(b"video-b"), content_type="video/quicktime"
            ),
        ],
        idempotency_key="op-multi-1",
    )

    assert not state.settled
    assert len(store.objects) == 2  # both staged, exactly like the single-item path
    # start_many() only writes ahead (QUA-99 4/6) — child CONTAINERS are created later,
    # one per advance() call, never synchronously inside this seam.
    assert client.calls == {
        "create": 0,
        "upload": 0,
        "status": 0,
        "publish": 0,
        "create_carousel": 0,
    }
    children = composition.production_publish_service()._repo.list_children(  # noqa: SLF001
        tenant_id=TENANT, attempt_id=state.attempt_id
    )
    assert len(children) == 2


@pytest.mark.asyncio
async def test_stage_and_start_many_publish_preserves_order_and_content_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The staged `media_object_key`s must reach `PublishService.start_many` as
    `MediaItem`s in the SAME order the caller supplied them — that order becomes
    `position`, which becomes the carousel's display order on Instagram."""
    _, _ = _wire(monkeypatch)
    seen_items: list[list] = []
    real_start_many = PublishService.start_many

    async def spy_start_many(self, **kwargs):
        seen_items.append(list(kwargs["items"]))
        return await real_start_many(self, **kwargs)

    monkeypatch.setattr(PublishService, "start_many", spy_start_many)

    await composition.stage_and_start_many_publish(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        items=[
            composition.PendingUpload(fileobj=io.BytesIO(b"first"), content_type="video/mp4"),
            composition.PendingUpload(
                fileobj=io.BytesIO(b"second"), content_type="video/quicktime"
            ),
        ],
        idempotency_key="op-order-1",
    )

    (items,) = seen_items
    assert [i.content_type for i in items] == ["video/mp4", "video/quicktime"]
    assert len({i.media_object_key for i in items}) == 2  # two distinct staged keys


@pytest.mark.asyncio
async def test_stage_and_start_many_publish_forwards_the_caption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _wire(monkeypatch)

    state = await composition.stage_and_start_many_publish(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        items=[
            composition.PendingUpload(fileobj=io.BytesIO(b"a"), content_type="video/mp4"),
            composition.PendingUpload(fileobj=io.BytesIO(b"b"), content_type="video/mp4"),
        ],
        idempotency_key="op-caption-1",
        caption="una descripcion del carrusel",
    )

    record = composition.production_publish_service()._repo.get_attempt(  # noqa: SLF001
        tenant_id=TENANT, attempt_id=state.attempt_id
    )
    assert record is not None and record.caption == "una descripcion del carrusel"


@pytest.mark.asyncio
async def test_stage_and_start_many_publish_is_idempotent_by_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _wire(monkeypatch)

    def _items() -> list[composition.PendingUpload]:
        # Fresh BytesIO per call — the first call's staging already consumed the first
        # set (reading a fileobj is destructive), same as a real retry would re-read a
        # fresh upload, not reuse an already-drained buffer.
        return [
            composition.PendingUpload(fileobj=io.BytesIO(b"a"), content_type="video/mp4"),
            composition.PendingUpload(fileobj=io.BytesIO(b"b"), content_type="video/mp4"),
        ]

    first = await composition.stage_and_start_many_publish(
        tenant_id=TENANT, connection_id=CONNECTION, items=_items(), idempotency_key="same-key"
    )
    second = await composition.stage_and_start_many_publish(
        tenant_id=TENANT, connection_id=CONNECTION, items=_items(), idempotency_key="same-key"
    )

    assert second.attempt_id == first.attempt_id
    # The second call stages (wastefully but harmlessly, same note the single-item
    # idempotency test already makes) but PublishService.start_many's own idempotency
    # (QUA-99 4/6, add_child per (attempt_id, position)) must still converge to 2 rows,
    # never 4 — and never reach the carousel step, which this seam alone never triggers.
    children = composition.production_publish_service()._repo.list_children(  # noqa: SLF001
        tenant_id=TENANT, attempt_id=first.attempt_id
    )
    assert len(children) == 2


@pytest.mark.asyncio
async def test_stage_and_start_many_publish_rejects_more_than_ten_before_staging_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The count guard is checked in THIS seam too (not only inside PublishService.
    start_many) so an 11-item request never stages a single byte to R2 before failing."""
    store, client = _wire(monkeypatch)
    items = [
        composition.PendingUpload(fileobj=io.BytesIO(f"v{i}".encode()), content_type="video/mp4")
        for i in range(11)
    ]

    with pytest.raises(TooManyItems):
        await composition.stage_and_start_many_publish(
            tenant_id=TENANT, connection_id=CONNECTION, items=items, idempotency_key="op-11"
        )

    assert store.objects == {}  # nothing staged
    assert client.calls == {
        "create": 0,
        "upload": 0,
        "status": 0,
        "publish": 0,
        "create_carousel": 0,
    }


@pytest.mark.asyncio
async def test_stage_and_start_many_publish_with_one_item_uses_the_single_video_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No IMAGE path, no parallel machinery: a single item routed through the MULTI
    entry point must still land on the exact same REELS behaviour QUA-19 already has —
    `PublishService.start_many` decides this internally (QUA-99 4/6), this seam does not
    special-case the count."""
    _, client = _wire(monkeypatch)

    state = await composition.stage_and_start_many_publish(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        items=[composition.PendingUpload(fileobj=io.BytesIO(b"solo"), content_type="video/mp4")],
        idempotency_key="op-solo-1",
    )

    assert state.status == "processing" and not state.settled
    assert client.calls["create_carousel"] == 0
    record = composition.production_publish_service()._repo.get_attempt(  # noqa: SLF001
        tenant_id=TENANT, attempt_id=state.attempt_id
    )
    assert record is not None and record.media_product_type == "REELS"


def test_production_publish_service_is_cached() -> None:
    # `functools.cache`-wrapped callables expose `cache_clear`/`cache_info` — a plain
    # function does not. Not calling it: no R2 configured in this offline test run.
    assert hasattr(composition.production_publish_service, "cache_clear")


def test_production_staging_service_is_cached() -> None:
    assert hasattr(composition.production_staging_service, "cache_clear")

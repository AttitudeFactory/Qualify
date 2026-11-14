"""`db` tests for the planner's own upload (m-25026384, `creative.own_upload`): the whole
life of the piece over real Postgres — written approved with provenance, idempotent
(twice, concurrently), listed as ready by `list_schedulable`, scheduled to each
destination the acceptance criterion names, and published by the executor at its hour
from the uploads prefix (only Meta and R2 are fakes; nothing is written to R2). Also: it
charges nothing, refuses a brand of another tenant, and writes nothing when refused.

Each test provisions its own tenant through `admin_session`; everything under test runs
through `tenant_session`.
"""

from __future__ import annotations

import asyncio
import io
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from qualify_shared.objects.gate import ObjectGate
from sqlalchemy import func, select

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.consumption.models import ConsumptionLedger
from qualify_api.creative import models as creative
from qualify_api.creative.own_upload import (
    PIPELINE_VERSION,
    OwnUpload,
    OwnUploadRefused,
    UploadRefusal,
    record_planner_upload,
    upload_request_key,
)
from qualify_api.planner.composition import PostgresConnectionGate
from qualify_api.planner.draft_post_reader import DraftPostReader
from qualify_api.planner.executor import EventExecutor, ExecutionOutcome
from qualify_api.planner.gallery import GalleryState, gallery_state
from qualify_api.planner.locks import PostgresAdvisoryLock
from qualify_api.planner.repository import PostgresPlannerRepository
from qualify_api.planner.service import PlannerService, UnsupportedDestination
from qualify_api.publishing.client import ResumableContainer, UploadOutcome
from qualify_api.publishing.composition import PostgresConnectionTargetReader
from qualify_api.publishing.repository import PostgresPublishAttemptRepository
from qualify_api.publishing.service import PublishService
from qualify_api.tenancy.models import Brand, Tenant, TenantMember, User

pytestmark = pytest.mark.db


@dataclass(frozen=True)
class World:
    tenant_id: UUID
    brand_id: UUID
    user_id: UUID
    connection_id: UUID


def _world() -> World:
    tenant_id = uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant_id,
                name=f"own-upload-{tenant_id}",
                country="VE",
                timezone="America/Caracas",
                currency="USD",
            )
        )
        session.flush()
        brand = Brand(tenant_id=tenant_id, name="Bianki")
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        user = User(tenant_id=tenant_id, email=f"o-{uuid4()}@p.co", display_name="Owner")
        session.add_all([brand, app, user])
        session.flush()
        session.add(TenantMember(tenant_id=tenant_id, user_id=user.id, role="owner"))
        session.flush()
        brand_id, app_id, user_id = brand.id, app.id, user.id
    with tenant_session(tenant_id) as session:
        conn = SocialConnection(
            tenant_id=tenant_id,
            brand_id=brand_id,
            platform_app_id=app_id,
            platform="instagram",
            account_type="business",
            external_account_id=f"ig-{uuid4()}",
            linked_page_id="page-1",
            granted_scopes=["basic"],
            status="active",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=user_id,
        )
        session.add(conn)
        session.flush()
        connection_id = conn.id
    return World(tenant_id, brand_id, user_id, connection_id)


def _upload_key(world: World, name: str = "foto.jpg") -> str:
    """Where `Qualify/upload_store.save_upload*` writes (`owner_uploads.new_upload_key`)."""
    return f"t/{world.tenant_id}/uploads/{uuid4().hex}_{name}"


def _image(world: World, **overrides: object) -> OwnUpload:
    fields: dict[str, object] = {
        "upload_id": uuid4(),
        "object_key": _upload_key(world),
        "media_type": "image",
        "content_type": "image/jpeg",
        "caption": "Shawarma mixto 🌯\n\n¡Hoy 2x1!",
        "width": 1080,
        "height": 1350,
        "size_bytes": 900_000,
    }
    fields.update(overrides)
    return OwnUpload(**fields)  # type: ignore[arg-type]


def _video(world: World, **overrides: object) -> OwnUpload:
    fields: dict[str, object] = {
        "upload_id": uuid4(),
        "object_key": _upload_key(world, "clip.mp4"),
        "media_type": "video",
        "content_type": "video/mp4",
        "caption": "",
        "width": 1080,
        "height": 1920,
        "duration_seconds": 14.2,
        "poster_object_key": _upload_key(world, "portada.jpg"),
    }
    fields.update(overrides)
    return OwnUpload(**fields)  # type: ignore[arg-type]


def _record(world: World, upload: OwnUpload):
    return record_planner_upload(
        tenant_id=world.tenant_id,
        brand_id=world.brand_id,
        user_id=world.user_id,
        upload=upload,
    )


def _drafts(world: World) -> int:
    with tenant_session(world.tenant_id) as session:
        return session.scalar(select(func.count()).select_from(creative.ContentDraft)) or 0


def _service(clock=lambda: datetime.now(UTC)) -> PlannerService:
    return PlannerService(
        repository=PostgresPlannerRepository(),
        posts=DraftPostReader(),
        connections=PostgresConnectionGate(),
        clock=clock,
    )


# -- the piece ---------------------------------------------------------------------------


def test_an_image_upload_is_an_approved_reusable_own_piece_with_provenance() -> None:
    world = _world()
    upload = _image(world)
    piece = _record(world, upload)
    assert piece.created and piece.category.value == "galeria"
    with tenant_session(world.tenant_id) as session:
        draft = session.get(creative.ContentDraft, piece.draft_id)
        assert draft is not None
        assert (draft.status, draft.revision, draft.approved_revision) == ("approved", 1, 1)
        assert draft.approved_by == world.user_id and draft.approved_at is not None
        assert draft.pipeline_version == PIPELINE_VERSION
        assert draft.request_key == upload_request_key(upload.upload_id)
        assert draft.reuse_type == "recurrente" and draft.category == "galeria"
        assert draft.title == "Shawarma mixto 🌯" and draft.preview_key == upload.object_key
        brief = session.get(creative.ContentBrief, draft.brief_id)
        assert brief is not None and brief.kind == "own_media"
        assert brief.image_route == "from_upload" and brief.format == "feed_4_5"
        version = session.get(creative.PieceVersion, draft.active_version_id)
        assert version is not None and version.model_id == "owner"
        assert version.pipeline_version == PIPELINE_VERSION
        asset = session.scalars(
            select(creative.ImageAsset).where(creative.ImageAsset.draft_id == draft.id)
        ).one()
        assert (asset.object_key, asset.content_type, asset.media_type) == (
            upload.object_key,
            "image/jpeg",
            "image",
        )
        assert (asset.width, asset.height, asset.model_id) == (1080, 1350, "owner")
        assert asset.params == {
            "source": "planner_upload",
            "pipeline_version": PIPELINE_VERSION,
            "source_ref": str(upload.upload_id),
        }


def test_a_video_upload_is_a_reel_with_its_poster_and_a_neutral_title() -> None:
    world = _world()
    upload = _video(world)
    piece = _record(world, upload)
    assert piece.category.value == "reel"
    with tenant_session(world.tenant_id) as session:
        draft = session.get(creative.ContentDraft, piece.draft_id)
        assert draft is not None and draft.title == "Video subido por ti"
        assert draft.preview_key == upload.poster_object_key
        asset = session.scalars(
            select(creative.ImageAsset).where(creative.ImageAsset.draft_id == draft.id)
        ).one()
        assert asset.params["thumbnail_key"] == upload.poster_object_key
        assert asset.params["duration_seconds"] == 14.2


def test_the_same_upload_twice_or_concurrently_is_one_piece() -> None:
    world = _world()
    upload = _image(world)
    first = _record(world, upload)
    again = _record(world, upload)
    assert first.created and not again.created and again.draft_id == first.draft_id
    other = _image(world)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: _record(world, other), range(4)))
    assert len({result.draft_id for result in results}) == 1
    assert sum(result.created for result in results) == 1
    assert _drafts(world) == 2


def test_a_refused_upload_or_a_brand_of_another_tenant_writes_nothing() -> None:
    world, stranger = _world(), _world()
    with pytest.raises(OwnUploadRefused) as caught:
        _record(world, _image(world, object_key=_upload_key(stranger)))
    assert caught.value.code is UploadRefusal.NOT_THIS_TENANT
    with pytest.raises(OwnUploadRefused) as caught:
        _record(world, _image(world, content_type="image/png"))
    assert caught.value.code is UploadRefusal.UNSUPPORTED_CONTENT_TYPE
    with pytest.raises(OwnUploadRefused) as caught:
        record_planner_upload(
            tenant_id=world.tenant_id,
            brand_id=stranger.brand_id,
            user_id=world.user_id,
            upload=_image(world),
        )
    assert caught.value.code is UploadRefusal.UNKNOWN_BRAND
    assert _drafts(world) == 0 and _drafts(stranger) == 0


def test_an_upload_charges_nothing() -> None:
    world = _world()
    _record(world, _image(world))
    _record(world, _video(world))
    with tenant_session(world.tenant_id) as session:
        charges = session.scalar(select(func.count()).select_from(creative.CreationCharge))
        ledger = session.scalar(select(func.count()).select_from(ConsumptionLedger))
    assert (charges, ledger) == (0, 0)


# -- schedulable --------------------------------------------------------------------------


def test_the_piece_is_ready_in_list_schedulable_and_the_gallery() -> None:
    world = _world()
    image = _record(world, _image(world))
    video = _record(world, _video(world))
    service = _service()
    cards = {
        card.post_id: card
        for card in service.list_schedulable(tenant_id=world.tenant_id, brand_id=world.brand_id)
    }
    assert set(cards) == {image.draft_id, video.draft_id}
    photo, clip = cards[image.draft_id], cards[video.draft_id]
    assert photo.is_publishable and photo.unpublishable_reason == ""
    assert (photo.media_types, photo.image_size, photo.content_kind) == (
        ("IMAGE",),
        (1080, 1350),
        "own_media",
    )
    assert photo.media_product_type == "IMAGE" and photo.title == "Shawarma mixto 🌯"
    assert clip.is_publishable and clip.media_types == ("VIDEO",)
    # m-25026481: the stored length reaches the selector's rule; an image has none
    assert (clip.video_seconds, photo.video_seconds) == (14.2, None)
    assert clip.media_product_type == "REELS" and clip.video_object_key is not None
    assert photo.thumbnail_url is not None and photo.thumbnail_url.startswith(
        f"t/{world.tenant_id}/uploads/"
    )
    for card in (photo, clip):
        assert gallery_state(card) is GalleryState.SCHEDULABLE
        # own media is exempt from the 90 days (ADR 39 amendment): no state, no deadline
        assert (card.retention_state, card.purge_deadline) == ("", None)
    unscheduled = service.list_unscheduled(tenant_id=world.tenant_id, brand_id=world.brand_id)
    assert {card.post_id for card in unscheduled} == {image.draft_id, video.draft_id}


@pytest.mark.parametrize(
    ("kind", "allowed", "refused"),
    [("image", ("post", "story"), ("reel",)), ("video", ("reel", "story"), ("post",))],
)
def test_each_destination_of_the_criterion_can_be_scheduled(
    kind: str, allowed: tuple[str, ...], refused: tuple[str, ...]
) -> None:
    world = _world()
    piece = _record(world, _image(world) if kind == "image" else _video(world))
    service = _service()
    start = datetime.now(UTC) + timedelta(days=1)
    for offset, destination in enumerate(allowed):
        event = service.schedule(
            tenant_id=world.tenant_id,
            brand_id=world.brand_id,
            post_id=piece.draft_id,
            connection_id=world.connection_id,
            scheduled_at=start + timedelta(hours=offset),
            scheduled_tz="America/Caracas",
            user_id=world.user_id,
            destination=destination,
        )
        assert (event.status, event.destination, event.post_id) == (
            "scheduled",
            destination,
            piece.draft_id,
        )
    for destination in refused:
        with pytest.raises(UnsupportedDestination):
            service.schedule(
                tenant_id=world.tenant_id,
                brand_id=world.brand_id,
                post_id=piece.draft_id,
                connection_id=world.connection_id,
                scheduled_at=start + timedelta(hours=5),
                scheduled_tz="America/Caracas",
                user_id=world.user_id,
                destination=destination,
            )


def test_a_tall_photo_is_a_story_and_cannot_be_scheduled_as_publicacion() -> None:
    world = _world()
    piece = _record(world, _image(world, width=1080, height=1920))
    assert piece.category.value == "story"
    service = _service()
    when = datetime.now(UTC) + timedelta(days=1)
    kwargs = {
        "tenant_id": world.tenant_id,
        "brand_id": world.brand_id,
        "post_id": piece.draft_id,
        "connection_id": world.connection_id,
        "scheduled_tz": "America/Caracas",
        "user_id": world.user_id,
    }
    assert service.schedule(scheduled_at=when, destination="story", **kwargs).destination == (
        "story"
    )
    with pytest.raises(UnsupportedDestination):
        service.schedule(scheduled_at=when + timedelta(hours=1), destination="post", **kwargs)


# -- published at its hour ----------------------------------------------------------------


class _Meta:
    """Meta stand-in: records what the publisher asked for, never calls anything."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    async def create_image_container(self, *, ig_user_id, image_url, caption=None, **kw):
        self.calls.append(("image", kw.get("media_type")))
        return f"c-{uuid4().hex}"

    async def create_container(self, *, ig_user_id, media_type, caption=None, **_):
        self.calls.append(("video", media_type))
        return ResumableContainer(container_id=f"c-{uuid4().hex}", upload_uri="https://u/x")

    async def upload_bytes(self, *, upload_uri, fileobj, file_size):
        return UploadOutcome(success=True)


class _Clients:
    def __init__(self, meta: _Meta) -> None:
        self._meta = meta

    async def client_for(self, *, tenant_id, connection_id):
        return self._meta


class _ReadOnlyR2:
    """R2 stand-in: reads only, and remembers which keys were opened. Never writes."""

    def __init__(self) -> None:
        self.opened: list[str] = []

    def put(self, key, fileobj, content_type) -> None:  # pragma: no cover - never called
        raise AssertionError("the executor never writes to R2")

    def open(self, key):
        self.opened.append(key)
        return io.BytesIO(b"\x00" * 64)


class _Linker:
    def __init__(self) -> None:
        self.linked: list[tuple[str, str]] = []

    def link(self, *, tenant_id: UUID, object_key: str, content_type: str) -> str:
        self.linked.append((object_key, content_type))
        return f"https://example.invalid/public/media/{uuid4().hex}"


@pytest.mark.parametrize(
    ("kind", "destination", "expected_call"),
    [
        ("image", "post", ("image", None)),
        ("image", "story", ("image", "STORIES")),
        ("video", "reel", ("video", "REELS")),
        ("video", "story", ("video", "STORIES")),
    ],
)
def test_the_executor_publishes_the_upload_at_its_hour(
    kind: str, destination: str, expected_call: tuple[str, str | None]
) -> None:
    world = _world()
    upload = _image(world) if kind == "image" else _video(world)
    piece = _record(world, upload)
    now = datetime.now(UTC)
    # planned a few minutes ago for a minute ago: due now
    event = _service(clock=lambda: now - timedelta(minutes=10)).schedule(
        tenant_id=world.tenant_id,
        brand_id=world.brand_id,
        post_id=piece.draft_id,
        connection_id=world.connection_id,
        scheduled_at=now - timedelta(minutes=1),
        scheduled_tz="America/Caracas",
        user_id=world.user_id,
        destination=destination,
    )
    meta, store, linker = _Meta(), _ReadOnlyR2(), _Linker()
    executor = EventExecutor(
        repository=PostgresPlannerRepository(),
        posts=DraftPostReader(),
        publisher=PublishService(
            repository=PostgresPublishAttemptRepository(),
            gate=ObjectGate(store),
            connections=PostgresConnectionTargetReader(),
            client_factory=_Clients(meta),
            media_linker=linker,
        ),
        attempts=PostgresPublishAttemptRepository(),
        lock=PostgresAdvisoryLock(),
        connections=PostgresConnectionGate(),
    )
    result = asyncio.run(executor.try_execute(event))
    assert result.outcome is ExecutionOutcome.STARTED, result
    assert meta.calls == [expected_call]
    if kind == "image":
        assert linker.linked == [(upload.object_key, "image/jpeg")] and store.opened == []
    else:
        assert store.opened == [upload.object_key] and linker.linked == []
    stored = PostgresPlannerRepository().get(tenant_id=world.tenant_id, event_id=event.id)
    assert stored is not None and stored.status == "publishing"
    assert stored.publish_attempt_id == result.attempt_id


# -- view-only (m-25019220) is never a planner upload, and vice versa ----------------------


def _published_event(world: World, post_id: UUID) -> None:
    """A past `published` event of the piece, as if it already went out once."""
    from qualify_api.planner.models import CalendarEvent  # noqa: PLC0415

    with tenant_session(world.tenant_id) as session:
        session.add(
            CalendarEvent(
                tenant_id=world.tenant_id,
                brand_id=world.brand_id,
                post_id=post_id,
                connection_id=world.connection_id,
                scheduled_at=datetime.now(UTC) - timedelta(days=2),
                scheduled_tz="America/Caracas",
                status="published",
                revision=1,
                created_by_user_id=world.user_id,
                destination="post",
                goals=[],
            )
        )


def test_a_planner_upload_is_never_view_only_even_after_it_went_out() -> None:
    """View-only = kind `own_media` AND `reuse_type` `promocional`
    (`Qualify/creative_vm.is_view_only_upload`; backend: `gallery.is_reusable`). A
    planner upload is `recurrente`, so it stays plannable once published."""
    world = _world()
    piece = _record(world, _image(world))
    _published_event(world, piece.draft_id)
    [card] = _service().list_schedulable(tenant_id=world.tenant_id, brand_id=world.brand_id)
    assert card.reuse_type == "recurrente" and card.content_kind == "own_media"
    assert card.is_publishable and card.times_published == 1
    assert gallery_state(card) is GalleryState.SCHEDULABLE


def test_a_view_only_backfilled_piece_stays_one_shot_with_the_merged_writer() -> None:
    """The backfill's override (`publish_backfill`: `promocional` + match params) still
    writes what main writes after our fields were added — and is never re-offered."""
    from qualify_creative.enums import ContentFormat, PostCategory, ReuseType  # noqa: PLC0415

    from qualify_api.creative.own_media import (  # noqa: PLC0415
        OwnMediaItem,
        OwnMediaPiece,
        create_own_media_piece,
        request_key_for,
    )

    world = _world()
    key = f"t/{world.tenant_id}/media/{world.connection_id}/{uuid4()}"
    with tenant_session(world.tenant_id) as session:
        draft_id, _ = create_own_media_piece(
            session,
            tenant_id=world.tenant_id,
            piece=OwnMediaPiece(
                brand_id=world.brand_id,
                user_id=world.user_id,
                caption="Ya salió",
                category=PostCategory.GALERIA,
                format=ContentFormat.FEED_4_5,
                approved_at=datetime.now(UTC),
                items=(OwnMediaItem(key, "image/jpeg", "image", 0),),
                request_key=request_key_for(uuid4()),
                pipeline_version="publish-backfill-test",
                reuse_type=ReuseType.PROMOCIONAL,
                asset_params=(("match", "instagram_copy"),),
            ),
        )
        asset = session.scalars(
            select(creative.ImageAsset).where(creative.ImageAsset.draft_id == draft_id)
        ).one()
        assert asset.params == {
            "source": "publish_now",
            "pipeline_version": "publish-backfill-test",
            "match": "instagram_copy",
        }
    _published_event(world, draft_id)
    [card] = _service().list_schedulable(tenant_id=world.tenant_id, brand_id=world.brand_id)
    assert card.reuse_type == "promocional"
    assert gallery_state(card) is GalleryState.USED

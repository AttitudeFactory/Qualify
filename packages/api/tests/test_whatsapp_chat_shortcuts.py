"""m-24945889 — WhatsApp chat shortcuts, offline: «Promoción de la semana» (one per
business, held by the ADR 39 retention), «Cómo llegar» (a location message with a point,
the address with a maps link without one, only on the owner's tap), video pieces (MP4 up
to 16 MB) and the daily cleanup of the picker's temporary R2 copies.

No DB, no network, no R2: in-memory repositories, a fake gate and a fake client.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from qualify_api.creative.retention import RetentionFacts, RetentionState, evaluate
from qualify_api.whatsapp.attachments import (
    MAX_VIDEO_BYTES,
    AttachmentRefused,
    ChatAttachmentService,
    MemoryAttachmentReads,
    MemoryBlobStore,
    PieceRow,
)
from qualify_api.whatsapp.chats import ChatService, MemoryChatRepository, WindowClosed
from qualify_api.whatsapp.client import build_location_body
from qualify_api.whatsapp.directions import (
    DirectionsService,
    LocationInvalid,
    MemoryLocationStore,
    maps_link,
)
from qualify_api.whatsapp.optins import MemoryOptInRepository, OptInService
from qualify_api.whatsapp.outbound_purge import OUTBOUND_TTL, purge_chat_outbound
from qualify_api.whatsapp.outbox import MemoryOutboxRepository, OutboxSender
from qualify_api.whatsapp.promotions import (
    MemoryPromotionRepository,
    PromotionNotAllowed,
    WeeklyPromotionService,
)

NOW = datetime(2026, 11, 8, 15, 0, tzinfo=UTC)
TENANT = UUID("a0000000-0000-4000-8000-000000945889")
OTHER_TENANT = UUID("b0000000-0000-4000-8000-000000945889")
BRAND = UUID("c0000000-0000-4000-8000-000000945889")
OTHER_BRAND = UUID("c1000000-0000-4000-8000-000000945889")
CONN = UUID("d0000000-0000-4000-8000-000000945889")
USER = UUID("e0000000-0000-4000-8000-000000945889")
WA_ID = "584240000000"
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64


class World:
    def __init__(self) -> None:
        self.chat_repo = MemoryChatRepository()
        self.outbox = MemoryOutboxRepository(clock=lambda: NOW)
        self.chats = ChatService(self.chat_repo, self.outbox, clock=lambda: NOW)
        self.reads = MemoryAttachmentReads()
        self.reads.brands[(TENANT, CONN)] = BRAND
        self.blobs = MemoryBlobStore()
        self.attachments = ChatAttachmentService(self.chats, self.reads, self.blobs)
        self.promotions = WeeklyPromotionService(
            MemoryPromotionRepository(), self.reads, clock=lambda: NOW
        )
        self.locations = MemoryLocationStore()
        self.locations.add_number(tenant_id=TENANT, connection_id=CONN)
        self.directions = DirectionsService(self.chats, self.locations, clock=lambda: NOW)

    def thread(self, *, inbound_ago: timedelta = timedelta(hours=1)) -> UUID:
        thread_id = self.chat_repo.add_thread(tenant_id=TENANT, connection_id=CONN, wa_id=WA_ID)
        self.chat_repo.add_message(
            thread_id=thread_id,
            direction="inbound",
            text_value="¿dónde quedan?",
            posted_at=NOW - inbound_ago,
        )
        self.outbox.threads[thread_id] = NOW - inbound_ago
        return thread_id

    def piece(
        self,
        *,
        status: str = "approved",
        media_type: str = "image",
        content: bytes = b"\x89PNG",
        brand: UUID = BRAND,
        tenant: UUID = TENANT,
    ) -> UUID:
        draft_id = uuid4()
        ext = "mp4" if media_type == "video" else "png"
        key = f"t/{tenant}/generated/{draft_id}/r1/feed.{ext}"
        self.reads.piece_rows[draft_id] = (
            tenant,
            PieceRow(
                id=draft_id,
                brand_id=brand,
                status=status,
                title="Martes 2x1",
                text="Ven por tu combo.",
                image_key=key,
                image_count=1,
                created_at=NOW - timedelta(days=1),
                media_type=media_type,
                poster_key=f"t/{tenant}/generated/{draft_id}/r1/poster.jpg"
                if media_type == "video"
                else None,
            ),
        )
        self.blobs.objects[(tenant, key)] = content
        return draft_id

    def only_row(self):
        assert len(self.outbox.rows) == 1
        return next(iter(self.outbox.rows.values()))


@pytest.fixture
def world() -> World:
    return World()


# --- «Promoción de la semana» -------------------------------------------------------------


def test_one_promotion_per_business_and_marking_another_replaces_it(world: World) -> None:
    first, second = world.piece(), world.piece(status="published")
    world.promotions.mark_weekly_promotion(
        tenant_id=TENANT, brand_id=BRAND, draft_id=first, user_id=USER
    )
    marked = world.promotions.mark_weekly_promotion(
        tenant_id=TENANT, brand_id=BRAND, draft_id=second, user_id=USER
    )
    current = world.promotions.get_weekly_promotion(tenant_id=TENANT, brand_id=BRAND)
    assert current == marked and current.draft_id == second and current.marked_at == NOW
    assert world.promotions.unmark_weekly_promotion(tenant_id=TENANT, brand_id=BRAND)
    assert world.promotions.get_weekly_promotion(tenant_id=TENANT, brand_id=BRAND) is None


def test_only_an_approved_piece_of_that_business_can_be_the_promotion(world: World) -> None:
    unapproved = world.piece(status="generated")
    foreign = world.piece(brand=OTHER_BRAND)
    other_tenant = world.piece(tenant=OTHER_TENANT)
    with pytest.raises(PromotionNotAllowed) as refused:
        world.promotions.mark_weekly_promotion(
            tenant_id=TENANT, brand_id=BRAND, draft_id=unapproved, user_id=USER
        )
    assert "Aprueba la pieza" in refused.value.message
    for draft_id in (foreign, other_tenant, uuid4()):
        with pytest.raises(PromotionNotAllowed):
            world.promotions.mark_weekly_promotion(
                tenant_id=TENANT, brand_id=BRAND, draft_id=draft_id, user_id=USER
            )
    assert world.promotions.get_weekly_promotion(tenant_id=TENANT, brand_id=BRAND) is None


def test_a_marked_piece_is_held_like_a_scheduled_one() -> None:
    """ADR 39: `read_facts` marks a promoted piece `held` (db test); held → never EXPIRED."""
    old = NOW - timedelta(days=300)
    assert evaluate(RetentionFacts(generated_at=old), NOW).state is RetentionState.EXPIRED
    assert evaluate(RetentionFacts(generated_at=old, held=True), NOW).state is RetentionState.HELD


# --- «Cómo llegar» -------------------------------------------------------------------------


def test_with_a_point_the_chat_sends_a_location_message(world: World) -> None:
    world.directions.set_location(
        tenant_id=TENANT,
        connection_id=CONN,
        latitude="7.894123",
        longitude=-72.503456,
        name="Bianki",
        address="Av. 5 #12-34, Cúcuta",
    )
    item = world.directions.send_directions(TENANT, world.thread(), USER, request_key="k1")
    row = world.only_row()
    assert row.id == item and row.kind == "reply" and row.payload["type"] == "location"
    assert row.payload["location"] == {
        "latitude": 7.894123,
        "longitude": -72.503456,
        "name": "Bianki",
        "address": "Av. 5 #12-34, Cúcuta",
    }
    assert row.attachment == {
        "kind": "directions",
        "mode": "location",
        "pipeline": "wa-directions-1",
    }
    # The same tap twice queues once.
    world.directions.send_directions(TENANT, row.thread_id, USER, request_key="k1")
    assert len(world.outbox.rows) == 1


def test_without_a_point_the_address_goes_with_a_maps_link(world: World) -> None:
    world.directions.set_address(
        tenant_id=TENANT, connection_id=CONN, address="Av. 5 #12-34, Cúcuta"
    )
    world.directions.send_directions(TENANT, world.thread(), USER)
    body = world.only_row().payload["text"]["body"]
    assert body == (
        "Estamos en Av. 5 #12-34, Cúcuta.\n"
        "https://maps.google.com/?q=Av.%205%20%2312-34%2C%20C%C3%BAcuta"
    )
    assert maps_link("a b&c") == "https://maps.google.com/?q=a%20b%26c"


def test_without_point_or_address_nothing_is_sent(world: World) -> None:
    with pytest.raises(AttachmentRefused) as refused:
        world.directions.send_directions(TENANT, world.thread(), USER)
    assert refused.value.reason == "no_location" and world.outbox.rows == {}


def test_directions_respect_the_24_hour_window(world: World) -> None:
    world.directions.set_address(tenant_id=TENANT, connection_id=CONN, address="Av. 5")
    with pytest.raises(WindowClosed):
        world.directions.send_directions(
            TENANT, world.thread(inbound_ago=timedelta(hours=25)), USER
        )
    assert world.outbox.rows == {}


def test_the_point_is_validated_and_cleared(world: World) -> None:
    for lat, lng in ((91, 0), (0, 181), ("x", 0)):
        with pytest.raises(LocationInvalid):
            world.directions.set_location(
                tenant_id=TENANT, connection_id=CONN, latitude=lat, longitude=lng
            )
    world.directions.set_location(
        tenant_id=TENANT, connection_id=CONN, latitude=1, longitude=2, address="Av. 5"
    )
    cleared = world.directions.clear_location(tenant_id=TENANT, connection_id=CONN)
    assert not cleared.has_point and cleared.address == "Av. 5"
    with pytest.raises(ValueError):
        build_location_body(WA_ID, 95, 0, None, None)
    location = world.directions.get_location(tenant_id=TENANT, connection_id=CONN)
    assert location.latitude is None and location.updated_at == NOW
    assert Decimal("1.000000") != location.latitude  # cleared, not kept


# --- video pieces ---------------------------------------------------------------------------


def test_video_pieces_are_listed_with_their_size(world: World) -> None:
    small = world.piece(media_type="video", content=MP4)
    big = world.piece(media_type="video", content=MP4 + b"\x00" * MAX_VIDEO_BYTES)
    picks = {UUID(p.id): p for p in world.attachments.list_pieces_for_chat(TENANT, BRAND)}
    assert picks[small].media_type == "video" and picks[small].bytes == len(MP4)
    assert picks[small].too_large is False and picks[small].thumb_key.endswith("poster.jpg")
    assert picks[big].too_large is True


def test_a_video_piece_goes_as_a_whatsapp_video(world: World) -> None:
    draft_id = world.piece(media_type="video", content=MP4)
    world.attachments.send_piece(TENANT, world.thread(), USER, draft_id, "Mira el combo.")
    row = world.only_row()
    assert row.payload["type"] == "video" and row.payload["video"] == {"caption": "Mira el combo."}
    att = row.attachment
    assert (att["content_type"], att["media_type"], att["draft_id"]) == (
        "video/mp4",
        "video",
        str(draft_id),
    )
    assert att["object_key"].startswith(f"t/{TENANT}/whatsapp/outbound/{CONN}/")
    assert att["object_key"].endswith(".mp4") and att["filename"].endswith(".mp4")


class _CountingBlobs(MemoryBlobStore):
    def __init__(self) -> None:
        super().__init__()
        self.reads = 0

    def read(self, tenant_id: UUID, key: str) -> bytes:
        self.reads += 1
        return super().read(tenant_id, key)


def test_a_video_over_16_mb_is_refused_before_it_is_read(world: World) -> None:
    world.blobs = _CountingBlobs()
    world.attachments = ChatAttachmentService(world.chats, world.reads, world.blobs)
    draft_id = world.piece(media_type="video", content=MP4 + b"\x00" * MAX_VIDEO_BYTES)
    with pytest.raises(AttachmentRefused) as refused:
        world.attachments.send_piece(TENANT, world.thread(), USER, draft_id, "")
    assert refused.value.reason == "video_too_large" and world.blobs.reads == 0
    assert world.outbox.rows == {}


def test_a_file_that_is_not_an_mp4_is_refused(world: World) -> None:
    draft_id = world.piece(media_type="video", content=b"not a video at all, really")
    with pytest.raises(AttachmentRefused) as refused:
        world.attachments.send_piece(TENANT, world.thread(), USER, draft_id, "")
    assert refused.value.reason == "not_a_video"


async def test_the_sender_uploads_the_video_once(world: World) -> None:
    draft_id = world.piece(media_type="video", content=MP4)
    world.attachments.send_piece(TENANT, world.thread(), USER, draft_id, "")
    uploads: list[str] = []
    payloads: list[dict[str, Any]] = []

    class Client:
        async def upload_media(self, content: bytes, content_type: str, filename: str) -> str:
            uploads.append(content_type)
            return "media-v"

        async def send_payload(self, payload: dict[str, Any]) -> str:
            payloads.append(payload)
            return "wamid.v"

    class Source:
        def read(self, tenant_id: UUID, key: str) -> bytes:
            return world.blobs.read(tenant_id, key)

    async def factory(**_: Any) -> Client:
        return Client()

    sender = OutboxSender(
        world.outbox,
        factory,
        lambda **_: None,
        worker_id="t",
        opt_ins=OptInService(MemoryOptInRepository(), clock=lambda: NOW),
        clock=lambda: NOW,
        attachments=Source(),
    )
    assert (await sender.run_once(TENANT)).sent == 1
    assert uploads == ["video/mp4"] and payloads[0]["video"]["id"] == "media-v"


# --- the picker's temporary R2 copies -----------------------------------------------------


@dataclass
class _Obj:
    key: str
    size: int
    last_modified: datetime | None


class FakeGate:
    def __init__(self, objects: list[_Obj], refuse: bool = False) -> None:
        self.objects = objects
        self.deleted: list[str] = []
        self.refuse = refuse

    def list_chat_outbound(self, tenant_id: UUID) -> list[_Obj]:
        return list(self.objects)

    def delete_chat_outbound(self, tenant_id: UUID, object_keys: list[str]) -> None:
        if self.refuse:
            from qualify_shared.objects.gate import DeleteRefused

            raise DeleteRefused(len(object_keys), ("ObjectLockedByBucketPolicy",))
        self.deleted.extend(object_keys)


def _key(name: str) -> str:
    return f"t/{TENANT}/whatsapp/outbound/{CONN}/{name}"


def test_used_copies_leave_and_the_in_flight_or_young_ones_stay() -> None:
    old = NOW - OUTBOUND_TTL - timedelta(hours=1)
    gate = FakeGate(
        [
            _Obj(_key("sent.jpg"), 10, old),
            _Obj(_key("queued.jpg"), 10, old),
            _Obj(_key("young.jpg"), 10, NOW - timedelta(hours=3)),
            _Obj(_key("no-date.jpg"), 10, None),
        ]
    )
    report = purge_chat_outbound(
        tenant_id=TENANT,
        gate=gate,
        in_flight=lambda tenant_id: {_key("queued.jpg")},
        now=NOW,
        execute=True,
    )
    assert gate.deleted == [_key("sent.jpg")]
    assert (report.found, report.kept, report.deleted) == (4, 3, [_key("sent.jpg")])


def test_a_dry_run_deletes_nothing() -> None:
    old = NOW - OUTBOUND_TTL - timedelta(hours=1)
    gate = FakeGate([_Obj(_key("sent.jpg"), 10, old)])
    report = purge_chat_outbound(
        tenant_id=TENANT, gate=gate, in_flight=lambda t: set(), now=NOW, execute=False
    )
    assert gate.deleted == [] and report.deleted == [_key("sent.jpg")]


def test_the_bucket_lock_is_reported_not_raised() -> None:
    old = NOW - OUTBOUND_TTL - timedelta(hours=1)
    gate = FakeGate([_Obj(_key("sent.jpg"), 10, old)], refuse=True)
    report = purge_chat_outbound(
        tenant_id=TENANT, gate=gate, in_flight=lambda t: set(), now=NOW, execute=True
    )
    assert report.refused and report.deleted == []


# --- review: the transcript and the streamed size check -----------------------------------


def test_a_sent_pin_never_shows_as_an_empty_bubble(world: World) -> None:
    world.directions.set_location(
        tenant_id=TENANT, connection_id=CONN, latitude=1, longitude=2, name="Bianki"
    )
    world.directions.send_directions(TENANT, world.thread(), USER)
    row = world.only_row()
    assert row.preview_text == "Ubicación: Bianki"
    row.status, row.locked_by = "sending", "t"
    world.outbox.mark_sent(tenant_id=TENANT, item_id=row.id, wamid="wamid.loc", now=NOW)
    assert world.outbox.messages[-1].text == "Ubicación: Bianki"


def test_a_pin_without_name_or_address_still_says_what_it_was(world: World) -> None:
    world.directions.set_location(tenant_id=TENANT, connection_id=CONN, latitude=1, longitude=2)
    world.directions.send_directions(TENANT, world.thread(), USER)
    assert world.only_row().preview_text == "Ubicación enviada"


class _UnsizedBlobs(MemoryBlobStore):
    """An old local key: the size is unknown, so only a bounded read may happen."""

    def __init__(self) -> None:
        super().__init__()
        self.limits: list[int] = []

    def size(self, tenant_id: UUID, key: str) -> int | None:
        return None

    def read(self, tenant_id: UUID, key: str) -> bytes:  # pragma: no cover - must not run
        raise AssertionError("a video of unknown size is never read whole")

    def read_limited(self, tenant_id: UUID, key: str, limit: int) -> bytes:
        self.limits.append(limit)
        return super().read_limited(tenant_id, key, limit)


def test_a_video_of_unknown_size_is_read_only_up_to_the_limit(world: World) -> None:
    world.blobs = _UnsizedBlobs()
    world.attachments = ChatAttachmentService(world.chats, world.reads, world.blobs)
    big = world.piece(media_type="video", content=MP4 + b"\x00" * MAX_VIDEO_BYTES)
    with pytest.raises(AttachmentRefused) as refused:
        world.attachments.send_piece(TENANT, world.thread(), USER, big, "")
    assert refused.value.reason == "video_too_large"
    assert world.blobs.limits == [MAX_VIDEO_BYTES + 1]
    small = world.piece(media_type="video", content=MP4)
    world.attachments.send_piece(TENANT, world.thread(), USER, small, "")
    assert world.only_row().payload["type"] == "video"

"""m-24976894 — sending a seasonal sticker or short video from a WhatsApp chat, offline:
what is queued (sticker alone, video with an optional caption), the owner-side
refusals, the request-key replay, and the sender's send-time re-check (archived, no
longer approved, stale attempt, foreign business key) and its single upload."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from qualify_api.whatsapp.chats import ChatService, MemoryChatRepository, WindowClosed
from qualify_api.whatsapp.client import WhatsAppApiError, build_sticker_body
from qualify_api.whatsapp.optins import MemoryOptInRepository, OptInService
from qualify_api.whatsapp.outbox import MemoryOutboxRepository, OutboxSender
from qualify_api.whatsapp.seasonal import (
    MemorySeasonalRepository,
    MemorySourceReads,
    SeasonalMediaService,
)
from qualify_api.whatsapp.seasonal_send import (
    STICKER_SENT_TEXT,
    SeasonalSendGuard,
    SeasonalSendRefused,
    SeasonalSendService,
    send_time_refusal,
    weight_label,
)

NOW = datetime(2026, 11, 8, 15, 0, tzinfo=UTC)
TENANT = UUID("a0000000-0000-4000-8000-000000976894")
OTHER_TENANT = UUID("b0000000-0000-4000-8000-000000976894")
BRAND = UUID("c0000000-0000-4000-8000-000000976894")
OTHER_BRAND = UUID("c1000000-0000-4000-8000-000000976894")
CONN = UUID("d0000000-0000-4000-8000-000000976894")
USER = UUID("e0000000-0000-4000-8000-000000976894")
WA_ID = "573001234567"
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 64
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class UploadingClient:
    def __init__(self, *outcomes: str | Exception) -> None:
        self._outcomes = list(outcomes)
        self.uploads: list[tuple[str, str]] = []
        self.payloads: list[dict[str, Any]] = []

    async def upload_media(self, content: bytes, content_type: str, filename: str) -> str:
        self.uploads.append((content_type, filename))
        return f"media-{len(self.uploads)}"

    async def send_payload(self, payload: dict[str, Any]) -> str:
        self.payloads.append(payload)
        outcome = self._outcomes.pop(0) if self._outcomes else f"wamid.{uuid4().hex}"
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class World:
    def __init__(self, *, inbound_ago: timedelta = timedelta(hours=1)) -> None:
        self.clock = Clock()
        self.chat_repo = MemoryChatRepository()
        self.outbox = MemoryOutboxRepository(clock=self.clock)
        self.chats = ChatService(self.chat_repo, self.outbox, clock=self.clock)
        self.library_repo = MemorySeasonalRepository()
        sources = MemorySourceReads()
        sources.pieces[(TENANT, BRAND)] = [uuid4() for _ in range(3)]
        sources.logos[(TENANT, BRAND)] = f"t/{TENANT}/brand/{BRAND}/logo.png"
        self.library = SeasonalMediaService(self.library_repo, sources, clock=self.clock)
        self.service = SeasonalSendService(
            self.chats,
            self.library,
            self.library_repo,
            lambda t, c: BRAND if (t, c) == (TENANT, CONN) else None,
        )
        self.thread_id = self.chat_repo.add_thread(
            tenant_id=TENANT, connection_id=CONN, wa_id=WA_ID
        )
        self.chat_repo.add_message(
            thread_id=self.thread_id,
            direction="inbound",
            text_value="Hola",
            posted_at=NOW - inbound_ago,
        )
        self.outbox.threads[self.thread_id] = NOW - inbound_ago
        self.files: dict[str, bytes] = {}
        self.reads: list[str] = []
        rows = self.library.plan_batch(TENANT, BRAND, "navidad-2026", "Navidad", "free", USER)
        self.sticker = self._approve(next(r for r in rows if r.kind == "sticker"))
        self.video = self._approve(next(r for r in rows if r.kind == "video"))
        self.client = UploadingClient()

    def _approve(self, media):
        ext = "webp" if media.kind == "sticker" else "mp4"
        key = f"seasonal/{TENANT}/{BRAND}/{media.season_key}/{media.id}-{media.attempt}.{ext}"
        self.files[key] = WEBP if media.kind == "sticker" else MP4
        self.library.mark_ready(
            tenant_id=TENANT,
            brand_id=BRAND,
            media_id=media.id,
            attempt=media.attempt,
            object_key=key,
            bytes=90_000 if media.kind == "sticker" else 2_400_000,
            width=512,
            height=512,
            duration_ms=None if media.kind == "sticker" else 4000,
        )
        (approved,) = self.library.approve(TENANT, BRAND, [media.id], USER)
        return approved

    def guard(self) -> SeasonalSendGuard:
        def open_file(tenant_id: UUID, brand_id: UUID, key: str) -> bytes:
            assert key.startswith(f"seasonal/{tenant_id}/{brand_id}/")
            self.reads.append(key)
            return self.files[key]

        return SeasonalSendGuard(
            lambda t, m: self.library_repo.get(tenant_id=t, media_id=m), open_file
        )

    def sender(self) -> OutboxSender:
        async def factory(**_: Any) -> UploadingClient:
            return self.client

        return OutboxSender(
            self.outbox,
            factory,
            lambda **_: None,
            worker_id="t",
            opt_ins=OptInService(MemoryOptInRepository(), clock=self.clock),
            clock=self.clock,
            seasonal=self.guard(),
        )

    def send(self, media, caption: str | None = None, **kw: Any) -> UUID:
        return self.service.send(TENANT, self.thread_id, USER, media.id, caption, **kw)


@pytest.fixture
def world() -> World:
    return World()


# --- what is queued ---------------------------------------------------------------------


def test_a_sticker_goes_alone_with_its_library_provenance(world: World) -> None:
    item_id = world.send(world.sticker)
    row = world.outbox.rows[item_id]
    assert row.kind == "reply"
    assert row.payload == build_sticker_body(WA_ID, None)
    assert row.preview_text == STICKER_SENT_TEXT
    att = row.attachment
    assert att["kind"] == "seasonal_media"
    assert att["seasonal_media_id"] == str(world.sticker.id)
    assert att["attempt"] == 1 and att["brand_id"] == str(BRAND)
    assert att["object_key"] == world.sticker.object_key  # the library file, no copy
    assert att["content_type"] == "image/webp" and att["media_id"] is None
    assert att["library_pipeline"] == "seasonal-v1"


def test_a_video_carries_its_optional_caption(world: World) -> None:
    row = world.outbox.rows[world.send(world.video, "  ¡Feliz Navidad!  ")]
    assert row.payload["type"] == "video" and row.payload["video"] == {"caption": "¡Feliz Navidad!"}
    assert row.preview_text == "¡Feliz Navidad!"
    bare = world.outbox.rows[world.send(world.video, request_key="k2")]
    assert bare.payload["video"] == {} and bare.preview_text is None


def test_a_double_tap_queues_once(world: World) -> None:
    first = world.send(world.sticker, request_key="tap-1")
    assert world.send(world.sticker, request_key="tap-1") == first
    assert len(world.outbox.rows) == 1


# --- refusals at «Enviar» (nothing written) ---------------------------------------------


def _refused(world: World, media, caption: str | None = None) -> str:
    with pytest.raises(SeasonalSendRefused) as refused:
        world.send(media, caption)
    assert world.outbox.rows == {}
    return refused.value.reason


def test_a_sticker_with_text_or_a_too_long_caption_is_refused(world: World) -> None:
    assert _refused(world, world.sticker, "hola") == "sticker_caption"
    assert _refused(world, world.video, "x" * 1025) == "caption_too_long"
    world.send(world.video, "x" * 1024)


def test_not_approved_archived_or_another_business_is_refused(world: World) -> None:
    world.library.reject(TENANT, BRAND, world.sticker.id, USER)
    assert _refused(world, world.sticker) == "not_approved"
    world.library.archive(TENANT, BRAND, "navidad-2026")
    assert _refused(world, world.video) == "archived"
    foreign = world.library_repo.rows[world.video.id]
    world.library_repo.rows[foreign.id] = replace(foreign, brand_id=OTHER_BRAND)
    assert _refused(world, foreign) == "not_found"


def test_a_closed_window_writes_nothing() -> None:
    world = World(inbound_ago=timedelta(hours=30))
    with pytest.raises(WindowClosed):
        world.send(world.sticker)
    assert world.outbox.rows == {}


def test_the_preview_says_kind_season_and_weight(world: World) -> None:
    preview = world.service.preview(TENANT, CONN, world.video.id)
    assert (preview.kind, preview.season_label, preview.weight_label) == (
        "video",
        "Navidad",
        "2,3 MB",
    )
    assert preview.caption_allowed and preview.max_caption_chars == 1024
    sticker = world.service.preview(TENANT, CONN, world.sticker.id)
    assert sticker.weight_label == "88 KB" and not sticker.caption_allowed
    assert weight_label(500) == "1 KB"
    with pytest.raises(SeasonalSendRefused):
        world.service.preview(OTHER_TENANT, CONN, world.video.id)


def test_the_picker_lists_approved_media_of_the_numbers_business(world: World) -> None:
    listed = world.service.list_for_chat(TENANT, CONN)
    assert [m.id for m in listed] == [world.sticker.id, world.video.id]
    assert world.service.list_for_chat(TENANT, uuid4()) == []


# --- at send time (the sender) ----------------------------------------------------------


async def test_the_sender_uploads_the_library_file_once_and_sends_a_sticker(
    world: World,
) -> None:
    item_id = world.send(world.sticker)
    world.client = UploadingClient(WhatsAppApiError("boom", is_transport=True), "wamid.ok")
    sender = world.sender()
    assert (await sender.run_once(TENANT)).retried == 1
    world.clock.now = NOW + timedelta(minutes=5)
    assert (await sender.run_once(TENANT)).sent == 1
    assert world.client.uploads == [("image/webp", "sticker.webp")]
    assert world.reads == [world.sticker.object_key]
    assert [p["sticker"] for p in world.client.payloads] == [{"id": "media-1"}] * 2
    assert world.outbox.rows[item_id].attachment["media_id"] == "media-1"
    (message,) = world.outbox.messages
    assert message.text == STICKER_SENT_TEXT


async def _fails_with(world: World, item_id: UUID) -> str | None:
    report = await world.sender().run_once(TENANT)
    assert report.failed == 1 and world.client.uploads == [] and world.client.payloads == []
    return world.outbox.rows[item_id].error_code


async def test_archived_after_queueing_is_withdrawn_unsent(world: World) -> None:
    item_id = world.send(world.video, "Hola")
    world.library.archive(TENANT, BRAND, "navidad-2026")
    assert await _fails_with(world, item_id) == "seasonal_withdrawn"


async def test_rejected_after_queueing_is_withdrawn_unsent(world: World) -> None:
    item_id = world.send(world.sticker)
    world.library.reject(TENANT, BRAND, world.sticker.id, USER)
    assert await _fails_with(world, item_id) == "seasonal_withdrawn"


async def test_another_attempt_after_queueing_is_refused(world: World) -> None:
    item_id = world.send(world.sticker)
    world.library.reject(TENANT, BRAND, world.sticker.id, USER)
    world.library.request_another(TENANT, BRAND, world.sticker.id, USER)
    world._approve(world.library_repo.rows[world.sticker.id])  # attempt 2, approved again
    assert await _fails_with(world, item_id) == "attachment_refused"


async def test_a_key_of_another_business_is_refused(world: World) -> None:
    item_id = world.send(world.sticker)
    row = world.outbox.rows[item_id]
    row.attachment = {
        **row.attachment,
        "object_key": row.attachment["object_key"].replace(str(BRAND), str(OTHER_BRAND)),
    }
    assert await _fails_with(world, item_id) == "attachment_refused"


def test_send_time_refusal_reads_malformed_attachments_as_refused(world: World) -> None:
    media = world.library_repo.rows[world.sticker.id]
    good = {
        "object_key": media.object_key,
        "brand_id": str(BRAND),
        "attempt": 1,
    }
    assert send_time_refusal(TENANT, good, media) is None
    assert send_time_refusal(TENANT, {**good, "brand_id": "x"}, media) == "attachment_refused"
    assert send_time_refusal(OTHER_TENANT, good, media) == "attachment_refused"
    assert send_time_refusal(TENANT, good, None) == "attachment_refused"


async def test_without_the_guard_a_seasonal_row_is_retried_never_sent(world: World) -> None:
    world.send(world.sticker)

    async def factory(**_: Any) -> UploadingClient:
        return world.client

    sender = OutboxSender(
        world.outbox,
        factory,
        lambda **_: None,
        worker_id="t",
        opt_ins=OptInService(MemoryOptInRepository(), clock=world.clock),
        clock=world.clock,
    )
    assert (await sender.run_once(TENANT)).retried == 1
    assert world.client.payloads == []

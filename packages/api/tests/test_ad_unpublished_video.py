"""Video pairs for an ad from an unpublished piece (m-24828982): MP4 limits before any
network call, chunked advideos transport, write-ahead claims and the processing gate."""

from __future__ import annotations

import io
import struct
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from packages.api.tests.test_ad_unpublished import (
    Client,
    Recipes,
    form,
    service,  # noqa: F401
)
from PIL import Image

from qualify_api.ads import unpublished as domain
from qualify_api.ads import unpublished_service as module
from qualify_api.ads.client import MarketingClient
from qualify_api.ads.errors import MarketingError
from qualify_api.ads.fake import FakeMarketingClient
from qualify_api.ads.unpublished import (
    ImageSelection,
    UnpublishedUnavailable,
    VideoSelection,
    creative_payload,
    mp4_facts,
    video_creative_payload,
)


def box(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(body), kind) + body


def mp4(width: int, height: int, seconds: float = 5, payload: bytes = b"x" * 3000) -> bytes:
    mvhd = box(b"mvhd", bytes(12) + struct.pack(">II", 1000, int(seconds * 1000)) + bytes(80))
    tkhd = box(b"tkhd", bytes(76) + struct.pack(">II", width << 16, height << 16))
    trak = box(b"trak", tkhd + box(b"mdia", box(b"hdlr", bytes(8) + b"vide" + bytes(12))))
    return box(b"ftyp", b"isom" + bytes(4)) + box(b"mdat", payload) + box(b"moov", mvhd + trak)


class VideoRecipes(Recipes):
    def __init__(self):
        super().__init__()
        self.videos = {}

    def claim_video(self, source, asset, digest, size):
        row = self.videos.setdefault(
            (asset.asset_id, digest),
            {"id": uuid4(), "state": "ready", "video_id": None, "claim_token": None},
        )
        if row["state"] == "ready":
            row.update(state="submitting", claim_token=uuid4())
            return deepcopy(row), row["claim_token"]
        return deepcopy(row), None

    def _row(self, row_id):
        return next(row for row in self.videos.values() if row["id"] == row_id)

    def video_named(self, tenant, row_id, token, value):
        row = self._row(row_id)
        assert row["claim_token"] == token and row["video_id"] is None
        row["video_id"] = value

    def finish_video(self, tenant, row_id, token, state, detail=None):
        row = self._row(row_id)
        assert row["state"] == "submitting" and row["claim_token"] == token
        row.update(state=state, claim_token=None)

    def video_checked(self, tenant, row_id, state):
        row = self._row(row_id)
        assert row["state"] == "processing"
        row["state"] = state


class VideoClient(Client):
    def __init__(self):
        super().__init__()
        self.video_uploads, self.video_failure = [], False
        self.start_refusals = []

    async def upload_video(self, stream, size, *, before_write, started):
        before_write()
        if self.start_refusals:  # a definite refusal of `start`: no video named
            raise self.start_refusals.pop(0)
        identifier = str(900 + len(self.video_uploads))
        started(identifier)
        self.video_uploads.append(b"".join(iter(lambda: stream.read(1000), b"")))
        if self.video_failure:
            raise MarketingError("unknown", outcome_unknown=True)
        self.objects[identifier] = {
            "id": identifier,
            "status": {"video_status": "processing"},
            "_resource": "advideos",
        }
        return identifier

    def finish_processing(self):
        for row in self.objects.values():
            if row["_resource"] == "advideos":
                row["status"] = {"video_status": "ready"}


@pytest.fixture
def video(service, monkeypatch):  # noqa: F811
    obj, image_source, actor, _, store = service
    tenant = image_source.tenant_id

    def pick(width, height):
        cover = ImageSelection(
            uuid4(), f"t/{tenant}/generated/{uuid4()}.png", "image/png", width, height
        )
        data = io.BytesIO()
        Image.new("RGB", (width, height)).save(data, format="PNG")
        store.put(cover.object_key, io.BytesIO(data.getvalue()), "image/png")
        clip = VideoSelection(
            uuid4(), f"t/{tenant}/generated/{uuid4()}.mp4", "video/mp4", width, height, cover
        )
        store.put(clip.object_key, io.BytesIO(mp4(width, height)), "video/mp4")
        return clip

    selected = replace(image_source, feed=pick(40, 50), vertical=pick(90, 160))
    client = VideoClient()
    obj.recipes = VideoRecipes()
    monkeypatch.setattr(module, "load_image_source", lambda *args: selected)

    async def account(s, a):
        obj._guard(s, a)
        # Fence reads during a write must use another client (the write holds the lock).
        observed = client
        if client.read_lock.locked():
            observed = VideoClient()
            observed.objects = client.objects
        return module.AccountAccess(s.tenant_id, s.brand_id, s.meta_account_id, "COP", observed)

    monkeypatch.setattr(obj, "_account", account)
    return obj, selected, actor, client, store


async def prepare(bundle):
    obj, selected, actor, *_ = bundle
    return await obj.prepare(
        tenant_id=selected.tenant_id,
        draft_id=selected.draft_id,
        ad_account_id=selected.account_id,
        feed_asset_id=selected.feed.asset_id,
        vertical_asset_id=selected.vertical.asset_id,
        feed_thumbnail_asset_id=selected.feed.thumbnail.asset_id,
        vertical_thumbnail_asset_id=selected.vertical.thumbnail.asset_id,
        form=form(),
        actor=actor,
        request_key=KEY,
        confirm_preparation=True,
    )


KEY = uuid4()


def test_video_pair_builds_one_ad_with_two_video_placement_rules(video):
    _, selected, *_ = video
    payload = video_creative_payload(selected, form(), (("901", "cover1"), ("902", "cover2")))
    spec = payload["asset_feed_spec"]
    assert spec["ad_formats"] == ["SINGLE_VIDEO"] and "images" not in spec
    assert spec["videos"] == [
        {"video_id": "901", "thumbnail_hash": "cover1", "adlabels": [{"name": "feed"}]},
        {"video_id": "902", "thumbnail_hash": "cover2", "adlabels": [{"name": "vertical"}]},
    ]
    assert [
        (rule["video_label"], rule["customization_spec"]["instagram_positions"])
        for rule in spec["asset_customization_rules"]
    ] == [({"name": "feed"}, ["stream"]), ({"name": "vertical"}, ["story", "reels"])]
    # An image hash is never a video id, and the image builder refuses a video source.
    for pairs in ((("abc-hash", "cover1"), ("902", "cover2")), (("901", "cover1"),)):
        with pytest.raises(UnpublishedUnavailable):
            video_creative_payload(selected, form(), pairs)
    with pytest.raises(UnpublishedUnavailable):
        creative_payload(selected, form(), ("h1", "h2"))


def test_no_mixing_and_a_missing_cover_is_blocked_with_the_reason(video, service):  # noqa: F811
    _, selected, *_ = video
    image_source = service[1]
    with pytest.raises(UnpublishedUnavailable, match="mezclar"):
        replace(selected, vertical=image_source.vertical).snapshot()
    with pytest.raises(UnpublishedUnavailable, match="portada"):
        replace(selected, feed=replace(selected.feed, thumbnail=None)).snapshot()
    with pytest.raises(UnpublishedUnavailable):
        replace(selected, feed=replace(selected.feed, content_type="video/quicktime")).snapshot()
    assert selected.snapshot()["pipeline"] == "ad-unpublished-video-v1"
    assert image_source.snapshot()["pipeline"] == "ad-unpublished-images-v1"


def test_mp4_facts_reads_metadata_and_refuses_non_mp4(monkeypatch):
    assert mp4_facts(io.BytesIO(mp4(90, 160, seconds=7.5))) == (len(mp4(90, 160)), 7.5, 90, 160)
    head, moov = mp4(90, 160).split(b"moov")[0][:-4], mp4(90, 160).split(b"moov", 1)[1]
    # 64-bit length (size field 1 + largesize) and a last box running to EOF (size 0).
    large = head + struct.pack(">I4sQ", 1, b"moov", 16 + len(moov)) + moov
    assert mp4_facts(io.BytesIO(large))[1:] == (5.0, 90, 160)
    open_ended = head + struct.pack(">I4s", 0, b"moov") + moov
    assert mp4_facts(io.BytesIO(open_ended))[1:] == (5.0, 90, 160)
    oversized_moov = head + box(b"moov", bytes(domain.MAX_MOOV_BYTES + 1))
    tiny_boxes = head + box(b"free", b"") * (domain.MAX_TOP_LEVEL_BOXES + 1) + box(b"moov", moov)
    for data in (
        b"not a video",
        mp4(90, 160)[:-10],
        box(b"moov", b""),
        b"",
        oversized_moov,
        tiny_boxes,
    ):
        with pytest.raises(UnpublishedUnavailable, match="No pudimos leer"):
            mp4_facts(io.BytesIO(data))

    class Unscanned(io.BytesIO):
        def read(self, *args):
            raise AssertionError("size must be refused before scanning")

    monkeypatch.setattr("qualify_api.ads.unpublished.MAX_VIDEO_BYTES", 100)
    with pytest.raises(UnpublishedUnavailable, match="100 MB. Recórtalo"):
        mp4_facts(Unscanned(mp4(90, 160)))


@pytest.mark.asyncio
async def test_duration_and_dimensions_are_refused_before_any_network_call(video):
    obj, selected, actor, client, store = video
    store.objects[selected.vertical.object_key] = mp4(90, 160, seconds=61)
    with pytest.raises(UnpublishedUnavailable, match="60 segundos"):
        await prepare(video)
    store.objects[selected.vertical.object_key] = mp4(80, 160)
    with pytest.raises(UnpublishedUnavailable, match="video cambió"):
        await prepare(video)
    assert not client.calls and not client.video_uploads and not obj.recipes.rows


@pytest.mark.asyncio
async def test_processing_video_builds_nothing_until_meta_reports_ready(video):
    obj, selected, actor, client, _ = video
    with pytest.raises(UnpublishedUnavailable, match="todavía está preparando tu video") as waiting:
        await prepare(video)
    assert waiting.value.reason == "video_processing"
    assert len(client.video_uploads) == 2 and client.upload_calls == 2
    assert client.video_uploads[0] == mp4(40, 50)
    assert not any(row["_resource"] != "advideos" for row in client.objects.values())
    assert {row["state"] for row in obj.recipes.videos.values()} == {"processing"}
    # The same call again is the reconcile step: one status read, no new upload.
    with pytest.raises(UnpublishedUnavailable, match="todavía"):
        await prepare(video)
    assert len(client.video_uploads) == 2
    client.finish_processing()
    preview = await prepare(video)
    assert len(client.video_uploads) == 2 and client.upload_calls == 2
    assert {row["state"] for row in obj.recipes.videos.values()} == {"ready_remote"}
    promotion = obj.promotions.get(selected.tenant_id, preview.promotion_id)
    spec = promotion.request["creative"]["asset_feed_spec"]
    assert [row["video_id"] for row in spec["videos"]] == ["900", "901"]
    assert [row["thumbnail_hash"] for row in spec["videos"]] == ["hash1", "hash2"]
    assert client.previews == ["INSTAGRAM_STANDARD", "INSTAGRAM_STORY"] and not client.updates
    result = await obj.confirm(
        tenant_id=selected.tenant_id,
        recipe_id=preview.recipe_id,
        review_id=preview.review_id,
        actor=actor,
        confirm_charge=True,
    )
    assert result == "active" and len(client.updates) == 3


@pytest.mark.asyncio
async def test_a_failed_send_is_unknown_and_never_sent_again(video):
    obj, _, _, client, _ = video
    client.video_failure = True
    with pytest.raises(UnpublishedUnavailable):
        await prepare(video)
    (row,) = obj.recipes.videos.values()
    assert row["state"] == "unknown" and row["video_id"] == "900"
    client.video_failure = False
    with pytest.raises(UnpublishedUnavailable, match="Pide ayuda") as uncertain:
        await prepare(video)
    assert uncertain.value.reason == "upload_uncertain"
    assert len(client.video_uploads) == 1


@pytest.mark.asyncio
async def test_a_refused_fence_releases_the_claim_without_sending(video, monkeypatch):
    obj, *_ = video
    client = video[3]
    original = obj._guard
    calls = []

    def guard(source, actor, expiry=None):
        calls.append(1)
        if any(row["state"] == "submitting" for row in obj.recipes.videos.values()):
            raise UnpublishedUnavailable("changed")
        return original(source, actor, expiry)

    monkeypatch.setattr(obj, "_guard", guard)
    with pytest.raises(UnpublishedUnavailable, match="changed"):
        await prepare(video)
    assert not client.video_uploads
    assert {row["state"] for row in obj.recipes.videos.values()} == {"ready"}


@pytest.mark.asyncio
async def test_status_read_honours_requested_fields():
    client = FakeMarketingClient(account_id="12")
    client.objects["77"] = {
        "id": "77",
        "status": {"video_status": "expired"},
        "secret": "x",
        "_resource": "advideos",
    }
    assert await client.video_status("77") == "error"
    assert client.calls[-1] == ("GET", "77", {"fields": "id,status"})
    client.objects["78"] = {"id": "78", "_resource": "advideos"}
    with pytest.raises(MarketingError):
        await client.video_status("78")


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_at", [None, "transfer"])
async def test_real_http_chunked_video_transport_never_retries(fail_at, monkeypatch):
    from urllib.parse import parse_qs

    monkeypatch.setattr("qualify_api.ads.client.VIDEO_CHUNK_BYTES", 4)
    data, calls, named, fences = b"0123456789", [], [], []

    def respond(request):
        assert request.url.host == "graph-video.facebook.com"
        assert request.url.path == "/v26.0/act_12/advideos" and request.method == "POST"
        body = request.content
        calls.append(body)
        if b"multipart" in request.headers["content-type"].encode():
            assert named == ["555"]
            if fail_at == "transfer":
                raise httpx.ReadTimeout("timeout")
            start = int(body.split(b'name="start_offset"\r\n\r\n')[1].split(b"\r\n")[0])
            end = min(start + 4, len(data))
            assert data[start:end] in body
            return httpx.Response(
                200, json={"start_offset": str(end), "end_offset": str(min(end + 4, len(data)))}
            )
        phase = parse_qs(body.decode())["upload_phase"][0]
        if phase == "start":
            assert fences == [True]
            return httpx.Response(
                200,
                json={
                    "video_id": "555",
                    "upload_session_id": "s1",
                    "start_offset": "0",
                    "end_offset": "4",
                },
            )
        return httpx.Response(200, json={"success": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        client = MarketingClient(client=http, account_id="12")
        upload = client.upload_video(
            io.BytesIO(data),
            len(data),
            before_write=lambda: fences.append(True),
            started=named.append,
        )
        if fail_at is None:
            assert await upload == "555"
            assert len(calls) == 5  # start, three chunks, finish
        else:
            with pytest.raises(MarketingError) as error:
                await upload
            assert error.value.outcome_unknown and len(calls) == 2


@pytest.mark.asyncio
async def test_a_definite_start_refusal_returns_the_claim_to_ready(video):
    obj, _, _, client, _ = video
    client.start_refusals.append(MarketingError("rate", code=17))
    with pytest.raises(UnpublishedUnavailable):
        await prepare(video)
    (row,) = obj.recipes.videos.values()
    assert row["state"] == "ready" and row["video_id"] is None and not client.video_uploads
    with pytest.raises(UnpublishedUnavailable, match="todavía"):
        await prepare(video)
    assert len(client.video_uploads) == 2


@pytest.mark.asyncio
async def test_video_reads_use_head_and_ranges_never_a_whole_object_open(video, monkeypatch):
    obj, selected, *_ = video
    monkeypatch.setattr(
        obj.gate, "open_object", lambda *a: (_ for _ in ()).throw(AssertionError("whole read"))
    )
    sizes = []
    original = obj.gate.object_size
    monkeypatch.setattr(obj.gate, "object_size", lambda *a: sizes.append(1) or original(*a))
    digest, size = module.video_facts(obj.gate, selected, selected.feed)
    assert size == len(mp4(40, 50)) and sizes
    monkeypatch.setattr(module, "MAX_VIDEO_BYTES", 10)
    monkeypatch.setattr(
        obj.gate, "open_range", lambda *a: (_ for _ in ()).throw(AssertionError("read"))
    )
    with pytest.raises(UnpublishedUnavailable, match="Recórtalo"):
        module.video_facts(obj.gate, selected, selected.feed)


def test_owner_copy_for_video_states():
    assert "no tienes que subirlo de nuevo" in module.VIDEO_WAIT["processing"]
    assert "de 1 a 60 segundos y en MP4" in module.VIDEO_WAIT["failed"]

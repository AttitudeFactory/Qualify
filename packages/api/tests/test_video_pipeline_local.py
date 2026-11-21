"""EF-06 (m-25026574): «Tu video, con efectos» — a `local` Clip, or a `local` part of a
video by parts, made from the owner's own videos and photos at cost 0, with no vendor.

Offline: the videos and photos are tiny files encoded here (PyAV), the store is a dict, the
BytePlus adapter is a double that fails if it is ever called, and the copy is scripted."""

from __future__ import annotations

import io
import tempfile
import time
from collections.abc import Iterator
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.creations import REQUEST_LOCAL_VIDEO, weight_for
from qualify_creative.enums import ContentFormat, ContentKind, GenerationTask
from qualify_creative.schemas import ContentBrief, MediaInputs, SourceSegment

from qualify_api.creative import job_queue as q
from qualify_api.creative.creations import InMemoryCreationsLedger
from qualify_api.creative.draft_mode import DRAFT_READY, draft_pending
from qualify_api.creative.fsm import APPROVED, GENERATED
from qualify_api.creative.part_final import PART_FINAL, final_parts, raw_key
from qualify_api.creative.part_join import (
    PartPreview,
    PartsToJoin,
    is_local_part,
    join_preview,
    ready_parts,
)
from qualify_api.creative.queue_dispatch import SWITCH, generation_jobs, job_pricing_version
from qualify_api.creative.service import ContentService
from qualify_api.creative.video_pipeline import local
from qualify_api.creative.video_pipeline.recipe import RecipeRefused

from .test_content_service import (
    BRAND_ID,
    TENANT_ID,
    USER_ID,
    FakeBrand,
    FakePricing,
    FakeRouter,
    FakeVoice,
    InMemoryRepository,
    RecordingDispatcher,
    StaticKeyResolver,
    copy_dict,
    make_brief,
    make_kit,
    make_voice,
    ok_outcome,
)
from .test_creative_media import BUDGET, COPY, KeysByProvider, SpyVendor, _kit

av = pytest.importorskip("av")
Image = pytest.importorskip("PIL.Image")

VIDEO_KEY = f"uploads/{TENANT_ID}/mi-cocina.mp4"
PHOTO_KEY = f"uploads/{TENANT_ID}/mi-plato.png"
OTHER_TENANT = UUID("0b0b0000-0000-4000-8000-0000000000ef")
FOREIGN_KEY = f"uploads/{OTHER_TENANT}/su-cocina.mp4"
SIZE = (180, 320)
GREEN = (20, 200, 40)
RED = (210, 30, 30)


# ---------------------------------------------------------------------------
# tiny sources and doubles


def _video_bytes(seconds: float, colour: tuple[int, int, int] = GREEN) -> bytes:
    """A silent 30 fps H.264 of `seconds`, one flat colour, at `SIZE`."""
    out = io.BytesIO()
    with av.open(out, mode="w", format="mp4") as sink:
        stream = sink.add_stream("libx264", rate=30)
        stream.width, stream.height = SIZE
        stream.pix_fmt = "yuv420p"
        stream.codec_context.time_base = Fraction(1, 30)
        picture = Image.new("RGB", SIZE, colour)
        for index in range(round(seconds * 30)):
            frame = av.VideoFrame.from_image(picture).reformat(format="yuv420p")
            frame.pts = index
            frame.time_base = Fraction(1, 30)
            for packet in stream.encode(frame):
                sink.mux(packet)
        for packet in stream.encode():
            sink.mux(packet)
    return out.getvalue()


def _png_bytes(colour: tuple[int, int, int] = RED) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (240, 320), colour).save(out, format="PNG")
    return out.getvalue()


class ReadingStore:
    """A dict store that records every key read — to prove what was NOT read."""

    def __init__(self, files: dict[str, bytes] | None = None) -> None:
        self.files = dict(files or {})
        self.reads: list[str] = []

    def read(self, key: str) -> bytes:
        self.reads.append(key)
        if key not in self.files:
            raise FileNotFoundError(key)
        return self.files[key]

    def write(self, key: str, data: bytes) -> None:
        self.files[key] = data


class ExplodingByteplus(SpyVendor):
    """The BytePlus adapter's double (Seedance, Seedream, OmniHuman): fails if called."""

    name = "seedance"
    supports = frozenset(GenerationTask)


@pytest.fixture
def queue_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SWITCH, "queue")


#: The one test that assembles at the real 1080×1920 (m-25041163).
REAL_SIZE_TEST = "test_a_local_clip_comes_out_1080x1920_encoded_at_that_size_once"


@pytest.fixture(autouse=True)
def assemble_at_the_sources_size(request: pytest.FixtureRequest, monkeypatch: Any) -> None:
    """A local part comes out 1080×1920 (m-25041163). Here, where the subject is the
    pipeline around the size, it is assembled at the sources' own 9:16 `SIZE` instead:
    encoding 1080×1920 in every test made this file ten times slower (20 s → 220 s). The
    real size is `REAL_SIZE_TEST`'s, and `speed`'s own tests'."""
    if request.node.name == REAL_SIZE_TEST:
        return
    from qualify_creative.video import prepare

    # `render_local_part` reads it at call time: the size of the photos and of the speed
    monkeypatch.setattr(prepare, "TARGET_SIZE", SIZE)


@pytest.fixture(autouse=True)
def no_normalize_jobs(monkeypatch: pytest.MonkeyPatch) -> Any:
    """m-25042483: the `normalize_local` jobs in memory (offline), none to begin with —
    this module's sources are 8-bit and small: read as they are, as before."""
    from qualify_api.creative.video_pipeline import local_sources

    jobs = local_sources.InMemoryLocalSourceJobs()
    monkeypatch.setattr(local_sources, "default_jobs", lambda: jobs)
    return jobs


@pytest.fixture(scope="module")
def sources() -> dict[str, bytes]:
    return {VIDEO_KEY: _video_bytes(4.0), PHOTO_KEY: _png_bytes()}


def _video(start: float = 0.0, end: float = 4.0, speed: float = 2.0) -> SourceSegment:
    return SourceSegment(key=VIDEO_KEY, start_s=start, end_s=end, speed=speed)


def _photo(seconds: float = 1.5) -> SourceSegment:
    return SourceSegment(key=PHOTO_KEY, start_s=0.0, end_s=seconds, kind="photo")


def _local_clip(*segments: SourceSegment, **media: Any) -> ContentBrief:
    return make_brief(
        variants=1,
        kind=ContentKind.CLIP,
        format=ContentFormat.REELS_9_16,
        media=MediaInputs(
            **{
                "duration_seconds": 5,
                "clip_reference_mode": "local",
                "segments": segments or (_video(), _photo()),
                **media,
            }
        ),
    )


def _producer(store: Any, vendor: SpyVendor, *, render_client: Any = None) -> Any:
    from qualify_creative.pricing import JsonPricingTable
    from qualify_creative.router import CreativeRouter

    from qualify_api.creative.media import MediaProducer

    pricing = JsonPricingTable("v2")
    router = CreativeRouter({vendor.name: vendor}, pricing, KeysByProvider())  # type: ignore[arg-type]
    return MediaProducer(
        store=store,
        router=router,
        credentials=KeysByProvider(),
        pricing=pricing,
        render_client=render_client,
    )


def _service(
    store: Any,
    vendor: SpyVendor,
    *,
    ledger: InMemoryCreationsLedger | None = None,
    render_client: Any = None,
) -> tuple[ContentService, InMemoryRepository, RecordingDispatcher]:
    repo, dispatcher = InMemoryRepository(), RecordingDispatcher()
    service = ContentService(
        router=FakeRouter([ok_outcome(copy_dict()) for _ in range(3)]),  # type: ignore[arg-type]
        pricing=FakePricing(),
        credentials=StaticKeyResolver(),
        voice_service=FakeVoice(make_voice()),
        brand_service=FakeBrand(make_kit()),
        repository=repo,
        dispatcher=dispatcher,
        media=_producer(store, vendor, render_client=render_client),
        creations=ledger,
    )
    return service, repo, dispatcher


def _stamped(brief: ContentBrief) -> ContentBrief:
    media = brief.media.model_copy(
        update={"effects_pipeline_version": local.effects_version_for(brief)}
    )
    return brief.model_copy(update={"media": media})


def _decoded(data: bytes) -> list[Any]:
    with av.open(io.BytesIO(data)) as container:
        stream = container.streams.video[0]
        assert len(container.streams.audio) == 1  # m-25049580: always one sound track
        return list(container.decode(stream))


# ---------------------------------------------------------------------------
# a `local` Clip: a `preview` job, no vendor, US$0.00 on v10, nothing discounted


def test_a_local_clip_rides_a_preview_job_that_never_takes_a_vendor_slot() -> None:
    """The queue gives a `local` Clip its ONE `preview` job — enqueued unprepared, it is
    never claimed (no executor call, no `vendor_slots` slot): the preparation makes the
    video and `_settle_local` closes the job, as for an image."""
    brief = _stamped(_local_clip())
    assert generation_jobs(brief) == [(q.KIND_PREVIEW, 0, q.SEEDANCE_POOL)]
    # the job row names the table that priced it: v10 (`local_video` 0.00)
    assert job_pricing_version(brief, "v8") == "v10"
    assert job_pricing_version(_local_clip(), "v8") == "v8"  # never stamped: not local


def test_a_local_clip_is_made_with_no_vendor_and_costs_zero_on_v10(
    queue_on: None, sources: dict[str, bytes]
) -> None:
    vendor = ExplodingByteplus()
    store = ReadingStore(sources)
    service, repo, dispatcher = _service(store, vendor)
    draft = service.create_draft(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=_local_clip(), user_id=USER_ID
    )
    stored = repo.briefs[repo.drafts[draft].brief_id]
    assert stored.media.effects_pipeline_version == local.LOCAL_EFFECTS_PIPELINE_VERSION
    assert dispatcher.calls == [(TENANT_ID, draft)]
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft)
    assert repo.drafts[draft].status == GENERATED
    assert vendor.requests == []  # BytePlus never reached
    (video,) = repo.media[draft]
    assert video.media_type == "video" and video.params["local"]["cost_usd"] == "0.00"
    (usage,) = [u for u in repo.usage if u.provider == local.LOCAL_PROVIDER]
    assert usage.cost_usd == 0 and usage.pricing_table_version == "v10"
    assert usage.model_id == "local_video" and usage.unit == "second"
    assert local.local_price(60) == 0  # the table itself: local_video 0.00 a second


def test_a_local_clip_uses_no_video_seconds_nor_vistas_previas(
    queue_on: None, sources: dict[str, bytes]
) -> None:
    """D3: a local piece is charged as made (one row of 0) and uses nothing of the month:
    no creation, no vista previa at creation, no video second at approval."""
    brief = _local_clip()
    price = weight_for(brief)
    assert (price.request_kind, price.weight, price.videos, price.video_seconds) == (
        REQUEST_LOCAL_VIDEO,
        0,
        0,
        0,
    )
    ledger = InMemoryCreationsLedger()
    service, repo, _ = _service(ReadingStore(sources), ExplodingByteplus(), ledger=ledger)
    before = ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID)
    draft = service.create_draft(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=brief, user_id=USER_ID
    )
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft)
    variant = next(v for v in repo.variants.values() if v.draft_id == draft)
    service.approve(tenant_id=TENANT_ID, draft_id=draft, variant_id=variant.id, user_id=USER_ID)
    assert repo.drafts[draft].status == APPROVED
    assert ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID) == before
    (row,) = ledger.rows.values()
    assert row.price.request_kind == REQUEST_LOCAL_VIDEO


def test_a_local_clip_is_publishable_with_no_final_and_not_marked_ai(
    queue_on: None, sources: dict[str, bytes]
) -> None:
    """No `draft` block (nothing to order from Seedance: publishable as it is) and
    `ai_generated=False` — the draft's «hecho con IA», which the Planificador sends to
    Instagram (`draft_post_reader`), follows the asset, not the Clip kind."""
    service, repo, _ = _service(ReadingStore(sources), ExplodingByteplus())
    brief = _local_clip()
    assert brief.requires_ai_disclosure is False
    draft = service.create_draft(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=brief, user_id=USER_ID
    )
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft)
    (video,) = repo.media[draft]
    assert "draft" not in video.params and draft_pending(video.params) is False
    assert video.params["ai_generated"] is False
    assert repo.drafts[draft].requires_ai_disclosure is False
    # a Seedance clip of the same business still is AI (read from what was made)
    seedance = make_brief(variants=1, kind=ContentKind.CLIP, format=ContentFormat.REELS_9_16)
    assert seedance.requires_ai_disclosure is True


def test_the_asset_records_its_provenance(queue_on: None, sources: dict[str, bytes]) -> None:
    outcome = _producer(ReadingStore(sources), ExplodingByteplus()).produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=_stamped(_local_clip()),
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
    )
    assert outcome.failure is None, outcome.detail
    (write,) = outcome.media
    assert write.ai_generated is False and write.provider == "local"
    meta = write.params["local"]
    assert meta["recipe_contract"] == 2 and meta["recipe_version"] == "local-v2"
    assert meta["effects_pipeline_version"] == 1 and meta["pricing_version"] == "v10"
    assert meta["effect_version"] == 1 and type(meta["effect_version"]) is int  # m-25029126
    assert meta["speed"]["recipe_version"] == "camara_rapida-v3"
    assert meta["speed"]["effect_version"] == 1
    assert meta["steps"]["speed"] == "camara_rapida-v3"
    from qualify_creative.video.speed import speed_effect_version

    assert speed_effect_version(meta) == speed_effect_version(meta["speed"]) == 1
    assert set(meta["steps"]) == {"prepare", "speed", "photo_hold", "sound"}
    assert [s["kind"] for s in meta["segments"]] == ["video", "photo"]
    assert all("tmp" not in str(s["source"]).lower() for s in meta["speed"]["segments"])


def test_a_local_clip_comes_out_1080x1920_encoded_at_that_size_once(
    queue_on: None, sources: dict[str, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    """m-25041163: a small 180×320 video and a photo come out one 1080×1920 video, BT.709
    tagged. `prepare` keeps the video at its own size (an intermediate, never enlarged) and
    the speed's single encode enlarges it — 1080×1920 is encoded once, not twice — and the
    provenance names the speed recipe that does it."""
    from qualify_creative.video import prepare
    from qualify_creative.video.speed import SPEED_RECIPE_VERSION

    assert prepare.TARGET_SIZE == (1080, 1920)  # not shrunk by the autouse fixture
    prepared: list[tuple[int, int]] = []
    real_apply = prepare.apply_prepare

    def spy(*args: Any, **kwargs: Any) -> Any:
        made = real_apply(*args, **kwargs)
        prepared.append((made.width, made.height))
        return made

    monkeypatch.setattr(prepare, "apply_prepare", spy)
    store = ReadingStore(sources)
    outcome = _producer(store, ExplodingByteplus()).produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=_stamped(_local_clip(_video(), _photo(1.5))),
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
    )
    assert outcome.failure is None, outcome.detail
    (write,) = outcome.media
    assert prepared == [SIZE]  # the intermediate: never enlarged by `prepare`
    steps = write.params["local"]["steps"]
    assert steps["speed"] == SPEED_RECIPE_VERSION == "camara_rapida-v3"
    frames = _decoded(store.files[write.object_key])
    assert {(f.width, f.height) for f in frames} == {(1080, 1920)}
    with av.open(io.BytesIO(store.files[write.object_key])) as written:
        context = written.streams.video[0].codec_context
        assert (context.color_range, context.colorspace) == (1, 1)  # limited, BT.709
        assert (context.color_primaries, context.color_trc) == (1, 1)
    first = frames[0].to_ndarray(format="rgb24")[960, 540]
    last = frames[-1].to_ndarray(format="rgb24")[960, 540]
    assert first[1] > 150 and first[0] < 90  # green: the video, enlarged
    assert last[0] > 150 and last[1] < 90  # red: the photo, at the same size


def test_a_local_video_waits_for_a_part_join_before_reading_anything(
    queue_on: None, sources: dict[str, bytes]
) -> None:
    """m-25042483: with a part join holding the worker, the local video is not made now:
    `LocalAssemblyWait` (retried on the next pass) before any file is read."""
    from qualify_api.creative.heavy_video import LocalAssemblyWait, joining

    store = ReadingStore(sources)
    with joining(), pytest.raises(LocalAssemblyWait):
        _producer(store, ExplodingByteplus()).produce(
            tenant_id=TENANT_ID,
            draft_id=uuid4(),
            brief=_stamped(_local_clip()),
            kit=_kit(),
            copy=COPY,
            budget=BUDGET,
        )
    assert store.reads == []


def test_a_photo_and_a_video_make_one_video_with_no_gaps(
    queue_on: None, sources: dict[str, bytes]
) -> None:
    """D-T1: 4 s of video at ×2 (2 s) then a photo held 1.5 s → 3.5 s: 105 frames at 30
    fps, stamped one after another, the video's picture first and the photo's last."""
    store = ReadingStore(sources)
    outcome = _producer(store, ExplodingByteplus()).produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=_stamped(_local_clip(_video(), _photo(1.5))),
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
    )
    assert outcome.failure is None, outcome.detail
    (write,) = outcome.media
    assert write.params["duration_seconds"] == pytest.approx(3.5)
    frames = _decoded(store.files[write.object_key])
    assert len(frames) == 105
    assert [f.pts for f in frames] == sorted(f.pts for f in frames)
    steps = {round(b.pts - a.pts, 6) for a, b in zip(frames, frames[1:], strict=False)}
    assert len(steps) == 1  # constant: no hole between the video and the photo
    first = frames[0].to_ndarray(format="rgb24")[160, 90]
    last = frames[-1].to_ndarray(format="rgb24")[160, 90]
    assert first[1] > 150 and first[0] < 90  # green: the video
    assert last[0] > 150 and last[1] < 90  # red: the photo
    speed = write.params["local"]["speed"]["segments"]
    assert [(s["out_start_s"], s["out_end_s"]) for s in speed] == [(0.0, 2.0), (2.0, 3.5)]


def test_a_retried_run_makes_the_same_single_asset(
    queue_on: None, sources: dict[str, bytes]
) -> None:
    """Idempotent: the same draft and revision run twice keep one video under the same
    key; a retried run of the service writes one asset, one usage row, one charge."""
    store = ReadingStore(sources)
    producer = _producer(store, ExplodingByteplus())
    draft_id, brief = uuid4(), _stamped(_local_clip())
    keys = []
    for _ in range(2):
        outcome = producer.produce(
            tenant_id=TENANT_ID,
            draft_id=draft_id,
            brief=brief,
            kit=_kit(),
            copy=COPY,
            budget=BUDGET,
        )
        (write,) = outcome.media
        keys.append(write.object_key)
    assert keys[0] == keys[1]
    ledger = InMemoryCreationsLedger()
    service, repo, _ = _service(store, ExplodingByteplus(), ledger=ledger)
    draft = service.create_draft(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=_local_clip(), user_id=USER_ID
    )
    for _ in range(2):  # a retried preparation: the second run finds it made
        service.run_generation(tenant_id=TENANT_ID, draft_id=draft)
    assert len(repo.media[draft]) == 1 and len(ledger.rows) == 1
    assert len([u for u in repo.usage if u.provider == local.LOCAL_PROVIDER]) == 1


# ---------------------------------------------------------------------------
# end to end: the editor's recipe in `segments` makes the Clip


def test_a_brief_with_the_recipe_in_segments_makes_the_clip(
    queue_on: None, sources: dict[str, bytes]
) -> None:
    """ED-02's recipe as the screen sends it (`segments`, speed and a photo): created
    without `recipe_unavailable`, stamped, made, with the length asked for."""
    brief = ContentBrief.model_validate(
        {
            **_local_clip().model_dump(mode="json"),
            "media": {
                **_local_clip().media.model_dump(mode="json"),
                "segments": [
                    {"key": VIDEO_KEY, "start_s": 0, "end_s": 3, "speed": 1.5, "rotate": 0},
                    {"key": PHOTO_KEY, "start_s": 0, "end_s": 2, "kind": "photo"},
                ],
            },
        }
    )
    service, repo, _ = _service(ReadingStore(sources), ExplodingByteplus())
    draft = service.create_draft(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=brief, user_id=USER_ID
    )
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft)
    assert repo.drafts[draft].status == GENERATED, repo.drafts[draft].failure_detail
    (video,) = repo.media[draft]
    assert video.params["duration_seconds"] == pytest.approx(4.0)  # 3 s at ×1.5 + 2 s


# ---------------------------------------------------------------------------
# option A (Deivid, 2026-11-16): outside 3-60 s «Crear» does not go on


@pytest.mark.parametrize(("end_s", "duration"), [(2.0, 2.0), (61.0, 61.0)])
def test_a_local_clip_outside_3_to_60_seconds_is_refused_saying_how_long(
    queue_on: None, end_s: float, duration: float
) -> None:
    ledger = InMemoryCreationsLedger()
    service, repo, dispatcher = _service(ReadingStore(), ExplodingByteplus(), ledger=ledger)
    brief = _local_clip(_video(0.0, end_s, 1.0))
    with pytest.raises(RecipeRefused) as refused:
        service.create_draft(tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=brief, user_id=USER_ID)
    # 61 s at ×1 is also a stretch over 60 s of its video (m-25042483): both are said
    problem = refused.value.problems[0]
    assert (problem.code, problem.duration_s) == ("local_length_out_of_range", duration)
    assert [p.code for p in refused.value.problems[1:]] == (
        ["segment_source_too_long"] if end_s > 60 else []
    )
    assert repo.drafts == {} and repo.briefs == {}
    assert ledger.rows == {} and dispatcher.calls == []


def test_a_sped_up_length_is_said_to_a_tenth_of_a_second(queue_on: None) -> None:
    service, _, _ = _service(ReadingStore(), ExplodingByteplus())
    brief = _local_clip(_video(0.0, 5.0, 3.0))  # 1.666… s
    with pytest.raises(RecipeRefused) as refused:
        service.create_draft(tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=brief, user_id=USER_ID)
    assert refused.value.problems[0].duration_s == 1.7


@pytest.mark.parametrize("end_s", [3.0, 60.0])
def test_a_local_clip_of_exactly_3_or_60_seconds_goes_on(queue_on: None, end_s: float) -> None:
    service, repo, dispatcher = _service(ReadingStore(), ExplodingByteplus())
    draft = service.create_draft(
        tenant_id=TENANT_ID,
        brand_id=BRAND_ID,
        brief=_local_clip(_video(0.0, end_s, 1.0)),
        user_id=USER_ID,
    )
    assert draft in repo.drafts and dispatcher.calls == [(TENANT_ID, draft)]


def _parent_with_local_part(seconds: int) -> ContentBrief:
    from qualify_creative.schemas import VideoPartPlan

    from .test_creative_parts import parent_brief

    stretch = SourceSegment(key=VIDEO_KEY, start_s=0.0, end_s=float(seconds))
    return parent_brief(
        VideoPartPlan(seconds=5, description="Uno."),
        VideoPartPlan(mode="local", seconds=seconds, segments=(stretch,), description="Dos."),
    )


def test_a_local_part_under_3_seconds_is_refused_before_anything(queue_on: None) -> None:
    """Option A for parts too: a 2 s `local` part would fail in the speed step after it
    was created — it is refused with its length, and nothing is written, charged or sent."""
    ledger = InMemoryCreationsLedger()
    service, repo, dispatcher = _service(ReadingStore(), ExplodingByteplus(), ledger=ledger)
    with pytest.raises(RecipeRefused) as refused:
        service.create_draft(
            tenant_id=TENANT_ID,
            brand_id=BRAND_ID,
            brief=_parent_with_local_part(2),
            user_id=USER_ID,
        )
    assert [(p.code, p.part, p.duration_s) for p in refused.value.problems] == [
        ("local_length_out_of_range", 2, 2.0)
    ]
    assert repo.drafts == {} and repo.briefs == {}
    assert ledger.rows == {} and dispatcher.calls == []


def test_a_local_part_of_3_seconds_goes_on(queue_on: None) -> None:
    service, repo, dispatcher = _service(ReadingStore(), ExplodingByteplus())
    draft = service.create_draft(
        tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=_parent_with_local_part(3), user_id=USER_ID
    )
    assert draft in repo.drafts and dispatcher.calls == [(TENANT_ID, draft)]


# ---------------------------------------------------------------------------
# never inside Reflex: the `inline` dispatcher refuses a `local` like VE-08's parts


def test_the_inline_dispatcher_refuses_a_local_clip_before_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SWITCH, "inline")
    ledger = InMemoryCreationsLedger()
    service, repo, dispatcher = _service(ReadingStore(), ExplodingByteplus(), ledger=ledger)
    with pytest.raises(RecipeRefused) as refused:
        service.create_draft(
            tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=_local_clip(), user_id=USER_ID
        )
    assert [(p.code, p.field) for p in refused.value.problems] == [("local_unavailable", "mode")]
    assert repo.drafts == {} and ledger.rows == {} and dispatcher.calls == []


def test_the_producer_decodes_nothing_outside_the_worker(
    monkeypatch: pytest.MonkeyPatch, sources: dict[str, bytes]
) -> None:
    """A regeneration dispatched to an `inline` thread (a stored local Clip) reads nothing:
    the piece fails and keeps its previous version."""
    monkeypatch.setenv(SWITCH, "inline")
    store = ReadingStore(sources)
    outcome = _producer(store, ExplodingByteplus()).produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=_stamped(_local_clip()),
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
    )
    assert outcome.failure is not None and outcome.media == ()
    assert outcome.detail == local.LOCAL_NEEDS_WORKER_TEXT
    assert store.reads == []


class CountingLease:
    """The `PipelineStore` double: counts the lease renewals while the video is made."""

    def __init__(self) -> None:
        self.renewals = 0

    def renew(self, run: Any) -> bool:
        self.renewals += 1
        return True


def test_the_preparations_lease_is_kept_alive_while_the_video_is_made(
    queue_on: None, sources: dict[str, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review #1: a long local render renews `creative_pipeline_runs`' lease, as the
    parts' join does — never lost before the final write."""
    monkeypatch.setattr(local, "LEASE_RENEW_EVERY_S", 0.005)
    store, lease = ReadingStore(sources), CountingLease()
    saved: dict[str, bytes] = {}

    def save(name: str, data: bytes, content_type: str) -> str:
        time.sleep(0.05)  # a slow R2: the lease must be renewed meanwhile
        saved[name] = data
        return f"t/{TENANT_ID}/generated/x/r1/{name}"

    save.optional = lambda *a: None  # type: ignore[attr-defined]
    run = SimpleNamespace(tenant_id=TENANT_ID, draft_id=uuid4(), phase="generation")
    outcome = local.produce_local(
        tenant_id=TENANT_ID,
        draft_id=run.draft_id,
        brief=_stamped(_local_clip()),
        store=store,
        save=save,
        run=run,
        lease_store=lease,
    )
    assert outcome.failure is None, outcome.detail
    assert lease.renewals >= 1 and "local.mp4" in saved


def test_a_video_the_decoder_cannot_open_is_unreadable_not_a_vendor_error(
    queue_on: None,
    sources: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Review #6: a decoder error no step wrapped (PyAV's own) is the owner's file that
    cannot be opened (`unreadable`), said in the owner's words — not a vendor error."""
    from qualify_creative.video import prepare

    def broken(*_: Any, **__: Any) -> Any:
        raise av.error.InvalidDataError(1094995529, "Invalid data found")

    monkeypatch.setattr(prepare, "read_source", broken)
    with pytest.raises(local.LocalVideoFailed) as failed:
        local.render_local_part(
            local.recipe_of(_stamped(_local_clip()))[0],
            tenant_id=TENANT_ID,
            store=ReadingStore(sources),
            root=tmp_path,
        )
    assert failed.value.code == "unreadable"
    assert failed.value.detail == local.LOCAL_SOURCE_FAILED_TEXT


@pytest.mark.parametrize("in_part", [False, True])
def test_a_stored_stretch_over_60_seconds_of_video_says_so_before_any_read(
    queue_on: None, in_part: bool
) -> None:
    """m-25042483: the worker's backstop — a stretch taking 90 s of its video (at ×10 it
    would last 9 s) is refused before anything is read, in the owner's words reviewed by
    ux-designer, «esta parte» in a part; nothing charged."""
    from qualify_creative.schemas import PartRef

    store = ReadingStore()
    whole = _local_clip(_video(0.0, 90.0, 10.0))
    brief = whole
    if in_part:
        part = PartRef(index=2, mode="local", seconds=9, segments=whole.media.segments)
        brief = whole.model_copy(update={"media": whole.media.model_copy(update={"part": part})})
    outcome = local.produce_local(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=_stamped(brief), store=store, save=None
    )
    want = local.LOCAL_PART_SOURCE_TOO_LONG_TEXT if in_part else local.LOCAL_SOURCE_TOO_LONG_TEXT
    assert outcome.detail == want and outcome.media == ()
    assert "aunque lo aceleres" in want and "1 minuto" in want
    assert store.reads == []


def test_a_part_whose_save_fails_says_this_part(queue_on: None, sources: dict[str, bytes]) -> None:
    """ux-designer: a part says «el video de esta parte» where a piece says «tu video»."""
    from qualify_creative.schemas import PartRef

    class NoKeep(ReadingStore):
        def keep_file(self, *_: Any) -> bool:
            return False

    class Saver:
        def key_for(self, name: str) -> str:
            return f"t/{TENANT_ID}/generated/x/r1/{name}"

    whole = _local_clip(_video(0.0, 4.0, 1.0), _photo(1.0))
    part = PartRef(index=2, mode="local", seconds=5, segments=whole.media.segments)
    brief = whole.model_copy(update={"media": whole.media.model_copy(update={"part": part})})
    outcome = local.produce_local(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=_stamped(brief),
        store=NoKeep(sources),
        save=Saver(),
    )
    assert outcome.detail == local.LOCAL_PART_SAVE_FAILED_TEXT and outcome.media == ()


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("a bug of ours"),
        av.error.OSError(28, "No space left on device"),
        av.error.ExternalError(-542398533, "Generic error in an external library"),
        av.error.BugError(-558323010, "Internal bug, should not have happened"),
    ],
    ids=["runtime", "disk_full", "external", "bug"],
)
def test_an_error_that_is_not_the_owners_file_goes_up_as_it_is(
    queue_on: None,
    sources: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    error: Exception,
) -> None:
    """Review 2: only the decoders' refusals are `unreadable` — our own bug, a full disk
    or FFmpeg's internal error are not the owner's file and go up unchanged."""
    from qualify_creative.video import prepare

    def broken(*_: Any, **__: Any) -> Any:
        raise error

    monkeypatch.setattr(prepare, "read_source", broken)
    with pytest.raises(type(error)) as raised:
        local.render_local_part(
            local.recipe_of(_stamped(_local_clip()))[0],
            tenant_id=TENANT_ID,
            store=ReadingStore(sources),
            root=tmp_path,
        )
    assert raised.value is error


def test_a_save_that_fails_says_so(queue_on: None, sources: dict[str, bytes]) -> None:
    """Review #3: R2 refusing the finished video reads «No pudimos guardar…», not a read."""

    class NoKeep(ReadingStore):
        def keep_file(self, *_: Any) -> bool:
            return False

    class Saver:
        def key_for(self, name: str) -> str:
            return f"t/{TENANT_ID}/generated/x/r1/{name}"

    outcome = local.produce_local(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=_stamped(_local_clip()),
        store=NoKeep(sources),
        save=Saver(),
    )
    assert outcome.detail == local.LOCAL_SAVE_FAILED_TEXT and outcome.media == ()


# ---------------------------------------------------------------------------
# isolation: a stretch of another business is never read


def test_a_stretch_of_another_business_is_never_read(
    queue_on: None, sources: dict[str, bytes]
) -> None:
    store = ReadingStore({**sources, FOREIGN_KEY: sources[VIDEO_KEY]})
    foreign = SourceSegment(key=FOREIGN_KEY, start_s=0.0, end_s=4.0)
    brief = _stamped(_local_clip(_video(), foreign))
    outcome = local.produce_local(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=brief,
        store=store,
        save=lambda *a, **k: pytest.fail("nothing is saved"),
    )
    assert outcome.failure == "route_blocked_by_policy" and outcome.media == ()
    assert store.reads == []


# ---------------------------------------------------------------------------
# a video by parts: a `local` part joins like the others; AI if one part is a vendor's


def _part(
    index: int, *, mode: str, status: str = GENERATED, block: dict | None = None
) -> PartPreview:
    key = f"t/{TENANT_ID}/generated/{uuid4()}/r1/clip.mp4"
    params: dict[str, Any] = {
        "part": {
            "index": index,
            "mode": mode,
            "seconds": 5,
            "generation_seconds": 5.2 if mode == "local" else 5,
            "clean_key": key,
        }
    }
    if mode == "local":
        params["local"] = {"pricing_version": "v10"}
    else:
        params["draft"] = block or {"status": DRAFT_READY, "created_at": time.time()}
    return PartPreview(
        draft_id=uuid4(),
        part_index=index,
        status=status,
        revision=1,
        version_id=uuid4(),
        object_key=key,
        params=params,
    )


class _Joins:
    def __init__(self, snapshot: PartsToJoin) -> None:
        self.snapshot = snapshot

    def read(self, *, tenant_id: UUID, parent_id: UUID) -> PartsToJoin:
        return self.snapshot

    def save(self, **_: Any) -> bool:  # pragma: no cover — not called here
        return True


def _joined(parts: tuple[PartPreview, ...]) -> Any:
    store = ReadingStore({p.object_key: b"mp4" for p in parts if p.object_key})
    snapshot = PartsToJoin(parent_id=uuid4(), revision=1, planned=len(parts), parts=parts)

    def joiner(clips: Any, *, out: Path, size: Any, overlay: Any) -> Any:
        out.write_bytes(b"joined")
        return SimpleNamespace(path=out, frames=300, poster=None)

    return join_preview(store, _Joins(snapshot), TENANT_ID, snapshot.parent_id, joiner=joiner)


def test_a_local_part_and_a_reference_part_join_as_ai() -> None:
    parts = (_part(1, mode="local"), _part(2, mode="reference"))
    assert is_local_part(parts[0].params) and not is_local_part(parts[1].params)
    snapshot = PartsToJoin(parent_id=uuid4(), revision=1, planned=2, parts=parts)
    assert ready_parts(snapshot, TENANT_ID) == parts
    write = _joined(parts)
    assert write is not None and write.ai_generated is True
    assert write.params["ai_generated"] is True
    assert [p["mode"] for p in write.params["join"]["parts"]] == ["local", "reference"]


def test_a_video_joined_only_from_local_parts_is_not_ai() -> None:
    write = _joined((_part(1, mode="local"), _part(2, mode="local")))
    assert write is not None and write.ai_generated is False


def test_a_local_part_is_its_own_final_once_approved() -> None:
    """VE-10b's final join reads a part's raw 1080p; a `local` part's file is its final
    (nothing ordered from Seedance), the `reference` part waits for its own."""
    local_part = _part(1, mode="local", status=APPROVED)
    waiting = _part(2, mode="reference", status=APPROVED)
    snapshot = PartsToJoin(parent_id=uuid4(), revision=1, planned=2, parts=(local_part, waiting))
    assert final_parts(snapshot, TENANT_ID) is None  # the reference part's final is not kept
    raw = {"key": f"t/{TENANT_ID}/generated/{uuid4()}/r1/raw.mp4"}
    kept = _part(
        2, mode="reference", status=APPROVED, block={"status": PART_FINAL, "raw_final": raw}
    )
    snapshot = PartsToJoin(parent_id=uuid4(), revision=1, planned=2, parts=(local_part, kept))
    assert final_parts(snapshot, TENANT_ID) == (local_part, kept)
    assert raw_key(local_part) == local_part.object_key


def _frames_of(data: bytes) -> Iterator[Any]:  # pragma: no cover — kept for debugging
    yield from _decoded(data)


# ---------------------------------------------------------------------------
# EF-05 hooked in: the owner's texts over the local video, drawn by our render service


def _texts(*layers: Any, part: bool = False) -> ContentBrief:
    """A stamped `local` Clip (4 s of video at ×2 then a photo held 1.5 s → 3.5 s) or a
    `local` part's child (5 s), with `layers` over it."""
    from qualify_creative.schemas import PartRef

    if part:  # a part's stretches last its planned 5 s: 4 s at ×1 and a photo of 1 s
        whole = _local_clip(_video(0.0, 4.0, 1.0), _photo(1.0), text_layers=layers)
    else:
        whole = _local_clip(text_layers=layers)
    if part:
        ref = PartRef(
            index=2, mode="local", seconds=5, segments=whole.media.segments, text_layers=layers
        )
        whole = whole.model_copy(update={"media": whole.media.model_copy(update={"part": ref})})
    return _stamped(whole)


def _render_service(outcome: Any = "completed") -> Any:
    """EF-05's render service double: draws a PNG per text and records the props."""
    from .test_video_pipeline_compose import FakeService

    return FakeService(outcome)


def _branded_kit() -> Any:
    return _kit().model_copy(update={"font_heading": "Poppins"})


def _produce(brief: ContentBrief, store: Any, render_client: Any) -> Any:
    return _producer(store, ExplodingByteplus(), render_client=render_client).produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=brief,
        kit=_branded_kit(),
        copy=COPY,
        budget=BUDGET,
    )


def _words(**over: Any) -> Any:
    from qualify_creative.schemas import VideoTextLayer

    return VideoTextLayer(**{"text": "Shawarma mixto", "place": "top", "end_s": 2.0, **over})


def test_a_local_clip_with_texts_has_them_drawn_and_kept_in_its_provenance(
    queue_on: None, sources: dict[str, bytes]
) -> None:
    """The compose step runs after `render_speed`: each text drawn once by our render
    service in the Brand Kit's typeface and palette, laid over the built video, at cost 0
    and with no vendor; its provenance kept in `params.local.text_layers`."""
    from qualify_api.creative.video_pipeline.compose import COMPOSE_VERSION

    render = _render_service()
    store = ReadingStore(sources)
    second = _words(text="Abrimos a las 7", place="bottom", start_s=1.0, end_s=None)
    outcome = _produce(_texts(_words(), second), store, render)
    assert outcome.failure is None, outcome.detail
    (write,) = outcome.media
    meta = write.params["local"]
    assert meta["steps"]["compose"] == COMPOSE_VERSION
    texts = meta["text_layers"]
    assert texts["compose_version"] == COMPOSE_VERSION and texts["cost_usd"] == "0"
    assert [layer["place"] for layer in texts["layers"]] == ["top", "bottom"]
    assert meta["cost_usd"] == "0.00" and write.provider == "local"
    (usage,) = outcome.usage
    assert usage.cost_usd == 0 and usage.provider == "local"
    # one render per text, in the brand's own type and colours (rule 7)
    assert [call["props"]["texts"]["text"] for call in render.calls] == [
        "Shawarma mixto",
        "Abrimos a las 7",
    ]
    brand = render.calls[0]["props"]["brand"]
    assert brand["fonts"]["heading"] == "Poppins"
    assert brand["palette"] == ["#C4622D", "#F5C518"]
    # the kept video is the composed one, as long as the built one (105 frames)
    assert len(_decoded(store.files[write.object_key])) == 105


def test_the_fade_the_owner_chose_reaches_the_compose_as_is(
    queue_on: None, sources: dict[str, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    """ED-13: the owner's fade (0.3-1.0 s, default 0.5 s) travels to the compose untouched
    and is what the provenance records — chosen and applied."""
    from qualify_api.creative.video_pipeline import compose

    seen: list[tuple[Any, ...]] = []
    real = compose.compose_text_layers

    def spy(video: Any, out: Any, layers: Any, brand: Any, **kw: Any) -> Any:
        seen.append(tuple(layers))
        return real(video, out, layers, brand, **kw)

    monkeypatch.setattr(compose, "compose_text_layers", spy)
    chosen, default = _words(fade_s=0.8), _words(place="bottom")
    outcome = _produce(_texts(chosen, default), ReadingStore(sources), _render_service())
    assert outcome.failure is None, outcome.detail
    ((top, bottom),) = seen
    assert top.fade_s == 0.8 and bottom.fade_s == compose.FADE_IN_SECONDS == 0.5
    layers = outcome.media[0].params["local"]["text_layers"]["layers"]
    assert [(lay["fade_s"], lay["fade_in_s"]) for lay in layers] == [(0.8, 0.8), (0.5, 0.5)]


def test_a_local_part_with_a_text_is_composed(queue_on: None, sources: dict[str, bytes]) -> None:
    render = _render_service()
    outcome = _produce(_texts(_words(), part=True), ReadingStore(sources), render)
    assert outcome.failure is None, outcome.detail
    (write,) = outcome.media
    assert write.params["part"]["mode"] == "local"
    assert len(write.params["local"]["text_layers"]["layers"]) == 1
    assert len(render.calls) == 1


def test_a_local_clip_without_texts_never_calls_the_render(
    queue_on: None, sources: dict[str, bytes]
) -> None:
    def no_client() -> Any:
        raise AssertionError("no render client without a text")

    outcome = _produce(_texts(), ReadingStore(sources), no_client)
    assert outcome.failure is None, outcome.detail
    meta = outcome.media[0].params["local"]
    assert "text_layers" not in meta and "compose" not in meta["steps"]


def _failed_run(sources: dict[str, bytes], render_client: Any) -> tuple[Any, int, int]:
    """A `local` Clip with a text made through the service: the draft, and the
    creations balance before and after."""
    ledger = InMemoryCreationsLedger()
    service, repo, _ = _service(
        ReadingStore(sources), ExplodingByteplus(), ledger=ledger, render_client=render_client
    )
    before = ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID)
    draft = service.create_draft(
        tenant_id=TENANT_ID,
        brand_id=BRAND_ID,
        brief=_local_clip(text_layers=(_words(),)),
        user_id=USER_ID,
    )
    service.run_generation(tenant_id=TENANT_ID, draft_id=draft)
    return repo.drafts[draft], before, ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID)


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (("render_error", 500, "Chromium crashed"), "OWNER_MESSAGE_UNAVAILABLE"),
        (("invalid_parameters", 422, "texts.layout_version: stale"), "OWNER_MESSAGE_REJECTED"),
    ],
    ids=["unavailable", "rejected"],
)
def test_a_render_service_that_cannot_draw_fails_the_piece_without_charging(
    queue_on: None, sources: dict[str, bytes], error: tuple[str, int, str], message: str
) -> None:
    """`ComposeUnavailable` / `ComposeRejected`: the piece fails with the stage's own
    message (it promises «No se descontó de tus creaciones») and the balance holds."""
    from qualify_creative.render.client import RenderServiceError

    from qualify_api.creative.video_pipeline import compose

    draft, before, after = _failed_run(sources, _render_service(RenderServiceError(*error)))
    assert draft.status == "failed"
    assert draft.failure_detail == getattr(compose, message)
    assert "No se descontó" in draft.failure_detail
    assert after == before


def test_a_text_that_does_not_fit_says_which_one(queue_on: None, sources: dict[str, bytes]) -> None:
    draft, before, after = _failed_run(sources, _render_service("refused"))
    assert draft.status == "failed"
    assert draft.failure_detail == (
        "El texto 1 («Shawarma mixto») tiene una palabra demasiado larga para la pantalla. "
        "Cámbiala por una más corta o pártela en dos, y vuelve a intentarlo."
    )
    assert after == before


def _broken_overlay(monkeypatch: pytest.MonkeyPatch) -> None:
    from qualify_creative.video.text_overlay import TextOverlayError

    from qualify_api.creative.video_pipeline import compose

    def broken(*_: Any, **__: Any) -> Any:
        raise TextOverlayError("aspect_mismatch", "the video is 1080x1080, not 9:16 (moov)")

    monkeypatch.setattr(compose, "overlay_text_layers", broken)


def test_an_overlay_failure_of_ours_never_shows_its_technical_message(
    queue_on: None, sources: dict[str, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    _broken_overlay(monkeypatch)
    draft, before, after = _failed_run(sources, _render_service())
    assert draft.status == "failed"
    assert (
        draft.failure_detail
        == local.LOCAL_COMPOSE_FAILED_TEXT
        == (
            "No pudimos terminar tu video por un problema nuestro. No se descontó de tus "
            "creaciones. Inténtalo de nuevo en unos minutos."
        )
    )
    assert "9:16" not in draft.failure_detail and "moov" not in draft.failure_detail
    assert after == before


def test_a_parts_compose_failures_charge_nothing_and_say_this_part(
    queue_on: None, sources: dict[str, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    """In a part too: no usage row, no creation (the child of a `local` part weighs 0),
    the stage's message for the service, «esta parte» for our overlay failure."""
    from qualify_creative.render.client import RenderServiceError

    from qualify_api.creative.video_pipeline import compose

    brief = _texts(_words(), part=True)
    price = weight_for(brief)
    assert (price.weight, price.videos, price.video_seconds) == (0, 0, 0)
    down = _produce(
        brief, ReadingStore(sources), _render_service(RenderServiceError("timeout", 504, "x"))
    )
    assert down.detail == compose.OWNER_MESSAGE_UNAVAILABLE
    assert down.media == () and down.usage == ()
    _broken_overlay(monkeypatch)
    broken = _produce(brief, ReadingStore(sources), _render_service())
    assert (
        broken.detail
        == local.LOCAL_PART_COMPOSE_FAILED_TEXT
        == (
            "No pudimos terminar el video de esta parte por un problema nuestro. No se descontó "
            "de tus creaciones. Inténtalo de nuevo en unos minutos."
        )
    )
    assert broken.media == () and broken.usage == ()


def test_a_producer_without_a_render_client_fails_a_text_as_the_service_down(
    queue_on: None, sources: dict[str, bytes]
) -> None:
    """Never a video without the texts the owner chose: no client wired = unavailable."""
    from qualify_api.creative.video_pipeline import compose

    outcome = _produce(_texts(_words()), ReadingStore(sources), None)
    assert outcome.detail == compose.OWNER_MESSAGE_UNAVAILABLE and outcome.media == ()


# ---------------------------------------------------------------------------
# EF-08 hooked in: the library's layers (smoke, embers, steam) before the texts


def _smoke(**over: Any) -> Any:
    from qualify_creative.schemas import EffectUse

    return EffectUse(**{"effect_id": "humo_capa", "version": 1, **over})


def _kept(outcome: Any, store: ReadingStore) -> bytes:
    assert outcome.failure is None, outcome.detail
    return store.files[outcome.media[0].object_key]


def _top_brightness(data: bytes) -> float:
    """The mean luma of the top third over the whole video (the smoke's default zone)."""
    frames = _decoded(data)
    rows = frames[0].height // 3
    planes = [f.to_ndarray()[:rows] for f in frames]  # yuv420p: the first rows are luma
    return sum(float(p.mean()) for p in planes) / len(planes)


def _frame_hashes(data: bytes) -> list[str]:
    from qualify_creative.video.text_overlay import decoded_frame_hashes

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "video.mp4"
        path.write_bytes(data)
        return decoded_frame_hashes(path)


def test_a_local_clip_with_smoke_has_it_laid_and_kept_in_its_provenance(
    queue_on: None, sources: dict[str, bytes]
) -> None:
    """A layer of the library v3 over a `local` Clip: laid at cost 0 with no vendor, its
    provenance (effect, version, params, span, the loop's sha256) in
    `params.local.effect_layers` and its step version in `steps`."""
    from qualify_creative.video.layer_overlay import LAYER_COMPOSE_VERSION

    plain_store, store = ReadingStore(sources), ReadingStore(sources)
    plain = _kept(_produce(_stamped(_local_clip()), plain_store, None), plain_store)
    use = _smoke(params={"intensity": 1.0}, start_s=0.5, end_s=3.0)
    outcome = _produce(_stamped(_local_clip(effects=(use,))), store, None)
    kept = _kept(outcome, store)
    meta = outcome.media[0].params["local"]
    assert meta["steps"]["layer_compose"] == LAYER_COMPOSE_VERSION
    layers = meta["effect_layers"]
    assert layers["compose_version"] == LAYER_COMPOSE_VERSION and layers["cost_usd"] == "0.00"
    (laid,) = layers["layers"]
    assert (laid["effect_id"], laid["effect_version"], laid["zone"]) == ("humo_capa", 1, "top")
    assert (laid["intensity"], laid["start_s"], laid["end_s"]) == (1.0, 0.5, 3.0)
    assert len(laid["loop_sha256"]) == 64 and laid["cost_usd"] == "0.00"
    assert meta["cost_usd"] == "0.00" and outcome.usage[0].cost_usd == 0
    assert len(_decoded(kept)) == 105  # as long as the built video
    # the smoke lights the top of the picture (a screen blend only brightens)
    assert _top_brightness(kept) > _top_brightness(plain) + 1.0


def test_the_layer_and_the_text_are_laid_in_one_pass_the_text_on_top(
    queue_on: None, sources: dict[str, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Layers and texts: ONE call (`overlay_layers_and_texts`: one decode, one encode)
    over the built video, the layers passed under the texts; never the layer step alone
    nor the text-only overlay. Both provenances are kept."""
    from qualify_creative.video import layer_overlay

    from qualify_api.creative.video_pipeline import compose

    calls: list[tuple[str, str, int, int]] = []
    real = layer_overlay.overlay_layers_and_texts

    def single(src: Any, out: Any, layers: Any, texts: Any, **kw: Any) -> Any:
        calls.append((Path(src).name, Path(out).name, len(layers), len(texts)))
        return real(src, out, layers, texts, **kw)

    def never(*_: Any, **__: Any) -> Any:
        raise AssertionError("one pass only")

    monkeypatch.setattr(layer_overlay, "overlay_layers_and_texts", single)
    monkeypatch.setattr(layer_overlay, "overlay_effect_layers", never)
    monkeypatch.setattr(compose, "overlay_text_layers", never)
    brief = _stamped(_local_clip(effects=(_smoke(),), text_layers=(_words(),)))
    outcome = _produce(brief, ReadingStore(sources), _render_service())
    assert outcome.failure is None, outcome.detail
    assert calls == [("local.mp4", "local-texts.mp4", 1, 1)]
    meta = outcome.media[0].params["local"]
    assert {"layer_compose", "compose"} <= set(meta["steps"])
    assert meta["effect_layers"]["layers"][0]["effect_id"] == "humo_capa"
    assert meta["text_layers"]["layers"][0]["place"] == "top"


def test_a_layer_failure_in_the_single_pass_is_ours_and_charges_nothing(
    queue_on: None, sources: dict[str, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    from qualify_creative.video import layer_overlay

    def broken(*_: Any, **__: Any) -> Any:
        raise layer_overlay.LayerOverlayError("loop_unreadable", "VP9 decoder: EBML junk")

    monkeypatch.setattr(layer_overlay, "overlay_layers_and_texts", broken)
    brief = _stamped(_local_clip(effects=(_smoke(),), text_layers=(_words(),)))
    outcome = _produce(brief, ReadingStore(sources), _render_service())
    assert outcome.detail == local.LOCAL_LAYER_FAILED_TEXT and "VP9" not in outcome.detail
    assert outcome.media == () and outcome.usage == ()


def test_without_layers_nothing_is_encoded_again(
    queue_on: None, sources: dict[str, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    """No layer: the step does not run (no second encode) and the video is as before."""
    from qualify_creative.video import layer_overlay

    first_store = ReadingStore(sources)
    first = _kept(_produce(_stamped(_local_clip()), first_store, None), first_store)

    def never(*_: Any, **__: Any) -> Any:
        raise AssertionError("no layer: no second encode")

    monkeypatch.setattr(layer_overlay, "overlay_effect_layers", never)
    store = ReadingStore(sources)
    outcome = _produce(_stamped(_local_clip()), store, None)
    second = _kept(outcome, store)
    meta = outcome.media[0].params["local"]
    assert "effect_layers" not in meta
    assert set(meta["steps"]) == {"prepare", "speed", "photo_hold", "sound"}
    assert _frame_hashes(first) == _frame_hashes(second)


def test_a_layer_failure_of_ours_charges_nothing_and_hides_its_message(
    queue_on: None, sources: dict[str, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    from qualify_creative.video import layer_overlay

    def broken(*_: Any, **__: Any) -> Any:
        raise layer_overlay.LayerOverlayError("loop_unreadable", "VP9 decoder: EBML junk")

    monkeypatch.setattr(layer_overlay, "overlay_effect_layers", broken)
    clip = _produce(_stamped(_local_clip(effects=(_smoke(),))), ReadingStore(sources), None)
    assert clip.detail == local.LOCAL_LAYER_FAILED_TEXT and "VP9" not in clip.detail
    assert clip.detail == (
        "No pudimos poner el efecto en tu video por un problema nuestro. No se descontó de "
        "tus creaciones. Inténtalo de nuevo en unos minutos o quita el efecto para terminarlo ya."
    )
    assert clip.media == () and clip.usage == ()
    # in a part: «esta parte»
    part = _stamped(_local_clip(_video(0.0, 4.0, 1.0), _photo(1.0), effects=(_smoke(),)))
    from qualify_creative.schemas import PartRef

    ref = PartRef(
        index=2, mode="local", seconds=5, segments=part.media.segments, effects=(_smoke(),)
    )
    part = part.model_copy(update={"media": part.media.model_copy(update={"part": ref})})
    in_part = _produce(part, ReadingStore(sources), None)
    assert (
        in_part.detail
        == local.LOCAL_PART_LAYER_FAILED_TEXT
        == (
            "No pudimos poner el efecto en esta parte por un problema nuestro. No se descontó "
            "de tus creaciones. Inténtalo de nuevo en unos minutos o quita el efecto para "
            "terminarlo ya."
        )
    )
    assert in_part.media == () and in_part.usage == ()


def test_an_effect_still_unbuilt_is_refused_before_any_row(queue_on: None) -> None:
    """Only the library's layers over a `local` piece are laid: fast motion as an effect
    stays `recipe_unavailable`, and so does smoke over a Clip that is not `local` and
    that EF-14 does not compose either (a square one: the layers are drawn for 9:16)."""
    from qualify_creative.schemas import EffectUse

    fast = EffectUse(effect_id="camara_rapida", version=1, params={"speed": 8.0})
    service, repo, dispatcher = _service(ReadingStore(), ExplodingByteplus())
    with pytest.raises(RecipeRefused) as refused:
        service.create_draft(
            tenant_id=TENANT_ID,
            brand_id=BRAND_ID,
            brief=_local_clip(effects=(fast,)),
            user_id=USER_ID,
        )
    found = [(p.code, p.field) for p in refused.value.problems]
    assert ("recipe_unavailable", "effects") in found
    seedance = make_brief(
        variants=1,
        kind=ContentKind.CLIP,
        format=ContentFormat.FEED_1_1,
        media=MediaInputs(duration_seconds=5, effects=(_smoke(),)),
    )
    with pytest.raises(RecipeRefused) as refused:
        service.create_draft(
            tenant_id=TENANT_ID, brand_id=BRAND_ID, brief=seedance, user_id=USER_ID
        )
    assert [(p.code, p.field) for p in refused.value.problems] == [
        ("recipe_unavailable", "effects")
    ]
    assert repo.drafts == {} and dispatcher.calls == []


def test_v3_lets_a_local_part_use_the_three_layers_up_to_three_times_each() -> None:
    from qualify_creative.effects import load_effects
    from qualify_creative.schemas import EffectUse

    from qualify_api.creative.video_pipeline.recipe import (
        PartRecipe,
        unbuilt_recipe_problems,
        validate_recipe,
    )

    stretch = SourceSegment(key=VIDEO_KEY, start_s=0.0, end_s=6.0)
    uses = (
        _smoke(start_s=0.0, end_s=2.0),
        _smoke(start_s=2.0, end_s=4.0),
        _smoke(start_s=4.0, end_s=6.0),
        EffectUse(effect_id="brasas_capa", version=1),
        EffectUse(effect_id="vapor_capa", version=1, params={"zone": "top"}),
    )
    part = PartRecipe(index=1, mode="local", seconds=6, segments=(stretch,), effects=uses)
    library = load_effects()
    assert library.version >= 3  # v3 and later (D9: v4) offer the three layers
    assert validate_recipe((part,), video_by_parts=False, library=library) == ()
    four = part.model_copy(update={"effects": (*uses, _smoke(start_s=5.0, end_s=6.0))})
    codes = [p.code for p in validate_recipe((four,), video_by_parts=False, library=library)]
    assert codes == ["too_many_of_effect"]
    # and nothing of it is left unbuilt
    assert unbuilt_recipe_problems(_local_clip(_video(0.0, 4.0, 1.0), effects=uses)) == ()


# ---------------------------------------------------------------------------
# m-25049580: the ×1 stretches keep their original sound

SOUND_KEY = f"uploads/{TENANT_ID}/con-sonido.mp4"


def _video_with_sound_bytes(seconds: float, click_s: float) -> bytes:
    """A 30 fps H.264 of `seconds` at `SIZE` with a mono 48 kHz AAC track: a quiet 440 Hz
    tone and a 20 ms 2 kHz burst at `click_s`."""
    import numpy as np

    out = io.BytesIO()
    with av.open(out, mode="w", format="mp4") as sink:
        stream = sink.add_stream("libx264", rate=30)
        stream.width, stream.height = SIZE
        stream.pix_fmt = "yuv420p"
        stream.codec_context.time_base = Fraction(1, 30)
        track = sink.add_stream("aac", rate=48_000)
        track.layout = "mono"
        picture = Image.new("RGB", SIZE, GREEN)
        for index in range(round(seconds * 30)):
            frame = av.VideoFrame.from_image(picture).reformat(format="yuv420p")
            frame.pts = index
            frame.time_base = Fraction(1, 30)
            for packet in stream.encode(frame):
                sink.mux(packet)
        t = np.arange(round(seconds * 48_000)) / 48_000
        wave = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        burst = (t >= click_s) & (t < click_s + 0.02)
        wave[burst] = (0.8 * np.sin(2 * np.pi * 2000 * (t[burst] - click_s))).astype(np.float32)
        for start in range(0, len(wave), 1024):
            chunk = av.AudioFrame.from_ndarray(
                wave[start : start + 1024].reshape(1, -1), format="fltp", layout="mono"
            )
            chunk.sample_rate = 48_000
            chunk.pts = start
            chunk.time_base = Fraction(1, 48_000)
            for packet in track.encode(chunk):
                sink.mux(packet)
        for packet in track.encode():
            sink.mux(packet)
        for packet in stream.encode():
            sink.mux(packet)
    return out.getvalue()


def _sound_of(data: bytes) -> tuple[Any, Any]:
    """The kept video's one audio track (its codec context) and its samples."""
    import numpy as np

    with av.open(io.BytesIO(data)) as container:
        (track,) = container.streams.audio
        context = track.codec_context
        chunks = [frame.to_ndarray() for frame in container.decode(track)]
    return context, np.concatenate(chunks, axis=1)


def _rms(samples: Any, start_s: float, end_s: float) -> float:
    import numpy as np

    window = samples[:, int(start_s * 48_000) : int(end_s * 48_000)]
    return float(np.sqrt(np.mean(window.astype(np.float64) ** 2)))


def _click_s(samples: Any) -> float:
    import numpy as np

    return float(np.flatnonzero(np.abs(samples).max(axis=0) > 0.5)[0] / 48_000)


@pytest.fixture(scope="module")
def sound_sources() -> dict[str, bytes]:
    return {SOUND_KEY: _video_with_sound_bytes(4.0, 1.5), PHOTO_KEY: _png_bytes()}


def _sound_clip(**media: Any) -> ContentBrief:
    """×1 of [0.5, 3.5) — the click at 1.5 s of the file lands at 1.0 s —, ×2 of the whole
    file (2 s, silent), a photo of 1.5 s (silent): 6.5 s."""
    return _stamped(
        _local_clip(
            SourceSegment(key=SOUND_KEY, start_s=0.5, end_s=3.5, speed=1.0),
            SourceSegment(key=SOUND_KEY, start_s=0.0, end_s=4.0, speed=2.0),
            _photo(1.5),
            **media,
        )
    )


def test_a_x1_stretch_keeps_its_sound_and_the_rest_is_silence(
    queue_on: None, sound_sources: dict[str, bytes]
) -> None:
    """Criteria 1-4, 6, 7 through the whole assembly: one AAC 48 kHz stereo track, the ×1
    stretch's own sound trimmed to its picture (the click within a frame of 1.0 s), the
    sped-up stretch and the photo silent; the provenance says which and why."""
    from qualify_creative.video.sound import SOUND_VERSION

    store = ReadingStore(sound_sources)
    outcome = _produce(_sound_clip(), store, None)
    data = _kept(outcome, store)
    meta = outcome.media[0].params["local"]
    assert meta["recipe_version"] == local.LOCAL_RECIPE_VERSION == "local-v2"
    assert meta["steps"]["sound"] == SOUND_VERSION and meta["steps"]["prepare"] == "prepare-v2"
    sound = meta["sound"]
    assert [(s["segment"], s["original_sound"], s["why"]) for s in sound["segments"]] == [
        (0, True, "kept"),
        (1, False, "sped_up"),
        (2, False, "photo"),
    ]
    assert sound["format"] == {
        "codec": "aac",
        "sample_rate": 48_000,
        "layout": "stereo",
        "bit_rate": 128_000,
    }
    assert sound["crossfade_s"] == 0.08
    assert meta["speed"]["audio"] is True and meta["speed"]["sound"]["original_sound"] == [0]
    context, samples = _sound_of(data)
    assert (context.name, context.sample_rate, context.channels) == ("aac", 48_000, 2)
    assert abs(samples.shape[1] - 6.5 * 48_000) <= 1024
    assert abs(_click_s(samples) - 1.0) <= 1 / 30
    assert _rms(samples, 0.1, 0.4) > 0.1  # the tone, from the stretch's first instant
    assert _rms(samples, 3.1, 6.4) < 0.005  # sped up, then the photo: silence
    assert len(_decoded(data)) == 195


def test_the_sound_stays_in_sync_under_the_texts(
    queue_on: None, sound_sources: dict[str, bytes]
) -> None:
    """EF-05 copies the built video's sound: with a text over it, the click is still within
    a frame of 1.0 s and the track as long as the picture."""
    store = ReadingStore(sound_sources)
    outcome = _produce(_sound_clip(text_layers=(_words(),)), store, _render_service())
    data = _kept(outcome, store)
    assert outcome.media[0].params["local"]["steps"]["compose"]
    _, samples = _sound_of(data)
    assert abs(_click_s(samples) - 1.0) <= 1 / 30
    assert abs(samples.shape[1] - 6.5 * 48_000) <= 2048

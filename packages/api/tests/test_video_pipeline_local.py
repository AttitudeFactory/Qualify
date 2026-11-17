"""EF-06 (m-25026574): «Tu video, con efectos» — a `local` Clip, or a `local` part of a
video by parts, made from the owner's own videos and photos at cost 0, with no vendor.

Offline: the videos and photos are tiny files encoded here (PyAV), the store is a dict, the
BytePlus adapter is a double that fails if it is ever called, and the copy is scripted."""

from __future__ import annotations

import io
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
        assert not container.streams.audio
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
    assert meta["recipe_contract"] == 2 and meta["recipe_version"] == "local-v1"
    assert meta["effects_pipeline_version"] == 1 and meta["pricing_version"] == "v10"
    assert meta["effect_version"] == "camara_rapida-v1"
    assert meta["speed"]["effect_version"] == "camara_rapida-v1"
    assert set(meta["steps"]) == {"prepare", "speed", "photo_hold"}
    assert [s["kind"] for s in meta["segments"]] == ["video", "photo"]
    assert all("tmp" not in str(s["source"]).lower() for s in meta["speed"]["segments"])


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
    (problem,) = refused.value.problems
    assert (problem.code, problem.duration_s) == ("local_length_out_of_range", duration)
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

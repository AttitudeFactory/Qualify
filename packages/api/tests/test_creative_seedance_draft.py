"""Seedance 2.5 draft mode in the media producer (m-24820142): every video on a model with
a draft mode is made as a 480p draft that carries what its final needs; `finalize` makes
the 1080p final from the draft's id alone, re-encodes it and returns the row that
replaces the draft. Same fakes as `test_creative_media_byteplus.py`, on the v5 prices."""

from __future__ import annotations

import re
import time
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from qualify_creative.enums import ContentFormat, ContentKind, FailureReason, GenerationTask
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.providers import GenerationRequest, GenerationResult, Usage
from qualify_creative.router import CreativeRouter
from qualify_creative.video import FittedVideo
from qualify_creative.video.fit import DETAIL_X264

from qualify_api.creative.draft_mode import (
    DRAFT_EXPIRED_TEXT,
    DRAFT_FINAL,
    DRAFT_READY,
    draft_expired,
    draft_pending,
)
from qualify_api.creative.media import MediaProducer
from qualify_api.creative.service import ImageRecord

from .test_creative_media_byteplus import (
    BUDGET,
    COPY,
    TENANT_ID,
    FakeSeedream,
    KeysByProvider,
    MemoryStore,
    _brief,
    _image,
    _kit,
    _seedance_brief,
)

DRAFT_MODEL = "dreamina-seedance-2-5-260628"
#: a draft made now: its id lives 7 days
CREATED_AT = int(time.time())


class DraftSeedance:
    """ModelArk's Seedance 2.5: a draft at 480p, or the final of a draft at 1080p."""

    name = "seedance"
    supports = frozenset({GenerationTask.SCENE_VIDEO})

    def __init__(self, *, fail_final: bool = False) -> None:
        self.fail_final = fail_final
        self.requests: list[GenerationRequest] = []

    def generate(self, request: GenerationRequest, *, api_key: str) -> GenerationResult:
        self.requests.append(request)
        final = "draft_task_id" in request.params
        if final and self.fail_final:
            raise RuntimeError("ArkTaskFailed: InternalServiceError")
        payload = {
            "task_id": "cgt-final" if final else "cgt-draft",
            "video_url": "https://ark/v.mp4",
            "duration_seconds": "5",
            "resolution": "1080p" if final else "480p",
            "generate_audio": True,
            "seed": 33608,
            "draft": not final,
            "draft_task_id": request.params.get("draft_task_id"),
            "created_at": int(time.time()) if final else CREATED_AT,
        }
        tokens = 243000 if final else 48000
        return GenerationResult(
            payload=payload,
            model_id=DRAFT_MODEL,
            provider="seedance",
            usage=Usage(pieces=1, media_seconds=Decimal(5), output_tokens=tokens),
            model_revision=DRAFT_MODEL,
            media_url="https://ark/v.mp4",
            media_expires_at_seconds=86400,
        )

    def estimate_cost_usd(self, request: GenerationRequest, pricing: Any, **_: Any) -> Decimal:
        return Decimal("0.5")


class RecordingFitter:
    def __init__(self, *, fail_overlay: bool = False) -> None:
        self.fail_overlay = fail_overlay
        self.calls: list[dict[str, Any]] = []

    def fit(self, data: bytes, *, size: tuple[int, int], **kw: Any) -> FittedVideo:
        self.calls.append({"data": data, "size": size, **kw})
        if self.fail_overlay and kw.get("overlay") is not None:
            raise ValueError("overlay would not lay")
        return FittedVideo(
            data=b"h264-" + data, width=size[0], height=size[1], duration_sec=5.0, poster=_image()
        )


def _producer(store: MemoryStore, seedance: DraftSeedance, fitter: RecordingFitter) -> Any:
    pricing = JsonPricingTable("v5")
    router = CreativeRouter(
        {"seedance": seedance, "seedream": FakeSeedream()}, pricing, KeysByProvider()
    )
    return MediaProducer(
        store=store,
        router=router,
        credentials=KeysByProvider(),
        pricing=pricing,
        download=lambda url: b"hevc-bytes",
        generated_ad_images=True,
        fitter=fitter,
        seedance_model=DRAFT_MODEL,
        seedance_reference_model=DRAFT_MODEL,
        seedance_resolution="720p",
    )


def _store() -> MemoryStore:
    return MemoryStore(
        {
            f"uploads/{TENANT_ID}/first.jpg": _image(size=(800, 600)),
            f"uploads/{TENANT_ID}/logo.png": _image((0, 0, 0), (200, 200)),
            f"uploads/{TENANT_ID}/p1.jpg": _image(),
            f"uploads/{TENANT_ID}/bg.jpg": _image((90, 60, 30), (800, 600)),
        }
    )


def _clip(**media: object) -> Any:
    return _brief(ContentKind.CLIP, clip_first_frame_key=f"uploads/{TENANT_ID}/first.jpg", **media)


def _record(write: Any) -> ImageRecord:
    return ImageRecord(
        id=uuid4(),
        media_url=write.media_url,
        width=write.width,
        height=write.height,
        aspect_ratio=write.aspect_ratio,
        media_type=write.media_type,
        position=write.position,
        params=write.params,
        object_key=write.object_key,
    )


def _finalize(producer: MediaProducer, brief: Any, asset: ImageRecord, draft_id: UUID) -> Any:
    return producer.finalize(
        tenant_id=TENANT_ID,
        draft_id=draft_id,
        brief=brief,
        kit=_kit(),
        asset=asset,
        budget=BUDGET,
        revision=1,
    )


def test_a_clip_on_2_5_is_made_as_a_480p_draft_that_keeps_what_its_final_needs() -> None:
    seedance, draft_id = DraftSeedance(), uuid4()
    outcome = _producer(_store(), seedance, RecordingFitter()).produce(
        tenant_id=TENANT_ID, draft_id=draft_id, brief=_clip(), kit=_kit(), copy=COPY, budget=BUDGET
    )

    assert outcome.failure is None
    (request,) = seedance.requests
    assert request.params["draft"] is True
    # the configured 720p does not apply: a draft is 480p
    assert request.params["resolution"] == "480p"
    (video,) = outcome.media
    assert video.params["seed"] == 33608
    assert video.params["resolution"] == "480p"
    assert (video.width, video.height) == (480, 854)
    block = video.params["draft"]
    assert block["status"] == DRAFT_READY
    assert block["task_id"] == "cgt-draft"
    assert block["created_at"] == CREATED_AT
    assert block["model"] == DRAFT_MODEL and block["finish"] == "clip"
    # the draft's own cost (48k tokens at 10.70/M), recorded apart from the final's
    assert Decimal(block["cost_usd"]) == Decimal("0.513600")
    assert outcome.usage[0].cost_usd == Decimal("0.513600")
    assert draft_pending(video.params)


def test_a_model_without_draft_mode_makes_the_video_directly() -> None:
    from .test_creative_media_byteplus import FakeSeedance

    pricing = JsonPricingTable("v5")
    seedance = FakeSeedance()
    producer = MediaProducer(
        store=_store(),
        router=CreativeRouter({"seedance": seedance}, pricing, KeysByProvider()),
        credentials=KeysByProvider(),
        pricing=pricing,
        download=lambda url: b"mp4",
    )
    outcome = producer.produce(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=_clip(), kit=_kit(), copy=COPY, budget=BUDGET
    )
    (request,) = seedance.requests
    assert "draft" not in request.params and request.params["resolution"] == "720p"
    (video,) = outcome.media
    assert "draft" not in video.params and not draft_pending(video.params)


def test_2_5_crops_an_operators_frame_to_the_pieces_ratio() -> None:
    """2.5 keeps the opening frame's own aspect: an 800×600 frame would make a landscape
    reel, so it goes cropped to 9:16."""
    import base64
    import io

    from PIL import Image

    seedance = DraftSeedance()
    _producer(_store(), seedance, RecordingFitter()).produce(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=_clip(), kit=_kit(), copy=COPY, budget=BUDGET
    )
    url = str(seedance.requests[0].params["first_frame"])
    frame = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
    assert abs(frame.width / frame.height - 9 / 16) < 0.01


def test_the_final_comes_from_the_draft_id_alone_and_is_re_encoded_with_the_logo() -> None:
    store, seedance, fitter, draft_id = _store(), DraftSeedance(), RecordingFitter(), uuid4()
    producer = _producer(store, seedance, fitter)
    brief = _clip(brand_logo_key=f"uploads/{TENANT_ID}/logo.png")
    (draft,) = producer.produce(
        tenant_id=TENANT_ID, draft_id=draft_id, brief=brief, kit=_kit(), copy=COPY, budget=BUDGET
    ).media
    fitter.calls.clear()

    outcome = _finalize(producer, brief, _record(draft), draft_id)

    assert outcome.failure is None
    final_request = seedance.requests[-1].params
    assert final_request["draft_task_id"] == "cgt-draft"
    assert final_request["model"] == DRAFT_MODEL
    assert "prompt" not in final_request and "first_frame" not in final_request
    # H.265 10-bit in, H.264 out at the final's size, logo laid, sound kept
    (call,) = fitter.calls
    assert call["data"] == b"hevc-bytes"
    assert call["size"] == (1080, 1920)
    assert call["overlay"] is not None and call["keep_audio"] is True
    assert call["x264"] == DETAIL_X264
    media = outcome.media
    assert media is not None and media.position == draft.position
    # under a key of its own per order (`attempt`): a retry never collides with it
    assert re.search(r"clip-final-[0-9a-f]{12}\.mp4$", media.object_key)
    assert store.files[media.object_key] == b"h264-hevc-bytes"
    assert (media.width, media.height) == (1080, 1920)
    assert media.params["resolution"] == "1080p"
    block = media.params["draft"]
    assert block["status"] == DRAFT_FINAL
    assert block["final_task_id"] == "cgt-final"
    assert block["draft_object_key"] == draft.object_key
    # the final's spend is its own (243k tokens at 11.7/M)
    assert Decimal(block["final_cost_usd"]) == Decimal("2.843100")
    assert outcome.spent_usd == Decimal("2.843100")
    assert not draft_pending(media.params)


def test_a_logo_that_will_not_lay_leaves_the_final_without_it() -> None:
    store, fitter, draft_id = _store(), RecordingFitter(fail_overlay=True), uuid4()
    producer = _producer(store, DraftSeedance(), fitter)
    brief = _clip(brand_logo_key=f"uploads/{TENANT_ID}/logo.png")
    (draft,) = producer.produce(
        tenant_id=TENANT_ID, draft_id=draft_id, brief=brief, kit=_kit(), copy=COPY, budget=BUDGET
    ).media

    outcome = _finalize(producer, brief, _record(draft), draft_id)

    assert outcome.failure is None and outcome.media is not None
    assert outcome.media.params["logo"] is False


def test_an_expired_draft_is_refused_before_any_call() -> None:
    seedance, draft_id = DraftSeedance(), uuid4()
    producer = _producer(_store(), seedance, RecordingFitter())
    (draft,) = producer.produce(
        tenant_id=TENANT_ID, draft_id=draft_id, brief=_clip(), kit=_kit(), copy=COPY, budget=BUDGET
    ).media
    old = {**draft.params, "draft": {**draft.params["draft"], "created_at": 1_000}}
    calls = len(seedance.requests)

    outcome = _finalize(producer, _clip(), _record(_replace_params(draft, old)), draft_id)

    assert outcome.media is None and outcome.detail == DRAFT_EXPIRED_TEXT
    assert outcome.failure == FailureReason.INVALID_PARAMETERS.value
    assert len(seedance.requests) == calls
    assert draft_expired({"created_at": 1_000})
    assert not draft_expired({"created_at": time.time()})
    assert not draft_expired({})  # no date: ModelArk judges


def test_a_failed_final_says_why_and_costs_nothing() -> None:
    draft_id = uuid4()
    producer = _producer(_store(), DraftSeedance(fail_final=True), RecordingFitter())
    (draft,) = producer.produce(
        tenant_id=TENANT_ID, draft_id=draft_id, brief=_clip(), kit=_kit(), copy=COPY, budget=BUDGET
    ).media

    outcome = _finalize(producer, _clip(), _record(draft), draft_id)

    assert outcome.media is None and outcome.failure == FailureReason.PROVIDER_ERROR.value
    assert outcome.detail and outcome.spent_usd == 0


def test_a_video_that_is_no_draft_has_no_final() -> None:
    record = ImageRecord(
        id=uuid4(), media_url="k", width=1, height=1, aspect_ratio="9:16", params={}
    )
    outcome = _finalize(
        _producer(_store(), DraftSeedance(), RecordingFitter()), _clip(), record, uuid4()
    )
    assert outcome.media is None and outcome.failure == FailureReason.INVALID_PARAMETERS.value


def test_a_talking_seedance_video_is_a_draft_finished_at_its_own_size_untouched() -> None:
    store, seedance, fitter, draft_id = _store(), DraftSeedance(), RecordingFitter(), uuid4()
    producer = _producer(store, seedance, fitter)
    brief = _seedance_brief(ContentFormat.REELS_9_16)
    outcome = producer.produce(
        tenant_id=TENANT_ID, draft_id=draft_id, brief=brief, kit=_kit(), copy=COPY, budget=BUDGET
    )
    assert outcome.failure is None, outcome.detail
    video = next(item for item in outcome.media if item.media_type == "video")
    assert video.params["draft"]["finish"] == "video"
    assert seedance.requests[0].params["draft"] is True

    final = _finalize(producer, brief, _record(video), draft_id)

    assert final.media is not None
    (call,) = fitter.calls
    assert call["overlay"] is None and call["keep_audio"] is True
    assert call["size"] == (1080, 1920)


def _replace_params(write: Any, params: dict[str, Any]) -> Any:
    from dataclasses import replace

    return replace(write, params=params)


def test_a_clip_with_references_on_2_5_is_sent_as_a_reference_task() -> None:
    """The generator only creates videos: on 2.5 a clip with references says so, so a
    reference video is never taken for one to edit or extend."""
    from .test_creative_clip import RecordingLinks

    store, seedance = _store(), DraftSeedance()
    store.files[f"uploads/{TENANT_ID}/ref.mp4"] = b"mp4-reference"
    producer = _producer(store, seedance, RecordingFitter())
    producer._reference_links = RecordingLinks()
    brief = _clip(clip_video_keys=(f"uploads/{TENANT_ID}/ref.mp4",))
    outcome = producer.produce(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit(), copy=COPY, budget=BUDGET
    )
    assert outcome.failure is None, outcome.detail
    (request,) = seedance.requests
    assert request.params["omni_reference_task_type"] == "reference"
    assert request.params["reference_videos"]
    # and the real adapter accepts that request as is
    from qualify_creative.adapters import SeedanceVideoAdapter

    body = SeedanceVideoAdapter(model=DRAFT_MODEL).spec(request.params).body()
    assert body["omni_reference_task_type"] == "reference" and body["draft"] is True


def test_a_frames_only_clip_sends_no_task_type() -> None:
    seedance = DraftSeedance()
    _producer(_store(), seedance, RecordingFitter()).produce(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=_clip(), kit=_kit(), copy=COPY, budget=BUDGET
    )
    assert "omni_reference_task_type" not in seedance.requests[0].params

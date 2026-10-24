"""Review 2026-10-23 of the Seedance 2.5 finals (m-24820142): what the final lays is
checked before the 1080p is paid for; the raw 1080p is kept as soon as it is downloaded,
so a fitter failure costs a retry nothing; every path that sends a first frame to a
model that keeps the frame's own aspect (2.5, `ratio: adaptive`) crops it to the named
ratio it records."""

from __future__ import annotations

import base64
import io
from dataclasses import replace
from decimal import Decimal
from typing import Any
from uuid import uuid4

from PIL import Image
from qualify_creative.enums import ContentFormat, ContentKind, FailureReason, SlideText
from qualify_creative.schemas import CarouselSlide, SlideSource
from qualify_creative.video import FittedVideo

from qualify_api.creative.draft_mode import DRAFT_FINAL, draft_expired, kept_raw_final
from qualify_api.creative.media import SCENE_SIZES, SEEDANCE_RATIOS, MediaProducer

from .test_creative_media_byteplus import BUDGET, COPY, TENANT_ID, _brief, _kit, _seedance_brief
from .test_creative_seedance_draft import (
    DraftSeedance,
    RecordingFitter,
    _clip,
    _finalize,
    _producer,
    _record,
    _store,
)
from .test_creative_seedance_draft import MemoryStore as _MemoryStore


class FlakyFitter(RecordingFitter):
    """Fails the final's re-encode the first `failures` times."""

    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures

    def fit(self, data: bytes, *, size: tuple[int, int], **kw: Any) -> FittedVideo:
        if "x264" in kw and self.failures:
            self.failures -= 1
            self.calls.append({"data": data, "size": size, **kw})
            raise RuntimeError("ffmpeg died")
        return super().fit(data, size=size, **kw)


def _finals(seedance: DraftSeedance) -> int:
    return sum(1 for r in seedance.requests if "draft_task_id" in r.params)


def _frame_aspect(url: str) -> float:
    """The sent frame's aspect (the data URL may be scaled down, never reshaped)."""
    image = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
    return round(image.width / image.height, 2)


def _scene_aspect(brief: Any) -> float:
    width, _, height = SCENE_SIZES[SEEDANCE_RATIOS[brief.format]].partition("x")
    return round(int(width) / int(height), 2)


def test_a_fitter_failure_keeps_the_paid_raw_final_and_the_retry_reuses_it() -> None:
    store, seedance, fitter, draft_id = _store(), DraftSeedance(), FlakyFitter(1), uuid4()
    producer = _producer(store, seedance, fitter)
    (draft,) = producer.produce(
        tenant_id=TENANT_ID, draft_id=draft_id, brief=_clip(), kit=_kit(), copy=COPY, budget=BUDGET
    ).media
    asset = _record(draft)

    failed = _finalize(producer, _clip(), asset, draft_id)

    assert failed.media is None and _finals(seedance) == 1
    assert failed.spent_usd == Decimal("2.843100")  # paid, and recorded as spent
    raw = failed.draft_changes["raw_final"]
    assert store.files[raw["key"]] == b"hevc-bytes"
    assert raw["key"].endswith("clip-final-raw.mp4") and raw["cost_usd"] == "2.843100"

    # the service keeps `draft_changes` in the block; the retry finishes the saved file
    block = {**asset.params["draft"], **failed.draft_changes, "status": "rendering"}
    retried = _finalize(
        producer, _clip(), replace(asset, params={**asset.params, "draft": block}), draft_id
    )

    assert retried.failure is None and _finals(seedance) == 1  # not paid again
    assert retried.spent_usd == 0
    media = retried.media
    assert media is not None and media.params["draft"]["status"] == DRAFT_FINAL
    assert media.params["draft"]["final_cost_usd"] == "2.843100"
    assert media.params["draft"]["final_task_id"] == "cgt-final"
    assert media.params["task_id"] == "cgt-final" and media.params["resolution"] == "1080p"


def test_a_kept_raw_final_never_expires_and_an_unreadable_one_is_paid_again() -> None:
    raw = {"key": "t/x/clip-final-raw.mp4"}
    assert kept_raw_final({"raw_final": raw}) == raw
    assert not draft_expired({"created_at": 1_000, "raw_final": raw})
    assert kept_raw_final({"raw_final": {"key": ""}}) is None

    store, seedance, draft_id = _store(), DraftSeedance(), uuid4()
    producer = _producer(store, seedance, RecordingFitter())
    (draft,) = producer.produce(
        tenant_id=TENANT_ID, draft_id=draft_id, brief=_clip(), kit=_kit(), copy=COPY, budget=BUDGET
    ).media
    asset = _record(draft)
    block = {**asset.params["draft"], "raw_final": {"key": "gone.mp4"}}
    outcome = _finalize(
        producer, _clip(), replace(asset, params={**asset.params, "draft": block}), draft_id
    )

    assert outcome.failure is None and _finals(seedance) == 1


def _gallery() -> Any:
    return _brief(
        ContentKind.CAROUSEL,
        slides=(
            CarouselSlide(source=SlideSource.ANIMATED),
            CarouselSlide(source=SlideSource.GENERATED),
        ),
    )


def test_a_slide_whose_words_are_missing_fails_before_the_final_is_paid() -> None:
    store, seedance, draft_id = _store(), DraftSeedance(), uuid4()
    producer = _producer(store, seedance, RecordingFitter())
    brief = _gallery()
    outcome = producer.produce(
        tenant_id=TENANT_ID, draft_id=draft_id, brief=brief, kit=_kit(), copy=COPY, budget=BUDGET
    )
    slide = _record(next(m for m in outcome.media if m.media_type == "video"))
    block = {**slide.params["draft"], "words": True, "overlay_key": None}

    final = _finalize(
        producer, brief, replace(slide, params={**slide.params, "draft": block}), draft_id
    )

    assert final.failure == FailureReason.PROVIDER_ERROR.value and final.spent_usd == 0
    assert _finals(seedance) == 0

    # a layer that is named but unreadable fails the same way, before any spend
    block = {**block, "overlay_key": "t/x/missing-words.png"}
    final = _finalize(
        producer, brief, replace(slide, params={**slide.params, "draft": block}), draft_id
    )
    assert final.media is None and final.spent_usd == 0 and _finals(seedance) == 0


def test_every_first_frame_is_cropped_to_the_named_ratio_on_2_5() -> None:
    # the talking video: Seedream's frame (4:5 here) goes cropped to the reel's 9:16
    seedance = DraftSeedance()
    brief = _seedance_brief(ContentFormat.REELS_9_16)
    producer = _producer(_store(), seedance, RecordingFitter())
    producer.produce(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit(), copy=COPY, budget=BUDGET
    )
    assert _frame_aspect(str(seedance.requests[0].params["first_frame"])) == _scene_aspect(brief)

    # the gallery's animated slide: its scene goes cropped to the slide's named ratio
    seedance = DraftSeedance()
    brief = _gallery()
    producer = _producer(_store(), seedance, RecordingFitter())
    producer.produce(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit(), copy=COPY, budget=BUDGET
    )
    (request,) = seedance.requests
    assert _frame_aspect(str(request.params["first_frame"])) == _scene_aspect(brief)


# -- review round 3 (m-24820142): a final whose last write never landed is finishable -----


class LockedR2(_MemoryStore):
    """An R2 store with the bucket's object lock, as `R2ReadingMediaStore.keep` answers
    it: a key, once written, refuses another write (`ObjectLockedByBucketPolicy`) —
    a success when it already holds the same bytes, `keep` False otherwise."""

    def __init__(self, files: dict[str, bytes], *, refuse: str = "") -> None:
        super().__init__(files)
        self.refuse = refuse
        self.writes: list[str] = []

    def keep(self, tenant_id: Any, key: str, data: bytes, content_type: str) -> bool:
        if key in self.files:
            return self.files[key] == data
        if self.refuse and key.endswith(self.refuse):
            return False
        self.writes.append(key)
        self.files[key] = data
        return True


def _locked() -> LockedR2:
    return LockedR2(dict(_store().files))


def _ordered(asset: Any, attempt: str) -> Any:
    """`asset` as a run reads it after an order: `rendering` for `attempt`."""
    block = {**asset.params["draft"], "status": "rendering", "attempt": attempt}
    return replace(asset, params={**asset.params, "draft": block})


def _finalize_hearing(
    producer: MediaProducer, asset: Any, draft_id: Any, heard: list[dict[str, Any]]
) -> Any:
    return producer.finalize(
        tenant_id=TENANT_ID,
        draft_id=draft_id,
        brief=_clip(),
        kit=_kit(),
        asset=asset,
        budget=BUDGET,
        revision=1,
        on_raw_kept=lambda raw: heard.append(dict(raw)),
    )


def test_the_raw_final_is_recorded_before_the_re_encode_and_rides_on_success() -> None:
    store, seedance, fitter, draft_id = _locked(), DraftSeedance(), FlakyFitter(1), uuid4()
    producer = _producer(store, seedance, fitter)
    (draft,) = producer.produce(
        tenant_id=TENANT_ID, draft_id=draft_id, brief=_clip(), kit=_kit(), copy=COPY, budget=BUDGET
    ).media
    heard: list[dict[str, Any]] = []
    fitted_when_heard: list[int] = []
    asset = _ordered(_record(draft), "a" * 32)

    def hear(raw: Any) -> None:
        heard.append(dict(raw))
        fitted_when_heard.append(sum(1 for c in fitter.calls if "x264" in c))

    failed = producer.finalize(
        tenant_id=TENANT_ID,
        draft_id=draft_id,
        brief=_clip(),
        kit=_kit(),
        asset=asset,
        budget=BUDGET,
        revision=1,
        on_raw_kept=hear,
    )

    # heard the moment it was kept — before the fitter ran (and failed)
    assert failed.media is None and fitted_when_heard == [0]
    (raw,) = heard
    assert raw["key"].endswith("clip-final-raw.mp4") and store.files[raw["key"]] == b"hevc-bytes"

    # the retry finishes the saved file, and its success carries the raw file too: the
    # failure the service writes when the final cannot be put in place keeps it
    block = {**asset.params["draft"], "raw_final": raw}
    done = _finalize_hearing(
        producer, replace(asset, params={**asset.params, "draft": block}), draft_id, heard
    )
    assert done.media is not None and _finals(seedance) == 1 and len(heard) == 1
    assert done.draft_changes == {"raw_final": raw}


def test_a_final_saved_but_never_settled_is_finished_by_the_retry() -> None:
    """The process died after saving `-final-raw` and the final, before any write: the
    retry pays again (nothing recorded the raw file), REUSES the raw object (the same
    bytes; the object lock refuses writing it again) and saves its final under its own
    key."""
    store, seedance, draft_id = _locked(), DraftSeedance(), uuid4()
    producer = _producer(store, seedance, RecordingFitter())
    (draft,) = producer.produce(
        tenant_id=TENANT_ID, draft_id=draft_id, brief=_clip(), kit=_kit(), copy=COPY, budget=BUDGET
    ).media
    asset = _record(draft)

    first = _finalize_hearing(producer, _ordered(asset, "1" * 32), draft_id, [])
    assert first.media is not None
    writes = len(store.writes)

    heard: list[dict[str, Any]] = []
    second = _finalize_hearing(producer, _ordered(asset, "2" * 32), draft_id, heard)

    assert second.failure is None and second.media is not None
    assert second.media.object_key != first.media.object_key
    assert second.media.object_key.endswith("clip-final-222222222222.mp4")
    (raw,) = heard
    assert raw["key"] == first.draft_changes["raw_final"]["key"]  # reused, not re-written
    assert all("final-raw" not in key for key in store.writes[writes:])

    # a DIFFERENT raw file already there (another download): kept beside it, not refused
    producer._download = lambda url: b"other-hevc-bytes"
    heard.clear()
    third = _finalize_hearing(producer, _ordered(asset, "3" * 32), draft_id, heard)
    assert third.media is not None
    (raw,) = heard
    assert raw["key"].endswith("clip-final-raw-333333333333.mp4")
    assert store.files[raw["key"]] == b"other-hevc-bytes"


def test_a_slide_whose_words_layer_cannot_be_kept_fails_the_generation() -> None:
    """A draft that prints words but lost its layer could never be finished: the layer
    is a required file, like the slide's video."""
    store, seedance, draft_id = _locked(), DraftSeedance(), uuid4()
    store.refuse = "-words.png"
    producer = _producer(store, seedance, RecordingFitter())
    worded = _brief(
        ContentKind.CAROUSEL,
        slides=(
            CarouselSlide(source=SlideSource.ANIMATED, text=SlideText.HOOK),
            CarouselSlide(source=SlideSource.GENERATED),
        ),
    )

    outcome = producer.produce(
        tenant_id=TENANT_ID,
        draft_id=draft_id,
        brief=worded,
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
    )

    assert outcome.failure == FailureReason.PROVIDER_ERROR.value and not outcome.media
    assert "R2" in outcome.detail
    assert outcome.spent_usd > 0  # the draft was paid: its spend is still recorded

    # with the layer kept, the draft records it next to `words`
    store.refuse = ""
    outcome = producer.produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=worded,
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
    )
    slide = next(m for m in outcome.media if m.media_type == "video")
    block = slide.params["draft"]
    assert block["words"] is True and store.files[block["overlay_key"]]


# -- review round 4 (m-24820142): the opening frame is cropped, never upscaled ----------


def test_the_opening_frame_is_cropped_at_its_own_resolution_and_encoded_once() -> None:
    """A 400x500 (4:5) frame for a 9:16 reel on 2.5: cut to 9:16 at its own height —
    not blown up to the scene's 1440x2560 and sent through a lossless PNG first."""
    producer = _producer(_store(), DraftSeedance(), RecordingFitter())
    source = io.BytesIO()
    Image.new("RGB", (400, 500), (200, 30, 30)).save(source, format="PNG")

    sent = Image.open(io.BytesIO(producer._opening_frame(source.getvalue(), "9:16", None)))

    assert sent.format == "JPEG"
    assert sent.size == (281, 500)  # round(500 * 9 / 16) wide, the source's own height
    assert round(sent.width / sent.height, 2) == round(9 / 16, 2)

    # a model that takes the named ratio itself gets the frame as it is, normalized once
    whole = producer._opening_frame(source.getvalue(), "9:16", "seedance-1-0-pro-250528")
    whole_image = Image.open(io.BytesIO(whole))
    assert whole_image.format == "JPEG" and whole_image.size == (400, 500)


def test_a_talking_video_with_no_room_for_its_line_fails_before_paying(
    monkeypatch: Any,
) -> None:
    """Review round 4: the line is settled before the first frame is paid for — a
    motion prompt that leaves it no room fails the piece with nothing spent."""
    from qualify_api.creative import media as media_module

    monkeypatch.setattr(
        media_module, "motion_prompt", lambda **kw: "m" * media_module.MEDIA_PROMPT_BUDGET
    )
    seedance = DraftSeedance()
    producer = _producer(_store(), seedance, RecordingFitter())

    outcome = producer.produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=_seedance_brief(ContentFormat.REELS_9_16),
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
    )

    assert outcome.failure == FailureReason.INVALID_PARAMETERS.value
    assert outcome.detail == media_module.SPOKEN_LINE_NO_ROOM_TEXT
    assert outcome.spent_usd == 0 and seedance.requests == [] and not outcome.media


def test_a_silent_drafts_final_is_asked_as_silent() -> None:
    """Review round 4: the draft block records whether the draft was made with sound,
    and the final's request carries it (for its payload and provenance — the adapter
    never sends it), instead of the family's default «with sound»."""

    class EchoSeedance(DraftSeedance):
        def generate(self, request: Any, *, api_key: str) -> Any:
            result = super().generate(request, api_key=api_key)
            sound = bool(request.params.get("generate_audio", True))
            return replace(result, payload={**result.payload, "generate_audio": sound})

    seedance, draft_id = EchoSeedance(), uuid4()
    producer = _producer(_store(), seedance, RecordingFitter())
    silent = _clip(clip_audio=False)
    (draft,) = producer.produce(
        tenant_id=TENANT_ID, draft_id=draft_id, brief=silent, kit=_kit(), copy=COPY, budget=BUDGET
    ).media
    assert draft.params["draft"]["audio"] is False

    done = _finalize(producer, silent, _ordered(_record(draft), "a" * 32), draft_id)

    assert done.media is not None
    final_request = next(r for r in seedance.requests if "draft_task_id" in r.params)
    assert final_request.params["generate_audio"] is False

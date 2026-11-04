"""m-24820842 (2026-11-03, drafts 9808559f / cb647505 / 0bcd259b): ModelArk downloads a
clip's reference videos inside the task POST, and 1080p stock references made three POSTs
time out. Each reference is now made light (720p short side, <= 30 fps, crf 23, no audio)
and cut to the clip — within the model family's limits — BEFORE the copy is paid, stored
once per draft revision and reused by the run that sends it. A reel replica (`edit`)
keeps its original length."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from qualify_creative.enums import ContentKind
from qualify_creative.schemas import MediaInputs
from qualify_creative.video import FittedVideo

from qualify_api.creative.brand_references import BrandReferenceError
from qualify_api.creative.media import (
    REFERENCE_VIDEO_UNREADABLE_TEXT,
    generated_key,
    reference_trim_seconds,
)

from .test_creative_clip import REF_MODEL, RecordingLinks, _clip_producer, _clip_store
from .test_creative_media_byteplus import TENANT_ID, FakeSeedance, _brief, _produce

V20 = "dreamina-seedance-2-0-260128"
V25 = "dreamina-seedance-2-5-260628"


def _media(seconds: int = 5, videos: int = 1, mode: str = "motion") -> MediaInputs:
    return MediaInputs(
        duration_seconds=seconds,
        clip_video_keys=tuple(f"uploads/{TENANT_ID}/ref{i}.mp4" for i in range(videos)),
        clip_reference_mode=mode,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    ("model", "seconds", "videos", "expected"),
    [
        (V20, 5, 1, 5.0),  # the clip's own length
        (V20, 10, 1, 10.0),
        (V20, 10, 2, 7.5),  # 15 s in all on 2.0, shared
        (V20, 10, 3, 5.0),
        (V25, 15, 3, 10.0),  # 30 s in all on 2.5
        (V25, 15, 1, 15.0),
        (V25, 30, 1, 30.0),
        (V20, 30, 1, 15.0),  # 15 s each at most on 2.0
    ],
)
def test_each_reference_is_cut_to_the_clip_within_the_familys_limits(
    model: str, seconds: int, videos: int, expected: float
) -> None:
    assert reference_trim_seconds(_media(seconds, videos), model) == expected


def test_a_reel_replica_keeps_its_original_length() -> None:
    assert reference_trim_seconds(_media(10, 1, mode="edit"), V25) is None


class ReferenceFitter:
    """Records `fit_reference` and answers a small file named by what it was given."""

    def __init__(self, *, broken: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.broken = broken

    def fit(self, data: bytes, *, size: tuple[int, int], **kw: Any) -> FittedVideo:
        return FittedVideo(data=b"fit-" + data, width=size[0], height=size[1], duration_sec=5.0)

    def fit_reference(self, data: bytes, **kw: Any) -> FittedVideo:
        self.calls.append({"data": data, **kw})
        if self.broken:
            raise ValueError("not a video")
        return FittedVideo(data=b"light-" + data, width=1280, height=720, duration_sec=4.9)


def _setup(fitter: ReferenceFitter) -> tuple[Any, Any, Any, RecordingLinks]:
    store, seedance, links = _clip_store(), FakeSeedance(), RecordingLinks()
    store.files[f"uploads/{TENANT_ID}/ref.mp4"] = b"mp4-reference-1080p"
    producer = _clip_producer(store, seedance, links)
    producer._fitter = fitter
    return producer, store, seedance, links


def _clip_brief(**media: Any) -> Any:
    return _brief(ContentKind.CLIP, clip_video_keys=(f"uploads/{TENANT_ID}/ref.mp4",), **media)


def test_the_light_reference_is_sent_and_priced_not_the_original() -> None:
    fitter = ReferenceFitter()
    producer, store, seedance, links = _setup(fitter)
    draft_id = uuid4()
    outcome = _produce(producer, _clip_brief(duration_seconds=5), draft_id)

    assert outcome.failure is None
    (call,) = fitter.calls
    assert call["data"] == b"mp4-reference-1080p" and call["max_seconds"] == 5.0
    ((sent_key, content_type),) = links.calls
    assert content_type == "video/mp4" and "reference-" in sent_key and "-t5" in sent_key
    assert store.files[sent_key] == b"light-mp4-reference-1080p"
    assert sent_key == generated_key(TENANT_ID, draft_id, sent_key.rsplit("/", 1)[1])
    (request,) = seedance.requests
    assert request.params["reference_video_seconds"] == 4.9  # what ModelArk bills


def test_it_is_fitted_once_before_the_copy_and_reused_by_the_run() -> None:
    fitter = ReferenceFitter()
    producer, _store, _seedance, links = _setup(fitter)
    draft_id = uuid4()
    brief = _clip_brief()
    producer.prepare_reference_videos(tenant_id=TENANT_ID, draft_id=draft_id, brief=brief)
    assert len(fitter.calls) == 1
    outcome = _produce(producer, brief, draft_id)
    assert outcome.failure is None
    assert len(fitter.calls) == 1  # the stored file was reused, not encoded again
    assert "reference-" in links.calls[0][0]


def test_an_unreadable_reference_is_refused_before_the_copy() -> None:
    producer, _store, seedance, _links = _setup(ReferenceFitter(broken=True))
    with pytest.raises(BrandReferenceError) as refused:
        producer.prepare_reference_videos(
            tenant_id=TENANT_ID, draft_id=uuid4(), brief=_clip_brief()
        )
    assert refused.value.detail == REFERENCE_VIDEO_UNREADABLE_TEXT
    assert seedance.requests == []


def test_a_replica_reference_is_made_light_but_never_cut() -> None:
    fitter = ReferenceFitter()
    producer, _store, _seedance, _links = _setup(fitter)
    brief = _clip_brief(
        clip_reference_mode="edit",
        duration_seconds=10,
        clip_image_keys=(f"uploads/{TENANT_ID}/product.jpg",),
    )
    producer._seedance_reference_model = V25
    producer.prepare_reference_videos(tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief)
    assert fitter.calls[0]["max_seconds"] is None


def test_without_a_fitter_that_can_the_original_goes_as_before() -> None:
    store, seedance, links = _clip_store(), FakeSeedance(), RecordingLinks()
    outcome = _produce(_clip_producer(store, seedance, links), _clip_brief(), uuid4())
    assert outcome.failure is None
    assert links.calls == [(f"uploads/{TENANT_ID}/ref.mp4", "video/mp4")]
    assert REF_MODEL  # the reference model of these fakes

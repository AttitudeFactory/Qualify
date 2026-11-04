"""A clip's copy as subtitles (founder, 2026-11-03: «como subtítulos»): laid after
Seedance in the brand's type — on the 480p draft and again on its 1080p final — never asked
of the video model. Same fakes as `test_creative_seedance_draft.py`."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any
from uuid import uuid4

from qualify_creative.enums import FailureReason
from qualify_creative.video import FittedVideo, SubtitleLayer

from qualify_api.creative.media import SUBTITLES_NOT_ADDED

from .test_creative_media_byteplus import BUDGET, COPY, TENANT_ID, _kit
from .test_creative_seedance_draft import (
    DraftSeedance,
    RecordingFitter,
    _clip,
    _finalize,
    _producer,
    _record,
    _store,
)


class SubtitleFitter(RecordingFitter):
    """The draft's fitter, which also burns subtitles (as `PyAvVideoFitter.subtitle`)."""

    def __init__(self, *, fail_subtitles: bool = False) -> None:
        super().__init__()
        self.fail_subtitles = fail_subtitles
        self.layers: list[SubtitleLayer] = []

    def subtitle(
        self, data: bytes, *, layers: Callable[[tuple[int, int]], Sequence[SubtitleLayer]]
    ) -> FittedVideo:
        self.calls.append({"subtitle": data})
        if self.fail_subtitles:
            raise ValueError("the file has no video stream")
        self.layers = list(layers((720, 1280)))
        return FittedVideo(data=b"sub-" + data, width=720, height=1280, duration_sec=5.0)


def _draft(fitter: SubtitleFitter, **media: Any) -> tuple[Any, Any, Any, Any]:
    store, seedance, draft_id = _store(), DraftSeedance(), uuid4()
    producer = _producer(store, seedance, fitter)
    brief = _clip(**media)
    outcome = producer.produce(
        tenant_id=TENANT_ID, draft_id=draft_id, brief=brief, kit=_kit(), copy=COPY, budget=BUDGET
    )
    return producer, brief, outcome, (store, seedance, draft_id)


def test_off_by_default_nothing_is_laid_and_nothing_is_recorded() -> None:
    fitter = SubtitleFitter()
    _, _, outcome, _ = _draft(fitter)
    assert outcome.failure is None and fitter.calls == []
    (video,) = outcome.media
    assert video.params["clip_subtitles"] is False and video.params["subtitles"] == []


def test_on_the_hook_and_the_cta_are_laid_over_the_draft_never_asked_of_seedance() -> None:
    fitter = SubtitleFitter()
    _, _, outcome, (store, seedance, _) = _draft(fitter, clip_subtitles=True)
    assert outcome.failure is None
    (request,) = seedance.requests
    # the video model is asked for no lettering, exactly as with the option off
    _, _, off, (_, seedance_off, _) = _draft(SubtitleFitter())
    assert request.params["prompt"] == seedance_off.requests[0].params["prompt"]
    assert [c for c in fitter.calls if "subtitle" in c] == [{"subtitle": b"hevc-bytes"}]
    assert len(fitter.layers) == 2 and all(layer.png[:4] == b"\x89PNG" for layer in fitter.layers)
    (video,) = outcome.media
    texts = [cue["text"] for cue in video.params["subtitles"]]
    assert texts == [COPY.hook, COPY.cta]
    assert store.files[video.object_key] == b"sub-hevc-bytes"


def test_subtitles_that_cannot_be_laid_keep_the_paid_clip_with_a_warning() -> None:
    fitter = SubtitleFitter(fail_subtitles=True)
    _, _, outcome, (store, _, _) = _draft(fitter, clip_subtitles=True)
    assert outcome.failure is None
    assert SUBTITLES_NOT_ADDED in [w.code for w in outcome.warnings]
    (video,) = outcome.media
    assert video.params["subtitles"] == []  # its final lays none either
    assert store.files[video.object_key] == b"hevc-bytes"


def test_the_final_lays_the_same_subtitles_at_its_own_size() -> None:
    fitter = SubtitleFitter()
    producer, brief, outcome, (store, _, draft_id) = _draft(fitter, clip_subtitles=True)
    (draft,) = outcome.media
    fitter.calls.clear()

    final = _finalize(producer, brief, _record(draft), draft_id)

    assert final.failure is None and final.media is not None
    fit, subtitle = fitter.calls
    assert fit["size"] == (1080, 1920) and subtitle == {"subtitle": b"h264-hevc-bytes"}
    assert store.files[final.media.object_key] == b"sub-h264-hevc-bytes"


def test_a_final_whose_subtitles_fail_keeps_its_raw_file_for_a_free_retry() -> None:
    fitter = SubtitleFitter()
    producer, brief, outcome, (_, seedance, draft_id) = _draft(fitter, clip_subtitles=True)
    (draft,) = outcome.media
    fitter.fail_subtitles = True

    final = _finalize(producer, brief, _record(draft), draft_id)

    assert final.failure == FailureReason.PROVIDER_ERROR.value
    assert "subtítulos" in final.detail and final.media is None
    assert final.draft_changes and final.draft_changes["raw_final"]["key"]
    paid = len(seedance.requests)
    fitter.fail_subtitles = False
    retry = producer.finalize(
        tenant_id=TENANT_ID,
        draft_id=draft_id,
        brief=brief,
        kit=_kit(),
        asset=_record(draft).__class__(
            **{
                **_record(draft).__dict__,
                "params": {
                    **draft.params,
                    "draft": {**draft.params["draft"], **final.draft_changes},
                },
            }
        ),
        budget=BUDGET,
        revision=1,
    )
    assert retry.failure is None and len(seedance.requests) == paid  # nothing paid again

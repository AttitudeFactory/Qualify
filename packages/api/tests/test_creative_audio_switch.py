"""«Con audio» (§ request 2026-10-23: «añadas en el clip la opción de generar el clip con
audio, igual la galería»): a clip asks Seedance for its sound unless the operator turned it
off; a gallery's animated slide is silent unless the operator turned it on — and then the
soundtrack is kept by the fitter, recorded on the draft and kept again by its final."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError
from qualify_creative.enums import ContentKind
from qualify_creative.providers import GenerationRequest, GenerationResult
from qualify_creative.schemas import CarouselSlide, MediaInputs, SlideSource

from .test_creative_media_byteplus import (
    BUDGET,
    COPY,
    TENANT_ID,
    FakeSeedance,
    _brief,
    _kit,
)
from .test_creative_seedance_draft import (
    DraftSeedance,
    RecordingFitter,
    _clip,
    _finalize,
    _producer,
    _record,
    _store,
)


class EchoSeedance(DraftSeedance):
    """A 2.5 that makes the sound it was asked for (the final reuses the draft's)."""

    def generate(self, request: GenerationRequest, *, api_key: str) -> GenerationResult:
        result = super().generate(request, api_key=api_key)
        if "draft_task_id" not in request.params:
            result.payload["generate_audio"] = bool(request.params.get("generate_audio", True))
        return result


def _produce(producer: Any, brief: Any) -> Any:
    return producer.produce(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit(), copy=COPY, budget=BUDGET
    )


def _gallery(*, audio: bool) -> Any:
    return _brief(
        ContentKind.CAROUSEL,
        slides=(
            CarouselSlide(source=SlideSource.ANIMATED, audio=audio),
            CarouselSlide(source=SlideSource.GENERATED),
        ),
    )


# -- the brief ---------------------------------------------------------------------------


def test_a_stored_brief_reads_as_before_clip_with_sound_slide_without() -> None:
    assert MediaInputs().clip_audio is True
    stored = MediaInputs.model_validate(
        {"slides": [{"source": "animated"}, {"source": "generated"}]}
    )
    assert stored.clip_audio is True
    assert [slide.audio for slide in stored.slides] == [False, False]


def test_only_an_animated_slide_has_sound_of_its_own() -> None:
    assert CarouselSlide(source=SlideSource.ANIMATED, audio=True).audio is True
    with pytest.raises(ValidationError, match="only an animated slide has sound"):
        CarouselSlide(source=SlideSource.GENERATED, audio=True)


# -- the clip ------------------------------------------------------------------------------


@pytest.mark.parametrize("audio", [True, False])
def test_the_clip_asks_for_its_sound_as_the_operator_chose(audio: bool) -> None:
    seedance = EchoSeedance()
    producer = _producer(_store(), seedance, RecordingFitter())
    outcome = _produce(producer, _clip(clip_audio=audio))
    assert outcome.failure is None
    (request,) = seedance.requests
    assert request.params["generate_audio"] is audio


# -- the gallery's animated slide ------------------------------------------------------------


def test_a_slide_with_sound_keeps_it_through_the_fitter_and_its_final() -> None:
    store, seedance, fitter = _store(), EchoSeedance(), RecordingFitter()
    producer = _producer(store, seedance, fitter)
    brief = _gallery(audio=True)
    outcome = _produce(producer, brief)

    assert outcome.failure is None
    (request,) = seedance.requests
    assert request.params["generate_audio"] is True
    (fit,) = fitter.calls
    assert fit["keep_audio"] is True
    slide = next(m for m in outcome.media if m.media_type == "video")
    assert slide.params["spoken"] is True
    assert slide.params["draft"]["finish"] == "slide" and slide.params["draft"]["audio"] is True

    # the final reuses the draft's sound and the fitter keeps it again; the request names
    # the draft's setting for the payload's provenance only — the adapter never sends it
    # (`test_byteplus_draft`)
    fitter.calls.clear()
    final = _finalize(producer, brief, _record(slide), uuid4())
    assert final.failure is None
    assert seedance.requests[-1].params["generate_audio"] is True
    (call,) = fitter.calls
    assert call["keep_audio"] is True and call["size"] == brief.format.dimensions


def test_a_slide_stays_silent_by_default_draft_and_final() -> None:
    store, seedance, fitter = _store(), EchoSeedance(), RecordingFitter()
    producer = _producer(store, seedance, fitter)
    brief = _gallery(audio=False)
    outcome = _produce(producer, brief)

    (request,) = seedance.requests
    assert request.params["generate_audio"] is False
    (fit,) = fitter.calls
    assert fit["keep_audio"] is False
    slide = next(m for m in outcome.media if m.media_type == "video")
    assert slide.params["spoken"] is False and slide.params["draft"]["audio"] is False

    fitter.calls.clear()
    _finalize(producer, brief, _record(slide), uuid4())
    (call,) = fitter.calls
    assert call["keep_audio"] is False


def test_a_draft_from_before_the_switch_finishes_silent() -> None:
    """A slide drafted before 2026-10-23 has no `audio` in its block: its final is
    silent, as it always was."""
    store, seedance, fitter = _store(), EchoSeedance(), RecordingFitter()
    producer = _producer(store, seedance, fitter)
    brief = _gallery(audio=True)
    slide = next(m for m in _produce(producer, brief).media if m.media_type == "video")
    record = _record(slide)
    old = {k: v for k, v in record.params["draft"].items() if k != "audio"}
    record = replace(record, params={**record.params, "draft": old})
    fitter.calls.clear()
    _finalize(producer, brief, record, uuid4())
    (call,) = fitter.calls
    assert call["keep_audio"] is False


def test_a_silent_model_keeps_no_soundtrack_even_when_asked() -> None:
    """Seedance 1.0 has no audio: the adapter answers `generate_audio: False`, and the
    fitter is not asked to keep a track that is not there."""
    from .test_creative_media_byteplus import FakeFitter, FakeSeedream, _carousel_producer
    from .test_creative_media_byteplus import _store as _plain_store

    seedance, fitter = FakeSeedance(), FakeFitter()  # answers generate_audio=False
    producer = _carousel_producer(_plain_store(), FakeSeedream(), seedance, fitter)
    outcome = _produce(producer, _gallery(audio=True))

    assert outcome.failure is None
    (request,) = seedance.requests
    assert request.params["generate_audio"] is True  # asked …
    (fit,) = fitter.calls
    assert fit["keep_audio"] is False  # … but nothing came back to keep
    slide = next(m for m in outcome.media if m.media_type == "video")
    assert slide.params["spoken"] is False

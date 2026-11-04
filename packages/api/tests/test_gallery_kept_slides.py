"""m-24820842 (live test 2026-11-03, draft 320257e3): a gallery whose slide 3 was cut by
Seedream lost slides 1 and 2 — paid (USD 0.66) and thrown away — and a retry paid them
all again. Now the failed outcome carries the slides already made, and a later attempt
reuses them (`kept_slides`): only the missing slides reach a vendor. No network: the
vendors are scripted fakes run by the real `CreativeRouter`."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import uuid4

from qualify_creative.enums import FailureReason, GenerationTask, SlideSource, SlideText
from qualify_creative.providers import GenerationRequest, GenerationResult
from qualify_creative.schemas import CarouselSlide

from qualify_api.creative.media import (
    IMAGE_SERVICE_SLOW_TEXT,
    KEPT_FROM_REVISION,
    gallery_slide_is_paid,
)

from .test_creative_media_byteplus import (
    BUDGET,
    COPY,
    TENANT_ID,
    FakeFitter,
    FakeSeedance,
    FakeSeedream,
    _brief,
    _carousel_producer,
    _carousel_store,
    _kit,
)


class CutSeedream(FakeSeedream):
    """Seedream that drops the connection on its `cut_at`-th call (1-based), as BytePlus
    did at ~60 s on slide 3."""

    supports = frozenset({GenerationTask.PRODUCT_IMAGE})

    def __init__(self, cut_at: int) -> None:
        super().__init__()
        self.cut_at = cut_at

    def generate(self, request: GenerationRequest, *, api_key: str) -> GenerationResult:
        if len(self.requests) + 1 == self.cut_at:
            self.requests.append(request)
            raise RuntimeError(
                "SeedreamDisconnected: RemoteProtocolError: Server disconnected without "
                "sending a response."
            )
        return super().generate(request, api_key=api_key)


def _gallery() -> Any:
    from qualify_creative.enums import ContentKind

    return _brief(
        ContentKind.CAROUSEL,
        slides=(
            CarouselSlide(source=SlideSource.GENERATED, text=SlideText.HOOK),
            CarouselSlide(source=SlideSource.ANIMATED, scene_prompt="la smash girando"),
            CarouselSlide(source=SlideSource.GENERATED, text=SlideText.CTA),
        ),
        closing_slide=True,
    )


def _produce(producer: Any, brief: Any, draft_id: Any, **kwargs: Any) -> Any:
    return producer.produce(
        tenant_id=TENANT_ID,
        draft_id=draft_id,
        brief=brief,
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
        **kwargs,
    )


def test_a_slide_cut_by_seedream_keeps_the_slides_already_made() -> None:
    seedream, seedance, fitter = CutSeedream(cut_at=3), FakeSeedance(), FakeFitter()
    store, draft_id = _carousel_store(), uuid4()
    producer = _carousel_producer(store, seedream, seedance, fitter)

    outcome = _produce(producer, _gallery(), draft_id)

    assert outcome.failure == FailureReason.PROVIDER_ERROR.value
    # the owner reads which slide failed and why — never the vendor's text
    assert outcome.detail == f"Diapositiva 3: {IMAGE_SERVICE_SLOW_TEXT}"
    # slides 1 (Seedream) and 2 (Seedream + Seedance) are kept: in R2, with provenance
    assert [(m.position, m.media_type) for m in outcome.media] == [(0, "image"), (1, "video")]
    assert all(gallery_slide_is_paid(m) for m in outcome.media)
    assert all(m.object_key in store.files for m in outcome.media)
    assert [m.provider for m in outcome.media] == ["seedream", "seedance"]
    assert outcome.media[0].params["source"] == "generated"
    assert outcome.media[1].params["task_id"] == "cgt-1"  # the paid video, by its task
    # what was paid is still recorded: two scenes and one video
    assert [u.unit for u in outcome.usage] == ["piece", "piece", "second"]


def test_a_failure_before_any_slide_keeps_nothing_and_says_it_as_before() -> None:
    seedream = CutSeedream(cut_at=1)
    producer = _carousel_producer(_carousel_store(), seedream, FakeSeedance(), FakeFitter())
    outcome = _produce(producer, _gallery(), uuid4())
    assert outcome.failure == FailureReason.PROVIDER_ERROR.value
    assert outcome.media == () and outcome.detail == IMAGE_SERVICE_SLOW_TEXT


def test_the_next_attempt_pays_only_the_missing_slides() -> None:
    first_seedream = CutSeedream(cut_at=3)
    store, draft_id = _carousel_store(), uuid4()
    failed = _produce(
        _carousel_producer(store, first_seedream, FakeSeedance(), FakeFitter()),
        _gallery(),
        draft_id,
    )
    # as `failed_attempt` reads them back from the failed version
    kept = {
        m.position: replace(m, params={**m.params, KEPT_FROM_REVISION: 1}) for m in failed.media
    }

    seedream, seedance, fitter = FakeSeedream(), FakeSeedance(), FakeFitter()
    outcome = _produce(
        _carousel_producer(store, seedream, seedance, fitter),
        _gallery(),
        draft_id,
        revision=2,
        kept_slides=kept,
    )

    assert outcome.failure is None
    # one Seedream scene (slide 3), no Seedance: slides 1 and 2 were reused as they were
    assert len(seedream.requests) == 1 and seedance.requests == []
    assert [u.unit for u in outcome.usage] == ["piece"]
    assert [(m.position, m.media_type) for m in outcome.media] == [
        (0, "image"),
        (1, "video"),
        (2, "image"),
        (3, "image"),  # the closing slide, free, made again
    ]
    assert outcome.media[0] == kept[0] and outcome.media[1] == kept[1]
    assert outcome.media[0].params[KEPT_FROM_REVISION] == 1
    assert KEPT_FROM_REVISION not in outcome.media[2].params

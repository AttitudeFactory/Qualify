"""EF-14 (m-25026592), second review: inside a real worker preparation (ADR 41 queue) a
render service that is down never fails a Seedance clip — the piece waits and a later pass
draws the texts (the `CheckpointRouter` replays the paid call); a text that does not fit
still fails before anything is paid. `_seedance_task_recorded` is NOT mocked: inside a
preparation it cannot tell (`service._tasks_of` is empty there), so the decision does not
rest on it. Nothing paid, nothing rendered."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from qualify_creative.enums import FailureReason

from qualify_api.creative.heavy_video import LocalVideoWait
from qualify_api.creative.pipeline import Preparation, preparing
from qualify_api.creative.video_pipeline import recompose
from qualify_api.creative.video_pipeline.recompose import ClipComposeFailed

from .test_creative_media_byteplus import BUDGET, COPY, _kit
from .test_creative_media_byteplus import TENANT_ID as MEDIA_TENANT
from .test_video_pipeline_recompose import (
    WORDS,
    FakeComposer,
    _brief_with,
    _composing_producer,
)

DOWN = ClipComposeFailed(
    "No pudimos poner los textos sobre tu video en este momento.",
    failure=FailureReason.DEPENDENCY_FAILED.value,
    code="text_layer_unavailable",
)
TOO_WIDE = ClipComposeFailed(
    "El texto 1 tiene una palabra demasiado larga.",
    failure=FailureReason.INVALID_PARAMETERS.value,
    code="text_layer_refused",
    owner_fault=True,
)


@pytest.fixture(autouse=True)
def in_the_worker() -> Iterator[None]:
    from qualify_api.creative.process import mark_worker_process, unmark_worker_process

    mark_worker_process()
    yield
    unmark_worker_process()


@pytest.fixture(autouse=True)
def no_checkpoint_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """The brand references' checkpoint (`pipeline.frozen_brand_references`) writes to
    Postgres inside a preparation; offline it builds them as it does outside one. The
    preparation itself (`current_preparation`) stays real."""
    from qualify_api.creative import media

    monkeypatch.setattr(media, "frozen_brand_references", lambda build: build())


def _produce_in_a_preparation(composer: FakeComposer) -> tuple[Any, Any]:
    producer, _, seedance = _composing_producer(composer)
    draft_id = uuid4()
    run = Preparation(MEDIA_TENANT, draft_id, 1, "generation", uuid4(), 1)
    with preparing(run):
        outcome = producer.produce(
            tenant_id=MEDIA_TENANT,
            draft_id=draft_id,
            brief=_brief_with(text_layers=(WORDS,)),
            kit=_kit(),
            copy=COPY,
            budget=BUDGET,
        )
    return outcome, seedance


def test_in_a_preparation_a_render_service_down_makes_the_piece_wait() -> None:
    composer = FakeComposer(fail_draw=DOWN)
    with pytest.raises(LocalVideoWait) as waited:
        _produce_in_a_preparation(composer)
    assert waited.value.retry_after_s == recompose.RENDER_RETRY_AFTER_SECONDS > 0
    assert composer.composes == []


def test_the_pass_after_the_wait_composes_once_the_render_is_back() -> None:
    composer = FakeComposer(fail_draw=DOWN)
    with pytest.raises(LocalVideoWait):
        _produce_in_a_preparation(composer)
    composer.fail_draw = None
    outcome, seedance = _produce_in_a_preparation(composer)
    assert outcome.failure is None and len(seedance.requests) == 1
    (video,) = outcome.media
    assert video.params["compose"]["recipe"]["text_layers"][0]["text"] == WORDS.text


def test_in_a_preparation_a_text_that_does_not_fit_still_fails_before_paying() -> None:
    composer = FakeComposer(fail_draw=TOO_WIDE)
    outcome, seedance = _produce_in_a_preparation(composer)
    assert outcome.failure == FailureReason.INVALID_PARAMETERS.value
    assert outcome.detail == TOO_WIDE.owner_message
    assert seedance.requests == []


def test_the_kept_text_pngs_carry_their_warnings_back() -> None:
    from types import SimpleNamespace

    from qualify_api.creative.video_pipeline.recompose import (
        ComposeRecipe,
        stored_text_images,
        text_images_params,
    )

    image = SimpleNamespace(
        png=b"png",
        job_id="j",
        width=1080,
        height=1920,
        report={},
        provenance={},
        warnings=("font_fallback",),
    )
    store: dict[str, bytes] = {}

    def keep(index: int, png: bytes) -> str:
        store[f"k{index}"] = png
        return f"k{index}"

    texts = text_images_params((image,), keep)
    assert texts is not None and texts[0]["warnings"] == ["font_fallback"]
    (back,) = stored_text_images({"texts": texts}, ComposeRecipe(text_layers=(WORDS,)), store.get)
    assert back.warnings == ("font_fallback",) and back.png == b"png"

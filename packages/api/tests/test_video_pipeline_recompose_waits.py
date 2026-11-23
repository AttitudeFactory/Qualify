"""EF-14 (m-25026592), reviews 2 and 3: inside a real worker preparation (ADR 41 queue)
a render service that did not answer never fails a Seedance clip at once — the piece waits
(at most `COMPOSE_OUTAGE_WINDOW`) and a later pass draws the texts while the
`CheckpointRouter` replays the paid call; anything that is not an outage (a 4xx, no render
client, our own bug) and a text that does not fit fail at once, before anything is paid.
`_seedance_task_recorded` is NOT mocked: inside a preparation it cannot tell
(`service._tasks_of` is empty there), so the decision does not rest on it. The pipeline's
checkpoints live in memory (`test_creative_queue_pipeline.Checkpoints`). Nothing paid,
nothing rendered."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from qualify_creative.enums import FailureReason, GenerationTask
from qualify_creative.providers import GenerationRequest, RenderedPrompt
from qualify_creative.render.client import RenderServiceError

from qualify_api.creative.heavy_video import LocalVideoWait
from qualify_api.creative.pipeline import CheckpointRouter, Preparation, encode_result, preparing
from qualify_api.creative.video_pipeline import recompose
from qualify_api.creative.video_pipeline.recompose import (
    COMPOSE_FIRST_FAILURE_STEP,
    ClipComposeFailed,
    ComposeRecipe,
    stored_text_images,
    text_images_params,
)

from .test_creative_media_byteplus import BUDGET, COPY, _kit
from .test_creative_media_byteplus import TENANT_ID as MEDIA_TENANT
from .test_creative_queue_pipeline import Checkpoints
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
    transient=True,
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


@pytest.fixture
def checkpoints() -> Iterator[Checkpoints]:
    """The pipeline's steps in memory: every `PipelineStore()` of this test reads them."""
    rows = Checkpoints()
    with patch("qualify_api.creative.pipeline.PipelineStore", return_value=rows):
        yield rows


class _Pass:
    """One worker pass over the same piece: a fresh router and preparation, the same
    checkpoints (another process after a restart, as `test_creative_queue_pipeline`)."""

    def __init__(self, producer: Any, checkpoints: Checkpoints) -> None:
        self.producer, self.checkpoints, self.draft_id = producer, checkpoints, uuid4()
        self.brief = _brief_with(text_layers=(WORDS,))

    def __call__(self) -> Any:
        router = self.producer._router
        if isinstance(router, CheckpointRouter):
            router = router.router
        self.producer._router = CheckpointRouter(router, self.checkpoints, self.producer._store)
        run = Preparation(MEDIA_TENANT, self.draft_id, 1, "generation", uuid4(), 1)
        with preparing(run):
            return self.producer.produce(
                tenant_id=MEDIA_TENANT,
                draft_id=self.draft_id,
                brief=self.brief,
                kit=_kit(),
                copy=COPY,
                budget=BUDGET,
            )


def _execute_seedance(seedance: Any, checkpoints: Checkpoints, files: Any) -> None:
    """The executor runs the deferred Seedance task and keeps its result (it is paid)."""
    (row,) = [r for r in checkpoints.rows.values() if r["job_id"] is not None]
    remote = seedance.generate(
        GenerationRequest(
            task=GenerationTask.SCENE_VIDEO, rendered_prompt=RenderedPrompt("", "", "")
        ),
        api_key="fake",
    )
    row["result"] = encode_result(remote, files, "result", MEDIA_TENANT)


def test_a_paid_task_in_the_queue_waits_for_the_render_and_is_paid_once(
    checkpoints: Checkpoints,
) -> None:
    """Pass 1 draws, orders Seedance (paid by the executor) and is deferred; pass 2 finds
    the render service down: it waits, the clip is not paid again; pass 3 composes."""
    composer = FakeComposer()
    producer, files, seedance = _composing_producer(composer)
    run = _Pass(producer, checkpoints)

    first = run()
    assert first.pending and len(composer.draws) == 1 and seedance.requests == []
    _execute_seedance(seedance, checkpoints, files)
    assert len(seedance.requests) == 1

    composer.fail_draw = DOWN
    with pytest.raises(LocalVideoWait) as waited:
        run()
    assert waited.value.retry_after_s == recompose.RENDER_RETRY_AFTER_SECONDS > 0
    assert len(seedance.requests) == 1 and composer.composes == []
    assert COMPOSE_FIRST_FAILURE_STEP in checkpoints.rows

    composer.fail_draw = None
    third = run()
    assert third.failure is None and not third.pending
    assert len(seedance.requests) == 1 and len(composer.composes) == 1
    (video,) = third.media
    assert video.params["compose"]["recipe"]["text_layers"][0]["text"] == WORDS.text


def test_past_the_outage_window_the_piece_fails_with_its_refund(
    checkpoints: Checkpoints,
) -> None:
    composer = FakeComposer(fail_draw=DOWN)
    producer, _, seedance = _composing_producer(composer)
    run = _Pass(producer, checkpoints)
    long_ago = datetime.now(UTC) - recompose.COMPOSE_OUTAGE_WINDOW - timedelta(seconds=1)
    checkpoints.rows[COMPOSE_FIRST_FAILURE_STEP] = {
        "request": {"first_failure_at": long_ago.isoformat(), "error": DOWN.code},
        "job_id": None,
        "result": None,
        "error": None,
    }
    outcome = run()
    assert outcome.failure == FailureReason.DEPENDENCY_FAILED.value
    assert outcome.detail == DOWN.owner_message and seedance.requests == []


def test_a_text_that_does_not_fit_still_fails_before_paying(checkpoints: Checkpoints) -> None:
    producer, _, seedance = _composing_producer(FakeComposer(fail_draw=TOO_WIDE))
    outcome = _Pass(producer, checkpoints)()
    assert outcome.failure == FailureReason.INVALID_PARAMETERS.value
    assert outcome.detail == TOO_WIDE.owner_message
    assert seedance.requests == []


def test_without_the_queue_an_outage_fails_as_before() -> None:
    producer, _, seedance = _composing_producer(FakeComposer(fail_draw=DOWN))
    outcome = producer.produce(
        tenant_id=MEDIA_TENANT,
        draft_id=uuid4(),
        brief=_brief_with(text_layers=(WORDS,)),
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
    )
    assert outcome.failure == FailureReason.DEPENDENCY_FAILED.value
    assert seedance.requests == []


# ---------------------------------------------------------------------------
# only an outage is waited for: the real composer over a render client that fails


class FailingRenderClient:
    """The render client's double: `render` raises what it is given."""

    def __init__(self, error: BaseException) -> None:
        self.error = error

    def render(self, **_: Any) -> Any:
        raise self.error


def _real_composer_pass(checkpoints: Checkpoints, client: Any) -> Any:
    producer, _, seedance = _composing_producer(FakeComposer())
    producer._clip_composer = None
    producer._render_client = client
    return _Pass(producer, checkpoints), seedance


def test_a_503_is_an_outage_and_waits(checkpoints: Checkpoints) -> None:
    run, seedance = _real_composer_pass(
        checkpoints, FailingRenderClient(RenderServiceError("unavailable", 503, "down"))
    )
    with pytest.raises(LocalVideoWait):
        run()
    assert seedance.requests == []


@pytest.mark.parametrize(
    "client",
    [
        FailingRenderClient(RenderServiceError("unauthorized", 401, "bad token")),
        None,  # no render client wired
        FailingRenderClient(TypeError("a bug of ours")),
    ],
    ids=["401", "no_client", "type_error"],
)
def test_anything_but_an_outage_fails_at_once(checkpoints: Checkpoints, client: Any) -> None:
    run, seedance = _real_composer_pass(checkpoints, client)
    outcome = run()
    assert outcome.failure is not None and outcome.failure != "pending"
    assert seedance.requests == [] and COMPOSE_FIRST_FAILURE_STEP not in checkpoints.rows


def test_the_kept_text_pngs_carry_their_warnings_back() -> None:
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

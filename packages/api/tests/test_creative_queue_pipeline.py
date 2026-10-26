"""Queue generation acceptance: real media pipeline, fake vendors, durable seam."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from qualify_creative.enums import ContentKind, SlideSource
from qualify_creative.schemas import CarouselSlide

from qualify_api.creative.pipeline import CheckpointRouter, Preparation, encode_result, preparing
from qualify_api.creative.queue_dispatch import generation_jobs, queue_enabled

from . import test_creative_media_byteplus as media


class Checkpoints:
    """The persistence seam survives replacement of the process/router instances."""

    def __init__(self) -> None:
        self.rows: dict[int, dict] = {}
        self.jobs = [uuid4() for _ in range(4)]
        self.eligible: set = set()

    def load_step(self, run: Preparation, step: int) -> dict | None:
        return self.rows.get(step)

    def save_step(self, run: Preparation, step: int, request: dict, job_id: Any) -> dict:
        self.rows.setdefault(
            step, {"request": request, "job_id": job_id, "result": None, "error": None}
        )
        return self.rows[step]

    def video_job(self, run: Preparation, ordinal: int, provider: str) -> Any:
        return self.jobs[ordinal]

    def ready(self, run: Preparation, job_id: Any) -> None:
        self.eligible.add(job_id)

    def intent(self, run: Preparation, step: int) -> None:
        self.rows[step]["error"] = "in_flight"

    def complete_step(
        self, tenant_id: Any, *, identity: dict, result: Any, error: Any = None, **_: Any
    ) -> None:
        self.rows[identity["s"]].update(result=result, error=error)


def _carousel() -> Any:
    return media._brief(
        ContentKind.CAROUSEL,
        closing_slide=False,
        slides=tuple(
            CarouselSlide(source=SlideSource.ANIMATED, scene_prompt=f"Una hamburguesa {i}")
            for i in range(4)
        ),
    )


def _round(producer: Any, checkpoints: Checkpoints, draft_id: Any) -> Any:
    # A fresh router/context models another process after a deployment.
    router = producer._router
    if isinstance(router, CheckpointRouter):
        router = router.router
    producer._router = CheckpointRouter(router, checkpoints, producer._store)
    run = Preparation(media.TENANT_ID, draft_id, 1, "generation", uuid4(), 1)
    with preparing(run):
        return media._produce(producer, _carousel(), draft_id)


def test_four_scenes_are_independent_and_ready_only_after_all_four_results() -> None:
    checkpoints = Checkpoints()
    frames, videos, files = media.FakeSeedream(), media.FakeSeedance(), media._store()
    producer = media._carousel_producer(files, frames, videos, media.FakeFitter())
    draft = uuid4()
    first = _round(producer, checkpoints, draft)
    assert first.pending and not first.media
    assert checkpoints.eligible == set(checkpoints.jobs)
    assert len(frames.requests) == 4
    assert videos.requests == []  # preparation never submits a video
    assert len(generation_jobs(_carousel())) == 4

    steps = [row for row in checkpoints.rows.values() if row["job_id"] is not None]
    # The executor's completed results arrive independently/out of order.
    from qualify_creative.providers import GenerationRequest, RenderedPrompt

    for row in steps[:3]:
        remote = videos.generate(
            GenerationRequest(
                task=media.GenerationTask.SCENE_VIDEO, rendered_prompt=RenderedPrompt("", "", "")
            ),
            api_key="fake",
        )
        row["result"] = encode_result(remote, files, "result", media.TENANT_ID)
    third = _round(producer, checkpoints, draft)
    assert third.pending and not third.media
    assert len(frames.requests) == 4  # no repeated paid frame after restart
    steps[-1]["result"] = steps[0]["result"]
    finished = _round(producer, checkpoints, draft)
    assert finished.failure is None and not finished.pending
    assert [asset.position for asset in finished.media] == [0, 1, 2, 3]
    assert len(frames.requests) == 4


def test_a_scene_failure_is_reported_with_its_number_after_other_scenes_finish() -> None:
    checkpoints = Checkpoints()
    videos, files = media.FakeSeedance(), media._store()
    producer = media._carousel_producer(files, media.FakeSeedream(), videos, media.FakeFitter())
    draft = uuid4()
    assert _round(producer, checkpoints, draft).pending
    steps = [row for row in checkpoints.rows.values() if row["job_id"] is not None]
    steps[1]["error"] = "video rejected"
    assert _round(producer, checkpoints, draft).pending
    from qualify_creative.providers import GenerationRequest, RenderedPrompt

    for row in (steps[0], *steps[2:]):
        remote = videos.generate(
            GenerationRequest(
                task=media.GenerationTask.SCENE_VIDEO, rendered_prompt=RenderedPrompt("", "", "")
            ),
            api_key="fake",
        )
        row["result"] = encode_result(remote, files, "result", media.TENANT_ID)
    outcome = _round(producer, checkpoints, draft)
    assert outcome.failure is not None and "Diapositiva 2" in outcome.detail


def test_queue_switch_is_explicit_and_inline_is_the_unchanged_default(monkeypatch) -> None:
    monkeypatch.delenv("QUALIFY_CREATIVE_DISPATCHER", raising=False)
    assert not queue_enabled()
    monkeypatch.setenv("QUALIFY_CREATIVE_DISPATCHER", "queue")
    assert queue_enabled()
    monkeypatch.setenv("QUALIFY_CREATIVE_DISPATCHER", "typo")
    with pytest.raises(ValueError):
        queue_enabled()


def test_ambiguous_checkpoint_reaches_a_non_paid_retry_failure_view_model():
    from Qualify.creative_vm import failure_vm
    from qualify_creative.providers import GenerationRequest, RenderedPrompt
    from qualify_creative.queue_errors import UNCERTAIN_REASON

    from qualify_api.creative.service import _failure_from_hops

    checkpoints = Checkpoints()
    checkpoints.rows[0] = {"request": {}, "job_id": None, "result": None, "error": "in_flight"}

    class NeverPay:
        def run(self, **kwargs):
            pytest.fail("an uncertain paid step was submitted again")

    router = CheckpointRouter(NeverPay(), checkpoints, media._store())
    run = Preparation(media.TENANT_ID, uuid4(), 1, "generation", uuid4(), 1)
    with preparing(run):
        outcome = router.run(
            tenant_id=media.TENANT_ID,
            brand_id=media.BRAND_ID,
            chain=("anthropic",),
            request=GenerationRequest(
                task=media.GenerationTask.COPY, rendered_prompt=RenderedPrompt("", "", "")
            ),
        )
    reason = _failure_from_hops(outcome.hops)
    assert reason == UNCERTAIN_REASON
    vm = failure_vm(reason)
    assert vm is not None and vm.action_route == ""
    assert "publicación" in vm.label and "equipo" in vm.label
    assert UNCERTAIN_REASON not in vm.label


def test_uncertain_final_preserves_cause_and_has_no_retry_in_backend_or_vm():
    from Qualify.creative_vm import video_draft_vm
    from qualify_creative.queue_errors import UNCERTAIN_REASON, UNCERTAIN_VIDEO_TEXT

    from qualify_api.creative.draft_mode import draft_summary, final_retryable

    block = {
        "status": "failed",
        "error": UNCERTAIN_VIDEO_TEXT,
        "failure_reason": UNCERTAIN_REASON,
    }
    assert not final_retryable(block, approved=True)
    state, cost, error = draft_summary([{"draft": block}], approved=True)
    vm = video_draft_vm(state, cost, error, approved=True)
    assert not vm.can_retry
    assert vm.note == UNCERTAIN_VIDEO_TEXT
    assert UNCERTAIN_REASON not in vm.note

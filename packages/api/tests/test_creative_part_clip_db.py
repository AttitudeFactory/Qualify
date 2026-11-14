"""VE-09 (m-24921066) against Postgres: a part made by the real media producer (the clip
tests' vendor fakes behind it) — refused for a real person it is `failed` with
`refused_face` and its vista previa `refunded` in `creation_charges`, with no other job;
made, its provenance is in `image_assets.params` and its cost in `creative_usage_events`;
a window is never cut into a folder of another business (RLS on `content_drafts`); and
the queue worker keeps ModelArk's refusal code instead of an uncertain submission.

No vendor is called."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.enums import ContentFormat, ContentKind, FailureReason
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.router import CreativeRouter
from qualify_creative.schemas import MediaInputs, PartRef, VideoPartPlan
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creative.composition import DbBrandKitReader, DbVoiceProfileReader
from qualify_api.creative.creations import PostgresCreationsLedger
from qualify_api.creative.media import PART_PROMPT_VERSION_V5, PartWindowRefused
from qualify_api.creative.part_windows import SourcePartWindows
from qualify_api.creative.parts import PartsService
from qualify_api.creative.queue_dispatch import QueueDispatcher
from qualify_api.creative.service import ContentService
from qualify_api.referentes.reel_analysis_window import PostgresDraftOwnership, SourceWindows

from . import test_content_service as base
from . import test_creative_queue_dispatch_db as _queue_db
from .test_creative_part_clip import (
    ANALYSIS_ID,
    REFUSED_ORIGINAL_TEXT,
    V25,
    DraftSeedance,
    FakeWindows,
    ReadLog,
    _jpeg,
    _setup,
)

pytestmark = pytest.mark.db

#: The queue tests' world (a business, the queue dispatcher, its own vendor pool).
queue_world = _queue_db.setup_queue


def _business(monkeypatch: pytest.MonkeyPatch) -> tuple[UUID, UUID, UUID]:
    monkeypatch.setattr(base, "DB_TENANT", uuid4())
    return base.seed_db_tenant()


def _scalar(tenant: UUID, sql: str, **params: object) -> Any:
    with tenant_session(tenant) as session:
        return session.execute(text(sql), params).scalar()


def _world(
    monkeypatch: pytest.MonkeyPatch, seedance: DraftSeedance
) -> tuple[ContentService, UUID, UUID]:
    """A business with a parent of one «Igual al original» part and that part created
    (charged, queued) — the real producer and the Postgres repository and ledger."""
    tenant, brand, user = _business(monkeypatch)
    photo = f"uploads/{tenant}/burger.jpg"
    producer, _, _, _, _ = _setup(seedance=seedance, store=ReadLog({photo: _jpeg()}))
    producer._reference_links = lambda **_: "https://qualify.example/public/media/tok"
    producer._part_windows = FakeWindows(producer._store)
    copy = base.FakeCopyAdapter()
    pricing = JsonPricingTable("v1")
    service = ContentService(
        router=CreativeRouter({"anthropic": copy}, pricing, base.StaticKeyResolver()),
        pricing=pricing,
        credentials=base.StaticKeyResolver(),
        brand_service=DbBrandKitReader(),
        voice_service=DbVoiceProfileReader(),
        media=producer,
        creations=PostgresCreationsLedger(),
    )
    service.dispatcher = QueueDispatcher(service.repository, pricing_version=pricing.version)
    plan = VideoPartPlan(
        mode="edit",
        seconds=4,
        analysis_id=ANALYSIS_ID,
        shot_indexes=(0,),
        description="La hamburguesa sobre la mesa.",
    )
    parent = service.create_draft(
        tenant_id=tenant,
        brand_id=brand,
        user_id=user,
        brief=base.make_brief(
            brand_id=brand,
            variants=1,
            kind=ContentKind.SHOT_VIDEO,
            format=ContentFormat.REELS_9_16,
            topic="Smash burger doble",
            media=MediaInputs(parts=(plan,), product_keys=(photo,)),
        ),
    )
    service.run_generation(tenant_id=tenant, draft_id=parent)
    (child,) = PartsService(service, require_queue=lambda: True).create_parts(
        tenant_id=tenant, parent_id=parent, user_id=user
    )
    return service, tenant, child


def test_criterion_2_refused_face_fails_the_part_and_refunds_it_db(monkeypatch) -> None:  # noqa: ANN001
    seedance = DraftSeedance(refuse="failed: InputVideoSensitiveContentDetected.PrivacyInformation")
    service, tenant, child = _world(monkeypatch, seedance)

    service.run_generation(tenant_id=tenant, draft_id=child)

    with tenant_session(tenant) as session:
        draft = session.execute(
            text("SELECT status, failure_reason, failure_detail FROM content_drafts WHERE id=:d"),
            {"d": child},
        ).one()
        charge = session.execute(
            text(
                "SELECT status, refund_reason, previews FROM creation_charges "
                "WHERE draft_id=:d AND revision=1"
            ),
            {"d": child},
        ).one()
        jobs = session.execute(
            text("SELECT kind FROM creative_jobs WHERE draft_id=:d"), {"d": child}
        ).all()
    assert tuple(draft) == ("failed", FailureReason.REFUSED_FACE.value, REFUSED_ORIGINAL_TEXT)
    assert tuple(charge) == ("refunded", FailureReason.REFUSED_FACE.value, 1)
    assert [j.kind for j in jobs] == ["preview"]  # the one made with it: no retry, no extra
    assert len(seedance.requests) == 1


def test_a_part_that_failed_on_our_side_is_refunded_as_part_failed_db(monkeypatch) -> None:  # noqa: ANN001
    seedance = DraftSeedance()
    service, tenant, child = _world(monkeypatch, seedance)
    service._media._part_windows = FakeWindows(service._media._store, refuse="bad_window")

    service.run_generation(tenant_id=tenant, draft_id=child)

    with tenant_session(tenant) as session:
        reason = session.execute(
            text("SELECT failure_reason FROM content_drafts WHERE id=:d"), {"d": child}
        ).scalar_one()
        charge = session.execute(
            text(
                "SELECT status, refund_reason FROM creation_charges "
                "WHERE draft_id=:d AND revision=1"
            ),
            {"d": child},
        ).one()
    assert reason == FailureReason.PART_FAILED.value
    assert tuple(charge) == ("refunded", FailureReason.PART_FAILED.value)
    assert seedance.requests == []


def test_criterion_3_a_made_part_keeps_its_provenance_and_cost_db(monkeypatch) -> None:  # noqa: ANN001
    service, tenant, child = _world(monkeypatch, DraftSeedance())

    service.run_generation(tenant_id=tenant, draft_id=child)

    assert _scalar(tenant, "SELECT status FROM content_drafts WHERE id=:d", d=child) == "generated"
    with tenant_session(tenant) as session:
        params = session.execute(
            text("SELECT params FROM image_assets WHERE draft_id=:d"), {"d": child}
        ).scalar_one()
        usage = session.execute(
            text(
                "SELECT provider, model_id, cost_usd, pricing_table_version "
                "FROM creative_usage_events WHERE draft_id=:d AND provider='seedance'"
            ),
            {"d": child},
        ).all()
    part = params["part"]
    assert part["analysis_id"] == str(ANALYSIS_ID) and part["shot_indexes"] == [0]
    # a new piece is sealed with the current compiler (5): its edit part is version 3
    assert part["prompt_version"] == params["part_prompt_version"] == PART_PROMPT_VERSION_V5
    assert part["window"]["key"].startswith(f"reel-windows/{tenant}/{child}/")
    assert params["draft"]["reference_mode"] == "edit"
    ((provider, model_id, cost, version),) = usage
    assert (provider, model_id, version) == ("seedance", V25, "v1")
    assert Decimal(cost) > 0


class _Unreachable:
    """A door that must never be opened (a foreign draft is refused before it)."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"touched {name} for a draft of another business")


def test_criterion_4_a_window_never_goes_to_another_business_folder_db(monkeypatch) -> None:  # noqa: ANN001
    _, tenant_a, child_of_a = _world(monkeypatch, DraftSeedance())
    tenant_b, _, _ = _business(monkeypatch)

    requests = SimpleNamespace(
        get=lambda _t, _a: SimpleNamespace(status="ok", source_seconds=9.0),
        shots=lambda _t, _a: [
            SimpleNamespace(
                shot_index=0,
                start_s=0.0,
                end_s=9.0,
                people_presence="not_observed",
                visible_faces="not_observed",
            )
        ],
    )
    windows = SourceWindows(
        requests=requests,  # type: ignore[arg-type]
        drafts=PostgresDraftOwnership(),  # RLS on `content_drafts`, as `qualify_app`
        gate=_Unreachable(),  # type: ignore[arg-type]
        public=_Unreachable(),  # type: ignore[arg-type]
        in_worker=lambda: True,
    )
    part = PartRef(index=1, mode="edit", seconds=4, analysis_id=ANALYSIS_ID, shot_indexes=(0,))
    with pytest.raises(PartWindowRefused) as refused:
        SourcePartWindows(windows)(tenant_id=tenant_b, draft_id=child_of_a, part=part)
    assert refused.value.code == "foreign_draft"
    assert _scalar(tenant_b, "SELECT count(*) FROM content_drafts WHERE id=:d", d=child_of_a) == 0
    assert _scalar(tenant_a, "SELECT count(*) FROM content_drafts WHERE id=:d", d=child_of_a) == 1


# ---------------------------------------------------------------------------
# The queue worker keeps ModelArk's refusal (what makes `refused_face` real in production)


def _executor(world: Any, adapter: Any, *, part: bool = True) -> tuple[Any, ...]:  # noqa: ANN401
    from qualify_creative.enums import GenerationTask
    from qualify_creative.providers import GenerationRequest, RenderedPrompt

    from qualify_api.creative import job_queue as q
    from qualify_api.creative.pipeline import PipelineStore, request_data
    from qualify_api.creative.worker.pipeline import PipelineExecutor
    from qualify_api.creative.worker.store import PostgresQueueStore

    from . import test_creative_media_byteplus as media
    from .test_creative_queue_dispatch_db import _request

    draft = _request(world)
    service, tenant, brand, _, _ = world
    if part:
        # the piece becomes part 1 of another piece (VE-09's scope is parts only)
        parent = _request(world)
        with tenant_session(tenant) as session:
            session.execute(
                text("UPDATE content_drafts SET parent_draft_id=:p, part_index=1 WHERE id=:d"),
                {"p": parent, "d": draft},
            )
    service._media = SimpleNamespace(_store=media._store())
    pipeline = PipelineStore()
    run = pipeline.acquire(tenant, draft, 1, "generation")
    assert run is not None
    with tenant_session(tenant) as session:
        job = session.scalar(text("SELECT id FROM creative_jobs WHERE draft_id=:d"), {"d": draft})
    request = GenerationRequest(
        task=GenerationTask.SCENE_VIDEO, rendered_prompt=RenderedPrompt("p", "v1", "s")
    )
    pipeline.save_step(run, 0, request_data(request, "seedance", brand), job)
    pipeline.ready(run, job)
    pipeline.release(run, completed=True)
    store = PostgresQueueStore()
    claim = store.claim_fair(
        vendor_model=q.SEEDANCE_POOL,
        size=10,
        worker_id="test",
        lease=timedelta(minutes=5),
        now=datetime.now(UTC),
        tenant_ids=(tenant,),
    )
    assert claim is not None
    return tenant, job, store, claim, PipelineExecutor(service, pipeline, adapter, "seedance")


def _process(tenant: UUID, store: Any, claim: Any, executor: Any) -> str:  # noqa: ANN401
    from qualify_api.creative import job_queue as q
    from qualify_api.creative.worker.downloads import DownloadGate
    from qualify_api.creative.worker.runner import CreativeWorker, WorkerConfig

    worker = CreativeWorker(
        store,
        {q.SEEDANCE_POOL: executor},
        WorkerConfig(pools={q.SEEDANCE_POOL: 10}, tenant_ids=(tenant,)),
        downloads=DownloadGate(2),
    )
    return worker.process(claim)


def _step_error(tenant: UUID, job: UUID) -> str | None:
    return _scalar(tenant, "SELECT error FROM creative_pipeline_steps WHERE job_id=:j", j=job)


class _Refusing:
    """ModelArk refusing the task's creation with a 4xx (nothing is created)."""

    calls = 0

    def estimate_cost_usd(self, *a: Any, **k: Any) -> Decimal:
        return Decimal("0.1")

    def submit(self, request: Any, *, api_key: str, priority: Any) -> str:
        from qualify_creative.adapters.byteplus_ark import ArkAPIError

        self.calls += 1
        raise ArkAPIError(
            400, "InputImageSensitiveContentDetected.PrivacyInformation", "real person"
        )


def _job_status(tenant: UUID, job: UUID) -> str:
    from qualify_api.creative import job_queue as q

    with tenant_session(tenant) as session:
        return q.load_job(session, job).status


def test_decision_b_a_part_refused_at_creation_fails_with_its_code_db(queue_world) -> None:  # noqa: ANN001
    adapter = _Refusing()
    tenant, job, store, claim, executor = _executor(queue_world, adapter, part=True)

    assert _process(tenant, store, claim, executor) == "failed"
    error = _step_error(tenant, job)
    assert error is not None and error.startswith("refused: HTTP 400")
    assert "PrivacyInformation" in error
    assert _job_status(tenant, job) == "failed"
    assert adapter.calls == 1


def test_decision_b_an_ordinary_clip_refused_at_creation_stays_uncertain_db(queue_world) -> None:  # noqa: ANN001
    adapter = _Refusing()
    tenant, job, store, claim, executor = _executor(queue_world, adapter, part=False)

    assert _process(tenant, store, claim, executor) == "interrupted"  # as today
    assert _step_error(tenant, job) == "submission_uncertain"
    assert adapter.calls == 1


def test_review_1_a_refusal_that_cannot_be_written_stays_uncertain_db(  # noqa: ANN001
    queue_world, monkeypatch
) -> None:
    """The refusal is one write; when it fails the step is still `submitting` (never
    NULL, so never POSTed again) and ends `submission_uncertain`, as before."""
    from qualify_api.creative.worker.pipeline import PipelineExecutor

    def broken(*_a: Any, **_k: Any) -> bool:
        raise RuntimeError("database gone")

    monkeypatch.setattr(PipelineExecutor, "_write_refusal", broken)
    adapter = _Refusing()
    tenant, job, store, claim, executor = _executor(queue_world, adapter, part=True)

    assert _process(tenant, store, claim, executor) == "interrupted"
    assert _step_error(tenant, job) == "submission_uncertain"
    assert adapter.calls == 1


def test_a_failed_task_keeps_its_vendor_code_db(queue_world) -> None:  # noqa: ANN001
    class FailedTask:
        def estimate_cost_usd(self, *a: Any, **k: Any) -> Decimal:
            return Decimal("0.1")

        def submit(self, request: Any, *, api_key: str, priority: Any) -> str:
            task = f"task-refused-{uuid4()}"
            request.observer.created(task)
            return task

        def poll(self, task_id: str, *, api_key: str) -> Any:
            return SimpleNamespace(
                status="failed",
                error_code="OutputVideoSensitiveContentDetected.PrivacyInformation",
            )

    tenant, job, store, claim, executor = _executor(queue_world, FailedTask(), part=True)
    _process(tenant, store, claim, executor)
    assert _step_error(tenant, job) == (
        "failed: OutputVideoSensitiveContentDetected.PrivacyInformation"
    )
    # decision B: any other piece keeps today's plain `failed` (no extra status GET)
    tenant, job, store, claim, executor = _executor(queue_world, FailedTask(), part=False)
    _process(tenant, store, claim, executor)
    assert _step_error(tenant, job) == "failed"

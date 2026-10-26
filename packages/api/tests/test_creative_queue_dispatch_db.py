"""Transactional outbox, reaper and preparation fencing through real tenant doors."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.router import CreativeRouter
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creative import job_queue as q
from qualify_api.creative.composition import DbBrandKitReader, DbVoiceProfileReader
from qualify_api.creative.dispatch import reap_stale_drafts
from qualify_api.creative.pipeline import PipelineStore
from qualify_api.creative.queue_dispatch import CheckpointError, QueueDispatcher
from qualify_api.creative.service import ContentService

from . import test_content_service as base

pytestmark = pytest.mark.db


@pytest.fixture
def setup_queue(monkeypatch):
    monkeypatch.setattr(base, "DB_TENANT", uuid4())
    tenant, brand, user = base.seed_db_tenant()
    copy = base.FakeCopyAdapter()
    pricing = JsonPricingTable("v1")
    service = ContentService(
        router=CreativeRouter({"anthropic": copy}, pricing, base.StaticKeyResolver()),
        pricing=pricing,
        credentials=base.StaticKeyResolver(),
        brand_service=DbBrandKitReader(),
        voice_service=DbVoiceProfileReader(),
    )
    service.dispatcher = QueueDispatcher(service._repo, pricing_version=pricing.version)
    return service, tenant, brand, user, copy


def _request(setup_queue, **overrides):
    service, tenant, brand, user, _ = setup_queue
    return service.create_draft(
        tenant_id=tenant,
        brand_id=brand,
        user_id=user,
        brief=base.make_brief(brand_id=brand, **overrides),
    )


def test_request_commits_job_and_piece_without_starting_threads(setup_queue, monkeypatch):
    monkeypatch.setattr("threading.Thread", lambda *a, **k: pytest.fail("request started a thread"))
    draft = _request(setup_queue)
    service, tenant, _, _, copy = setup_queue
    with tenant_session(tenant) as session:
        rows = (
            session.execute(
                text("""
            SELECT j.*, d.status AS draft_status FROM creative_jobs j
            JOIN content_drafts d ON d.id=j.draft_id WHERE j.draft_id=:d
        """),
                {"d": draft},
            )
            .mappings()
            .all()
        )
    assert len(rows) == 1
    assert rows[0]["status"] == "queued" and rows[0]["draft_status"] == "drafting"
    assert rows[0]["not_before"].year == 9999
    assert copy.calls == 0


def test_enqueue_failure_rolls_back_piece_and_consumption_together(setup_queue, monkeypatch):
    service, tenant, brand, user, _ = setup_queue
    request_key = uuid4()
    original = service._repo.insert_brief_and_draft
    seen = []

    def insert(**kwargs):
        draft = original(**kwargs)
        seen.append(draft)
        # Represents the real ledger's nested tenant_session: it must join the UoW.
        with tenant_session(tenant) as session:
            session.execute(
                text("""
                INSERT INTO creation_charges (tenant_id,brand_id,draft_id,revision,request_kind,
                    weight,monthly_quota,weights_version,pricing_table_version,period_month)
                VALUES (:t,:b,:d,1,'create',1,10,'v1','v1',date_trunc('month',now())::date)
            """),
                {"t": tenant, "b": brand, "d": draft},
            )
        return draft

    monkeypatch.setattr(service._repo, "insert_brief_and_draft", insert)
    monkeypatch.setattr(q, "enqueue_job", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db")))
    with pytest.raises(RuntimeError):
        service.create_draft(
            tenant_id=tenant,
            brand_id=brand,
            user_id=user,
            brief=base.make_brief(brand_id=brand),
            request_key=request_key,
        )
    with tenant_session(tenant) as session:
        for table in ("content_drafts", "creation_charges", "creative_pipeline_runs"):
            column = "id" if table == "content_drafts" else "draft_id"
            assert (
                session.scalar(
                    text(f"SELECT count(*) FROM {table} WHERE {column}=:d"), {"d": seen[0]}
                )
                == 0
            )


def test_reaper_ignores_half_hour_wait_but_reaps_twenty_minutes_without_progress(setup_queue):
    draft = _request(setup_queue)
    _, tenant, _, _, _ = setup_queue
    with tenant_session(tenant) as session:
        session.execute(
            text("UPDATE content_drafts SET updated_at=:old WHERE id=:d"),
            {"d": draft, "old": datetime.now(UTC) - timedelta(minutes=30)},
        )
    reap_stale_drafts(tenant_id=tenant)
    with tenant_session(tenant) as session:
        assert (
            session.scalar(text("SELECT status FROM content_drafts WHERE id=:d"), {"d": draft})
            == "drafting"
        )
        session.execute(
            text("UPDATE creative_jobs SET not_before=now() WHERE draft_id=:d"), {"d": draft}
        )
    from qualify_api.creative.worker.store import PostgresQueueStore

    assert (
        PostgresQueueStore().claim_fair(
            vendor_model=q.SEEDANCE_POOL,
            size=10,
            worker_id="test",
            lease=timedelta(minutes=5),
            now=datetime.now(UTC),
            tenant_ids=(tenant,),
        )
        is not None
    )
    reap_stale_drafts(tenant_id=tenant)
    with tenant_session(tenant) as session:
        assert (
            session.scalar(text("SELECT status FROM content_drafts WHERE id=:d"), {"d": draft})
            == "failed"
        )


def test_expired_preparation_cannot_checkpoint_or_activate_after_new_owner(setup_queue):
    draft = _request(setup_queue)
    _, tenant, _, _, _ = setup_queue
    store = PipelineStore()
    old = store.acquire(tenant, draft, 1, "generation")
    assert old is not None
    with tenant_session(tenant) as session:
        session.execute(
            text(
                "UPDATE creative_pipeline_runs SET lease_until=now()-interval '1s' "
                "WHERE draft_id=:d"
            ),
            {"d": draft},
        )
        job = session.scalar(text("SELECT id FROM creative_jobs WHERE draft_id=:d"), {"d": draft})
    new = store.acquire(tenant, draft, 1, "generation")
    assert new is not None and new.token != old.token
    with pytest.raises(CheckpointError):
        store.save_step(old, 0, {}, job)
    with pytest.raises(CheckpointError):
        store.ready(old, job)
    store.release(new, completed=True)


def test_queued_piece_and_checkpoints_are_invisible_to_another_tenant(setup_queue):
    draft = _request(setup_queue)
    _, tenant, _, _, _ = setup_queue
    other = uuid4()
    store = PipelineStore()
    run = store.acquire(tenant, draft, 1, "generation")
    assert run is not None
    store.save_step(run, 0, {"private": "brand prompt"}, None)
    with tenant_session(other) as session:
        assert (
            session.scalar(
                text("SELECT count(*) FROM creative_jobs WHERE draft_id=:d"), {"d": draft}
            )
            == 0
        )
        assert (
            session.scalar(
                text("SELECT count(*) FROM creative_pipeline_steps WHERE draft_id=:d"), {"d": draft}
            )
            == 0
        )
    store.release(run, completed=True)


def test_checkpoint_job_cannot_reference_another_tenants_job(setup_queue):
    from sqlalchemy.exc import IntegrityError

    draft = _request(setup_queue)
    _, tenant, _, _, _ = setup_queue
    from qualify_shared.db.admin import admin_session

    from qualify_api.tenancy.models import Brand, Tenant

    from .test_creative_worker_db import _enqueue

    other = uuid4()
    with admin_session() as session:
        session.add(
            Tenant(id=other, name="other", country="CO", timezone="America/Bogota", currency="COP")
        )
        session.flush()
        session.add(Brand(tenant_id=other, name="other"))
    foreign_job = _enqueue(other, q.SEEDANCE_POOL)
    run = PipelineStore().acquire(tenant, draft, 1, "generation")
    assert run is not None
    with pytest.raises(IntegrityError):
        PipelineStore().save_step(run, 0, {}, foreign_job)


def _prepared_executor(setup_queue, monkeypatch, *, observer_crashes=False):
    from decimal import Decimal
    from types import SimpleNamespace

    from qualify_creative.enums import GenerationTask
    from qualify_creative.providers import GenerationRequest, RenderedPrompt

    from qualify_api.creative.pipeline import request_data
    from qualify_api.creative.worker.pipeline import PipelineExecutor, SubmissionRecorder
    from qualify_api.creative.worker.store import PostgresQueueStore

    from . import test_creative_media_byteplus as media

    draft = _request(setup_queue)
    service, tenant, brand, _, _ = setup_queue
    files = media._store()
    service._media = SimpleNamespace(_store=files)
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

    class Adapter:
        calls = 0

        def estimate_cost_usd(self, *a, **k):
            return Decimal("0.1")

        def submit(self, request, *, api_key, priority):
            self.calls += 1
            request.observer.created("paid-real-task")
            return "paid-real-task"

        def poll(self, task_id, *, api_key):
            assert task_id == "paid-real-task"
            return SimpleNamespace(status="succeeded")

        def result(self, request, state):
            return media.FakeSeedance().generate(request, api_key="test")

    adapter = Adapter()
    if observer_crashes:
        monkeypatch.setattr(
            SubmissionRecorder, "created", lambda *a: (_ for _ in ()).throw(RuntimeError("db"))
        )
    monkeypatch.setattr("qualify_api.creative.media._http_download", lambda url: b"paid video")
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
    executor = PipelineExecutor(service, pipeline, adapter, "seedance")
    return tenant, job, store, claim, executor, adapter, files


def test_real_executor_submit_poll_and_finish_checkpoint_paid_result_once(setup_queue, monkeypatch):
    from qualify_api.creative.worker.downloads import DownloadGate
    from qualify_api.creative.worker.runner import CreativeWorker, WorkerConfig

    tenant, job, store, claim, executor, adapter, files = _prepared_executor(
        setup_queue, monkeypatch
    )
    worker = CreativeWorker(
        store,
        {q.SEEDANCE_POOL: executor},
        WorkerConfig(pools={q.SEEDANCE_POOL: 10}, tenant_ids=(tenant,)),
        downloads=DownloadGate(2),
    )
    assert worker.process(claim) == "succeeded"
    with tenant_session(tenant) as session:
        row = q.load_job(session, job)
        result = session.scalar(
            text("SELECT result FROM creative_pipeline_steps WHERE job_id=:j"), {"j": job}
        )
    assert row.status == "succeeded" and row.vendor_task_id == "paid-real-task"
    assert result["checkpoint_media"] and files.read(result["checkpoint_media"]) == b"paid video"
    assert adapter.calls == 1


def test_uncertain_acceptance_keeps_slot_and_never_resubmits_after_restart(
    setup_queue, monkeypatch
):
    from qualify_api.creative.worker.downloads import DownloadGate
    from qualify_api.creative.worker.runner import CreativeWorker, WorkerConfig

    tenant, job, store, claim, executor, adapter, _ = _prepared_executor(
        setup_queue, monkeypatch, observer_crashes=True
    )
    worker = CreativeWorker(
        store,
        {q.SEEDANCE_POOL: executor},
        WorkerConfig(pools={q.SEEDANCE_POOL: 10}, tenant_ids=(tenant,)),
        downloads=DownloadGate(2),
    )
    assert worker.process(claim) == "interrupted"
    after = datetime.now(UTC) + timedelta(minutes=10)
    store.recover(now=after, tenant_ids=(tenant,))
    assert (
        store.claim_fair(
            vendor_model=q.SEEDANCE_POOL,
            size=10,
            worker_id="restarted",
            lease=timedelta(minutes=5),
            now=after,
            tenant_ids=(tenant,),
        )
        is None
    )
    from qualify_shared.db.creative_worker import creative_worker_session

    with creative_worker_session() as session:
        assert (
            session.scalar(
                text("SELECT count(*) FROM vendor_slots WHERE holder_job_id=:j"), {"j": job}
            )
            == 1
        )
    assert adapter.calls == 1


def test_snapshot_uses_original_brief_after_live_brand_inputs_change(setup_queue):
    from qualify_api.creative.pipeline import frozen_inputs, preparing

    draft = _request(setup_queue)
    _, tenant, brand, _, _ = setup_queue
    run = PipelineStore().acquire(tenant, draft, 1, "generation")
    assert run is not None
    original = base.make_brief(brand_id=brand, topic="Original")
    with preparing(run):
        (first,) = frozen_inputs(brief=original)
    with preparing(run):
        (replayed,) = frozen_inputs(brief=original.model_copy(update={"topic": "Changed"}))
    assert first.topic == replayed.topic == "Original"


def test_paid_boundary_rejects_a_refunded_plan_reservation(setup_queue, monkeypatch):
    from qualify_api.creative.worker.downloads import DownloadGate
    from qualify_api.creative.worker.runner import CreativeWorker, WorkerConfig

    tenant, job, store, claim, executor, adapter, _ = _prepared_executor(setup_queue, monkeypatch)
    service, _, brand, _, _ = setup_queue
    with tenant_session(tenant) as session:
        charge = session.execute(
            text("""
            INSERT INTO creation_charges (tenant_id,brand_id,draft_id,revision,request_kind,
                weight,monthly_quota,weights_version,pricing_table_version,period_month,status,refunded_at)
            SELECT :t,:b,draft_id,revision,'create',1,10,'v1','v1',
                   date_trunc('month',now())::date,'refunded',now()
            FROM creative_jobs WHERE id=:j RETURNING id
        """),
            {"t": tenant, "b": brand, "j": job},
        ).scalar_one()
        session.execute(
            text("UPDATE creative_jobs SET charge_id=:c WHERE id=:j"), {"c": charge, "j": job}
        )
    service._creations = object()  # production has a ledger; these rows are its actual reservation
    worker = CreativeWorker(
        store,
        {q.SEEDANCE_POOL: executor},
        WorkerConfig(pools={q.SEEDANCE_POOL: 10}, tenant_ids=(tenant,)),
        downloads=DownloadGate(2),
    )
    assert worker.process(claim) == "failed"
    assert adapter.calls == 0


def test_paid_result_download_failure_resumes_same_task_without_second_post(
    setup_queue, monkeypatch
):
    from qualify_api.creative.worker.downloads import DownloadGate
    from qualify_api.creative.worker.runner import CreativeWorker, WorkerConfig

    tenant, job, store, claim, executor, adapter, _ = _prepared_executor(setup_queue, monkeypatch)
    config = WorkerConfig(pools={q.SEEDANCE_POOL: 10}, tenant_ids=(tenant,))
    worker = CreativeWorker(store, {q.SEEDANCE_POOL: executor}, config, downloads=DownloadGate(2))
    monkeypatch.setattr(
        "qualify_api.creative.media._http_download",
        lambda url: (_ for _ in ()).throw(OSError("temporary download error")),
    )
    assert worker.process(claim) == "finish_error"
    after = datetime.now(UTC) + timedelta(minutes=10)
    store.recover(now=after, tenant_ids=(tenant,))
    recovered = store.claim_fair(
        vendor_model=q.SEEDANCE_POOL,
        size=10,
        worker_id="new",
        lease=timedelta(minutes=5),
        now=after,
        tenant_ids=(tenant,),
    )
    assert recovered is not None and recovered.job_id == job
    monkeypatch.setattr("qualify_api.creative.media._http_download", lambda url: b"paid video")
    worker.clock = lambda: after
    assert worker.process(recovered) == "succeeded"
    assert adapter.calls == 1

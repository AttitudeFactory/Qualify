"""Atomic whole-piece cancellation, real ledger and RLS (m-24852170)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from qualify_creative.creations import CreationPrice
from qualify_shared.db.creative_worker import creative_worker_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select, text

from qualify_api.creative import job_queue as q
from qualify_api.creative.creations import PostgresCreationsLedger
from qualify_api.creative.models import ContentDraft, CreationCharge, ImageAsset
from qualify_api.creative.queue_visibility import (
    QueueCancellationUnavailable,
    cancel_queued,
    queue_status,
)

from .test_creation_packs_db import _tenant
from .test_creative_worker_db import _draft

pytestmark = pytest.mark.db


def _setup(*, scenes: int = 1, final: bool = False):
    tenant, brand = _tenant()
    draft = _draft(tenant)
    at = datetime.now(UTC)
    ledger = PostgresCreationsLedger(clock=lambda: at)
    ledger.charge(
        tenant_id=tenant,
        brand_id=brand,
        draft_id=draft,
        revision=1,
        price=CreationPrice("carousel", 1, videos=scenes),
    )
    asset = uuid4()
    phase = f"final:{asset}" if final else "generation"
    if final:
        ledger.charge_videos(tenant_id=tenant, brand_id=brand, draft_id=draft, revision=1, videos=1)
    with tenant_session(tenant) as session:
        if final:
            record = session.get(ContentDraft, draft)
            record.status = "approved"
            session.add(
                ImageAsset(
                    id=asset,
                    tenant_id=tenant,
                    draft_id=draft,
                    media_type="video",
                    params={"draft": {"status": "rendering"}},
                )
            )
        session.execute(
            text("""
            INSERT INTO creative_pipeline_runs
                (tenant_id,draft_id,revision,phase,pipeline_version)
            VALUES (:t,:d,1,:p,'queue-test')
        """),
            {"t": tenant, "d": draft, "p": phase},
        )
        jobs = [
            q.enqueue_job(
                session,
                tenant_id=tenant,
                draft_id=draft,
                kind=q.KIND_FINAL if final else q.KIND_CAROUSEL_SCENE,
                revision=1,
                position=i,
                vendor_model=q.SEEDANCE_POOL,
                lane=q.LANE_IMMEDIATE,
                not_before=at - timedelta(minutes=1),
            ).job_id
            for i in range(scenes)
        ]
    return tenant, brand, draft, ledger, jobs, at, asset


def test_carousel_refunds_one_charge_and_never_claims_after_cancel() -> None:
    tenant, brand, draft, ledger, jobs, at, _ = _setup(scenes=4)
    assert ledger.balance(tenant_id=tenant, brand_id=brand).used == 1
    assert queue_status(tenant_id=tenant, draft_id=draft, load={}).can_cancel
    assert cancel_queued(tenant_id=tenant, draft_id=draft, now=at)
    assert not cancel_queued(tenant_id=tenant, draft_id=draft, now=at)
    assert ledger.balance(tenant_id=tenant, brand_id=brand).used == 0
    with tenant_session(tenant) as session:
        charges = session.scalars(
            select(CreationCharge).where(CreationCharge.draft_id == draft)
        ).all()
        assert len(charges) == 1 and charges[0].status == "refunded"
        assert (
            session.execute(
                text("SELECT status FROM creative_jobs WHERE draft_id=:d"), {"d": draft}
            )
            .scalars()
            .all()
            == ["cancelled"] * 4
        )
        assert session.get(ContentDraft, draft).status == "failed"
    with creative_worker_session() as session:
        assert (
            q.claim_job(
                session,
                job_id=jobs[0],
                vendor_model=q.SEEDANCE_POOL,
                size=10,
                worker_id="cancel-race",
                lease=timedelta(minutes=5),
                now=at,
            )
            is None
        )


def test_claim_before_cancel_refuses_and_keeps_charge() -> None:
    tenant, brand, draft, ledger, jobs, at, _ = _setup()
    with creative_worker_session() as session:
        claim = q.claim_job(
            session,
            job_id=jobs[0],
            vendor_model=q.SEEDANCE_POOL,
            size=10,
            worker_id="claim-first",
            lease=timedelta(minutes=5),
            now=at,
        )
    assert claim is not None
    assert not queue_status(tenant_id=tenant, draft_id=draft, now=at, load={}).can_cancel
    with pytest.raises(QueueCancellationUnavailable):
        cancel_queued(tenant_id=tenant, draft_id=draft, now=at)
    assert ledger.balance(tenant_id=tenant, brand_id=brand).used == 1
    # Release the test slot using the normal terminal operation.
    with tenant_session(tenant) as session:
        q.settle_job(
            session, job_id=jobs[0], claim_token=claim.claim_token, status=q.FAILED, now=at
        )
    with creative_worker_session() as session:
        q.release_slot(session, job_id=jobs[0], now=at)


def test_preparation_lease_and_uncertain_step_block_cancel() -> None:
    tenant, _, draft, _, _, at, _ = _setup()
    with tenant_session(tenant) as session:
        session.execute(
            text("""UPDATE creative_pipeline_runs SET lease_token=:token,
            lease_until=:until WHERE draft_id=:d"""),
            {"token": uuid4(), "until": at + timedelta(minutes=2), "d": draft},
        )
    assert not queue_status(tenant_id=tenant, draft_id=draft, now=at, load={}).can_cancel
    with pytest.raises(QueueCancellationUnavailable):
        cancel_queued(tenant_id=tenant, draft_id=draft, now=at)
    with tenant_session(tenant) as session:
        session.execute(
            text("UPDATE creative_pipeline_runs SET lease_until=NULL WHERE draft_id=:d"),
            {"d": draft},
        )
        session.execute(
            text("""INSERT INTO creative_pipeline_steps
            (tenant_id,draft_id,revision,phase,step,request,error)
            VALUES (:t,:d,1,'generation',0,'{}','in_flight')"""),
            {"t": tenant, "d": draft},
        )
    with pytest.raises(QueueCancellationUnavailable):
        cancel_queued(tenant_id=tenant, draft_id=draft, now=at)


def test_other_tenant_cannot_read_or_cancel() -> None:
    tenant, _, draft, ledger, _, at, _ = _setup()
    other, _ = _tenant()
    assert not queue_status(tenant_id=other, draft_id=draft, load={}).can_cancel
    with pytest.raises(QueueCancellationUnavailable):
        cancel_queued(tenant_id=other, draft_id=draft, now=at)
    assert queue_status(tenant_id=tenant, draft_id=draft, load={}).can_cancel


def test_final_refunds_video_only_keeps_piece_and_preview() -> None:
    tenant, brand, draft, ledger, _, at, asset = _setup(final=True)
    before = ledger.balance(tenant_id=tenant, brand_id=brand)
    assert cancel_queued(tenant_id=tenant, draft_id=draft, now=at)
    assert not cancel_queued(tenant_id=tenant, draft_id=draft, now=at)
    after = ledger.balance(tenant_id=tenant, brand_id=brand)
    assert after.used == before.used == 1
    assert after.videos_used == before.videos_used - 1
    with tenant_session(tenant) as session:
        assert session.get(ContentDraft, draft).status == "approved"
        assert session.get(ImageAsset, asset).params["draft"]["status"] == "failed"


def test_estimate_reads_only_anonymous_load_and_own_queue() -> None:
    tenant, _, draft, _, _, at, _ = _setup()
    minute = int((at - timedelta(minutes=1)).timestamp() // 60)
    load = {
        q.SEEDANCE_POOL: {
            "standard": {"free": 4, "mean_seconds": 120, "waiting": {str(minute - 1): 12}}
        }
    }
    status = queue_status(tenant_id=tenant, draft_id=draft, now=at, load=load)
    assert status.estimated_minutes == 6 and status.can_cancel


def test_cancel_locks_fence_a_concurrent_claim(monkeypatch) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from qualify_api.creative import queue_visibility as visibility

    tenant, _, draft, _, jobs, at, _ = _setup()
    locked, proceed = Event(), Event()
    refund = visibility.refund_in_session

    def paused_refund(*args, **kwargs):
        locked.set()
        assert proceed.wait(5)
        return refund(*args, **kwargs)

    monkeypatch.setattr(visibility, "refund_in_session", paused_refund)
    with ThreadPoolExecutor(max_workers=1) as executor:
        cancellation = executor.submit(cancel_queued, tenant_id=tenant, draft_id=draft, now=at)
        try:
            assert locked.wait(5)
            with creative_worker_session() as session:
                assert (
                    q.claim_job(
                        session,
                        job_id=jobs[0],
                        vendor_model=q.SEEDANCE_POOL,
                        size=10,
                        worker_id="racing",
                        lease=timedelta(minutes=5),
                        now=at,
                    )
                    is None
                )
        finally:
            proceed.set()
        assert cancellation.result(timeout=5)


def test_publisher_contains_only_anonymous_counts() -> None:
    import json

    from qualify_api.creative.worker.queue_load import publish_load

    tenant, _, draft, _, _, at, _ = _setup()

    class Store:
        data = ""

        def set(self, key, value, **kwargs):
            self.data = value

    store = Store()
    publish_load(store, now=at, pools={q.SEEDANCE_POOL: 10})
    assert str(tenant) not in store.data and str(draft) not in store.data
    value = json.loads(store.data)[q.SEEDANCE_POOL]["standard"]
    assert set(value) == {"waiting", "mean_seconds", "free"}


def test_cancellation_fences_preparation_acquisition_before_eligibility_read(monkeypatch) -> None:
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    from threading import Event

    from qualify_api.creative import queue_visibility as visibility
    from qualify_api.creative.pipeline import PipelineStore

    tenant, brand, draft, ledger, _, at, _ = _setup()
    runs_locked, proceed = Event(), Event()
    original = visibility._preparing

    def paused_eligibility(*args, **kwargs):
        runs_locked.set()
        assert proceed.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(visibility, "_preparing", paused_eligibility)
    with ThreadPoolExecutor(max_workers=2) as executor:
        cancellation = executor.submit(cancel_queued, tenant_id=tenant, draft_id=draft, now=at)
        assert runs_locked.wait(5)
        preparation = executor.submit(PipelineStore().acquire, tenant, draft, 1, "generation")
        try:
            # Preparation must wait for the cancellation's eligibility decision.
            with pytest.raises(TimeoutError):
                preparation.result(timeout=0.1)
        finally:
            proceed.set()
        assert cancellation.result(timeout=5)
        # The committed cancellation closed dirty_version before lease acquisition.
        assert preparation.result(timeout=5) is None
    assert ledger.balance(tenant_id=tenant, brand_id=brand).used == 0


def test_active_assembly_run_lock_is_safe_unavailable_without_a_draft_deadlock() -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    tenant, brand, draft, ledger, _, at, _ = _setup()
    run_locked, release = Event(), Event()

    def assembly():
        # The actual pipeline assembly holds this run before it locks its draft.
        with tenant_session(tenant) as session:
            session.execute(
                text("SELECT phase FROM creative_pipeline_runs WHERE draft_id=:d FOR UPDATE"),
                {"d": draft},
            )
            run_locked.set()
            assert release.wait(5)
            session.execute(
                text("SELECT id FROM content_drafts WHERE id=:d FOR UPDATE"), {"d": draft}
            )

    with ThreadPoolExecutor(max_workers=1) as executor:
        active = executor.submit(assembly)
        try:
            assert run_locked.wait(5)
            with pytest.raises(QueueCancellationUnavailable):
                cancel_queued(tenant_id=tenant, draft_id=draft, now=at)
            assert ledger.balance(tenant_id=tenant, brand_id=brand).used == 1
        finally:
            release.set()
        active.result(timeout=5)
    assert cancel_queued(tenant_id=tenant, draft_id=draft, now=at)
    assert ledger.balance(tenant_id=tenant, brand_id=brand).used == 0

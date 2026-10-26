"""Every retry keeps its old paid task and reuses the same quota consumption."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.session import tenant_session
from sqlalchemy import select, text

from qualify_api.creative import job_queue as q
from qualify_api.creative import models as orm
from qualify_api.creative.final_retries import final_phase, retry_final_asset

from .test_final_review_db import _fixture

pytestmark = pytest.mark.db
NOW = datetime(2026, 10, 27, 5, tzinfo=UTC)


def _failed(*, paid: bool = True, result: object = None) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    tenant, draft, _ = _fixture(status="failed")
    charge = uuid4()
    with tenant_session(tenant) as session:
        asset = session.scalar(select(orm.ImageAsset).where(orm.ImageAsset.draft_id == draft))
        asset_id = asset.id
        asset.params = {
            "draft": {
                "status": "failed",
                "final_transient_failure": True,
                "final_origin": "approval",
                "final_batch_not_before": (NOW - timedelta(hours=1)).isoformat(),
                "final_deadline": (NOW + timedelta(days=1)).isoformat(),
                "created_at": (NOW - timedelta(days=1)).timestamp(),
                "task_id": "paid-preview",
            }
        }
        job = q.enqueue_job(
            session,
            tenant_id=tenant,
            draft_id=draft,
            revision=1,
            kind=q.KIND_FINAL,
            vendor_model=q.SEEDANCE_POOL,
            lane=q.LANE_NIGHTLY,
            charge_id=charge,
            deadline=NOW + timedelta(days=1),
        )
        session.execute(
            text("""
            UPDATE creative_jobs SET status='failed', vendor_task_id=:vendor,
              last_error=:error, finished_at=:now WHERE id=:job
        """),
            {
                "job": job.job_id,
                "vendor": "paid-final-0" if paid else None,
                "error": "finish_failed" if result is not None else "failed",
                "now": NOW,
            },
        )
        phase = final_phase(asset_id, 0)
        session.execute(
            text("""
            INSERT INTO creative_pipeline_runs(tenant_id,draft_id,revision,phase,pipeline_version)
            VALUES(:tenant,:draft,1,:phase,'test')
        """),
            {"tenant": tenant, "draft": draft, "phase": phase},
        )
        import json

        session.execute(
            text("""
            INSERT INTO creative_pipeline_steps(tenant_id,draft_id,revision,phase,step,job_id,
                                                 request,result,error)
            VALUES(:tenant,:draft,1,:phase,0,:job,'{}',CAST(:result AS jsonb),:error)
        """),
            {
                "tenant": tenant,
                "draft": draft,
                "phase": phase,
                "job": job.job_id,
                "result": json.dumps(result) if result is not None else None,
                "error": None if result is not None else "failed",
            },
        )
    return tenant, draft, asset_id, job.job_id, charge


def test_terminal_retry_is_new_id_same_charge_and_concurrent_repeat_is_idempotent() -> None:
    tenant, draft, asset, previous, charge = _failed()
    assert (
        retry_final_asset(tenant_id=tenant, draft_id=draft, asset_id=asset, now=NOW, automatic=True)
        == "created"
    )
    assert (
        retry_final_asset(tenant_id=tenant, draft_id=draft, asset_id=asset, now=NOW, automatic=True)
        == "inflight"
    )
    with tenant_session(tenant) as session:
        rows = (
            session.execute(
                text("SELECT * FROM creative_jobs WHERE draft_id=:d ORDER BY final_attempt"),
                {"d": draft},
            )
            .mappings()
            .all()
        )
        assert len(rows) == 2 and rows[0]["id"] == previous
        assert rows[0]["vendor_task_id"] == "paid-final-0"
        assert rows[1]["vendor_task_id"] is None
        assert rows[1]["charge_id"] == rows[0]["charge_id"] == charge
        assert rows[1]["final_attempt"] == 1 and rows[1]["revision"] == 1


def test_paid_local_assembly_retry_keeps_result_and_vendor_id() -> None:
    tenant, draft, asset, previous, _ = _failed(result={"checkpoint_media": "kept-final"})
    assert (
        retry_final_asset(tenant_id=tenant, draft_id=draft, asset_id=asset, now=NOW, automatic=True)
        == "resumed"
    )
    with tenant_session(tenant) as session:
        rows = (
            session.execute(text("SELECT * FROM creative_jobs WHERE draft_id=:d"), {"d": draft})
            .mappings()
            .all()
        )
        assert len(rows) == 1 and rows[0]["id"] == previous
        assert rows[0]["vendor_task_id"] == "paid-final-0" and rows[0]["status"] == "queued"
        assert (
            session.execute(
                text("SELECT result FROM creative_pipeline_steps WHERE job_id=:j"), {"j": previous}
            ).scalar()["checkpoint_media"]
            == "kept-final"
        )


def test_ambiguous_submission_never_creates_another_paid_attempt() -> None:
    tenant, draft, asset, _, _ = _failed(paid=False)
    assert (
        retry_final_asset(tenant_id=tenant, draft_id=draft, asset_id=asset, now=NOW, automatic=True)
        == "blocked"
    )


def test_hard_deadline_and_other_tenant_cannot_retry() -> None:
    tenant, draft, asset, _, _ = _failed()
    assert (
        retry_final_asset(
            tenant_id=tenant,
            draft_id=draft,
            asset_id=asset,
            now=NOW + timedelta(days=2),
            automatic=True,
        )
        == "blocked"
    )
    other, _, _ = _fixture()
    assert retry_final_asset(tenant_id=other, draft_id=draft, asset_id=asset, now=NOW) == "blocked"


def test_nonfinal_attempt_is_rejected() -> None:
    with pytest.raises(ValueError, match="only finals"):
        q.enqueue_job(
            None,
            tenant_id=uuid4(),
            draft_id=uuid4(),
            revision=1,
            kind=q.KIND_PREVIEW,
            final_attempt=1,
            lane=q.LANE_IMMEDIATE,
            vendor_model=q.SEEDANCE_POOL,
        )


def test_three_total_vendor_attempts_then_clear_failed_state() -> None:
    tenant, draft, asset_id, _, _ = _failed()
    for attempt in (1, 2):
        assert (
            retry_final_asset(
                tenant_id=tenant, draft_id=draft, asset_id=asset_id, now=NOW, automatic=True
            )
            == "created"
        )
        with tenant_session(tenant) as session:
            session.execute(
                text("""
                UPDATE creative_jobs SET status='failed',vendor_task_id=:vendor,last_error='failed'
                WHERE draft_id=:d AND final_attempt=:attempt
            """),
                {"d": draft, "attempt": attempt, "vendor": f"paid-final-{attempt}"},
            )
            asset = session.get(orm.ImageAsset, asset_id)
            asset.params = {**asset.params, "draft": {**asset.params["draft"], "status": "failed"}}
    assert (
        retry_final_asset(
            tenant_id=tenant, draft_id=draft, asset_id=asset_id, now=NOW, automatic=True
        )
        == "blocked"
    )
    with tenant_session(tenant) as session:
        assert (
            session.execute(
                text("SELECT count(*) FROM creative_jobs WHERE draft_id=:d"), {"d": draft}
            ).scalar()
            == 3
        )
        block = session.get(orm.ImageAsset, asset_id).params["draft"]
        assert block["status"] == "failed" and block["final_retry_exhausted"]
        from qualify_api.creative.final_review import FINAL_FAILED_TEXT

        assert block["error"] == FINAL_FAILED_TEXT


def test_content_refusal_or_unknown_failure_is_not_retried_automatically() -> None:
    tenant, draft, asset_id, job, _ = _failed()
    from qualify_api.creative.final_retries import record_final_vendor_failure

    record_final_vendor_failure(tenant_id=tenant, job_id=job, code="ContentPolicyViolation")
    assert (
        retry_final_asset(
            tenant_id=tenant, draft_id=draft, asset_id=asset_id, now=NOW, automatic=True
        )
        == "blocked"
    )

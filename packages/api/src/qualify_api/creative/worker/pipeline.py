"""Production queue executors and preparation, run inside creative-worker only."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from qualify_creative.adapters.byteplus_ark import VendorBusy
from qualify_creative.providers import GenerationRequest
from qualify_shared.db.creative_worker import creative_worker_session
from qualify_shared.db.session import tenant_session, tenant_unit_of_work
from sqlalchemy import text

from qualify_api.creative import job_queue as q
from qualify_api.creative.final_deadline import (
    FINAL_EXPIRED_TEXT,
    FinalDeadlineExpired,
    final_deadline_passed,
)
from qualify_api.creative.pipeline import (
    PipelineStore,
    encode_result,
    preparing,
    request_from,
)
from qualify_api.creative.queue_dispatch import SubmissionUncertain
from qualify_api.creative.worker.executor import JobContext, TaskPoll

logger = logging.getLogger(__name__)


class SubmissionRecorder:
    """Keep the real id at acceptance, before the adapter returns to the loop."""

    def __init__(self, job: JobContext) -> None:
        self.job = job

    def created(self, task_id: str) -> None:
        with tenant_session(self.job.tenant_id) as session:
            if not q.record_submission(
                session,
                job_id=self.job.job_id,
                claim_token=self.job.claim_token,
                vendor_task_id=task_id,
                now=datetime.now(UTC),
            ):
                raise RuntimeError("submission lost its claim")

    def polled(self, task_id: str, status: str) -> None:
        pass


class PipelineExecutor:
    def __init__(self, service: Any, pipeline: PipelineStore, adapter: Any, provider: str) -> None:
        self.service, self.pipeline, self.adapter, self.provider = (
            service,
            pipeline,
            adapter,
            provider,
        )

    def _step(self, job: JobContext) -> Any:
        row = self.pipeline.job_step(job.tenant_id, job.job_id)
        if row["draft_id"] != job.draft_id or row["revision"] != job.revision:
            raise ValueError("job does not match its immutable preparation")
        return row

    def _request(self, job: JobContext) -> tuple[Any, GenerationRequest, Any]:
        row = self._step(job)
        request = request_from(row["request"])
        key = self.service._credentials.resolve(
            tenant_id=job.tenant_id, brand_id=row["brand_id"], provider=self.provider
        )
        return row, request, key

    def submit(self, job: JobContext) -> str:
        row, request, key = self._request(job)
        if row["error"] is not None:
            raise ValueError("previous submission needs reconciliation; refusing another paid call")
        # Repeat the price guard at the actual paid boundary, not just preparation.
        budget = self.service._repo.budget_state(tenant_id=job.tenant_id, brand_id=row["brand_id"])
        estimate = self.adapter.estimate_cost_usd(
            request, self.service._pricing, api_key=key.api_key
        )
        if budget is not None and estimate > budget.remaining_usd:
            raise ValueError("generation budget no longer covers this task")
        self._validate_reservation(job)
        self._stamp_started(job)
        # Credentials/budget checks can take time: recheck at the paid boundary too.
        if job.kind == q.KIND_FINAL and final_deadline_passed(job.deadline, datetime.now(UTC)):
            raise FinalDeadlineExpired(FINAL_EXPIRED_TEXT)
        with tenant_session(job.tenant_id) as session:
            session.execute(
                text("""
                UPDATE creative_pipeline_steps SET error='submitting'
                WHERE job_id=:j AND result IS NULL AND error IS NULL
            """),
                {"j": job.job_id},
            )
            session.execute(
                text(
                    "UPDATE creative_jobs SET not_before=:until WHERE id=:j "
                    "AND claim_token=:token AND status='claimed' AND vendor_task_id IS NULL"
                ),
                {
                    "j": job.job_id,
                    "token": job.claim_token,
                    "until": datetime.now(UTC) + timedelta(hours=48),
                },
            )
        request = replace(request, observer=SubmissionRecorder(job))
        try:
            if self.provider == "seedance":
                task_id = self.adapter.submit(
                    request, api_key=key.api_key, priority=job.vendor_priority
                )
            else:
                task_id = self.adapter.submit(request, api_key=key.api_key)
        except VendorBusy:
            # A 429 proves no task was created; permit the worker's adaptive retry.
            with tenant_session(job.tenant_id) as session:
                session.execute(
                    text("""
                    UPDATE creative_pipeline_steps SET error=NULL
                    WHERE job_id=:j AND error='submitting'
                """),
                    {"j": job.job_id},
                )
            raise
        except Exception as exc:
            # The POST may have been accepted. The pre-POST eligibility fence also
            # survives a database outage here; recovery conservatively keeps its slot.
            try:
                with tenant_session(job.tenant_id) as session:
                    known = q.load_job(session, job.job_id)
                    if known is not None and known.vendor_task_id is None:
                        session.execute(
                            text("""
                            UPDATE creative_pipeline_steps SET error='submission_uncertain'
                            WHERE job_id=:j AND error='submitting'
                        """),
                            {"j": job.job_id},
                        )
                        session.execute(
                            text("""
                            UPDATE creative_pipeline_runs SET dirty_version=dirty_version+1
                            WHERE tenant_id=:t AND draft_id=:d AND revision=:r AND phase=:p
                        """),
                            {
                                "t": job.tenant_id,
                                "d": job.draft_id,
                                "r": job.revision,
                                "p": row["phase"],
                            },
                        )
            except Exception:
                logger.error("creative.pipeline.reconciliation_pending job_id=%s", job.job_id)
            raise SubmissionUncertain("vendor acceptance requires reconciliation") from exc
        with tenant_session(job.tenant_id) as session:
            session.execute(
                text("""
                UPDATE creative_pipeline_steps SET error=NULL
                WHERE job_id=:j AND error='submitting'
            """),
                {"j": job.job_id},
            )
            session.execute(
                text("UPDATE creative_jobs SET not_before=:now WHERE id=:j"),
                {"j": job.job_id, "now": datetime.now(UTC)},
            )
        return task_id

    def _validate_reservation(self, job: JobContext) -> None:
        with tenant_session(job.tenant_id) as session:
            row = (
                session.execute(
                    text("""
                SELECT j.status, j.claim_token, j.charge_id, d.revision, d.status AS draft_status,
                       j.final_attempt,
                       coalesce((a.params->'draft'->>'final_attempt')::int,0) AS asset_attempt,
                       a.params->'draft'->>'status' AS asset_status,
                       c.status AS charge_status, c.videos,
                       c.final_refunded_assets
                FROM creative_jobs j JOIN content_drafts d ON d.id=j.draft_id
                LEFT JOIN image_assets a ON a.draft_id=j.draft_id AND a.position=j.position
                    AND a.params ? 'draft'
                LEFT JOIN creation_charges c ON c.id=j.charge_id
                    AND c.tenant_id=j.tenant_id AND c.draft_id=j.draft_id
                    AND c.revision=j.revision
                WHERE j.id=:j FOR UPDATE OF j,d
            """),
                    {"j": job.job_id},
                )
                .mappings()
                .one()
            )
            if (
                row["status"] != "claimed"
                or row["claim_token"] != job.claim_token
                or row["revision"] != job.revision
            ):
                raise ValueError("job no longer belongs to the current piece revision")
            if job.kind == q.KIND_FINAL:
                if (
                    row["draft_status"] != "approved"
                    or row["asset_attempt"] != row["final_attempt"]
                    or row["asset_status"] not in {"final_scheduled", "rendering"}
                ):
                    raise ValueError("final attempt no longer belongs to the approved piece")
            elif row["draft_status"] != "drafting":
                raise ValueError("generation no longer belongs to a drafting piece")
            if self.service._creations is not None:
                if row["charge_id"] is None or row["charge_status"] != "charged":
                    raise ValueError("generation reservation is no longer active")
                if job.kind == q.KIND_FINAL and not row["videos"]:
                    raise ValueError("final video has no reserved plan unit")

    def _stamp_started(self, job: JobContext) -> None:
        with tenant_session(job.tenant_id) as session:
            session.execute(
                text("""
                UPDATE content_drafts SET updated_at=:now WHERE id=:d AND revision=:r
            """),
                {"d": job.draft_id, "r": job.revision, "now": datetime.now(UTC)},
            )
            if job.kind == q.KIND_FINAL:
                session.execute(
                    text("""
                    UPDATE image_assets SET params=jsonb_set(
                        jsonb_set(params, '{draft,rendering_at}',
                            to_jsonb(CAST(:stamp AS double precision))),
                        '{draft,status}', '"rendering"'::jsonb)
                    WHERE draft_id=:d AND position=:pos
                      AND EXISTS (SELECT 1 FROM content_drafts d WHERE d.id=:d AND d.revision=:r)
                      AND coalesce((params->'draft'->>'final_attempt')::int,0)=
                          (SELECT final_attempt FROM creative_jobs WHERE id=:job)
                """),
                    {
                        "d": job.draft_id,
                        "pos": job.position,
                        "r": job.revision,
                        "job": job.job_id,
                        "stamp": datetime.now(UTC).timestamp(),
                    },
                )

    def poll(self, job: JobContext, vendor_task_id: str) -> TaskPoll:
        row, _, key = self._request(job)
        if row["result"] is not None:
            return TaskPoll("succeeded")
        if row["error"] is not None and row["error"] != "submitting":
            return TaskPoll("failed")
        if self.provider == "seedance":
            state = self.adapter.poll(vendor_task_id, api_key=key.api_key)
            status = state.status
            if status == "failed" and job.kind == q.KIND_FINAL:
                from qualify_api.creative.final_retries import record_final_vendor_failure

                record_final_vendor_failure(
                    tenant_id=job.tenant_id,
                    job_id=job.job_id,
                    code=getattr(state, "error_code", None),
                )
        else:
            from qualify_api.creative.vendor_recovery import OMNIHUMAN_STATES

            data = self.adapter.get_task(vendor_task_id, api_key=key.api_key)
            status = OMNIHUMAN_STATES.get(str(data.get("status") or ""), "unknown")
        if status == "running":
            with tenant_session(job.tenant_id) as session:
                session.execute(
                    text("""
                    UPDATE creative_jobs SET running_at=COALESCE(running_at,:now) WHERE id=:j
                """),
                    {"j": job.job_id, "now": datetime.now(UTC)},
                )
        # A job waiting on the vendor is alive; the reaper counts silence, not age.
        self._stamp_started(job)
        return TaskPoll(status, 5)

    def finish(self, job: JobContext, vendor_task_id: str | None, status: str) -> None:
        row = self._step(job)
        identity = {
            "t": job.tenant_id,
            "d": job.draft_id,
            "r": job.revision,
            "p": row["phase"],
            "s": row["step"],
        }
        if row["result"] is not None or row["error"] not in (None, "submitting"):
            return
        if row["error"] == "submitting":
            # A task id on the queue proves acceptance even if the process died before
            # clearing the intent. Without an id we preserve an explicit uncertain
            # result, never silently submit it twice.
            with tenant_session(job.tenant_id) as session:
                session.execute(
                    text("""
                    UPDATE creative_pipeline_steps SET error=NULL
                    WHERE job_id=:j AND error='submitting'
                """),
                    {"j": job.job_id},
                )
            if vendor_task_id is None:
                status = "submission_uncertain"
        if status == "expired" and vendor_task_id is None and job.kind == q.KIND_FINAL:
            self._expire_final(job, row["phase"])
        result = None
        if status == "succeeded" and vendor_task_id:
            _, request, key = self._request(job)
            if self.provider == "seedance":
                state = self.adapter.poll(vendor_task_id, api_key=key.api_key)
                result = self.adapter.result(request, state)
            else:
                data = dict(self.adapter.get_task(vendor_task_id, api_key=key.api_key))
                data["task_id"] = vendor_task_id
                result = self.adapter.result(request, data)
        if result is not None:
            from qualify_api.creative.media import _http_download, generated_object_key

            media = self.service._media
            data = encode_result(result, media._store, "", job.tenant_id)
            if result.media_url:
                raw_key = generated_object_key(
                    job.tenant_id, job.draft_id, job.revision, f"queue-{job.job_id}.bin"
                )
                # A crash after keeping bytes but before PG must not require a live vendor URL.
                checkpoint = getattr(media._store, "checkpoint_download", None)
                if checkpoint is not None:
                    checkpoint(job.tenant_id, raw_key, result.media_url)
                else:
                    # Small in-memory/local stores used by engine callers and tests.
                    # Production's R2 store always streams through checkpoint_download.
                    try:
                        raw = media._store.read(raw_key)
                    except Exception:
                        raw = _http_download(result.media_url)
                        keep = getattr(media._store, "keep", None)
                        if keep is not None:
                            if not keep(job.tenant_id, raw_key, raw, "video/mp4"):
                                raise RuntimeError("could not checkpoint the paid video")
                        else:
                            media._store.write(raw_key, raw)
                data["checkpoint_media"] = raw_key
            self.pipeline.complete_step(job.tenant_id, identity=identity, result=data)
        else:
            self.pipeline.complete_step(job.tenant_id, identity=identity, result=None, error=status)

    def _expire_final(self, job: JobContext, phase: str) -> None:
        """Fail only this revision's asset, without credentials or any vendor call."""
        asset_id = UUID(phase.split(":", 1)[1].split("@", 1)[0])
        with tenant_unit_of_work(job.tenant_id), tenant_session(job.tenant_id) as session:
            current = session.execute(
                text("""
                SELECT a.id FROM image_assets a
                JOIN content_drafts d ON d.id=a.draft_id AND d.tenant_id=a.tenant_id
                JOIN creative_jobs j ON j.draft_id=d.id AND j.tenant_id=d.tenant_id
                WHERE j.id=:j AND j.claim_token=:token AND j.status='claimed'
                  AND j.vendor_task_id IS NULL AND d.revision=:r
                  AND a.id=:a AND a.position=:pos
                  AND coalesce((a.params->'draft'->>'final_attempt')::int,0)=j.final_attempt
                FOR UPDATE OF a,d,j
                """),
                {
                    "j": job.job_id,
                    "token": job.claim_token,
                    "r": job.revision,
                    "a": asset_id,
                    "pos": job.position,
                },
            ).scalar_one_or_none()
            if current is None:
                raise ValueError("expired final no longer belongs to this claim")
            session.execute(
                text("""
                UPDATE image_assets
                SET params=jsonb_set(COALESCE(params, '{}'::jsonb), '{draft}',
                    COALESCE(params->'draft', '{}'::jsonb) || CAST(:changes AS jsonb))
                WHERE id=:a
                """),
                {
                    "a": asset_id,
                    "changes": json.dumps(
                        {
                            "status": "failed",
                            "error": FINAL_EXPIRED_TEXT,
                        }
                    ),
                },
            )
            if self.service._creations is not None:
                self.service._creations.refund_final(
                    tenant_id=job.tenant_id,
                    draft_id=job.draft_id,
                    revision=job.revision,
                    reason="draft_expired",
                    asset_ids=(asset_id,),
                )


class PipelinePreparation:
    def __init__(
        self, service: Any, store: PipelineStore, tenant_ids: Sequence[UUID] | None
    ) -> None:
        self.service, self.store, self.tenant_ids = service, store, tenant_ids

    def __call__(self) -> None:
        if self.tenant_ids is None:
            # Only opaque queue metadata crosses tenants. Content is always read again
            # through the owning tenant door, never this restricted worker role.
            with creative_worker_session() as session:
                tenants = (
                    session.execute(text("SELECT DISTINCT tenant_id FROM creative_jobs"))
                    .scalars()
                    .all()
                )
        else:
            tenants = self.tenant_ids
        for tenant_id in tenants:
            with tenant_session(tenant_id) as session:
                runs = (
                    session.execute(
                        text("""
                    SELECT draft_id,revision,phase FROM creative_pipeline_runs
                    WHERE dirty_version > prepared_version
                    ORDER BY draft_id,revision,phase LIMIT 20
                """)
                    )
                    .mappings()
                    .all()
                )
            for item in runs:
                run = self.store.acquire(
                    tenant_id, item["draft_id"], item["revision"], item["phase"]
                )
                if run is None:
                    continue
                completed = False
                try:
                    draft = self.service._repo.get_draft(tenant_id=tenant_id, draft_id=run.draft_id)
                    if draft is None or draft.revision != run.revision:
                        completed = True
                        continue
                    with preparing(run):
                        if run.phase == "generation":
                            self.service.run_generation(tenant_id=tenant_id, draft_id=run.draft_id)
                        else:
                            self.service.run_queued_final(
                                tenant_id=tenant_id,
                                draft_id=run.draft_id,
                                asset_id=UUID(run.phase.split(":", 1)[1].split("@", 1)[0]),
                            )
                    self._settle_local(run)
                    completed = True
                except Exception as exc:
                    logger.error(
                        "creative.pipeline.preparation_failed draft_id=%s error_type=%s",
                        run.draft_id,
                        type(exc).__name__,
                    )
                finally:
                    self.store.release(run, completed=completed)

    def _settle_local(self, run: Any) -> None:
        """Image/copy-only jobs finish in preparation; videos are settled by executors."""
        with tenant_session(run.tenant_id) as session:
            session.execute(
                text("""
                UPDATE creative_jobs j SET status=CASE WHEN d.status='failed' THEN 'failed'
                    ELSE 'succeeded' END, finished_at=:now
                FROM content_drafts d
                WHERE j.tenant_id=:t AND j.draft_id=:d AND j.revision=:r
                  AND j.draft_id=d.id AND j.kind<>'final' AND j.status='queued'
                  AND d.status IN ('generated','failed')
                  AND NOT EXISTS (SELECT 1 FROM creative_pipeline_steps s WHERE s.job_id=j.id)
            """),
                {**run.params(), "now": datetime.now(UTC)},
            )

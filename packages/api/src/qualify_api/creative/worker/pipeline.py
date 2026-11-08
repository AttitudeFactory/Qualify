"""Production queue executors and preparation, run inside creative-worker only."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from qualify_creative.adapters.byteplus_ark import ArkAPIError, VendorBusy
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
from qualify_api.creative.part_final import JOIN_FINAL_PHASE, run_join_final
from qualify_api.creative.part_join import JOIN_PHASE, run_join
from qualify_api.creative.pipeline import (
    PipelineStore,
    encode_result,
    lease_kept,
    preparing,
    request_from,
)
from qualify_api.creative.queue_dispatch import SubmissionUncertain
from qualify_api.creative.worker.executor import JobContext, TaskPoll

logger = logging.getLogger(__name__)

#: VE-10a / VE-10b: the parent's local joins (its preview, its 1080p final) — run off the
#: loop, one at a time, with their lease kept alive
_JOIN_PHASES = frozenset({JOIN_PHASE, JOIN_FINAL_PHASE})


class VendorRefused(Exception):
    """VE-09, parts only: ModelArk answered the task's creation with a 4xx that is not «busy» (an
    input moderated as a real person, `PrivacyInformation`; a bad parameter): no task
    exists and nothing is billed. The step keeps the vendor's code (`refused: <code>`),
    so the generation's preparation fails the piece saying why, instead of holding a
    slot as an uncertain submission."""


def _is_part(job: JobContext) -> bool:
    """Whether the job's piece is a part of a video by parts (VE-09 scope)."""
    try:
        with tenant_session(job.tenant_id) as session:
            return bool(
                session.execute(
                    text("SELECT parent_draft_id IS NOT NULL FROM content_drafts WHERE id=:d"),
                    {"d": job.draft_id},
                ).scalar()
            )
    except Exception:  # noqa: BLE001 — unknown: today's behaviour
        return False


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
        except ArkAPIError as exc:
            if (
                job.kind != q.KIND_FINAL
                and 400 <= exc.status_code < 500
                and self._refused(job, row, exc)
            ):
                raise VendorRefused(exc.code or "unknown_error") from exc
            self._uncertain(job, row)
            raise SubmissionUncertain("vendor acceptance requires reconciliation") from exc
        except Exception as exc:
            self._uncertain(job, row)
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

    def _refused(self, job: JobContext, row: Any, exc: ArkAPIError) -> bool:
        """VE-09, parts only (Deivid, 2026-11-06): a 4xx at creation proves no task
        exists, so a PART's step fails with the vendor's code — what the preparation's
        re-run reads. One transaction turns `submitting` into the refusal and dirties the
        run; any other piece, or a write that fails, returns False and the caller keeps
        today's `submission_uncertain` (the step never goes back to NULL, so it is never
        POSTed again)."""
        error = f"refused: HTTP {exc.status_code} {exc.code or 'unknown_error'}"
        try:
            with tenant_session(job.tenant_id) as session:
                refused = self._write_refusal(session, job, row, error)
        except Exception as write_error:  # noqa: BLE001 — falls back to uncertain
            logger.error(
                "creative.pipeline.refusal_not_written job_id=%s error_type=%s",
                job.job_id,
                type(write_error).__name__,
            )
            return False
        if refused:
            logger.warning(
                "creative.pipeline.vendor_refused job_id=%s code=%s", job.job_id, exc.code
            )
        return refused

    def _write_refusal(self, session: Any, job: JobContext, row: Any, error: str) -> bool:
        changed = session.execute(
            text("""
            UPDATE creative_pipeline_steps SET error=:error
            WHERE job_id=:j AND error='submitting'
              AND EXISTS (SELECT 1 FROM content_drafts d
                          WHERE d.id=:d AND d.parent_draft_id IS NOT NULL)
            RETURNING step
        """),
            {"j": job.job_id, "d": job.draft_id, "error": error},
        ).scalar()
        if changed is None:
            return False
        session.execute(
            text("""
            UPDATE creative_pipeline_runs SET dirty_version=dirty_version+1
            WHERE tenant_id=:t AND draft_id=:d AND revision=:r AND phase=:p
        """),
            {"t": job.tenant_id, "d": job.draft_id, "r": job.revision, "p": row["phase"]},
        )
        return True

    def _uncertain(self, job: JobContext, row: Any) -> None:
        """The POST may have been accepted. The pre-POST eligibility fence also survives
        a database outage here; recovery conservatively keeps its slot."""
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
            self.pipeline.complete_step(
                job.tenant_id,
                identity=identity,
                result=None,
                error=self._failed_with_code(job, vendor_task_id, status),
            )

    def _failed_with_code(self, job: JobContext, vendor_task_id: str | None, status: str) -> str:
        """VE-09, parts only: a preview task Seedance ended `failed` keeps the vendor's code in the
        step (`failed: <code>`), so the preparation's re-run says why — a real person
        refused is `refused_face`, not a provider error. Read with one status GET (not
        billed); without it the step says `failed`, as before."""
        if status != "failed" or not vendor_task_id or job.kind == q.KIND_FINAL:
            return status
        if self.provider != "seedance" or not _is_part(job):
            return status
        try:
            _, _, key = self._request(job)
            code = getattr(
                self.adapter.poll(vendor_task_id, api_key=key.api_key), "error_code", None
            )
        except Exception as exc:  # noqa: BLE001 — the reason is a nicety, the failure is not
            logger.warning(
                "creative.pipeline.failure_code_unread job_id=%s error_type=%s",
                job.job_id,
                type(exc).__name__,
            )
            return status
        return f"{status}: {code}" if code else status

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


def _final_asset(phase: str) -> UUID | None:
    """The asset of a `final:<uuid>[@attempt]` phase, or None for any other name."""
    if not phase.startswith("final:"):
        return None
    try:
        return UUID(phase.split(":", 1)[1].split("@", 1)[0])
    except ValueError:
        return None


#: How long a stopping worker waits for a join in flight before abandoning it (Docker
#: gives `stop_grace_period`; the join is redone or reused on the next start).
JOIN_SHUTDOWN_GRACE_SECONDS = 20.0


class BackgroundJoins:
    """VE-10a: the parents' joins off the worker's main loop — ONE at a time, on its own
    daemon thread, so `claim_round`, `recover` and the heartbeat (`monitor.beat`) keep
    running while a slow arm64 encodes. The thread owns the run it was handed: it keeps
    its lease alive (`lease_kept`) and releases it when done (marked prepared only when
    the join finished). A stopping worker waits `JOIN_SHUTDOWN_GRACE_SECONDS`, then
    abandons it: renewals stop and the lease is released NOT done, so the next start
    redoes the join or reuses its file (the key is its fingerprint; the save is one
    transaction fenced by the lease, so an abandoned thread can never write after)."""

    def __init__(self, store: PipelineStore) -> None:
        self.store = store
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._run: Any = None
        self._halt = threading.Event()

    def busy(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self, run: Any, work: Callable[[Any], object]) -> bool:
        """Run `work(run)` in the background; False (nothing started) while another
        join is in flight or after shutdown. `work` gets the RUN — everything it
        needs (tenant, draft) comes from it, never from the caller's loop variables,
        which have moved on by the time the thread runs."""
        with self._lock:
            if self.busy() or self._halt.is_set():
                return False

            def body() -> None:
                completed = False
                try:
                    with preparing(run), lease_kept(self.store, run, halt=self._halt):
                        work(run)
                    completed = True
                except Exception as exc:
                    logger.error(
                        "creative.pipeline.preparation_failed draft_id=%s error_type=%s",
                        run.draft_id,
                        type(exc).__name__,
                    )
                finally:
                    self.store.release(run, completed=completed)

            self._run = run
            self._thread = threading.Thread(target=body, name="creative-join", daemon=True)
            self._thread.start()
            return True

    def shutdown(self, timeout: float | None = JOIN_SHUTDOWN_GRACE_SECONDS) -> bool:
        """Stop taking joins; wait for the one in flight (`timeout=None`: as long as it
        takes, `--once`). True when none is left running."""
        from qualify_creative.video.join_child import WORKER_STOPPING  # noqa: PLC0415

        with self._lock:
            if timeout is not None:
                self._halt.set()
                # a join child killed from here on is not lost to its part (VE-10b)
                WORKER_STOPPING.set()
            thread, run = self._thread, self._run
        if thread is None:
            return True
        thread.join(timeout)
        if not thread.is_alive():
            return True
        self._halt.set()
        logger.warning(
            "creative.pipeline.join_abandoned draft_id=%s (redone or reused on next start)",
            run.draft_id,
        )
        try:
            self.store.release(run, completed=False)  # token-matched: never another's
        except Exception as exc:  # noqa: BLE001 — the lease then just runs out
            logger.warning(
                "creative.pipeline.join_release_failed error_type=%s", type(exc).__name__
            )
        return False


class PipelinePreparation:
    def __init__(
        self,
        service: Any,
        store: PipelineStore,
        tenant_ids: Sequence[UUID] | None,
        *,
        background_joins: bool = False,
    ) -> None:
        self.service, self.store, self.tenant_ids = service, store, tenant_ids
        #: VE-10a: the worker loop joins in the background (one at a time); tests and the
        #: memory harness join inline, the same code on the calling thread
        self.joins = BackgroundJoins(store) if background_joins else None

    def shutdown(self, timeout: float | None = JOIN_SHUTDOWN_GRACE_SECONDS) -> bool:
        """The worker is stopping: wait for (or abandon) the join in flight."""
        if timeout is not None:
            from qualify_creative.video.join_child import WORKER_STOPPING  # noqa: PLC0415

            WORKER_STOPPING.set()  # also for an inline join (tests, the memory harness)
        return True if self.joins is None else self.joins.shutdown(timeout)

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
                if item["phase"] in _JOIN_PHASES and self.joins is not None and self.joins.busy():
                    continue  # one join at a time: this one waits for the next pass
                run = self.store.acquire(
                    tenant_id, item["draft_id"], item["revision"], item["phase"]
                )
                if run is None:
                    continue
                completed = handed = False
                try:
                    draft = self.service._repo.get_draft(tenant_id=tenant_id, draft_id=run.draft_id)
                    if draft is None or draft.revision != run.revision:
                        completed = True
                        continue
                    asset_id = _final_asset(run.phase)
                    if (
                        run.phase != "generation"
                        and run.phase not in _JOIN_PHASES
                        and asset_id is None
                    ):
                        # VE-10a: a phase this worker does not know is failed ONCE —
                        # done, logged — never retried in a loop as a preparation error
                        logger.error(
                            "creative.pipeline.unknown_phase draft_id=%s phase=%s",
                            run.draft_id,
                            run.phase,
                        )
                        completed = True
                        continue
                    if run.phase in _JOIN_PHASES and self.joins is not None:
                        # the thread owns the run (and its release) from here on
                        handed = self.joins.start(run, self._join_run)
                        continue
                    with preparing(run):
                        if run.phase == "generation":
                            self.service.run_generation(tenant_id=tenant_id, draft_id=run.draft_id)
                        elif run.phase in _JOIN_PHASES:
                            # VE-10a/VE-10b: the parent of a video by parts joins its parts'
                            # previews or raw finals (local, cost 0); it has no job of its
                            # own to settle. The encode can outlast the lease: kept alive.
                            with lease_kept(self.store, run):
                                self._join_run(run)
                        else:
                            self.service.run_queued_final(
                                tenant_id=tenant_id, draft_id=run.draft_id, asset_id=asset_id
                            )
                    if run.phase not in _JOIN_PHASES:
                        self._settle_local(run)
                    completed = True
                except Exception as exc:
                    logger.error(
                        "creative.pipeline.preparation_failed draft_id=%s error_type=%s",
                        run.draft_id,
                        type(exc).__name__,
                    )
                finally:
                    if not handed:
                        self.store.release(run, completed=completed)

    def _join(self, tenant_id: UUID, parent_id: UUID) -> None:
        run_join(self.service._media, tenant_id, parent_id)

    def _join_run(self, run: Any) -> None:
        """The join of `run`: its own tenant and parent, bound from the run (never from
        the loop's variables) — the preview (`join`) or the 1080p final (`join_final`)."""
        if run.phase == JOIN_FINAL_PHASE:
            run_join_final(self.service._media, run.tenant_id, run.draft_id)
        else:
            self._join(run.tenant_id, run.draft_id)

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

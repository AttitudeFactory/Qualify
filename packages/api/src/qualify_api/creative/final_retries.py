"""Bounded final retries retain each paid vendor id and the original quota charge."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from qualify_shared.db.session import tenant_session
from sqlalchemy import select, text

from qualify_api.creative import job_queue as q
from qualify_api.creative import models as orm
from qualify_api.creative.draft_mode import draft_state
from qualify_api.creative.versions import visible_version

MAX_FINAL_ATTEMPTS = 3
UNPREPARED = datetime(9999, 1, 1, tzinfo=UTC)
# BytePlus's documented temporary failures, never moderation or bad inputs:
# https://docs.byteplus.com/en/docs/modelark/error-codes
TRANSIENT_VENDOR_ERRORS = frozenset({"InternalServiceError", "ServerOverloaded"})


def record_final_vendor_failure(*, tenant_id: UUID, job_id: UUID, code: str | None) -> None:
    """Called by the final poller, with the vendor's structured error code only."""
    with tenant_session(tenant_id) as session:
        job = (
            session.execute(
                text("""
            SELECT draft_id,position,final_attempt FROM creative_jobs
            WHERE id=:id AND kind='final'
        """),
                {"id": job_id},
            )
            .mappings()
            .first()
        )
        if job is None:
            return
        asset = session.scalar(
            select(orm.ImageAsset)
            .where(
                orm.ImageAsset.draft_id == job["draft_id"],
                visible_version(orm.ImageAsset),
                orm.ImageAsset.position == job["position"],
            )
            .with_for_update()
        )
        if asset is None:
            return
        block = dict(draft_state(asset.params) or {})
        if int(block.get("final_attempt") or 0) != job["final_attempt"]:
            return
        block.update(
            final_vendor_error_code=code, final_transient_failure=code in TRANSIENT_VENDOR_ERRORS
        )
        asset.params = {**dict(asset.params or {}), "draft": block}


def final_phase(asset_id: UUID, attempt: int) -> str:
    return f"final:{asset_id}" + (f"@{attempt}" if attempt else "")


def automatic_retry_window(block: Mapping[str, object], *, now: datetime, timezone: str) -> bool:
    """One overnight batch plus its first morning hour; never retry forever."""
    from qualify_api.creative.final_review import configured_night_hours

    if block.get("final_origin") != "approval":
        return False
    raw = block.get("final_batch_not_before")
    if not isinstance(raw, str):
        return False
    batch = datetime.fromisoformat(raw)
    _, end = configured_night_hours()
    local_batch = batch.astimezone(ZoneInfo(timezone))
    close = local_batch.replace(hour=end % 24, minute=0, second=0, microsecond=0)
    if end == 24 or close <= local_batch:
        close += timedelta(days=1)
    return batch <= now <= close + timedelta(hours=1)


def retry_final_asset(
    *,
    tenant_id: UUID,
    draft_id: UUID,
    asset_id: UUID,
    now: datetime | None = None,
    automatic: bool = False,
) -> str:
    """Return created/resumed/inflight/blocked/initial; every decision is row locked.

    A failed paid vendor task gets a NEW final attempt and a NEW preparation phase.
    A paid success whose local assembly failed reuses its result/id, never another
    POST. Ambiguous submission failures are deliberately not retried automatically.
    """
    from qualify_api.creative.final_review import FINAL_FAILED_TEXT
    from qualify_api.tenancy.models import Tenant

    moment = now or datetime.now(UTC)
    with tenant_session(tenant_id) as session:
        draft = session.get(orm.ContentDraft, draft_id, with_for_update=True)
        asset = session.get(orm.ImageAsset, asset_id, with_for_update=True)
        if (
            draft is None
            or asset is None
            or asset.draft_id != draft_id
            or draft.status != "approved"
        ):
            return "blocked"
        block = dict(draft_state(asset.params) or {})
        if block.get("status") != "failed":
            return "inflight"
        tenant = session.get(Tenant, tenant_id)
        timezone = tenant.timezone if tenant else "UTC"
        if automatic and not automatic_retry_window(block, now=moment, timezone=timezone):
            return "blocked"
        deadline_raw = block.get("final_deadline")
        if isinstance(deadline_raw, str) and datetime.fromisoformat(deadline_raw) <= moment:
            return "blocked"
        previous = (
            session.execute(
                text("""
            SELECT * FROM creative_jobs WHERE draft_id=:draft AND revision=:revision
              AND kind='final' AND position=:position
            ORDER BY final_attempt DESC LIMIT 1 FOR UPDATE
        """),
                {"draft": draft_id, "revision": draft.revision, "position": asset.position},
            )
            .mappings()
            .first()
        )
        if previous is None:
            return "initial"
        if previous["status"] in {"queued", "claimed", "submitted"}:
            return "inflight"
        checkpoint = (
            session.execute(
                text("""
            SELECT phase, result, error FROM creative_pipeline_steps WHERE job_id=:job
        """),
                {"job": previous["id"]},
            )
            .mappings()
            .first()
        )
        has_result = checkpoint is not None and checkpoint["result"] is not None
        if previous["vendor_task_id"] and (has_result or previous["last_error"] == "finish_failed"):
            # Existing paid task/result: resume local work, without changing its id.
            local_retries = int(block.get("final_local_retries") or 0)
            if local_retries >= MAX_FINAL_ATTEMPTS:
                return "blocked"
            phase = (
                checkpoint["phase"]
                if checkpoint is not None
                else final_phase(asset_id, previous["final_attempt"])
            )
            session.execute(
                text("""
                UPDATE creative_jobs SET status='queued', not_before=:now, finished_at=NULL,
                  last_error=NULL WHERE id=:job AND status IN ('failed','succeeded')
            """),
                {"job": previous["id"], "now": moment},
            )
            session.execute(
                text("""
                UPDATE creative_pipeline_runs SET dirty_version=dirty_version+1
                WHERE draft_id=:draft AND revision=:revision AND phase=:phase
            """),
                {"draft": draft_id, "revision": draft.revision, "phase": phase},
            )
            block.update(status="rendering", error=None, final_local_retries=local_retries + 1)
            asset.params = {**dict(asset.params or {}), "draft": block}
            return "resumed"
        if (
            previous["status"] != "failed"
            or not previous["vendor_task_id"]
            or previous["last_error"] != "failed"
        ):
            return "blocked"
        if automatic and not block.get("final_transient_failure"):
            return "blocked"
        attempt = int(previous["final_attempt"]) + 1
        if attempt >= MAX_FINAL_ATTEMPTS:
            block.update(error=FINAL_FAILED_TEXT, final_retry_exhausted=True)
            asset.params = {**dict(asset.params or {}), "draft": block}
            return "blocked"
        wait = timedelta(seconds=30 * attempt) if automatic else timedelta(0)
        when = moment + wait
        if isinstance(deadline_raw, str) and when >= datetime.fromisoformat(deadline_raw):
            return "blocked"
        phase = final_phase(asset_id, attempt)
        session.execute(
            text("""
            INSERT INTO creative_pipeline_runs(tenant_id,draft_id,revision,phase,pipeline_version)
            VALUES(:tenant,:draft,:revision,:phase,:version) ON CONFLICT DO NOTHING
        """),
            {
                "tenant": tenant_id,
                "draft": draft_id,
                "revision": draft.revision,
                "phase": phase,
                "version": draft.pipeline_version,
            },
        )
        q.enqueue_job(
            session,
            tenant_id=tenant_id,
            draft_id=draft_id,
            revision=draft.revision,
            kind=q.KIND_FINAL,
            position=asset.position,
            final_attempt=attempt,
            vendor_model=previous["vendor_model"],
            lane=previous["lane"],
            priority=previous["priority"],
            not_before=UNPREPARED,
            deadline=previous["deadline"],
            charge_id=previous["charge_id"],
            pricing_version=previous["pricing_version"],
            pipeline_version=previous["pipeline_version"],
        )
        block.update(
            status="rendering",
            final_attempt=attempt,
            final_not_before=when.isoformat(),
            rendering_at=None,
            error=None,
            attempt=uuid4().hex,
            claim=None,
            final_retry_exhausted=False,
        )
        asset.params = {**dict(asset.params or {}), "draft": block}
        return "created"

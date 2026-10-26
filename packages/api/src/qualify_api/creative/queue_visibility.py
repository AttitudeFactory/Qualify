"""Tenant-scoped queue facts and atomic pre-submit cancellation (m-24852170).

The UI reads only its own jobs. Shared load estimates come from anonymous Redis
aggregates; cross-tenant queue reads remain in the worker, never in a request.
"""

from __future__ import annotations

import json
import logging
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from qualify_creative.queue_errors import CANCELLED_TEXT
from qualify_shared.db.session import tenant_session
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from qualify_api.creative.creations import refund_final_in_session, refund_in_session
from qualify_api.creative.fsm import DRAFTING, DraftTrigger, apply_transition
from qualify_api.creative.models import ContentDraft, ImageAsset

logger = logging.getLogger(__name__)
CANCEL_NOT_AVAILABLE = "Tu video ya se está preparando. Ya no se puede cancelar."
LOAD_KEY = "qualify:creative-queue:public-load:v1"
LOAD_TTL = 180


class QueueCancellationUnavailable(ValueError):
    """The piece is absent or work already started; no mutation/refund happened."""


@dataclass(frozen=True)
class QueueStatus:
    queued: bool = False
    can_cancel: bool = False
    cancelled: bool = False
    estimated_minutes: int | None = None


def estimate_minutes(jobs_ahead: int, free_slots: int, mean_seconds: float) -> int | None:
    """Round an estimate to whole minutes; unknown or unavailable capacity is not a promise."""
    if jobs_ahead < 0 or free_slots <= 0 or not math.isfinite(mean_seconds) or mean_seconds <= 0:
        return None
    seconds = jobs_ahead * mean_seconds / free_slots
    if seconds < 60:
        return 0
    return max(1, math.floor(seconds / 60 + 0.5))


def _load() -> Mapping[str, Any]:
    try:
        import redis  # noqa: PLC0415

        client = redis.Redis.from_url(
            os.environ.get("QUALIFY_REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True,
            socket_connect_timeout=0.25,
            socket_timeout=0.25,
        )
        try:
            raw = client.get(LOAD_KEY)
        finally:
            client.close()
        value = json.loads(raw) if raw else {}
        return value if isinstance(value, dict) else {}
    except Exception:
        # Loss of an estimate never prevents generation or cancellation.
        return {}


def _jobs(session: Any, draft: ContentDraft, *, lock: bool = False) -> list[Any]:
    clause = "FOR UPDATE NOWAIT" if lock else ""
    return list(
        session.execute(
            text(f"""
        SELECT id, kind, status, vendor_task_id, vendor_model, lane, priority, queued_at, not_before
        FROM creative_jobs j WHERE draft_id=:draft AND revision=:revision
          AND (kind<>'final' OR final_attempt=(SELECT max(current.final_attempt)
              FROM creative_jobs current WHERE current.draft_id=j.draft_id
                AND current.revision=j.revision AND current.position=j.position
                AND current.kind='final'))
          AND ((:generation AND kind <> 'final') OR (NOT :generation AND kind='final'))
        ORDER BY id {clause}
    """),
            {
                "draft": draft.id,
                "revision": draft.revision,
                "generation": draft.status == DRAFTING or draft.failure_reason == "cancelled",
            },
        ).mappings()
    )


def _preparing(session: Any, draft: ContentDraft, jobs: list[Any], now: datetime) -> bool:
    if not jobs:
        return False
    return bool(
        session.execute(
            text("""
        SELECT EXISTS (
            SELECT 1 FROM creative_pipeline_runs r
            WHERE r.draft_id=:draft AND r.revision=:revision
              AND ((:generation AND r.phase='generation')
                   OR (NOT :generation AND EXISTS (SELECT 1 FROM image_assets a
                       WHERE a.draft_id=r.draft_id AND r.phase='final:' || a.id::text ||
                       CASE WHEN coalesce((a.params->'draft'->>'final_attempt')::int,0)=0
                       THEN '' ELSE '@' || (a.params->'draft'->>'final_attempt') END)))
              AND (r.lease_until > :now OR EXISTS (
                  SELECT 1 FROM creative_pipeline_steps s
                  WHERE s.tenant_id=r.tenant_id AND s.draft_id=r.draft_id
                    AND s.revision=r.revision AND s.phase=r.phase
                    AND s.error IN ('in_flight', 'submitting', 'submission_uncertain', 'uncertain')
              ))
        )
    """),
            {
                "draft": draft.id,
                "revision": draft.revision,
                "now": now,
                "generation": draft.status == DRAFTING or draft.failure_reason == "cancelled",
            },
        ).scalar_one()
    )


def queue_status(
    *,
    tenant_id: UUID,
    draft_id: UUID,
    now: datetime | None = None,
    load: Mapping[str, Any] | None = None,
) -> QueueStatus:
    at = now or datetime.now(UTC)
    with tenant_session(tenant_id) as session:
        draft = session.get(ContentDraft, draft_id)
        if draft is None:
            return QueueStatus()
        jobs = _jobs(session, draft)
        if not jobs:
            return QueueStatus()
        cancelled = all(row["status"] == "cancelled" for row in jobs)
        queued = all(row["status"] == "queued" and not row["vendor_task_id"] for row in jobs)
        available = queued and not _preparing(session, draft, jobs, at)
    estimates = []
    values = _load() if load is None else load
    for job in jobs if queued else ():
        if job["not_before"] > at:
            continue
        lane = (
            "scheduled"
            if job["lane"] == "nightly"
            else (
                "now"
                if job["priority"] >= 8
                else ("final" if job["kind"] == "final" else "standard")
            )
        )
        group = values.get(job["vendor_model"], {}).get(lane, {})
        if not isinstance(group, dict):
            continue
        # Counts are rounded minute buckets, with no business, piece or job ids.
        minute = int(job["queued_at"].timestamp() // 60)
        buckets = group.get("waiting", {})
        try:
            ahead = sum(int(count) for bucket, count in buckets.items() if int(bucket) < minute)
            estimate = estimate_minutes(ahead, int(group["free"]), float(group["mean_seconds"]))
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
        if estimate is not None:
            estimates.append(estimate)
    return QueueStatus(available, available, cancelled, max(estimates) if estimates else None)


def _cancel_queued(*, tenant_id: UUID, draft_id: UUID, now: datetime | None = None) -> bool:
    """Cancel the whole revision's current phase or nothing, racing safely with claim.

    Locking jobs fences the claim query. A claimed job is rejected even before its
    vendor id is persisted. The same transaction fences preparation and refunds the
    existing ledger entry once; no per-scene new refund records are created.
    """
    at = now or datetime.now(UTC)
    with tenant_session(tenant_id) as session:
        draft = session.get(ContentDraft, draft_id)
        if draft is None:
            raise QueueCancellationUnavailable(CANCEL_NOT_AVAILABLE)
        revision = draft.revision
        generation = draft.status == DRAFTING or draft.failure_reason == "cancelled"
        # Assembly fences its run before locking the draft. Use the same order;
        # NOWAIT turns an active assembly/claim into a safe, retryable refusal.
        phases = list(
            session.execute(
                text("""
            SELECT phase FROM creative_pipeline_runs
            WHERE draft_id=:draft AND revision=:revision
              AND ((:generation AND phase='generation')
                   OR (NOT :generation AND phase LIKE 'final:%'))
            FOR UPDATE NOWAIT
        """),
                {"draft": draft_id, "revision": revision, "generation": generation},
            ).scalars()
        )
        draft = session.scalar(
            select(ContentDraft)
            .where(ContentDraft.id == draft_id)
            .execution_options(populate_existing=True)
            .with_for_update(nowait=True)
        )
        if (
            draft is None
            or draft.revision != revision
            or generation != (draft.status == DRAFTING or draft.failure_reason == "cancelled")
        ):
            raise QueueCancellationUnavailable(CANCEL_NOT_AVAILABLE)
        if not generation:
            from qualify_api.creative.final_retries import final_phase

            current_phases = {
                final_phase(
                    asset.id, int((asset.params.get("draft") or {}).get("final_attempt") or 0)
                )
                for asset in session.scalars(
                    select(ImageAsset).where(ImageAsset.draft_id == draft_id)
                )
                if asset.params and asset.params.get("draft")
            }
            phases = [phase for phase in phases if phase in current_phases]
        jobs = _jobs(session, draft, lock=True)
        if jobs and all(row["status"] == "cancelled" for row in jobs):
            return False
        # Hold the run locks before inspecting leases/intents. Otherwise preparation
        # could acquire a lease between the eligibility read and its invalidation.
        if (
            not jobs
            or any(row["status"] != "queued" or row["vendor_task_id"] for row in jobs)
            or _preparing(session, draft, jobs, at)
        ):
            raise QueueCancellationUnavailable(CANCEL_NOT_AVAILABLE)
        session.execute(
            text("""
            UPDATE creative_pipeline_runs
            SET prepared_version=dirty_version, lease_token=NULL, lease_until=NULL
            WHERE draft_id=:draft AND revision=:revision AND phase=ANY(:phases)
        """),
            {"draft": draft_id, "revision": draft.revision, "phases": phases},
        )
        session.execute(
            text("""
            UPDATE creative_jobs SET status='cancelled', finished_at=:now
            WHERE id=ANY(CAST(:ids AS uuid[]))
        """),
            {"ids": [row["id"] for row in jobs], "now": at},
        )
        if generation:
            draft.status = apply_transition(
                draft.status, DraftTrigger.GENERATE_FAIL, failure_reason="cancelled"
            )
            draft.failure_reason = "cancelled"
            refund_in_session(session, ((draft_id, draft.revision),), "queue_cancelled", at)
        else:
            assets = [UUID(phase.removeprefix("final:").split("@", 1)[0]) for phase in phases]
            for asset in session.scalars(
                select(ImageAsset).where(ImageAsset.id.in_(assets)).with_for_update()
            ):
                params = dict(asset.params or {})
                block = dict(params.get("draft") or {})
                block.update(status="failed", error=CANCELLED_TEXT, failure_reason="cancelled")
                params["draft"] = block
                asset.params = params
            refund_final_in_session(
                session,
                draft_id=draft_id,
                revision=draft.revision,
                reason="queue_cancelled",
                asset_ids=assets,
                now=at,
            )
        return True


def cancel_queued(*, tenant_id: UUID, draft_id: UUID, now: datetime | None = None) -> bool:
    """A racing claim/preparation is unavailable, never a partial refund or a 500."""
    try:
        return _cancel_queued(tenant_id=tenant_id, draft_id=draft_id, now=now)
    except OperationalError as exc:
        if getattr(exc.orig, "sqlstate", None) in {"55P03", "40P01", "40001"}:
            raise QueueCancellationUnavailable(CANCEL_NOT_AVAILABLE) from None
        raise

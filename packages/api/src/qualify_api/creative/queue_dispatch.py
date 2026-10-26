"""Request-side transactional outbox and configuration switch (m-24852166)."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from functools import wraps
from typing import Any
from uuid import UUID

from qualify_creative.enums import ContentKind, SlideSource, VideoEngine
from qualify_shared.db.session import tenant_session, tenant_unit_of_work
from sqlalchemy import text

from qualify_api.creative import job_queue as q

SWITCH = "QUALIFY_CREATIVE_DISPATCHER"
# Preparation makes a job eligible only after its immutable request is stored.
UNPREPARED = datetime(9999, 1, 1, tzinfo=UTC)


class SubmissionUncertain(Exception):
    """A paid submission may be alive: preserve its slot until provider expiry."""


class GenerationDeferred(Exception):
    """Preparation checkpointed a video request; wait for its independent job."""


class CheckpointError(Exception):
    """Infrastructure interrupted preparation; retry from durable checkpoints."""


def queue_enabled() -> bool:
    value = os.environ.get(SWITCH, "inline").strip().lower()
    if value not in {"inline", "queue"}:
        raise ValueError(f"{SWITCH} must be inline or queue")
    return value == "queue"


def transactional_dispatch(method: Callable[..., Any]) -> Callable[..., Any]:
    """Repository mutations, consumption and outbox either all commit or all roll back."""

    @wraps(method)
    def call(self: Any, *args: Any, **kwargs: Any) -> Any:
        if not isinstance(self.dispatcher, QueueDispatcher):
            return method(self, *args, **kwargs)
        with tenant_unit_of_work(kwargs["tenant_id"]):
            return method(self, *args, **kwargs)

    return call


def generation_jobs(brief: Any) -> list[tuple[str, int, str]]:
    if brief.kind is ContentKind.CAROUSEL:
        animated = [
            (q.KIND_CAROUSEL_SCENE, pos, q.SEEDANCE_POOL)
            for pos, slide in enumerate(brief.media.slides)
            if slide.source is SlideSource.ANIMATED
        ]
        if animated:
            return animated
    if brief.kind.is_video and brief.media.video_engine is VideoEngine.OMNIHUMAN:
        return [(q.KIND_PRESENTER, 0, q.OMNIHUMAN_POOL)]
    return [(q.KIND_PREVIEW, 0, q.SEEDANCE_POOL)]


class QueueDispatcher:
    """The same two-UUID contract as InlineDispatcher, with no request threads."""

    supports_deferred_final = True

    def __init__(self, repository: Any, *, pricing_version: str) -> None:
        self.repo = repository
        self.pricing_version = pricing_version

    def dispatch_generation(self, *, tenant_id: UUID, draft_id: UUID) -> None:
        draft = self.repo.get_draft(tenant_id=tenant_id, draft_id=draft_id)
        if draft is None:
            return
        brief = self.repo.get_brief(tenant_id=tenant_id, brief_id=draft.brief_id)
        if brief is None:
            raise ValueError("draft has no brief")
        self._enqueue(tenant_id, draft, "generation", generation_jobs(brief))

    def dispatch_finalize(self, *, tenant_id: UUID, draft_id: UUID) -> None:
        draft = self.repo.get_draft(tenant_id=tenant_id, draft_id=draft_id)
        if draft is None:
            return
        for asset in self.repo.draft_videos_for(tenant_id=tenant_id, draft_id=draft_id):
            block = (asset.params or {}).get("draft") or {}
            if block.get("status") == "rendering":
                self._enqueue(
                    tenant_id,
                    draft,
                    f"final:{asset.id}",
                    [(q.KIND_FINAL, asset.position, q.SEEDANCE_POOL)],
                )

    def _enqueue(
        self, tenant_id: UUID, draft: Any, phase: str, jobs: list[tuple[str, int, str]]
    ) -> None:
        with tenant_session(tenant_id) as session:
            session.execute(
                text("""
                INSERT INTO creative_pipeline_runs
                    (tenant_id, draft_id, revision, phase, pipeline_version)
                VALUES (:t, :d, :r, :p, :v) ON CONFLICT DO NOTHING
            """),
                {
                    "t": tenant_id,
                    "d": draft.id,
                    "r": draft.revision,
                    "p": phase,
                    "v": draft.pipeline_version,
                },
            )
            charge_id = session.execute(
                text(
                    "SELECT id FROM creation_charges WHERE draft_id=:d AND revision=:r "
                    "AND status='charged'"
                ),
                {"d": draft.id, "r": draft.revision},
            ).scalar()
            for kind, position, pool in jobs:
                q.enqueue_job(
                    session,
                    tenant_id=tenant_id,
                    draft_id=draft.id,
                    kind=kind,
                    revision=draft.revision,
                    position=position,
                    vendor_model=pool,
                    lane=q.LANE_IMMEDIATE,
                    not_before=UNPREPARED,
                    charge_id=charge_id,
                    pricing_version=self.pricing_version,
                    pipeline_version=draft.pipeline_version,
                )

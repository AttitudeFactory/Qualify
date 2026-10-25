"""When each vendor task waited in BytePlus's queue and rendered (m-24852158).

The next phases of the generation epic fire on measurements (`docs/escalar-generacion-
concurrencia.md` §5): tasks at once, the wait in BytePlus's queue, the render. This module
stamps them, per task, from the answers the adapters already get while they wait — no
extra vendor call:

- `submitted_at` when the vendor accepts the task (`VendorTaskObserver.created`);
- `running_at` at the first `running` (Seedance) / `generating` (OmniHuman) answer —
  only when this same observation saw the task queued first or created it. A resumed run
  (m-24852154) that finds it already running cannot know since when: the wait stays
  unknown instead of inflated;
- `finished_at` + `final_status` at the first terminal answer, with `finished_late` when
  no live observation saw the task active before (a resumed run finding it ended): the
  time is then an upper bound, kept for «tareas a la vez» and out of the render time.

Every stamp is best effort: a measurement never breaks or slows a generation (errors
are logged and swallowed). The team reads the numbers with
`just creative-queue-report` (`vendor_queue_report`); no owner screen reads them.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert

from qualify_api.creative.models import CreativeVendorTaskTiming

logger = logging.getLogger(__name__)

QUEUED = "queued"
RUNNING = "running"
#: The vendors' words, read as ours. ModelArk: queued / running / succeeded / failed /
#: cancelled / expired. OmniHuman: in_queue / generating / done / not_found / expired /
#: canceled / failed.
_STATUS = {
    "queued": QUEUED,
    "in_queue": QUEUED,
    "running": RUNNING,
    "generating": RUNNING,
    "succeeded": "succeeded",
    "done": "succeeded",
    "failed": "failed",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "expired": "expired",
    "not_found": "not_found",
}
TERMINAL = frozenset({"succeeded", "failed", "cancelled", "expired", "not_found"})


def normalize_status(status: str) -> str:
    """The vendor's status in our words; "" when it says nothing we know."""
    return _STATUS.get((status or "").strip().lower(), "")


def phase_of(slot: str) -> str:
    """`final:<asset id>` is a 1080p final; every other slot is part of the draft."""
    return "final" if slot.startswith("final:") else "draft"


def utcnow() -> datetime:
    return datetime.now(UTC)


@runtime_checkable
class VendorTaskClock(Protocol):
    """Where the stamps go. Every method runs in the task's tenant session."""

    def mark_submitted(
        self,
        *,
        tenant_id: UUID,
        provider: str,
        model_id: str,
        vendor_task_id: str,
        draft_id: UUID | None,
        revision: int | None,
        slot: str,
        pipeline_version: str | None,
        at: datetime,
    ) -> None: ...

    def mark_running(self, *, tenant_id: UUID, vendor_task_id: str, at: datetime) -> None: ...

    def mark_finished(
        self,
        *,
        tenant_id: UUID,
        vendor_task_id: str,
        status: str,
        at: datetime,
        late: bool,
    ) -> None: ...


class PostgresVendorTaskClock:
    """`creative_vendor_task_timings` (0094). Each stamp is written once: a second
    `running` or terminal answer — another poll, another run — changes nothing."""

    def mark_submitted(
        self,
        *,
        tenant_id: UUID,
        provider: str,
        model_id: str,
        vendor_task_id: str,
        draft_id: UUID | None,
        revision: int | None,
        slot: str,
        pipeline_version: str | None,
        at: datetime,
    ) -> None:
        statement = (
            insert(CreativeVendorTaskTiming.__table__)
            .values(
                tenant_id=tenant_id,
                provider=provider,
                model_id=model_id,
                vendor_task_id=vendor_task_id,
                phase=phase_of(slot),
                draft_id=draft_id,
                revision=revision,
                slot=slot,
                pipeline_version=pipeline_version,
                submitted_at=at,
            )
            .on_conflict_do_nothing(constraint="uq_vendor_task_timings_task")
        )
        with tenant_session(tenant_id) as session:
            session.execute(statement)

    def mark_running(self, *, tenant_id: UUID, vendor_task_id: str, at: datetime) -> None:
        table = CreativeVendorTaskTiming
        with tenant_session(tenant_id) as session:
            session.execute(
                update(table)
                .where(
                    table.vendor_task_id == vendor_task_id,
                    table.running_at.is_(None),
                    table.finished_at.is_(None),
                )
                .values(running_at=at, updated_at=utcnow())
            )

    def mark_finished(
        self,
        *,
        tenant_id: UUID,
        vendor_task_id: str,
        status: str,
        at: datetime,
        late: bool,
    ) -> None:
        table = CreativeVendorTaskTiming
        with tenant_session(tenant_id) as session:
            session.execute(
                update(table)
                .where(table.vendor_task_id == vendor_task_id, table.finished_at.is_(None))
                .values(
                    finished_at=at, final_status=status, finished_late=late, updated_at=utcnow()
                )
            )


class TaskWatch:
    """One observation of one slot's task (an adapter's wait, from its creation or from a
    resume): turns the answers it hears into the three stamps. Never raises."""

    def __init__(
        self,
        clock: VendorTaskClock,
        *,
        tenant_id: UUID,
        draft_id: UUID | None,
        revision: int | None,
        slot: str,
        provider: str,
        model_id: str,
        pipeline_version: str | None,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._clock = clock
        self._tenant_id = tenant_id
        self._draft_id = draft_id
        self._revision = revision
        self._slot = slot
        self._provider = provider
        self._model_id = model_id
        self._pipeline_version = pipeline_version
        self._now = now
        self._created = False
        self._seen_queued = False
        self._seen_running = False
        self._running_done = False
        self._finished_done = False

    def created(self, task_id: str) -> None:
        self._created = True
        if not self._provider:
            return  # a resume binding: the task was submitted (and stamped) before
        self._safely(
            "submitted",
            lambda: self._clock.mark_submitted(
                tenant_id=self._tenant_id,
                provider=self._provider,
                model_id=self._model_id,
                vendor_task_id=task_id,
                draft_id=self._draft_id,
                revision=self._revision,
                slot=self._slot,
                pipeline_version=self._pipeline_version,
                at=self._now(),
            ),
        )

    def polled(self, task_id: str, status: str) -> None:
        state = normalize_status(status)
        if state == QUEUED:
            self._seen_queued = True
        elif state == RUNNING:
            if not self._running_done:
                self._running_done = True
                if self._created or self._seen_queued:
                    at = self._now()
                    self._safely(
                        "running",
                        lambda: self._clock.mark_running(
                            tenant_id=self._tenant_id, vendor_task_id=task_id, at=at
                        ),
                    )
            self._seen_running = True
        elif state in TERMINAL and not self._finished_done:
            self._finished_done = True
            late = not (self._created or self._seen_queued or self._seen_running)
            at = self._now()
            self._safely(
                "finished",
                lambda: self._clock.mark_finished(
                    tenant_id=self._tenant_id,
                    vendor_task_id=task_id,
                    status=state,
                    at=at,
                    late=late,
                ),
            )

    def _safely(self, what: str, stamp: Callable[[], None]) -> None:
        try:
            stamp()
        except Exception:  # noqa: BLE001 — a measurement never breaks the generation
            logger.warning("vendor task %s stamp failed (slot %s)", what, self._slot, exc_info=True)

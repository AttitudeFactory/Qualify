"""The vendor tasks a generation created, kept by id (m-24852154).

Seedance is asynchronous: the POST answers a task id and the video comes minutes later.
Until this module, the id lived only in the thread waiting for it. When the wait ran out
(time in BytePlus's own queue used up the 8-minute window) or the thread died with the
process (a deploy), the piece failed — while BytePlus finished the video and BILLED it,
and nobody ever asked for it again.

Now every task is recorded the moment ModelArk accepts it (`creative_vendor_tasks`,
0090), inside the owning tenant's session, with the copy the video was made from
(`context`). A run that stops waiting leaves the draft `drafting` — the owner's piece is
«in progress», not failed, and nothing is refunded. A later run resumes it by id
(`RESUME_TASK_PARAM`): the reaper sweep on the screen's next read re-dispatches it
(`dispatch.claim_waiting_drafts`), it waits for the pending tasks first, then rebuilds
the piece from the same copy — a task that has an id is never submitted again. BytePlus
says `failed`/`expired` → the piece fails and its creations come back (CREAR-5).

`slot` names the call inside the generation: `seedance-N` for the N-th Seedance task of
a run (the pipeline is deterministic for a brief, so a resumed run makes the same calls
in the same order), `final:<asset id>` for a 1080p final.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from qualify_creative.adapters.byteplus_ark import VENDOR_TASK_EXPIRY_SECONDS
from qualify_creative.providers import VendorTaskObserver
from qualify_shared.db.session import tenant_session
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from qualify_api.creative.models import CreativeVendorTask

logger = logging.getLogger(__name__)

PENDING = "pending"
SUCCEEDED = "succeeded"
FAILED = "failed"
#: A pending task older than this is given up: BytePlus has expired it by then (48 h,
#: `execution_expires_after`'s default) plus a margin — the reaper fails the piece.
GIVE_UP_AFTER = timedelta(seconds=VENDOR_TASK_EXPIRY_SECONDS) + timedelta(hours=1)
#: The owner sees «tu video está en fila» once a task has waited past the window the
#: thread used to give it (8 min) — before that, the usual progress bar.
WAITING_NOTE_AFTER = timedelta(minutes=8)
#: A sign of life at most this often while a thread polls (a poll every 5 s).
_BEAT_EVERY_SECONDS = 60.0


@dataclass(frozen=True)
class VendorTaskRecord:
    slot: str
    vendor_task_id: str
    provider: str
    model_id: str
    status: str
    context: Mapping[str, Any]
    created_at: datetime | None = None


class VendorTaskStore(Protocol):
    """Where the tasks live. Every method runs in the draft's tenant session."""

    def record(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        revision: int,
        slot: str,
        provider: str,
        model_id: str,
        vendor_task_id: str,
        pipeline_version: str | None,
        context: Mapping[str, Any],
    ) -> None:
        """Insert the task; a slot whose earlier task FAILED takes the new one (a retried
        final). A slot already holding a live task is left as it is."""
        ...

    def tasks(
        self, *, tenant_id: UUID, draft_id: UUID, revision: int
    ) -> tuple[VendorTaskRecord, ...]: ...

    def settle(
        self, *, tenant_id: UUID, draft_id: UUID, revision: int, slot: str, status: str
    ) -> None:
        """Turn a pending slot `succeeded` or `failed` (once; a settled one stays)."""
        ...

    def waiting(self, *, tenant_id: UUID, draft_ids: Sequence[UUID]) -> frozenset[UUID]:
        """The drafts, of these, still `drafting` with a task pending past
        `WAITING_NOTE_AFTER` on their current revision."""
        ...


class PostgresVendorTaskStore:
    def record(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        revision: int,
        slot: str,
        provider: str,
        model_id: str,
        vendor_task_id: str,
        pipeline_version: str | None,
        context: Mapping[str, Any],
    ) -> None:
        table = CreativeVendorTask.__table__
        statement = insert(table).values(
            tenant_id=tenant_id,
            draft_id=draft_id,
            revision=revision,
            slot=slot,
            provider=provider,
            model_id=model_id,
            vendor_task_id=vendor_task_id,
            pipeline_version=pipeline_version,
            context=dict(context),
        )
        now = datetime.now(UTC)
        statement = statement.on_conflict_do_update(
            constraint="uq_creative_vendor_tasks_slot",
            set_={
                "vendor_task_id": statement.excluded.vendor_task_id,
                "provider": statement.excluded.provider,
                "model_id": statement.excluded.model_id,
                "context": statement.excluded.context,
                "status": PENDING,
                "settled_at": None,
                "created_at": now,
                "updated_at": now,
            },
            where=table.c.status == FAILED,
        )
        with tenant_session(tenant_id) as session:
            session.execute(statement)

    def tasks(
        self, *, tenant_id: UUID, draft_id: UUID, revision: int
    ) -> tuple[VendorTaskRecord, ...]:
        with tenant_session(tenant_id) as session:
            rows = session.scalars(
                select(CreativeVendorTask)
                .where(
                    CreativeVendorTask.draft_id == draft_id,
                    CreativeVendorTask.revision == revision,
                )
                .order_by(CreativeVendorTask.created_at)
            ).all()
            return tuple(
                VendorTaskRecord(
                    slot=row.slot,
                    vendor_task_id=row.vendor_task_id,
                    provider=row.provider,
                    model_id=row.model_id,
                    status=row.status,
                    context=dict(row.context or {}),
                    created_at=row.created_at,
                )
                for row in rows
            )

    def settle(
        self, *, tenant_id: UUID, draft_id: UUID, revision: int, slot: str, status: str
    ) -> None:
        now = datetime.now(UTC)
        with tenant_session(tenant_id) as session:
            session.execute(
                update(CreativeVendorTask)
                .where(
                    CreativeVendorTask.draft_id == draft_id,
                    CreativeVendorTask.revision == revision,
                    CreativeVendorTask.slot == slot,
                    CreativeVendorTask.status == PENDING,
                )
                .values(status=status, settled_at=now, updated_at=now)
            )

    def waiting(self, *, tenant_id: UUID, draft_ids: Sequence[UUID]) -> frozenset[UUID]:
        if not draft_ids:
            return frozenset()
        from qualify_api.creative.fsm import DRAFTING
        from qualify_api.creative.models import ContentDraft

        cutoff = datetime.now(UTC) - WAITING_NOTE_AFTER
        with tenant_session(tenant_id) as session:
            ids = session.scalars(
                select(CreativeVendorTask.draft_id)
                .join(ContentDraft, ContentDraft.id == CreativeVendorTask.draft_id)
                .where(
                    CreativeVendorTask.draft_id.in_(list(draft_ids)),
                    CreativeVendorTask.status == PENDING,
                    CreativeVendorTask.revision == ContentDraft.revision,
                    CreativeVendorTask.created_at < cutoff,
                    ContentDraft.status == DRAFTING,
                )
            ).all()
            return frozenset(ids)


# -- what a run hands the media producer --------------------------------------------------


class VendorTaskBinding(Protocol):
    """One run's view of its tasks, for `MediaProducer`: which id to resume for a slot,
    the observer that records a new one, and the settlement of a slot."""

    def resume_id(self, slot: str) -> str | None: ...

    def observer(self, slot: str, provider: str, model_id: str) -> VendorTaskObserver: ...

    def settle(self, slot: str, status: str) -> None: ...


class _Observer:
    def __init__(
        self,
        record: Callable[[str], None],
        beat: Callable[[], None] | None,
    ) -> None:
        self._record = record
        self._beat = beat
        self._last_beat = 0.0

    def created(self, task_id: str) -> None:
        self._record(task_id)
        self._pulse(force=True)

    def polled(self, task_id: str, status: str) -> None:
        self._pulse(force=False)

    def _pulse(self, *, force: bool) -> None:
        if self._beat is None:
            return
        now = time.monotonic()
        if not force and now - self._last_beat < _BEAT_EVERY_SECONDS:
            return
        self._last_beat = now
        try:
            self._beat()
        except Exception:  # noqa: BLE001 — a sign of life never breaks the wait
            logger.warning("vendor task heartbeat failed", exc_info=True)


class DraftVendorTasks:
    """A generation run's binding: `seedance-N` slots of (draft, revision). Records each
    new task with the run's copy snapshot (`context`), stamps the draft's heartbeat
    while a thread polls, and resumes any task of this revision not failed."""

    def __init__(
        self,
        store: VendorTaskStore,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        revision: int,
        pipeline_version: str | None,
        context: Mapping[str, Any],
        heartbeat: Callable[[], None] | None,
        existing: Sequence[VendorTaskRecord] = (),
    ) -> None:
        self._store = store
        self._tenant_id = tenant_id
        self._draft_id = draft_id
        self._revision = revision
        self._pipeline_version = pipeline_version
        self._context = dict(context)
        self._heartbeat = heartbeat
        self._known = {t.slot: t.vendor_task_id for t in existing if t.status != FAILED}

    def resume_id(self, slot: str) -> str | None:
        return self._known.get(slot)

    def observer(self, slot: str, provider: str, model_id: str) -> VendorTaskObserver:
        def record(task_id: str) -> None:
            self._known[slot] = task_id
            self._store.record(
                tenant_id=self._tenant_id,
                draft_id=self._draft_id,
                revision=self._revision,
                slot=slot,
                provider=provider,
                model_id=model_id,
                vendor_task_id=task_id,
                pipeline_version=self._pipeline_version,
                context=self._context,
            )

        return _Observer(record, self._heartbeat)

    def observer_for_wait(self, slot: str) -> VendorTaskObserver:
        """While a resumed run waits for a task it already has: only the heartbeat (a
        resumed task is never created, so nothing is recorded)."""
        return self.observer(slot, "", "")

    def settle(self, slot: str, status: str) -> None:
        try:
            self._store.settle(
                tenant_id=self._tenant_id,
                draft_id=self._draft_id,
                revision=self._revision,
                slot=slot,
                status=status,
            )
        except Exception:  # noqa: BLE001 — the row stays pending; the piece goes on
            logger.warning("draft %s: task %s not settled", self._draft_id, slot, exc_info=True)


class FinalVendorTasks(DraftVendorTasks):
    """A 1080p final's binding: whatever slot the producer names, the task is the
    final of THIS asset (`final:<asset id>`) — a retried final resumes the task of the
    earlier order instead of paying for another one. While a thread polls it, the
    final's `rendering_at` is kept fresh (`heartbeat`), so the screen does not call a
    final still being made «a medias»."""

    def __init__(
        self,
        store: VendorTaskStore,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        revision: int,
        asset_id: UUID,
        heartbeat: Callable[[], None] | None,
        existing: Sequence[VendorTaskRecord] = (),
    ) -> None:
        self.slot = final_slot(asset_id)
        super().__init__(
            store,
            tenant_id=tenant_id,
            draft_id=draft_id,
            revision=revision,
            pipeline_version=None,
            context={},
            heartbeat=heartbeat,
            existing=[t for t in existing if t.slot == self.slot],
        )

    def resume_id(self, slot: str) -> str | None:
        return super().resume_id(self.slot)

    def observer(self, slot: str, provider: str, model_id: str) -> VendorTaskObserver:
        return super().observer(self.slot, provider, model_id)

    def settle(self, slot: str, status: str) -> None:
        super().settle(self.slot, status)


def final_slot(asset_id: UUID) -> str:
    return f"final:{asset_id}"


# -- the copy a resumed run reuses ---------------------------------------------------------


def snapshot(variants: Sequence[Any], usage: Sequence[Any], spent: Decimal) -> dict[str, Any]:
    """The run's copy as JSON: the variants (`VariantWrite`) and the copy's own spend
    (`UsageWrite`, recorded once, when the piece settles)."""
    return {
        "variants": [
            {
                "ordinal": v.ordinal,
                "copy": dict(v.copy),
                "fidelity": dict(v.fidelity),
                "model_id": v.model_id,
                "model_revision": v.model_revision,
            }
            for v in variants
        ],
        "copy_usage": [
            {
                "provider": u.provider,
                "model_id": u.model_id,
                "unit": u.unit,
                "input_tokens": u.input_tokens,
                "output_tokens": u.output_tokens,
                "cache_read_tokens": u.cache_read_tokens,
                "cache_creation_tokens": u.cache_creation_tokens,
                "cost_usd": str(u.cost_usd),
                "paid_by": u.paid_by,
                "pricing_table_version": u.pricing_table_version,
                "pieces": u.pieces,
            }
            for u in usage
        ],
        "copy_spent_usd": str(spent),
    }


def resumable(tasks: Sequence[VendorTaskRecord]) -> bool:
    """A run of this revision left a task still pending, with the copy to rebuild on."""
    return any(t.status == PENDING for t in tasks) and any(
        isinstance(t.context.get("variants"), list) and t.context["variants"] for t in tasks
    )


def context_of(tasks: Sequence[VendorTaskRecord]) -> Mapping[str, Any]:
    for task in tasks:
        if isinstance(task.context.get("variants"), list) and task.context["variants"]:
            return task.context
    return {}

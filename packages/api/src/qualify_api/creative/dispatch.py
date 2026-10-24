"""How generation work leaves the request — and how stuck work gets swept up (§7.4).

Two seams live here, and both exist to make the in-process MVP honest about its own
failure mode:

- ``TaskDispatcher`` is the ONE place that knows how ``run_generation`` gets invoked
  (D6, design §7.4). ``InlineDispatcher`` runs it in this process, in a daemon thread;
  the future ``CeleryDispatcher`` is ``run_generation.delay(str(tenant_id),
  str(draft_id))`` and nothing else changes — the two-UUID keyword signature of
  ``dispatch_generation`` IS the Celery task signature, which is why it takes ids, never
  objects. Nothing outside the dispatcher may call ``run_generation`` out of band.

- ``reap_stale_drafts`` is the reaper, and per §7.4 it is part of the MVP, not the
  future: an ``InlineDispatcher`` thread dies with the process (deploy, crash), and
  without the reaper the draft it was working on stays ``DRAFTING`` forever behind an
  eternal spinner. Every ``DRAFTING`` draft whose LAST SIGN OF LIFE is older than the
  threshold goes to ``FAILED`` with ``failure_reason='timeout'`` through the FSM's
  ``reap`` edge. It runs on listing (``ContentService.list_drafts``) — a query, not a
  service.

The sign of life (m-24852156) is ``content_drafts.updated_at``: stamped when the draft
enters ``DRAFTING`` (insert, «Pedir otra versión») and by ``record_progress`` every time
the run keeps a file (each carousel slide, each clip). A ten-slide animated carousel
takes ~20 min because its slides run one after another; measured from ``created_at`` it
was reaped while alive and still being paid for. A dead thread stops stamping, so the
reaper still catches it the same 20 min after its last progress. The future queue's
``started_at`` (Fase 1) replaces the entry stamp, not this rule.
"""

from __future__ import annotations

import logging
import math
import threading
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from qualify_creative.adapters.byteplus_omnihuman import (
    DEFAULT_POLL_TIMEOUT_SECONDS as OMNIHUMAN_POLL_TIMEOUT_SECONDS,
)
from qualify_shared.db.session import tenant_session
from sqlalchemy import select, update

from qualify_api.creative.creations import refund_in_session
from qualify_api.creative.fsm import (
    DRAFTING,
    REAP_FAILURE_REASON,
    DraftTrigger,
    apply_transition,
)
from qualify_api.creative.models import ContentBrief, ContentDraft

logger = logging.getLogger(__name__)

#: §7.4 minimal implementation: a generation round trip is 15-60s and a carousel slide
#: ~2 min, so twenty minutes in ``DRAFTING`` WITHOUT PROGRESS means the worker is dead,
#: not slow (m-24852156: measured from the last progress, not from the start).
DEFAULT_REAP_AFTER_MINUTES = 20
#: A talking presenter is the one slow round trip (§ 2026-10-16): OmniHuman renders at
#: ~25x real time, so a one-minute script takes ~25 min and the adapter waits up to its
#: poll window. Its draft is reaped only after that window plus the presenter frame and
#: the voice (a margin of 10 min) — before, the reaper failed a render still being paid.
OMNIHUMAN_REAP_AFTER_MINUTES = math.ceil(OMNIHUMAN_POLL_TIMEOUT_SECONDS / 60) + 10


class GenerationRunner(Protocol):
    """The callable an ``InlineDispatcher`` invokes — ``ContentService.run_generation``
    in production, a recorder in tests."""

    def __call__(self, *, tenant_id: UUID, draft_id: UUID) -> None: ...


class TaskDispatcher(Protocol):
    """The one place that knows HOW work leaves the request. Swapping the
    implementation is the entire Celery migration (design §7.4)."""

    def dispatch_generation(self, *, tenant_id: UUID, draft_id: UUID) -> None: ...

    def dispatch_finalize(self, *, tenant_id: UUID, draft_id: UUID) -> None:
        """The finals of a draft's approved 480p drafts (m-24820142) —
        `ContentService.run_finalize`, the same two-UUID shape."""
        ...


class InlineDispatcher:
    """MVP dispatcher (D6): runs the generation callable in a daemon thread of THIS
    process. It dies with the process — hence the reaper below. The thread target
    receives exactly ``(tenant_id, draft_id)`` as keywords, the same two serializable
    UUIDs a ``CeleryDispatcher`` would put on the wire, so migrating means swapping this
    class and nothing else (§7.4's four-property contract)."""

    def __init__(self, run: GenerationRunner, finalize: GenerationRunner | None = None) -> None:
        self._run = run
        self._finalize = finalize

    def dispatch_generation(self, *, tenant_id: UUID, draft_id: UUID) -> None:
        self._start(self._run, "creative-generation", tenant_id, draft_id)

    def dispatch_finalize(self, *, tenant_id: UUID, draft_id: UUID) -> None:
        if self._finalize is None:
            raise RuntimeError("this dispatcher was wired without a finalize runner")
        self._start(self._finalize, "creative-final", tenant_id, draft_id)

    @staticmethod
    def _start(target: GenerationRunner, name: str, tenant_id: UUID, draft_id: UUID) -> None:
        thread = threading.Thread(
            target=target,
            kwargs={"tenant_id": tenant_id, "draft_id": draft_id},
            name=f"{name}-{draft_id}",
            daemon=True,
        )
        thread.start()


def record_progress(*, tenant_id: UUID, draft_id: UUID) -> None:
    """The run's heartbeat (m-24852156): stamp ``updated_at`` of a draft still
    ``DRAFTING`` — inside the owning tenant's session, so RLS keeps it to that business.
    A draft past ``DRAFTING`` (reaped, finished) is left alone. Never a reason to break
    the run: a stamp that cannot be written is logged and the run goes on."""
    try:
        with tenant_session(tenant_id) as session:
            session.execute(
                update(ContentDraft)
                .where(ContentDraft.id == draft_id, ContentDraft.status == DRAFTING)
                .values(updated_at=datetime.now(UTC))
            )
    except Exception:
        logger.warning("draft %s: progress stamp not written", draft_id, exc_info=True)


def reap_stale_drafts(
    *, tenant_id: UUID, older_than_minutes: int = DEFAULT_REAP_AFTER_MINUTES
) -> int:
    """Fail every ``DRAFTING`` draft with no progress for longer than the threshold
    (``updated_at``, see the module docstring); return how many flipped.

    The status write goes through ``apply_transition`` (the ``reap`` edge — no status
    mutation outside the FSM), and the reason is forced to ``timeout``, never
    caller-supplied. Safe to run repeatedly and concurrently with ``run_generation``:
    a draft the reaper already failed makes the runner's idempotency check a no-op, and
    a draft the runner already finished is no longer ``DRAFTING`` so the reaper skips it.
    """
    now = datetime.now(UTC)
    cutoff = now - timedelta(minutes=older_than_minutes)
    presenter_cutoff = now - timedelta(
        minutes=max(older_than_minutes, OMNIHUMAN_REAP_AFTER_MINUTES)
    )
    with tenant_session(tenant_id) as session:
        rows = session.execute(
            select(ContentDraft, ContentBrief.media)
            .join(ContentBrief, ContentBrief.id == ContentDraft.brief_id)
            .where(
                ContentDraft.status == DRAFTING,
                ContentDraft.updated_at < cutoff,
            )
        ).all()
        stale = [
            draft
            for draft, media in rows
            if not (
                isinstance(media, dict)
                and media.get("video_engine") == "omnihuman"
                and draft.updated_at >= presenter_cutoff
            )
        ]
        for draft in stale:
            draft.status = apply_transition(draft.status, DraftTrigger.REAP)
            draft.failure_reason = REAP_FAILURE_REASON
        # CREAR-5: a reaped generation gives its creations back, in the same transaction
        if stale:
            refund_in_session(
                session, ((draft.id, draft.revision) for draft in stale), REAP_FAILURE_REASON, now
            )
        return len(stale)

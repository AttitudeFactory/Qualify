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
  eternal spinner. Every ``DRAFTING`` draft older than the threshold goes to ``FAILED``
  with ``failure_reason='timeout'`` through the FSM's ``reap`` edge. It runs on listing
  (``ContentService.list_drafts``) — a query, not a service.
"""

from __future__ import annotations

import math
import threading
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from qualify_creative.adapters.byteplus_omnihuman import (
    DEFAULT_POLL_TIMEOUT_SECONDS as OMNIHUMAN_POLL_TIMEOUT_SECONDS,
)
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.creative.creations import refund_in_session
from qualify_api.creative.fsm import (
    DRAFTING,
    REAP_FAILURE_REASON,
    DraftTrigger,
    apply_transition,
)
from qualify_api.creative.models import ContentBrief, ContentDraft

#: §7.4 minimal implementation: a generation round trip is 15-60s, so ten minutes in
#: ``DRAFTING`` means the worker is dead, not slow.
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


class InlineDispatcher:
    """MVP dispatcher (D6): runs the generation callable in a daemon thread of THIS
    process. It dies with the process — hence the reaper below. The thread target
    receives exactly ``(tenant_id, draft_id)`` as keywords, the same two serializable
    UUIDs a ``CeleryDispatcher`` would put on the wire, so migrating means swapping this
    class and nothing else (§7.4's four-property contract)."""

    def __init__(self, run: GenerationRunner) -> None:
        self._run = run

    def dispatch_generation(self, *, tenant_id: UUID, draft_id: UUID) -> None:
        thread = threading.Thread(
            target=self._run,
            kwargs={"tenant_id": tenant_id, "draft_id": draft_id},
            name=f"creative-generation-{draft_id}",
            daemon=True,
        )
        thread.start()


def reap_stale_drafts(
    *, tenant_id: UUID, older_than_minutes: int = DEFAULT_REAP_AFTER_MINUTES
) -> int:
    """Fail every ``DRAFTING`` draft older than the threshold; return how many flipped.

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
                ContentDraft.created_at < cutoff,
            )
        ).all()
        stale = [
            draft
            for draft, media in rows
            if not (
                isinstance(media, dict)
                and media.get("video_engine") == "omnihuman"
                and draft.created_at >= presenter_cutoff
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

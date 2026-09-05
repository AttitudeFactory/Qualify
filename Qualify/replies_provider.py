"""The seam between `/inbox`'s assisted-reply panel and the real replies backend
(QUA-22, comments tranche only). Same split `publishing_provider.py` establishes for
its own Meta-writing calls: direct in-process projections over `qualify_api.replies`'s
published seam (`generate_drafts`/`list_pending_drafts`/`decide_draft`/`send_draft`) —
no HTTP hop, same posture `http/app.py`'s own module docstring documents for the
Reflex CRM in general. `send_draft` is the one function here that calls Meta and is
therefore `async def`, same reason `publishing_provider.start_publish` is.

**The DM tranche does not exist anywhere in this file.** `qualify_api.replies` only
ever produces comment-channel drafts (gated by `qualify_api.replies.gate`, comments
only) — there is no code path here that could show a DM draft even by accident.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from qualify_api.replies import decide_draft as _decide_draft
from qualify_api.replies import generate_drafts as _generate_drafts
from qualify_api.replies import list_pending_drafts as _list_pending_drafts
from qualify_api.replies import send_draft as _send_draft
from qualify_api.replies.repository import DraftRecord
from qualify_api.replies.service import UnknownDraft

__all__ = [
    "DraftVM",
    "GenerationSummaryVM",
    "UnknownDraft",
    "decide_draft",
    "generate_drafts",
    "pending_drafts",
    "send_draft",
]


@dataclass(frozen=True)
class DraftVM:
    """Display-ready projection of one `DraftRecord` — exactly the fields the reply
    panel renders. `final_text` is `""` (never a Python `None`) so the Reflex text
    area always has a plain string to bind to, same convention `CommentVM.text`
    already follows for a possibly-absent comment body."""

    id: str
    source_id: str
    sentiment_label: str
    comment_text: str
    generated_text: str
    final_text: str
    status: str
    created_at: str


@dataclass(frozen=True)
class GenerationSummaryVM:
    candidates_seen: int
    drafts_created: int
    gate_rejected: int


def _to_vm(record: DraftRecord) -> DraftVM:
    return DraftVM(
        id=str(record.id),
        source_id=record.source_id,
        sentiment_label=record.sentiment_label,
        comment_text=record.comment_text,
        generated_text=record.generated_text,
        final_text=record.final_text or "",
        status=record.status,
        created_at=record.created_at.strftime("%d %b %Y, %H:%M"),
    )


def pending_drafts(*, tenant_id: UUID, connection_id: UUID) -> list[DraftVM]:
    """The review queue: `status == 'proposed'` only. Blocking DB call — callers on
    the event loop must run it off-thread, same convention `inbox_provider`'s
    synchronous read seams already establish."""
    return [
        _to_vm(d) for d in _list_pending_drafts(tenant_id=tenant_id, connection_id=connection_id)
    ]


def generate_drafts(*, tenant_id: UUID, connection_id: UUID) -> GenerationSummaryVM:
    """Runs the gate + generator over every pending POS comment without a draft yet.
    Blocking (the generator call is a synchronous HF Inference request) — callers on
    the event loop must run it off-thread. Idempotent: a comment that already has a
    draft is silently skipped, never re-generated (see `qualify_api.replies`'s module
    docstring)."""
    summary = _generate_drafts(tenant_id=tenant_id, connection_id=connection_id)
    return GenerationSummaryVM(
        candidates_seen=summary.candidates_seen,
        drafts_created=summary.drafts_created,
        gate_rejected=summary.gate_rejected,
    )


def decide_draft(
    *,
    tenant_id: UUID,
    draft_id: UUID,
    decision: str,
    final_text: str | None,
    decided_by_user_id: UUID,
) -> DraftVM:
    """`decision` in `('accepted', 'edited', 'discarded')` — QUA-22's own criterion:
    every draft records which of the three a human chose. Blocking DB call. Raises
    `ValueError` if the draft is not `'proposed'` (already decided)."""
    result = _decide_draft(
        tenant_id=tenant_id,
        draft_id=draft_id,
        decision=decision,
        final_text=final_text,
        decided_by_user_id=decided_by_user_id,
    )
    return _to_vm(result.draft)


async def send_draft(*, tenant_id: UUID, draft_id: UUID) -> DraftVM:
    """The real write to Meta — `async def`, same posture `publishing_provider.
    start_publish` has for its own Meta call. Only reachable for an
    `'accepted'`/`'edited'` draft; raises `ValueError` otherwise and `UnknownDraft` if
    the id is not visible to this tenant — both propagate, same "typed exception,
    never swallowed" discipline `inbox_provider.toggle_monitoring` documents for its
    own service."""
    record = await _send_draft(tenant_id=tenant_id, draft_id=draft_id)
    return _to_vm(record)

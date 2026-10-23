"""The seam between `/inbox`'s assisted-reply panel and the real replies backend
(QUA-22, comments tranche only). Same split `publishing_provider.py` establishes for
its own Meta-writing calls: direct in-process projections over `qualify_api.replies`'s
published seam (`generate_drafts`/`list_pending_drafts`/`decide_draft`/`send_draft`,
and since m-24789645 `regenerate_draft`) —
no HTTP hop, same posture `http/app.py`'s own module docstring documents for the
Reflex CRM in general. `send_draft` is the one function here that calls Meta and is
therefore `async def`, same reason `publishing_provider.start_publish` is — and it
requires a `HumanApproval` naming the draft (m-24789645), built by the caller from the
logged-in person (`acting_user`, resolved from the session email the same way
Conversaciones does).

The display rules (sources, «Requiere revisión», intent chips, the review gate) live in
`replies_vm.py`, pure and tested; `DraftVM` is re-exported from there.

**The DM tranche does not exist anywhere in this file.** `qualify_api.replies` only
ever produces comment-channel drafts (gated by `qualify_api.replies.gate`, comments
only) — there is no code path here that could show a DM draft even by accident.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from qualify_api.assisted.approval import HumanApproval
from qualify_api.intent import (
    CURRENT_INTENT_VERSION,
    IntentClass,
    IntentSignal,
    class_reliability,
)
from qualify_api.intent import current_signals as _current_signals
from qualify_api.replies import decide_draft as _decide_draft
from qualify_api.replies import generate_drafts as _generate_drafts
from qualify_api.replies import list_pending_drafts as _list_pending_drafts
from qualify_api.replies import regenerate_draft as _regenerate_draft
from qualify_api.replies import send_draft as _send_draft
from qualify_api.replies.repository import DraftRecord
from qualify_api.replies.service import RegenerationRefused, UnknownDraft

from .conversations_provider import gateway as conversations_gateway
from .inbox_provider import tenant_zone
from .inbox_vm import CandidateMediaVM
from .replies_vm import PUBLICATION_ALT_FALLBACK, DraftVM, build_draft_vm

__all__ = [
    "DraftVM",
    "GenerationSummaryVM",
    "PUBLICATION_ALT_FALLBACK",
    "RegenerationRefused",
    "UnknownDraft",
    "acting_user",
    "approval_for",
    "decide_draft",
    "generate_drafts",
    "pending_drafts",
    "regenerate_draft",
    "send_draft",
]


@dataclass(frozen=True)
class GenerationSummaryVM:
    candidates_seen: int
    drafts_created: int
    gate_rejected: int


def _tenant_zone(tenant_id: UUID) -> ZoneInfo:
    """The business's zone for dates on the card — `inbox_provider.tenant_zone`
    (m-24842988), the same clock the rest of the screen uses; UTC if unreadable."""
    return tenant_zone(tenant_id)


def _to_vm(record: DraftRecord, *, zone: ZoneInfo | None = None) -> DraftVM:
    """A single record, without intent chips — for the decision/send returns, whose
    result the state never renders (it re-reads the queue)."""
    return build_draft_vm(record, zone=zone or ZoneInfo("UTC"))


def build_queue(
    records: Sequence[DraftRecord],
    *,
    zone: ZoneInfo,
    signals: Mapping[UUID, IntentSignal] | None = None,
    reliable: Mapping[IntentClass, bool] | None = None,
    candidates: Iterable[CandidateMediaVM] = (),
) -> list[DraftVM]:
    """The review queue as VMs. A commercial draft (it carries a grounding record) gets
    its comment's current intent chips; a sentiment-era draft gets none.

    m-24842989: `candidates` is the inbox's ALREADY-loaded candidate list — the only
    source of a publication picture, since the inbox stores none (Meta's URLs expire).
    Same cross-reference `inbox_provider._to_reel_summary_vm` does for the Reel cards:
    zero new queries, zero new Meta calls. A publication outside the 2-week list gets
    no thumbnail."""
    signals = signals or {}
    by_media_id = {c.external_media_id: c for c in candidates}
    return [
        build_draft_vm(
            r,
            zone=zone,
            signal=signals.get(r.message_id) if r.grounding is not None else None,
            reliable=reliable or {},
            media=by_media_id.get(r.external_media_id),
        )
        for r in records
    ]


def pending_drafts(
    *,
    tenant_id: UUID,
    connection_id: UUID,
    candidates: Iterable[CandidateMediaVM] = (),
) -> list[DraftVM]:
    """The review queue: `status == 'proposed'` only. Blocking DB reads — callers on
    the event loop must run it off-thread, same convention `inbox_provider`'s
    synchronous read seams already establish. `candidates` is `InboxState.candidates`
    (already loaded) — the drafts' thumbnails come from there, see `build_queue`.

    For the commercial drafts (m-24789645) one extra read: the comments' intent signals
    under `CURRENT_INTENT_VERSION` and the per-class reliability, the same pair the
    comment list uses for its chips."""
    records = _list_pending_drafts(tenant_id=tenant_id, connection_id=connection_id)
    if not records:
        return []
    commercial = [r.message_id for r in records if r.grounding is not None]
    signals = _current_signals(tenant_id=tenant_id, message_ids=commercial) if commercial else {}
    reliable = class_reliability(CURRENT_INTENT_VERSION.detector_version) if signals else {}
    return build_queue(
        records,
        zone=_tenant_zone(tenant_id),
        signals=signals,
        reliable=reliable,
        candidates=candidates,
    )


def regenerate_draft(*, tenant_id: UUID, draft_id: UUID, user_id: UUID) -> str:
    """«Regenerar» (m-24789645): replaces a `proposed` draft with a fresh one, through
    the gate, as `user_id` (the logged-in person). Never sends. Blocking (it may call
    the generator) — run it off-thread. Returns the id of the comment's live draft.
    Raises `UnknownDraft`, `ValueError` (not `proposed`) or `RegenerationRefused`."""
    record = _regenerate_draft(tenant_id=tenant_id, draft_id=draft_id, user_id=user_id)
    return str(record.id)


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


def acting_user(tenant_id: UUID, email: str) -> UUID | None:
    """The logged-in person's `users.id` in this tenant (by session email), or None —
    the same resolution Conversaciones and Seguimientos use. Blocking DB call."""
    return conversations_gateway().acting_user(tenant_id, email)


def approval_for(*, user_id: UUID, draft_id: UUID) -> HumanApproval:
    """The approval a click on «Enviar» gives: this person, now, this draft."""
    return HumanApproval(user_id=user_id, approved_at=datetime.now(UTC), draft_id=draft_id)


async def send_draft(*, tenant_id: UUID, draft_id: UUID, approval: HumanApproval) -> DraftVM:
    """The real write to Meta — `async def`, same posture `publishing_provider.
    start_publish` has for its own Meta call. Only reachable for an
    `'accepted'`/`'edited'` draft; raises `ValueError` otherwise and `UnknownDraft` if
    the id is not visible to this tenant — both propagate, same "typed exception,
    never swallowed" discipline `inbox_provider.toggle_monitoring` documents for its
    own service. Raises `ApprovalRequired` without an approval naming this draft."""
    record = await _send_draft(tenant_id=tenant_id, draft_id=draft_id, approval=approval)
    return _to_vm(record)

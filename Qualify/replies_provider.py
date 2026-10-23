"""The seam between `/inbox`'s assisted-reply panel and the real replies backend
(QUA-22, comments tranche only). Same split `publishing_provider.py` establishes for
its own Meta-writing calls: direct in-process projections over `qualify_api.replies`'s
published seam (`generate_drafts`/`list_pending_drafts`/`decide_draft`/`send_draft`) —
no HTTP hop, same posture `http/app.py`'s own module docstring documents for the
Reflex CRM in general. `send_draft` is the one function here that calls Meta and is
therefore `async def`, same reason `publishing_provider.start_publish` is — and it
requires a `HumanApproval` naming the draft (m-24789645), built by the caller from the
logged-in person (`acting_user`, resolved from the session email the same way
Conversaciones does).

**The DM tranche does not exist anywhere in this file.** `qualify_api.replies` only
ever produces comment-channel drafts (gated by `qualify_api.replies.gate`, comments
only) — there is no code path here that could show a DM draft even by accident.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from qualify_api.assisted.approval import HumanApproval
from qualify_api.replies import decide_draft as _decide_draft
from qualify_api.replies import generate_drafts as _generate_drafts
from qualify_api.replies import list_pending_drafts as _list_pending_drafts
from qualify_api.replies import send_draft as _send_draft
from qualify_api.replies.repository import DraftRecord
from qualify_api.replies.service import UnknownDraft

from .conversations_provider import gateway as conversations_gateway
from .inbox_vm import CandidateMediaVM, short_day_label
from .planner_vm import time_label_12h

# m-24842989: the thumbnail's alt text when the publication has no caption we know of.
PUBLICATION_ALT_FALLBACK = "Publicación"

__all__ = [
    "DraftVM",
    "GenerationSummaryVM",
    "UnknownDraft",
    "acting_user",
    "approval_for",
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
    # m-24842989: who wrote the comment (`""` when the channel did not say) and the
    # publication it was left on — its picture (`""` shows the generic frame) and the
    # picture's alt text (the caption, else «Publicación»; never empty).
    author_username: str = ""
    media_thumbnail_url: str = ""
    media_alt: str = PUBLICATION_ALT_FALLBACK
    # m-24842988: the day the publication went up («21 oct»), for «En tu publicación
    # del 21 oct». `""` when the publication is outside the loaded 2-week list.
    media_day: str = ""


@dataclass(frozen=True)
class GenerationSummaryVM:
    candidates_seen: int
    drafts_created: int
    gate_rejected: int


def moment_label(moment: datetime, zone: ZoneInfo) -> str:
    """«23 oct, 2:05 p. m.» — Spanish short month and 12-hour time in the business's
    zone (m-24842988), the same clock the Planificador shows."""
    local = moment.astimezone(zone)
    return f"{short_day_label(local)}, {time_label_12h(local)}"


def _tenant_zone(tenant_id: UUID) -> ZoneInfo:
    """The business's own zone (`tenants.timezone`, read through `tenant_session` by
    the Conversaciones gateway); UTC if it cannot be read — a date is never worth an
    error on the reply panel."""
    try:
        return ZoneInfo(conversations_gateway().timezone(tenant_id) or "UTC")
    except Exception:  # noqa: BLE001 - the zone is cosmetic; the queue must still load
        return ZoneInfo("UTC")


def _to_vm(
    record: DraftRecord,
    candidates_by_media_id: dict[str, CandidateMediaVM] | None = None,
    zone: ZoneInfo | None = None,
) -> DraftVM:
    """`candidates_by_media_id` is the inbox's ALREADY-loaded candidate list keyed by
    media id — the only source of a picture, since the inbox stores none (Meta's URLs
    expire). Same cross-reference `inbox_provider._to_reel_summary_vm` does for the Reel
    cards: zero new queries, zero new Meta calls. Without it (or for a publication
    outside the 2-week list) the thumbnail is `""`."""
    media = (candidates_by_media_id or {}).get(record.external_media_id)
    caption = (record.media_caption or (media.caption if media else "")).strip()
    return DraftVM(
        id=str(record.id),
        source_id=record.source_id,
        sentiment_label=record.sentiment_label,
        comment_text=record.comment_text,
        generated_text=record.generated_text,
        final_text=record.final_text or "",
        status=record.status,
        created_at=moment_label(record.created_at, zone or ZoneInfo("UTC")),
        author_username=record.author_username,
        media_thumbnail_url=media.thumbnail_url if media else "",
        media_alt=caption or PUBLICATION_ALT_FALLBACK,
        media_day=media.posted_day if media else "",
    )


def pending_drafts(
    *,
    tenant_id: UUID,
    connection_id: UUID,
    candidates: Iterable[CandidateMediaVM] = (),
) -> list[DraftVM]:
    """The review queue: `status == 'proposed'` only. Blocking DB call — callers on
    the event loop must run it off-thread, same convention `inbox_provider`'s
    synchronous read seams already establish. `candidates` is `InboxState.candidates`
    (already loaded) — the drafts' thumbnails come from there, see `_to_vm`."""
    by_media_id = {c.external_media_id: c for c in candidates}
    drafts = _list_pending_drafts(tenant_id=tenant_id, connection_id=connection_id)
    if not drafts:
        return []
    zone = _tenant_zone(tenant_id)
    return [_to_vm(d, by_media_id, zone) for d in drafts]


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

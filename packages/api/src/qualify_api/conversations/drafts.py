"""Assisted-reply drafts for private conversations — the CONTRACT only (QUA-226, E1).

Generation (Claude, catalog grounding, cost reporting) is E4 and lives nowhere yet. What
E1 fixes is the shape every later piece must agree on, so the outbox and the service can
already be written against it:

- A draft's statuses are `comment_reply_drafts`' own (0014), verbatim: a draft is
  `proposed` until a person `accepted`/`edited`/`discarded` it; only an accepted or edited
  draft can turn into a send. `sending`/`sent`/`send_failed`/`send_ambiguous` are the
  outbox's reflection back onto the draft (E4 decides whether to store that reflection
  or read it from the outbox row — `conversation_outbox.draft_id` already points back).
- Approving a draft is NOT a draft operation: it is `ConversationService.reply(...,
  approval=HumanApproval(user_id, approved_at, draft_id))`. The draft table never gets a
  `send` column of its own — the one path to a send is the outbox, whose
  `approved_by_user_id` is NOT NULL. Keeping the two apart is what makes "no code path
  sends without approval" a property of the schema rather than of each caller's care.

No Postgres table exists for drafts yet (E4's revision adds it, with the `settle_once`
trigger of 0014). `MemoryDraftRepository` is the only implementation and exists so the
contract is executable in tests, not as a stand-in for the real store.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, Protocol
from uuid import UUID, uuid4


class DraftStatus(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    EDITED = "edited"
    DISCARDED = "discarded"
    SENDING = "sending"
    SENT = "sent"
    SEND_FAILED = "send_failed"
    SEND_AMBIGUOUS = "send_ambiguous"


# The decisions a person may take on a `proposed` draft, and nothing else.
HUMAN_DECISIONS: Final = frozenset(
    {DraftStatus.ACCEPTED, DraftStatus.EDITED, DraftStatus.DISCARDED}
)
# The statuses from which a send may be queued (`final_text` is set on both).
SENDABLE: Final = frozenset({DraftStatus.ACCEPTED, DraftStatus.EDITED})


@dataclass(frozen=True)
class ConversationDraft:
    id: UUID
    tenant_id: UUID
    thread_id: UUID
    # The inbound message this draft answers (`messages.id`).
    message_id: UUID
    generator_version: str
    generated_text: str
    # Why the pre-generator gate let this message through (the QUA-22 discipline).
    gate_reason: str
    # E4: the grounding verdict — `True` when the generator lacked validated tenant data
    # (catalog) for something the text asserts, so the UI must flag «requiere revisión».
    needs_review: bool
    status: DraftStatus
    created_at: datetime
    final_text: str | None = None
    decided_at: datetime | None = None
    decided_by_user_id: UUID | None = None


class InvalidDraftTransition(ValueError):
    """The requested status is not a human decision, or the draft is no longer `proposed`."""


class UnknownDraft(LookupError):
    """No draft with that id is visible in this tenant."""


class DraftRepository(Protocol):
    def create(self, draft: ConversationDraft) -> ConversationDraft: ...

    def get(self, *, tenant_id: UUID, draft_id: UUID) -> ConversationDraft | None: ...

    def list_pending(
        self, *, tenant_id: UUID, thread_id: UUID | None = None
    ) -> list[ConversationDraft]: ...

    def decide(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        status: DraftStatus,
        final_text: str | None,
        decided_by_user_id: UUID,
        now: datetime,
    ) -> ConversationDraft: ...


def _utcnow() -> datetime:
    return datetime.now(UTC)


def new_draft(
    *,
    tenant_id: UUID,
    thread_id: UUID,
    message_id: UUID,
    generator_version: str,
    generated_text: str,
    gate_reason: str,
    needs_review: bool = False,
    now: datetime | None = None,
) -> ConversationDraft:
    """A fresh `proposed` draft. The only constructor callers should use: a draft is
    born `proposed`, never in any other status."""
    return ConversationDraft(
        id=uuid4(),
        tenant_id=tenant_id,
        thread_id=thread_id,
        message_id=message_id,
        generator_version=generator_version,
        generated_text=generated_text,
        gate_reason=gate_reason,
        needs_review=needs_review,
        status=DraftStatus.PROPOSED,
        created_at=now or _utcnow(),
    )


def decide_draft(
    draft: ConversationDraft,
    *,
    status: DraftStatus,
    final_text: str | None,
    decided_by_user_id: UUID,
    now: datetime,
) -> ConversationDraft:
    """The pure transition `proposed -> accepted | edited | discarded`. `accepted` keeps
    the generated text as final; `edited` needs a non-empty different text; `discarded`
    has no final text. Anything else is `InvalidDraftTransition`."""
    if draft.status is not DraftStatus.PROPOSED:
        raise InvalidDraftTransition(f"draft {draft.id} is {draft.status}, not proposed")
    if status not in HUMAN_DECISIONS:
        raise InvalidDraftTransition(f"{status} is not a human decision")
    if status is DraftStatus.ACCEPTED:
        final = draft.generated_text
    elif status is DraftStatus.EDITED:
        if final_text is None or not final_text.strip():
            raise InvalidDraftTransition("an edited draft needs a non-empty final text")
        final = final_text
    else:
        final = None
    return replace(
        draft,
        status=status,
        final_text=final,
        decided_at=now,
        decided_by_user_id=decided_by_user_id,
    )


class MemoryDraftRepository:
    def __init__(self, *, clock: Callable[[], datetime] = _utcnow) -> None:
        self._clock = clock
        self.rows: dict[UUID, ConversationDraft] = {}

    def create(self, draft: ConversationDraft) -> ConversationDraft:
        if any(
            d.message_id == draft.message_id and d.tenant_id == draft.tenant_id
            for d in self.rows.values()
        ):
            raise ValueError(f"a draft already exists for message {draft.message_id}")
        self.rows[draft.id] = draft
        return draft

    def get(self, *, tenant_id: UUID, draft_id: UUID) -> ConversationDraft | None:
        draft = self.rows.get(draft_id)
        return draft if draft is not None and draft.tenant_id == tenant_id else None

    def list_pending(
        self, *, tenant_id: UUID, thread_id: UUID | None = None
    ) -> list[ConversationDraft]:
        return sorted(
            (
                d
                for d in self.rows.values()
                if d.tenant_id == tenant_id
                and d.status is DraftStatus.PROPOSED
                and (thread_id is None or d.thread_id == thread_id)
            ),
            key=lambda d: d.created_at,
        )

    def decide(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        status: DraftStatus,
        final_text: str | None,
        decided_by_user_id: UUID,
        now: datetime,
    ) -> ConversationDraft:
        draft = self.get(tenant_id=tenant_id, draft_id=draft_id)
        if draft is None:
            raise UnknownDraft(str(draft_id))
        decided = decide_draft(
            draft,
            status=status,
            final_text=final_text,
            decided_by_user_id=decided_by_user_id,
            now=now,
        )
        self.rows[draft_id] = decided
        return decided

"""Assisted-reply drafts for private conversations (QUA-226, E1 contract + E4 store).

Generation (Claude, catalog grounding, cost reporting) lives in `suggest.py`. What this
module fixes is the shape every piece agrees on, so the outbox, the service and the UI
are written against it:

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

`conversation_drafts` (0063) is the store, read through `PostgresDraftRepository` under
RLS; `MemoryDraftRepository` is the same contract for offline tests. One `proposed` draft
per message at a time (`DraftPending`); a discarded one never blocks a new suggestion.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final, Protocol
from uuid import UUID, uuid4

from qualify_shared.db.session import tenant_session
from sqlalchemy import text


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
    # Cost provenance (QUA-144): which model wrote it and what the call cost. Zero on a
    # draft that no model wrote (tests, a future rule-based generator).
    model_id: str | None = None
    model_revision: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    # The validated facts the generator was given (business name, products with their
    # prices) — what `needs_review` is judged against. Never user text.
    grounding: Mapping[str, Any] = field(default_factory=dict)


class InvalidDraftTransition(ValueError):
    """The requested status is not a human decision, or the draft is no longer `proposed`."""


class UnknownDraft(LookupError):
    """No draft with that id is visible in this tenant."""


class DraftPending(ValueError):
    """The message already has a `proposed` draft: decide it before asking for another.
    A discarded draft does NOT block a new one — «sugerir de nuevo» is allowed."""


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
    model_id: str | None = None,
    model_revision: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
    grounding: Mapping[str, Any] | None = None,
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
        model_id=model_id,
        model_revision=model_revision,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        grounding=dict(grounding or {}),
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
            d.message_id == draft.message_id
            and d.tenant_id == draft.tenant_id
            and d.status is DraftStatus.PROPOSED
            for d in self.rows.values()
        ):
            raise DraftPending(f"a proposed draft already exists for message {draft.message_id}")
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


# --- Postgres -----------------------------------------------------------------------------

_DRAFT_COLUMNS = """
    d.id, d.tenant_id, d.thread_id, d.message_id, d.generator_version, d.generated_text,
    d.gate_reason, d.needs_review, d.status, d.final_text, d.created_at, d.decided_at,
    d.decided_by_user_id, d.model_id, d.model_revision, d.input_tokens, d.output_tokens,
    d.cost_usd, d.grounding
"""

_INSERT_DRAFT = text(
    """
    INSERT INTO conversation_drafts (
        id, tenant_id, thread_id, message_id, generator_version, generated_text,
        gate_reason, needs_review, status, created_at, model_id, model_revision,
        input_tokens, output_tokens, cost_usd, grounding
    ) VALUES (
        :id, :tenant_id, :thread_id, :message_id, :generator_version, :generated_text,
        :gate_reason, :needs_review, 'proposed', :created_at, :model_id, :model_revision,
        :input_tokens, :output_tokens, :cost_usd, CAST(:grounding AS jsonb)
    )
    """
)

_PENDING_FOR_MESSAGE = text(
    """
    SELECT 1 FROM conversation_drafts
     WHERE message_id = :message_id AND status = 'proposed'
     LIMIT 1
    """
)

_GET_DRAFT = text(f"SELECT {_DRAFT_COLUMNS} FROM conversation_drafts d WHERE d.id = :draft_id")

_LIST_PENDING = text(
    f"""
    SELECT {_DRAFT_COLUMNS} FROM conversation_drafts d
     WHERE d.status = 'proposed'
       AND (CAST(:thread_id AS uuid) IS NULL OR d.thread_id = :thread_id)
     ORDER BY d.created_at
    """
)

# The transition is decided in Python (`decide_draft`) and written back only if the row
# is still `proposed`: two people deciding the same draft cannot both win.
_DECIDE = text(
    """
    UPDATE conversation_drafts
       SET status = :status, final_text = :final_text, decided_at = :now,
           decided_by_user_id = :user_id
     WHERE id = :draft_id AND status = 'proposed'
    """
)


def _row_to_draft(r: Any) -> ConversationDraft:
    grounding = r.grounding if isinstance(r.grounding, dict) else {}
    return ConversationDraft(
        id=r.id,
        tenant_id=r.tenant_id,
        thread_id=r.thread_id,
        message_id=r.message_id,
        generator_version=r.generator_version,
        generated_text=r.generated_text,
        gate_reason=r.gate_reason,
        needs_review=bool(r.needs_review),
        status=DraftStatus(r.status),
        created_at=r.created_at,
        final_text=r.final_text,
        decided_at=r.decided_at,
        decided_by_user_id=r.decided_by_user_id,
        model_id=r.model_id,
        model_revision=r.model_revision,
        input_tokens=int(r.input_tokens or 0),
        output_tokens=int(r.output_tokens or 0),
        cost_usd=float(r.cost_usd or 0),
        grounding=grounding,
    )


class PostgresDraftRepository:
    """`conversation_drafts` under RLS (`tenant_session`). Same contract as the memory
    repository; the only difference is that the "one proposed draft per message" rule is
    checked with a query, not a scan."""

    def create(self, draft: ConversationDraft) -> ConversationDraft:
        with tenant_session(draft.tenant_id) as session:
            pending = session.execute(
                _PENDING_FOR_MESSAGE, {"message_id": draft.message_id}
            ).first()
            if pending is not None:
                raise DraftPending(
                    f"a proposed draft already exists for message {draft.message_id}"
                )
            session.execute(
                _INSERT_DRAFT,
                {
                    "id": draft.id,
                    "tenant_id": draft.tenant_id,
                    "thread_id": draft.thread_id,
                    "message_id": draft.message_id,
                    "generator_version": draft.generator_version,
                    "generated_text": draft.generated_text,
                    "gate_reason": draft.gate_reason,
                    "needs_review": draft.needs_review,
                    "created_at": draft.created_at,
                    "model_id": draft.model_id,
                    "model_revision": draft.model_revision,
                    "input_tokens": draft.input_tokens,
                    "output_tokens": draft.output_tokens,
                    "cost_usd": draft.cost_usd,
                    "grounding": json.dumps(dict(draft.grounding)),
                },
            )
        return draft

    def get(self, *, tenant_id: UUID, draft_id: UUID) -> ConversationDraft | None:
        with tenant_session(tenant_id) as session:
            row = session.execute(_GET_DRAFT, {"draft_id": draft_id}).first()
        return _row_to_draft(row) if row is not None else None

    def list_pending(
        self, *, tenant_id: UUID, thread_id: UUID | None = None
    ) -> list[ConversationDraft]:
        with tenant_session(tenant_id) as session:
            rows = session.execute(_LIST_PENDING, {"thread_id": thread_id}).all()
        return [_row_to_draft(r) for r in rows]

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
        with tenant_session(tenant_id) as session:
            result = session.execute(
                _DECIDE,
                {
                    "draft_id": draft_id,
                    "status": decided.status.value,
                    "final_text": decided.final_text,
                    "now": now,
                    "user_id": decided_by_user_id,
                },
            )
            if result.rowcount != 1:
                raise InvalidDraftTransition(f"draft {draft_id} was decided concurrently")
        return decided

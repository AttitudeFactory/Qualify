"""The assisted-draft CONTRACT (QUA-226, E1 — `conversations/drafts.py`): a draft is born
`proposed`, a person may only accept / edit / discard it, and approving it is NOT a draft
operation but a `HumanApproval` handed to `ConversationService.reply` (see
`test_conversations_service.py`). No table exists yet; this pins the pure transition and
the memory repository E4 will build against."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from qualify_api.conversations.drafts import (
    HUMAN_DECISIONS,
    SENDABLE,
    DraftStatus,
    InvalidDraftTransition,
    MemoryDraftRepository,
    UnknownDraft,
    decide_draft,
    new_draft,
)

T0 = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
TENANT, USER = uuid4(), uuid4()


def _draft(**overrides):
    base = dict(
        tenant_id=TENANT,
        thread_id=uuid4(),
        message_id=uuid4(),
        generator_version="e4-not-built",
        generated_text="Sí, tenemos talla M.",
        gate_reason="inbound, window open, text present",
        now=T0,
    )
    base.update(overrides)
    return new_draft(**base)


def test_a_draft_is_born_proposed() -> None:
    draft = _draft()
    assert draft.status is DraftStatus.PROPOSED
    assert draft.final_text is None and draft.decided_by_user_id is None
    assert draft.needs_review is False


def test_accept_keeps_the_generated_text() -> None:
    decided = decide_draft(
        _draft(), status=DraftStatus.ACCEPTED, final_text=None, decided_by_user_id=USER, now=T0
    )
    assert decided.status is DraftStatus.ACCEPTED
    assert decided.final_text == "Sí, tenemos talla M."
    assert decided.decided_by_user_id == USER and decided.decided_at == T0


def test_edit_needs_a_text_and_keeps_it() -> None:
    with pytest.raises(InvalidDraftTransition):
        decide_draft(
            _draft(), status=DraftStatus.EDITED, final_text="  ", decided_by_user_id=USER, now=T0
        )
    decided = decide_draft(
        _draft(),
        status=DraftStatus.EDITED,
        final_text="Sí, M y L.",
        decided_by_user_id=USER,
        now=T0,
    )
    assert decided.final_text == "Sí, M y L." and decided.generated_text == "Sí, tenemos talla M."


def test_discard_has_no_final_text() -> None:
    decided = decide_draft(
        _draft(),
        status=DraftStatus.DISCARDED,
        final_text="ignored",
        decided_by_user_id=USER,
        now=T0,
    )
    assert decided.status is DraftStatus.DISCARDED and decided.final_text is None


@pytest.mark.parametrize("status", sorted(set(DraftStatus) - HUMAN_DECISIONS))
def test_only_human_decisions_are_transitions(status: DraftStatus) -> None:
    with pytest.raises(InvalidDraftTransition):
        decide_draft(_draft(), status=status, final_text=None, decided_by_user_id=USER, now=T0)


def test_a_decided_draft_is_final() -> None:
    decided = decide_draft(
        _draft(), status=DraftStatus.ACCEPTED, final_text=None, decided_by_user_id=USER, now=T0
    )
    with pytest.raises(InvalidDraftTransition):
        decide_draft(
            decided, status=DraftStatus.DISCARDED, final_text=None, decided_by_user_id=USER, now=T0
        )


def test_sendable_is_exactly_accepted_or_edited() -> None:
    assert SENDABLE == {DraftStatus.ACCEPTED, DraftStatus.EDITED}


def test_memory_repository_one_draft_per_message_and_tenant_scoped() -> None:
    repo = MemoryDraftRepository()
    draft = repo.create(_draft())
    with pytest.raises(ValueError):
        repo.create(_draft(message_id=draft.message_id))
    assert repo.get(tenant_id=uuid4(), draft_id=draft.id) is None
    assert repo.list_pending(tenant_id=TENANT) == [draft]
    with pytest.raises(UnknownDraft):
        repo.decide(
            tenant_id=uuid4(),
            draft_id=draft.id,
            status=DraftStatus.ACCEPTED,
            final_text=None,
            decided_by_user_id=USER,
            now=T0,
        )
    decided = repo.decide(
        tenant_id=TENANT,
        draft_id=draft.id,
        status=DraftStatus.ACCEPTED,
        final_text=None,
        decided_by_user_id=USER,
        now=T0 + timedelta(minutes=1),
    )
    assert decided.status is DraftStatus.ACCEPTED
    assert repo.list_pending(tenant_id=TENANT) == []

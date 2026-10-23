"""`db`-marked: «Reintentar» (ATENDER-9, m-24849130) against the real
`comment_reply_drafts` — the live index, the settle-once trigger (the failed row is
never rewritten) and the «newest draft per comment» rule of the retry list."""

from __future__ import annotations

import pytest

from qualify_api.replies.repository import PostgresReplyRepository

from .test_replies_repository_db import TENANT_A, _create, _fresh_version, _seed_pos_comment

pytestmark = pytest.mark.db


def _failed(repo: PostgresReplyRepository, *, code: str):
    version = _fresh_version()
    connection_id, candidate, user_id = _seed_pos_comment(TENANT_A, version)
    draft = _create(repo, connection_id, candidate)
    assert draft is not None
    repo.decide_draft(
        tenant_id=TENANT_A,
        draft_id=draft.id,
        decision="edited",
        final_text="¡Gracias, Ana!",
        decided_by_user_id=user_id,
    )
    repo.mark_sending(tenant_id=TENANT_A, draft_id=draft.id)
    failed = repo.mark_send_failed(tenant_id=TENANT_A, draft_id=draft.id, error_code=code)
    return connection_id, user_id, failed


def test_a_passing_failure_is_listed_and_cloned_once() -> None:
    repo = PostgresReplyRepository()
    connection_id, user_id, failed = _failed(repo, code="transient:not_sent")

    listed = repo.list_retryable_drafts(tenant_id=TENANT_A, connection_id=connection_id)
    assert [d.id for d in listed] == [failed.id]
    assert listed[0].comment_text  # the card shows what it answers

    new = repo.clone_for_retry(tenant_id=TENANT_A, draft_id=failed.id, decided_by_user_id=user_id)
    assert new is not None
    assert new.id != failed.id
    assert new.status == "edited"
    assert new.final_text == "¡Gracias, Ana!"
    assert new.settled_at is None

    # A second tap writes nothing.
    again = repo.clone_for_retry(tenant_id=TENANT_A, draft_id=failed.id, decided_by_user_id=user_id)
    assert again is None
    assert repo.list_retryable_drafts(tenant_id=TENANT_A, connection_id=connection_id) == ()
    # The failed row is the untouched record of what happened.
    kept = repo.get_draft(tenant_id=TENANT_A, draft_id=failed.id)
    assert kept is not None and kept.send_error_code == "transient:not_sent"


def test_a_retry_that_fails_again_is_the_only_card() -> None:
    repo = PostgresReplyRepository()
    connection_id, user_id, failed = _failed(repo, code="transient:not_sent")
    new = repo.clone_for_retry(tenant_id=TENANT_A, draft_id=failed.id, decided_by_user_id=user_id)
    assert new is not None
    repo.mark_sending(tenant_id=TENANT_A, draft_id=new.id)
    repo.mark_send_failed(tenant_id=TENANT_A, draft_id=new.id, error_code="transient:platform:2")

    listed = repo.list_retryable_drafts(tenant_id=TENANT_A, connection_id=connection_id)
    assert [d.id for d in listed] == [new.id]
    # The older failure can no longer be retried: only the newest draft can.
    assert (
        repo.clone_for_retry(tenant_id=TENANT_A, draft_id=failed.id, decided_by_user_id=user_id)
        is None
    )


@pytest.mark.parametrize("code", ["deleted:100/33", "platform:10", "auth:190", "unknown"])
def test_other_refusals_are_not_retryable(code: str) -> None:
    repo = PostgresReplyRepository()
    connection_id, user_id, failed = _failed(repo, code=code)
    assert repo.list_retryable_drafts(tenant_id=TENANT_A, connection_id=connection_id) == ()
    assert (
        repo.clone_for_retry(tenant_id=TENANT_A, draft_id=failed.id, decided_by_user_id=user_id)
        is None
    )

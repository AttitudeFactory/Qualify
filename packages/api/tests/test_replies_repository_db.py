"""`db`-marked end-to-end test for QUA-22's comments tranche: `PostgresReplyRepository`
against a self-seeded, disposable tenant/connection/thread/message/sentiment-result —
same seeding pattern `test_sentiment_results_db.py::_seed_two_comments` establishes,
extended one step further (a `comment_sentiment_results` row, migration 0014's own
composite-FK dependency).

Covers what a purely offline (Memory-repository) test cannot: the real FK/CHECK
constraints from migration 0014, RLS isolation between two tenants, and the
`comment_reply_drafts_settle_once` trigger actually refusing a write.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.inbox.models import Message, Thread
from qualify_api.replies.repository import CandidateComment, PostgresReplyRepository
from qualify_api.sentiment.models import CommentSentimentResult
from qualify_api.sentiment.repository import AnalysisVersion
from qualify_api.tenancy.models import Tenant, User

pytestmark = pytest.mark.db

TENANT_A = UUID("e0000000-0000-4000-8000-0000000000f7")
TENANT_B = UUID("e0000000-0000-4000-8000-0000000000f8")


def _fresh_version() -> AnalysisVersion:
    run_id = uuid4().hex[:8]
    return AnalysisVersion(
        detector_version=f"test-replies-e2e-{run_id}",
        pipeline_version="test-replies-e2e-pipeline",
        model_id="test/e2e-stub",
        model_revision=None,
    )


def _ensure_tenant(tenant_id: UUID, name: str) -> None:
    with admin_session() as session:
        if session.get(Tenant, tenant_id) is None:
            session.add(
                Tenant(
                    id=tenant_id, name=name, country="CO", timezone="America/Bogota", currency="COP"
                )
            )
            session.flush()


def _seed_pos_comment(
    tenant_id: UUID, version: AnalysisVersion
) -> tuple[UUID, CandidateComment, UUID]:
    """Seeds a connection + comment-channel thread + one inbound message + one POS
    `comment_sentiment_results` row under `version` — the exact shape
    `list_positive_comments_without_draft` reads. Returns
    `(connection_id, candidate, user_id)` — `user_id` is a REAL seeded row, required
    because `decided_by_user_id` carries a live FK to `users.id` (migration 0014); a
    random `uuid4()` would violate it, which is itself worth asserting once (see
    `test_decided_by_user_id_fk_is_enforced` below)."""
    _ensure_tenant(tenant_id, f"t-replies-e2e-{tenant_id.hex[:6]}")
    with admin_session() as session:
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        session.add(app)
        session.flush()
        user = User(tenant_id=tenant_id, email=f"u-{uuid4()}@e2e.co", display_name="U")
        session.add(user)
        session.flush()
        app_id, user_id = app.id, user.id

    with tenant_session(tenant_id) as session:
        conn = SocialConnection(
            tenant_id=tenant_id,
            platform_app_id=app_id,
            platform="instagram",
            account_type="business",
            external_account_id=f"ig-{uuid4()}",
            linked_page_id="page-1",
            granted_scopes=["basic", "manage_comments"],
            status="active",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=user_id,
        )
        session.add(conn)
        session.flush()
        connection_id = conn.id

        thread = Thread(
            tenant_id=tenant_id,
            connection_id=connection_id,
            channel="comment",
            external_thread_id=f"media-{uuid4()}",
            status="open",
        )
        session.add(thread)
        session.flush()

        source_id = f"comment-{uuid4()}"
        message = Message(
            tenant_id=tenant_id,
            thread_id=thread.id,
            connection_id=connection_id,
            external_message_id=source_id,
            direction="inbound",
            text="Me encanta, excelente servicio!",
            shape_version="ig-comment-shapes-1.0.0",
        )
        session.add(message)
        session.flush()

        result = CommentSentimentResult(
            tenant_id=tenant_id,
            connection_id=connection_id,
            message_id=message.id,
            source_id=source_id,
            detector_version=version.detector_version,
            pipeline_version=version.pipeline_version,
            model_id=version.model_id,
            model_revision=version.model_revision,
            label="POS",
            score=0.95,
        )
        session.add(result)
        session.flush()

        candidate = CandidateComment(
            message_id=message.id,
            source_id=source_id,
            text=message.text or "",
            sentiment_result_id=result.id,
            sentiment_label="POS",
        )
    return connection_id, candidate, user_id


def test_finds_the_seeded_pos_comment_and_creates_a_draft() -> None:
    version = _fresh_version()
    connection_id, candidate, _user_id = _seed_pos_comment(TENANT_A, version)
    repo = PostgresReplyRepository()

    candidates = repo.list_positive_comments_without_draft(
        tenant_id=TENANT_A, connection_id=connection_id, version=version
    )
    assert [c.message_id for c in candidates] == [candidate.message_id]

    created = repo.create_draft(
        tenant_id=TENANT_A,
        connection_id=connection_id,
        candidate=candidate,
        gate_reason="comment channel, POS sentiment, non-empty text, no existing draft",
        generator_version="qua22.1:test-model",
        generated_text="¡Gracias por tu comentario!",
    )
    assert created is not None
    assert created.status == "proposed"

    # The candidate no longer appears — a draft now exists for it.
    remaining = repo.list_positive_comments_without_draft(
        tenant_id=TENANT_A, connection_id=connection_id, version=version
    )
    assert remaining == ()


def test_a_soft_deleted_comment_is_never_a_draft_candidate() -> None:
    """QUA-101 regression: a comment Meta no longer returns (`messages.deleted_at` set
    by `InboxRepository.reconcile_media_comments`) must never surface as a candidate
    for a NEW reply draft — even though it is still POS-analyzed and has no draft yet.
    Wasting a generator call and showing a human reviewer a draft for a comment that no
    longer exists on Instagram was the exact bug this test pins closed."""
    version = _fresh_version()
    connection_id, candidate, _user_id = _seed_pos_comment(TENANT_A, version)
    with tenant_session(TENANT_A) as session:
        message = session.get(Message, candidate.message_id)
        assert message is not None
        message.deleted_at = datetime.now(UTC)
        session.flush()
    repo = PostgresReplyRepository()

    candidates = repo.list_positive_comments_without_draft(
        tenant_id=TENANT_A, connection_id=connection_id, version=version
    )

    assert candidates == ()


def test_unique_message_id_returns_none_not_an_exception() -> None:
    version = _fresh_version()
    connection_id, candidate, _user_id = _seed_pos_comment(TENANT_A, version)
    repo = PostgresReplyRepository()
    first = repo.create_draft(
        tenant_id=TENANT_A,
        connection_id=connection_id,
        candidate=candidate,
        gate_reason="r",
        generator_version="v1",
        generated_text="text one",
    )
    assert first is not None

    second = repo.create_draft(
        tenant_id=TENANT_A,
        connection_id=connection_id,
        candidate=candidate,
        gate_reason="r",
        generator_version="v1",
        generated_text="text two",
    )
    assert second is None


def test_full_lifecycle_accept_send_sent_is_settled() -> None:
    version = _fresh_version()
    connection_id, candidate, user_id = _seed_pos_comment(TENANT_A, version)
    repo = PostgresReplyRepository()
    draft = repo.create_draft(
        tenant_id=TENANT_A,
        connection_id=connection_id,
        candidate=candidate,
        gate_reason="r",
        generator_version="v1",
        generated_text="¡Gracias!",
    )
    assert draft is not None

    decided = repo.decide_draft(
        tenant_id=TENANT_A,
        draft_id=draft.id,
        decision="accepted",
        final_text=None,
        decided_by_user_id=user_id,
    )
    assert decided.status == "accepted"
    assert decided.settled_at is None  # accepted is NOT terminal — only sent/failed/discarded are

    sending = repo.mark_sending(tenant_id=TENANT_A, draft_id=draft.id)
    assert sending.status == "sending"

    sent = repo.mark_sent(tenant_id=TENANT_A, draft_id=draft.id, external_reply_id="meta-reply-1")
    assert sent.status == "sent"
    assert sent.is_settled is True
    assert sent.external_reply_id == "meta-reply-1"


def test_ambiguous_send_does_not_settle() -> None:
    version = _fresh_version()
    connection_id, candidate, user_id = _seed_pos_comment(TENANT_A, version)
    repo = PostgresReplyRepository()
    draft = repo.create_draft(
        tenant_id=TENANT_A,
        connection_id=connection_id,
        candidate=candidate,
        gate_reason="r",
        generator_version="v1",
        generated_text="¡Gracias!",
    )
    assert draft is not None
    repo.decide_draft(
        tenant_id=TENANT_A,
        draft_id=draft.id,
        decision="accepted",
        final_text=None,
        decided_by_user_id=user_id,
    )
    repo.mark_sending(tenant_id=TENANT_A, draft_id=draft.id)

    ambiguous = repo.mark_send_ambiguous(
        tenant_id=TENANT_A, draft_id=draft.id, error_code="transport:timeout"
    )
    assert ambiguous.status == "send_ambiguous"
    assert ambiguous.settled_at is None  # deliberately unsettled — see migration 0014


def test_settle_once_trigger_refuses_a_second_write_to_a_settled_row() -> None:
    """The `comment_reply_drafts_settle_once` trigger, exercised directly with raw SQL
    — the same class of test `publish_attempts_settle_once` gets, proving the
    invariant is enforced by Postgres, not merely by `PostgresReplyRepository`'s own
    discipline."""
    version = _fresh_version()
    connection_id, candidate, user_id = _seed_pos_comment(TENANT_A, version)
    repo = PostgresReplyRepository()
    draft = repo.create_draft(
        tenant_id=TENANT_A,
        connection_id=connection_id,
        candidate=candidate,
        gate_reason="r",
        generator_version="v1",
        generated_text="¡Gracias!",
    )
    assert draft is not None
    repo.decide_draft(
        tenant_id=TENANT_A,
        draft_id=draft.id,
        decision="discarded",
        final_text=None,
        decided_by_user_id=user_id,
    )

    with tenant_session(TENANT_A) as session, pytest.raises(DBAPIError, match="already settled"):
        session.execute(
            text("UPDATE comment_reply_drafts SET status = 'proposed' WHERE id = :id"),
            {"id": str(draft.id)},
        )


def test_rls_isolates_another_tenants_draft() -> None:
    version = _fresh_version()
    connection_id, candidate, _user_id = _seed_pos_comment(TENANT_A, version)
    repo = PostgresReplyRepository()
    draft = repo.create_draft(
        tenant_id=TENANT_A,
        connection_id=connection_id,
        candidate=candidate,
        gate_reason="r",
        generator_version="v1",
        generated_text="¡Gracias!",
    )
    assert draft is not None
    _ensure_tenant(TENANT_B, "t-replies-e2e-b")

    invisible = repo.get_draft(tenant_id=TENANT_B, draft_id=draft.id)
    assert invisible is None

    visible = repo.get_draft(tenant_id=TENANT_A, draft_id=draft.id)
    assert visible is not None


def test_decided_by_user_id_fk_is_enforced() -> None:
    """The failure this file's own earlier draft tripped over, kept as a real test
    rather than silently fixed away: `decided_by_user_id` is a live FK to `users.id`
    (migration 0014), so a random, never-seeded uuid must be refused, not silently
    accepted."""
    version = _fresh_version()
    connection_id, candidate, _user_id = _seed_pos_comment(TENANT_A, version)
    repo = PostgresReplyRepository()
    draft = repo.create_draft(
        tenant_id=TENANT_A,
        connection_id=connection_id,
        candidate=candidate,
        gate_reason="r",
        generator_version="v1",
        generated_text="¡Gracias!",
    )
    assert draft is not None

    with pytest.raises(DBAPIError, match="decided_by_user_id_fkey"):
        repo.decide_draft(
            tenant_id=TENANT_A,
            draft_id=draft.id,
            decision="accepted",
            final_text=None,
            decided_by_user_id=uuid4(),
        )

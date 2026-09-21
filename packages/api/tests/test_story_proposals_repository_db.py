"""`db`-marked end-to-end test for QUA-106: `PostgresStoryProposalRepository` against a
self-seeded, disposable tenant/connection — same seeding pattern
`test_replies_repository_db.py::_seed_pos_comment` establishes, simplified (a Story
proposal needs only a connection, not a comment/sentiment chain).

Covers what a purely offline (Memory-repository) test cannot: the real FK/CHECK
constraints from migration 0021, RLS isolation between two tenants, and the
`story_proposals_settle_once` trigger actually refusing a write.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.publishing.models import PublishAttempt
from qualify_api.stories.repository import PostgresStoryProposalRepository
from qualify_api.tenancy.models import Tenant, User

pytestmark = pytest.mark.db

TENANT_A = UUID("e0000000-0000-4000-8000-0000000000fa")
TENANT_B = UUID("e0000000-0000-4000-8000-0000000000fb")


def _ensure_tenant(tenant_id: UUID, name: str) -> None:
    with admin_session() as session:
        if session.get(Tenant, tenant_id) is None:
            session.add(
                Tenant(
                    id=tenant_id, name=name, country="CO", timezone="America/Bogota", currency="COP"
                )
            )
            session.flush()


def _seed_connection(tenant_id: UUID) -> tuple[UUID, UUID]:
    """Returns `(connection_id, user_id)` — `user_id` is a REAL seeded row, required
    because `decided_by_user_id` carries a live FK to `users.id` (migration 0021)."""
    _ensure_tenant(tenant_id, f"t-stories-e2e-{tenant_id.hex[:6]}")
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
            granted_scopes=["basic"],
            status="active",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=user_id,
        )
        session.add(conn)
        session.flush()
        connection_id = conn.id
    return connection_id, user_id


def test_propose_creates_a_proposed_row() -> None:
    connection_id, _user_id = _seed_connection(TENANT_A)
    repo = PostgresStoryProposalRepository()

    proposal = repo.propose(
        tenant_id=TENANT_A,
        connection_id=connection_id,
        media_object_key=f"t/{TENANT_A}/stories/{uuid4().hex}.mp4",
        media_content_type="video/mp4",
        caption="Un caption",
        trend_audio_id=None,
        trend_audio_title=None,
    )

    assert proposal.status == "proposed"
    assert proposal.settled_at is None
    fetched = repo.get(tenant_id=TENANT_A, proposal_id=proposal.id)
    assert fetched is not None
    assert fetched.id == proposal.id


def test_full_lifecycle_approve_publish_published_is_settled() -> None:
    connection_id, user_id = _seed_connection(TENANT_A)
    repo = PostgresStoryProposalRepository()
    proposal = repo.propose(
        tenant_id=TENANT_A,
        connection_id=connection_id,
        media_object_key=f"t/{TENANT_A}/stories/{uuid4().hex}.mp4",
        media_content_type="video/mp4",
        caption="Un caption",
        trend_audio_id="audio-1",
        trend_audio_title="Cancion de prueba",
    )

    decided = repo.decide(
        tenant_id=TENANT_A,
        proposal_id=proposal.id,
        decision="approved",
        final_caption=None,
        decided_by_user_id=user_id,
    )
    assert decided.status == "approved"
    assert decided.settled_at is None  # approved is NOT terminal

    # A real publish_attempts row is required for the composite FK — same R2
    # discipline `comment_reply_drafts` already exercises against `messages`.
    with tenant_session(TENANT_A) as session:
        attempt = PublishAttempt(
            tenant_id=TENANT_A,
            connection_id=connection_id,
            idempotency_key=f"story-proposal:{proposal.id}",
            media_product_type="STORIES",
            adapter_version="test",
            status="processing",
        )
        session.add(attempt)
        session.flush()
        attempt_id = attempt.id

    publishing = repo.mark_publishing(
        tenant_id=TENANT_A, proposal_id=proposal.id, publish_attempt_id=attempt_id
    )
    assert publishing.status == "publishing"
    assert publishing.publish_attempt_id == attempt_id

    published = repo.mark_published(tenant_id=TENANT_A, proposal_id=proposal.id)
    assert published.status == "published"
    assert published.is_settled is True


def test_rejected_settles_without_a_publish_attempt() -> None:
    connection_id, user_id = _seed_connection(TENANT_A)
    repo = PostgresStoryProposalRepository()
    proposal = repo.propose(
        tenant_id=TENANT_A,
        connection_id=connection_id,
        media_object_key=f"t/{TENANT_A}/stories/{uuid4().hex}.mp4",
        media_content_type="video/mp4",
        caption="Un caption",
        trend_audio_id=None,
        trend_audio_title=None,
    )

    rejected = repo.decide(
        tenant_id=TENANT_A,
        proposal_id=proposal.id,
        decision="rejected",
        final_caption=None,
        decided_by_user_id=user_id,
    )

    assert rejected.status == "rejected"
    assert rejected.is_settled is True
    assert rejected.publish_attempt_id is None


def test_settle_once_trigger_refuses_a_second_write_to_a_settled_row() -> None:
    """The `story_proposals_settle_once` trigger, exercised directly with raw SQL —
    same class of test `comment_reply_drafts_settle_once`/`publish_attempts_settle_
    once` already get, proving the invariant is enforced by Postgres."""
    connection_id, user_id = _seed_connection(TENANT_A)
    repo = PostgresStoryProposalRepository()
    proposal = repo.propose(
        tenant_id=TENANT_A,
        connection_id=connection_id,
        media_object_key=f"t/{TENANT_A}/stories/{uuid4().hex}.mp4",
        media_content_type="video/mp4",
        caption=None,
        trend_audio_id=None,
        trend_audio_title=None,
    )
    repo.decide(
        tenant_id=TENANT_A,
        proposal_id=proposal.id,
        decision="rejected",
        final_caption=None,
        decided_by_user_id=user_id,
    )

    with tenant_session(TENANT_A) as session, pytest.raises(DBAPIError, match="already settled"):
        session.execute(
            text("UPDATE story_proposals SET status = 'proposed' WHERE id = :id"),
            {"id": str(proposal.id)},
        )


def test_rls_isolates_another_tenants_proposal() -> None:
    connection_id, _user_id = _seed_connection(TENANT_A)
    repo = PostgresStoryProposalRepository()
    proposal = repo.propose(
        tenant_id=TENANT_A,
        connection_id=connection_id,
        media_object_key=f"t/{TENANT_A}/stories/{uuid4().hex}.mp4",
        media_content_type="video/mp4",
        caption=None,
        trend_audio_id=None,
        trend_audio_title=None,
    )
    _ensure_tenant(TENANT_B, "t-stories-e2e-b")

    invisible = repo.get(tenant_id=TENANT_B, proposal_id=proposal.id)
    assert invisible is None

    visible = repo.get(tenant_id=TENANT_A, proposal_id=proposal.id)
    assert visible is not None


def test_decided_by_user_id_fk_is_enforced() -> None:
    connection_id, _user_id = _seed_connection(TENANT_A)
    repo = PostgresStoryProposalRepository()
    proposal = repo.propose(
        tenant_id=TENANT_A,
        connection_id=connection_id,
        media_object_key=f"t/{TENANT_A}/stories/{uuid4().hex}.mp4",
        media_content_type="video/mp4",
        caption=None,
        trend_audio_id=None,
        trend_audio_title=None,
    )

    with pytest.raises(DBAPIError, match="decided_by_user_id_fkey"):
        repo.decide(
            tenant_id=TENANT_A,
            proposal_id=proposal.id,
            decision="approved",
            final_caption=None,
            decided_by_user_id=uuid4(),
        )

"""`db`-marked tests for `PostgresSentimentRepository` — idempotency, versioning and
tenant isolation against the real constraints from migration 0012. Same
`seeded_connection`-style fixture as `test_inbox_repository.py`.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.inbox.models import Message, Thread
from qualify_api.sentiment.repository import AnalysisVersion, PostgresSentimentRepository
from qualify_api.tenancy.models import Tenant, User

pytestmark = pytest.mark.db

TENANT_S = UUID("e0000000-0000-4000-8000-0000000000f3")
TENANT_S2 = UUID("e0000000-0000-4000-8000-0000000000f4")

VERSION = AnalysisVersion(
    detector_version="robertuito-sentiment-v1",
    pipeline_version="owned-comments-0.1.0",
    model_id="pysentimiento/robertuito-sentiment-analysis",
    model_revision=None,
)


def _seed_tenant(tenant_id: UUID, *, name: str) -> None:
    with admin_session() as session:
        if session.get(Tenant, tenant_id) is None:
            session.add(
                Tenant(
                    id=tenant_id,
                    name=name,
                    country="CO",
                    timezone="America/Bogota",
                    currency="COP",
                )
            )
            session.flush()


def _seed_message(tenant_id: UUID) -> tuple[UUID, UUID, str]:
    """(connection_id, message_id, source_id) with a real comment-channel `messages`
    row backing it, so the repository's JOIN through `threads` has something real to
    find."""
    _seed_tenant(tenant_id, name=f"t-{tenant_id}")
    with admin_session() as session:
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        session.add(app)
        session.flush()
        user = User(tenant_id=tenant_id, email=f"u-{uuid4()}@s.co", display_name="U")
        session.add(user)
        session.flush()
        app_id = app.id
        user_id = user.id

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

        source_id = f"comment-{uuid4()}"
        thread = Thread(
            tenant_id=tenant_id,
            connection_id=connection_id,
            channel="comment",
            external_thread_id=f"media-{uuid4()}",
            status="open",
        )
        session.add(thread)
        session.flush()
        message = Message(
            tenant_id=tenant_id,
            thread_id=thread.id,
            connection_id=connection_id,
            external_message_id=source_id,
            direction="inbound",
            text="me encanta este producto",
            shape_version="ig-comment-shapes-1.0.0",
        )
        session.add(message)
        session.flush()
        message_id = message.id

    return connection_id, message_id, source_id


@pytest.fixture
def seeded_message() -> tuple[UUID, UUID, UUID, str]:
    connection_id, message_id, source_id = _seed_message(TENANT_S)
    return TENANT_S, connection_id, message_id, source_id


def test_pending_lists_a_never_analyzed_comment(
    seeded_message: tuple[UUID, UUID, UUID, str],
) -> None:
    tenant_id, connection_id, message_id, source_id = seeded_message
    repo = PostgresSentimentRepository()

    pending = repo.list_pending_for_analysis(
        tenant_id=tenant_id, connection_id=connection_id, version=VERSION
    )

    assert any(p.message_id == message_id and p.source_id == source_id for p in pending)


def test_recorded_result_is_no_longer_pending(
    seeded_message: tuple[UUID, UUID, UUID, str],
) -> None:
    tenant_id, connection_id, message_id, source_id = seeded_message
    repo = PostgresSentimentRepository()

    inserted = repo.record_sentiment_result(
        tenant_id=tenant_id,
        connection_id=connection_id,
        message_id=message_id,
        source_id=source_id,
        version=VERSION,
        label="POS",
        score=0.9,
    )
    assert inserted is True

    pending = repo.list_pending_for_analysis(
        tenant_id=tenant_id, connection_id=connection_id, version=VERSION
    )
    assert not any(p.message_id == message_id for p in pending)


def test_recording_the_same_version_twice_is_idempotent(
    seeded_message: tuple[UUID, UUID, UUID, str],
) -> None:
    tenant_id, connection_id, message_id, source_id = seeded_message
    repo = PostgresSentimentRepository()

    first = repo.record_sentiment_result(
        tenant_id=tenant_id,
        connection_id=connection_id,
        message_id=message_id,
        source_id=source_id,
        version=VERSION,
        label="POS",
        score=0.9,
    )
    second = repo.record_sentiment_result(
        tenant_id=tenant_id,
        connection_id=connection_id,
        message_id=message_id,
        source_id=source_id,
        version=VERSION,
        label="NEG",
        score=0.1,
    )

    assert first is True
    assert second is False  # same (message, version) key — refused, not a second row


def test_a_new_model_version_is_pending_again_and_the_old_row_survives(
    seeded_message: tuple[UUID, UUID, UUID, str],
) -> None:
    """Pins the whole point of 'versionar, no sobrescribir' in one test: bump
    `model_revision`, the comment becomes pending again, AND the row from the previous
    version is still there afterward — untouched, not replaced."""
    tenant_id, connection_id, message_id, source_id = seeded_message
    repo = PostgresSentimentRepository()
    repo.record_sentiment_result(
        tenant_id=tenant_id,
        connection_id=connection_id,
        message_id=message_id,
        source_id=source_id,
        version=VERSION,
        label="POS",
        score=0.9,
    )

    upgraded = AnalysisVersion(
        detector_version=VERSION.detector_version,
        pipeline_version=VERSION.pipeline_version,
        model_id=VERSION.model_id,
        model_revision="rev-2",
    )
    pending_under_new_version = repo.list_pending_for_analysis(
        tenant_id=tenant_id, connection_id=connection_id, version=upgraded
    )
    assert any(p.message_id == message_id for p in pending_under_new_version)

    second = repo.record_sentiment_result(
        tenant_id=tenant_id,
        connection_id=connection_id,
        message_id=message_id,
        source_id=source_id,
        version=upgraded,
        label="NEG",
        score=0.2,
    )
    assert second is True

    with tenant_session(tenant_id) as session:
        count = session.execute(
            text("SELECT count(*) FROM comment_sentiment_results WHERE message_id = :mid"),
            {"mid": str(message_id)},
        ).scalar_one()
    assert count == 2  # both versions coexist


def test_tenant_isolation_a_tenant_cannot_see_another_tenants_results() -> None:
    conn_a, message_a, source_a = _seed_message(TENANT_S)
    conn_b, message_b, source_b = _seed_message(TENANT_S2)
    repo = PostgresSentimentRepository()

    repo.record_sentiment_result(
        tenant_id=TENANT_S,
        connection_id=conn_a,
        message_id=message_a,
        source_id=source_a,
        version=VERSION,
        label="POS",
        score=0.9,
    )
    repo.record_sentiment_result(
        tenant_id=TENANT_S2,
        connection_id=conn_b,
        message_id=message_b,
        source_id=source_b,
        version=VERSION,
        label="NEG",
        score=0.9,
    )

    # TENANT_S2's pending list must never include TENANT_S's message, even though both
    # were just recorded — RLS scopes every read.
    pending_for_s2 = repo.list_pending_for_analysis(
        tenant_id=TENANT_S2, connection_id=conn_b, version=VERSION
    )
    assert not any(p.message_id == message_a for p in pending_for_s2)

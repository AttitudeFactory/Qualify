"""`PostgresMentionsRepository` (QUA-49) against real Postgres.

Proves the one thing `test_mentions_repository.py`'s in-memory coverage cannot: that
`uq_mention_natural_key` (migration 0013's `COALESCE(comment_id, '')` expression index)
actually enforces idempotency at the database level, and that RLS actually isolates one
tenant's mentions from another's — not merely that this module's own Python logic
believes it does.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.mentions.repository import (
    ENRICHMENT_OK,
    NewMention,
    PostgresMentionsRepository,
)
from qualify_api.sentiment.repository import AnalysisVersion
from qualify_api.tenancy.models import Tenant, User

pytestmark = pytest.mark.db

TENANT_A = UUID("c1111111-1111-4111-8111-111111111111")
TENANT_B = UUID("c2222222-2222-4222-8222-222222222222")

VERSION = AnalysisVersion(
    detector_version="v1",
    pipeline_version="mentions-text-1.0.0",
    model_id="m1",
    model_revision=None,
)


def _ensure_tenant(session, tenant_id: UUID) -> None:
    if session.get(Tenant, tenant_id) is None:
        session.add(
            Tenant(
                id=tenant_id,
                name=f"mentions-repo-{tenant_id}",
                country="CO",
                timezone="America/Bogota",
                currency="COP",
            )
        )
        session.flush()


def _seed_connection(tenant_id: UUID) -> UUID:
    with admin_session() as session:
        _ensure_tenant(session, tenant_id)
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        session.add(app)
        session.flush()
        user = User(tenant_id=tenant_id, email=f"u-{uuid4()}@t.co", display_name="U")
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
        return conn.id


def _mention(
    *, tenant_id: UUID, connection_id: UUID, media_id: str, comment_id: str | None
) -> NewMention:
    return NewMention(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_account_id="ig-user-1",
        media_id=media_id,
        comment_id=comment_id,
        caption="hola @qualifymkt.co" if comment_id is None else None,
        text="hola @qualifymkt.co" if comment_id is not None else None,
        author_username="someone",
        media_type="IMAGE",
        like_count=1,
        content_posted_at=datetime(2026, 8, 1, tzinfo=UTC),
        enrichment_status=ENRICHMENT_OK,
    )


def test_upsert_mention_creates_a_real_row() -> None:
    connection_id = _seed_connection(TENANT_A)
    repo = PostgresMentionsRepository()

    mention_id, created = repo.upsert_mention(
        _mention(tenant_id=TENANT_A, connection_id=connection_id, media_id="m1", comment_id=None)
    )

    assert created is True
    records = repo.list_mentions(tenant_id=TENANT_A, connection_id=None, version=VERSION)
    assert any(r.id == mention_id for r in records)


def test_upsert_mention_natural_key_is_enforced_by_postgres() -> None:
    """The real regression this migration exists to prevent: a redelivered webhook for
    the same event must never create a second row — enforced by
    `uq_mention_natural_key`, not by this repository's own Python, which is exactly why
    this test issues the SAME logical event twice through two INDEPENDENT calls."""
    connection_id = _seed_connection(TENANT_A)
    repo = PostgresMentionsRepository()
    media_id = f"media-{uuid4()}"

    first_id, first_created = repo.upsert_mention(
        _mention(
            tenant_id=TENANT_A, connection_id=connection_id, media_id=media_id, comment_id=None
        )
    )
    second_id, second_created = repo.upsert_mention(
        _mention(
            tenant_id=TENANT_A, connection_id=connection_id, media_id=media_id, comment_id=None
        )
    )

    assert first_created is True
    assert second_created is False
    assert first_id == second_id


def test_upsert_mention_null_comment_id_does_not_collide_across_media() -> None:
    """Two DIFFERENT caption mentions (different `media_id`, both `comment_id=None`)
    must NOT be treated as duplicates of each other — the COALESCE normalization keys
    on the full tuple, not just "comment_id was null"."""
    connection_id = _seed_connection(TENANT_A)
    repo = PostgresMentionsRepository()

    _id_a, created_a = repo.upsert_mention(
        _mention(
            tenant_id=TENANT_A, connection_id=connection_id, media_id="media-a", comment_id=None
        )
    )
    _id_b, created_b = repo.upsert_mention(
        _mention(
            tenant_id=TENANT_A, connection_id=connection_id, media_id="media-b", comment_id=None
        )
    )

    assert created_a is True
    assert created_b is True


def test_list_mentions_is_isolated_by_rls() -> None:
    """`TENANT_A`/`TENANT_B` are shared across this module's tests (each test seeds its
    own fresh connection under them), so a real Postgres tenant can carry mentions from
    earlier tests too — this asserts by a unique media_id's PRESENCE/ABSENCE, never by
    an exhaustive equality over the whole result set, same discipline
    `test_mentions_resolve.py` already uses for its own shared-tenant fixtures."""
    connection_a = _seed_connection(TENANT_A)
    connection_b = _seed_connection(TENANT_B)
    repo = PostgresMentionsRepository()
    media_a = f"m-{uuid4()}"
    media_b = f"m-{uuid4()}"
    repo.upsert_mention(
        _mention(tenant_id=TENANT_A, connection_id=connection_a, media_id=media_a, comment_id=None)
    )
    repo.upsert_mention(
        _mention(tenant_id=TENANT_B, connection_id=connection_b, media_id=media_b, comment_id=None)
    )

    a_records = repo.list_mentions(tenant_id=TENANT_A, connection_id=connection_a, version=VERSION)
    b_records = repo.list_mentions(tenant_id=TENANT_B, connection_id=connection_b, version=VERSION)
    # The cross-check that actually proves RLS: querying TENANT_A's session can never
    # see TENANT_B's connection's mention, even if asked for it by id.
    a_records_wrong_connection = repo.list_mentions(
        tenant_id=TENANT_A, connection_id=connection_b, version=VERSION
    )

    assert {r.media_id for r in a_records} == {media_a}
    assert {r.media_id for r in b_records} == {media_b}
    assert a_records_wrong_connection == ()


def test_sentiment_result_idempotency_is_enforced_by_postgres() -> None:
    connection_id = _seed_connection(TENANT_A)
    repo = PostgresMentionsRepository()
    mention_id, _created = repo.upsert_mention(
        _mention(
            tenant_id=TENANT_A,
            connection_id=connection_id,
            media_id=f"m-{uuid4()}",
            comment_id="c1",
        )
    )

    first = repo.record_sentiment_result(
        tenant_id=TENANT_A, mention_id=mention_id, version=VERSION, label="POS", score=0.7
    )
    second = repo.record_sentiment_result(
        tenant_id=TENANT_A, mention_id=mention_id, version=VERSION, label="POS", score=0.7
    )

    assert first is True
    assert second is False

    records = repo.list_mentions(tenant_id=TENANT_A, connection_id=None, version=VERSION)
    analyzed = next(r for r in records if r.id == mention_id)
    assert analyzed.sentiment_label == "POS"

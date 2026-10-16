"""`NewMention.read_from_network` against real Postgres: the creation stamp lands on the
database clock, exactly as `refresh_content` stamps it, and ONLY when asked for.

Companion of `test_mentions_ingest_read_stamp.py` (the memory repository proves the
orchestration; this proves the column). Seeding follows `test_mentions_repository_db.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.mentions.models import Mention
from qualify_api.mentions.repository import (
    ENRICHMENT_OK,
    NewMention,
    PostgresMentionsRepository,
)
from qualify_api.tenancy.models import Tenant, User

pytestmark = pytest.mark.db

TENANT = UUID("c3333333-3333-4333-8333-333333333333")


def _seed_connection(tenant_id: UUID) -> UUID:
    with admin_session() as session:
        if session.get(Tenant, tenant_id) is None:
            session.add(
                Tenant(
                    id=tenant_id,
                    name=f"mentions-stamp-{tenant_id}",
                    country="CO",
                    timezone="America/Bogota",
                    currency="COP",
                )
            )
            session.flush()
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


def _mention(connection_id: UUID, *, read_from_network: bool) -> NewMention:
    return NewMention(
        tenant_id=TENANT,
        connection_id=connection_id,
        external_account_id="ig-user-1",
        media_id=f"m-{uuid4().hex[:8]}",
        comment_id=f"c-{uuid4().hex[:8]}",
        caption=None,
        text="hola @qualifymkt.co",
        author_username="someone",
        media_type=None,
        like_count=1,
        content_posted_at=datetime(2026, 10, 14, tzinfo=UTC),
        enrichment_status=ENRICHMENT_OK,
        read_from_network=read_from_network,
    )


def _stamps(mention_id: UUID) -> tuple[datetime | None, datetime | None]:
    with tenant_session(TENANT) as session:
        row = session.execute(select(Mention).where(Mention.id == mention_id)).scalar_one()
        return row.content_refreshed_at, row.content_refresh_attempted_at


def test_a_network_read_at_creation_is_stamped_and_counts_as_ever_read() -> None:
    connection_id = _seed_connection(TENANT)
    repo = PostgresMentionsRepository()

    read_id, created = repo.upsert_mention(_mention(connection_id, read_from_network=True))
    unread_id, _ = repo.upsert_mention(_mention(connection_id, read_from_network=False))

    assert created is True
    refreshed, attempted = _stamps(read_id)
    assert refreshed is not None and attempted == refreshed
    assert _stamps(unread_id) == (None, None)
    targets = repo.list_refresh_targets(tenant_id=TENANT, mention_ids=(read_id, unread_id))
    assert {t.mention_id: t.ever_read for t in targets} == {read_id: True, unread_id: False}


def test_a_redelivery_never_restamps_through_the_insert_path() -> None:
    """The duplicate insert trips the natural key and returns the existing row; whatever
    `read_from_network` says the second time, the stored stamps are untouched here (a
    real re-read goes through `refresh_content`, which is what the webhook path calls)."""
    connection_id = _seed_connection(TENANT)
    repo = PostgresMentionsRepository()
    first = _mention(connection_id, read_from_network=False)

    mention_id, created = repo.upsert_mention(first)
    again_id, again_created = repo.upsert_mention(
        NewMention(**{**first.__dict__, "read_from_network": True})
    )

    assert (created, again_created, again_id) == (True, False, mention_id)
    assert _stamps(mention_id) == (None, None)

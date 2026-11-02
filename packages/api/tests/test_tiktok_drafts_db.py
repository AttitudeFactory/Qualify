"""`db`-marked tests for migration 0109 (m-24921091): TikTok connections without a Page,
`tiktok_drafts` RLS / idempotency / settle-once, and append-only credential rotation."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy.exc import DBAPIError, IntegrityError

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.connections.tiktok_credentials import PostgresTikTokCredentialRotator
from qualify_api.publishing.tiktok_drafts import PostgresTikTokDraftRepository
from qualify_api.tenancy.models import Tenant, User

pytestmark = pytest.mark.db

TENANT_A = UUID("e1000000-0000-4000-8000-0000000000a1")
TENANT_B = UUID("e1000000-0000-4000-8000-0000000000b1")


def _tenant_with_user(tenant_id: UUID) -> tuple[UUID, UUID]:
    with admin_session() as session:
        if session.get(Tenant, tenant_id) is None:
            session.add(
                Tenant(
                    id=tenant_id,
                    name=f"t-tiktok-{tenant_id.hex[:6]}",
                    country="CO",
                    timezone="America/Bogota",
                    currency="COP",
                )
            )
            session.flush()
        app = PlatformApp(app_id=f"tt-{uuid4()}", secret_ref="ref", api_version="v2")
        user = User(tenant_id=tenant_id, email=f"u-{uuid4()}@t.co", display_name="U")
        session.add_all([app, user])
        session.flush()
        return app.id, user.id


def _tiktok_connection(tenant_id: UUID, platform: str = "tiktok") -> tuple[UUID, UUID]:
    app_id, user_id = _tenant_with_user(tenant_id)
    with tenant_session(tenant_id) as session:
        conn = SocialConnection(
            tenant_id=tenant_id,
            platform_app_id=app_id,
            platform=platform,
            account_type="creator",
            external_account_id=f"open-{uuid4()}",
            linked_page_id=None,
            granted_scopes=["video.upload"],
            status="active",
            access_posture="development",
            current_credential_version=1,
            connected_by_user_id=user_id,
        )
        session.add(conn)
        session.flush()
        return conn.id, user_id


def test_tiktok_connection_needs_no_page_but_instagram_still_does() -> None:
    _tiktok_connection(TENANT_A)  # must not raise
    with pytest.raises(IntegrityError):
        _tiktok_connection(TENANT_A, platform="instagram")


def _create(repo, tenant, conn, user, key="k1"):
    return repo.create_or_get(
        tenant_id=tenant,
        connection_id=conn,
        post_id=uuid4(),
        output_port=None,
        approved_revision=1,
        idempotency_key=key,
        upload_mode="FILE_UPLOAD",
        media_object_key=f"t/{tenant}/v.mp4",
        caption="c",
        user_id=user,
    )


def test_idempotent_create_rls_and_settle_once() -> None:
    repo = PostgresTikTokDraftRepository()
    conn, user = _tiktok_connection(TENANT_A)
    first, created = _create(repo, TENANT_A, conn, user)
    again, created_again = _create(repo, TENANT_A, conn, user)
    assert created and not created_again and first.id == again.id

    # another tenant cannot read it
    assert repo.get(tenant_id=TENANT_B, draft_id=first.id) is None

    repo.update(tenant_id=TENANT_A, draft_id=first.id, status="uploading", publish_id="p1")
    repo.update(tenant_id=TENANT_A, draft_id=first.id, status="in_inbox")
    # terminal is final: the repository ignores it and the trigger would refuse it
    repo.update(tenant_id=TENANT_A, draft_id=first.id, status="failed", platform_error_code="x")
    final = repo.get(tenant_id=TENANT_A, draft_id=first.id)
    assert final is not None and final.status == "in_inbox" and final.settled
    assert final.publish_id == "p1"

    with pytest.raises(DBAPIError), tenant_session(TENANT_A) as session:
        session.execute(
            __import__("sqlalchemy").text(
                "UPDATE tiktok_drafts SET status='failed', settled_at=now() WHERE id=:i"
            ),
            {"i": str(first.id)},
        )


def test_rotation_appends_a_version_and_refuses_a_stale_pointer() -> None:
    rotator = PostgresTikTokCredentialRotator()
    conn, _ = _tiktok_connection(TENANT_A)
    now = datetime.now(UTC)
    assert rotator.current_version(tenant_id=TENANT_A, connection_id=conn) == 1
    new = rotator.rotate(
        tenant_id=TENANT_A,
        connection_id=conn,
        expected_version=1,
        ciphertext=b"c",
        key_id="k",
        issued_at=now,
        expires_at=now,
    )
    assert new == 2
    stale = rotator.rotate(
        tenant_id=TENANT_A,
        connection_id=conn,
        expected_version=1,
        ciphertext=b"c",
        key_id="k",
        issued_at=now,
        expires_at=now,
    )
    assert stale is None
    assert rotator.current_version(tenant_id=TENANT_B, connection_id=conn) is None  # RLS

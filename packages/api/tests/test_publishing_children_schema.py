"""`db`-marked schema tests for migration 0016 (QUA-99, 2/6) — `publish_attempt_children`.

Schema only, same posture `test_publishing_inbox_schema.py` takes for 0003/0004: these
assert what the DATABASE enforces, not what a repository remembers to do. This table is
not read or written by any service/repository code yet (that is commits 3/6 and 4/6) —
these tests insert raw SQL rows directly, the way `test_publishing_inbox_schema.py`
already does for `publish_attempts`/`messages`.

VIDEO-ONLY scope, pinned by test: `media_product_type` accepts only the three values
`publish_attempts` already accepts. No IMAGE value exists in this migration.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.tenancy.models import Tenant, User

pytestmark = pytest.mark.db

TENANT_P = UUID("e0000000-0000-4000-8000-0000000000c1")
OTHER_TENANT = UUID("e0000000-0000-4000-8000-0000000000c2")


@pytest.fixture
def seeded_connection() -> tuple[UUID, UUID]:
    """(tenant_id, connection_id) — same two-door split every publishing schema test uses."""
    with admin_session() as session:
        if session.get(Tenant, TENANT_P) is None:
            session.add(
                Tenant(
                    id=TENANT_P,
                    name="t-publishing-children",
                    country="CO",
                    timezone="America/Bogota",
                    currency="COP",
                )
            )
            session.flush()
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        session.add(app)
        session.flush()
        user = User(tenant_id=TENANT_P, email=f"u-{uuid4()}@p.co", display_name="U")
        session.add(user)
        session.flush()
        app_id, user_id = app.id, user.id

    with tenant_session(TENANT_P) as session:
        conn = SocialConnection(
            tenant_id=TENANT_P,
            platform_app_id=app_id,
            platform="instagram",
            account_type="business",
            external_account_id=f"ig-{uuid4()}",
            linked_page_id="page-1",
            granted_scopes=["basic"],
            status="pending",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=user_id,
        )
        session.add(conn)
        session.flush()
        connection_id = conn.id
    return TENANT_P, connection_id


def _insert_attempt(session, tenant_id: UUID, connection_id: UUID) -> UUID:
    return session.execute(
        text(
            "INSERT INTO publish_attempts "
            "(tenant_id, connection_id, idempotency_key, media_product_type, "
            " adapter_version, status) "
            "VALUES (:tid, :cid, :key, 'CAROUSEL', 'v1', 'pending') RETURNING id"
        ),
        {"tid": str(tenant_id), "cid": str(connection_id), "key": f"key-{uuid4()}"},
    ).scalar_one()


def _insert_child(
    session,
    tenant_id: UUID,
    attempt_id: UUID,
    position: int,
    *,
    media_product_type: str = "VIDEO",
    status: str = "pending",
) -> UUID:
    return session.execute(
        text(
            "INSERT INTO publish_attempt_children "
            "(tenant_id, attempt_id, position, media_object_key, media_content_type, "
            " media_product_type, status) "
            "VALUES (:tid, :aid, :pos, :key, 'video/mp4', :mpt, :status) RETURNING id"
        ),
        {
            "tid": str(tenant_id),
            "aid": str(attempt_id),
            "pos": position,
            "key": f"t/{tenant_id}/child-{uuid4()}",
            "mpt": media_product_type,
            "status": status,
        },
    ).scalar_one()


# --------------------------------------------------------------------------------------
# VIDEO-ONLY scope
# --------------------------------------------------------------------------------------


def test_video_media_product_types_are_accepted(seeded_connection: tuple[UUID, UUID]) -> None:
    tenant_id, connection_id = seeded_connection
    with tenant_session(tenant_id) as session:
        attempt_id = _insert_attempt(session, tenant_id, connection_id)
        for i, media_type in enumerate(("REELS", "STORIES", "VIDEO")):
            _insert_child(session, tenant_id, attempt_id, i, media_product_type=media_type)


def test_image_media_product_type_is_rejected(seeded_connection: tuple[UUID, UUID]) -> None:
    """QUA-99 is video-only in this PR — IMAGE has no code path yet, and the schema
    itself refuses to store one, not just the (nonexistent) service layer."""
    tenant_id, connection_id = seeded_connection
    with pytest.raises(IntegrityError):
        with tenant_session(tenant_id) as session:
            attempt_id = _insert_attempt(session, tenant_id, connection_id)
            _insert_child(session, tenant_id, attempt_id, 0, media_product_type="IMAGE")


def test_an_unrecognised_media_product_type_is_rejected(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    tenant_id, connection_id = seeded_connection
    with pytest.raises(IntegrityError):
        with tenant_session(tenant_id) as session:
            attempt_id = _insert_attempt(session, tenant_id, connection_id)
            _insert_child(session, tenant_id, attempt_id, 0, media_product_type="GIF")


# --------------------------------------------------------------------------------------
# status vocabulary
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["pending", "uploading", "processing", "finished", "failed"])
def test_every_documented_child_status_is_accepted(
    seeded_connection: tuple[UUID, UUID], status: str
) -> None:
    tenant_id, connection_id = seeded_connection
    with tenant_session(tenant_id) as session:
        attempt_id = _insert_attempt(session, tenant_id, connection_id)
        _insert_child(session, tenant_id, attempt_id, 0, status=status)


def test_an_unrecognised_status_is_rejected(seeded_connection: tuple[UUID, UUID]) -> None:
    tenant_id, connection_id = seeded_connection
    with pytest.raises(IntegrityError):
        with tenant_session(tenant_id) as session:
            attempt_id = _insert_attempt(session, tenant_id, connection_id)
            # "published" is a publish_attempts status, never a child's.
            _insert_child(session, tenant_id, attempt_id, 0, status="published")


# --------------------------------------------------------------------------------------
# position — display order, one slot per attempt
# --------------------------------------------------------------------------------------


def test_two_children_cannot_share_a_position_in_the_same_attempt(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    """A carousel's display order is `children`'s order at creation time — two rows
    claiming the same slot would leave that order ambiguous."""
    tenant_id, connection_id = seeded_connection
    with tenant_session(tenant_id) as session:
        attempt_id = _insert_attempt(session, tenant_id, connection_id)
        _insert_child(session, tenant_id, attempt_id, 0)

    with pytest.raises(IntegrityError):
        with tenant_session(tenant_id) as session:
            _insert_child(session, tenant_id, attempt_id, 0)


def test_the_same_position_is_fine_across_different_attempts(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    """The uniqueness is scoped to (attempt_id, position), not a global slot counter."""
    tenant_id, connection_id = seeded_connection
    with tenant_session(tenant_id) as session:
        attempt_a = _insert_attempt(session, tenant_id, connection_id)
        attempt_b = _insert_attempt(session, tenant_id, connection_id)
        _insert_child(session, tenant_id, attempt_a, 0)
        _insert_child(session, tenant_id, attempt_b, 0)  # must not conflict


# --------------------------------------------------------------------------------------
# composite FK — a child cannot disagree with its parent attempt's tenant
# --------------------------------------------------------------------------------------


def test_a_child_requires_an_existing_attempt_in_the_same_tenant(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    tenant_id, _connection_id = seeded_connection
    with pytest.raises(IntegrityError):
        with tenant_session(tenant_id) as session:
            _insert_child(session, tenant_id, uuid4(), 0)  # no such attempt at all


# --------------------------------------------------------------------------------------
# no settle-once guard — a design decision this migration deliberately makes
# --------------------------------------------------------------------------------------


def test_a_child_row_can_be_updated_repeatedly_without_a_settle_once_trigger(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    """Unlike `publish_attempts`, nothing here is ever hand to `media_publish` — a child
    reaching 'finished' is not an irreversible fact worth guarding with a trigger the way
    `publish_attempts_settle_once` guards a real publish outcome. Pinned so a future
    reader does not assume one exists."""
    tenant_id, connection_id = seeded_connection
    with tenant_session(tenant_id) as session:
        attempt_id = _insert_attempt(session, tenant_id, connection_id)
        child_id = _insert_child(session, tenant_id, attempt_id, 0)

    for status in ("uploading", "processing", "finished"):
        with tenant_session(tenant_id) as session:
            session.execute(
                text("UPDATE publish_attempt_children SET status = :s WHERE id = :id"),
                {"s": status, "id": str(child_id)},
            )
    with tenant_session(tenant_id) as session:
        final_status = session.execute(
            text("SELECT status FROM publish_attempt_children WHERE id = :id"),
            {"id": str(child_id)},
        ).scalar_one()
    assert final_status == "finished"


# --------------------------------------------------------------------------------------
# RLS
# --------------------------------------------------------------------------------------


def test_rls_makes_another_tenants_children_invisible(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    tenant_id, connection_id = seeded_connection
    with tenant_session(tenant_id) as session:
        attempt_id = _insert_attempt(session, tenant_id, connection_id)
        _insert_child(session, tenant_id, attempt_id, 0)

    with tenant_session(OTHER_TENANT) as session:
        rows = session.execute(
            text("SELECT id FROM publish_attempt_children WHERE attempt_id = :aid"),
            {"aid": str(attempt_id)},
        ).all()
    assert rows == []

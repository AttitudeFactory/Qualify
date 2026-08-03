"""`db`-marked schema tests for migrations 0003/0004 (QUA-19 / QUA-20).

These assert the guarantees the ARCHITECT made conditions of sign-off, at the layer that
actually enforces them — the database. A repository that remembers to write
`WHERE settled_at IS NULL` is a convention; a trigger that refuses is a guarantee, and the
difference only shows up when a second code path (a backfill, a psql session, a future
worker) does the wrong thing.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.tenancy.models import Tenant, User

pytestmark = pytest.mark.db

TENANT_P = UUID("e0000000-0000-4000-8000-0000000000f1")


@pytest.fixture
def seeded_connection() -> tuple[UUID, UUID, UUID]:
    """(tenant_id, connection_id, user_id) — same two-door split as C-03's schema tests."""
    with admin_session() as session:
        if session.get(Tenant, TENANT_P) is None:
            session.add(
                Tenant(
                    id=TENANT_P,
                    name="t-publishing",
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
    return TENANT_P, connection_id, user_id


def _insert_attempt(session, connection_id: UUID, key: str, *, settled: bool = False) -> UUID:
    # `now()` is interpolated as SQL, not bound as a parameter. Binding the STRING "now()"
    # happens to work — Postgres coerces it — but a test whose setup depends on an obscure
    # coercion is a test whose green cannot be trusted at a glance.
    settled_at = "now()" if settled else "NULL"
    status = "published" if settled else "pending"
    return session.execute(
        text(
            "INSERT INTO publish_attempts "
            "(tenant_id, connection_id, idempotency_key, media_product_type, "
            " adapter_version, status, settled_at) "
            f"VALUES (:tid, :cid, :key, 'REELS', 'v1', :status, {settled_at}) RETURNING id"
        ),
        {"tid": str(TENANT_P), "cid": str(connection_id), "key": key, "status": status},
    ).scalar_one()


# --------------------------------------------------------------------------------------
# publish_attempts — the write-ahead record
# --------------------------------------------------------------------------------------


def test_a_settled_attempt_cannot_be_updated(
    seeded_connection: tuple[UUID, UUID, UUID],
) -> None:
    """The architect's condition on row-per-attempt-with-UPDATE. A late reconciliation must
    not overwrite an already-settled outcome with stale information — the exact failure
    ADR 22(e) exists to prevent."""
    _, connection_id, _ = seeded_connection
    with tenant_session(TENANT_P) as session:
        attempt_id = _insert_attempt(session, connection_id, f"key-{uuid4()}", settled=True)

    with pytest.raises(DBAPIError):  # raised by the settle_once trigger
        with tenant_session(TENANT_P) as session:
            session.execute(
                text("UPDATE publish_attempts SET status = 'failed' WHERE id = :id"),
                {"id": str(attempt_id)},
            )


def test_an_unsettled_attempt_can_still_be_updated(
    seeded_connection: tuple[UUID, UUID, UUID],
) -> None:
    """The guard must not be so blunt that it forbids the normal path: an in-flight attempt
    is updated repeatedly as it moves through upload and processing."""
    _, connection_id, _ = seeded_connection
    with tenant_session(TENANT_P) as session:
        attempt_id = _insert_attempt(session, connection_id, f"key-{uuid4()}")

    with tenant_session(TENANT_P) as session:
        session.execute(
            text("UPDATE publish_attempts SET creation_id = 'ig-container-1' WHERE id = :id"),
            {"id": str(attempt_id)},
        )
        assert (
            session.execute(
                text("SELECT creation_id FROM publish_attempts WHERE id = :id"),
                {"id": str(attempt_id)},
            ).scalar_one()
            == "ig-container-1"
        )


def test_settling_an_unsettled_attempt_is_allowed_once(
    seeded_connection: tuple[UUID, UUID, UUID],
) -> None:
    """The transition INTO settled is legal; only a second one is not. Without this the
    trigger would make the terminal state unreachable."""
    _, connection_id, _ = seeded_connection
    with tenant_session(TENANT_P) as session:
        attempt_id = _insert_attempt(session, connection_id, f"key-{uuid4()}")

    with tenant_session(TENANT_P) as session:
        session.execute(
            text(
                "UPDATE publish_attempts SET status='published', settled_at=now(), "
                "published_media_id='ig-media-1' WHERE id = :id"
            ),
            {"id": str(attempt_id)},
        )

    with pytest.raises(DBAPIError):
        with tenant_session(TENANT_P) as session:
            session.execute(
                text("UPDATE publish_attempts SET published_media_id='ig-media-2' WHERE id = :id"),
                {"id": str(attempt_id)},
            )


def test_idempotency_key_is_unique_per_connection(
    seeded_connection: tuple[UUID, UUID, UUID],
) -> None:
    """What makes "retry safely" implementable: the same key cannot open a second attempt."""
    _, connection_id, _ = seeded_connection
    key = f"key-{uuid4()}"
    with tenant_session(TENANT_P) as session:
        _insert_attempt(session, connection_id, key)

    with pytest.raises(IntegrityError):
        with tenant_session(TENANT_P) as session:
            _insert_attempt(session, connection_id, key)


def test_settled_at_and_status_cannot_disagree(
    seeded_connection: tuple[UUID, UUID, UUID],
) -> None:
    """A row claiming to be settled while still 'pending' would make reconciliation read two
    contradictory answers off one row."""
    _, connection_id, _ = seeded_connection
    with pytest.raises(IntegrityError):
        with tenant_session(TENANT_P) as session:
            session.execute(
                text(
                    "INSERT INTO publish_attempts "
                    "(tenant_id, connection_id, idempotency_key, media_product_type, "
                    " adapter_version, status, settled_at) "
                    "VALUES (:tid, :cid, :key, 'REELS', 'v1', 'pending', now())"
                ),
                {"tid": str(TENANT_P), "cid": str(connection_id), "key": f"key-{uuid4()}"},
            )


# --------------------------------------------------------------------------------------
# messages — the dedup guarantee
# --------------------------------------------------------------------------------------


def _insert_thread(session, connection_id: UUID, external_id: str) -> UUID:
    return session.execute(
        text(
            "INSERT INTO threads (tenant_id, connection_id, channel, external_thread_id, status) "
            "VALUES (:tid, :cid, 'comment', :ext, 'open') RETURNING id"
        ),
        {"tid": str(TENANT_P), "cid": str(connection_id), "ext": external_id},
    ).scalar_one()


def _insert_message(session, thread_id: UUID, connection_id: UUID, external_id: str) -> None:
    session.execute(
        text(
            "INSERT INTO messages (tenant_id, thread_id, connection_id, external_message_id, "
            " direction, shape_version) "
            "VALUES (:tid, :thid, :cid, :ext, 'inbound', 'ig-comment-shapes-1.0.0')"
        ),
        {
            "tid": str(TENANT_P),
            "thid": str(thread_id),
            "cid": str(connection_id),
            "ext": external_id,
        },
    )


def test_the_same_message_delivered_twice_does_not_duplicate(
    seeded_connection: tuple[UUID, UUID, UUID],
) -> None:
    """QUA-20's dedup criterion, at the layer that enforces it. This is the constraint the
    upsert will target with ON CONFLICT — without it, a re-poll silently doubles a thread."""
    _, connection_id, _ = seeded_connection
    external_id = f"comment-{uuid4()}"
    with tenant_session(TENANT_P) as session:
        thread_id = _insert_thread(session, connection_id, f"thread-{uuid4()}")
        _insert_message(session, thread_id, connection_id, external_id)

    with pytest.raises(IntegrityError):
        with tenant_session(TENANT_P) as session:
            _insert_message(session, thread_id, connection_id, external_id)


def test_a_message_may_arrive_without_author_or_timestamp(
    seeded_connection: tuple[UUID, UUID, UUID],
) -> None:
    """Nullability derived from the QUA-67 contract, not guessed: `from`/`username` are
    REQUIRES_PERMISSION (absent without `instagram_manage_comments`) and `timestamp` is
    IF_REQUESTED. A NOT NULL here would reject payloads Meta legitimately sends."""
    _, connection_id, _ = seeded_connection
    with tenant_session(TENANT_P) as session:
        thread_id = _insert_thread(session, connection_id, f"thread-{uuid4()}")
        _insert_message(session, thread_id, connection_id, f"comment-{uuid4()}")
        row = session.execute(
            text(
                "SELECT author_external_id, author_username, posted_at, ingested_at "
                "FROM messages WHERE thread_id = :thid"
            ),
            {"thid": str(thread_id)},
        ).one()
    assert row.author_external_id is None and row.author_username is None
    assert row.posted_at is None
    # `ingested_at` is always known, so ordering never has to invent a timestamp.
    assert row.ingested_at is not None


def test_threads_carry_a_separate_inbound_clock(
    seeded_connection: tuple[UUID, UUID, UUID],
) -> None:
    """The messaging window derives from `last_inbound_at`, never `last_message_at`: replying
    does NOT extend Meta's 24 h window (`overview.md:178`). Both columns must therefore exist
    and be independently settable, or a reply would silently reopen a closed window."""
    _, connection_id, _ = seeded_connection
    with tenant_session(TENANT_P) as session:
        thread_id = _insert_thread(session, connection_id, f"thread-{uuid4()}")
        session.execute(
            text(
                "UPDATE threads SET last_message_at = now(), last_inbound_at = NULL WHERE id = :id"
            ),
            {"id": str(thread_id)},
        )
        row = session.execute(
            text("SELECT last_message_at, last_inbound_at FROM threads WHERE id = :id"),
            {"id": str(thread_id)},
        ).one()
    # An outbound-only thread: activity exists, but no window was ever opened. NULL here means
    # "no window", which is NOT "window expired" (R10) — the two must stay distinguishable.
    assert row.last_message_at is not None
    assert row.last_inbound_at is None

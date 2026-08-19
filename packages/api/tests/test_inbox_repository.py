"""`db`-marked tests for `PostgresInboxRepository` — the three idempotency/accounting
guarantees this module translates, exercised against the real constraints from
0004/0005/0010. Same `seeded_connection` shape as `test_publishing_inbox_schema.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from qualify_shared.social.ig_shapes import IGComment
from sqlalchemy import text

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.inbox.repository import PostgresInboxRepository
from qualify_api.tenancy.models import Tenant, User

pytestmark = pytest.mark.db

TENANT_I = UUID("e0000000-0000-4000-8000-0000000000f2")


@pytest.fixture
def seeded_connection() -> tuple[UUID, UUID]:
    """(tenant_id, connection_id) — same two-door split as the publishing/inbox schema tests."""
    with admin_session() as session:
        if session.get(Tenant, TENANT_I) is None:
            session.add(
                Tenant(
                    id=TENANT_I,
                    name="t-inbox",
                    country="CO",
                    timezone="America/Bogota",
                    currency="COP",
                )
            )
            session.flush()
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        session.add(app)
        session.flush()
        user = User(tenant_id=TENANT_I, email=f"u-{uuid4()}@i.co", display_name="U")
        session.add(user)
        session.flush()
        app_id = app.id

    with tenant_session(TENANT_I) as session:
        conn = SocialConnection(
            tenant_id=TENANT_I,
            platform_app_id=app_id,
            platform="instagram",
            account_type="business",
            external_account_id=f"ig-{uuid4()}",
            linked_page_id="page-1",
            granted_scopes=["basic"],
            status="active",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=user.id,
        )
        session.add(conn)
        session.flush()
        connection_id = conn.id
    return TENANT_I, connection_id


def _second_connection(tenant_id: UUID) -> UUID:
    """A second `social_connections` row under the SAME tenant — for the ledger's
    per-connection isolation test, where `seeded_connection`'s single row is not enough.
    Mirrors `seeded_connection`'s own setup rather than factoring it out, matching this
    file's existing amount of duplication between its two connection-creation blocks."""
    with admin_session() as session:
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        session.add(app)
        session.flush()
        user = User(tenant_id=tenant_id, email=f"u-{uuid4()}@i.co", display_name="U2")
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
            linked_page_id="page-2",
            granted_scopes=["basic"],
            status="active",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=user_id,
        )
        session.add(conn)
        session.flush()
        return conn.id


def _monitored_row_count(connection_id: UUID, media_id: str) -> int:
    with tenant_session(TENANT_I) as session:
        return session.execute(
            text(
                "SELECT count(*) FROM monitored_media "
                "WHERE connection_id = :cid AND external_media_id = :mid"
            ),
            {"cid": str(connection_id), "mid": media_id},
        ).scalar_one()


def _message_row_count(connection_id: UUID, external_message_id: str) -> int:
    with tenant_session(TENANT_I) as session:
        return session.execute(
            text(
                "SELECT count(*) FROM messages "
                "WHERE connection_id = :cid AND external_message_id = :mid"
            ),
            {"cid": str(connection_id), "mid": external_message_id},
        ).scalar_one()


# --------------------------------------------------------------------------------------
# monitored_media — toggle is an UPDATE, never a second row
# --------------------------------------------------------------------------------------


def test_toggling_monitoring_on_then_off_never_creates_a_second_row(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    tenant_id, connection_id = seeded_connection
    repo = PostgresInboxRepository()
    media_id = f"media-{uuid4()}"

    repo.set_media_monitored(
        tenant_id=tenant_id, connection_id=connection_id, external_media_id=media_id, monitored=True
    )
    repo.set_media_monitored(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        monitored=False,
    )
    repo.set_media_monitored(
        tenant_id=tenant_id, connection_id=connection_id, external_media_id=media_id, monitored=True
    )

    assert _monitored_row_count(connection_id, media_id) == 1


def test_list_monitored_media_ids_excludes_disabled_ones(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    tenant_id, connection_id = seeded_connection
    repo = PostgresInboxRepository()
    on_media, off_media = f"media-{uuid4()}", f"media-{uuid4()}"

    repo.set_media_monitored(
        tenant_id=tenant_id, connection_id=connection_id, external_media_id=on_media, monitored=True
    )
    repo.set_media_monitored(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=off_media,
        monitored=True,
    )
    repo.set_media_monitored(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=off_media,
        monitored=False,
    )

    monitored = repo.list_monitored_media_ids(tenant_id=tenant_id, connection_id=connection_id)
    assert monitored == frozenset({on_media})


# --------------------------------------------------------------------------------------
# upsert_comment — the dedup guarantee, plus the thread clocks
# --------------------------------------------------------------------------------------


def _comment(comment_id: str, *, text_value: str = "hi") -> IGComment:
    return IGComment.model_validate({"id": comment_id, "text": text_value})


def _thread_last_message_at(connection_id: UUID, media_id: str):
    with tenant_session(TENANT_I) as session:
        return session.execute(
            text(
                "SELECT last_message_at FROM threads "
                "WHERE connection_id = :cid AND external_thread_id = :mid"
            ),
            {"cid": str(connection_id), "mid": media_id},
        ).scalar_one()


def test_the_same_comment_synced_twice_does_not_duplicate(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    """B2's acceptance criterion, both halves: re-syncing the same comment creates no
    new row (already covered below) AND does not alter `last_message_at` — a duplicate
    is not a new event, so the thread's ordering clock must not move for it either."""
    tenant_id, connection_id = seeded_connection
    repo = PostgresInboxRepository()
    media_id = f"media-{uuid4()}"
    comment = _comment(f"comment-{uuid4()}")

    first = repo.upsert_comment(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        comment=comment,
    )
    last_message_at_after_first = _thread_last_message_at(connection_id, media_id)

    second = repo.upsert_comment(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        comment=comment,
    )
    last_message_at_after_second = _thread_last_message_at(connection_id, media_id)

    assert first is True
    assert second is False
    assert _message_row_count(connection_id, comment.id) == 1
    assert last_message_at_after_second == last_message_at_after_first


def test_two_comments_on_the_same_media_share_one_thread(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    tenant_id, connection_id = seeded_connection
    repo = PostgresInboxRepository()
    media_id = f"media-{uuid4()}"

    repo.upsert_comment(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        comment=_comment(f"comment-{uuid4()}"),
    )
    repo.upsert_comment(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        comment=_comment(f"comment-{uuid4()}"),
    )

    with tenant_session(TENANT_I) as session:
        thread_count = session.execute(
            text(
                "SELECT count(*) FROM threads WHERE connection_id = :cid "
                "AND channel = 'comment' AND external_thread_id = :mid"
            ),
            {"cid": str(connection_id), "mid": media_id},
        ).scalar_one()
    assert thread_count == 1


def test_upserting_a_comment_sets_both_thread_clocks(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    """Every comment synced today is inbound (B4/replies do not exist yet) — both
    `last_message_at` and `last_inbound_at` must move together for now."""
    tenant_id, connection_id = seeded_connection
    repo = PostgresInboxRepository()
    media_id = f"media-{uuid4()}"

    repo.upsert_comment(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        comment=_comment(f"comment-{uuid4()}"),
    )

    with tenant_session(TENANT_I) as session:
        row = session.execute(
            text(
                "SELECT last_message_at, last_inbound_at FROM threads "
                "WHERE connection_id = :cid AND external_thread_id = :mid"
            ),
            {"cid": str(connection_id), "mid": media_id},
        ).one()
    assert row.last_message_at is not None
    assert row.last_inbound_at is not None


def test_a_comment_without_author_or_timestamp_still_persists(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    """Nullability from the QUA-67 contract, not guessed — same guarantee
    `test_publishing_inbox_schema.py::test_a_message_may_arrive_without_author_or_timestamp`
    already asserts at the schema layer; this asserts the repository respects it too."""
    tenant_id, connection_id = seeded_connection
    repo = PostgresInboxRepository()
    media_id = f"media-{uuid4()}"
    comment = IGComment.model_validate(
        {"id": f"comment-{uuid4()}"}
    )  # no text, no from, no timestamp

    created = repo.upsert_comment(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        comment=comment,
    )
    assert created is True


# --------------------------------------------------------------------------------------
# inbox_meta_call_log — the Meta call budget ledger (QUA-88, migration 0010)
# --------------------------------------------------------------------------------------


def _call_log_row_count(connection_id: UUID) -> int:
    with tenant_session(TENANT_I) as session:
        return session.execute(
            text("SELECT count(*) FROM inbox_meta_call_log WHERE connection_id = :cid"),
            {"cid": str(connection_id)},
        ).scalar_one()


def test_record_call_appends_a_row_never_updates_one(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    """A logged call is a permanent fact — three calls must leave three rows, never
    collapse into one the way `monitored_media`'s toggle deliberately does."""
    tenant_id, connection_id = seeded_connection
    repo = PostgresInboxRepository()
    now = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)

    repo.record_call(tenant_id=tenant_id, connection_id=connection_id, called_at=now)
    repo.record_call(tenant_id=tenant_id, connection_id=connection_id, called_at=now)
    repo.record_call(tenant_id=tenant_id, connection_id=connection_id, called_at=now)

    assert _call_log_row_count(connection_id) == 3


def test_calls_in_last_hour_counts_what_was_recorded(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    tenant_id, connection_id = seeded_connection
    repo = PostgresInboxRepository()
    now = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)

    for _ in range(5):
        repo.record_call(tenant_id=tenant_id, connection_id=connection_id, called_at=now)

    assert repo.calls_in_last_hour(tenant_id=tenant_id, connection_id=connection_id, now=now) == 5


def test_calls_in_last_hour_is_a_true_sliding_window_against_real_timestamps(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    """The same guarantee `test_inbox_service.py`'s offline test pins on
    `MemoryInboxRepository` — re-verified here against real Postgres `TIMESTAMPTZ`
    comparison, not Python datetime arithmetic."""
    tenant_id, connection_id = seeded_connection
    repo = PostgresInboxRepository()
    reference_now = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)
    just_inside = reference_now - timedelta(minutes=59)
    just_outside = reference_now - timedelta(hours=1, minutes=1)

    repo.record_call(tenant_id=tenant_id, connection_id=connection_id, called_at=just_inside)
    repo.record_call(tenant_id=tenant_id, connection_id=connection_id, called_at=just_outside)

    assert (
        repo.calls_in_last_hour(tenant_id=tenant_id, connection_id=connection_id, now=reference_now)
        == 1
    )


def test_calls_in_last_hour_is_scoped_to_one_connection(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    """Two connections under the SAME tenant must not share a budget — a busy connection
    must never exhaust a quiet one's."""
    tenant_id, connection_a = seeded_connection
    connection_b = _second_connection(tenant_id)
    repo = PostgresInboxRepository()
    now = datetime(2026, 8, 18, 12, 0, 0, tzinfo=UTC)

    for _ in range(10):
        repo.record_call(tenant_id=tenant_id, connection_id=connection_a, called_at=now)
    repo.record_call(tenant_id=tenant_id, connection_id=connection_b, called_at=now)

    assert repo.calls_in_last_hour(tenant_id=tenant_id, connection_id=connection_a, now=now) == 10
    assert repo.calls_in_last_hour(tenant_id=tenant_id, connection_id=connection_b, now=now) == 1


def test_calls_in_last_hour_is_zero_for_a_connection_with_no_calls(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    tenant_id, connection_id = seeded_connection
    repo = PostgresInboxRepository()

    assert (
        repo.calls_in_last_hour(
            tenant_id=tenant_id, connection_id=connection_id, now=datetime.now(UTC)
        )
        == 0
    )

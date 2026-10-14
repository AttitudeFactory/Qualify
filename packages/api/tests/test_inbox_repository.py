"""`db`-marked tests for `PostgresInboxRepository` — the four idempotency/accounting
guarantees this module translates, exercised against the real constraints from
0004/0005/0010/0015. Same `seeded_connection` shape as `test_publishing_inbox_schema.py`.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from qualify_shared.social.ig_shapes import IGComment
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.inbox.media_type import MediaType, is_unrecognized_media_type, known_media_type
from qualify_api.inbox.monitoring import (
    MONITORING_WINDOW,
    MediaMetadata,
    MetadataFetchError,
    MonitoringState,
)
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


def _seed_connection_for_new_tenant() -> tuple[UUID, UUID]:
    """A brand-new tenant + connection, for tests that need genuine cross-TENANT
    isolation (RLS), unlike `_second_connection`'s second connection under the SAME
    tenant (that one exercises the per-connection budget scoping instead)."""
    tenant_id = uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant_id,
                name=f"t-{tenant_id}",
                country="CO",
                timezone="America/Bogota",
                currency="COP",
            )
        )
        session.flush()
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        session.add(app)
        session.flush()
        user = User(tenant_id=tenant_id, email=f"u-{uuid4()}@i.co", display_name="U")
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
        return tenant_id, conn.id


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


def _message_deleted_at(tenant_id: UUID, connection_id: UUID, external_message_id: str):
    """`messages.deleted_at` for one comment, read directly (QUA-101) — `None` means
    active, a real timestamp means soft-deleted. Takes `tenant_id` (unlike
    `_message_row_count` above, which is hardcoded to `TENANT_I`) so the cross-tenant
    isolation test below can read a SECOND tenant's row through its own RLS-scoped
    session."""
    with tenant_session(tenant_id) as session:
        return session.execute(
            text(
                "SELECT deleted_at FROM messages "
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


# --------------------------------------------------------------------------------------
# reconcile_media_comments — soft-delete/restore against the real `messages.deleted_at`
# column (QUA-101, migration 0015)
# --------------------------------------------------------------------------------------


def test_reconcile_marks_a_missing_comment_deleted(seeded_connection: tuple[UUID, UUID]) -> None:
    tenant_id, connection_id = seeded_connection
    repo = PostgresInboxRepository()
    media_id = f"media-{uuid4()}"
    kept, gone = f"comment-{uuid4()}", f"comment-{uuid4()}"
    repo.upsert_comment(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        comment=_comment(kept),
    )
    repo.upsert_comment(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        comment=_comment(gone),
    )

    newly_deleted = repo.reconcile_media_comments(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        current_external_ids=frozenset({kept}),  # Meta no longer returns `gone`
    )

    assert newly_deleted == 1
    assert _message_deleted_at(tenant_id, connection_id, gone) is not None
    assert _message_deleted_at(tenant_id, connection_id, kept) is None


def test_reconcile_never_touches_a_comment_still_present(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    tenant_id, connection_id = seeded_connection
    repo = PostgresInboxRepository()
    media_id = f"media-{uuid4()}"
    comment_id = f"comment-{uuid4()}"
    repo.upsert_comment(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        comment=_comment(comment_id),
    )

    newly_deleted = repo.reconcile_media_comments(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        current_external_ids=frozenset({comment_id}),
    )

    assert newly_deleted == 0
    assert _message_deleted_at(tenant_id, connection_id, comment_id) is None


def test_reconcile_restores_a_comment_that_reappears(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    tenant_id, connection_id = seeded_connection
    repo = PostgresInboxRepository()
    media_id = f"media-{uuid4()}"
    comment_id = f"comment-{uuid4()}"
    repo.upsert_comment(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        comment=_comment(comment_id),
    )
    repo.reconcile_media_comments(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        current_external_ids=frozenset(),  # marks it deleted
    )
    assert _message_deleted_at(tenant_id, connection_id, comment_id) is not None

    newly_deleted = repo.reconcile_media_comments(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        current_external_ids=frozenset({comment_id}),  # Meta shows it again
    )

    assert newly_deleted == 0  # a restore is not a NEW deletion
    assert _message_deleted_at(tenant_id, connection_id, comment_id) is None


def test_reconcile_returns_zero_for_a_media_never_synced(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    """No `threads` row exists for this media at all — nothing to reconcile, and this
    must not raise."""
    tenant_id, connection_id = seeded_connection
    repo = PostgresInboxRepository()

    newly_deleted = repo.reconcile_media_comments(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=f"media-{uuid4()}",
        current_external_ids=frozenset(),
    )

    assert newly_deleted == 0


def test_upsert_comment_restores_a_soft_deleted_comment_on_reappearance(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    """The other route back to "active": `upsert_comment` itself (not only
    `reconcile_media_comments`) must clear `deleted_at` when the same comment id is
    upserted again — the ordinary path a real `sync_comments` call takes when Meta shows
    a previously-vanished comment again."""
    tenant_id, connection_id = seeded_connection
    repo = PostgresInboxRepository()
    media_id = f"media-{uuid4()}"
    comment = _comment(f"comment-{uuid4()}")
    repo.upsert_comment(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        comment=comment,
    )
    repo.reconcile_media_comments(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        current_external_ids=frozenset(),
    )
    assert _message_deleted_at(tenant_id, connection_id, comment.id) is not None

    created = repo.upsert_comment(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        comment=comment,
    )

    assert created is False  # still a duplicate, not a new row
    assert _message_deleted_at(tenant_id, connection_id, comment.id) is None
    assert _message_row_count(connection_id, comment.id) == 1  # no second row was created


def test_reconcile_media_comments_never_crosses_tenants() -> None:
    """RLS regression (QUA-101): two tenants each have a comment under the SAME
    `external_media_id`/`external_message_id` strings (identifiers are per-connection,
    never globally unique) — reconciling tenant A's media with an EMPTY current set
    must soft-delete ONLY tenant A's row. Tenant B's row, same string identifiers, must
    come out completely untouched; if RLS ever stopped scoping this method's queries,
    this test would catch it by finding tenant B's comment deleted too."""
    tenant_a, connection_a = _seed_connection_for_new_tenant()
    tenant_b, connection_b = _seed_connection_for_new_tenant()
    repo = PostgresInboxRepository()
    shared_media_id = "media-shared-across-tenants"
    shared_comment_id = "comment-shared-across-tenants"
    repo.upsert_comment(
        tenant_id=tenant_a,
        connection_id=connection_a,
        external_media_id=shared_media_id,
        comment=_comment(shared_comment_id),
    )
    repo.upsert_comment(
        tenant_id=tenant_b,
        connection_id=connection_b,
        external_media_id=shared_media_id,
        comment=_comment(shared_comment_id),
    )

    newly_deleted = repo.reconcile_media_comments(
        tenant_id=tenant_a,
        connection_id=connection_a,
        external_media_id=shared_media_id,
        current_external_ids=frozenset(),  # tenant A's comment is gone from Meta
    )

    assert newly_deleted == 1
    assert _message_deleted_at(tenant_a, connection_a, shared_comment_id) is not None
    assert _message_deleted_at(tenant_b, connection_b, shared_comment_id) is None


# --------------------------------------------------------------------------------------
# QUA-149 (0046) — metadata kept past the window, expired media never offered to the sync
# --------------------------------------------------------------------------------------

_NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


def _meta(posted_at: datetime, caption: str | None = "caption") -> MediaMetadata:
    return MediaMetadata(
        posted_at=posted_at,
        caption=caption,
        permalink="https://www.instagram.com/reel/x/",
        media_product_type="REELS",
    )


def test_turning_on_with_metadata_persists_it(seeded_connection: tuple[UUID, UUID]) -> None:
    tenant_id, connection_id = seeded_connection
    repo = PostgresInboxRepository()
    media_id = f"media-{uuid4()}"

    repo.set_media_monitored(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        monitored=True,
        metadata=_meta(_NOW - timedelta(days=2)),
        fetched_at=_NOW,
    )

    row = repo.get_monitored_media(
        tenant_id=tenant_id, connection_id=connection_id, external_media_id=media_id
    )
    assert row is not None
    assert row.is_monitored
    assert row.media_posted_at == _NOW - timedelta(days=2)
    assert row.caption == "caption"
    assert row.permalink == "https://www.instagram.com/reel/x/"
    assert row.media_product_type == "REELS"
    assert row.metadata_fetched_at == _NOW
    assert row.metadata_error is None
    assert row.state(_NOW) is MonitoringState.ACTIVE


def test_turning_off_keeps_metadata_in_the_same_row(seeded_connection: tuple[UUID, UUID]) -> None:
    tenant_id, connection_id = seeded_connection
    repo = PostgresInboxRepository()
    media_id = f"media-{uuid4()}"
    repo.set_media_monitored(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        monitored=True,
        metadata=_meta(_NOW - timedelta(days=2)),
        fetched_at=_NOW,
    )

    repo.set_media_monitored(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        monitored=False,
    )

    row = repo.get_monitored_media(
        tenant_id=tenant_id, connection_id=connection_id, external_media_id=media_id
    )
    assert row is not None
    assert not row.is_monitored
    assert row.caption == "caption"
    assert row.state(_NOW) is MonitoringState.INACTIVE
    assert _monitored_row_count(connection_id, media_id) == 1


def test_list_media_to_sync_applies_the_window_in_sql(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    """Active, expired, exactly-on-the-boundary, legacy (unknown date) and turned-off rows
    on one connection: only active, boundary and legacy are offered to the sync."""
    tenant_id, connection_id = seeded_connection
    repo = PostgresInboxRepository()
    suffix = uuid4().hex[:8]
    ids = {n: f"{n}-{suffix}" for n in ("active", "boundary", "expired", "legacy", "off")}
    for name, posted_at in (
        ("active", _NOW - timedelta(days=3)),
        ("boundary", _NOW - MONITORING_WINDOW),
        ("expired", _NOW - MONITORING_WINDOW - timedelta(seconds=1)),
    ):
        repo.set_media_monitored(
            tenant_id=tenant_id,
            connection_id=connection_id,
            external_media_id=ids[name],
            monitored=True,
            metadata=_meta(posted_at),
            fetched_at=_NOW,
        )
    repo.set_media_monitored(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=ids["legacy"],
        monitored=True,
    )
    repo.set_media_monitored(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=ids["off"],
        monitored=False,
        metadata=_meta(_NOW - timedelta(days=1)),
        fetched_at=_NOW,
    )

    to_sync = repo.list_media_to_sync(tenant_id=tenant_id, connection_id=connection_id, now=_NOW)
    ours = {m.external_media_id: m for m in to_sync if m.external_media_id.endswith(suffix)}

    assert set(ours) == {ids["active"], ids["boundary"], ids["legacy"]}
    assert ours[ids["legacy"]].needs_metadata
    assert not ours[ids["active"]].needs_metadata
    assert [m.external_media_id for m in to_sync] == sorted(m.external_media_id for m in to_sync)
    # The expired row is untouched and still readable.
    expired = repo.get_monitored_media(
        tenant_id=tenant_id, connection_id=connection_id, external_media_id=ids["expired"]
    )
    assert expired is not None and expired.is_monitored and expired.caption == "caption"
    assert expired.state(_NOW) is MonitoringState.EXPIRED
    # QUA-149 phase 2: exactly the monitored rows the query above left out by date (the
    # legacy row's date is unknown, the turned-off row is not monitored).
    assert repo.count_expired_media(tenant_id=tenant_id, connection_id=connection_id, now=_NOW) == 1


def test_metadata_failure_then_backfill_on_a_legacy_row(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    tenant_id, connection_id = seeded_connection
    repo = PostgresInboxRepository()
    media_id = f"legacy-{uuid4()}"
    repo.set_media_monitored(
        tenant_id=tenant_id, connection_id=connection_id, external_media_id=media_id, monitored=True
    )

    repo.record_media_metadata_failure(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        error=MetadataFetchError.PERMISSION,
        attempted_at=_NOW,
    )
    failed = repo.get_monitored_media(
        tenant_id=tenant_id, connection_id=connection_id, external_media_id=media_id
    )
    assert failed is not None
    assert failed.is_monitored
    assert failed.metadata_error is MetadataFetchError.PERMISSION
    assert failed.metadata_attempted_at == _NOW
    assert failed.metadata_fetched_at is None

    repo.record_media_metadata(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        metadata=_meta(_NOW - timedelta(days=40), caption=None),
        fetched_at=_NOW + timedelta(minutes=5),
    )
    done = repo.get_monitored_media(
        tenant_id=tenant_id, connection_id=connection_id, external_media_id=media_id
    )
    assert done is not None
    assert done.is_monitored
    assert done.caption is None
    assert done.metadata_fetched_at == _NOW + timedelta(minutes=5)
    assert done.metadata_error is None
    assert done.state(_NOW) is MonitoringState.EXPIRED
    to_sync = repo.list_media_to_sync(tenant_id=tenant_id, connection_id=connection_id, now=_NOW)
    assert media_id not in {m.external_media_id for m in to_sync}


def test_a_failure_never_erases_stored_metadata(seeded_connection: tuple[UUID, UUID]) -> None:
    tenant_id, connection_id = seeded_connection
    repo = PostgresInboxRepository()
    media_id = f"media-{uuid4()}"
    repo.set_media_monitored(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        monitored=True,
        metadata=_meta(_NOW - timedelta(days=2)),
        fetched_at=_NOW,
    )

    repo.record_media_metadata_failure(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        error=MetadataFetchError.TRANSIENT,
        attempted_at=_NOW + timedelta(hours=1),
    )

    row = repo.get_monitored_media(
        tenant_id=tenant_id, connection_id=connection_id, external_media_id=media_id
    )
    assert row is not None
    assert row.caption == "caption"
    assert row.media_posted_at == _NOW - timedelta(days=2)
    assert row.metadata_fetched_at == _NOW


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE monitored_media SET metadata_error = 'deleted' WHERE external_media_id = :mid",
        "UPDATE monitored_media SET metadata_fetched_at = now(), media_posted_at = NULL "
        "WHERE external_media_id = :mid",
    ],
)
def test_check_constraints_reject_inconsistent_metadata(
    seeded_connection: tuple[UUID, UUID], statement: str
) -> None:
    tenant_id, connection_id = seeded_connection
    media_id = f"media-{uuid4()}"
    PostgresInboxRepository().set_media_monitored(
        tenant_id=tenant_id, connection_id=connection_id, external_media_id=media_id, monitored=True
    )
    with pytest.raises(IntegrityError):
        with tenant_session(tenant_id) as session:
            session.execute(text(statement), {"mid": media_id})
            session.flush()


def test_monitored_media_metadata_never_crosses_tenants() -> None:
    tenant_a, connection_a = _seed_connection_for_new_tenant()
    tenant_b, _ = _seed_connection_for_new_tenant()
    repo = PostgresInboxRepository()
    media_id = f"media-{uuid4()}"
    repo.set_media_monitored(
        tenant_id=tenant_a,
        connection_id=connection_a,
        external_media_id=media_id,
        monitored=True,
        metadata=_meta(_NOW - timedelta(days=1)),
        fetched_at=_NOW,
    )

    assert (
        repo.get_monitored_media(
            tenant_id=tenant_b, connection_id=connection_a, external_media_id=media_id
        )
        is None
    )
    assert repo.list_media_to_sync(tenant_id=tenant_b, connection_id=connection_a, now=_NOW) == ()
    repo.record_media_metadata_failure(
        tenant_id=tenant_b,
        connection_id=connection_a,
        external_media_id=media_id,
        error=MetadataFetchError.UNKNOWN,
        attempted_at=_NOW,
    )
    row = repo.get_monitored_media(
        tenant_id=tenant_a, connection_id=connection_a, external_media_id=media_id
    )
    assert row is not None and row.metadata_error is None


# --------------------------------------------------------------------------------------
# QUA-146 (0049) — `media_type`: historical backfill, verbatim storage of unknown values
# --------------------------------------------------------------------------------------


def _backfill_reels_sql() -> str:
    path = (
        Path(__file__).resolve().parents[3]
        / "migrations"
        / "postgres"
        / "versions"
        / "0049_monitored_media_type.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0049", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BACKFILL_REELS_SQL


def _force_columns(tenant_id: UUID, media_id: str, **columns: str | None) -> None:
    """Put a row in a state the repository never writes itself (a historical row, or a
    value Meta might send in the future) — raw SQL through the RLS-scoped door."""
    assignments = ", ".join(f"{name} = :{name}" for name in columns)
    with tenant_session(tenant_id) as session:
        session.execute(
            text(f"UPDATE monitored_media SET {assignments} WHERE external_media_id = :mid"),
            {"mid": media_id, **columns},
        )


def test_the_0049_backfill_marks_only_historical_reels_as_video() -> None:
    """The migration's exact statement, run through `tenant_session` so RLS confines it to
    this test's own fresh tenant: Reels without a type become VIDEO; FEED, STORY, an
    unknown product type and an already-typed Reel are left alone."""
    tenant_id, connection_id = _seed_connection_for_new_tenant()
    repo = PostgresInboxRepository()
    cases = {
        "reel": ("REELS", None, "VIDEO"),
        "feed": ("FEED", None, None),
        "story": ("STORY", None, None),
        "no-product-type": (None, None, None),
        "reel-already-typed": ("REELS", "CAROUSEL_ALBUM", "CAROUSEL_ALBUM"),
    }
    for name, (product_type, media_type, _) in cases.items():
        repo.set_media_monitored(
            tenant_id=tenant_id,
            connection_id=connection_id,
            external_media_id=name,
            monitored=True,
            metadata=_meta(_NOW - timedelta(days=1)),
            fetched_at=_NOW,
        )
        _force_columns(tenant_id, name, media_product_type=product_type, media_type=media_type)

    with tenant_session(tenant_id) as session:
        session.execute(text(_backfill_reels_sql()))

    for name, (_, _, expected) in cases.items():
        row = repo.get_monitored_media(
            tenant_id=tenant_id, connection_id=connection_id, external_media_id=name
        )
        assert row is not None
        assert row.media_type == expected, name


def test_an_unknown_media_type_is_stored_and_read_back_verbatim() -> None:
    """No CHECK on `media_type`: a value Meta may add later is accepted by Postgres and
    survives every QUA-149 write untouched — metadata refresh, failure, turning off."""
    tenant_id, connection_id = _seed_connection_for_new_tenant()
    repo = PostgresInboxRepository()
    media_id = f"media-{uuid4()}"
    repo.set_media_monitored(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        monitored=True,
        metadata=_meta(_NOW - timedelta(days=1)),
        fetched_at=_NOW,
    )
    _force_columns(tenant_id, media_id, media_type="FUTURE_FORMAT")

    repo.record_media_metadata(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        metadata=_meta(_NOW - timedelta(days=1), caption="edited"),
        fetched_at=_NOW + timedelta(minutes=1),
    )
    repo.record_media_metadata_failure(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        error=MetadataFetchError.TRANSIENT,
        attempted_at=_NOW + timedelta(minutes=2),
    )
    repo.set_media_monitored(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        monitored=False,
    )

    row = repo.get_monitored_media(
        tenant_id=tenant_id, connection_id=connection_id, external_media_id=media_id
    )
    assert row is not None
    assert row.media_type == "FUTURE_FORMAT"
    assert known_media_type(row.media_type) is None
    assert is_unrecognized_media_type(row.media_type)
    assert row.caption == "edited"


def test_a_known_media_type_reads_back_as_the_enum() -> None:
    tenant_id, connection_id = _seed_connection_for_new_tenant()
    repo = PostgresInboxRepository()
    media_id = f"media-{uuid4()}"
    repo.set_media_monitored(
        tenant_id=tenant_id, connection_id=connection_id, external_media_id=media_id, monitored=True
    )
    _force_columns(tenant_id, media_id, media_type="IMAGE")

    row = repo.get_monitored_media(
        tenant_id=tenant_id, connection_id=connection_id, external_media_id=media_id
    )
    assert row is not None
    assert known_media_type(row.media_type) is MediaType.IMAGE


# --------------------------------------------------------------------------------------
# QUA-146 phase 2 — `media_type` writes and the `needs_media_type` flag, in Postgres
# --------------------------------------------------------------------------------------


def _meta_with_type(posted_at: datetime, media_type: str | None) -> MediaMetadata:
    return MediaMetadata(
        posted_at=posted_at,
        caption="caption",
        permalink="https://www.instagram.com/p/x/",
        media_product_type="FEED",
        media_type=media_type,
    )


def test_activation_persists_media_type_and_a_later_read_without_it_keeps_it() -> None:
    tenant_id, connection_id = _seed_connection_for_new_tenant()
    repo = PostgresInboxRepository()
    media_id = f"media-{uuid4()}"
    repo.set_media_monitored(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        monitored=True,
        metadata=_meta_with_type(_NOW - timedelta(days=1), "CAROUSEL_ALBUM"),
        fetched_at=_NOW,
    )

    repo.record_media_metadata(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        metadata=_meta(_NOW - timedelta(days=1), caption="edited"),  # no media_type
        fetched_at=_NOW + timedelta(minutes=1),
    )

    row = repo.get_monitored_media(
        tenant_id=tenant_id, connection_id=connection_id, external_media_id=media_id
    )
    assert row is not None
    assert row.media_type == "CAROUSEL_ALBUM"
    assert row.caption == "edited"
    assert known_media_type(row.media_type) is MediaType.CAROUSEL_ALBUM


def test_record_media_type_writes_only_that_field_and_clears_the_failure() -> None:
    tenant_id, connection_id = _seed_connection_for_new_tenant()
    repo = PostgresInboxRepository()
    media_id = f"media-{uuid4()}"
    repo.set_media_monitored(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        monitored=True,
        metadata=_meta_with_type(_NOW - timedelta(days=1), None),
        fetched_at=_NOW,
    )
    repo.record_media_metadata_failure(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        error=MetadataFetchError.UNKNOWN,
        attempted_at=_NOW + timedelta(minutes=1),
    )

    repo.record_media_type(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_media_id=media_id,
        media_type="FUTURE_FORMAT",
        fetched_at=_NOW + timedelta(hours=7),
    )

    row = repo.get_monitored_media(
        tenant_id=tenant_id, connection_id=connection_id, external_media_id=media_id
    )
    assert row is not None
    assert row.media_type == "FUTURE_FORMAT"
    assert is_unrecognized_media_type(row.media_type)
    assert row.metadata_error is None
    assert row.metadata_attempted_at == _NOW + timedelta(hours=7)
    assert row.metadata_fetched_at == _NOW  # untouched
    assert row.caption == "caption"
    assert row.media_posted_at == _NOW - timedelta(days=1)
    assert row.is_monitored


def test_list_media_to_sync_flags_only_active_complete_rows_without_media_type() -> None:
    tenant_id, connection_id = _seed_connection_for_new_tenant()
    repo = PostgresInboxRepository()
    cases = {
        "typed": (_NOW - timedelta(days=1), "IMAGE"),
        "untyped": (_NOW - timedelta(days=1), None),
        "expired-untyped": (_NOW - MONITORING_WINDOW - timedelta(seconds=1), None),
    }
    for name, (posted_at, media_type) in cases.items():
        repo.set_media_monitored(
            tenant_id=tenant_id,
            connection_id=connection_id,
            external_media_id=name,
            monitored=True,
            metadata=_meta_with_type(posted_at, media_type),
            fetched_at=_NOW,
        )
    repo.set_media_monitored(
        tenant_id=tenant_id, connection_id=connection_id, external_media_id="legacy", monitored=True
    )

    to_sync = {
        m.external_media_id: m
        for m in repo.list_media_to_sync(tenant_id=tenant_id, connection_id=connection_id, now=_NOW)
    }

    assert set(to_sync) == {"typed", "untyped", "legacy"}  # the expired one is never handed over
    assert to_sync["untyped"].needs_media_type and not to_sync["untyped"].needs_metadata
    assert not to_sync["typed"].needs_media_type
    # A legacy row is read in full (QUA-149); its media_type rides on that read.
    assert to_sync["legacy"].needs_metadata and not to_sync["legacy"].needs_media_type

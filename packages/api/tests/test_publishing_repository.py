"""A4 — the write-ahead publish-attempt repository.

Split the way the backlog orders it: the idempotency and settle-once invariants are
exercised against an in-memory double offline, AND against the real `uq_attempt_idempotency`
constraint and `publish_attempts_settle_once` trigger under the `db` marker — because the
double asserting a behaviour is only worth something if the real database demonstrably
behaves the same way.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.publishing.repository import (
    AlreadySettled,
    AttemptStart,
    ChildAdd,
    MemoryPublishAttemptRepository,
    PostgresPublishAttemptRepository,
)
from qualify_api.tenancy.models import Tenant, User

TENANT_P = UUID("e0000000-0000-4000-8000-0000000000f1")
OTHER_TENANT = UUID("e0000000-0000-4000-8000-0000000000b2")


# --------------------------------------------------------------------------------------
# The in-memory double (now shipped next to the real one — importlib test mode forbids
# cross-test imports, and two copies would drift; precedent: InMemoryEventPublisher)
# --------------------------------------------------------------------------------------


def _start(repo: MemoryPublishAttemptRepository, key: str = "op-1") -> AttemptStart:
    return repo.start_attempt(
        tenant_id=TENANT_P,
        connection_id=UUID("22222222-2222-4222-8222-222222222222"),
        idempotency_key=key,
        media_product_type="REELS",
        adapter_version="v1",
    )


def test_double_duplicate_key_returns_existing_and_creates_nothing() -> None:
    repo = MemoryPublishAttemptRepository()
    first = _start(repo)
    second = _start(repo)
    assert first.created and not second.created
    assert second.record.id == first.record.id
    assert len(repo.rows) == 1


def test_double_settled_row_refuses_every_update() -> None:
    repo = MemoryPublishAttemptRepository()
    attempt = _start(repo).record
    repo.settle(
        tenant_id=TENANT_P, attempt_id=attempt.id, status="published", published_media_id="m-1"
    )
    with pytest.raises(AlreadySettled):
        repo.settle(tenant_id=TENANT_P, attempt_id=attempt.id, status="failed")
    with pytest.raises(AlreadySettled):
        repo.advance_status(tenant_id=TENANT_P, attempt_id=attempt.id, status="processing")


def test_terminal_vocabulary_guards_hold_without_a_database() -> None:
    """The guards fire BEFORE any session opens, on the real class too — a terminal status
    through advance_status (or a non-terminal through settle) names the actual mistake
    instead of surfacing a constraint string."""
    real = PostgresPublishAttemptRepository()
    with pytest.raises(ValueError, match="settle"):
        real.advance_status(tenant_id=TENANT_P, attempt_id=uuid4(), status="published")
    with pytest.raises(ValueError, match="terminal"):
        real.settle(tenant_id=TENANT_P, attempt_id=uuid4(), status="uploading")


# --------------------------------------------------------------------------------------
# carousel children (QUA-99, 3/6) — the in-memory double
# --------------------------------------------------------------------------------------


def _add_child(repo: MemoryPublishAttemptRepository, attempt_id: UUID, position: int) -> ChildAdd:
    return repo.add_child(
        tenant_id=TENANT_P,
        attempt_id=attempt_id,
        position=position,
        media_object_key=f"t/{TENANT_P}/child-{position}",
        media_content_type="video/mp4",
        media_product_type="VIDEO",
    )


def test_child_add_is_idempotent_per_attempt_and_position() -> None:
    """Same shape as `start_attempt`'s idempotency — an orchestration step (commit 4/6)
    that crashes and resumes must be able to call `add_child` again for a slot it already
    wrote and get that row back, not a second one."""
    repo = MemoryPublishAttemptRepository()
    attempt_id = uuid4()
    first = _add_child(repo, attempt_id, 0)
    second = _add_child(repo, attempt_id, 0)
    assert first.created and not second.created
    assert second.record.id == first.record.id
    assert len(repo.children) == 1


def test_child_starts_pending_with_no_creation_id() -> None:
    repo = MemoryPublishAttemptRepository()
    child = _add_child(repo, uuid4(), 0).record
    assert child.status == "pending"
    assert child.creation_id is None
    assert not child.is_terminal


def test_list_children_is_ordered_by_position_not_insertion_order() -> None:
    """Instagram displays a carousel in the order `children` was sent when the CAROUSEL
    container was created — this must be `position`, never row/insertion order."""
    repo = MemoryPublishAttemptRepository()
    attempt_id = uuid4()
    _add_child(repo, attempt_id, 2)
    _add_child(repo, attempt_id, 0)
    _add_child(repo, attempt_id, 1)

    ordered = repo.list_children(tenant_id=TENANT_P, attempt_id=attempt_id)

    assert [c.position for c in ordered] == [0, 1, 2]


def test_list_children_is_scoped_to_one_attempt() -> None:
    repo = MemoryPublishAttemptRepository()
    attempt_a, attempt_b = uuid4(), uuid4()
    _add_child(repo, attempt_a, 0)
    _add_child(repo, attempt_b, 0)
    _add_child(repo, attempt_b, 1)

    assert len(repo.list_children(tenant_id=TENANT_P, attempt_id=attempt_a)) == 1
    assert len(repo.list_children(tenant_id=TENANT_P, attempt_id=attempt_b)) == 2


def test_record_child_creation_id_is_independent_of_the_parent_attempts() -> None:
    """The child's own container id must never be confused with the parent attempt's —
    they are tracked on two different dataclasses/rows precisely to make that impossible."""
    repo = MemoryPublishAttemptRepository()
    child = _add_child(repo, uuid4(), 0).record

    repo.record_child_creation_id(tenant_id=TENANT_P, child_id=child.id, creation_id="child-c-1")

    reread = repo.get_child(tenant_id=TENANT_P, child_id=child.id)
    assert reread is not None
    assert reread.creation_id == "child-c-1"


def test_child_advances_through_non_terminal_statuses() -> None:
    repo = MemoryPublishAttemptRepository()
    child = _add_child(repo, uuid4(), 0).record

    for status in ("uploading", "processing"):
        repo.advance_child_status(tenant_id=TENANT_P, child_id=child.id, status=status)
        assert repo.get_child(tenant_id=TENANT_P, child_id=child.id).status == status


def test_child_advance_status_refuses_a_terminal_value() -> None:
    """Same guard style as the parent's `advance_status` — the mistake is named locally,
    not surfaced as a raw constraint violation two layers away."""
    repo = MemoryPublishAttemptRepository()
    child = _add_child(repo, uuid4(), 0).record
    with pytest.raises(ValueError, match="settle_child"):
        repo.advance_child_status(tenant_id=TENANT_P, child_id=child.id, status="finished")


def test_settle_child_requires_a_terminal_value() -> None:
    repo = MemoryPublishAttemptRepository()
    child = _add_child(repo, uuid4(), 0).record
    with pytest.raises(ValueError, match="terminal"):
        repo.settle_child(tenant_id=TENANT_P, child_id=child.id, status="uploading")


def test_settle_child_records_the_outcome_and_the_platform_error_code() -> None:
    repo = MemoryPublishAttemptRepository()
    child = _add_child(repo, uuid4(), 0).record

    repo.settle_child(
        tenant_id=TENANT_P,
        child_id=child.id,
        status="failed",
        platform_error_code="container_error",
    )

    settled = repo.get_child(tenant_id=TENANT_P, child_id=child.id)
    assert settled.status == "failed"
    assert settled.platform_error_code == "container_error"
    assert settled.is_terminal


def test_a_child_can_be_updated_again_after_settling_no_settle_once_guard() -> None:
    """Deliberately DIFFERENT from `AttemptRecord`/`settle()`: children carry no
    settle-once guard (0016's own design decision, mirrored here) — nothing at this
    table's layer is ever handed to `media_publish`, so there is no irreversible
    transition at this layer to protect."""
    repo = MemoryPublishAttemptRepository()
    child = _add_child(repo, uuid4(), 0).record
    repo.settle_child(tenant_id=TENANT_P, child_id=child.id, status="finished")

    repo.settle_child(tenant_id=TENANT_P, child_id=child.id, status="failed")  # must not raise

    assert repo.get_child(tenant_id=TENANT_P, child_id=child.id).status == "failed"


def test_get_child_respects_tenant_isolation() -> None:
    repo = MemoryPublishAttemptRepository()
    child = _add_child(repo, uuid4(), 0).record
    assert repo.get_child(tenant_id=OTHER_TENANT, child_id=child.id) is None


# --------------------------------------------------------------------------------------
# The real constraint and the real trigger (compose Postgres)
# --------------------------------------------------------------------------------------


@pytest.fixture
def seeded_connection() -> tuple[UUID, UUID]:
    """(tenant_id, connection_id) — same two-door split as the schema tests."""
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
    return TENANT_P, connection_id


@pytest.mark.db
def test_start_attempt_is_the_write_ahead_record(seeded_connection: tuple[UUID, UUID]) -> None:
    """The row exists in 'pending' with creation_id NULL before anything touches Meta —
    a crash before the container call leaves this row, never an absence."""
    tenant_id, connection_id = seeded_connection
    repo = PostgresPublishAttemptRepository()

    start = repo.start_attempt(
        tenant_id=tenant_id,
        connection_id=connection_id,
        idempotency_key=f"op-{uuid4()}",
        media_product_type="REELS",
        adapter_version="v1",
    )

    assert start.created
    assert start.record.status == "pending"
    assert start.record.creation_id is None
    assert start.record.settled_at is None


@pytest.mark.db
def test_real_unique_constraint_makes_duplicates_return_the_existing_attempt(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    tenant_id, connection_id = seeded_connection
    repo = PostgresPublishAttemptRepository()
    key = f"op-{uuid4()}"

    first = repo.start_attempt(
        tenant_id=tenant_id,
        connection_id=connection_id,
        idempotency_key=key,
        media_product_type="REELS",
        adapter_version="v1",
    )
    second = repo.start_attempt(
        tenant_id=tenant_id,
        connection_id=connection_id,
        idempotency_key=key,
        media_product_type="REELS",
        adapter_version="v1",
    )

    assert first.created and not second.created
    assert second.record.id == first.record.id
    with tenant_session(tenant_id) as session:
        count = session.scalar(
            text("SELECT count(*) FROM publish_attempts WHERE idempotency_key = :k"),
            {"k": key},
        )
    assert count == 1


@pytest.mark.db
def test_real_trigger_translates_to_already_settled(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    """Settle lands terminal status + settled_at in one statement (the CHECK demands it);
    the trigger's refusal of ANY later update arrives as AlreadySettled — the idempotent
    retry path, not a 500."""
    tenant_id, connection_id = seeded_connection
    repo = PostgresPublishAttemptRepository()
    attempt = repo.start_attempt(
        tenant_id=tenant_id,
        connection_id=connection_id,
        idempotency_key=f"op-{uuid4()}",
        media_product_type="REELS",
        adapter_version="v1",
    ).record

    repo.record_creation_id(tenant_id=tenant_id, attempt_id=attempt.id, creation_id="c-1")
    repo.advance_status(tenant_id=tenant_id, attempt_id=attempt.id, status="processing")
    repo.settle(
        tenant_id=tenant_id, attempt_id=attempt.id, status="published", published_media_id="m-1"
    )

    settled = repo.find_by_idempotency_key(
        tenant_id=tenant_id, connection_id=connection_id, idempotency_key=attempt.idempotency_key
    )
    assert settled is not None and settled.is_settled
    assert settled.status == "published"
    assert settled.published_media_id == "m-1"

    with pytest.raises(AlreadySettled):
        repo.settle(tenant_id=tenant_id, attempt_id=attempt.id, status="failed")
    with pytest.raises(AlreadySettled):
        repo.advance_status(tenant_id=tenant_id, attempt_id=attempt.id, status="processing")


@pytest.mark.db
def test_rls_makes_another_tenants_attempt_invisible(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    """Invisible at the database, not filtered in Python: the same query under another
    tenant's session simply returns nothing."""
    tenant_id, connection_id = seeded_connection
    repo = PostgresPublishAttemptRepository()
    key = f"op-{uuid4()}"
    repo.start_attempt(
        tenant_id=tenant_id,
        connection_id=connection_id,
        idempotency_key=key,
        media_product_type="REELS",
        adapter_version="v1",
    )

    assert (
        repo.find_by_idempotency_key(
            tenant_id=OTHER_TENANT, connection_id=connection_id, idempotency_key=key
        )
        is None
    )


# --------------------------------------------------------------------------------------
# carousel children (QUA-99, 3/6) — the real constraint and the real FK (compose Postgres)
# --------------------------------------------------------------------------------------


def _start_real_attempt(
    repo: PostgresPublishAttemptRepository, tenant_id: UUID, connection_id: UUID
):
    return repo.start_attempt(
        tenant_id=tenant_id,
        connection_id=connection_id,
        idempotency_key=f"op-{uuid4()}",
        media_product_type="CAROUSEL",
        adapter_version="v1",
    ).record


@pytest.mark.db
def test_real_add_child_writes_a_row_and_lists_it_ordered(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    tenant_id, connection_id = seeded_connection
    repo = PostgresPublishAttemptRepository()
    attempt = _start_real_attempt(repo, tenant_id, connection_id)

    repo.add_child(
        tenant_id=tenant_id,
        attempt_id=attempt.id,
        position=1,
        media_object_key=f"t/{tenant_id}/b",
        media_content_type="video/mp4",
        media_product_type="VIDEO",
    )
    repo.add_child(
        tenant_id=tenant_id,
        attempt_id=attempt.id,
        position=0,
        media_object_key=f"t/{tenant_id}/a",
        media_content_type="video/quicktime",
        media_product_type="VIDEO",
    )

    ordered = repo.list_children(tenant_id=tenant_id, attempt_id=attempt.id)
    assert [c.media_object_key for c in ordered] == [f"t/{tenant_id}/a", f"t/{tenant_id}/b"]
    assert all(c.status == "pending" and c.creation_id is None for c in ordered)


@pytest.mark.db
def test_real_duplicate_position_returns_the_existing_child_not_a_second_row(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    """`uq_attempt_child_position` (0016), translated the same way
    `uq_attempt_idempotency` already is for the parent attempt."""
    tenant_id, connection_id = seeded_connection
    repo = PostgresPublishAttemptRepository()
    attempt = _start_real_attempt(repo, tenant_id, connection_id)
    kwargs = {
        "tenant_id": tenant_id,
        "attempt_id": attempt.id,
        "position": 0,
        "media_object_key": f"t/{tenant_id}/x",
        "media_content_type": "video/mp4",
        "media_product_type": "VIDEO",
    }

    first = repo.add_child(**kwargs)
    second = repo.add_child(**kwargs)

    assert first.created and not second.created
    assert second.record.id == first.record.id
    with tenant_session(tenant_id) as session:
        count = session.scalar(
            text("SELECT count(*) FROM publish_attempt_children WHERE attempt_id = :aid"),
            {"aid": str(attempt.id)},
        )
    assert count == 1


@pytest.mark.db
def test_real_add_child_on_an_unknown_attempt_raises_rather_than_masking_the_fk_violation(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    """A bad `attempt_id` also raises `IntegrityError` on insert (the FK, not the unique
    constraint) — `add_child` must not mistake that for a benign duplicate-position retry
    and silently return nothing useful."""
    tenant_id, _connection_id = seeded_connection
    repo = PostgresPublishAttemptRepository()

    with pytest.raises(IntegrityError):
        repo.add_child(
            tenant_id=tenant_id,
            attempt_id=uuid4(),  # no such attempt
            position=0,
            media_object_key=f"t/{tenant_id}/orphan",
            media_content_type="video/mp4",
            media_product_type="VIDEO",
        )


@pytest.mark.db
def test_real_record_child_creation_id_is_independent_of_the_parent(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    tenant_id, connection_id = seeded_connection
    repo = PostgresPublishAttemptRepository()
    attempt = _start_real_attempt(repo, tenant_id, connection_id)
    child = repo.add_child(
        tenant_id=tenant_id,
        attempt_id=attempt.id,
        position=0,
        media_object_key=f"t/{tenant_id}/a",
        media_content_type="video/mp4",
        media_product_type="VIDEO",
    ).record

    repo.record_creation_id(tenant_id=tenant_id, attempt_id=attempt.id, creation_id="carousel-c-1")
    repo.record_child_creation_id(tenant_id=tenant_id, child_id=child.id, creation_id="child-c-1")

    reread_attempt = repo.get_attempt(tenant_id=tenant_id, attempt_id=attempt.id)
    reread_child = repo.get_child(tenant_id=tenant_id, child_id=child.id)
    assert reread_attempt.creation_id == "carousel-c-1"
    assert reread_child.creation_id == "child-c-1"


@pytest.mark.db
def test_real_advance_and_settle_child_status(seeded_connection: tuple[UUID, UUID]) -> None:
    tenant_id, connection_id = seeded_connection
    repo = PostgresPublishAttemptRepository()
    attempt = _start_real_attempt(repo, tenant_id, connection_id)
    child = repo.add_child(
        tenant_id=tenant_id,
        attempt_id=attempt.id,
        position=0,
        media_object_key=f"t/{tenant_id}/a",
        media_content_type="video/mp4",
        media_product_type="VIDEO",
    ).record

    repo.advance_child_status(tenant_id=tenant_id, child_id=child.id, status="uploading")
    repo.advance_child_status(tenant_id=tenant_id, child_id=child.id, status="processing")
    repo.settle_child(tenant_id=tenant_id, child_id=child.id, status="finished")

    settled = repo.get_child(tenant_id=tenant_id, child_id=child.id)
    assert settled.status == "finished"
    assert settled.is_terminal

    # No settle-once trigger on this table (0016's design decision) — a further update
    # must NOT raise AlreadySettled, unlike the parent attempt.
    repo.settle_child(
        tenant_id=tenant_id,
        child_id=child.id,
        status="failed",
        platform_error_code="container_error",
    )
    resettled = repo.get_child(tenant_id=tenant_id, child_id=child.id)
    assert resettled.status == "failed"
    assert resettled.platform_error_code == "container_error"


@pytest.mark.db
def test_real_rls_makes_another_tenants_children_invisible(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    tenant_id, connection_id = seeded_connection
    repo = PostgresPublishAttemptRepository()
    attempt = _start_real_attempt(repo, tenant_id, connection_id)
    child = repo.add_child(
        tenant_id=tenant_id,
        attempt_id=attempt.id,
        position=0,
        media_object_key=f"t/{tenant_id}/a",
        media_content_type="video/mp4",
        media_product_type="VIDEO",
    ).record

    assert repo.get_child(tenant_id=OTHER_TENANT, child_id=child.id) is None
    assert repo.list_children(tenant_id=OTHER_TENANT, attempt_id=attempt.id) == []

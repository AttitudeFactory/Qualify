"""`db`-marked tests for the Planificador (QUA-108): migration 0024's schema and RLS,
the Postgres repository, and the temporary `DraftPostReader` over real creative rows.

Same two-door fixture split the publishing schema tests use: provisioning through
`admin_session` (BYPASSRLS), everything under test through `tenant_session`.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.creative import models as creative
from qualify_api.planner.composition import PostgresConnectionGate, tenant_timezone
from qualify_api.planner.draft_post_reader import DraftPostReader
from qualify_api.planner.fsm import EventTrigger, apply_transition
from qualify_api.planner.post_reader import ApprovalStatus
from qualify_api.planner.repository import (
    MemoryPlannerRepository,
    NewEvent,
    PostgresPlannerRepository,
)
from qualify_api.planner.rules import idempotency_key
from qualify_api.planner.service import PlannerService
from qualify_api.publishing.repository import PostgresPublishAttemptRepository
from qualify_api.tenancy.models import Brand, Tenant, User

pytestmark = pytest.mark.db

TENANT_P = UUID("e0000000-0000-4000-8000-0000000001a8")
TENANT_Q = UUID("e0000000-0000-4000-8000-0000000001b8")


def _provision(tenant_id: UUID, name: str) -> tuple[UUID, UUID, UUID]:
    """(brand_id, user_id, active connection_id) for `tenant_id`, idempotent."""
    with admin_session() as session:
        if session.get(Tenant, tenant_id) is None:
            session.add(
                Tenant(
                    id=tenant_id,
                    name=name,
                    country="VE",
                    timezone="America/Caracas",
                    currency="USD",
                )
            )
            session.flush()
        brand = session.scalar(select(Brand).where(Brand.tenant_id == tenant_id))
        if brand is None:
            brand = Brand(tenant_id=tenant_id, name=f"brand-{name}")
            session.add(brand)
            session.flush()
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        session.add(app)
        session.flush()
        user = User(tenant_id=tenant_id, email=f"u-{uuid4()}@p.co", display_name="U")
        session.add(user)
        session.flush()
        brand_id, app_id, user_id = brand.id, app.id, user.id

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
    return brand_id, user_id, connection_id


def _draft(
    tenant_id: UUID,
    brand_id: UUID,
    *,
    status: str,
    topic: str = "Promo de octubre",
    image_url: str | None = "https://cdn.example/img.jpg",
    expires_in: timedelta | None = timedelta(days=1),
    object_key: str | None = None,
) -> UUID:
    with tenant_session(tenant_id) as session:
        brief = creative.ContentBrief(
            tenant_id=tenant_id,
            brand_id=brand_id,
            objective="sale",
            topic=topic,
            platform="instagram",
            format="feed_4_5",
            intent="organic",
            content_type="promotion",
            image_route="template_only",
        )
        session.add(brief)
        session.flush()
        draft = creative.ContentDraft(
            tenant_id=tenant_id, brief_id=brief.id, brand_id=brand_id, status=status
        )
        session.add(draft)
        session.flush()
        session.add(
            creative.CopyVariant(
                tenant_id=tenant_id,
                draft_id=draft.id,
                ordinal=1,
                copy={"hook": "¡Oferta!", "caption": "Dos por uno   todo octubre", "cta": ""},
            )
        )
        if image_url is not None:
            session.add(
                creative.ImageAsset(
                    tenant_id=tenant_id,
                    draft_id=draft.id,
                    media_url=image_url,
                    media_expires_at=(
                        datetime.now(UTC) + expires_in if expires_in is not None else None
                    ),
                    object_key=object_key,
                )
            )
        session.flush()
        return draft.id


@pytest.fixture
def world_p() -> tuple[UUID, UUID, UUID]:
    return _provision(TENANT_P, "t-planner-p")


@pytest.fixture
def world_q() -> tuple[UUID, UUID, UUID]:
    return _provision(TENANT_Q, "t-planner-q")


def _new_event(
    tenant_id: UUID, brand_id: UUID, user_id: UUID, connection_id: UUID, *, hours: int = 24
) -> NewEvent:
    return NewEvent(
        tenant_id=tenant_id,
        brand_id=brand_id,
        post_id=uuid4(),
        connection_id=connection_id,
        scheduled_at=datetime.now(UTC) + timedelta(hours=hours),
        scheduled_tz="America/Caracas",
        created_by_user_id=user_id,
    )


# --- schema / RLS ------------------------------------------------------------


def test_repository_round_trip_under_rls(world_p) -> None:
    brand_id, user_id, conn_id = world_p
    repo = PostgresPlannerRepository()
    event = repo.add(_new_event(TENANT_P, brand_id, user_id, conn_id))
    assert event.status == "scheduled" and event.revision == 1
    assert repo.get(tenant_id=TENANT_P, event_id=event.id) == event


def test_another_tenant_cannot_read_or_update_the_event(world_p, world_q) -> None:
    brand_id, user_id, conn_id = world_p
    repo = PostgresPlannerRepository()
    event = repo.add(_new_event(TENANT_P, brand_id, user_id, conn_id))
    assert repo.get(tenant_id=TENANT_Q, event_id=event.id) is None
    assert (
        repo.set_status(
            tenant_id=TENANT_Q,
            event_id=event.id,
            expected_status="scheduled",
            new_status="cancelled",
        )
        is None
    )
    assert repo.get(tenant_id=TENANT_P, event_id=event.id).status == "scheduled"


def test_an_event_cannot_point_at_another_tenants_connection(world_p, world_q) -> None:
    brand_id, user_id, _ = world_p
    _, _, foreign_conn = world_q
    with pytest.raises(IntegrityError):
        PostgresPlannerRepository().add(_new_event(TENANT_P, brand_id, user_id, foreign_conn))


def test_status_check_rejects_unknown_values(world_p) -> None:
    brand_id, user_id, conn_id = world_p
    event = PostgresPlannerRepository().add(_new_event(TENANT_P, brand_id, user_id, conn_id))
    with pytest.raises(DBAPIError), tenant_session(TENANT_P) as session:
        session.execute(
            text("UPDATE calendar_events SET status = 'bogus' WHERE id = :id"),
            {"id": str(event.id)},
        )


def test_reschedule_is_compare_and_set_on_revision(world_p) -> None:
    brand_id, user_id, conn_id = world_p
    repo = PostgresPlannerRepository()
    event = repo.add(_new_event(TENANT_P, brand_id, user_id, conn_id))
    target = datetime.now(UTC) + timedelta(days=3)
    moved = repo.reschedule(
        tenant_id=TENANT_P,
        event_id=event.id,
        expected_revision=1,
        scheduled_at=target,
        scheduled_tz="America/Bogota",
        connection_id=conn_id,
    )
    assert moved is not None and moved.revision == 2 and moved.scheduled_tz == "America/Bogota"
    stale = repo.reschedule(
        tenant_id=TENANT_P,
        event_id=event.id,
        expected_revision=1,
        scheduled_at=target,
        scheduled_tz="America/Caracas",
        connection_id=conn_id,
    )
    assert stale is None


def test_list_range_and_list_due(world_p) -> None:
    brand_id, user_id, conn_id = world_p
    repo = PostgresPlannerRepository()
    soon = repo.add(_new_event(TENANT_P, brand_id, user_id, conn_id, hours=1))
    far = repo.add(_new_event(TENANT_P, brand_id, user_id, conn_id, hours=24 * 30))
    window = repo.list_range(
        tenant_id=TENANT_P,
        brand_id=brand_id,
        start=datetime.now(UTC),
        end=datetime.now(UTC) + timedelta(hours=2),
    )
    ids = {e.id for e in window}
    assert soon.id in ids and far.id not in ids
    due = repo.list_due(tenant_id=TENANT_P, now=datetime.now(UTC) + timedelta(hours=2))
    assert soon.id in {e.id for e in due}
    assert far.id not in {e.id for e in due}


# --- composition ---------------------------------------------------------------


def test_connection_gate_and_tenant_timezone(world_p, world_q) -> None:
    _, _, conn_p = world_p
    gate = PostgresConnectionGate()
    assert gate.status(tenant_id=TENANT_P, connection_id=conn_p) == "active"
    assert gate.status(tenant_id=TENANT_Q, connection_id=conn_p) is None  # RLS
    assert tenant_timezone(TENANT_P) == "America/Caracas"


# --- temporary DraftPostReader --------------------------------------------------


def test_draft_reader_maps_status_to_approval_and_reads_the_card_fields(world_p) -> None:
    brand_id, _, _ = world_p
    pending = _draft(TENANT_P, brand_id, status="generated")
    approved = _draft(TENANT_P, brand_id, status="approved", object_key="t/x/img.jpg")
    rejected = _draft(TENANT_P, brand_id, status="rejected")
    reader = DraftPostReader()

    got = reader.get_many(tenant_id=TENANT_P, post_ids=[pending, approved, rejected])
    assert got[pending].approval is ApprovalStatus.PENDING
    assert got[approved].approval is ApprovalStatus.APPROVED
    assert got[rejected].approval is ApprovalStatus.REJECTED

    card = got[pending]
    assert card.title == "Promo de octubre"
    assert card.caption_excerpt == "Dos por uno todo octubre"  # whitespace collapsed
    assert card.thumbnail_url == "https://cdn.example/img.jpg"
    assert card.category == "feed" and card.media_product_type == "IMAGE"
    assert card.content_type == "promotion"
    assert card.reuse_type is None  # the draft model has no such concept
    assert card.asset_count == 1 and card.asset_types == ("IMAGE",)
    assert card.detail_href == f"/drafts/{pending}"
    assert not card.is_publishable and card.unpublishable_reason
    assert got[approved].is_publishable  # its image has an R2 key


def test_draft_reader_hides_an_expired_thumbnail(world_p) -> None:
    brand_id, _, _ = world_p
    expired = _draft(TENANT_P, brand_id, status="approved", expires_in=timedelta(hours=-1))
    assert DraftPostReader().get(tenant_id=TENANT_P, post_id=expired).thumbnail_url is None


def test_draft_reader_lists_only_schedulable_and_respects_rls(world_p, world_q) -> None:
    brand_id, _, _ = world_p
    pending = _draft(TENANT_P, brand_id, status="generated")
    rejected = _draft(TENANT_P, brand_id, status="rejected")
    reader = DraftPostReader()
    listed = {p.post_id for p in reader.list_schedulable(tenant_id=TENANT_P, brand_id=brand_id)}
    assert pending in listed and rejected not in listed
    assert reader.get(tenant_id=TENANT_Q, post_id=pending) is None


def test_draft_reader_never_writes(world_p) -> None:
    brand_id, _, _ = world_p
    draft_id = _draft(TENANT_P, brand_id, status="drafting")
    with tenant_session(TENANT_P) as session:
        before = session.get(creative.ContentDraft, draft_id).updated_at
    DraftPostReader().get(tenant_id=TENANT_P, post_id=draft_id)
    DraftPostReader().list_schedulable(tenant_id=TENANT_P, brand_id=brand_id)
    with tenant_session(TENANT_P) as session:
        row = session.get(creative.ContentDraft, draft_id)
        assert row.status == "drafting" and row.updated_at == before


# --- service end to end over Postgres ---------------------------------------------


def test_service_schedules_a_real_draft_and_it_leaves_unscheduled(world_p) -> None:
    brand_id, user_id, conn_id = world_p
    draft_id = _draft(TENANT_P, brand_id, status="approved")
    svc = PlannerService(
        repository=PostgresPlannerRepository(),
        posts=DraftPostReader(),
        connections=PostgresConnectionGate(),
    )
    assert draft_id in {
        p.post_id for p in svc.list_unscheduled(tenant_id=TENANT_P, brand_id=brand_id)
    }
    at = datetime.now(UTC) + timedelta(days=2)
    event = svc.schedule(
        tenant_id=TENANT_P,
        brand_id=brand_id,
        post_id=draft_id,
        connection_id=conn_id,
        scheduled_at=at,
        scheduled_tz="America/Caracas",
        user_id=user_id,
    )
    assert draft_id not in {
        p.post_id for p in svc.list_unscheduled(tenant_id=TENANT_P, brand_id=brand_id)
    }
    monday = (at.astimezone(UTC).date()) - timedelta(days=at.astimezone(UTC).weekday())
    week = svc.list_week(
        tenant_id=TENANT_P,
        brand_id=brand_id,
        monday=date.fromordinal(monday.toordinal()),
        tz_name="UTC",
    )
    assert event.id in {p.event.id for p in week}


# --- planning tags (0025) -------------------------------------------------------------


def test_tag_names_are_unique_per_tenant_ignoring_case(world_p) -> None:
    repo = PostgresPlannerRepository()
    name = f"Etiqueta {uuid4().hex[:6]}"
    repo.add_tag(tenant_id=TENANT_P, name=name, color="teal")
    with pytest.raises(IntegrityError):
        repo.add_tag(tenant_id=TENANT_P, name=name.upper(), color="blue")
    assert repo.find_tag(tenant_id=TENANT_P, name=name.lower()) is not None


def test_tag_colour_is_checked(world_p) -> None:
    with pytest.raises(IntegrityError):
        PostgresPlannerRepository().add_tag(
            tenant_id=TENANT_P, name=f"x-{uuid4().hex[:6]}", color="chartreuse"
        )


def test_event_tags_round_trip_and_stay_in_their_tenant(world_p, world_q) -> None:
    brand_id, user_id, conn_id = world_p
    repo = PostgresPlannerRepository()
    event = repo.add(_new_event(TENANT_P, brand_id, user_id, conn_id))
    tag = repo.add_tag(tenant_id=TENANT_P, name=f"Promo {uuid4().hex[:6]}", color="pink")
    repo.replace_event_tags(tenant_id=TENANT_P, event_id=event.id, tag_ids=[tag.id])
    assert [
        t.id for t in repo.tags_for_events(tenant_id=TENANT_P, event_ids=[event.id])[event.id]
    ] == [tag.id]
    assert repo.tags_for_events(tenant_id=TENANT_Q, event_ids=[event.id]) == {event.id: []}
    repo.replace_event_tags(tenant_id=TENANT_P, event_id=event.id, tag_ids=[])
    assert repo.tags_for_events(tenant_id=TENANT_P, event_ids=[event.id])[event.id] == []


def test_an_event_cannot_carry_another_tenants_tag(world_p, world_q) -> None:
    brand_id, user_id, conn_id = world_p
    repo = PostgresPlannerRepository()
    event = repo.add(_new_event(TENANT_P, brand_id, user_id, conn_id))
    foreign = repo.add_tag(tenant_id=TENANT_Q, name=f"Ajena {uuid4().hex[:6]}", color="gray")
    with pytest.raises((IntegrityError, DBAPIError)):
        repo.replace_event_tags(tenant_id=TENANT_P, event_id=event.id, tag_ids=[foreign.id])


def test_delete_tag_removes_links_and_is_tenant_scoped(world_p, world_q) -> None:
    brand_id, user_id, conn_id = world_p
    repo = PostgresPlannerRepository()
    event = repo.add(_new_event(TENANT_P, brand_id, user_id, conn_id))
    tag = repo.add_tag(tenant_id=TENANT_P, name=f"Borrar {uuid4().hex[:6]}", color="teal")
    repo.replace_event_tags(tenant_id=TENANT_P, event_id=event.id, tag_ids=[tag.id])
    assert repo.delete_tag(tenant_id=TENANT_Q, tag_id=tag.id) is False  # RLS: invisible
    assert repo.delete_tag(tenant_id=TENANT_P, tag_id=tag.id) is True
    assert repo.tags_for_events(tenant_id=TENANT_P, event_ids=[event.id])[event.id] == []
    assert repo.find_tag(tenant_id=TENANT_P, name=tag.name) is None
    assert repo.get(tenant_id=TENANT_P, event_id=event.id) is not None


def test_delete_cancelled_only_deletes_cancelled_events(world_p) -> None:
    brand_id, user_id, conn_id = world_p
    repo = PostgresPlannerRepository()
    event = repo.add(_new_event(TENANT_P, brand_id, user_id, conn_id))
    tag = repo.add_tag(tenant_id=TENANT_P, name=f"Del {uuid4().hex[:6]}", color="gray")
    repo.replace_event_tags(tenant_id=TENANT_P, event_id=event.id, tag_ids=[tag.id])
    assert repo.delete_cancelled(tenant_id=TENANT_P, event_id=event.id) is False
    repo.set_status(
        tenant_id=TENANT_P, event_id=event.id, expected_status="scheduled", new_status="cancelled"
    )
    assert repo.delete_cancelled(tenant_id=TENANT_P, event_id=event.id) is True
    assert repo.get(tenant_id=TENANT_P, event_id=event.id) is None
    assert repo.find_tag(tenant_id=TENANT_P, name=tag.name) is not None  # the tag stays


# --- execution: claim / link / in-flight (QUA-111 F1) ---------------------------
#
# The contract tests run against BOTH repositories, so the in-memory stand-in the unit
# tests use cannot drift from the Postgres semantics. The race test is Postgres-only: it
# is the database's row lock that makes the claim atomic, not the Python code.


@pytest.fixture(params=["memory", "postgres"])
def repo(request: pytest.FixtureRequest) -> MemoryPlannerRepository | PostgresPlannerRepository:
    return MemoryPlannerRepository() if request.param == "memory" else PostgresPlannerRepository()


def _attempt_id(repo: object, tenant_id: UUID, connection_id: UUID) -> UUID:
    """A publish attempt the event may link to: a real row for Postgres (the composite FK
    demands it), any id for the in-memory repository."""
    if isinstance(repo, MemoryPlannerRepository):
        return uuid4()
    return (
        PostgresPublishAttemptRepository()
        .start_attempt(
            tenant_id=tenant_id,
            connection_id=connection_id,
            idempotency_key=f"test-{uuid4()}",
            media_product_type="REELS",
            adapter_version="test",
        )
        .record.id
    )


def _due_event(repo, world, *, hours: int = -1):
    brand_id, user_id, conn_id = world
    return repo.add(_new_event(TENANT_P, brand_id, user_id, conn_id, hours=hours))


def _retire(repo, *events) -> None:
    """Cancel what a test left `scheduled`. These tests run against the shared dev
    database with no teardown (nothing is deleted), and a past-due `scheduled` row that
    outlives its test is exactly what crowds `list_due`'s default limit for everyone
    else."""
    for event in events:
        repo.set_status(
            tenant_id=TENANT_P,
            event_id=event.id,
            expected_status="scheduled",
            new_status="cancelled",
        )


def test_claim_moves_a_due_scheduled_event_to_publishing_once(repo, world_p) -> None:
    event = _due_event(repo, world_p)
    now = datetime.now(UTC)
    claimed = repo.claim(tenant_id=TENANT_P, event_id=event.id, expected_revision=1, now=now)
    assert claimed is not None
    assert claimed.status == apply_transition("scheduled", EventTrigger.CLAIM) == "publishing"
    assert claimed.revision == 1 and claimed.publish_attempt_id is None
    assert idempotency_key(claimed.id, claimed.revision) == f"cal:{event.id}:1"
    # A second claim of the same event (a second executor, or a replay) wins nothing.
    assert repo.claim(tenant_id=TENANT_P, event_id=event.id, expected_revision=1, now=now) is None


def test_claim_with_a_stale_revision_fails(repo, world_p) -> None:
    _, _, conn_id = world_p
    event = _due_event(repo, world_p)
    moved = repo.reschedule(
        tenant_id=TENANT_P,
        event_id=event.id,
        expected_revision=1,
        scheduled_at=event.scheduled_at,
        scheduled_tz=event.scheduled_tz,
        connection_id=conn_id,
    )
    assert moved is not None and moved.revision == 2
    now = datetime.now(UTC)
    assert repo.claim(tenant_id=TENANT_P, event_id=event.id, expected_revision=1, now=now) is None
    assert repo.get(tenant_id=TENANT_P, event_id=event.id).status == "scheduled"
    _retire(repo, event)


def test_claim_before_scheduled_at_fails(repo, world_p) -> None:
    event = _due_event(repo, world_p, hours=2)
    claimed = repo.claim(
        tenant_id=TENANT_P, event_id=event.id, expected_revision=1, now=datetime.now(UTC)
    )
    assert claimed is None
    assert repo.get(tenant_id=TENANT_P, event_id=event.id).status == "scheduled"
    _retire(repo, event)


def test_claim_of_a_cancelled_event_fails(repo, world_p) -> None:
    event = _due_event(repo, world_p)
    repo.set_status(
        tenant_id=TENANT_P, event_id=event.id, expected_status="scheduled", new_status="cancelled"
    )
    claimed = repo.claim(
        tenant_id=TENANT_P, event_id=event.id, expected_revision=1, now=datetime.now(UTC)
    )
    assert claimed is None
    assert repo.get(tenant_id=TENANT_P, event_id=event.id).status == "cancelled"


def test_another_tenant_cannot_claim_the_event(repo, world_p, world_q) -> None:
    event = _due_event(repo, world_p)
    now = datetime.now(UTC)
    assert repo.claim(tenant_id=TENANT_Q, event_id=event.id, expected_revision=1, now=now) is None
    assert repo.get(tenant_id=TENANT_P, event_id=event.id).status == "scheduled"
    _retire(repo, event)


def test_once_claimed_the_event_can_no_longer_be_moved_or_cancelled(repo, world_p) -> None:
    """QUA-108's existing compare-and-set on `status='scheduled'` is what locks the
    operator out after a claim — F1 relies on it and does not change it."""
    _, _, conn_id = world_p
    event = _due_event(repo, world_p)
    repo.claim(tenant_id=TENANT_P, event_id=event.id, expected_revision=1, now=datetime.now(UTC))
    assert (
        repo.reschedule(
            tenant_id=TENANT_P,
            event_id=event.id,
            expected_revision=1,
            scheduled_at=datetime.now(UTC) + timedelta(days=1),
            scheduled_tz=event.scheduled_tz,
            connection_id=conn_id,
        )
        is None
    )
    assert (
        repo.set_status(
            tenant_id=TENANT_P,
            event_id=event.id,
            expected_status="scheduled",
            new_status="cancelled",
        )
        is None
    )


def test_link_attempt_is_idempotent_for_the_same_attempt(repo, world_p) -> None:
    _, _, conn_id = world_p
    event = _due_event(repo, world_p)
    repo.claim(tenant_id=TENANT_P, event_id=event.id, expected_revision=1, now=datetime.now(UTC))
    attempt = _attempt_id(repo, TENANT_P, conn_id)
    first = repo.link_attempt(
        tenant_id=TENANT_P, event_id=event.id, expected_revision=1, attempt_id=attempt
    )
    again = repo.link_attempt(
        tenant_id=TENANT_P, event_id=event.id, expected_revision=1, attempt_id=attempt
    )
    assert first is not None and first.publish_attempt_id == attempt
    assert again is not None and again.publish_attempt_id == attempt
    assert again.status == "publishing"


def test_link_attempt_never_replaces_a_different_attempt(repo, world_p) -> None:
    _, _, conn_id = world_p
    event = _due_event(repo, world_p)
    repo.claim(tenant_id=TENANT_P, event_id=event.id, expected_revision=1, now=datetime.now(UTC))
    attempt = _attempt_id(repo, TENANT_P, conn_id)
    other = _attempt_id(repo, TENANT_P, conn_id)
    repo.link_attempt(
        tenant_id=TENANT_P, event_id=event.id, expected_revision=1, attempt_id=attempt
    )
    refused = repo.link_attempt(
        tenant_id=TENANT_P, event_id=event.id, expected_revision=1, attempt_id=other
    )
    assert refused is None
    assert repo.get(tenant_id=TENANT_P, event_id=event.id).publish_attempt_id == attempt


def test_link_attempt_outside_publishing_or_at_another_revision_is_refused(repo, world_p) -> None:
    _, _, conn_id = world_p
    attempt = _attempt_id(repo, TENANT_P, conn_id)
    scheduled = _due_event(repo, world_p)
    assert (
        repo.link_attempt(
            tenant_id=TENANT_P, event_id=scheduled.id, expected_revision=1, attempt_id=attempt
        )
        is None
    )
    assert repo.get(tenant_id=TENANT_P, event_id=scheduled.id).publish_attempt_id is None
    _retire(repo, scheduled)

    claimed = _due_event(repo, world_p)
    repo.claim(tenant_id=TENANT_P, event_id=claimed.id, expected_revision=1, now=datetime.now(UTC))
    assert (
        repo.link_attempt(
            tenant_id=TENANT_P, event_id=claimed.id, expected_revision=2, attempt_id=attempt
        )
        is None
    )


def test_list_in_flight_returns_only_the_tenants_publishing_events(repo, world_p, world_q) -> None:
    claimed = _due_event(repo, world_p)
    waiting = _due_event(repo, world_p)
    repo.claim(tenant_id=TENANT_P, event_id=claimed.id, expected_revision=1, now=datetime.now(UTC))
    in_flight = repo.list_in_flight(tenant_id=TENANT_P, limit=10_000)
    assert claimed.id in {e.id for e in in_flight}
    assert waiting.id not in {e.id for e in in_flight}
    assert all(e.status == "publishing" for e in in_flight)
    assert claimed.id not in {e.id for e in repo.list_in_flight(tenant_id=TENANT_Q)}
    _retire(repo, waiting)


def test_two_concurrent_claims_exactly_one_wins(world_p) -> None:
    """The real race: N threads, each on its own pooled connection, released together by
    a barrier against the same due event. Repeated so a lucky interleaving cannot pass."""
    repo = PostgresPlannerRepository()
    contenders = 4
    for _ in range(5):
        event = _due_event(repo, world_p)
        barrier = threading.Barrier(contenders)

        def contend(_: int, event_id: UUID = event.id, gate: threading.Barrier = barrier):
            gate.wait()
            return repo.claim(
                tenant_id=TENANT_P,
                event_id=event_id,
                expected_revision=1,
                now=datetime.now(UTC),
            )

        with ThreadPoolExecutor(max_workers=contenders) as pool:
            results = list(pool.map(contend, range(contenders)))
        assert sum(r is not None for r in results) == 1
        assert repo.get(tenant_id=TENANT_P, event_id=event.id).status == "publishing"

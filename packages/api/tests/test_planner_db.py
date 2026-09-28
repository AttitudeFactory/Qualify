"""`db`-marked tests for the Planificador (QUA-108): migration 0024's schema and RLS,
the Postgres repository, and the temporary `DraftPostReader` over real creative rows.

Same two-door fixture split the publishing schema tests use: provisioning through
`admin_session` (BYPASSRLS), everything under test through `tenant_session`.
"""

from __future__ import annotations

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
from qualify_api.planner.post_reader import ApprovalStatus
from qualify_api.planner.repository import NewEvent, PostgresPlannerRepository
from qualify_api.planner.service import PlannerService
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

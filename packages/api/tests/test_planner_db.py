"""`db`-marked tests for the Planificador (QUA-108): migration 0024's schema and RLS,
the Postgres repository, and the temporary `DraftPostReader` over real creative rows.

Same two-door fixture split the publishing schema tests use: provisioning through
`admin_session` (BYPASSRLS), everything under test through `tenant_session`.
"""

from __future__ import annotations

import asyncio
import io
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from qualify_shared.objects.gate import ObjectGate
from qualify_shared.objects.keys import media_key
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.creative import models as creative
from qualify_api.planner import draft_post_reader
from qualify_api.planner.composition import PostgresConnectionGate, tenant_timezone
from qualify_api.planner.discovery import DiscoveredTenants, ScopedTenants
from qualify_api.planner.draft_post_reader import DraftPostReader
from qualify_api.planner.embedded import (
    EmbeddedCalendarWorker,
    EmbeddedWorkerConfig,
    WorkerMode,
)
from qualify_api.planner.executor import (
    AdvanceOutcome,
    EventExecutor,
    ExecutionOutcome,
    SettleOutcome,
)
from qualify_api.planner.fsm import EventTrigger, apply_transition
from qualify_api.planner.locks import PostgresAdvisoryLock, attempt_lock_key
from qualify_api.planner.post_reader import (
    ApprovalStatus,
    NotPublishable,
    PublishablePost,
    UnpublishableReason,
)
from qualify_api.planner.publishable import REASON_TEXT
from qualify_api.planner.repository import (
    EventRecord,
    MemoryPlannerRepository,
    NewEvent,
    PostgresPlannerRepository,
)
from qualify_api.planner.rules import idempotency_key
from qualify_api.planner.service import DuplicateEvent, PlannerService
from qualify_api.planner.tick import TickRunner
from qualify_api.publishing.client import (
    ContainerStatus,
    RecentMedia,
    ResumableContainer,
    UploadOutcome,
)
from qualify_api.publishing.composition import PostgresConnectionTargetReader
from qualify_api.publishing.repository import PostgresPublishAttemptRepository
from qualify_api.publishing.service import PublishService
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
    # The POST's own category (0027), never the brief's render format; this row has none.
    assert card.category is None and card.media_product_type is None
    assert card.content_type == "promotion"
    assert card.reuse_type is None  # `content_drafts.reuse_type` (0027) not set on this row
    assert card.times_published == 0 and card.has_live_event is False  # QUA-118 D2
    assert card.asset_count == 1 and card.asset_types == ("IMAGE",)
    assert card.detail_href == f"/drafts/{pending}"
    assert not card.is_publishable and card.unpublishable_reason
    # QUA-111 F2: "has an object_key" is no longer "publishable" — this row has no
    # approved_revision, no category, and a key outside its tenant's prefix.
    assert not got[approved].is_publishable and got[approved].unpublishable_reason


def test_draft_reader_hides_an_expired_thumbnail(world_p) -> None:
    brand_id, _, _ = world_p
    expired = _draft(TENANT_P, brand_id, status="approved", expires_in=timedelta(hours=-1))
    assert DraftPostReader().get(tenant_id=TENANT_P, post_id=expired).thumbnail_url is None


def test_draft_reader_lists_only_schedulable_and_respects_rls(world_p, world_q) -> None:
    brand_id, _, _ = world_p
    pending = _draft(TENANT_P, brand_id, status="generated")
    approved = _draft(TENANT_P, brand_id, status="approved")
    rejected = _draft(TENANT_P, brand_id, status="rejected")
    reader = DraftPostReader()
    listed = {p.post_id for p in reader.list_schedulable(tenant_id=TENANT_P, brand_id=brand_id)}
    # QUA-118 D1: only an approved draft can be planned; a pending one is no longer listed.
    assert approved in listed and pending not in listed and rejected not in listed
    assert reader.get(tenant_id=TENANT_Q, post_id=pending) is None


def test_draft_reader_lists_every_post_of_the_brand_for_the_gallery(world_p, world_q) -> None:
    """QUA-118 gallery: `list_for_brand` returns drafts in every state, newest first,
    each with its history — and nothing of another tenant or brand."""
    brand_id, _, _ = world_p
    drafting = _draft(TENANT_P, brand_id, status="drafting")
    pending = _draft(TENANT_P, brand_id, status="generated")
    approved = _draft(TENANT_P, brand_id, status="approved")
    rejected = _draft(TENANT_P, brand_id, status="rejected")
    reader = DraftPostReader()
    listed = reader.list_for_brand(tenant_id=TENANT_P, brand_id=brand_id)
    ids = [p.post_id for p in listed]
    assert {drafting, pending, approved, rejected} <= set(ids)
    assert ids.index(rejected) < ids.index(drafting)  # newest first
    mine = [p for p in listed if p.post_id in {drafting, pending, approved, rejected}]
    assert all(p.times_published == 0 and p.has_live_event is False for p in mine)
    assert reader.list_for_brand(tenant_id=TENANT_Q, brand_id=brand_id) == []


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
    # QUA-118 D1: approved AND publishable — `_post_row` shapes a real publishable POST.
    draft_id = _post_row((TENANT_P, brand_id, conn_id))
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
    # QUA-118 D2: the reader sees the live event in the POST's history (one aggregate).
    summary = DraftPostReader().get(tenant_id=TENANT_P, post_id=draft_id)
    assert summary.has_live_event is True and summary.times_published == 0
    # ...and stops seeing it once the calendar would call it «Vencido» (QUA-115 window).
    later = DraftPostReader(clock=lambda: at + timedelta(hours=25))
    assert later.get(tenant_id=TENANT_P, post_id=draft_id).has_live_event is False
    monday = (at.astimezone(UTC).date()) - timedelta(days=at.astimezone(UTC).weekday())
    week = svc.list_week(
        tenant_id=TENANT_P,
        brand_id=brand_id,
        monday=date.fromordinal(monday.toordinal()),
        tz_name="UTC",
    )
    assert event.id in {p.event.id for p in week}


# --- QUA-118 Phase 2: many events in one transaction ------------------------------------


def test_add_many_is_all_or_nothing_on_postgres(world_p, world_q) -> None:
    """Three events in one batch, the third pointing at another tenant's connection:
    the FK/RLS refusal rolls the first two back as well — zero rows."""
    brand_id, user_id, conn_id = world_p
    _, _, foreign_conn = world_q
    post_id = uuid4()
    repo = PostgresPlannerRepository()
    batch = [
        _new_event(TENANT_P, brand_id, user_id, conn_id, hours=24),
        _new_event(TENANT_P, brand_id, user_id, conn_id, hours=48),
        _new_event(TENANT_P, brand_id, user_id, foreign_conn, hours=72),
    ]
    batch = [replace(new, post_id=post_id) for new in batch]
    with pytest.raises(Exception):  # noqa: B017 — the FK / RLS refusal, whichever fires
        repo.add_many(batch)
    assert repo.list_for_post(tenant_id=TENANT_P, post_id=post_id) == []
    # The same batch without the foreign row lands whole, in order.
    created = repo.add_many(batch[:2])
    assert [e.id for e in repo.list_for_post(tenant_id=TENANT_P, post_id=post_id)] == [
        e.id for e in created
    ]
    with pytest.raises(ValueError):
        repo.add_many([batch[0], replace(batch[1], tenant_id=TENANT_Q)])


def test_service_creates_a_weekly_series_over_postgres(world_p) -> None:
    """A real publishable POST, three Mondays, one account: three independent rows at
    revision 1, seven days apart, every one of them visible to the week and due-list
    queries on its own."""
    brand_id, user_id, conn_id = world_p
    draft_id = _post_row((TENANT_P, brand_id, conn_id))
    svc = PlannerService(
        repository=PostgresPlannerRepository(),
        posts=DraftPostReader(),
        connections=PostgresConnectionGate(),
    )
    first_day = (datetime.now(UTC) + timedelta(days=3)).date()
    events = svc.schedule_series(
        tenant_id=TENANT_P,
        brand_id=brand_id,
        post_id=draft_id,
        connection_ids=[conn_id],
        first_day=first_day,
        at=time(10, 0),
        scheduled_tz="America/Caracas",
        user_id=user_id,
        count=3,
    )
    stored = svc._repo.list_for_post(tenant_id=TENANT_P, post_id=draft_id)
    assert [e.id for e in stored] == [e.id for e in events]
    assert [e.revision for e in stored] == [1, 1, 1]
    assert [e.scheduled_at - stored[0].scheduled_at for e in stored] == [
        timedelta(0),
        timedelta(days=7),
        timedelta(days=14),
    ]
    # The POST's history sees the live series; a one-shot POST leaves Sin programar.
    summary = DraftPostReader().get(tenant_id=TENANT_P, post_id=draft_id)
    assert summary.has_live_event is True
    assert draft_id not in {
        p.post_id for p in svc.list_unscheduled(tenant_id=TENANT_P, brand_id=brand_id)
    }
    # Planning it again on the same Mondays is a duplicate, and creates nothing.
    with pytest.raises(DuplicateEvent):
        svc.schedule_series(
            tenant_id=TENANT_P,
            brand_id=brand_id,
            post_id=draft_id,
            connection_ids=[conn_id],
            first_day=first_day,
            at=time(10, 0),
            scheduled_tz="America/Caracas",
            user_id=user_id,
            count=2,
        )
    assert len(svc._repo.list_for_post(tenant_id=TENANT_P, post_id=draft_id)) == 3


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


# --- the publishable POST (QUA-111 F2) --------------------------------------------
#
# A FRESH tenant per test run: these rows must never mix with what earlier runs left in
# the shared dev database (TENANT_P/TENANT_Q accumulate), nor be mistaken for real data.


@pytest.fixture(scope="module")
def world_f2() -> tuple[UUID, UUID, UUID]:
    tenant_id = uuid4()
    brand_id, _, connection_id = _provision(tenant_id, f"t-qua111-f2-{tenant_id.hex[:8]}")
    return tenant_id, brand_id, connection_id


_APPROVED_COPY = {
    "hook": "¡Oferta!",
    "caption": "Dos por uno todo octubre",
    "hashtags": ["promo", "#octubre"],
    "cta": "Pide ya",
}


def _post_row(
    world: tuple[UUID, UUID, UUID],
    *,
    status: str = "approved",
    revision: int = 1,
    approved_revision: int | None = 1,
    category: str | None = "galeria",
    edited: dict | None = None,
    items: list[tuple[str | None, str | None, str, int]] | None = None,
) -> UUID:
    """A draft shaped as a POST: two variants (the SECOND is the selected one), and
    `items` as (object_key, content_type, media_type, position). Default: one JPEG in
    the tenant's R2 prefix."""
    tenant_id, brand_id, conn_id = world
    if items is None:
        items = [(media_key(tenant_id, conn_id, uuid4().hex), "image/jpeg", "image", 0)]
    with tenant_session(tenant_id) as session:
        brief = creative.ContentBrief(
            tenant_id=tenant_id,
            brand_id=brand_id,
            objective="sale",
            topic="Promo",
            platform="instagram",
            format="feed_4_5",
            intent="organic",
            content_type="promotion",
            image_route="template_only",
        )
        session.add(brief)
        session.flush()
        draft = creative.ContentDraft(
            tenant_id=tenant_id,
            brief_id=brief.id,
            brand_id=brand_id,
            status=status,
            pipeline_version="test",
            category=category,
            revision=revision,
            approved_revision=approved_revision,
        )
        session.add(draft)
        session.flush()
        other = creative.CopyVariant(
            tenant_id=tenant_id,
            draft_id=draft.id,
            ordinal=0,
            copy={"hook": "Otra", "caption": "No elegida", "cta": ""},
            model_id="test",
        )
        chosen = creative.CopyVariant(
            tenant_id=tenant_id,
            draft_id=draft.id,
            ordinal=1,
            copy=_APPROVED_COPY,
            edited_copy=edited,
            model_id="test",
        )
        session.add_all([other, chosen])
        session.flush()
        if status in ("approved", "staged", "published"):
            draft.selected_variant_id = chosen.id
        for object_key, content_type, media_type, position in items:
            session.add(
                creative.ImageAsset(
                    tenant_id=tenant_id,
                    draft_id=draft.id,
                    media_url=object_key or "https://cdn.example/x",
                    object_key=object_key,
                    content_type=content_type,
                    media_type=media_type,
                    position=position,
                )
            )
        session.flush()
        return draft.id


def _publishable(world, post_id: UUID) -> PublishablePost | NotPublishable:
    return DraftPostReader().get_publishable(tenant_id=world[0], post_id=post_id)


def test_an_approved_post_at_its_approved_revision_is_publishable(world_f2) -> None:
    tenant_id, _, conn_id = world_f2
    keys = [media_key(tenant_id, conn_id, uuid4().hex) for _ in range(3)]
    post_id = _post_row(
        world_f2,
        items=[
            (keys[2], "image/jpeg", "image", 2),
            (keys[0], "video/mp4", "video", 0),
            (keys[1], "image/jpeg", "image", 1),
        ],
    )
    verdict = _publishable(world_f2, post_id)
    assert isinstance(verdict, PublishablePost)
    assert verdict.tenant_id == tenant_id and verdict.post_id == post_id
    assert verdict.approved_revision == 1
    assert verdict.media_product_type == "CAROUSEL"
    assert [m.object_key for m in verdict.media] == keys  # by position, not creation
    assert [m.media_type for m in verdict.media] == ["VIDEO", "IMAGE", "IMAGE"]
    # The SELECTED variant, rendered the one way the creative module defines.
    assert verdict.caption == "¡Oferta!\n\nDos por uno todo octubre\n\nPide ya\n\n#promo #octubre"


def test_the_caption_is_the_selected_variants_edited_copy(world_f2) -> None:
    edited = {**_APPROVED_COPY, "hook": "", "caption": "Editado antes de aprobar", "hashtags": []}
    verdict = _publishable(world_f2, _post_row(world_f2, edited=edited))
    assert isinstance(verdict, PublishablePost)
    assert verdict.caption == "Editado antes de aprobar\n\nPide ya"


def test_an_edit_after_approval_is_blocked(world_f2) -> None:
    verdict = _publishable(world_f2, _post_row(world_f2, revision=2, approved_revision=1))
    assert isinstance(verdict, NotPublishable)
    assert verdict.reason is UnpublishableReason.REVISION_NOT_APPROVED


def test_an_unapproved_post_is_blocked(world_f2) -> None:
    post_id = _post_row(world_f2, status="generated", approved_revision=None)
    verdict = _publishable(world_f2, post_id)
    assert isinstance(verdict, NotPublishable)
    assert verdict.reason is UnpublishableReason.NOT_APPROVED


def test_local_generated_media_is_blocked(world_f2) -> None:
    tenant_id = world_f2[0]
    local = f"generated/{tenant_id}/{uuid4()}/slide-1.png"
    verdict = _publishable(world_f2, _post_row(world_f2, items=[(local, None, "image", 0)]))
    assert isinstance(verdict, NotPublishable)
    assert verdict.reason is UnpublishableReason.MEDIA_NOT_IN_R2


def test_a_null_content_type_from_the_column_is_blocked(world_f2) -> None:
    tenant_id, _, conn_id = world_f2
    key = media_key(tenant_id, conn_id, uuid4().hex)
    verdict = _publishable(world_f2, _post_row(world_f2, items=[(key, None, "image", 0)]))
    assert isinstance(verdict, NotPublishable)
    assert verdict.reason is UnpublishableReason.CONTENT_TYPE_MISSING


def test_a_png_from_the_column_is_blocked_and_an_mp4_reel_passes(world_f2) -> None:
    tenant_id, _, conn_id = world_f2
    png = _post_row(
        world_f2, items=[(media_key(tenant_id, conn_id, uuid4().hex), "image/png", "image", 0)]
    )
    reel = _post_row(
        world_f2,
        category="reel",
        items=[(media_key(tenant_id, conn_id, uuid4().hex), "video/mp4", "video", 0)],
    )
    assert _publishable(world_f2, png).reason is UnpublishableReason.UNSUPPORTED_CONTENT_TYPE
    verdict = _publishable(world_f2, reel)
    assert isinstance(verdict, PublishablePost) and verdict.media_product_type == "REELS"


def test_another_tenant_reads_the_post_as_not_found(world_f2, world_q) -> None:
    post_id = _post_row(world_f2)
    verdict = DraftPostReader().get_publishable(tenant_id=TENANT_Q, post_id=post_id)
    assert isinstance(verdict, NotPublishable)
    assert verdict.reason is UnpublishableReason.POST_NOT_FOUND


def test_the_card_and_the_executor_use_the_same_evaluation(world_f2, monkeypatch) -> None:
    """Same verdict for every shape, and literally the same function: `_summarize` and
    `get_publishable` both go through `publishable.evaluate` (spied, not assumed)."""
    tenant_id, _, conn_id = world_f2
    posts = [
        _post_row(world_f2),
        _post_row(world_f2, revision=2, approved_revision=1),
        _post_row(world_f2, status="generated", approved_revision=None),
        _post_row(world_f2, category="story"),
        _post_row(world_f2, category=None),
        _post_row(world_f2, items=[(media_key(tenant_id, conn_id, uuid4().hex), None, "image", 0)]),
    ]
    calls: list[UUID] = []
    real_evaluate = draft_post_reader.evaluate

    def spy(candidate):
        calls.append(candidate.post_id)
        return real_evaluate(candidate)

    monkeypatch.setattr(draft_post_reader, "evaluate", spy)
    reader = DraftPostReader()
    cards = reader.get_many(tenant_id=tenant_id, post_ids=posts)
    for post_id in posts:
        verdict = reader.get_publishable(tenant_id=tenant_id, post_id=post_id)
        card = cards[post_id]
        assert card.is_publishable is isinstance(verdict, PublishablePost)
        if isinstance(verdict, NotPublishable):
            assert card.unpublishable_reason == REASON_TEXT[verdict.reason]
        else:
            assert card.media_product_type == verdict.media_product_type
    assert sorted(calls) == sorted(posts * 2)  # once per card, once per executor read


def test_get_publishable_never_writes(world_f2) -> None:
    tenant_id = world_f2[0]
    post_id = _post_row(world_f2)
    with tenant_session(tenant_id) as session:
        before = session.get(creative.ContentDraft, post_id).updated_at
    DraftPostReader().get_publishable(tenant_id=tenant_id, post_id=post_id)
    with tenant_session(tenant_id) as session:
        row = session.get(creative.ContentDraft, post_id)
        assert row.status == "approved" and row.updated_at == before


# --- the executor's start over real Postgres (QUA-111 F3) ---------------------------
#
# Real planner repository, real DraftPostReader, real PublishService over the real
# publish_attempts table; only Meta (the client) and R2 (the store) are fakes. Same
# isolated tenant as F2 (`world_f2`).


class _CountingClient:
    """Meta stand-in for the REELS path. `create_container` is the first platform call
    `start()` makes — counting it counts "publications that reached Meta". The sleep
    widens the window in which a competing execution could slip in."""

    def __init__(self, counter: list[str]) -> None:
        self._counter = counter

    async def create_container(self, *, ig_user_id, media_type, caption=None, **_):
        self._counter.append(media_type)
        await asyncio.sleep(0.3)
        return ResumableContainer(container_id=f"c-{uuid4().hex}", upload_uri="https://u/x")

    async def upload_bytes(self, *, upload_uri, fileobj, file_size):
        return UploadOutcome(success=True)


class _ClientFactory:
    def __init__(self, counter: list[str]) -> None:
        self._counter = counter

    async def client_for(self, *, tenant_id, connection_id):
        return _CountingClient(self._counter)


class _BytesStore:
    def put(self, key, fileobj, content_type) -> None:  # pragma: no cover - unused
        raise AssertionError("the executor never stages media")

    def open(self, key):
        return io.BytesIO(b"\x00" * 64)


class _NoLock:
    """Lets two executions into the critical section at once, to prove the publisher's
    own idempotency is the second barrier behind the event lock."""

    @contextmanager
    def hold(self, *, tenant_id, key):
        yield True


def _executor(
    counter: list[str], lock=None, factory=None, posts=None, connections=None
) -> EventExecutor:
    return EventExecutor(
        repository=PostgresPlannerRepository(),
        posts=posts or DraftPostReader(),
        publisher=PublishService(
            repository=PostgresPublishAttemptRepository(),
            gate=ObjectGate(_BytesStore()),
            connections=PostgresConnectionTargetReader(),
            client_factory=factory or _ClientFactory(counter),
        ),
        attempts=PostgresPublishAttemptRepository(),
        lock=lock or PostgresAdvisoryLock(),
        connections=connections,
    )


def _due_reel_event(world, post_id: UUID | None = None) -> EventRecord:
    """A due event for `post_id` — by default a fresh single-MP4 reel POST."""
    tenant_id, brand_id, conn_id = world
    if post_id is None:
        post_id = _post_row(
            world,
            category="reel",
            items=[(media_key(tenant_id, conn_id, uuid4().hex), "video/mp4", "video", 0)],
        )
    with admin_session() as session:
        user_id = session.scalar(select(User.id).where(User.tenant_id == tenant_id))
    return PostgresPlannerRepository().add(
        NewEvent(
            tenant_id=tenant_id,
            brand_id=brand_id,
            post_id=post_id,
            connection_id=conn_id,
            scheduled_at=datetime.now(UTC) - timedelta(minutes=1),
            scheduled_tz="America/Caracas",
            created_by_user_id=user_id,
        )
    )


def _attempt_rows(tenant_id: UUID, key: str) -> list[UUID]:
    with tenant_session(tenant_id) as session:
        return list(
            session.scalars(
                text("SELECT id FROM publish_attempts WHERE idempotency_key = :k"), {"k": key}
            )
        )


def _race(fn, contenders: int = 2) -> list:
    """Run `fn()` (a coroutine factory) in `contenders` threads, each with its own event
    loop and its own pooled connections, released together by a barrier."""
    barrier = threading.Barrier(contenders)

    def run(_: int):
        barrier.wait()
        return asyncio.run(fn())

    with ThreadPoolExecutor(max_workers=contenders) as pool:
        return list(pool.map(run, range(contenders)))


def test_executor_starts_a_ready_event_once_and_links_it(world_f2) -> None:
    tenant_id = world_f2[0]
    event = _due_reel_event(world_f2)
    calls: list[str] = []
    result = asyncio.run(_executor(calls).try_execute(event))
    assert result.outcome is ExecutionOutcome.STARTED
    key = f"cal:{event.id}:1"
    assert _attempt_rows(tenant_id, key) == [result.attempt_id]
    assert calls == ["REELS"]
    stored = PostgresPlannerRepository().get(tenant_id=tenant_id, event_id=event.id)
    assert (stored.status, stored.publish_attempt_id) == ("publishing", result.attempt_id)


def test_two_concurrent_executions_of_one_event_publish_once(world_f2) -> None:
    """Two executors on the same due event: the claim lets one through; one attempt row,
    one call to Meta, the event linked to it."""
    tenant_id = world_f2[0]
    event = _due_reel_event(world_f2)
    calls: list[str] = []
    results = _race(lambda: _executor(calls).try_execute(event))
    outcomes = sorted(r.outcome for r in results)
    assert outcomes == sorted([ExecutionOutcome.STARTED, ExecutionOutcome.CLAIM_LOST])
    rows = _attempt_rows(tenant_id, f"cal:{event.id}:1")
    assert len(rows) == 1 and calls == ["REELS"]
    stored = PostgresPlannerRepository().get(tenant_id=tenant_id, event_id=event.id)
    assert stored.publish_attempt_id == rows[0]


def test_two_concurrent_starts_of_one_claimed_event_are_serialised_by_the_lock(
    world_f2,
) -> None:
    """Both past the claim (a resume racing the claimer): the advisory lock lets one in;
    the other is BUSY, or — if it got the lock after the first finished — only re-links."""
    tenant_id = world_f2[0]
    event = _due_reel_event(world_f2)
    claimed = PostgresPlannerRepository().claim(
        tenant_id=tenant_id, event_id=event.id, expected_revision=1, now=datetime.now(UTC)
    )
    calls: list[str] = []
    results = _race(lambda: _executor(calls).start_claimed(claimed))
    started = [r for r in results if r.outcome is ExecutionOutcome.STARTED]
    others = {r.outcome for r in results if r.outcome is not ExecutionOutcome.STARTED}
    assert len(started) == 1
    assert others <= {ExecutionOutcome.BUSY, ExecutionOutcome.LINKED_EXISTING}
    assert _attempt_rows(tenant_id, f"cal:{event.id}:1") == [started[0].attempt_id]
    assert calls == ["REELS"]


def test_without_the_lock_the_publisher_idempotency_still_yields_one_attempt(world_f2) -> None:
    """The second barrier: with the event lock taken away, both executions reach
    `start()`; `uq_attempt_idempotency` gives both the SAME attempt, Meta is called once,
    and both end linked to it."""
    tenant_id = world_f2[0]
    event = _due_reel_event(world_f2)
    claimed = PostgresPlannerRepository().claim(
        tenant_id=tenant_id, event_id=event.id, expected_revision=1, now=datetime.now(UTC)
    )
    calls: list[str] = []
    results = _race(lambda: _executor(calls, lock=_NoLock()).start_claimed(claimed))
    attempt_ids = {r.attempt_id for r in results}
    assert len(attempt_ids) == 1 and None not in attempt_ids
    assert {r.outcome for r in results} <= {
        ExecutionOutcome.STARTED,
        ExecutionOutcome.LINKED_EXISTING,
    }
    assert _attempt_rows(tenant_id, f"cal:{event.id}:1") == list(attempt_ids)
    assert calls == ["REELS"]
    stored = PostgresPlannerRepository().get(tenant_id=tenant_id, event_id=event.id)
    assert stored.publish_attempt_id in attempt_ids


def test_the_advisory_lock_excludes_across_connections_and_releases_at_commit(world_f2) -> None:
    tenant_id = world_f2[0]
    key = f"qua111-test:{uuid4()}"
    lock = PostgresAdvisoryLock()
    holding, release = threading.Event(), threading.Event()

    def holder() -> bool:
        with lock.hold(tenant_id=tenant_id, key=key) as held:
            holding.set()
            release.wait(timeout=10)
            return held

    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(holder)
        assert holding.wait(timeout=10)
        with lock.hold(tenant_id=tenant_id, key=key) as second:
            assert second is False  # another connection holds it
        release.set()
        assert first.result(timeout=10) is True
    with lock.hold(tenant_id=tenant_id, key=key) as again:
        assert again is True  # released when the holder's transaction ended


def test_the_advisory_lock_is_released_when_the_transaction_fails(world_f2) -> None:
    tenant_id = world_f2[0]
    key = f"qua111-test:{uuid4()}"
    lock = PostgresAdvisoryLock()
    with pytest.raises(RuntimeError), lock.hold(tenant_id=tenant_id, key=key) as held:
        assert held
        raise RuntimeError("crash inside the critical section")
    with lock.hold(tenant_id=tenant_id, key=key) as again:
        assert again is True


def test_fail_unstarted_never_touches_a_linked_event(world_f2) -> None:
    tenant_id = world_f2[0]
    event = _due_reel_event(world_f2)
    result = asyncio.run(_executor([]).try_execute(event))
    repo = PostgresPlannerRepository()
    assert repo.fail_unstarted(tenant_id=tenant_id, event_id=event.id, expected_revision=1) is None
    stored = repo.get(tenant_id=tenant_id, event_id=event.id)
    assert (stored.status, stored.publish_attempt_id) == ("publishing", result.attempt_id)


# --- advance under the attempt lock (QUA-111 F4) -----------------------------------
#
# Real PublishService.advance() over the real publish_attempts / children rows; Meta is a
# fake that counts every platform call. Same isolated tenant (`world_f2`).


class _MetaCalls:
    """Every platform call any fake client made, across threads (list.append is atomic)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def count(self, name: str) -> int:
        return self.calls.count(name)


class _AdvanceClient:
    """Meta for the advance path. `container_status` answers `status`; `media_publish`
    returns a media id. Optional barriers make two advances meet at a given call — used
    ONLY by the diagnostic no-lock test, never by the positive ones."""

    def __init__(
        self, meta: _MetaCalls, *, status=None, raises=None, barriers=None, recent=()
    ) -> None:
        self._meta = meta
        self._status = status
        self._raises = raises
        self._barriers = barriers or {}
        self._recent = list(recent)

    async def recent_media(self, *, ig_user_id, since, stories=False):
        self._meta.calls.append("recent_media")
        return list(self._recent)

    def _meet(self, name: str) -> None:
        barrier = self._barriers.get(name)
        if barrier is not None:
            barrier.wait(timeout=10)  # a broken barrier fails the test loudly, never flakes

    async def create_container(self, *, ig_user_id, media_type, caption=None, **_):
        self._meta.calls.append("create_container")
        return ResumableContainer(container_id=f"c-{uuid4().hex}", upload_uri="https://u/x")

    async def upload_bytes(self, *, upload_uri, fileobj, file_size):
        self._meta.calls.append("upload_bytes")
        return UploadOutcome(success=True)

    async def container_status(self, *, container_id):
        self._meta.calls.append("container_status")
        if self._raises is not None:
            raise self._raises
        self._meet("container_status")
        return self._status

    async def publish_container(self, *, ig_user_id, creation_id):
        self._meta.calls.append("media_publish")
        self._meet("media_publish")
        return f"media-{uuid4().hex[:8]}"


class _AdvanceFactory:
    def __init__(self, meta: _MetaCalls, **kw) -> None:
        self._meta, self._kw = meta, kw

    async def client_for(self, *, tenant_id, connection_id):
        return _AdvanceClient(self._meta, **self._kw)


def _linked_event(world, *, carousel: bool = False) -> EventRecord:
    """A due event taken through F3 (claim + start) with the fake Meta: `publishing` with
    its attempt linked. REELS: container created + uploaded (`processing`). CAROUSEL: the
    parent + children written ahead, no platform call yet."""
    tenant_id, _, conn_id = world
    post_id = None
    if carousel:
        keys = [media_key(tenant_id, conn_id, uuid4().hex) for _ in range(2)]
        post_id = _post_row(
            world,
            category="galeria",
            items=[(keys[0], "video/mp4", "video", 0), (keys[1], "video/mp4", "video", 1)],
        )
    event = _due_reel_event(world, post_id)
    started = asyncio.run(_executor([]).try_execute(event))
    assert started.outcome is ExecutionOutcome.STARTED
    return PostgresPlannerRepository().get(tenant_id=tenant_id, event_id=event.id)


def _attempt(tenant_id: UUID, attempt_id: UUID):
    return PostgresPublishAttemptRepository().get_attempt(
        tenant_id=tenant_id, attempt_id=attempt_id
    )


def test_two_concurrent_advances_of_a_finished_container_publish_once(world_f2) -> None:
    tenant_id = world_f2[0]
    event = _linked_event(world_f2)
    meta = _MetaCalls()
    factory = _AdvanceFactory(meta, status=ContainerStatus.FINISHED)
    results = _race(lambda: _executor([], factory=factory).advance_event(event))
    assert meta.count("media_publish") == 1
    outcomes = sorted(r.outcome.value for r in results)
    # The loser is BUSY, or — had it reached the lock after the winner — reads a settled
    # attempt from the row. Either way it never reaches Meta.
    assert outcomes in (["busy", "settled"], ["settled", "settled"])
    attempt = _attempt(tenant_id, event.publish_attempt_id)
    assert attempt.status == "published" and attempt.published_media_id
    stored = PostgresPlannerRepository().get(tenant_id=tenant_id, event_id=event.id)
    assert stored.status == "publishing"  # F4 never changes the event (F5 does)


def test_two_concurrent_advances_of_an_assembling_carousel_create_children_once(
    world_f2,
) -> None:
    tenant_id = world_f2[0]
    event = _linked_event(world_f2, carousel=True)
    attempt = _attempt(tenant_id, event.publish_attempt_id)
    assert attempt.media_product_type == "CAROUSEL" and attempt.creation_id is None
    meta = _MetaCalls()
    factory = _AdvanceFactory(meta, status=ContainerStatus.IN_PROGRESS)
    _race(lambda: _executor([], factory=factory).advance_event(event))
    children = PostgresPublishAttemptRepository().list_children(
        tenant_id=tenant_id, attempt_id=event.publish_attempt_id
    )
    assert len(children) == 2
    assert meta.count("create_container") == 2  # one per child, never duplicated
    assert len({c.creation_id for c in children}) == 2 and None not in {
        c.creation_id for c in children
    }
    # The carousel's own container is not created while children are still in flight.
    assert _attempt(tenant_id, event.publish_attempt_id).creation_id is None


def test_advancing_a_settled_attempt_calls_meta_zero_times(world_f2) -> None:
    tenant_id = world_f2[0]
    event = _linked_event(world_f2)
    first = _MetaCalls()
    finished = _AdvanceFactory(first, status=ContainerStatus.FINISHED)
    asyncio.run(_executor([], factory=finished).advance_event(event))
    assert _attempt(tenant_id, event.publish_attempt_id).status == "published"
    again = _MetaCalls()
    result = asyncio.run(
        _executor(
            [], factory=_AdvanceFactory(again, status=ContainerStatus.FINISHED)
        ).advance_event(event)
    )
    assert result.outcome is AdvanceOutcome.SETTLED
    assert again.calls == []


def test_the_attempt_lock_is_released_after_advance_raises(world_f2) -> None:
    tenant_id = world_f2[0]
    event = _linked_event(world_f2)
    meta = _MetaCalls()
    failing = _AdvanceFactory(meta, raises=RuntimeError("graph 500"))
    result = asyncio.run(_executor([], factory=failing).advance_event(event))
    assert result.outcome is AdvanceOutcome.ADVANCE_ERROR and result.error == "RuntimeError"
    with PostgresAdvisoryLock().hold(
        tenant_id=tenant_id, key=attempt_lock_key(event.publish_attempt_id)
    ) as held:
        assert held is True  # the rollback released it
    retry = asyncio.run(_executor([], factory=failing).advance_event(event))
    assert retry.outcome is AdvanceOutcome.ADVANCE_ERROR  # ran again, not BUSY
    assert meta.count("container_status") == 2
    stored = PostgresPlannerRepository().get(tenant_id=tenant_id, event_id=event.id)
    assert (stored.status, stored.publish_attempt_id) == ("publishing", event.publish_attempt_id)


def test_a_held_attempt_lock_makes_advance_busy(world_f2) -> None:
    tenant_id = world_f2[0]
    event = _linked_event(world_f2)
    key = attempt_lock_key(event.publish_attempt_id)
    holding, release = threading.Event(), threading.Event()

    def holder() -> None:
        with PostgresAdvisoryLock().hold(tenant_id=tenant_id, key=key) as held:
            assert held
            holding.set()
            release.wait(timeout=10)

    meta = _MetaCalls()
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(holder)
        assert holding.wait(timeout=10)
        factory = _AdvanceFactory(meta, status=ContainerStatus.FINISHED)
        result = asyncio.run(_executor([], factory=factory).advance_event(event))
        release.set()
        running.result(timeout=10)
    assert result.outcome is AdvanceOutcome.BUSY
    assert meta.calls == []


def test_diagnostic_without_the_attempt_lock_two_advances_publish_twice(world_f2) -> None:
    """DIAGNOSTIC — documents WHY `advance_event` takes the attempt lock; it does not
    validate any production path (production always passes the lock).

    With the lock removed, two advances of the same FINISHED attempt both read "not sent"
    from their own snapshot, both write the send marker (a plain UPDATE, not a
    compare-and-set) and both call `media_publish`. Two barriers make that interleaving
    deterministic — both advances must reach `container_status`, then both must reach
    `media_publish`, before either continues — so this needs no sleep and cannot pass or
    fail by timing: a broken barrier raises instead."""
    event = _linked_event(world_f2)
    meta = _MetaCalls()
    barriers = {
        "container_status": threading.Barrier(2),
        "media_publish": threading.Barrier(2),
    }
    factory = _AdvanceFactory(meta, status=ContainerStatus.FINISHED, barriers=barriers)
    _race(lambda: _executor([], lock=_NoLock(), factory=factory).advance_event(event))
    assert meta.count("media_publish") == 2  # the double publish the attempt lock prevents


# --- settling the event from its attempt (QUA-111 F5) -------------------------------
#
# A FRESH tenant per test here: `advance_in_flight` steps every linked `publishing` event
# of the tenant, and the module-wide `world_f2` tenant holds F3/F4 leftovers.


@pytest.fixture
def world_f5() -> tuple[UUID, UUID, UUID]:
    tenant_id = uuid4()
    brand_id, _, connection_id = _provision(tenant_id, f"t-qua111-f5-{tenant_id.hex[:8]}")
    return tenant_id, brand_id, connection_id


def _stored(tenant_id: UUID, event_id: UUID) -> EventRecord:
    return PostgresPlannerRepository().get(tenant_id=tenant_id, event_id=event_id)


def _advance_and_settle(world, status: ContainerStatus) -> tuple[EventRecord, list]:
    """try_execute → advance_in_flight (advance + settle) with Meta answering `status`."""
    tenant_id = world[0]
    event = _due_reel_event(world)
    executor = _executor([], factory=_AdvanceFactory(_MetaCalls(), status=status))
    assert asyncio.run(executor.try_execute(event)).outcome is ExecutionOutcome.STARTED
    steps = asyncio.run(executor.advance_in_flight(tenant_id=tenant_id))
    return _stored(tenant_id, event.id), steps


def test_end_to_end_execute_advance_settle_publishes_with_the_media_id(world_f5) -> None:
    tenant_id = world_f5[0]
    event, steps = _advance_and_settle(world_f5, ContainerStatus.FINISHED)
    ((advanced, settled),) = steps
    assert advanced.outcome is AdvanceOutcome.SETTLED
    assert settled.outcome is SettleOutcome.SETTLED_PUBLISHED
    assert event.status == "published"
    attempt = _attempt(tenant_id, event.publish_attempt_id)
    assert attempt.status == "published" and attempt.published_media_id
    assert settled.published_media_id == attempt.published_media_id
    # QUA-111 criterion 8: the approved caption, as sent to Meta, is on the attempt.
    assert attempt.caption == "¡Oferta!\n\nDos por uno todo octubre\n\nPide ya\n\n#promo #octubre"


def test_a_published_confirmation_recovers_the_media_id_from_recent_media(world_f5) -> None:
    """QUA-111 criterion 7 — Meta reports the container PUBLISHED and `media_publish`
    never returned an id (reconciliation path): the id is recovered read-only from the
    account's media (surface + time + the caption recorded on the attempt), with zero
    `media_publish` calls, and the event is settled with it."""
    tenant_id = world_f5[0]
    event = _due_reel_event(world_f5)
    asyncio.run(_executor([]).try_execute(event))
    event = _stored(tenant_id, event.id)
    caption = _attempt(tenant_id, event.publish_attempt_id).caption
    listing = [
        RecentMedia("17900000000000009", "REELS", caption, datetime.now(UTC)),
        RecentMedia("17900000000000008", "REELS", "otro texto", datetime.now(UTC)),
    ]
    meta = _MetaCalls()
    factory = _AdvanceFactory(meta, status=ContainerStatus.PUBLISHED, recent=listing)
    ((_, settled),) = asyncio.run(
        _executor([], factory=factory).advance_in_flight(tenant_id=tenant_id)
    )
    assert settled.outcome is SettleOutcome.SETTLED_PUBLISHED
    assert settled.published_media_id == "17900000000000009"
    assert _attempt(tenant_id, event.publish_attempt_id).published_media_id == "17900000000000009"
    assert meta.count("media_publish") == 0 and meta.count("recent_media") == 1


def test_an_unresolvable_published_confirmation_keeps_the_id_null(world_f5) -> None:
    """No candidate in the listing: published (Meta said so), id NULL — never guessed."""
    tenant_id = world_f5[0]
    event, steps = _advance_and_settle(world_f5, ContainerStatus.PUBLISHED)
    ((_, settled),) = steps
    assert settled.outcome is SettleOutcome.SETTLED_PUBLISHED
    assert settled.published_media_id is None
    assert event.status == "published"
    assert _attempt(tenant_id, event.publish_attempt_id).published_media_id is None


def test_published_media_ids_lists_only_this_connections_recorded_ids(world_f5, world_q) -> None:
    tenant_id = world_f5[0]
    event, _ = _advance_and_settle(world_f5, ContainerStatus.FINISHED)
    media_id = _attempt(tenant_id, event.publish_attempt_id).published_media_id
    repo = PostgresPublishAttemptRepository()
    assert media_id in repo.published_media_ids(
        tenant_id=tenant_id, connection_id=event.connection_id
    )
    assert repo.published_media_ids(tenant_id=TENANT_Q, connection_id=event.connection_id) == set()


def test_a_failed_attempt_fails_the_event_and_keeps_its_platform_reason(world_f5) -> None:
    tenant_id = world_f5[0]
    event, steps = _advance_and_settle(world_f5, ContainerStatus.ERROR)
    ((_, settled),) = steps
    assert settled.outcome is SettleOutcome.SETTLED_FAILED
    assert settled.reason == "container_error"
    assert event.status == "failed"
    assert _attempt(tenant_id, event.publish_attempt_id).platform_error_code == "container_error"


def test_a_non_terminal_attempt_leaves_the_event_publishing(world_f5) -> None:
    tenant_id = world_f5[0]
    event, steps = _advance_and_settle(world_f5, ContainerStatus.IN_PROGRESS)
    ((advanced, settled),) = steps
    assert advanced.outcome is AdvanceOutcome.ADVANCED and settled is None
    assert _executor([]).settle_event(event).outcome is SettleOutcome.NOT_SETTLED
    assert _stored(tenant_id, event.id).status == "publishing"


def test_a_repeated_settlement_is_already_settled(world_f5) -> None:
    tenant_id = world_f5[0]
    event, _ = _advance_and_settle(world_f5, ContainerStatus.FINISHED)
    again = _executor([]).settle_event(event)
    assert again.outcome is SettleOutcome.ALREADY_SETTLED
    assert _stored(tenant_id, event.id).status == "published"


def test_a_mismatched_attempt_revision_or_state_writes_nothing(world_f5) -> None:
    tenant_id = world_f5[0]
    executor = _executor([], factory=_AdvanceFactory(_MetaCalls(), status=ContainerStatus.ERROR))
    mine = _due_reel_event(world_f5)
    other = _due_reel_event(world_f5)
    for event in (mine, other):
        asyncio.run(executor.try_execute(event))
    mine, other = _stored(tenant_id, mine.id), _stored(tenant_id, other.id)
    asyncio.run(executor.advance_event(other))  # settles OTHER's attempt as failed
    # Another event's attempt: key does not match this event.
    stolen = replace(mine, publish_attempt_id=other.publish_attempt_id)
    assert _executor([]).settle_event(stolen).outcome is SettleOutcome.MISMATCH
    # A stale revision: key does not match either.
    assert _executor([]).settle_event(replace(other, revision=2)).outcome is SettleOutcome.MISMATCH
    # The repository CAS itself refuses a wrong attempt or revision.
    repo = PostgresPlannerRepository()
    kw = {"tenant_id": tenant_id, "event_id": mine.id, "published": False}
    assert repo.settle_from_attempt(expected_revision=1, attempt_id=uuid4(), **kw) is None
    assert (
        repo.settle_from_attempt(expected_revision=2, attempt_id=mine.publish_attempt_id, **kw)
        is None
    )
    assert _stored(tenant_id, mine.id).status == "publishing"
    assert _stored(tenant_id, other.id).status == "publishing"


def test_two_concurrent_settlements_make_exactly_one_transition(world_f5) -> None:
    tenant_id = world_f5[0]
    event = _due_reel_event(world_f5)
    finished = _AdvanceFactory(_MetaCalls(), status=ContainerStatus.FINISHED)
    executor = _executor([], factory=finished)
    asyncio.run(executor.try_execute(event))
    event = _stored(tenant_id, event.id)
    asyncio.run(executor.advance_event(event))  # the attempt is now settled `published`
    barrier = threading.Barrier(2)

    def settle(_: int):
        barrier.wait(timeout=10)
        return _executor([]).settle_event(event)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(settle, range(2)))
    assert sorted(r.outcome.value for r in results) == ["already_settled", "settled_published"]
    stored = _stored(tenant_id, event.id)
    assert (stored.status, stored.publish_attempt_id) == ("published", event.publish_attempt_id)


def test_an_attempt_settled_by_another_caller_is_reflected(world_f5) -> None:
    """E.g. the HTTP GET route advanced it: the executor only reads the row."""
    tenant_id = world_f5[0]
    event = _due_reel_event(world_f5)
    asyncio.run(_executor([]).try_execute(event))
    event = _stored(tenant_id, event.id)
    PostgresPublishAttemptRepository().settle(
        tenant_id=tenant_id,
        attempt_id=event.publish_attempt_id,
        status="published",
        published_media_id="ext-1789",
    )
    result = _executor([]).settle_event(event)
    assert result.outcome is SettleOutcome.SETTLED_PUBLISHED
    assert result.published_media_id == "ext-1789"
    assert _stored(tenant_id, event.id).status == "published"


# --- the multi-tenant tick (QUA-111 F6) ---------------------------------------------
#
# Fresh tenants per test. No test here runs the production discovery unrestricted: the
# shared dev database holds earlier test tenants that a real tick would act on.


def _fresh_world(label: str) -> tuple[UUID, UUID, UUID]:
    tenant_id = uuid4()
    brand_id, _, connection_id = _provision(tenant_id, f"t-qua111-f6-{label}-{tenant_id.hex[:6]}")
    return tenant_id, brand_id, connection_id


@pytest.fixture
def worlds_ab() -> tuple[tuple[UUID, UUID, UUID], tuple[UUID, UUID, UUID]]:
    return _fresh_world("a"), _fresh_world("b")


class _DiscoveredOnly:
    """The REAL production discovery, narrowed to the tenants a test created — so the
    test proves discovery finds them without acting on anyone else's data."""

    def __init__(self, *allowed: UUID) -> None:
        self.allowed, self.found = set(allowed), []

    def tenants(self, *, now):
        self.found = DiscoveredTenants().tenants(now=now)
        return [t for t in self.found if t in self.allowed]


def _tick(
    source, meta: _MetaCalls, *, posts=None, repository=None, status=None, connections=None
) -> TickRunner:
    executor = _executor(
        [], factory=_AdvanceFactory(meta, status=status), posts=posts, connections=connections
    )
    return TickRunner(
        tenants=source, repository=repository or PostgresPlannerRepository(), executor=executor
    )


def _updated_at(tenant_id: UUID, event_id: UUID) -> datetime:
    return _stored(tenant_id, event_id).updated_at


def test_discovery_returns_only_the_ids_of_tenants_with_work_and_writes_nothing(
    worlds_ab,
) -> None:
    (a, b), idle = worlds_ab, _fresh_world("idle")
    event_a, event_b = _due_reel_event(a), _due_reel_event(b)
    before = (_updated_at(a[0], event_a.id), _updated_at(b[0], event_b.id))
    found = DiscoveredTenants().tenants(now=datetime.now(UTC))
    assert all(isinstance(t, UUID) for t in found)  # tenant ids, nothing else
    assert a[0] in found and b[0] in found and idle[0] not in found
    assert (_updated_at(a[0], event_a.id), _updated_at(b[0], event_b.id)) == before


def test_a_tick_scoped_to_a_never_touches_b(worlds_ab) -> None:
    a, b = worlds_ab
    event_a, event_b = _due_reel_event(a), _due_reel_event(b)
    b_before = _stored(b[0], event_b.id)
    report = asyncio.run(_tick(ScopedTenants([a[0]]), _MetaCalls()).run_once())
    assert [t.tenant_id for t in report.tenants] == [a[0]]
    assert [r.event_id for r in report.tenants[0].executed] == [event_a.id]  # RLS: A's only
    assert _stored(a[0], event_a.id).status == "publishing"
    assert _stored(b[0], event_b.id) == b_before


def test_the_multi_tenant_tick_discovers_and_processes_both(worlds_ab) -> None:
    a, b = worlds_ab
    event_a, event_b = _due_reel_event(a), _due_reel_event(b)
    source = _DiscoveredOnly(a[0], b[0])
    first = asyncio.run(_tick(source, _MetaCalls()).run_once())
    assert a[0] in source.found and b[0] in source.found
    assert {t.tenant_id for t in first.tenants} == {a[0], b[0]}
    assert _stored(a[0], event_a.id).status == _stored(b[0], event_b.id).status == "publishing"
    # Next tick: Meta reports FINISHED → both publish and settle.
    second = asyncio.run(_tick(source, _MetaCalls(), status=ContainerStatus.FINISHED).run_once())
    assert all(len(t.advanced) == 1 for t in second.tenants)
    assert _stored(a[0], event_a.id).status == _stored(b[0], event_b.id).status == "published"


def test_a_failing_tenant_does_not_stop_another(worlds_ab) -> None:
    a, b = worlds_ab
    event_a, event_b = _due_reel_event(a), _due_reel_event(b)

    class _ReaderDownForA(DraftPostReader):
        def get_publishable(self, *, tenant_id, post_id, output_port=None):
            if tenant_id == a[0]:
                raise ConnectionError("reader down for A")
            return super().get_publishable(
                tenant_id=tenant_id, post_id=post_id, output_port=output_port
            )

    report = asyncio.run(
        _tick(ScopedTenants([a[0], b[0]]), _MetaCalls(), posts=_ReaderDownForA()).run_once()
    )
    a_report, b_report = report.tenants
    assert a_report.errors == [f"{event_a.id}:ConnectionError"]
    assert _stored(a[0], event_a.id).status == "scheduled"
    assert b_report.errors == [] and _stored(b[0], event_b.id).status == "publishing"


def test_two_concurrent_ticks_do_not_duplicate_a_publication(worlds_ab) -> None:
    a, b = worlds_ab
    event_a, event_b = _due_reel_event(a), _due_reel_event(b)
    meta = _MetaCalls()
    _race(lambda: _tick(ScopedTenants([a[0], b[0]]), meta).run_once())
    for world, event in ((a, event_a), (b, event_b)):
        rows = _attempt_rows(world[0], f"cal:{event.id}:1")
        assert len(rows) == 1
        assert _stored(world[0], event.id).publish_attempt_id == rows[0]
    assert meta.count("create_container") == 2  # one per event, never two


class _AppendHook(list):
    """A list whose `append` also calls a hook — lets a fake Meta call act mid-tick."""

    def __init__(self, hook) -> None:
        super().__init__()
        self._hook = hook

    def append(self, item) -> None:
        super().append(item)
        self._hook(item)


def test_an_event_created_after_the_snapshot_waits_for_the_next_tick(worlds_ab) -> None:
    a, _ = worlds_ab
    _due_reel_event(a)
    created: list[EventRecord] = []

    class _PlanAnotherMidTick(_MetaCalls):
        def __init__(self) -> None:
            super().__init__()
            self.calls = _AppendHook(self._plan)

        def _plan(self, name: str) -> None:
            if name == "create_container" and not created:
                created.append(_due_reel_event(a))

    meta = _PlanAnotherMidTick()
    asyncio.run(_tick(ScopedTenants([a[0]]), meta).run_once())
    assert created and _stored(a[0], created[0].id).status == "scheduled"
    second = asyncio.run(_tick(ScopedTenants([a[0]]), _MetaCalls()).run_once())
    assert created[0].id in {r.event_id for r in second.tenants[0].executed}
    assert _stored(a[0], created[0].id).status == "publishing"


def test_a_change_between_snapshot_and_execution_is_caught_by_the_claim(worlds_ab) -> None:
    a, _ = worlds_ab
    event = _due_reel_event(a)

    class _CancelAfterSnapshot(PostgresPlannerRepository):
        def list_due(self, *, tenant_id, now, limit=100):
            rows = super().list_due(tenant_id=tenant_id, now=now, limit=limit)
            self.set_status(
                tenant_id=tenant_id,
                event_id=event.id,
                expected_status="scheduled",
                new_status="cancelled",
            )
            return rows

    meta = _MetaCalls()
    report = asyncio.run(
        _tick(ScopedTenants([a[0]]), meta, repository=_CancelAfterSnapshot()).run_once()
    )
    assert [r.outcome for r in report.tenants[0].executed] == [ExecutionOutcome.CLAIM_LOST]
    assert _stored(a[0], event.id).status == "cancelled"
    assert meta.calls == []


def test_a_tenant_without_work_generates_no_operations(worlds_ab) -> None:
    idle = _fresh_world("idle")
    meta = _MetaCalls()
    report = asyncio.run(_tick(ScopedTenants([idle[0]]), meta).run_once())
    assert report.tenants[0].operations == 0 and report.tenants[0].errors == []
    assert meta.calls == []


# --- the worker embedded in the app process (QUA-111 follow-up) ----------------------
#
# The real thread, loop, tick, executor, publisher and Postgres; only Meta and R2 are
# fakes. Scoped to fresh tenants, like every tick test above.


def _embedded(runner_factory, *, all_tenants: bool = False) -> EmbeddedCalendarWorker:
    scope = {"all_tenants": True} if all_tenants else {"tenant_ids": (uuid4(),)}
    return EmbeddedCalendarWorker(
        EmbeddedWorkerConfig(WorkerMode.EMBEDDED, interval=0, **scope),
        make_runner=runner_factory,
    )


def _wait_for(predicate, timeout: float = 20.0) -> bool:
    deadline = datetime.now(UTC) + timedelta(seconds=timeout)
    while datetime.now(UTC) < deadline:
        if predicate():
            return True
        threading.Event().wait(0.05)
    return predicate()


def test_the_embedded_worker_publishes_a_due_event_by_itself(worlds_ab) -> None:
    a, _ = worlds_ab
    event = _due_reel_event(a)
    meta = _MetaCalls()
    worker = _embedded(lambda: _tick(ScopedTenants([a[0]]), meta, status=ContainerStatus.FINISHED))
    worker.start()
    try:
        assert _wait_for(lambda: _stored(a[0], event.id).status == "published")
    finally:
        worker.stop(timeout=10)
    assert len(_attempt_rows(a[0], f"cal:{event.id}:1")) == 1
    assert meta.count("create_container") == 1


def test_a_rescheduled_event_publishes_at_its_new_time_under_its_new_revision(worlds_ab) -> None:
    a, _ = worlds_ab
    event = _due_reel_event(a)
    repo = PostgresPlannerRepository()
    later = repo.reschedule(
        tenant_id=a[0],
        event_id=event.id,
        expected_revision=1,
        scheduled_at=datetime.now(UTC) + timedelta(hours=1),
        scheduled_tz="America/Caracas",
        connection_id=a[2],
    )
    assert later is not None and later.revision == 2
    meta = _MetaCalls()
    runner = _tick(ScopedTenants([a[0]]), meta, status=ContainerStatus.FINISHED)
    asyncio.run(runner.run_once())
    assert _stored(a[0], event.id).status == "scheduled"  # not due at its NEW time
    assert meta.calls == []
    # Time passes: the new instant is reached (simulated by moving it into the past).
    due = repo.reschedule(
        tenant_id=a[0],
        event_id=event.id,
        expected_revision=2,
        scheduled_at=datetime.now(UTC) - timedelta(seconds=1),
        scheduled_tz="America/Caracas",
        connection_id=a[2],
    )
    asyncio.run(runner.run_once())  # claim + start
    asyncio.run(runner.run_once())  # advance → FINISHED → settle
    assert _stored(a[0], event.id).status == "published"
    assert _attempt_rows(a[0], f"cal:{event.id}:1") == []
    assert len(_attempt_rows(a[0], f"cal:{event.id}:{due.revision}")) == 1


def test_a_worker_restart_mid_publication_resumes_without_publishing_twice(worlds_ab) -> None:
    a, _ = worlds_ab
    event = _due_reel_event(a)
    meta = _MetaCalls()
    # First process: claims and starts, then "dies" before Meta finishes processing.
    first = _tick(ScopedTenants([a[0]]), meta, status=ContainerStatus.IN_PROGRESS)
    asyncio.run(first.run_once())
    assert _stored(a[0], event.id).status == "publishing"
    # Second process (app restarted): resumes the in-flight attempt, never restarts it.
    worker = _embedded(lambda: _tick(ScopedTenants([a[0]]), meta, status=ContainerStatus.FINISHED))
    worker.start()
    try:
        assert _wait_for(lambda: _stored(a[0], event.id).status == "published")
    finally:
        worker.stop(timeout=10)
    assert len(_attempt_rows(a[0], f"cal:{event.id}:1")) == 1
    assert meta.count("create_container") == 1


def test_two_embedded_workers_publish_an_event_once(worlds_ab) -> None:
    """Two app processes (or app + CLI worker) at the same time."""
    a, _ = worlds_ab
    events = [_due_reel_event(a) for _ in range(3)]
    meta = _MetaCalls()
    workers = [
        _embedded(lambda: _tick(ScopedTenants([a[0]]), meta, status=ContainerStatus.FINISHED))
        for _ in range(2)
    ]
    for w in workers:
        w.start()
    try:
        assert _wait_for(lambda: all(_stored(a[0], e.id).status == "published" for e in events))
    finally:
        for w in workers:
            w.stop(timeout=10)
    for e in events:
        assert len(_attempt_rows(a[0], f"cal:{e.id}:1")) == 1
    assert meta.count("create_container") == 3


# --- the default: every tenant with a connected account (all-tenants discovery) -------
#
# The production discovery runs for real (`DiscoveredTenants`), narrowed by
# `_DiscoveredOnly` to the tenants each test creates: the shared dev database holds
# earlier test tenants a real all-tenants tick would act on. The narrowing is a test
# safety net only — what is asserted is that the REAL discovery found the tenant.


def _set_connection_status(world, status: str) -> None:
    tenant_id, _, conn_id = world
    with tenant_session(tenant_id) as session:
        session.get(SocialConnection, conn_id).status = status


def _discovery_worker(source, meta: _MetaCalls) -> EmbeddedCalendarWorker:
    return _embedded(
        lambda: _tick(
            source, meta, status=ContainerStatus.FINISHED, connections=PostgresConnectionGate()
        ),
        all_tenants=True,
    )


def test_the_default_worker_publishes_for_every_connected_tenant(worlds_ab) -> None:
    a, b = worlds_ab
    event_a, event_b = _due_reel_event(a), _due_reel_event(b)
    meta, source = _MetaCalls(), _DiscoveredOnly(a[0], b[0])
    worker = _discovery_worker(source, meta)
    worker.start()
    try:
        assert _wait_for(
            lambda: (
                _stored(a[0], event_a.id).status == "published"
                and _stored(b[0], event_b.id).status == "published"
            )
        )
    finally:
        worker.stop(timeout=10)
    # `_DiscoveredOnly` hands the tick only tenants the REAL discovery returned, so both
    # publishing proves both were discovered (`found` itself is the LAST tick's answer,
    # taken after they were published and therefore had no work left).
    assert a[0] not in source.found and b[0] not in source.found
    for world, event in ((a, event_a), (b, event_b)):
        (attempt_id,) = _attempt_rows(world[0], f"cal:{event.id}:1")
        assert _attempt(world[0], attempt_id).connection_id == world[2]  # its OWN account


def test_a_tenant_without_an_active_connection_is_skipped_and_blocks_no_one(worlds_ab) -> None:
    a, b = worlds_ab
    event_a, event_b = _due_reel_event(a), _due_reel_event(b)
    _set_connection_status(b, "revoked")
    found = DiscoveredTenants().tenants(now=datetime.now(UTC))
    assert a[0] in found and b[0] not in found  # not even discovered

    # Forced into a tick anyway (a restricted worker): B is "not ready", never an error,
    # never a failed event, never a publish attempt — and A publishes regardless.
    runner = _tick(
        ScopedTenants([b[0], a[0]]),
        _MetaCalls(),
        status=ContainerStatus.FINISHED,
        connections=PostgresConnectionGate(),
    )
    report = asyncio.run(runner.run_once())
    b_report = next(t for t in report.tenants if t.tenant_id == b[0])
    assert [(r.outcome, r.reason) for r in b_report.executed] == [
        (ExecutionOutcome.NOT_READY, "connection_not_active")
    ]
    assert b_report.errors == []
    assert _stored(b[0], event_b.id).status == "scheduled"
    assert _attempt_rows(b[0], f"cal:{event_b.id}:1") == []
    asyncio.run(runner.run_once())
    assert _stored(a[0], event_a.id).status == "published"

    # The account is reconnected: the waiting event publishes, nothing to configure.
    _set_connection_status(b, "active")
    assert b[0] in DiscoveredTenants().tenants(now=datetime.now(UTC))
    asyncio.run(runner.run_once())
    asyncio.run(runner.run_once())
    assert _stored(b[0], event_b.id).status == "published"


def test_an_event_can_never_use_another_tenants_connection(worlds_ab) -> None:
    a, b = worlds_ab
    post_id = _post_row(
        a,
        category="reel",
        items=[(media_key(a[0], a[2], uuid4().hex), "video/mp4", "video", 0)],
    )
    with admin_session() as session:
        user_id = session.scalar(select(User.id).where(User.tenant_id == a[0]))
    with pytest.raises(DBAPIError):  # composite FK (connection_id, tenant_id)
        PostgresPlannerRepository().add(
            NewEvent(
                tenant_id=a[0],
                brand_id=a[1],
                post_id=post_id,
                connection_id=b[2],
                scheduled_at=datetime.now(UTC) - timedelta(minutes=1),
                scheduled_tz="America/Caracas",
                created_by_user_id=user_id,
            )
        )
    # And under A's RLS, B's connection does not exist at all.
    assert PostgresConnectionGate().status(tenant_id=a[0], connection_id=b[2]) is None
    assert PostgresConnectionGate().status(tenant_id=a[0], connection_id=a[2]) == "active"


def test_two_default_workers_publish_each_event_once(worlds_ab) -> None:
    a, b = worlds_ab
    events = [(a, _due_reel_event(a)), (b, _due_reel_event(b)), (a, _due_reel_event(a))]
    meta = _MetaCalls()
    workers = [_discovery_worker(_DiscoveredOnly(a[0], b[0]), meta) for _ in range(2)]
    for w in workers:
        w.start()
    try:
        assert _wait_for(lambda: all(_stored(w[0], e.id).status == "published" for w, e in events))
    finally:
        for w in workers:
            w.stop(timeout=10)
    for world, event in events:
        assert len(_attempt_rows(world[0], f"cal:{event.id}:1")) == 1
    assert meta.count("create_container") == 3


def test_an_account_connected_after_startup_is_covered_with_no_configuration() -> None:
    early = _fresh_world("early")
    late_id = uuid4()  # does not exist yet when the worker starts
    meta = _MetaCalls()
    worker = _discovery_worker(_DiscoveredOnly(early[0], late_id), meta)
    worker.start()
    try:
        assert _wait_for(lambda: worker.status().last_tick_at is not None)
        # A new business signs up and connects its account while the worker runs.
        brand_id, _, conn_id = _provision(late_id, f"t-qua111-late-{late_id.hex[:6]}")
        event = _due_reel_event((late_id, brand_id, conn_id))
        assert _wait_for(lambda: _stored(late_id, event.id).status == "published")
    finally:
        worker.stop(timeout=10)
    assert worker.config.all_tenants  # no tenant list, no restart


# --- approved but not ready: the UI reads the verdict, the worker waits ----------------


def _set_selected_variant(world, post_id: UUID, *, clear: bool) -> None:
    tenant_id = world[0]
    with tenant_session(tenant_id) as session:
        draft = session.get(creative.ContentDraft, post_id)
        if clear:
            draft.selected_variant_id = None
        else:
            draft.selected_variant_id = session.scalar(
                select(creative.CopyVariant.id).where(
                    creative.CopyVariant.draft_id == post_id, creative.CopyVariant.ordinal == 1
                )
            )


def test_an_approved_post_missing_its_copy_waits_scheduled_and_publishes_once_completed(
    worlds_ab,
) -> None:
    a, _ = worlds_ab
    post_id = _post_row(
        a,
        category="reel",
        items=[(media_key(a[0], a[2], uuid4().hex), "video/mp4", "video", 0)],
    )
    _set_selected_variant(a, post_id, clear=True)  # "approved" with no approved copy
    event = _due_reel_event(a, post_id)

    # The Planificador shows it: approved, not publishable, with the evaluator's reason.
    summary = DraftPostReader().get(tenant_id=a[0], post_id=post_id)
    assert summary.approval is ApprovalStatus.APPROVED and not summary.is_publishable
    assert summary.unpublishable_reason == REASON_TEXT[UnpublishableReason.APPROVED_COPY_MISSING]

    meta = _MetaCalls()
    runner = _tick(
        ScopedTenants([a[0]]),
        meta,
        status=ContainerStatus.FINISHED,
        connections=PostgresConnectionGate(),
    )
    report = asyncio.run(runner.run_once())
    (executed,) = report.tenants[0].executed
    assert (executed.outcome, executed.reason) == (
        ExecutionOutcome.NOT_READY,
        UnpublishableReason.APPROVED_COPY_MISSING,
    )
    assert _stored(a[0], event.id).status == "scheduled"  # neither failed nor published
    assert _attempt_rows(a[0], f"cal:{event.id}:1") == [] and meta.calls == []

    # The operator completes it after the hour: the next ticks publish it, once.
    _set_selected_variant(a, post_id, clear=False)
    assert DraftPostReader().get(tenant_id=a[0], post_id=post_id).is_publishable
    asyncio.run(runner.run_once())
    asyncio.run(runner.run_once())
    assert _stored(a[0], event.id).status == "published"
    assert len(_attempt_rows(a[0], f"cal:{event.id}:1")) == 1


# --- editing an approved POST sends it back to review (2026-09-30) ---------------------


class _Kit:
    """`BrandService` stand-in: a permissive kit for the tenant's own brand."""

    def __init__(self, brand_id: UUID) -> None:
        from qualify_creative.schemas import BrandKit, ToneAxes

        self._kit = BrandKit.model_validate(
            {
                "brand_id": brand_id,
                "positioning": "promos de barrio",
                "audience": "clientes del local",
                "tone_axes": ToneAxes(
                    formal_casual=70, sober_enthusiastic=60, technical_plain=80, brief_elaborate=40
                ),
            }
        )

    def kit(self, *, tenant_id: UUID, brand_id: UUID):
        return self._kit


def _content_service(brand_id: UUID):
    from qualify_api.creative.service import ContentService

    unused = object()  # generation collaborators: edit/approve never touch them
    return ContentService(
        router=unused,  # type: ignore[arg-type]
        pricing=unused,  # type: ignore[arg-type]
        credentials=unused,  # type: ignore[arg-type]
        voice_service=unused,  # type: ignore[arg-type]
        brand_service=_Kit(brand_id),
    )


def test_editing_an_approved_scheduled_post_waits_for_reapproval_then_publishes(
    worlds_ab,
) -> None:
    from qualify_creative.schemas import CopyPayload

    a, _ = worlds_ab
    tenant_id, brand_id, _conn = a
    post_id = _post_row(
        a,
        category="reel",
        items=[(media_key(tenant_id, a[2], uuid4().hex), "video/mp4", "video", 0)],
    )
    event = _due_reel_event(a, post_id)
    service = _content_service(brand_id)
    with tenant_session(tenant_id) as session:
        variant_id = session.scalar(
            select(creative.ContentDraft.selected_variant_id).where(
                creative.ContentDraft.id == post_id
            )
        )
        user_id = session.scalar(select(User.id).where(User.tenant_id == tenant_id))

    # The operator edits the approved copy (real service, real Postgres repository).
    edited = CopyPayload.model_validate(
        {
            "hook": "Nueva promo",
            "caption": "Dos por uno todo octubre en todas las arepas del local, solo en "
            "tienda y hasta agotar existencias.",
            "hashtags": ["promo", "octubre"],
            "cta": "Pide ya",
        }
    )
    assert (
        service.edit_variant(
            tenant_id=tenant_id, variant_id=variant_id, copy=edited, user_id=user_id
        )
        == ()
    )
    summary = DraftPostReader().get(tenant_id=tenant_id, post_id=post_id)
    assert summary.lifecycle_status == "generated"  # back in review, not a dead "approved"
    assert summary.approval is ApprovalStatus.PENDING and not summary.is_publishable

    # The worker waits: not approved → the event stays scheduled, nothing is sent.
    meta = _MetaCalls()
    runner = _tick(
        ScopedTenants([tenant_id]),
        meta,
        status=ContainerStatus.FINISHED,
        connections=PostgresConnectionGate(),
    )
    (executed,) = asyncio.run(runner.run_once()).tenants[0].executed
    assert executed.outcome is ExecutionOutcome.NOT_READY
    assert _stored(tenant_id, event.id).status == "scheduled" and meta.calls == []

    # Approved again: the edited revision is what gets published.
    service.approve(tenant_id=tenant_id, draft_id=post_id, variant_id=variant_id, user_id=user_id)
    publishable = DraftPostReader().get_publishable(tenant_id=tenant_id, post_id=post_id)
    assert isinstance(publishable, PublishablePost)
    assert publishable.approved_revision == 2
    assert "Dos por uno todo octubre en todas las arepas" in publishable.caption  # the edit
    asyncio.run(runner.run_once())
    asyncio.run(runner.run_once())
    assert _stored(tenant_id, event.id).status == "published"
    (attempt_id,) = _attempt_rows(tenant_id, f"cal:{event.id}:1")
    assert _attempt(tenant_id, attempt_id).caption == publishable.caption  # the edit went out


def test_the_summary_names_an_r2_video_so_the_ui_can_show_it(worlds_ab) -> None:
    a, _ = worlds_ab
    tenant_id = a[0]
    video_key = media_key(tenant_id, a[2], uuid4().hex)
    reel = _post_row(a, category="reel", items=[(video_key, "video/mp4", "video", 0)])
    image = _post_row(a)  # default: one JPEG
    local = _post_row(
        a, category="reel", items=[("generated/x/video.mp4", "video/mp4", "video", 0)]
    )
    reader = DraftPostReader()
    assert reader.get(tenant_id=tenant_id, post_id=reel).video_object_key == video_key
    assert reader.get(tenant_id=tenant_id, post_id=image).video_object_key is None
    assert reader.get(tenant_id=tenant_id, post_id=local).video_object_key is None


# --- reject from the Planificador, then take the rejected POST off the calendar -------------


def test_a_post_rejected_from_the_planner_is_never_published_and_can_be_removed(
    worlds_ab,
) -> None:
    from qualify_api.creative.fsm import InvalidTransition
    from qualify_api.planner.service import PostNotRejected

    a, _ = worlds_ab
    tenant_id, brand_id, _conn = a
    post_id = _post_row(
        a,
        status="generated",
        approved_revision=None,
        category="reel",
        items=[(media_key(tenant_id, a[2], uuid4().hex), "video/mp4", "video", 0)],
    )
    event = _due_reel_event(a, post_id)
    planner = PlannerService(
        repository=PostgresPlannerRepository(),
        posts=DraftPostReader(),
        connections=PostgresConnectionGate(),
    )
    # Still in review: "Quitar del calendario" is refused, nothing is touched.
    with pytest.raises(PostNotRejected):
        planner.remove_rejected_post(tenant_id=tenant_id, event_id=event.id)

    with tenant_session(tenant_id) as session:
        user_id = session.scalar(select(User.id).where(User.tenant_id == tenant_id))
    content = _content_service(brand_id)
    content.reject(tenant_id=tenant_id, draft_id=post_id, reason="planner", user_id=user_id)
    assert DraftPostReader().get(tenant_id=tenant_id, post_id=post_id).approval is (
        ApprovalStatus.REJECTED
    )
    # A rejected POST cannot be rejected again (the FSM, not the button, decides).
    with pytest.raises(InvalidTransition):
        content.reject(tenant_id=tenant_id, draft_id=post_id, reason="again", user_id=user_id)

    # The worker leaves it alone: due, but not approved.
    meta = _MetaCalls()
    runner = _tick(
        ScopedTenants([tenant_id]),
        meta,
        status=ContainerStatus.FINISHED,
        connections=PostgresConnectionGate(),
    )
    (executed,) = asyncio.run(runner.run_once()).tenants[0].executed
    assert executed.outcome is ExecutionOutcome.NOT_READY and meta.calls == []
    assert _stored(tenant_id, event.id).status == "scheduled"

    assert planner.remove_rejected_post(tenant_id=tenant_id, event_id=event.id) == 1
    assert _stored(tenant_id, event.id) is None
    assert DraftPostReader().get(tenant_id=tenant_id, post_id=post_id) is not None  # POST kept


# --- execution window (QUA-115) --------------------------------------------------


def test_list_due_hides_expired_events(repo, world_p) -> None:
    # `limit` is raised so rows left behind by other tests in the shared test tenant
    # (there is no teardown) cannot crowd this test's own events out of the page.
    expired = _due_event(repo, world_p, hours=-25)
    fresh = _due_event(repo, world_p, hours=-1)
    due = {e.id for e in repo.list_due(tenant_id=TENANT_P, now=datetime.now(UTC), limit=10_000)}
    assert fresh.id in due and expired.id not in due
    _retire(repo, expired, fresh)


def test_claim_of_an_expired_event_fails(repo, world_p) -> None:
    expired = _due_event(repo, world_p, hours=-25)
    claimed = repo.claim(
        tenant_id=TENANT_P, event_id=expired.id, expected_revision=1, now=datetime.now(UTC)
    )
    assert claimed is None
    assert repo.get(tenant_id=TENANT_P, event_id=expired.id).status == "scheduled"
    _retire(repo, expired)


def test_a_rescheduled_expired_event_is_due_and_claimable_again(repo, world_p) -> None:
    _, _, conn_id = world_p
    expired = _due_event(repo, world_p, hours=-25)
    moved = repo.reschedule(
        tenant_id=TENANT_P,
        event_id=expired.id,
        expected_revision=1,
        scheduled_at=datetime.now(UTC) - timedelta(hours=1),
        scheduled_tz=expired.scheduled_tz,
        connection_id=conn_id,
    )
    assert moved is not None and moved.revision == 2
    now = datetime.now(UTC)
    assert expired.id in {e.id for e in repo.list_due(tenant_id=TENANT_P, now=now, limit=10_000)}
    claimed = repo.claim(tenant_id=TENANT_P, event_id=expired.id, expected_revision=2, now=now)
    assert claimed is not None and claimed.status == "publishing"


# --- MP-11: one event per template output -------------------------------------------
# A `promo_producto` run leaves three `image_assets` on the draft, named by port: a Reel
# MP4, a feed JPEG and a story JPEG. The whole POST is no publishable shape; each output
# is, through its own event.


def _package_row(world: tuple[UUID, UUID, UUID], *, category: str | None = "reel") -> UUID:
    tenant_id, _, conn_id = world
    items = [
        (media_key(tenant_id, conn_id, uuid4().hex), "video/mp4", "video", 0),
        (media_key(tenant_id, conn_id, uuid4().hex), "image/jpeg", "image", 1),
        (media_key(tenant_id, conn_id, uuid4().hex), "image/jpeg", "image", 2),
    ]
    post_id = _post_row(world, category=category, items=items)
    with tenant_session(tenant_id) as session:
        for image in session.scalars(
            select(creative.ImageAsset).where(creative.ImageAsset.draft_id == post_id)
        ):
            image.output_port = {0: "reel", 1: "feed", 2: "story"}[image.position]
        session.flush()
    return post_id


def _user_of(tenant_id: UUID) -> UUID:
    with admin_session() as session:
        return session.scalar(select(User.id).where(User.tenant_id == tenant_id))


def test_output_port_round_trips_and_an_empty_string_is_refused(world_p) -> None:
    brand_id, user_id, conn_id = world_p
    repo = PostgresPlannerRepository()
    new = _new_event(TENANT_P, brand_id, user_id, conn_id)
    whole = repo.add(new)
    reel = repo.add(replace(new, output_port="reel"))
    assert whole.output_port is None and reel.output_port == "reel"
    assert repo.get(tenant_id=TENANT_P, event_id=reel.id).output_port == "reel"
    # A reschedule never changes the output.
    moved = repo.reschedule(
        tenant_id=TENANT_P,
        event_id=reel.id,
        expected_revision=1,
        scheduled_at=reel.scheduled_at + timedelta(hours=1),
        scheduled_tz=reel.scheduled_tz,
        connection_id=conn_id,
    )
    assert moved.output_port == "reel" and moved.revision == 2
    with pytest.raises(IntegrityError):
        repo.add(replace(new, output_port=""))
    occupying = repo.list_occupying(tenant_id=TENANT_P, brand_id=brand_id)
    assert {e.id for e in occupying} >= {whole.id, reel.id}


def test_a_package_evaluates_per_output_as_reels_image_and_stories(world_f2) -> None:
    tenant_id = world_f2[0]
    post_id = _package_row(world_f2)
    reader = DraftPostReader()

    whole = reader.get_publishable(tenant_id=tenant_id, post_id=post_id)
    assert isinstance(whole, NotPublishable)
    assert whole.reason is UnpublishableReason.UNSUPPORTED_SHAPE

    by_port = {
        port: reader.get_publishable(tenant_id=tenant_id, post_id=post_id, output_port=port)
        for port in ("reel", "feed", "story")
    }
    assert all(isinstance(v, PublishablePost) for v in by_port.values()), by_port
    assert {port: v.media_product_type for port, v in by_port.items()} == {
        "reel": "REELS",
        "feed": "IMAGE",
        "story": "STORIES",
    }
    for port, verdict in by_port.items():
        (item,) = verdict.media  # only that port's asset, at position 0
        assert item.position == 0 and verdict.output_port == port
    assert by_port["story"].media[0].content_type == "image/jpeg"
    assert by_port["reel"].media[0].media_type == "VIDEO"

    # The card sees the outputs and is publishable because each of them is.
    summary = reader.get(tenant_id=tenant_id, post_id=post_id)
    assert summary.output_ports == ("reel", "feed", "story")
    assert all(o.is_publishable for o in summary.outputs)
    assert summary.is_publishable and summary.media_product_type is None
    assert {o.port: o.media_product_type for o in summary.outputs} == {
        "reel": "REELS",
        "feed": "IMAGE",
        "story": "STORIES",
    }


def test_a_package_schedules_three_events_and_the_executor_asks_for_each_port(
    world_f2,
) -> None:
    tenant_id, brand_id, conn_id = world_f2
    post_id = _package_row(world_f2)
    user_id = _user_of(tenant_id)
    service = PlannerService(
        repository=PostgresPlannerRepository(),
        posts=DraftPostReader(),
        connections=PostgresConnectionGate(),
    )
    at = datetime.now(UTC) + timedelta(hours=2)
    events = {
        port: service.schedule(
            tenant_id=tenant_id,
            brand_id=brand_id,
            post_id=post_id,
            connection_id=conn_id,
            scheduled_at=at if port != "story" else at + timedelta(hours=6),
            scheduled_tz="America/Caracas",
            user_id=user_id,
            output_port=port,
        )
        for port in ("reel", "feed", "story")
    }
    assert {port: e.output_port for port, e in events.items()} == {
        "reel": "reel",
        "feed": "feed",
        "story": "story",
    }
    assert events["reel"].scheduled_at == events["feed"].scheduled_at
    # Fully planned: the POST leaves Sin programar.
    assert post_id not in {
        p.post_id for p in service.list_unscheduled(tenant_id=tenant_id, brand_id=brand_id)
    }

    # The Reel event, once due, is started as a REEL from its own port's asset.
    repo = PostgresPlannerRepository()
    with tenant_session(tenant_id) as session:
        session.execute(
            text(
                "UPDATE calendar_events SET scheduled_at = now() - interval '1 minute' "
                "WHERE id = :id"
            ),
            {"id": events["reel"].id},
        )
    due = repo.get(tenant_id=tenant_id, event_id=events["reel"].id)
    calls: list[str] = []
    result = asyncio.run(_executor(calls).try_execute(due))
    assert result.outcome is ExecutionOutcome.STARTED
    assert calls == ["REELS"]
    stored = repo.get(tenant_id=tenant_id, event_id=due.id)
    assert stored.output_port == "reel" and stored.publish_attempt_id == result.attempt_id

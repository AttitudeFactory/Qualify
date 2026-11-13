"""`db` tests for «Publicar» → «Tu semana» (m-25019217, migration 0158): the piece and
the `published` event `planner.immediate.record_publication` writes, their idempotency
(twice, concurrently), the week view, the piece's publishability, RLS between tenants,
what is never recorded, and the tick's bounded sweep.

Provisioning through `admin_session`; everything under test through `tenant_session`.
Each test provisions its own tenant, so re-runs against `qualify_test` never see another
run's attempts.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.creative import models as creative
from qualify_api.creative.own_media import PIPELINE_VERSION, request_key_for
from qualify_api.planner.composition import PostgresConnectionGate
from qualify_api.planner.discovery import DiscoveredTenants
from qualify_api.planner.draft_post_reader import DraftPostReader
from qualify_api.planner.immediate import (
    Outcome,
    Skip,
    record_publication,
    sweep_recent_publications,
)
from qualify_api.planner.models import CalendarEvent
from qualify_api.planner.post_reader import PublishablePost
from qualify_api.planner.repository import PostgresPlannerRepository
from qualify_api.planner.service import PlannerService
from qualify_api.publishing.models import PublishAttempt, PublishAttemptChild
from qualify_api.tenancy.models import Brand, Tenant, TenantMember, User

pytestmark = pytest.mark.db

CAPTION = "Shawarma mixto 🌯\n\n¡Hoy 2x1!\n\n#shawarma"
SETTLED = datetime(2026, 11, 11, 18, 30, tzinfo=UTC)  # a Wednesday


@dataclass(frozen=True)
class World:
    tenant_id: UUID
    brand_id: UUID
    user_id: UUID
    connection_id: UUID


def _world(*, brand: bool = True) -> World:
    tenant_id = uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant_id,
                name=f"immediate-{tenant_id}",
                country="VE",
                timezone="America/Caracas",
                currency="USD",
            )
        )
        session.flush()
        brand_row = Brand(tenant_id=tenant_id, name="Bianki")
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        user = User(tenant_id=tenant_id, email=f"o-{uuid4()}@p.co", display_name="Owner")
        session.add_all([brand_row, app, user])
        session.flush()
        session.add(TenantMember(tenant_id=tenant_id, user_id=user.id, role="owner"))
        session.flush()
        brand_id, app_id, user_id = brand_row.id, app.id, user.id
    with tenant_session(tenant_id) as session:
        conn = SocialConnection(
            tenant_id=tenant_id,
            brand_id=brand_id if brand else None,
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
    return World(tenant_id, brand_id, user_id, connection_id)


def _key(world: World) -> str:
    return f"t/{world.tenant_id}/media/{world.connection_id}/{uuid4()}"


def _attempt(
    world: World,
    *,
    product: str = "IMAGE",
    status: str = "published",
    settled_at: datetime | None = SETTLED,
    key: str | None = None,
    content_type: str | None = "image/jpeg",
    children: tuple[tuple[str, str, str], ...] = (),
) -> UUID:
    with tenant_session(world.tenant_id) as session:
        row = PublishAttempt(
            tenant_id=world.tenant_id,
            connection_id=world.connection_id,
            idempotency_key=key or f"web:{uuid4()}",
            caption=CAPTION,
            media_product_type=product,
            adapter_version="test",
            status=status,
            settled_at=settled_at,
            published_media_id="1789" if status == "published" else None,
            media_object_key=None if product == "CAROUSEL" else _key(world),
            media_content_type=None if product == "CAROUSEL" else content_type,
        )
        session.add(row)
        session.flush()
        for position, (object_key, content, media_type) in enumerate(children):
            session.add(
                PublishAttemptChild(
                    tenant_id=world.tenant_id,
                    attempt_id=row.id,
                    position=position,
                    media_object_key=object_key,
                    media_content_type=content,
                    media_product_type=media_type,
                    status="finished",
                )
            )
        session.flush()
        return row.id


def _counts(world: World) -> tuple[int, int]:
    with tenant_session(world.tenant_id) as session:
        drafts = session.scalar(select(func.count()).select_from(creative.ContentDraft))
        events = session.scalar(select(func.count()).select_from(CalendarEvent))
        return int(drafts or 0), int(events or 0)


def _record(world: World, attempt_id: UUID):
    return record_publication(
        tenant_id=world.tenant_id, attempt_id=attempt_id, user_id=world.user_id
    )


# -- idempotency ----------------------------------------------------------------------------


def test_recording_twice_leaves_one_piece_and_one_event() -> None:
    world = _world()
    attempt = _attempt(world)
    first = _record(world, attempt)
    second = _record(world, attempt)
    assert first.outcome is Outcome.RECORDED
    assert second.outcome is Outcome.EXISTING
    assert (second.draft_id, second.event_id) == (first.draft_id, first.event_id)
    assert _counts(world) == (1, 1)


def test_concurrent_recordings_leave_one_piece_and_one_event() -> None:
    world = _world()
    attempt = _attempt(world)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: _record(world, attempt), range(4)))
    assert sorted(r.outcome for r in results) == sorted(
        [Outcome.RECORDED, Outcome.EXISTING, Outcome.EXISTING, Outcome.EXISTING]
    )
    assert _counts(world) == (1, 1)


def test_the_database_refuses_a_second_event_for_one_attempt() -> None:
    world = _world()
    attempt = _attempt(world)
    result = _record(world, attempt)
    with pytest.raises(IntegrityError), tenant_session(world.tenant_id) as session:
        session.add(
            CalendarEvent(
                tenant_id=world.tenant_id,
                brand_id=world.brand_id,
                post_id=result.draft_id,
                connection_id=world.connection_id,
                scheduled_at=SETTLED,
                scheduled_tz="UTC",
                status="published",
                publish_attempt_id=attempt,
                created_by_user_id=world.user_id,
            )
        )
        session.flush()


# -- what is written ------------------------------------------------------------------------


def test_the_piece_is_an_approved_reusable_own_media_piece_with_provenance() -> None:
    world = _world()
    attempt = _attempt(world)
    result = _record(world, attempt)
    with tenant_session(world.tenant_id) as session:
        draft = session.get(creative.ContentDraft, result.draft_id)
        assert draft is not None
        brief = session.get(creative.ContentBrief, draft.brief_id)
        assert brief is not None and brief.kind == "own_media"
        assert (draft.status, draft.revision, draft.approved_revision) == ("approved", 1, 1)
        assert draft.approved_by == world.user_id and draft.approved_at == SETTLED
        assert (draft.reuse_type, draft.category) == ("recurrente", "galeria")
        assert draft.pipeline_version == PIPELINE_VERSION
        assert draft.request_key == request_key_for(attempt)
        assert draft.brand_id == world.brand_id
        event = session.get(CalendarEvent, result.event_id)
        assert event is not None
        assert (event.status, event.post_id, event.publish_attempt_id) == (
            "published",
            draft.id,
            attempt,
        )
        assert event.scheduled_at == SETTLED and event.destination == "post"
        assert event.scheduled_tz == "America/Caracas"
        attempt_row = session.get(PublishAttempt, attempt)
        assert attempt_row is not None
        assets = session.scalars(
            select(creative.ImageAsset).where(creative.ImageAsset.draft_id == draft.id)
        ).all()
        assert [a.object_key for a in assets] == [attempt_row.media_object_key]
        # the attempt itself is untouched: nothing here advances or settles it
        assert (attempt_row.status, attempt_row.settled_at) == ("published", SETTLED)


def test_list_week_shows_the_event_at_the_settled_time() -> None:
    world = _world()
    attempt = _attempt(world)
    result = _record(world, attempt)
    service = PlannerService(
        repository=PostgresPlannerRepository(),
        posts=DraftPostReader(),
        connections=PostgresConnectionGate(),
    )
    week = service.list_week(
        tenant_id=world.tenant_id,
        brand_id=world.brand_id,
        monday=date(2026, 11, 9),
        tz_name="America/Caracas",
    )
    assert [(p.event.id, p.event.post_id, p.event.scheduled_at, p.event.status) for p in week] == [
        (result.event_id, result.draft_id, SETTLED, "published")
    ]
    card = week[0].post
    assert card is not None and card.title == "Shawarma mixto 🌯"
    assert card.is_publishable and card.times_published == 1


def test_the_piece_is_publishable_again_with_the_original_caption() -> None:
    world = _world()
    result = _record(world, _attempt(world))
    assert result.draft_id is not None
    verdict = DraftPostReader().get_publishable(
        tenant_id=world.tenant_id, post_id=result.draft_id, destination="post"
    )
    assert isinstance(verdict, PublishablePost), verdict
    assert verdict.caption == CAPTION
    assert verdict.media_product_type == "IMAGE"


def test_a_carousel_attempt_is_one_piece_with_its_assets_in_order() -> None:
    world = _world()
    keys = [_key(world) for _ in range(3)]
    attempt = _attempt(
        world,
        product="CAROUSEL",
        children=(
            (keys[0], "image/jpeg", "IMAGE"),
            (keys[1], "video/mp4", "VIDEO"),
            (keys[2], "image/jpeg", "IMAGE"),
        ),
    )
    result = _record(world, attempt)
    with tenant_session(world.tenant_id) as session:
        assets = session.scalars(
            select(creative.ImageAsset)
            .where(creative.ImageAsset.draft_id == result.draft_id)
            .order_by(creative.ImageAsset.position)
        ).all()
    assert [(a.object_key, a.media_type, a.position) for a in assets] == [
        (keys[0], "image", 0),
        (keys[1], "video", 1),
        (keys[2], "image", 2),
    ]
    assert result.draft_id is not None
    verdict = DraftPostReader().get_publishable(
        tenant_id=world.tenant_id, post_id=result.draft_id, destination="post"
    )
    assert isinstance(verdict, PublishablePost) and verdict.media_product_type == "CAROUSEL"


def test_n_single_attempts_make_n_pieces() -> None:
    world = _world()
    attempts = [_attempt(world) for _ in range(3)]
    results = [_record(world, a) for a in attempts]
    assert len({r.draft_id for r in results}) == 3
    assert _counts(world) == (3, 3)


# -- what is never recorded -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("changes", "skip"),
    [
        ({"status": "failed"}, Skip.NOT_PUBLISHED),
        ({"status": "processing", "settled_at": None}, Skip.NOT_SETTLED),
        ({"key": "cal:00000000-0000-4000-8000-000000000001:1"}, Skip.CALENDAR_ATTEMPT),
    ],
)
def test_a_failed_unsettled_or_calendar_attempt_creates_nothing(
    changes: dict[str, object], skip: Skip
) -> None:
    world = _world()
    attempt = _attempt(world, **changes)  # type: ignore[arg-type]
    result = _record(world, attempt)
    assert (result.outcome, result.skip) == (Outcome.SKIPPED, skip)
    assert _counts(world) == (0, 0)


def test_a_connection_without_brand_records_nothing() -> None:
    world = _world(brand=False)
    result = _record(world, _attempt(world))
    assert (result.outcome, result.skip) == (Outcome.SKIPPED, Skip.NO_BRAND)
    assert _counts(world) == (0, 0)


# -- tenant isolation ------------------------------------------------------------------------


def test_tenant_b_cannot_read_or_record_tenant_a_rows() -> None:
    a, b = _world(), _world()
    attempt = _attempt(a)
    result = _record(a, attempt)
    with tenant_session(b.tenant_id) as session:
        assert session.get(creative.ContentDraft, result.draft_id) is None
        assert session.get(CalendarEvent, result.event_id) is None
        assert session.get(PublishAttempt, attempt) is None
    # B naming A's attempt sees nothing and writes nothing
    other = record_publication(tenant_id=b.tenant_id, attempt_id=attempt, user_id=b.user_id)
    assert (other.outcome, other.skip) == (Outcome.SKIPPED, Skip.NOT_FOUND)
    assert _counts(b) == (0, 0)


# -- the tick's sweep ------------------------------------------------------------------------


def test_the_sweep_is_bounded_and_idempotent() -> None:
    world = _world()
    now = datetime.now(UTC)
    recent = [_attempt(world, settled_at=now - timedelta(minutes=n + 1)) for n in range(3)]
    _attempt(world, settled_at=now - timedelta(hours=60))  # outside the 48 h window
    _attempt(world, status="failed", settled_at=now - timedelta(minutes=5))
    _attempt(world, key=f"cal:{uuid4()}:1", settled_at=now - timedelta(minutes=5))

    first = sweep_recent_publications(tenant_id=world.tenant_id, now=now, limit=2)
    assert [r.attempt_id for r in first] == recent[:2]  # newest first, at most `limit`
    assert all(r.outcome is Outcome.RECORDED for r in first)
    second = sweep_recent_publications(tenant_id=world.tenant_id, now=now, limit=2)
    assert [r.attempt_id for r in second] == recent[2:]
    assert sweep_recent_publications(tenant_id=world.tenant_id, now=now) == []
    assert _counts(world) == (3, 3)
    with tenant_session(world.tenant_id) as session:
        authors = set(session.scalars(select(CalendarEvent.created_by_user_id)).all())
    assert authors == {world.user_id}  # the tenant's owner


def test_the_production_discovery_finds_a_tenant_with_an_unrecorded_publication() -> None:
    world = _world()
    now = datetime.now(UTC)
    attempt = _attempt(world, settled_at=now - timedelta(minutes=3))
    assert world.tenant_id in DiscoveredTenants().tenants(now=now)
    _record(world, attempt)
    assert world.tenant_id not in DiscoveredTenants().tenants(now=now)


# -- the migration's index -------------------------------------------------------------------


def test_the_kind_check_admits_own_media_and_the_attempt_columns_exist() -> None:
    with admin_session() as session:
        check = session.scalar(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_content_briefs_kind'"
            )
        )
        columns = set(
            session.scalars(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'publish_attempts'"
                )
            )
        )
        index = session.scalar(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_cal_event_attempt'")
        )
    assert check is not None and "'own_media'" in check
    assert {"media_object_key", "media_content_type", "permalink"} <= columns
    assert index is not None and "UNIQUE" in index and "publish_attempt_id IS NOT NULL" in index

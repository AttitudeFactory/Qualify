"""`db`-marked tests for campaigns (QUA-143, migration 0045): the table's RLS, the
composite FK that keeps a POST inside its own tenant and brand, `ON DELETE SET NULL
(campaign_id)`, the service that assigns and clears a POST's campaign WITHOUT touching
its revision/status/approval, and the campaign reaching every calendar event of the POST
through `DraftPostReader` — several accounts, a weekly series, tags alongside — while
independent POSTs read exactly as before.

Provisioning through `admin_session` (BYPASSRLS); everything under test through
`tenant_session` / the services. The one delete goes through the owner role: the app
role has no DELETE on `campaigns` in V1."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from qualify_shared.objects.keys import media_key
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, IntegrityError

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.creative import campaigns
from qualify_api.creative import models as creative
from qualify_api.planner.composition import PostgresConnectionGate
from qualify_api.planner.draft_post_reader import DraftPostReader
from qualify_api.planner.post_reader import PostCampaign, PublishablePost
from qualify_api.planner.repository import PostgresPlannerRepository
from qualify_api.planner.service import PlannerService
from qualify_api.tenancy.models import Brand, Tenant, User

pytestmark = pytest.mark.db

TENANT_C = UUID("c0000000-0000-4000-8000-000000000143")
TENANT_D = UUID("d0000000-0000-4000-8000-000000000143")


def _provision(tenant_id: UUID, name: str, *, brands: int = 1) -> tuple[list[UUID], UUID, UUID]:
    """(brand_ids, user_id, active instagram connection_id) for `tenant_id`, idempotent."""
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
        existing = list(session.scalars(select(Brand).where(Brand.tenant_id == tenant_id)).all())
        while len(existing) < brands:
            brand = Brand(tenant_id=tenant_id, name=f"brand-{name}-{len(existing)}")
            session.add(brand)
            session.flush()
            existing.append(brand)
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        session.add(app)
        user = User(tenant_id=tenant_id, email=f"u-{uuid4()}@c.co", display_name="U")
        session.add(user)
        session.flush()
        brand_ids = sorted((b.id for b in existing), key=str)[:brands]
        app_id, user_id = app.id, user.id
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
    return brand_ids, user_id, connection_id


def _second_connection(tenant_id: UUID, user_id: UUID) -> UUID:
    with admin_session() as session:
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        session.add(app)
        session.flush()
        app_id = app.id
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


def _approved_post(tenant_id: UUID, brand_id: UUID, connection_id: UUID) -> UUID:
    """An approved, publishable POST at its approved revision: one JPEG in the tenant's
    R2 prefix, the selected variant set — what the Planificador accepts (QUA-118 D1)."""
    with tenant_session(tenant_id) as session:
        brief = creative.ContentBrief(
            tenant_id=tenant_id,
            brand_id=brand_id,
            objective="sale",
            topic="Lanzamiento",
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
            status="approved",
            pipeline_version="test",
            category="galeria",
            revision=1,
            approved_revision=1,
        )
        session.add(draft)
        session.flush()
        variant = creative.CopyVariant(
            tenant_id=tenant_id,
            draft_id=draft.id,
            ordinal=0,
            copy={"hook": "¡Nuevo!", "caption": "Sabor de temporada", "cta": "Pide ya"},
            model_id="test",
        )
        session.add(variant)
        session.flush()
        draft.selected_variant_id = variant.id
        session.add(
            creative.ImageAsset(
                tenant_id=tenant_id,
                draft_id=draft.id,
                media_url="https://cdn.example/x.jpg",
                object_key=media_key(tenant_id, connection_id, uuid4().hex),
                content_type="image/jpeg",
                media_type="image",
                position=0,
            )
        )
        session.flush()
        return draft.id


def _draft_state(tenant_id: UUID, post_id: UUID) -> tuple:
    with tenant_session(tenant_id) as session:
        d = session.get(creative.ContentDraft, post_id)
        assert d is not None
        return (
            d.status,
            d.revision,
            d.approved_revision,
            d.selected_variant_id,
            d.approved_at,
            d.updated_at,
        )


def _planner() -> PlannerService:
    return PlannerService(
        repository=PostgresPlannerRepository(),
        posts=DraftPostReader(),
        connections=PostgresConnectionGate(),
    )


def _monday(moment: datetime) -> date:
    day = moment.astimezone(UTC).date()
    return day - timedelta(days=day.weekday())


@pytest.fixture
def world_c() -> tuple[list[UUID], UUID, UUID]:
    return _provision(TENANT_C, "t-campaigns-c", brands=2)


@pytest.fixture
def world_d() -> tuple[list[UUID], UUID, UUID]:
    return _provision(TENANT_D, "t-campaigns-d")


@pytest.fixture
def owner_engine() -> Iterator[Engine]:
    engine = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    try:
        yield engine
    finally:
        engine.dispose()


# --- schema / RLS -----------------------------------------------------------------------


def test_campaigns_has_forced_rls_and_the_standard_policy() -> None:
    with admin_session() as session:
        flags = session.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE oid = 'public.campaigns'::regclass"
            )
        ).one()
        policies = session.scalars(
            text("SELECT policyname FROM pg_policies WHERE tablename = 'campaigns'")
        ).all()
    assert tuple(flags) == (True, True)
    assert policies == ["tenant_isolation"]


def test_another_tenant_neither_sees_nor_uses_a_campaign(world_c, world_d) -> None:
    (brand_c, _), user_c, conn_c = world_c
    (brand_d,), _, conn_d = world_d
    mine = campaigns.create_campaign(TENANT_C, brand_c, f"Privada {uuid4().hex[:6]}")
    # RLS: tenant D reads nothing of C, even by id.
    with tenant_session(TENANT_D) as session:
        assert session.get(creative.Campaign, mine.id) is None
    assert mine.id not in {c.id for c in campaigns.list_campaigns(TENANT_D, brand_d)}
    # ...and cannot put its own POST in C's campaign: the service refuses first...
    post_d = _approved_post(TENANT_D, brand_d, conn_d)
    with pytest.raises(campaigns.UnknownCampaign):
        campaigns.set_post_campaign(TENANT_D, post_d, mine.id)
    # ...and the composite FK refuses a direct write too.
    with pytest.raises(IntegrityError):
        with tenant_session(TENANT_D) as session:
            session.get(creative.ContentDraft, post_d).campaign_id = mine.id
            session.flush()
    # Inserting a campaign row for another tenant is refused by the policy's WITH CHECK.
    with pytest.raises(DBAPIError):
        with tenant_session(TENANT_D) as session:
            session.add(
                creative.Campaign(tenant_id=TENANT_C, brand_id=brand_c, name="x", color="blue")
            )
            session.flush()


def test_a_post_cannot_join_a_campaign_of_another_brand(world_c) -> None:
    (brand_1, brand_2), _, conn = world_c
    other_brand = campaigns.create_campaign(TENANT_C, brand_2, f"Marca 2 {uuid4().hex[:6]}")
    post = _approved_post(TENANT_C, brand_1, conn)
    with pytest.raises(campaigns.UnknownCampaign):
        campaigns.set_post_campaign(TENANT_C, post, other_brand.id)
    with pytest.raises(IntegrityError):  # the composite FK, not only the service
        with tenant_session(TENANT_C) as session:
            session.get(creative.ContentDraft, post).campaign_id = other_brand.id
            session.flush()
    assert campaigns.campaign_of(TENANT_C, post) is None


def test_names_are_unique_per_brand_ignoring_case_and_colours_rotate(world_c) -> None:
    (brand_1, brand_2), user, _ = world_c
    tag = uuid4().hex[:6]
    first = campaigns.create_campaign(TENANT_C, brand_1, f"  Lanzamiento   {tag} ", created_by=user)
    assert first.name == f"Lanzamiento {tag}"
    again = campaigns.create_campaign(TENANT_C, brand_1, f"lanzamiento {tag.upper()}")
    assert again == first  # picks the existing one instead of failing
    # Another brand of the same tenant may reuse the name.
    assert campaigns.create_campaign(TENANT_C, brand_2, f"Lanzamiento {tag}").id != first.id
    second = campaigns.create_campaign(TENANT_C, brand_1, f"Otra {tag}")
    assert second.color in campaigns.CAMPAIGN_COLORS and first.color in campaigns.CAMPAIGN_COLORS
    names = [c.name for c in campaigns.list_campaigns(TENANT_C, brand_1)]
    assert f"Lanzamiento {tag}" in names and f"Otra {tag}" in names
    with pytest.raises(campaigns.InvalidCampaignName):
        campaigns.create_campaign(TENANT_C, brand_1, "   ")
    with pytest.raises(campaigns.InvalidCampaignName):
        campaigns.create_campaign(TENANT_C, brand_1, "x" * (campaigns.NAME_MAX + 1))
    for state_color in ("teal", "green", "amber", "gray", "red"):  # the CHECK, not only us
        with pytest.raises(DBAPIError):
            with tenant_session(TENANT_C) as session:
                session.add(
                    creative.Campaign(
                        tenant_id=TENANT_C,
                        brand_id=brand_1,
                        name=f"{state_color} {tag}",
                        color=state_color,
                    )
                )
                session.flush()


def test_deleting_a_campaign_clears_only_the_posts_campaign(world_c, owner_engine) -> None:
    (brand_1, _), _, conn = world_c
    camp = campaigns.create_campaign(TENANT_C, brand_1, f"Efímera {uuid4().hex[:6]}")
    post = _approved_post(TENANT_C, brand_1, conn)
    campaigns.set_post_campaign(TENANT_C, post, camp.id)
    with owner_engine.begin() as conn_:
        conn_.execute(text("DELETE FROM campaigns WHERE id = :id"), {"id": camp.id})
    with tenant_session(TENANT_C) as session:
        draft = session.get(creative.ContentDraft, post)
        assert draft is not None
        assert draft.campaign_id is None
        assert draft.tenant_id == TENANT_C and draft.brand_id == brand_1


# --- the service never edits the POST's content -----------------------------------------


def test_assigning_and_clearing_keep_revision_status_and_approval(world_c) -> None:
    (brand_1, _), user, conn = world_c
    post = _approved_post(TENANT_C, brand_1, conn)
    before = _draft_state(TENANT_C, post)
    camp_a = campaigns.create_campaign(TENANT_C, brand_1, f"A {uuid4().hex[:6]}")
    camp_b = campaigns.create_campaign(TENANT_C, brand_1, f"B {uuid4().hex[:6]}")

    campaigns.set_post_campaign(TENANT_C, post, camp_a.id)
    assert campaigns.campaign_of(TENANT_C, post) == camp_a
    assert _draft_state(TENANT_C, post) == before
    campaigns.set_post_campaign(TENANT_C, post, camp_b.id)  # change
    assert campaigns.campaign_of(TENANT_C, post) == camp_b
    assert _draft_state(TENANT_C, post) == before
    campaigns.set_post_campaign(TENANT_C, post, None)  # clear
    assert campaigns.campaign_of(TENANT_C, post) is None
    assert _draft_state(TENANT_C, post) == before
    # Still publishable at its approved revision.
    assert isinstance(
        DraftPostReader().get_publishable(tenant_id=TENANT_C, post_id=post), PublishablePost
    )
    with pytest.raises(campaigns.UnknownPost):
        campaigns.set_post_campaign(TENANT_C, uuid4(), camp_a.id)


def test_a_scheduled_post_stays_scheduled_and_publishable_when_its_campaign_changes(
    world_c,
) -> None:
    (brand_1, _), user, conn = world_c
    post = _approved_post(TENANT_C, brand_1, conn)
    svc = _planner()
    at = datetime.now(UTC) + timedelta(days=2)
    event = svc.schedule(
        tenant_id=TENANT_C,
        brand_id=brand_1,
        post_id=post,
        connection_id=conn,
        scheduled_at=at,
        scheduled_tz="America/Caracas",
        user_id=user,
    )
    camp = campaigns.create_campaign(TENANT_C, brand_1, f"Programada {uuid4().hex[:6]}")
    campaigns.set_post_campaign(TENANT_C, post, camp.id)
    stored = svc._repo.get(tenant_id=TENANT_C, event_id=event.id)
    assert stored is not None
    assert (stored.status, stored.revision) == (event.status, event.revision)
    verdict = DraftPostReader().get_publishable(
        tenant_id=TENANT_C, post_id=post, destination=stored.destination
    )
    assert isinstance(verdict, PublishablePost) and verdict.approved_revision == 1
    summary = DraftPostReader().get(tenant_id=TENANT_C, post_id=post)
    assert summary is not None and summary.is_publishable is True
    assert summary.approval.value == "approved"


# --- every event of the POST reads the campaign through it ------------------------------


def test_every_event_of_a_campaign_post_reads_its_campaign(world_c) -> None:
    (brand_1, _), user, conn = world_c
    conn_2 = _second_connection(TENANT_C, user)
    in_campaign = _approved_post(TENANT_C, brand_1, conn)
    independent = _approved_post(TENANT_C, brand_1, conn)
    camp = campaigns.create_campaign(TENANT_C, brand_1, f"Semana {uuid4().hex[:6]}")
    campaigns.set_post_campaign(TENANT_C, in_campaign, camp.id)
    svc = _planner()

    # Two accounts at once, and a weekly series of three on the first account.
    at = datetime.now(UTC) + timedelta(days=1)
    pair = svc.schedule_many(
        tenant_id=TENANT_C,
        brand_id=brand_1,
        post_id=in_campaign,
        connection_ids=[conn, conn_2],
        scheduled_at=at,
        scheduled_tz="UTC",
        user_id=user,
    )
    first_day = (at + timedelta(days=1)).date()
    series = svc.schedule_series(
        tenant_id=TENANT_C,
        brand_id=brand_1,
        post_id=in_campaign,
        connection_ids=[conn],
        first_day=first_day,
        at=time(9, 0),
        scheduled_tz="UTC",
        user_id=user,
        count=3,
    )
    solo = svc.schedule(
        tenant_id=TENANT_C,
        brand_id=brand_1,
        post_id=independent,
        connection_id=conn,
        scheduled_at=at + timedelta(hours=1),
        scheduled_tz="UTC",
        user_id=user,
    )
    # A tag on one campaign event: the tag and the campaign coexist.
    tag = svc._repo.add_tag(tenant_id=TENANT_C, name=f"Etiqueta {uuid4().hex[:6]}", color="pink")
    svc.set_event_tags(tenant_id=TENANT_C, event_id=pair[0].id, tag_ids=[tag.id])

    expected = PostCampaign(id=camp.id, name=camp.name, color=camp.color)
    seen: dict[UUID, object] = {}
    for monday in sorted({_monday(e.scheduled_at) for e in [*pair, *series, solo]}):
        for planned in svc.list_week(
            tenant_id=TENANT_C, brand_id=brand_1, monday=monday, tz_name="UTC"
        ):
            seen[planned.event.id] = planned
    campaign_events = [e.id for e in [*pair, *series]]
    assert set(campaign_events) <= set(seen)
    for event_id in campaign_events:
        assert seen[event_id].post.campaign == expected
    assert seen[solo.id].post.campaign is None  # the independent POST, as before
    assert [t.id for t in seen[pair[0].id].tags] == [tag.id]  # tags untouched
    assert seen[pair[0].id].post.campaign == expected

    # The event table never learnt about campaigns.
    with admin_session() as session:
        columns = session.scalars(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'calendar_events'"
            )
        ).all()
    assert "campaign_id" not in columns

    # The gallery reads it too; clearing the campaign makes every event independent again.
    gallery = {
        p.post_id: p for p in DraftPostReader().list_for_brand(tenant_id=TENANT_C, brand_id=brand_1)
    }
    assert gallery[in_campaign].campaign == expected and gallery[independent].campaign is None
    campaigns.set_post_campaign(TENANT_C, in_campaign, None)
    after = svc.get(tenant_id=TENANT_C, event_id=series[1].id)
    assert after.post is not None and after.post.campaign is None


# --- colour: a closed list of four, recolourable, never a state colour ------------------


def test_only_the_four_campaign_colours_are_accepted(world_c) -> None:
    (brand_1, _), _, conn = world_c
    assert campaigns.CAMPAIGN_COLORS == ("violet", "pink", "blue", "orange")
    tag = uuid4().hex[:6]
    chosen = campaigns.create_campaign(TENANT_C, brand_1, f"Violeta {tag}", color="violet")
    assert chosen.color == "violet"
    pink = campaigns.create_campaign(TENANT_C, brand_1, f"Rosa {tag}", color="pink")
    assert pink.color == "pink"
    # An existing name keeps ITS colour: typing it again picks it, it does not recolour it.
    assert campaigns.create_campaign(TENANT_C, brand_1, f"violeta {tag}", color="blue") == chosen
    post = _approved_post(TENANT_C, brand_1, conn)
    for state_color in ("teal", "green", "amber", "gray", "tomato", ""):
        with pytest.raises(campaigns.InvalidCampaignColor):
            campaigns.create_campaign(TENANT_C, brand_1, f"Estado {tag}", color=state_color)
        with pytest.raises(campaigns.InvalidCampaignColor):
            campaigns.create_for_post(TENANT_C, post, f"Estado {tag}", color=state_color)
        with pytest.raises(campaigns.InvalidCampaignColor):
            campaigns.set_campaign_color(TENANT_C, chosen.id, state_color)
    assert campaigns.campaign_of(TENANT_C, post) is None  # refused before touching the POST
    assert campaigns.suggested_color(0) == "violet" and campaigns.suggested_color(5) == "pink"


def test_the_app_role_may_recolour_but_never_rename(world_c) -> None:
    (brand_1, _), _, _ = world_c
    camp = campaigns.create_campaign(TENANT_C, brand_1, f"Fija {uuid4().hex[:6]}")
    with pytest.raises(DBAPIError):  # column grant: UPDATE (color) only
        with tenant_session(TENANT_C) as session:
            session.execute(
                text("UPDATE campaigns SET name = 'Otro nombre' WHERE id = :id"), {"id": camp.id}
            )
    with tenant_session(TENANT_C) as session:
        session.execute(
            text("UPDATE campaigns SET color = 'orange' WHERE id = :id"), {"id": camp.id}
        )
    with tenant_session(TENANT_C) as session:
        stored = session.get(creative.Campaign, camp.id)
        assert stored is not None and (stored.name, stored.color) == (camp.name, "orange")


def test_recolouring_reaches_every_post_and_event_and_edits_none(world_c) -> None:
    (brand_1, _), user, conn = world_c
    first = _approved_post(TENANT_C, brand_1, conn)
    second = _approved_post(TENANT_C, brand_1, conn)
    camp = campaigns.create_campaign(
        TENANT_C, brand_1, f"Recolor {uuid4().hex[:6]}", color="violet"
    )
    campaigns.set_post_campaign(TENANT_C, first, camp.id)
    campaigns.set_post_campaign(TENANT_C, second, camp.id)
    svc = _planner()
    at = datetime.now(UTC) + timedelta(days=4)
    events = [
        svc.schedule(
            tenant_id=TENANT_C,
            brand_id=brand_1,
            post_id=post,
            connection_id=conn,
            scheduled_at=at + timedelta(hours=i),
            scheduled_tz="UTC",
            user_id=user,
        )
        for i, post in enumerate((first, second))
    ]
    before = {p: _draft_state(TENANT_C, p) for p in (first, second)}
    stored_before = {e.id: svc._repo.get(tenant_id=TENANT_C, event_id=e.id) for e in events}

    assert campaigns.set_campaign_color(TENANT_C, camp.id, "orange").color == "orange"

    for event in events:
        planned = svc.get(tenant_id=TENANT_C, event_id=event.id)
        assert planned.post is not None and planned.post.campaign is not None
        assert planned.post.campaign.color == "orange"
        assert svc._repo.get(tenant_id=TENANT_C, event_id=event.id) == stored_before[event.id]
    assert {p: _draft_state(TENANT_C, p) for p in (first, second)} == before
    with pytest.raises(campaigns.UnknownCampaign):
        campaigns.set_campaign_color(TENANT_C, uuid4(), "blue")


# --- the drawer's «Confirmar» path (QUA-143 AC 17-22) ------------------------------------


def test_the_reader_counts_the_posts_publications(world_c) -> None:
    (brand_1, _), user, conn = world_c
    post = _approved_post(TENANT_C, brand_1, conn)
    assert DraftPostReader().get(tenant_id=TENANT_C, post_id=post).event_count == 0
    svc = _planner()
    at = datetime.now(UTC) + timedelta(days=5)
    svc.schedule_series(
        tenant_id=TENANT_C,
        brand_id=brand_1,
        post_id=post,
        connection_ids=[conn],
        first_day=at.date(),
        at=time(8, 0),
        scheduled_tz="UTC",
        user_id=user,
        count=3,
    )
    assert DraftPostReader().get(tenant_id=TENANT_C, post_id=post).event_count == 3


def test_the_drawer_confirm_path_creates_and_assigns_without_editing_the_post(world_c) -> None:
    """What «Confirmar» runs per piece (`Qualify.campaign_provider.apply_post_choice`
    maps onto exactly these calls): a new campaign in a chosen colour, then clear, then an
    existing one — the POST's revision, status and approval never move."""
    (brand_1, _), user, conn = world_c
    post = _approved_post(TENANT_C, brand_1, conn)
    before = _draft_state(TENANT_C, post)
    name = f"Drawer {uuid4().hex[:6]}"
    camp = campaigns.create_for_post(TENANT_C, post, name, color="orange", created_by=user)
    assert campaigns.campaign_of(TENANT_C, post) == camp and camp.color == "orange"
    assert _draft_state(TENANT_C, post) == before
    campaigns.set_post_campaign(TENANT_C, post, None)
    assert campaigns.campaign_of(TENANT_C, post) is None
    campaigns.set_post_campaign(TENANT_C, post, camp.id)
    assert campaigns.campaign_of(TENANT_C, post) == camp
    assert _draft_state(TENANT_C, post) == before

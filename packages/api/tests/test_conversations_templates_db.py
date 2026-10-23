"""`PostgresReplyTemplateRepository` against the real database (m-24789472, 0079). What only
Postgres can prove:

- the defaults are seeded once even when several first opens race (the seed marker's
  `ON CONFLICT DO NOTHING`), and deleting them all does not bring them back;
- create appends under the cap; reorder persists; the CHECKs mirror the service's limits;
- RLS: another tenant reads, edits, deletes and seeds nothing of an account's library,
  and both tables are invisible to it;
- B5: none of it writes a `conversation_outbox` row.

Seeding follows `test_conversations_repository_db.py`: tenant/user/app via `admin_session`,
the Instagram connection through `tenant_session` (the production door). Each test uses a
fresh connection, so re-runs need no cleanup.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.conversations.composition import brand_name_for
from qualify_api.conversations.contracts import CHANNEL_DM
from qualify_api.conversations.models import (
    ConversationOutboxItem,
    ConversationReplyTemplate,
    ConversationReplyTemplateSeed,
)
from qualify_api.conversations.repository import PostgresConversationRepository
from qualify_api.conversations.templates import (
    DEFAULT_TEMPLATES,
    MAX_TEMPLATES_PER_CONNECTION,
    PostgresReplyTemplateRepository,
    ReplyTemplateError,
    ReplyTemplateNotFound,
    ReplyTemplateService,
)
from qualify_api.tenancy.models import Brand, Tenant, User

pytestmark = pytest.mark.db

TENANT = UUID("a0000000-0000-4000-8000-0000000007b1")
OTHER = UUID("a0000000-0000-4000-8000-0000000007b2")
DEFAULT_KEYS = [d.key for d in DEFAULT_TEMPLATES]


@pytest.fixture
def seeded() -> dict[str, UUID]:
    with admin_session() as session:
        for tenant_id, name in ((TENANT, "reply-templates"), (OTHER, "reply-templates-other")):
            if session.get(Tenant, tenant_id) is None:
                session.add(
                    Tenant(
                        id=tenant_id,
                        name=f"t-{name}",
                        country="CO",
                        timezone="America/Bogota",
                        currency="COP",
                    )
                )
                session.flush()
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        user = User(tenant_id=TENANT, email=f"u-{uuid4()}@templates.co", display_name="U")
        session.add_all([app, user])
        session.flush()
        app_id, user_id = app.id, user.id

    with tenant_session(TENANT) as session:
        brand = Brand(tenant_id=TENANT, name="Polet Bubble Tea")
        session.add(brand)
        session.flush()
        connection = SocialConnection(
            tenant_id=TENANT,
            platform_app_id=app_id,
            brand_id=brand.id,
            platform="instagram",
            account_type="business",
            external_account_id=f"ig-{uuid4().hex[:12]}",
            linked_page_id="page-1",
            granted_scopes=["instagram_manage_messages"],
            status="active",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=user_id,
        )
        session.add(connection)
        session.flush()
        return {"connection": connection.id, "user": user_id}


def _service() -> ReplyTemplateService:
    return ReplyTemplateService(
        repository=PostgresReplyTemplateRepository(),
        threads=PostgresConversationRepository(),
        brand_name=brand_name_for,
    )


def _outbox_rows(connection_id: UUID) -> int:
    with tenant_session(TENANT) as session:
        return int(
            session.scalar(
                select(func.count(ConversationOutboxItem.id)).where(
                    ConversationOutboxItem.connection_id == connection_id
                )
            )
            or 0
        )


def test_first_open_seeds_once_and_is_remembered(seeded) -> None:
    service = _service()
    conn = seeded["connection"]
    first = service.list_for_connection(tenant_id=TENANT, connection_id=conn)
    second = service.list_for_connection(tenant_id=TENANT, connection_id=conn)
    assert [t.default_key for t in first] == DEFAULT_KEYS
    assert [t.id for t in second] == [t.id for t in first]
    with tenant_session(TENANT) as session:
        seed = session.get(ConversationReplyTemplateSeed, conn)
        assert seed is not None and seed.defaults_version == 1

    for template in first:
        assert service.delete(tenant_id=TENANT, template_id=template.id) is True
    assert service.list_for_connection(tenant_id=TENANT, connection_id=conn) == []


def test_concurrent_first_opens_seed_exactly_once(seeded) -> None:
    repo = PostgresReplyTemplateRepository()
    conn = seeded["connection"]
    workers = 6
    barrier = Barrier(workers)

    def open_library() -> bool:
        barrier.wait()
        return repo.ensure_defaults(tenant_id=TENANT, connection_id=conn)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda _: open_library(), range(workers)))
    assert results.count(True) == 1
    listed = repo.list_templates(tenant_id=TENANT, connection_id=conn)
    assert [t.default_key for t in listed] == DEFAULT_KEYS


def test_create_update_reorder_and_cap(seeded) -> None:
    service = _service()
    conn, user = seeded["connection"], seeded["user"]
    created = service.create(
        tenant_id=TENANT, connection_id=conn, title="Envíos", body="Enviamos.", user_id=user
    )
    assert created.position == len(DEFAULT_TEMPLATES)
    assert created.created_by_user_id == user

    updated = service.update(
        tenant_id=TENANT,
        template_id=created.id,
        title="Envíos",
        body="Enviamos hoy.",
        user_id=user,
    )
    assert updated.body == "Enviamos hoy." and updated.updated_at >= created.updated_at

    ids = [t.id for t in service.list_for_connection(tenant_id=TENANT, connection_id=conn)]
    wanted = [ids[-1], *ids[:-1]]
    service.reorder(tenant_id=TENANT, connection_id=conn, template_ids=wanted)
    listed = service.list_for_connection(tenant_id=TENANT, connection_id=conn)
    assert [t.id for t in listed] == wanted
    assert [t.position for t in listed] == list(range(len(wanted)))

    with pytest.raises(ReplyTemplateError) as stale:
        service.reorder(tenant_id=TENANT, connection_id=conn, template_ids=wanted[:-1])
    assert stale.value.code == "order_stale"

    for n in range(MAX_TEMPLATES_PER_CONNECTION - len(wanted)):
        service.create(tenant_id=TENANT, connection_id=conn, title=f"P{n}", body="x", user_id=None)
    with pytest.raises(ReplyTemplateError) as cap:
        service.create(tenant_id=TENANT, connection_id=conn, title="Otra", body="x", user_id=None)
    assert cap.value.code == "limit_reached"


def test_checks_mirror_the_service_limits(seeded) -> None:
    PostgresReplyTemplateRepository().ensure_defaults(
        tenant_id=TENANT, connection_id=seeded["connection"]
    )
    for title, body in (("ok", "x" * 1001), ("x" * 61, "ok"), ("  ", "ok"), ("ok", "")):
        with pytest.raises(IntegrityError), tenant_session(TENANT) as session:
            session.add(
                ConversationReplyTemplate(
                    tenant_id=TENANT,
                    connection_id=seeded["connection"],
                    title=title,
                    body=body,
                    position=99,
                )
            )
            session.flush()


def test_a_second_copy_of_a_default_is_impossible(seeded) -> None:
    PostgresReplyTemplateRepository().ensure_defaults(
        tenant_id=TENANT, connection_id=seeded["connection"]
    )
    with pytest.raises(IntegrityError), tenant_session(TENANT) as session:
        session.add(
            ConversationReplyTemplate(
                tenant_id=TENANT,
                connection_id=seeded["connection"],
                title="Saludo",
                body="Hola",
                position=9,
                default_key="greeting",
            )
        )
        session.flush()


def test_render_reads_the_thread_and_the_brand(seeded) -> None:
    conn = seeded["connection"]
    threads = PostgresConversationRepository()
    upsert = threads.upsert_thread(
        tenant_id=TENANT,
        connection_id=conn,
        channel=CHANNEL_DM,
        counterpart_external_id=f"igsid-{uuid4().hex[:10]}",
    )
    service = _service()
    greeting = service.list_for_connection(tenant_id=TENANT, connection_id=conn)[0]
    rendered = service.render(tenant_id=TENANT, template_id=greeting.id, thread_id=upsert.thread_id)
    # No profile synced yet: {nombre} stays visible for the person; the brand resolves.
    assert rendered.text.startswith("¡Hola, {nombre}! Gracias por escribirnos a Polet Bubble Tea.")
    assert rendered.unresolved == ("{nombre}",)


def test_brand_name_falls_back_to_the_business_name(seeded) -> None:
    conn = seeded["connection"]
    with tenant_session(TENANT) as session:
        session.execute(
            text("UPDATE social_connections SET brand_id = NULL WHERE id = :id"), {"id": conn}
        )
    assert brand_name_for(TENANT, conn) == "t-reply-templates"


def test_rls_another_tenant_sees_and_touches_nothing(seeded) -> None:
    conn = seeded["connection"]
    mine = _service().list_for_connection(tenant_id=TENANT, connection_id=conn)
    theirs = _service()
    repo = PostgresReplyTemplateRepository()

    with pytest.raises(ReplyTemplateNotFound) as caught:
        theirs.list_for_connection(tenant_id=OTHER, connection_id=conn)
    assert caught.value.code == "connection_not_found"
    with pytest.raises(ReplyTemplateNotFound):
        theirs.create(tenant_id=OTHER, connection_id=conn, title="x", body="y", user_id=None)
    with pytest.raises(ReplyTemplateNotFound):
        theirs.update(tenant_id=OTHER, template_id=mine[0].id, title="x", body="y", user_id=None)
    assert theirs.delete(tenant_id=OTHER, template_id=mine[0].id) is False
    assert repo.get_template(tenant_id=OTHER, template_id=mine[0].id) is None
    assert repo.list_templates(tenant_id=OTHER, connection_id=conn) == []

    with tenant_session(OTHER) as session:
        assert session.scalar(select(func.count()).select_from(ConversationReplyTemplate)) == 0
        assert session.scalar(select(func.count()).select_from(ConversationReplyTemplateSeed)) == 0
    # Writing a row for another tenant's account is refused by the policy's WITH CHECK.
    with pytest.raises(DBAPIError), tenant_session(OTHER) as session:
        session.add(
            ConversationReplyTemplate(
                tenant_id=TENANT, connection_id=conn, title="x", body="y", position=0
            )
        )
        session.flush()

    # Untouched for the owner.
    again = _service().list_for_connection(tenant_id=TENANT, connection_id=conn)
    assert [(t.id, t.title, t.body) for t in again] == [(t.id, t.title, t.body) for t in mine]


def test_no_template_operation_writes_the_outbox(seeded) -> None:
    conn = seeded["connection"]
    threads = PostgresConversationRepository()
    upsert = threads.upsert_thread(
        tenant_id=TENANT,
        connection_id=conn,
        channel=CHANNEL_DM,
        counterpart_external_id=f"igsid-{uuid4().hex[:10]}",
    )
    service = _service()
    listed = service.list_for_connection(tenant_id=TENANT, connection_id=conn)
    created = service.create(
        tenant_id=TENANT, connection_id=conn, title="Gracias", body="¡Gracias!", user_id=None
    )
    for template in [*listed, created]:
        service.render(tenant_id=TENANT, template_id=template.id, thread_id=upsert.thread_id)
    service.reorder(
        tenant_id=TENANT, connection_id=conn, template_ids=[created.id, *(t.id for t in listed)]
    )
    service.delete(tenant_id=TENANT, template_id=created.id)
    assert _outbox_rows(conn) == 0

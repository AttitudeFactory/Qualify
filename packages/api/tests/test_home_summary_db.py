"""`read_home_counts` against the real database (m-24842962, NAV-4): the counts respect
RLS — two tenants, each sees only its own.

Fresh tenant ids per run: the app role cannot DELETE `threads`/`messages`, so reusing
fixed ids would let earlier runs leak into the exact counts asserted here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.home import read_home_counts
from qualify_api.tenancy.models import Tenant, User

pytestmark = pytest.mark.db

NOW = datetime.now(UTC)

_THREAD = text(
    """
    INSERT INTO threads (id, tenant_id, connection_id, channel, external_thread_id, status,
                         last_message_at, last_inbound_at)
    VALUES (:id, :tenant_id, :connection_id, :channel, :ext, 'open', :at, :at)
    """
)
_MESSAGE = text(
    """
    INSERT INTO messages (id, tenant_id, thread_id, connection_id, external_message_id,
                          direction, text, posted_at, shape_version)
    VALUES (:id, :tenant_id, :thread_id, :connection_id, :ext, :direction, 'hola', :at,
            'test')
    """
)


def _tenant_with_connection(name: str) -> tuple[UUID, UUID]:
    tenant_id = uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant_id,
                name=f"home-{name}-{tenant_id.hex[:6]}",
                country="CO",
                timezone="America/Bogota",
                currency="COP",
            )
        )
        session.flush()
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        user = User(tenant_id=tenant_id, email=f"u-{uuid4()}@home.co", display_name="U")
        session.add_all([app, user])
        session.flush()
        app_id, user_id = app.id, user.id
    with tenant_session(tenant_id) as session:
        connection = SocialConnection(
            tenant_id=tenant_id,
            platform_app_id=app_id,
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
        return tenant_id, connection.id


def _dm_waiting(tenant_id: UUID, connection_id: UUID, *, channel: str = "dm") -> None:
    """A thread whose last message is an unread inbound one: someone is waiting."""
    thread_id = uuid4()
    with tenant_session(tenant_id) as session:
        session.execute(
            _THREAD,
            {
                "id": thread_id,
                "tenant_id": tenant_id,
                "connection_id": connection_id,
                "channel": channel,
                "ext": uuid4().hex,
                "at": NOW - timedelta(hours=1),
            },
        )
        session.execute(
            _MESSAGE,
            {
                "id": uuid4(),
                "tenant_id": tenant_id,
                "thread_id": thread_id,
                "connection_id": connection_id,
                "ext": uuid4().hex,
                "direction": "inbound",
                "at": NOW - timedelta(hours=1),
            },
        )


def test_each_tenant_counts_only_its_own() -> None:
    tenant_a, conn_a = _tenant_with_connection("a")
    tenant_b, conn_b = _tenant_with_connection("b")
    _dm_waiting(tenant_a, conn_a)
    for _ in range(3):
        _dm_waiting(tenant_b, conn_b)
    _dm_waiting(tenant_b, conn_b, channel="whatsapp")

    a = read_home_counts(tenant_a, now=NOW)
    b = read_home_counts(tenant_b, now=NOW)

    assert (a.people_waiting, a.messages_week_dm, a.messages_week_whatsapp) == (1, 1, 0)
    assert (b.people_waiting, b.messages_week_dm, b.messages_week_whatsapp) == (3, 3, 1)
    assert a.instagram_connected and b.instagram_connected
    assert not a.has_publication and a.drafts_to_approve == 0


def test_a_tenant_with_nothing_reads_zeros() -> None:
    tenant_id, _conn = _tenant_with_connection("empty")
    counts = read_home_counts(tenant_id, now=NOW)
    assert counts.people_waiting == counts.messages_week == counts.mentions_week == 0
    assert counts.instagram_connected


def _draft_with_preview(tenant_id: UUID, *, created: datetime, status: str = "draft") -> None:
    """A generated publication whose video is a vista previa made at `created`."""
    from qualify_api.creative.models import ContentBrief, ContentDraft, ImageAsset
    from qualify_api.tenancy.models import Brand

    with admin_session() as session:
        brand = Brand(tenant_id=tenant_id, name=f"home-brand-{uuid4().hex[:6]}")
        session.add(brand)
        session.flush()
        brand_id = brand.id
    with tenant_session(tenant_id) as session:
        brief = ContentBrief(
            tenant_id=tenant_id,
            brand_id=brand_id,
            objective="sale",
            topic="shawarma mixto",
            platform="instagram",
            format="reels_9_16",
            intent="organic",
            content_type="product",
            image_route="template_only",
            kind="clip",
        )
        session.add(brief)
        session.flush()
        draft = ContentDraft(
            tenant_id=tenant_id,
            brand_id=brand_id,
            brief_id=brief.id,
            status="generated",
            pipeline_version="creative-v2",
        )
        session.add(draft)
        session.flush()
        session.add(
            ImageAsset(
                tenant_id=tenant_id,
                draft_id=draft.id,
                media_url=f"generated/{tenant_id}/{draft.id}/clip.mp4",
                object_key=f"generated/{tenant_id}/{draft.id}/clip.mp4",
                position=0,
                params={"draft": {"status": status, "created_at": created.timestamp()}},
            )
        )


def test_videos_about_to_expire_are_counted_from_two_days_before() -> None:
    """Founder 2026-10-24: a vista previa lasts 7 days; Inicio warns from 2 days before."""
    tenant_id, _conn = _tenant_with_connection("expiring")
    _draft_with_preview(tenant_id, created=NOW - timedelta(days=6))  # 1 day left: counted
    _draft_with_preview(tenant_id, created=NOW - timedelta(days=5, hours=1))  # counted
    _draft_with_preview(tenant_id, created=NOW - timedelta(days=2))  # 5 days left: not yet
    _draft_with_preview(tenant_id, created=NOW - timedelta(days=8))  # expired: not counted
    _draft_with_preview(tenant_id, created=NOW - timedelta(days=6), status="final")
    assert read_home_counts(tenant_id, now=NOW).videos_expiring_soon == 2

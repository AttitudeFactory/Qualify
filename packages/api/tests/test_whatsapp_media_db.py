"""0061 — inbound media columns against the real database.

What only Postgres can prove: the webhook worker (`qualify_webhook_worker`, BYPASSRLS,
grant-bounded) can INSERT the three `media_*` columns it writes; `qualify_app` reads them
through the chats SQL (preview + `has_media`) and fills `media_object_key` once (the
`IS NULL` guard) under RLS; another tenant's message is invisible to the locator's read;
the CHECK refuses a type outside the list; and the capturing locator runs end to end over
`PostgresMediaRecordRepository`.

Seeding follows `test_whatsapp_chat_repository_db.py`. Every run makes fresh connections
and filters by them — the app role cannot DELETE, so earlier rows stay.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import IO
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from qualify_shared.db.webhook import webhook_worker_session
from qualify_shared.objects.keys import require_tenant_prefix
from qualify_shared.social.wa_shapes import SHAPE_VERSION
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.tenancy.models import Tenant, User
from qualify_api.whatsapp.chats import PostgresChatRepository
from qualify_api.whatsapp.client import MediaInfo
from qualify_api.whatsapp.media import CapturingMediaLocator, PostgresMediaRecordRepository
from qualify_api.whatsapp.repository import PostgresWhatsAppInboxRepository

pytestmark = pytest.mark.db

TENANT = UUID("a0000000-0000-4000-8000-0000000000b1")
OTHER_TENANT = UUID("a0000000-0000-4000-8000-0000000000b2")
NOW = datetime.now(UTC).replace(microsecond=0)


def _ensure_tenant(session: Session, tenant_id: UUID, name: str) -> None:
    if session.get(Tenant, tenant_id) is None:
        session.add(
            Tenant(id=tenant_id, name=name, country="CO", timezone="America/Bogota", currency="COP")
        )
        session.flush()


def _connection(tenant_id: UUID, app_id: UUID, user_id: UUID) -> UUID:
    with tenant_session(tenant_id) as session:
        connection = SocialConnection(
            tenant_id=tenant_id,
            platform_app_id=app_id,
            platform="whatsapp",
            account_type="waba_phone_number",
            external_account_id=f"pn-{uuid4().hex[:12]}",
            linked_page_id=None,
            granted_scopes=["whatsapp_business_messaging"],
            status="active",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=user_id,
        )
        session.add(connection)
        session.flush()
        return connection.id


@pytest.fixture
def seeded() -> dict[str, UUID]:
    with admin_session() as session:
        _ensure_tenant(session, TENANT, "t-wa-media")
        _ensure_tenant(session, OTHER_TENANT, "t-wa-media-other")
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        user = User(tenant_id=TENANT, email=f"u-{uuid4()}@wamedia.co", display_name="U")
        other = User(tenant_id=OTHER_TENANT, email=f"o-{uuid4()}@wamedia.co", display_name="O")
        session.add_all([app, user, other])
        session.flush()
        ids = {"app": app.id, "user": user.id, "other": other.id}
    ids["connection"] = _connection(TENANT, ids["app"], ids["user"])
    ids["other_connection"] = _connection(OTHER_TENANT, ids["app"], ids["other"])
    return ids


def _inbound(
    tenant_id: UUID,
    connection_id: UUID,
    *,
    media_type: str | None,
    media_id: str | None = None,
    media_mime: str | None = None,
    text_value: str | None = None,
) -> tuple[UUID, UUID]:
    """Through the WORKER door, exactly as the handler writes. Returns (thread, message)."""
    worker = PostgresWhatsAppInboxRepository()
    wa_id = f"57{uuid4().int % 10**10:010d}"
    wamid = f"wamid.{uuid4().hex}"
    upsert = worker.upsert_thread(
        tenant_id=tenant_id, connection_id=connection_id, wa_id=wa_id, inbound_at=NOW
    )
    assert worker.insert_inbound_message(
        tenant_id=tenant_id,
        thread_id=upsert.thread_id,
        connection_id=connection_id,
        external_message_id=wamid,
        author_external_id=wa_id,
        author_username=None,
        text=text_value,
        posted_at=NOW - timedelta(minutes=1),
        shape_version=SHAPE_VERSION,
        media_type=media_type,
        media_id=media_id,
        media_mime=media_mime,
    )
    with webhook_worker_session() as session:
        message_id = session.execute(
            text("SELECT id FROM messages WHERE connection_id = :c AND external_message_id = :w"),
            {"c": connection_id, "w": wamid},
        ).scalar_one()
    return upsert.thread_id, message_id


def test_the_worker_writes_media_and_the_app_reads_it_through_the_chats_sql(
    seeded: dict[str, UUID],
) -> None:
    conn = seeded["connection"]
    thread_id, _ = _inbound(
        TENANT, conn, media_type="audio", media_id="998877", media_mime="audio/ogg; codecs=opus"
    )
    repo = PostgresChatRepository()
    [message] = repo.list_messages(tenant_id=TENANT, thread_id=thread_id, before=None, limit=10)
    assert (message.media_kind, message.has_media, message.media_mime) == (
        "audio",
        True,
        "audio/ogg; codecs=opus",
    )
    [summary] = repo.list_threads(
        tenant_id=TENANT, connection_id=conn, status=None, limit=5, before=None, thread_id=thread_id
    )
    assert (summary.last_message_text, summary.last_message_media_kind) == (None, "audio")


def test_a_location_names_its_kind_without_media(seeded: dict[str, UUID]) -> None:
    thread_id, _ = _inbound(TENANT, seeded["connection"], media_type="location")
    [message] = PostgresChatRepository().list_messages(
        tenant_id=TENANT, thread_id=thread_id, before=None, limit=10
    )
    assert (message.media_kind, message.has_media) == ("location", False)


def test_the_check_refuses_a_type_outside_the_list(seeded: dict[str, UUID]) -> None:
    with pytest.raises(IntegrityError, match="ck_message_media_type"):
        _inbound(TENANT, seeded["connection"], media_type="reaction")


def test_the_lazy_fill_is_written_once_under_rls(seeded: dict[str, UUID]) -> None:
    _, message_id = _inbound(
        TENANT, seeded["connection"], media_type="image", media_id="5544", media_mime="image/png"
    )
    records = PostgresMediaRecordRepository()
    record = records.get_media(tenant_id=TENANT, message_id=message_id)
    assert record is not None
    assert (record.direction, record.media_id, record.media_object_key) == ("inbound", "5544", None)

    first = f"t/{TENANT}/fp/whatsapp/{seeded['connection']}/media/5544"
    records.set_media_object_key(tenant_id=TENANT, message_id=message_id, object_key=first)
    records.set_media_object_key(tenant_id=TENANT, message_id=message_id, object_key="t/x/other")
    again = records.get_media(tenant_id=TENANT, message_id=message_id)
    assert again is not None and again.media_object_key == first  # `IS NULL` guard

    # Another tenant: invisible to the read, and its write touches nothing.
    assert records.get_media(tenant_id=OTHER_TENANT, message_id=message_id) is None


class _Client:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def media_url(self, media_id: str) -> MediaInfo:
        self.calls.append("media_url")
        return MediaInfo(
            id=media_id,
            url="https://lookaside.example/x",
            mime_type="image/png",
            sha256=None,
            file_size=3,
        )

    async def download_media(self, url: str) -> bytes:
        self.calls.append("download")
        return b"png"


class _Sink:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_media(
        self, tenant_id: UUID, object_key: str, fileobj: IO[bytes], content_type: str
    ) -> None:
        self.objects[require_tenant_prefix(tenant_id, object_key)] = fileobj.read()


class _Linker:
    def link(self, *, tenant_id: UUID, object_key: str, content_type: str) -> str:
        return f"https://public.example/public/media/{object_key.rsplit('/', 1)[-1]}"


async def test_the_capturing_locator_end_to_end_over_postgres(seeded: dict[str, UUID]) -> None:
    conn = seeded["connection"]
    _, message_id = _inbound(
        TENANT, conn, media_type="image", media_id="6677", media_mime="image/png"
    )
    client, sink = _Client(), _Sink()

    async def clients(*, tenant_id: UUID, connection_id: UUID) -> _Client:
        assert (tenant_id, connection_id) == (TENANT, conn)
        return client

    locator = CapturingMediaLocator(PostgresMediaRecordRepository(), sink, clients, _Linker())
    first = await locator.locate(tenant_id=TENANT, message_id=message_id)
    second = await locator.locate(tenant_id=TENANT, message_id=message_id)

    key = f"t/{TENANT}/fp/whatsapp/{conn}/media/6677"
    assert first == second == "https://public.example/public/media/6677"
    assert client.calls == ["media_url", "download"]
    assert sink.objects == {key: b"png"}
    with tenant_session(TENANT) as session:
        stored = session.execute(
            text("SELECT media_object_key FROM messages WHERE id = :id"), {"id": message_id}
        ).scalar_one()
    assert stored == key

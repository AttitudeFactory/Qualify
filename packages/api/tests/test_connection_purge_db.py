"""Erasure's real boundary: forced RLS, FK graph, consent fence and retry manifest."""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.connection_purge import connection_purge_session
from qualify_shared.db.session import tenant_session
from qualify_shared.db.webhook import webhook_worker_session
from qualify_shared.objects.gate import ObjectGate, StoredObject
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from qualify_api.connections import purge_cli
from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.connections.purge import (
    ConnectionPurgeInProgress,
    UnsupportedConnectionPlatform,
    cancel_disconnect_purge,
    connection_purge_status,
    purge_connection,
    request_connection_purge,
)
from qualify_api.connections.revoke import ConnectionNotFound
from qualify_api.planner.composition import PostgresConnectionGate
from qualify_api.planner.draft_post_reader import DraftPostReader
from qualify_api.planner.executor import EventExecutor, SettleOutcome
from qualify_api.planner.locks import MemoryExecutionLock
from qualify_api.planner.repository import PostgresPlannerRepository
from qualify_api.planner.rules import idempotency_key
from qualify_api.planner.service import PlannerService
from qualify_api.publishing.client import ContainerStatus
from qualify_api.publishing.composition import PostgresConnectionTargetReader
from qualify_api.publishing.repository import AlreadySettled, PostgresPublishAttemptRepository
from qualify_api.publishing.service import CEILING_EXCEEDED, PublishService
from qualify_api.tenancy.models import Brand, Tenant, User

pytestmark = pytest.mark.db


class FakeObjects:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}
        self.fail = False

    def put(self, key: str, stream: io.BytesIO, content_type: str) -> None:
        self.data[key] = stream.read()

    def list_prefix(self, prefix: str) -> list[StoredObject]:
        return [
            StoredObject(key, len(value))
            for key, value in self.data.items()
            if key.startswith(prefix)
        ]

    def delete_keys(self, keys: list[str]) -> None:
        if self.fail:
            raise RuntimeError("fake store unavailable")
        for key in keys:
            self.data.pop(key, None)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> tuple[UUID, UUID, UUID, FakeObjects]:
    tenant, other = uuid4(), uuid4()
    with admin_session() as session:
        for tid in (tenant, other):
            session.add(
                Tenant(
                    id=tid,
                    name="purge test",
                    country="CO",
                    timezone="America/Bogota",
                    currency="COP",
                )
            )
        session.flush()
        user = User(tenant_id=tenant, email=f"{uuid4()}@purge.test", display_name="test")
        app = PlatformApp(app_id=f"purge-{uuid4()}", secret_ref="test", api_version="v21.0")
        session.add_all((user, app))
        session.flush()
        uid, aid = user.id, app.id
    with tenant_session(tenant) as session:
        row = SocialConnection(
            tenant_id=tenant,
            platform_app_id=aid,
            platform="instagram",
            account_type="business",
            external_account_id=f"ig-{uuid4()}",
            external_username="erase_me",
            linked_page_id="page-test",
            granted_scopes=["basic"],
            status="active",
            access_posture="development",
            current_credential_version=1,
            connected_by_user_id=uid,
        )
        session.add(row)
        session.flush()
        cid = row.id
        session.execute(
            text("""INSERT INTO oauth_credentials
            (connection_id,tenant_id,version,token_type,ciphertext,key_id,issued_at)
            VALUES (:cid,:tid,1,'page',:ciphertext,'fake',now())"""),
            {"cid": cid, "tid": tenant, "ciphertext": b"fake-encrypted-test-token"},
        )
    # Raw intake ownership has its own DB suite. This fixture isolates relational/R2
    # retries without invoking any platform or live object store.
    monkeypatch.setattr("qualify_api.connections.purge._purge_webhooks", lambda *args: None)
    return tenant, other, cid, FakeObjects()


def _count(tenant: UUID, cid: UUID, table: str) -> int:
    with connection_purge_session(tenant) as session:
        return session.scalar(
            text(f"SELECT count(*) FROM {table} WHERE connection_id=:cid"), {"cid": cid}
        )


def test_manual_purge_manifest_survives_r2_failure_and_retries_without_credentials(world) -> None:
    tenant, other, cid, store = world
    key = f"t/{tenant}/inbox/thumbs/{cid}/media-1"
    orphan = f"t/{tenant}/media/{cid}/dm-unsaved"
    foreign = f"t/{other}/inbox/thumbs/{cid}/unrelated"
    store.data.update({key: b"picture", orphan: b"upload", foreign: b"keep"})
    with tenant_session(tenant) as session:
        session.execute(
            text("""INSERT INTO monitored_media
            (tenant_id,connection_id,external_media_id,is_monitored,thumbnail_key,
             thumbnail_content_type,thumbnail_source,thumbnail_stored_at)
            VALUES (:tid,:cid,'media-1',true,:key,'image/jpeg','meta_thumbnail_url',now())"""),
            {"tid": tenant, "cid": cid, "key": key},
        )
    first = request_connection_purge(tenant_id=tenant, connection_id=cid)
    second = request_connection_purge(tenant_id=tenant, connection_id=cid)
    assert first.request_id == second.request_id and first.deadline_at == second.deadline_at
    store.fail = True
    with pytest.raises(RuntimeError, match="fake store"):
        purge_connection(tenant_id=tenant, connection_id=cid, objects=ObjectGate(store))
    assert _count(tenant, cid, "oauth_credentials") == 0
    assert _count(tenant, cid, "monitored_media") == 0
    failed = connection_purge_status(tenant_id=tenant, connection_id=cid)
    assert failed.status == "running" and failed.last_error_code == "RuntimeError"
    with tenant_session(tenant) as session:
        manifest = session.scalar(
            text("""SELECT object_keys FROM connection_purge_requests
            WHERE connection_id=:cid"""),
            {"cid": cid},
        )
    assert set(manifest) == {key, orphan}
    store.fail = False
    done = purge_connection(tenant_id=tenant, connection_id=cid, objects=ObjectGate(store))
    assert done.status == "completed" and store.data == {foreign: b"keep"}
    with tenant_session(tenant) as session:
        row = session.get(SocialConnection, cid)
        assert row.external_account_id == f"purged:{cid}"
        assert row.external_username is None and row.granted_scopes == [] and row.purged_at
        audit = session.execute(
            text("""SELECT object_keys,counts FROM connection_purge_requests
            WHERE connection_id=:cid"""),
            {"cid": cid},
        ).one()
        assert audit.object_keys == [] and audit.counts["oauth_credentials"] == 1
    assert (
        purge_connection(tenant_id=tenant, connection_id=cid, objects=ObjectGate(store)).status
        == "completed"
    )


def test_tenant_cannot_request_read_or_execute_another_tenants_purge(world) -> None:
    tenant, other, cid, store = world
    with pytest.raises(ConnectionNotFound):
        request_connection_purge(tenant_id=other, connection_id=cid)
    request_connection_purge(tenant_id=tenant, connection_id=cid)
    assert connection_purge_status(tenant_id=other, connection_id=cid) is None
    with pytest.raises(ConnectionNotFound):
        purge_connection(tenant_id=other, connection_id=cid, objects=ObjectGate(store))
    assert _count(tenant, cid, "oauth_credentials") == 1


def test_deletion_worker_has_no_credential_read_and_request_role_has_no_credential_delete(
    world,
) -> None:
    tenant, _, cid, _ = world
    with (
        pytest.raises(DBAPIError, match="permission denied"),
        connection_purge_session(tenant) as s,
    ):
        s.execute(
            text("SELECT ciphertext FROM oauth_credentials WHERE connection_id=:cid"), {"cid": cid}
        )
    with pytest.raises(DBAPIError, match="permission denied"), tenant_session(tenant) as s:
        s.execute(text("DELETE FROM oauth_credentials WHERE connection_id=:cid"), {"cid": cid})
    with connection_purge_session(tenant) as s:
        assert (
            s.scalar(text("SELECT rolbypassrls FROM pg_roles WHERE rolname=current_user")) is False
        )
    with webhook_worker_session() as s:
        assert (
            s.scalar(
                text("""SELECT has_column_privilege(
            current_user,'public.social_connections','purge_started_at','SELECT')""")
            )
            is False
        )
        assert (
            s.scalar(
                text("""SELECT has_function_privilege(
            current_user,'public.connection_purge_write_fence()','EXECUTE')""")
            )
            is False
        )


def test_disconnect_preserves_data_until_due_and_reconnect_cancels_only_automatic(world) -> None:
    tenant, _, cid, store = world
    now = datetime.now(UTC)
    queued = request_connection_purge(
        tenant_id=tenant, connection_id=cid, reason="disconnect", now=now
    )
    assert queued.due_at == now + timedelta(days=29)
    assert queued.deadline_at == now + timedelta(days=30)
    assert (
        purge_connection(
            tenant_id=tenant, connection_id=cid, objects=ObjectGate(store), now=now
        ).status
        == "scheduled"
    )
    assert _count(tenant, cid, "oauth_credentials") == 1
    with tenant_session(tenant) as session:
        row = session.get(SocialConnection, cid, with_for_update=True)
        cancel_disconnect_purge(session, row)
        row.current_credential_version += 1
        row.status = "active"
    assert connection_purge_status(tenant_id=tenant, connection_id=cid).status == "cancelled"
    request_connection_purge(tenant_id=tenant, connection_id=cid, reason="manual")
    with pytest.raises(ConnectionPurgeInProgress), tenant_session(tenant) as session:
        cancel_disconnect_purge(session, session.get(SocialConnection, cid))


def test_purge_fence_rejects_late_ingestion_and_uploads(world) -> None:
    tenant, _, cid, store = world
    request_connection_purge(tenant_id=tenant, connection_id=cid)
    purge_connection(tenant_id=tenant, connection_id=cid, objects=ObjectGate(store))
    with pytest.raises(DBAPIError, match="connection deletion has started"):
        with tenant_session(tenant) as session:
            session.execute(
                text("""INSERT INTO monitored_media
                (tenant_id,connection_id,external_media_id,is_monitored)
                VALUES (:tid,:cid,'late',true)"""),
                {"tid": tenant, "cid": cid},
            )
    with pytest.raises(ValueError, match="connection_deletion"):
        ObjectGate(store).put_connection_media(
            tenant, cid, f"t/{tenant}/media/{cid}/late", io.BytesIO(b"late"), "image/jpeg"
        )
    assert not store.data


def test_whatsapp_is_explicitly_pending_and_does_not_queue_or_revoke(world) -> None:
    tenant, _, cid, _ = world
    with tenant_session(tenant) as session:
        row = session.get(SocialConnection, cid)
        row.platform = "whatsapp"
        row.linked_page_id = None
    with pytest.raises(UnsupportedConnectionPlatform):
        request_connection_purge(tenant_id=tenant, connection_id=cid)
    assert connection_purge_status(tenant_id=tenant, connection_id=cid) is None
    with tenant_session(tenant) as session:
        assert session.get(SocialConnection, cid).status == "active"


def test_complete_worker_integrates_real_webhook_cleanup_with_fake_objects(
    world, monkeypatch
) -> None:
    tenant, _, cid, store = world
    monkeypatch.undo()
    request_connection_purge(tenant_id=tenant, connection_id=cid)
    assert (
        purge_connection(tenant_id=tenant, connection_id=cid, objects=ObjectGate(store)).status
        == "completed"
    )
    with tenant_session(tenant) as session:
        assert (
            session.scalar(
                text("""SELECT webhook_deleted FROM connection_purge_requests
            WHERE connection_id=:cid"""),
                {"cid": cid},
            )
            is True
        )


def test_delete_nested_synced_graph_scrub_terminal_raw_keep_published_asset(world) -> None:
    tenant, _, cid, store = world
    thread, message, mention, draft, schedule, attempt = (uuid4() for _ in range(6))
    published_key = f"t/{tenant}/media/{cid}/owned-publication"
    raw_key = f"t/{tenant}/fp/instagram/{cid}/publish-response"
    store.data.update({published_key: b"owned-brand-picture", raw_key: b"personal-raw"})
    with tenant_session(tenant) as session:
        connection = session.get(SocialConnection, cid)
        params = {
            "tid": tenant,
            "cid": cid,
            "thread": thread,
            "message": message,
            "mention": mention,
            "draft": draft,
            "schedule": schedule,
            "attempt": attempt,
            "uid": connection.connected_by_user_id,
            "published": published_key,
            "raw": raw_key,
        }
        statements = (
            """INSERT INTO threads (id,tenant_id,connection_id,channel,external_thread_id,status,
                    counterpart_name,counterpart_username)
                VALUES (:thread,:tid,:cid,'dm','person','open','Private person','private')""",
            """INSERT INTO messages (id,tenant_id,connection_id,thread_id,external_message_id,
                    direction,author_username,text,shape_version)
                VALUES (:message,:tid,:cid,:thread,'message-1','inbound',
                    'private','Private text','v1')""",
            """INSERT INTO conversation_drafts (id,tenant_id,thread_id,message_id,generator_version,
                    generated_text,gate_reason)
                VALUES (:draft,:tid,:thread,:message,'v1','Private','ok')""",
            """INSERT INTO conversation_outbox (tenant_id,connection_id,thread_id,channel,payload,
                    approved_by_user_id,approved_at,draft_id)
                VALUES (:tid,:cid,:thread,'dm','{}'::jsonb,:uid,now(),:draft)""",
            """INSERT INTO mentions (id,tenant_id,connection_id,external_account_id,media_id,text)
                VALUES (:mention,:tid,:cid,'private-account','mention-media','Private mention')""",
            """INSERT INTO mention_sentiment_results (tenant_id,mention_id,detector_version,
                    pipeline_version,model_id,label,score)
                VALUES (:tid,:mention,'v1','v1','fake','NEU',0.9)""",
            """INSERT INTO mention_sentiment_failures (tenant_id,mention_id,detector_version,
                    pipeline_version,model_id,error_class)
                VALUES (:tid,:mention,'v1','v1','fake','FakeFailure')""",
            """INSERT INTO scheduled_posts (id,tenant_id,connection_id,media_object_key,
                    media_content_type,media_product_type,scheduled_for,scheduled_tz,status,
                    created_by_user_id)
                VALUES (:schedule,:tid,:cid,:published,'image/jpeg','STORIES',
                    now(),'America/Bogota','published',:uid)""",
            """INSERT INTO publish_attempts (id,tenant_id,connection_id,scheduled_post_id,
                    idempotency_key,media_product_type,adapter_version,status,settled_at,
                    raw_response_r2_key,published_media_id)
                VALUES (:attempt,:tid,:cid,:schedule,'one','STORIES','fake','published',now(),
                    :raw,'externally-published-id')""",
            """INSERT INTO monitored_media (tenant_id,connection_id,external_media_id,is_monitored,
                    thumbnail_key,thumbnail_content_type,thumbnail_source,thumbnail_stored_at)
                VALUES (:tid,:cid,'published-media',true,:published,
                    'image/jpeg','published_asset',now())""",
        )
        for statement in statements:
            session.execute(text(statement), params)
    with pytest.raises(DBAPIError, match="already settled"), tenant_session(tenant) as session:
        session.execute(
            text("UPDATE publish_attempts SET caption='changed' WHERE id=:id"), {"id": attempt}
        )

    request_connection_purge(tenant_id=tenant, connection_id=cid)
    assert (
        purge_connection(tenant_id=tenant, connection_id=cid, objects=ObjectGate(store)).status
        == "completed"
    )
    assert store.data == {published_key: b"owned-brand-picture"}
    with tenant_session(tenant) as session:
        for table in (
            "messages",
            "threads",
            "mentions",
            "conversation_drafts",
            "conversation_outbox",
            "mention_sentiment_results",
            "mention_sentiment_failures",
        ):
            assert (
                session.scalar(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id=:tid"), {"tid": tenant}
                )
                == 0
            )
        row = session.execute(
            text("""SELECT raw_response_r2_key,published_media_id
            FROM publish_attempts WHERE id=:id"""),
            {"id": attempt},
        ).one()
        assert (
            row.raw_response_r2_key is None and row.published_media_id == "externally-published-id"
        )
        assert (
            session.scalar(
                text("SELECT media_object_key FROM scheduled_posts WHERE id=:id"), {"id": schedule}
            )
            == published_key
        )
    with (
        pytest.raises(DBAPIError, match="connection deletion has started"),
        tenant_session(tenant) as session,
    ):
        session.execute(
            text("UPDATE publish_attempts SET caption='changed' WHERE id=:id"), {"id": attempt}
        )


def test_retained_calendar_can_cancel_delete_and_settle_but_not_retarget_after_purge(world) -> None:
    tenant, _, cid, store = world
    brand, cancel_event, settle_event, frozen_event = (uuid4() for _ in range(4))
    own_attempt, other_attempt = uuid4(), uuid4()
    with admin_session() as session:
        session.add(Brand(id=brand, tenant_id=tenant, name="Preserved authored brand"))
    with tenant_session(tenant) as session:
        source = session.get(SocialConnection, cid)
        other_connection = SocialConnection(
            tenant_id=tenant,
            platform_app_id=source.platform_app_id,
            platform="instagram",
            account_type="business",
            external_account_id=f"other-{uuid4()}",
            linked_page_id="page-other",
            granted_scopes=[],
            status="active",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=source.connected_by_user_id,
        )
        session.add(other_connection)
        session.flush()
        other_cid = other_connection.id
        for event_id, status in (
            (cancel_event, "scheduled"),
            (settle_event, "publishing"),
            (frozen_event, "scheduled"),
        ):
            session.execute(
                text("""INSERT INTO calendar_events
                (id,tenant_id,brand_id,post_id,connection_id,scheduled_at,scheduled_tz,status,
                 created_by_user_id)
                VALUES (:id,:tid,:brand,:post,:cid,now(),'UTC',:status,:uid)"""),
                {
                    "id": event_id,
                    "tid": tenant,
                    "brand": brand,
                    "post": uuid4(),
                    "cid": cid,
                    "status": status,
                    "uid": source.connected_by_user_id,
                },
            )
        for aid, connection_id in ((own_attempt, cid), (other_attempt, other_cid)):
            session.execute(
                text("""INSERT INTO publish_attempts
                (id,tenant_id,connection_id,idempotency_key,media_product_type,adapter_version,status)
                VALUES (:id,:tid,:cid,:key,'REELS','fake','processing')"""),
                {"id": aid, "tid": tenant, "cid": connection_id, "key": str(uuid4())},
            )
        session.execute(
            text("UPDATE calendar_events SET publish_attempt_id=:aid WHERE id=:id"),
            {"aid": own_attempt, "id": cancel_event},
        )
    request_connection_purge(tenant_id=tenant, connection_id=cid)
    assert (
        purge_connection(tenant_id=tenant, connection_id=cid, objects=ObjectGate(store)).status
        == "completed"
    )
    repository = PostgresPlannerRepository()
    planner = PlannerService(
        repository=repository, posts=DraftPostReader(), connections=PostgresConnectionGate()
    )
    planner.cancel_and_delete(tenant_id=tenant, event_id=cancel_event)
    assert repository.get(tenant_id=tenant, event_id=cancel_event) is None
    with tenant_session(tenant) as session:
        assert (
            session.scalar(
                text("SELECT count(*) FROM publish_attempts WHERE id=:id"), {"id": own_attempt}
            )
            == 1
        )
    with pytest.raises(DBAPIError, match="connection deletion has started"):
        repository.link_attempt(
            tenant_id=tenant, event_id=settle_event, expected_revision=1, attempt_id=other_attempt
        )
    assert (
        repository.link_attempt(
            tenant_id=tenant, event_id=settle_event, expected_revision=1, attempt_id=own_attempt
        )
        is not None
    )
    settled = repository.settle_from_attempt(
        tenant_id=tenant,
        event_id=settle_event,
        expected_revision=1,
        attempt_id=own_attempt,
        published=True,
    )
    assert settled is not None and settled.status == "published"
    for assignment, extra in (
        ("scheduled_at=scheduled_at+interval '1 day'", {}),
        ("revision=revision+1", {}),
        ("post_id=:post", {"post": uuid4()}),
        ("connection_id=:other", {"other": other_cid}),
        ("status='publishing'", {}),
    ):
        with pytest.raises(DBAPIError, match="connection deletion has started"):
            with tenant_session(tenant) as session:
                session.execute(
                    text(f"UPDATE calendar_events SET {assignment} WHERE id=:id"),
                    {"id": frozen_event, **extra},
                )
    with pytest.raises(DBAPIError, match="connection deletion has started"):
        with tenant_session(tenant) as session:
            session.execute(
                text("""INSERT INTO calendar_events
                (id,tenant_id,brand_id,post_id,connection_id,scheduled_at,scheduled_tz,status,
                 created_by_user_id)
                SELECT :new_id,tenant_id,brand_id,post_id,connection_id,scheduled_at,scheduled_tz,
                    status,created_by_user_id FROM calendar_events WHERE id=:old_id"""),
                {"new_id": uuid4(), "old_id": frozen_event},
            )


def test_execute_cli_filters_due_jobs_before_limit_and_dry_run_keeps_future_jobs(
    world, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tenant, _, cid, _ = world
    now = datetime.now(UTC)
    with tenant_session(tenant) as session:
        source = session.get(SocialConnection, cid)
        future_ids = []
        for _ in range(2):
            row = SocialConnection(
                tenant_id=tenant,
                platform_app_id=source.platform_app_id,
                platform="instagram",
                account_type="business",
                external_account_id=str(uuid4()),
                linked_page_id="page-future",
                granted_scopes=[],
                status="active",
                access_posture="development",
                current_credential_version=0,
                connected_by_user_id=source.connected_by_user_id,
            )
            session.add(row)
            session.flush()
            future_ids.append(row.id)
    for future_id in future_ids:
        request_connection_purge(
            tenant_id=tenant,
            connection_id=future_id,
            reason="disconnect",
            now=now - timedelta(days=1),
        )
    request_connection_purge(tenant_id=tenant, connection_id=cid, reason="manual", now=now)
    executed: list[UUID] = []

    def execute(**kwargs: object) -> SimpleNamespace:
        executed.append(kwargs["connection_id"])
        return SimpleNamespace(status="completed")

    monkeypatch.setattr(purge_cli, "purge_connection", execute)
    assert purge_cli.main(["--tenant", str(tenant), "--execute", "--limit", "1"]) == 0
    assert executed == [cid]
    with connection_purge_session(tenant) as session:
        session.execute(
            text("UPDATE connection_purge_requests SET status='running' WHERE connection_id=:cid"),
            {"cid": cid},
        )
    assert purge_cli.main(["--tenant", str(tenant), "--execute", "--limit", "1"]) == 0
    assert executed == [cid, cid]
    capsys.readouterr()
    assert purge_cli.main(["--tenant", str(tenant), "--limit", "1"]) == 0
    preview = capsys.readouterr().out
    assert "dry_run" in preview and any(str(future_id) in preview for future_id in future_ids)


@pytest.mark.parametrize("late_success", [True, False], ids=["late_success", "local_ceiling"])
async def test_publish_service_can_record_preexisting_attempt_outcome_after_purge_and_settle_event(
    world, late_success: bool
) -> None:
    tenant, _, cid, store = world
    brand, event_id, attempt_id = uuid4(), uuid4(), uuid4()
    with admin_session() as session:
        session.add(Brand(id=brand, tenant_id=tenant, name="Authored publication history"))
    with tenant_session(tenant) as session:
        connection = session.get(SocialConnection, cid)
        session.execute(
            text("""INSERT INTO publish_attempts
            (id,tenant_id,connection_id,idempotency_key,media_product_type,adapter_version,
             status,creation_id,started_at)
            VALUES (:aid,:tid,:cid,:key,'REELS','fake','processing',:creation,
                now()-interval '1 hour')"""),
            {
                "aid": attempt_id,
                "tid": tenant,
                "cid": cid,
                "key": idempotency_key(event_id, 1),
                "creation": "container-before-purge" if late_success else None,
            },
        )
        session.execute(
            text("""INSERT INTO calendar_events
            (id,tenant_id,brand_id,post_id,connection_id,scheduled_at,scheduled_tz,status,
             publish_attempt_id,created_by_user_id)
            VALUES (:id,:tid,:brand,:post,:cid,now(),'UTC','publishing',:aid,:uid)"""),
            {
                "id": event_id,
                "tid": tenant,
                "brand": brand,
                "post": uuid4(),
                "cid": cid,
                "aid": attempt_id,
                "uid": connection.connected_by_user_id,
            },
        )
    calls: list[str] = []

    def erase() -> None:
        request_connection_purge(tenant_id=tenant, connection_id=cid)
        assert (
            purge_connection(tenant_id=tenant, connection_id=cid, objects=ObjectGate(store)).status
            == "completed"
        )

    class Client:
        async def container_status(self, *, container_id: str) -> ContainerStatus:
            calls.append("status")
            return ContainerStatus.FINISHED

        async def publish_container(self, *, ig_user_id: str, creation_id: str) -> str:
            calls.append("publish")
            # The already-admitted send returns after the manual purge commits.
            erase()
            return "known-owned-publication"

    class Factory:
        async def client_for(self, *, tenant_id: UUID, connection_id: UUID) -> Client:
            calls.append("client")
            assert late_success, "local ceiling settlement must not construct a client"
            return Client()

    attempts = PostgresPublishAttemptRepository()
    planner = PostgresPlannerRepository()
    publisher = PublishService(
        repository=attempts,
        gate=ObjectGate(store),
        connections=PostgresConnectionTargetReader(),
        client_factory=Factory(),
    )
    if not late_success:
        erase()
    state = await publisher.advance(tenant_id=tenant, attempt_id=attempt_id)
    assert state.settled and state.status == ("published" if late_success else "failed")
    assert calls == (["client", "status", "publish"] if late_success else [])
    attempt = attempts.get_attempt(tenant_id=tenant, attempt_id=attempt_id)
    assert attempt.published_media_id == ("known-owned-publication" if late_success else None)
    assert attempt.platform_error_code == (None if late_success else CEILING_EXCEEDED)
    executor = EventExecutor(
        repository=planner,
        posts=DraftPostReader(),
        publisher=publisher,
        attempts=attempts,
        lock=MemoryExecutionLock(),
    )
    event = planner.get(tenant_id=tenant, event_id=event_id)
    result = executor.settle_event(event)
    assert result.outcome is (
        SettleOutcome.SETTLED_PUBLISHED if late_success else SettleOutcome.SETTLED_FAILED
    )
    assert planner.get(tenant_id=tenant, event_id=event_id).status == attempt.status
    assert executor.settle_event(event).outcome is SettleOutcome.ALREADY_SETTLED
    # Settle-once remains a typed idempotent rejection, not a terminal overwrite.
    with pytest.raises(AlreadySettled):
        attempts.settle(tenant_id=tenant, attempt_id=attempt_id, status="failed")
    for assignment, params in (
        ("status='processing'", {}),
        ("caption='late captured content'", {}),
        ("creation_id='late-container'", {}),
        ("adapter_version='new-provenance'", {}),
        ("idempotency_key='new-operation'", {}),
        ("connection_id=:connection", {"connection": uuid4()}),
        ("raw_response_r2_key=:raw", {"raw": f"t/{tenant}/fp/instagram/{cid}/late"}),
    ):
        with pytest.raises(DBAPIError, match="connection deletion has started"):
            with tenant_session(tenant) as session:
                session.execute(
                    text(f"UPDATE publish_attempts SET {assignment} WHERE id=:id"),
                    {"id": attempt_id, **params},
                )
    with pytest.raises(DBAPIError, match="connection deletion has started"):
        with tenant_session(tenant) as session:
            session.execute(
                text("""INSERT INTO publish_attempts
                (tenant_id,connection_id,idempotency_key,media_product_type,adapter_version,status)
                VALUES (:tid,:cid,:key,'REELS','fake','pending')"""),
                {"tid": tenant, "cid": cid, "key": str(uuid4())},
            )

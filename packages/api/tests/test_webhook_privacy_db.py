"""Real-role consent admission, ownership fences and legacy deletion deadline."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.connection_purge import connection_purge_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.connections.purge import request_connection_purge
from qualify_api.tenancy.models import Tenant, User
from qualify_api.webhooks.purge import purge_connection_webhooks
from qualify_api.webhooks.receiver import record_delivery
from qualify_api.webhooks.repository import WebhookQueue

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def owner() -> Iterator[Engine]:
    engine = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    yield engine
    engine.dispose()


def _connection(subject: str | None = None, page: str | None = None) -> tuple[UUID, UUID, str]:
    tid = uuid4()
    with admin_session() as session:
        session.add(Tenant(id=tid, name="privacy", country="CO", timezone="UTC", currency="COP"))
        session.flush()
        user = User(tenant_id=tid, email=f"{uuid4()}@privacy.test", display_name="test")
        app = PlatformApp(app_id=str(uuid4()), secret_ref="fake", api_version="v21.0")
        session.add_all((user, app))
        session.flush()
        uid, aid = user.id, app.id
    subject = subject or f"ig-{uuid4()}"
    with tenant_session(tid) as session:
        connection = SocialConnection(
            tenant_id=tid,
            platform_app_id=aid,
            platform="instagram",
            account_type="business",
            external_account_id=subject,
            linked_page_id=page or f"page-{uuid4()}",
            granted_scopes=["basic"],
            status="active",
            access_posture="development",
            current_credential_version=1,
            connected_by_user_id=uid,
        )
        session.add(connection)
        session.flush()
        cid = connection.id
    return tid, cid, subject


def _body(*subjects: str, object_: str = "instagram", extra: bool = False) -> bytes:
    payload = {
        "object": object_,
        "entry": [
            {
                "id": subject,
                "time": 1,
                "changes": [{"field": "mentions", "value": {"media_id": f"media-{subject}"}}],
            }
            for subject in subjects
        ],
    }
    if extra:
        payload["private_extension"] = "must disappear"
        payload["entry"][0]["private_extension"] = "must disappear"
    return json.dumps(payload).encode()


def _prepare(tid: UUID, cid: UUID, now: datetime) -> None:
    request_connection_purge(tenant_id=tid, connection_id=cid, now=now)
    with connection_purge_session(tid) as session:
        session.execute(
            text("UPDATE social_connections SET purge_started_at=:now WHERE id=:cid"),
            {"now": now, "cid": cid},
        )
        session.execute(
            text("UPDATE connection_purge_requests SET status='running' WHERE connection_id=:cid"),
            {"cid": cid},
        )


def test_mixed_intake_admits_only_consent_and_stores_no_original_signature(owner) -> None:
    tid, cid, subject = _connection()
    unknown = f"unknown-{uuid4()}"
    result = record_delivery(
        body=_body(subject, unknown, extra=True), signature_header="secret-sign"
    )
    with owner.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM meta_webhook_deliveries WHERE id=:id"), {"id": result.delivery_id}
        ).one()
        assert unknown.encode() not in bytes(row.raw_body)
        assert b"private_extension" not in bytes(row.raw_body)
        assert row.signature_header == "" and row.raw_redacted and row.signature_verified
        assert row.entry_ids == [subject] and result.changes_new == 1
        owners = conn.execute(
            text(
                "SELECT tenant_id,connection_id FROM meta_webhook_event_owners "
                "WHERE event_id IN (SELECT id FROM meta_webhook_events "
                "WHERE delivery_id=:id)"
            ),
            {"id": result.delivery_id},
        ).all()
        assert owners == [(tid, cid)]
    duplicate = record_delivery(body=_body(subject, unknown, extra=True), signature_header="secret")
    assert duplicate.duplicate_delivery and duplicate.delivery_id == result.delivery_id


def test_page_ownership_snapshots_all_tenants_and_forces_rls(owner) -> None:
    page = f"shared-page-{uuid4()}"
    a, ca, _ = _connection(page=page)
    b, cb, _ = _connection(page=page)
    result = record_delivery(body=_body(page, object_="page"), signature_header="verified")
    for tid, cid in ((a, ca), (b, cb)):
        with tenant_session(tid) as session:
            rows = session.execute(
                text(
                    "SELECT tenant_id,connection_id "
                    "FROM meta_webhook_delivery_owners WHERE delivery_id=:did"
                ),
                {"did": result.delivery_id},
            ).all()
            assert rows == [(tid, cid)]
    with owner.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM meta_webhook_delivery_owners WHERE delivery_id=:did"),
                {"did": result.delivery_id},
            ).scalar()
            == 2
        )
    now = datetime.now(UTC)
    _prepare(a, ca, now)
    assert purge_connection_webhooks(tenant_id=a, connection_id=ca, now=now)
    with owner.connect() as conn:
        event = conn.execute(
            text("SELECT id FROM meta_webhook_events WHERE entry_id=:page"), {"page": page}
        ).one()
        assert conn.execute(
            text("SELECT meta_webhook_frozen_owners(:eid)"), {"eid": event.id}
        ).scalar() == [{"tenant_id": str(b), "connection_id": str(cb)}]


def test_a_deletion_erases_shared_raw_without_deleting_other_account_event(owner) -> None:
    a, ca, sa = _connection()
    _, _, sb = _connection()
    result = record_delivery(body=_body(sa, sb), signature_header="verified")
    now = datetime.now(UTC)
    _prepare(a, ca, now)
    purge_connection_webhooks(tenant_id=a, connection_id=ca, now=now)
    with owner.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM meta_webhook_deliveries WHERE id=:id"),
                {"id": result.delivery_id},
            ).scalar()
            == 0
        )
        assert (
            conn.execute(
                text("SELECT count(*) FROM meta_webhook_events WHERE entry_id=:s"), {"s": sa}
            ).scalar()
            == 0
        )
        event = conn.execute(
            text("SELECT delivery_id FROM meta_webhook_events WHERE entry_id=:s"), {"s": sb}
        ).one()
        assert event.delivery_id is None


def test_identical_payload_in_b_new_consent_epoch_survives_a_purge(owner) -> None:
    a, ca, subject = _connection()
    body = _body(subject)
    first = record_delivery(body=body, signature_header="verified")
    now = datetime.now(UTC)
    _prepare(a, ca, now)
    b, cb, _ = _connection(subject)
    second = record_delivery(body=body, signature_header="verified")
    assert not second.duplicate_delivery and second.changes_new == 1
    assert first.delivery_id != second.delivery_id
    purge_connection_webhooks(tenant_id=a, connection_id=ca, now=now)
    with owner.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT d.id,o.tenant_id,o.connection_id "
                "FROM meta_webhook_deliveries d JOIN meta_webhook_delivery_owners o "
                "ON o.delivery_id=d.id WHERE d.entry_ids @> ARRAY[:s]"
            ),
            {"s": subject},
        ).all()
        assert rows == [(second.delivery_id, b, cb)]
        old_owners = conn.execute(
            text("SELECT meta_webhook_frozen_owners(:eid)"), {"eid": uuid4()}
        ).scalar()
        assert old_owners == []
    claimed = WebhookQueue().claim(
        worker_id=f"privacy-{uuid4()}", now=now + timedelta(seconds=2), limit=10000
    )
    events = [event for event in claimed if event.entry_id == subject]
    assert len(events) == 1 and events[0].owners == ((b, cb),)


def test_legacy_processing_waits_until_original_29_day_expiry(owner) -> None:
    tid, cid, subject = _connection()
    now = datetime.now(UTC)
    eid, did = uuid4(), uuid4()
    with owner.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO meta_webhook_deliveries "
                "(id,received_at,raw_body,body_sha256,body_bytes,signature_header,object,"
                "parse_status,entry_ids,privacy_legacy) "
                "VALUES (:did,:now,:body,:hash,2,'old','instagram','parsed',ARRAY[:subject],true)"
            ),
            {"did": did, "now": now, "body": b"{}", "hash": str(did), "subject": subject},
        )
        conn.execute(
            text(
                "INSERT INTO meta_webhook_events "
                "(id,delivery_id,received_at,change_index,object,entry_id,field,value,"
                "dedup_key,status,privacy_legacy) "
                "VALUES (:eid,:did,:now,0,'instagram',:subject,'mentions','{}',:hash,"
                "'processing',true)"
            ),
            {"eid": eid, "did": did, "now": now, "subject": subject, "hash": str(eid)},
        )
    _prepare(tid, cid, now)
    assert not purge_connection_webhooks(tenant_id=tid, connection_id=cid, now=now)
    # A newly consented B must not become the owner of pre-snapshot legacy data.
    _connection(subject)
    with owner.connect() as conn:
        assert (
            conn.execute(text("SELECT meta_webhook_frozen_owners(:eid)"), {"eid": eid}).scalar()
            == []
        )
    assert not purge_connection_webhooks(
        tenant_id=tid, connection_id=cid, now=now + timedelta(days=29) - timedelta(microseconds=1)
    )
    # Queue replay changes status, never the original expiry clock.
    with owner.begin() as conn:
        conn.execute(
            text(
                "UPDATE meta_webhook_events SET status='pending',next_attempt_at=:now WHERE id=:id"
            ),
            {"now": now + timedelta(days=29), "id": eid},
        )
    assert purge_connection_webhooks(tenant_id=tid, connection_id=cid, now=now + timedelta(days=29))
    with owner.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM meta_webhook_events WHERE id=:id"), {"id": eid}
            ).scalar()
            == 0
        )
        assert (
            conn.execute(
                text("SELECT count(*) FROM meta_webhook_deliveries WHERE id=:id"), {"id": did}
            ).scalar()
            == 0
        )


def test_scoped_purge_refuses_other_tenant(owner) -> None:
    tid, cid, _ = _connection()
    other, _, _ = _connection()
    now = datetime.now(UTC)
    _prepare(tid, cid, now)
    with pytest.raises(DBAPIError):
        purge_connection_webhooks(tenant_id=other, connection_id=cid, now=now)


def test_admission_waits_for_deletion_lock_then_discards_revoked_subject(owner) -> None:
    tid, cid, subject = _connection()
    started, finished = threading.Event(), threading.Event()
    results, errors = [], []

    def receive() -> None:
        started.set()
        try:
            results.append(record_delivery(body=_body(subject), signature_header="verified"))
        except Exception as exc:
            errors.append(exc)
        finally:
            finished.set()

    with connection_purge_session(tid) as session:
        session.execute(
            text("SELECT id FROM social_connections WHERE id=:id FOR UPDATE"), {"id": cid}
        )
        worker = threading.Thread(target=receive)
        worker.start()
        assert started.wait(5) and not finished.wait(0.2)
        session.execute(
            text(
                "UPDATE social_connections SET status='revoked',purge_started_at=now() WHERE id=:id"
            ),
            {"id": cid},
        )
    worker.join(10)
    assert not worker.is_alive() and errors == [] and results[0].changes_new == 0
    with owner.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM meta_webhook_events WHERE entry_id=:s"), {"s": subject}
            ).scalar()
            == 0
        )


def test_whatsapp_raw_remains_byte_exact(owner) -> None:
    body = _body(f"waba-{uuid4()}", object_="whatsapp_business_account", extra=True)
    result = record_delivery(body=body, signature_header="wa-signature")
    with owner.connect() as conn:
        row = conn.execute(
            text(
                "SELECT raw_body,signature_header,ownership_frozen "
                "FROM meta_webhook_deliveries WHERE id=:id"
            ),
            {"id": result.delivery_id},
        ).one()
        assert bytes(row.raw_body) == body and row.signature_header == "wa-signature"
        assert not row.ownership_frozen


def test_new_malformed_whatsapp_never_blocks_or_is_erased_by_instagram_purge(owner) -> None:
    tid, cid, _ = _connection()
    now = datetime.now(UTC)
    _prepare(tid, cid, now)
    body = json.dumps({"object": "whatsapp_business_account", "entry": str(uuid4())}).encode()
    result = record_delivery(body=body, signature_header="wa-original-signature")
    assert result.parse_status == "unparseable"
    assert purge_connection_webhooks(tenant_id=tid, connection_id=cid, now=now)
    with owner.connect() as conn:
        row = conn.execute(
            text(
                "SELECT raw_body,signature_header,privacy_legacy "
                "FROM meta_webhook_deliveries WHERE id=:id"
            ),
            {"id": result.delivery_id},
        ).one()
        assert bytes(row.raw_body) == body and row.signature_header == "wa-original-signature"
        assert not row.privacy_legacy


def test_public_functions_have_narrow_execute_grants_and_worker_cannot_read_raw(owner) -> None:
    with owner.connect() as conn:
        for role in ("qualify_app", "qualify_credential", "qualify_webhook_worker"):
            assert not conn.execute(
                text("SELECT has_function_privilege(:role,'admit_meta_webhook(jsonb)','EXECUTE')"),
                {"role": role},
            ).scalar()
        assert not conn.execute(
            text(
                "SELECT has_function_privilege('qualify_webhook',"
                "'purge_connection_meta_webhooks(uuid,timestamptz)','EXECUTE')"
            )
        ).scalar()
        assert not conn.execute(
            text(
                "SELECT has_column_privilege('qualify_webhook_worker',"
                "'meta_webhook_deliveries','raw_body','SELECT')"
            )
        ).scalar()

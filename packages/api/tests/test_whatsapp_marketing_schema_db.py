"""Migration 0060 (WA-18/19/20), checked as the REAL roles — same method as
`test_whatsapp_menus_schema_db.py`: one statement per check, always rolled back, writes with
`WHERE false` so the grant is exercised without a row. Then the structural facts (RLS,
uniques, the outbox → send mirror trigger) with real rows through the production doors.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from psycopg.errors import CheckViolation, InsufficientPrivilege, UniqueViolation
from qualify_shared.db.admin import admin_session
from qualify_shared.db.config import admin_dsn, app_dsn, credential_dsn, webhook_worker_dsn
from qualify_shared.db.session import tenant_session
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, IntegrityError

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.leads.models import Lead, LeadFormSettings
from qualify_api.tenancy.models import Tenant, User
from qualify_api.whatsapp.campaigns import (
    CampaignService,
    PostgresCampaignReceiptRepository,
    PostgresCampaignRepository,
)
from qualify_api.whatsapp.client import TemplateInfo
from qualify_api.whatsapp.models import (
    WhatsAppCampaign,
    WhatsAppCampaignSend,
    WhatsAppOptIn,
    WhatsAppOutboxItem,
    WhatsAppPhoneNumber,
    WhatsAppTemplate,
)
from qualify_api.whatsapp.optins import (
    AudienceFilter,
    OptInService,
    PostgresOptInRepository,
    PostgresOptOutRepository,
    RecordOutcome,
)
from qualify_api.whatsapp.outbox import PostgresOutboxRepository
from qualify_api.whatsapp.resolve import PhoneResolutionOutcome, resolve_waba
from qualify_api.whatsapp.templates import (
    PostgresTemplateRepository,
    PostgresTemplateWebhookRepository,
    TemplateAlreadyExists,
    TemplateRecord,
)

pytestmark = pytest.mark.db

TENANT = UUID("a0000000-0000-4000-8000-000000000e18")
OTHER_TENANT = UUID("a0000000-0000-4000-8000-000000000e19")

_ROLE_DSNS = {
    "app": app_dsn,
    "admin": admin_dsn,
    "worker": webhook_worker_dsn,
    "credential": credential_dsn,
}
_NEW_TABLES = (
    "whatsapp_templates",
    "whatsapp_opt_ins",
    "whatsapp_campaigns",
    "whatsapp_campaign_sends",
)
_TABLES_SQL = ", ".join(f"'{t}'" for t in _NEW_TABLES)

_WORKER_COLUMN_GRANTS = (
    {
        ("whatsapp_templates", "SELECT", c)
        for c in ("id", "tenant_id", "waba_id", "name", "language", "meta_template_id")
    }
    | {
        ("whatsapp_templates", "UPDATE", c)
        for c in ("status", "quality", "rejected_reason", "updated_at")
    }
    | {("whatsapp_opt_ins", "SELECT", c) for c in ("id", "tenant_id", "phone_e164", "revoked_at")}
    | {("whatsapp_opt_ins", "UPDATE", c) for c in ("revoked_at", "revoke_reason")}
    | {
        ("whatsapp_opt_ins", "INSERT", c)
        for c in (
            "tenant_id",
            "brand_id",
            "phone_e164",
            "source",
            "consent_text",
            "consent_policy_version",
            "proof",
            "captured_at",
        )
    }
    | {
        ("whatsapp_campaign_sends", "SELECT", c)
        for c in ("id", "tenant_id", "outbox_id", "wamid", "status")
    }
    | {
        ("whatsapp_campaign_sends", "UPDATE", c)
        for c in ("status", "error_code", "price_category", "updated_at")
    }
)


@pytest.fixture(scope="module")
def engines() -> Iterator[dict[str, Engine]]:
    built = {name: create_engine(dsn()) for name, dsn in _ROLE_DSNS.items()}
    built["owner"] = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    try:
        yield built
    finally:
        for engine in built.values():
            engine.dispose()


def _attempt(engine: Engine, sql: str) -> str:
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text(sql))
            return "ok"
        except DBAPIError as exc:
            if isinstance(exc.orig, InsufficientPrivilege):
                return "denied"
            raise
        finally:
            trans.rollback()


_INSERT_TEMPLATE = (
    "INSERT INTO whatsapp_templates (tenant_id, waba_id, name, language, category, status) "
    "SELECT gen_random_uuid(), 'w', 'n', 'es', 'marketing', 'PENDING' WHERE false"
)
_INSERT_OPT_IN = (
    "INSERT INTO whatsapp_opt_ins (tenant_id, brand_id, phone_e164, source, consent_text, "
    "consent_policy_version, proof, captured_at) "
    "SELECT gen_random_uuid(), NULL, '+573000000000', 'menu', 'si', NULL, NULL, now() WHERE false"
)
_INSERT_CAMPAIGN = (
    "INSERT INTO whatsapp_campaigns (tenant_id, connection_id, template_id, name, "
    "created_by_user_id) SELECT gen_random_uuid(), gen_random_uuid(), gen_random_uuid(), 'c', "
    "gen_random_uuid() WHERE false"
)
_INSERT_SEND = (
    "INSERT INTO whatsapp_campaign_sends (tenant_id, campaign_id, phone_e164) "
    "SELECT gen_random_uuid(), gen_random_uuid(), '+573000000000' WHERE false"
)


# --- qualify_app: S/I/U on the four, never DELETE -----------------------------------------


@pytest.mark.parametrize(
    "sql",
    [f"SELECT * FROM {t} LIMIT 1" for t in _NEW_TABLES]
    + [_INSERT_TEMPLATE, _INSERT_OPT_IN, _INSERT_CAMPAIGN, _INSERT_SEND]
    + [f"UPDATE {t} SET tenant_id = tenant_id WHERE false" for t in _NEW_TABLES],
)
def test_app_reads_and_writes(engines, sql: str) -> None:
    assert _attempt(engines["app"], sql) == "ok"


@pytest.mark.parametrize("table", _NEW_TABLES)
def test_nobody_deletes(engines, table: str) -> None:
    for role in ("app", "admin", "worker"):
        assert _attempt(engines[role], f"DELETE FROM {table} WHERE false") == "denied", role


# --- qualify_webhook_worker: the documented columns, nothing else ------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id, tenant_id, waba_id, name, language, meta_template_id "
        "FROM whatsapp_templates LIMIT 1",
        "UPDATE whatsapp_templates SET status = 'APPROVED', quality = NULL, "
        "rejected_reason = NULL, updated_at = now() WHERE false",
        "SELECT id, tenant_id, phone_e164, revoked_at FROM whatsapp_opt_ins LIMIT 1",
        "UPDATE whatsapp_opt_ins SET revoked_at = now(), revoke_reason = 'stop' WHERE false",
        _INSERT_OPT_IN,
        "SELECT id, tenant_id, outbox_id, wamid, status FROM whatsapp_campaign_sends LIMIT 1",
        "UPDATE whatsapp_campaign_sends SET status = 'read', error_code = NULL, "
        "price_category = 'marketing', updated_at = now() WHERE false",
        "SELECT tenant_id, waba_id FROM whatsapp_phone_numbers LIMIT 1",
    ],
)
def test_worker_has_exactly_what_it_needs(engines, sql: str) -> None:
    assert _attempt(engines["worker"], sql) == "ok"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM whatsapp_templates LIMIT 1",
        "SELECT components FROM whatsapp_templates LIMIT 1",
        _INSERT_TEMPLATE,
        "UPDATE whatsapp_templates SET components = components WHERE false",
        "SELECT consent_text FROM whatsapp_opt_ins LIMIT 1",
        "UPDATE whatsapp_opt_ins SET consent_text = consent_text WHERE false",
        "SELECT 1 FROM whatsapp_campaigns LIMIT 1",
        _INSERT_CAMPAIGN,
        "SELECT phone_e164 FROM whatsapp_campaign_sends LIMIT 1",
        "SELECT cost_estimate FROM whatsapp_campaign_sends LIMIT 1",
        _INSERT_SEND,
        "UPDATE whatsapp_campaign_sends SET wamid = wamid WHERE false",
        "UPDATE whatsapp_campaign_sends SET cost_estimate = cost_estimate WHERE false",
        "SELECT 1 FROM whatsapp_outbox LIMIT 1",
    ],
)
def test_worker_is_denied_everything_else(engines, sql: str) -> None:
    assert _attempt(engines["worker"], sql) == "denied"


@pytest.mark.parametrize("table", _NEW_TABLES)
def test_admin_reads_only_and_credential_nothing(engines, table: str) -> None:
    assert _attempt(engines["admin"], f"SELECT * FROM {table} LIMIT 1") == "ok"
    assert _attempt(engines["admin"], f"UPDATE {table} SET tenant_id = tenant_id WHERE false") == (
        "denied"
    )
    assert _attempt(engines["credential"], f"SELECT 1 FROM {table} LIMIT 1") == "denied"


# --- the catalog ---------------------------------------------------------------------------


def test_exactly_the_documented_grants_and_nothing_more(engines) -> None:
    with engines["owner"].connect() as conn:
        table_level = {
            (r.grantee, r.table_name, r.privilege_type)
            for r in conn.execute(
                text(
                    "SELECT grantee, table_name, privilege_type "
                    "FROM information_schema.role_table_grants "
                    f"WHERE table_name IN ({_TABLES_SQL}) "
                    "AND grantee LIKE 'qualify_%' AND grantee <> 'qualify_owner'"
                )
            )
        }
        column_level = {
            (r.grantee, r.table_name, r.privilege_type, r.column_name)
            for r in conn.execute(
                text(
                    "SELECT grantee, table_name, privilege_type, column_name "
                    "FROM information_schema.column_privileges "
                    f"WHERE table_name IN ({_TABLES_SQL}) "
                    "AND grantee LIKE 'qualify_%' AND grantee <> 'qualify_owner'"
                )
            )
        }
    expected_table = {
        (grantee, table, priv)
        for table in _NEW_TABLES
        for grantee, priv in (
            ("qualify_app", "SELECT"),
            ("qualify_app", "INSERT"),
            ("qualify_app", "UPDATE"),
            ("qualify_admin", "SELECT"),
        )
    }
    assert table_level == expected_table
    expanded = {row for row in column_level if row[:3] in table_level}
    assert column_level - expanded == {
        ("qualify_webhook_worker", table, priv, col) for (table, priv, col) in _WORKER_COLUMN_GRANTS
    }


def test_new_tables_have_rls_enabled_forced_and_one_policy(engines) -> None:
    with engines["owner"].connect() as conn:
        flags = {
            r.relname: (r.relrowsecurity, r.relforcerowsecurity)
            for r in conn.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                    f"WHERE relname IN ({_TABLES_SQL}) AND relkind = 'r'"
                )
            )
        }
        policies = {
            r.tablename: (r.policyname, r.qual)
            for r in conn.execute(
                text(
                    "SELECT tablename, policyname, qual FROM pg_policies "
                    f"WHERE tablename IN ({_TABLES_SQL})"
                )
            )
        }
    for table in _NEW_TABLES:
        assert flags[table] == (True, True), table
        name, qual = policies[table]
        assert name == "tenant_isolation", table
        assert "NULLIF" in qual.upper(), table


def test_uniques_fks_and_the_trigger_exist(engines) -> None:
    with engines["owner"].connect() as conn:
        constraints = {
            r.conname: r.def_
            for r in conn.execute(
                text(
                    "SELECT conname, pg_get_constraintdef(oid) AS def_ FROM pg_constraint "
                    "WHERE conname IN ('uq_wa_template_natural_key', 'uq_wa_opt_in_tenant_phone', "
                    "'uq_wa_campaign_send_phone', 'uq_wa_outbox_id_tenant', "
                    "'fk_wa_campaign_send_outbox_tenant', 'fk_wa_campaign_template_tenant', "
                    "'fk_wa_campaign_conn_tenant', 'fk_wa_campaign_send_campaign_tenant')"
                )
            )
        }
        triggers = {
            r.tgname
            for r in conn.execute(
                text(
                    "SELECT tgname FROM pg_trigger "
                    "WHERE tgrelid = 'whatsapp_outbox'::regclass AND NOT tgisinternal"
                )
            )
        }
    assert constraints["uq_wa_template_natural_key"] == (
        "UNIQUE (tenant_id, waba_id, name, language)"
    )
    assert constraints["uq_wa_opt_in_tenant_phone"] == "UNIQUE (tenant_id, phone_e164)"
    assert constraints["uq_wa_campaign_send_phone"] == "UNIQUE (campaign_id, phone_e164)"
    assert constraints["uq_wa_outbox_id_tenant"] == "UNIQUE (id, tenant_id)"
    assert constraints["fk_wa_campaign_send_outbox_tenant"] == (
        "FOREIGN KEY (outbox_id, tenant_id) REFERENCES whatsapp_outbox(id, tenant_id)"
    )
    assert constraints["fk_wa_campaign_template_tenant"] == (
        "FOREIGN KEY (template_id, tenant_id) REFERENCES whatsapp_templates(id, tenant_id)"
    )
    assert "wa_outbox_campaign_mirror" in triggers


# --- behaviour with real rows -----------------------------------------------------------


def _ensure_tenant(session, tenant_id: UUID, name: str) -> None:
    if session.get(Tenant, tenant_id) is None:
        session.add(
            Tenant(id=tenant_id, name=name, country="CO", timezone="America/Bogota", currency="COP")
        )
        session.flush()


@pytest.fixture
def seeded() -> dict[str, UUID]:
    """Tenant + user + platform app, then a WhatsApp connection, a phone number and an
    approved template through `tenant_session`."""
    with admin_session() as session:
        _ensure_tenant(session, TENANT, "t-wa18")
        _ensure_tenant(session, OTHER_TENANT, "t-wa18-other")
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        user = User(tenant_id=TENANT, email=f"u-{uuid4()}@wa18.co", display_name="U")
        session.add_all([app, user])
        session.flush()
        app_id, user_id = app.id, user.id

    waba = f"waba-{uuid4()}"
    with tenant_session(TENANT) as session:
        conn = SocialConnection(
            tenant_id=TENANT,
            platform_app_id=app_id,
            platform="whatsapp",
            account_type="waba_phone_number",
            external_account_id=f"wa-{uuid4()}",
            linked_page_id=None,
            granted_scopes=["whatsapp_business_messaging"],
            status="pending",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=user_id,
        )
        session.add(conn)
        session.flush()
        phone = WhatsAppPhoneNumber(
            tenant_id=TENANT,
            connection_id=conn.id,
            waba_id=waba,
            phone_number_id=f"pn-{uuid4()}",
            display_phone_number="+57 300 000 0000",
        )
        template = WhatsAppTemplate(
            tenant_id=TENANT,
            waba_id=waba,
            name=f"promo_{uuid4().hex[:8]}",
            language="es",
            category="marketing",
            status="APPROVED",
        )
        session.add_all([phone, template])
        session.flush()
        ids = {
            "user": user_id,
            "connection": conn.id,
            "phone": phone.id,
            "template": template.id,
        }
    ids["waba"] = waba  # type: ignore[assignment]
    return ids


def _campaign_with_send(seeded: dict[str, UUID], phone_e164: str) -> tuple[UUID, UUID, UUID]:
    """A campaign, one outbox row of kind campaign_send and the send row linked to it."""
    with tenant_session(TENANT) as session:
        campaign = WhatsAppCampaign(
            tenant_id=TENANT,
            connection_id=seeded["connection"],
            template_id=seeded["template"],
            name="Promo",
            created_by_user_id=seeded["user"],
        )
        session.add(campaign)
        session.flush()
        outbox = WhatsAppOutboxItem(
            tenant_id=TENANT,
            connection_id=seeded["connection"],
            thread_id=None,
            kind="campaign_send",
            payload={"messaging_product": "whatsapp", "to": phone_e164, "type": "template"},
        )
        session.add(outbox)
        session.flush()
        send = WhatsAppCampaignSend(
            tenant_id=TENANT,
            campaign_id=campaign.id,
            phone_e164=phone_e164,
            outbox_id=outbox.id,
            status="queued",
        )
        session.add(send)
        session.flush()
        return campaign.id, outbox.id, send.id


def _send(send_id: UUID) -> WhatsAppCampaignSend:
    with tenant_session(TENANT) as session:
        row = session.get(WhatsAppCampaignSend, send_id)
        assert row is not None
        session.expunge(row)
        return row


def _settle_outbox(outbox_id: UUID, **values: object) -> None:
    with tenant_session(TENANT) as session:
        row = session.get(WhatsAppOutboxItem, outbox_id)
        assert row is not None
        for key, value in values.items():
            setattr(row, key, value)


def test_the_mirror_copies_the_wamid_when_the_outbox_row_is_sent(seeded) -> None:
    _, outbox_id, send_id = _campaign_with_send(seeded, "+573001110001")
    _settle_outbox(outbox_id, status="sending")
    assert _send(send_id).status == "queued"
    _settle_outbox(outbox_id, status="sent", wamid="wamid.MIRROR1")
    row = _send(send_id)
    assert (row.status, row.wamid, row.error_code) == ("sent", "wamid.MIRROR1", None)


@pytest.mark.parametrize(
    ("outbox_status", "error_code", "expected"),
    [
        ("failed", "131026", "failed"),
        ("dead", "auth", "failed"),
        ("failed", "131049", "skipped"),
        ("failed", "campaign_cancelled", "skipped"),
    ],
)
def test_the_mirror_settles_failures(seeded, outbox_status, error_code, expected) -> None:
    _, outbox_id, send_id = _campaign_with_send(seeded, f"+57300{uuid4().int % 10**7:07d}")
    _settle_outbox(outbox_id, status=outbox_status, error_code=error_code)
    row = _send(send_id)
    assert (row.status, row.error_code) == (expected, error_code)


def test_the_mirror_never_regresses_a_receipt(seeded) -> None:
    _, outbox_id, send_id = _campaign_with_send(seeded, "+573001110002")
    with tenant_session(TENANT) as session:
        row = session.get(WhatsAppCampaignSend, send_id)
        assert row is not None
        row.status = "delivered"
    _settle_outbox(outbox_id, status="sent", wamid="wamid.LATE")
    assert _send(send_id).status == "delivered"


def test_one_send_per_campaign_and_phone(seeded) -> None:
    campaign_id, _, _ = _campaign_with_send(seeded, "+573001110003")
    with pytest.raises(IntegrityError) as excinfo:
        with tenant_session(TENANT) as session:
            session.add(
                WhatsAppCampaignSend(
                    tenant_id=TENANT, campaign_id=campaign_id, phone_e164="+573001110003"
                )
            )
            session.flush()
    assert isinstance(excinfo.value.orig, UniqueViolation)


def test_one_opt_in_per_tenant_and_phone_and_e164_is_enforced(seeded) -> None:
    phone = f"+57301{uuid4().int % 10**7:07d}"
    with tenant_session(TENANT) as session:
        session.add(
            WhatsAppOptIn(tenant_id=TENANT, phone_e164=phone, source="manual", consent_text="Sí")
        )
    with pytest.raises(IntegrityError) as excinfo:
        with tenant_session(TENANT) as session:
            session.add(
                WhatsAppOptIn(
                    tenant_id=TENANT, phone_e164=phone, source="import", consent_text="Sí"
                )
            )
            session.flush()
    assert isinstance(excinfo.value.orig, UniqueViolation)
    with pytest.raises(IntegrityError) as excinfo:
        with tenant_session(TENANT) as session:
            session.add(
                WhatsAppOptIn(
                    tenant_id=TENANT, phone_e164="3001234567", source="manual", consent_text="Sí"
                )
            )
            session.flush()
    assert isinstance(excinfo.value.orig, CheckViolation)


def test_rls_hides_another_tenants_rows(seeded) -> None:
    phone = f"+57302{uuid4().int % 10**7:07d}"
    with tenant_session(TENANT) as session:
        session.add(
            WhatsAppOptIn(tenant_id=TENANT, phone_e164=phone, source="manual", consent_text="Sí")
        )
    with tenant_session(OTHER_TENANT) as session:
        assert (
            session.scalars(select(WhatsAppOptIn).where(WhatsAppOptIn.phone_e164 == phone)).all()
            == []
        )
        assert session.get(WhatsAppTemplate, seeded["template"]) is None


# --- templates: the Postgres repositories through the production doors (WA-18) --------


def test_template_repository_round_trip_and_worker_webhook(seeded) -> None:
    repo = PostgresTemplateRepository()
    waba = str(seeded["waba"])
    ref = repo.waba_for_connection(tenant_id=TENANT, connection_id=seeded["connection"])
    assert ref is not None and (ref.waba_id, ref.phone_number_row_id) == (waba, seeded["phone"])

    record = repo.insert(
        TemplateRecord(
            id=uuid4(),
            tenant_id=TENANT,
            waba_id=waba,
            name="hola_es",
            language="es",
            category="utility",
            status="PENDING",
            meta_template_id="555",
            components=[{"type": "BODY", "text": "Hola"}],
        )
    )
    with pytest.raises(TemplateAlreadyExists):
        repo.insert(replace(record, id=uuid4()))

    # Sync: one refresh of the existing row, one new row.
    assert not repo.upsert_from_meta(
        tenant_id=TENANT,
        waba_id=waba,
        info=TemplateInfo(
            id="555", name="hola_es", language="es", status="APPROVED", category="utility"
        ),
        phone_number_row_id=None,
    )
    assert repo.upsert_from_meta(
        tenant_id=TENANT,
        waba_id=waba,
        info=TemplateInfo(
            id="556", name="otra", language="es", status="PENDING", category="marketing"
        ),
        phone_number_row_id=None,
    )
    refreshed = repo.get(tenant_id=TENANT, template_id=record.id)
    assert refreshed is not None and refreshed.status == "APPROVED"

    # The worker: resolves the WABA, then updates only its granted columns.
    resolution = resolve_waba(waba)
    assert (resolution.outcome, resolution.tenant_id) == (PhoneResolutionOutcome.RESOLVED, TENANT)
    assert resolve_waba(f"nope-{uuid4()}").outcome is PhoneResolutionOutcome.ORPHAN
    worker = PostgresTemplateWebhookRepository()
    keys = dict(tenant_id=TENANT, waba_id=waba, meta_template_id="555", name="x", language="x")
    assert worker.apply_status(**keys, status="PAUSED", rejected_reason=None)
    assert worker.apply_quality(**keys, quality="RED")
    assert not worker.apply_status(
        **{**keys, "tenant_id": OTHER_TENANT}, status="DISABLED", rejected_reason=None
    )
    after = repo.get(tenant_id=TENANT, template_id=record.id)
    assert after is not None and (after.status, after.quality) == ("PAUSED", "RED")

    assert repo.set_status_by_name(tenant_id=TENANT, waba_id=waba, name="otra", status="DELETED")
    listed = {t.name: t.status for t in repo.list(tenant_id=TENANT, waba_id=waba)}
    assert listed["otra"] == "DELETED"


# --- opt-ins: app repository, lead import and the worker's STOP revocation (WA-19) -----


def _random_phone() -> str:
    return f"+57310{uuid4().int % 10**7:07d}"


def test_opt_in_repository_import_and_worker_revoke(seeded) -> None:
    with tenant_session(TENANT) as session:
        if session.scalars(select(LeadFormSettings)).first() is None:
            session.add(
                LeadFormSettings(
                    tenant_id=TENANT,
                    business_name="Bianki",
                    whatsapp_phone="+573000000000",
                    consent_text="Acepto recibir mensajes de Bianki por WhatsApp.",
                    consent_policy_version="v1",
                )
            )
        lead_phone = _random_phone()
        session.add(
            Lead(
                tenant_id=TENANT,
                full_name="Ana",
                whatsapp_phone=lead_phone,
                consent_at=datetime(2026, 10, 1, tzinfo=UTC),
                consent_policy_version="v1",
            )
        )

    service = OptInService(PostgresOptInRepository())
    report = service.import_from_leads(tenant_id=TENANT)
    assert report.created >= 1
    row = service.get(tenant_id=TENANT, phone=lead_phone)
    assert row is not None and row.source == "lead_form" and row.is_active
    assert row.proof is not None and row.proof["consent_at"].startswith("2026-10-01")
    assert service.import_from_leads(tenant_id=TENANT).created == 0  # idempotent

    manual = _random_phone()
    service.record(tenant_id=TENANT, phone=manual, source="manual", consent_text="Sí, acepto")
    actives = {r.phone_e164 for r in service.list_active(tenant_id=TENANT)}
    assert {lead_phone, manual} <= actives

    # The worker door: revokes by (tenant, phone), once; another tenant's id never matches.
    worker = PostgresOptOutRepository()
    at = datetime(2026, 10, 14, tzinfo=UTC)
    assert not worker.revoke(tenant_id=OTHER_TENANT, phone_e164=manual, at=at, reason="stop")
    assert worker.revoke(tenant_id=TENANT, phone_e164=manual, at=at, reason="stop_keyword")
    assert not worker.revoke(tenant_id=TENANT, phone_e164=manual, at=at, reason="stop_keyword")
    revoked = service.get(tenant_id=TENANT, phone=manual)
    assert revoked is not None and (revoked.revoked_at, revoked.revoke_reason) == (
        at,
        "stop_keyword",
    )

    # A consent captured after the STOP re-opts the phone in (same row, reconsented).
    again = service.record(
        tenant_id=TENANT,
        phone=manual,
        source="menu",
        consent_text="Sí, acepto",
        captured_at=at + timedelta(days=1),
    )
    assert again.outcome is RecordOutcome.RECONSENTED and again.record.id == revoked.id
    assert service.is_opted_in(tenant_id=TENANT, phone=manual)


# --- campaigns: launch → real outbox sender settle → trigger → worker receipt (WA-20) --


def test_campaign_end_to_end_through_the_real_outbox_and_worker(seeded) -> None:
    optins = OptInService(PostgresOptInRepository())
    prefix = f"+5799{uuid4().int % 10**4:04d}"  # a prefix only this run's phones share
    phones = [f"{prefix}{i:05d}" for i in range(3)]
    for phone in phones:
        optins.record(tenant_id=TENANT, phone=phone, source="manual", consent_text="Sí, acepto")

    service = CampaignService(
        PostgresCampaignRepository(), PostgresTemplateRepository(), PostgresOptInRepository()
    )
    campaign = service.create(
        tenant_id=TENANT,
        connection_id=seeded["connection"],
        template_id=seeded["template"],
        name="Promo e2e",
        created_by_user_id=seeded["user"],
        audience=AudienceFilter(phone_prefixes=(prefix,)),
        max_per_minute=60,
    )
    report = service.launch(tenant_id=TENANT, campaign_id=campaign.id, user_id=seeded["user"])
    assert (report.audience, report.inserted, report.enqueued) == (3, 3, 3)
    assert service.launch(
        tenant_id=TENANT, campaign_id=campaign.id, user_id=seeded["user"]
    ).enqueued == (0)

    sends = service.sends(tenant_id=TENANT, campaign_id=campaign.id)
    assert {s.status for s in sends} == {"queued"}
    with tenant_session(TENANT) as session:
        items = session.scalars(
            select(WhatsAppOutboxItem).where(
                WhatsAppOutboxItem.id.in_([s.outbox_id for s in sends])
            )
        ).all()
        assert {i.kind for i in items} == {"campaign_send"}
        dues = sorted(i.next_attempt_at for i in items)
        assert dues[1] - dues[0] == timedelta(seconds=1)  # 60/min
        assert all(i.thread_id is None for i in items)

    # The real WA-08 sender settles the rows; the 0060 trigger mirrors them.
    outbox = PostgresOutboxRepository()
    far = datetime.now(UTC) + timedelta(days=1)
    claimed = {
        i.id for i in outbox.claim(tenant_id=TENANT, worker_id="wa18-test", now=far, limit=500)
    }
    mine = [s for s in sends if s.outbox_id in claimed]
    assert len(mine) == 3
    a, b, c = mine
    outbox.mark_sent(tenant_id=TENANT, item_id=a.outbox_id, wamid=f"wamid.{uuid4()}", now=far)
    outbox.mark_sent(tenant_id=TENANT, item_id=b.outbox_id, wamid=f"wamid.{uuid4()}", now=far)
    outbox.mark_failed(tenant_id=TENANT, item_id=c.outbox_id, error_code="131026")
    by_id = {s.id: s for s in service.sends(tenant_id=TENANT, campaign_id=campaign.id)}
    assert by_id[a.id].status == "sent" and by_id[a.id].wamid is not None
    assert (by_id[c.id].status, by_id[c.id].error_code) == ("failed", "131026")

    # Receipts through the worker door.
    receipts = PostgresCampaignReceiptRepository()
    wamid_a, wamid_b = by_id[a.id].wamid, by_id[b.id].wamid
    assert receipts.apply_receipt(
        tenant_id=TENANT, wamid=wamid_a, status="read", error_code=None, price_category=None
    )
    assert receipts.apply_receipt(
        tenant_id=TENANT,
        wamid=wamid_a,
        status="delivered",
        error_code=None,
        price_category="marketing",
    )
    assert receipts.apply_receipt(
        tenant_id=TENANT, wamid=wamid_b, status="failed", error_code="131049", price_category=None
    )
    assert not receipts.apply_receipt(
        tenant_id=OTHER_TENANT, wamid=wamid_a, status="read", error_code=None, price_category=None
    )
    by_id = {s.id: s for s in service.sends(tenant_id=TENANT, campaign_id=campaign.id)}
    assert (by_id[a.id].status, by_id[a.id].price_category) == ("read", "marketing")
    assert (by_id[b.id].status, by_id[b.id].error_code) == ("skipped", "131049")

    summary = service.summary(tenant_id=TENANT, campaign_id=campaign.id)
    assert summary.retry_after_24h == 1 and summary.counts["read"] == 1
    assert service.finalize_if_complete(tenant_id=TENANT, campaign_id=campaign.id)


def test_campaign_cancel_withdraws_pending_outbox_rows(seeded) -> None:
    optins = OptInService(PostgresOptInRepository())
    prefix = f"+5798{uuid4().int % 10**4:04d}"
    for i in range(2):
        optins.record(
            tenant_id=TENANT, phone=f"{prefix}{i:05d}", source="manual", consent_text="Sí"
        )
    service = CampaignService(
        PostgresCampaignRepository(), PostgresTemplateRepository(), PostgresOptInRepository()
    )
    campaign = service.create(
        tenant_id=TENANT,
        connection_id=seeded["connection"],
        template_id=seeded["template"],
        name="Promo cancel",
        created_by_user_id=seeded["user"],
        audience=AudienceFilter(phone_prefixes=(prefix,)),
    )
    service.launch(tenant_id=TENANT, campaign_id=campaign.id, user_id=None)
    assert service.cancel(tenant_id=TENANT, campaign_id=campaign.id) == 2
    sends = service.sends(tenant_id=TENANT, campaign_id=campaign.id)
    assert {(s.status, s.error_code) for s in sends} == {("skipped", "campaign_cancelled")}
    with tenant_session(TENANT) as session:
        statuses = set(
            session.scalars(
                select(WhatsAppOutboxItem.status).where(
                    WhatsAppOutboxItem.id.in_([s.outbox_id for s in sends])
                )
            )
        )
    assert statuses == {"failed"}
    assert service.get(tenant_id=TENANT, campaign_id=campaign.id).status == "cancelled"

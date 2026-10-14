"""Migration 0050's grants, checked as the REAL roles (QUA-147).

Each check connects with the role's own DSN and runs ONE statement inside a transaction
that is always rolled back: an allowed statement leaves nothing behind, a denied one must
fail with `insufficient_privilege`. Together they pin the effective-permissions table of
the migration docstring, cell by cell — so widening any role later fails here first.
Structural checks (role attributes, unique-index count, FK action, no RLS policy) run as
the owner.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import uuid4

import pytest
from psycopg.errors import InsufficientPrivilege
from qualify_shared.db.config import (
    admin_dsn,
    app_dsn,
    credential_dsn,
    webhook_dsn,
    webhook_worker_dsn,
)
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.db

_ROLE_DSNS = {
    "webhook": webhook_dsn,
    "worker": webhook_worker_dsn,
    "app": app_dsn,
    "admin": admin_dsn,
    "credential": credential_dsn,
}


@pytest.fixture(scope="module")
def engines() -> Iterator[dict[str, Engine]]:
    built = {name: create_engine(dsn()) for name, dsn in _ROLE_DSNS.items()}
    built["owner"] = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    try:
        yield built
    finally:
        for engine in built.values():
            engine.dispose()


def _attempt(engine: Engine, sql: str, params: dict | None = None) -> str:
    """'ok' or 'denied' — always rolled back, so nothing a check does persists."""
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text(sql), params or {})
            return "ok"
        except DBAPIError as exc:
            if isinstance(exc.orig, InsufficientPrivilege):
                return "denied"
            raise
        finally:
            trans.rollback()


_INSERT_DELIVERY = (
    "INSERT INTO meta_webhook_deliveries (id, raw_body, body_sha256, body_bytes, "
    "signature_header, parse_status) VALUES (gen_random_uuid(), '\\x00', :h, 1, 's', "
    "'parsed') ON CONFLICT DO NOTHING"
)


def _h() -> dict:
    return {"h": f"perm-{uuid4()}"}


# --- the receiver: INSERT and nothing else -------------------------------------------


def test_receiver_can_insert_with_a_targetless_on_conflict(engines) -> None:
    assert _attempt(engines["webhook"], _INSERT_DELIVERY, _h()) == "ok"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1 FROM meta_webhook_deliveries LIMIT 1",
        "SELECT 1 FROM meta_webhook_events LIMIT 1",
        "UPDATE meta_webhook_events SET status = status",
        "DELETE FROM meta_webhook_events",
        "DELETE FROM meta_webhook_deliveries",
        _INSERT_DELIVERY + " RETURNING id",
        _INSERT_DELIVERY.replace("ON CONFLICT DO NOTHING", "ON CONFLICT (body_sha256) DO NOTHING"),
        "SELECT 1 FROM social_connections LIMIT 1",
        "SELECT 1 FROM mentions LIMIT 1",
        "SELECT 1 FROM tenants LIMIT 1",
    ],
)
def test_receiver_is_denied_everything_else(engines, sql: str) -> None:
    assert _attempt(engines["webhook"], sql, _h()) == "denied"


# --- the processor: the queue columns, the purge, five columns of social_connections --


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id, received_at, body_sha256, body_bytes, object, parse_status, change_count, "
        "entry_ids FROM meta_webhook_deliveries LIMIT 1",
        "SELECT * FROM meta_webhook_events LIMIT 1",
        "UPDATE meta_webhook_events SET status = status, attempts = attempts, "
        "next_attempt_at = next_attempt_at, locked_at = locked_at, locked_by = locked_by, "
        "processed_at = processed_at, last_error = last_error WHERE false",
        "DELETE FROM meta_webhook_events WHERE false",
        "DELETE FROM meta_webhook_deliveries WHERE false",
        "SELECT id, tenant_id, platform, external_account_id, status FROM social_connections "
        "LIMIT 1",
    ],
)
def test_worker_has_exactly_what_it_needs(engines, sql: str) -> None:
    assert _attempt(engines["worker"], sql) == "ok"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT raw_body FROM meta_webhook_deliveries LIMIT 1",
        "SELECT signature_header FROM meta_webhook_deliveries LIMIT 1",
        "UPDATE meta_webhook_events SET value = value WHERE false",
        "UPDATE meta_webhook_events SET field = field WHERE false",
        "UPDATE meta_webhook_events SET delivery_id = delivery_id WHERE false",
        "UPDATE meta_webhook_deliveries SET raw_body = raw_body WHERE false",
        _INSERT_DELIVERY,
        "SELECT linked_page_id FROM social_connections LIMIT 1",
        "UPDATE social_connections SET status = status WHERE false",
        "SELECT 1 FROM tenants LIMIT 1",
        "SELECT 1 FROM oauth_credentials LIMIT 1",
        "SELECT 1 FROM mentions LIMIT 1",
        # 0057 (WA-04) gave it SELECT/INSERT/UPDATE on the conversation — never DELETE.
        "DELETE FROM messages WHERE false",
        "DELETE FROM threads WHERE false",
    ],
)
def test_worker_is_denied_everything_else(engines, sql: str) -> None:
    assert _attempt(engines["worker"], sql, _h()) == "denied"


def test_worker_resolves_across_tenants(engines) -> None:
    """The one reason it has BYPASSRLS: no `app.tenant_id` is set, yet it sees every
    tenant's rows (an RLS-subject role would see none)."""
    with engines["worker"].connect() as conn:
        worker_rows = conn.execute(text("SELECT count(*) FROM social_connections")).scalar()
    with engines["owner"].connect() as conn:
        all_rows = conn.execute(text("SELECT count(*) FROM social_connections")).scalar()
    assert worker_rows == all_rows


# --- every pre-existing role: no access at all -----------------------------------------


@pytest.mark.parametrize("role", ["app", "admin", "credential"])
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1 FROM meta_webhook_deliveries LIMIT 1",
        "SELECT 1 FROM meta_webhook_events LIMIT 1",
        _INSERT_DELIVERY,
        "DELETE FROM meta_webhook_events WHERE false",
    ],
)
def test_pre_existing_roles_cannot_touch_the_intake(engines, role: str, sql: str) -> None:
    assert _attempt(engines[role], sql, _h()) == "denied"


# --- structure --------------------------------------------------------------------------


def test_role_attributes(engines) -> None:
    with engines["owner"].connect() as conn:
        rows = {
            r.rolname: r
            for r in conn.execute(
                text(
                    "SELECT rolname, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole "
                    "FROM pg_roles WHERE rolname IN ('qualify_webhook', 'qualify_webhook_worker')"
                )
            )
        }
    receiver, worker = rows["qualify_webhook"], rows["qualify_webhook_worker"]
    assert (receiver.rolsuper, receiver.rolbypassrls) == (False, False)
    assert (worker.rolsuper, worker.rolbypassrls) == (False, True)
    for role in (receiver, worker):
        assert (role.rolcreatedb, role.rolcreaterole) == (False, False)


# Tables where 0057 (WA-04) gave the worker TABLE-level grants. `column_privileges` lists
# a table-level grant once per column, so they are excluded from the column-level pin and
# asserted at table level instead.
_WORKER_TABLE_GRANTED = ("threads", "messages", "whatsapp_thread_state", "whatsapp_outbox")


def _table_granted_sql() -> str:
    return ", ".join(f"'{t}'" for t in _WORKER_TABLE_GRANTED)


def test_exactly_the_documented_grants_and_nothing_more(engines) -> None:
    """Table- and column-level privileges of the two roles, as the catalog reports them.
    An extra grant anywhere (another table, another column) fails this. The WhatsApp
    rows come from 0057 (WA-04): the worker writes the inbound conversation."""
    with engines["owner"].connect() as conn:
        table_level = {
            (r.grantee, r.table_name, r.privilege_type)
            for r in conn.execute(
                text(
                    "SELECT grantee, table_name, privilege_type "
                    "FROM information_schema.role_table_grants "
                    "WHERE grantee IN ('qualify_webhook', 'qualify_webhook_worker')"
                )
            )
        }
        column_level = {
            (r.grantee, r.table_name, r.column_name, r.privilege_type)
            for r in conn.execute(
                text(
                    "SELECT grantee, table_name, column_name, privilege_type "
                    "FROM information_schema.column_privileges "
                    "WHERE grantee IN ('qualify_webhook', 'qualify_webhook_worker') "
                    "AND table_name NOT LIKE 'meta_webhook_%' "
                    f"AND table_name NOT IN ({_table_granted_sql()})"
                )
            )
        }
    assert table_level == {
        ("qualify_webhook", "meta_webhook_deliveries", "INSERT"),
        ("qualify_webhook", "meta_webhook_events", "INSERT"),
        ("qualify_webhook_worker", "meta_webhook_deliveries", "DELETE"),
        ("qualify_webhook_worker", "meta_webhook_events", "SELECT"),
        ("qualify_webhook_worker", "meta_webhook_events", "DELETE"),
        ("qualify_webhook_worker", "threads", "SELECT"),
        ("qualify_webhook_worker", "threads", "INSERT"),
        ("qualify_webhook_worker", "threads", "UPDATE"),
        ("qualify_webhook_worker", "messages", "SELECT"),
        ("qualify_webhook_worker", "messages", "INSERT"),
        ("qualify_webhook_worker", "messages", "UPDATE"),
        ("qualify_webhook_worker", "whatsapp_thread_state", "SELECT"),
        ("qualify_webhook_worker", "whatsapp_thread_state", "INSERT"),
        ("qualify_webhook_worker", "whatsapp_thread_state", "UPDATE"),
        ("qualify_webhook_worker", "whatsapp_outbox", "INSERT"),
    }
    assert column_level == {
        ("qualify_webhook_worker", "social_connections", c, "SELECT")
        for c in ("id", "tenant_id", "platform", "external_account_id", "status")
    } | {
        # 0059 (WA-15) adds `brand_id`: the catalog loader finds the number's brand.
        # 0060 (WA-18) adds `waba_id`: template webhooks resolve the tenant by WABA.
        ("qualify_webhook_worker", "whatsapp_phone_numbers", c, "SELECT")
        for c in ("id", "tenant_id", "connection_id", "phone_number_id", "brand_id", "waba_id")
    } | {
        # 0059 (WA-15): the menu's `products` node reads the brand's active catalog.
        ("qualify_webhook_worker", "brand_products", c, "SELECT")
        for c in (
            "id",
            "tenant_id",
            "brand_id",
            "name",
            "price_amount",
            "price_currency",
            "category",
            "is_active",
            "position",
        )
    } | {
        # 0060 (WA-18/19/20): template webhooks, the STOP revocation, campaign receipts.
        ("qualify_webhook_worker", "whatsapp_templates", c, "SELECT")
        for c in ("id", "tenant_id", "waba_id", "name", "language", "meta_template_id")
    } | {
        ("qualify_webhook_worker", "whatsapp_templates", c, "UPDATE")
        for c in ("status", "quality", "rejected_reason", "updated_at")
    } | {
        ("qualify_webhook_worker", "whatsapp_opt_ins", c, "SELECT")
        for c in ("id", "tenant_id", "phone_e164", "revoked_at")
    } | {
        ("qualify_webhook_worker", "whatsapp_opt_ins", c, "UPDATE")
        for c in ("revoked_at", "revoke_reason")
    } | {
        ("qualify_webhook_worker", "whatsapp_opt_ins", c, "INSERT")
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
    } | {
        ("qualify_webhook_worker", "whatsapp_campaign_sends", c, "SELECT")
        for c in ("id", "tenant_id", "outbox_id", "wamid", "status")
    } | {
        ("qualify_webhook_worker", "whatsapp_campaign_sends", c, "UPDATE")
        for c in ("status", "error_code", "price_category", "updated_at")
    } | {
        # 0058 (WA-14): the handler loads the live menu of a number and its definition.
        ("qualify_webhook_worker", "whatsapp_menus", c, "SELECT")
        for c in ("id", "tenant_id", "phone_number_row_id", "published_version_id", "is_paused")
    } | {
        ("qualify_webhook_worker", "whatsapp_menu_versions", c, "SELECT")
        for c in ("id", "tenant_id", "menu_id", "version", "definition")
    }


def test_worker_column_grants_on_the_intake_are_exact(engines) -> None:
    with engines["owner"].connect() as conn:
        rows = conn.execute(
            text(
                "SELECT table_name, column_name, privilege_type "
                "FROM information_schema.column_privileges "
                "WHERE grantee = 'qualify_webhook_worker' "
                "AND table_name LIKE 'meta_webhook_%' AND privilege_type IN ('SELECT','UPDATE')"
            )
        ).all()
    delivery_select = {r.column_name for r in rows if r.table_name == "meta_webhook_deliveries"}
    event_update = {
        r.column_name
        for r in rows
        if r.table_name == "meta_webhook_events" and r.privilege_type == "UPDATE"
    }
    assert delivery_select == {
        "id",
        "received_at",
        "body_sha256",
        "body_bytes",
        "object",
        "parse_status",
        "change_count",
        "entry_ids",
    }
    assert event_update == {
        "status",
        "attempts",
        "next_attempt_at",
        "locked_at",
        "locked_by",
        "processed_at",
        "last_error",
    }


def test_each_intake_table_has_exactly_two_unique_indexes(engines) -> None:
    """The receiver's targetless `ON CONFLICT DO NOTHING` swallows ANY unique violation;
    it is only safe while the PK (minted in Python) and the dedup key are the only ones."""
    with engines["owner"].connect() as conn:
        rows = conn.execute(
            text(
                "SELECT t.relname AS table_name, count(*) AS n FROM pg_index i "
                "JOIN pg_class t ON t.oid = i.indrelid "
                "WHERE t.relname IN ('meta_webhook_deliveries', 'meta_webhook_events') "
                "AND i.indisunique GROUP BY t.relname"
            )
        ).all()
    assert {r.table_name: r.n for r in rows} == {
        "meta_webhook_deliveries": 2,
        "meta_webhook_events": 2,
    }


def test_the_delivery_fk_sets_null_and_never_cascades(engines) -> None:
    with engines["owner"].connect() as conn:
        action = conn.execute(
            text("SELECT confdeltype FROM pg_constraint WHERE conname = 'fk_mwe_delivery'")
        ).scalar()
    assert action == "n"  # SET NULL ('c' would be CASCADE)


def test_the_intake_tables_have_no_rls_policy_and_no_tenant_id(engines) -> None:
    """The documented exception (migration 0050): isolation is by GRANT. Pinned so nobody
    'fixes' it with a policy that would silently filter the processor to zero rows."""
    with engines["owner"].connect() as conn:
        policies = conn.execute(
            text("SELECT count(*) FROM pg_policies WHERE tablename LIKE 'meta_webhook_%'")
        ).scalar()
        tenant_cols = conn.execute(
            text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name LIKE 'meta_webhook_%' AND column_name = 'tenant_id'"
            )
        ).scalar()
    assert (policies, tenant_cols) == (0, 0)

"""`db`: migration 0179 — `creative_usage_events.vendor_task_id` and its partial unique
key (m-25112161).

Same mechanics as `test_awareness_migration_0166_db.py`: 0179's own `downgrade()` /
`upgrade()` run inside ONE owner transaction that is rolled back, so the shared test
database is never left downgraded.

What it proves: the downgrade removes the column and the index; the upgrade brings them
back — the column text and NULL-able, the index UNIQUE on `(tenant_id, vendor_task_id)`
only where the task id is set; RLS stays enabled and forced with its NULLIF policy, and
the app role keeps its grants, throughout.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, create_engine, text

pytestmark = pytest.mark.db

_MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "migrations/postgres/versions/0179_usage_event_vendor_task_id.py"
)
_TABLE = "creative_usage_events"
_INDEX = "uq_usage_event_tenant_vendor_task"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0179", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["migration_0179"] = module
    spec.loader.exec_module(module)
    return module


def _column(conn: Connection) -> tuple[str, str] | None:
    row = conn.execute(
        text(
            "SELECT data_type, is_nullable FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = 'vendor_task_id'"
        ),
        {"t": _TABLE},
    ).one_or_none()
    return None if row is None else (row[0], row[1])


def _index(conn: Connection) -> str | None:
    return conn.execute(
        text("SELECT indexdef FROM pg_indexes WHERE tablename = :t AND indexname = :i"),
        {"t": _TABLE, "i": _INDEX},
    ).scalar_one_or_none()


def _isolated(conn: Connection) -> bool:
    forced = conn.execute(
        text(
            "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class "
            "WHERE relname = :t AND relkind = 'r'"
        ),
        {"t": _TABLE},
    ).scalar_one()
    policies = conn.execute(
        text("SELECT qual FROM pg_policies WHERE tablename = :t"), {"t": _TABLE}
    ).scalars()
    return bool(forced) and any("NULLIF" in (q or "") for q in policies)


def _app_grants(conn: Connection) -> tuple[bool, bool, bool]:
    return tuple(  # type: ignore[return-value]
        conn.execute(
            text(
                "SELECT has_table_privilege('qualify_app', :t, 'SELECT'), "
                "has_table_privilege('qualify_app', :t, 'INSERT'), "
                "has_table_privilege('qualify_app', :t, 'UPDATE')"
            ),
            {"t": _TABLE},
        ).one()
    )


def test_downgrade_drops_the_column_and_key_and_upgrade_restores_them() -> None:
    migration = _load()
    engine = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    try:
        with engine.connect() as conn:
            outer = conn.begin()
            try:
                grants = _app_grants(conn)
                assert grants == (True, True, True)
                assert _column(conn) == ("text", "YES") and _index(conn) is not None
                assert _isolated(conn)

                with Operations.context(MigrationContext.configure(conn)):
                    migration.downgrade()
                assert _column(conn) is None and _index(conn) is None
                assert _isolated(conn) and _app_grants(conn) == grants

                with Operations.context(MigrationContext.configure(conn)):
                    migration.upgrade()
                assert _column(conn) == ("text", "YES")
                indexdef = _index(conn)
                assert indexdef is not None and indexdef.startswith("CREATE UNIQUE INDEX")
                assert "(tenant_id, vendor_task_id)" in indexdef
                assert "WHERE (vendor_task_id IS NOT NULL)" in indexdef
                assert _isolated(conn) and _app_grants(conn) == grants
            finally:
                outer.rollback()
    finally:
        engine.dispose()

"""`db`: migration 0163 — business perks on the kit, awareness level on angles and briefs.

Same mechanics as `test_own_media_migration_0159_db.py`: 0163's own `downgrade()` /
`upgrade()` run inside ONE owner transaction that is rolled back, so the shared test
database is never left downgraded.

What it proves: the downgrade removes the three columns and their CHECKs; the upgrade
brings them back with `business_perks` defaulting to `[]` (NOT NULL, an array only) and
`awareness_level` NULL-able and limited to the five levels; RLS stays forced on the three
tables throughout.
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
    / "migrations/postgres/versions/0163_awareness_levels_business_perks.py"
)
_TABLES = ("brand_kits", "creative_angles", "content_briefs")
_COLUMNS = {
    ("brand_kits", "business_perks"),
    ("creative_angles", "awareness_level"),
    ("content_briefs", "awareness_level"),
}


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0163", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["migration_0163"] = module
    spec.loader.exec_module(module)
    return module


def _present(conn: Connection) -> set[tuple[str, str]]:
    rows = conn.execute(
        text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_name = ANY(:t) AND column_name IN ('business_perks','awareness_level')"
        ),
        {"t": list(_TABLES)},
    )
    return {(r[0], r[1]) for r in rows}


def _rls_forced(conn: Connection) -> bool:
    rows = conn.execute(
        text(
            "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class "
            "WHERE relname = ANY(:t) AND relkind = 'r'"
        ),
        {"t": list(_TABLES)},
    ).scalars()
    return all(rows)


def test_downgrade_drops_the_columns_and_upgrade_restores_them_with_their_checks() -> None:
    migration = _load()
    engine = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    try:
        with engine.connect() as conn:
            outer = conn.begin()
            try:
                assert _present(conn) == _COLUMNS and _rls_forced(conn)
                with Operations.context(MigrationContext.configure(conn)):
                    migration.downgrade()
                assert _present(conn) == set() and _rls_forced(conn)
                with Operations.context(MigrationContext.configure(conn)):
                    migration.upgrade()
                assert _present(conn) == _COLUMNS and _rls_forced(conn)

                default = conn.execute(
                    text(
                        "SELECT column_default, is_nullable FROM information_schema.columns "
                        "WHERE table_name = 'brand_kits' AND column_name = 'business_perks'"
                    )
                ).one()
                assert "'[]'::jsonb" in default[0] and default[1] == "NO"
                checks = dict(
                    conn.execute(
                        text(
                            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                            "WHERE conname = ANY(:n)"
                        ),
                        {
                            "n": [
                                "ck_creative_angles_awareness_level",
                                "ck_content_briefs_awareness_level",
                                "ck_brand_kits_business_perks_array",
                            ]
                        },
                    ).all()
                )
                assert len(checks) == 3
                for name in (
                    "ck_creative_angles_awareness_level",
                    "ck_content_briefs_awareness_level",
                ):
                    assert all(
                        level in checks[name]
                        for level in (
                            "unaware",
                            "problem_aware",
                            "solution_aware",
                            "product_aware",
                            "most_aware",
                        )
                    )
                assert "jsonb_typeof" in checks["ck_brand_kits_business_perks_array"]
            finally:
                outer.rollback()
    finally:
        engine.dispose()

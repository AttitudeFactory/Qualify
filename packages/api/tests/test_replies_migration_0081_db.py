"""`db`: migration 0081 (m-24789645, PR 2) — the schema it leaves, and its round trip.

Same mechanics as `test_replies_migration_0080_db.py`: 0081's own `downgrade()` /
`upgrade()` run inside ONE owner transaction that is rolled back, so the shared test
database is never left downgraded. CI also runs the whole chain on an empty database.

What it proves: with an intent-only draft present the downgrade REFUSES and changes
nothing; without one it restores NOT NULL and drops both CHECKs; upgrading again brings
them back.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from qualify_shared.db.admin import admin_session
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.db

_HERE = Path(__file__)
_MIGRATION = (
    _HERE.resolve().parents[3]
    / "migrations/postgres/versions/0081_comment_reply_draft_intent_only.py"
)
_CHECKS = ("ck_reply_draft_sentiment_pair", "ck_reply_draft_has_signal")


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _nullable(conn: Connection, column: str) -> bool:
    return (
        conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = 'comment_reply_drafts' AND column_name = :c"
            ),
            {"c": column},
        ).scalar_one()
        == "YES"
    )


def _has_constraint(conn: Connection, name: str) -> bool:
    found = conn.execute(text("SELECT 1 FROM pg_constraint WHERE conname = :n"), {"n": name})
    return found.first() is not None


def _seed_intent_only_draft() -> None:
    seeds = _load(_HERE.with_name("test_replies_public_drafts_db.py"), "faseb_db_seeds")
    sentiment, intent = seeds._version("sent"), seeds._version("intent")
    connection_id, thread_id, _ = seeds._seed_connection(seeds.TENANT_A)
    seeds._seed_comment(
        seeds.TENANT_A, connection_id, thread_id, "¿Precio?", intent=(intent, {"price": 0.9})
    )
    summary = seeds._service(sentiment, intent, seeds.FakeGenerator()).generate_drafts(
        tenant_id=seeds.TENANT_A, connection_id=connection_id
    )
    assert summary.drafts_created == 1


def test_schema_after_0081() -> None:
    with admin_session() as session:
        conn = session.connection()
        assert _nullable(conn, "sentiment_result_id") and _nullable(conn, "sentiment_label")
        assert all(_has_constraint(conn, name) for name in _CHECKS)


def test_round_trip_refuses_with_intent_only_drafts_then_restores_and_reapplies() -> None:
    _seed_intent_only_draft()
    migration = _load(_MIGRATION, "migration_0081")
    engine = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    try:
        with engine.connect() as conn:
            outer = conn.begin()
            try:
                with Operations.context(MigrationContext.configure(conn)):
                    savepoint = conn.begin_nested()
                    with pytest.raises(DBAPIError, match="downgrade 0081 refused"):
                        migration.downgrade()
                    savepoint.rollback()
                    assert _nullable(conn, "sentiment_result_id")

                    conn.execute(
                        text("DELETE FROM comment_reply_drafts WHERE sentiment_result_id IS NULL")
                    )
                    migration.downgrade()
                    assert not _nullable(conn, "sentiment_result_id")
                    assert not _nullable(conn, "sentiment_label")
                    assert not any(_has_constraint(conn, name) for name in _CHECKS)

                    migration.upgrade()
                    assert _nullable(conn, "sentiment_result_id")
                    assert all(_has_constraint(conn, name) for name in _CHECKS)
            finally:
                outer.rollback()
    finally:
        engine.dispose()

    with admin_session() as session:
        conn = session.connection()
        remaining = conn.execute(
            text("SELECT count(*) FROM comment_reply_drafts WHERE sentiment_result_id IS NULL")
        ).scalar_one()
    assert remaining >= 1  # the rollback restored the deleted drafts

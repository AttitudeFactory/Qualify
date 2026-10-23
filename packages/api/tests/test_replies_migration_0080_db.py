"""`db`: migration 0080 (m-24789645) — the schema it leaves, and its round trip.

The round trip runs 0080's own `downgrade()` / `upgrade()` inside ONE owner transaction
that is rolled back at the end (Postgres DDL is transactional), so the shared test
database is never left downgraded and no other test is disturbed. CI additionally runs
the whole chain (`upgrade head → downgrade base → upgrade head`) on an empty database.

What it proves:
- with several drafts for one comment, the downgrade REFUSES and changes nothing;
- once the superseded drafts are deleted (the SQL in 0080's docstring), the downgrade
  restores `UNIQUE(message_id)` and drops every 0080 column, and upgrading again brings
  the partial index and the columns back.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType
from uuid import UUID

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from qualify_shared.db.admin import admin_session
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import DBAPIError

from qualify_api.replies.repository import CandidateComment, PostgresReplyRepository

pytestmark = pytest.mark.db

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MIGRATION = _REPO_ROOT / "migrations/postgres/versions/0080_comment_reply_draft_grounding.py"
_NEW_COLUMNS = {
    "grounding",
    "needs_review",
    "unsupported_claims",
    "model_id",
    "model_revision",
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "intent_result_id",
}
_DELETE_SUPERSEDED = """
DELETE FROM comment_reply_drafts d USING (
    SELECT id, row_number() OVER (
        PARTITION BY message_id
        ORDER BY (status NOT IN ('discarded','send_failed')) DESC, created_at DESC, id DESC
    ) AS rn FROM comment_reply_drafts) r
WHERE d.id = r.id AND r.rn > 1
"""


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _columns(conn: Connection) -> set[str]:
    return set(
        conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'comment_reply_drafts'"
            )
        ).scalars()
    )


def _index_def(conn: Connection, name: str) -> str | None:
    return conn.execute(
        text("SELECT indexdef FROM pg_indexes WHERE indexname = :n"), {"n": name}
    ).scalar_one_or_none()


def _has_constraint(conn: Connection, name: str) -> bool:
    return (
        conn.execute(text("SELECT 1 FROM pg_constraint WHERE conname = :n"), {"n": name}).first()
        is not None
    )


def _seed_two_drafts_for_one_comment() -> UUID:
    """A discarded draft and its live replacement — what PR 3's «Regenerar» leaves.
    Seeded with the sibling file's helpers (loaded by path: `--import-mode=importlib`
    puts no test directory on `sys.path`)."""
    seeds = _load(Path(__file__).with_name("test_replies_repository_db.py"), "replies_db_seeds")
    tenant = seeds.TENANT_A
    connection_id, candidate, user_id = seeds._seed_pos_comment(tenant, seeds._fresh_version())
    repo = PostgresReplyRepository()

    def create(c: CandidateComment) -> UUID:
        draft = repo.create_draft(
            tenant_id=tenant,
            connection_id=connection_id,
            candidate=c,
            gate_reason="r",
            generator_version="v1",
            generated_text="t",
        )
        assert draft is not None
        return draft.id

    first = create(candidate)
    repo.decide_draft(
        tenant_id=tenant,
        draft_id=first,
        decision="discarded",
        final_text=None,
        decided_by_user_id=user_id,
    )
    create(candidate)
    return candidate.message_id


def test_schema_after_0080() -> None:
    with admin_session() as session:
        conn = session.connection()
        assert _NEW_COLUMNS <= _columns(conn)
        live = _index_def(conn, "uq_reply_draft_live_message")
        assert live is not None
        assert "UNIQUE" in live and "(message_id)" in live
        assert "'discarded'" in live and "'send_failed'" in live
        assert not _has_constraint(conn, "uq_reply_draft_message")
        assert _has_constraint(conn, "fk_reply_draft_intent_tenant")
        assert _has_constraint(conn, "uq_comment_intent_result_id_tenant")
        # The app role keeps exactly the table privileges 0014 gave it: no DELETE.
        privileges = {
            p: conn.execute(
                text("SELECT has_table_privilege('qualify_app', 'comment_reply_drafts', :p)"),
                {"p": p},
            ).scalar_one()
            for p in ("SELECT", "INSERT", "UPDATE", "DELETE")
        }
        assert privileges == {"SELECT": True, "INSERT": True, "UPDATE": True, "DELETE": False}


def test_round_trip_refuses_with_duplicates_then_restores_and_reapplies() -> None:
    message_id = _seed_two_drafts_for_one_comment()
    migration = _load(_MIGRATION, "migration_0080")
    engine = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    try:
        with engine.connect() as conn:
            outer = conn.begin()
            try:
                ops_context = Operations.context(MigrationContext.configure(conn))
                with ops_context:
                    # 1. Several drafts for one comment: the downgrade refuses.
                    savepoint = conn.begin_nested()
                    with pytest.raises(DBAPIError, match="downgrade 0080 refused"):
                        migration.downgrade()
                    savepoint.rollback()
                    assert _index_def(conn, "uq_reply_draft_live_message") is not None
                    assert _NEW_COLUMNS <= _columns(conn)

                    # 2. Superseded drafts deleted: the downgrade goes through.
                    conn.execute(text(_DELETE_SUPERSEDED))
                    remaining = conn.execute(
                        text("SELECT status FROM comment_reply_drafts WHERE message_id = :m"),
                        {"m": str(message_id)},
                    ).scalars()
                    assert list(remaining) == ["proposed"]  # the live one was kept
                    migration.downgrade()
                    assert _has_constraint(conn, "uq_reply_draft_message")
                    assert _index_def(conn, "uq_reply_draft_live_message") is None
                    assert not (_NEW_COLUMNS & _columns(conn))
                    assert not _has_constraint(conn, "uq_comment_intent_result_id_tenant")

                    # 3. And back up.
                    migration.upgrade()
                    assert _index_def(conn, "uq_reply_draft_live_message") is not None
                    assert not _has_constraint(conn, "uq_reply_draft_message")
                    assert _NEW_COLUMNS <= _columns(conn)
            finally:
                outer.rollback()  # the shared test database stays exactly as it was
    finally:
        engine.dispose()

    with admin_session() as session:
        conn = session.connection()
        assert _index_def(conn, "uq_reply_draft_live_message") is not None
        count = conn.execute(
            text("SELECT count(*) FROM comment_reply_drafts WHERE message_id = :m"),
            {"m": str(message_id)},
        ).scalar_one()
    assert count == 2  # the rollback restored the deleted draft too

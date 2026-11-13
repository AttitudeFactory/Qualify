"""`db`: migration 0159 (m-25019217) — its downgrade with recorded `own_media` pieces.

Same mechanics as `test_replies_migration_0081_db.py`: 0159's own `downgrade()` /
`upgrade()` run inside ONE owner transaction that is rolled back, so the shared test
database is never left downgraded. CI also runs the whole chain, but on an EMPTY database,
which is how a downgrade that deleted a draft's variant before unhooking the draft from it
(`fk_draft_selected_variant`) went unnoticed.

What it proves: with a piece and its `published` event recorded by `record_publication`,
the downgrade succeeds, leaves no `own_media` brief, draft, variant, asset, version or
event behind (the publication itself stays in `publish_attempts`), and upgrading again
restores the schema.
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

_HERE = Path(__file__)
_MIGRATION = (
    _HERE.resolve().parents[3] / "migrations/postgres/versions/0159_publish_now_own_media.py"
)


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(module)
    return module


def _count(conn: Connection, sql: str, **params: object) -> int:
    return int(conn.execute(text(sql), params).scalar_one())


def _columns(conn: Connection) -> set[str]:
    return set(
        conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'publish_attempts'"
            )
        ).scalars()
    )


def test_downgrade_removes_recorded_own_media_pieces_then_upgrade_reapplies() -> None:
    seeds = _load(_HERE.with_name("test_planner_immediate_db.py"), "immediate_db_seeds")
    world = seeds._world()
    attempt_id = seeds._attempt(world)
    result = seeds._record(world, attempt_id)
    assert result.draft_id is not None and result.event_id is not None

    migration = _load(_MIGRATION, "migration_0159")
    engine = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    tenant = {"t": world.tenant_id}
    try:
        with engine.connect() as conn:
            outer = conn.begin()
            try:
                conn.execute(text("SET LOCAL row_security = off"))
                own = (
                    "SELECT count(*) FROM content_drafts d JOIN content_briefs b "
                    "ON b.id = d.brief_id WHERE b.kind = 'own_media' AND d.tenant_id = :t"
                )
                assert _count(conn, own, **tenant) == 1
                with Operations.context(MigrationContext.configure(conn)):
                    migration.downgrade()

                    conn.execute(text("SET LOCAL row_security = off"))
                    assert (
                        _count(conn, "SELECT count(*) FROM content_briefs WHERE kind = 'own_media'")
                        == 0
                    )
                    assert (
                        _count(
                            conn,
                            "SELECT count(*) FROM content_drafts WHERE id = :d",
                            d=result.draft_id,
                        )
                        == 0
                    )
                    for table in ("copy_variants", "image_assets", "piece_versions"):
                        assert (
                            _count(
                                conn,
                                f"SELECT count(*) FROM {table} WHERE draft_id = :d",
                                d=result.draft_id,
                            )
                            == 0
                        )
                    assert (
                        _count(
                            conn,
                            "SELECT count(*) FROM calendar_events WHERE id = :e",
                            e=result.event_id,
                        )
                        == 0
                    )
                    assert (
                        _count(
                            conn,
                            "SELECT count(*) FROM publish_attempts WHERE id = :a",
                            a=attempt_id,
                        )
                        == 1
                    )
                    assert not {"media_object_key", "media_content_type", "permalink"} & _columns(
                        conn
                    )

                    migration.upgrade()
                    assert {"media_object_key", "media_content_type", "permalink"} <= _columns(conn)
                    check = conn.execute(
                        text(
                            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                            "WHERE conname = 'ck_content_briefs_kind'"
                        )
                    ).scalar_one()
                    assert "'own_media'" in check
            finally:
                outer.rollback()
    finally:
        engine.dispose()

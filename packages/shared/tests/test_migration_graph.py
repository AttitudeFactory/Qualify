"""Catch concurrent revision-number collisions before the live migration gate."""

from __future__ import annotations

import ast
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[3]


def test_migration_revision_identifiers_are_unique() -> None:
    seen: dict[str, str] = {}
    for path in sorted((ROOT / "migrations/postgres/versions").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "revision" for target in node.targets
            ):
                revision = ast.literal_eval(node.value)
                assert revision not in seen, (
                    f"Duplicate revision {revision}: {seen.get(revision)} and {path.name}"
                )
                seen[revision] = path.name
    assert seen, "No migration revisions discovered"


def test_migrations_have_one_head() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations/postgres"))
    heads = ScriptDirectory.from_config(config).get_heads()
    assert len(heads) == 1, f"Expected one migration head, got {heads}"

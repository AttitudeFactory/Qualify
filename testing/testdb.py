"""The test database: `qualify_test` (+ Redis db 15), never the development `qualify`.

Why this exists: until 2026-09-30 every `db` test wrote into the development database
(`localhost:5432/qualify`), because the DSNs in `qualify_shared.db.config` default there
and nothing redirected the tests. Thousands of test tenants accumulated next to the real
ones. This module is the whole fix, used by the root `conftest.py` and by
`just test-db-reset`:

- `apply_test_defaults()` points every DSN + Redis at the test targets, unless already set.
- `guard_problems()` is the guardrail: every DSN must name a database ending in `_test`
  (never `qualify`), all of them the same one, and Redis must not be db 0. Any violation
  aborts the run — whatever the command, whoever set the variable.
- `ensure()` creates `qualify_test` if missing and applies NEW migrations. It never
  deletes data: what a run leaves behind stays there, pass or fail, for inspection.
- `reset()` is the only destructive operation, and it is explicit (`pytest
  --reset-test-db`, `just test-db-reset`, `just test-fresh`): DROP DATABASE + CREATE +
  `alembic upgrade head` + FLUSHDB on the test Redis db. Dropping the whole database
  means no row-level cleanup, no FK ordering, nothing to know about what tests created.

Migrations edited IN PLACE (allowed pre-deploy, ADR 27 R8a) are not re-run by `upgrade
head`. `ensure()` detects them with a per-file hash stored as the database's COMMENT and
aborts with instructions instead of resetting by itself (that would erase data someone
may be inspecting).

The database name is never an argument: it comes from the validated migration DSN, and
`reset()` re-checks it right before DROP.

CLI: `python testing/testdb.py reset`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_ROOT / "migrations" / "postgres"

DEV_DB_NAME = "qualify"
TEST_DB_SUFFIX = "_test"
DSN_VARS = (
    "QUALIFY_APP_DSN",
    "QUALIFY_ADMIN_DSN",
    "QUALIFY_CREDENTIAL_DSN",
    "QUALIFY_WEBHOOK_DSN",
    "QUALIFY_WEBHOOK_WORKER_DSN",
    "QUALIFY_CREATIVE_WORKER_DSN",
    "QUALIFY_CONNECTION_PURGE_DSN",
    "QUALIFY_MIGRATION_DSN",
)
REDIS_VAR = "QUALIFY_REDIS_URL"

# Same roles and dev passwords as `qualify_shared.db.config` / migrations/postgres/env.py
# (roles are cluster-wide, created by 0001/0002 with IF NOT EXISTS) — only the database
# name and the Redis db differ.
TEST_DEFAULTS: dict[str, str] = {
    "QUALIFY_APP_DSN": "postgresql+psycopg://qualify_app:app_dev@localhost:5432/qualify_test",
    "QUALIFY_ADMIN_DSN": "postgresql+psycopg://qualify_admin:admin_dev@localhost:5432/qualify_test",
    "QUALIFY_CREDENTIAL_DSN": (
        "postgresql+psycopg://qualify_credential:credential_dev@localhost:5432/qualify_test"
    ),
    "QUALIFY_WEBHOOK_DSN": (
        "postgresql+psycopg://qualify_webhook:webhook_dev@localhost:5432/qualify_test"
    ),
    "QUALIFY_WEBHOOK_WORKER_DSN": (
        "postgresql+psycopg://qualify_webhook_worker:webhook_worker_dev@localhost:5432/qualify_test"
    ),
    "QUALIFY_CREATIVE_WORKER_DSN": (
        "postgresql+psycopg://qualify_creative_worker:creative_worker_dev@localhost:5432/qualify_test"
    ),
    "QUALIFY_CONNECTION_PURGE_DSN": (
        "postgresql+psycopg://qualify_connection_purge:connection_purge_dev@localhost:5432/qualify_test"
    ),
    "QUALIFY_MIGRATION_DSN": (
        "postgresql+psycopg://qualify_owner:dev_only@localhost:5432/qualify_test"
    ),
    REDIS_VAR: "redis://localhost:6379/15",
}

_SAFE_NAME = re.compile(r"^[a-z0-9_]+$")
_COMMENT_PREFIX = "qualify-test-migrations:"


class DbGuardError(RuntimeError):
    """A refusal: the run must stop, with this message."""


# -- configuration + guardrail --------------------------------------------------------


def apply_test_defaults(env: MutableMapping[str, str] | None = None) -> None:
    """Point every unset DSN / Redis URL at the test targets. A variable that is already
    set is kept — and then judged by `guard_problems`, never silently replaced."""
    env = os.environ if env is None else env
    for name, value in TEST_DEFAULTS.items():
        env.setdefault(name, value)


def _database(dsn: str) -> str | None:
    from sqlalchemy.engine import make_url  # noqa: PLC0415

    try:
        return make_url(dsn).database
    except Exception:  # noqa: BLE001 — an unparsable DSN is a guard failure, reported
        return None


def is_test_database(name: str | None) -> bool:
    return bool(
        name and name != DEV_DB_NAME and name.endswith(TEST_DB_SUFFIX) and _SAFE_NAME.match(name)
    )


def _redis_db(url: str) -> int | None:
    from urllib.parse import urlparse  # noqa: PLC0415

    path = urlparse(url).path.strip("/")
    if not path:
        return 0  # redis-py's default when the URL names no db
    return int(path) if path.isdigit() else None


def guard_problems(env: Mapping[str, str] | None = None) -> list[str]:
    """Every reason this configuration may NOT be used by tests. Empty = safe."""
    env = os.environ if env is None else env
    problems: list[str] = []
    names: set[str | None] = set()
    for var in DSN_VARS:
        dsn = env.get(var, "")
        name = _database(dsn)
        names.add(name)
        if not is_test_database(name):
            problems.append(
                f"{var} points at database {name!r}; tests may only use a database named "
                f"'*{TEST_DB_SUFFIX}' (never {DEV_DB_NAME!r})"
            )
    if len(names) > 1:
        problems.append(f"the DSNs disagree on the database: {sorted(map(str, names))}")
    redis_db = _redis_db(env.get(REDIS_VAR, ""))
    if redis_db is None or redis_db == 0:
        problems.append(
            f"{REDIS_VAR} uses Redis db {redis_db!r}; tests must use a non-zero db "
            "(default 15) — db 0 is the app's"
        )
    return problems


def require_safe(env: Mapping[str, str] | None = None) -> str:
    """The test database name, or `DbGuardError` listing every problem."""
    env = os.environ if env is None else env
    problems = guard_problems(env)
    if problems:
        raise DbGuardError(
            "Refusing to use this database configuration for tests:\n  - " + "\n  - ".join(problems)
        )
    name = _database(env["QUALIFY_MIGRATION_DSN"])
    assert name is not None  # guard_problems proved it
    return name


# -- migration fingerprint ----------------------------------------------------------------


def migration_hashes(directory: Path = MIGRATIONS_DIR) -> dict[str, str]:
    """sha256 per migration file (+ env.py), line endings normalised so a Windows and a
    macOS checkout of the same commit agree."""
    files = sorted((directory / "versions").glob("*.py")) + [directory / "env.py"]
    return {
        str(path.relative_to(directory)).replace("\\", "/"): hashlib.sha256(
            path.read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest()
        for path in files
    }


@dataclass(frozen=True)
class MigrationDiff:
    changed: tuple[str, ...]  # applied files whose content differs → edited in place
    removed: tuple[str, ...]  # applied files that no longer exist
    added: tuple[str, ...]  # new files → `upgrade head` applies them


def diff_migrations(stored: Mapping[str, str], current: Mapping[str, str]) -> MigrationDiff:
    return MigrationDiff(
        changed=tuple(sorted(f for f in stored if f in current and stored[f] != current[f])),
        removed=tuple(sorted(f for f in stored if f not in current)),
        added=tuple(sorted(f for f in current if f not in stored)),
    )


# -- Postgres operations (owner connection) --------------------------------------------


def _owner_engine(database: str):
    from sqlalchemy import create_engine  # noqa: PLC0415
    from sqlalchemy.engine import make_url  # noqa: PLC0415

    url = make_url(os.environ["QUALIFY_MIGRATION_DSN"]).set(database=database)
    return create_engine(url, isolation_level="AUTOCOMMIT", pool_pre_ping=True)


def _exists(name: str) -> bool:
    from sqlalchemy import text  # noqa: PLC0415

    engine = _owner_engine("postgres")
    try:
        with engine.connect() as conn:
            return bool(
                conn.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}
                ).scalar()
            )
    finally:
        engine.dispose()


def _stored_hashes(name: str) -> dict[str, str] | None:
    from sqlalchemy import text  # noqa: PLC0415

    engine = _owner_engine(name)
    try:
        with engine.connect() as conn:
            comment = conn.execute(
                text(
                    "SELECT shobj_description(oid, 'pg_database') FROM pg_database "
                    "WHERE datname = current_database()"
                )
            ).scalar()
    finally:
        engine.dispose()
    if not comment or not comment.startswith(_COMMENT_PREFIX):
        return None
    return json.loads(comment[len(_COMMENT_PREFIX) :])


def _store_hashes(name: str, hashes: Mapping[str, str]) -> None:
    from sqlalchemy import text  # noqa: PLC0415

    payload = (_COMMENT_PREFIX + json.dumps(dict(hashes), sort_keys=True)).replace("'", "''")
    engine = _owner_engine(name)
    try:
        with engine.connect() as conn:
            conn.execute(text(f"COMMENT ON DATABASE \"{name}\" IS '{payload}'"))
    finally:
        engine.dispose()


def _upgrade_head() -> None:
    """In a subprocess: alembic's env.py runs `logging.config.fileConfig`, which would
    reconfigure the test process's loggers."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        env=dict(os.environ),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise DbGuardError(f"alembic upgrade head failed on the test database:\n{result.stderr}")


def _flush_test_redis() -> None:
    import redis  # noqa: PLC0415

    url = os.environ[REDIS_VAR]
    db = _redis_db(url)
    if not db:  # re-checked here, right before the destructive call
        raise DbGuardError(f"refusing to FLUSHDB Redis db {db!r}")
    client = redis.Redis.from_url(url)
    try:
        client.flushdb()
    finally:
        client.close()


# -- the two entry points -----------------------------------------------------------------


def ensure() -> str:
    """Make the test database usable WITHOUT deleting anything: create it if missing,
    apply new migrations, refuse in-place edits. Returns a one-line status."""
    name = require_safe()
    current = migration_hashes()
    if not _exists(name):
        _create(name)
        _upgrade_head()
        _store_hashes(name, current)
        return f"{name}: created and migrated"
    stored = _stored_hashes(name)
    if stored is not None:
        diff = diff_migrations(stored, current)
        if diff.changed or diff.removed:
            raise DbGuardError(
                f"The migrations applied to {name} were modified in place "
                f"(changed: {list(diff.changed) or '-'}, removed: {list(diff.removed) or '-'}).\n"
                f"`alembic upgrade head` cannot re-run them, so {name} no longer matches the "
                "code. Nothing was reset — inspect its data first if you need to, then run:\n"
                "    just test-db-reset"
            )
    _upgrade_head()
    _store_hashes(name, current)
    added = diff_migrations(stored or {}, current).added if stored is not None else ()
    return f"{name}: up to date" + (f" (applied {len(added)} new)" if added else "")


def _create(name: str) -> None:
    if not is_test_database(name):
        raise DbGuardError(f"refusing to create {name!r}")
    engine = _owner_engine("postgres")
    try:
        with engine.connect() as conn:
            from sqlalchemy import text  # noqa: PLC0415

            role = conn.execute(text("SELECT current_user")).scalar()
            conn.execute(text(f'CREATE DATABASE "{name}" OWNER "{role}"'))
    finally:
        engine.dispose()


def reset() -> str:
    """DROP + CREATE + migrate the test database, FLUSHDB the test Redis db. The ONLY
    destructive operation, and only ever on a `*_test` database."""
    name = require_safe()
    # Belt and braces, right before the irreversible statement: the name is the one the
    # guard validated, never an argument, and it can never be the development database.
    if not is_test_database(name) or name == DEV_DB_NAME:
        raise DbGuardError(f"refusing to drop {name!r}")
    from sqlalchemy import text  # noqa: PLC0415

    engine = _owner_engine("postgres")
    try:
        with engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        engine.dispose()
    _create(name)
    _upgrade_head()
    _store_hashes(name, migration_hashes())
    _flush_test_redis()
    redis_db = _redis_db(os.environ[REDIS_VAR])
    return f"{name}: dropped, recreated and migrated; Redis db {redis_db} flushed"


def verify_live_connections() -> None:
    """The guard on the REAL connections: every sanctioned door, as the application code
    will open it, must land on the test database."""
    from uuid import uuid4  # noqa: PLC0415

    from qualify_shared.db.admin import admin_session  # noqa: PLC0415
    from qualify_shared.db.connection_purge import connection_purge_session  # noqa: PLC0415
    from qualify_shared.db.credential import credential_session  # noqa: PLC0415
    from qualify_shared.db.session import tenant_session  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415

    expected = require_safe()
    probe = uuid4()
    seen = {}
    with admin_session() as s:
        seen["admin_session"] = s.execute(text("SELECT current_database()")).scalar()
    with tenant_session(probe) as s:
        seen["tenant_session"] = s.execute(text("SELECT current_database()")).scalar()
    with credential_session(probe) as s:
        seen["credential_session"] = s.execute(text("SELECT current_database()")).scalar()
    with connection_purge_session(probe) as s:
        seen["connection_purge_session"] = s.execute(text("SELECT current_database()")).scalar()
    wrong = {door: db for door, db in seen.items() if db != expected}
    if wrong:
        raise DbGuardError(f"sanctioned DB doors are connected to the wrong database: {wrong}")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args not in (["reset"], ["ensure"]):
        print("usage: python testing/testdb.py reset|ensure", file=sys.stderr)
        return 2
    apply_test_defaults()
    try:
        print(reset() if args == ["reset"] else ensure())
    except DbGuardError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

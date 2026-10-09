"""Set the production passwords of the three application roles (run after migrations).

Migrations 0001/0002 create `qualify_app`, `qualify_admin` and `qualify_credential` with
the committed DEV passwords (`app_dev`, ...) so local compose and CI DSNs line up — and
document that any real environment rotates them out-of-band with `ALTER ROLE ... PASSWORD`.
This script is that out-of-band step, made repeatable: the `migrate` service runs it right
after `alembic upgrade head` on every deploy, so the roles always carry the passwords from
`/opt/qualify/.env.prod` and never the dev ones, even on a freshly created volume.

It connects as `qualify_owner` (the container's POSTGRES_USER, hence a superuser in the
`pgvector/pgvector:pg16` image) — the only role allowed to ALTER other roles. Idempotent:
re-running it with the same passwords is a no-op in effect.

Environment:
  QUALIFY_MIGRATION_DSN            owner DSN (same one Alembic uses)
  QUALIFY_DB_APP_PASSWORD          -> qualify_app
  QUALIFY_DB_ADMIN_PASSWORD        -> qualify_admin
  QUALIFY_DB_CREDENTIAL_PASSWORD   -> qualify_credential
"""

from __future__ import annotations

import os
import sys

import psycopg
from psycopg import sql

ROLE_PASSWORD_ENVS: dict[str, str] = {
    "qualify_app": "QUALIFY_DB_APP_PASSWORD",
    "qualify_admin": "QUALIFY_DB_ADMIN_PASSWORD",
    "qualify_credential": "QUALIFY_DB_CREDENTIAL_PASSWORD",
}
DEV_PASSWORDS = frozenset({"app_dev", "admin_dev", "credential_dev", "dev_only"})
MIN_PASSWORD_LENGTH = 16


def _libpq_dsn(sqlalchemy_dsn: str) -> str:
    """`postgresql+psycopg://...` (SQLAlchemy form) -> `postgresql://...` (libpq form)."""
    return sqlalchemy_dsn.replace("postgresql+psycopg://", "postgresql://", 1)


def _passwords_from_env() -> dict[str, str]:
    passwords: dict[str, str] = {}
    problems: list[str] = []
    for role, env in ROLE_PASSWORD_ENVS.items():
        value = os.environ.get(env, "")
        if len(value) < MIN_PASSWORD_LENGTH:
            problems.append(f"{env} is missing or shorter than {MIN_PASSWORD_LENGTH} chars")
        elif value in DEV_PASSWORDS:
            problems.append(f"{env} is a committed dev password")
        else:
            passwords[role] = value
    if problems:
        raise SystemExit("bootstrap_db_roles: " + "; ".join(problems))
    return passwords


def main() -> int:
    dsn = os.environ.get("QUALIFY_MIGRATION_DSN", "")
    if not dsn:
        raise SystemExit("bootstrap_db_roles: QUALIFY_MIGRATION_DSN is not set")
    passwords = _passwords_from_env()
    with psycopg.connect(_libpq_dsn(dsn), autocommit=True) as conn:
        for role, password in passwords.items():
            exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
            if exists is None:
                raise SystemExit(f"bootstrap_db_roles: role {role} does not exist — run migrations")
            conn.execute(
                sql.SQL("ALTER ROLE {} WITH PASSWORD {}").format(
                    sql.Identifier(role), sql.Literal(password)
                )
            )
            print(f"bootstrap_db_roles: password set for {role}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

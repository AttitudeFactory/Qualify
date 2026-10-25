"""Set the production passwords of the application roles (run after migrations).

Migrations 0001/0002 create `qualify_app`, `qualify_admin` and `qualify_credential`, and
0050 creates the Meta-webhook pair `qualify_webhook` / `qualify_webhook_worker`, with
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
  QUALIFY_DB_WEBHOOK_PASSWORD      -> qualify_webhook
  QUALIFY_DB_WEBHOOK_WORKER_PASSWORD -> qualify_webhook_worker
  QUALIFY_DB_CREATIVE_WORKER_PASSWORD -> qualify_creative_worker (OPTIONAL, see below)

0096 creates `qualify_creative_worker` (ADR 41, the generation queue's worker). Its
password is optional until that worker is deployed (m-24852163): while
QUALIFY_DB_CREATIVE_WORKER_PASSWORD is unset the role is made NOLOGIN, so the committed dev
password never opens a production login; once set, the role gets LOGIN + that password.
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
    "qualify_webhook": "QUALIFY_DB_WEBHOOK_PASSWORD",
    "qualify_webhook_worker": "QUALIFY_DB_WEBHOOK_WORKER_PASSWORD",
}
# Roles whose password may be absent: NOLOGIN until it is set (never the dev password).
OPTIONAL_ROLE_PASSWORD_ENVS: dict[str, str] = {
    "qualify_creative_worker": "QUALIFY_DB_CREATIVE_WORKER_PASSWORD",
}
DEV_PASSWORDS = frozenset(
    {
        "app_dev",
        "admin_dev",
        "credential_dev",
        "webhook_dev",
        "webhook_worker_dev",
        "creative_worker_dev",
        "dev_only",
    }
)
MIN_PASSWORD_LENGTH = 16


def _libpq_dsn(sqlalchemy_dsn: str) -> str:
    """`postgresql+psycopg://...` (SQLAlchemy form) -> `postgresql://...` (libpq form)."""
    return sqlalchemy_dsn.replace("postgresql+psycopg://", "postgresql://", 1)


def _password_problem(env: str, value: str) -> str | None:
    if len(value) < MIN_PASSWORD_LENGTH:
        return f"{env} is missing or shorter than {MIN_PASSWORD_LENGTH} chars"
    if value in DEV_PASSWORDS:
        return f"{env} is a committed dev password"
    return None


def _optional_passwords_from_env() -> dict[str, str | None]:
    """role -> password, or None when unset (the role is then made NOLOGIN). A value that
    IS set must still pass the same checks as a required one."""
    passwords: dict[str, str | None] = {}
    problems: list[str] = []
    for role, env in OPTIONAL_ROLE_PASSWORD_ENVS.items():
        value = os.environ.get(env, "")
        if not value:
            passwords[role] = None
        elif (problem := _password_problem(env, value)) is not None:
            problems.append(problem)
        else:
            passwords[role] = value
    if problems:
        raise SystemExit("bootstrap_db_roles: " + "; ".join(problems))
    return passwords


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
    optional = _optional_passwords_from_env()
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
        for role, password in optional.items():
            exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
            if exists is None:
                print(f"bootstrap_db_roles: role {role} not created yet — skipped")
                continue
            if password is None:
                conn.execute(sql.SQL("ALTER ROLE {} WITH NOLOGIN").format(sql.Identifier(role)))
                print(f"bootstrap_db_roles: {role} has no password set — NOLOGIN")
            else:
                conn.execute(
                    sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(
                        sql.Identifier(role), sql.Literal(password)
                    )
                )
                print(f"bootstrap_db_roles: password set for {role}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

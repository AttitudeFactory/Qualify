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
  QUALIFY_DB_REELS_WORKER_PASSWORD -> qualify_reels_worker (OPTIONAL, same rule; 0119)

0096 creates `qualify_creative_worker` (ADR 41, the generation queue's worker). Its
password is optional until that worker is deployed (m-24852163): while
QUALIFY_DB_CREATIVE_WORKER_PASSWORD is unset the role is made NOLOGIN, so the committed dev
password never opens a production login; once set, the role gets LOGIN + that password.
0119 creates `qualify_reels_worker` under the same rule.

Every password is validated first (whitespace stripped), then each role is applied on its
own: a valid password is set; a set-but-invalid one leaves that role untouched; an unset
OPTIONAL one turns its login off. The script exits non-zero at the end if any check failed,
so a bad value never takes down a role that already works.
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
    "qualify_connection_purge": "QUALIFY_DB_CONNECTION_PURGE_PASSWORD",
    # 0119 (ADR 44): the reels-worker's role; NOLOGIN until R8 deploys the service.
    "qualify_reels_worker": "QUALIFY_DB_REELS_WORKER_PASSWORD",
}
DEV_PASSWORDS = frozenset(
    {
        "app_dev",
        "admin_dev",
        "credential_dev",
        "webhook_dev",
        "webhook_worker_dev",
        "creative_worker_dev",
        "connection_purge_dev",
        "reels_worker_dev",
        "dev_only",
    }
)
MIN_PASSWORD_LENGTH = 16


def _libpq_dsn(sqlalchemy_dsn: str) -> str:
    """`postgresql+psycopg://...` (SQLAlchemy form) -> `postgresql://...` (libpq form)."""
    return sqlalchemy_dsn.replace("postgresql+psycopg://", "postgresql://", 1)


def _password_problem(env: str, value: str) -> str | None:
    # Judged without surrounding spaces: a padded dev password must not pass.
    stripped = value.strip()
    if len(stripped) < MIN_PASSWORD_LENGTH:
        return f"{env} is missing or shorter than {MIN_PASSWORD_LENGTH} chars"
    if stripped in DEV_PASSWORDS:
        return f"{env} is a committed dev password"
    return None


def _check_passwords(
    envs: dict[str, str], *, optional: bool
) -> tuple[dict[str, str | None], list[str]]:
    """role -> validated password, or None for an UNSET optional password; a role whose
    value is set but invalid is left out (never touched), with its problem recorded.
    Never raises: every role is judged, then applied independently by `apply`."""
    passwords: dict[str, str | None] = {}
    problems: list[str] = []
    for role, env in envs.items():
        value = os.environ.get(env, "")
        if optional and not value:
            passwords[role] = None
        elif (problem := _password_problem(env, value)) is not None:
            problems.append(problem)
        else:
            passwords[role] = value
    return passwords, problems


def _role_exists(conn: psycopg.Connection, role: str) -> bool:
    return conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone() is not None


def apply(conn: psycopg.Connection) -> list[str]:
    """Apply every role's password from the environment; return the problems (empty = ok).

    Each role is handled on its own, so one bad value never touches another role:
    - a value that is set but invalid (required or optional) -> that role is left as it is,
      and the run fails at the end;
    - required role with a valid password -> PASSWORD set;
    - optional role with a valid password -> LOGIN + PASSWORD; UNSET -> NOLOGIN (the
      committed dev password must never open a production login).
    """
    required, problems = _check_passwords(ROLE_PASSWORD_ENVS, optional=False)
    optional, optional_problems = _check_passwords(OPTIONAL_ROLE_PASSWORD_ENVS, optional=True)
    problems += optional_problems
    for role in ROLE_PASSWORD_ENVS:
        if not _role_exists(conn, role):
            problems.append(f"role {role} does not exist — run migrations")
            continue
        password = required.get(role)
        if password is None:
            continue
        conn.execute(
            sql.SQL("ALTER ROLE {} WITH PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(password)
            )
        )
        print(f"bootstrap_db_roles: password set for {role}")
    for role, password in optional.items():
        if not _role_exists(conn, role):
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
    return problems


def main() -> int:
    dsn = os.environ.get("QUALIFY_MIGRATION_DSN", "")
    if not dsn:
        raise SystemExit("bootstrap_db_roles: QUALIFY_MIGRATION_DSN is not set")
    with psycopg.connect(_libpq_dsn(dsn), autocommit=True) as conn:
        problems = apply(conn)
    if problems:
        raise SystemExit("bootstrap_db_roles: " + "; ".join(problems))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Alembic environment for Qualify's Postgres plane (ADR 27).

Migrations run as `qualify_owner` (object owner + the only role that runs DDL).
The DSN comes from `QUALIFY_MIGRATION_DSN`; the default targets the local
docker-compose Postgres as `qualify_owner`. RLS, roles and `FORCE ROW LEVEL
SECURITY` are hand-written in each revision's `op.execute()` — there is no ORM
metadata to autogenerate against, so `target_metadata` stays None on purpose.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# DDL is written by hand (RLS/roles/policies are invisible to autogenerate), so
# there is deliberately no target metadata.
target_metadata = None

# Owner DSN: env override for CI/prod, local compose default for `just dev`.
DEFAULT_MIGRATION_DSN = "postgresql+psycopg://qualify_owner:dev_only@localhost:5432/qualify"
_dsn = os.environ.get("QUALIFY_MIGRATION_DSN", DEFAULT_MIGRATION_DSN)
config.set_main_option("sqlalchemy.url", _dsn)


def run_migrations_offline() -> None:
    """Emit SQL without a live connection (`alembic upgrade head --sql`)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the live owner connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

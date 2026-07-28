"""tenancy foundation: tenants/users/tenant_members/brands + 3 roles + RLS (C-01)

Revision ID: 0001
Revises:
Create Date: 2026-07-25

Creates the multi-tenant foundation in ONE reversible revision (ruling: RLS ships in the
same migration that creates each table). Runs as `qualify_owner`. RLS, roles, FORCE ROW
LEVEL SECURITY and GRANTs are hand-written SQL — autogenerate never sees them.

The isolation guarantee rests ONLY on `qualify_app` (subject to RLS): `qualify_owner` is
the object owner (and superuser in dev/CI, so it bypasses RLS — but it runs no runtime
queries), and `qualify_admin` has BYPASSRLS for provisioning/seed. A structural test
pins `rolsuper=false AND rolbypassrls=false` on `qualify_app`.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Dev/CI passwords — mirrored by the DSNs in docker-compose/CI. Production rotates these
# out-of-band with `ALTER ROLE ... PASSWORD` (never committed).
_APP_PASSWORD = "app_dev"
_ADMIN_PASSWORD = "admin_dev"

_BUSINESS_TABLES = ("tenants", "users", "tenant_members", "brands")


def _create_roles() -> None:
    # Roles are cluster-global, so CREATE ROLE is NOT idempotent — guard each one, so a
    # second `upgrade` (or a shared cluster) does not error.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'qualify_app') THEN
                CREATE ROLE qualify_app LOGIN PASSWORD '{_APP_PASSWORD}'
                    NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
            END IF;
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'qualify_admin') THEN
                CREATE ROLE qualify_admin LOGIN PASSWORD '{_ADMIN_PASSWORD}'
                    NOSUPERUSER BYPASSRLS NOCREATEDB NOCREATEROLE;
            END IF;
        END
        $$;
        """
    )


def _grant_runtime_privileges() -> None:
    # Neither runtime role owns the tables; both get DML only (never OWNER). `qualify_app`
    # is the request path; `qualify_admin` (BYPASSRLS) runs the seed/provisioning, so it
    # also needs INSERT.
    op.execute("GRANT USAGE ON SCHEMA public TO qualify_app, qualify_admin;")
    for table in _BUSINESS_TABLES:
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO qualify_app, qualify_admin;"
        )


def _enable_rls(table: str, *, key_column: str) -> None:
    # ENABLE turns policies on; FORCE also subjects the table OWNER (Postgres exempts the
    # owner by default → "there are policies" vs "the policies protect"). WITH CHECK blocks
    # writing another tenant's row, not just reading it.
    #
    # NULLIF is load-bearing (R7). A custom GUC stays DEFINED for the life of the session
    # once set; ending the transaction reverts `set_config(..., is_local => true)` to the
    # placeholder's *reset value*, which is the empty string — not "undefined". So on a
    # reused pooled connection `current_setting('app.tenant_id', true)` yields `''`, and a
    # bare `''::uuid` raises `invalid input syntax for type uuid` instead of failing closed.
    # NULL only ever occurs on a pristine physical connection. `NULLIF(..., '')` maps both
    # regimes to NULL → `key = NULL` is NULL → row filtered → fail-closed (zero rows, no
    # error, no leak).
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {table}
            USING ({key_column} = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK ({key_column} = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
    _create_roles()

    op.create_table(
        "tenants",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("country", sa.Text(), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_table(
        "users",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    )
    op.create_index("ix_users_tenant", "users", ["tenant_id"])

    op.create_table(
        "tenant_members",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('owner','admin','agent','viewer')", name="ck_members_role"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_members_tenant_user"),
    )
    op.create_index("ix_members_tenant", "tenant_members", ["tenant_id"])

    op.create_table(
        "brands",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_brands_tenant", "brands", ["tenant_id"])

    _grant_runtime_privileges()

    # RLS in the same revision that creates each table. `tenants` compares against its PK.
    _enable_rls("tenants", key_column="id")
    _enable_rls("users", key_column="tenant_id")
    _enable_rls("tenant_members", key_column="tenant_id")
    _enable_rls("brands", key_column="tenant_id")


def downgrade() -> None:
    # Reverse order, clean enough for `alembic downgrade base`. Dropping a table drops its
    # policies; then strip the roles' remaining privileges and drop them (guarded, since
    # roles are cluster-global). `qualify_owner` is NOT dropped — it is the compose user.
    op.drop_index("ix_brands_tenant", table_name="brands")
    op.drop_table("brands")
    op.drop_index("ix_members_tenant", table_name="tenant_members")
    op.drop_table("tenant_members")
    op.drop_index("ix_users_tenant", table_name="users")
    op.drop_table("users")
    op.drop_table("tenants")

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'qualify_app') THEN
                REVOKE ALL ON SCHEMA public FROM qualify_app;
                DROP OWNED BY qualify_app;
                DROP ROLE qualify_app;
            END IF;
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'qualify_admin') THEN
                REVOKE ALL ON SCHEMA public FROM qualify_admin;
                DROP OWNED BY qualify_admin;
                DROP ROLE qualify_admin;
            END IF;
        END
        $$;
        """
    )

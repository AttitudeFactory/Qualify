"""connections: platform_apps (global) + social_connections + oauth_credentials +
connection_events, with R1/R2/R3 (C-03)

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-25

R1: `platform_apps` is GLOBAL (no tenant_id, no RLS) — Qualify's own Meta apps; SELECT to
    qualify_app, writes by admin/owner. `social_connections.platform_app_id` is provenance.
R2: `oauth_credentials`/`connection_events` carry denormalized `tenant_id` with a COMPOSITE
    FK to `social_connections(id, tenant_id)` (which gains `UNIQUE(id, tenant_id)`), so a
    mismatched tenant is structurally unbuildable — plus a local-column RLS policy.
R3: column-level GRANTs — `qualify_app` gets SELECT on every column of `oauth_credentials`
    EXCEPT `ciphertext`/`key_id` (a table grant would supersede column grants, so it gets
    none) + INSERT (append-only, no UPDATE/DELETE). The narrow `qualify_credential` role
    gets SELECT on `ciphertext`/`key_id` only. Both roles are NOSUPERUSER NOBYPASSRLS.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_CREDENTIAL_PASSWORD = "credential_dev"

# qualify_app may read every oauth_credentials column EXCEPT the secret ones.
_APP_CRED_COLUMNS = (
    "id",
    "connection_id",
    "tenant_id",
    "version",
    "token_type",
    "issued_at",
    "expires_at",
    "created_at",
)
# qualify_credential may read ONLY what it needs to decrypt.
_CREDENTIAL_COLUMNS = ("ciphertext", "key_id", "connection_id", "tenant_id", "version")


def _enable_tenant_rls(table: str, *, key_column: str = "tenant_id") -> None:
    # NULLIF is load-bearing (R7) — see the long note on 0001's `_enable_rls`. A custom GUC
    # reverts to the empty string (its reset value), not to undefined, when the transaction
    # that `set_config`'d it ends; without NULLIF a reused pooled connection raises
    # `invalid input syntax for type uuid: ""` instead of failing closed.
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
    # Narrow decryption role (R3). RLS-subject like qualify_app → decrypts only in-tenant.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'qualify_credential') THEN
                CREATE ROLE qualify_credential LOGIN PASSWORD '{_CREDENTIAL_PASSWORD}'
                    NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
            END IF;
        END
        $$;
        """
    )
    op.execute("GRANT USAGE ON SCHEMA public TO qualify_credential;")

    # --- platform_apps: GLOBAL, no tenant_id, no RLS (R1) ---
    op.create_table(
        "platform_apps",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("app_id", sa.Text(), nullable=False),
        sa.Column("secret_ref", sa.Text(), nullable=False),
        sa.Column("api_version", sa.Text(), nullable=False),
        sa.Column("config_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.execute("GRANT SELECT ON platform_apps TO qualify_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE ON platform_apps TO qualify_admin;")

    # --- social_connections: tenant-scoped + RLS; UNIQUE(id, tenant_id) anti-drift (R2) ---
    op.create_table(
        "social_connections",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("brand_id", PGUUID(as_uuid=True), sa.ForeignKey("brands.id"), nullable=True),
        sa.Column(
            "platform_app_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("platform_apps.id"),
            nullable=False,
        ),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("account_type", sa.Text(), nullable=False),
        sa.Column("external_account_id", sa.Text(), nullable=False),
        sa.Column("external_username", sa.Text(), nullable=True),
        sa.Column("linked_page_id", sa.Text(), nullable=False),
        sa.Column("granted_scopes", ARRAY(sa.Text()), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        # ADR 22(a): the app's access level is DATA, not a hardcoded constant — customer
        # zero runs under Development Mode while Advanced Access is still pending, and the
        # same code must serve both once it lands.
        sa.Column("access_posture", sa.Text(), nullable=False),
        sa.Column("current_credential_version", sa.Integer(), nullable=False),
        sa.Column(
            "connected_by_user_id", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "connected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "tenant_id", "platform", "external_account_id", name="uq_conn_natural_key"
        ),
        sa.UniqueConstraint("id", "tenant_id", name="uq_conn_id_tenant"),
        sa.CheckConstraint(
            "access_posture IN ('development','live')", name="ck_conn_access_posture"
        ),
    )
    op.create_index("ix_conn_tenant", "social_connections", ["tenant_id"])
    op.execute("GRANT SELECT, INSERT, UPDATE ON social_connections TO qualify_app;")
    op.execute("GRANT SELECT ON social_connections TO qualify_admin;")
    _enable_tenant_rls("social_connections")

    # --- oauth_credentials: append-only, composite FK, column-level grants (R2/R3) ---
    op.create_table(
        "oauth_credentials",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("connection_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("token_type", sa.Text(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("key_id", sa.Text(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("connection_id", "version", name="uq_cred_conn_version"),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_cred_conn_tenant",
        ),
    )
    op.create_index("ix_cred_tenant", "oauth_credentials", ["tenant_id"])
    # NO table-level SELECT to qualify_app (it would supersede the column grant). Column
    # SELECT excludes ciphertext/key_id; INSERT is table-level (append-only, no UPDATE/DELETE).
    op.execute(
        f"GRANT SELECT ({', '.join(_APP_CRED_COLUMNS)}) ON oauth_credentials TO qualify_app;"
    )
    op.execute("GRANT INSERT ON oauth_credentials TO qualify_app;")
    _cred_cols = ", ".join(_CREDENTIAL_COLUMNS)
    op.execute(f"GRANT SELECT ({_cred_cols}) ON oauth_credentials TO qualify_credential;")
    _enable_tenant_rls("oauth_credentials")

    # --- connection_events: append-only audit, composite FK, RLS ---
    op.create_table(
        "connection_events",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("connection_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("credential_version", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("platform_error_code", sa.Text(), nullable=True),
        sa.Column("raw_response_r2_key", sa.Text(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_event_conn_tenant",
        ),
    )
    op.create_index("ix_event_tenant", "connection_events", ["tenant_id"])
    op.execute("GRANT SELECT, INSERT ON connection_events TO qualify_app;")
    op.execute("GRANT SELECT ON connection_events TO qualify_admin;")
    _enable_tenant_rls("connection_events")


def downgrade() -> None:
    op.drop_index("ix_event_tenant", table_name="connection_events")
    op.drop_table("connection_events")
    op.drop_index("ix_cred_tenant", table_name="oauth_credentials")
    op.drop_table("oauth_credentials")
    op.drop_index("ix_conn_tenant", table_name="social_connections")
    op.drop_table("social_connections")
    op.drop_table("platform_apps")

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'qualify_credential') THEN
                REVOKE ALL ON SCHEMA public FROM qualify_credential;
                DROP OWNED BY qualify_credential;
                DROP ROLE qualify_credential;
            END IF;
        END
        $$;
        """
    )

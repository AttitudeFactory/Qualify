"""business_open_audit: one row each time a login opens a business (m-24849192, S5)

Revision ID: 0113
Revises: 0112
Create Date: 2026-11-02

ADR 43 (§2.2, A15; F5 signed 2026-10-25): one login may own several businesses and
move between them without logging out. Every time a session opens a business — picking
it in the selector after login (S3) or switching to it from another one (S4) — the
server writes a row here, **in the destination tenant**: who (`auth_user_id`, the
provider's id, plus the local `users.id` of that business), from which tenant (or none,
right after login), how (`login` / `switch`) and when.

The row lives in the destination tenant and is RLS-scoped like every other tenant table,
so the origin business never sees where its owner went next; `from_tenant_id` is a bare
id (no FK: it names another tenant and is never joined). Append-only: the application
role gets SELECT + INSERT, nothing else. There is no screen for it yet (out of scope).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0113"
down_revision = "0112"
branch_labels = None
depends_on = None

_TABLE = "business_open_audit"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "tenant_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("auth_user_id", PGUUID(as_uuid=True), nullable=False),
        # SET NULL, not CASCADE: if a seat's local user is ever deleted, its trail stays
        # (`auth_user_id` still names the login).
        sa.Column(
            "user_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("from_tenant_id", PGUUID(as_uuid=True), nullable=True),
        sa.Column("via", sa.Text(), nullable=False),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("via IN ('login', 'switch')", name="ck_business_open_audit_via"),
        sa.CheckConstraint(
            "from_tenant_id IS NULL OR from_tenant_id <> tenant_id",
            name="ck_business_open_audit_from_other",
        ),
    )
    op.create_index("ix_business_open_audit_tenant", _TABLE, ["tenant_id", "opened_at"])
    op.execute(f"GRANT SELECT, INSERT ON {_TABLE} TO qualify_app;")
    # Append-only for everyone: the tenant FK cascade needs no DELETE grant.
    op.execute(f"GRANT SELECT ON {_TABLE} TO qualify_admin;")
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {_TABLE}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )


def downgrade() -> None:
    op.drop_index("ix_business_open_audit_tenant", table_name=_TABLE)
    op.drop_table(_TABLE)

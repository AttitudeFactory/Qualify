"""brand_kit_drafts: the Brand Kit before an account exists

Revision ID: 0037
Revises: 0036
Create Date: 2026-10-02

§ request 2026-10-02: "quiero que [el brandkit] aparezca antes del login, que se pueda
usar sin necesidad de iniciar sesión pero que siga guardando los datos ... como primera
view se le pida el correo para guardar el brandkit a ese correo y al momento de que se
cree la cuenta con su correo ya tiene el brandkit desde antes".

The email asked for on that first view provisions a tenant on the spot — a `tenants`
row, a login-less owner `users` row (`auth_user_id` NULL, the "seat without a login"
0008 already allows), its `tenant_members` seat and a `brands` row — so the wizard writes
through `tenant_session` exactly as it does for a logged-in tenant, RLS included. Nothing
in the Brand Kit's tables changes. This table is the only new thing: which email such a
draft tenant was provisioned for, so that (a) typing the same email again resumes it and
(b) the signup with that email adopts the tenant instead of minting a fresh one
(`qualify_api.auth.drafts`). `claimed_at` marks the adoption; a claimed draft is an
account and is never resumed by email again.

`email_key` is the lowercased, trimmed email — the lookup key. `email` keeps what was
typed. It carries a `tenant_id`, so it gets the standard isolation policy like every
tenant-owned table (`test_rls_policy_shape`); in practice only `qualify_admin` (BYPASSRLS,
provisioning) reads or writes it — the lookup by email is cross-tenant by nature.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def _enable_tenant_rls(table: str) -> None:
    # NULLIF is load-bearing (R7) — see 0001's `_enable_rls`.
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )


def upgrade() -> None:
    op.create_table(
        "brand_kit_drafts",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("email_key", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("email_key", name="uq_brand_kit_drafts_email_key"),
        sa.UniqueConstraint("tenant_id", name="uq_brand_kit_drafts_tenant"),
        sa.CheckConstraint(
            "email_key <> '' AND email_key = lower(btrim(email_key))",
            name="ck_brand_kit_drafts_email_key",
        ),
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON brand_kit_drafts TO qualify_admin;")
    op.execute("GRANT SELECT ON brand_kit_drafts TO qualify_app;")
    _enable_tenant_rls("brand_kit_drafts")


def downgrade() -> None:
    op.drop_table("brand_kit_drafts")

"""social_account_claims: a brand's own Instagram / TikTok account belongs to one brand

Revision ID: 0044
Revises: 0043
Create Date: 2026-10-06

§ request 2026-10-06: "quiero que cuando otra cuenta intente scrapear las redes de una
cuenta que ya está registrada no pueda, ya que estos datos son sensibles y no deberían
compartirse — ejemplo a@gmail.com se registró con su user de Instagram y b@gmail.com
quiere usar el user de Instagram de a@gmail.com".

One row per (network, account) a brand took as ITS OWN in the Brand Kit's Tu cuenta
(`qualify_api.creative.account_claims`). Two properties carry the whole feature:

- `UNIQUE(network, handle_key)` is global: Postgres enforces it across every tenant, RLS
  or not. That is how a second tenant learns "taken" — its `INSERT … ON CONFLICT DO
  NOTHING` inserts nothing — without ever reading the other tenant's row. No
  `admin_session` on the request path, no SECURITY DEFINER function, no second policy:
  the table keeps the one standard `tenant_isolation` policy (`test_rls_policy_shape`).
- `handle_key` is the lookup form (`strip().lstrip("@").strip().lower()`), the one every
  profile cache in this repo uses plus a second strip, so "@MiduDev" and "midudev" are
  one account.

Backfill: the accounts Brand Kits already saved (`brand_kit_details.connect`'s `network`
+ `username`). When several tenants saved the same account, a REGISTERED tenant (no
draft row, or a claimed one — 0037) wins over a pre-login draft, then the oldest kit.
The others keep their saved answers but lose the account: their next read of it is
refused. Runs as `qualify_owner`, the superuser in dev, CI and production
(`deploy/bootstrap_db_roles.py`), so it reads across tenants despite FORCE RLS.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None

_HANDLE_KEY_CHECK = (
    "handle_key <> '' AND handle_key = lower(btrim(handle_key)) AND left(handle_key, 1) <> '@'"
)


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
        "social_account_claims",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("brand_id", PGUUID(as_uuid=True), sa.ForeignKey("brands.id"), nullable=False),
        sa.Column("network", sa.Text(), nullable=False),
        sa.Column("handle_key", sa.Text(), nullable=False),
        sa.Column("handle", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("network", "handle_key", name="uq_social_account_claims_account"),
        sa.CheckConstraint(
            "network IN ('instagram','tiktok')", name="ck_social_account_claims_network"
        ),
        sa.CheckConstraint(_HANDLE_KEY_CHECK, name="ck_social_account_claims_handle_key"),
    )
    op.create_index(
        "ix_social_account_claims_tenant", "social_account_claims", ["tenant_id", "brand_id"]
    )
    op.execute("GRANT SELECT, INSERT, DELETE ON social_account_claims TO qualify_app;")
    _enable_tenant_rls("social_account_claims")

    op.execute(
        f"""
        INSERT INTO social_account_claims
            (tenant_id, brand_id, network, handle_key, handle, created_at)
        SELECT DISTINCT ON (network, handle_key)
               tenant_id, brand_id, network, handle_key, handle, created_at
        FROM (
            SELECT d.tenant_id,
                   d.brand_id,
                   d.connect ->> 'network' AS network,
                   lower(btrim(ltrim(btrim(d.connect ->> 'username'), '@'))) AS handle_key,
                   btrim(d.connect ->> 'username') AS handle,
                   d.created_at,
                   (dr.id IS NOT NULL AND dr.claimed_at IS NULL) AS unregistered
            FROM brand_kit_details d
            LEFT JOIN brand_kit_drafts dr ON dr.tenant_id = d.tenant_id
            WHERE d.connect ->> 'network' IN ('instagram', 'tiktok')
        ) saved
        WHERE {_HANDLE_KEY_CHECK}
        ORDER BY network, handle_key, unregistered, created_at
        ON CONFLICT DO NOTHING;
        """
    )


def downgrade() -> None:
    op.drop_index("ix_social_account_claims_tenant", table_name="social_account_claims")
    op.drop_table("social_account_claims")

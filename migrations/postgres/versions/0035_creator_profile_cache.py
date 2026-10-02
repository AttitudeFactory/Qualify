"""referentes: the profile cache in Postgres, the full bio and the external link

Revision ID: 0035
Revises: 0034
Create Date: 2026-10-01

Three things the founder asked for on 2026-10-01 ("no quiero más json", "la bio
completa", and a visual mark for AI / non-organic profiles — the mark itself travels
inside `card`, no column needed):

## creator_profile_cache

The brand's OWN account as the Brand Kit read it (profile + the week's posts), per
tenant, with a time to live of 7 days — replacing the one global JSON snapshot under
`Qualify/fixtures/` that every session wrote over (`brand_connect_profile.json`, the
cross-tenant race `test_brand_connect_flow` used to guard against). One row per
`(tenant, network, handle, kind)`; `kind` is `'snapshot'` today (the column stays so a
second per-tenant kind can join without a migration). `expires_at` is the time to live;
nothing is served past it. The profile reads the referentes SEARCH makes are not here:
they are public data and live in the shared pool (0036, `vendor_payloads` / `creators`).

## brand_discovered_accounts.bio / external_url

The account's bio in full (the card used to keep a 110-character blurb, losing the web
addresses and contacts a bio carries) and the link the profile points at.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None

_HANDLE_CHECK = "handle <> '' AND handle = lower(handle) AND left(handle, 1) <> '@'"


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
        "creator_profile_cache",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("network", sa.Text(), nullable=False),
        sa.Column("handle", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("document", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("missing", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id", "network", "handle", "kind", name="uq_creator_profile_cache"
        ),
        sa.CheckConstraint(
            "network IN ('tiktok','instagram')", name="ck_creator_profile_cache_network"
        ),
        sa.CheckConstraint(_HANDLE_CHECK, name="ck_creator_profile_cache_handle_normalized"),
        sa.CheckConstraint("kind IN ('snapshot')", name="ck_creator_profile_cache_kind"),
        sa.CheckConstraint("expires_at > fetched_at", name="ck_creator_profile_cache_ttl"),
    )
    op.create_index(
        "ix_creator_profile_cache_expires", "creator_profile_cache", ["tenant_id", "expires_at"]
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON creator_profile_cache TO qualify_app;")
    _enable_tenant_rls("creator_profile_cache")

    op.add_column(
        "brand_discovered_accounts",
        sa.Column("bio", sa.Text(), server_default="", nullable=False),
    )
    op.add_column(
        "brand_discovered_accounts",
        sa.Column("external_url", sa.Text(), server_default="", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("brand_discovered_accounts", "external_url")
    op.drop_column("brand_discovered_accounts", "bio")
    op.drop_index("ix_creator_profile_cache_expires", table_name="creator_profile_cache")
    op.drop_table("creator_profile_cache")

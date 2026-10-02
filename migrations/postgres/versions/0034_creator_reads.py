"""growth: every creator read kept, so a series exists

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-01

No vendor sells a creator's history (`docs/scrapecreators-crecimiento-organico-y-contenido-ia.md`
§2): Scrape Creators answers with today's figures only, and until now every read was
written over the previous one (the JSON snapshot, the discovery's profile cache). A
growth figure — let alone an organic one — needs two reads apart in time, so from here
on every read is a row, never an update.

## creator_reads

One row per read of a creator's profile: followers / following / posts / total likes at
`fetched_at`, from `source` (`profile` = the Brand Kit's own-account read, `discovery` =
a referente seen by the search). Append-only; `(tenant, platform, handle, fetched_at)`
is the series.

## creator_post_reads

One row per read of one post: its counters at `fetched_at`, plus the platform's own
"made with AI" label as read that day (`ai_generated` NULL = nothing said either way,
never "not AI"; `ai_label` = who labelled it, `ai_source` = what C2PA named). The
curve of a post is its rows ordered by `fetched_at`.

Both are tenant-scoped (RLS as in 0001): what a tenant read is that tenant's data,
even when two tenants read the same public creator.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0034"
down_revision = "0033"
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
        "creator_reads",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("handle", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("followers", sa.BigInteger(), nullable=True),
        sa.Column("following", sa.BigInteger(), nullable=True),
        sa.Column("posts_count", sa.BigInteger(), nullable=True),
        sa.Column("total_likes", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("platform IN ('tiktok','instagram')", name="ck_creator_read_platform"),
        sa.CheckConstraint(_HANDLE_CHECK, name="ck_creator_read_handle_normalized"),
        sa.CheckConstraint("source IN ('profile','discovery')", name="ck_creator_read_source"),
    )
    op.create_index(
        "ix_creator_reads_series",
        "creator_reads",
        ["tenant_id", "platform", "handle", "fetched_at"],
    )
    op.execute("GRANT SELECT, INSERT ON creator_reads TO qualify_app;")
    _enable_tenant_rls("creator_reads")

    op.create_table(
        "creator_post_reads",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("handle", sa.Text(), nullable=False),
        sa.Column("post_id", sa.Text(), nullable=False),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("views", sa.BigInteger(), nullable=True),
        sa.Column("likes", sa.BigInteger(), nullable=True),
        sa.Column("comments", sa.BigInteger(), nullable=True),
        sa.Column("shares", sa.BigInteger(), nullable=True),
        sa.Column("ai_generated", sa.Boolean(), nullable=True),
        sa.Column("ai_label", sa.Text(), server_default="", nullable=False),
        sa.Column("ai_source", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "platform IN ('tiktok','instagram')", name="ck_creator_post_read_platform"
        ),
        sa.CheckConstraint(_HANDLE_CHECK, name="ck_creator_post_read_handle_normalized"),
        sa.CheckConstraint("post_id <> ''", name="ck_creator_post_read_post_id"),
    )
    op.create_index(
        "ix_creator_post_reads_series",
        "creator_post_reads",
        ["tenant_id", "platform", "handle", "post_id", "fetched_at"],
    )
    op.execute("GRANT SELECT, INSERT ON creator_post_reads TO qualify_app;")
    _enable_tenant_rls("creator_post_reads")


def downgrade() -> None:
    op.drop_index("ix_creator_post_reads_series", table_name="creator_post_reads")
    op.drop_table("creator_post_reads")
    op.drop_index("ix_creator_reads_series", table_name="creator_reads")
    op.drop_table("creator_reads")

"""tiktok: draft uploads to the creator's TikTok inbox + TikTok connections without a Page

Revision ID: 0109
Revises: 0108
Create Date: 2026-11-02

m-24921091 (native TikTok integration, founder-approved scope). Two changes:

1. `social_connections.linked_page_id` was conditional on the platform since 0057 (only
   WhatsApp had no Facebook Page). A TikTok account has none either, so the CHECK
   `ck_conn_linked_page_by_platform` now exempts `whatsapp` AND `tiktok`; ADR 25's guarantee
   for Instagram/Facebook rows is untouched. No new enum: `platform`/`account_type` are
   free text, as for WhatsApp.
2. `tiktok_drafts` — the write-ahead record of one draft sent to the TikTok inbox via the
   Content Posting API (`/v2/post/publish/inbox/video/init/`). It is its own table, not a
   `publish_attempts` row: that table's `media_product_type` / container / `media_publish`
   vocabulary is Meta's, and TikTok has a different lifecycle (init -> chunk PUTs -> status
   fetch). Drafts only: there is no scheduled or direct-post state (ADR 21(d)/23(c)).
   - Idempotency: `UNIQUE (connection_id, idempotency_key)`; the service derives the key from
     (post, approved revision), so a double click never puts two drafts in the creator's inbox.
   - Provenance: `post_id` + `approved_revision` (which approved content was sent),
     `adapter_version` (which adapter wrote it), `publish_id` (TikTok's own id).
   - Settle-once trigger like `publish_attempts` (0003): a terminal outcome is final.
   - Tenant isolation: `tenant_id NOT NULL`, composite FK to the connection, RLS ENABLE+FORCE
     with the NULLIF policy.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0109"
down_revision = "0108"
branch_labels = None
depends_on = None

_SETTLE_ONCE = """
CREATE OR REPLACE FUNCTION tiktok_drafts_settle_once() RETURNS trigger AS $$
BEGIN
    IF OLD.settled_at IS NOT NULL THEN
        RAISE EXCEPTION
            'tiktok_drafts %: already settled at %, refusing to overwrite a terminal outcome',
            OLD.id, OLD.settled_at
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.execute("ALTER TABLE social_connections DROP CONSTRAINT ck_conn_linked_page_by_platform;")
    op.execute(
        "ALTER TABLE social_connections ADD CONSTRAINT ck_conn_linked_page_by_platform "
        "CHECK ((platform IN ('whatsapp','tiktok')) OR (linked_page_id IS NOT NULL));"
    )

    op.create_table(
        "tiktok_drafts",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("post_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("output_port", sa.Text(), nullable=True),
        sa.Column("approved_revision", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("upload_mode", sa.Text(), nullable=False),
        sa.Column("media_object_key", sa.Text(), nullable=False),
        sa.Column("video_bytes", sa.BigInteger(), nullable=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("publish_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("platform_error_code", sa.Text(), nullable=True),
        sa.Column("adapter_version", sa.Text(), nullable=False),
        sa.Column(
            "created_by_user_id", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("connection_id", "idempotency_key", name="uq_tiktok_draft_idem"),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_tiktok_draft_conn_tenant",
        ),
        sa.CheckConstraint(
            "status IN ('pending','uploading','processing','in_inbox','failed')",
            name="ck_tiktok_draft_status",
        ),
        sa.CheckConstraint(
            "upload_mode IN ('FILE_UPLOAD','PULL_FROM_URL')", name="ck_tiktok_draft_mode"
        ),
        sa.CheckConstraint(
            "(settled_at IS NULL) = (status NOT IN ('in_inbox','failed'))",
            name="ck_tiktok_draft_settled_matches_status",
        ),
    )
    op.create_index("ix_tiktok_draft_tenant", "tiktok_drafts", ["tenant_id"])
    op.create_index("ix_tiktok_draft_post", "tiktok_drafts", ["tenant_id", "post_id"])
    op.execute("GRANT SELECT, INSERT, UPDATE ON tiktok_drafts TO qualify_app;")
    op.execute("GRANT SELECT ON tiktok_drafts TO qualify_admin;")
    op.execute("ALTER TABLE tiktok_drafts ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE tiktok_drafts FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON tiktok_drafts
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )
    op.execute(_SETTLE_ONCE)
    op.execute(
        """
        CREATE TRIGGER tiktok_drafts_settle_once
            BEFORE UPDATE ON tiktok_drafts
            FOR EACH ROW EXECUTE FUNCTION tiktok_drafts_settle_once();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS tiktok_drafts_settle_once ON tiktok_drafts;")
    op.execute("DROP FUNCTION IF EXISTS tiktok_drafts_settle_once();")
    op.drop_index("ix_tiktok_draft_post", table_name="tiktok_drafts")
    op.drop_index("ix_tiktok_draft_tenant", table_name="tiktok_drafts")
    op.drop_table("tiktok_drafts")
    # Non-destructive: keep any TikTok connection rows, just satisfy the old CHECK.
    op.execute(
        "UPDATE social_connections SET linked_page_id = '' "
        "WHERE platform = 'tiktok' AND linked_page_id IS NULL;"
    )
    op.execute("ALTER TABLE social_connections DROP CONSTRAINT ck_conn_linked_page_by_platform;")
    op.execute(
        "ALTER TABLE social_connections ADD CONSTRAINT ck_conn_linked_page_by_platform "
        "CHECK ((platform = 'whatsapp') OR (linked_page_id IS NOT NULL));"
    )

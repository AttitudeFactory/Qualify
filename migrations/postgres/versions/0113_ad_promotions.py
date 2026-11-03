"""Durable paused promotion creation and per-step claims (m-24828974).

Revision ID: 0113
Revises: 0112

meta_ad_account_id is a remote numeric snapshot, not the future local ad_accounts
FK of m-24828972. This revision does not authorize or connect advertising accounts.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0113"
down_revision = "0112"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table, columns, name in (
        ("brands", ["id", "tenant_id"], "uq_ads_brand_tenant"),
        ("content_drafts", ["id", "tenant_id", "brand_id"], "uq_ads_draft_tenant_brand"),
        ("publish_attempts", ["id", "tenant_id"], "uq_ads_publish_tenant"),
        ("users", ["id", "tenant_id"], "uq_ads_user_tenant"),
    ):
        op.create_unique_constraint(name, table, columns)
    op.create_table(
        "ad_promotions",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("brand_id", UUID(as_uuid=True), nullable=False),
        sa.Column("request_key", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("request_snapshot", JSONB(), nullable=False),
        sa.Column("meta_ad_account_id", sa.Text(), nullable=False),
        sa.Column("content_draft_id", UUID(as_uuid=True)),
        sa.Column("publish_attempt_id", UUID(as_uuid=True)),
        sa.Column("source_media_id", sa.Text()),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("special_ad_categories", JSONB(), nullable=False),
        sa.Column("cta_type", sa.Text(), nullable=False),
        sa.Column("link_url", sa.Text(), nullable=False),
        sa.Column("budget_kind", sa.Text(), nullable=False),
        sa.Column("budget_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("targeting", JSONB(), nullable=False),
        *(
            sa.Column(name, sa.Text())
            for name in ("meta_campaign_id", "meta_adset_id", "meta_creative_id", "meta_ad_id")
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("effective_status", sa.Text()),
        sa.Column("review_feedback", JSONB()),
        sa.Column("approved_by", UUID(as_uuid=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("adapter_version", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("tenant_id", "request_key", name="uq_ad_promotion_request"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_ad_promotion_tenant"),
        sa.ForeignKeyConstraint(
            ["brand_id", "tenant_id"],
            ["brands.id", "brands.tenant_id"],
            name="fk_ad_promotion_brand",
        ),
        sa.ForeignKeyConstraint(
            ["content_draft_id", "tenant_id", "brand_id"],
            ["content_drafts.id", "content_drafts.tenant_id", "content_drafts.brand_id"],
            name="fk_ad_promotion_draft",
        ),
        sa.ForeignKeyConstraint(
            ["publish_attempt_id", "tenant_id"],
            ["publish_attempts.id", "publish_attempts.tenant_id"],
            name="fk_ad_promotion_publish",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_ad_promotion_approver",
        ),
        sa.CheckConstraint(
            "budget_kind IN ('daily','lifetime') AND budget_minor > 0",
            name="ck_ad_promotion_budget",
        ),
        sa.CheckConstraint("end_time > start_time", name="ck_ad_promotion_schedule"),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$' AND meta_ad_account_id ~ '^[0-9]+$'",
            name="ck_ad_promotion_account_currency",
        ),
        sa.CheckConstraint(
            "content_draft_id IS NOT NULL OR publish_attempt_id IS NOT NULL "
            "OR source_media_id IS NOT NULL",
            name="ck_ad_promotion_source",
        ),
        sa.CheckConstraint(
            "status IN ('pending','creating','paused')", name="ck_ad_promotion_status"
        ),
    )
    op.create_table(
        "ad_promotion_steps",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("promotion_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("resource", sa.Text(), primary_key=True),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("claim_token", UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("meta_id", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["promotion_id", "tenant_id"],
            ["ad_promotions.id", "ad_promotions.tenant_id"],
            name="fk_ad_step_promotion",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "resource IN ('campaigns','adsets','adcreatives','ads')", name="ck_ad_step_resource"
        ),
        sa.CheckConstraint(
            "(state = 'in_flight' AND meta_id IS NULL) OR "
            "(state = 'completed' AND meta_id IS NOT NULL AND meta_id ~ '^[0-9]+$')",
            name="ck_ad_step_state",
        ),
    )
    for column in ("meta_campaign_id", "meta_adset_id", "meta_creative_id", "meta_ad_id"):
        op.create_index(
            "uq_ad_promotions_" + column,
            "ad_promotions",
            ["meta_ad_account_id", column],
            unique=True,
            postgresql_where=sa.text(column + " IS NOT NULL"),
        )
    for table in ("ad_promotions", "ad_promotion_steps"):
        op.create_index("ix_" + table + "_tenant", table, ["tenant_id"])
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO qualify_app")
        op.execute(f"GRANT SELECT ON {table} TO qualify_admin")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )
    op.execute("""
    CREATE FUNCTION ad_promotions_immutable() RETURNS trigger AS $$
    BEGIN
      IF (to_jsonb(NEW) - ARRAY['status','effective_status','review_feedback',
          'meta_campaign_id','meta_adset_id','meta_creative_id','meta_ad_id']) IS DISTINCT FROM
         (to_jsonb(OLD) - ARRAY['status','effective_status','review_feedback',
          'meta_campaign_id','meta_adset_id','meta_creative_id','meta_ad_id']) THEN
        RAISE EXCEPTION 'promotion approval snapshot is immutable' USING ERRCODE='check_violation';
      END IF;
      IF (OLD.meta_campaign_id IS NOT NULL
          AND NEW.meta_campaign_id IS DISTINCT FROM OLD.meta_campaign_id)
        OR (OLD.meta_adset_id IS NOT NULL AND NEW.meta_adset_id IS DISTINCT FROM OLD.meta_adset_id)
        OR (OLD.meta_creative_id IS NOT NULL
          AND NEW.meta_creative_id IS DISTINCT FROM OLD.meta_creative_id)
        OR (OLD.meta_ad_id IS NOT NULL AND NEW.meta_ad_id IS DISTINCT FROM OLD.meta_ad_id) THEN
        RAISE EXCEPTION 'remote identity cannot be replaced' USING ERRCODE='check_violation';
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER ad_promotions_immutable BEFORE UPDATE ON ad_promotions
      FOR EACH ROW EXECUTE FUNCTION ad_promotions_immutable();
    CREATE FUNCTION ad_promotion_steps_immutable() RETURNS trigger AS $$
    BEGIN
      IF OLD.state = 'completed' OR
        (to_jsonb(NEW) - ARRAY['state','meta_id']) IS DISTINCT FROM
        (to_jsonb(OLD) - ARRAY['state','meta_id']) OR NEW.state <> 'completed' THEN
        RAISE EXCEPTION 'creation intent cannot be replaced or reset'
          USING ERRCODE='check_violation';
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER ad_promotion_steps_immutable BEFORE UPDATE ON ad_promotion_steps
      FOR EACH ROW EXECUTE FUNCTION ad_promotion_steps_immutable();
    """)


def downgrade() -> None:
    for table in ("ad_promotion_steps", "ad_promotions"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
        op.execute(f"DROP FUNCTION IF EXISTS {table}_immutable()")
        op.drop_table(table)
    for table, name in (
        ("users", "uq_ads_user_tenant"),
        ("publish_attempts", "uq_ads_publish_tenant"),
        ("content_drafts", "uq_ads_draft_tenant_brand"),
        ("brands", "uq_ads_brand_tenant"),
    ):
        op.drop_constraint(name, table, type_="unique")

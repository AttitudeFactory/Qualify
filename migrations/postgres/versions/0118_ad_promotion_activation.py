"""Immutable preview review and spend confirmation claims (m-24828976).

Revision ID: 0118
Revises: 0117
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0118"
down_revision = "0117"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_ad_promotion_status", "ad_promotions", type_="check")
    op.create_check_constraint(
        "ck_ad_promotion_status",
        "ad_promotions",
        "status IN ('pending','creating','paused','activating','activation_unknown','active')",
    )
    op.create_table(
        "ad_promotion_activations",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("promotion_id", UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("preview_html", sa.Text(), nullable=False),
        sa.Column("preview_hash", sa.Text(), nullable=False),
        sa.Column("checks_snapshot", JSONB(), nullable=False),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prepared_by", UUID(as_uuid=True), nullable=False),
        sa.Column("confirmed_by", UUID(as_uuid=True)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("claim_token", UUID(as_uuid=True)),
        sa.Column("state", sa.Text(), nullable=False, server_default="ready"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["promotion_id", "tenant_id"],
            ["ad_promotions.id", "ad_promotions.tenant_id"],
            ondelete="CASCADE",
            name="fk_ad_activation_promotion",
        ),
        sa.ForeignKeyConstraint(
            ["prepared_by", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_ad_activation_preparer",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by", "tenant_id"],
            ["users.id", "users.tenant_id"],
            name="fk_ad_activation_confirmer",
        ),
        sa.CheckConstraint(
            "(state='ready' AND confirmed_by IS NULL AND confirmed_at IS NULL "
            "AND claim_token IS NULL)"
            " OR (state IN ('in_flight','unknown','active') AND confirmed_by=prepared_by"
            " AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL "
            "AND claim_token IS NOT NULL)",
            name="ck_ad_activation_confirmation",
        ),
    )
    op.create_index("ix_ad_promotion_activations_tenant", "ad_promotion_activations", ["tenant_id"])
    op.execute("GRANT SELECT,INSERT,UPDATE ON ad_promotion_activations TO qualify_app")
    op.execute("GRANT SELECT ON ad_promotion_activations TO qualify_admin")
    op.execute("ALTER TABLE ad_promotion_activations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ad_promotion_activations FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON ad_promotion_activations "
        "USING (tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid) "
        "WITH CHECK (tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid)"
    )
    op.execute("""
        CREATE FUNCTION ad_promotion_activations_immutable() RETURNS trigger AS $$
        BEGIN
          IF (to_jsonb(NEW)-ARRAY['state','claim_token','confirmed_by','confirmed_at'])
             IS DISTINCT FROM
             (to_jsonb(OLD)-ARRAY['state','claim_token','confirmed_by','confirmed_at']) OR
             (OLD.state='ready' AND NEW.state<>'in_flight') OR
             (OLD.state<>'ready' AND
               ((NEW.claim_token,NEW.confirmed_by,NEW.confirmed_at) IS DISTINCT FROM
                (OLD.claim_token,OLD.confirmed_by,OLD.confirmed_at) OR
                OLD.state='active' OR NEW.state NOT IN ('unknown','active'))) THEN
            RAISE EXCEPTION 'activation consent cannot be changed or reset'
              USING ERRCODE='check_violation';
          END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql;
        CREATE TRIGGER ad_promotion_activations_immutable
          BEFORE UPDATE ON ad_promotion_activations FOR EACH ROW
          EXECUTE FUNCTION ad_promotion_activations_immutable();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER ad_promotion_activations_immutable ON ad_promotion_activations")
    op.execute("DROP FUNCTION ad_promotion_activations_immutable()")
    op.drop_table("ad_promotion_activations")
    op.execute(
        "UPDATE ad_promotions SET status='paused' WHERE status IN "
        "('activating','activation_unknown','active')"
    )
    op.drop_constraint("ck_ad_promotion_status", "ad_promotions", type_="check")
    op.create_check_constraint(
        "ck_ad_promotion_status", "ad_promotions", "status IN ('pending','creating','paused')"
    )

"""Per-brand explicit creative permissions, default opt-out (m-24828984).

Revision ID: 0130
Revises: 0129
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0130"
down_revision = "0129"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ad_brand_enhancements",
        sa.Column("tenant_id", UUID(), nullable=False),
        sa.Column("brand_id", UUID(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("feature_flags", JSONB(), nullable=False),
        # Identity-provider login id is provenance, not a cross-business local user FK.
        sa.Column("updated_by", UUID(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["brand_id", "tenant_id"], ["brands.id", "brands.tenant_id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint("version > 0", name="ck_ad_brand_enhancement_version"),
        sa.CheckConstraint(
            "jsonb_typeof(feature_flags) = 'object'", name="ck_ad_brand_enhancement_values"
        ),
        sa.CheckConstraint(
            "feature_flags ?& ARRAY['image_touchups','text_optimizations','enhance_cta',"
            "'image_animation'] AND feature_flags - ARRAY['image_touchups','text_optimizations',"
            "'enhance_cta','image_animation'] = '{}'::jsonb AND "
            "jsonb_typeof(feature_flags->'image_touchups') = 'boolean' AND "
            "jsonb_typeof(feature_flags->'text_optimizations') = 'boolean' AND "
            "jsonb_typeof(feature_flags->'enhance_cta') = 'boolean' AND "
            "jsonb_typeof(feature_flags->'image_animation') = 'boolean'",
            name="ck_ad_brand_enhancement_allowlist",
        ),
    )
    op.create_index("ix_ad_brand_enhancements_tenant", "ad_brand_enhancements", ["tenant_id"])
    op.execute("GRANT SELECT,INSERT,UPDATE ON ad_brand_enhancements TO qualify_app")
    op.execute("GRANT SELECT ON ad_brand_enhancements TO qualify_admin")
    op.execute("ALTER TABLE ad_brand_enhancements ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ad_brand_enhancements FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON ad_brand_enhancements "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def downgrade() -> None:
    op.drop_table("ad_brand_enhancements")

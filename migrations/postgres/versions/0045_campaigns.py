"""campaigns: a brand's campaign groups several POSTs (QUA-143)

Revision ID: 0045
Revises: 0044
Create Date: 2026-10-07

Herwin, after QUA-118: «Una campaña se conforma de varios posts y en el calendario quiero
diferenciar entre campañas y posts independientes.»

- `campaigns`: one row per campaign of a brand — a name (unique per brand ignoring case,
  same rule as `planner_tags`) and a palette `color`. The colour is a key of the tag
  palette (0025, drawn with the same `q-tint-*` CSS) but only the FOUR that carry no
  state meaning on the calendar — violet, pink, blue, orange. teal (approved/scheduled
  edge), green (published), amber (pending/expired) and gray (cancelled) are refused by
  `ck_campaign_color`. No dates, budget or status: V1 is the grouping and its colour.
- The app role may change a campaign's `color` and nothing else: `UPDATE (color)` is a
  COLUMN grant, so a rename is refused by Postgres itself (V1 has no rename or delete).
- `content_drafts.campaign_id` (0038, a bare uuid until now) gets its FK. It is
  COMPOSITE — `(campaign_id, tenant_id, brand_id)` → `campaigns (id, tenant_id,
  brand_id)` — so Postgres itself refuses a POST in another tenant's or another brand's
  campaign, RLS or not. `ON DELETE SET NULL (campaign_id)` (Postgres ≥ 15; dev, CI and
  production run 16) clears only the campaign: the POST's own `tenant_id`/`brand_id`
  are NOT NULL and must never be touched by a campaign going away.

The campaign lives on the POST, never on `calendar_events`: every event of a POST reads
it through the POST (`PostSummary.campaign`). Setting or clearing it is not a content
edit — it never bumps `content_drafts.revision` (the service's job, tested there), so a
scheduled, approved POST keeps publishing.

Any `campaign_id` already set points at nothing (no code wrote it; only schema tests),
so the upgrade clears them before the FK is declared.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None

# A subset of 0025's `TAG_COLORS`: the four that mean nothing about state on the calendar.
CAMPAIGN_COLORS = ("violet", "pink", "blue", "orange")


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
    colors = ", ".join(f"'{c}'" for c in CAMPAIGN_COLORS)
    op.create_table(
        "campaigns",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("brand_id", PGUUID(as_uuid=True), sa.ForeignKey("brands.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("color", sa.Text(), nullable=False),
        sa.Column("created_by", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # The target of the composite FK below.
        sa.UniqueConstraint("id", "tenant_id", "brand_id", name="uq_campaign_id_tenant_brand"),
        sa.CheckConstraint("char_length(btrim(name)) BETWEEN 1 AND 60", name="ck_campaign_name"),
        sa.CheckConstraint(f"color IN ({colors})", name="ck_campaign_color"),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_campaign_brand_name "
        "ON campaigns (tenant_id, brand_id, lower(name));"
    )
    # V1: create, read and recolour — never rename (column grant) and never delete.
    op.execute("GRANT SELECT, INSERT ON campaigns TO qualify_app;")
    op.execute("GRANT UPDATE (color) ON campaigns TO qualify_app;")
    op.execute("GRANT SELECT ON campaigns TO qualify_admin;")
    _enable_tenant_rls("campaigns")

    op.execute("UPDATE content_drafts SET campaign_id = NULL WHERE campaign_id IS NOT NULL;")
    op.execute(
        """
        ALTER TABLE content_drafts
            ADD CONSTRAINT fk_content_draft_campaign
            FOREIGN KEY (campaign_id, tenant_id, brand_id)
            REFERENCES campaigns (id, tenant_id, brand_id)
            ON DELETE SET NULL (campaign_id);
        """
    )
    op.execute(
        "CREATE INDEX ix_content_drafts_campaign ON content_drafts (tenant_id, campaign_id) "
        "WHERE campaign_id IS NOT NULL;"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_content_drafts_campaign;")
    op.execute("ALTER TABLE content_drafts DROP CONSTRAINT IF EXISTS fk_content_draft_campaign;")
    op.execute("DROP INDEX IF EXISTS uq_campaign_brand_name;")
    op.drop_table("campaigns")

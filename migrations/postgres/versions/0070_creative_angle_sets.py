"""creative_angle_sets / creative_angles: ten visual variations of one catalog product

Revision ID: 0070
Revises: 0069
Create Date: 2026-10-21

Ticket 24803289 (Meegle): from ONE product of the catalog and a creative preset, Claude
proposes N (ten) visual angles — scenario, composition, hook, CTA — and each angle the
operator keeps becomes ONE `content_drafts` row of the existing generator (Seedream scene
+ local composition, or the Remotion template), grouped in a campaign.

- `creative_angle_sets`: one row per request — the product (FK `brand_products`, RESTRICT:
  a set is evidence of what was proposed and paid for), the preset, how many angles were
  asked, the price label the catalog had AT THAT MOMENT (`price_label`; "" = none, and
  `price_missing` says so — the UI tells the operator no price will be printed), the
  campaign the pieces are grouped in, the model's provenance (`model_id`,
  `model_revision`, tokens, `prompt_fingerprint`) and its cost. Status: `drafting`
  (angles being asked) → `angles_ready` → `generating` (≥1 piece requested) →
  `completed` | `failed`.
- `creative_angles`: one row per angle, `position` 1..N within the set, the structured
  proposal as Claude wrote it (bounded by the engine), its own status (`proposed`,
  `discarded`, `reserved`, `queued`, `failed`, `approved`) and the draft it became
  (`draft_id`, FK
  `content_drafts`, SET NULL if the draft ever goes). The draft's own status (generating,
  generated, failed…) is read from the draft, never copied here. `attempts` counts the
  drafts created for this angle — a retry creates a NEW draft and points here at it.
  `reserved` + `request_key` + `reserved_at` are the generation lock: an angle is
  claimed with a conditional UPDATE before any draft is created, so a double click or
  two tabs never create two drafts, and an abandoned reservation is recovered by
  looking its draft up by `request_key` (never by assuming none was created).
- `content_drafts.request_key` (+ a partial UNIQUE per tenant): the idempotency key
  `ContentService.create_draft` honours — the same key returns the same draft and
  never dispatches (pays for) its generation twice. NULL for every other caller.
- `creative_angle_sets.brand_kit_fingerprint`: which brand kit facts the angles were
  asked with (provenance; `brand_kits` has no version column).

RLS on both (tenant_id NOT NULL, ENABLE + FORCE, the NULLIF policy of 0001). The app role
reads, inserts and updates; it never deletes (a discarded angle is a status, a set is
history). The admin role reads.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0070"
down_revision = "0069"
branch_labels = None
depends_on = None

SET_STATUSES = ("drafting", "angles_ready", "generating", "completed", "failed")
ANGLE_STATUSES = ("proposed", "discarded", "reserved", "queued", "failed", "approved")


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
    set_statuses = ", ".join(f"'{s}'" for s in SET_STATUSES)
    angle_statuses = ", ".join(f"'{s}'" for s in ANGLE_STATUSES)
    op.create_table(
        "creative_angle_sets",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("brand_id", PGUUID(as_uuid=True), sa.ForeignKey("brands.id"), nullable=False),
        sa.Column(
            "product_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("brand_products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "campaign_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("campaigns.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("preset_key", sa.Text(), nullable=False),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="drafting"),
        # the product as the set saw it — the name for the campaign and the prompt, the
        # price label the pieces print ("" = the catalog had none)
        sa.Column("product_name", sa.Text(), nullable=False, server_default=""),
        sa.Column("price_label", sa.Text(), nullable=False, server_default=""),
        sa.Column("price_missing", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        # provenance of the angles call
        sa.Column("model_id", sa.Text(), nullable=True),
        sa.Column("model_revision", sa.Text(), nullable=True),
        sa.Column("prompt_fingerprint", sa.Text(), nullable=True),
        sa.Column("brand_kit_fingerprint", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=False, server_default="0"),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.Column("created_by", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_at",
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
        sa.CheckConstraint(f"status IN ({set_statuses})", name="ck_creative_angle_sets_status"),
        sa.CheckConstraint("requested_count BETWEEN 1 AND 12", name="ck_creative_angle_sets_count"),
    )
    op.create_index(
        "ix_creative_angle_sets_brand_created",
        "creative_angle_sets",
        ["tenant_id", "brand_id", sa.text("created_at DESC")],
    )
    op.create_index("ix_creative_angle_sets_product", "creative_angle_sets", ["product_id"])
    op.execute("GRANT SELECT, INSERT, UPDATE ON creative_angle_sets TO qualify_app;")
    op.execute("GRANT SELECT ON creative_angle_sets TO qualify_admin;")
    _enable_tenant_rls("creative_angle_sets")

    op.create_table(
        "creative_angles",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "set_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("creative_angle_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("scene", sa.Text(), nullable=False),
        sa.Column("composition", sa.Text(), nullable=False, server_default=""),
        sa.Column("hook", sa.Text(), nullable=False, server_default=""),
        sa.Column("cta", sa.Text(), nullable=False, server_default=""),
        sa.Column("rationale", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False, server_default="proposed"),
        sa.Column(
            "draft_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("content_drafts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        # the generation lock: the attempt in flight and when it was claimed
        sa.Column("request_key", PGUUID(as_uuid=True), nullable=True),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        # the brief the angle was generated with, for the record (and a retry)
        sa.Column("brief", JSONB, nullable=True),
        sa.Column(
            "created_at",
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
        sa.UniqueConstraint("set_id", "position", name="uq_creative_angles_set_position"),
        sa.CheckConstraint(f"status IN ({angle_statuses})", name="ck_creative_angles_status"),
        sa.CheckConstraint("position BETWEEN 1 AND 12", name="ck_creative_angles_position"),
    )
    op.create_index("ix_creative_angles_tenant", "creative_angles", ["tenant_id"])
    op.create_index("ix_creative_angles_draft", "creative_angles", ["draft_id"])
    op.execute("GRANT SELECT, INSERT, UPDATE ON creative_angles TO qualify_app;")
    op.execute("GRANT SELECT ON creative_angles TO qualify_admin;")
    _enable_tenant_rls("creative_angles")

    # the idempotency key of a draft — NULL for every caller that does not send one
    op.add_column("content_drafts", sa.Column("request_key", PGUUID(as_uuid=True)))
    op.create_index(
        "uq_content_drafts_request_key",
        "content_drafts",
        ["tenant_id", "request_key"],
        unique=True,
        postgresql_where=sa.text("request_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_content_drafts_request_key", table_name="content_drafts")
    op.drop_column("content_drafts", "request_key")
    op.drop_index("ix_creative_angles_draft", table_name="creative_angles")
    op.drop_index("ix_creative_angles_tenant", table_name="creative_angles")
    op.drop_table("creative_angles")
    op.drop_index("ix_creative_angle_sets_product", table_name="creative_angle_sets")
    op.drop_index("ix_creative_angle_sets_brand_created", table_name="creative_angle_sets")
    op.drop_table("creative_angle_sets")

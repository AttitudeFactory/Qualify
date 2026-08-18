"""creative: brand content engine data model (MC-01, ADR 32 / design doc)

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-18

Implements MC-01 with the amendments the design carries after the 2026-08-18 decisions
(`docs/diseno-motor-contenido-marca.md` §3.1, read together with §1.8-§1.10 and §7.5):

- D4 (Qualify pays all generation, no BYOK in the MVP): there is deliberately NO
  `provider_credentials` table here, even though the backlog's original MC-01 row lists
  one. Platform keys live in the environment; the table returns the day a client brings
  their own key. What D4 leaves behind instead is accounting: `creative_usage_events`
  (with `paid_by`, `PLATFORM` throughout the MVP) and the per-brand cap plus
  `max_regenerations_per_draft` in `creative_engine_config` (§7.5 — the cap now protects
  Qualify's own money, and the per-draft regeneration stop is the concrete brake on the
  regeneration loop).
- D14 (`1 tenant = 1 brand`): `brand_kits` and `creative_engine_config` are UNIQUE per
  `brand_id` — one kit, one config, no brand selector anywhere.
- D16 (template provenance): `content_drafts.template_id` + `template_version` record
  which template mold produced the piece, so per-template performance becomes calculable
  once owned-media insights arrive.
- D18 (photo recipe emits `(photo, mask)`, not a cropped photo):
  `image_assets.mask_object_key` persists the segmentation mask next to the asset —
  one inference, many consumers. The per-brand parameters live in
  `brand_kits.photo_recipe`.
- §1.8 (the three outputs; no Instagram-side drafts exist): the STAGED state between
  APPROVED and PUBLISHED materializes as `content_drafts.staged_container_id` +
  `staged_expires_at` (Meta's media container expires after 24 h) and
  `published_media_id` for the terminal state.

Every table carries `tenant_id UUID NOT NULL` with the 0001-shape RLS policy
(ENABLE + FORCE + `NULLIF(...)::uuid`) in this same revision. No RLS exception here:
unlike `ingestion.raw_payloads` (ADR 18), everything in this module is first-party.

`content_drafts.brand_id` is denormalized (no FK) for the inbox-style index
`(brand_id, status, created_at DESC)`, the same way `tenant_id` is denormalized for RLS.
`content_drafts.selected_variant_id` and `copy_variants.draft_id` reference each other,
so the draft-side FK is added AFTER `copy_variants` exists and dropped first on the way
down.

Note on numbering: the backlog wrote this migration down as `0005_creative`, but
revisions `0005` (monitored_media), `0006` (leads), `0007` (clarity) and `0008`
(auth_identity, QUA-66) landed on `main` first — so this revision chains onto `0008` as
`0009`. It briefly shipped as a second `0008` (PR #15, same morning as QUA-66), which
made Alembic reject the whole chain ("revision 0008 is present more than once"); fixed
in place per ADR 27 R8a since nothing is deployed. The filesystem, not the backlog, is
authoritative for what exists.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def _enable_tenant_rls(table: str, *, key_column: str = "tenant_id") -> None:
    # NULLIF is load-bearing (R7) — see 0001's `_enable_rls`.
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {table}
            USING ({key_column} = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK ({key_column} = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )


def _grants_and_rls(table: str) -> None:
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO qualify_app;")
    op.execute(f"GRANT SELECT ON {table} TO qualify_admin;")
    _enable_tenant_rls(table)


def _id_column() -> sa.Column:
    return sa.Column(
        "id",
        PGUUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        primary_key=True,
    )


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "brand_kits",
        _id_column(),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        # UNIQUE: one kit per brand (D14 — 1 tenant = 1 brand, no multibrand in the MVP).
        sa.Column("brand_id", PGUUID(as_uuid=True), sa.ForeignKey("brands.id"), nullable=False),
        sa.Column("positioning", sa.Text(), nullable=True),
        sa.Column("audience", sa.Text(), nullable=True),
        sa.Column("language", sa.Text(), server_default=sa.text("'es'"), nullable=False),
        sa.Column("regional_variant", sa.Text(), server_default=sa.text("'es-CO'"), nullable=False),
        sa.Column("tone_axes", JSONB(), nullable=False),
        sa.Column("do_examples", JSONB(), nullable=True),
        sa.Column("dont_examples", JSONB(), nullable=True),
        sa.Column("banned_words", ARRAY(sa.Text()), nullable=True),
        sa.Column("forbidden_claims", ARRAY(sa.Text()), nullable=True),
        sa.Column("cta_patterns", ARRAY(sa.Text()), nullable=True),
        sa.Column("palette_rgb", ARRAY(sa.Text()), nullable=True),
        sa.Column("reference_image_keys", ARRAY(sa.Text()), nullable=True),
        sa.Column("emoji_policy", sa.Text(), nullable=True),
        sa.Column("hashtag_policy", JSONB(), nullable=True),
        sa.Column("length_targets", JSONB(), nullable=True),
        sa.Column("image_policy", JSONB(), nullable=True),
        # D17/D18: per-brand photo-treatment parameters, discovered once, applied for free.
        sa.Column("photo_recipe", JSONB(), nullable=True),
        sa.Column("logo_asset_key", sa.Text(), nullable=True),
        sa.Column("template_asset_key", sa.Text(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("brand_id", name="uq_brand_kit_brand"),
    )
    _grants_and_rls("brand_kits")

    op.create_table(
        "brand_voice_profiles",
        _id_column(),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("brand_id", PGUUID(as_uuid=True), sa.ForeignKey("brands.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("profile", JSONB(), nullable=False),
        # Provenance: which sources the profile was distilled from.
        sa.Column("sources", JSONB(), nullable=False),
        sa.Column("distilled_by_model", sa.Text(), nullable=True),
        sa.Column("distilled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("brand_id", "version", name="uq_voice_profile_brand_version"),
    )
    _grants_and_rls("brand_voice_profiles")

    op.create_table(
        "content_briefs",
        _id_column(),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("brand_id", PGUUID(as_uuid=True), sa.ForeignKey("brands.id"), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("product_ref", sa.Text(), nullable=True),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("format", sa.Text(), nullable=False),
        sa.Column("intent", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("image_route", sa.Text(), nullable=False),
        sa.Column("source_media_key", sa.Text(), nullable=True),
        sa.Column("video_plan", JSONB(), nullable=True),
        sa.Column("constraints", JSONB(), nullable=True),
        sa.Column("variants_requested", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column("created_by", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        *_timestamps(),
    )
    _grants_and_rls("content_briefs")

    op.create_table(
        "content_drafts",
        _id_column(),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column(
            "brief_id", PGUUID(as_uuid=True), sa.ForeignKey("content_briefs.id"), nullable=False
        ),
        # Denormalized (no FK) for the index below, the way tenant_id is for RLS.
        sa.Column("brand_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        # FK to copy_variants.id added after that table exists (circular reference).
        sa.Column("selected_variant_id", PGUUID(as_uuid=True), nullable=True),
        sa.Column("voice_profile_version", sa.Integer(), nullable=True),
        sa.Column("pipeline_version", sa.Text(), nullable=True),
        # D16: template provenance — per-template performance becomes calculable.
        sa.Column("template_id", sa.Text(), nullable=True),
        sa.Column("template_version", sa.Integer(), nullable=True),
        sa.Column(
            "requires_ai_disclosure",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("approved_by", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        # §1.8: STAGED sits between APPROVED and PUBLISHED — the Meta media container is
        # created and verified but not published, and it expires after 24 h.
        sa.Column("staged_container_id", sa.Text(), nullable=True),
        sa.Column("staged_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_media_id", sa.Text(), nullable=True),
        *_timestamps(),
    )
    op.create_index(
        "ix_draft_brand_status_created",
        "content_drafts",
        ["brand_id", "status", sa.text("created_at DESC")],
    )
    _grants_and_rls("content_drafts")

    op.create_table(
        "copy_variants",
        _id_column(),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column(
            "draft_id", PGUUID(as_uuid=True), sa.ForeignKey("content_drafts.id"), nullable=False
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("copy", JSONB(), nullable=False),
        # NULL means the human did not touch the generated copy.
        sa.Column("edited_copy", JSONB(), nullable=True),
        sa.Column("fidelity", JSONB(), nullable=True),
        sa.Column("model_id", sa.Text(), nullable=True),
        sa.Column("model_revision", sa.Text(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("draft_id", "ordinal", name="uq_copy_variant_ordinal"),
    )
    _grants_and_rls("copy_variants")

    # Circular reference resolved: the draft's selected variant FK lands only now.
    op.create_foreign_key(
        "fk_draft_selected_variant",
        "content_drafts",
        "copy_variants",
        ["selected_variant_id"],
        ["id"],
    )

    op.create_table(
        "image_assets",
        _id_column(),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column(
            "draft_id", PGUUID(as_uuid=True), sa.ForeignKey("content_drafts.id"), nullable=False
        ),
        # MVP serves the provider's URL; object_key stays NULL until R2 lands (§5.1).
        sa.Column("media_url", sa.Text(), nullable=True),
        sa.Column("media_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("object_key", sa.Text(), nullable=True),
        # D18: the persisted segmentation mask — one inference, many consumers.
        sa.Column("mask_object_key", sa.Text(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("aspect_ratio", sa.Text(), nullable=True),
        sa.Column("rendered_prompt", sa.Text(), nullable=True),
        sa.Column("model_id", sa.Text(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("params", JSONB(), nullable=True),
        sa.Column("fidelity", JSONB(), nullable=True),
        *_timestamps(),
    )
    _grants_and_rls("image_assets")

    op.create_table(
        "creative_usage_events",
        _id_column(),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("brand_id", PGUUID(as_uuid=True), sa.ForeignKey("brands.id"), nullable=False),
        sa.Column("draft_id", PGUUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=True),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "cache_creation_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("pieces", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=False),
        # D4/§7.5: PLATFORM throughout the MVP — the subsidy must be measurable day one.
        sa.Column("paid_by", sa.Text(), nullable=False),
        sa.Column("pricing_table_version", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
    )
    op.create_index(
        "ix_usage_event_brand_occurred", "creative_usage_events", ["brand_id", "occurred_at"]
    )
    _grants_and_rls("creative_usage_events")

    op.create_table(
        "creative_engine_config",
        _id_column(),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("brand_id", PGUUID(as_uuid=True), sa.ForeignKey("brands.id"), nullable=False),
        # D4/§7.5: with the platform paying, the cap protects Qualify's own money.
        sa.Column("monthly_budget_cap_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column(
            "budget_spent_usd", sa.Numeric(10, 2), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("cycle_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hard_stop_on_cap", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("hitl_required", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        # §7.5 control 2: the concrete brake on the regeneration loop — the monthly cap
        # arrives too late.
        sa.Column(
            "max_regenerations_per_draft",
            sa.Integer(),
            server_default=sa.text("3"),
            nullable=False,
        ),
        sa.Column("task_chains", JSONB(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("brand_id", name="uq_creative_config_brand"),
    )
    _grants_and_rls("creative_engine_config")


def downgrade() -> None:
    op.drop_table("creative_engine_config")
    op.drop_index("ix_usage_event_brand_occurred", table_name="creative_usage_events")
    op.drop_table("creative_usage_events")
    op.drop_table("image_assets")
    # The circular FK must go before either side of the draft <-> variant pair.
    op.drop_constraint("fk_draft_selected_variant", "content_drafts", type_="foreignkey")
    op.drop_table("copy_variants")
    op.drop_index("ix_draft_brand_status_created", table_name="content_drafts")
    op.drop_table("content_drafts")
    op.drop_table("content_briefs")
    op.drop_table("brand_voice_profiles")
    op.drop_table("brand_kits")

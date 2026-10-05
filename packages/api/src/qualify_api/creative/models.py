"""ORM models for the Brand Content Engine (MC-01). DDL/RLS/column-grants are the
creative migration's job (`0005_creative` in design §3.1, authored in parallel); these
mirror it for typed access via the sanctioned sessions.

Key rulings encoded in the shapes:
- Every table carries `tenant_id NOT NULL` and RLS — no exception here, unlike
  `ingestion.raw_payloads` (ADR 18): everything creative is first-party and isolates.
- `content_drafts.brand_id` is DENORMALIZED from the brief so the hot listing index
  `(brand_id, status, created_at DESC)` never needs the join.
- `content_drafts.selected_variant_id` points at `copy_variants.id` but is deliberately
  NOT a declared FK: `copy_variants.draft_id` already points back at the draft, and a
  circular FK pair would force deferred constraints for no isolation gain. The FSM guard
  (`approve` requires a variant) plus the service are the enforcement.
- Status/vocabulary columns are `Text`, not native enums; the string values are the
  contract with `qualify_creative.enums` (see `creative/fsm.py`).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from qualify_api.tenancy.models import Base


class BrandKit(Base):
    """The declared identity of a brand: voice inputs, policies, visual assets. One row
    per brand, filled progressively. Completeness is computed by readiness, never stored:
    a persisted score of a derivable value is a staleness bug waiting to be believed."""

    __tablename__ = "brand_kits"
    __table_args__ = (
        UniqueConstraint("brand_id", name="uq_brand_kits_brand"),
        Index("ix_brand_kits_tenant", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    brand_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("brands.id"), nullable=False
    )
    positioning: Mapped[str | None] = mapped_column(Text, nullable=True)
    audience: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(Text, nullable=False)  # e.g. 'es'
    regional_variant: Mapped[str | None] = mapped_column(Text, nullable=True)  # e.g. 'es-CO'
    tone_axes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    do_examples: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    dont_examples: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    banned_words: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    forbidden_claims: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    emoji_policy: Mapped[str | None] = mapped_column(Text, nullable=True)  # EmojiPolicy values
    hashtag_policy: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    cta_patterns: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    length_targets: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    palette_rgb: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    # the brand's type faces, by family name (0038) — the files, if any, are assets
    font_heading: Mapped[str | None] = mapped_column(Text, nullable=True)
    font_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_asset_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_asset_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_image_keys: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    image_policy: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # ImagePolicy shape
    photo_recipe: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # D17/D18 params
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class BrandVoiceProfile(Base):
    """A distilled, versioned voice profile (HITL #0 output). `sources` is provenance:
    which kit fields / owned media / public pages the distillation read."""

    __tablename__ = "brand_voice_profiles"
    __table_args__ = (
        UniqueConstraint("brand_id", "version", name="uq_voice_profiles_brand_version"),
        Index("ix_voice_profiles_tenant", "tenant_id"),
        # at most one ACTIVE profile per brand, as a database fact (0032)
        Index(
            "uq_voice_profiles_one_active",
            "brand_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    brand_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("brands.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)  # VoiceProfileStatus values
    profile: Mapped[dict] = mapped_column(JSONB, nullable=False)
    sources: Mapped[dict] = mapped_column(JSONB, nullable=False)  # provenance
    distilled_by_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    distilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class BrandVoiceClone(Base):
    """The brand's own voice cloned in HeyGen (0032): one per brand, replaced on a new
    clone. Manual, with the operator's recorded consent (`consent_by`/`consent_at`).
    `heygen_voice_id` works anywhere a HeyGen `voice_id` does once `status` is
    `complete`."""

    __tablename__ = "brand_voice_clones"
    __table_args__ = (
        UniqueConstraint("brand_id", name="uq_voice_clone_brand"),
        Index("ix_voice_clones_tenant", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    brand_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("brands.id"), nullable=False
    )
    heygen_voice_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="processing")
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(Text, nullable=True)
    gender: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_audio_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    consent_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class BrandKitAsset(Base):
    """One file of the brand's brandboard, kept in R2 (0033): a version of the logo
    (`kind = 'logo_version'`, `slot` = logotipo/isotipo/imagotipo/isologo), another
    element added with the "+" (`kind = 'extra'`, `slot` = its id), a standalone logo
    (`kind = 'logo'`) or a font file (`kind = 'font'`, `slot` = heading/body — 0038).
    `label`/`context` are the operator's own words about it."""

    __tablename__ = "brand_kit_assets"
    __table_args__ = (
        UniqueConstraint("brand_id", "kind", "slot", name="uq_brand_kit_asset_slot"),
        Index("ix_brand_kit_assets_tenant", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    brand_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("brands.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    slot: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    content_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    label: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    context: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class BrandKitDetails(Base):
    """The wizards' own answers for a brand (0033), as three JSONB documents:
    `logo_brief`, `connect` (network, user, account kind, rubro, location, hashtags) and
    `profile` (the account as read, and its metrics)."""

    __tablename__ = "brand_kit_details"
    __table_args__ = (Index("ix_brand_kit_details_tenant", "tenant_id"),)

    brand_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("brands.id"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    logo_brief: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    connect: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    profile: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'"))
    updated_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ContentBrief(Base):
    """The operator's order: what the piece is for, where it runs, what it must respect.
    Immutable input to a draft — regeneration re-reads the brief, never edits it."""

    __tablename__ = "content_briefs"
    __table_args__ = (Index("ix_content_briefs_tenant", "tenant_id"),)

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    brand_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("brands.id"), nullable=False
    )
    objective: Mapped[str] = mapped_column(Text, nullable=False)  # BriefObjective values
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    product_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    platform: Mapped[str] = mapped_column(Text, nullable=False)  # Platform values
    format: Mapped[str] = mapped_column(Text, nullable=False)  # ContentFormat values
    intent: Mapped[str] = mapped_column(Text, nullable=False)  # BriefIntent values
    content_type: Mapped[str] = mapped_column(Text, nullable=False)  # ContentType values
    image_route: Mapped[str] = mapped_column(Text, nullable=False)  # ImageRoute values
    source_media_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_plan: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    variants_requested: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    constraints: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # ContentKind value and its MediaInputs (0026)
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="static_flyer")
    media: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ContentDraft(Base):
    """One generation attempt and its lifecycle (`creative/fsm.py`). `brand_id` is
    denormalized from the brief so the listing index never joins."""

    __tablename__ = "content_drafts"
    __table_args__ = (
        Index("ix_content_drafts_listing", "brand_id", "status", text("created_at DESC")),
        Index("ix_content_drafts_tenant", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    brand_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("brands.id"), nullable=False
    )
    brief_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_briefs.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)  # DraftStatus values (fsm.py)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # FailureReason
    # why, in the operator's words (0028)
    failure_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Points at copy_variants.id; not a declared FK (see module docstring).
    selected_variant_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    voice_profile_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pipeline_version: Mapped[str] = mapped_column(Text, nullable=False)
    template_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requires_ai_disclosure: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    approved_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Staging state; both cleared together on the `stage_expired` edge.
    staged_container_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    staged_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_media_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The POST fields (0027, QUA-109): the draft IS the POST.
    title: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    category: Mapped[str | None] = mapped_column(Text, nullable=True)  # PostCategory
    reuse_type: Mapped[str | None] = mapped_column(Text, nullable=True)  # ReuseType
    preview_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    approved_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class CopyVariant(Base):
    """One structured copy proposal (`CopyPayload` shape, design §3.2) for a draft.
    `edited_copy` stays NULL until the human touches it — the diff IS the signal."""

    __tablename__ = "copy_variants"
    __table_args__ = (
        Index("ix_copy_variants_draft", "draft_id"),
        Index("ix_copy_variants_tenant", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    draft_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_drafts.id"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    copy: Mapped[dict] = mapped_column(JSONB, nullable=False)  # CopyPayload (§3.2)
    edited_copy: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    fidelity: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    model_revision: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ImageAsset(Base):
    """One rendered/generated image for a draft. MVP serves the provider's `media_url`
    (design §5.1); `object_key`/`mask_object_key` stay NULL until R2 custody lands."""

    __tablename__ = "image_assets"
    __table_args__ = (
        Index("ix_image_assets_draft", "draft_id"),
        Index("ix_image_assets_tenant", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    draft_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_drafts.id"), nullable=False
    )
    media_url: Mapped[str] = mapped_column(Text, nullable=False)
    media_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The MIME type the object was stored with (0029). Written by whoever persists the
    # asset in R2 (QUA-109/110); NULL means "not publishable" to QUA-111.
    content_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    mask_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    aspect_ratio: Mapped[str | None] = mapped_column(Text, nullable=True)  # e.g. '4:5'
    rendered_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str | None] = mapped_column(Text, nullable=True)
    params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    fidelity: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # 'image' | 'video', and a carousel slide's order (0026)
    media_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="image")
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class CreativeUsageEvent(Base):
    """Cost provenance: one row per billable vendor call (or free local render), so the
    budget cap in `creative_engine_config` is enforced over facts, not estimates."""

    __tablename__ = "creative_usage_events"
    __table_args__ = (
        Index("ix_usage_event_brand_occurred", "brand_id", "occurred_at"),
        Index("ix_usage_events_tenant", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    brand_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("brands.id"), nullable=False
    )
    draft_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_drafts.id"), nullable=True
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(Text, nullable=False)  # 'piece' | 'token'
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_creation_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pieces: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    paid_by: Mapped[str] = mapped_column(Text, nullable=False)  # PaidBy values
    pricing_table_version: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class CreativeEngineConfig(Base):
    """Per-brand operating limits. `hitl_required` is always true in the MVP — the column
    exists so relaxing it someday is a data change with an audit trail, not a deploy."""

    __tablename__ = "creative_engine_config"
    __table_args__ = (
        UniqueConstraint("brand_id", name="uq_engine_config_brand"),
        Index("ix_engine_config_tenant", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    brand_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("brands.id"), nullable=False
    )
    monthly_budget_cap_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    budget_spent_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, server_default=text("0")
    )
    cycle_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    hard_stop_on_cap: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    hitl_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    task_chains: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    max_regenerations_per_draft: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("3")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

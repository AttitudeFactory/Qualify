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

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
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

# `template_runs` vocabularies (0038). Strings, not enums — same contract style as the
# draft FSM; the CHECK constraints in the migration pin the same sets.
TEMPLATE_RUN_ENGINES: frozenset[str] = frozenset({"remotion", "heygen", "ugc"})
TEMPLATE_RUN_STATUSES: frozenset[str] = frozenset(
    {"pending", "generating", "completed", "failed", "cancelled"}
)


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
    # the brand's type faces, by family name (0043) — the files, if any, are assets
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
    """The brand's own cloned voice (0032; vendor-neutral since 0066): one per brand,
    replaced on a new clone. Manual, with the operator's recorded consent
    (`consent_by`/`consent_at`/`consent_text`). `provider` says where it lives —
    `seed_speech` since 2026-10-16, `heygen` for rows made before — and
    `external_voice_id` is its id there (Seed Speech: our own post-paid `qlf-…`)."""

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
    provider: Mapped[str] = mapped_column(Text, nullable=False, server_default="heygen")
    external_voice_id: Mapped[str] = mapped_column(Text, nullable=False)
    #: History only (0066): the HeyGen id of a voice cloned before the move to Seed Speech.
    heygen_voice_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="processing")
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(Text, nullable=True)
    gender: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_audio_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    sample_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    consent_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
    (`kind = 'logo'`) or a font file (`kind = 'font'`, `slot` = heading/body — 0043).
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


class SocialAccountClaim(Base):
    """A brand's own social account, taken for that brand alone (0044, § request
    2026-10-06: an account registered by one email may not be read by another).

    `UNIQUE(network, handle_key)` is GLOBAL while RLS keeps every row private to its
    tenant: the index is what tells a second tenant "taken" without letting it read whose
    (`qualify_api.creative.account_claims`)."""

    __tablename__ = "social_account_claims"
    __table_args__ = (
        UniqueConstraint("network", "handle_key", name="uq_social_account_claims_account"),
        CheckConstraint(
            "network IN ('instagram','tiktok')", name="ck_social_account_claims_network"
        ),
        CheckConstraint(
            "handle_key <> '' AND handle_key = lower(btrim(handle_key)) "
            "AND left(handle_key, 1) <> '@'",
            name="ck_social_account_claims_handle_key",
        ),
        Index("ix_social_account_claims_tenant", "tenant_id", "brand_id"),
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
    network: Mapped[str] = mapped_column(Text, nullable=False)
    handle_key: Mapped[str] = mapped_column(Text, nullable=False)
    handle: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Campaign(Base):
    """A brand's campaign: several POSTs grouped under one name and colour (0045,
    QUA-143). The POST points at it (`ContentDraft.campaign_id`); calendar events never
    do — they read it through their POST. Name unique per brand ignoring case."""

    __tablename__ = "campaigns"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", "brand_id", name="uq_campaign_id_tenant_brand"),
        CheckConstraint("char_length(btrim(name)) BETWEEN 1 AND 60", name="ck_campaign_name"),
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
    name: Mapped[str] = mapped_column(Text, nullable=False)
    color: Mapped[str] = mapped_column(Text, nullable=False)  # a `CAMPAIGN_COLORS` key
    created_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
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
    # the caller's idempotency key (0070): the same key never creates a second draft
    request_key: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
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
    # The campaign this POST belongs to (0038; FK since 0045, QUA-143). The FK is
    # composite — `(campaign_id, tenant_id, brand_id)` → `campaigns` — with
    # `ON DELETE SET NULL (campaign_id)`, which SQLAlchemy cannot spell: it lives in the
    # migration only. Setting it is not a content edit (`creative/campaigns.py`).
    campaign_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    # When the piece's R2 files were deleted by the retention rule (0076, m-24828907).
    # NULL = the files are there; set = «Contenido eliminado» (`creative/retention.py`).
    media_purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ContentDraftPurge(Base):
    """One retention run that acted on a piece (0076, m-24828907): what prefix, how many
    objects and bytes, real or dry run. Append-only — the app role has no UPDATE/DELETE."""

    __tablename__ = "content_draft_purges"
    __table_args__ = (
        Index("ix_draft_purges_tenant", "tenant_id"),
        Index("ix_draft_purges_draft", "draft_id", "purged_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    draft_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_drafts.id", ondelete="CASCADE"), nullable=False
    )
    prefix: Mapped[str] = mapped_column(Text, nullable=False)
    object_count: Mapped[int] = mapped_column(Integer, nullable=False)
    byte_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False)
    expired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    purged_at: Mapped[datetime] = mapped_column(
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
        Index("ix_image_assets_template_run", "template_run_id"),
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
    # Which template port this output came from, and the run that produced it (0038).
    # Both NULL for everything rendered before the Remotion engine.
    output_port: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("template_runs.id", name="fk_image_assets_template_run"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class TemplateRun(Base):
    """One render job (0038, `docs/plan-mvp-plantillas-remotion.md` §2.1 #6, §2.3). The
    row's `id` IS the `jobId` handed to the render service, so its `status`/`cancel` and
    this row agree by construction.

    Provenance: `template_id`/`template_version`, `prompt_id`/`prompt_version`, the `engine`
    the router chose (`TEMPLATE_RUN_ENGINES`), the `router_rule` that chose it and
    `overridden_by` when the operator picked another option. Lifecycle in `status`
    (`TEMPLATE_RUN_STATUSES`); `outputs` mirrors the per-port status the service reports;
    `props` is the resolved template input, kept so a run can be re-rendered as-is."""

    __tablename__ = "template_runs"
    __table_args__ = (
        CheckConstraint(
            "engine IN ('remotion','heygen','omnihuman','ugc')", name="ck_template_runs_engine"
        ),
        CheckConstraint(
            "status IN ('pending','generating','completed','failed','cancelled')",
            name="ck_template_runs_status",
        ),
        Index("ix_template_runs_draft", "draft_id"),
        Index("ix_template_runs_tenant_created", "tenant_id", "created_at"),
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
    draft_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_drafts.id"), nullable=False
    )
    template_id: Mapped[str] = mapped_column(Text, nullable=False)
    template_version: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    engine: Mapped[str] = mapped_column(Text, nullable=False)  # TEMPLATE_RUN_ENGINES
    router_rule: Mapped[str | None] = mapped_column(Text, nullable=True)
    overridden_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)  # TEMPLATE_RUN_STATUSES
    outputs: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    estimated_eta_sec: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    actual_sec: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    actual_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    props: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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


CREATION_CHARGE_STATUSES: tuple[str, ...] = ("charged", "refunded")


class CreationCharge(Base):
    """One charged generation in «creaciones del mes» (0088, CREAR-5 m-24848531): its
    weight and the versions that priced it. A refund keeps the row and turns its status;
    the dollars stay in `creative_usage_events`, joined by `draft_id` for the team.
    `previews` (founder, 2026-10-24) are the «vistas previas» charged at creation;
    `videos` the month's videos charged at APPROVAL (0 until then; `videos_period_month`
    is the approval's month); a failed 1080p final gives its video back by adding its
    asset to `final_refunded_assets`."""

    __tablename__ = "creation_charges"
    __table_args__ = (
        CheckConstraint("status IN ('charged','refunded')", name="ck_creation_charges_status"),
        UniqueConstraint("draft_id", "revision", name="uq_creation_charges_generation"),
        Index("ix_creation_charges_tenant", "tenant_id"),
        Index("ix_creation_charges_brand_month", "tenant_id", "brand_id", "period_month"),
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
    draft_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    request_kind: Mapped[str] = mapped_column(Text, nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False)
    monthly_quota: Mapped[int] = mapped_column(Integer, nullable=False)
    weights_version: Mapped[str] = mapped_column(Text, nullable=False)
    pricing_table_version: Mapped[str] = mapped_column(Text, nullable=False)
    period_month: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'charged'"))
    refund_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    charged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    previews: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    monthly_preview_quota: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    videos: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    monthly_video_quota: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    videos_period_month: Mapped[date | None] = mapped_column(Date, nullable=True)
    videos_charged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    final_refunded_assets: Mapped[list[UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=False, server_default=text("'{}'::uuid[]")
    )
    final_refunded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    final_refund_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class CreativeVendorTask(Base):
    """One asynchronous vendor task a generation created (0090, m-24852154): recorded the
    moment the vendor accepts it, so a task that outlives our wait — BytePlus's queue, a
    deploy killing the thread — is resumed by its id and never submitted again nor lost
    while billed. `slot` names the call inside the generation ('video', 'clip',
    'slide-3', 'final:<asset id>'); `context` keeps what a resumed run reuses (the copy
    the video was made from). `status` leaves 'pending' once the run settles it."""

    __tablename__ = "creative_vendor_tasks"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="ck_creative_vendor_tasks_revision"),
        CheckConstraint(
            "status IN ('pending','succeeded','failed')", name="ck_creative_vendor_tasks_status"
        ),
        UniqueConstraint("draft_id", "revision", "slot", name="uq_creative_vendor_tasks_slot"),
        Index("ix_creative_vendor_tasks_tenant", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    draft_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_drafts.id", ondelete="CASCADE"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    slot: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    vendor_task_id: Mapped[str] = mapped_column(Text, nullable=False)
    pipeline_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    context: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CreativeVendorTaskTiming(Base):
    """When one asynchronous vendor task was submitted, started rendering and ended (0094,
    m-24852158): the team's measurement of BytePlus's queue and of tasks at once. One row
    per task ever submitted (a retried slot keeps its failed task's row). `running_at` is
    NULL when no live observation saw the task go from queued to running; `finished_late`
    marks a `finished_at` that is only an upper bound (seen by a resumed run)."""

    __tablename__ = "creative_vendor_task_timings"
    __table_args__ = (
        CheckConstraint("phase IN ('draft','final')", name="ck_vendor_task_timings_phase"),
        CheckConstraint(
            "final_status IS NULL OR final_status IN "
            "('succeeded','failed','cancelled','expired','not_found')",
            name="ck_vendor_task_timings_final_status",
        ),
        CheckConstraint(
            "(final_status IS NULL) = (finished_at IS NULL)",
            name="ck_vendor_task_timings_finished",
        ),
        UniqueConstraint("provider", "vendor_task_id", name="uq_vendor_task_timings_task"),
        Index("ix_vendor_task_timings_tenant", "tenant_id"),
        Index("ix_vendor_task_timings_submitted", "submitted_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    vendor_task_id: Mapped[str] = mapped_column(Text, nullable=False)
    phase: Mapped[str] = mapped_column(Text, nullable=False)
    draft_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    slot: Mapped[str | None] = mapped_column(Text, nullable=True)
    pipeline_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    running_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    final_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    finished_late: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


# `creative_angle_sets` / `creative_angles` vocabularies (0070, ticket 24803289). Strings
# with CHECK constraints, same contract style as `template_runs`.
ANGLE_SET_STATUSES: tuple[str, ...] = (
    "drafting",
    "angles_ready",
    "generating",
    "completed",
    "failed",
)
ANGLE_STATUSES: tuple[str, ...] = (
    "proposed",
    "discarded",
    "reserved",
    "queued",
    "failed",
    "approved",
)


class CreativeAngleSet(Base):
    """One «10 variaciones» request (0070): the catalog product, the preset, the price the
    catalog had then, the campaign the pieces group in, and the provenance and cost of
    the angles call. The pieces themselves are `content_drafts`, one per angle."""

    __tablename__ = "creative_angle_sets"
    #: «Eliminar grupo» (0078): off the list for good; the row and its pieces stay.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        CheckConstraint(
            "status IN ('drafting','angles_ready','generating','completed','failed')",
            name="ck_creative_angle_sets_status",
        ),
        CheckConstraint("requested_count BETWEEN 1 AND 12", name="ck_creative_angle_sets_count"),
        Index(
            "ix_creative_angle_sets_brand_created",
            "tenant_id",
            "brand_id",
            text("created_at DESC"),
        ),
        Index("ix_creative_angle_sets_product", "product_id"),
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
    product_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("brand_products.id", ondelete="RESTRICT"), nullable=False
    )
    campaign_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True
    )
    preset_key: Mapped[str] = mapped_column(Text, nullable=False)
    requested_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="drafting")
    product_name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    price_label: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    price_missing: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    model_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_revision: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_fingerprint: Mapped[str | None] = mapped_column(Text, nullable=True)
    brand_kit_fingerprint: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, server_default="0")
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class CreativeAngle(Base):
    """One visual angle of a set (0070): the structured proposal, its own status and the
    draft it became. The draft's generation status lives on the draft."""

    __tablename__ = "creative_angles"
    __table_args__ = (
        UniqueConstraint("set_id", "position", name="uq_creative_angles_set_position"),
        CheckConstraint(
            "status IN ('proposed','discarded','reserved','queued','failed','approved')",
            name="ck_creative_angles_status",
        ),
        CheckConstraint("position BETWEEN 1 AND 12", name="ck_creative_angles_position"),
        Index("ix_creative_angles_tenant", "tenant_id"),
        Index("ix_creative_angles_draft", "draft_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    set_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("creative_angle_sets.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    scene: Mapped[str] = mapped_column(Text, nullable=False)
    composition: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    hook: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    cta: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    rationale: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="proposed")
    draft_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_drafts.id", ondelete="SET NULL"), nullable=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    request_key: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    reserved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: «Guardar para después» (0077): put aside from the review, not a status.
    saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    brief: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ContentDraftPurgeWarning(Base):
    """Successful warning per piece, exact deadline and recipient and stage (0101, m-24842840)."""

    __tablename__ = "content_draft_purge_warnings"
    __table_args__ = (
        UniqueConstraint(
            "draft_id", "deadline", "recipient", "stage", name="uq_purge_warnings_draft_deadline"
        ),
        Index("ix_purge_warnings_tenant", "tenant_id"),
        CheckConstraint("stage IN ('window_15d', 'last_day')", name="ck_purge_warning_stage"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    draft_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_drafts.id", ondelete="CASCADE"), nullable=False
    )
    recipient: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    notified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ContentDraftWarningBatch(Base):
    """Frozen retention email outbox; delivery state changes, payload never does (0101)."""

    __tablename__ = "content_draft_warning_batches"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_warning_batch_key"),
        Index("ix_warning_batches_tenant", "tenant_id"),
        Index(
            "uq_warning_batches_pending",
            "tenant_id",
            "brand_id",
            "recipient",
            "stage",
            unique=True,
            postgresql_where=text(
                "sent_at IS NULL AND cancelled_at IS NULL AND needs_review_at IS NULL"
            ),
        ),
        CheckConstraint("stage IN ('window_15d', 'last_day')", name="ck_warning_batch_stage"),
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
    recipient: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    first_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    needs_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_id: Mapped[str | None] = mapped_column(Text, nullable=True)

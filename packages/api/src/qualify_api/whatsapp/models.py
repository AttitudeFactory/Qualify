"""ORM models for the WhatsApp module (WA-04 + WA-14 + WA-18/19/20). DDL/RLS/grants are
the job of migrations 0057 (numbers, thread state, outbox), 0058 (menus, versions) and 0060
(templates, opt-ins, campaigns, campaign sends); these mirror them for typed access via the
sanctioned sessions — same relationship `inbox/models.py` has to 0004.

Every table carries a denormalized `tenant_id` with a composite FK to its parent
(`social_connections`, `threads`, `whatsapp_phone_numbers` or `whatsapp_menus`, R2
discipline), so a row whose tenant disagrees with its parent is structurally unbuildable.
The conversation itself is NOT here: a WhatsApp chat is a `Thread` with `channel =
'whatsapp'` and its `Message`s, the same inbox tables Instagram DMs use (0057 widened
`ck_thread_channel`).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    text as sql_now,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from qualify_api.tenancy.models import Base

OUTBOX_KINDS: tuple[str, ...] = ("reply", "automation", "campaign_send")
OUTBOX_STATUSES: tuple[str, ...] = ("pending", "sending", "sent", "failed", "dead")
DELIVERY_STATUSES: tuple[str, ...] = ("sent", "delivered", "read", "failed")
# 0061: `messages.media_type` (CHECK `ck_message_media_type`; the ORM copy lives on
# `inbox.models.Message`). `other` absorbs every inbound type not listed.
MEDIA_TYPE_OTHER = "other"
MEDIA_TYPES: tuple[str, ...] = (
    "image",
    "audio",
    "video",
    "document",
    "sticker",
    "location",
    "contacts",
    "interactive",
    "button",
    "order",
    MEDIA_TYPE_OTHER,
)
# The subset whose bytes can be downloaded from Meta (`WAMedia` carries an id).
DOWNLOADABLE_MEDIA_TYPES: tuple[str, ...] = ("image", "audio", "video", "document", "sticker")
# 0060 (WA-18/19/20).
TEMPLATE_CATEGORIES: tuple[str, ...] = ("marketing", "utility", "authentication")
OPT_IN_SOURCES: tuple[str, ...] = ("lead_form", "menu", "import", "manual")
CAMPAIGN_STATUSES: tuple[str, ...] = (
    "draft",
    "scheduled",
    "running",
    "paused",
    "done",
    "cancelled",
)
CAMPAIGN_SEND_STATUSES: tuple[str, ...] = (
    "pending",
    "queued",
    "sent",
    "delivered",
    "read",
    "failed",
    "skipped",
)


def _sql_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class WhatsAppPhoneNumber(Base):
    """One WhatsApp Business phone number connected to Qualify.

    `phone_number_id` is Meta's global identifier and the key the webhook resolves the
    owning tenant by — UNIQUE across the table, not per tenant. The Graph metadata columns
    are stored verbatim and nullable (WA-05 reads them at connect time and on re-run;
    `last_synced_at` says when). `automation` is the conversational-automation object as
    published to Meta, so the editor can diff against it.
    """

    __tablename__ = "whatsapp_phone_numbers"
    __table_args__ = (
        UniqueConstraint("phone_number_id", name="uq_wa_phone_number_id"),
        # Target of `whatsapp_menus`' composite FK (added by 0058).
        UniqueConstraint("id", "tenant_id", name="uq_wa_phone_id_tenant"),
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_wa_phone_conn_tenant",
        ),
        Index("ix_wa_phone_tenant", "tenant_id"),
        Index("ix_wa_phone_connection", "connection_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=sql_now("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    brand_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("brands.id"), nullable=True
    )
    connection_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    waba_id: Mapped[str] = mapped_column(Text, nullable=False)
    phone_number_id: Mapped[str] = mapped_column(Text, nullable=False)
    display_phone_number: Mapped[str] = mapped_column(Text, nullable=False)
    verified_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    name_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    quality_rating: Mapped[str | None] = mapped_column(Text, nullable=True)
    messaging_limit_tier: Mapped[str | None] = mapped_column(Text, nullable=True)
    platform_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    automation: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sql_now("'{}'::jsonb")
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=sql_now("now()"), nullable=False)


class WhatsAppThreadState(Base):
    """The automation cursor of ONE WhatsApp thread (`thread_id` is the PK): which menu
    version and node the conversation sits on, the order being built (`context`) and
    whether a person took over (`automation_paused_at` / `paused_by_user_id`).

    `menu_version_id` → `whatsapp_menu_versions` (composite with `tenant_id`, 0058).
    `attempts` is the engine's `ThreadMenuState.attempts`: consecutive unknown inputs on
    the current node, reset on every successful step.
    """

    __tablename__ = "whatsapp_thread_state"
    __table_args__ = (
        ForeignKeyConstraint(
            ["thread_id", "tenant_id"],
            ["threads.id", "threads.tenant_id"],
            name="fk_wa_thread_state_thread_tenant",
        ),
        ForeignKeyConstraint(
            ["menu_version_id", "tenant_id"],
            ["whatsapp_menu_versions.id", "whatsapp_menu_versions.tenant_id"],
            name="fk_wa_thread_state_menu_version_tenant",
        ),
        CheckConstraint("attempts >= 0", name="ck_wa_thread_state_attempts"),
        Index("ix_wa_thread_state_tenant", "tenant_id"),
    )

    thread_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    menu_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    node_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    context: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sql_now("'{}'::jsonb")
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    automation_paused_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paused_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(server_default=sql_now("now()"), nullable=False)


class WhatsAppOutboxItem(Base):
    """One message Qualify intends to send: the already-built body of
    `POST /{phone_number_id}/messages` (`payload`) plus the queue columns the sender
    (WA-08) claims by `(status, next_attempt_at)` with `FOR UPDATE SKIP LOCKED`.

    `thread_id` is nullable: a `campaign_send` may open a conversation that has no thread
    yet; a `reply` always has one. `wamid` is Meta's id once accepted — the key the
    `statuses[]` webhook later updates `messages.delivery_status` by.
    """

    __tablename__ = "whatsapp_outbox"
    __table_args__ = (
        # Target of `whatsapp_campaign_sends`' composite FK (added by 0060).
        UniqueConstraint("id", "tenant_id", name="uq_wa_outbox_id_tenant"),
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_wa_outbox_conn_tenant",
        ),
        ForeignKeyConstraint(
            ["thread_id", "tenant_id"],
            ["threads.id", "threads.tenant_id"],
            name="fk_wa_outbox_thread_tenant",
        ),
        CheckConstraint(f"kind IN ({_sql_list(OUTBOX_KINDS)})", name="ck_wa_outbox_kind"),
        CheckConstraint(f"status IN ({_sql_list(OUTBOX_STATUSES)})", name="ck_wa_outbox_status"),
        CheckConstraint("attempts >= 0", name="ck_wa_outbox_attempts"),
        Index("ix_wa_outbox_tenant", "tenant_id"),
        Index("ix_wa_outbox_claim", "status", "next_attempt_at"),
        Index(
            "ix_wa_outbox_thread",
            "thread_id",
            "created_at",
            postgresql_where=sql_now("thread_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=sql_now("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    connection_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    thread_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sql_now("now()"), nullable=False
    )
    locked_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    wamid: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=sql_now("now()"), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WhatsAppMenu(Base):
    """One menu a business authors for ONE of its WhatsApp numbers (0058, WA-14).

    `published_version_id` is the version the number answers with — a composite FK
    `(published_version_id, id)` → `whatsapp_menu_versions (id, menu_id)`, so a menu can
    only publish one of its OWN versions. At most one menu per number is published at a
    time (`uq_wa_menu_phone_published`): the handler's "menu of this number" lookup is
    deterministic. `is_paused` stops the automation for the whole number without
    unpublishing; the per-thread pause lives in `WhatsAppThreadState`.
    """

    __tablename__ = "whatsapp_menus"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_wa_menu_id_tenant"),
        ForeignKeyConstraint(
            ["phone_number_row_id", "tenant_id"],
            ["whatsapp_phone_numbers.id", "whatsapp_phone_numbers.tenant_id"],
            name="fk_wa_menu_phone_tenant",
        ),
        ForeignKeyConstraint(
            ["published_version_id", "id"],
            ["whatsapp_menu_versions.id", "whatsapp_menu_versions.menu_id"],
            name="fk_wa_menu_published_version",
            use_alter=True,
        ),
        CheckConstraint("length(btrim(name)) > 0", name="ck_wa_menu_name_not_blank"),
        Index("ix_wa_menu_tenant", "tenant_id"),
        Index("ix_wa_menu_phone", "phone_number_row_id"),
        Index(
            "uq_wa_menu_phone_name",
            "tenant_id",
            "phone_number_row_id",
            sql_now("lower(name)"),
            unique=True,
        ),
        Index(
            "uq_wa_menu_phone_published",
            "phone_number_row_id",
            unique=True,
            postgresql_where=sql_now("published_version_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=sql_now("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    brand_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("brands.id"), nullable=True
    )
    phone_number_row_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    published_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    is_paused: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_now("false")
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=sql_now("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(server_default=sql_now("now()"), nullable=False)


class WhatsAppMenuVersion(Base):
    """One immutable snapshot of a menu: the validated `MenuDefinition.model_dump()` in
    `definition` and the `ENGINE_VERSION` it was validated against (provenance). `version`
    counts per menu. Only the publication stamp (`published_at`, `published_by_user_id`)
    may change after INSERT — a column-level grant, not a convention — and no role may
    delete a version: a thread may still sit on it.
    """

    __tablename__ = "whatsapp_menu_versions"
    __table_args__ = (
        UniqueConstraint("menu_id", "version", name="uq_wa_menu_version"),
        UniqueConstraint("id", "tenant_id", name="uq_wa_menu_version_id_tenant"),
        UniqueConstraint("id", "menu_id", name="uq_wa_menu_version_id_menu"),
        ForeignKeyConstraint(
            ["menu_id", "tenant_id"],
            ["whatsapp_menus.id", "whatsapp_menus.tenant_id"],
            name="fk_wa_menu_version_menu_tenant",
        ),
        CheckConstraint("version > 0", name="ck_wa_menu_version_positive"),
        Index("ix_wa_menu_version_tenant", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=sql_now("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    menu_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    engine_version: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=sql_now("now()"), nullable=False)


class WhatsAppTemplate(Base):
    """The mirror of one message template of a WABA (0060, WA-18).

    Natural key `(tenant_id, waba_id, name, language)`. `status`/`quality` are Meta's
    strings verbatim (no CHECK: Meta adds statuses without notice); `category` is one of
    `TEMPLATE_CATEGORIES` (lowercase — Meta's uppercase is normalized on the way in).
    `meta_template_id` is NULL until Meta answers the create call or a sync finds it.
    """

    __tablename__ = "whatsapp_templates"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "waba_id", "name", "language", name="uq_wa_template_natural_key"
        ),
        UniqueConstraint("id", "tenant_id", name="uq_wa_template_id_tenant"),
        ForeignKeyConstraint(
            ["phone_number_row_id", "tenant_id"],
            ["whatsapp_phone_numbers.id", "whatsapp_phone_numbers.tenant_id"],
            name="fk_wa_template_phone_tenant",
        ),
        CheckConstraint(
            f"category IN ({_sql_list(TEMPLATE_CATEGORIES)})", name="ck_wa_template_category"
        ),
        CheckConstraint("length(btrim(name)) > 0", name="ck_wa_template_name_not_blank"),
        Index("ix_wa_template_tenant", "tenant_id"),
        Index(
            "ix_wa_template_meta_id",
            "waba_id",
            "meta_template_id",
            postgresql_where=sql_now("meta_template_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=sql_now("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    waba_id: Mapped[str] = mapped_column(Text, nullable=False)
    phone_number_row_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    meta_template_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    quality: Mapped[str | None] = mapped_column(Text, nullable=True)
    components: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=sql_now("'[]'::jsonb")
    )
    rejected_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=sql_now("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(server_default=sql_now("now()"), nullable=False)


class WhatsAppOptIn(Base):
    """One consent to receive a tenant's WhatsApp messages (0060, WA-19).

    One row per `(tenant_id, phone_e164)`. A revocation sets `revoked_at` and keeps the
    row: it is the evidence the audience must exclude that phone. `consent_text` is the
    text the person agreed to, stored with the row.
    """

    __tablename__ = "whatsapp_opt_ins"
    __table_args__ = (
        UniqueConstraint("tenant_id", "phone_e164", name="uq_wa_opt_in_tenant_phone"),
        CheckConstraint(f"source IN ({_sql_list(OPT_IN_SOURCES)})", name="ck_wa_opt_in_source"),
        CheckConstraint(r"phone_e164 ~ '^\+[1-9][0-9]{7,14}$'", name="ck_wa_opt_in_phone_e164"),
        CheckConstraint(
            "length(btrim(consent_text)) > 0", name="ck_wa_opt_in_consent_text_not_blank"
        ),
        Index("ix_wa_opt_in_tenant", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=sql_now("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    brand_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("brands.id"), nullable=True
    )
    phone_e164: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    consent_text: Mapped[str] = mapped_column(Text, nullable=False)
    consent_policy_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    proof: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sql_now("now()"), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class WhatsAppCampaign(Base):
    """One marketing send from one number with one template (0060, WA-20).

    `audience_filter` is evaluated against live opt-ins at launch; `send_components` is
    the `components` array of the template send body (its parameters), passed verbatim to
    `client.build_template_body`; `max_per_minute` paces the outbox rows it enqueues.
    """

    __tablename__ = "whatsapp_campaigns"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_wa_campaign_id_tenant"),
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_wa_campaign_conn_tenant",
        ),
        ForeignKeyConstraint(
            ["template_id", "tenant_id"],
            ["whatsapp_templates.id", "whatsapp_templates.tenant_id"],
            name="fk_wa_campaign_template_tenant",
        ),
        CheckConstraint(
            f"status IN ({_sql_list(CAMPAIGN_STATUSES)})", name="ck_wa_campaign_status"
        ),
        CheckConstraint("max_per_minute BETWEEN 1 AND 1000", name="ck_wa_campaign_max_per_minute"),
        CheckConstraint("length(btrim(name)) > 0", name="ck_wa_campaign_name_not_blank"),
        Index("ix_wa_campaign_tenant", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=sql_now("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    brand_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("brands.id"), nullable=True
    )
    connection_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    template_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    audience_filter: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sql_now("'{}'::jsonb")
    )
    send_components: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=sql_now("'[]'::jsonb")
    )
    max_per_minute: Mapped[int] = mapped_column(Integer, nullable=False, server_default="30")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(server_default=sql_now("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(server_default=sql_now("now()"), nullable=False)


class WhatsAppCampaignSend(Base):
    """One recipient of one campaign (0060, WA-20). UNIQUE `(campaign_id, phone_e164)`:
    relaunching never sends twice. `wamid` and the `sent`/`failed`/`skipped` settle are
    mirrored from the outbox row by the trigger `wa_outbox_campaign_mirror`; receipts
    (`delivered`/`read`/`failed`, `price_category`) arrive by `wamid` from the webhook."""

    __tablename__ = "whatsapp_campaign_sends"
    __table_args__ = (
        UniqueConstraint("campaign_id", "phone_e164", name="uq_wa_campaign_send_phone"),
        ForeignKeyConstraint(
            ["campaign_id", "tenant_id"],
            ["whatsapp_campaigns.id", "whatsapp_campaigns.tenant_id"],
            name="fk_wa_campaign_send_campaign_tenant",
        ),
        ForeignKeyConstraint(
            ["outbox_id", "tenant_id"],
            ["whatsapp_outbox.id", "whatsapp_outbox.tenant_id"],
            name="fk_wa_campaign_send_outbox_tenant",
        ),
        CheckConstraint(
            f"status IN ({_sql_list(CAMPAIGN_SEND_STATUSES)})", name="ck_wa_campaign_send_status"
        ),
        CheckConstraint(
            "cost_estimate IS NULL OR cost_estimate >= 0", name="ck_wa_campaign_send_cost"
        ),
        Index("ix_wa_campaign_send_tenant", "tenant_id"),
        Index("ix_wa_campaign_send_campaign_status", "campaign_id", "status"),
        Index("ix_wa_campaign_send_wamid", "wamid", postgresql_where=sql_now("wamid IS NOT NULL")),
        Index(
            "ix_wa_campaign_send_outbox",
            "outbox_id",
            postgresql_where=sql_now("outbox_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=sql_now("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    campaign_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    phone_e164: Mapped[str] = mapped_column(Text, nullable=False)
    outbox_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    wamid: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_category: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_estimate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    currency: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=sql_now("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(server_default=sql_now("now()"), nullable=False)

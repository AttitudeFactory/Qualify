"""ORM models for the WhatsApp module (WA-04). DDL/RLS/grants are migration 0057's job;
these mirror it for typed access via the sanctioned sessions — same relationship
`inbox/models.py` has to 0004.

All three tables carry a denormalized `tenant_id` with a composite FK to their parent
(`social_connections` or `threads`, R2 discipline), so a row whose tenant disagrees with
its connection or thread is structurally unbuildable. The conversation itself is NOT here:
a WhatsApp chat is a `Thread` with `channel = 'whatsapp'` and its `Message`s, the same
inbox tables Instagram DMs use (0057 widened `ck_thread_channel`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
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

    `menu_version_id` is a bare uuid until the menu tables exist (WA-14 adds the FK, the
    way 0045 added the FK on `content_drafts.campaign_id`).
    """

    __tablename__ = "whatsapp_thread_state"
    __table_args__ = (
        ForeignKeyConstraint(
            ["thread_id", "tenant_id"],
            ["threads.id", "threads.tenant_id"],
            name="fk_wa_thread_state_thread_tenant",
        ),
        Index("ix_wa_thread_state_tenant", "tenant_id"),
    )

    thread_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    menu_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    node_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    context: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=sql_now("'{}'::jsonb")
    )
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

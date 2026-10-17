"""ORM models for the Conversaciones module (QUA-226, E1). DDL/RLS/grants are migration
0063's job; these mirror it for typed access via the sanctioned sessions — the same
relationship `whatsapp/models.py` has to 0057. The conversation itself is NOT here: a
private thread is an `inbox.models.Thread` with `channel = 'dm'` and its `Message`s
(0004), which 0063 only widened with `external_conversation_id` and `last_read_at`.
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
    PrimaryKeyConstraint,
    Text,
)
from sqlalchemy import (
    text as sql_now,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from qualify_api.conversations.contracts import AccessStatus
from qualify_api.tenancy.models import Base

OUTBOX_CHANNELS: tuple[str, ...] = ("dm",)
OUTBOX_KINDS: tuple[str, ...] = ("reply",)
OUTBOX_STATUSES: tuple[str, ...] = ("pending", "sending", "sent", "failed", "dead")
ACCESS_STATUSES: tuple[str, ...] = tuple(status.value for status in AccessStatus)
SYNC_STATUSES: tuple[str, ...] = ("ok", "partial", "failed")


def _sql_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


class ConversationSyncState(Base):
    """One row per `(connection, channel)`: the access verdict and the last sync."""

    __tablename__ = "conversation_sync_state"
    __table_args__ = (
        PrimaryKeyConstraint("connection_id", "channel", name="pk_conversation_sync_state"),
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_conv_sync_state_conn_tenant",
        ),
        CheckConstraint(
            f"access_status IN ({_sql_list(ACCESS_STATUSES)})",
            name="ck_conv_sync_state_access_status",
        ),
        CheckConstraint(
            f"last_sync_status IS NULL OR last_sync_status IN ({_sql_list(SYNC_STATUSES)})",
            name="ck_conv_sync_state_sync_status",
        ),
        Index("ix_conv_sync_state_tenant", "tenant_id"),
    )

    connection_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    access_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="unknown")
    access_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sync_cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_sync_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_sync_finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_sync_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sql_now("now()"), nullable=False
    )


class ConversationOutboxItem(Base):
    """One private message Qualify intends to send: the already-built wire body of the
    channel (`payload`), the queue columns, and — NOT NULL — the person who approved it.
    No row of this table can exist without a human (ADR 21c); see 0063's docstring for
    why this is a second outbox and not `whatsapp_outbox`."""

    __tablename__ = "conversation_outbox"
    __table_args__ = (
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_conv_outbox_conn_tenant",
        ),
        ForeignKeyConstraint(
            ["thread_id", "tenant_id"],
            ["threads.id", "threads.tenant_id"],
            name="fk_conv_outbox_thread_tenant",
        ),
        CheckConstraint(
            f"channel IN ({_sql_list(OUTBOX_CHANNELS)})", name="ck_conversation_outbox_channel"
        ),
        CheckConstraint(f"kind IN ({_sql_list(OUTBOX_KINDS)})", name="ck_conversation_outbox_kind"),
        CheckConstraint(
            f"status IN ({_sql_list(OUTBOX_STATUSES)})", name="ck_conversation_outbox_status"
        ),
        CheckConstraint("attempts >= 0", name="ck_conversation_outbox_attempts"),
        Index("ix_conv_outbox_tenant", "tenant_id"),
        Index("ix_conv_outbox_claim", "status", "next_attempt_at"),
        Index("ix_conv_outbox_thread", "thread_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=sql_now("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    connection_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    thread_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="reply")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sql_now("now()"), nullable=False
    )
    locked_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    external_message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    draft_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    # A media reply: the R2 object the sender links into a public URL at send time.
    media_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_content_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sql_now("now()"), nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

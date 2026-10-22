"""ORM model for `interaction_followups` (m-24789646). DDL/CHECKs/RLS/grants are
migration 0071's job; this mirrors it for typed access via the sanctioned sessions — the
same relationship `conversations/models.py` has to 0065.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, Text
from sqlalchemy import text as sql_now
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from qualify_api.tenancy.models import Base


class InteractionFollowup(Base):
    """One interaction (a comment or a story reply) a person may continue in private."""

    __tablename__ = "interaction_followups"
    __table_args__ = (
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_followup_conn_tenant",
        ),
        ForeignKeyConstraint(
            ["origin_message_id", "tenant_id"],
            ["messages.id", "messages.tenant_id"],
            name="fk_followup_message_tenant",
        ),
        ForeignKeyConstraint(
            ["dm_thread_id", "tenant_id"],
            ["threads.id", "threads.tenant_id"],
            name="fk_followup_thread_tenant",
        ),
        ForeignKeyConstraint(
            ["intent_result_id", "tenant_id"],
            ["comment_intent_results.id", "comment_intent_results.tenant_id"],
            name="fk_followup_intent_tenant",
        ),
        ForeignKeyConstraint(
            ["outbox_id", "tenant_id"],
            ["conversation_outbox.id", "conversation_outbox.tenant_id"],
            name="fk_followup_outbox_tenant",
        ),
        Index("ix_followup_tenant", "tenant_id"),
        Index("ix_followup_queue", "connection_id", "status", "created_at"),
        Index("ix_followup_thread", "dm_thread_id"),
        # The CHECKs, the UNIQUE on origin_message_id and the partial unique index on
        # notice_external_id live only in the migration: Postgres enforces them.
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=sql_now("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    connection_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    origin_kind: Mapped[str] = mapped_column(Text, nullable=False)
    origin_message_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    dm_thread_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    trigger: Mapped[str] = mapped_column(Text, nullable=False)
    intent_result_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    send_route: Mapped[str | None] = mapped_column(Text, nullable=True)
    outbox_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    notice_status: Mapped[str] = mapped_column(Text, nullable=False)
    notice_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    notice_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    notice_external_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    notice_error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    notice_posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The notice queue (0074): backoff after a transient error, and the claim's lock.
    notice_next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notice_locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notice_locked_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sql_now("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sql_now("now()"), nullable=False
    )

"""ORM model for `comment_intent_results` (m-24789644). DDL/CHECKs/RLS/grants are
migration 0069's job; this mirrors it for typed access via the sanctioned sessions — same
relationship `sentiment/models.py` has to 0012.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, ForeignKeyConstraint, Index, Text
from sqlalchemy import text as sql_now
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from qualify_api.tenancy.models import Base


class CommentIntentResult(Base):
    """One (comment, analysis version) intent signal. Append-only — superseded by a new
    row under a new version, never edited (no UPDATE/DELETE grant, see 0069)."""

    __tablename__ = "comment_intent_results"
    __table_args__ = (
        ForeignKeyConstraint(
            ["message_id", "tenant_id"],
            ["messages.id", "messages.tenant_id"],
            name="fk_comment_intent_message_tenant",
        ),
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_comment_intent_conn_tenant",
        ),
        Index("ix_comment_intent_message", "message_id"),
        # The CHECKs and the COALESCE unique index live only in the migration, like
        # 0012's: Postgres enforces them at INSERT time; nothing queries through them.
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=sql_now("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    connection_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    message_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    detector_version: Mapped[str] = mapped_column(Text, nullable=False)
    pipeline_version: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    model_revision: Mapped[str | None] = mapped_column(Text, nullable=True)
    # {IntentClass value: confidence}, assigned classes only.
    confidences: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    commercial_intent: Mapped[bool] = mapped_column(Boolean, nullable=False)
    analyzed_at: Mapped[datetime] = mapped_column(server_default=sql_now("now()"), nullable=False)

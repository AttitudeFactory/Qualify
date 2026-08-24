"""ORM model for `comment_sentiment_results` (QUA-21). DDL/RLS/grants are migration
0012's job; this mirrors it for typed access via the sanctioned sessions — same
relationship `inbox/models.py` has to migrations 0004/0005/0010.

Carries the composite FK `(message_id, tenant_id) -> messages` and
`(connection_id, tenant_id) -> social_connections` (R2 discipline), so a row whose
tenant disagrees with either parent is structurally unbuildable.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, Float, ForeignKeyConstraint, Index, Text
from sqlalchemy import text as sql_now
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from qualify_api.tenancy.models import Base


class CommentSentimentResult(Base):
    """One (comment, model version) analysis. Append-only — see migration 0012's
    docstring for why there is no `UPDATE`/`DELETE` grant: a row is superseded by a
    new one under a new `detector_version`/`pipeline_version`/`model_id`/
    `model_revision`, never edited in place."""

    __tablename__ = "comment_sentiment_results"
    __table_args__ = (
        CheckConstraint("label IN ('POS','NEG','NEU')", name="ck_comment_sentiment_label"),
        ForeignKeyConstraint(
            ["message_id", "tenant_id"],
            ["messages.id", "messages.tenant_id"],
            name="fk_comment_sentiment_message_tenant",
        ),
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_comment_sentiment_conn_tenant",
        ),
        Index("ix_comment_sentiment_tenant", "tenant_id"),
        Index("ix_comment_sentiment_message", "message_id"),
        # The idempotency/versioning unique index (over COALESCE(model_revision, ''))
        # is created via raw SQL in the migration — SQLAlchemy's declarative Index
        # does not model expression indexes cleanly, and this table is never queried
        # by that index directly (Postgres enforces it at INSERT time); see 0012.
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=sql_now("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    connection_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    message_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    # = SentimentResult.source_id = messages.external_message_id, denormalized so the
    # row is self-explaining without a join.
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    detector_version: Mapped[str] = mapped_column(Text, nullable=False)
    pipeline_version: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    # NULL is a real, expected value — LocalRobertuitoSentimentProvider does not pin a
    # revision. See qualify_models.schemas.SentimentResult's docstring.
    model_revision: Mapped[str | None] = mapped_column(Text, nullable=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    analyzed_at: Mapped[datetime] = mapped_column(server_default=sql_now("now()"), nullable=False)

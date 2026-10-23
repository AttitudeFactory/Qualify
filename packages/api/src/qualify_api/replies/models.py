"""ORM model for `comment_reply_drafts` (QUA-22, comments tranche). DDL/RLS/grants/
trigger are migration 0014's job; this mirrors it for typed access via the sanctioned
sessions — same relationship `sentiment/models.py` has to migration 0012.

Carries the composite FKs `(message_id, tenant_id) -> messages`,
`(connection_id, tenant_id) -> social_connections`, and
`(sentiment_result_id, tenant_id) -> comment_sentiment_results` and, since 0080,
`(intent_result_id, tenant_id) -> comment_intent_results` (R2 discipline), so a row
whose tenant disagrees with any parent is structurally unbuildable.

0080 (m-24789645) added the grounding / review / cost / intent provenance columns and
replaced `UNIQUE(message_id)` with the partial unique index `uq_reply_draft_live_message`
(one LIVE draft per comment — see `LIVE_STATUSES`).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    Text,
)
from sqlalchemy import text as sql_now
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

# Registers `comment_intent_results` on the shared metadata so the 0080 composite FK
# below resolves, the same way the sentiment/messages tables are registered by import.
from qualify_api.intent import models as _intent_models  # noqa: F401
from qualify_api.tenancy.models import Base

#: Statuses that do NOT hold a comment's one live draft (0080's partial unique index):
#: a person discarded it, or Meta refused it (known not public). Everything else —
#: proposed, accepted, edited, sending, send_ambiguous, sent — is live, so a comment is
#: never answered publicly twice. Keep in sync with `uq_reply_draft_live_message`.
DEAD_STATUSES: Final = frozenset({"discarded", "send_failed"})
LIVE_STATUSES: Final = frozenset(
    {"proposed", "accepted", "edited", "sending", "send_ambiguous", "sent"}
)


class CommentReplyDraft(Base):
    """At most one LIVE assisted reply draft per comment (0080's partial unique index
    `uq_reply_draft_live_message`, status not in `DEAD_STATUSES`); a discarded or
    refused draft leaves room for a new one. Row-per-draft WITH
    UPDATE, same posture `PublishAttempt` has, not `CommentSentimentResult`'s
    append-only one: a draft is one logical operation (generate → decide → send), not a
    fact log. `settled_at` is terminal for `('sent','send_failed','discarded')` only —
    `send_ambiguous` is deliberately excluded, same reason `PublishService.advance()`
    never settles a transport-timeout outcome (see migration 0014's docstring)."""

    __tablename__ = "comment_reply_drafts"
    __table_args__ = (
        Index(
            "uq_reply_draft_live_message",
            "message_id",
            unique=True,
            postgresql_where=sql_now("status NOT IN ('discarded', 'send_failed')"),
        ),
        Index("ix_reply_draft_message", "message_id"),
        ForeignKeyConstraint(
            ["message_id", "tenant_id"],
            ["messages.id", "messages.tenant_id"],
            name="fk_reply_draft_message_tenant",
        ),
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_reply_draft_conn_tenant",
        ),
        ForeignKeyConstraint(
            ["sentiment_result_id", "tenant_id"],
            ["comment_sentiment_results.id", "comment_sentiment_results.tenant_id"],
            name="fk_reply_draft_sentiment_tenant",
        ),
        ForeignKeyConstraint(
            ["intent_result_id", "tenant_id"],
            ["comment_intent_results.id", "comment_intent_results.tenant_id"],
            name="fk_reply_draft_intent_tenant",
        ),
        CheckConstraint(
            "status IN ('proposed','accepted','edited','discarded','sending','sent',"
            "'send_failed','send_ambiguous')",
            name="ck_reply_draft_status",
        ),
        CheckConstraint(
            "sentiment_label IN ('POS','NEG','NEU')", name="ck_reply_draft_sentiment_label"
        ),
        Index("ix_reply_draft_tenant", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=sql_now("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    connection_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    message_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    # = messages.external_message_id, denormalized so the row is self-explaining.
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    sentiment_result_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    # Denormalized from comment_sentiment_results.label AT GENERATION TIME — audit trail
    # independent of whatever a later re-analysis might record.
    sentiment_label: Mapped[str] = mapped_column(Text, nullable=False)
    gate_reason: Mapped[str] = mapped_column(Text, nullable=False)
    generator_version: Mapped[str] = mapped_column(Text, nullable=False)
    generated_text: Mapped[str] = mapped_column(Text, nullable=False)
    # NULL until decided. Equal to generated_text on a plain accept, different on edit —
    # the diff is computed by comparing the two, never stored a third time.
    final_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=sql_now("now()"), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(nullable=True)
    decided_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    sent_at: Mapped[datetime | None] = mapped_column(nullable=True)
    external_reply_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    send_error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # --- 0080 (m-24789645): grounding, review verdict, cost and intent provenance ---
    # The validated facts the model was given (`assisted.grounding.Grounding.as_record`);
    # NULL on sentiment-era drafts, grounded on nothing.
    grounding: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    needs_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sql_now("false")
    )
    unsupported_claims: Mapped[list[str] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    model_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_revision: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    # The Fase A signal that made this comment a candidate (NULL on the QUA-22 path).
    intent_result_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

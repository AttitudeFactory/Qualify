"""ORM model for `story_proposals` (QUA-106, first slice). DDL/RLS/grants/trigger are
migration 0021's job; this mirrors it for typed access via the sanctioned sessions —
same relationship `replies/models.py` has to migration 0014.

Carries the composite FKs `(connection_id, tenant_id) -> social_connections` and
`(publish_attempt_id, tenant_id) -> publish_attempts` (R2 discipline), so a row whose
tenant disagrees with either parent is structurally unbuildable.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Text,
)
from sqlalchemy import text as sql_now
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from qualify_api.tenancy.models import Base


class StoryProposal(Base):
    """One Story proposal awaiting human review (QUA-106). Row-per-proposal WITH
    UPDATE, same posture `CommentReplyDraft`/`PublishAttempt` have: a proposal is one
    logical operation (propose -> decide -> publish), not a fact log. `settled_at` is
    terminal for `('rejected','published','publish_failed')` only."""

    __tablename__ = "story_proposals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_story_proposal_conn_tenant",
        ),
        ForeignKeyConstraint(
            ["publish_attempt_id", "tenant_id"],
            ["publish_attempts.id", "publish_attempts.tenant_id"],
            name="fk_story_proposal_attempt_tenant",
        ),
        CheckConstraint(
            "status IN ('proposed','approved','edited','rejected','publishing',"
            "'published','publish_failed')",
            name="ck_story_proposal_status",
        ),
        Index("ix_story_proposal_tenant", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=sql_now("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    connection_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    media_object_key: Mapped[str] = mapped_column(Text, nullable=False)
    media_content_type: Mapped[str] = mapped_column(Text, nullable=False)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    # NULL until decided. Equal to caption on a plain approve, different on edit — the
    # diff (if any) is computed at read time, never stored a third time.
    final_caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Reference only — never sent to Meta in this slice (no `audio_configuration`).
    trend_audio_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    trend_audio_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    publish_attempt_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    publish_error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=sql_now("now()"), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(nullable=True)
    decided_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    settled_at: Mapped[datetime | None] = mapped_column(nullable=True)

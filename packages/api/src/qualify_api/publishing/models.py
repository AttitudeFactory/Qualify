"""ORM models for the publishing module (A4, layer L1). DDL/RLS/grants/trigger are the
migration's job (0003); these mirror it for typed access via the sanctioned sessions.

Two shapes worth naming:
- `publish_attempts` is the WRITE-AHEAD record: a row exists before the first platform
  call, `creation_id` is null until Meta returns a container, and `settled_at` non-null is
  terminal — made one-way by the `publish_attempts_settle_once` trigger, which no code
  path here may work around (the migration says so in as many words).
- Both tables carry the composite FK `(connection_id, tenant_id)` → `social_connections`,
  so a child row whose tenant disagrees with its parent connection is structurally
  unbuildable (same R2 discipline as the connections module).
- The column is `media_product_type`, never `media_type`: Meta's `media_type` reads back
  VIDEO even for a story (`content-publishing.md:230,262`).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from qualify_api.tenancy.models import Base


class PublishAttempt(Base):
    __tablename__ = "publish_attempts"
    __table_args__ = (
        UniqueConstraint("connection_id", "idempotency_key", name="uq_attempt_idempotency"),
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_attempt_conn_tenant",
        ),
        Index("ix_attempt_tenant", "tenant_id"),
        Index("ix_attempt_reconcile", "tenant_id", "creation_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    connection_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    scheduled_post_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    # Caller-chosen operation identity — what makes "no blind retry" (ADR 22e) implementable.
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    # QUA-99 (4.5/6) — CAROUSEL-only in practice. A single video never reads this back:
    # start() consumes its caption synchronously within one create_container() call and
    # never persists it. A carousel's caption is needed later, inside a LATER advance()
    # call (_create_carousel, service.py) that has no other way to receive one — this
    # column is that bridge. NULL for every single-video attempt.
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Null until Meta returns the container; reconciliation enters by this value.
    creation_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_product_type: Mapped[str] = mapped_column(Text, nullable=False)
    adapter_version: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    platform_error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Meta's OWN judgement from a rupload failure — never inferred from a timeout.
    retriable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    raw_response_r2_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_media_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
    # Non-null == terminal; the settle_once trigger makes that one-way.
    settled_at: Mapped[datetime | None] = mapped_column(nullable=True)


class PublishAttemptChild(Base):
    """One child container of a carousel attempt (QUA-99, 2/6) — schema only, not yet read
    or written by any service code (that lands in commits 3/6 and 4/6).

    VIDEO-ONLY, matching the CHECK in migration 0016: `media_product_type` accepts only
    `REELS`/`STORIES`/`VIDEO`, the same set `publish_attempts` and `RESUMABLE_MEDIA_TYPES`
    (`client.py`) already accept. No `IMAGE` value exists here.

    No `settled_at`/settle-once trigger, unlike `PublishAttempt` — nothing here is ever
    handed to `media_publish` (only the CAROUSEL container `PublishAttempt.creation_id`
    eventually is), so there is no irreversible transition at this table's layer to guard.
    """

    __tablename__ = "publish_attempt_children"
    __table_args__ = (
        UniqueConstraint("attempt_id", "position", name="uq_attempt_child_position"),
        ForeignKeyConstraint(
            ["attempt_id", "tenant_id"],
            ["publish_attempts.id", "publish_attempts.tenant_id"],
            name="fk_attempt_child_attempt_tenant",
        ),
        Index("ix_attempt_child_tenant", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    attempt_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    # Display order inside the carousel (0-indexed) — Instagram shows children in the
    # order `children` was sent when the CAROUSEL container was created, not row/insertion
    # order, which Postgres does not guarantee to preserve across an UPDATE.
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    media_object_key: Mapped[str] = mapped_column(Text, nullable=False)
    media_content_type: Mapped[str] = mapped_column(Text, nullable=False)
    media_product_type: Mapped[str] = mapped_column(Text, nullable=False)
    # Null until Meta returns THIS child's own container — distinct from the parent
    # `PublishAttempt.creation_id`, which (once every child is ready) holds the CAROUSEL
    # container's id, never a child's.
    creation_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    platform_error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)


class ScheduledPost(Base):
    __tablename__ = "scheduled_posts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_sched_conn_tenant",
        ),
        Index("ix_sched_tenant", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    connection_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    media_object_key: Mapped[str] = mapped_column(Text, nullable=False)
    media_content_type: Mapped[str] = mapped_column(Text, nullable=False)
    media_product_type: Mapped[str] = mapped_column(Text, nullable=False)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    # A frame of the video itself; `cover_url` is deliberately absent (ADR 28).
    thumb_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scheduled_for: Mapped[datetime] = mapped_column(nullable=False)
    scheduled_tz: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)

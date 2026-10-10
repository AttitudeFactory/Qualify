"""ORM models for the inbox module (B2/B3 + monitored-media + the Meta call ledger).
DDL/RLS/grants are the migrations' job (0004 for `threads`/`messages`, 0005 for
`monitored_media`, 0010 for `inbox_meta_call_log`); these mirror them for typed access via
the sanctioned sessions — same relationship `publishing/models.py` has to `0003`.

All four tables carry the composite FK `(connection_id, tenant_id) -> social_connections`
(R2 discipline), so a child row whose tenant disagrees with its parent connection is
structurally unbuildable.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    text as sql_now,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from qualify_api.tenancy.models import Base


class MonitoredMedia(Base):
    __tablename__ = "monitored_media"
    __table_args__ = (
        UniqueConstraint(
            "connection_id", "external_media_id", name="uq_monitored_media_natural_key"
        ),
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_monitored_media_conn_tenant",
        ),
        Index("ix_monitored_media_tenant", "tenant_id"),
        Index("ix_monitored_media_active", "connection_id", "is_monitored"),
        CheckConstraint(
            "metadata_error IS NULL OR metadata_error IN "
            "('transient', 'permission', 'rate_limited', 'unknown')",
            name="ck_monitored_media_metadata_error",
        ),
        CheckConstraint(
            "metadata_fetched_at IS NULL OR media_posted_at IS NOT NULL",
            name="ck_monitored_media_fetched_has_posted_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=sql_now("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    connection_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    external_media_id: Mapped[str] = mapped_column(Text, nullable=False)
    # A column, not row presence — toggling is an UPDATE, never a delete+reinsert. See
    # the migration's docstring for why.
    is_monitored: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=sql_now("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(server_default=sql_now("now()"), nullable=False)
    # QUA-149 (0046): the media's own metadata, kept so it stays readable after the
    # 14-day window ends. NULL on rows monitored before 0046 until the sync reads them once.
    media_posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    permalink: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_product_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    metadata_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    metadata_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # QUA-146 (0047): Meta's `media_type`, verbatim and without a CHECK — an unknown
    # value is kept, and interpreted only by `qualify_api.inbox.media_type`. NULL = not
    # read yet (0047 backfilled `VIDEO` on Reels only).
    media_type: Mapped[str | None] = mapped_column(Text, nullable=True)


class Thread(Base):
    __tablename__ = "threads"
    __table_args__ = (
        UniqueConstraint(
            "connection_id", "channel", "external_thread_id", name="uq_thread_natural_key"
        ),
        UniqueConstraint("id", "tenant_id", name="uq_thread_id_tenant"),
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_thread_conn_tenant",
        ),
        CheckConstraint("channel IN ('comment','dm')", name="ck_thread_channel"),
        CheckConstraint("status IN ('open','closed')", name="ck_thread_status"),
        Index("ix_thread_tenant", "tenant_id"),
        Index("ix_thread_inbox_order", "tenant_id", "last_message_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=sql_now("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    connection_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    external_thread_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    assigned_agent_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    # Inbox ordering only. NEVER the basis of a messaging window (0004's B2 condition).
    last_message_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_inbound_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=sql_now("now()"), nullable=False)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("connection_id", "external_message_id", name="uq_message_external_id"),
        ForeignKeyConstraint(
            ["thread_id", "tenant_id"],
            ["threads.id", "threads.tenant_id"],
            name="fk_message_thread_tenant",
        ),
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_message_conn_tenant",
        ),
        CheckConstraint("direction IN ('inbound','outbound')", name="ck_message_direction"),
        Index("ix_message_tenant", "tenant_id"),
        Index("ix_message_thread", "thread_id", "posted_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=sql_now("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    thread_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    connection_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    external_message_id: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    # An IGSID: stable per app/account, NOT a portable user identity
    # (`ig_shapes.IGSID_IS_PORTABLE_IDENTITY is False`). Never join it against another
    # person identifier.
    author_external_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_username: Mapped[str | None] = mapped_column(Text, nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(server_default=sql_now("now()"), nullable=False)
    raw_payload_r2_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Which version of the QUA-67 contract parsed this row.
    shape_version: Mapped[str] = mapped_column(Text, nullable=False)
    # QUA-101: non-NULL means Meta stopped returning this comment on a COMPLETE walk of
    # its media (`InboxRepository.reconcile_media_comments`) — never a physical DELETE,
    # so `comment_sentiment_results`/`comment_reply_drafts` FKs (0012/0014) stay intact.
    # Cleared automatically if Meta shows the comment again (see that method's docstring
    # for why a restore, not a real delete-then-undelete, is the likely explanation).
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)


class InboxMetaCallLog(Base):
    """One row per real Meta Graph API call made by `InboxService.sync_comments` — the
    ledger `InboxRepository.calls_in_last_hour`/`record_call` count against (QUA-88).

    Append-only by design, same posture `ClaritySnapshot` already establishes for
    budgeting a vendor call from a ledger of rows rather than a counter that could drift
    from reality: one row IS one spent call, so counting rows counts spent budget. No
    `UPDATE`/`DELETE` grant is expected — a call, once made, was made.

    Deliberately narrow scope: only `CommentsClient.list_comments` calls made inside
    `sync_comments` are logged here, not `MediaClient` calls made by
    `list_candidate_media`/`set_media_monitored` (the picker and the toggle). QUA-88
    scopes the budget to the manual sync path specifically; widening it to every Meta
    call this module makes is a known, disclosed gap, not an oversight.

    No retention/pruning implemented yet — same deferred posture `clarity_snapshots` has.
    At today's scale (manual trigger, one tenant) row growth is trivial; revisit if this
    ever becomes automated/scheduled.
    """

    __tablename__ = "inbox_meta_call_log"
    __table_args__ = (
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_inbox_meta_call_log_conn_tenant",
        ),
        Index("ix_inbox_meta_call_log_conn_called", "connection_id", "called_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=sql_now("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    connection_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    called_at: Mapped[datetime] = mapped_column(server_default=sql_now("now()"), nullable=False)

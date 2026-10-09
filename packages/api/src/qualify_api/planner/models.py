"""ORM model for the Planificador (QUA-108). DDL/RLS/grants are the migration's job
(0024); this mirrors it for typed access through the sanctioned sessions.

A `CalendarEvent` holds planning state only — which POST, which connection, which
instant. Nothing about the content lives here: that is the POST's (QUA-109), read
through `PostReader`.
"""

from __future__ import annotations

from datetime import datetime
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
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

# Registered on the shared metadata so the composite FKs below resolve at flush time.
from qualify_api.connections import models as _connections_models  # noqa: F401
from qualify_api.publishing import models as _publishing_models  # noqa: F401
from qualify_api.tenancy.models import Base


class CalendarEvent(Base):
    __tablename__ = "calendar_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_cal_event_conn_tenant",
        ),
        ForeignKeyConstraint(
            ["publish_attempt_id", "tenant_id"],
            ["publish_attempts.id", "publish_attempts.tenant_id"],
            name="fk_cal_event_attempt_tenant",
        ),
        UniqueConstraint("id", "tenant_id", name="uq_cal_event_id_tenant"),
        CheckConstraint(
            "status IN ('scheduled','cancelled','publishing','published','failed')",
            name="ck_cal_event_status",
        ),
        CheckConstraint("revision >= 1", name="ck_cal_event_revision"),
        CheckConstraint(
            "output_port IS NULL OR output_port <> ''", name="ck_cal_event_output_port"
        ),
        CheckConstraint(
            "destination IS NULL OR destination IN ('post','reel','story')",
            name="ck_cal_event_destination",
        ),
        CheckConstraint(
            "goals <@ ARRAY['likes','views','comments','ads','followers','engagement']::text[]",
            name="ck_cal_event_goals",
        ),
        Index("ix_cal_event_tenant", "tenant_id"),
        Index("ix_cal_event_brand_scheduled", "brand_id", "scheduled_at"),
        Index("ix_cal_event_post", "tenant_id", "post_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    brand_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("brands.id"), nullable=False
    )
    # No FK until QUA-109 exists — see migration 0024.
    post_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    connection_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scheduled_tz: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    publish_attempt_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    # MP-11 (0040): the one template output this event publishes (`image_assets.output_port`:
    # `reel` / `feed` / `story`), or NULL for the whole POST — every pre-MP-11 event.
    output_port: Mapped[str | None] = mapped_column(Text, nullable=True)
    # QUA-118 v2 (0041): where this event goes out — `post` («Publicación»), `reel` or
    # `story`. The POST's category stays the origin; the event decides the destination.
    # NULL only for an event the backfill could not derive (its POST is gone).
    destination: Mapped[str | None] = mapped_column(Text, nullable=True)
    # QUA-118 v2 (0042): the goals of the plan this event was created in (`EVENT_GOALS`
    # keys) — kept for the later analysis of what each publication was meant to achieve.
    goals: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


# The goals a plan may set (0042's `ck_cal_event_goals`): likes, vistas, comentarios,
# ads, seguidores, interacción.
EVENT_GOALS: tuple[str, ...] = ("likes", "views", "comments", "ads", "followers", "engagement")

# Palette keys a tag may use — mirrors 0025's `ck_planner_tag_color`. The UI maps each
# key to a Radix scale; adding a key means a migration AND a UI mapping.
TAG_COLORS: tuple[str, ...] = ("teal", "blue", "violet", "pink", "amber", "green", "orange", "gray")


class PlannerTag(Base):
    """A planning label ("Campaña octubre"), per tenant. Name unique ignoring case."""

    __tablename__ = "planner_tags"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_planner_tag_id_tenant"),
        CheckConstraint("char_length(btrim(name)) BETWEEN 1 AND 40", name="ck_planner_tag_name"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    color: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


class CalendarEventTag(Base):
    """Event ↔ tag link. Both FKs carry `tenant_id` (see migration 0025)."""

    __tablename__ = "calendar_event_tags"
    __table_args__ = (
        ForeignKeyConstraint(
            ["event_id", "tenant_id"],
            ["calendar_events.id", "calendar_events.tenant_id"],
            name="fk_cal_event_tag_event_tenant",
        ),
        ForeignKeyConstraint(
            ["tag_id", "tenant_id"],
            ["planner_tags.id", "planner_tags.tenant_id"],
            name="fk_cal_event_tag_tag_tenant",
        ),
        Index("ix_cal_event_tag_tag", "tenant_id", "tag_id"),
    )

    event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tag_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)

"""ORM mapping of `support_requests` (migration 0056). Alembic owns the DDL, including the
RLS policy; this class exists so the service can read and write rows by name."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from qualify_api.tenancy.models import Base


class SupportRequest(Base):
    """One "Pedir ayuda 1:1" request from a tenant (QUA-202).

    `context` carries only what the screen knew about the failed attempt — the outcome
    code and the two R9(e.1) counts — never a Page id, a username or a token. `status` is
    the support team's, not the operator's: `open` on creation, `contacted` once someone
    reached out, `closed` when done."""

    __tablename__ = "support_requests"
    __table_args__ = (
        CheckConstraint(
            "topic IN ('connect_accounts','more_creations','other')",
            name="ck_support_requests_topic",
        ),
        CheckConstraint(
            "status IN ('open','contacted','closed')", name="ck_support_requests_status"
        ),
        CheckConstraint("contact_email <> ''", name="ck_support_requests_contact_email"),
        Index("ix_support_requests_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    requested_by_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    topic: Mapped[str] = mapped_column(String, nullable=False)
    contact_email: Mapped[str] = mapped_column(Text, nullable=False)
    contact_whatsapp: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    message: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    context: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="open")
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

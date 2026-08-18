"""ORM models for the clarity module. DDL/RLS/grants are the migration's job (0006);
these mirror it for typed access via the sanctioned sessions.

The custody call worth naming: `token_ciphertext`/`token_key_id` follow the C-03
Encryptor seam but NOT the `qualify_credential` role ceremony — a Data Export token
can only read aggregated analytics, so it gets encrypted-at-rest custody through the
normal RLS-scoped session rather than a dedicated database role. See 0006's docstring.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from qualify_api.tenancy.models import Base


class ClaritySettings(Base):
    __tablename__ = "clarity_settings"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_clarity_settings_tenant"),
        Index("ix_clarity_settings_tenant", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    # Clarity's project id — appears in the dashboard URL and the tracking snippet.
    project_id: Mapped[str] = mapped_column(Text, nullable=False)
    token_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    token_key_id: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ClaritySnapshot(Base):
    __tablename__ = "clarity_snapshots"
    __table_args__ = (Index("ix_clarity_snapshots_tenant_fetched", "tenant_id", "fetched_at"),)

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    num_of_days: Mapped[int] = mapped_column(Integer, nullable=False)
    dimensions: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    # The API response verbatim: [{"metricName": ..., "information": [...]}, ...].
    payload: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

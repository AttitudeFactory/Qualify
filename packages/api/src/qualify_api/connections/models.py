"""ORM models for the connections module (C-03). DDL/RLS/column-grants are the migration's
job (0002); these mirror it for typed access via the sanctioned sessions.

Key rulings encoded in the shapes:
- `platform_apps` is GLOBAL (no `tenant_id`, no RLS) — Qualify's own Meta apps; every
  tenant connects through the same row (R1). `social_connections.platform_app_id` records
  which app/api_version obtained a payload (provenance, not scoping).
- `oauth_credentials` and `connection_events` carry a denormalized `tenant_id` with a
  COMPOSITE FK `(connection_id, tenant_id) -> social_connections(id, tenant_id)` (R2), so a
  child row whose tenant disagrees with its parent connection is structurally unbuildable.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from qualify_api.tenancy.models import Base


class PlatformApp(Base):
    __tablename__ = "platform_apps"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    app_id: Mapped[str] = mapped_column(Text, nullable=False)
    secret_ref: Mapped[str] = mapped_column(Text, nullable=False)  # a reference, never the secret
    api_version: Mapped[str] = mapped_column(Text, nullable=False)
    config_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)


class SocialConnection(Base):
    __tablename__ = "social_connections"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "platform", "external_account_id", name="uq_conn_natural_key"
        ),
        # Anti-drift target for the composite FKs from child tables (R2).
        UniqueConstraint("id", "tenant_id", name="uq_conn_id_tenant"),
        Index("ix_conn_tenant", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    brand_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("brands.id"), nullable=True
    )
    platform_app_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("platform_apps.id"), nullable=False
    )
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    account_type: Mapped[str] = mapped_column(Text, nullable=False)
    external_account_id: Mapped[str] = mapped_column(Text, nullable=False)
    external_username: Mapped[str | None] = mapped_column(Text, nullable=True)
    linked_page_id: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # ADR 25 (row only exists post-link)
    granted_scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    access_posture: Mapped[str] = mapped_column(Text, nullable=False)  # ADR 22a: data
    current_credential_version: Mapped[int] = mapped_column(Integer, nullable=False)
    connected_by_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    connected_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))
    last_verified_at: Mapped[datetime | None] = mapped_column(nullable=True)
    disconnected_at: Mapped[datetime | None] = mapped_column(nullable=True)


class OAuthCredential(Base):
    __tablename__ = "oauth_credentials"
    __table_args__ = (
        UniqueConstraint("connection_id", "version", name="uq_cred_conn_version"),
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_cred_conn_tenant",
        ),
        Index("ix_cred_tenant", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    connection_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    token_type: Mapped[str] = mapped_column(Text, nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_id: Mapped[str] = mapped_column(Text, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))


class ConnectionEvent(Base):
    __tablename__ = "connection_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_event_conn_tenant",
        ),
        Index("ix_event_tenant", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    connection_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    credential_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)  # 'user' | 'system'
    platform_error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response_r2_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(nullable=False, server_default=text("now()"))

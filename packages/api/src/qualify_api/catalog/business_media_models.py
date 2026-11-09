"""ORM models of the Galería's business media and its job queue (migration 0133,
m-24955918, ADR 47). DDL, CHECKs, RLS and grants are Alembic's; these mirror them for
typed access through `tenant_session`.

- `BusinessMedia` — a photo or video of the business (not of a product), its files in R2
  under `gallery/{tenant}/{id}/`. `deleted_at` is the tombstone: every read filters it.
- `GalleryJob` — one unit of `media-worker` work (`ingest` now, `cut` in CM-3).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from qualify_api.tenancy.models import Base

JOB_INGEST = "ingest"
JOB_CUT = "cut"

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_PARTS_SAVED = "parts_saved"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
#: Non-terminal statuses: the ones the partial unique indexes of 0133 cover.
ACTIVE_STATUSES: tuple[str, ...] = (STATUS_QUEUED, STATUS_RUNNING, STATUS_PARTS_SAVED)

INGEST_PIPELINE_VERSION = "gallery-ingest-v1"
CUT_PIPELINE_VERSION = "gallery-cut-v1"


class BusinessMedia(Base):
    __tablename__ = "business_media"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    brand_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    media_type: Mapped[str] = mapped_column(Text, nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    poster_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    has_audio: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    filename: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    upload_sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_media_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    cut_start_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cut_end_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    job_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    pipeline_version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GalleryJob(Base):
    __tablename__ = "gallery_jobs"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    brand_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=STATUS_QUEUED)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    staged_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    filename: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    upload_sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source_media_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    segments: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    pipeline_version: Mapped[str] = mapped_column(Text, nullable=False)
    # 0145 (m-24976891): a `seasonal_media` job's payload (`whatsapp.seasonal`); NULL for
    # `ingest`/`cut`. SQL NULL, never JSON `null` (the CHECK takes NULL or an object).
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

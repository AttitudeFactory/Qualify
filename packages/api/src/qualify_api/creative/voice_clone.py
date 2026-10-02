"""The brand's own voice, cloned in HeyGen (§ request 2026-09-30; table 0032).

This module only keeps the record — one row per brand. The HeyGen round trip (upload
the sample, `POST /v3/voices/clone`, poll `GET /v3/voices/{id}`) lives with the caller,
which hands the results here. Cloning is manual and needs the operator's consent, so
`record` requires who consented; cloning again replaces the row and returns the old
HeyGen voice id, for the caller to delete there (a HeyGen account holds a limited number
of clones)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.creative.models import BrandVoiceClone as CloneRow

#: HeyGen's own clone states (`GET /v3/voices/{id}` → `status`).
PROCESSING = "processing"
COMPLETE = "complete"
FAILED = "failed"
CLONE_STATUSES = frozenset({PROCESSING, COMPLETE, FAILED})


@dataclass(frozen=True)
class VoiceClone:
    heygen_voice_id: str
    name: str
    status: str
    failure_message: str
    language: str
    gender: str
    preview_audio_url: str
    consent_at: datetime

    @property
    def is_ready(self) -> bool:
        return self.status == COMPLETE


def _clone(row: CloneRow) -> VoiceClone:
    return VoiceClone(
        heygen_voice_id=row.heygen_voice_id,
        name=row.name,
        status=row.status,
        failure_message=row.failure_message or "",
        language=row.language or "",
        gender=row.gender or "",
        preview_audio_url=row.preview_audio_url or "",
        consent_at=row.consent_at,
    )


class VoiceCloneService:
    def current(self, *, tenant_id: UUID, brand_id: UUID) -> VoiceClone | None:
        with tenant_session(tenant_id) as session:
            row = session.scalar(select(CloneRow).where(CloneRow.brand_id == brand_id))
            return None if row is None else _clone(row)

    def record(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        heygen_voice_id: str,
        name: str,
        consent_by: UUID,
        language: str | None = None,
    ) -> str | None:
        """A clone just requested in HeyGen, in `processing`. Replaces the brand's
        previous one; returns that one's HeyGen id (None if there was none)."""
        now = datetime.now(UTC)
        with tenant_session(tenant_id) as session:
            row = session.scalar(select(CloneRow).where(CloneRow.brand_id == brand_id))
            replaced = None
            if row is None:
                row = CloneRow(tenant_id=tenant_id, brand_id=brand_id)
                session.add(row)
            elif row.heygen_voice_id != heygen_voice_id:
                replaced = row.heygen_voice_id
            row.heygen_voice_id = heygen_voice_id
            row.name = name
            row.status = PROCESSING
            row.failure_message = None
            row.language = language
            row.gender = None
            row.preview_audio_url = None
            row.consent_by = consent_by
            row.consent_at = now
            row.updated_at = now
            session.flush()
            return replaced

    def update_status(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        heygen_voice_id: str,
        status: str,
        failure_message: str | None = None,
        language: str | None = None,
        gender: str | None = None,
        preview_audio_url: str | None = None,
    ) -> VoiceClone | None:
        """What HeyGen says about the clone now. Ignored (None) when the brand's clone is
        no longer this one — a poll that outlived a re-clone must not overwrite it."""
        if status not in CLONE_STATUSES:
            raise ValueError(f"unknown clone status {status!r}")
        with tenant_session(tenant_id) as session:
            row = session.scalar(select(CloneRow).where(CloneRow.brand_id == brand_id))
            if row is None or row.heygen_voice_id != heygen_voice_id:
                return None
            row.status = status
            row.failure_message = failure_message
            if language:
                row.language = language
            if gender:
                row.gender = gender
            if preview_audio_url:
                row.preview_audio_url = preview_audio_url
            row.updated_at = datetime.now(UTC)
            session.flush()
            return _clone(row)

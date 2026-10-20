"""The brand's own voice, cloned (§ request 2026-09-30; table 0032, vendor-neutral 0066).

Since 2026-10-16 the voice is cloned in BytePlus Seed Speech (`provider="seed_speech"`,
`external_voice_id` = our own post-paid `qlf-…` id); rows cloned in HeyGen before then
still read (`provider="heygen"`) but no longer render — a brand re-clones.

This module only keeps the record — one row per brand. The vendor round trip (the clone
request, polling its status, copying the demo clip to R2) lives with the caller, which
hands the results here. Cloning is manual and needs the operator's consent, so `record`
requires who consented and the sentence they confirmed. Cloning again replaces the row
and returns the old voice's id: Seed Speech has NO delete API, so the caller can only log
it (an unused post-paid voice is deleted by BytePlus after 7 days; an activated one stays
in the account)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.creative.models import BrandVoiceClone as CloneRow

PROCESSING = "processing"
COMPLETE = "complete"
FAILED = "failed"
CLONE_STATUSES = frozenset({PROCESSING, COMPLETE, FAILED})
SEED_SPEECH = "seed_speech"
HEYGEN = "heygen"


@dataclass(frozen=True)
class VoiceClone:
    provider: str
    voice_id: str  # the id at its provider (`external_voice_id`)
    name: str
    status: str
    failure_message: str
    language: str
    gender: str
    preview_audio_url: str
    consent_at: datetime
    preview_object_key: str = ""
    sample_object_key: str = ""
    activated_at: datetime | None = None

    @property
    def is_ready(self) -> bool:
        """Ready to read a script — a Seed Speech voice only: a HeyGen clone of before
        2026-10-16 cannot render anywhere any more."""
        return self.status == COMPLETE and self.provider == SEED_SPEECH


def _clone(row: CloneRow) -> VoiceClone:
    return VoiceClone(
        provider=row.provider,
        voice_id=row.external_voice_id,
        name=row.name,
        status=row.status,
        failure_message=row.failure_message or "",
        language=row.language or "",
        gender=row.gender or "",
        preview_audio_url=row.preview_audio_url or "",
        consent_at=row.consent_at,
        preview_object_key=row.preview_object_key or "",
        sample_object_key=row.sample_object_key or "",
        activated_at=row.activated_at,
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
        voice_id: str,
        name: str,
        consent_by: UUID,
        consent_text: str,
        provider: str = SEED_SPEECH,
        language: str | None = None,
        sample_object_key: str | None = None,
    ) -> str | None:
        """A clone just requested, in `processing`. Replaces the brand's previous one;
        returns that one's id (None if there was none, or it was the same voice)."""
        now = datetime.now(UTC)
        with tenant_session(tenant_id) as session:
            row = session.scalar(select(CloneRow).where(CloneRow.brand_id == brand_id))
            replaced = None
            if row is None:
                row = CloneRow(tenant_id=tenant_id, brand_id=brand_id)
                session.add(row)
            elif row.external_voice_id != voice_id:
                replaced = row.external_voice_id
            row.provider = provider
            row.external_voice_id = voice_id
            row.heygen_voice_id = voice_id if provider == HEYGEN else None
            row.name = name
            row.status = PROCESSING
            row.failure_message = None
            row.language = language
            row.gender = None
            row.preview_audio_url = None
            row.preview_object_key = None
            row.sample_object_key = sample_object_key
            row.consent_text = consent_text
            row.activated_at = None
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
        voice_id: str,
        status: str,
        failure_message: str | None = None,
        language: str | None = None,
        gender: str | None = None,
        preview_object_key: str | None = None,
    ) -> VoiceClone | None:
        """What the provider says about the clone now. Ignored (None) when the brand's
        clone is no longer this one — a poll that outlived a re-clone must not overwrite
        it."""
        if status not in CLONE_STATUSES:
            raise ValueError(f"unknown clone status {status!r}")
        with tenant_session(tenant_id) as session:
            row = session.scalar(select(CloneRow).where(CloneRow.brand_id == brand_id))
            if row is None or row.external_voice_id != voice_id:
                return None
            row.status = status
            row.failure_message = failure_message
            if language:
                row.language = language
            if gender:
                row.gender = gender
            if preview_object_key:
                row.preview_object_key = preview_object_key
            row.updated_at = datetime.now(UTC)
            session.flush()
            return _clone(row)

    def mark_activated(self, *, tenant_id: UUID, brand_id: UUID, voice_id: str) -> None:
        """The voice's first real synthesis: Seed Speech charged its slot and fixed it.
        Idempotent — only the first call stamps the time."""
        with tenant_session(tenant_id) as session:
            row = session.scalar(select(CloneRow).where(CloneRow.brand_id == brand_id))
            if row is not None and row.external_voice_id == voice_id and row.activated_at is None:
                row.activated_at = datetime.now(UTC)
                session.flush()

"""The read seam for downstream modules (design §4.5) — publishing and the future Ads
module consume approved creative through THESE functions, as a Python import (ADR 1:
same process, no HTTP hop, exception types intact).

The gate is ``DraftStatus.is_artifact``: a ``GENERATED`` draft is work in progress, not
an artifact — nothing no human approved leaves the module (HITL #2). The copy handed
out is the selected variant's ``edited_copy`` when the human touched it, the model's
``copy`` otherwise, always as the frozen ``CopyPayload`` contract.

Image fields are optional in this slice: the MVP's no-model routes can legally produce a
copy-only draft (see ``service.run_generation``), and per §7.6 whatever image exists is
addressed by the draft, never by a raw ``media_url`` pasted around.

m-24820142: an approved piece whose video is still its 480p Seedance draft (its 1080p
final being made, failed or never ordered — ``draft_mode.draft_pending``) is not an
artifact yet either: the Planificador refuses to publish it (``MEDIA_DRAFT_PENDING``),
and every other consumer reads the same rule here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from uuid import UUID

from qualify_creative.enums import BriefIntent, DraftStatus
from qualify_creative.schemas import CopyPayload
from qualify_shared.db.session import tenant_session
from sqlalchemy import select
from sqlalchemy.orm import Session

from qualify_api.creative import models as orm
from qualify_api.creative.draft_mode import draft_pending

_ARTIFACT_STATUSES: tuple[str, ...] = tuple(s.value for s in DraftStatus if s.is_artifact)


@dataclass(frozen=True)
class ApprovedCreative:
    """The module's output artifact: everything a downstream consumer needs to publish
    organically or route to Ads, with no second call into the creative engine.

    ``provenance`` carries the versions that produced the piece (pipeline, template,
    voice profile, copy model + revision) — the hard architectural rule that every
    model-written artifact names what wrote it.
    """

    draft_id: UUID
    brand_id: UUID
    copy: CopyPayload
    intent: BriefIntent
    voice_profile_version: int | None
    approved_at: datetime | None
    requires_ai_disclosure: bool
    image_media_url: str | None
    image_object_key: str | None
    image_width: int | None
    image_height: int | None
    aspect_ratio: str | None
    provenance: Mapping[str, object]


def _artifact_from_rows(
    session: Session, draft: orm.ContentDraft
) -> tuple[ApprovedCreative, str] | None:
    """Build the artifact (plus the brief's intent value, for filtering) or None when
    the draft has no readable selected variant — an approved draft without one is
    unrepresentable through the FSM guard, so None here only means RLS or corruption,
    and handing out half an artifact would be worse than handing out none. None as well
    while any of its videos is still a 480p draft (`draft_pending`): its media is not
    the piece that will be published."""
    if draft.selected_variant_id is None:
        return None
    variant = session.get(orm.CopyVariant, draft.selected_variant_id)
    if variant is None or variant.draft_id != draft.id:
        return None
    brief = session.get(orm.ContentBrief, draft.brief_id)
    if brief is None:
        return None
    from qualify_api.creative.versions import visible_version

    images = session.scalars(
        select(orm.ImageAsset)
        .where(orm.ImageAsset.draft_id == draft.id, visible_version(orm.ImageAsset))
        .order_by(orm.ImageAsset.created_at)
    ).all()
    if any(draft_pending(asset.params) for asset in images):
        return None
    image = images[0] if images else None
    copy = CopyPayload.model_validate(variant.edited_copy or variant.copy)
    # m-24820837: a replica names the reel it was made from — read from the brief's own
    # JSONB, so it outlives the discovery card and the original reel. None otherwise.
    source_reel = (brief.media or {}).get("source_reel")
    provenance: Mapping[str, object] = MappingProxyType(
        {
            "pipeline_version": draft.pipeline_version,
            "template_id": draft.template_id,
            "template_version": draft.template_version,
            "voice_profile_version": draft.voice_profile_version,
            "copy_model_id": variant.model_id,
            "copy_model_revision": variant.model_revision,
            "copy_was_edited": variant.edited_copy is not None,
            "source_reel": source_reel,
        }
    )
    artifact = ApprovedCreative(
        draft_id=draft.id,
        brand_id=draft.brand_id,
        copy=copy,
        intent=BriefIntent(brief.intent),
        voice_profile_version=draft.voice_profile_version,
        approved_at=draft.approved_at,
        requires_ai_disclosure=draft.requires_ai_disclosure,
        image_media_url=image.media_url if image is not None else None,
        image_object_key=image.object_key if image is not None else None,
        image_width=image.width if image is not None else None,
        image_height=image.height if image is not None else None,
        aspect_ratio=image.aspect_ratio if image is not None else None,
        provenance=provenance,
    )
    return artifact, brief.intent


def approved_creative(*, tenant_id: UUID, draft_id: UUID) -> ApprovedCreative | None:
    """None when the draft does not exist, is not visible to this tenant (RLS makes the
    two indistinguishable, on purpose), or is not yet an artifact (``is_artifact``, or
    a video still at its 480p draft)."""
    with tenant_session(tenant_id) as session:
        draft = session.get(orm.ContentDraft, draft_id)
        if draft is None or not DraftStatus(draft.status).is_artifact:
            return None
        built = _artifact_from_rows(session, draft)
        return None if built is None else built[0]


def list_approved(
    *,
    tenant_id: UUID,
    brand_id: UUID,
    since: datetime | None = None,
    intent: BriefIntent | None = None,
) -> tuple[ApprovedCreative, ...]:
    """Every artifact of the brand, newest approval first. ``since`` filters on
    ``approved_at``; ``intent`` filters on the brief's declared intent (an Ads consumer
    asks for ``ADS``/``BOTH`` pieces by calling twice — the enum stays honest). A piece
    whose video is still a 480p draft is left out until its final is in place."""
    with tenant_session(tenant_id) as session:
        stmt = (
            select(orm.ContentDraft)
            .where(
                orm.ContentDraft.brand_id == brand_id,
                orm.ContentDraft.status.in_(_ARTIFACT_STATUSES),
            )
            .order_by(orm.ContentDraft.approved_at.desc())
        )
        if since is not None:
            stmt = stmt.where(orm.ContentDraft.approved_at >= since)
        artifacts: list[ApprovedCreative] = []
        for draft in session.scalars(stmt):
            built = _artifact_from_rows(session, draft)
            if built is None:
                continue
            artifact, intent_value = built
            if intent is not None and intent_value != intent.value:
                continue
            artifacts.append(artifact)
        return tuple(artifacts)

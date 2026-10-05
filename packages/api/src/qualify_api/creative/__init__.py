"""Creative module (MC-01): the Brand Content Engine's persistence shapes and the
content-draft lifecycle FSM.

The ORM models mirror the creative migration (DDL/RLS/grants are Alembic's job); the FSM
is pure logic — every draft status mutation goes through `apply_transition`, nowhere
else. Status/failure-reason string values are the contract with
`qualify_creative.enums` (see `fsm.py`)."""

from qualify_api.creative.fsm import (
    APPROVED,
    DRAFT_STATUSES,
    DRAFTING,
    FAILED,
    GENERATED,
    PUBLISHED,
    REAP_FAILURE_REASON,
    REJECTED,
    STAGED,
    DraftTrigger,
    GuardUnsatisfied,
    InvalidTransition,
    apply_transition,
)
from qualify_api.creative.models import (
    BrandKit,
    BrandVoiceProfile,
    ContentBrief,
    ContentDraft,
    CopyVariant,
    CreativeEngineConfig,
    CreativeUsageEvent,
    ImageAsset,
    TemplateRun,
)

__all__ = [
    "APPROVED",
    "DRAFT_STATUSES",
    "DRAFTING",
    "FAILED",
    "GENERATED",
    "PUBLISHED",
    "REAP_FAILURE_REASON",
    "REJECTED",
    "STAGED",
    "BrandKit",
    "BrandVoiceProfile",
    "ContentBrief",
    "ContentDraft",
    "CopyVariant",
    "CreativeEngineConfig",
    "CreativeUsageEvent",
    "DraftTrigger",
    "GuardUnsatisfied",
    "ImageAsset",
    "InvalidTransition",
    "TemplateRun",
    "apply_transition",
]

from qualify_api.creative.brand_service import BrandKitService
from qualify_api.creative.composition import production_content_service
from qualify_api.creative.dispatch import InlineDispatcher, TaskDispatcher, reap_stale_drafts
from qualify_api.creative.read import ApprovedCreative, approved_creative, list_approved
from qualify_api.creative.readiness import BrandReadiness, compute_readiness
from qualify_api.creative.service import BrandNotReady, ContentService, RouteBlockedByPolicy
from qualify_api.creative.voice_service import VoiceProfileService

__all__ = [
    "ApprovedCreative",
    "BrandKitService",
    "BrandNotReady",
    "BrandReadiness",
    "ContentService",
    "InlineDispatcher",
    "RouteBlockedByPolicy",
    "TaskDispatcher",
    "VoiceProfileService",
    "approved_creative",
    "compute_readiness",
    "list_approved",
    "production_content_service",
    "reap_stale_drafts",
]

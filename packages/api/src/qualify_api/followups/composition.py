"""Production wiring of Fase C (m-24789646): the followup service and the
«Consultas desde comentarios» workspace over Postgres, the conversations registry every
process shares, and this deployment's capability switches (read once, here — nothing
below the composition reads the environment). The Claude client of the drafts is built on
the first draft, so composing this without `QUALIFY_ANTHROPIC_API_KEY` is fine."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID

from qualify_api.conversations.composition import (
    grounding_for,
    production_outbox,
    production_registry,
    production_repository,
)
from qualify_api.conversations.drafts import PostgresDraftRepository
from qualify_api.conversations.suggest import ClaudeDraftGenerator
from qualify_api.followups.capabilities import Capabilities
from qualify_api.followups.origins import PostgresCommercialIntentReader, PostgresOriginReader
from qualify_api.followups.repository import PostgresFollowupRepository
from qualify_api.followups.service import FollowupService
from qualify_api.followups.workspace import FollowupWorkspace
from qualify_api.intent import (
    CURRENT_INTENT_VERSION,
    IntentClass,
    IntentSignal,
    class_reliability,
    current_signals,
)


def production_capabilities() -> Capabilities:
    return Capabilities.from_env()


def production_followup_service() -> FollowupService:
    return FollowupService(
        followups=PostgresFollowupRepository(),
        origins=PostgresOriginReader(),
        conversations=production_repository(),
        outbox=production_outbox(),
        registry=production_registry(),
        capabilities=production_capabilities(),
    )


def _signals(tenant_id: UUID, message_ids: Sequence[UUID]) -> Mapping[UUID, IntentSignal]:
    return current_signals(tenant_id=tenant_id, message_ids=message_ids)


def _reliability() -> Mapping[IntentClass, bool]:
    return class_reliability(CURRENT_INTENT_VERSION.detector_version)


def production_workspace() -> FollowupWorkspace:
    return FollowupWorkspace(
        service=production_followup_service(),
        followups=PostgresFollowupRepository(),
        origins=PostgresOriginReader(),
        commercial=PostgresCommercialIntentReader(),
        drafts=PostgresDraftRepository(),
        generator=ClaudeDraftGenerator(),
        grounding=grounding_for,
        signals=_signals,
        reliability=_reliability,
        intent_version=CURRENT_INTENT_VERSION,
    )

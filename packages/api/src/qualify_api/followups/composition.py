"""Production wiring of Fase C (m-24789646): the followup service over Postgres, the
conversations registry every process shares, and this deployment's capability switches
(read once, here — nothing below the composition reads the environment)."""

from __future__ import annotations

from qualify_api.conversations.composition import (
    production_outbox,
    production_registry,
    production_repository,
)
from qualify_api.followups.capabilities import Capabilities
from qualify_api.followups.origins import PostgresOriginReader
from qualify_api.followups.repository import PostgresFollowupRepository
from qualify_api.followups.service import FollowupService


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

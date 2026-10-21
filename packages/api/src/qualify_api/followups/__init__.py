"""Interacciones · Fase C (m-24789646): a commercial query found in a public interaction —
a comment, or a DM that replied to a story — continued in private in Conversaciones.

This package holds the link the rest of Fase C hangs on (`interaction_followups`,
migration 0071: interaction → intent → DM thread → approved send → public notice) and the
per-origin capabilities that keep every unverified Meta operation switched off (B6).
Sending is NOT here: the one path to a send stays `conversations.outbox` with a
`HumanApproval` (ADR 21c)."""

from qualify_api.followups.capabilities import (
    REGISTRY,
    STATE_LABELS,
    Availability,
    Capabilities,
    Capability,
    CapabilitySpec,
    CapabilityState,
)
from qualify_api.followups.repository import (
    Followup,
    FollowupOpening,
    FollowupRepository,
    FollowupStatus,
    FollowupTrigger,
    InvalidFollowupTransition,
    MemoryFollowupRepository,
    NoticeStatus,
    OriginKind,
    PostgresFollowupRepository,
    SendRoute,
    UnknownFollowup,
    approve_followup,
    discard_followup,
    new_followup,
)

__all__ = [
    "REGISTRY",
    "STATE_LABELS",
    "Availability",
    "Capabilities",
    "Capability",
    "CapabilitySpec",
    "CapabilityState",
    "Followup",
    "FollowupOpening",
    "FollowupRepository",
    "FollowupStatus",
    "FollowupTrigger",
    "InvalidFollowupTransition",
    "MemoryFollowupRepository",
    "NoticeStatus",
    "OriginKind",
    "PostgresFollowupRepository",
    "SendRoute",
    "UnknownFollowup",
    "approve_followup",
    "discard_followup",
    "new_followup",
]

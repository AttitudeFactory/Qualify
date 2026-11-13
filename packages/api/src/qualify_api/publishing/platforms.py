"""Which connected-account platforms Qualify can publish to — the ONE source of truth.

Shared by the direct publish path («Publicar», `publishing.service.PublishService`) and the
Planificador (`planner.publishable.SCHEDULABLE_PLATFORMS` is an alias of
`PUBLISHABLE_PLATFORMS`, not a copy). Kept in a leaf module (stdlib imports only) so
both `publishing` and `planner` can depend on it without a cycle.

Only Instagram today (founder, 2026-11-12): Facebook has no publisher, WhatsApp is a
messaging channel (its `external_account_id` is a phone-number id, not an IG user id), and
TikTok scheduled publishing is blocked by the platform (ADR 23c — TikTok goes to the
owner's drafts through `publishing.tiktok_drafts`, never through this path).
"""

from __future__ import annotations

from uuid import UUID

PLATFORM_INSTAGRAM = "instagram"
PUBLISHABLE_PLATFORMS: frozenset[str] = frozenset({PLATFORM_INSTAGRAM})


class UnsupportedPlatform(Exception):
    """The connection exists but its platform cannot take a publication from Qualify.

    Raised BEFORE anything is staged to R2, any `publish_attempts` row is written or any
    Graph call is made. Same semantics as the Planificador's `IncompatibleConnection`.
    `platform` is the connection's raw value (`"whatsapp"`, `"facebook"`, …) so the UI can
    word the refusal; this module carries no client-facing copy."""

    def __init__(self, *, connection_id: UUID, platform: str) -> None:
        super().__init__(f"{connection_id} is {platform!r}; publishable: instagram only")
        self.connection_id = connection_id
        self.platform = platform


def require_publishable_platform(*, connection_id: UUID, platform: str) -> None:
    """Raise `UnsupportedPlatform` unless `platform` is in `PUBLISHABLE_PLATFORMS`."""
    if platform not in PUBLISHABLE_PLATFORMS:
        raise UnsupportedPlatform(connection_id=connection_id, platform=platform)

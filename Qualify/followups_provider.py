"""The transport of «Consultas desde comentarios» (m-24789646, PR 3): everything the
screen asks of `qualify_api.followups.workspace.FollowupWorkspace`, scoped to the
session's tenant, returning VMs. In process (`tenant_session` underneath), synchronous —
the state calls it through `asyncio.to_thread`. The production workspace is built on the
first call, so importing this never needs Postgres or the Claude key.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from qualify_api.followups.workspace import FollowupWorkspace, OpenSummary

from .conversations_provider import gateway as conversations_gateway
from .followups_vm import FollowupCardVM, build_card_vm


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


class FollowupsGateway:
    def __init__(
        self,
        workspace: FollowupWorkspace | None = None,
        *,
        timezone: Callable[[UUID], str] | None = None,
        acting_user: Callable[[UUID, str], UUID | None] | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._workspace = workspace
        self._timezone = timezone
        self._acting_user = acting_user
        self._clock = clock

    @property
    def workspace(self) -> FollowupWorkspace:
        if self._workspace is None:
            from qualify_api.followups.composition import production_workspace  # noqa: PLC0415

            self._workspace = production_workspace()
        return self._workspace

    def timezone(self, tenant_id: UUID) -> str:
        if self._timezone is not None:
            return self._timezone(tenant_id)
        return conversations_gateway().timezone(tenant_id)

    def acting_user(self, tenant_id: UUID, email: str) -> UUID | None:
        if self._acting_user is not None:
            return self._acting_user(tenant_id, email)
        return conversations_gateway().acting_user(tenant_id, email)

    def cards(self, tenant_id: UUID, zone_name: str) -> list[FollowupCardVM]:
        now, zone = self._clock(), _zone(zone_name)
        return [
            build_card_vm(card, now=now, zone=zone)
            for card in self.workspace.list_open(tenant_id=tenant_id)
        ]

    def open_from_intents(self, tenant_id: UUID, connection_id: UUID) -> OpenSummary:
        return self.workspace.open_from_intents(tenant_id=tenant_id, connection_id=connection_id)

    def open_manual(self, tenant_id: UUID, message_id: UUID) -> str:
        opening = self.workspace.open_manual(tenant_id=tenant_id, origin_message_id=message_id)
        return str(opening.followup.id)

    def suggest(self, tenant_id: UUID, followup_id: UUID) -> None:
        self.workspace.suggest(tenant_id=tenant_id, followup_id=followup_id)

    def regenerate(self, tenant_id: UUID, followup_id: UUID, user_id: UUID) -> None:
        self.workspace.regenerate(tenant_id=tenant_id, followup_id=followup_id, user_id=user_id)

    def discard(self, tenant_id: UUID, followup_id: UUID, user_id: UUID) -> None:
        self.workspace.discard(tenant_id=tenant_id, followup_id=followup_id, user_id=user_id)

    def approve(
        self,
        tenant_id: UUID,
        followup_id: UUID,
        *,
        text: str,
        user_id: UUID,
        draft_id: UUID | None,
        notice_text: str | None = None,
    ) -> str:
        """Queue the text (and the public notice approved with it, if any); returns the
        route it goes out on (`dm` / `private_reply`)."""
        approved = self.workspace.approve(
            tenant_id=tenant_id,
            followup_id=followup_id,
            text=text,
            user_id=user_id,
            draft_id=draft_id,
            notice_text=notice_text,
        )
        return approved.send_route.value if approved.send_route else ""


_GATEWAY: FollowupsGateway | None = None


def gateway() -> FollowupsGateway:
    global _GATEWAY
    if _GATEWAY is None:
        _GATEWAY = FollowupsGateway()
    return _GATEWAY

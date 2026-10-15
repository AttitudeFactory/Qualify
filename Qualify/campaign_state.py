"""State of the POST's «Campaña» field on `/drafts/[draft_id]` (QUA-143).

The one place a campaign is created and assigned: pick one of the POST's brand, create a
new one by name right there (no modal, no management screen), or leave the POST
independent. Kept apart from `CreativeState` on purpose — the campaign is not part of the
review/edit flow and never touches the POST's revision, status or approval."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

import reflex as rx
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
from .campaign_provider import (
    NO_CAMPAIGN,
    CampaignFieldVM,
    CampaignOptionVM,
    InvalidCampaignColor,
    InvalidCampaignName,
    UnknownCampaign,
    UnknownPost,
    assign_campaign,
    campaign_field,
    create_campaign_for_post,
    error_message,
    recolor_post_campaign,
    suggested_color,
)
from .creative_provider import acting_user_id
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_NO_SESSION = "No hay una sesión activa. Vuelve a iniciar sesión."
_SAVE_FAILED = "No se pudo guardar la campaña. Inténtalo de nuevo."


class CampaignState(rx.State):
    options: list[CampaignOptionVM] = []
    current_id: str = NO_CAMPAIGN
    current_name: str = ""
    current_color: str = ""
    creating: bool = False  # the «Nueva campaña» inline input is open
    new_name: str = ""
    new_color: str = ""  # the swatch chosen for the new campaign (preselected: suggested)
    busy: bool = False
    loading: bool = False
    error: str = ""

    def _post_id(self) -> UUID | None:
        # the dynamic route arg, as `CreativeState._route_draft_id` reads it — not
        # `router.page.params`, deprecated since Reflex 0.8.1 and gone in 1.0
        raw = getattr(self, "draft_id", "")
        try:
            return UUID(str(raw))
        except (ValueError, AttributeError):
            return None

    def _apply(self, vm: CampaignFieldVM) -> None:
        self.options = list(vm.options)
        self.current_id = vm.current_id
        self.current_name = vm.current_name
        self.current_color = vm.current_color

    async def _ids(self) -> tuple[UUID, UUID] | None:
        """(tenant, POST) for this session and route, or None with the reason stored."""
        async with self:
            auth = await self.get_state(AuthState)
            # A logged-in page: the session's tenant, never the Brand Kit's draft one.
            raw_tenant = auth.session_tenant_id
            post_id = self._post_id()
        tenant_id = tenant_uuid(raw_tenant) if raw_tenant else None
        if tenant_id is None or post_id is None:
            async with self:
                self.error = _NO_SESSION if tenant_id is None else error_message(UnknownPost())
            return None
        return tenant_id, post_id

    @rx.event(background=True)
    async def load(self) -> None:
        async with self:
            self.loading = True
            self.error = ""
            self.creating = False
            self.new_name = ""
            self._apply(CampaignFieldVM())
        ids = await self._ids()
        if ids is None:
            async with self:
                self.loading = False
            return
        tenant_id, post_id = ids
        try:
            vm = await asyncio.to_thread(campaign_field, tenant_id, post_id)
        except UnknownPost as exc:
            async with self:
                self.loading = False
                self.error = error_message(exc)
            return
        except SQLAlchemyError as exc:
            logger.error("campaign field load failed: %s", type(exc).__name__)
            async with self:
                self.loading = False
                self.error = _SAVE_FAILED
            return
        async with self:
            self.loading = False
            self._apply(vm)

    @rx.event(background=True)
    async def choose(self, value: str) -> None:
        """Assign the chosen campaign, or `NO_CAMPAIGN` to make the POST independent."""
        async with self:
            if self.busy or value == self.current_id:
                return
            self.busy = True
            self.error = ""
        ids = await self._ids()
        if ids is None:
            async with self:
                self.busy = False
            return
        tenant_id, post_id = ids
        try:
            vm = await asyncio.to_thread(assign_campaign, tenant_id, post_id, value)
        except (UnknownPost, UnknownCampaign, ValueError) as exc:
            async with self:
                self.busy = False
                self.error = error_message(exc)
            return
        except SQLAlchemyError as exc:
            logger.error("campaign assign failed: %s", type(exc).__name__)
            async with self:
                self.busy = False
                self.error = _SAVE_FAILED
            return
        async with self:
            self.busy = False
            self._apply(vm)

    @rx.event
    def start_create(self) -> None:
        self.creating = True
        self.new_name = ""
        self.new_color = suggested_color(self.options)
        self.error = ""

    @rx.event
    def set_new_color(self, color: str) -> None:
        self.new_color = color

    @rx.event
    def cancel_create(self) -> None:
        self.creating = False
        self.new_name = ""
        self.error = ""

    @rx.event
    def set_new_name(self, value: str) -> None:
        self.new_name = value

    @rx.event
    def create_on_enter(self, key: str):
        if key == "Enter":
            return CampaignState.create
        if key == "Escape":
            return CampaignState.cancel_create
        return None

    @rx.event(background=True)
    async def create(self) -> None:
        """Create the campaign in the POST's brand (or pick the one with that name) and
        put the POST in it."""
        async with self:
            if self.busy:
                return
            self.busy = True
            self.error = ""
            name, color = self.new_name, self.new_color
        ids = await self._ids()
        if ids is None:
            async with self:
                self.busy = False
            return
        tenant_id, post_id = ids
        try:
            user_id = await asyncio.to_thread(acting_user_id, tenant_id)
            vm = await asyncio.to_thread(
                create_campaign_for_post, tenant_id, post_id, name, user_id, color
            )
        except (InvalidCampaignName, InvalidCampaignColor, UnknownPost, UnknownCampaign) as exc:
            async with self:
                self.busy = False
                self.error = error_message(exc)
            return
        except SQLAlchemyError as exc:
            logger.error("campaign create failed: %s", type(exc).__name__)
            async with self:
                self.busy = False
                self.error = _SAVE_FAILED
            return
        async with self:
            self.busy = False
            self.creating = False
            self.new_name = ""
            self._apply(vm)

    @rx.event(background=True)
    async def recolor(self, color: str) -> None:
        """Recolour the POST's campaign — every POST and event of it shows the new colour;
        none of them is edited (`set_campaign_color` writes `campaigns.color` alone)."""
        async with self:
            if self.busy or self.current_name == "" or color == self.current_color:
                return
            self.busy = True
            self.error = ""
        ids = await self._ids()
        if ids is None:
            async with self:
                self.busy = False
            return
        tenant_id, post_id = ids
        try:
            vm = await asyncio.to_thread(recolor_post_campaign, tenant_id, post_id, color)
        except (InvalidCampaignColor, UnknownPost, UnknownCampaign) as exc:
            async with self:
                self.busy = False
                self.error = error_message(exc)
            return
        except SQLAlchemyError as exc:
            logger.error("campaign recolor failed: %s", type(exc).__name__)
            async with self:
                self.busy = False
                self.error = _SAVE_FAILED
            return
        async with self:
            self.busy = False
            self._apply(vm)

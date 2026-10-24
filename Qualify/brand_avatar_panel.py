"""«Tu avatar animado» on the Brand Kit editor — SCAFFOLD (§ request 2026-10-19; design:
docs/brand-kit-avatar-animado.md; service: `qualify_api.creative.brand_avatar`).

The avatar is drawn in the background when the Brand Kit is finished
(`brand_finish.save_brand_kit` → `start_brand_avatar`) and shown here. While the feature
is off (`QUALIFY_BRAND_AVATAR` unset, or no BytePlus ModelArk key) the card is a quiet
placeholder and «Regenerar» is hidden: nothing here calls BytePlus."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any
from uuid import UUID

import reflex as rx
from qualify_api.creative.brand_avatar import (
    AvatarStatus,
    BrandAvatarFailed,
    BrandAvatarUnavailable,
    avatar_enabled,
    generate_brand_avatar,
    load_brand_avatar,
    maybe_generate_after_kit,
)
from sqlalchemy.exc import SQLAlchemyError

from .r2_media import issue_view_path
from .ui import callout, card, media_thumb, progress_panel
from .ui import tokens as T

logger = logging.getLogger(__name__)

PLACEHOLDER_OFF = (
    "Todavía no está disponible. Será una mascota para tu marca, dibujada a partir de "
    "tu logo, tus colores y tu tono."
)
PLACEHOLDER_EMPTY = "Aún no tienes avatar. Pulsa «Regenerar» para crearlo."
FAILED_TEXT = "No pudimos crear tu avatar. Inténtalo de nuevo más tarde."

#: Fire-and-forget generations kept alive until done (the loop holds only weak refs).
_BACKGROUND: set[asyncio.Task[Any]] = set()


def start_brand_avatar(tenant_id: UUID, brand_id: UUID) -> bool:
    """The Brand Kit completion hook: when enabled, draw the avatar in a background
    thread — the wizard never waits for it; the editor reads the stored result. A no-op
    (False) while the feature is off. Call from inside the running event loop."""
    if not avatar_enabled():
        return False
    work: Coroutine[Any, Any, Any] = asyncio.to_thread(
        maybe_generate_after_kit, tenant_id, brand_id
    )
    task = asyncio.get_running_loop().create_task(work)
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)
    return True


class BrandAvatarState(rx.State):
    """What the card shows; the record itself lives in `brand_kit_details`."""

    #: The feature is on (switch + key): «Regenerar» is offered.
    enabled: bool = False
    #: "" (none yet) | pending | ready | failed — `AvatarStatus`.
    status: str = ""
    #: A short-lived `/r2media/<token>` for the ready image ("" otherwise).
    image_url: str = ""
    error: str = ""
    working: bool = False

    @rx.event(background=True)
    async def load(self) -> None:
        """Read the stored avatar (on mount). Reading is harmless with the feature off:
        an avatar drawn while it was on still shows."""
        from .brand_finish import session_ids

        enabled = avatar_enabled()
        ids = await session_ids(self)
        status, url, error = "", "", ""
        if ids is not None:
            status, url, error = await asyncio.to_thread(_read, ids[0], ids[1])
        async with self:
            self.enabled = enabled
            self.status = status
            self.image_url = url
            self.error = error

    @rx.event(background=True)
    async def regenerate(self) -> None:
        """Draw it again (a fresh R2 key; the old record is replaced). Only while on."""
        from .brand_finish import session_ids

        async with self:
            if self.working or not avatar_enabled():
                return
            self.working = True
            self.status = AvatarStatus.PENDING.value
            self.error = ""
        ids = await session_ids(self)
        try:
            if ids is not None:
                await asyncio.to_thread(generate_brand_avatar, ids[0], ids[1])
        except (BrandAvatarUnavailable, BrandAvatarFailed) as exc:
            logger.info("brand avatar not regenerated: %s", exc)
        status, url, error = ("", "", "")
        if ids is not None:
            status, url, error = await asyncio.to_thread(_read, ids[0], ids[1])
        async with self:
            self.working = False
            self.status = status
            self.image_url = url
            self.error = error


def _read(tenant_id: UUID, brand_id: UUID) -> tuple[str, str, str]:
    """(status, view url, error) of the stored avatar — off the event loop."""
    try:
        avatar = load_brand_avatar(tenant_id, brand_id)
    except SQLAlchemyError:
        return "", "", ""
    if avatar is None:
        return "", "", ""
    url = ""
    if avatar.status is AvatarStatus.READY and avatar.object_key:
        try:
            url = issue_view_path(
                tenant_id, avatar.object_key, "image", avatar.content_type or None
            )
        except Exception as exc:  # noqa: BLE001 — Redis down: the card says so quietly
            logger.warning("brand avatar view not issued: %s", type(exc).__name__)
    error = (avatar.error or FAILED_TEXT) if avatar.status is AvatarStatus.FAILED else ""
    return avatar.status.value, url, error


# --------------------------------------------------------------------------------------
# The card


def _faint(text: str) -> rx.Component:
    return rx.text(text, size="2", color=T.TEXT_FAINT)


def _body() -> rx.Component:
    return rx.match(
        BrandAvatarState.status,
        (
            AvatarStatus.READY.value,
            media_thumb(
                BrandAvatarState.image_url,
                size="10rem",
                icon="smile",
                alt="El avatar animado de tu marca",
                fit="contain",
            ),
        ),
        (
            AvatarStatus.PENDING.value,
            # Brand Kit waits are a progress bar, never a spinner (house rule)
            progress_panel(
                "Creando tu avatar",
                "Lo dibujamos a partir de tu logo, tus colores y tu tono.",
                creep_seconds=40,
            ),
        ),
        (AvatarStatus.FAILED.value, callout(BrandAvatarState.error, "error")),
        rx.cond(BrandAvatarState.enabled, _faint(PLACEHOLDER_EMPTY), _faint(PLACEHOLDER_OFF)),
    )


def brand_avatar_card() -> rx.Component:
    """«Tu avatar animado»: the avatar when there is one, otherwise a quiet placeholder;
    «Regenerar» only while the feature is on."""
    return card(
        rx.vstack(
            rx.hstack(
                rx.center(
                    rx.icon("smile", size=18),
                    class_name="q-brand-glyph",
                    width="2.25rem",
                    height="2.25rem",
                ),
                rx.vstack(
                    rx.text("Tu avatar animado", size="3", weight="bold"),
                    rx.text(
                        "La mascota de tu marca, creada a partir de tu logo, tus colores "
                        "y tu tono.",
                        size="2",
                        color=T.TEXT_MUTED,
                    ),
                    spacing="1",
                    align_items="start",
                    min_width="0",
                    flex="1",
                ),
                rx.cond(
                    BrandAvatarState.enabled,
                    rx.button(
                        rx.icon("refresh-cw", size=T.ICON_SM),
                        "Regenerar",
                        variant="soft",
                        size="2",
                        on_click=BrandAvatarState.regenerate,
                        loading=BrandAvatarState.working,
                        disabled=BrandAvatarState.working,
                        flex_shrink="0",
                    ),
                ),
                spacing="3",
                align="center",
                width="100%",
            ),
            _body(),
            spacing="3",
            width="100%",
            align_items="stretch",
        ),
        id="seccion-avatar",
        on_mount=BrandAvatarState.load,
        scroll_margin_top="1rem",
    )

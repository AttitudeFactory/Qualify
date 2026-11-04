"""«Ideas para tus reels» in /create («Descubrir reels» in the code, § request 2026-10-15):
the reels that work best among the accounts the brand follows — only the ones of its own
product or category — as cards the owner can watch, read and replicate.

ADR 42 R7 (m-24854854): opening the view ONLY READS WHAT IS STORED. The weekly run (R8)
and the owner's search (R9) are what pay; the view brings their latest `ok` run from
Postgres (`reels_discovery.load_ideas`) and shows it at once, dated in the business's
zone (`reels_ideas_vm`). Nothing here reads ScrapeCreators or asks the model: the old
on-mount read, «Actualizar», the 90-day tab and the on-demand «Ver transcripción» —
all four paid inline — are gone; a card shows the transcript the run stored.

Two writes ride on opening, both through `reels_discovery` (decisions of 2026-11-04):
the brand's «last opened» mark (the worker's 14-day rule) and, for a brand that never had
a run, its first run queued (option A, pending the founder) — the view then says it is
being prepared and re-reads the view, free, until that run ends.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import reflex as rx
from qualify_api.referentes import reels_ai
from qualify_api.referentes.reel_reference import ReelReferenceUnavailable

from . import reels_discovery, reels_ideas_vm
from .auth_state import AuthState
from .creative_provider import default_brand_id
from .creative_state import CreativeState
from .r2_media import BACKEND_BASE
from .reel_replication import import_reference
from .reels_ideas_vm import (
    SCREEN_CHECK_FAILED,
    SCREEN_IDEAS,
    SCREEN_NO_ACCOUNTS,
    SCREEN_NO_BRIEF,
    SCREEN_NO_IDEAS,
    SCREEN_UNAVAILABLE,
)
from .tenant import tenant_uuid
from .ui import callout, card, empty_state, loading_spinner, section, skeleton_card
from .ui import tokens as T
from .ui.steps import go_to_step

#: Always visible on phones too; opening the form never generates a paid piece.
REPLICATE_HELP = (
    "Usa los primeros 5 s del reel como base, conservando planos y acciones con tu "
    "producto y marca, sin su audio. Podrás revisarlo antes de generar."
)

#: Where every empty state's button leads: the accounts the brand follows and what it
#: sells live in Tu marca.
BRAND_KIT_HREF = "/brand/kit"

#: The «preparando» screen re-reads the view (a database read, free) this often, for at
#: most this long, and never once the owner left the view (decision 2(a)).
POLL_SECONDS = 12.0
POLL_LIMIT_SECONDS = 10 * 60

logger = logging.getLogger(__name__)


class DiscoverReelsState(rx.State):
    """What «Ideas para tus reels» shows: one `reels_ideas_vm.SCREEN_*` and its words,
    and the stored ideas as cards (`reels.reel_card`). The cards stay on the backend
    (`_cards`) — only a server-held card can open a replica — and the browser receives
    `reels`, the ones the check kept for the product or its category."""

    replicating: str = ""
    replicate_error: str = ""
    _cards_tenant_id: str = ""

    #: Which `reels_ideas_vm.SCREEN_*` is on screen; "" until the first read lands.
    screen: str = ""
    #: The header over the ideas, or the empty state's title, body and button.
    title: str = ""
    body: str = ""
    action: str = ""
    #: A notice above stored ideas that are still true (a newer run failed its check).
    notice_title: str = ""
    notice_body: str = ""
    #: A run is in flight for a brand with nothing stored: the «preparando» screen shows
    #: work in progress (a spinner) and re-reads the view until the run ends.
    waiting: bool = False
    #: Why the stored ideas could not be read (`reels_ideas_vm.LOAD_ERROR`), "" none.
    load_error: str = ""
    #: The reel playing inside its own card (its `key`), "" when none — one at a time,
    #: so starting another stops the previous (its iframe unmounts).
    playing_key: str = ""

    #: The stored ideas, best first (backend only).
    _cards: list[dict[str, str]] = []
    #: Which read is the live one: a new mount, or leaving the view, supersedes the
    #: others — a stale read never paints, and the «preparando» re-reads stop.
    _load_id: int = 0

    @rx.var
    def reels(self) -> list[dict[str, str]]:
        """The ideas the check kept for the brand's product or category — never another
        product's reel, even from a card stored under another rule."""
        return [c for c in self._cards if c.get("affinity") in reels_ai.FITS]

    def _claim_cards(self, tenant_id: str) -> None:
        if self._cards_tenant_id != tenant_id:
            self._cards = []
            self.playing_key = ""
            self.failed_videos = []
            self.failed_covers = []
            self.expanded = []
            self._cards_tenant_id = tenant_id

    def _show(self, shown: reels_ideas_vm.IdeasScreen) -> None:
        self.screen = shown.screen
        self.title = shown.title
        self.body = shown.body
        self.action = shown.action
        self.notice_title = shown.notice_title
        self.notice_body = shown.notice_body
        self.waiting = shown.waiting
        self._cards = list(shown.cards)
        keys = {c.get("key", "") for c in self._cards}
        if self.playing_key not in keys:
            self.playing_key = ""
        self.expanded = [k for k in self.expanded if k in keys]

    @rx.event(background=True)
    async def load(self) -> None:
        """Bring what is stored (ADR 42 R7): Postgres only — opening never reads the
        vendor nor asks the model. Marks the brand as opened beside the read, without
        waiting for it; on the «preparando» screen, re-reads until the run ends."""
        async with self:
            self._load_id += 1
            load_id = self._load_id
            self.load_error = ""
            auth = await self.get_state(AuthState)
            # the logged-in tenant only: a pre-login Brand Kit draft never opens /create
            session_tenant_id = auth.session_tenant_id
        tenant_id = tenant_uuid(session_tenant_id) if session_tenant_id else None
        opened: asyncio.Task[None] | None = None
        try:
            brand_id = await asyncio.to_thread(default_brand_id, tenant_id) if tenant_id else None
            if tenant_id is None or brand_id is None:
                raise LookupError("no brand in this session")
            # the «last opened» mark (R8's 14-day rule) goes first, in its own thread —
            # the read never waits for it
            opened = asyncio.create_task(
                asyncio.to_thread(reels_discovery.mark_opened, tenant_id, brand_id)
            )
            shown = await asyncio.to_thread(reels_discovery.load_ideas, tenant_id, brand_id)
        except Exception as exc:  # noqa: BLE001 — the view says it, the log keeps why
            logger.warning("stored reel ideas unreadable: %s: %s", type(exc).__name__, exc)
            async with self:
                if self._load_id == load_id:
                    self.load_error = reels_ideas_vm.LOAD_ERROR
            await _settle(opened)
            return
        async with self:
            live = await _still_mine(self, load_id, tenant_id)
            if live:
                self._claim_cards(str(tenant_id))
                self._show(shown)
        await _settle(opened)
        if not live:
            return
        # decision 2(a): the first run is being prepared — re-read the view (free) until
        # it ends, for at most `POLL_LIMIT_SECONDS`, and never after the owner left
        deadline = time.monotonic() + POLL_LIMIT_SECONDS
        while shown.waiting and time.monotonic() < deadline:
            await asyncio.sleep(POLL_SECONDS)
            async with self:
                if not await _still_mine(self, load_id, tenant_id):
                    return
            try:
                shown = await asyncio.to_thread(
                    reels_discovery.load_ideas, tenant_id, brand_id, first_run=False
                )
            except Exception as exc:  # noqa: BLE001 — the screen stays; the next tick retries
                logger.warning("reel ideas re-read failed: %s: %s", type(exc).__name__, exc)
                continue
            async with self:
                if not await _still_mine(self, load_id, tenant_id):
                    return
                self._show(shown)

    @rx.event
    def leave(self) -> None:
        """The view left the page: a read still in flight never paints, and the
        «preparando» re-reads stop."""
        self._load_id += 1
        self.playing_key = ""

    @rx.event
    def play(self, key: str) -> None:
        """Play the reel `key` inside its card, in the network's own player."""
        self.playing_key = key

    @rx.event
    def stop(self) -> None:
        self.playing_key = ""

    #: Reels whose own MP4 would not play (its signed CDN URL died, ~24-33 h after the
    #: run read it): they play in the network's embed instead.
    failed_videos: list[str] = []

    @rx.event
    def video_failed(self, key: str) -> None:
        if key not in self.failed_videos:
            self.failed_videos = [*self.failed_videos, key]

    #: Reels whose cover would not load (a CDN picture expires before the idea does, until
    #: R12 keeps covers in R2): their card shows the placeholder instead.
    failed_covers: list[str] = []

    @rx.event
    def cover_failed(self, key: str) -> None:
        if key not in self.failed_covers:
            self.failed_covers = [*self.failed_covers, key]

    #: Cards whose «Detalles» is open (an accordion under the figures).
    expanded: list[str] = []

    @rx.event
    def toggle_details(self, key: str) -> None:
        if key in self.expanded:
            self.expanded = [k for k in self.expanded if k != key]
        else:
            self.expanded = [*self.expanded, key]

    def _card(self, key: str) -> dict[str, str] | None:
        return next((c for c in self._cards if c.get("key") == key), None)

    @rx.event(background=True)
    async def replicate(self, key: str) -> AsyncIterator[rx.event.EventSpec]:
        """Only a server-held card of this session can open a Seedance Clip."""
        async with self:
            if self.replicating:
                return
            self.replicate_error = ""
            auth = await self.get_state(AuthState)
            tenant_id = tenant_uuid(auth.session_tenant_id)
            creative = await self.get_state(CreativeState)
            card = self._card(key)
            if tenant_id is None or self._cards_tenant_id != str(tenant_id):
                self.replicate_error = "Vuelve a abrir los reels de tu marca para continuar."
                return
            if card is None or card.get("affinity") not in reels_ai.FITS:
                self.replicate_error = "Este reel ya no está en la selección. Elige otro."
                return
            if creative.gen_generating or creative.gen_mode != "discover":
                return
            product = (creative.selected_product_id, creative.product_source)
            card = dict(card)
            self.replicating = key
        try:
            imported = await asyncio.to_thread(import_reference, tenant_id, card)
        except Exception as exc:
            logger.warning("reel reference failed: %s", type(exc).__name__)
            async with self:
                self.replicating = ""
                self.replicate_error = (
                    str(exc)
                    if isinstance(exc, ReelReferenceUnavailable)
                    else "No pudimos preparar la referencia. Inténtalo de nuevo."
                )
            return
        async with self:
            self.replicating = ""
            auth = await self.get_state(AuthState)
            creative = await self.get_state(CreativeState)
            if (
                auth.session_tenant_id != str(tenant_id)
                or creative.gen_mode != "discover"
                or creative.gen_generating
                or product != (creative.selected_product_id, creative.product_source)
            ):
                return
            creative._apply_reel_reference(card, imported)
            self.playing_key = ""
        yield go_to_step("/create", 1)


async def _still_mine(state: Any, load_id: int, tenant_id: UUID) -> bool:
    """`state`'s read `load_id` is still the live one, for the tenant still logged in.
    Called inside `async with state`."""
    auth = await state.get_state(AuthState)
    return state._load_id == load_id and auth.session_tenant_id == str(tenant_id)


async def _settle(task: asyncio.Task[None] | None) -> None:
    """Wait for the «last opened» mark after the screen was painted; it never raises
    (`reels_discovery.mark_opened`), and nothing it does may reach the owner."""
    if task is not None:
        with contextlib.suppress(Exception):
            await task


# --------------------------------------------------------------------------------------
# view
# --------------------------------------------------------------------------------------


class _ReelVideo(rx.el.Video):
    """The reel's own MP4. Reflex's `video` element declares no `error` trigger; this
    one does, so a signed CDN URL that already died hands the card over to the
    network's embed (`DiscoverReelsState.video_failed`)."""

    on_error: rx.EventHandler[rx.event.no_args_event_spec]


class _ReelCover(rx.el.Img):
    """The reel's cover. Reflex's `img` declares no `error` trigger either; this one
    does, so a CDN picture that expired shows the card's placeholder instead of a broken
    image (`DiscoverReelsState.cover_failed`)."""

    on_error: rx.EventHandler[rx.event.no_args_event_spec]


def _detail(label: str, value: rx.Var[str]) -> rx.Component:
    return rx.fragment(
        rx.text(label, size="1", color=T.TEXT_MUTED),
        rx.text(value, size="1", weight="medium"),
    )


def _reel_media(reel: rx.Var[dict[str, str]]) -> rx.Component:
    """The card's picture, and its player (§ request 2026-10-15): the cover — or, when
    there is none or it would not load, the film placeholder — with the lift, the network
    and the length over it; a click plays JUST the video in its place — the reel's own
    MP4, streamed from the network's CDN, no page around it — or, when the reel has no
    MP4 or its signed URL already died, the network's own embed."""
    key = reel["key"]
    has_cover = (reel["cover"] != "") & ~DiscoverReelsState.failed_covers.contains(key)
    cover = rx.box(
        rx.cond(
            has_cover,
            _ReelCover.create(
                src=BACKEND_BASE + reel["cover"],
                alt="",
                loading="lazy",
                class_name="q-dr-cover-img",
                on_error=DiscoverReelsState.cover_failed(key),
            ),
            rx.center(rx.icon("film", size=28, color=T.TEXT_FAINT), class_name="q-dr-cover-img"),
        ),
        rx.cond(
            reel["lift"] != "",
            rx.box(
                rx.text(reel["lift"], size="1", weight="bold"),
                class_name=rx.cond(
                    reel["lift_tone"] == "ok", "q-dr-lift q-dr-lift--ok", "q-dr-lift"
                ),
            ),
        ),
        rx.box(
            rx.text(reel["network_label"], size="1", weight="medium"),
            class_name="q-cr-mark",
            top="0.45rem",
            right="0.45rem",
            padding="0.1rem 0.45rem",
        ),
        rx.cond(
            reel["seconds"] != "",
            rx.box(
                rx.text(reel["seconds"], size="1", weight="medium"),
                class_name="q-cr-mark",
                bottom="0.45rem",
                right="0.45rem",
                padding="0.1rem 0.45rem",
            ),
        ),
        rx.center(rx.icon("play", size=22), class_name="q-dr-play", aria_hidden="true"),
        class_name="q-dr-cover",
    )
    embed_only = DiscoverReelsState.failed_videos.contains(key) | (reel["video"] == "")
    player = rx.box(
        rx.cond(
            embed_only,
            rx.el.iframe(
                src=reel["embed"],
                title="Reproductor del reel",
                allow="autoplay; fullscreen; encrypted-media; picture-in-picture",
                allow_full_screen=True,
                class_name="q-dr-embed",
            ),
            _ReelVideo.create(
                src=reel["video"],
                auto_play=True,
                controls=True,
                loop=True,
                plays_inline=True,
                preload="auto",
                class_name="q-dr-video",
                on_error=DiscoverReelsState.video_failed(key),
            ),
        ),
        rx.icon_button(
            rx.icon("x", size=14),
            size="1",
            variant="solid",
            color_scheme="gray",
            high_contrast=True,
            radius="full",
            aria_label="Cerrar video",
            title="Cerrar video",
            on_click=DiscoverReelsState.stop,
            class_name="q-dr-close",
        ),
        class_name=rx.cond(embed_only, "q-dr-cover q-dr-cover--embed", "q-dr-cover"),
    )
    return rx.cond(
        DiscoverReelsState.playing_key == key,
        player,
        rx.el.button(
            cover,
            type="button",
            on_click=DiscoverReelsState.play(key),
            class_name="q-dr-cover-button",
            aria_label="Ver el reel aquí",
        ),
    )


def _transcript_block(reel: rx.Var[dict[str, str]]) -> rx.Component:
    """What is said in the reel, as the run stored it (ADR 42 R7: the screen never pays
    for a transcript) — «no tiene voz» when it was transcribed and says nothing, nothing
    at all when it never was."""
    return rx.cond(
        reel["transcript"] != "",
        rx.vstack(
            rx.hstack(
                rx.icon("captions", size=13, color=T.TEXT_MUTED),
                rx.text("Lo que se dice", size="1", weight="medium"),
                spacing="1",
                align="center",
            ),
            rx.text(reel["transcript"], size="1", color=T.TEXT_MUTED, class_name="q-dr-transcript"),
            spacing="1",
            align_items="start",
            width="100%",
        ),
        rx.cond(
            reel["transcript_state"] == "none",
            rx.text("Este video no tiene voz.", size="1", color=T.TEXT_MUTED),
        ),
    )


def _details_panel(reel: rx.Var[dict[str, str]]) -> rx.Component:
    """Everything else about the reel (§ request 2026-10-15): a «Detalles» bar that
    opens the card downwards — an accordion, by click, the same on a phone — with the
    other figures, the caption, the sound, why it is of the rubro and the transcript."""
    figures = rx.box(
        _detail("Me gusta", reel["likes"]),
        _detail("Comentarios", reel["comments"]),
        rx.cond(reel["saves"] != "", _detail("Guardados", reel["saves"])),
        rx.cond(reel["seconds"] != "", _detail("Duración", reel["seconds"])),
        _detail("Publicado", reel["age"]),
        class_name="q-dr-figures",
    )
    panel = rx.vstack(
        figures,
        rx.cond(
            reel["caption"] != "",
            rx.text(reel["caption"], size="1", color=T.TEXT_MUTED, class_name="q-dr-caption"),
        ),
        rx.cond(
            reel["sound"] != "",
            rx.hstack(
                rx.icon("music", size=12, color=T.TEXT_FAINT, flex_shrink="0"),
                rx.text(reel["sound"], size="1", color=T.TEXT_MUTED, class_name="q-dr-ellipsis"),
                spacing="1",
                align="center",
                width="100%",
            ),
        ),
        rx.cond(
            reel["reason"] != "",
            rx.hstack(
                rx.icon("sparkles", size=12, color=T.TEXT_FAINT, flex_shrink="0"),
                rx.text(reel["reason"], size="1", color=T.TEXT_MUTED),
                spacing="1",
                align="start",
                width="100%",
            ),
        ),
        _transcript_block(reel),
        rx.link(
            rx.hstack(
                rx.icon("external-link", size=13),
                rx.text("Abrir en ", reel["network_label"], size="1"),
                spacing="1",
                align="center",
            ),
            href=reel["url"],
            is_external=True,
        ),
        spacing="2",
        width="100%",
        align_items="start",
        class_name="q-dr-more-panel",
    )
    open_ = DiscoverReelsState.expanded.contains(reel["key"])
    return rx.box(
        rx.el.button(
            rx.text(rx.cond(open_, "Menos", "Detalles"), size="1", weight="medium"),
            rx.icon(rx.cond(open_, "chevron-up", "chevron-down"), size=14),
            type="button",
            class_name="q-dr-more-bar",
            aria_expanded=rx.cond(open_, "true", "false"),
            on_click=DiscoverReelsState.toggle_details(reel["key"]),
        ),
        rx.cond(open_, panel),
        class_name="q-dr-more",
    )


def _reel_tile(reel: rx.Var[dict[str, str]]) -> rx.Component:
    """One idea as the «C» card (§ request 2026-10-15): the picture with how it does
    against its own account, who and how many views, what it is (format and hook), the
    rest folded into «Detalles», and «Replicar con mi marca»."""
    return card(
        rx.vstack(
            _reel_media(reel),
            rx.vstack(
                rx.hstack(
                    rx.text(reel["handle"], size="2", weight="bold", class_name="q-dr-ellipsis"),
                    rx.spacer(),
                    rx.text(reel["age"], size="1", color=T.TEXT_MUTED, white_space="nowrap"),
                    spacing="2",
                    align="center",
                    width="100%",
                ),
                # the three figures that rank a reel (§ 2026-10-15): «2.7M vistas ·
                # 92K/día · 15%» — views, views per day since it was published, and
                # interactions over views
                rx.hstack(
                    rx.text(reel["views"], " vistas", size="3", weight="medium"),
                    rx.cond(
                        reel["per_day"] != "",
                        rx.fragment(
                            rx.text("·", size="3", color=T.TEXT_FAINT),
                            rx.text(reel["per_day"], size="3", weight="medium"),
                        ),
                    ),
                    rx.cond(
                        reel["engagement"] != "",
                        rx.fragment(
                            rx.text("·", size="3", color=T.TEXT_FAINT),
                            rx.text(
                                reel["engagement"],
                                size="3",
                                weight="medium",
                                title="Interacciones sobre vistas",
                            ),
                        ),
                    ),
                    spacing="2",
                    align="center",
                    wrap="wrap",
                    class_name="q-dr-figures-line",
                ),
                # § 2026-10-20: the shown reels are the product OR its category again, so
                # the card says which (it had no pill while only the product was shown)
                rx.hstack(
                    rx.cond(
                        reel["affinity"] == "categoria",
                        rx.box(
                            rx.text("Tu categoría", size="1"),
                            class_name="q-dr-tag q-dr-tag--muted",
                            title="La misma clase de oferta que vendes, sin ser tu producto",
                        ),
                        rx.box(rx.text("Tu producto", size="1"), class_name="q-dr-tag"),
                    ),
                    rx.cond(
                        reel["format"] != "",
                        rx.box(
                            rx.text(reel["format"], size="1"),
                            class_name="q-dr-tag q-dr-tag--muted",
                        ),
                    ),
                    spacing="1",
                    wrap="wrap",
                ),
                spacing="1",
                width="100%",
                align_items="start",
            ),
            _details_panel(reel),
            rx.vstack(
                rx.button(
                    rx.cond(
                        DiscoverReelsState.replicating == reel["key"],
                        loading_spinner("sm"),
                        rx.icon("copy", size=14),
                    ),
                    rx.cond(
                        DiscoverReelsState.replicating == reel["key"],
                        "Preparando referencia…",
                        "Replicar con mi marca",
                    ),
                    size="2",
                    width="100%",
                    min_height="44px",
                    variant="soft",
                    on_click=DiscoverReelsState.replicate(reel["key"]),
                    disabled=(DiscoverReelsState.replicating != "") | CreativeState.gen_generating,
                    class_name="q-dr-replicate",
                ),
                rx.text(
                    REPLICATE_HELP,
                    size="1",
                    color=T.TEXT_MUTED,
                    class_name="q-dr-replicate-help",
                ),
                spacing="1",
                width="100%",
                align_items="start",
            ),
            spacing="2",
            width="100%",
            align_items="start",
        ),
        padding="0.6rem",
        width="100%",
        class_name="q-dr-card",
        # Keep each card tied to its reel when the list changes.
        key=reel["key"],
    )


def _ideas() -> rx.Component:
    """The stored ideas under the header that dates them — and, above them, the notice
    of a newer run that could not check its reels (the ideas below are still true)."""
    S = DiscoverReelsState
    grid = rx.box(
        rx.foreach(S.reels, _reel_tile),
        class_name="q-dr-grid",
        role="list",
        aria_label="Ideas para tus reels",
    )
    return rx.vstack(
        rx.cond(
            S.notice_title != "",
            callout(
                rx.fragment(rx.text.strong(S.notice_title), rx.el.br(), S.notice_body),
                "warn",
            ),
        ),
        section(S.title, grid, description=S.body),
        spacing="4",
        width="100%",
    )


def _empty(icon: str) -> rx.Component:
    """The empty state on screen: its words, and its one button when it has one — the
    accounts the brand follows and what it sells are both set in Tu marca."""
    S = DiscoverReelsState
    return empty_state(
        icon,
        S.title,
        S.body,
        rx.cond(
            S.action != "",
            rx.link(rx.button(S.action, variant="soft", size="3"), href=BRAND_KIT_HREF),
        ),
    )


def _preparing() -> rx.Component:
    """The first run is being prepared (decision 2(a)): while it is in flight that is
    work in progress, so a spinner over the sentence that says it (`docs/design-system.md`
    §5.4), centred like `empty_state`; with nothing queued (option B, or a first run that
    could not be queued) no spinner — nothing is running."""
    S = DiscoverReelsState
    return rx.center(
        rx.vstack(
            rx.cond(
                S.waiting,
                loading_spinner("md"),
                rx.icon("sparkles", size=T.ICON_LG, color=T.TEXT_FAINT),
            ),
            rx.heading(S.title, size="5", as_="h2", text_align="center"),
            rx.text(S.body, size="2", color=T.TEXT_MUTED, text_align="center", max_width="440px"),
            spacing="3",
            align="center",
        ),
        padding=T.PAD_EMPTY,
        width="100%",
        flex="1",
    )


def _loading() -> rx.Component:
    """The stored ideas are being read: content loading, so skeletons in the shape of
    the cards (`docs/design-system.md` §5.4), never a spinner."""
    return rx.box(
        *(skeleton_card(lines=4) for _ in range(3)),
        class_name="q-dr-grid",
    )


def _load_failed() -> rx.Component:
    """The stored ideas could not be read: the error replaces the list, with the button
    that reads them again (a database read — it never searches nor pays)."""
    return rx.vstack(
        callout(DiscoverReelsState.load_error, "error"),
        rx.button(
            rx.icon("refresh-cw", size=14),
            reels_ideas_vm.RETRY,
            variant="soft",
            on_click=DiscoverReelsState.load,
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _body() -> rx.Component:
    S = DiscoverReelsState
    return rx.cond(
        S.load_error != "",
        _load_failed(),
        rx.match(
            S.screen,
            ("", _loading()),
            (SCREEN_IDEAS, _ideas()),
            (SCREEN_NO_ACCOUNTS, _empty("users")),
            (SCREEN_NO_BRIEF, _empty("store")),
            (SCREEN_CHECK_FAILED, _empty("clock")),
            (SCREEN_NO_IDEAS, _empty("film")),
            (SCREEN_UNAVAILABLE, _empty("calendar-clock")),
            _preparing(),
        ),
    )


def discover_view() -> rx.Component:
    """The centre of /create when «Descubrir reels» is chosen. Opening it reads only what
    is stored (ADR 42 R7): the ideas show at once, nothing is searched or paid; leaving it
    stops any re-read."""
    return card(
        rx.vstack(
            rx.cond(
                DiscoverReelsState.replicate_error != "",
                callout(DiscoverReelsState.replicate_error, "error"),
            ),
            _body(),
            spacing="4",
            width="100%",
            flex="1",
        ),
        padding="1.25rem",
        width="100%",
        flex="1",
        display="flex",
        on_mount=DiscoverReelsState.load,
        on_unmount=DiscoverReelsState.leave,
    )

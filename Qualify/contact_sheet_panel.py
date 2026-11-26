"""«Revisa tu video antes de aprobarlo» — the contact sheet right before «Aprobar»
(EF-18, m-25026598; ADR 50 D8, D-E1).

The creative worker keeps six frames of the composed video (start, end and cuts, with
the texts and effects on top) beside the piece. This panel shows them, before the
approval, on the two review screens: the Clip's page (`creative_pages`) and «Tu video
completo» (`final_video_card`).

- **Informative only (D8):** the owner alone reviews it. It never holds «Aprobar»: with
  no sheet yet the panel simply is not there (no waiting line — a piece whose kind gets
  no sheet would otherwise wait forever).
- **Read once per piece and video**, never per render: `watch` runs on mount, keyed by
  the draft and the file the screen shows (a new version or a new join remounts it).
  While the worker has not made the sheet (or made none drawable here) `read_loop`
  reads again every `RETRY_SECONDS`, at most `MAX_READS` times, and only while the
  panel is on screen (`stop` on unmount); a miss is remembered `MISS_SECONDS`. A
  failed read is logged and leaves no sheet; the screen goes on.
- **Grid:** three columns on every width, a 375 px phone included (Deivid, 2026-11-25,
  option A): the frames are small there, so each one opens bigger in a dialog with
  «Cerrar», and the panel says so. Each frame shows its second («0:03») and has its own
  `alt` («Cuadro de tu video en el segundo 3»).
- **What to do when something looks wrong:** each screen passes its own sentence
  (`fix`), naming the way it really offers, and only while it is offered.

Backend: `contact_sheet_provider`. Words and the business-key filter: `contact_sheet_vm`.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
from uuid import UUID

import reflex as rx

from . import contact_sheet_provider as provider
from . import contact_sheet_vm as vm
from .auth_state import AuthState
from .r2_media import BACKEND_BASE
from .tenant import tenant_uuid
from .ui import tokens as T
from .ui.primitives import card

logger = logging.getLogger(__name__)

PANEL_ID = "q-contact-sheet"
HEADING_ID = "q-contact-sheet-title"
#: Between two reads while the worker has not made the sheet yet.
RETRY_SECONDS = 10.0
#: First read plus the retries: about a minute on screen. The sheet is made before the
#: piece can be approved, so this only covers a race with the worker.
MAX_READS = 7
#: A read is reused this long; past it the `/r2media` tokens (1 h) are minted again.
REUSE_SECONDS = 30 * 60
#: Three columns on every width, phones included (Deivid, 2026-11-25, option A).
GRID_COLUMNS = "repeat(3, 1fr)"


#: «Not made yet» after `MAX_READS` is remembered per piece and file this long: a remount
#: within it does not read `MAX_READS` times again.
MISS_SECONDS = 5 * 60
#: Watch tokens come from the module, never from the state: a reset (logout, business
#: switch) sets the state's back to 0, and a counter on the state would hand a NEW
#: watch the same number as an old one still retrying for the previous business.
_tokens = itertools.count(1)


def _target(draft_id: str, video_key: str) -> str:
    """What a panel shows: «draft|video» — the same string the component compares."""
    return f"{draft_id}|{video_key}"


class ContactSheetState(rx.State):
    """The sheet of the piece on screen (one at a time)."""

    #: what the grid draws: `{"url", "time", "alt", "zoom"}` per frame
    frames: list[dict[str, str]] = []
    #: «draft|video» the frames belong to: a panel shows them only when it is ITS own
    #: (another piece's, the instant before its read, or a second panel, never)
    showing: str = ""
    #: the worker already made the sheet for `showing` (no reason to read again)
    _made: bool = False
    _read_at: float = 0.0
    #: «draft|video» → when its reads ran out without a sheet (`MISS_SECONDS`)
    _missed: dict[str, float] = {}
    _token: int = 0
    #: what `read_loop` reads, set by `watch` for the token it claimed
    _draft: str = ""
    _video: str = ""
    _tenant: str = ""

    @rx.var
    def has_frames(self) -> bool:
        return len(self.frames) > 0

    async def _session_tenant(self) -> UUID | None:
        """The session's business (in a background event, under the state's lock)."""
        auth = await self.get_state(AuthState)
        return tenant_uuid(auth.session_tenant_id)

    async def _still_mine(self, token: int, target: str, tenant: UUID) -> bool:
        """Under the lock: this watch is still the panel's, for the same piece and file,
        in the same business (a logout or a switch in between drops its result)."""
        return (
            token == self._token
            and self.showing == target
            and await self._session_tenant() == tenant
        )

    @rx.event
    async def watch(self, draft_id: str, video_key: str) -> rx.event.EventSpec | None:
        """The panel mounted for `draft_id`'s file on screen (`video_key`). A normal event,
        so it runs in order with `stop`: it claims the panel (a new token) and hands the
        reads to `read_loop` — which, if `stop` came first, finds another token at its
        first lock and never starts. Nothing is read again for a piece and file already
        read (`REUSE_SECONDS`) or just missed (`MISS_SECONDS`)."""
        raw = draft_id if isinstance(draft_id, str) else ""
        draft = tenant_uuid(raw) if raw else None
        video = video_key if isinstance(video_key, str) else ""
        target = _target(raw, video)
        now = time.monotonic()
        if (
            draft is not None
            and video
            and self.showing == target
            and self._made
            and now - self._read_at < REUSE_SECONDS
        ):
            return None  # already read for this piece and file
        self._token = next(_tokens)
        self.showing = target
        self._made = False
        self.frames = []
        if draft is None or not video:
            return None
        if now - self._missed.get(target, now - MISS_SECONDS) < MISS_SECONDS:
            return None  # its reads ran out a moment ago
        tenant = await self._session_tenant()
        if tenant is None:
            return None
        self._draft, self._video, self._tenant = str(draft), video, str(tenant)
        return ContactSheetState.read_loop(self._token)

    @rx.event(background=True)
    async def read_loop(self, token: int) -> None:
        """Read the sheet for the panel that claimed `token`, again only while the worker
        has not made it (or made none drawable) and the panel is still that one."""
        async with self:
            target = self.showing
            draft = tenant_uuid(self._draft)
            tenant = tenant_uuid(self._tenant)
            video = self._video
            if draft is None or tenant is None:
                return
            if not await self._still_mine(token, target, tenant):
                return  # unmounted (or replaced) before the first read
        for attempt in range(MAX_READS):
            if attempt:
                await asyncio.sleep(RETRY_SECONDS)
                async with self:
                    if not await self._still_mine(token, target, tenant):
                        return  # unmounted, another piece/file, or another business
            try:
                read = await asyncio.to_thread(provider.read_sheet, tenant, draft, video)
            except Exception as exc:  # noqa: BLE001 — no sheet; the screen goes on
                logger.warning("contact sheet unreadable: %s", type(exc).__name__)
                return
            if not (read.made and read.frames):
                continue  # not made, or nothing drawable for this file: the normal rule
            async with self:
                if not await self._still_mine(token, target, tenant):
                    return
                self._made = True
                self._read_at = time.monotonic()
                self.frames = [dict(frame) for frame in read.frames]
            return
        async with self:
            if await self._still_mine(token, target, tenant):
                now = time.monotonic()
                # remember this miss; forget the ones past `MISS_SECONDS`
                kept = {k: t for k, t in self._missed.items() if now - t < MISS_SECONDS}
                self._missed = {**kept, target: now}

    @rx.event
    def stop(self) -> None:
        """The panel left the screen: a pending retry reads nothing more."""
        self._token = next(_tokens)


S = ContactSheetState


def _big_frame(frame: rx.Var[dict[str, str]]) -> rx.Component:
    """The frame bigger, in a dialog: its title is the frame's `alt`, its one way out
    «Cerrar». Radix gives the focus back to the frame that opened it (its trigger)."""
    return rx.dialog.content(
        rx.dialog.title(frame["alt"], size="3"),
        rx.dialog.description(vm.ZOOM_HELP, size="2", color=T.TEXT_MUTED),
        rx.image(
            src=BACKEND_BASE + frame["url"],
            alt=frame["alt"],
            width="100%",
            height="auto",
            max_height="70vh",
            object_fit="contain",
            class_name="q-thumb",
            margin_y="0.75rem",
        ),
        rx.flex(
            rx.dialog.close(
                rx.button(vm.CLOSE_LABEL, variant="soft", size="3", min_height="2.75rem"),
            ),
            justify="end",
        ),
        max_width="26rem",
    )


def _frame(frame: rx.Var[dict[str, str]]) -> rx.Component:
    """One frame: the picture (the trigger of its own dialog) and its second below."""
    return rx.box(
        rx.dialog.root(
            rx.dialog.trigger(
                rx.el.button(
                    rx.image(
                        src=BACKEND_BASE + frame["url"],
                        alt=frame["alt"],
                        width="100%",
                        height="auto",
                        loading="lazy",
                        class_name="q-thumb",
                        display="block",
                    ),
                    type="button",
                    aria_label=frame["zoom"],
                    title=frame["alt"],
                    padding="0",
                    border="none",
                    background="transparent",
                    cursor="zoom-in",
                    width="100%",
                    display="block",
                ),
            ),
            _big_frame(frame),
        ),
        rx.text(frame["time"], size="1", color=T.TEXT_MUTED, class_name="q-nums"),
        role="listitem",
        display="flex",
        flex_direction="column",
        gap="0.25rem",
        min_width="0",
    )


def _sheet(heading: str, fix: rx.Var[str] | str) -> rx.Component:
    fix_line = rx.text(fix, size="2", color=T.TEXT_MUTED)
    return rx.vstack(
        rx.heading(vm.TITLE, as_=heading, size="3", id=HEADING_ID),
        rx.text(vm.HELP, size="2", color=T.TEXT_MUTED),
        rx.text(vm.TAP_HINT, size="2", color=T.TEXT_MUTED),
        rx.cond(fix != "", fix_line) if isinstance(fix, rx.Var) else (fix_line if fix else None),
        rx.box(
            rx.foreach(S.frames, _frame),
            role="list",
            aria_labelledby=HEADING_ID,
            display="grid",
            grid_template_columns=GRID_COLUMNS,
            gap="0.75rem",
            width="100%",
        ),
        spacing="2",
        align_items="start",
        width="100%",
    )


def _key(draft_id: rx.Var[str] | str, video_key: rx.Var[str] | str) -> rx.Var[str] | str:
    """The panel's React key: a new draft or file is a new panel (a new `watch`)."""
    if isinstance(draft_id, str) and isinstance(video_key, str):
        return _target(draft_id, video_key)
    return rx.Var.create(draft_id).to(str) + "|" + rx.Var.create(video_key).to(str)


def contact_sheet_panel(
    draft_id: rx.Var[str] | str,
    video_key: rx.Var[str] | str,
    *,
    heading: str = "h3",
    framed: bool = False,
    fix: rx.Var[str] | str = "",
) -> rx.Component:
    """The sheet of `draft_id`'s video on screen (`video_key`), as a `section` named by
    its heading — nothing at all until there are frames. `framed=True` puts it on its
    own `card` (the Clip's page); inside «Tu video completo» it sits in the card's
    column. `fix` is the screen's «Si algo se ve mal, …» sentence ("" = none: that way
    is not offered now). Mounting it starts the read; a new draft or file remounts it
    (`key`)."""
    body = _sheet(heading, fix)
    key = _key(draft_id, video_key)
    # only ITS frames: never the previous piece's for an instant, nor another panel's
    mine = S.has_frames & (S.showing == key)
    return rx.el.section(
        rx.cond(mine, card(body) if framed else body),
        id=PANEL_ID,
        aria_labelledby=HEADING_ID,
        key=key,
        on_mount=S.watch(draft_id, video_key),
        on_unmount=S.stop,
        display=rx.cond(mine, "block", "none"),
        width="100%",
    )


__all__ = [
    "GRID_COLUMNS",
    "HEADING_ID",
    "MAX_READS",
    "MISS_SECONDS",
    "PANEL_ID",
    "RETRY_SECONDS",
    "ContactSheetState",
    "contact_sheet_panel",
]

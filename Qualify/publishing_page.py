"""Publish screen (A5 vertical slice) — upload 1-10 files, pick a connected account,
publish. 2-10 videos publish together as one Instagram carousel (QUA-99).

Built on the `ui` shell (`app_shell` / `page_header` / `page_body`); badges and callouts
follow the design-system tones (docs/design-system.md). Adds the `/publish` route only.

QUA-98 started as a visual-only pass — every original `PublishState` binding (`value=`,
`on_change=`, `on_click=`, `disabled=`) is still byte-for-byte the same expression. One
narrow, explicitly-authorized addition later touched `publishing_state.py` too (never Meta
calls/payloads/auth/account selection/video loading/caption logic/the publish button's
core behavior): the success/failure toasts and the post-success form reset — see
`_success_toast`/`_failure_toast` and the `self.caption = ""` reset there (the
gallery-redesign follow-up below replaced QUA-98's original `rx.clear_selected_files`
reset with clearing `pending_items` directly, since the dropzone's own client-side
selection state is no longer what the gallery renders from).

QUA-99 (6/6): the dropzone gained `multiple=True`/`max_files` raised from 1 to 10 — the
SAME `rx.upload` widget, no new upload abstraction. The caption field
(`_caption_section`) is completely UNTOUCHED — one field, one source of truth, used
identically for 1 file or a carousel; only `publishing_state.py` decides downstream
which provider seam (`start_publish` vs `start_many_publish`) the SAME `self.caption`
value reaches. QUA-103 then added `image/jpeg` to `accept` — see that ticket's note
below for the image path this screen gained.

**Gallery redesign (QUA-99 UX follow-up)** replaced the plain list of selected names with
a grid — see `_pending_tile`'s docstring for the shape. Each tile shows a REAL thumbnail,
captured entirely client-side (a first-frame capture for video, a direct read for image —
`ui/video_preview.py` / `ui/image_preview.py`, native browser APIs, no library, no backend
change), falling back to a kind-appropriate icon while nothing has been captured yet (or
never could be). The polling status (`_status_block`) also stopped being one generic
spinner: while a carousel is being assembled it now shows which child video is
uploading/processing, or that the carousel/final confirmation step is under way
(`PublishState.carousel_stage_label`), plus how long the wait has been running
(`PublishState.elapsed_label`) and a plain-language note that Meta's own processing can
take several minutes — all derived from data the backend already had, nothing invented.

**QUA-103** added JPEG images as a first-class selection alongside video — the `accept`
dropzone, the thumbnail strategy per tile (`PendingItemVM.kind`), and the copy below all
know about both kinds. A carousel (2-10 items) may now be any mix of image and video —
`PublishState`/`PublishService` bifurcate per item by its own `media_type`; this screen's
own code never branches on it beyond picking a thumbnail.

**Known, deliberately unaddressed risk (documented, not fixed, in this ticket):** Meta
crops every item in a carousel to the aspect ratio of its FIRST item
(`content-publishing.md:110`) — if a mixed carousel starts with an image, any video(s)
after it are cropped to that image's ratio, not their own. Neither this screen nor
`PublishService` does anything about it (no reordering, no warning) — the operator's own
selection order is respected exactly as given. Any UX mitigation (a warning, a suggested
reorder) is a follow-up decision, not part of this ticket's scope.

**PUBLICAR-4 (m-24842986): three steps and a «listo».** `/publish` is now one
assistant (N6) — ① ¿Qué vas a publicar? (this gallery) ② ¿Dónde sale? (publication on
the profile or a 24-hour historia, and the account, preselected when there is only
one) ③ Revisa y publica (the review in words, the text only for a publication). Every
step stays MOUNTED and is only hidden (`_step_panel`), so «Atrás» never loses a file,
a thumbnail or a word. Formats and sizes no longer show up front: only in the error
when a file does not fit. A confirmed publish replaces the assistant with a persistent
`callout` and two buttons (N3: «Ver mi semana», «Publicar otra») — the toast stays as
an extra. «Tendencias e inspiración» left the flow: it opens behind «Ideas para tu
próxima publicación». The step and the kind live in `PublishHubState`; a historia is
published by `StoriesState` (`publish_now` hands the file over); the historia-only
pieces are in `stories_page.py`. Before this, QUA-113 had put two separate forms
behind a `Publicaciones | Historias` selector here, with an «Antes de publicar» card.
"""

from __future__ import annotations

import reflex as rx

from .publish_hub_state import FLOW_POSTS, FLOW_STORIES, PublishHubState
from .publish_wizard_vm import (
    STEP_REVIEW,
    STEP_TITLES,
    STEP_WHAT,
    STEP_WHERE,
    STORY_NEEDS_ONE_FILE,
    TOTAL_STEPS,
)
from .publishing_state import _MAX_ITEMS, _UPLOAD_ID, _WAIT_EXPLANATION, PublishState
from .publishing_vm import ConnectionOptionVM, PendingItemVM
from .stories_page import share_to_instagram_button, stories_status_block
from .stories_state import StoriesState
from .trending_panel import trending_card
from .ui import (
    app_shell,
    callout,
    card,
    choice_card,
    choice_card_check,
    dropzone,
    empty_state,
    loading_spinner,
    page_body,
    page_header,
    section,
)
from .ui import tokens as T
from .ui.image_preview import gallery_image_preview_capture_anchor
from .ui.video_preview import gallery_preview_capture_anchor, video_frame_preview_src

# Gallery redesign, part 2 (QUA-99 UX follow-up) — a stable DOM id `video_preview.py`
# listens on (native `drop`/`change` delegation) to find each tile's own `File` for its
# real thumbnail. Lives here, not there, for the same reason `_UPLOAD_ID` does: this
# module owns the actual DOM structure, `video_preview.py` stays a plain generic helper
# with no knowledge of this specific screen's layout.
_GALLERY_ROOT_ID = "publish-gallery-root"

# PUBLICAR-4: «Abrir en Instagram» (a historia) shares the File `ui/video_preview.py`
# stashed for this gallery — the LAST one picked. Removing any tile forgets it, so a
# removed file can never be the one shared; the owner picks it again instead.
_FORGET_SHARED_FILE = (
    "if (window.__qualifyPreviews && window.__qualifyPreviews.filesByRoot) "
    f"{{ delete window.__qualifyPreviews.filesByRoot['{_GALLERY_ROOT_ID}']; }}"
)

# N12: every control on this screen is at least 44 px tall.
_TARGET = "44px"


def _connection_item(conn: ConnectionOptionVM) -> rx.Component:
    return rx.select.item(conn.external_username + " · " + conn.platform, value=conn.id)


def _connection_selector() -> rx.Component:
    return rx.select.root(
        rx.select.trigger(placeholder="Elige una cuenta conectada", width="100%"),
        rx.select.content(
            rx.foreach(PublishState.connections, _connection_item),
        ),
        value=PublishState.selected_connection_id,
        on_change=PublishState.select_connection,
        size="3",
        width="100%",
    )


def _pending_tile(item: PendingItemVM, index: rx.Var[int]) -> rx.Component:
    """One already-selected file, image or video (gallery redesign, QUA-99 UX
    follow-up; image support QUA-103).

    Shows a REAL thumbnail (`video_frame_preview_src`, `ui/video_preview.py` /
    `ui/image_preview.py` — native browser APIs, client-side only, no backend/Meta call)
    once the gallery's shared capture hook has processed it; falls back to a
    kind-appropriate icon+filename tile while it is not ready yet (a moment, right after
    the file is picked) or never could be (an unsupported codec for video — the fallback
    is not an error state, just what "no preview" always looked like here). `preview_src`
    reads the SAME shared store regardless of which anchor (video or image) wrote it —
    see `video_frame_preview_src`'s docstring for why the capture logic itself has to
    live in gallery-wide hooks rather than one hook per tile (a per-tile hook cannot see
    `rx.foreach`'s per-item Var at all; `previews[filename]`, a plain lookup rather than
    a hook, can).

    Rendered as a SIBLING of the dropzone (`_gallery_zone` below), never as its child —
    that is what makes clicking a tile or its `X` never reopen the file picker; only the
    `+` tile (the actual `rx.upload` widget) is wired to do that.
    """
    preview_src = video_frame_preview_src(root_id=_GALLERY_ROOT_ID, filename=item.filename)
    return rx.box(
        rx.cond(
            preview_src != "",
            rx.el.img(src=preview_src, alt=item.filename, class_name="q-pub-tile-img"),
            rx.vstack(
                rx.cond(
                    item.kind == "image",
                    rx.icon("image", size=24, color=T.tone_color("ok", 9)),
                    rx.icon("film", size=24, color=T.tone_color("ok", 9)),
                ),
                rx.text(
                    item.filename,
                    size="1",
                    color=T.TEXT_MUTED,
                    width="100%",
                    text_align="center",
                    white_space="nowrap",
                    overflow="hidden",
                    text_overflow="ellipsis",
                ),
                spacing="1",
                align="center",
                justify="center",
                height="100%",
                padding="0.4rem",
            ),
        ),
        # The carousel position: a dark glass chip (`.q-pub-tile-pos`), readable on any
        # first frame — a chip, never a solid badge.
        rx.box(index + 1, class_name="q-pub-tile-pos", aria_hidden="true"),
        # A thumbnail can be almost any color underneath this — the dark glass chip
        # with its ring (`.q-pub-tile-x`, assets/qualify-publish.css) is what keeps the
        # X readable regardless (a plain solid red circle alone was reported hard to
        # notice against a busy first frame). Soft under the skin, so «Publicar» stays
        # the screen's one solid button.
        rx.icon_button(
            rx.icon("x", size=14),
            on_click=[
                PublishState.remove_pending_file(index),
                rx.call_script(_FORGET_SHARED_FILE),
            ],
            disabled=~PublishState.can_edit_gallery,
            title="Quitar este archivo",
            aria_label="Quitar este archivo",
            size="1",
            variant="soft",
            color_scheme=T.tone_scale("error"),
            radius="full",
            class_name="q-pub-tile-x",
        ),
        class_name="q-pub-tile",
    )


def _upload_widget(children: rx.Component, *, compact: bool) -> rx.Component:
    """The ONE actual dropzone (`rx.upload`) on this screen — either the big empty-state
    prompt (`compact=False`, nothing selected yet) or the small `+` tile that sits inside
    the grid alongside already-selected tiles (`compact=True`). Same widget, same props,
    either way: `multiple=True` and a dynamic `max_files` (QUA-99 UX follow-up —
    `PublishState.remaining_slots`, so a half-full gallery cannot accept more than the
    10-item cap actually leaves room for) plus the real, server-side invariant in
    `PublishState.add_files`, which this is only a client-side nicety on top of, same
    posture the original single-video dropzone already documented for itself.
    """
    return dropzone(
        children,
        upload_id=_UPLOAD_ID,
        # QUA-103: JPEG joins the two video containers Meta already accepted here —
        # JPEG is the ONLY image format Meta's Content Publishing API supports at all
        # (a platform restriction, not an incomplete whitelist — see
        # `qualify_api.publishing.client.IMAGE_CONTENT_TYPE`'s docstring). This is a
        # client-side nicety, same posture as everything else in this widget: the real
        # gate is `MediaStagingService.stage_media`'s content-type + magic-byte check.
        accept={
            "video/mp4": [".mp4"],
            "video/quicktime": [".mov"],
            "image/jpeg": [".jpg", ".jpeg"],
        },
        multiple=True,
        max_files=PublishState.remaining_slots,
        # Client-side mirror of `ObjectGate.MAX_MEDIA_BYTES` (qualify_shared/objects/
        # gate.py) — the video ceiling, and the widest one `rx.upload` can express in one
        # `max_size` (react-dropzone has no per-accepted-type limit). The real,
        # load-bearing barriers are server-side and per-format: 300 MB for video, 8 MB
        # for IMAGE (`MediaStagingService`/`client.IMAGE_MAX_BYTES`) — an oversized JPEG
        # still passes this client-side check and is rejected there, with a clear toast
        # (`publishing_state._IMAGE_TOO_LARGE`), same "server-side guard is the real
        # invariant" posture this widget already documents for everything else.
        max_size=300 * 1024 * 1024,
        disabled=~PublishState.can_edit_gallery,
        # QUA-99 UX follow-up: bound to `add_files`, which BUFFERS onto whatever is
        # already selected (gallery redesign) rather than replacing it — see
        # `PublishState.add_files`'s docstring for why a plain `rx.selected_files`-driven
        # gallery cannot support "add more without losing what's there" at all.
        # `video_frame_preview_src` (`ui/video_preview.py`) gets its own real `File`
        # access to the SAME dropped files a different way (a native `drop`/`change`
        # DOM listener on `_GALLERY_ROOT_ID`, never touching this `on_drop` wiring) — see
        # that module's docstring for why reusing Reflex's own `filesById` Context here
        # turned out not to be composable with a second handler in this list.
        on_drop=PublishState.add_files,
        # Replaces Reflex's default English "Files not Accepted" toast
        # (reflex_components_core.core.upload._default_drop_rejected) with one in
        # Spanish, consistent with the rest of Qualify. Static on purpose: it covers
        # every rejection reason (wrong format, too large, more than the cap) with one
        # message rather than inspecting `rejected_files` via undocumented internal Var
        # APIs.
        # PUBLICAR-4: formats and sizes are said HERE, in the error, and nowhere up
        # front. Static on purpose: one message for every rejection reason (wrong
        # format, too large, more than the cap), never `rejected_files` internals.
        on_drop_rejected=rx.toast.error(
            "Ese archivo no se puede usar",
            description=(
                "Elige fotos JPG o videos MP4 o MOV: hasta 300 MB por video, 8 MB por "
                f"foto y {_MAX_ITEMS} a la vez."
            ),
        ),
        variant="tile" if compact else "zone",
    )


def _add_tile_content() -> rx.Component:
    return rx.vstack(
        rx.icon("plus", size=22, color=T.tone_color("accent", 9)),
        rx.text("Agregar", size="1", color=T.TEXT_MUTED),
        spacing="1",
        align="center",
        justify="center",
        height="100%",
    )


def _empty_state_content() -> rx.Component:
    return rx.vstack(
        rx.icon("image-plus", size=32, color=T.TEXT_FAINT),
        rx.text("Toca para elegir fotos o videos de tu teléfono", size="3", weight="medium"),
        rx.text(
            "Desde la computadora también puedes arrastrarlos aquí.", size="1", color=T.TEXT_MUTED
        ),
        spacing="2",
        align="center",
        text_align="center",
    )


def _preview_capture_anchor() -> rx.Component:
    """Mounted UNCONDITIONALLY (a sibling of the `rx.cond` below, never inside either
    branch of it) so the gallery's shared thumbnail-capture listeners
    (`gallery_preview_capture_anchor` for video, `gallery_image_preview_capture_anchor`
    for JPEG — QUA-103) are already attached before the very FIRST file is ever picked —
    not only once a tile exists to ask for one.

    Without this, the FIRST video (always selected while the gallery still shows the
    empty-state prompt, since `pending_items` starts empty) never got a real thumbnail
    while every LATER one did — reported exactly this way, 2026-09-10. The empty-state
    prompt is one `rx.cond` branch, the tile grid is the other, and the tile grid is
    the only place a capture listener used to get mounted — so a file dropped while the
    empty prompt was still showing had nothing listening yet. Renders nothing visible;
    only the hook's side effect (attaching the listeners) matters here.
    """
    return rx.box(
        gallery_preview_capture_anchor(root_id=_GALLERY_ROOT_ID),
        # QUA-103: a SECOND, independent capture anchor for JPEG files — mounted
        # alongside the video one, never replacing it. See `ui/image_preview.py`'s
        # module docstring for why two listeners on the same root id is safe.
        gallery_image_preview_capture_anchor(root_id=_GALLERY_ROOT_ID),
        display="none",
    )


def _gallery_zone() -> rx.Component:
    """Instagram-carousel-style grid (gallery redesign, QUA-99 UX follow-up) — replaces
    the old plain list of file names. Each already-selected video is its own tile
    (`_pending_tile`, position badge + `X`), followed by a `+` tile while there is still
    room (`PublishState.remaining_slots > 0`); once the gallery is empty, the whole area
    collapses back to the original big drag-and-drop prompt. Visual order here IS
    `PublishState.pending_items`' order, which IS the order `publish_background` sends
    downstream as carousel `position` (`PublishService.start_many`, QUA-99 4/6) —
    `rx.foreach`'s own index is the only place that order is read from, never a second,
    separately-tracked position field that could drift from it.
    """
    return rx.box(
        _preview_capture_anchor(),
        rx.cond(
            PublishState.pending_items.length() > 0,
            rx.flex(
                rx.foreach(PublishState.pending_items, _pending_tile),
                rx.cond(
                    PublishState.remaining_slots > 0,
                    _upload_widget(_add_tile_content(), compact=True),
                    rx.fragment(),
                ),
                wrap="wrap",
                gap="0.75rem",
                width="100%",
            ),
            _upload_widget(_empty_state_content(), compact=False),
        ),
        # QUA-99 UX follow-up: the element `_preview_capture_anchor`/`video_frame_
        # preview_src` (`ui/video_preview.py`) listen on for native `drop`/`change`
        # delegation — see `_GALLERY_ROOT_ID`. This wrapping box stays mounted for the
        # whole time the gallery is on screen, regardless of which `rx.cond` branch
        # above is currently showing.
        id=_GALLERY_ROOT_ID,
        width="100%",
    )


def _status_block() -> rx.Component:
    # QUA-99 (6/6): "el video" (singular) only makes sense while exactly one file is
    # selected. `pending_items` is still populated during "staging_and_starting" (it is
    # only released once staging actually succeeds, `publishing_state.py`), so it is a
    # correct read here — unlike during "polling", where it has already been cleared,
    # which is exactly why the polling arm below reads `carousel_stage_label` instead
    # (server-tracked via `_is_carousel`, QUA-99 UX follow-up) rather than this Var.
    is_carousel = PublishState.pending_items.length() > 1
    return rx.match(
        PublishState.phase,
        (
            "staging_and_starting",
            callout(
                rx.hstack(
                    loading_spinner("sm"),
                    rx.cond(
                        is_carousel,
                        rx.text(
                            "Subiendo el contenido y arrancando la publicación del carrusel...",
                            size="2",
                        ),
                        rx.text("Subiendo el video y arrancando la publicación...", size="2"),
                    ),
                    spacing="2",
                    align="center",
                ),
                "neutral",
                icon="upload",
            ),
        ),
        (
            "polling",
            callout(
                rx.vstack(
                    rx.hstack(
                        loading_spinner("sm"),
                        # QUA-99 UX follow-up: `carousel_stage_label` is only non-empty
                        # for a carousel attempt that has already taken its first poll
                        # tick — everything else (a single video, or the first tick
                        # before any child status has been read yet) falls back to the
                        # original generic message, never a blank line.
                        rx.cond(
                            PublishState.carousel_stage_label != "",
                            rx.text(PublishState.carousel_stage_label, size="2", weight="medium"),
                            rx.text(
                                "Publicando, esperando que Instagram lo confirme...",
                                size="2",
                                weight="medium",
                            ),
                        ),
                        rx.cond(
                            PublishState.elapsed_label != "",
                            rx.text(
                                PublishState.elapsed_label,
                                size="1",
                                color=T.TEXT_FAINT,
                                class_name="q-mono q-nums",
                            ),
                            rx.fragment(),
                        ),
                        spacing="2",
                        align="center",
                        width="100%",
                    ),
                    rx.text(_WAIT_EXPLANATION, size="1", color=T.TEXT_MUTED),
                    spacing="1",
                    align_items="start",
                    width="100%",
                ),
                "warn",
                icon="clock",
            ),
        ),
        # "success" has no arm: since PUBLICAR-4 the page replaces the whole assistant
        # with a persistent «listo» and the next step (`_done_panel`, N3); the toast
        # fired from `publishing_state.py` is only an extra.
        ("failure", callout(PublishState.error, "error")),
        rx.fragment(),
    )


# ---------------------------------------------------------------------------
# PUBLICAR-4: the three steps, the «listo» and the ideas behind a link.


def _is_stories() -> rx.Var[bool]:
    return PublishHubState.active_flow == FLOW_STORIES


def _busy() -> rx.Var[bool]:
    """A publish is in flight in either machine — nothing moves then."""
    return ~PublishState.can_edit_gallery | ~StoriesState.can_edit_gallery


def _file_count() -> rx.Var[int]:
    return PublishState.pending_items.length()


def _step_counter() -> rx.Component:
    """«Paso N de 3» above the page title — same eyebrow treatment the Brand Kit
    wizard passes to `page_header(kicker=…)`."""
    return rx.text(
        "Paso ",
        PublishHubState.step,
        f" de {TOTAL_STEPS}",
        size="1",
        weight="bold",
        color=T.TEXT_MUTED,
        letter_spacing="0.08em",
        text_transform="uppercase",
    )


def _step_panel(step: int, *children: rx.Component) -> rx.Component:
    """One step's content. Hidden — never unmounted — while another step shows, so
    going back finds every file, thumbnail and word where the owner left it (N6)."""
    return rx.vstack(
        rx.heading(STEP_TITLES[step], size="4", as_="h2"),
        *children,
        spacing="4",
        width="100%",
        align_items="stretch",
        display=rx.cond(PublishHubState.step == step, "flex", "none"),
    )


def _back_button() -> rx.Component:
    return rx.button(
        rx.icon("chevron-left", size=T.ICON_SM),
        "Atrás",
        on_click=PublishHubState.go_back,
        disabled=_busy(),
        variant="soft",
        color_scheme="gray",
        size="3",
        min_height=_TARGET,
    )


def _next_button(enabled: rx.Var[bool]) -> rx.Component:
    return rx.button(
        "Seguir",
        rx.icon("chevron-right", size=T.ICON_SM),
        on_click=PublishHubState.go_next,
        disabled=~enabled,
        size="3",
        min_height=_TARGET,
        flex_grow="1",
    )


def _step_footer(*buttons: rx.Component) -> rx.Component:
    return rx.hstack(*buttons, spacing="3", width="100%", align="center")


# -- ① ¿Qué vas a publicar? -------------------------------------------------


def _what_step() -> rx.Component:
    return _step_panel(
        STEP_WHAT,
        _gallery_zone(),
        rx.cond(
            _file_count() > 1,
            rx.text(
                "Con dos o más, salen juntas en una sola publicación que se desliza "
                "(carrusel), en este orden.",
                size="2",
                color=T.TEXT_MUTED,
            ),
            rx.fragment(),
        ),
        _step_footer(_next_button(_file_count() > 0)),
    )


# -- ② ¿Dónde sale? ---------------------------------------------------------


def _kind_choice(
    flow: str, icon: str, title: str, description: rx.Component, *, disabled: rx.Var[bool]
) -> rx.Component:
    selected = PublishHubState.active_flow == flow
    return choice_card(
        rx.hstack(
            rx.icon(icon, size=T.ICON_MD, color=T.tone_color("accent", 9)),
            rx.vstack(
                rx.text(title, size="3", weight="medium"),
                description,
                spacing="1",
                align_items="start",
            ),
            rx.spacer(),
            rx.cond(selected, choice_card_check(), rx.fragment()),
            spacing="3",
            align="start",
            width="100%",
        ),
        selected=selected,
        on_select=PublishHubState.select_flow(flow),
        disabled=disabled,
        width="100%",
        min_height=_TARGET,
        text_align="left",
    )


def _kind_choices() -> rx.Component:
    story_blocked = _file_count() != 1
    return rx.vstack(
        _kind_choice(
            FLOW_POSTS,
            "layout-grid",
            "Publicación en tu perfil",
            rx.text("Queda en tu perfil, con su texto.", size="2", color=T.TEXT_MUTED),
            disabled=_busy(),
        ),
        _kind_choice(
            FLOW_STORIES,
            "circle-dashed",
            "Historia (24 h)",
            rx.cond(
                story_blocked,
                rx.text(STORY_NEEDS_ONE_FILE, size="2", color=T.TEXT_MUTED),
                rx.text("Se ve durante 24 horas y luego desaparece.", size="2", color=T.TEXT_MUTED),
            ),
            disabled=_busy() | story_blocked,
        ),
        spacing="3",
        width="100%",
        role="radiogroup",
        aria_label="Cómo sale",
    )


def _no_accounts() -> rx.Component:
    return empty_state(
        "link",
        "Aún no tienes una cuenta conectada",
        "Conecta tu Instagram en Tus redes y vuelve aquí para publicar.",
        action=rx.link(
            rx.button("Conectar mi cuenta", size="3", min_height=_TARGET),
            href="/connections",
        ),
    )


def _account_picker() -> rx.Component:
    return rx.cond(
        PublishState.load_error != "",
        callout(PublishState.load_error, "error"),
        rx.cond(
            PublishState.is_loading_connections,
            rx.hstack(
                loading_spinner("sm"),
                rx.text("Buscando tus cuentas...", size="2", color=T.TEXT_MUTED),
                spacing="2",
                align="center",
            ),
            rx.cond(
                PublishState.connections.length() > 0,
                section(
                    "Cuenta",
                    _connection_selector(),
                    description="Dónde sale lo que elegiste.",
                ),
                _no_accounts(),
            ),
        ),
    )


def _where_step() -> rx.Component:
    can_continue = (PublishState.selected_connection_id != "") & (
        ~_is_stories() | (_file_count() == 1)
    )
    return _step_panel(
        STEP_WHERE,
        _kind_choices(),
        _account_picker(),
        _step_footer(_back_button(), _next_button(can_continue)),
    )


# -- ③ Revisa y publica -----------------------------------------------------


def _review_thumb(item: PendingItemVM) -> rx.Component:
    preview_src = video_frame_preview_src(root_id=_GALLERY_ROOT_ID, filename=item.filename)
    return rx.box(
        rx.cond(
            preview_src != "",
            rx.el.img(src=preview_src, alt=item.filename, class_name="q-pub-tile-img"),
            rx.center(
                rx.cond(
                    item.kind == "image",
                    rx.icon("image", size=20, color=T.tone_color("ok", 9)),
                    rx.icon("film", size=20, color=T.tone_color("ok", 9)),
                ),
                height="100%",
            ),
        ),
        class_name="q-pub-tile",
        style={"--q-dropzone-tile": "4.5rem"},
    )


def _review_summary() -> rx.Component:
    return rx.vstack(
        rx.flex(
            rx.foreach(PublishState.pending_items, _review_thumb),
            wrap="wrap",
            gap="0.5rem",
            width="100%",
        ),
        rx.hstack(
            rx.icon("send", size=T.ICON_SM, color=T.tone_color("accent", 9)),
            rx.text(
                rx.cond(
                    _is_stories(),
                    PublishState.review_story_sentence,
                    PublishState.review_post_sentence,
                ),
                size="3",
                weight="medium",
            ),
            spacing="2",
            align="start",
        ),
        spacing="3",
        width="100%",
    )


def _caption_field() -> rx.Component:
    return section(
        "Texto de la publicación (opcional)",
        rx.text_area(
            placeholder="Ej.: Hoy combo vecino a mitad de precio hasta las 9 p. m.",
            value=PublishState.caption,
            on_change=PublishState.set_caption,
            rows="4",
            size="3",
            width="100%",
            disabled=_busy(),
        ),
        description="Sale tal como lo escribas.",
    )


def _publish_button() -> rx.Component:
    ready = rx.cond(
        _is_stories(),
        (_file_count() == 1) & (PublishState.selected_connection_id != ""),
        PublishState.can_publish,
    )
    return rx.button(
        rx.icon("send", size=18),
        "Publicar",
        on_click=PublishHubState.publish_now,
        disabled=_busy() | ~ready,
        size="4",
        width="100%",
        min_height=_TARGET,
    )


def _review_step() -> rx.Component:
    return _step_panel(
        STEP_REVIEW,
        _review_summary(),
        rx.cond(
            _is_stories(),
            share_to_instagram_button(root_id=_GALLERY_ROOT_ID, enabled=_file_count() == 1),
            _caption_field(),
        ),
        _publish_button(),
        rx.cond(_is_stories(), stories_status_block(), _status_block()),
        _step_footer(_back_button()),
    )


def _assistant_card() -> rx.Component:
    return card(
        rx.vstack(
            _what_step(),
            _where_step(),
            _review_step(),
            spacing="5",
            width="100%",
            align_items="stretch",
        ),
        padding="1.5rem",
    )


# -- the «listo» (N3) and the ideas ------------------------------------------


def _is_done() -> rx.Var[bool]:
    return rx.cond(_is_stories(), StoriesState.phase == "success", PublishState.phase == "success")


def _done_panel() -> rx.Component:
    """Persistent, not a toast: what happened and the next step — one solid button
    to the next job, one soft to start again (N3)."""
    return callout(
        rx.vstack(
            rx.text(PublishHubState.done_text, size="3", weight="medium"),
            rx.flex(
                rx.link(
                    rx.button("Ver mi semana", size="3", width="100%", min_height=_TARGET),
                    href="/planner",
                    width="100%",
                ),
                rx.button(
                    "Publicar otra",
                    on_click=PublishHubState.start_over,
                    variant="soft",
                    size="3",
                    width="100%",
                    min_height=_TARGET,
                ),
                direction=rx.breakpoints(initial="column", sm="row"),
                gap="0.75rem",
                width="100%",
            ),
            spacing="3",
            width="100%",
            align_items="stretch",
        ),
        "ok",
        icon="circle-check",
    )


def _ideas() -> rx.Component:
    return rx.vstack(
        rx.button(
            rx.icon("lightbulb", size=T.ICON_SM),
            "Ideas para tu próxima publicación",
            rx.cond(
                PublishHubState.show_ideas,
                rx.icon("chevron-up", size=T.ICON_SM),
                rx.icon("chevron-down", size=T.ICON_SM),
            ),
            on_click=PublishHubState.toggle_ideas,
            variant="ghost",
            size="3",
            min_height=_TARGET,
            aria_expanded=rx.cond(PublishHubState.show_ideas, "true", "false"),
        ),
        rx.cond(PublishHubState.show_ideas, trending_card(), rx.fragment()),
        spacing="3",
        width="100%",
        align_items="start",
    )


def publish_topbar() -> rx.Component:
    return page_header(
        "Publicar ahora",
        "Sube una foto o un video de tu teléfono y publícalo en tu Instagram.",
        kicker=rx.cond(_is_done(), rx.fragment(), _step_counter()),
    )


def publish_index() -> rx.Component:
    main = rx.vstack(
        rx.cond(_is_done(), _done_panel(), _assistant_card()),
        _ideas(),
        spacing="5",
        width="100%",
        max_width="40rem",
        align_items="stretch",
    )
    return app_shell(publish_topbar(), page_body(main))

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

**QUA-103** added a single JPEG image as a first-class selection alongside video — the
`accept` dropzone, the thumbnail strategy per tile (`PendingItemVM.kind`), and the copy
below all know about both kinds now. A carousel (2-10 items) is still VIDEO-ONLY: the
gallery lets a JPEG sit alone, but `PublishState`'s own guard refuses to combine an image
with anything else — see `publishing_state.py`'s `_IMAGE_CAROUSEL_NOT_SUPPORTED`.
"""

from __future__ import annotations

import reflex as rx

from .publishing_state import _MAX_ITEMS, _UPLOAD_ID, _WAIT_EXPLANATION, PublishState
from .publishing_vm import ConnectionOptionVM, PendingItemVM
from .ui import app_shell, callout, card, page_body, page_header, section
from .ui import tokens as T
from .ui.image_preview import gallery_image_preview_capture_anchor
from .ui.video_preview import gallery_preview_capture_anchor, video_frame_preview_src

# Gallery redesign, part 2 (QUA-99 UX follow-up) — a stable DOM id `video_preview.py`
# listens on (native `drop`/`change` delegation) to find each tile's own `File` for its
# real thumbnail. Lives here, not there, for the same reason `_UPLOAD_ID` does: this
# module owns the actual DOM structure, `video_preview.py` stays a plain generic helper
# with no knowledge of this specific screen's layout.
_GALLERY_ROOT_ID = "publish-gallery-root"


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


def _connection_section() -> rx.Component:
    return section(
        "Cuenta",
        _connection_selector(),
        description="La cuenta de Instagram conectada donde se publicará este contenido.",
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
    preview_src = video_frame_preview_src(filename=item.filename)
    return rx.box(
        rx.cond(
            preview_src != "",
            rx.el.img(
                src=preview_src,
                alt=item.filename,
                style={
                    "width": "100%",
                    "height": "100%",
                    "object_fit": "cover",
                    "display": "block",
                },
            ),
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
        rx.badge(
            index + 1,
            color_scheme="gray",
            variant="solid",
            size="1",
            position="absolute",
            top="0.3rem",
            left="0.3rem",
        ),
        rx.button(
            rx.icon("x", size=14, color="white"),
            on_click=PublishState.remove_pending_file(index),
            disabled=~PublishState.can_edit_gallery,
            title="Quitar este archivo",
            size="1",
            variant="solid",
            color_scheme="tomato",
            radius="full",
            position="absolute",
            top="0.25rem",
            right="0.25rem",
            width="1.6rem",
            height="1.6rem",
            padding="0",
            # A thumbnail can be almost any color underneath this — the white ring plus
            # a drop shadow is what keeps the X readable regardless (a plain solid red
            # circle alone was reported hard to notice against a busy first frame).
            border=f"2px solid {T.CARD_BG}",
            box_shadow="0 1px 3px rgba(0, 0, 0, 0.35)",
            cursor="pointer",
            _hover={"background": rx.color("tomato", 10)},
        ),
        position="relative",
        width="6.5rem",
        height="6.5rem",
        overflow="hidden",  # keeps the thumbnail's object-fit:cover inside the rounded tile
        border=f"1.5px solid {rx.color('grass', 7)}",
        border_radius=T.RADIUS_CARD,
        background=T.tone_color("ok", 2),
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
    return rx.upload(
        children,
        id=_UPLOAD_ID,
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
        on_drop_rejected=rx.toast.error(
            "Formato no permitido",
            description=f"Solo se aceptan archivos MP4, MOV o JPEG, hasta {_MAX_ITEMS} en total.",
        ),
        border=f"1.5px dashed {rx.color('gray', 7)}",
        border_radius=T.RADIUS_CARD,
        background=T.CARD_BG,
        width="6.5rem" if compact else "100%",
        height="6.5rem" if compact else "auto",
        padding="0" if compact else "2.5rem 1.5rem",
        display="flex",
        align_items="center",
        justify_content="center",
        transition=f"border-color {T.DUR_FAST} {T.EASE}, background {T.DUR_FAST} {T.EASE}",
        _hover={
            "border_color": rx.color("accent", 8),
            "background": T.tone_color("accent", 2),
        },
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
        rx.icon("film", size=32, color=T.TEXT_FAINT),
        rx.text(
            "Arrastra tu contenido aquí o haz clic para elegirlo",
            size="3",
            weight="medium",
        ),
        rx.text(
            f"MP4, MOV o JPEG · hasta 300 MB (video) / 8 MB (imagen) · hasta {_MAX_ITEMS} archivos",
            size="1",
            color=T.TEXT_MUTED,
        ),
        spacing="2",
        align="center",
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


def _content_section() -> rx.Component:
    return section(
        "Contenido",
        _gallery_zone(),
        description="Lo que se publicará en la cuenta elegida arriba.",
    )


def _caption_section() -> rx.Component:
    return section(
        "Caption",
        rx.text_area(
            placeholder="Escribe el caption...",
            value=PublishState.caption,
            on_change=PublishState.set_caption,
            rows="5",
            size="3",
            width="100%",
        ),
        description="Se publicará exactamente como lo escribas.",
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
            rx.callout(
                rx.hstack(
                    rx.spinner(size="2"),
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
                color_scheme="gray",
                width="100%",
            ),
        ),
        (
            "polling",
            rx.callout(
                rx.vstack(
                    rx.hstack(
                        rx.spinner(size="2"),
                        # QUA-99 UX follow-up: `carousel_stage_label` is only non-empty
                        # for a carousel attempt that has already taken its first poll
                        # tick — everything else (a single video, or the first tick
                        # before any child status has been read yet) falls back to the
                        # original generic message, never a blank line.
                        rx.cond(
                            PublishState.carousel_stage_label != "",
                            rx.text(PublishState.carousel_stage_label, size="2", weight="medium"),
                            rx.text(
                                "Publicando, esperando confirmación de Meta...",
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
                                font_family="monospace",
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
                icon="clock",
                color_scheme="amber",
                width="100%",
            ),
        ),
        # QUA-98: "success" has no inline arm on purpose — the confirmation moved to a
        # transient `rx.toast.success` fired from `publishing_state.py` (same convention
        # `inbox_state.py` already established: success = toast, error = persistent
        # callout below, unchanged). Falls through to the catch-all `rx.fragment()`.
        (
            "failure",
            rx.callout(
                PublishState.error,
                icon="triangle-alert",
                color_scheme="tomato",
                width="100%",
            ),
        ),
        rx.fragment(),
    )


def _publish_button() -> rx.Component:
    return rx.button(
        rx.icon("send", size=18),
        "Publicar",
        # QUA-99 UX follow-up: `add_files` already buffered everything the gallery holds
        # into `PublishState._pending_files`/`pending_items` — `publish()` no longer
        # receives the upload directly, so this no longer passes `rx.upload_files(...)`.
        on_click=PublishState.publish(),
        disabled=~PublishState.can_publish,
        size="4",
        width="100%",
    )


def _form_card() -> rx.Component:
    return card(
        rx.vstack(
            _connection_section(),
            rx.divider(),
            _content_section(),
            rx.divider(),
            _caption_section(),
            rx.divider(),
            rx.vstack(
                _publish_button(),
                _status_block(),
                spacing="3",
                width="100%",
                align_items="stretch",
            ),
            spacing="5",
            align_items="stretch",
            width="100%",
        ),
        padding="2rem",
    )


def _tip_row(icon: str, text: str) -> rx.Component:
    return rx.hstack(
        rx.icon(icon, size=T.ICON_SM, color=T.TEXT_FAINT),
        rx.text(text, size="2", color=T.TEXT_MUTED),
        spacing="2",
        align="start",
    )


def _tips_card() -> rx.Component:
    """Static, informational only — every fact here mirrors an existing constraint
    already enforced by `PublishState`/`_gallery_zone` (accepted formats, size limit,
    polling behavior), not a new claim about functionality."""
    return card(
        rx.vstack(
            rx.hstack(
                rx.icon("info", size=T.ICON_MD, color=T.tone_color("info", 9)),
                rx.heading("Antes de publicar", size="3", as_="h2"),
                spacing="2",
                align="center",
            ),
            rx.vstack(
                _tip_row("film", "Formatos aceptados: MP4, MOV (video) y JPEG (imagen)."),
                _tip_row("scale", "Tamaño máximo: 300 MB por video, 8 MB por imagen."),
                _tip_row(
                    "layers",
                    f"Hasta {_MAX_ITEMS} videos — 2 o más se publican juntos, como un "
                    "carrusel. Una imagen se publica sola por ahora.",
                ),
                _tip_row("at-sign", "Se publica en la cuenta que elijas arriba."),
                _tip_row("clock", "La confirmación de Meta puede tardar unos minutos."),
                spacing="3",
                align_items="start",
                width="100%",
            ),
            spacing="4",
            align_items="start",
            width="100%",
        ),
        padding="1.5rem",
    )


def _form() -> rx.Component:
    return rx.flex(
        rx.box(_form_card(), flex="2 1 480px", min_width="0", width="100%"),
        rx.box(_tips_card(), flex="1 1 280px", min_width="0", width="100%"),
        spacing="5",
        width="100%",
        wrap="wrap",
        align_items="start",
    )


def _load_error() -> rx.Component:
    return callout(PublishState.load_error, "error")


def publish_topbar() -> rx.Component:
    return page_header(
        "Publicar",
        "Sube una imagen o uno o varios reels y publícalos en una de tus cuentas de "
        "Instagram conectadas — 2 o más videos se publican juntos, como un carrusel",
    )


def publish_index() -> rx.Component:
    return app_shell(
        publish_topbar(),
        page_body(rx.cond(PublishState.load_error != "", _load_error(), _form())),
    )

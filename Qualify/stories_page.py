"""The Stories publish flow (QUA-106 V1 redesign) — since QUA-113 Fase 2 it is the
second flow INSIDE `/publish` (`publishing_page.publish_index` mounts
`stories_flow` when `PublishHubState.active_flow == "stories"`), no longer a screen of
its own; `/stories` redirects to `/publish?flow=stories`. The flow itself is
unchanged: pick a connected account,
select one video (real thumbnail in the grid, reusing `ui/video_preview.py` exactly
as `/publish` does), hit "Publicar", poll until Meta settles. A panel of trending
content/audio (QUA-107 + Meta's `GET /ig_audio`) sits alongside the form, purely for
reference — no field here ever reaches the publish call. Since QUA-113 that panel is
`trending_panel.trending_card` (state: `TrendingState`), shared with any publish flow.

No propuesta, no aprobación, no revisión, no historial: there is no second screen.
"""

from __future__ import annotations

import reflex as rx

from .publish_tips import tip_row, tips_card
from .stories_state import _UPLOAD_ID, StoriesState
from .ui import callout, card, section
from .ui import tokens as T
from .ui.image_preview import gallery_image_preview_capture_anchor
from .ui.video_preview import (
    gallery_file_js,
    gallery_preview_capture_anchor,
    video_frame_preview_src,
)

_GALLERY_ROOT_ID = "stories-gallery-root"

# ---------------------------------------------------------------------------
# "Abrir en Instagram" -- Web Share API handoff (PoC validated on real
# Android + iPhone devices: `navigator.share` with the video File opens
# Instagram's own Story composer with the video pre-loaded and the Music
# sticker fully available). An ALTERNATIVE to "Publicar", never a step of it:
# Meta's Graph API cannot attach a native Music sticker to a Story
# (`audio_configuration` only ever applies to Reels), so this hands the video
# to the phone's OS share sheet instead, and the user finishes the post
# themselves inside Instagram. No connected account is needed for this path
# — it never touches Meta's Graph API.
#
# The video File itself never round-trips through Reflex state or the
# server: `ui/video_preview.py`'s existing drop/change capture listener
# (already mounted for the real-thumbnail feature) stashes the raw File per
# gallery root, and this script reads the slot of THIS gallery
# (`_GALLERY_ROOT_ID`) via `gallery_file_js` — never a page-global "last file",
# so a video dropped in another gallery on the same page (the Publicaciones
# flow, QUA-113) can never be the one shared. A Story is never a carousel, so
# the last file dropped on this root is always the one currently in it.
_SHARE_TO_INSTAGRAM_SCRIPT = """
(function () {
  try {
    // Desktop OS share panels (Windows' "Compartir", macOS' share sheet) may list
    // "Instagram" too, but Instagram there is web/desktop -- it never registers
    // itself to actually RECEIVE the shared file into a Story composer the way the
    // real Instagram mobile app does. Selecting it just drops the user on a plain
    // "select a story" screen with nothing attached (reported 2026-09-23 testing
    // from a Windows PC). Gating on the OS keeps that dead-end out of reach.
    var isMobileOS = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent || "");
    if (!isMobileOS) { return "desktop"; }
    if (!window.isSecureContext) { return "insecure"; }
    if (!navigator.share || !navigator.canShare) { return "unsupported"; }
    var file = __STORIES_GALLERY_FILE__;
    if (!file) { return "no_file"; }
    if (!navigator.canShare({ files: [file] })) { return "cannot_share_file"; }
    return navigator.share({ files: [file] }).then(
      function () { return "shared"; },
      function (err) {
        if (err && err.name === "AbortError") { return "cancelled"; }
        return "error:" + (err && err.message ? err.message : String(err));
      }
    );
  } catch (e) {
    return "error:" + (e && e.message ? e.message : String(e));
  }
})()
""".replace("__STORIES_GALLERY_FILE__", gallery_file_js(_GALLERY_ROOT_ID))


def _connection_item(conn) -> rx.Component:
    return rx.select.item(conn.external_username + " · " + conn.platform, value=conn.id)


def _connection_selector() -> rx.Component:
    return rx.select.root(
        rx.select.trigger(placeholder="Elige una cuenta conectada", width="100%"),
        rx.select.content(rx.foreach(StoriesState.connections, _connection_item)),
        value=StoriesState.selected_connection_id,
        on_change=StoriesState.select_connection,
        size="3",
        width="100%",
    )


def _connection_section() -> rx.Component:
    return section(
        "Cuenta",
        _connection_selector(),
        description="La cuenta de Instagram conectada donde se publicará la Story.",
    )


# ---------------------------------------------------------------------------
# Content gallery — one tile, real video-frame thumbnail (reused from /publish's
# `ui/video_preview.py`, unchanged), no "+" add tile since a Story is never a
# carousel: a second drop simply REPLACES the first (`StoriesState.add_file`).


def _pending_tile() -> rx.Component:
    """The one selected video or JPEG (QUA-113), shown with a REAL thumbnail — same
    mechanism `publishing_page._pending_tile` uses (`video_frame_preview_src` is the
    one generic reader for both kinds), falling back to a film/image icon + filename
    while nothing has been captured yet or never could be."""
    preview_src = video_frame_preview_src(
        root_id=_GALLERY_ROOT_ID, filename=StoriesState.pending_filename
    )
    return rx.box(
        rx.cond(
            preview_src != "",
            rx.el.img(
                src=preview_src,
                alt=StoriesState.pending_filename,
                style={
                    "width": "100%",
                    "height": "100%",
                    "object_fit": "cover",
                    "display": "block",
                },
            ),
            rx.vstack(
                rx.cond(
                    StoriesState.pending_is_image,
                    rx.icon("image", size=24, color=T.tone_color("ok", 9)),
                    rx.icon("film", size=24, color=T.tone_color("ok", 9)),
                ),
                rx.text(
                    StoriesState.pending_filename,
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
        rx.button(
            rx.icon("x", size=14, color="white"),
            on_click=StoriesState.clear_file,
            disabled=~StoriesState.can_edit_gallery,
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
            border=f"2px solid {T.CARD_BG}",
            box_shadow="0 1px 3px rgba(0, 0, 0, 0.35)",
            cursor="pointer",
            _hover={"background": rx.color("tomato", 10)},
        ),
        position="relative",
        width="8rem",
        height="8rem",
        overflow="hidden",
        border=f"1.5px solid {rx.color('grass', 7)}",
        border_radius=T.RADIUS_CARD,
        background=T.tone_color("ok", 2),
    )


def _empty_state_content() -> rx.Component:
    return rx.vstack(
        rx.icon("film", size=32, color=T.TEXT_FAINT),
        rx.text(
            "Arrastra el video o la imagen de la Story aquí o haz clic para elegirlo",
            size="3",
            weight="medium",
        ),
        rx.text(
            "MP4, MOV o JPEG · hasta 300 MB (video) / 8 MB (imagen)",
            size="1",
            color=T.TEXT_MUTED,
        ),
        spacing="2",
        align="center",
    )


def _upload_widget(children: rx.Component, *, compact: bool) -> rx.Component:
    return rx.upload(
        children,
        id=_UPLOAD_ID,
        accept={
            "video/mp4": [".mp4"],
            "video/quicktime": [".mov"],
            "image/jpeg": [".jpg", ".jpeg"],
        },
        multiple=False,
        max_files=1,
        disabled=~StoriesState.can_edit_gallery,
        on_drop=StoriesState.add_file,
        on_drop_rejected=rx.toast.error(
            "Formato no permitido", description="Solo se aceptan archivos MP4, MOV o JPEG."
        ),
        border=f"1.5px dashed {rx.color('gray', 7)}",
        border_radius=T.RADIUS_CARD,
        background=T.CARD_BG,
        width="8rem" if compact else "100%",
        height="8rem" if compact else "auto",
        padding="0" if compact else "2.5rem 1.5rem",
        display="flex",
        align_items="center",
        justify_content="center",
        transition=f"border-color {T.DUR_FAST} {T.EASE}, background {T.DUR_FAST} {T.EASE}",
        _hover={"border_color": rx.color("accent", 8), "background": T.tone_color("accent", 2)},
    )


def _preview_capture_anchor() -> rx.Component:
    """Mounted UNCONDITIONALLY — see `publishing_page._preview_capture_anchor`'s
    docstring for why: without this, a video dropped while the empty-state prompt is
    still showing (always true for the FIRST file) never gets a real thumbnail. Both
    anchors, as on `/publish`: video frames and (QUA-113) JPEG images."""
    return rx.box(
        gallery_preview_capture_anchor(root_id=_GALLERY_ROOT_ID),
        gallery_image_preview_capture_anchor(root_id=_GALLERY_ROOT_ID),
        display="none",
    )


def _gallery_zone() -> rx.Component:
    return rx.box(
        _preview_capture_anchor(),
        rx.cond(
            StoriesState.pending_filename != "",
            rx.flex(_pending_tile(), wrap="wrap", gap="0.75rem", width="100%"),
            _upload_widget(_empty_state_content(), compact=False),
        ),
        id=_GALLERY_ROOT_ID,
        width="100%",
    )


def _content_section() -> rx.Component:
    return section(
        "Contenido de la Story",
        _gallery_zone(),
        description=(
            "Tu propio video o imagen — nunca se genera ni se reutiliza contenido de terceros."
        ),
    )


# ---------------------------------------------------------------------------
# Publish form + status — same shape `publishing_page.py` uses for `/publish`.


def _status_block() -> rx.Component:
    return rx.match(
        StoriesState.phase,
        (
            "staging_and_starting",
            rx.callout(
                rx.hstack(
                    rx.spinner(size="2"),
                    rx.text("Subiendo el video y arrancando la publicación...", size="2"),
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
                        rx.text(
                            "Publicando, esperando confirmación de Meta...",
                            size="2",
                            weight="medium",
                        ),
                        rx.cond(
                            StoriesState.elapsed_label != "",
                            rx.text(
                                StoriesState.elapsed_label,
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
                    rx.text(
                        "Meta está procesando la Story. Esto puede tardar varios minutos.",
                        size="1",
                        color=T.TEXT_MUTED,
                    ),
                    spacing="1",
                    align_items="start",
                    width="100%",
                ),
                icon="clock",
                color_scheme="amber",
                width="100%",
            ),
        ),
        (
            "failure",
            rx.callout(
                StoriesState.error, icon="triangle-alert", color_scheme="tomato", width="100%"
            ),
        ),
        rx.fragment(),
    )


def _publish_button() -> rx.Component:
    return rx.button(
        rx.icon("send", size=16),
        "Publicar",
        on_click=StoriesState.publish(),
        disabled=~StoriesState.can_publish,
        size="3",
        width="100%",
    )


def _share_to_instagram_button() -> rx.Component:
    """Alternative to `_publish_button` — see the module-level comment above
    `_SHARE_TO_INSTAGRAM_SCRIPT` for why this exists and what it does. Gated only
    on having a video selected: unlike "Publicar", it needs no connected account."""
    return rx.button(
        rx.icon("share-2", size=16),
        "Abrir en Instagram",
        on_click=rx.call_script(
            _SHARE_TO_INSTAGRAM_SCRIPT, callback=StoriesState.handle_share_result
        ),
        disabled=StoriesState.pending_filename == "",
        variant="soft",
        size="3",
        width="100%",
    )


def _form_card(header: rx.Component) -> rx.Component:
    return card(
        rx.vstack(
            header,
            rx.divider(),
            _connection_section(),
            rx.divider(),
            _content_section(),
            rx.divider(),
            rx.vstack(
                _publish_button(),
                rx.hstack(
                    rx.divider(flex_grow="1"),
                    rx.text("o", size="1", color=T.TEXT_FAINT),
                    rx.divider(flex_grow="1"),
                    align="center",
                    width="100%",
                    spacing="2",
                ),
                _share_to_instagram_button(),
                rx.text(
                    "Te permite seleccionar música oficial y personalizar tu historia "
                    "desde la app.",
                    size="1",
                    color=T.TEXT_FAINT,
                ),
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


def _connections_error() -> rx.Component:
    return callout(StoriesState.connections_error, tone="error")


def stories_tips_card() -> rx.Component:
    """The Stories counterpart of Publicaciones' "Antes de publicar" block (QUA-113) —
    same shell, Stories' own facts. Each row mirrors a constraint this flow already
    enforces: MP4/MOV video or JPEG image (`_resolve_story_media`), the 300 MB video /
    8 MB image limits (`_TOO_LARGE` / `_IMAGE_TOO_LARGE`), one file that a new drop
    replaces (`add_file`), no caption (`publish_background` always sends
    `caption=""`), the account picked above, Meta's confirmation wait, and the
    "Abrir en Instagram" phone handoff for official music."""
    return tips_card(
        tip_row("film", "Formatos aceptados: MP4, MOV (video) y JPEG (imagen)."),
        tip_row("scale", "Tamaño máximo: 300 MB por video, 8 MB por imagen."),
        tip_row("square", "Una pieza por Story: si eliges otra, reemplaza a la anterior."),
        tip_row("type", "Sin caption: Instagram no muestra texto en una Story publicada así."),
        tip_row("at-sign", "Se publica en la cuenta que elijas arriba."),
        tip_row("clock", "La confirmación de Meta puede tardar unos minutos."),
        tip_row(
            "music",
            "¿Música oficial? Usa «Abrir en Instagram» desde tu celular y termina la "
            "Story en la app.",
        ),
    )


def stories_flow(header: rx.Component) -> rx.Component:
    """The whole Stories flow as `/publish` mounts it — `header` is the flow selector,
    shown at the top of the form card (QUA-113). The accounts-load error stays above
    the card, where `/stories` used to show it. Its "Antes de publicar" block is
    `stories_tips_card`, placed by the page in the same column Publicaciones' uses."""
    return rx.vstack(
        rx.cond(StoriesState.connections_error != "", _connections_error(), rx.fragment()),
        _form_card(header),
        spacing="5",
        width="100%",
        align_items="stretch",
    )

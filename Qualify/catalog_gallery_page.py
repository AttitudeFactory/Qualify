"""«Fotos y videos de tu negocio» — the section of Galería (/catalog) above the products
(CM-2, m-24955919; contract `docs/epica-galeria-medios-negocio.md` §5 CM-2).

Built only from the design system (`Qualify/ui`, design-system §9.1): `section` for the
block, `ui.dropzone` (``variant="bare"``) behind the one solid button «Agregar fotos o
videos» — on a phone it opens the system's chooser (camera, photos, files) and takes
several at once —, `progress_panel` with the real percentage while the bytes go up,
`callout` for refusals and notices, `media_thumb` and the catalog tile material
(`.q-catalog-tile`) for each photo or video, `loading_spinner` while a video is being
prepared, and the same «¿Quitar…?» alert dialog the product media use.

Phone first (360 px): two tiles per row, every action a word on a 44 px target,
nothing that depends on hovering. Media load through the backend's short-lived
`/r2media/<token>` paths (`post_card.viewable_src`), never the local upload store.
"""

from __future__ import annotations

import reflex as rx
from reflex_base.event import parse_args_spec, passthrough_event_spec

from .catalog_gallery_state import UPLOAD_ID, CatalogGalleryState
from .catalog_gallery_vm import (
    ADD_LABEL,
    GALLERY_DESCRIPTION,
    GALLERY_EMPTY,
    GALLERY_MEDIA_ACCEPT,
    GALLERY_TITLE,
    MAX_UPLOAD_BYTES,
    REMOVE_DESCRIPTION,
    TRIMMED_DISMISS,
    TRIMMED_TEXT,
    VIDEOS_WAITING_TEXT,
    GalleryItemVM,
)
from .catalog_vm import REMOVE_CONFIRM, REMOVE_MEDIA, REMOVE_STAY
from .post_card import viewable_src
from .ui import (
    callout,
    card,
    dropzone,
    loading_spinner,
    media_thumb,
    progress_panel,
    section,
    skeleton_rows,
    tone_badge,
)
from .ui import tokens as T

__all__ = ["gallery_dialogs", "gallery_section", "picked_files"]

G = CatalogGalleryState
_TOUCH_MIN = "44px"
_THUMB_H = "var(--q-catalog-thumb-h, 8rem)"


def _dropped_files() -> rx.Var:
    """The files `on_drop` is called with: the placeholder Reflex itself substitutes for
    the upload's `files` argument (`Upload._update_arg_tuple_for_on_drop`), built the
    same way (`parse_args_spec` of the trigger's spec), so it names the same JS value."""
    placeholders, _ = parse_args_spec(passthrough_event_spec(list[rx.UploadFile]))
    return placeholders[0]


def picked_files() -> rx.Var:
    """The names and sizes of the files just chosen, in an `on_drop` chain. Sent with
    the business upload as a bound argument (Reflex parses it before the first file
    byte, so the handler can refuse without receiving the files), and before each
    product upload to `CatalogState.check_upload_size` (Caddy's 520 MB per request)."""
    files = _dropped_files()
    return rx.Var(
        f"(({files}) ?? []).map((f) => ({{name: f.name ?? f.path ?? '', size: f.size ?? 0}}))",
        _var_type=list[dict[str, str | int]],
    )


def _add_button() -> rx.Component:
    return dropzone(
        rx.button(
            rx.cond(G.uploading, loading_spinner("sm"), rx.icon("image-plus", size=T.ICON_SM)),
            ADD_LABEL,
            size="3",
            type="button",
            min_height=_TOUCH_MIN,
            width=rx.breakpoints(initial="100%", sm="auto"),
            disabled=G.uploading | G.busy,
        ),
        upload_id=UPLOAD_ID,
        accept=GALLERY_MEDIA_ACCEPT,
        multiple=True,
        max_files=0,
        max_size=MAX_UPLOAD_BYTES,
        disabled=G.uploading | G.busy,
        on_drop=G.receive_upload(
            rx.upload_files_chunk(upload_id=UPLOAD_ID, on_upload_progress=G.upload_progress),
            picked_files(),
        ),
        on_drop_rejected=G.picker_rejected,
        variant="bare",
        width=rx.breakpoints(initial="100%", sm="auto"),
    )


def _status() -> rx.Component:
    """What is happening with the last upload, right under the button."""
    return rx.vstack(
        rx.cond(
            G.uploading,
            card(
                progress_panel(G.upload_label, value=G.upload_percent),
                padding="0 1rem",
                width="100%",
            ),
        ),
        rx.cond(G.upload_error != "", callout(G.upload_error, "error")),
        rx.cond(
            G.videos_full & ~G.uploading,
            callout(VIDEOS_WAITING_TEXT, "info"),
        ),
        rx.cond(
            G.show_trimmed,
            rx.vstack(
                callout(TRIMMED_TEXT, "info"),
                rx.button(
                    rx.icon("check", size=T.ICON_SM),
                    TRIMMED_DISMISS,
                    variant="soft",
                    color_scheme=T.tone_scale("neutral"),
                    size="2",
                    type="button",
                    min_height=_TOUCH_MIN,
                    width=rx.breakpoints(initial="100%", sm="auto"),
                    on_click=G.dismiss_trimmed,
                    disabled=G.busy,
                ),
                spacing="2",
                width="100%",
                align_items="start",
            ),
        ),
        rx.cond(G.load_error != "", callout(G.load_error, "error")),
        spacing="2",
        width="100%",
    )


def _picture(item: rx.Var[GalleryItemVM]) -> rx.Component:
    """The photo, the video (its poster until it plays, its length in a corner), or the
    frame with a glyph while a video is not ready."""
    video = rx.box(
        rx.el.video(
            src=viewable_src(item.video_url),
            poster=rx.cond(item.thumb_url != "", viewable_src(item.thumb_url), ""),
            controls=True,
            preload="none",
            plays_inline=True,
            aria_label=item.label,
            width="100%",
            height="100%",
        ),
        rx.cond(
            item.duration != "",
            rx.box(
                tone_badge(item.duration, "neutral", icon="film"),
                position="absolute",
                top="0.45rem",
                left="0.45rem",
                class_name="q-nums",
            ),
        ),
        class_name="q-catalog-video",
        position="relative",
        height=_THUMB_H,
    )
    pending = rx.box(
        media_thumb(
            "",
            has=rx.Var.create(False),
            size=None,
            width="100%",
            height=_THUMB_H,
            icon=rx.cond(item.state == "failed", "film", "clapperboard"),
        ),
        rx.cond(
            item.state == "preparing",
            rx.center(loading_spinner("md"), position="absolute", inset="0"),
        ),
        position="relative",
        width="100%",
        role="img",
        aria_label=item.label,
    )
    return rx.cond(
        (item.state == "preparing") | (item.state == "failed"),
        pending,
        rx.cond(
            item.media_type == "video",
            video,
            media_thumb(
                viewable_src(item.thumb_url),
                has=item.thumb_url != "",
                size=None,
                width="100%",
                height=_THUMB_H,
                alt=item.label,
            ),
        ),
    )


def _tile(item: rx.Var[GalleryItemVM]) -> rx.Component:
    remove = rx.button(
        rx.icon("trash-2", size=T.ICON_SM),
        REMOVE_MEDIA,
        variant="soft",
        size="2",
        type="button",
        min_height=_TOUCH_MIN,
        width="100%",
        on_click=rx.cond(
            item.state == "failed", G.dismiss(item.job_id), G.ask_remove(item.media_id)
        ),
        disabled=G.busy,
        aria_label="Quitar " + item.label,
        **T.tone_scheme("error"),
    )
    return rx.box(
        _picture(item),
        rx.vstack(
            rx.text(
                rx.cond(item.media_type == "video", "Video", "Foto"),
                rx.cond(item.duration != "", rx.text.span(" · ", item.duration), ""),
                size="1",
                color=T.TEXT_MUTED,
                class_name="q-nums",
                aria_hidden="true",
            ),
            rx.cond(
                item.note != "",
                rx.text(
                    item.note,
                    size="1",
                    color=rx.cond(
                        item.note_tone == "error", T.tone_color("error", 11), T.TEXT_MUTED
                    ),
                    role=rx.cond(item.state == "failed", "alert", "status"),
                ),
            ),
            rx.cond(item.can_remove, remove),
            class_name="q-catalog-tile-foot",
            spacing="2",
            width="100%",
            align_items="stretch",
        ),
        class_name="q-catalog-tile",
        role="listitem",
        key=item.key,
        width="100%",
        min_width="0",
    )


def _grid() -> rx.Component:
    return rx.box(
        rx.foreach(G.items, _tile),
        display="grid",
        # two per row on a 360 px phone, as many as fit on a laptop
        grid_template_columns="repeat(auto-fill, minmax(9rem, 1fr))",
        gap="0.6rem",
        width="100%",
        role="list",
        aria_label=GALLERY_TITLE,
    )


def gallery_section() -> rx.Component:
    """The section, or nothing when the business cannot have one yet (no session, no
    brand: `CatalogState` already says what to do)."""
    body = section(
        GALLERY_TITLE,
        _add_button(),
        _status(),
        rx.cond(
            G.has_items,
            _grid(),
            rx.cond(
                ~G.uploading,
                rx.text(GALLERY_EMPTY, size="2", color=T.TEXT_MUTED),
            ),
        ),
        description=GALLERY_DESCRIPTION,
    )
    return rx.cond(
        G.loaded,
        rx.cond(G.available, body),
        rx.box(skeleton_rows(2), width="100%", aria_busy="true"),
    )


def _remove_dialog() -> rx.Component:
    """«¿Quitar este video de tu Galería? Las publicaciones que ya hiciste no
    cambian.»: «Volver» first and on Esc, «Sí, quitar» as the destructive verb; stacked
    full width on a phone."""
    big = {"size": "3", "min_height": _TOUCH_MIN, "width": "100%"}
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title(G.remove_title_text),
            rx.alert_dialog.description(REMOVE_DESCRIPTION, size="2"),
            rx.box(
                rx.alert_dialog.cancel(
                    rx.button(
                        rx.icon("arrow-left", size=T.ICON_SM),
                        REMOVE_STAY,
                        variant="soft",
                        color_scheme=T.tone_scale("neutral"),
                        type="button",
                        **big,
                    ),
                ),
                rx.alert_dialog.action(
                    rx.button(
                        rx.icon("trash-2", size=T.ICON_SM),
                        REMOVE_CONFIRM,
                        type="button",
                        on_click=G.confirm_remove,
                        **T.tone_scheme("error"),
                        **big,
                    ),
                ),
                display="grid",
                grid_template_columns=rx.breakpoints(
                    initial="minmax(0, 1fr)", sm="repeat(2, minmax(0, 1fr))"
                ),
                gap="0.75rem",
                margin_top="1.25rem",
                width="100%",
            ),
            max_width="28rem",
        ),
        open=G.remove_open,
        on_open_change=G.set_remove_open,
    )


def gallery_dialogs() -> rx.Component:
    """The section's dialogs, mounted once at page level (outside any `rx.cond`)."""
    return _remove_dialog()

"""«Fotos y videos de tu negocio» — the section of Galería (/catalog) above the products
(CM-2, m-24955919; contract `docs/epica-galeria-medios-negocio.md` §5 CM-2).

Built only from the design system (`Qualify/ui`, design-system §9.1): `section` for the
block, `ui.dropzone` (``variant="bare"``) behind the one solid button «Agregar fotos o
videos» — on a phone it opens the system's chooser (camera, photos, files) and takes
several at once —, `progress_panel` with the real percentage while the bytes go up,
`callout` for refusals and notices, `media_thumb` and the catalog tile material
(`.q-catalog-tile`) for each photo or video, `loading_spinner` while a video is being
prepared, and the same «¿Quitar…?» alert dialog the product media use.

m-24976806 (founder, 2026-11-08): the whole section takes files dropped anywhere on
it (`ui.dropzone` ``variant="section"``, the accent veil «Suelta aquí tus fotos y
videos» while they hover), through the same handler and refusals as the button — which
stays, for the phone, where nothing is dragged. A cut shows as a card above the tiles
(its stage, then «Listo…» with the parts, or the failure with «Intentar de nuevo»), and
a placeholder per part where the parts will land.

Phone first (360 px): two tiles per row, every action a word on a 44 px target,
nothing that depends on hovering. Media load through the backend's short-lived
`/r2media/<token>` paths (`post_card.viewable_src`), never the local upload store.
"""

from __future__ import annotations

import reflex as rx
from reflex_base.event import parse_args_spec, passthrough_event_spec

from .catalog_cut_page import cut_dialogs, cut_drawer
from .catalog_cut_state import CatalogCutState
from .catalog_cut_vm import CUT_BUTTON, CUT_DONE_DISMISS
from .catalog_gallery_state import DROP_ID, UPLOAD_ID, CatalogGalleryState
from .catalog_gallery_vm import (
    ADD_LABEL,
    CUT_RETRY,
    DRAG_HINT,
    DROP_HINT,
    GALLERY_DESCRIPTION,
    GALLERY_EMPTY,
    GALLERY_MEDIA_ACCEPT,
    GALLERY_TITLE,
    MAX_UPLOAD_BYTES,
    REMOVE_DESCRIPTION,
    TRIMMED_DISMISS,
    TRIMMED_TEXT,
    VIDEOS_WAITING_NOTICE,
    CutCardVM,
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
        # files dragged over the button are the section's (one drop, one upload)
        no_drag=True,
        variant="bare",
        width=rx.breakpoints(initial="100%", sm="auto"),
    )


def _drag_hint() -> rx.Component:
    """One line under the button, on a computer only (a phone drags nothing)."""
    return rx.text(
        DRAG_HINT,
        size="1",
        color=T.TEXT_MUTED,
        display=rx.breakpoints(initial="none", md="block"),
    )


def _droppable(body: rx.Component) -> rx.Component:
    """The whole section as a drop target (m-24976806): the same handler, refusals and
    limits as the button's picker, checked before any byte goes up."""
    return dropzone(
        body,
        upload_id=DROP_ID,
        accept=GALLERY_MEDIA_ACCEPT,
        multiple=True,
        max_files=0,
        max_size=MAX_UPLOAD_BYTES,
        on_drop=G.receive_drop(
            rx.upload_files_chunk(upload_id=DROP_ID, on_upload_progress=G.upload_progress),
            picked_files(),
        ),
        on_drop_rejected=G.picker_rejected,
        variant="section",
        drop_hint=DROP_HINT,
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
            # not twice: the red refusal may already say the same sentence
            G.videos_full & ~G.uploading & (G.upload_error != VIDEOS_WAITING_NOTICE),
            callout(VIDEOS_WAITING_NOTICE, "info"),
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
        # m-24976806: every cut on its way (and the ended ones this tab saw running)
        rx.foreach(G.cut_cards, _cut_card),
        spacing="2",
        width="100%",
    )


def _dismiss_cut(cut: rx.Var[CutCardVM], **props: object) -> rx.Component:
    return rx.button(
        rx.icon("check", size=T.ICON_SM),
        CUT_DONE_DISMISS,
        variant="soft",
        color_scheme=T.tone_scale("neutral"),
        size="2",
        type="button",
        min_height=_TOUCH_MIN,
        width=rx.breakpoints(initial="100%", sm="auto"),
        on_click=G.dismiss_cut(cut.job_id),
        **props,
    )


def _cut_card(cut: rx.Var[CutCardVM]) -> rx.Component:
    """A cut above the tiles: the video's poster, the stage it is in (read from the
    job, so it survives leaving and coming back), then how it ended."""
    running = rx.vstack(
        rx.text(cut.title, size="3", weight="medium"),
        rx.hstack(
            loading_spinner("sm"),
            rx.text(cut.stage_text, size="2"),
            align="center",
            spacing="2",
        ),
        rx.text(cut.detail, size="1", color=T.TEXT_MUTED),
        spacing="1",
        width="100%",
        min_width="0",
    )
    # the parts are the first tiles right below: the card only says it is done (UX)
    done = rx.vstack(
        callout(cut.title, "ok"),
        _dismiss_cut(cut),
        spacing="2",
        width="100%",
        min_width="0",
        align_items="start",
    )
    failed = rx.vstack(
        callout(cut.title, "error"),
        rx.cond(
            (G.retry_error != "") & (G.retry_for == cut.job_id),
            rx.text(G.retry_error, size="2", role="alert"),
        ),
        rx.box(
            rx.button(
                rx.cond(
                    G.retrying & (G.retry_for == cut.job_id),
                    loading_spinner("sm"),
                    rx.icon("rotate-ccw", size=T.ICON_SM),
                ),
                CUT_RETRY,
                size="2",
                type="button",
                min_height=_TOUCH_MIN,
                width="100%",
                on_click=G.retry_cut(cut.job_id),
                disabled=G.retrying,
            ),
            _dismiss_cut(cut, disabled=G.retrying),
            display="grid",
            grid_template_columns=rx.breakpoints(
                initial="minmax(0, 1fr)", sm="repeat(2, max-content)"
            ),
            gap="0.5rem",
            width="100%",
        ),
        spacing="2",
        width="100%",
        min_width="0",
        align_items="start",
    )
    return card(
        rx.hstack(
            media_thumb(
                viewable_src(cut.thumb_url),
                has=cut.thumb_url != "",
                size="4.5rem",
                icon="clapperboard",
            ),
            # how it goes is announced as it changes, the end too (UX review)
            rx.box(
                rx.match(cut.phase, ("done", done), ("failed", failed), running),
                aria_live="polite",
                width="100%",
                min_width="0",
            ),
            align="start",
            spacing="3",
            width="100%",
        ),
        padding="0.9rem 1rem",
        width="100%",
        key=cut.job_id,
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
            (item.state == "preparing") | (item.state == "part_pending"),
            rx.center(loading_spinner("md"), position="absolute", inset="0"),
        ),
        # a part on its way already knows its length
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
        position="relative",
        width="100%",
        role="img",
        aria_label=item.label,
    )
    return rx.cond(
        (item.state == "preparing") | (item.state == "failed") | (item.state == "part_pending"),
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
        aria_label="Quitar " + item.remove_label,
        **T.tone_scheme("error"),
    )
    return rx.box(
        _picture(item),
        rx.vstack(
            # the length is the badge on the picture; the footer only says what is
            # happening and offers «Quitar» (UX review: once, not three times)
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
            # CM-4: a ready video can be cut into parts — or, too short, the button
            # says so instead of vanishing (m-24976897)
            rx.cond(
                item.cut_shown,
                rx.vstack(
                    rx.button(
                        rx.icon("scissors", size=T.ICON_SM),
                        CUT_BUTTON,
                        variant="soft",
                        size="2",
                        type="button",
                        min_height=_TOUCH_MIN,
                        width="100%",
                        on_click=CatalogCutState.open_cut(item.media_id),
                        disabled=G.busy | ~item.cuttable,
                        aria_label="Cortar " + item.remove_label,
                        aria_describedby=rx.cond(
                            item.cut_reason != "", "cut-why-" + item.key, None
                        ),
                    ),
                    rx.cond(
                        item.cut_reason != "",
                        rx.text(
                            item.cut_reason,
                            size="1",
                            color=T.TEXT_MUTED,
                            id="cut-why-" + item.key,
                        ),
                    ),
                    spacing="1",
                    width="100%",
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


def _more_button() -> rx.Component:
    """«Ver todas (14)» / «Ver menos»: only the first six tiles show until asked, so the
    products below stay within reach on a phone. Words, 44 px, full width there."""
    return rx.cond(
        G.more_text != "",
        rx.button(
            rx.cond(
                G.show_all,
                rx.icon("chevron-up", size=T.ICON_SM),
                rx.icon("chevron-down", size=T.ICON_SM),
            ),
            G.more_text,
            variant="soft",
            color_scheme=T.tone_scale("neutral"),
            size="2",
            type="button",
            min_height=_TOUCH_MIN,
            width=rx.breakpoints(initial="100%", sm="auto"),
            aria_expanded=rx.cond(G.show_all, "true", "false"),
            on_click=G.toggle_show_all,
        ),
    )


def _grid() -> rx.Component:
    return rx.box(
        rx.foreach(G.shown_items, _tile),
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
        _drag_hint(),
        _status(),
        rx.cond(
            G.has_items,
            rx.fragment(_grid(), _more_button()),
            rx.cond(
                ~G.uploading,
                rx.text(GALLERY_EMPTY, size="2", color=T.TEXT_MUTED),
            ),
        ),
        description=GALLERY_DESCRIPTION,
    )
    return rx.cond(
        G.loaded,
        rx.cond(G.available, _droppable(body)),
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
    """The section's dialogs and the cutter (CM-4), mounted once at page level
    (outside any `rx.cond`)."""
    return rx.fragment(_remove_dialog(), cut_drawer(), cut_dialogs())

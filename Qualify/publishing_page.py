"""«Publicar ahora» (`/publish`) — one or several photos and videos to Instagram, now.

Spec: `docs/mockups/publicar-varias-imagenes.md` (visual reference
`docs/mockups/publicar-varias-imagenes.html`); founder decisions 2026-11-12. A step
assistant (N6) with one question per step, M counted live:

1. ¿Qué vas a publicar? — the gallery (`_what_step`).
2. ¿Cómo sale? / ¿Cómo salen? — publicación or historia; with several, «Juntas en un
   carrusel», «Una por una» (a mural, ≤ 9) or «Como historias» (`_how_step`).
3. The order, only with 2 or more — a list for a carousel or historias, the profile grid
   for a mural (`_order_step`). Drag (`assets/rank-drag.js`, `DragCard` + `sort_handle`)
   or «⋯» (Primero · Subir uno · Bajar uno · Último · Quitar): never drag alone.
4. ¿En qué Instagram sale? — only with 2 or more Instagram accounts; Facebook listed
   off with its reason, WhatsApp not listed (`_account_step`).
5. Revisa y publica — the description(s), «Publicar», then the progress, a failure with
   «Continuar», or the «listo» (`_review_step`, `_done_panel`).

Every step stays MOUNTED and is only hidden (`_step_panel`), so «Atrás» never loses a
file, a thumbnail or a word. Only design-system pieces (`Qualify/ui/`); the mural grid is
the gallery tile (`.q-pub-tile`) laid out in three columns (`assets/qualify-publish.css`).
The state is `PublishState` (data + the run) and `PublishHubState` (navigation).
"""

from __future__ import annotations

import reflex as rx

from .publish_hub_state import PublishHubState, link_guard_script
from .publish_wizard_vm import (
    BACK,
    BEFORE_TILE,
    CAPTION_EXAMPLE,
    CAPTION_HELP,
    CAPTION_LABEL,
    CONTINUE,
    COPY_CAPTION,
    COVER_BADGE,
    DISCARD,
    GALLERY_FULL,
    KEEP_AS_IS,
    KEEP_AS_IS_TITLE,
    LEAVE_GO,
    LEAVE_STAY,
    LEAVE_TITLE,
    MODE_CAROUSEL,
    MODE_ONE_BY_ONE,
    MODE_POST,
    MODE_STORIES,
    MODE_STORY,
    MURAL_HELP,
    MURAL_SHIFT_NOTE,
    ONE_STORY_OPEN_HINT,
    ORDER_HELP,
    PICK_NEXT_HINT,
    PROGRESS_DETAIL,
    RECONNECT,
    REJECTED_FILE_HELP,
    REJECTED_FILE_TITLE,
    STEP_ACCOUNT,
    STEP_HOW,
    STEP_ORDER,
    STEP_REVIEW,
    STEP_WHAT,
    STORIES_NO_TEXT,
    STORIES_ORDER_HELP,
)
from .publishing_state import _UPLOAD_ID, PublishState
from .publishing_vm import ConnectionOptionVM, PendingItemVM
from .stories_page import share_to_instagram_button
from .trending_panel import trending_card
from .ui import (
    DragCard,
    app_shell,
    asset_script,
    callout,
    card,
    choice_card,
    choice_card_check,
    dropzone,
    empty_state,
    loading_spinner,
    media_thumb,
    page_body,
    page_header,
    platform_badge,
    progress_panel,
    section,
    signal_pill,
    sort_handle,
    tone_badge,
)
from .ui import tokens as T
from .ui.image_preview import gallery_image_preview_capture_anchor
from .ui.steps import step_foot, step_frame, step_head, step_sync
from .ui.video_preview import (
    gallery_crop_warning,
    gallery_preview_capture_anchor,
    video_frame_preview_src,
)

P = PublishState
H = PublishHubState

# The DOM id the preview capture anchors listen on (`ui/video_preview.py`).
_GALLERY_ROOT_ID = "publish-gallery-root"
# «Abrir en Instagram» shares the LAST File picked; removing any tile forgets it.
_FORGET_SHARED_FILE = (
    "if (window.__qualifyPreviews && window.__qualifyPreviews.filesByRoot) "
    f"{{ delete window.__qualifyPreviews.filesByRoot['{_GALLERY_ROOT_ID}']; }}"
)
_RANK_DRAG_JS = asset_script("rank-drag.js")
_CROP_TEMPLATE = (
    "Instagram corta todas a la forma de la primera ({forma}). Si alguna se ve cortada, "
    "pon primero la que tiene la forma que quieres."
)
# N12: every control on this screen is at least 44 px tall.
_TARGET = "44px"


def _preview(item: PendingItemVM) -> rx.Var[str]:
    return video_frame_preview_src(root_id=_GALLERY_ROOT_ID, filename=item.filename)


def _kind_icon(item: PendingItemVM, size: int = 20) -> rx.Component:
    return rx.cond(
        item.kind == "image",
        rx.icon("image", size=size, color=T.tone_color("ok", 9)),
        rx.icon("film", size=size, color=T.tone_color("ok", 9)),
    )


def _thumb56(item: PendingItemVM) -> rx.Component:
    src = _preview(item)
    return rx.cond(
        item.kind == "image",
        media_thumb(src, size="56px", icon="image", alt="", has=src != ""),
        media_thumb(src, size="56px", icon="film", alt="", has=src != ""),
    )


def _step_panel(step: str, *children: rx.Component) -> rx.Component:
    """One step's content. Hidden — never unmounted — while another step shows."""
    return rx.vstack(
        *children,
        spacing="4",
        width="100%",
        align_items="stretch",
        display=rx.cond(P.step_id == step, "flex", "none"),
    )


def _muted(text: str | rx.Var, size: str = "2") -> rx.Component:
    return rx.text(text, size=size, color=T.TEXT_MUTED)


# -- ① ¿Qué vas a publicar? ---------------------------------------------------------------


def _pending_tile(item: PendingItemVM) -> rx.Component:
    """One selected file: its real thumbnail (or an icon while there is none), its
    position chip and the ✕ (spec §3, paso 1 — the order changes in step 3)."""
    preview_src = _preview(item)
    return rx.box(
        rx.cond(
            preview_src != "",
            rx.el.img(src=preview_src, alt=item.label, class_name="q-pub-tile-img"),
            rx.vstack(
                _kind_icon(item, 24),
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
        rx.box(item.position, class_name="q-pub-tile-pos", aria_hidden="true"),
        rx.icon_button(
            rx.icon("x", size=14),
            on_click=[P.remove_item(item.id, False), rx.call_script(_FORGET_SHARED_FILE)],
            disabled=~P.can_edit_gallery,
            title="Quitar " + item.label,
            aria_label="Quitar " + item.label,
            size="1",
            variant="soft",
            color_scheme=T.tone_scale("error"),
            radius="full",
            class_name="q-pub-tile-x",
        ),
        class_name="q-pub-tile",
    )


def _upload_widget(children: rx.Component, *, compact: bool) -> rx.Component:
    """The ONE dropzone: the big empty prompt, or the `+` tile inside the grid. The real
    limits are server-side (`PublishState.add_files`, the staging service)."""
    return dropzone(
        children,
        upload_id=_UPLOAD_ID,
        accept={
            "video/mp4": [".mp4"],
            "video/quicktime": [".mov"],
            "image/jpeg": [".jpg", ".jpeg"],
        },
        multiple=True,
        max_files=P.remaining_slots,
        max_size=300 * 1024 * 1024,
        disabled=~P.can_edit_gallery,
        on_drop=P.add_files,
        on_drop_rejected=[
            P.mark_drop_rejected,
            rx.toast.error(REJECTED_FILE_TITLE, description=REJECTED_FILE_HELP),
        ],
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
        _muted("Desde la computadora también puedes arrastrarlos aquí.", "1"),
        spacing="2",
        align="center",
        text_align="center",
    )


def _preview_capture_anchor() -> rx.Component:
    """Mounted unconditionally so the very first pick already gets its thumbnail."""
    return rx.box(
        gallery_preview_capture_anchor(root_id=_GALLERY_ROOT_ID),
        gallery_image_preview_capture_anchor(root_id=_GALLERY_ROOT_ID),
        display="none",
    )


def _gallery_zone() -> rx.Component:
    return rx.box(
        _preview_capture_anchor(),
        rx.cond(
            P.file_count > 0,
            rx.box(
                rx.foreach(P.pending_items, _pending_tile),
                rx.cond(
                    P.remaining_slots > 0,
                    _upload_widget(_add_tile_content(), compact=True),
                    rx.fragment(),
                ),
                # three columns, like the profile grid (UX review 2026-11-12)
                class_name="q-pub-gallery",
            ),
            _upload_widget(_empty_state_content(), compact=False),
        ),
        id=_GALLERY_ROOT_ID,
        width="100%",
    )


def _rejected_callout() -> rx.Component:
    return rx.cond(
        P.last_drop_rejected,
        callout(f"{REJECTED_FILE_TITLE}. {REJECTED_FILE_HELP}", "error"),
        rx.fragment(),
    )


def _no_instagram_first() -> rx.Component:
    """No Instagram account to publish to: said before any file is picked (a business
    with only WhatsApp or Facebook sees it too — spec §3, paso 1)."""
    return rx.cond(
        P.connections_loaded & (P.load_error == "") & ~P.has_instagram,
        empty_state(
            "link",
            "Primero conecta tu Instagram",
            "Para publicar, primero conecta tu Instagram. Toma un par de minutos.",
            action=rx.link(
                rx.button(RECONNECT, size="3", min_height=_TARGET),
                href="/connections",
            ),
        ),
        rx.fragment(),
    )


def _leftover_callout() -> rx.Component:
    """«Te quedaron {r} sin publicar…» — a mural or historias left unfinished."""
    return rx.cond(
        P.leftover_text != "",
        callout(
            rx.vstack(
                rx.text(P.leftover_text, size="3", weight="medium"),
                rx.flex(
                    rx.cond(
                        P.needs_reconnect | ~P.pinned_account_ready,
                        rx.link(
                            rx.button(RECONNECT, size="3", width="100%", min_height=_TARGET),
                            href="/connections",
                            width="100%",
                        ),
                        rx.button(
                            CONTINUE,
                            on_click=H.resume_leftover,
                            size="3",
                            width="100%",
                            min_height=_TARGET,
                        ),
                    ),
                    rx.button(
                        DISCARD,
                        on_click=H.start_over,
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
            "warn",
            icon="triangle-alert",
        ),
        rx.fragment(),
    )


def _what_step() -> rx.Component:
    return _step_panel(
        STEP_WHAT,
        _leftover_callout(),
        _no_instagram_first(),
        _gallery_zone(),
        _rejected_callout(),
        rx.cond(P.remaining_slots == 0, _muted(GALLERY_FULL), rx.fragment()),
        rx.cond(P.file_count > 1, _muted(PICK_NEXT_HINT), rx.fragment()),
    )


# -- ② ¿Cómo sale? / ¿Cómo salen? ----------------------------------------------------------


def _kind_choice(
    mode: str,
    icon: str,
    title: str,
    description: rx.Component,
    *,
    disabled: rx.Var[bool] | bool = False,
) -> rx.Component:
    selected = P.mode == mode
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
        on_select=H.select_kind(mode),
        disabled=P.busy | disabled if isinstance(disabled, rx.Var) else P.busy,
        width="100%",
        min_height=_TARGET,
        text_align="left",
    )


def _how_step() -> rx.Component:
    one = rx.vstack(
        _kind_choice(
            MODE_POST,
            "layout-grid",
            "Publicación en tu perfil",
            _muted("Queda en tu perfil, con su descripción."),
        ),
        _kind_choice(
            MODE_STORY,
            "circle-dashed",
            "Historia (24 h)",
            _muted("Se ve durante 24 horas, sin texto."),
        ),
        spacing="3",
        width="100%",
        role="radiogroup",
        aria_label="Cómo sale",
    )
    many = rx.vstack(
        _kind_choice(
            MODE_CAROUSEL,
            "gallery-horizontal",
            "Juntas en un carrusel",
            _muted("Una sola publicación que se desliza, con una descripción."),
        ),
        _kind_choice(
            MODE_ONE_BY_ONE,
            "layout-grid",
            "Una por una",
            rx.cond(
                P.one_by_one_reason != "",
                _muted(P.one_by_one_reason),
                _muted(
                    "Cada foto es su propia publicación, con su descripción. Así se arma "
                    "un mural en tu perfil."
                ),
            ),
            disabled=P.one_by_one_reason != "",
        ),
        _kind_choice(
            MODE_STORIES,
            "circle-dashed",
            "Como historias",
            _muted(
                "Una historia por cada foto o video, una tras otra. Se ven 24 horas, sin texto."
            ),
        ),
        spacing="3",
        width="100%",
        role="radiogroup",
        aria_label="Cómo salen",
    )
    return _step_panel(STEP_HOW, rx.cond(P.file_count > 1, many, one))


# -- ③ the order ---------------------------------------------------------------------------


def _move_menu(item: PendingItemVM, *, overlay: bool = False) -> rx.Component:
    at_top = item.position == 1
    at_end = item.position == item.total
    return rx.menu.root(
        rx.menu.trigger(
            rx.icon_button(
                rx.icon("ellipsis", size=T.ICON_MD),
                variant="soft" if overlay else "ghost",
                size="3",
                type="button",
                aria_label=item.more_label,
                min_width=_TARGET,
                min_height=_TARGET,
                class_name="q-pub-mural-more" if overlay else "",
                **T.tone_scheme("neutral"),
            ),
        ),
        rx.menu.content(
            rx.menu.item("Primero", on_click=P.place(item.id, 0), disabled=at_top),
            rx.menu.item(
                "Subir uno", on_click=P.place(item.id, item.position - 2), disabled=at_top
            ),
            rx.menu.item("Bajar uno", on_click=P.place(item.id, item.position), disabled=at_end),
            rx.menu.item("Último", on_click=P.place(item.id, item.total - 1), disabled=at_end),
            rx.menu.separator(),
            rx.menu.item(
                rx.icon("x", size=T.ICON_SM),
                "Quitar",
                on_click=[P.remove_item(item.id, True), rx.call_script(_FORGET_SHARED_FILE)],
                color=T.tone_color("error", 11),
            ),
            align="end",
        ),
    )


def _order_row(item: PendingItemVM) -> rx.Component:
    """A carousel or historias row: handle · 56 px thumbnail · «Foto k» · «Portada» · ⋯"""
    return DragCard.create(
        rx.hstack(
            sort_handle(
                item.handle_label,
                lambda key: P.handle_key(item.id, key),
                key=item.id,
                lifted=P.lifted == item.id,
            ),
            _thumb56(item),
            rx.hstack(
                rx.text(item.label, size="3", weight="medium"),
                rx.cond(
                    (P.mode == MODE_CAROUSEL) & (item.position == 1),
                    tone_badge(COVER_BADGE, "accent"),
                    rx.fragment(),
                ),
                spacing="2",
                align="center",
                flex="1",
                min_width="0",
                wrap="wrap",
            ),
            _move_menu(item),
            align="center",
            spacing="2",
            width="100%",
        ),
        class_name="q-rank-card q-order-row",
        custom_attrs={
            "data-rank-group": "publish-order",
            "data-rank-key": item.id,
            "role": "listitem",
        },
        on_drag_start=P.pick(item.id),
        on_drop=P.drop(item.id),
        key=item.id,
        width="100%",
        padding_y="0.25rem",
    )


def _mural_image(item: PendingItemVM) -> rx.Component:
    preview_src = _preview(item)
    return rx.cond(
        preview_src != "",
        rx.el.img(src=preview_src, alt=item.label, class_name="q-pub-tile-img"),
        rx.center(_kind_icon(item, 24), height="100%"),
    )


def _mural_tile(item: PendingItemVM) -> rx.Component:
    """One tile of the profile grid: its position top-left (with the film icon for a
    video), «⋯» top-right; a long press lifts it (no handle: it does not fit in ~105 px —
    the keyboard and screen readers use «⋯», spec §7)."""
    return DragCard.create(
        _mural_image(item),
        rx.hstack(
            rx.text(item.position, as_="span"),
            rx.cond(item.kind == "video", rx.icon("film", size=12), rx.fragment()),
            class_name="q-pub-tile-pos",
            spacing="1",
            align="center",
            aria_hidden="true",
        ),
        _move_menu(item, overlay=True),
        class_name="q-rank-card q-pub-tile q-pub-mural-tile",
        custom_attrs={
            "data-rank-group": "publish-mural",
            "data-rank-key": item.id,
            "role": "listitem",
            "aria-label": item.label + ", posición " + item.position.to_string(),
        },
        on_drag_start=P.pick(item.id),
        on_drop=P.drop(item.id),
        key=item.id,
    )


def _before_tile(_slot: rx.Var[int]) -> rx.Component:
    return rx.center(
        rx.text(BEFORE_TILE, size="1", color=T.TEXT_FAINT),
        class_name="q-pub-tile q-pub-mural-tile q-pub-mural-before",
        aria_hidden="true",
    )


def _mural_grid(tile: object) -> rx.Component:
    return rx.box(
        rx.foreach(P.pending_items, tile),
        rx.foreach(P.before_slots, _before_tile),
        class_name="q-pub-mural",
        role="list",
        aria_label="Así se verá tu perfil",
    )


def _crop_notice() -> rx.Component:
    warning = gallery_crop_warning(
        root_id=_GALLERY_ROOT_ID, filenames=P.pending_filenames, template=_CROP_TEMPLATE
    )
    return rx.box(
        rx.cond(warning != "", callout(warning, "warn"), rx.fragment()),
        role="status",
        aria_live="polite",
        width="100%",
    )


def _order_step() -> rx.Component:
    rows = rx.vstack(
        rx.foreach(P.pending_items, _order_row),
        spacing="2",
        width="100%",
        role="list",
        aria_label="Orden",
    )
    return _step_panel(
        STEP_ORDER,
        rx.cond(
            P.mode == MODE_ONE_BY_ONE,
            rx.vstack(
                _muted(MURAL_HELP),
                _muted(ORDER_HELP, "1"),
                _mural_grid(_mural_tile),
                rx.cond(P.rows_hint != "", callout(P.rows_hint, "info"), rx.fragment()),
                _muted(MURAL_SHIFT_NOTE, "1"),
                # the fixed foot covers the page's bottom on a phone: keep the note clear
                rx.box(class_name="q-pub-foot-room", aria_hidden="true"),
                spacing="3",
                width="100%",
                align_items="stretch",
            ),
            rx.vstack(
                rx.cond(P.mode == MODE_STORIES, _muted(STORIES_ORDER_HELP), rx.fragment()),
                _muted(ORDER_HELP, "1"),
                rows,
                rx.cond(P.mode == MODE_CAROUSEL, _crop_notice(), rx.fragment()),
                rx.box(class_name="q-pub-foot-room", aria_hidden="true"),
                spacing="3",
                width="100%",
                align_items="stretch",
            ),
        ),
        rx.text(P.announce, class_name="q-order-live", role="status", aria_live="polite"),
        rx.box(display="none", on_mount=rx.call_script(_RANK_DRAG_JS)),
    )


# -- ④ ¿En qué Instagram sale? ------------------------------------------------------------


def _account_card(conn: ConnectionOptionVM) -> rx.Component:
    selected = P.selected_connection_id == conn.id
    return choice_card(
        rx.hstack(
            platform_badge(conn.platform),
            rx.vstack(
                rx.text(conn.handle, size="3", weight="medium"),
                rx.cond(conn.note != "", _muted(conn.note), rx.fragment()),
                spacing="1",
                align_items="start",
            ),
            rx.spacer(),
            rx.cond(selected, choice_card_check(), rx.fragment()),
            spacing="3",
            align="center",
            width="100%",
        ),
        selected=selected,
        on_select=P.select_connection(conn.id),
        disabled=~conn.selectable | P.account_locked,
        width="100%",
        min_height=_TARGET,
        text_align="left",
    )


def _no_accounts() -> rx.Component:
    return empty_state(
        "link",
        "Aún no tienes una cuenta de Instagram conectada",
        "Conecta tu Instagram y vuelve aquí para publicar.",
        action=rx.link(rx.button(RECONNECT, size="3", min_height=_TARGET), href="/connections"),
    )


def _account_step() -> rx.Component:
    return _step_panel(
        STEP_ACCOUNT,
        rx.cond(
            P.load_error != "",
            callout(P.load_error, "error"),
            rx.cond(
                P.is_loading_connections,
                rx.hstack(
                    loading_spinner("sm"),
                    _muted("Buscando tus cuentas..."),
                    spacing="2",
                    align="center",
                ),
                rx.cond(
                    P.has_instagram,
                    rx.vstack(
                        rx.foreach(P.connections, _account_card),
                        spacing="3",
                        width="100%",
                        role="radiogroup",
                        aria_label="Cuenta",
                    ),
                    _no_accounts(),
                ),
            ),
        ),
    )


# -- ⑤ Revisa y publica ------------------------------------------------------------------


def _review_thumb(item: PendingItemVM) -> rx.Component:
    preview_src = _preview(item)
    return rx.box(
        rx.cond(
            preview_src != "",
            rx.el.img(src=preview_src, alt=item.label, class_name="q-pub-tile-img"),
            rx.center(_kind_icon(item), height="100%"),
        ),
        class_name="q-pub-tile",
        style={"--q-dropzone-tile": "4.5rem"},
    )


def _review_summary() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.icon("send", size=T.ICON_SM, color=T.tone_color("accent", 9)),
            rx.text(P.review_text, size="3", weight="medium"),
            spacing="2",
            align="start",
        ),
        rx.flex(
            rx.foreach(P.pending_items, _review_thumb),
            wrap="wrap",
            gap="0.5rem",
            width="100%",
        ),
        spacing="3",
        width="100%",
    )


def _caption_field() -> rx.Component:
    return section(
        CAPTION_LABEL,
        rx.text_area(
            placeholder=CAPTION_EXAMPLE,
            value=P.caption,
            on_change=P.set_caption,
            rows="4",
            size="3",
            width="100%",
            disabled=P.busy,
            aria_label=CAPTION_LABEL,
        ),
        description=CAPTION_HELP,
    )


def _item_caption(item: PendingItemVM) -> rx.Component:
    """«Una por una»: one card per photo, in the mural's order (spec §3, paso 5)."""
    field_id = "q-pub-caption-" + item.id
    return card(
        rx.vstack(
            rx.hstack(
                rx.box(
                    _thumb56(item),
                    rx.box(item.position, class_name="q-pub-tile-pos", aria_hidden="true"),
                    position="relative",
                ),
                rx.text(item.publication_title, size="3", weight="medium"),
                spacing="3",
                align="center",
            ),
            rx.el.label(item.caption_label, html_for=field_id, class_name="rt-Text rt-r-size-2"),
            rx.text_area(
                id=field_id,
                placeholder=CAPTION_EXAMPLE,
                value=P.item_captions[item.id],
                on_change=lambda value: P.set_item_caption(item.id, value),
                rows="3",
                size="3",
                width="100%",
                disabled=P.busy,
            ),
            rx.cond(
                item.position == 1,
                rx.button(
                    COPY_CAPTION,
                    on_click=P.copy_first_caption,
                    variant="soft",
                    size="3",
                    min_height=_TARGET,
                    disabled=~P.can_copy_caption,
                ),
                rx.fragment(),
            ),
            spacing="2",
            width="100%",
            align_items="stretch",
        ),
        padding="1rem",
    )


def _descriptions() -> rx.Component:
    return rx.match(
        P.mode,
        (
            MODE_ONE_BY_ONE,
            rx.vstack(
                rx.foreach(P.pending_items, _item_caption),
                _muted(CAPTION_HELP, "1"),
                spacing="3",
                width="100%",
            ),
        ),
        (MODE_STORIES, _muted(STORIES_NO_TEXT)),
        (
            MODE_STORY,
            rx.vstack(
                _muted(STORIES_NO_TEXT + " " + ONE_STORY_OPEN_HINT),
                spacing="2",
                width="100%",
            ),
        ),
        _caption_field(),
    )


def _single_status() -> rx.Component:
    """One publication, a carousel or one historia going out (spec §4.1, as before)."""
    return rx.cond(
        P.busy,
        rx.cond(
            P.run_waiting,
            callout(
                rx.vstack(
                    rx.hstack(
                        loading_spinner("sm"),
                        rx.cond(
                            P.carousel_stage_label != "",
                            rx.text(P.carousel_stage_label, size="2", weight="medium"),
                            rx.text(
                                "Publicando, esperando que Instagram lo confirme...",
                                size="2",
                                weight="medium",
                            ),
                        ),
                        rx.cond(
                            P.elapsed_label != "",
                            rx.text(
                                P.elapsed_label,
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
                    _muted(P.wait_text, "1"),
                    spacing="1",
                    align_items="start",
                    width="100%",
                ),
                "warn",
                icon="clock",
            ),
            callout(
                rx.hstack(
                    loading_spinner("sm"),
                    rx.text("Subiendo tus fotos y videos...", size="2"),
                    spacing="2",
                    align="center",
                ),
                "neutral",
                icon="upload",
            ),
        ),
        rx.cond(
            (P.phase == "failure") & (P.error != ""),
            callout(P.error, "error"),
            rx.fragment(),
        ),
    )


def _piece_row(item: PendingItemVM) -> rx.Component:
    return rx.hstack(
        _thumb56(item),
        rx.text(item.label, size="3", weight="medium", flex="1"),
        signal_pill(item.status_label, item.status_tone),
        spacing="3",
        align="center",
        width="100%",
        role="listitem",
    )


def _piece_tile(item: PendingItemVM) -> rx.Component:
    return rx.box(
        _mural_image(item),
        rx.box(item.position, class_name="q-pub-tile-pos", aria_hidden="true"),
        rx.box(signal_pill(item.status_label, item.status_tone), class_name="q-pub-mural-pill"),
        class_name="q-pub-tile q-pub-mural-tile",
        role="listitem",
        aria_label=item.label + ": " + item.status_label,
    )


def _pieces() -> rx.Component:
    """Each piece with its word (spec §4.2) — the mural marks itself from the last to
    the first, as it goes out."""
    return rx.cond(
        P.run_mode == MODE_ONE_BY_ONE,
        _mural_grid(_piece_tile),
        rx.vstack(
            rx.foreach(P.pending_items, _piece_row),
            spacing="2",
            width="100%",
            role="list",
            aria_label="Historias",
        ),
    )


def _series_failure() -> rx.Component:
    """«Salieron {s} de {n}. La foto {k} no salió.» + why + what «Continuar» does."""
    return callout(
        rx.vstack(
            rx.cond(
                P.failed_title != "",
                rx.text(P.failed_title, size="3", weight="medium"),
                rx.text(P.leftover_text, size="3", weight="medium"),
            ),
            rx.cond(P.error != "", rx.text(P.error, size="2"), rx.fragment()),
            rx.cond(P.failed_next != "", rx.text(P.failed_next, size="2"), rx.fragment()),
            rx.flex(
                rx.cond(
                    P.needs_reconnect | ~P.pinned_account_ready,
                    rx.link(
                        rx.button(RECONNECT, size="3", width="100%", min_height=_TARGET),
                        href="/connections",
                        width="100%",
                    ),
                    rx.fragment(),
                ),
                rx.button(
                    KEEP_AS_IS,
                    on_click=H.ask_keep_as_is,
                    variant="soft",
                    size="3",
                    width="100%",
                    min_height=_TARGET,
                ),
                direction=rx.breakpoints(initial="column", sm="row"),
                gap="0.75rem",
                width="100%",
            ),
            spacing="2",
            width="100%",
            align_items="stretch",
        ),
        "error",
    )


def _series_view() -> rx.Component:
    return rx.vstack(
        rx.cond(
            P.busy,
            progress_panel(P.progress_title, PROGRESS_DETAIL, value=P.progress_value),
            _series_failure(),
        ),
        _pieces(),
        spacing="4",
        width="100%",
        align_items="stretch",
    )


def _or_divider() -> rx.Component:
    return rx.hstack(
        rx.separator(size="4", flex="1"),
        rx.text("o", size="2", color=T.TEXT_MUTED),
        rx.separator(size="4", flex="1"),
        spacing="3",
        align="center",
        width="100%",
    )


def _review_step() -> rx.Component:
    series_on_screen = P.is_series_run & (P.busy | P.resumable)
    return _step_panel(
        STEP_REVIEW,
        rx.cond(
            series_on_screen,
            _series_view(),
            rx.vstack(
                _review_summary(),
                _descriptions(),
                _single_status(),
                rx.cond(
                    (P.mode == MODE_STORY) & ~P.busy,
                    rx.vstack(
                        _or_divider(),
                        share_to_instagram_button(
                            root_id=_GALLERY_ROOT_ID, enabled=P.file_count == 1
                        ),
                        spacing="3",
                        width="100%",
                        align_items="stretch",
                    ),
                    rx.fragment(),
                ),
                spacing="4",
                width="100%",
                align_items="stretch",
            ),
        ),
    )


# -- dialogs -------------------------------------------------------------------------------


def _leave_dialog() -> rx.Component:
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title(LEAVE_TITLE),
            rx.alert_dialog.description(P.leave_text, size="2"),
            rx.flex(
                rx.button(
                    LEAVE_STAY, on_click=H.stay, size="3", min_height=_TARGET, auto_focus=True
                ),
                rx.button(
                    LEAVE_GO,
                    on_click=H.leave_anyway,
                    variant="soft",
                    size="3",
                    min_height=_TARGET,
                ),
                direction=rx.breakpoints(initial="column", sm="row-reverse"),
                gap="0.75rem",
                margin_top="1rem",
            ),
        ),
        open=H.leave_open,
    )


def _keep_dialog() -> rx.Component:
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title(KEEP_AS_IS_TITLE),
            rx.alert_dialog.description(P.keep_as_is_text, size="2"),
            rx.flex(
                rx.button(
                    KEEP_AS_IS,
                    on_click=H.confirm_keep_as_is,
                    size="3",
                    min_height=_TARGET,
                ),
                rx.button(
                    BACK,
                    on_click=H.cancel_keep_as_is,
                    variant="soft",
                    size="3",
                    min_height=_TARGET,
                    auto_focus=True,
                ),
                direction=rx.breakpoints(initial="column", sm="row-reverse"),
                gap="0.75rem",
                margin_top="1rem",
            ),
        ),
        open=H.keep_open,
    )


def _leave_guard() -> rx.Component:
    """While a series goes out: links outside the assistant ask first (spec §4.2)."""
    return rx.fragment(
        rx.box(display="none", on_mount=rx.call_script(link_guard_script())),
        rx.cond(
            P.busy & P.is_series_run,
            rx.el.button(
                id="q-pub-leave-ask",
                on_click=H.ask_leave,
                type="button",
                tab_index=-1,
                aria_hidden="true",
                style={"display": "none"},
            ),
            rx.fragment(),
        ),
        _leave_dialog(),
        _keep_dialog(),
    )


# -- the frame -----------------------------------------------------------------------------


def _assistant_frame() -> rx.Component:
    reviewing = P.step_id == STEP_REVIEW
    review_ready = rx.cond(P.resumable, P.can_continue, P.can_publish)
    return step_frame(
        rx.cond(
            H.entered,
            step_sync(P.step_number, H.direction, epoch=H.entry_epoch),
        ),
        _what_step(),
        _how_step(),
        _order_step(),
        _account_step(),
        _review_step(),
        # only on the first step: on the order and the review it distracts (UX review)
        rx.cond(P.step_id == STEP_WHAT, _ideas(), rx.fragment()),
        _leave_guard(),
        head=step_head(
            P.step_title,
            step=P.step_number,
            total=P.step_total,
            back_label="Inicio",
            on_exit=H.leave,
        ),
        foot=step_foot(
            rx.cond(reviewing, P.primary_label, "Siguiente"),
            step=P.step_number,
            on_primary=H.continue_or_publish,
            on_back=H.go_back,
            on_later=H.leave,
            primary_disabled=rx.cond(reviewing, ~review_ready, ~P.can_go),
            primary_busy=P.busy,
            reason=rx.cond(P.busy | reviewing, "", P.step_reason),
        ),
        # The gallery's native files and preview cache stay mounted between steps.
        step=1,
        direction=H.direction,
        on_pop=H.read_step,
        on_leave=H.leave_frame,
    )


# -- the «listo» (N3) and the ideas -----------------------------------------------------


def _done_actions() -> rx.Component:
    return rx.flex(
        rx.link(
            rx.button("Ver mi semana", size="3", width="100%", min_height=_TARGET),
            href="/planner",
            width="100%",
        ),
        rx.button(
            "Publicar otra",
            on_click=H.start_over,
            variant="soft",
            size="3",
            width="100%",
            min_height=_TARGET,
        ),
        direction=rx.breakpoints(initial="column", sm="row"),
        gap="0.75rem",
        width="100%",
    )


def _done_panel() -> rx.Component:
    """Persistent, not a toast: what happened and the next step (N3, spec §4.4)."""
    return rx.cond(
        P.phase == "partial",
        callout(
            rx.vstack(
                rx.text(P.partial_text, size="3", weight="medium"),
                _done_actions(),
                spacing="3",
                width="100%",
                align_items="stretch",
            ),
            "warn",
            icon="triangle-alert",
        ),
        callout(
            rx.vstack(
                rx.text(P.done_text, size="3", weight="medium"),
                _done_actions(),
                spacing="3",
                width="100%",
                align_items="stretch",
            ),
            "ok",
            icon="circle-check",
        ),
    )


def _ideas() -> rx.Component:
    return rx.vstack(
        rx.button(
            rx.icon("lightbulb", size=T.ICON_SM),
            "Ideas para tu próxima publicación",
            rx.cond(
                H.show_ideas,
                rx.icon("chevron-up", size=T.ICON_SM),
                rx.icon("chevron-down", size=T.ICON_SM),
            ),
            on_click=H.toggle_ideas,
            variant="ghost",
            size="3",
            min_height=_TARGET,
            aria_expanded=rx.cond(H.show_ideas, "true", "false"),
        ),
        rx.cond(H.show_ideas, trending_card(), rx.fragment()),
        spacing="3",
        width="100%",
        align_items="start",
    )


def publish_topbar() -> rx.Component:
    return page_header(
        "Publicar ahora",
        "Sube fotos o videos de tu teléfono y publícalos en tu Instagram.",
    )


def publish_index() -> rx.Component:
    return app_shell(
        rx.cond(
            (P.phase == "success") | (P.phase == "partial"),
            rx.fragment(publish_topbar(), page_body(_done_panel(), _ideas())),
            _assistant_frame(),
        )
    )

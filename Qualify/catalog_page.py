"""/catalog — Catálogo de productos (plan-mvp-plantillas-remotion.md §2.1 #1).

The screen where the founder puts the real products of a brand with their real photos
and short clips — the one input the template engine cannot invent. Three blocks on one
page, design-system §9.1 (`app_shell(page_header, page_body)`):

1. **Agregar producto** — a drawer in three steps (m-24842974): the photo first (the
   phone's camera or gallery), then the name and an optional price (category and
   description behind «Más detalles»), then «Listo» with the two next moves. Opens from
   the header's one solid action; on a phone the drawer is the whole screen.
2. **The editor** of the selected product — a drawer too (m-24842976): the whole
   screen on a phone, with its own address (`/catalog?producto=<id>`, N5) so the phone's
   «atrás» closes it and leaves the list where it was. Its fields, and its media: an
   upload zone that takes photos AND short videos (both normalized at upload by the
   service), the tiles with a «Principal» badge and the words «Principal» and «Quitar»
   (m-24842977: 44 px, «Quitar» asks «¿Quitar esta foto?» first). Leaving
   with unsaved changes asks «¿Salir sin guardar?» first.
3. **The grid** of products as cards: primary photo, name, category, counts — each card
   a real button that says «Editar» in words (never only on hover).

Media keys render through `rx.get_upload_url`, like every upload the generator makes:
the catalog writes to the same store (`catalog_provider`).
"""

from __future__ import annotations

import reflex as rx

from .catalog_state import CatalogState
from .catalog_vm import (
    LEAVE_DISCARD,
    LEAVE_SAVE,
    LEAVE_STAY,
    LEAVE_TITLE,
    MAIN_CURRENCIES,
    MAKE_PRIMARY,
    MEDIA_ACCEPT,
    MISSING_PHOTO,
    NEEDS_PHOTO_REASON,
    NEW_PRODUCT_STEP_ICONS,
    NEW_PRODUCT_STEPS,
    NO_CURRENCY,
    OTHER_CURRENCIES,
    OTHER_CURRENCY_GROUP,
    REMOVE_CONFIRM,
    REMOVE_MEDIA,
    REMOVE_STAY,
    RETURN_HINT,
    RETURN_LABEL,
    RETURN_WITHOUT_LABEL,
    SAVING_PHOTOS_REASON,
    STEP_DONE,
    STEP_NAME,
    STEP_PHOTO,
    ProductMediaVM,
    ProductVM,
)
from .ui import (
    DragCard,
    app_shell,
    asset_script,
    callout,
    card,
    drawer,
    dropzone,
    empty_state,
    media_thumb,
    page_body,
    page_header,
    progress_panel,
    section,
    skeleton_card,
    stepper,
    tag,
    tone_badge,
)
from .ui import tokens as T
from .ui.flow_history import flow_sync
from .ui.route_history import route_history
from .ui.steps import step_progress

#: N12: every control of the «Agregar producto» flow is at least this tall on a phone.
_TOUCH_MIN = "44px"


def _field(label: str, control: rx.Component, hint: str | None = None) -> rx.Component:
    """§5.6: visible label above, help below in size 1 muted."""
    return rx.vstack(
        rx.text(label, size="2", weight="medium"),
        control,
        rx.text(hint, size="1", color=T.TEXT_MUTED) if hint else rx.fragment(),
        spacing="1",
        width="100%",
        align_items="start",
    )


def _currency_select(currency: rx.Var[str], on_currency: object) -> rx.Component:
    """m-24842974: the currency reads by its name («Pesos colombianos (COP)»), starts on
    the business's own, and the four of our markets come first; the rest sit under
    «Otra moneda». «Sin moneda» stays a real choice (the price prints bare)."""
    return rx.select.root(
        rx.select.trigger(aria_label="Moneda", min_height=_TOUCH_MIN, width="100%"),
        rx.select.content(
            rx.select.group(
                *[rx.select.item(name, value=code) for code, name in MAIN_CURRENCIES],
                rx.select.item(NO_CURRENCY, value=NO_CURRENCY),
            ),
            rx.select.separator(),
            rx.select.group(
                rx.select.label(OTHER_CURRENCY_GROUP),
                *[rx.select.item(name, value=code) for code, name in OTHER_CURRENCIES],
            ),
        ),
        value=rx.cond(currency == "", NO_CURRENCY, currency),
        on_change=on_currency,
        size="3",
    )


def _price_field(
    amount: rx.Var[str],
    on_amount: object,
    currency: rx.Var[str],
    on_currency: object,
) -> rx.Component:
    """The optional price (m-24803289). It is what «Variaciones» prints on the piece,
    so the help text says both halves out loud: leaving it empty is a valid answer, and
    what is written here is what the piece shows, exactly."""
    return _field(
        "Precio",
        rx.hstack(
            rx.input(
                value=amount,
                on_change=on_amount,
                placeholder="Ej.: 89990",
                input_mode="decimal",
                size="3",
                min_height=_TOUCH_MIN,
                flex="1 1 8rem",
                min_width="0",
            ),
            _currency_select(currency, on_currency),
            spacing="2",
            width="100%",
            max_width="30rem",  # a price is a short number: not a field across the page
            align="center",
            wrap="wrap",
        ),
        "Opcional. Si lo dejas vacío, la publicación no muestra precio. Si lo escribes, "
        "sale tal cual.",
    )


def _product_fields(
    *,
    name: rx.Var[str],
    on_name: object,
    category: rx.Var[str],
    on_category: object,
    description: rx.Var[str],
    on_description: object,
    price: rx.Var[str],
    on_price: object,
    currency: rx.Var[str],
    on_currency: object,
    name_autofocus: bool = False,
) -> rx.Component:
    """The same fields for creating and for editing a product."""
    return rx.vstack(
        # name and category share a row from `md` (request 2026-10-22: the form read as
        # a plain stack of full-width fields); the description keeps the whole width
        rx.grid(
            _field(
                "Nombre",
                rx.input(
                    value=name,
                    on_change=on_name,
                    placeholder="Ej.: Shawarma mixto",
                    width="100%",
                    auto_focus=name_autofocus,
                ),
                "Es lo único obligatorio.",
            ),
            _field(
                "Categoría",
                rx.input(
                    value=category,
                    on_change=on_category,
                    placeholder="Ej.: shawarmas, helados, combos",
                    width="100%",
                ),
                "Agrupa productos parecidos.",
            ),
            columns=rx.breakpoints(initial="1", md="2"),
            spacing="3",
            width="100%",
        ),
        _field(
            "Descripción",
            rx.text_area(
                value=description,
                on_change=on_description,
                placeholder="Qué lleva, para quién es, qué lo hace distinto.",
                rows="3",
                width="100%",
            ),
            "Nos ayuda a escribir el texto de la publicación. No se copia tal cual.",
        ),
        _price_field(price, on_price, currency, on_currency),
        spacing="3",
        width="100%",
        align_items="start",
    )


# -- Agregar producto --------------------------------------------------------------------


def _photo_step() -> rx.Component:
    """① La foto: one big tap target that opens the phone's camera or gallery. No
    «arrastra», no «haz clic», no formats — those only appear when a file is refused."""
    return rx.vstack(
        dropzone(
            rx.vstack(
                rx.icon("camera", size=T.ICON_LG, color=T.TEXT_MUTED),
                rx.text(
                    "Toca para tomar una foto o elegirla de tu galería",
                    size="3",
                    weight="medium",
                    text_align="center",
                ),
                rx.text(
                    "Fotos o videos cortos (hasta 15 segundos).",
                    size="2",
                    text_align="center",
                    color=T.TEXT_MUTED,
                ),
                align="center",
                spacing="2",
                padding_y="1.5rem",
            ),
            upload_id="catalog_new_media",
            accept=MEDIA_ACCEPT,
            multiple=True,
            max_files=12,
            on_drop=CatalogState.handle_new_media(rx.upload_files(upload_id="catalog_new_media")),
            on_drop_rejected=CatalogState.new_media_rejected,
        ),
        rx.cond(
            CatalogState.new_media_error != "",
            callout(CatalogState.new_media_error, "error"),
        ),
        rx.cond(
            CatalogState.new_previews.length() > 0,
            rx.box(
                rx.foreach(CatalogState.new_previews, _new_file_tile),
                display="grid",
                grid_template_columns="repeat(auto-fill, minmax(8.5rem, 1fr))",
                gap="0.6rem",
                width="100%",
            ),
        ),
        spacing="3",
        width="100%",
    )


def _name_step() -> rx.Component:
    """② ¿Cómo se llama?: the name (the only must) and the price; category and
    description wait behind «Más detalles». Every field keeps what was typed when the
    owner goes back to the photo (N6)."""
    return rx.vstack(
        _field(
            "Nombre",
            rx.input(
                value=CatalogState.new_name,
                on_change=CatalogState.set_new_name,
                placeholder="Ej.: Shawarma mixto",
                size="3",
                min_height=_TOUCH_MIN,
                width="100%",
                auto_focus=True,
            ),
            "Es lo único obligatorio.",
        ),
        _price_field(
            CatalogState.new_price,
            CatalogState.set_new_price,
            CatalogState.new_currency,
            CatalogState.set_new_currency,
        ),
        rx.button(
            rx.cond(
                CatalogState.new_details_open,
                rx.icon("chevron-up", size=T.ICON_SM),
                rx.icon("chevron-down", size=T.ICON_SM),
            ),
            "Más detalles",
            variant="ghost",
            color_scheme="gray",
            size="3",
            type="button",
            min_height=_TOUCH_MIN,
            on_click=CatalogState.toggle_new_details,
            aria_expanded=rx.cond(CatalogState.new_details_open, "true", "false"),
        ),
        rx.cond(
            CatalogState.new_details_open,
            rx.vstack(
                _field(
                    "Categoría",
                    rx.input(
                        value=CatalogState.new_category,
                        on_change=CatalogState.set_new_category,
                        placeholder="Ej.: shawarmas, helados, combos",
                        size="3",
                        min_height=_TOUCH_MIN,
                        width="100%",
                    ),
                    "Agrupa productos parecidos.",
                ),
                _field(
                    "Descripción",
                    rx.text_area(
                        value=CatalogState.new_description,
                        on_change=CatalogState.set_new_description,
                        placeholder="Qué lleva, para quién es, qué lo hace distinto.",
                        rows="3",
                        size="3",
                        width="100%",
                    ),
                    "Nos ayuda a escribir el texto de la publicación. No se copia tal cual.",
                ),
                spacing="3",
                width="100%",
            ),
        ),
        rx.cond(
            CatalogState.form_error != "",
            rx.text(CatalogState.form_error, size="2", color=T.tone_color("error", 11)),
        ),
        spacing="4",
        width="100%",
        align_items="start",
    )


def _done_step() -> rx.Component:
    """③ Listo: what happened, what is still missing, and the two next moves."""
    return rx.vstack(
        callout(
            "«" + CatalogState.created_name + "» ya está en tus productos.",
            "ok",
        ),
        rx.cond(
            ~CatalogState.created_has_media,
            rx.hstack(
                tone_badge(MISSING_PHOTO, "warn", icon="camera"),
                rx.text(
                    "Súbele una foto para poder usarlo en tus publicaciones.",
                    size="2",
                    color=T.TEXT_MUTED,
                ),
                spacing="2",
                align="center",
                wrap="wrap",
            ),
        ),
        rx.cond(CatalogState.uploading, _upload_progress()),
        rx.cond(
            CatalogState.created_has_media & (CatalogState.upload_error != ""),
            callout(CatalogState.upload_error, "error"),
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _photo_step_next(big: dict[str, str]) -> rx.Component:
    """① Foto's verb: «Siguiente» with photos, «Sin foto por ahora» without."""
    return rx.cond(
        CatalogState.new_previews.length() > 0,
        rx.button(
            "Siguiente",
            rx.icon("arrow-right", size=T.ICON_SM),
            type="button",
            on_click=CatalogState.next_new_step,
            **big,
        ),
        rx.button(
            "Sin foto por ahora",
            rx.icon("arrow-right", size=T.ICON_SM),
            variant="soft",
            color_scheme="gray",
            type="button",
            on_click=CatalogState.next_new_step,
            **big,
        ),
    )


def _new_product_footer() -> rx.Component:
    """One column of full-width buttons on a phone, the verb last (§7)."""
    big = {"size": "3", "min_height": _TOUCH_MIN, "width": "100%"}
    return rx.box(
        rx.match(
            CatalogState.new_step,
            (
                STEP_PHOTO,
                rx.fragment(
                    # Coming from a publication (m-24842973, N4): the soft way back,
                    # naming its destination, before the verb (§7).
                    rx.cond(
                        CatalogState.returning,
                        rx.link(
                            rx.button(
                                rx.icon("arrow-left", size=T.ICON_SM),
                                RETURN_WITHOUT_LABEL,
                                variant="soft",
                                color_scheme="gray",
                                type="button",
                                **big,
                            ),
                            href=CatalogState.return_to,
                            width="100%",
                        ),
                    ),
                    _photo_step_next(big),
                ),
            ),
            (
                STEP_NAME,
                rx.fragment(
                    rx.button(
                        rx.icon("arrow-left", size=T.ICON_SM),
                        "Atrás",
                        variant="soft",
                        color_scheme="gray",
                        type="button",
                        on_click=CatalogState.back_new_step,
                        **big,
                    ),
                    rx.button(
                        rx.icon("check", size=T.ICON_SM),
                        "Guardar producto",
                        type="button",
                        on_click=CatalogState.submit_new_product,
                        loading=CatalogState.saving,
                        disabled=CatalogState.new_name.strip() == "",
                        **big,
                    ),
                ),
            ),
            (
                STEP_DONE,
                rx.fragment(
                    rx.button(
                        rx.icon("plus", size=T.ICON_SM),
                        "Agregar otro producto",
                        variant="soft",
                        type="button",
                        on_click=CatalogState.add_another_product,
                        **big,
                    ),
                    # Live only once the photos are in; while they upload it says so;
                    # with no photo (or a failed upload) it leads straight to adding one.
                    rx.cond(
                        CatalogState.created_ready,
                        rx.link(
                            rx.button(
                                rx.icon(
                                    rx.cond(CatalogState.returning, "arrow-left", "sparkles"),
                                    size=T.ICON_SM,
                                ),
                                # m-24842973 (N4): back to the publication the owner left,
                                # with this product chosen and their step as they left it
                                rx.cond(CatalogState.returning, RETURN_LABEL, "Crear publicación"),
                                type="button",
                                **big,
                            ),
                            href=CatalogState.created_href,
                            width="100%",
                        ),
                        rx.cond(
                            CatalogState.created_preparing,
                            rx.button(
                                rx.icon("hourglass", size=T.ICON_SM),
                                "Preparando tu foto…",
                                type="button",
                                disabled=True,
                                **big,
                            ),
                            rx.button(
                                rx.icon("camera", size=T.ICON_SM),
                                "Subirle una foto",
                                type="button",
                                on_click=CatalogState.upload_photo_for_created,
                                **big,
                            ),
                        ),
                    ),
                ),
            ),
        ),
        display="grid",
        grid_template_columns=rx.breakpoints(initial="minmax(0, 1fr)", sm="repeat(2, 1fr)"),
        gap="0.75rem",
        width="100%",
    )


def _new_product_drawer() -> rx.Component:
    """«Agregar producto» in three steps (m-24842974), in the system's drawer: the whole
    screen on a phone, a panel on the right on a computer. The stepper only shows where
    the owner is; «Atrás» and «Siguiente» are the targets (≥ 44 px, N12)."""
    return drawer(
        rx.vstack(
            flow_sync("producto", CatalogState.new_step + 1, ready=CatalogState.flow_ready),
            rx.box(
                stepper(
                    list(NEW_PRODUCT_STEPS),
                    current=CatalogState.new_step,
                    completed=CatalogState.new_steps_done,
                    icons=list(NEW_PRODUCT_STEP_ICONS),
                ),
                class_name="q-stepper-wrap",
                # On a phone «Paso N de 3» and the heading say where the owner is: the
                # bar would push the tap area below the fold.
                display=rx.breakpoints(initial="none", sm="block"),
            ),
            # m-24842973 (N4): saving takes the owner back to the publication they left
            rx.cond(
                CatalogState.returning & (CatalogState.new_step != STEP_DONE),
                callout(RETURN_HINT, "info", icon="arrow-left"),
            ),
            rx.match(
                CatalogState.new_step,
                (STEP_PHOTO, _photo_step()),
                (STEP_NAME, _name_step()),
                (STEP_DONE, _done_step()),
                _photo_step(),
            ),
            spacing="4",
            width="100%",
        ),
        open=CatalogState.form_open,
        on_open_change=CatalogState.set_form_open,
        title="Agregar producto",
        step=rx.vstack(
            step_progress(CatalogState.new_step + 1, len(NEW_PRODUCT_STEPS)),
            rx.text(CatalogState.new_step_title, size="2", weight="medium"),
            spacing="1",
            width="100%",
        ),
        description="La foto, el nombre y listo. Lo demás lo puedes completar después.",
        footer=_new_product_footer(),
        width="34rem",
        icon="package-plus",
    )


def _new_file_tile(row: rx.Var[dict[str, str]], index: rx.Var[int]) -> rx.Component:
    """One file waiting in the form, as the editor will show it (request 2026-10-22: the
    picture, not its name): the thumbnail — or the kit's frame with a clip / file glyph —
    and under it «Quitar», which takes it out before anything is uploaded. The phone's
    file name is never shown (it means nothing to the owner); it stays for screen readers."""
    return rx.box(
        media_thumb(
            rx.get_upload_url(row["key"]),
            has=row["kind"] == "image",
            size=None,
            width="100%",
            height="6.5rem",
            alt=row["name"],
            icon=rx.cond(row["kind"] == "video", "film", "file-image"),
        ),
        rx.hstack(
            rx.spacer(),
            rx.button(
                rx.icon("x", size=T.ICON_SM),
                rx.text("Quitar", size="1"),
                variant="ghost",
                color_scheme="gray",
                size="3",
                type="button",
                min_width=_TOUCH_MIN,
                min_height=_TOUCH_MIN,
                on_click=CatalogState.remove_new_file(index),
                aria_label="Quitar " + row["name"],
            ),
            class_name="q-catalog-tile-foot",
            align="center",
            spacing="1",
            width="100%",
        ),
        class_name="q-catalog-tile",
        key=row["key"] + row["name"],
        width="100%",
    )


# -- the editor -----------------------------------------------------------------------------


#: The ranking's pointer script (`ui.asset_script`), run when the editor mounts; it
#: guards against running twice, so the head copy in Qualify.py never stacks listeners.
_RANK_DRAG_JS = asset_script("rank-drag.js")
_ORDER_HINT = (
    "Mantén pulsada la imagen de una foto y arrástrala para cambiar el orden: "
    "la primera es la principal."
)


def _media_tile(item: rx.Var[ProductMediaVM]) -> rx.Component:
    """One picture or clip: the image fills the tile, «Principal» sits in its corner,
    and under it the format and the two actions in words, «Principal» and «Quitar»
    (m-24842977); «Quitar» asks first."""
    src = rx.get_upload_url(item.key)
    return DragCard.create(
        rx.box(
            rx.cond(
                item.media_type == "video",
                rx.box(
                    rx.video(src=src, controls=True, muted=True, width="100%", height="100%"),
                    class_name="q-catalog-video",
                ),
                media_thumb(
                    src,
                    size=None,
                    width="100%",
                    height="var(--q-catalog-thumb-h, 8rem)",
                    alt=item.filename,
                ),
            ),
            rx.cond(
                item.is_primary,
                rx.box(
                    tone_badge("Principal", "accent", icon="star"),
                    position="absolute",
                    top="0.45rem",
                    left="0.45rem",
                ),
            ),
            position="relative",
            width="100%",
        ),
        # Under the picture, on a solid surface (request 2026-10-22: over a dark photo the
        # words vanished): the format, then the two actions as words, each its own
        # full-width row of 44 px with a gap between them, so a thumb on a phone never
        # hits «Quitar» when it meant «Principal» (m-24842977).
        rx.vstack(
            rx.text(
                rx.cond(item.media_type == "video", "Video", "Foto"),
                rx.cond(item.meta_label != "", rx.text.span(" · ", item.meta_label), ""),
                size="1",
                color=T.TEXT_MUTED,
                class_name="q-nums",
            ),
            rx.cond(
                (item.media_type == "image") & ~item.is_primary,
                rx.button(
                    rx.icon("star", size=T.ICON_SM),
                    MAKE_PRIMARY,
                    variant="soft",
                    size="2",
                    type="button",
                    min_height=_TOUCH_MIN,
                    width="100%",
                    # «Hacer principal» may wrap to two lines on a narrow tile at 360 px.
                    white_space="normal",
                    line_height="1.2",
                    on_click=CatalogState.make_primary(item.media_id),
                    disabled=CatalogState.media_busy,
                    aria_label="Hacer principal " + item.filename,
                ),
            ),
            rx.button(
                rx.icon("trash-2", size=T.ICON_SM),
                REMOVE_MEDIA,
                variant="soft",
                size="2",
                type="button",
                min_height=_TOUCH_MIN,
                width="100%",
                on_click=CatalogState.ask_remove_media(item.media_id),
                disabled=CatalogState.media_busy,
                aria_label="Quitar " + item.filename,
                **T.tone_scheme("error"),
            ),
            class_name="q-catalog-tile-foot",
            spacing="2",
            width="100%",
            align_items="stretch",
        ),
        # `.q-rank-card` is what the drag script moves; `.q-catalog-tile` its look here
        class_name="q-rank-card q-catalog-tile",
        custom_attrs={
            "data-rank-group": "catalog-media",
            "data-rank-key": item.media_id,
            "role": "listitem",
            "aria-label": item.filename,
        },
        on_drag_start=CatalogState.media_pick(item.media_id),
        on_drop=CatalogState.media_drop(item.media_id),
        key=item.media_id,
        width="100%",
    )


def _upload_zone() -> rx.Component:
    return dropzone(
        rx.vstack(
            rx.icon("image-up", size=T.ICON_MD, color=T.TEXT_FAINT),
            rx.text(
                "Toca para tomar una foto o elegirla de tu galería",
                size="1",
                text_align="center",
                color=T.TEXT_MUTED,
            ),
            rx.text(
                "Fotos o videos cortos (hasta 15 segundos).",
                size="1",
                text_align="center",
                color=T.TEXT_FAINT,
            ),
            align="center",
            spacing="1",
        ),
        upload_id="catalog_media",
        accept=MEDIA_ACCEPT,
        multiple=True,
        max_files=12,
        on_drop=CatalogState.handle_media_upload(rx.upload_files(upload_id="catalog_media")),
        on_drop_rejected=CatalogState.media_rejected,
        variant="compact",
    )


def _upload_progress() -> rx.Component:
    """The running ingest: in the editor's media block while a product is open, and at
    page level when the files dropped in the «Agregar producto» form follow a product
    whose editor is not open."""
    return rx.vstack(
        progress_panel(
            CatalogState.upload_label,
            "Acomodando cada foto para que se vea bien. Puedes seguir usando la pantalla.",
            value=CatalogState.upload_progress,
        ),
        rx.text(
            CatalogState.upload_current,
            size="1",
            color=T.TEXT_FAINT,
            text_align="center",
            class_name="q-mono",
        ),
        spacing="1",
        width="100%",
        align="center",
    )


def _media_block() -> rx.Component:
    product = CatalogState.selected
    return rx.vstack(
        rx.hstack(
            rx.icon("images", size=T.ICON_SM, color=T.TEXT_MUTED),
            rx.text("Fotos y videos", size="2", weight="medium"),
            rx.text(product.counts_label, size="1", color=T.TEXT_MUTED),
            rx.spacer(),
            rx.text("Puedes subir hasta 12", size="1", color=T.TEXT_FAINT),
            width="100%",
            align="center",
            spacing="2",
        ),
        rx.cond(CatalogState.uploading, _upload_progress(), _upload_zone()),
        rx.cond(
            CatalogState.upload_error != "",
            rx.text(CatalogState.upload_error, size="1", color=T.tone_color("error", 11)),
        ),
        rx.cond(
            product.media.length() > 0,
            # as many small tiles as fit: each one a thumbnail, never a quarter of the
            # screen (request 2026-10-22)
            rx.vstack(
                rx.box(
                    rx.foreach(product.media, _media_tile),
                    display="grid",
                    grid_template_columns="repeat(auto-fill, minmax(8.5rem, 1fr))",
                    gap="0.6rem",
                    width="100%",
                    role="list",
                ),
                rx.text(_ORDER_HINT, size="1", color=T.TEXT_FAINT),
                rx.box(display="none", on_mount=rx.call_script(_RANK_DRAG_JS)),
                spacing="2",
                width="100%",
                align_items="start",
            ),
            rx.text(
                "Todavía no tiene fotos. La primera que subas queda como principal.",
                size="1",
                color=T.TEXT_FAINT,
            ),
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _create_with_product_button(product: rx.Var[ProductVM]) -> rx.Component:
    """The editor's «Crear publicación con este producto» (m-24842972): soft, in the
    editor's footer above «Guardar cambios», a real link to `/create?producto=<id>` so
    the generator opens with this product chosen. Off with its reason said under it
    («Primero súbele una foto», never hover-only, N12) while the product has no photo.
    When the owner came from a publication (`?volver=`, m-24842973) it says «Volver a tu
    publicación» and goes back there with this product chosen (N4)."""
    label = rx.cond(CatalogState.returning, RETURN_LABEL, "Crear publicación con este producto")
    icon = rx.icon(rx.cond(CatalogState.returning, "arrow-left", "sparkles"), size=T.ICON_SM)
    big = {"size": "3", "min_height": _TOUCH_MIN, "width": "100%"}
    return rx.vstack(
        rx.cond(
            product.photo_count > 0,
            rx.link(
                rx.button(
                    icon,
                    label,
                    variant="soft",
                    type="button",
                    **big,
                ),
                href=CatalogState.selected_create_href,
                width="100%",
            ),
            rx.button(
                icon,
                label,
                variant="soft",
                type="button",
                disabled=True,
                **big,
            ),
        ),
        rx.cond(
            product.photo_count == 0,
            rx.text(
                rx.cond(CatalogState.uploading, SAVING_PHOTOS_REASON, NEEDS_PHOTO_REASON),
                size="1",
                color=T.TEXT_MUTED,
                width="100%",
                text_align="center",
            ),
        ),
        spacing="1",
        width="100%",
        grid_column="1 / -1",
    )


def _editor_body() -> rx.Component:
    """The selected product in its drawer: what it carries (price, photos), then the
    fields, then its media — one column, so it reads the same at 360 px and on a
    computer."""
    product = CatalogState.selected
    return rx.vstack(
        rx.hstack(
            media_thumb(
                rx.get_upload_url(product.primary_photo_key),
                has=product.primary_photo_key != "",
                size="3.25rem",
                alt=product.name,
                icon="package",
            ),
            rx.hstack(
                rx.cond(
                    product.price_label != "",
                    tone_badge(product.price_label, "ok", icon="tag"),
                ),
                rx.cond(
                    product.photo_count == 0,
                    tone_badge(MISSING_PHOTO, "warn", icon="camera"),
                    tone_badge(product.counts_label, "neutral"),
                ),
                spacing="2",
                align="center",
                wrap="wrap",
                min_width="0",
            ),
            width="100%",
            align="center",
            spacing="3",
        ),
        rx.vstack(
            rx.hstack(
                rx.icon("pencil-line", size=T.ICON_SM, color=T.TEXT_MUTED),
                rx.text("Datos del producto", size="2", weight="medium"),
                spacing="2",
                align="center",
            ),
            _product_fields(
                name=CatalogState.edit_name,
                on_name=CatalogState.set_edit_name,
                category=CatalogState.edit_category,
                on_category=CatalogState.set_edit_category,
                description=CatalogState.edit_description,
                on_description=CatalogState.set_edit_description,
                price=CatalogState.edit_price,
                on_price=CatalogState.set_edit_price,
                currency=CatalogState.edit_currency,
                on_currency=CatalogState.set_edit_currency,
            ),
            rx.cond(
                CatalogState.edit_error != "",
                callout(CatalogState.edit_error, "error"),
            ),
            spacing="3",
            width="100%",
            align_items="start",
            class_name="q-catalog-panel",
        ),
        rx.vstack(_media_block(), class_name="q-catalog-panel", width="100%"),
        spacing="4",
        width="100%",
        align_items="start",
        key=CatalogState.selected_id,
    )


def _editor_footer() -> rx.Component:
    """«Crear publicación con este producto» across the top (m-24842972), then
    «Eliminar» first and the verb last (§7); one full-width column on a phone (N12)."""
    big = {"size": "3", "min_height": _TOUCH_MIN, "width": "100%"}
    return rx.box(
        rx.cond(
            CatalogState.editor_open,
            _create_with_product_button(CatalogState.selected),
        ),
        # request 2026-10-22: a product can be deleted from here (a dialog first: it
        # leaves every list; the pieces already made keep their provenance)
        rx.button(
            rx.icon("trash-2", size=T.ICON_SM),
            "Eliminar producto",
            variant="soft",
            type="button",
            on_click=CatalogState.ask_delete_product,
            disabled=CatalogState.edit_saving,
            **T.tone_scheme("error"),
            **big,
        ),
        rx.button(
            rx.icon("save", size=T.ICON_SM),
            "Guardar cambios",
            type="button",
            on_click=CatalogState.save_product,
            loading=CatalogState.edit_saving,
            **big,
        ),
        display="grid",
        grid_template_columns=rx.breakpoints(initial="minmax(0, 1fr)", sm="repeat(2, 1fr)"),
        gap="0.75rem",
        width="100%",
    )


def _editor_drawer() -> rx.Component:
    """m-24842976: the product opens in the system's drawer — the whole screen on a
    phone, a panel on the right on a computer. Its ×, Esc and the backdrop all go
    through `request_close`, which asks before dropping unsaved changes."""
    return drawer(
        rx.cond(CatalogState.editor_open, _editor_body()),
        open=CatalogState.editor_open,
        on_open_change=CatalogState.set_editor_open,
        title=CatalogState.edit_title,
        description="Los cambios se guardan al tocar «Guardar cambios». Las fotos, al subirlas.",
        footer=_editor_footer(),
        width="40rem",
        icon="package",
    )


def _leave_dialog() -> rx.Component:
    """«¿Salir sin guardar?» (DS §6.2, m-24842976): the safe answer («Volver») first
    and on Esc, «Guardar y salir» as the verb, and leaving without the changes as the
    destructive one. Stacked full-width on a phone (N12)."""
    big = {"size": "3", "min_height": _TOUCH_MIN, "width": "100%"}
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title(LEAVE_TITLE),
            rx.alert_dialog.description(CatalogState.leave_text, size="2"),
            rx.box(
                rx.alert_dialog.cancel(
                    rx.button(
                        rx.icon("arrow-left", size=T.ICON_SM),
                        LEAVE_STAY,
                        variant="soft",
                        color_scheme="gray",
                        type="button",
                        **big,
                    ),
                ),
                rx.button(
                    rx.icon("trash-2", size=T.ICON_SM),
                    LEAVE_DISCARD,
                    variant="soft",
                    type="button",
                    on_click=CatalogState.discard_and_leave,
                    **T.tone_scheme("error"),
                    **big,
                ),
                rx.button(
                    rx.icon("save", size=T.ICON_SM),
                    LEAVE_SAVE,
                    type="button",
                    on_click=CatalogState.save_and_leave,
                    **big,
                ),
                display="grid",
                grid_template_columns=rx.breakpoints(
                    initial="minmax(0, 1fr)", sm="repeat(3, minmax(0, 1fr))"
                ),
                gap="0.75rem",
                margin_top="1.25rem",
                width="100%",
            ),
            max_width="34rem",
        ),
        open=CatalogState.leave_open,
        on_open_change=CatalogState.set_leave_open,
    )


def _delete_product_dialog() -> rx.Component:
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title("¿Eliminar este producto?"),
            rx.alert_dialog.description(
                "«" + CatalogState.delete_product_name + "» ya no aparecerá para crear "
                "publicaciones. Las publicaciones que ya hiciste con él no cambian.",
                size="2",
            ),
            rx.flex(
                rx.alert_dialog.cancel(
                    rx.button(
                        rx.icon("arrow-left", size=15),
                        "Volver",
                        variant="soft",
                        color_scheme="gray",
                        size="3",
                        min_height=_TOUCH_MIN,
                    ),
                ),
                rx.alert_dialog.action(
                    rx.button(
                        rx.icon("trash-2", size=15),
                        "Sí, eliminar",
                        size="3",
                        min_height=_TOUCH_MIN,
                        on_click=CatalogState.confirm_delete_product,
                        **T.tone_scheme("error"),
                    ),
                ),
                justify="end",
                gap="0.75rem",
                margin_top="1.25rem",
                wrap="wrap",
            ),
            max_width="28rem",
        ),
        open=CatalogState.delete_product_name != "",
        on_open_change=CatalogState.set_delete_product_open,
    )


def _remove_media_dialog() -> rx.Component:
    """«¿Quitar esta foto?» (m-24842977): «Volver» first and on Esc, «Sí, quitar» as
    the destructive verb. Stacked full-width on a phone (N12)."""
    big = {"size": "3", "min_height": _TOUCH_MIN, "width": "100%"}
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title(CatalogState.remove_media_title_text),
            rx.alert_dialog.description(CatalogState.remove_media_text, size="2"),
            rx.box(
                rx.alert_dialog.cancel(
                    rx.button(
                        rx.icon("arrow-left", size=T.ICON_SM),
                        REMOVE_STAY,
                        variant="soft",
                        color_scheme="gray",
                        type="button",
                        **big,
                    ),
                ),
                rx.alert_dialog.action(
                    rx.button(
                        rx.icon("trash-2", size=T.ICON_SM),
                        REMOVE_CONFIRM,
                        type="button",
                        on_click=CatalogState.confirm_remove_media,
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
        open=CatalogState.remove_media_open,
        on_open_change=CatalogState.set_remove_media_open,
    )


# -- the grid -------------------------------------------------------------------------------


def _thumb(product: rx.Var[ProductVM]) -> rx.Component:
    return media_thumb(
        rx.get_upload_url(product.primary_photo_key),
        has=product.primary_photo_key != "",
        size=None,
        width="100%",
        height="var(--q-catalog-thumb-h, 9.5rem)",
        alt=product.name,
        icon="image-off",
        icon_size=T.ICON_LG,
    )


def _product_card(product: rx.Var[ProductVM]) -> rx.Component:
    """m-24842976: the card is a real ``<button>`` on the system's choice-card material
    (the same `.q-choice-card` look as `ui.choice_card`, without its radio role: a tap
    here opens, it does not choose), announced as «Editar {producto}», with «Editar»
    written on it — nothing depends on hovering."""
    selected = CatalogState.selected_id == product.product_id
    return rx.el.button(
        rx.vstack(
            _thumb(product),
            rx.text(
                product.name,
                size="3",
                weight="medium",
                overflow="hidden",
                text_overflow="ellipsis",
                white_space="nowrap",
                min_width="0",
                width="100%",
            ),
            rx.hstack(
                rx.cond(product.category != "", tag(product.category)),
                # m-24803289: the price the pieces of this product will print, so the
                # operator sees at a glance which products carry one
                rx.cond(
                    product.price_label != "",
                    tone_badge(product.price_label, "ok", icon="tag"),
                ),
                rx.spacer(),
                rx.cond(
                    product.photo_count == 0,
                    tone_badge(MISSING_PHOTO, "warn", icon="camera"),
                    rx.text(
                        product.counts_label,
                        size="1",
                        color=T.TEXT_MUTED,
                        class_name="q-nums",
                        white_space="nowrap",
                    ),
                ),
                # m-24803289: the row wraps instead of pushing past the card's edge
                # when tag + price + counts are wider than the grid's column.
                wrap="wrap",
                width="100%",
                min_width="0",
                align="center",
                row_gap="0.35rem",
            ),
            rx.hstack(
                rx.icon("pencil", size=T.ICON_SM),
                rx.text("Editar", size="2", weight="medium"),
                spacing="1",
                align="center",
                color=T.tone_color("accent", 11),
                aria_hidden="true",
            ),
            spacing="2",
            width="100%",
            min_width="0",
            align_items="start",
        ),
        type="button",
        aria_label="Editar " + product.name,
        aria_current=rx.cond(selected, "true", "false"),
        on_click=CatalogState.select_product(product.product_id),
        class_name=rx.cond(selected, "q-choice-card q-choice-card--on", "q-choice-card"),
        padding="0.75rem",
        min_width="0",
        key=product.product_id,
    )


def _grid() -> rx.Component:
    return rx.grid(
        rx.foreach(CatalogState.visible_products, _product_card),
        columns=rx.breakpoints(initial="1", sm="2", md="3", lg="4"),
        spacing="3",
        width="100%",
    )


def _missing_photo_filter() -> rx.Component:
    """«Ver los 2 sin foto» narrows the list to what still needs a photo; «Ver todos
    los productos» brings it back (m-24842977). 44 px, full width on a phone. The label
    already says what a tap does, so no `aria-pressed`; the warn tone only while it
    invites the owner to finish, neutral once the filter is on."""
    return rx.cond(
        CatalogState.show_missing_filter,
        rx.button(
            rx.cond(
                CatalogState.missing_filter_on,
                rx.icon("list", size=T.ICON_SM),
                rx.icon("camera", size=T.ICON_SM),
            ),
            CatalogState.missing_filter_label,
            variant="soft",
            size="2",
            type="button",
            min_height=_TOUCH_MIN,
            width=rx.breakpoints(initial="100%", sm="auto"),
            on_click=CatalogState.toggle_missing_photo,
            color_scheme=rx.cond(
                CatalogState.missing_filter_on, T.tone_scale("neutral"), T.tone_scale("warn")
            ),
        ),
    )


def _empty() -> rx.Component:
    return empty_state(
        "package",
        "Aún no tienes productos",
        "Sube tu primer producto con dos o más fotos reales: con eso ya puedes crear "
        "publicaciones e historias que se ven como lo que vendes.",
        rx.button(
            rx.icon("plus", size=T.ICON_SM),
            "Agregar producto",
            size="2",
            on_click=CatalogState.open_form,
        ),
    )


def _loading() -> rx.Component:
    return rx.grid(
        *[skeleton_card(lines=3) for _ in range(4)],
        columns=rx.breakpoints(initial="1", sm="2", md="3", lg="4"),
        spacing="3",
        width="100%",
        aria_busy="true",
    )


def catalog_index() -> rx.Component:
    return app_shell(
        route_history(
            CatalogState.enter_history,
            ack=CatalogState.history_ack,
            on_leave=CatalogState.leave_flow,
        ),
        page_header(
            "Tus productos",
            "Sube la foto real de lo que vendes y úsala en tus publicaciones.",
            rx.button(
                rx.icon("plus", size=T.ICON_SM),
                "Agregar producto",
                size="2",
                on_click=CatalogState.open_form,
            ),
            badge=rx.cond(
                CatalogState.has_products,
                tone_badge(CatalogState.product_count_label, "neutral"),
                rx.fragment(),
            ),
        ),
        page_body(
            rx.cond(CatalogState.error != "", callout(CatalogState.error, "error")),
            # No brand yet: the error names the step, this is the way to it (m-24842971).
            rx.cond(
                CatalogState.needs_brand,
                rx.link(
                    rx.button(
                        rx.icon("palette", size=T.ICON_SM),
                        "Completar mi marca",
                        size="2",
                        variant="soft",
                    ),
                    href="/brand",
                ),
            ),
            # The ingest of the files dropped in the form runs with no editor open:
            # its progress and its failures show here, not in a panel nobody sees.
            rx.cond(
                CatalogState.uploading & (CatalogState.selected_id == ""),
                card(_upload_progress(), padding="1rem 1.25rem"),
            ),
            rx.cond(
                (CatalogState.upload_error != "") & (CatalogState.selected_id == ""),
                callout(CatalogState.upload_error, "error"),
            ),
            # m-24842973 (N4): came from a publication and closed the form — one soft
            # way back that names its destination (N7)
            rx.cond(
                CatalogState.returning & ~CatalogState.form_open,
                rx.link(
                    rx.button(
                        rx.icon("arrow-left", size=T.ICON_SM),
                        RETURN_LABEL,
                        variant="soft",
                        color_scheme=T.tone_scale("neutral"),
                        size="3",
                        min_height=_TOUCH_MIN,
                    ),
                    href=CatalogState.return_to,
                ),
            ),
            _new_product_drawer(),
            _editor_drawer(),
            _leave_dialog(),
            _delete_product_dialog(),
            _remove_media_dialog(),
            rx.cond(
                CatalogState.loading,
                _loading(),
                rx.cond(
                    CatalogState.has_products,
                    section(
                        "Productos",
                        _missing_photo_filter(),
                        _grid(),
                        description="Toca uno para editarlo y subirle fotos.",
                    ),
                    _empty(),
                ),
            ),
        ),
    )

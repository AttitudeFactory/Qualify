"""/catalog — Catálogo de productos (plan-mvp-plantillas-remotion.md §2.1 #1).

The screen where the founder puts the real products of a brand with their real photos
and short clips — the one input the template engine cannot invent. Three blocks on one
page, design-system §9.1 (`app_shell(page_header, page_body)`):

1. **Nuevo producto** — a card with the form (name, category, description). Opens
   from the header's one solid action. No price: the founder dropped it from the
   catalog (2026-10-19); prices already stored stay in the DB, unused by this screen.
2. **The editor** of the selected product — its fields, and its media: an upload zone
   that takes photos AND short videos (both normalized at upload by the service), the
   tiles with a "Principal" badge, "Hacer principal" and "Quitar".
3. **The grid** of products as cards: primary photo, name, category, counts.

Media keys render through `rx.get_upload_url`, like every upload the generator makes:
the catalog writes to the same store (`catalog_provider`).
"""

from __future__ import annotations

import reflex as rx

from .catalog_state import CatalogState
from .catalog_vm import (
    CURRENCY_OPTIONS,
    MEDIA_ACCEPT,
    NO_CURRENCY,
    ProductMediaVM,
    ProductVM,
)
from .ui import (
    app_shell,
    callout,
    card,
    dropzone,
    empty_state,
    media_thumb,
    page_body,
    page_header,
    progress_panel,
    section,
    skeleton_card,
    tag,
    tone_badge,
)
from .ui import tokens as T


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
                width="100%",
            ),
            rx.select(
                list(CURRENCY_OPTIONS),
                value=rx.cond(currency == "", NO_CURRENCY, currency),
                on_change=on_currency,
                width="10rem",
            ),
            spacing="2",
            width="100%",
            align="center",
        ),
        "Opcional. Si lo dejas vacío, las piezas no mostrarán ningún precio; si lo "
        "escribes, se imprime exactamente así.",
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
            "Ayuda a escribir el gancho; no se imprime entera.",
        ),
        _price_field(price, on_price, currency, on_currency),
        spacing="3",
        width="100%",
        align_items="start",
    )


# -- Nuevo producto --------------------------------------------------------------------


def _new_product_form() -> rx.Component:
    return card(
        rx.form(
            rx.vstack(
                rx.hstack(
                    rx.heading("Nuevo producto", size="4", as_="h2"),
                    rx.spacer(),
                    rx.button(
                        rx.icon("x", size=T.ICON_SM),
                        variant="ghost",
                        color_scheme=T.tone_scale("neutral"),
                        size="1",
                        type="button",
                        on_click=CatalogState.close_form,
                        aria_label="Cerrar",
                    ),
                    width="100%",
                    align="center",
                ),
                _product_fields(
                    name=CatalogState.new_name,
                    on_name=CatalogState.set_new_name,
                    category=CatalogState.new_category,
                    on_category=CatalogState.set_new_category,
                    description=CatalogState.new_description,
                    on_description=CatalogState.set_new_description,
                    price=CatalogState.new_price,
                    on_price=CatalogState.set_new_price,
                    currency=CatalogState.new_currency,
                    on_currency=CatalogState.set_new_currency,
                    name_autofocus=True,
                ),
                _new_media_field(),
                rx.cond(
                    CatalogState.form_error != "",
                    rx.text(CatalogState.form_error, size="1", color=T.tone_color("error", 11)),
                ),
                rx.hstack(
                    rx.spacer(),
                    rx.button(
                        "Cancelar",
                        variant="ghost",
                        color_scheme=T.tone_scale("neutral"),
                        size="2",
                        type="button",
                        on_click=CatalogState.close_form,
                    ),
                    rx.button(
                        rx.icon("plus", size=T.ICON_SM),
                        "Crear producto",
                        size="2",
                        type="submit",
                        loading=CatalogState.saving,
                        disabled=CatalogState.new_name.strip() == "",
                    ),
                    width="100%",
                    spacing="2",
                ),
                spacing="4",
                width="100%",
                align_items="start",
            ),
            on_submit=CatalogState.submit_new_product,
            reset_on_submit=False,
            width="100%",
        ),
        padding="1.25rem 1.5rem",
    )


def _new_file_chip(name: rx.Var[str], index: rx.Var[int]) -> rx.Component:
    return rx.hstack(
        rx.icon("paperclip", size=12, color=T.TEXT_MUTED),
        rx.text(
            name,
            size="1",
            max_width="12rem",
            white_space="nowrap",
            overflow="hidden",
            text_overflow="ellipsis",
            title=name,
        ),
        rx.icon_button(
            rx.icon("x", size=12),
            variant="ghost",
            color_scheme=T.tone_scale("neutral"),
            size="1",
            type="button",
            on_click=CatalogState.remove_new_file(index),
            aria_label="Quitar " + name,
        ),
        spacing="1",
        align="center",
        padding="0.1rem 0.25rem 0.1rem 0.5rem",
        border=T.BORDER,
        border_radius="999px",
    )


def _new_media_field() -> rx.Component:
    """Photos and videos right in the form (§ request 2026-10-19: «no me deja poner la
    imagen de una vez»): they wait as chips and are processed as soon as the product is
    created — the editor that opens shows their progress."""
    return _field(
        "Fotos y videos",
        rx.vstack(
            dropzone(
                rx.vstack(
                    rx.icon("image-up", size=T.ICON_MD, color=T.TEXT_FAINT),
                    rx.text(
                        "Arrastra fotos y videos cortos del producto, o haz clic",
                        size="1",
                        text_align="center",
                        color=T.TEXT_MUTED,
                    ),
                    rx.text(
                        "JPG, PNG, HEIC · MP4, MOV (hasta 15 s). Se procesan al crear el producto.",
                        size="1",
                        text_align="center",
                        color=T.TEXT_FAINT,
                    ),
                    align="center",
                    spacing="1",
                ),
                upload_id="catalog_new_media",
                accept=MEDIA_ACCEPT,
                multiple=True,
                max_files=12,
                on_drop=CatalogState.handle_new_media(
                    rx.upload_files(upload_id="catalog_new_media")
                ),
                variant="compact",
            ),
            rx.cond(
                CatalogState.new_files.length() > 0,
                rx.flex(
                    rx.foreach(CatalogState.new_files, _new_file_chip),
                    wrap="wrap",
                    gap="0.4rem",
                ),
            ),
            spacing="2",
            width="100%",
        ),
    )


# -- the editor -----------------------------------------------------------------------------


def _media_tile(item: rx.Var[ProductMediaVM]) -> rx.Component:
    src = rx.get_upload_url(item.key)
    return rx.box(
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
                    height="var(--q-catalog-thumb-h, 9.5rem)",
                    alt=item.filename,
                ),
            ),
            rx.cond(
                item.is_primary,
                rx.box(
                    tone_badge("Principal", "accent", icon="star"),
                    position="absolute",
                    top="0.4rem",
                    left="0.4rem",
                ),
            ),
            position="relative",
            width="100%",
        ),
        rx.hstack(
            rx.text(
                rx.cond(item.media_type == "video", "Video", "Foto"),
                rx.cond(item.meta_label != "", rx.text.span(" · ", item.meta_label), ""),
                size="1",
                color=T.TEXT_MUTED,
                class_name="q-nums",
            ),
            rx.spacer(),
            rx.cond(
                (item.media_type == "image") & ~item.is_primary,
                rx.button(
                    rx.icon("star", size=12),
                    "Principal",
                    variant="ghost",
                    size="1",
                    on_click=CatalogState.make_primary(item.media_id),
                    disabled=CatalogState.media_busy,
                    title="Usar como foto principal",
                ),
            ),
            rx.icon_button(
                rx.icon("trash-2", size=12),
                variant="ghost",
                color_scheme=T.tone_scale("neutral"),
                size="1",
                on_click=CatalogState.delete_media(item.media_id),
                disabled=CatalogState.media_busy,
                aria_label="Quitar",
            ),
            width="100%",
            align="center",
            spacing="1",
        ),
        key=item.media_id,
        width="100%",
    )


def _upload_zone() -> rx.Component:
    return dropzone(
        rx.vstack(
            rx.icon("image-up", size=T.ICON_MD, color=T.TEXT_FAINT),
            rx.text(
                "Arrastra fotos y videos cortos del producto, o haz clic",
                size="1",
                text_align="center",
                color=T.TEXT_MUTED,
            ),
            rx.text(
                "JPG, PNG, HEIC · MP4, MOV (hasta 15 s). Se corrigen y recortan solos.",
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
        variant="compact",
    )


def _media_block() -> rx.Component:
    product = CatalogState.selected
    return rx.vstack(
        rx.hstack(
            rx.text("Fotos y videos", size="2", weight="medium"),
            rx.text(product.counts_label, size="1", color=T.TEXT_MUTED),
            rx.spacer(),
            rx.text("Hasta 12 por producto", size="1", color=T.TEXT_FAINT),
            width="100%",
            align="baseline",
            spacing="2",
        ),
        rx.cond(
            CatalogState.uploading,
            rx.vstack(
                progress_panel(
                    CatalogState.upload_label,
                    "Corrigiendo y recortando cada archivo antes de guardarlo.",
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
            ),
            _upload_zone(),
        ),
        rx.cond(
            CatalogState.upload_error != "",
            rx.text(CatalogState.upload_error, size="1", color=T.tone_color("error", 11)),
        ),
        rx.cond(
            product.media.length() > 0,
            rx.grid(
                rx.foreach(product.media, _media_tile),
                columns=rx.breakpoints(initial="2", sm="3", md="4"),
                spacing="3",
                width="100%",
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


def _editor() -> rx.Component:
    product = CatalogState.selected
    return card(
        rx.vstack(
            rx.hstack(
                rx.vstack(
                    rx.heading(product.name, size="4", as_="h2"),
                    rx.text(product.slug, size="1", color=T.TEXT_FAINT, class_name="q-mono"),
                    spacing="0",
                    align_items="start",
                ),
                rx.spacer(),
                rx.button(
                    rx.icon("x", size=T.ICON_SM),
                    "Cerrar",
                    variant="ghost",
                    color_scheme=T.tone_scale("neutral"),
                    size="1",
                    on_click=CatalogState.close_editor,
                ),
                width="100%",
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
                rx.text(CatalogState.edit_error, size="1", color=T.tone_color("error", 11)),
            ),
            rx.hstack(
                rx.spacer(),
                # soft: the screen's one solid action is "Nuevo producto" (§5.5)
                rx.button(
                    rx.icon("save", size=T.ICON_SM),
                    "Guardar cambios",
                    variant="soft",
                    size="2",
                    on_click=CatalogState.save_product,
                    loading=CatalogState.edit_saving,
                ),
                width="100%",
            ),
            rx.divider(),
            _media_block(),
            spacing="4",
            width="100%",
            align_items="start",
        ),
        padding="1.25rem 1.5rem",
        key=CatalogState.selected_id,
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
    selected = CatalogState.selected_id == product.product_id
    return card(
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
                rx.text(product.counts_label, size="1", color=T.TEXT_MUTED, class_name="q-nums"),
                width="100%",
                align="center",
            ),
            spacing="2",
            width="100%",
            align_items="start",
        ),
        interactive=True,
        on_click=CatalogState.select_product(product.product_id),
        padding="0.75rem",
        # The selected card is ringed and washed in the accent by the sheet
        # (`.q-card[data-selected]`), so it keeps the card material.
        data_selected=rx.cond(selected, "true", "false"),
        key=product.product_id,
        role="button",
        aria_pressed=rx.cond(selected, "true", "false"),
    )


def _grid() -> rx.Component:
    return rx.grid(
        rx.foreach(CatalogState.products, _product_card),
        columns=rx.breakpoints(initial="1", sm="2", md="3", lg="4"),
        spacing="3",
        width="100%",
    )


def _empty() -> rx.Component:
    return empty_state(
        "package",
        "Aún no hay productos",
        "Crea el primero y súbele dos o más fotos reales: con eso una plantilla ya "
        "produce Reel, feed e historia.",
        rx.button(
            rx.icon("plus", size=T.ICON_SM),
            "Nuevo producto",
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
        page_header(
            "Catálogo",
            "Tus productos con sus fotos reales: lo que las plantillas componen.",
            rx.button(
                rx.icon("plus", size=T.ICON_SM),
                "Nuevo producto",
                size="2",
                on_click=CatalogState.open_form,
                disabled=CatalogState.form_open,
            ),
            badge=rx.cond(
                CatalogState.has_products,
                tone_badge(CatalogState.product_count_label, "neutral"),
                rx.fragment(),
            ),
        ),
        page_body(
            rx.cond(CatalogState.error != "", callout(CatalogState.error, "error")),
            rx.cond(
                CatalogState.notice != "",
                callout(CatalogState.notice, "ok", icon="circle-check"),
            ),
            rx.cond(CatalogState.form_open, _new_product_form()),
            rx.cond(CatalogState.selected, _editor()),
            rx.cond(
                CatalogState.loading,
                _loading(),
                rx.cond(
                    CatalogState.has_products,
                    section(
                        "Productos",
                        _grid(),
                        description="Toca uno para editarlo y subirle fotos.",
                    ),
                    rx.cond(~CatalogState.form_open, _empty()),
                ),
            ),
        ),
    )

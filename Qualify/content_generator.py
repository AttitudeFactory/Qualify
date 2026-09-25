"""The content generator (§ request 2026-09-25): the five content kinds and their inputs,
shown on /signals — where the operator tests generation — while /create keeps its
original form. Same `CreativeState` and the same service underneath: a submitted piece
becomes a draft at /drafts/{id}, whose screen shows the video / the carousel and the
script."""

from __future__ import annotations

import reflex as rx

from .creative_state import CreativeState
from .creative_vm import KIND_OPTIONS
from .ui import callout, card
from .ui import tokens as T


def _card(*children: rx.Component, **props) -> rx.Component:
    return card(
        rx.vstack(*children, spacing="3", align_items="start", width="100%"),
        padding="1.25rem 1.5rem",
        **props,
    )


def _objective_button(value: str, label: str) -> rx.Component:
    return rx.button(
        label,
        variant=rx.cond(CreativeState.brief_objective == value, "solid", "soft"),
        color_scheme=rx.cond(CreativeState.brief_objective == value, "grass", "gray"),
        on_click=CreativeState.set_objective(value),
        size="2",
    )


def _intent_button(value: str, label: str) -> rx.Component:
    return rx.button(
        label,
        variant=rx.cond(CreativeState.brief_intent == value, "solid", "soft"),
        color_scheme="gray",
        on_click=CreativeState.set_intent(value),
        size="2",
    )


_IMAGE_ACCEPT = {"image/*": [".png", ".jpg", ".jpeg", ".webp"]}


def _kind_card(key: str, title: str, blurb: str, icon: str) -> rx.Component:
    """One content kind (§ request 2026-09-25). `template` is shown but not selectable
    yet — declared, with its badge, so the operator knows it is coming."""
    selected = CreativeState.brief_kind == key
    enabled = key != "template"
    return rx.box(
        rx.hstack(
            rx.icon(icon, size=20, color=rx.cond(selected, rx.color("accent", 10), T.TEXT_FAINT)),
            rx.vstack(
                rx.hstack(
                    rx.text(title, size="2", weight="medium"),
                    rx.badge("Próximamente", color_scheme="gray", variant="soft", size="1")
                    if not enabled
                    else rx.fragment(),
                    spacing="2",
                    align="center",
                ),
                rx.text(blurb, size="1", color=T.TEXT_MUTED),
                spacing="1",
                align_items="start",
            ),
            spacing="3",
            align="start",
        ),
        on_click=CreativeState.choose_kind(key) if enabled else None,
        cursor="pointer" if enabled else "not-allowed",
        opacity="1" if enabled else "0.55",
        padding="0.85rem 1rem",
        border=rx.cond(
            selected, f"1px solid {rx.color('accent', 8)}", f"1px solid {rx.color('gray', 5)}"
        ),
        background=rx.cond(selected, rx.color("accent", 2), rx.color("gray", 2)),
        border_radius="0.75rem",
        width="100%",
    )


def _kind_picker() -> rx.Component:
    return _card(
        rx.text("Tipo de contenido", size="2", weight="medium"),
        rx.grid(
            *(_kind_card(*option) for option in KIND_OPTIONS),
            columns=rx.breakpoints(initial="1", sm="2"),
            spacing="2",
            width="100%",
        ),
    )


def _upload_zone(upload_id: str, label: str, handler: object, *, multiple: bool) -> rx.Component:
    return rx.upload(
        rx.vstack(
            rx.icon("image-up", size=20, color=T.TEXT_FAINT),
            rx.text(label, size="1", text_align="center"),
            align="center",
            spacing="1",
        ),
        id=upload_id,
        accept=_IMAGE_ACCEPT,
        max_files=10 if multiple else 1,
        multiple=multiple,
        on_drop=handler(rx.upload_files(upload_id=upload_id)),
        border=f"1px dashed {rx.color('gray', 7)}",
        border_radius="0.5rem",
        padding="1rem",
        width="100%",
    )


def _file_chip(name: rx.Var[str], on_remove: object) -> rx.Component:
    return rx.badge(
        rx.icon("image", size=12),
        rx.text(name, max_width="14rem", overflow="hidden", text_overflow="ellipsis"),
        rx.el.button(
            rx.icon("x", size=12),
            on_click=on_remove,
            type="button",
            aria_label="Quitar",
            display="flex",
            background="transparent",
            border="none",
            padding="0",
            color="inherit",
            cursor="pointer",
        ),
        variant="surface",
        color_scheme="gray",
        size="2",
        radius="full",
        gap="1",
    )


def _images_section() -> rx.Component:
    """Background and product images — optional for every kind that takes them."""
    return rx.vstack(
        rx.text("Fondo (opcional)", size="2", weight="medium"),
        rx.cond(
            CreativeState.media_background_key != "",
            _file_chip(CreativeState.media_background_name, CreativeState.clear_background),
            _upload_zone(
                "creative_background",
                "Arrastra la imagen de fondo o haz clic",
                CreativeState.handle_background_upload,
                multiple=False,
            ),
        ),
        rx.text("Producto o productos (opcional)", size="2", weight="medium"),
        rx.cond(
            CreativeState.product_items.length() > 0,
            rx.flex(
                rx.foreach(
                    CreativeState.product_items,
                    lambda item: _file_chip(
                        item["name"], CreativeState.remove_product(item["key"])
                    ),
                ),
                wrap="wrap",
                gap="2",
            ),
        ),
        _upload_zone(
            "creative_products",
            "Arrastra una o varias fotos de producto (hasta 10). Con fondo transparente"
            " quedan mejor.",
            CreativeState.handle_product_uploads,
            multiple=True,
        ),
        rx.cond(
            CreativeState.kind_is_flyer,
            rx.hstack(
                rx.switch(
                    checked=CreativeState.media_carousel,
                    on_change=CreativeState.set_media_carousel,
                ),
                rx.text("Hacerlo carrusel: una imagen por producto y un cierre", size="2"),
                spacing="2",
                align="center",
            ),
        ),
        rx.cond(
            CreativeState.upload_error != "",
            rx.text(CreativeState.upload_error, size="1", color=rx.color("tomato", 10)),
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _look_card(look: rx.Var[dict[str, str]]) -> rx.Component:
    selected = CreativeState.avatar_look_id == look["id"]
    return rx.box(
        rx.cond(
            look["preview"] != "",
            rx.image(
                src=look["preview"],
                width="100%",
                height="7.5rem",
                object_fit="cover",
                border_radius="0.5rem",
            ),
            rx.center(rx.icon("user-round", size=28, color=T.TEXT_FAINT), height="7.5rem"),
        ),
        rx.text(look["name"], size="1", text_align="center", margin_top="0.35rem", trim="both"),
        on_click=CreativeState.choose_look(look["id"]),
        cursor="pointer",
        padding="0.4rem",
        border=rx.cond(
            selected, f"2px solid {rx.color('accent', 9)}", f"1px solid {rx.color('gray', 5)}"
        ),
        border_radius="0.6rem",
        width="100%",
    )


def _voice_select() -> rx.Component:
    return rx.vstack(
        rx.text("Voz", size="2", weight="medium"),
        rx.select.root(
            rx.select.trigger(placeholder="Elige la voz", width="100%"),
            rx.select.content(
                rx.foreach(
                    CreativeState.heygen_voices,
                    lambda voice: rx.select.item(voice["name"], value=voice["id"]),
                ),
            ),
            value=CreativeState.voice_id,
            on_change=CreativeState.set_voice_id,
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _avatar_section() -> rx.Component:
    """The presenter: a library look (human avatar) or an animated character, generated
    by AI from a description or animated from the operator's image."""
    human = rx.vstack(
        rx.hstack(
            rx.text("Avatar", size="2", weight="medium"),
            rx.cond(
                CreativeState.selected_look_name != "",
                rx.text("· ", CreativeState.selected_look_name, size="2", color=T.TEXT_MUTED),
            ),
            spacing="1",
        ),
        rx.grid(
            rx.foreach(CreativeState.heygen_looks, _look_card),
            columns=rx.breakpoints(initial="3", sm="5"),
            spacing="2",
            width="100%",
            max_height="22rem",
            overflow_y="auto",
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )
    animated = rx.vstack(
        rx.text("Personaje", size="2", weight="medium"),
        rx.segmented_control.root(
            rx.segmented_control.item("Generado por IA", value="ai"),
            rx.segmented_control.item("Desde una imagen", value="image"),
            value=CreativeState.avatar_source,
            on_change=CreativeState.set_avatar_source,
        ),
        rx.cond(
            CreativeState.avatar_source == "ai",
            rx.text_area(
                value=CreativeState.avatar_prompt,
                on_change=CreativeState.set_avatar_prompt,
                placeholder=(
                    "Describe al personaje: una hamburguesa sonriente con gorra roja, "
                    "un chef bigotón con delantal verde…"
                ),
                width="100%",
                rows="3",
                max_length=600,
            ),
            rx.vstack(
                rx.cond(
                    CreativeState.avatar_image_key != "",
                    _file_chip(CreativeState.avatar_image_name, CreativeState.clear_avatar_image),
                    _upload_zone(
                        "creative_avatar",
                        "Sube la imagen del personaje (tu mascota, una ilustración)",
                        CreativeState.handle_avatar_upload,
                        multiple=False,
                    ),
                ),
                rx.checkbox(
                    "Tengo derecho a animar esta imagen (no es la foto de una persona real "
                    "sin su permiso).",
                    checked=CreativeState.avatar_rights_confirmed,
                    on_change=CreativeState.set_avatar_rights_confirmed,
                    size="2",
                ),
                spacing="2",
                width="100%",
                align_items="start",
            ),
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )
    return rx.cond(
        CreativeState.heygen_error != "",
        callout(CreativeState.heygen_error, "warn"),
        rx.cond(
            CreativeState.heygen_loading,
            rx.hstack(
                rx.spinner(size="2"),
                rx.text("Cargando avatares y voces…", size="2", color=T.TEXT_MUTED),
                spacing="2",
                align="center",
            ),
            rx.vstack(
                rx.cond(CreativeState.brief_kind == "avatar_video", human, animated),
                _voice_select(),
                spacing="4",
                width="100%",
                align_items="start",
            ),
        ),
    )


def _duration_select() -> rx.Component:
    return rx.hstack(
        rx.text("Duración", size="2", weight="medium"),
        rx.segmented_control.root(
            *(rx.segmented_control.item(f"{s} s", value=s) for s in ("15", "30", "45", "60")),
            value=CreativeState.media_duration,
            on_change=CreativeState.set_media_duration,
        ),
        spacing="3",
        align="center",
        wrap="wrap",
    )


def _kind_inputs() -> rx.Component:
    """What the chosen kind takes, beyond the brief."""
    return _card(
        rx.match(
            CreativeState.brief_kind,
            (
                "creator_script",
                rx.vstack(
                    rx.text("El guion", size="2", weight="medium"),
                    rx.text(
                        "Generamos lo que dice la persona, toma por toma, y el texto del post.",
                        size="1",
                        color=T.TEXT_MUTED,
                    ),
                    _duration_select(),
                    spacing="2",
                    align_items="start",
                ),
            ),
            (
                "static_flyer",
                rx.vstack(
                    rx.text("Tus imágenes", size="2", weight="medium"),
                    rx.text(
                        "Tu foto de producto no se retoca: la ponemos sobre tu fondo con el "
                        "gancho y el llamado a la acción.",
                        size="1",
                        color=T.TEXT_MUTED,
                    ),
                    _images_section(),
                    spacing="2",
                    align_items="start",
                    width="100%",
                ),
            ),
            rx.vstack(
                _avatar_section(),
                rx.divider(),
                _duration_select(),
                rx.divider(),
                rx.text(
                    "El fondo y los productos se componen en una sola imagen detrás del avatar.",
                    size="1",
                    color=T.TEXT_MUTED,
                ),
                _images_section(),
                spacing="3",
                align_items="start",
                width="100%",
            ),
        ),
    )


def _brief_card() -> rx.Component:
    return _card(
        rx.text("Objetivo", size="2", weight="medium"),
        rx.hstack(
            _objective_button("awareness", "Reconocimiento"),
            _objective_button("consideration", "Consideración"),
            _objective_button("lead", "Captar contacto"),
            _objective_button("sale", "Vender"),
            spacing="2",
            wrap="wrap",
        ),
        rx.text("De qué trata", size="2", weight="medium"),
        rx.select.root(
            rx.select.trigger(width="100%"),
            rx.select.content(
                rx.foreach(
                    CreativeState.content_type_choices,
                    lambda pair: rx.select.item(pair[1], value=pair[0]),
                ),
            ),
            value=CreativeState.brief_content_type,
            on_change=CreativeState.set_content_type,
        ),
        rx.text("Tema o producto", size="2", weight="medium"),
        rx.text_area(
            value=CreativeState.brief_topic,
            on_change=CreativeState.set_brief_topic,
            placeholder="Qué anuncia esta pieza",
            width="100%",
            rows="2",
        ),
        rx.text("Formato", size="2", weight="medium"),
        rx.cond(
            CreativeState.kind_is_video,
            rx.badge("Instagram · Reel vertical 9:16", color_scheme="grass", variant="soft"),
            rx.badge("Instagram · Post de feed 4:5", color_scheme="grass", variant="soft"),
        ),
        rx.text("Destino", size="2", weight="medium"),
        rx.hstack(
            _intent_button("organic", "Orgánico"),
            _intent_button("ads", "Anuncio"),
            _intent_button("both", "Ambos"),
            spacing="2",
        ),
    )


def _restrictions_card() -> rx.Component:
    return _card(
        rx.text("Restricciones opcionales", size="2", weight="medium"),
        rx.input(
            value=CreativeState.brief_must_mention,
            on_change=CreativeState.set_brief_must_mention,
            placeholder="Debe mencionar (separado por comas)",
            width="100%",
        ),
        rx.input(
            value=CreativeState.brief_must_avoid,
            on_change=CreativeState.set_brief_must_avoid,
            placeholder="Debe evitar (separado por comas)",
            width="100%",
        ),
    )


def generator_panel() -> rx.Component:
    """The whole generator, as one block of the /signals page."""
    readiness = CreativeState.readiness
    return rx.vstack(
        rx.vstack(
            rx.heading("Generador de contenido", size="4", as_="h2"),
            rx.text(
                "Elige qué quieres generar. El resultado queda como borrador para revisarlo.",
                size="2",
                color=T.TEXT_MUTED,
            ),
            spacing="1",
            align_items="start",
        ),
        rx.cond(
            readiness,
            rx.cond(
                ~readiness.can_generate,
                callout(
                    "La marca aún no está lista para generar: completa el Brand Kit y la "
                    "voz en Marca.",
                    "warn",
                ),
            ),
        ),
        _kind_picker(),
        _brief_card(),
        _kind_inputs(),
        _restrictions_card(),
        rx.cond(
            CreativeState.create_error != "",
            callout(CreativeState.create_error, "error"),
        ),
        rx.hstack(
            rx.spacer(),
            rx.button(
                rx.icon("sparkles", size=16),
                "Generar",
                on_click=CreativeState.submit_generator_form,
                loading=CreativeState.is_submitting,
                size="3",
            ),
            width="100%",
        ),
        spacing="4",
        width="100%",
        align_items="start",
    )

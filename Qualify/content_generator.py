"""The content generator (§ request 2026-09-25), on /signals — where the operator tests
generation — while /create keeps its original form. Two views:

1. **Configura** — the form, interactive: the content kind picked decides which fields
   appear (avatar and voice for the avatar kinds, images for the kinds that take them,
   the carousel for a flyer in a feed format, the duration for scripts and videos) and
   which formats can be chosen (`ContentKind.formats`).
2. **Resultado** — one view per kind, filled in as the draft lands (`poll_generator`):
   the script alone for a real creator; the HeyGen video for both avatar kinds; the
   image or the carousel's slides for a flyer (composed locally).

Same `CreativeState` and the same service underneath: every piece is also a draft at
/drafts/{id}, where it is edited and approved."""

from __future__ import annotations

import reflex as rx

from .canva_state import CanvaState
from .creative_state import CreativeState
from .creative_vm import KIND_OPTIONS
from .ui import (
    callout,
    card,
    loading_spinner,
    removable_pill,
    section,
    signal_pill,
    tag,
    tone_badge,
)
from .ui import tokens as T


def _card(
    *children: rx.Component,
    title: str | rx.Var | None = None,
    icon: str | None = None,
    actions: tuple[rx.Component, ...] = (),
    **props,
) -> rx.Component:
    """A generator block: design-system `card` with, optionally, its entity title
    (heading 4 — §3.2) and the block's own controls on the right."""
    header: list[rx.Component] = []
    if title is not None:
        header.append(
            rx.hstack(
                rx.icon(icon, size=T.ICON_MD, color=T.TEXT_MUTED) if icon else rx.fragment(),
                rx.heading(title, size="4", as_="h3"),
                rx.spacer(),
                *actions,
                spacing="2",
                width="100%",
                align="center",
            )
        )
    return card(
        rx.vstack(*header, *children, spacing="3", align_items="start", width="100%"),
        padding="1.25rem 1.5rem",
        **props,
    )


def _field_label(text: str, hint: str | None = None) -> rx.Component:
    """§5.6: visible label above, help below in size 1 muted."""
    return rx.vstack(
        rx.text(text, size="2", weight="medium"),
        rx.text(hint, size="1", color=T.TEXT_MUTED) if hint else rx.fragment(),
        spacing="0",
        align_items="start",
    )


def _choice(
    value: rx.Var[str], on_change: object, options: tuple[tuple[str, str], ...]
) -> rx.Component:
    """A single choice among a few named options. A segmented control, not a row of
    `solid` buttons: the screen keeps ONE solid action (Generar, §5.5)."""
    return rx.segmented_control.root(
        *(rx.segmented_control.item(label, value=key) for key, label in options),
        value=value,
        on_change=on_change,
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
            rx.icon(
                icon,
                size=T.ICON_MD,
                color=rx.cond(selected, T.tone_color("accent", 11), T.TEXT_FAINT),
                flex_shrink="0",
            ),
            rx.vstack(
                rx.hstack(
                    rx.text(title, size="2", weight="medium"),
                    tone_badge("Próximamente", "neutral") if not enabled else rx.fragment(),
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
        role="radio",
        aria_checked=rx.cond(selected, "true", "false"),
        cursor="pointer" if enabled else "not-allowed",
        opacity="1" if enabled else "0.55",
        padding="0.85rem 1rem",
        border=rx.cond(selected, f"1px solid {T.tone_color('accent', 8)}", T.BORDER),
        background=rx.cond(selected, T.tone_color("accent", 2), T.CARD_BG),
        border_radius=T.RADIUS_CONTROL,
        transition=f"border-color {T.DUR_FAST} {T.EASE}, background {T.DUR_FAST} {T.EASE}",
        width="100%",
    )


def _kind_picker() -> rx.Component:
    return _card(
        rx.grid(
            *(_kind_card(*option) for option in KIND_OPTIONS),
            columns=rx.breakpoints(initial="1", sm="2"),
            spacing="2",
            width="100%",
            role="radiogroup",
            aria_label="Tipo de contenido",
        ),
        title="Tipo de contenido",
        icon="layout-grid",
    )


def _upload_zone(upload_id: str, label: str, handler: object, *, multiple: bool) -> rx.Component:
    return rx.upload(
        rx.vstack(
            rx.icon("image-up", size=T.ICON_MD, color=T.TEXT_FAINT),
            rx.text(label, size="1", text_align="center", color=T.TEXT_MUTED),
            align="center",
            spacing="1",
        ),
        id=upload_id,
        accept=_IMAGE_ACCEPT,
        max_files=10 if multiple else 1,
        multiple=multiple,
        on_drop=handler(rx.upload_files(upload_id=upload_id)),
        border=f"1px dashed {rx.color('gray', 7)}",
        border_radius=T.RADIUS_CONTROL,
        background=T.CARD_BG,
        padding="1rem",
        cursor="pointer",
        width="100%",
    )


def _file_chip(name: rx.Var[str], on_remove: object) -> rx.Component:
    return rx.box(
        removable_pill(name, on_remove, icon="image", remove_label="Quitar imagen"),
        max_width="18rem",
    )


def _images_section() -> rx.Component:
    """Background and product images — optional for the avatar videos."""
    return rx.vstack(
        _background_upload("Fondo (opcional)", "Arrastra la imagen de fondo o haz clic"),
        _products_upload("Producto o productos (opcional)"),
        _upload_error(),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _background_upload(label: str, hint: str) -> rx.Component:
    return rx.vstack(
        rx.text(label, size="2", weight="medium"),
        rx.cond(
            CreativeState.media_background_key != "",
            _file_chip(CreativeState.media_background_name, CreativeState.clear_background),
            _upload_zone(
                "creative_background",
                hint,
                CreativeState.handle_background_upload,
                multiple=False,
            ),
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _products_upload(label: str) -> rx.Component:
    return rx.vstack(
        rx.text(label, size="2", weight="medium"),
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
            CreativeState.carousel_allowed,
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
        spacing="2",
        width="100%",
        align_items="start",
    )


def _upload_error() -> rx.Component:
    return rx.cond(
        CreativeState.upload_error != "",
        rx.text(CreativeState.upload_error, size="1", color=T.tone_color("error", 11)),
    )


def _ad_image_section() -> rx.Component:
    """The advertising image: the operator's product, their background (their venue)
    or both, and the scene around them. The multi-reference image model that renders
    the scene is chosen but not wired yet, so the piece is still composed locally."""
    return rx.vstack(
        rx.text("¿Con qué armamos el anuncio?", size="2", weight="medium"),
        rx.segmented_control.root(
            rx.segmented_control.item("Producto", value="product"),
            rx.segmented_control.item("Fondo", value="background"),
            rx.segmented_control.item("Producto + fondo", value="both"),
            value=CreativeState.ad_mode,
            on_change=CreativeState.set_ad_mode,
            size="2",
        ),
        rx.text(
            rx.match(
                CreativeState.ad_mode,
                ("product", "Tu producto tal cual es; la escena alrededor se inventa."),
                ("background", "Tu fondo real (tu local, tu vitrina); lo de delante se inventa."),
                "Tu producto real dentro de tu fondo real: por ejemplo, una mano con tu vaso "
                "y tu local desenfocado detrás.",
            ),
            size="1",
            color=T.TEXT_MUTED,
        ),
        rx.cond(
            CreativeState.ad_mode != "background",
            _products_upload("Foto del producto"),
        ),
        rx.cond(
            CreativeState.ad_mode != "product",
            _background_upload("Foto del fondo", "Arrastra la foto de tu local o del fondo"),
        ),
        _upload_error(),
        rx.text("Describe la escena (opcional)", size="2", weight="medium"),
        rx.text_area(
            value=CreativeState.ad_scene_prompt,
            on_change=CreativeState.set_ad_scene_prompt,
            placeholder=(
                "Una mano sosteniendo el vaso a la altura del pecho, la etiqueta de frente, "
                "con el local desenfocado detrás y luz cálida…"
            ),
            width="100%",
            rows="3",
            max_length=600,
        ),
        callout(
            "La generación con IA de la escena aún no está conectada: por ahora componemos "
            "tus fotos sin retocarlas. Tu descripción queda guardada con el encargo.",
            "info",
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _look_grid(looks: rx.Var[list[dict[str, str]]], gender: str) -> rx.Component:
    """One gender's looks. Always mounted, only shown for its gender — see
    `CreativeState.female_looks` for why the grids are not one list."""
    return rx.grid(
        rx.foreach(looks, _look_card),
        columns=rx.breakpoints(initial="4", sm="6"),
        spacing="2",
        width="100%",
        max_height="18rem",
        overflow_y="auto",
        display=rx.cond(CreativeState.human_avatar_mode == gender, "grid", "none"),
    )


def _look_card(look: rx.Var[dict[str, str]]) -> rx.Component:
    selected = CreativeState.avatar_look_id == look["id"]
    return rx.box(
        rx.cond(
            look["preview"] != "",
            rx.image(
                src=look["preview"],
                width="100%",
                height="5.25rem",
                object_fit="cover",
                object_position="top",
                border_radius="0.4rem",
            ),
            rx.center(rx.icon("user-round", size=22, color=T.TEXT_FAINT), height="5.25rem"),
        ),
        rx.text(
            look["name"],
            size="1",
            text_align="center",
            margin_top="0.25rem",
            trim="both",
            white_space="nowrap",
            overflow="hidden",
            text_overflow="ellipsis",
        ),
        key=look["id"],
        on_click=CreativeState.choose_look(look["id"]),
        cursor="pointer",
        padding="0.3rem",
        border=rx.cond(
            selected, f"2px solid {rx.color('accent', 9)}", f"1px solid {rx.color('gray', 5)}"
        ),
        border_radius="0.6rem",
        width="100%",
    )


def _voice_select() -> rx.Component:
    """The voices of one gender. With a library woman or man the gender follows the
    avatar; with a custom or animated presenter the operator picks it here."""
    voice_follows_avatar = (CreativeState.brief_kind == "avatar_video") & (
        CreativeState.human_avatar_mode != "custom"
    )
    return rx.vstack(
        rx.hstack(
            rx.text("Voz", size="2", weight="medium"),
            rx.cond(
                voice_follows_avatar,
                rx.text(
                    rx.cond(CreativeState.voice_gender == "female", "· de mujer", "· de hombre"),
                    size="2",
                    color=T.TEXT_MUTED,
                ),
            ),
            spacing="1",
        ),
        rx.cond(
            ~voice_follows_avatar,
            rx.segmented_control.root(
                rx.segmented_control.item("Femenina", value="female"),
                rx.segmented_control.item("Masculina", value="male"),
                value=CreativeState.voice_gender,
                on_change=CreativeState.set_voice_gender,
                size="2",
            ),
        ),
        rx.select.root(
            rx.select.trigger(placeholder="Elige la voz", width="100%"),
            rx.select.content(
                rx.foreach(
                    CreativeState.visible_voices,
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
    """The presenter: a library woman or man, or a custom person described in words
    (human avatar); or an animated character, generated by AI from a description or
    animated from the operator's image."""
    library = rx.cond(
        CreativeState.visible_looks.length() > 0,
        rx.box(
            _look_grid(CreativeState.female_looks, "female"),
            _look_grid(CreativeState.male_looks, "male"),
            width="100%",
        ),
        rx.text("No hay avatares de este tipo en la biblioteca.", size="2", color=T.TEXT_MUTED),
    )
    custom = rx.vstack(
        rx.text_area(
            value=CreativeState.human_avatar_prompt,
            on_change=CreativeState.set_human_avatar_prompt,
            placeholder=(
                "Describe a la persona: mujer de unos 30 años, pelo rizado castaño, blusa "
                "verde, sonriente, en una cocina luminosa…"
            ),
            width="100%",
            rows="3",
            max_length=600,
        ),
        rx.text(
            "HeyGen genera una persona sintética (no es nadie real) antes del video: tarda "
            "unos minutos más y se cobra aparte.",
            size="1",
            color=T.TEXT_MUTED,
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )
    human = rx.vstack(
        rx.hstack(
            rx.text("Avatar", size="2", weight="medium"),
            rx.cond(
                (CreativeState.human_avatar_mode != "custom")
                & (CreativeState.selected_look_name != ""),
                rx.text("· ", CreativeState.selected_look_name, size="2", color=T.TEXT_MUTED),
            ),
            spacing="1",
        ),
        rx.segmented_control.root(
            rx.segmented_control.item("Mujer", value="female"),
            rx.segmented_control.item("Hombre", value="male"),
            rx.segmented_control.item("Personalizado", value="custom"),
            value=CreativeState.human_avatar_mode,
            on_change=CreativeState.set_human_avatar_mode,
            size="2",
        ),
        rx.cond(CreativeState.human_avatar_mode == "custom", custom, library),
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
                loading_spinner("sm"),
                rx.text("Cargando avatares y voces…", size="2", color=T.TEXT_MUTED),
                spacing="2",
                align="center",
            ),
            rx.vstack(
                rx.cond(CreativeState.brief_kind == "avatar_video", human, animated),
                _voice_select(),
                # an image subject always renders on Avatar IV: no choice to make there
                rx.cond(
                    (CreativeState.brief_kind == "avatar_video")
                    | (CreativeState.avatar_source == "ai"),
                    _engine_select(),
                ),
                spacing="4",
                width="100%",
                align_items="start",
            ),
        ),
    )


def _engine_select() -> rx.Component:
    return rx.vstack(
        rx.text("Motor de HeyGen", size="2", weight="medium"),
        rx.segmented_control.root(
            rx.segmented_control.item("Avatar IV · más natural", value="avatar_iv"),
            rx.segmented_control.item("Avatar III · más barato", value="avatar_iii"),
            value=CreativeState.avatar_engine,
            on_change=CreativeState.set_avatar_engine,
            size="2",
        ),
        spacing="2",
        align_items="start",
    )


def _script_source() -> rx.Component:
    """Claude writes the script to the chosen length, or the operator writes it and the
    avatar reads it word for word."""
    return rx.vstack(
        rx.hstack(
            rx.switch(
                checked=CreativeState.own_script_on, on_change=CreativeState.set_own_script_on
            ),
            rx.text("Escribir mi propio guion", size="2"),
            spacing="2",
            align="center",
        ),
        rx.cond(
            CreativeState.own_script_on,
            rx.text_area(
                value=CreativeState.own_script,
                on_change=CreativeState.set_own_script,
                placeholder="Lo que va a decir el avatar, palabra por palabra.",
                width="100%",
                rows="5",
                max_length=2000,
            ),
            _duration_select(),
        ),
        spacing="2",
        width="100%",
        align_items="start",
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
                    rx.text(
                        "Generamos lo que dice la persona, toma por toma, y el texto del post.",
                        size="2",
                        color=T.TEXT_MUTED,
                    ),
                    _duration_select(),
                    spacing="3",
                    align_items="start",
                ),
            ),
            (
                "static_flyer",
                _ad_image_section(),
            ),
            rx.vstack(
                _avatar_section(),
                rx.divider(),
                _script_source(),
                rx.divider(),
                _field_label(
                    "Fondo y productos",
                    "Se componen en una sola imagen detrás del avatar.",
                ),
                _images_section(),
                spacing="4",
                align_items="start",
                width="100%",
            ),
        ),
        title=rx.match(
            CreativeState.brief_kind,
            ("creator_script", "El guion"),
            ("static_flyer", "El anuncio"),
            "El video",
        ),
        icon="sliders-horizontal",
    )


def _field(label: str, control: rx.Component, hint: str | None = None) -> rx.Component:
    return rx.vstack(
        _field_label(label, hint),
        control,
        spacing="2",
        width="100%",
        align_items="start",
    )


def _brief_card() -> rx.Component:
    return _card(
        _field(
            "Objetivo",
            _choice(
                CreativeState.brief_objective,
                CreativeState.set_objective,
                (
                    ("awareness", "Reconocimiento"),
                    ("consideration", "Consideración"),
                    ("lead", "Captar contacto"),
                    ("sale", "Vender"),
                ),
            ),
        ),
        _field(
            "Tema o producto",
            rx.text_area(
                value=CreativeState.brief_topic,
                on_change=CreativeState.set_brief_topic,
                placeholder="Ej.: nuestra hamburguesa doble con papas, solo este fin de semana",
                width="100%",
                rows="2",
            ),
            "Qué anuncia esta pieza. Es lo único obligatorio.",
        ),
        rx.grid(
            _field(
                "De qué trata",
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
            ),
            _field(
                "Destino",
                _choice(
                    CreativeState.brief_intent,
                    CreativeState.set_intent,
                    (("organic", "Orgánico"), ("ads", "Anuncio"), ("both", "Ambos")),
                ),
            ),
            columns=rx.breakpoints(initial="1", sm="2"),
            spacing="4",
            width="100%",
        ),
        _field(
            "Formato",
            rx.segmented_control.root(
                rx.foreach(
                    CreativeState.format_options,
                    lambda option: rx.segmented_control.item(option[1], value=option[0]),
                ),
                value=CreativeState.effective_format,
                on_change=CreativeState.set_brief_format,
                size="2",
            ),
        ),
        title="El encargo",
        icon="clipboard-list",
    )


def _restrictions_card() -> rx.Component:
    return _card(
        rx.grid(
            _field(
                "Debe mencionar",
                rx.input(
                    value=CreativeState.brief_must_mention,
                    on_change=CreativeState.set_brief_must_mention,
                    placeholder="Ej.: envío gratis, reserva por WhatsApp",
                    width="100%",
                ),
                "Separado por comas.",
            ),
            _field(
                "Debe evitar",
                rx.input(
                    value=CreativeState.brief_must_avoid,
                    on_change=CreativeState.set_brief_must_avoid,
                    placeholder="Ej.: descuento, barato",
                    width="100%",
                ),
                "Separado por comas.",
            ),
            columns=rx.breakpoints(initial="1", sm="2"),
            spacing="4",
            width="100%",
        ),
        title="Restricciones (opcional)",
        icon="shield-check",
    )


def _step(number: str, label: str, active: rx.Var[bool]) -> rx.Component:
    return rx.hstack(
        rx.center(
            rx.text(number, size="1", weight="bold", class_name="q-nums"),
            width="1.5rem",
            height="1.5rem",
            border_radius="9999px",
            background=rx.cond(active, T.tone_color("accent", 9), T.SURFACE_BG_RAISED),
            color=rx.cond(active, T.tone_color("accent", 1), T.TEXT_MUTED),
        ),
        rx.text(
            label,
            size="2",
            weight=rx.cond(active, "medium", "regular"),
            color=rx.cond(active, T.TEXT_STRONG, T.TEXT_MUTED),
        ),
        spacing="2",
        align="center",
        aria_current=rx.cond(active, "step", "false"),
    )


def _stepper() -> rx.Component:
    on_form = CreativeState.generator_view == "form"
    return rx.hstack(
        _step("1", "Configura", on_form),
        rx.box(height="1px", width="2rem", background=rx.color("gray", 6)),
        _step("2", "Resultado", ~on_form),
        spacing="3",
        align="center",
    )


def _form_view() -> rx.Component:
    readiness = CreativeState.readiness
    return rx.vstack(
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
        # §5.6: the submit error sits above the form, where it is seen first
        rx.cond(
            CreativeState.create_error != "",
            callout(CreativeState.create_error, "error"),
        ),
        _kind_picker(),
        _brief_card(),
        _kind_inputs(),
        _restrictions_card(),
        rx.hstack(
            rx.text(
                "Cada pieza queda también como borrador, para revisarla y aprobarla.",
                size="1",
                color=T.TEXT_MUTED,
            ),
            rx.spacer(),
            # the screen's one solid action (§5.5)
            rx.button(
                rx.icon("sparkles", size=16),
                "Generar",
                on_click=CreativeState.submit_generator_form,
                loading=CreativeState.is_submitting,
                size="2",
            ),
            width="100%",
            align="center",
            wrap="wrap",
            spacing="3",
        ),
        spacing="4",
        width="100%",
        align_items="start",
    )


# -- the result view -------------------------------------------------------------------


def _media_src(key: rx.Var[str]) -> rx.Var[str]:
    return rx.get_upload_url(key)


def _download(key: rx.Var[str], label: str = "Descargar") -> rx.Component:
    return rx.link(
        rx.hstack(rx.icon("download", size=14), rx.text(label, size="2"), spacing="1"),
        href=_media_src(key),
        is_external=True,
        download=True,
    )


def _variant_switch() -> rx.Component:
    return rx.cond(
        CreativeState.gen_variant_labels.length() > 1,
        rx.segmented_control.root(
            rx.foreach(
                CreativeState.gen_variant_labels,
                lambda option: rx.segmented_control.item(option[1], value=option[0]),
            ),
            value=CreativeState.gen_variant.to_string(),
            on_change=CreativeState.choose_gen_variant,
            size="1",
        ),
    )


def _shot_row(line: rx.Var[str]) -> rx.Component:
    return rx.box(
        rx.text(line, size="2"),
        padding="0.6rem 0.8rem",
        border_left=f"3px solid {T.tone_color('accent', 7)}",
        background=T.SURFACE_BG_RAISED,
        border_radius=T.RADIUS_CONTROL,
        width="100%",
    )


def _script_result() -> rx.Component:
    """Creator's script: only the script — what is said, and the shots to record."""
    variant = CreativeState.gen_variant_vm
    return _card(
        rx.text(variant.script, size="3", white_space="pre-wrap", line_height="1.6"),
        rx.button(
            rx.icon("copy", size=14),
            "Copiar guion",
            variant="soft",
            size="1",
            on_click=rx.set_clipboard(variant.script),
        ),
        rx.cond(
            variant.shots.length() > 0,
            rx.vstack(
                rx.text("Tomas", size="2", weight="medium", color=T.TEXT_MUTED),
                rx.foreach(variant.shots, _shot_row),
                spacing="2",
                width="100%",
            ),
        ),
        title="Guion",
        icon="clapperboard",
        actions=(_variant_switch(),),
    )


def _post_text() -> rx.Component:
    """The post's own copy under a video or an image: what goes in the caption."""
    variant = CreativeState.gen_variant_vm
    return rx.vstack(
        rx.text("Texto del post", size="2", weight="medium", color=T.TEXT_MUTED),
        rx.text(variant.rendered_caption, size="2", white_space="pre-wrap"),
        rx.button(
            rx.icon("copy", size=14),
            "Copiar texto",
            variant="soft",
            size="1",
            on_click=rx.set_clipboard(variant.rendered_caption),
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _video_item(item: rx.Var) -> rx.Component:
    return rx.vstack(
        rx.video(src=_media_src(item.key), controls=True, width="100%", max_width="22rem"),
        _download(item.key, "Descargar video"),
        spacing="2",
        align="center",
    )


def _video_result() -> rx.Component:
    """Avatar video (human or animated): the HeyGen video, the script it read, the post."""
    variant = CreativeState.gen_variant_vm
    return _card(
        rx.flex(
            rx.box(
                rx.foreach(CreativeState.gen_draft.media, _video_item),
                flex_shrink="0",
            ),
            rx.vstack(
                rx.text("Guion leído", size="2", weight="medium", color=T.TEXT_MUTED),
                rx.text(variant.script, size="2", white_space="pre-wrap"),
                rx.divider(),
                _post_text(),
                spacing="3",
                width="100%",
                align_items="start",
            ),
            direction=rx.breakpoints(initial="column", md="row"),
            gap="5",
            width="100%",
        ),
        title="Video",
        icon="video",
        actions=(_variant_switch(),),
    )


def _image_item(item: rx.Var) -> rx.Component:
    return rx.vstack(
        rx.image(
            src=_media_src(item.key),
            width="100%",
            border_radius=T.RADIUS_CONTROL,
            border=T.BORDER,
        ),
        rx.hstack(
            rx.text(item.label, size="1", color=T.TEXT_MUTED),
            rx.spacer(),
            _download(item.key),
            width="100%",
        ),
        spacing="1",
        width="100%",
    )


def _image_result() -> rx.Component:
    """Ad image: the image, or the carousel's slides in order (composed locally)."""
    return _card(
        rx.grid(
            rx.foreach(CreativeState.gen_draft.media, _image_item),
            columns=rx.breakpoints(initial="1", sm="2", md="3"),
            spacing="3",
            width="100%",
        ),
        rx.divider(),
        _post_text(),
        title="Imagen",
        icon="image",
        actions=(_variant_switch(),),
    )


def _waiting() -> rx.Component:
    return _card(
        rx.hstack(
            loading_spinner("md"),
            rx.vstack(
                rx.text(CreativeState.gen_waiting_label, size="3", weight="medium"),
                rx.text(
                    "Puedes quedarte aquí: el resultado aparece solo cuando esté listo.",
                    size="2",
                    color=T.TEXT_MUTED,
                ),
                spacing="1",
                align_items="start",
            ),
            spacing="4",
            align="center",
        ),
        rx.cond(
            CreativeState.gen_timed_out,
            callout(
                "Está tardando más de lo normal. Revisa el borrador más tarde en Borradores.",
                "warn",
            ),
        ),
    )


def _failed() -> rx.Component:
    return callout(
        rx.cond(
            CreativeState.gen_failure_label != "",
            CreativeState.gen_failure_label,
            "No se pudo generar esta pieza.",
        ),
        "error",
    )


def _canva_link_item(item: rx.Var) -> rx.Component:
    """One piece sent to Canva: its state, reopen, bring back, and the edited file."""
    return rx.vstack(
        rx.hstack(
            rx.match(
                item["status"],
                ("exported", signal_pill(item["status_label"], "ok")),
                ("failed", signal_pill(item["status_label"], "error")),
                signal_pill(item["status_label"], "info"),
            ),
            rx.cond(
                item["exported_at"] != "",
                rx.text(item["exported_at"], size="1", color=T.TEXT_MUTED),
            ),
            rx.spacer(),
            rx.cond(
                item["open_url"] != "",
                rx.link(
                    rx.button(rx.icon("external-link", size=14), "Abrir", variant="soft", size="1"),
                    href=item["open_url"],
                ),
            ),
            rx.button(
                rx.icon("download", size=14),
                "Traer de Canva",
                variant="soft",
                size="1",
                loading=CanvaState.busy,
                on_click=CanvaState.pull(item["id"]),
            ),
            width="100%",
            align="center",
            spacing="2",
        ),
        rx.cond(
            item["error"] != "",
            rx.text(item["error"], size="1", color=T.tone_color("error", 11)),
        ),
        rx.cond(
            item["exported_key"] != "",
            rx.hstack(
                rx.cond(
                    item["media_type"] == "video",
                    rx.video(
                        src=_media_src(item["exported_key"]),
                        controls=True,
                        width="12rem",
                        height="auto",
                    ),
                    rx.image(
                        src=_media_src(item["exported_key"]),
                        width="12rem",
                        border_radius="0.4rem",
                    ),
                ),
                _download(item["exported_key"]),
                spacing="3",
                align="end",
            ),
        ),
        spacing="2",
        width="100%",
        padding="0.6rem",
        border=f"1px solid {rx.color('gray', 5)}",
        border_radius="0.6rem",
    )


def _canva_card() -> rx.Component:
    """Edit the piece in the operator's own Canva and bring the result back. The whole
    trip stays in this tab (the session lives here); see `canva_state.py`."""
    return _card(
        rx.cond(
            ~CanvaState.configured,
            rx.hstack(
                tone_badge("Sin configurar", "neutral", icon="plug-zap"),
                rx.text(
                    "Faltan las credenciales de la integración con Canva en este servidor.",
                    size="2",
                    color=T.TEXT_MUTED,
                ),
                spacing="2",
                align="center",
                wrap="wrap",
            ),
            rx.vstack(
                rx.text(
                    "Mandamos la pieza a tu Canva, la editas allí y, al pulsar «Volver» en "
                    "Canva, la traemos de vuelta aquí.",
                    size="2",
                    color=T.TEXT_MUTED,
                ),
                rx.cond(
                    CreativeState.gen_kind != "static_flyer",
                    rx.text(
                        "Los videos llegan a «Subidos» en Canva: arrástralo al diseño (Canva no "
                        "deja colocarlo automáticamente).",
                        size="1",
                        color=T.TEXT_MUTED,
                    ),
                ),
                # soft: the result screen's one solid action is "Revisar y aprobar"
                rx.cond(
                    CanvaState.connected,
                    rx.button(
                        rx.icon("external-link", size=16),
                        "Editar en Canva",
                        size="2",
                        variant="soft",
                        loading=CanvaState.busy,
                        on_click=CanvaState.send,
                    ),
                    rx.button(
                        rx.icon("link", size=16),
                        "Conectar Canva",
                        size="2",
                        variant="soft",
                        on_click=CanvaState.connect,
                    ),
                ),
                rx.cond(CanvaState.notice != "", callout(CanvaState.notice, "ok")),
                rx.cond(CanvaState.error != "", callout(CanvaState.error, "error")),
                rx.cond(
                    CanvaState.has_links,
                    rx.vstack(
                        rx.foreach(CanvaState.links, _canva_link_item),
                        spacing="2",
                        width="100%",
                    ),
                ),
                spacing="3",
                width="100%",
                align_items="start",
            ),
        ),
        title="Editar en Canva",
        icon="palette",
        actions=(
            rx.cond(
                CanvaState.connected,
                rx.button(
                    "Desconectar",
                    variant="ghost",
                    color_scheme="gray",
                    size="1",
                    on_click=CanvaState.disconnect,
                ),
            ),
        ),
        # (re)read the connection and the links whenever the result's draft is shown
        on_mount=CanvaState.load(CreativeState.gen_draft_id),
    )


def _result_view() -> rx.Component:
    return rx.vstack(
        # what the piece is — metadata, so `tag`s (§5.3), not state badges
        rx.hstack(
            rx.cond(CreativeState.gen_draft, tag(CreativeState.gen_draft.kind_label, size="2")),
            tag(CreativeState.effective_format_label, size="2"),
            spacing="2",
        ),
        rx.cond(
            CreativeState.gen_is_ready,
            rx.match(
                CreativeState.gen_kind,
                ("creator_script", _script_result()),
                ("static_flyer", _image_result()),
                _video_result(),
            ),
            rx.cond(CreativeState.gen_is_failed, _failed(), _waiting()),
        ),
        rx.cond(
            CreativeState.gen_is_ready & (CreativeState.gen_kind != "creator_script"),
            _canva_card(),
        ),
        rx.hstack(
            rx.button(
                rx.icon("arrow-left", size=16),
                "Crear otro",
                variant="soft",
                color_scheme="gray",
                on_click=CreativeState.new_generation,
                size="2",
            ),
            rx.spacer(),
            rx.cond(
                CreativeState.gen_draft_id != "",
                # the result screen's one solid action (§5.5): where the piece goes next
                rx.link(
                    rx.button(
                        "Revisar y aprobar en Borradores",
                        rx.icon("arrow-right", size=16),
                        size="2",
                    ),
                    href="/drafts/" + CreativeState.gen_draft_id,
                ),
            ),
            width="100%",
            align="center",
        ),
        spacing="4",
        width="100%",
        align_items="start",
    )


def generator_panel() -> rx.Component:
    """The whole generator, as one block of the /signals page (design system `section`):
    step 1 configures, step 2 shows the piece."""
    return section(
        "Generador de contenido",
        rx.cond(CreativeState.generator_view == "result", _result_view(), _form_view()),
        description="Elige qué quieres crear, cuéntanos el encargo y genera la pieza.",
        actions=(_stepper(),),
        spacing="4",
    )

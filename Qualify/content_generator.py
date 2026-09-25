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
                _script_source(),
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
        rx.segmented_control.root(
            rx.foreach(
                CreativeState.format_options,
                lambda option: rx.segmented_control.item(option[1], value=option[0]),
            ),
            value=CreativeState.effective_format,
            on_change=CreativeState.set_brief_format,
            size="2",
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


def _step(number: str, label: str, active: rx.Var[bool]) -> rx.Component:
    return rx.hstack(
        rx.center(
            rx.text(number, size="1", weight="bold"),
            width="1.5rem",
            height="1.5rem",
            border_radius="9999px",
            background=rx.cond(active, rx.color("accent", 9), rx.color("gray", 4)),
            color=rx.cond(active, "white", rx.color("gray", 11)),
        ),
        rx.text(label, size="2", weight=rx.cond(active, "bold", "regular")),
        spacing="2",
        align="center",
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
        border_left=f"3px solid {rx.color('accent', 7)}",
        background=rx.color("gray", 2),
        border_radius="0.35rem",
        width="100%",
    )


def _script_result() -> rx.Component:
    """Creator's script: only the script — what is said, and the shots to record."""
    variant = CreativeState.gen_variant_vm
    return _card(
        rx.hstack(
            rx.text("Guion", size="3", weight="bold"),
            rx.spacer(),
            _variant_switch(),
            width="100%",
            align="center",
        ),
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
        rx.text("Video", size="3", weight="bold"),
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
    )


def _image_item(item: rx.Var) -> rx.Component:
    return rx.vstack(
        rx.image(src=_media_src(item.key), width="100%", border_radius="0.5rem"),
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
    """Flyer: the image, or the carousel's slides in order (composed locally)."""
    return _card(
        rx.hstack(
            rx.text("Imagen", size="3", weight="bold"),
            rx.spacer(),
            _variant_switch(),
            width="100%",
            align="center",
        ),
        rx.grid(
            rx.foreach(CreativeState.gen_draft.media, _image_item),
            columns=rx.breakpoints(initial="1", sm="2", md="3"),
            spacing="3",
            width="100%",
        ),
        rx.divider(),
        _post_text(),
    )


def _waiting() -> rx.Component:
    return _card(
        rx.hstack(
            rx.spinner(size="3"),
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


def _result_view() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.cond(
                CreativeState.gen_draft,
                rx.badge(CreativeState.gen_draft.kind_label, color_scheme="gray", variant="soft"),
            ),
            rx.badge(CreativeState.effective_format_label, color_scheme="gray", variant="soft"),
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
        rx.hstack(
            rx.button(
                rx.icon("arrow-left", size=15),
                "Crear otro",
                variant="soft",
                color_scheme="gray",
                on_click=CreativeState.new_generation,
                size="2",
            ),
            rx.spacer(),
            rx.cond(
                CreativeState.gen_draft_id != "",
                rx.link(
                    rx.button(
                        "Revisar y aprobar en Borradores",
                        rx.icon("arrow-right", size=15),
                        variant="soft",
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
    """The whole generator, as one block of the /signals page: step 1 configures, step
    2 shows the piece."""
    return rx.vstack(
        rx.vstack(
            rx.heading("Generador de contenido", size="4", as_="h2"),
            _stepper(),
            spacing="2",
            align_items="start",
        ),
        rx.cond(CreativeState.generator_view == "result", _result_view(), _form_view()),
        spacing="4",
        width="100%",
        align_items="start",
    )

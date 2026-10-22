"""The «Variaciones» view of Crear pieza (ticket 24803289).

One screen, three numbered steps and then the review:

1. the CATALOG product (requirement 1: never a stock pick),
2. the preset — the ones that cannot be used say why, right on the card,
3. the plan, and the one button that makes the paid Claude call,

then the angles it proposed, each discardable before a single image is paid for.

Lives in its own module so `content_generator.py` only gains the branch that renders
it. Every state rule is in `variations_state.py`; every label and tone in
`variations_vm.py`. This file only draws.
"""

from __future__ import annotations

import reflex as rx
from qualify_creative.angles import COMPOSITION_MAX, SCENE_MAX

from .r2_media import BACKEND_BASE
from .ui import callout, card, choice_card, choice_card_check, empty_state, media_thumb, tone_badge
from .ui import tokens as T
from .variations_state import VariationsState

_INTRO = (
    "Diez ángulos visuales distintos del mismo producto: cada uno con su escenario, "
    "su composición y su enfoque. Claude los propone; tú decides cuáles siguen."
)
_NEXT_STEP = (
    "Revisa las propuestas y descarta las que no te convenzan. Después genera las "
    "imágenes de los ángulos que queden: cada una se paga al generarla."
)
_POLL_TIMEOUT = (
    "Algunas piezas llevan demasiado tiempo. Vuelve a abrir este grupo más tarde o "
    "reinténtalas una a una."
)


# The VM ships the tone as data; the design system needs it at build time, so a
# dynamic tone is dispatched with `rx.match` (same helpers as `conversations_page`).
_TONES = ("ok", "warn", "error", "info", "neutral")


def _tone_badge(label: rx.Var[str], tone: rx.Var[str]) -> rx.Component:
    return rx.match(
        tone,
        *[(t, tone_badge(label, t)) for t in _TONES[:-1]],
        tone_badge(label, "neutral"),
    )


def _tone_callout(message: rx.Var[str], tone: rx.Var[str]) -> rx.Component:
    return rx.match(
        tone,
        *[(t, callout(message, t)) for t in _TONES[:-1]],
        callout(message, "neutral"),
    )


def _step_heading(number: str, title: str, hint: str = "") -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.center(
                rx.text(number, size="1", weight="bold", line_height="1"),
                width="1.5rem",
                height="1.5rem",
                flex_shrink="0",
                border_radius="50%",
                background=T.tone_color("accent", 3),
                color=T.tone_color("accent", 11),
            ),
            rx.heading(title, size="4", as_="h2"),
            spacing="2",
            align="center",
        ),
        rx.cond(hint != "", rx.text(hint, size="1", color=T.TEXT_MUTED)),
        spacing="1",
        align_items="start",
        width="100%",
    )


# -- 1. the product -------------------------------------------------------------------------


def _product_tile(row: rx.Var[dict[str, str]]) -> rx.Component:
    selected = VariationsState.product_id == row["id"]
    return choice_card(
        rx.vstack(
            rx.box(
                media_thumb(
                    rx.get_upload_url(row["photo_key"]),
                    has=row["photo_key"] != "",
                    width="100%",
                    height="5.5rem",
                    alt=row["name"],
                ),
                rx.cond(
                    selected,
                    rx.box(
                        choice_card_check(),
                        position="absolute",
                        top="0.35rem",
                        right="0.35rem",
                    ),
                ),
                position="relative",
                width="100%",
            ),
            rx.vstack(
                rx.text(row["name"], size="2", weight="bold"),
                rx.text(row["counts_label"], size="1", color=T.TEXT_MUTED),
                spacing="0",
                align_items="start",
                width="100%",
            ),
            spacing="2",
            align_items="start",
            width="100%",
        ),
        selected=selected,
        on_select=VariationsState.choose_product(row["id"]),
        padding="0.75rem",
        width="100%",
    )


def _product_step() -> rx.Component:
    return rx.vstack(
        _step_heading("1", "Elige el producto", "Solo productos de tu catálogo."),
        rx.cond(
            VariationsState.has_products,
            rx.grid(
                rx.foreach(VariationsState.products, _product_tile),
                columns=rx.breakpoints(initial="2", sm="3", lg="4"),
                spacing="3",
                width="100%",
            ),
            empty_state(
                "package",
                "Aún no tienes productos",
                "Variaciones parte de un producto real de tu catálogo: agrégalo con sus "
                "fotos y vuelve aquí.",
                rx.link(rx.button("Ir a Catálogo", size="2"), href="/catalog"),
            ),
        ),
        spacing="3",
        width="100%",
    )


def _product_facts() -> rx.Component:
    """The product as the engine sees it: its photos and the price it will print."""
    return card(
        rx.vstack(
            rx.hstack(
                rx.icon("package-check", size=T.ICON_SM, color=T.tone_color("accent", 11)),
                rx.text(VariationsState.product_name, size="2", weight="bold"),
                rx.spacer(),
                rx.button(
                    "Cambiar producto",
                    variant="ghost",
                    color_scheme="gray",
                    size="1",
                    on_click=VariationsState.start_over,
                ),
                spacing="2",
                align="center",
                width="100%",
            ),
            rx.hstack(
                tone_badge(VariationsState.photo_count_label, tone="neutral"),
                rx.cond(
                    VariationsState.price_missing,
                    tone_badge("Sin precio", tone="warn", icon="triangle-alert"),
                    tone_badge(VariationsState.price_label, tone="ok", icon="tag"),
                ),
                spacing="2",
                align="center",
            ),
            rx.cond(
                VariationsState.price_missing,
                callout(VariationsState.price_note, "warn"),
            ),
            spacing="3",
            width="100%",
        ),
        padding="0.9rem",
        width="100%",
    )


# -- 2. the preset ---------------------------------------------------------------------------


def _preset_card(preset: rx.Var) -> rx.Component:
    selected = VariationsState.preset_key == preset.key
    return choice_card(
        rx.vstack(
            rx.hstack(
                rx.icon(preset.icon, size=T.ICON_SM),
                rx.text(preset.name, size="2", weight="bold"),
                rx.spacer(),
                rx.cond(selected, choice_card_check()),
                spacing="2",
                align="center",
                width="100%",
            ),
            rx.text(preset.description, size="1", color=T.TEXT_MUTED),
            rx.hstack(
                tone_badge(preset.format_label, tone="neutral"),
                spacing="2",
            ),
            rx.cond(
                preset.available,
                rx.fragment(),
                rx.text(preset.reason, size="1", color=T.tone_color("warn", 11)),
            ),
            spacing="2",
            align_items="start",
            width="100%",
        ),
        selected=selected,
        disabled=~preset.available,
        on_select=VariationsState.choose_preset(preset.key),
        width="100%",
    )


def _preset_step() -> rx.Component:
    return rx.vstack(
        _step_heading("2", "Elige el estilo", "Define el formato y la composición de las piezas."),
        rx.grid(
            rx.foreach(VariationsState.presets, _preset_card),
            columns=rx.breakpoints(initial="1", sm="2", lg="3"),
            spacing="3",
            width="100%",
        ),
        spacing="3",
        width="100%",
    )


# -- 3. the plan ------------------------------------------------------------------------------


def _plan_step() -> rx.Component:
    return rx.vstack(
        _step_heading("3", "Revisa y genera los ángulos"),
        card(
            rx.vstack(
                rx.hstack(
                    rx.vstack(
                        rx.text(VariationsState.plan_count_label, size="3", weight="bold"),
                        rx.text(VariationsState.plan_images_label, size="1", color=T.TEXT_MUTED),
                        spacing="0",
                        align_items="start",
                    ),
                    rx.spacer(),
                    rx.button(
                        rx.icon("sparkles", size=15),
                        "Generar los ángulos",
                        size="3",
                        disabled=~VariationsState.can_create,
                        loading=VariationsState.creating,
                        on_click=VariationsState.create_set,
                    ),
                    spacing="3",
                    align="center",
                    width="100%",
                ),
                rx.text(VariationsState.plan_note, size="1", color=T.TEXT_MUTED),
                spacing="3",
                width="100%",
            ),
            padding="1rem",
            width="100%",
        ),
        spacing="3",
        width="100%",
    )


# -- the angles -------------------------------------------------------------------------------


def _angle_field(label: str, value: rx.Var[str]) -> rx.Component:
    return rx.cond(
        value != "",
        rx.vstack(
            rx.text(label, size="1", color=T.TEXT_FAINT),
            rx.text(value, size="2"),
            spacing="0",
            align_items="start",
            width="100%",
        ),
    )


def _piece_src(url: rx.Var[str], key: rx.Var[str]) -> rx.Var[str]:
    """An R2 object through `/r2media`, a local upload through the upload store."""
    return rx.cond(url != "", BACKEND_BASE + url, rx.get_upload_url(key))


def _angle_preview(angle: rx.Var) -> rx.Component:
    """The piece this angle produced, whole (`contain`: a 4:5 or 9:16 picture is never
    cropped to a strip) and a click away from full size; the system's empty frame while
    there is none."""
    has_piece = (angle.preview_url != "") | (angle.preview_key != "")
    return rx.box(
        media_thumb(
            _piece_src(angle.preview_url, angle.preview_key),
            has=has_piece,
            width="100%",
            height="18rem",
            fit="contain",
            alt=angle.title,
        ),
        rx.cond(
            has_piece,
            rx.box(
                rx.icon("maximize-2", size=T.ICON_SM),
                position="absolute",
                bottom="0.5rem",
                right="0.5rem",
                padding="0.3rem",
                border_radius=T.RADIUS_CONTROL,
                background=T.tone_color("neutral", 2),
                color=T.TEXT_MUTED,
                pointer_events="none",
            ),
        ),
        position="relative",
        width="100%",
        cursor=rx.cond(has_piece, "zoom-in", "default"),
        on_click=VariationsState.open_lightbox(angle.id),
        title="Ver en grande",
        role="button",
    )


def _angle_actions(angle: rx.Var) -> rx.Component:
    busy = VariationsState.busy_angle_id == angle.id
    return rx.hstack(
        rx.spacer(),
        rx.cond(
            angle.can_edit,
            rx.button(
                rx.icon("pencil", size=14),
                "Editar escenario",
                variant="soft",
                color_scheme="gray",
                size="1",
                disabled=busy,
                on_click=VariationsState.open_editor(angle.id),
            ),
        ),
        rx.cond(
            angle.can_discard,
            rx.button(
                rx.icon("circle-x", size=14),
                "Descartar",
                variant="soft",
                color_scheme="gray",
                size="1",
                disabled=busy,
                on_click=VariationsState.discard_angle(angle.id),
            ),
        ),
        rx.cond(
            angle.can_restore,
            rx.button(
                rx.icon("undo-2", size=14),
                "Recuperar",
                variant="soft",
                size="1",
                disabled=busy,
                on_click=VariationsState.restore_angle(angle.id),
            ),
        ),
        rx.cond(
            angle.can_retry,
            rx.button(
                rx.icon("refresh-cw", size=14),
                "Reintentar",
                variant="soft",
                color_scheme="gray",
                size="1",
                disabled=busy,
                on_click=VariationsState.retry_angle(angle.id),
            ),
        ),
        rx.cond(
            angle.can_regenerate,
            rx.button(
                rx.icon("refresh-cw", size=14),
                "Regenerar",
                variant="soft",
                color_scheme="gray",
                size="1",
                disabled=busy,
                on_click=VariationsState.regenerate_angle(angle.id),
                title="Otra toma del mismo escenario",
            ),
        ),
        rx.cond(
            angle.draft_id != "",
            rx.link(
                rx.button(
                    rx.icon("eye", size=14),
                    "Ver pieza",
                    variant="ghost",
                    color_scheme="gray",
                    size="1",
                ),
                href="/drafts/" + angle.draft_id,
                display="inline-flex",
                align_items="center",
                underline="none",
            ),
        ),
        rx.cond(
            angle.can_approve,
            rx.button(
                rx.icon("circle-check", size=14),
                "Aprobar",
                size="1",
                disabled=busy,
                on_click=VariationsState.approve_angle(angle.id),
            ),
        ),
        spacing="2",
        align="center",
        width="100%",
        wrap="wrap",
    )


def _angle_card(angle: rx.Var) -> rx.Component:
    discarded = angle.can_restore
    return card(
        rx.vstack(
            rx.hstack(
                rx.text(angle.position.to_string() + ".", size="2", color=T.TEXT_FAINT),
                rx.text(angle.title, size="2", weight="bold"),
                rx.spacer(),
                # once a piece exists its own state is the truth; the angle's own
                # label would read «En generación» next to «Listo para revisar»
                rx.cond(
                    angle.draft_label != "",
                    _tone_badge(angle.draft_label, angle.draft_tone),
                    _tone_badge(angle.status_label, angle.status_tone),
                ),
                spacing="2",
                align="center",
                width="100%",
            ),
            # only once a piece exists: a discarded angle showed an empty frame
            rx.cond(angle.draft_id != "", _angle_preview(angle)),
            _angle_field("Escenario", angle.scene),
            _angle_field("Composición", angle.composition),
            _angle_field("Gancho", angle.hook),
            _angle_field("Llamada a la acción", angle.cta),
            _angle_field("Por qué", angle.rationale),
            rx.cond(angle.failure_text != "", callout(angle.failure_text, "error")),
            rx.foreach(angle.warnings, lambda text: callout(text, "warn")),
            _angle_actions(angle),
            spacing="2",
            width="100%",
            opacity=rx.cond(discarded, "0.55", "1"),
        ),
        padding="0.9rem",
        width="100%",
    )


def _lightbox() -> rx.Component:
    """One piece at full size. Its source is the state's (the angle's preview as the
    last read left it), through the same two doors the thumbnail uses."""
    return rx.dialog.root(
        rx.dialog.content(
            rx.vstack(
                rx.hstack(
                    rx.dialog.title(VariationsState.lightbox_title, size="3", margin="0"),
                    rx.spacer(),
                    rx.dialog.close(
                        rx.icon_button(
                            rx.icon("x", size=T.ICON_MD),
                            variant="ghost",
                            color_scheme="gray",
                            size="2",
                            aria_label="Cerrar",
                        ),
                    ),
                    width="100%",
                    align="center",
                    spacing="3",
                ),
                rx.image(
                    src=_piece_src(VariationsState.lightbox_url, VariationsState.lightbox_key),
                    alt=VariationsState.lightbox_title,
                    width="100%",
                    max_height="80vh",
                    object_fit="contain",
                    border_radius=T.RADIUS_CONTROL,
                ),
                spacing="3",
                width="100%",
            ),
            max_width="min(60rem, 94vw)",
        ),
        open=VariationsState.lightbox_open,
        on_open_change=VariationsState.set_lightbox_open,
    )


def _editor_field(label: str, hint: str, control: rx.Component) -> rx.Component:
    return rx.vstack(
        rx.text(label, size="2", weight="medium"),
        control,
        rx.text(hint, size="1", color=T.TEXT_FAINT),
        spacing="1",
        width="100%",
        align_items="start",
    )


def _scene_editor() -> rx.Component:
    """The angle's scene and framing, in the operator's words. «Guardar» keeps them for
    the next piece; with a piece already on screen, «Guardar y regenerar» makes another
    take right away — a paid image."""
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(VariationsState.editor_title),
            rx.dialog.description(
                "Describe lo que debe mostrar la imagen. El producto siempre es el real: "
                "cambia lo que lo rodea, no el producto.",
                size="2",
                color=T.TEXT_MUTED,
            ),
            rx.vstack(
                _editor_field(
                    "Escenario",
                    "Dónde está el producto, sobre qué, con qué luz, qué lo acompaña.",
                    rx.text_area(
                        value=VariationsState.editor_scene,
                        on_change=VariationsState.set_editor_scene,
                        rows="4",
                        max_length=SCENE_MAX,
                        width="100%",
                    ),
                ),
                _editor_field(
                    "Composición",
                    "Plano, ángulo de cámara, dónde queda el producto y qué zona queda limpia.",
                    rx.text_area(
                        value=VariationsState.editor_composition,
                        on_change=VariationsState.set_editor_composition,
                        rows="2",
                        max_length=COMPOSITION_MAX,
                        width="100%",
                    ),
                ),
                rx.cond(
                    VariationsState.error != "",
                    callout(VariationsState.error, "error"),
                ),
                rx.flex(
                    rx.dialog.close(
                        rx.button(
                            "Cancelar",
                            variant="soft",
                            color_scheme="gray",
                            disabled=VariationsState.saving,
                        ),
                    ),
                    rx.spacer(),
                    rx.button(
                        "Guardar",
                        variant=rx.cond(VariationsState.editor_can_regenerate, "soft", "solid"),
                        loading=VariationsState.saving,
                        on_click=VariationsState.save_edit,
                    ),
                    rx.cond(
                        VariationsState.editor_can_regenerate,
                        rx.button(
                            rx.icon("refresh-cw", size=14),
                            "Guardar y regenerar",
                            loading=VariationsState.saving,
                            on_click=VariationsState.save_edit_and_regenerate,
                        ),
                    ),
                    spacing="3",
                    width="100%",
                ),
                spacing="3",
                width="100%",
                margin_top="1rem",
            ),
            max_width="36rem",
        ),
        open=VariationsState.editor_open,
        on_open_change=VariationsState.set_editor_open,
    )


def _angles_review() -> rx.Component:
    return rx.vstack(
        _lightbox(),
        _scene_editor(),
        card(
            rx.vstack(
                rx.hstack(
                    rx.vstack(
                        rx.text(VariationsState.product_name, size="3", weight="bold"),
                        rx.text(VariationsState.kept_label, size="1", color=T.TEXT_MUTED),
                        spacing="0",
                        align_items="start",
                    ),
                    rx.spacer(),
                    _tone_badge(
                        VariationsState.set_status_label,
                        VariationsState.set_status_tone,
                    ),
                    rx.button(
                        "Empezar de nuevo",
                        variant="ghost",
                        color_scheme="gray",
                        size="1",
                        on_click=VariationsState.start_over,
                    ),
                    spacing="3",
                    align="center",
                    width="100%",
                ),
                rx.cond(
                    VariationsState.set_price_note != "",
                    callout(VariationsState.set_price_note, "warn"),
                ),
                rx.cond(
                    VariationsState.set_failure_text != "",
                    callout(VariationsState.set_failure_text, "error"),
                ),
                rx.cond(
                    VariationsState.outcome_message != "",
                    rx.vstack(
                        _tone_callout(
                            VariationsState.outcome_message, VariationsState.outcome_tone
                        ),
                        rx.foreach(
                            VariationsState.outcome_details,
                            lambda text: rx.text(text, size="1", color=T.TEXT_MUTED),
                        ),
                        spacing="1",
                        width="100%",
                    ),
                ),
                rx.cond(VariationsState.poll_timed_out, callout(_POLL_TIMEOUT, "warn")),
                rx.cond(
                    VariationsState.can_generate,
                    rx.hstack(
                        rx.text(_NEXT_STEP, size="1", color=T.TEXT_MUTED),
                        rx.spacer(),
                        rx.button(
                            rx.icon("wand-sparkles", size=15),
                            VariationsState.generate_label,
                            size="2",
                            loading=VariationsState.generating,
                            on_click=VariationsState.generate_pieces,
                        ),
                        spacing="3",
                        align="center",
                        width="100%",
                    ),
                ),
                rx.cond(
                    VariationsState.in_flight,
                    callout(
                        "Generando las piezas. Esta pantalla se actualiza sola.",
                        "info",
                        icon="loader-circle",
                    ),
                ),
                spacing="3",
                width="100%",
            ),
            padding="1rem",
            width="100%",
        ),
        rx.grid(
            rx.foreach(VariationsState.angles, _angle_card),
            columns=rx.breakpoints(initial="1", lg="2"),
            spacing="3",
            width="100%",
        ),
        spacing="3",
        width="100%",
    )


def _set_row(summary: rx.Var) -> rx.Component:
    return rx.el.button(
        rx.hstack(
            rx.icon("layers", size=T.ICON_SM, color=T.TEXT_MUTED),
            rx.vstack(
                rx.text(summary.product_name, size="2", weight="bold"),
                rx.text(summary.created_label, size="1", color=T.TEXT_FAINT),
                spacing="0",
                align_items="start",
            ),
            rx.spacer(),
            _tone_badge(summary.status_label, summary.status_tone),
            spacing="3",
            align="center",
            width="100%",
        ),
        type="button",
        on_click=VariationsState.open_set(summary.id),
        class_name="q-choice-card",
        padding="0.6rem 0.8rem",
        width="100%",
    )


def _sets_list() -> rx.Component:
    """The sets already made, so one left open yesterday can be reopened."""
    return rx.cond(
        VariationsState.has_sets,
        rx.vstack(
            rx.text("Tus variaciones", size="1", color=T.TEXT_MUTED),
            rx.vstack(
                rx.foreach(VariationsState.sets, _set_row),
                spacing="2",
                width="100%",
            ),
            spacing="2",
            width="100%",
        ),
    )


# -- the view --------------------------------------------------------------------------------


def variations_view() -> rx.Component:
    """What `/create` shows while the «Variaciones» option is the chosen one."""
    return rx.vstack(
        rx.cond(VariationsState.error != "", callout(VariationsState.error, "error")),
        rx.cond(
            VariationsState.has_set,
            _angles_review(),
            rx.vstack(
                rx.text(_INTRO, size="2", color=T.TEXT_MUTED),
                _sets_list(),
                _product_step(),
                rx.cond(
                    VariationsState.product_chosen,
                    rx.vstack(
                        _product_facts(),
                        _preset_step(),
                        _plan_step(),
                        spacing="4",
                        width="100%",
                    ),
                ),
                spacing="4",
                width="100%",
            ),
        ),
        spacing="4",
        width="100%",
        min_width="0",
    )

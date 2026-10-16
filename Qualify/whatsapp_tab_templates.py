"""`/whatsapp` → Plantillas tab (WA-18, QUA-217): the number's message templates, «Sincronizar
con Meta», and the guided «Nueva plantilla» form with a live preview.

Same hook as the other tabs: `templates_tab()` renders only while the tab is active,
inside the shell's box keyed by `WhatsAppState.selected_connection_id`, so the root's
`on_mount` (`WhatsAppTemplatesState.ensure_loaded`) fires on tab entry and on every
number switch. The page never talks to the provider — only to the state.
"""

from __future__ import annotations

import reflex as rx

from .ui import (
    callout,
    card,
    chat_bubble,
    choice_card,
    choice_card_check,
    drawer,
    empty_state,
    mono,
    skeleton_rows,
    tag,
)
from .ui import tokens as T
from .whatsapp_marketing_ui import (
    confirm_action,
    field,
    ghost_refresh,
    retry_button,
    section_head,
    tone_banner,
    tone_pill,
)
from .whatsapp_templates_state import WhatsAppTemplatesState as S
from .whatsapp_templates_vm import (
    AUTHENTICATION_NOTICE,
    BUTTON_KINDS,
    BUTTONS_QUICK,
    BUTTONS_URL,
    CATEGORIES,
    CATEGORY_AUTHENTICATION,
    LANGUAGES,
    MAX_BUTTON_CHARS,
    MAX_FOOTER_CHARS,
    MAX_HEADER_CHARS,
    MAX_NAME_CHARS,
    MAX_URL_CHARS,
    REVIEW_NOTICE,
    ExampleFieldVM,
    TemplateVM,
)

# ======================================================================================
# The list
# ======================================================================================


def _delete_action(t: TemplateVM) -> rx.Component:
    return confirm_action(
        rx.button(
            rx.icon("trash-2", size=T.ICON_SM),
            "Eliminar",
            loading=S.deleting_id == t.template_id,
            variant="soft",
            size="1",
            **T.tone_scheme("neutral"),
        ),
        title="Eliminar plantilla",
        description=rx.text(
            "Meta elimina ",
            rx.text.strong(t.name),
            " en todos sus idiomas. Las campañas que la usan dejan de poder enviarse y el "
            "nombre no se puede reutilizar durante 30 días.",
        ),
        verb="Eliminar",
        on_confirm=S.delete(t.template_id),
    )


def _template_row(t: TemplateVM) -> rx.Component:
    return rx.table.row(
        rx.table.cell(
            rx.vstack(
                mono(t.name, weight="medium"),
                rx.text(
                    t.body_text,
                    size="1",
                    color=T.TEXT_MUTED,
                    max_width="28rem",
                    overflow="hidden",
                    text_overflow="ellipsis",
                    white_space="nowrap",
                ),
                rx.cond(
                    t.rejected_reason != "",
                    rx.text(t.rejected_reason, size="1", color=T.tone_color("error", 11)),
                    rx.fragment(),
                ),
                spacing="1",
                align_items="start",
            )
        ),
        rx.table.cell(rx.text(t.language_label, size="2")),
        rx.table.cell(tag(t.category_label)),
        rx.table.cell(tone_pill(t.status_label, t.status_tone)),
        rx.table.cell(tone_pill(t.quality_label, t.quality_tone)),
        rx.table.cell(rx.text(t.updated_at, size="1", color=T.TEXT_MUTED, class_name="q-nums")),
        rx.table.cell(rx.cond(t.can_delete, _delete_action(t), rx.fragment())),
        align="center",
    )


def _templates_table() -> rx.Component:
    return rx.box(
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("Plantilla"),
                    rx.table.column_header_cell("Idioma"),
                    rx.table.column_header_cell("Categoría"),
                    rx.table.column_header_cell("Estado"),
                    rx.table.column_header_cell("Calidad"),
                    rx.table.column_header_cell("Actualizada"),
                    rx.table.column_header_cell(""),
                )
            ),
            rx.table.body(rx.foreach(S.templates, _template_row)),
            variant="surface",
            width="100%",
        ),
        overflow_x="auto",
        width="100%",
    )


def _list() -> rx.Component:
    return rx.cond(
        S.ready,
        rx.cond(
            S.has_templates,
            _templates_table(),
            empty_state(
                "file-text",
                "Aún no hay plantillas en este número",
                "Las plantillas son los mensajes que puedes enviar fuera de la ventana de "
                "24 h, como una campaña. Crea la primera, o sincroniza las que ya tienes "
                "en WhatsApp Manager.",
                action=rx.button(
                    rx.icon("plus", size=16), "Nueva plantilla", on_click=S.open_form, size="3"
                ),
            ),
        ),
        rx.cond(
            S.failed,
            retry_button("Volver a leer las plantillas", S.reload),
            skeleton_rows(4, height="3.5rem"),
        ),
    )


# ======================================================================================
# «Nueva plantilla»
# ======================================================================================


def _category_card(key: str, label: str, hint: str) -> rx.Component:
    selected = S.form_category == key
    return choice_card(
        rx.hstack(
            rx.vstack(
                rx.text(label, size="2", weight="bold"),
                rx.text(hint, size="1", color=T.TEXT_MUTED),
                spacing="1",
                align_items="start",
            ),
            rx.spacer(),
            rx.cond(selected, choice_card_check(), rx.fragment()),
            align="start",
            width="100%",
        ),
        selected=selected,
        on_select=S.set_category(key),
        padding="0.75rem 1rem",
        text_align="left",
        width="100%",
    )


def _example_input(item: ExampleFieldVM) -> rx.Component:
    return rx.hstack(
        mono(item.placeholder, size="1", min_width="7rem", color=T.TEXT_MUTED),
        rx.input(
            value=item.value,
            on_change=lambda v: S.set_example(item.name, v),
            placeholder="Ejemplo: Ana",
            width="100%",
        ),
        align="center",
        width="100%",
        spacing="2",
    )


def _buttons_editor() -> rx.Component:
    return rx.vstack(
        rx.segmented_control.root(
            *[rx.segmented_control.item(label, value=key) for key, label in BUTTON_KINDS],
            value=S.form_button_kind,
            on_change=S.set_button_kind,
            size="1",
        ),
        rx.match(
            S.form_button_kind,
            (
                BUTTONS_QUICK,
                rx.grid(
                    *[
                        rx.input(
                            value=getattr(S, f"form_quick_{i}"),
                            on_change=lambda v, i=i: S.set_quick_reply(i, v),
                            max_length=MAX_BUTTON_CHARS,
                            placeholder=f"Respuesta {i}" + (" (opcional)" if i > 1 else ""),
                            width="100%",
                        )
                        for i in (1, 2, 3)
                    ],
                    columns=rx.breakpoints(initial="1", sm="3"),
                    spacing="2",
                    width="100%",
                ),
            ),
            (
                BUTTONS_URL,
                rx.grid(
                    rx.input(
                        value=S.form_url_text,
                        on_change=lambda v: S.set_field("url_text", v),
                        max_length=MAX_BUTTON_CHARS,
                        placeholder="Texto: Ver menú",
                        width="100%",
                    ),
                    rx.input(
                        value=S.form_url,
                        on_change=lambda v: S.set_field("url", v),
                        max_length=MAX_URL_CHARS,
                        placeholder="https://",
                        type="url",
                        width="100%",
                    ),
                    columns=rx.breakpoints(initial="1", sm="2"),
                    spacing="2",
                    width="100%",
                ),
            ),
            rx.fragment(),
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _form_fields() -> rx.Component:
    return rx.vstack(
        field(
            "Categoría",
            rx.vstack(
                *[_category_card(k, label, hint) for k, label, hint in CATEGORIES],
                spacing="2",
                width="100%",
                role="radiogroup",
                aria_label="Categoría",
            ),
        ),
        rx.cond(
            S.form_category == CATEGORY_AUTHENTICATION,
            callout(AUTHENTICATION_NOTICE, "info"),
            rx.fragment(),
        ),
        rx.grid(
            field(
                "Nombre",
                rx.input(
                    value=S.form_name,
                    on_change=lambda v: S.set_field("name", v),
                    max_length=MAX_NAME_CHARS,
                    placeholder="promo_octubre",
                    width="100%",
                    class_name="q-mono",
                ),
                "Minúsculas, números y guion bajo. Lo ve tu equipo, no el cliente.",
            ),
            field(
                "Idioma",
                rx.select.root(
                    rx.select.trigger(width="100%"),
                    rx.select.content(
                        *[rx.select.item(label, value=key) for key, label in LANGUAGES]
                    ),
                    value=S.form_language,
                    on_change=S.set_language,
                ),
            ),
            columns=rx.breakpoints(initial="1", sm="2"),
            spacing="3",
            width="100%",
        ),
        field(
            "Encabezado (opcional)",
            rx.input(
                value=S.form_header,
                on_change=lambda v: S.set_field("header", v),
                max_length=MAX_HEADER_CHARS,
                placeholder="Ej.: Novedades de octubre",
                width="100%",
            ),
            f"Texto en negrita arriba del mensaje. Hasta {MAX_HEADER_CHARS} caracteres, "
            "sin variables.",
        ),
        field(
            "Mensaje",
            rx.text_area(
                value=S.form_body,
                on_change=lambda v: S.set_field("body", v),
                rows="5",
                placeholder=(
                    "Hola {{nombre}}, esta semana tu pedido {{pedido}} viene con envío gratis."
                ),
                width="100%",
            ),
            rx.hstack(
                rx.text(
                    "Usa variables entre dobles llaves: {{nombre}}. No pueden ir al principio "
                    "ni al final.",
                    size="1",
                    color=T.TEXT_MUTED,
                ),
                rx.spacer(),
                rx.text(S.body_count, size="1", color=T.TEXT_FAINT, class_name="q-nums"),
                width="100%",
            ),
        ),
        rx.cond(
            S.form_examples_fields.length() > 0,
            field(
                "Ejemplos de las variables",
                rx.vstack(
                    rx.foreach(S.form_examples_fields, _example_input),
                    spacing="2",
                    width="100%",
                ),
                "Meta los exige para revisar la plantilla. No se envían a tus clientes.",
            ),
            rx.fragment(),
        ),
        field(
            "Pie (opcional)",
            rx.input(
                value=S.form_footer,
                on_change=lambda v: S.set_field("footer", v),
                max_length=MAX_FOOTER_CHARS,
                placeholder="Ej.: Responde BAJA para no recibir más mensajes",
                width="100%",
            ),
            f"Texto pequeño debajo del mensaje. Hasta {MAX_FOOTER_CHARS} caracteres.",
        ),
        field("Botones", _buttons_editor()),
        spacing="4",
        width="100%",
        align_items="start",
    )


def _preview_button(label: rx.Var[str]) -> rx.Component:
    return card(
        rx.text(label, size="2", weight="medium", text_align="center"),
        padding="0.5rem 0.75rem",
    )


def _preview() -> rx.Component:
    return rx.vstack(
        rx.text("Así lo verá tu cliente", size="1", color=T.TEXT_MUTED),
        chat_bubble(
            rx.cond(
                S.preview_header != "",
                rx.text(S.preview_header, size="2", weight="bold"),
                rx.fragment(),
            ),
            rx.text(
                rx.cond(S.preview_text != "", S.preview_text, "Escribe el mensaje…"),
                size="2",
                white_space="pre-wrap",
            ),
            rx.cond(
                S.preview_footer != "",
                rx.text(S.preview_footer, size="1", color=T.TEXT_MUTED),
                rx.fragment(),
            ),
            direction="out",
            max_width="100%",
        ),
        rx.vstack(
            rx.foreach(S.preview_button_labels, _preview_button),
            spacing="1",
            width="100%",
        ),
        spacing="2",
        width="100%",
        align_items="start",
        position="sticky",
        top="0",
    )


def _form_footer() -> rx.Component:
    return rx.vstack(
        rx.cond(
            S.form_error != "",
            tone_banner(S.form_error, S.form_error_tone),
            rx.fragment(),
        ),
        rx.hstack(
            rx.text(
                rx.cond(S.form_problem != "", S.form_problem, REVIEW_NOTICE),
                size="1",
                color=T.TEXT_MUTED,
                flex="1",
            ),
            rx.button(
                rx.icon("send", size=16),
                "Enviar a revisión",
                on_click=S.submit,
                loading=S.submitting,
                disabled=S.form_problem != "",
                size="2",
            ),
            align="center",
            spacing="3",
            width="100%",
        ),
        spacing="2",
        width="100%",
    )


def template_form() -> rx.Component:
    return drawer(
        rx.grid(
            _form_fields(),
            _preview(),
            columns=rx.breakpoints(initial="1", md="2"),
            spacing="5",
            width="100%",
            align_items="start",
        ),
        open=S.form_open,
        on_open_change=S.set_form_open,
        title="Nueva plantilla",
        description="Meta la revisa antes de que puedas enviarla.",
        footer=_form_footer(),
        width="56rem",
        icon="file-plus",
    )


# ======================================================================================
# The tab
# ======================================================================================


def templates_tab() -> rx.Component:
    return rx.vstack(
        tone_banner(S.banner, S.banner_tone),
        section_head(
            "Plantillas",
            ghost_refresh("Sincronizar con Meta", S.sync, loading=S.syncing),
            rx.button(rx.icon("plus", size=16), "Nueva plantilla", on_click=S.open_form, size="2"),
        ),
        rx.text(
            "Las plantillas son los mensajes aprobados por Meta que puedes enviar cuando el "
            "cliente no te ha escrito en las últimas 24 h — por ejemplo, en una campaña. "
            + REVIEW_NOTICE,
            size="2",
            color=T.TEXT_MUTED,
        ),
        _list(),
        template_form(),
        spacing="4",
        width="100%",
        align_items="start",
        on_mount=S.ensure_loaded,
    )

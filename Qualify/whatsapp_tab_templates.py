"""`/whatsapp` → Plantillas tab (WA-18, QUA-217): the number's message templates, «Ver si
ya las aprobaron», and «Crear un mensaje» — four guided steps with the preview at the end
(m-24842997): the owner never types `{{…}}` nor an underscore.

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
    skeleton_rows,
    stepper,
    tag,
)
from .ui import tokens as T
from .whatsapp_marketing_ui import (
    card_line,
    confirm_action,
    field,
    ghost_refresh,
    retry_button,
    section_head,
    table_or_cards,
    tone_banner,
    tone_pill,
)
from .whatsapp_templates_state import WhatsAppTemplatesState as S
from .whatsapp_templates_vm import (
    ADD_NAME_LABEL,
    BUTTON_KINDS,
    BUTTONS_QUICK,
    BUTTONS_URL,
    CATEGORY_UTILITY,
    DONE_HINT_PROMO,
    DONE_HINT_UTILITY,
    FORM_REVIEW_NOTICE,
    FORM_TITLE,
    GUIDED_CATEGORIES,
    LANGUAGES,
    MAX_BUTTON_CHARS,
    MAX_FOOTER_CHARS,
    MAX_HEADER_CHARS,
    MAX_LABEL_CHARS,
    MAX_URL_CHARS,
    NAME_HINT_PROMO,
    NAME_HINT_UTILITY,
    NEXT_STEP_CHATS,
    NEXT_STEP_CONTACTS,
    RESTART_LABEL,
    RESUME_NOTICE,
    REVIEW_NOTICE,
    STEP_BUTTONS,
    STEP_KIND,
    STEP_KIND_HINT,
    STEP_MESSAGE,
    STEP_REVIEW,
    STEP_TITLES,
    STEPS,
    SUBMIT_LABEL,
    SUBMITTED_MESSAGE,
    TemplateVM,
)

# N12: every target is thumb-sized at 360 px.
_TAP = {"min_height": "44px"}

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
            **_TAP,
            **T.tone_scheme("neutral"),
        ),
        title="¿Eliminar este mensaje?",
        description=rx.text(
            "Se borra ",
            rx.text.strong(t.display_name),
            " en todos sus idiomas. Las promociones que lo usan ya no se podrán enviar.",
        ),
        verb="Eliminar",
        on_confirm=S.delete(t.template_id),
    )


def _template_row(t: TemplateVM) -> rx.Component:
    return rx.table.row(
        rx.table.cell(
            rx.vstack(
                rx.text(t.display_name, size="2", weight="medium"),
                rx.text(
                    t.body_preview,
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


def _template_card(t: TemplateVM) -> rx.Component:
    """Phone (m-24842998): one approved message per card, its text wrapped, never cut."""
    return card(
        rx.vstack(
            rx.text(t.display_name, size="3", weight="medium"),
            card_line(tone_pill(t.status_label, t.status_tone), tag(t.category_label)),
            rx.text(t.body_preview, size="2", color=T.TEXT_MUTED),
            rx.cond(
                t.rejected_reason != "",
                rx.text(t.rejected_reason, size="2", color=T.tone_color("error", 11)),
                rx.fragment(),
            ),
            rx.text(
                t.language_label + " · " + t.updated_at,
                size="1",
                color=T.TEXT_MUTED,
                class_name="q-nums",
            ),
            rx.cond(t.can_delete, _delete_action(t), rx.fragment()),
            spacing="2",
            width="100%",
            align_items="start",
        ),
        padding="1rem",
    )


def _templates_list() -> rx.Component:
    return table_or_cards(
        _templates_table(),
        rx.vstack(rx.foreach(S.templates, _template_card), spacing="3", width="100%"),
    )


def _templates_table() -> rx.Component:
    return rx.box(
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("Mensaje"),
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
            _templates_list(),
            empty_state(
                "file-text",
                "Aún no hay plantillas en este número",
                "Estos mensajes, una vez que Meta los aprueba, te sirven para escribirle a un "
                "cliente después de 24 horas o para enviar una promoción. Crea el primero. "
                "Si ya tienes mensajes aprobados en Meta, toca «Ver si ya las aprobaron» y "
                "aparecerán aquí.",
                action=rx.button(
                    rx.icon("plus", size=16), FORM_TITLE, on_click=S.open_form, size="3", **_TAP
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
# «Crear un mensaje» (m-24842997): four steps, the preview at the end
# ======================================================================================


def _fold(title: str, value: str, content: rx.Component) -> rx.Component:
    return rx.accordion.root(
        rx.accordion.item(
            header=title,
            content=content,
            value=value,
            style={"& button": {"min_height": "44px", "width": "100%"}},
        ),
        collapsible=True,
        variant="ghost",
        width="100%",
    )


def _step_heading(step: int, hint: str) -> rx.Component:
    return rx.vstack(
        rx.heading(STEP_TITLES[step], size="4", as_="h3"),
        rx.text(hint, size="2", color=T.TEXT_MUTED),
        spacing="1",
        width="100%",
        align_items="start",
    )


def _category_card(key: str, label: str, hint: str) -> rx.Component:
    selected = S.form_category == key
    return choice_card(
        rx.hstack(
            rx.vstack(
                rx.text(label, size="3", weight="bold"),
                rx.text(hint, size="2", color=T.TEXT_MUTED),
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
        padding="0.875rem 1rem",
        text_align="left",
        width="100%",
        **_TAP,
    )


def _step_kind() -> rx.Component:
    """① ¿Qué quieres avisar?"""
    return rx.vstack(
        _step_heading(STEP_KIND, STEP_KIND_HINT),
        rx.vstack(
            *[_category_card(k, label, hint) for k, label, hint in GUIDED_CATEGORIES],
            spacing="2",
            width="100%",
            role="radiogroup",
            aria_label=STEP_TITLES[STEP_KIND],
        ),
        spacing="4",
        width="100%",
        align_items="start",
    )


def _more_options() -> rx.Component:
    """«Más opciones»: the name to recognise it by, the language and the extras — all
    filled in already, so the owner can skip them."""
    return rx.vstack(
        field(
            "Nombre para reconocerlo",
            rx.input(
                value=S.form_label,
                on_change=lambda v: S.set_field("label", v),
                max_length=MAX_LABEL_CHARS,
                placeholder=S.label_placeholder,
                width="100%",
                size="3",
            ),
            "Solo lo ves tú, en la lista de mensajes. Si no escribes nada, usamos el que "
            "aparece en gris.",
        ),
        field(
            "Idioma",
            rx.select.root(
                rx.select.trigger(width="100%", **_TAP),
                rx.select.content(*[rx.select.item(label, value=key) for key, label in LANGUAGES]),
                value=S.form_language,
                on_change=S.set_language,
                size="3",
            ),
        ),
        field(
            "Título en negrita (opcional)",
            rx.input(
                value=S.form_header,
                on_change=lambda v: S.set_field("header", v),
                max_length=MAX_HEADER_CHARS,
                placeholder="Ej.: Novedades de octubre",
                width="100%",
                size="3",
            ),
            f"Va arriba del mensaje. Hasta {MAX_HEADER_CHARS} caracteres.",
        ),
        field(
            "Texto pequeño al final (opcional)",
            rx.input(
                value=S.form_footer,
                on_change=lambda v: S.set_field("footer", v),
                max_length=MAX_FOOTER_CHARS,
                placeholder="Ej.: Válido hasta el domingo",
                width="100%",
                size="3",
            ),
            f"Va debajo del mensaje. Hasta {MAX_FOOTER_CHARS} caracteres.",
        ),
        spacing="4",
        width="100%",
        align_items="start",
        padding_top="0.5rem",
    )


def _step_message() -> rx.Component:
    """② Escribe el mensaje — the name is a button, never `{{…}}`."""
    return rx.vstack(
        _step_heading(
            STEP_MESSAGE,
            "Escríbelo como se lo dirías a tu cliente. Si quieres saludarlo por su nombre, "
            "toca el botón y aparecerá [nombre] en el texto.",
        ),
        rx.text_area(
            value=S.form_body,
            on_change=lambda v: S.set_field("body", v),
            rows="6",
            placeholder="Ej.: Hola, esta semana tu segundo helado va por la mitad de precio.",
            width="100%",
            size="3",
            aria_label=STEP_TITLES[STEP_MESSAGE],
        ),
        rx.hstack(
            rx.button(
                rx.icon("user-plus", size=16),
                ADD_NAME_LABEL,
                on_click=S.add_name,
                variant="soft",
                size="3",
                **_TAP,
            ),
            rx.spacer(),
            rx.text(S.body_count, size="1", color=T.TEXT_FAINT, class_name="q-nums"),
            align="center",
            width="100%",
            wrap="wrap",
            spacing="2",
        ),
        rx.text(
            rx.cond(S.form_category == CATEGORY_UTILITY, NAME_HINT_UTILITY, NAME_HINT_PROMO),
            size="1",
            color=T.TEXT_MUTED,
        ),
        _fold("Más opciones", "more", _more_options()),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _button_kind_choice(key: str, label: str) -> rx.Component:
    selected = S.form_button_kind == key
    return choice_card(
        rx.hstack(
            rx.text(label, size="2", weight="medium"),
            rx.spacer(),
            rx.cond(selected, choice_card_check(), rx.fragment()),
            align="center",
            width="100%",
        ),
        selected=selected,
        on_select=S.set_button_kind(key),
        padding="0.75rem 1rem",
        text_align="left",
        width="100%",
        **_TAP,
    )


def _step_buttons() -> rx.Component:
    """③ Botones (opcional)."""
    return rx.vstack(
        _step_heading(
            STEP_BUTTONS,
            "Con un botón tu cliente responde con un toque. Puedes seguir sin botones.",
        ),
        rx.vstack(
            *[_button_kind_choice(key, label) for key, label in BUTTON_KINDS],
            spacing="2",
            width="100%",
            role="radiogroup",
            aria_label=STEP_TITLES[STEP_BUTTONS],
        ),
        rx.match(
            S.form_button_kind,
            (
                BUTTONS_QUICK,
                field(
                    "Respuestas que puede tocar tu cliente",
                    rx.vstack(
                        *[
                            rx.input(
                                value=getattr(S, f"form_quick_{i}"),
                                on_change=lambda v, i=i: S.set_quick_reply(i, v),
                                max_length=MAX_BUTTON_CHARS,
                                placeholder=(
                                    "Ej.: Lo quiero" if i == 1 else f"Respuesta {i} (opcional)"
                                ),
                                aria_label=(
                                    "Respuesta 1" if i == 1 else f"Respuesta {i} (opcional)"
                                ),
                                width="100%",
                                size="3",
                            )
                            for i in (1, 2, 3)
                        ],
                        spacing="2",
                        width="100%",
                    ),
                    f"Hasta {MAX_BUTTON_CHARS} caracteres cada una.",
                ),
            ),
            (
                BUTTONS_URL,
                rx.vstack(
                    field(
                        "Texto del botón",
                        rx.input(
                            value=S.form_url_text,
                            on_change=lambda v: S.set_field("url_text", v),
                            max_length=MAX_BUTTON_CHARS,
                            placeholder="Ej.: Ver el menú",
                            width="100%",
                            size="3",
                        ),
                    ),
                    field(
                        "Enlace que abre",
                        rx.input(
                            value=S.form_url,
                            on_change=lambda v: S.set_field("url", v),
                            max_length=MAX_URL_CHARS,
                            placeholder="https://",
                            type="url",
                            width="100%",
                            size="3",
                        ),
                    ),
                    spacing="3",
                    width="100%",
                ),
            ),
            rx.fragment(),
        ),
        spacing="4",
        width="100%",
        align_items="start",
    )


def _preview_button(label: rx.Var[str]) -> rx.Component:
    return card(
        rx.text(label, size="2", weight="medium", text_align="center"),
        padding="0.625rem 0.75rem",
    )


def _summary_line(label: str, value: rx.Var[str]) -> rx.Component:
    return rx.hstack(
        rx.text(label, size="2", color=T.TEXT_MUTED),
        rx.text(value, size="2", weight="medium"),
        spacing="2",
        align="baseline",
        wrap="wrap",
    )


def _step_review() -> rx.Component:
    """④ Así lo verá tu cliente — the preview, then «Enviar a aprobación»."""
    return rx.vstack(
        _step_heading(
            STEP_REVIEW,
            "Revisa el mensaje. Si quieres cambiar algo, toca «Atrás»: no se pierde nada.",
        ),
        chat_bubble(
            rx.cond(
                S.preview_header != "",
                rx.text(S.preview_header, size="2", weight="bold"),
                rx.fragment(),
            ),
            rx.text(S.preview_text, size="2", white_space="pre-wrap"),
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
        rx.vstack(
            _summary_line("Tipo:", S.form_kind_label),
            _summary_line("Lo reconocerás como:", S.form_display_name),
            _summary_line("Idioma:", S.form_language_label),
            spacing="1",
            width="100%",
            align_items="start",
        ),
        rx.text(FORM_REVIEW_NOTICE, size="1", color=T.TEXT_MUTED),
        spacing="4",
        width="100%",
        align_items="start",
    )


def _done() -> rx.Component:
    """N3: the exact notice once Meta has the message, and the next step under it."""
    return rx.vstack(
        callout(SUBMITTED_MESSAGE, "ok", icon="circle-check"),
        rx.cond(
            S.form_category == CATEGORY_UTILITY,
            rx.vstack(
                rx.text(DONE_HINT_UTILITY, size="2", color=T.TEXT_MUTED),
                rx.button(
                    rx.icon("message-circle", size=16),
                    NEXT_STEP_CHATS,
                    on_click=S.see_chats,
                    size="3",
                    width=rx.breakpoints(initial="100%", sm="auto"),
                    **_TAP,
                ),
                spacing="4",
                width="100%",
                align_items="start",
            ),
            rx.vstack(
                rx.text(DONE_HINT_PROMO, size="2", color=T.TEXT_MUTED),
                rx.button(
                    rx.icon("users", size=16),
                    NEXT_STEP_CONTACTS,
                    on_click=S.see_contacts,
                    size="3",
                    width=rx.breakpoints(initial="100%", sm="auto"),
                    **_TAP,
                ),
                spacing="4",
                width="100%",
                align_items="start",
            ),
        ),
        spacing="4",
        width="100%",
        align_items="start",
    )


def _form_footer() -> rx.Component:
    return rx.cond(
        S.form_done,
        rx.hstack(
            rx.spacer(),
            rx.button(
                "Cerrar",
                on_click=S.set_form_open(False),
                variant="soft",
                size="3",
                **_TAP,
                **T.tone_scheme("neutral"),
            ),
            width="100%",
        ),
        rx.vstack(
            rx.cond(
                S.form_error != "",
                tone_banner(S.form_error, S.form_error_tone),
                rx.cond(
                    S.step_problem != "",
                    rx.text(S.step_problem, size="1", color=T.TEXT_MUTED),
                    rx.fragment(),
                ),
            ),
            rx.hstack(
                rx.cond(
                    S.step > STEP_KIND,
                    rx.button(
                        rx.icon("chevron-left", size=16),
                        "Atrás",
                        on_click=S.back,
                        variant="soft",
                        size="3",
                        disabled=S.submitting,
                        **_TAP,
                        **T.tone_scheme("neutral"),
                    ),
                    rx.fragment(),
                ),
                rx.spacer(),
                rx.cond(
                    S.step == STEP_REVIEW,
                    rx.button(
                        rx.icon("send", size=16),
                        SUBMIT_LABEL,
                        on_click=S.submit,
                        loading=S.submitting,
                        disabled=S.form_problem != "",
                        size="3",
                        **_TAP,
                    ),
                    rx.button(
                        "Siguiente",
                        rx.icon("chevron-right", size=16),
                        on_click=S.next_step,
                        disabled=S.step_problem != "",
                        size="3",
                        **_TAP,
                    ),
                ),
                align="center",
                spacing="3",
                width="100%",
            ),
            spacing="2",
            width="100%",
        ),
    )


def _resume_notice() -> rx.Component:
    """N6: the drawer was closed with answers in it; they are all still here."""
    return rx.hstack(
        callout(RESUME_NOTICE, "info", icon="history", flex="1", min_width="12rem"),
        rx.button(
            rx.icon("rotate-ccw", size=16),
            RESTART_LABEL,
            on_click=S.restart_form,
            variant="soft",
            size="3",
            disabled=S.submitting,
            **_TAP,
            **T.tone_scheme("neutral"),
        ),
        align="center",
        spacing="2",
        width="100%",
        wrap="wrap",
    )


def template_form() -> rx.Component:
    return drawer(
        rx.cond(
            S.form_done,
            _done(),
            rx.vstack(
                rx.cond(S.form_resumed, _resume_notice(), rx.fragment()),
                rx.text(
                    "Paso ",
                    S.step + 1,
                    f" de {len(STEPS)}",
                    size="1",
                    color=T.TEXT_MUTED,
                    class_name="q-nums",
                ),
                stepper(
                    list(STEPS),
                    current=S.step,
                    completed=S.completed_steps,
                    on_select=S.go_to_step,
                ),
                rx.match(
                    S.step,
                    (STEP_KIND, _step_kind()),
                    (STEP_MESSAGE, _step_message()),
                    (STEP_BUTTONS, _step_buttons()),
                    (STEP_REVIEW, _step_review()),
                    _step_kind(),
                ),
                spacing="4",
                width="100%",
                align_items="start",
            ),
        ),
        open=S.form_open,
        on_open_change=S.set_form_open,
        title=FORM_TITLE,
        description=(
            "Meta lo aprueba antes de que puedas enviarlo. Te guiamos para que salga a la primera."
        ),
        footer=_form_footer(),
        width="40rem",
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
            ghost_refresh("Ver si ya las aprobaron", S.sync, loading=S.syncing),
            rx.button(rx.icon("plus", size=16), FORM_TITLE, on_click=S.open_form, size="3", **_TAP),
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

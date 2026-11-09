"""A short, reviewable form editor; publishing a form never activates an ad."""

from __future__ import annotations

import reflex as rx

from .ad_forms_state import AdFormsState as S
from .ad_forms_vm import FORM_NOTICE, WHATSAPP_NOTICE, AdFormVM, FormConnectionVM
from .ui import (
    app_shell,
    callout,
    card,
    choice_card,
    empty_state,
    page_body,
    page_header,
    signal_pill,
    skeleton_rows,
    step_foot,
    step_frame,
    step_head,
    step_sync,
)
from .ui import tokens as T


def _field(label: str, name: str, value: rx.Var[str], **props: object) -> rx.Component:
    field_id = "ad-form-" + name
    return rx.vstack(
        rx.el.label(label, html_for=field_id, font_weight="500"),
        rx.input(
            id=field_id,
            value=value,
            on_change=lambda text: S.edit(name, text),
            disabled=S.busy | ((S.selected.id != "") & ~S.selected.editable),
            size="3",
            min_height="44px",
            width="100%",
            **props,
        ),
        spacing="2",
        width="100%",
    )


def _connection(row: FormConnectionVM) -> rx.Component:
    return choice_card(
        rx.vstack(
            rx.text(row.label, weight="medium", overflow_wrap="anywhere"),
            rx.cond(row.reason != "", rx.text(row.reason, size="2", color=T.TEXT_MUTED)),
            spacing="1",
            width="100%",
            align_items="start",
        ),
        selected=S.draft.connection_id == row.id,
        on_select=S.choose_connection(row.id),
        disabled=S.busy | ~row.available | (S.selected.id != ""),
        min_height="44px",
        width="100%",
    )


def _page_choice() -> rx.Component:
    return rx.vstack(
        rx.text("Esta página será la dueña del formulario.", color=T.TEXT_MUTED),
        rx.vstack(
            rx.foreach(S.connections, _connection),
            role="radiogroup",
            aria_label="Página de tu negocio",
            spacing="3",
            width="100%",
        ),
        _field(
            "Nombre para reconocer el formulario",
            "name",
            S.draft.name,
            placeholder="Consulta de viajes",
        ),
        spacing="4",
        width="100%",
    )


def _question_choice(label: str, name: str, value: rx.Var[bool]) -> rx.Component:
    return rx.checkbox(
        label,
        checked=value,
        on_change=lambda enabled: S.ask(name, enabled),
        disabled=S.busy,
        min_height="44px",
        size="3",
    )


def _questions() -> rx.Component:
    return rx.vstack(
        rx.text("Pide solo lo que necesitas para atender su consulta.", color=T.TEXT_MUTED),
        _question_choice("Nombre completo", "ask_name", S.draft.ask_name),
        _question_choice("Correo electrónico", "ask_email", S.draft.ask_email),
        _question_choice("Teléfono", "ask_phone", S.draft.ask_phone),
        rx.text("Pide al menos un correo o un teléfono.", size="2", color=T.TEXT_MUTED),
        rx.el.label(
            "Otras preguntas (opcional)", html_for="ad-form-custom-questions", font_weight="500"
        ),
        rx.text_area(
            id="ad-form-custom-questions",
            value=S.draft.custom_questions,
            on_change=lambda text: S.edit("custom_questions", text),
            placeholder="¿Qué destino te interesa?",
            disabled=S.busy,
            width="100%",
            min_height="100px",
        ),
        rx.text(
            "Una pregunta por línea. Hasta tres, de 120 caracteres cada una.",
            size="2",
            color=T.TEXT_MUTED,
        ),
        rx.text(
            "Si quieres dar opciones, escríbelas así: Destino | Playa | Montaña",
            size="2",
            color=T.TEXT_MUTED,
        ),
        callout(WHATSAPP_NOTICE, "info"),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _privacy() -> rx.Component:
    return rx.vstack(
        rx.text(
            "Las personas deben poder consultar cómo trata tu negocio sus datos. "
            "Usa el enlace público de su política de privacidad.",
            color=T.TEXT_MUTED,
        ),
        _field(
            "Política de privacidad",
            "privacy_url",
            S.draft.privacy_url,
            type="url",
            placeholder="https://tu-negocio.com/privacidad",
        ),
        rx.text("Incluiremos este enlace en el formulario de Meta.", size="2", color=T.TEXT_MUTED),
        spacing="3",
        width="100%",
    )


def _thank_you() -> rx.Component:
    return rx.vstack(
        _field(
            "Título de agradecimiento", "thank_you_title", S.draft.thank_you_title, max_length=60
        ),
        _field(
            "Mensaje de agradecimiento", "thank_you_body", S.draft.thank_you_body, max_length=200
        ),
        _field(
            "Página que podrán abrir al terminar",
            "thank_you_url",
            S.draft.thank_you_url,
            type="url",
            placeholder="https://tu-negocio.com",
        ),
        rx.text("El formulario se creará en español.", size="2", color=T.TEXT_MUTED),
        spacing="4",
        width="100%",
    )


def _review() -> rx.Component:
    return rx.vstack(
        rx.heading(S.draft.name, size="4", as_="h2", overflow_wrap="anywhere"),
        rx.text("Página del negocio", weight="medium"),
        rx.text(S.page_label, overflow_wrap="anywhere"),
        rx.text("Datos y preguntas", weight="medium"),
        rx.text(S.questions_label, overflow_wrap="anywhere"),
        rx.text("Política de privacidad", weight="medium"),
        rx.link(
            "Leer política de privacidad ↗",
            href=S.draft.privacy_url,
            target="_blank",
            rel="noopener noreferrer",
            min_height="44px",
        ),
        rx.text("Al terminar", weight="medium"),
        rx.text(S.draft.thank_you_title, weight="medium"),
        rx.text(S.draft.thank_you_body, overflow_wrap="anywhere"),
        rx.link(
            "Abrir página de agradecimiento ↗",
            href=S.draft.thank_you_url,
            target="_blank",
            rel="noopener noreferrer",
            min_height="44px",
        ),
        callout(FORM_NOTICE, "info"),
        callout(WHATSAPP_NOTICE, "info"),
        rx.cond(
            S.selected.id != "",
            signal_pill(S.selected.status_label, S.selected.tone),
        ),
        rx.cond(
            S.saved_current & S.selected.editable,
            rx.checkbox(
                "Revisé los datos y autorizo crear este formulario en Meta.",
                checked=S.publish_consent,
                on_change=S.consent,
                disabled=S.busy,
                min_height="44px",
                size="3",
            ),
        ),
        rx.cond(
            (S.selected.id != "") & ~S.selected.editable & ~S.selected.published,
            callout(
                "La creación necesita comprobación. No repitas la operación; "
                "revisa el formulario en Meta antes de continuar.",
                "warn",
            ),
        ),
        rx.cond(
            S.selected.published,
            rx.vstack(
                rx.heading("Recibir las respuestas", size="3", as_="h3"),
                rx.text(
                    "Esta autorización habilita la recepción para los formularios "
                    "de esta página que Qualify reconoce. No envía mensajes ni crea anuncios.",
                    size="2",
                    color=T.TEXT_MUTED,
                ),
                rx.checkbox(
                    "Quiero recibir en Qualify los datos que envíen a estos formularios.",
                    checked=S.receive_consent,
                    on_change=S.consent_to_receive,
                    disabled=S.busy,
                    min_height="44px",
                    size="3",
                ),
                rx.button(
                    "Activar recepción de datos",
                    on_click=S.receive_answers,
                    disabled=S.busy | ~S.receive_consent,
                    min_height="44px",
                    size="3",
                ),
                rx.link(
                    "Ver clientes interesados",
                    href="/responder?tab=interesados",
                    min_height="44px",
                ),
                spacing="3",
                align_items="start",
                width="100%",
            ),
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _editor() -> rx.Component:
    locked = (S.selected.id != "") & ~S.selected.editable
    footer = rx.cond(
        locked,
        rx.button(
            "Volver a formularios",
            on_click=S.close_editor,
            variant="soft",
            min_height="44px",
            disabled=S.busy,
        ),
        rx.cond(
            S.step == 5,
            rx.cond(
                S.saved_current,
                step_foot(
                    "Crear formulario en Meta",
                    step=S.step,
                    on_primary=S.publish,
                    on_back=S.back_step,
                    primary_disabled=~S.can_publish,
                    primary_busy=S.busy,
                ),
                step_foot(
                    "Guardar borrador",
                    step=S.step,
                    on_primary=S.save,
                    on_back=S.back_step,
                    primary_disabled=S.busy,
                    primary_busy=S.busy,
                ),
            ),
            step_foot(
                "Siguiente",
                step=S.step,
                on_primary=S.next_step,
                on_back=S.back_step,
                primary_disabled=S.busy,
            ),
        ),
    )
    return step_frame(
        step_sync(S.step, S.direction),
        rx.cond(S.error != "", callout(S.error, "error")),
        rx.cond(S.notice != "", callout(S.notice, "info")),
        rx.match(
            S.step,
            (1, _page_choice()),
            (2, _questions()),
            (3, _privacy()),
            (4, _thank_you()),
            _review(),
        ),
        head=step_head(
            S.title, step=S.step, total=5, back_label="Formularios", on_exit=S.close_editor
        ),
        foot=footer,
        step=S.step,
        direction=S.direction,
        on_pop=S.read_step,
    )


def _form_card(row: AdFormVM) -> rx.Component:
    return card(
        rx.vstack(
            rx.text(row.name, weight="medium", overflow_wrap="anywhere"),
            rx.text("Página: " + row.page_label, size="2", color=T.TEXT_MUTED),
            signal_pill(row.status_label, row.tone),
            rx.button(
                rx.cond(row.editable, "Revisar borrador", "Ver formulario"),
                on_click=S.open_form(row.id),
                variant="soft",
                min_height="44px",
                disabled=S.busy,
            ),
            rx.cond(
                row.published,
                rx.button(
                    "Consultar respuestas",
                    on_click=S.refresh_answers(row.id),
                    variant="outline",
                    min_height="44px",
                    disabled=S.busy,
                ),
            ),
            spacing="3",
            align_items="start",
            width="100%",
        ),
        width="100%",
    )


def ad_forms_index() -> rx.Component:
    listing = rx.fragment(
        page_header("Formularios", "Recibe los datos de las personas interesadas en tu negocio."),
        page_body(
            rx.link("Volver a Anuncios", href="/promotions", min_height="44px"),
            rx.cond(S.error != "", callout(S.error, "error")),
            rx.cond(S.notice != "", callout(S.notice, "info")),
            rx.cond(
                S.loading,
                skeleton_rows(3),
                rx.vstack(
                    rx.cond(
                        S.has_unfinished,
                        rx.vstack(
                            rx.text(
                                "Tienes un formulario en curso. Los cambios sin guardar "
                                "se conservan mientras sigas en esta sesión.",
                                size="2",
                                color=T.TEXT_MUTED,
                            ),
                            rx.button(
                                "Continuar borrador",
                                on_click=S.resume_editor,
                                disabled=S.busy,
                                min_height="44px",
                                size="3",
                            ),
                            rx.button(
                                "Preparar otro formulario",
                                on_click=S.ask_discard,
                                disabled=S.busy,
                                min_height="44px",
                                variant="outline",
                            ),
                            spacing="2",
                            width="100%",
                            align_items="start",
                        ),
                        rx.button(
                            "Preparar formulario",
                            on_click=S.new_form,
                            disabled=S.busy | ~S.has_available_page,
                            min_height="44px",
                            size="3",
                        ),
                    ),
                    rx.cond(
                        S.discard_open,
                        card(
                            rx.vstack(
                                rx.text(
                                    "Si continúas, perderás los cambios sin guardar. "
                                    "Los borradores guardados se conservan.",
                                ),
                                rx.button(
                                    "Conservar mi borrador",
                                    on_click=S.keep_draft,
                                    variant="soft",
                                    min_height="44px",
                                ),
                                rx.button(
                                    "Descartar cambios y continuar",
                                    on_click=S.discard_draft,
                                    variant="outline",
                                    min_height="44px",
                                ),
                                spacing="2",
                                width="100%",
                                align_items="start",
                            ),
                            width="100%",
                        ),
                    ),
                    rx.cond(
                        ~S.has_available_page,
                        rx.vstack(
                            callout(
                                "Necesitas una página conectada con permiso para sus formularios. "
                                "Revisa tus cuentas en Tus redes.",
                                "info",
                            ),
                            rx.link("Revisar Tus redes", href="/connections", min_height="44px"),
                            spacing="2",
                            width="100%",
                        ),
                    ),
                    rx.cond(
                        S.forms.length() > 0,
                        rx.vstack(rx.foreach(S.forms, _form_card), spacing="3", width="100%"),
                        empty_state(
                            "clipboard-list",
                            "Todavía no tienes formularios aquí",
                            "Prepara las preguntas y revisa tu política de privacidad "
                            "antes de crearlo en Meta.",
                        ),
                    ),
                    rx.link(
                        "Ver clientes interesados",
                        href="/responder?tab=interesados",
                        min_height="44px",
                    ),
                    spacing="4",
                    width="100%",
                ),
            ),
        ),
    )
    return app_shell(rx.cond(S.editing, _editor(), listing))

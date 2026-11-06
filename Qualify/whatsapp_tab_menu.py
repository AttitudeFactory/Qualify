"""`/whatsapp` → Menú tab (WA-16): the editor where the business builds its automatic
menu and publishes it to its WhatsApp number.

Plugs into the shell through the agreed hook: `menu_tab() -> rx.Component` renders only
while the tab is active, inside a box keyed by `WhatsAppState.selected_connection_id`, so
its root `on_mount` (`WhatsAppMenuState.ensure_loaded`) fires on tab entry and on every
number switch.

Layout (docs/design-system.md §9.1 — tones only, the system's primitives, one solid
action): the number's menus; then, for the open menu, a structured editor (Entrada →
Pasos — a form, not a graph canvas, plan §5.3) next to a phone-style preview that runs
the real engine over the brand's real catalog. Every field shows its Spanish validation
message under it.

Publishing (m-24842995): the menu's bar carries the one solid action, «Publicar en mi
WhatsApp» (saves the changes and publishes, behind a confirmation), «Guardar sin
publicar» as the secondary, «Probar el menú» on the phone (jumps to the preview, which
sits under the long editor there), and, after publishing, «listo» plus the next step —
the QR for the counter (guide N3). Older versions live behind «Ver versiones
anteriores»; opening one puts it in the editor, and the same main button publishes it.

The menu in four steps (m-24848536) is what an owner sees first: ① ¿Cómo saludas?
② ¿Qué te preguntan siempre? (m-24936836: one ordered list of answers — the first ones are
WhatsApp's buttons, the rest go to «Más preguntas»; «Subir»/«Bajar», the limits always on
screen, each answer's panel with its «Falta: …» gaps) ③ Tus productos ④ Pruébalo y
publícalo (a gap never goes out: «Completarlas» / «Quitar las que faltan y publicar»)
— «Paso N de 4», «Atrás» and «Siguiente», «Guardar y seguir después», and the full
editor behind «Más opciones (avanzado)». No step id, button id or field key is shown
anywhere: steps are listed and chosen by name.

Talks to `WhatsAppMenuState` only — never to the provider, Graph or Postgres.
"""

from __future__ import annotations

import reflex as rx

from .catalog_group_vm import GROUP_BUTTON
from .catalog_group_vm import NAME_HELP as CATEGORY_NAME_HELP
from .catalog_group_vm import NAME_LABEL as CATEGORY_NAME_LABEL
from .catalog_group_vm import NAME_PLACEHOLDER as CATEGORY_NAME_PLACEHOLDER
from .ui import (
    callout,
    card,
    chat_bubble,
    choice_card,
    choice_card_check,
    dropzone,
    empty_state,
    mono,
    signal_pill,
    skeleton_card,
    skeleton_rows,
    tag,
    tone_badge,
)
from .ui import tokens as T
from .ui.flow_history import flow_sync
from .ui.steps import step_foot, step_frame, step_head
from .whatsapp_menu_state import ANSWER_TEXT_ID, IMPORT_REVIEW_HEADING_ID
from .whatsapp_menu_state import WhatsAppMenuState as S
from .whatsapp_menu_vm import (
    ADDRESS_ASK,
    ADDRESS_SKIP,
    ANSWER_ISSUE,
    ANSWERS_EMPTY,
    ANSWERS_FULL,
    BUTTONS_HEADING,
    CATALOG_FIX_FIRST,
    CATALOG_SAVED_HINT,
    CHANGE_ORDER,
    COLLECT_FIELDS,
    COLLECT_VALIDATIONS,
    GAP_FILL_HINT,
    HANDOFF_REASONS,
    IMPORT_ADD_BUTTON,
    IMPORT_CANCEL,
    IMPORT_CHECK_ALL,
    IMPORT_CHOOSE,
    IMPORT_DONE,
    IMPORT_EDIT,
    IMPORT_EDIT_DONE,
    IMPORT_EMPTY_PHASE,
    IMPORT_LINK,
    IMPORT_MAX_BYTES,
    IMPORT_NOT_NOW,
    IMPORT_OFFER_HELP,
    IMPORT_OFFER_TITLE,
    IMPORT_PAGE,
    IMPORT_PAGE_BUTTON,
    IMPORT_PAGE_CARD,
    IMPORT_PAGE_CARD_HELP,
    IMPORT_PAGE_HELP,
    IMPORT_PAGE_LABEL,
    IMPORT_PAGE_PLACEHOLDER,
    IMPORT_PAGE_TITLE,
    IMPORT_PHOTO,
    IMPORT_PHOTO_BUTTON,
    IMPORT_PHOTO_CARD,
    IMPORT_PHOTO_CARD_HELP,
    IMPORT_PHOTO_HELP,
    IMPORT_PHOTO_TITLE,
    IMPORT_PRIVACY,
    IMPORT_PRODUCTS_NEW_HELP,
    IMPORT_READING,
    IMPORT_READING_TEXT,
    IMPORT_REVIEW,
    IMPORT_REVIEW_HELP,
    IMPORT_SKIP,
    IMPORT_SLOW,
    IMPORT_UNCHECK_ALL,
    IMPORT_USE,
    IMPORT_USE_SENTENCE,
    KIND_BUTTONS,
    KIND_COLLECT,
    KIND_HANDOFF,
    KIND_LIST,
    KIND_ORDER_SUMMARY,
    KIND_PRODUCTS,
    KIND_TEXT,
    MORE_HEADING,
    MORE_ROW_TEXT,
    MORE_ROW_TITLE,
    NEXT_STEP_QR,
    NO_PRODUCTS,
    NO_PRODUCTS_WARNING,
    NODE_KINDS,
    NONE_VALUE,
    ORDER_HINT,
    PAYMENT_ANSWER_AUTO,
    PAYMENT_ANSWER_CHANGE,
    PAYMENTS_INVITE,
    PAYMENTS_INVITE_BUTTON,
    PRICES_FROM_CATALOG,
    PUBLISH_BUTTON,
    PUBLISH_CONFIRM,
    PUBLISH_CONFIRM_BUTTON,
    PUBLISHED_BUT_PAUSED,
    RESUME_BUTTON,
    SAVE_ONLY_BUTTON,
    SUGGEST_AGAIN,
    SUGGEST_ANSWER,
    SUGGEST_DONE,
    SUGGEST_DONE_GAPS,
    SUGGEST_GO_BRAND,
    SUGGEST_GREETING,
    SUGGEST_NEUTRAL,
    SUGGEST_UNDO,
    SUGGESTION_CUSTOM,
    TEMPLATE_EMPTY,
    TEMPLATE_FAST_FOOD,
    AnswerVM,
    CatalogRowVM,
    CatalogSectionVM,
    CommandForm,
    IceBreakerForm,
    ImportFactVM,
    ImportProductVM,
    KeywordForm,
    MenuSummaryVM,
    MenuVersionVM,
    NodeChoiceVM,
    NodeForm,
    OptionForm,
    PreviewChoiceVM,
    PreviewMessageVM,
    SuggestionVM,
    SuggestVM,
)
from .whatsapp_state import WhatsAppState
from .whatsapp_vm import TAB_QR

_TONES = ("ok", "warn", "error", "info", "neutral")
PREVIEW_ELEMENT_ID = "whatsapp-menu-preview"
TOOLBAR_ELEMENT_ID = "whatsapp-menu-toolbar"
# Guide N12: touch targets of at least 44 px on the phone.
TARGET_MIN = "44px"


# ======================================================================================
# Small helpers (the shell's equivalents live in whatsapp_page.py, which imports this
# module — so they cannot be imported from there without a cycle)
# ======================================================================================


def _tone_pill(label: rx.Var[str], tone: rx.Var[str]) -> rx.Component:
    return rx.match(
        tone,
        *[(t, signal_pill(label, t)) for t in _TONES[:-1]],
        signal_pill(label, "neutral"),
    )


def _banner(message: rx.Var[str], tone: rx.Var[str]) -> rx.Component:
    return rx.cond(
        message != "",
        rx.match(
            tone,
            *[(t, callout(message, t)) for t in _TONES[:-1]],
            callout(message, "neutral"),
        ),
        rx.fragment(),
    )


def _err(errors: rx.Var, key: str) -> rx.Component:
    """The Spanish validation message of `key`, under its field."""
    return rx.cond(
        errors.contains(key),
        rx.text(errors[key], size="1", color=T.tone_color("error", 11)),
        rx.fragment(),
    )


def _field(label: str | rx.Var, control: rx.Component, *below: rx.Component) -> rx.Component:
    return rx.vstack(
        rx.text(label, size="2", weight="medium"),
        control,
        *below,
        spacing="1",
        width="100%",
        align_items="start",
        min_width="0",
    )


def _hint(text: str) -> rx.Component:
    return rx.text(text, size="1", color=T.TEXT_FAINT)


def _section_title(title: str, *extra: rx.Component) -> rx.Component:
    return rx.hstack(
        rx.heading(title, size="3", as_="h2"),
        rx.spacer(),
        *extra,
        width="100%",
        align="center",
    )


def _icon_button(icon: str, label: str, on_click: rx.EventHandler, **props: object) -> rx.Component:
    return rx.icon_button(
        rx.icon(icon, size=T.ICON_SM),
        on_click=on_click,
        variant="ghost",
        size="1",
        aria_label=label,
        title=label,
        **T.tone_scheme("neutral"),
        **props,
    )


def _node_select(
    value: rx.Var[str],
    on_change: rx.EventHandler,
    *,
    none_label: str | None = None,
    handoffs_only: bool = False,
) -> rx.Component:
    """A select over the menu's steps, by name (the value is the id, never shown).
    `none_label` adds the «ninguno» choice."""
    items = S.handoff_choices if handoffs_only else S.node_choices

    def item(choice: NodeChoiceVM) -> rx.Component:
        return rx.select.item(choice.label, value=choice.node_id)

    return rx.select.root(
        rx.select.trigger(placeholder="Elige un paso", width="100%"),
        rx.select.content(
            *([rx.select.item(none_label, value=NONE_VALUE)] if none_label else []),
            rx.foreach(items, item),
        ),
        value=value,
        on_change=on_change,
    )


# ======================================================================================
# Menus of the number + «Nuevo menú»
# ======================================================================================


def _template_choice(value: str, title: str, description: str) -> rx.Component:
    selected = S.new_template == value
    return choice_card(
        rx.vstack(
            rx.hstack(
                rx.text(title, size="2", weight="medium"),
                rx.spacer(),
                rx.cond(selected, choice_card_check(), rx.fragment()),
                width="100%",
            ),
            rx.text(description, size="1", color=T.TEXT_MUTED),
            spacing="1",
            align_items="start",
            width="100%",
        ),
        selected=selected,
        on_select=S.set_new_template(value),
        padding="0.75rem 1rem",
    )


def _new_menu_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.trigger(
            rx.button(
                rx.icon("plus", size=T.ICON_SM),
                "Nuevo menú",
                variant="soft",
                size="2",
            ),
        ),
        rx.dialog.content(
            rx.dialog.title("Nuevo menú"),
            rx.dialog.description(
                "Un número responde con un solo menú publicado a la vez. Puedes tener "
                "varios guardados y publicar el que toque.",
                size="2",
                color=T.TEXT_MUTED,
            ),
            rx.vstack(
                _field(
                    "Nombre",
                    rx.input(
                        value=S.new_name,
                        on_change=S.set_new_name,
                        placeholder="Ej.: Menú principal",
                        width="100%",
                    ),
                    rx.cond(
                        S.new_error != "",
                        rx.text(S.new_error, size="1", color=T.tone_color("error", 11)),
                        rx.fragment(),
                    ),
                ),
                _template_choice(
                    TEMPLATE_FAST_FOOD,
                    "Con lo que ya sabemos de tu negocio",
                    "Tu nombre, tu dirección y tus productos. Tú completas lo que falte.",
                ),
                _template_choice(
                    TEMPLATE_EMPTY,
                    "Vacío",
                    "Un solo paso para escribir desde cero.",
                ),
                rx.flex(
                    rx.dialog.close(
                        rx.button("Cancelar", variant="soft", **T.tone_scheme("neutral")),
                    ),
                    rx.button(
                        "Crear menú",
                        on_click=S.create_new_menu,
                        loading=S.creating,
                    ),
                    spacing="3",
                    justify="end",
                    width="100%",
                ),
                spacing="3",
                width="100%",
                margin_top="1rem",
            ),
            max_width="30rem",
        ),
        open=S.new_open,
        on_open_change=S.set_new_open,
    )


def _menu_row(menu: MenuSummaryVM) -> rx.Component:
    is_open = menu.menu_id == S.menu.menu_id
    return choice_card(
        rx.hstack(
            rx.icon("list-tree", size=T.ICON_MD, color=T.TEXT_MUTED),
            rx.vstack(
                rx.text(menu.name, size="2", weight="medium"),
                # Unpublished: the status pill already says «Sin publicar».
                rx.cond(
                    menu.is_published,
                    rx.text(menu.published_label, size="1", color=T.TEXT_MUTED),
                    rx.fragment(),
                ),
                spacing="0",
                align_items="start",
                min_width="0",
            ),
            rx.spacer(),
            _tone_pill(menu.status_label, menu.status_tone),
            spacing="3",
            align="center",
            width="100%",
        ),
        selected=is_open,
        on_select=S.open_menu(menu.menu_id),
        padding="0.75rem 1rem",
    )


def _menus_card() -> rx.Component:
    return card(
        rx.vstack(
            _section_title("Menús de este número", _new_menu_dialog()),
            rx.text(
                "Tu WhatsApp responde con el menú que tú escribiste: saluda, muestra "
                "atajos, toma el pedido desde tu catálogo y te pasa el chat para cerrarlo.",
                size="2",
                color=T.TEXT_MUTED,
            ),
            rx.cond(
                S.menus.length() > 0,
                rx.grid(
                    rx.foreach(S.menus, _menu_row),
                    columns=rx.breakpoints(initial="1", md="2"),
                    spacing="2",
                    width="100%",
                ),
                empty_state(
                    "list-tree",
                    "Este número aún no tiene menú",
                    "Créalo con lo que ya sabemos de tu negocio y completa lo que falte, o "
                    "empieza desde cero.",
                    # N8 (m-24842961): opens the same «Crear menú» dialog.
                    action=rx.button(
                        rx.icon("plus", size=16),
                        "Crear menú",
                        on_click=S.set_new_open(True),
                        variant="soft",
                        size="3",
                    ),
                ),
            ),
            spacing="3",
            width="100%",
            align_items="start",
        ),
        padding="1.25rem 1.5rem",
    )


# ======================================================================================
# Toolbar of the open menu
# ======================================================================================


# «Más opciones»: the disabled «Publicar» is described by why it is off and what is missing.
PUBLISH_REASON_ID = "whatsapp-menu-publish-reason"
PUBLISH_DETAIL_ID = "whatsapp-menu-publish-detail"


def _publish_dialog() -> rx.Component:
    """The one solid action of the tab: saves the changes (if any) and publishes."""
    return rx.alert_dialog.root(
        rx.alert_dialog.trigger(
            rx.button(
                rx.icon("send", size=T.ICON_SM),
                PUBLISH_BUTTON,
                display=rx.cond(S.advanced_open, "inline-flex", "none"),
                disabled=~S.can_publish,
                loading=S.publishing,
                size="3",
                aria_describedby=rx.cond(
                    S.publish_block_reason != "",
                    f"{PUBLISH_REASON_ID} {PUBLISH_DETAIL_ID}",
                    "",
                ),
            ),
        ),
        rx.alert_dialog.content(
            rx.alert_dialog.title(PUBLISH_BUTTON),
            rx.alert_dialog.description(PUBLISH_CONFIRM, size="2"),
            rx.vstack(
                rx.foreach(
                    S.publish_confirm_lines,
                    lambda line: rx.text(line, size="2", color=T.TEXT_MUTED),
                ),
                spacing="1",
                align_items="start",
                margin_top="0.5rem",
            ),
            rx.flex(
                rx.alert_dialog.cancel(
                    rx.button("Cancelar", variant="soft", size="3", **T.tone_scheme("neutral")),
                ),
                rx.alert_dialog.action(
                    rx.button(PUBLISH_CONFIRM_BUTTON, on_click=S.publish_current, size="3"),
                ),
                spacing="3",
                margin_top="1rem",
                justify="end",
                wrap="wrap",
            ),
            max_width="28rem",
        ),
        open=S.publish_confirm_open,
        on_open_change=S.set_publish_confirm_open,
    )


def _actions() -> rx.Component:
    return rx.flex(
        _publish_dialog(),
        rx.button(
            rx.icon("play", size=T.ICON_SM),
            "Probar el menú",
            on_click=rx.scroll_to(PREVIEW_ELEMENT_ID),
            variant="soft",
            size="3",
            display=rx.breakpoints(initial="inline-flex", lg="none"),
        ),
        rx.button(
            rx.icon("save", size=T.ICON_SM),
            SAVE_ONLY_BUTTON,
            on_click=S.save_current_version,
            disabled=~S.can_save | S.publishing,
            loading=S.saving & ~S.publishing,
            variant="soft",
            size="3",
            **T.tone_scheme("neutral"),
        ),
        # In «Más opciones» the main button says why it is off, never a silent block.
        rx.cond(
            S.advanced_open & (S.publish_block_reason != "") & ~S.publishing,
            rx.vstack(
                rx.text(
                    S.publish_block_reason,
                    id=PUBLISH_REASON_ID,
                    size="1",
                    color=T.tone_color("warn", 11),
                ),
                rx.text(
                    S.publish_block_detail,
                    id=PUBLISH_DETAIL_ID,
                    size="1",
                    color=T.tone_color("warn", 11),
                    display=rx.cond(S.publish_block_detail != "", "block", "none"),
                ),
                spacing="1",
                align_items="start",
            ),
            rx.fragment(),
        ),
        spacing="2",
        wrap="wrap",
        align="center",
        width="100%",
    )


def _next_step() -> rx.Component:
    """Guide N3: after publishing, «listo» and the next job — the QR for the counter —
    with one solid button to it and a soft one to go back to the editor."""
    return rx.vstack(
        rx.hstack(
            rx.icon("circle-check", size=T.ICON_MD, color=T.tone_color("ok", 11)),
            rx.text("Listo: tu WhatsApp ya responde con este menú.", size="2", weight="medium"),
            spacing="2",
            align="center",
        ),
        rx.text(NEXT_STEP_QR, size="2"),
        rx.text(
            "Tus clientes lo escanean, te escriben y les responde este menú.",
            size="1",
            color=T.TEXT_MUTED,
        ),
        rx.flex(
            rx.button(
                rx.icon("qr-code", size=T.ICON_SM),
                "Crear mi código QR",
                on_click=WhatsAppState.select_tab(TAB_QR),
                size="3",
            ),
            rx.button(
                "Seguir editando",
                on_click=S.dismiss_next_step,
                variant="soft",
                size="3",
                **T.tone_scheme("neutral"),
            ),
            spacing="2",
            wrap="wrap",
        ),
        spacing="2",
        align_items="start",
        width="100%",
        padding="0.75rem 1rem",
        border=T.BORDER,
        border_radius=T.RADIUS_CONTROL,
        background=T.tone_color("ok", 2),
    )


def _published_but_paused() -> rx.Component:
    """Published while paused: the pause stays, so «listo» would be false. Say so, and
    offer the resume as the one solid action (the same handler as the switch)."""
    return rx.vstack(
        callout(PUBLISHED_BUT_PAUSED, "warn"),
        rx.flex(
            rx.button(
                rx.icon("play", size=T.ICON_SM),
                RESUME_BUTTON,
                on_click=S.toggle_pause(False),
                loading=S.pausing,
                size="3",
            ),
            rx.button(
                "Seguir editando",
                on_click=S.dismiss_next_step,
                variant="soft",
                size="3",
                **T.tone_scheme("neutral"),
            ),
            spacing="2",
            wrap="wrap",
        ),
        spacing="2",
        align_items="start",
        width="100%",
    )


def _publish_area() -> rx.Component:
    """«Publicar en mi WhatsApp» and friends, or — right after publishing — «listo» and
    the next step. Lives in step 4, or in the toolbar of «Más opciones (avanzado)»."""
    return rx.cond(
        S.just_published,
        rx.cond(S.menu.is_paused, _published_but_paused(), _next_step()),
        _actions(),
    )


def _toolbar() -> rx.Component:
    return card(
        rx.vstack(
            rx.vstack(
                rx.hstack(
                    rx.heading(S.menu.name, size="4", as_="h2"),
                    _tone_pill(S.menu.status_label, S.menu.status_tone),
                    rx.cond(S.dirty, tag("Cambios sin publicar"), rx.fragment()),
                    spacing="2",
                    align="center",
                    wrap="wrap",
                ),
                rx.text(S.editing_from, size="1", color=T.TEXT_MUTED),
                spacing="1",
                align_items="start",
            ),
            rx.cond(S.advanced_open, _publish_area(), rx.fragment()),
            # One decision per step: pausing only matters once the menu is live.
            rx.cond(S.menu.is_published | S.advanced_open, _pause_row(), rx.fragment()),
            rx.cond(
                S.error_count > 0,
                callout(S.issues_text, "warn"),
                rx.fragment(),
            ),
            rx.foreach(S.menu_errors, lambda message: callout(message, "warn")),
            spacing="3",
            width="100%",
            align_items="start",
        ),
        padding="1rem 1.25rem",
        id=TOOLBAR_ELEMENT_ID,
        scroll_margin_top=T.SCROLL_MARGIN_TOP,
    )


def _pause_row() -> rx.Component:
    return rx.hstack(
        rx.switch(
            checked=S.menu.is_paused,
            on_change=S.toggle_pause,
            disabled=S.pausing | ~S.menu.is_published,
            size="2",
        ),
        rx.vstack(
            rx.text("Pausar el menú en tu WhatsApp", size="2", weight="medium"),
            rx.text(
                rx.cond(
                    S.menu.is_published,
                    "En pausa, tu WhatsApp no responde con el menú; los mensajes "
                    "llegan a Chats como siempre.",
                    "Se puede pausar una vez publicado.",
                ),
                size="1",
                color=T.TEXT_MUTED,
            ),
            spacing="0",
            align_items="start",
        ),
        spacing="3",
        align="center",
    )


# ======================================================================================
# Entrada
# ======================================================================================


def _keyword_row(row: KeywordForm, index: rx.Var[int]) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.input(
                value=row.word,
                on_change=lambda v: S.set_entry_row("keywords", index, "word", v),
                placeholder="Ej.: menú",
                width="100%",
            ),
            rx.box(
                _node_select(row.node, lambda v: S.set_entry_row("keywords", index, "node", v)),
                width="100%",
            ),
            _icon_button("trash-2", "Quitar palabra", S.remove_entry_row("keywords", index)),
            spacing="2",
            width="100%",
            align="center",
        ),
        _err(row.errors, "word"),
        _err(row.errors, "node"),
        spacing="1",
        width="100%",
    )


def _ice_breaker_row(row: IceBreakerForm, index: rx.Var[int]) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.input(
                value=row.text,
                on_change=lambda v: S.set_entry_row("ice_breakers", index, "text", v),
                placeholder="Ej.: Ver menú",
                width="100%",
            ),
            rx.box(
                _node_select(row.node, lambda v: S.set_entry_row("ice_breakers", index, "node", v)),
                width="100%",
            ),
            _icon_button("trash-2", "Quitar atajo", S.remove_entry_row("ice_breakers", index)),
            spacing="2",
            width="100%",
            align="center",
        ),
        _err(row.errors, "text"),
        _err(row.errors, "node"),
        spacing="1",
        width="100%",
    )


def _command_row(row: CommandForm, index: rx.Var[int]) -> rx.Component:
    return rx.vstack(
        rx.grid(
            rx.hstack(
                mono("/", color=T.TEXT_MUTED),
                rx.input(
                    value=row.name,
                    on_change=lambda v: S.set_entry_row("commands", index, "name", v),
                    placeholder="menu",
                    width="100%",
                ),
                spacing="1",
                align="center",
                width="100%",
            ),
            rx.input(
                value=row.hint,
                on_change=lambda v: S.set_entry_row("commands", index, "hint", v),
                placeholder="Qué hace (lo ve el cliente)",
                width="100%",
            ),
            rx.hstack(
                rx.box(
                    _node_select(row.node, lambda v: S.set_entry_row("commands", index, "node", v)),
                    width="100%",
                ),
                _icon_button("trash-2", "Quitar comando", S.remove_entry_row("commands", index)),
                spacing="2",
                align="center",
                width="100%",
            ),
            columns=rx.breakpoints(initial="1", md="3"),
            spacing="2",
            width="100%",
        ),
        _err(row.errors, "name"),
        _err(row.errors, "hint"),
        _err(row.errors, "node"),
        spacing="1",
        width="100%",
    )


def _add_row_button(label: str, table: str, disabled: rx.Var[bool] | bool = False) -> rx.Component:
    return rx.button(
        rx.icon("plus", size=T.ICON_SM),
        label,
        on_click=S.add_entry_row(table),
        disabled=disabled,
        variant="ghost",
        size="1",
    )


def _entry_card() -> rx.Component:
    return card(
        rx.vstack(
            _section_title("Entrada"),
            rx.text(
                "Cómo empieza la conversación. Los atajos y comandos también se publican "
                "en WhatsApp: el cliente los ve al abrir el chat.",
                size="2",
                color=T.TEXT_MUTED,
            ),
            _field(
                "Bienvenida",
                rx.text_area(
                    value=S.welcome,
                    on_change=S.set_welcome,
                    placeholder="Ej.: ¡Hola! Soy el asistente de tu negocio.",
                    width="100%",
                    rows="2",
                ),
                _err(S.entry_errors, "welcome"),
                _hint("Se envía antes del paso inicial en el primer mensaje de cada cliente."),
            ),
            rx.hstack(
                rx.switch(
                    checked=S.on_first_message,
                    on_change=S.set_on_first_message,
                    size="2",
                ),
                rx.text("Responder al primer mensaje", size="2", weight="medium"),
                spacing="3",
                align="center",
            ),
            rx.grid(
                _field(
                    "Paso inicial",
                    _node_select(S.start_node, S.set_start_node),
                    _err(S.entry_errors, "start_node"),
                ),
                _field(
                    "Si no entiende dos veces seguidas",
                    _node_select(
                        S.fallback_node,
                        S.set_fallback_node,
                        none_label="Pasar a una persona (mensaje de Qualify)",
                        handoffs_only=True,
                    ),
                    _err(S.entry_errors, "fallback_node"),
                ),
                columns=rx.breakpoints(initial="1", md="2"),
                spacing="3",
                width="100%",
            ),
            _err(S.entry_errors, "_entry"),
            rx.divider(),
            _section_title("Palabras clave", _add_row_button("Agregar palabra", "keywords")),
            _hint(
                "Si el cliente escribe la palabra (sin importar tildes ni mayúsculas), "
                "salta al paso."
            ),
            rx.foreach(S.keywords, _keyword_row),
            _err(S.entry_errors, "keywords"),
            rx.divider(),
            _section_title(
                "Atajos",
                rx.text(S.ice_breaker_count, size="1", color=T.TEXT_FAINT, class_name="q-nums"),
                _add_row_button("Agregar atajo", "ice_breakers", S.ice_breakers_full),
            ),
            _hint(
                "Hasta 4, de máximo 80 caracteres y sin emojis. WhatsApp los muestra al "
                "abrir el chat."
            ),
            rx.foreach(S.ice_breakers, _ice_breaker_row),
            _err(S.entry_errors, "ice_breakers"),
            rx.divider(),
            _section_title(
                "Comandos",
                rx.text(S.command_count, size="1", color=T.TEXT_FAINT, class_name="q-nums"),
                _add_row_button("Agregar comando", "commands", S.commands_full),
            ),
            _hint("Hasta 30. El cliente escribe «/» y elige; la descripción es lo que ve."),
            rx.foreach(S.commands, _command_row),
            _err(S.entry_errors, "commands"),
            spacing="3",
            width="100%",
            align_items="start",
        ),
        padding="1.25rem 1.5rem",
    )


# ======================================================================================
# Pasos
# ======================================================================================


def _step_row(node: NodeForm, index: rx.Var[int]) -> rx.Component:
    selected = index == S.selected_node
    row = rx.hstack(
        choice_card(
            rx.vstack(
                rx.hstack(
                    rx.text(node.label, size="2", weight="medium"),
                    rx.cond(
                        node.node_id == S.start_node,
                        tag("Inicio"),
                        rx.fragment(),
                    ),
                    spacing="2",
                    align="center",
                    wrap="wrap",
                ),
                rx.hstack(
                    rx.text(node.kind_label, size="1", color=T.TEXT_MUTED),
                    rx.cond(node.has_issue, signal_pill("Revisar", "warn"), rx.fragment()),
                    rx.cond(node.unused, tag("Sin usar"), rx.fragment()),
                    spacing="2",
                    align="center",
                    wrap="wrap",
                ),
                spacing="1",
                align_items="start",
                width="100%",
            ),
            selected=selected,
            on_select=S.select_node(index),
            padding="0.5rem 0.75rem",
            flex="1",
            min_width="0",
        ),
        _icon_button("trash-2", "Quitar paso", S.remove_node(index)),
        spacing="1",
        align="center",
        width="100%",
    )
    return rx.vstack(
        row,
        rx.cond(
            node.unused,
            rx.hstack(
                rx.text(
                    "Nadie llega a este paso. Puedes quitarlo.",
                    size="1",
                    color=T.TEXT_MUTED,
                ),
                rx.button(
                    "Quitar",
                    on_click=S.remove_node(index),
                    variant="ghost",
                    size="3",
                    min_height=TARGET_MIN,
                    **T.tone_scheme("neutral"),
                ),
                spacing="2",
                align="center",
                wrap="wrap",
                padding_left="0.75rem",
            ),
            rx.fragment(),
        ),
        spacing="0",
        width="100%",
    )


def _add_step_menu() -> rx.Component:
    return rx.menu.root(
        rx.menu.trigger(
            rx.button(
                rx.icon("plus", size=T.ICON_SM),
                "Agregar paso",
                rx.icon("chevron-down", size=T.ICON_SM),
                variant="soft",
                size="1",
            ),
        ),
        rx.menu.content(
            *[rx.menu.item(label, on_click=S.add_node(kind)) for kind, label in NODE_KINDS]
        ),
    )


def _node_input(label: str, field: str, value: rx.Var[str], placeholder: str = "") -> rx.Component:
    return _field(
        label,
        rx.input(
            value=value,
            on_change=lambda v: S.set_node_field(field, v),
            placeholder=placeholder,
            width="100%",
        ),
        _err(S.selected.errors, field),
    )


def _node_ref(
    label: str, field: str, value: rx.Var[str], none_label: str | None = None
) -> rx.Component:
    return _field(
        label,
        _node_select(value, lambda v: S.set_node_field(field, v), none_label=none_label),
        _err(S.selected.errors, field),
    )


def _option_row(option: OptionForm, index: rx.Var[int]) -> rx.Component:
    is_list = S.selected.kind == KIND_LIST
    return card(
        rx.vstack(
            rx.grid(
                rx.cond(
                    is_list,
                    _field(
                        "Sección",
                        rx.input(
                            value=option.section,
                            on_change=lambda v: S.set_option_field(index, "section", v),
                            width="100%",
                        ),
                        _err(option.errors, "section"),
                    ),
                    rx.fragment(),
                ),
                _field(
                    rx.cond(is_list, "Título de la fila", "Texto del botón"),
                    rx.input(
                        value=option.label,
                        on_change=lambda v: S.set_option_field(index, "label", v),
                        width="100%",
                    ),
                    _err(option.errors, "label"),
                ),
                rx.cond(
                    is_list,
                    _field(
                        "Descripción (opcional)",
                        rx.input(
                            value=option.description,
                            on_change=lambda v: S.set_option_field(index, "description", v),
                            width="100%",
                        ),
                        _err(option.errors, "description"),
                    ),
                    rx.fragment(),
                ),
                _field(
                    "Lleva a",
                    _node_select(option.next, lambda v: S.set_option_field(index, "next", v)),
                    _err(option.errors, "next"),
                ),
                columns=rx.breakpoints(initial="1", md="2"),
                spacing="2",
                width="100%",
            ),
            rx.hstack(
                rx.spacer(),
                _icon_button("chevron-up", "Subir", S.move_option(index, -1)),
                _icon_button("chevron-down", "Bajar", S.move_option(index, 1)),
                _icon_button("trash-2", "Quitar opción", S.remove_option(index)),
                spacing="1",
                width="100%",
            ),
            spacing="2",
            width="100%",
        ),
        padding="0.75rem 1rem",
    )


def _options_editor() -> rx.Component:
    node = S.selected
    return rx.vstack(
        rx.hstack(
            rx.text(
                rx.cond(node.kind == KIND_LIST, "Filas de la lista", "Botones"),
                size="2",
                weight="medium",
            ),
            rx.text(
                rx.cond(node.kind == KIND_LIST, "hasta 10", "hasta 3"),
                size="1",
                color=T.TEXT_FAINT,
            ),
            rx.spacer(),
            rx.button(
                rx.icon("plus", size=T.ICON_SM),
                "Agregar opción",
                on_click=S.add_option,
                disabled=S.options_full,
                variant="ghost",
                size="1",
            ),
            width="100%",
            align="center",
        ),
        _err(node.errors, "options"),
        rx.foreach(node.options, _option_row),
        # Button ids are generated; a clash (only from an old hand-made menu) shows here.
        rx.foreach(
            node.options,
            lambda option: _err(option.errors, "option_id"),
        ),
        spacing="2",
        width="100%",
    )


def _header_footer() -> rx.Component:
    node = S.selected
    return rx.grid(
        _node_input("Encabezado (opcional)", "header", node.header),
        _node_input("Pie (opcional)", "footer", node.footer),
        columns=rx.breakpoints(initial="1", md="2"),
        spacing="3",
        width="100%",
    )


def _kind_fields() -> rx.Component:
    node = S.selected
    two = rx.breakpoints(initial="1", md="2")
    return rx.match(
        node.kind,
        (KIND_TEXT, _node_ref("Después", "next", node.next, none_label="Termina aquí")),
        (KIND_BUTTONS, rx.vstack(_header_footer(), _options_editor(), spacing="3", width="100%")),
        (
            KIND_LIST,
            rx.vstack(
                _header_footer(),
                _node_input("Botón que abre la lista", "button_label", node.button_label),
                _options_editor(),
                spacing="3",
                width="100%",
            ),
        ),
        (
            KIND_PRODUCTS,
            rx.vstack(
                rx.text(
                    "Las filas salen solas del catálogo de la marca (una sección por "
                    "categoría). Elegir un producto lo suma al pedido.",
                    size="1",
                    color=T.TEXT_MUTED,
                ),
                _header_footer(),
                rx.grid(
                    _node_input("Botón que abre la lista", "button_label", node.button_label),
                    _node_input("Fila «ver más»", "more_label", node.more_label),
                    _node_input("Filas por mensaje (2 a 10)", "page_size", node.page_size),
                    _node_ref("Después de elegir", "next_after_pick", node.next_after_pick),
                    columns=two,
                    spacing="3",
                    width="100%",
                ),
                _field(
                    "Si no hay productos",
                    rx.text_area(
                        value=node.empty_body,
                        on_change=lambda v: S.set_node_field("empty_body", v),
                        width="100%",
                        rows="2",
                    ),
                    _err(node.errors, "empty_body"),
                ),
                spacing="3",
                width="100%",
            ),
        ),
        (
            KIND_ORDER_SUMMARY,
            rx.vstack(
                rx.text(
                    "Muestra las líneas del pedido y tres botones fijos. «Confirmar» debe "
                    "terminar en «Pasar a una persona»: un pedido siempre lo cierra alguien "
                    "del equipo.",
                    size="1",
                    color=T.TEXT_MUTED,
                ),
                rx.grid(
                    _node_input("Botón confirmar", "confirm_label", node.confirm_label),
                    _node_ref("Confirmar lleva a", "confirm_next", node.confirm_next),
                    _node_input("Botón agregar", "add_more_label", node.add_more_label),
                    _node_ref("Agregar lleva a", "add_more_next", node.add_more_next),
                    _node_input("Botón cancelar", "cancel_label", node.cancel_label),
                    _node_ref("Cancelar lleva a", "cancel_next", node.cancel_next),
                    columns=two,
                    spacing="3",
                    width="100%",
                ),
                _node_input("Si el pedido está vacío", "empty_line", node.empty_line),
                spacing="3",
                width="100%",
            ),
        ),
        (
            KIND_COLLECT,
            rx.vstack(
                rx.grid(
                    _field(
                        "Qué dato pide",
                        rx.select.root(
                            rx.select.trigger(width="100%"),
                            rx.select.content(
                                *[rx.select.item(lbl, value=key) for key, lbl in COLLECT_FIELDS]
                            ),
                            value=node.field_name,
                            on_change=lambda v: S.set_node_field("field_name", v),
                        ),
                        _err(node.errors, "field_name"),
                    ),
                    _field(
                        "Qué se acepta",
                        rx.select.root(
                            rx.select.trigger(width="100%"),
                            rx.select.content(
                                *[
                                    rx.select.item(lbl, value=key)
                                    for key, lbl in COLLECT_VALIDATIONS
                                ]
                            ),
                            value=node.validation,
                            on_change=lambda v: S.set_node_field("validation", v),
                        ),
                        _err(node.errors, "validation"),
                    ),
                    columns=two,
                    spacing="3",
                    width="100%",
                ),
                rx.cond(
                    node.validation == "yes_no",
                    rx.grid(
                        _node_input("Botón sí", "yes_label", node.yes_label),
                        _node_input("Botón no", "no_label", node.no_label),
                        columns=two,
                        spacing="3",
                        width="100%",
                    ),
                    rx.fragment(),
                ),
                _node_input("Si la respuesta no sirve", "error_message", node.error_message),
                _node_ref("Después", "next", node.next),
                spacing="3",
                width="100%",
            ),
        ),
        (
            KIND_HANDOFF,
            _field(
                "Por qué te pasa el chat (lo ves en Chats)",
                rx.select.root(
                    rx.select.trigger(width="100%"),
                    rx.select.content(
                        *[rx.select.item(lbl, value=key) for key, lbl in HANDOFF_REASONS]
                    ),
                    value=node.reason,
                    on_change=lambda v: S.set_node_field("reason", v),
                ),
                _err(node.errors, "reason"),
            ),
        ),
        rx.fragment(),
    )


def _step_detail() -> rx.Component:
    node = S.selected
    return card(
        rx.vstack(
            rx.grid(
                _node_input("Nombre del paso", "title", node.title),
                _field(
                    "Tipo",
                    rx.select.root(
                        rx.select.trigger(width="100%"),
                        rx.select.content(
                            *[rx.select.item(label, value=kind) for kind, label in NODE_KINDS]
                        ),
                        value=node.kind,
                        on_change=S.set_node_kind,
                    ),
                ),
                columns=rx.breakpoints(initial="1", md="2"),
                spacing="3",
                width="100%",
            ),
            _hint("Solo lo ves tú. Cambiarlo no cambia nada en tu WhatsApp."),
            _err(node.errors, "node_id"),
            _err(node.errors, "_node"),
            _field(
                rx.match(
                    node.kind,
                    (KIND_COLLECT, "Pregunta"),
                    (KIND_HANDOFF, "Mensaje antes de pasar a una persona"),
                    (KIND_ORDER_SUMMARY, "Texto bajo el pedido (incluye {total})"),
                    "Texto del mensaje",
                ),
                rx.text_area(
                    value=node.body,
                    on_change=lambda v: S.set_node_field("body", v),
                    width="100%",
                    rows="3",
                ),
                _err(node.errors, "body"),
            ),
            _kind_fields(),
            spacing="3",
            width="100%",
            align_items="start",
        ),
        padding="1rem 1.25rem",
    )


def _steps_card() -> rx.Component:
    return card(
        rx.vstack(
            _section_title("Pasos", _add_step_menu()),
            rx.text(
                "Cada paso es un mensaje: texto, botones, una lista, el catálogo, el resumen "
                "del pedido, una pregunta o pasar a una persona. Elige uno para editarlo.",
                size="2",
                color=T.TEXT_MUTED,
            ),
            rx.grid(
                rx.vstack(
                    rx.foreach(S.nodes, _step_row),
                    spacing="1",
                    width="100%",
                ),
                rx.cond(S.has_selected, _step_detail(), rx.fragment()),
                grid_template_columns=rx.breakpoints(
                    initial="minmax(0, 1fr)", md="minmax(0, 15rem) minmax(0, 1fr)"
                ),
                gap="1rem",
                width="100%",
                align_items="start",
            ),
            spacing="3",
            width="100%",
            align_items="start",
        ),
        padding="1.25rem 1.5rem",
    )


# ======================================================================================
# Versiones
# ======================================================================================


def _version_row(version: MenuVersionVM) -> rx.Component:
    return rx.hstack(
        rx.vstack(
            rx.hstack(
                rx.text(version.label, size="2", weight="medium"),
                rx.cond(
                    version.is_live,
                    signal_pill("La que responde ahora", "ok"),
                    rx.cond(version.published_at != "", tag("Publicada antes"), rx.fragment()),
                ),
                spacing="2",
                align="center",
                wrap="wrap",
            ),
            rx.text(
                "Guardada el ",
                version.created_at,
                size="1",
                color=T.TEXT_MUTED,
            ),
            spacing="0",
            align_items="start",
        ),
        rx.spacer(),
        rx.button(
            rx.icon("pencil", size=T.ICON_SM),
            "Abrir en el editor",
            on_click=S.open_version(version.version_id),
            variant="ghost",
            size="1",
            **T.tone_scheme("neutral"),
        ),
        spacing="2",
        align="center",
        width="100%",
        wrap="wrap",
        padding_y="0.5rem",
        border_top=T.BORDER,
    )


def _versions_section() -> rx.Component:
    """«Ver versiones anteriores»: folded by default — the main button is the way to
    publish; this is only for going back to an older version."""
    return rx.vstack(
        rx.button(
            rx.cond(
                S.versions_open,
                rx.icon("chevron-up", size=T.ICON_SM),
                rx.icon("chevron-down", size=T.ICON_SM),
            ),
            rx.cond(S.versions_open, "Ocultar versiones anteriores", "Ver versiones anteriores"),
            on_click=S.toggle_versions,
            variant="ghost",
            size="3",
            **T.tone_scheme("neutral"),
        ),
        rx.cond(
            S.versions_open,
            card(
                rx.vstack(
                    rx.text(
                        "Cada vez que guardas queda una versión. Abre una en el editor y "
                        "toca «Publicar en mi WhatsApp» para volver a ella.",
                        size="2",
                        color=T.TEXT_MUTED,
                    ),
                    rx.cond(
                        S.dirty & (S.versions.length() > 0),
                        callout(
                            "Tienes cambios sin publicar: «Abrir en el editor» los descarta.",
                            "info",
                        ),
                        rx.fragment(),
                    ),
                    rx.cond(
                        S.versions.length() > 0,
                        rx.vstack(rx.foreach(S.versions, _version_row), spacing="0", width="100%"),
                        rx.text(
                            "Aún no guardaste ninguna versión de este menú.",
                            size="2",
                            color=T.TEXT_FAINT,
                        ),
                    ),
                    spacing="3",
                    width="100%",
                    align_items="start",
                ),
                padding="1rem 1.25rem",
            ),
            rx.fragment(),
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


# ======================================================================================
# Phone preview
# ======================================================================================


def _choice_button(choice: PreviewChoiceVM) -> rx.Component:
    return rx.button(
        choice.title,
        on_click=S.preview_choose(choice.reply_kind, choice.reply_id, choice.title),
        disabled=S.preview_paused,
        variant="soft",
        size="1",
        width="100%",
    )


def _list_row(choice: PreviewChoiceVM) -> rx.Component:
    return rx.vstack(
        rx.cond(
            choice.section != "",
            rx.text(
                choice.section, size="1", weight="medium", color=T.TEXT_MUTED, padding_top="0.25rem"
            ),
            rx.fragment(),
        ),
        rx.button(
            rx.vstack(
                rx.text(choice.title, size="2"),
                rx.cond(
                    choice.description != "",
                    rx.text(choice.description, size="1", color=T.TEXT_MUTED),
                    rx.fragment(),
                ),
                spacing="0",
                align_items="start",
                width="100%",
            ),
            on_click=S.preview_choose(choice.reply_kind, choice.reply_id, choice.title),
            disabled=S.preview_paused,
            variant="ghost",
            size="1",
            width="100%",
            height="auto",
            padding_y="0.35rem",
            justify_content="start",
            **T.tone_scheme("neutral"),
        ),
        spacing="0",
        width="100%",
        align_items="start",
    )


def _bubble(message: PreviewMessageVM) -> rx.Component:
    text = rx.text(message.text, size="2", white_space="pre-line")
    out = chat_bubble(
        text,
        rx.cond(
            message.choices.length() > 0,
            rx.cond(
                message.is_list,
                rx.vstack(
                    rx.hstack(
                        rx.icon("list", size=T.ICON_SM),
                        rx.text(message.list_label, size="1", weight="medium"),
                        spacing="1",
                        align="center",
                        padding_top="0.5rem",
                    ),
                    rx.foreach(message.choices, _list_row),
                    spacing="0",
                    width="100%",
                ),
                rx.vstack(
                    rx.foreach(message.choices, _choice_button),
                    spacing="1",
                    width="100%",
                    padding_top="0.5rem",
                ),
            ),
            rx.fragment(),
        ),
        direction="out",
        width="auto",
        max_width="88%",
    )
    return rx.match(
        message.direction,
        (
            "note",
            rx.box(
                rx.hstack(
                    rx.icon("user-round", size=T.ICON_SM, color=T.tone_color("info", 11)),
                    rx.text(message.text, size="1", white_space="pre-line"),
                    spacing="2",
                    align="start",
                ),
                padding="0.5rem 0.75rem",
                border=T.BORDER,
                border_radius=T.RADIUS_CONTROL,
                background=T.tone_color("info", 2),
                width="100%",
            ),
        ),
        (
            "in",
            rx.flex(
                chat_bubble(text, direction="in", width="auto", max_width="85%"),
                justify="end",
                width="100%",
            ),
        ),
        rx.flex(out, justify="start", width="100%"),
    )


def _preview_start() -> rx.Component:
    return rx.vstack(
        rx.text("Así lo ve tu cliente al abrir el chat.", size="1", color=T.TEXT_MUTED),
        rx.cond(
            S.ice_breaker_texts.length() > 0,
            rx.vstack(
                rx.foreach(
                    S.ice_breaker_texts,
                    lambda t: rx.button(
                        t,
                        on_click=S.preview_shortcut(t),
                        variant="outline",
                        size="1",
                        width="100%",
                    ),
                ),
                spacing="1",
                width="100%",
            ),
            rx.fragment(),
        ),
        rx.button(
            rx.icon("message-circle", size=T.ICON_SM),
            "Abrir el chat sin escribir",
            on_click=S.preview_open_chat,
            variant="ghost",
            size="1",
            **T.tone_scheme("neutral"),
        ),
        spacing="2",
        width="100%",
        align_items="center",
        padding_top="1rem",
    )


def _preview_card() -> rx.Component:
    return card(
        rx.vstack(
            _section_title(
                "Vista previa",
                rx.button(
                    rx.icon("rotate-ccw", size=T.ICON_SM),
                    "Reiniciar",
                    on_click=S.restart_preview,
                    variant="ghost",
                    size="1",
                    **T.tone_scheme("neutral"),
                ),
            ),
            rx.text(S.catalog_text, size="1", color=T.TEXT_MUTED),
            rx.cond(
                ~S.preview_available & ~S.preview_started,
                callout("Corrige lo marcado en el editor para probar el menú.", "warn"),
                rx.fragment(),
            ),
            rx.cond(
                S.preview_stale,
                callout("Cambiaste el menú. Reinicia para probar los cambios.", "info"),
                rx.fragment(),
            ),
            rx.box(
                rx.cond(
                    S.preview_started,
                    rx.vstack(
                        rx.foreach(S.preview_messages, _bubble),
                        spacing="2",
                        width="100%",
                    ),
                    rx.cond(S.preview_available, _preview_start(), rx.fragment()),
                ),
                height="30rem",
                overflow_y="auto",
                padding="0.75rem",
                border=T.BORDER,
                border_radius=T.RADIUS_CARD,
                background=T.GROUND,
                width="100%",
            ),
            rx.cond(
                S.preview_paused,
                callout(
                    "El menú quedó en pausa en este chat: ahora responde una persona. "
                    "Reinicia para volver a probar.",
                    "info",
                ),
                rx.fragment(),
            ),
            rx.hstack(
                rx.input(
                    value=S.preview_text,
                    on_change=S.set_preview_text,
                    on_key_down=S.preview_key,
                    placeholder="Escribe como el cliente…",
                    disabled=S.preview_paused | ~S.preview_available,
                    width="100%",
                ),
                rx.icon_button(
                    rx.icon("send-horizontal", size=T.ICON_SM),
                    on_click=S.preview_send,
                    disabled=S.preview_paused | ~S.preview_available,
                    aria_label="Enviar",
                    variant="soft",
                    size="2",
                ),
                spacing="2",
                width="100%",
            ),
            rx.cond(
                S.preview_order.length() > 0,
                rx.vstack(
                    rx.text("Pedido en curso", size="1", weight="medium", color=T.TEXT_MUTED),
                    rx.foreach(
                        S.preview_order, lambda line: rx.text(line, size="1", class_name="q-nums")
                    ),
                    spacing="0",
                    width="100%",
                    align_items="start",
                ),
                rx.fragment(),
            ),
            rx.button(
                rx.icon("arrow-up", size=T.ICON_SM),
                "Listo, ir a publicar",
                on_click=rx.scroll_to(TOOLBAR_ELEMENT_ID),
                variant="soft",
                size="3",
                width="100%",
                display=rx.breakpoints(initial="flex", lg="none"),
            ),
            spacing="3",
            width="100%",
            align_items="start",
        ),
        padding="1rem 1.25rem",
    )


# ======================================================================================
# The menu in four steps (m-24848536)
# ======================================================================================


def _guided_err(message: rx.Var[str]) -> rx.Component:
    return rx.cond(
        message != "",
        rx.text(message, size="1", color=T.tone_color("error", 11)),
        rx.fragment(),
    )


def _suggest_tools(
    kind: str,
    label: rx.Var[str],
    view: SuggestVM,
    on_suggest: rx.EventHandler,
    on_again: rx.EventHandler,
    on_undo: rx.EventHandler,
    *,
    show_missing: bool,
    has_gaps: rx.Var[bool] | bool = False,
) -> rx.Component:
    """«Mejorar mi texto» / «Escribirlo por mí» under a field (m-24936838, spec §5): the
    generator's «Potenciar con IA» pattern — a soft button with its name always written,
    never the step's solid action. While Claude writes, the field is read-only and a line
    says so; then «Deshacer» (the owner's exact text) and «Otra versión». `show_missing`:
    the «Dejamos [x]…» line, only where no «Falta: …» line already says it (the greeting);
    `has_gaps`: the result line then asks to complete what is missing."""
    busy = S.suggest_busy == kind
    any_busy = S.suggest_busy != ""
    small = {"size": "2", "min_height": TARGET_MIN}
    return rx.vstack(
        rx.hstack(
            rx.button(
                rx.icon("sparkles", size=T.ICON_SM),
                label,
                on_click=on_suggest,
                loading=busy,
                disabled=any_busy,
                variant="soft",
                aria_label=label,
                **small,
            ),
            rx.cond(
                view.has_proposal & ~any_busy,
                rx.hstack(
                    rx.button(
                        rx.icon("undo-2", size=T.ICON_SM),
                        SUGGEST_UNDO,
                        on_click=on_undo,
                        variant="ghost",
                        aria_label="Deshacer: volver a tu texto",
                        **T.tone_scheme("neutral"),
                        **small,
                    ),
                    rx.button(
                        rx.icon("refresh-cw", size=T.ICON_SM),
                        SUGGEST_AGAIN,
                        on_click=on_again,
                        variant="ghost",
                        aria_label="Otra versión de la sugerencia",
                        **T.tone_scheme("neutral"),
                        **small,
                    ),
                    spacing="2",
                    wrap="wrap",
                ),
                rx.fragment(),
            ),
            spacing="2",
            align="center",
            wrap="wrap",
            width="100%",
        ),
        # One fixed live region (UX U5): it says «Escribiendo…» and then that the
        # proposal landed, so a screen reader hears both.
        rx.box(
            rx.cond(
                busy,
                rx.text(S.suggest_writing, size="2", color=T.TEXT_MUTED),
                rx.cond(
                    view.has_proposal,
                    rx.cond(
                        view.neutral,
                        callout(SUGGEST_NEUTRAL, "info"),
                        rx.text(
                            rx.cond(has_gaps, SUGGEST_DONE_GAPS, SUGGEST_DONE),
                            size="2",
                            color=T.TEXT_MUTED,
                        ),
                    ),
                    rx.fragment(),
                ),
            ),
            custom_attrs={"aria-live": "polite"},
            width="100%",
        ),
        rx.cond(
            view.has_proposal & ~busy,
            rx.vstack(
                rx.cond(
                    view.neutral,
                    rx.vstack(
                        rx.button(
                            SUGGEST_GO_BRAND,
                            on_click=S.save_and_open_brand,
                            disabled=S.saving | S.publishing,
                            variant="ghost",
                            **small,
                        ),
                        rx.cond(
                            S.suggest_notice != "",
                            callout(S.suggest_notice, "warn"),
                            rx.fragment(),
                        ),
                        spacing="1",
                        width="100%",
                        align_items="start",
                    ),
                    rx.fragment(),
                ),
                *(
                    [
                        rx.cond(
                            view.missing_line != "",
                            rx.text(view.missing_line, size="2", color=T.tone_color("warn", 11)),
                            rx.fragment(),
                        )
                    ]
                    if show_missing
                    else []
                ),
                rx.foreach(view.warnings, lambda w: callout(w, "warn")),
                spacing="2",
                width="100%",
                align_items="start",
            ),
            rx.fragment(),
        ),
        rx.cond(view.error != "", callout(view.error, "warn"), rx.fragment()),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _guided_greeting() -> rx.Component:
    g = S.guided
    return _field(
        "Tu saludo",
        rx.text_area(
            value=g.greeting,
            on_change=S.set_guided_greeting,
            read_only=S.suggest_busy == SUGGEST_GREETING,
            aria_label="Tu saludo",
            placeholder="Ej.: ¡Hola! Gracias por escribirnos. Te ayudo con tu pedido.",
            width="100%",
            rows="4",
            size="3",
        ),
        _guided_err(g.greeting_error),
        _hint("Llega una sola vez, la primera vez que cada cliente te escribe."),
        _suggest_tools(
            SUGGEST_GREETING,
            S.greeting_suggest_label,
            S.greeting_suggest,
            S.suggest_greeting,
            S.suggest_greeting_again,
            S.undo_greeting_suggestion,
            show_missing=True,
        ),
    )


def _text_action(label: str | rx.Var, on_click: rx.EventHandler, **props: object) -> rx.Component:
    """«Subir» / «Bajar» / «Editar»: text buttons of 44 px (guide N12), never drag only."""
    return rx.button(
        label,
        on_click=on_click,
        variant="ghost",
        size="2",
        min_height=TARGET_MIN,
        **T.tone_scheme("neutral"),
        **props,
    )


def _answer_row(answer: AnswerVM) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.text(
                rx.cond(answer.label != "", answer.label, "Sin nombre"),
                size="2",
                weight="medium",
                min_width="0",
            ),
            rx.spacer(),
            _tone_pill(answer.status_label, answer.status_tone),
            width="100%",
            align="center",
            spacing="2",
        ),
        rx.cond(
            answer.preview != "",
            rx.text(answer.preview, size="1", color=T.TEXT_MUTED),
            rx.fragment(),
        ),
        # Closed, the card already says what is missing (m-24945866): a gap at the end of a
        # long text never shows in the one-line preview.
        rx.cond(
            answer.gaps_line != "",
            rx.text(answer.gaps_line, size="1", color=T.tone_color("warn", 11)),
            rx.fragment(),
        ),
        rx.hstack(
            rx.spacer(),
            rx.cond(
                answer.can_up,
                _text_action(
                    "Subir",
                    S.move_answer(answer.index, -1),
                    aria_label=f"Subir «{answer.label}»",
                ),
                rx.fragment(),
            ),
            rx.cond(
                answer.can_down,
                _text_action(
                    "Bajar",
                    S.move_answer(answer.index, 1),
                    aria_label=f"Bajar «{answer.label}»",
                ),
                rx.fragment(),
            ),
            _text_action(
                "Editar",
                S.open_answer_panel(answer.index),
                aria_label=f"Editar «{answer.label}»",
            ),
            spacing="1",
            width="100%",
            align="center",
        ),
        spacing="1",
        width="100%",
        align_items="start",
        padding_y="0.5rem",
        border_top=T.BORDER,
    )


def _answers_heading(*children: rx.Component | str) -> rx.Component:
    return rx.text(*children, size="1", weight="medium", color=T.TEXT_MUTED)


def _limit_notice() -> rx.Component:
    """«Subir» on the first answer of «Más preguntas» (spec §3): why, and the way out."""
    return rx.cond(
        S.limit_notice >= 0,
        rx.vstack(
            callout(S.limit_notice_text, "info"),
            rx.hstack(
                rx.button(
                    S.limit_move_label,
                    on_click=S.limit_move_down,
                    variant="soft",
                    size="3",
                    min_height=TARGET_MIN,
                ),
                rx.button(
                    "Dejar así",
                    on_click=S.dismiss_limit_notice,
                    variant="ghost",
                    size="3",
                    min_height=TARGET_MIN,
                    **T.tone_scheme("neutral"),
                ),
                spacing="2",
                wrap="wrap",
            ),
            spacing="2",
            width="100%",
            align_items="start",
        ),
        rx.fragment(),
    )


def _add_answer() -> rx.Component:
    a = S.answers

    def suggestion(item: SuggestionVM) -> rx.Component:
        return rx.button(
            item.label,
            on_click=S.add_answer(item.key),
            variant="soft",
            size="3",
            min_height=TARGET_MIN,
        )

    return rx.vstack(
        rx.button(
            rx.icon("plus", size=T.ICON_SM),
            "Agregar otra respuesta",
            on_click=S.toggle_add_answer,
            disabled=a.full,
            variant="ghost",
            size="3",
            min_height=TARGET_MIN,
        ),
        rx.cond(a.full, _hint(ANSWERS_FULL), rx.fragment()),
        rx.cond(
            S.add_open & ~a.full,
            rx.flex(
                rx.foreach(a.suggestions, suggestion),
                rx.button(
                    "Escribir la mía",
                    on_click=S.add_answer(SUGGESTION_CUSTOM),
                    variant="ghost",
                    size="3",
                    min_height=TARGET_MIN,
                    **T.tone_scheme("neutral"),
                ),
                spacing="2",
                wrap="wrap",
                width="100%",
            ),
            rx.fragment(),
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _auto_payment_answer(text: rx.Var[str]) -> rx.Component:
    """m-24955648 §6: the starter's «Formas de pago» while the business offers methods —
    read-only, exactly what the customer reads; changed in Formas de pago, not here (and
    no «Mejorar mi texto»)."""
    return rx.vstack(
        rx.text("Lo que le respondes", size="2", weight="medium"),
        rx.box(
            rx.text(text, size="2", white_space="pre-wrap"),
            padding="0.75rem",
            border=T.BORDER,
            border_radius=T.RADIUS_CONTROL,
            width="100%",
        ),
        rx.text(PAYMENT_ANSWER_AUTO, size="2", color=T.TEXT_MUTED),
        rx.button(
            rx.icon("wallet", size=T.ICON_SM),
            PAYMENT_ANSWER_CHANGE,
            on_click=S.save_and_open_payments,
            disabled=S.saving | S.publishing,
            variant="soft",
            size="3",
            min_height=TARGET_MIN,
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _answer_panel() -> rx.Component:
    """One answer, opened from «Editar» (spec §2 «Panel de una respuesta»)."""
    a = S.open_answer
    remove_area = rx.cond(
        S.answer_confirm_remove,
        rx.vstack(
            callout(S.remove_confirm_text, "warn"),
            rx.hstack(
                rx.button(
                    "Dejarla",
                    on_click=S.keep_answer,
                    variant="soft",
                    size="3",
                    min_height=TARGET_MIN,
                    **T.tone_scheme("neutral"),
                ),
                rx.button(
                    "Quitar",
                    on_click=S.remove_answer,
                    size="3",
                    min_height=TARGET_MIN,
                    **T.tone_scheme("error"),
                ),
                spacing="2",
                justify="end",
                width="100%",
            ),
            spacing="2",
            width="100%",
        ),
        rx.hstack(
            rx.button(
                "Quitar esta respuesta",
                on_click=S.ask_remove_answer,
                variant="soft",
                size="3",
                min_height=TARGET_MIN,
                **T.tone_scheme("neutral"),
            ),
            rx.spacer(),
            rx.button("Listo", on_click=S.close_answer_panel, size="3", min_height=TARGET_MIN),
            width="100%",
            align="center",
            wrap="wrap",
            spacing="2",
        ),
    )
    catalog_link = rx.button(
        "Ir a la Galería",
        on_click=S.save_and_open_catalog,
        disabled=S.saving | S.publishing,
        variant="soft",
        size="3",
        min_height=TARGET_MIN,
    )
    return rx.dialog.root(
        rx.dialog.content(
            rx.vstack(
                rx.button(
                    rx.icon("chevron-left", size=T.ICON_SM),
                    "Volver a tus respuestas",
                    on_click=S.close_answer_panel,
                    variant="ghost",
                    size="2",
                    min_height=TARGET_MIN,
                    **T.tone_scheme("neutral"),
                ),
                rx.dialog.title(rx.cond(a.label != "", a.label, "Tu respuesta"), margin="0"),
                _field(
                    "Nombre (lo que ve tu cliente)",
                    rx.input(
                        value=a.label,
                        on_change=S.set_answer_label,
                        placeholder="Por ejemplo: Promociones",
                        width="100%",
                        size="3",
                    ),
                    rx.text(a.label_count, size="1", color=T.TEXT_MUTED, class_name="q-nums"),
                    _guided_err(a.label_error),
                ),
                rx.text("Al tocarla: ", a.does, size="2", color=T.TEXT_MUTED),
                rx.cond(
                    a.auto_composed,
                    _auto_payment_answer(a.text),
                    rx.cond(
                        a.text_editable,
                        _field(
                            "Lo que le respondes",
                            rx.cond(
                                S.answer_from_gaps & a.has_gaps,
                                rx.text(GAP_FILL_HINT, size="2"),
                                rx.fragment(),
                            ),
                            rx.text_area(
                                value=a.text,
                                id=ANSWER_TEXT_ID,
                                aria_label="Lo que le respondes",
                                on_change=S.set_answer_text,
                                read_only=S.suggest_busy == SUGGEST_ANSWER,
                                width="100%",
                                rows="5",
                                size="3",
                            ),
                            rx.cond(
                                a.gaps_line != "",
                                rx.text(a.gaps_line, size="2", color=T.tone_color("warn", 11)),
                                rx.fragment(),
                            ),
                            _guided_err(a.text_error),
                            _suggest_tools(
                                SUGGEST_ANSWER,
                                S.answer_suggest_label,
                                S.answer_suggest,
                                S.suggest_answer,
                                S.suggest_answer_again,
                                S.undo_answer_suggestion,
                                show_missing=False,
                                has_gaps=a.has_gaps,
                            ),
                        ),
                        rx.cond(
                            a.is_products,
                            rx.vstack(
                                rx.cond(
                                    S.catalog_count > 0,
                                    rx.text(PRICES_FROM_CATALOG, size="2"),
                                    rx.text(NO_PRODUCTS, size="2"),
                                ),
                                catalog_link,
                                spacing="2",
                                align_items="start",
                                width="100%",
                            ),
                            rx.text(
                                "Muestra otros botones: ",
                                a.preview,
                                ". Los cambias en «Más opciones (avanzado)».",
                                size="2",
                                color=T.TEXT_MUTED,
                            ),
                        ),
                    ),
                ),
                rx.divider(),
                remove_area,
                spacing="3",
                width="100%",
                align_items="start",
            ),
            max_width="32rem",
        ),
        open=S.has_open_answer,
        on_open_change=S.set_answer_panel_open,
    )


def _guided_answers() -> rx.Component:
    """Step 2, «¿Qué te preguntan siempre?» (m-24936836): one ordered list; the first
    ones are WhatsApp's buttons, a line marks where they end, the rest go to «Más
    preguntas». The limits are always on screen, never a silent block."""
    g = S.guided
    a = S.answers
    more_button = rx.vstack(
        rx.text(MORE_ROW_TITLE, size="2", weight="medium"),
        rx.text(MORE_ROW_TEXT, size="1", color=T.TEXT_MUTED),
        spacing="1",
        width="100%",
        align_items="start",
        padding_y="0.5rem",
        border_top=T.BORDER,
    )
    listing = rx.vstack(
        card(
            rx.vstack(
                _answers_heading(BUTTONS_HEADING),
                rx.foreach(a.buttons, _answer_row),
                rx.cond(a.has_more, more_button, rx.fragment()),
                spacing="0",
                width="100%",
                align_items="start",
            ),
            padding="0.75rem 1rem",
        ),
        _limit_notice(),
        rx.cond(
            a.has_more,
            rx.vstack(
                rx.divider(size="4", border_style="dashed"),
                _answers_heading(MORE_HEADING, " (", a.rows_count, ")"),
                rx.foreach(a.rows, _answer_row),
                spacing="1",
                width="100%",
                align_items="start",
            ),
            rx.fragment(),
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )
    return rx.vstack(
        _import_link(),
        rx.cond(
            g.uses_buttons,
            _field(
                "Lo que preguntas sobre los botones",
                rx.input(
                    value=g.question,
                    on_change=S.set_guided_question,
                    placeholder="Ej.: ¿En qué te ayudamos?",
                    width="100%",
                    size="3",
                ),
                _guided_err(g.question_error),
            ),
            rx.fragment(),
        ),
        rx.cond(
            a.count > 0,
            listing,
            rx.vstack(
                callout(ANSWERS_EMPTY, "info"),
                rx.button(
                    rx.icon("plus", size=T.ICON_SM),
                    "Agregar una respuesta",
                    on_click=S.toggle_add_answer,
                    variant="soft",
                    size="3",
                    min_height=TARGET_MIN,
                ),
                spacing="2",
                width="100%",
                align_items="start",
            ),
        ),
        rx.cond(a.count > 0, _add_answer(), _add_answer_suggestions_only()),
        _answer_panel(),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _add_answer_suggestions_only() -> rx.Component:
    """With no answer left, «Agregar una respuesta» (the empty state) opens these."""

    def suggestion(item: SuggestionVM) -> rx.Component:
        return rx.button(
            item.label,
            on_click=S.add_answer(item.key),
            variant="soft",
            size="3",
            min_height=TARGET_MIN,
        )

    return rx.cond(
        S.add_open,
        rx.flex(
            rx.foreach(S.answers.suggestions, suggestion),
            rx.button(
                "Escribir la mía",
                on_click=S.add_answer(SUGGESTION_CUSTOM),
                variant="ghost",
                size="3",
                min_height=TARGET_MIN,
                **T.tone_scheme("neutral"),
            ),
            spacing="2",
            wrap="wrap",
            width="100%",
        ),
        rx.fragment(),
    )


def _strip_dialog() -> rx.Component:
    """«Quitar las que faltan y publicar» names what goes; nothing is removed before «Sí»."""
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title("Quitar las que faltan y publicar"),
            rx.alert_dialog.description(S.publish_gaps.strip_text, size="2"),
            rx.flex(
                rx.alert_dialog.cancel(
                    rx.button("Cancelar", variant="soft", size="3", **T.tone_scheme("neutral")),
                ),
                rx.alert_dialog.action(
                    rx.button(
                        "Sí, publicar sin ellas",
                        on_click=S.confirm_strip_and_publish,
                        size="3",
                    ),
                ),
                spacing="3",
                margin_top="1rem",
                justify="end",
                wrap="wrap",
            ),
            max_width="28rem",
        ),
        open=S.strip_confirm_open,
        on_open_change=S.set_strip_confirm_open,
    )


def _no_products_warning() -> rx.Component:
    """Step 4 with an empty catalog: a warning, not a green check. Publishing stays on."""
    return rx.cond(
        S.answers.shows_products & (S.catalog_count == 0),
        rx.vstack(
            callout(NO_PRODUCTS_WARNING, "warn"),
            rx.button(
                "Ir a la Galería",
                on_click=S.save_and_open_catalog,
                disabled=S.saving | S.publishing,
                variant="soft",
                size="3",
                min_height=TARGET_MIN,
            ),
            spacing="2",
            width="100%",
            align_items="start",
        ),
        rx.fragment(),
    )


def _publish_gaps() -> rx.Component:
    """Step 4: a gap never reaches a customer — say which answers, and the two ways out."""
    gaps = S.publish_gaps
    return rx.fragment(
        _strip_dialog(),
        rx.cond(
            gaps.greeting != "",
            rx.vstack(
                callout(gaps.greeting, "warn"),
                rx.button(
                    "Corregir en el paso 1",
                    on_click=S.guided_go(1),
                    variant="soft",
                    size="3",
                    min_height=TARGET_MIN,
                ),
                spacing="2",
                width="100%",
                align_items="start",
            ),
            rx.fragment(),
        ),
        rx.cond(
            gaps.answers_text != "",
            rx.vstack(
                callout(gaps.answers_text, "warn"),
                rx.flex(
                    rx.button(
                        "Completarlas",
                        on_click=S.complete_gaps,
                        variant="soft",
                        size="3",
                        min_height=TARGET_MIN,
                    ),
                    rx.cond(
                        gaps.can_strip,
                        rx.button(
                            "Quitar las que faltan y publicar",
                            on_click=S.strip_gaps_and_publish,
                            disabled=S.saving | S.publishing,
                            variant="ghost",
                            size="3",
                            min_height=TARGET_MIN,
                            **T.tone_scheme("neutral"),
                        ),
                        rx.fragment(),
                    ),
                    spacing="2",
                    wrap="wrap",
                ),
                spacing="2",
                width="100%",
                align_items="start",
            ),
            rx.fragment(),
        ),
        rx.cond(
            gaps.elsewhere,
            rx.vstack(
                callout(gaps.elsewhere_text, "warn"),
                rx.button(
                    "Revisar en «Más opciones»",
                    on_click=S.set_advanced(True),
                    variant="soft",
                    size="3",
                    min_height=TARGET_MIN,
                    **T.tone_scheme("neutral"),
                ),
                spacing="2",
                width="100%",
                align_items="start",
            ),
            rx.fragment(),
        ),
    )


def _catalog_row(row: CatalogRowVM) -> rx.Component:
    return rx.hstack(
        rx.text(row.name, size="2", min_width="0"),
        rx.spacer(),
        rx.text(row.price, size="2", color=T.TEXT_MUTED, class_name="q-nums", flex_shrink="0"),
        width="100%",
        align="center",
        padding_y="0.35rem",
        border_top=T.BORDER,
    )


def _catalog_section(section: CatalogSectionVM) -> rx.Component:
    """One category of step 3's read-only order, as WhatsApp titles its section."""
    return rx.vstack(
        rx.hstack(
            rx.text(section.label, size="1", weight="bold", color=T.TEXT_MUTED),
            rx.cond(
                section.count_label != "",
                rx.text(section.count_label, size="1", color=T.TEXT_MUTED, class_name="q-nums"),
                rx.fragment(),
            ),
            spacing="2",
            align="baseline",
        ),
        rx.foreach(section.rows, _catalog_row),
        spacing="0",
        width="100%",
        align_items="start",
    )


def _address_choice(value: str, title: str, description: str) -> rx.Component:
    selected = S.guided.address_choice == value
    return choice_card(
        rx.vstack(
            rx.hstack(
                rx.text(title, size="2", weight="medium"),
                rx.spacer(),
                rx.cond(selected, choice_card_check(), rx.fragment()),
                width="100%",
            ),
            rx.text(description, size="1", color=T.TEXT_MUTED),
            spacing="1",
            align_items="start",
            width="100%",
        ),
        selected=selected,
        on_select=S.set_guided_address(value),
        padding="0.75rem 1rem",
        min_height=TARGET_MIN,
    )


def _guided_products() -> rx.Component:
    g = S.guided
    # Going to Catálogo saves first (N6); with something to fix it cannot, and says so.
    leave_blocked = S.dirty & (S.error_count > 0)

    def leave_hint() -> rx.Component:
        return rx.cond(
            leave_blocked,
            rx.text(CATALOG_FIX_FIRST, size="1", color=T.tone_color("warn", 11)),
            _hint(CATALOG_SAVED_HINT),
        )

    catalog = rx.cond(
        S.catalog_count > 0,
        rx.vstack(
            # m-24955643: the order, read-only — it is chosen in one place, Catálogo
            rx.text(ORDER_HINT, size="2", weight="medium"),
            rx.text(S.catalog_order_text, size="2", color=T.TEXT_MUTED),
            rx.cond(
                S.catalog_mode_text != "",
                rx.text(S.catalog_mode_text, size="2", color=T.TEXT_MUTED),
                rx.fragment(),
            ),
            rx.vstack(
                rx.foreach(S.catalog_first_screen, _catalog_section),
                spacing="2",
                width="100%",
            ),
            rx.cond(
                S.catalog_more_text != "",
                rx.text(S.catalog_more_text, size="1", color=T.TEXT_MUTED),
            ),
            # m-24955838: products without a category show as one long list
            rx.cond(
                S.group_notice_text != "",
                rx.vstack(
                    callout(S.group_notice_text, "info", icon="layers"),
                    rx.button(
                        rx.icon("layers", size=T.ICON_SM),
                        GROUP_BUTTON,
                        on_click=S.save_and_open_group,
                        disabled=leave_blocked | S.saving | S.publishing,
                        size="3",
                        min_height=TARGET_MIN,
                    ),
                    spacing="2",
                    width="100%",
                    align_items="start",
                ),
                rx.fragment(),
            ),
            rx.button(
                rx.icon("arrow-up-down", size=T.ICON_SM),
                CHANGE_ORDER,
                on_click=S.save_and_open_order,
                disabled=leave_blocked | S.saving | S.publishing,
                variant="soft",
                size="3",
                min_height=TARGET_MIN,
            ),
            rx.button(
                "Guardar y cambiar mis productos",
                on_click=S.save_and_open_catalog,
                disabled=leave_blocked | S.saving | S.publishing,
                loading=S.saving & ~S.publishing,
                variant="ghost",
                size="3",
                min_height=TARGET_MIN,
            ),
            leave_hint(),
            spacing="2",
            width="100%",
            align_items="start",
        ),
        empty_state(
            "package",
            "Aún no tienes productos",
            "Agrega tus productos con su precio y vuelve aquí: tu cliente podrá elegirlos "
            "desde WhatsApp.",
            rx.vstack(
                rx.button(
                    rx.icon("plus", size=T.ICON_SM),
                    "Guardar y agregar mis productos",
                    on_click=S.save_and_open_catalog,
                    disabled=leave_blocked | S.saving | S.publishing,
                    loading=S.saving & ~S.publishing,
                    size="3",
                    min_height=TARGET_MIN,
                ),
                leave_hint(),
                spacing="2",
                align_items="center",
            ),
        ),
    )
    payments_invite = rx.cond(
        (S.catalog_count > 0) & (S.payments_offered == 0),
        rx.vstack(
            callout(PAYMENTS_INVITE, "info", icon="wallet"),
            rx.button(
                rx.icon("wallet", size=T.ICON_SM),
                PAYMENTS_INVITE_BUTTON,
                on_click=S.save_and_open_payments,
                disabled=leave_blocked | S.saving | S.publishing,
                variant="soft",
                size="3",
                min_height=TARGET_MIN,
            ),
            spacing="2",
            width="100%",
            align_items="start",
        ),
        rx.fragment(),
    )
    return rx.vstack(
        catalog,
        payments_invite,
        rx.cond(
            g.has_products,
            _field(
                "Lo que dices antes de la lista",
                rx.input(
                    value=g.products_intro,
                    on_change=S.set_guided_products_intro,
                    placeholder="Ej.: Elige un producto para agregarlo a tu pedido.",
                    width="100%",
                    size="3",
                ),
                _guided_err(g.products_intro_error),
            ),
            rx.vstack(
                rx.text(
                    "Para que tu cliente vea tus productos, agrega «Ver menú y pedir» a "
                    "tus respuestas.",
                    size="2",
                ),
                rx.button(
                    rx.icon("arrow-left", size=T.ICON_SM),
                    "Ir a tus respuestas",
                    on_click=S.guided_go(2),
                    variant="soft",
                    size="3",
                    min_height=TARGET_MIN,
                ),
                spacing="2",
                align_items="start",
                width="100%",
            ),
        ),
        rx.cond(
            g.has_order,
            rx.vstack(
                rx.text("Cuando tu cliente confirma el pedido", size="2", weight="medium"),
                rx.grid(
                    _address_choice(
                        ADDRESS_ASK,
                        "Pedir dirección",
                        "Le pregunta a dónde lo llevas y luego te pasa el chat.",
                    ),
                    _address_choice(
                        ADDRESS_SKIP,
                        "No pedir nada",
                        "Te pasa el chat enseguida, para que lo cierres tú.",
                    ),
                    columns=rx.breakpoints(initial="1", sm="2"),
                    spacing="2",
                    width="100%",
                ),
                rx.cond(
                    g.address_choice == ADDRESS_ASK,
                    _field(
                        "Cómo pides la dirección",
                        rx.input(
                            value=g.address_prompt,
                            on_change=S.set_guided_address_prompt,
                            width="100%",
                            size="3",
                        ),
                        _guided_err(g.address_error),
                    ),
                    rx.fragment(),
                ),
                spacing="2",
                width="100%",
                align_items="start",
            ),
            rx.fragment(),
        ),
        spacing="4",
        width="100%",
        align_items="start",
    )


def _step_issue(show: rx.Var[bool], text: str, step: int) -> rx.Component:
    return rx.cond(
        show,
        rx.vstack(
            callout(text, "warn"),
            rx.button(
                f"Corregir en el paso {step}",
                on_click=S.guided_go(step),
                variant="soft",
                size="3",
                min_height=TARGET_MIN,
            ),
            spacing="2",
            width="100%",
            align_items="start",
        ),
        rx.fragment(),
    )


def _guided_publish() -> rx.Component:
    g = S.guided
    return rx.vstack(
        # What blocks publishing comes first: on a phone the review list below is long.
        _publish_gaps(),
        rx.text("Así va a responder tu WhatsApp:", size="2", weight="medium"),
        rx.vstack(
            rx.foreach(
                S.guided_review,
                lambda line: rx.hstack(
                    rx.icon("check", size=T.ICON_SM, color=T.tone_color("ok", 11), flex_shrink="0"),
                    rx.text(line, size="2"),
                    spacing="2",
                    align="start",
                ),
            ),
            spacing="2",
            width="100%",
            align_items="start",
        ),
        # Each step with something to fix, and the way back to it (N6/N10).
        _step_issue(g.greeting_issue, "Falta tu saludo.", 1),
        _step_issue(g.buttons_issue, ANSWER_ISSUE, 2),
        _no_products_warning(),
        _step_issue(
            g.products_issue,
            "Falta lo que dices antes de tus productos o cómo pides la dirección.",
            3,
        ),
        rx.cond(
            g.hidden_issues > 0,
            rx.vstack(
                callout(
                    "Hay algo por corregir en partes del menú que no están en estos 4 pasos.",
                    "warn",
                ),
                rx.button(
                    "Revisar en «Más opciones»",
                    on_click=S.set_advanced(True),
                    variant="soft",
                    size="3",
                    min_height=TARGET_MIN,
                    **T.tone_scheme("neutral"),
                ),
                spacing="2",
                width="100%",
                align_items="start",
            ),
            rx.fragment(),
        ),
        _publish_area(),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _guided_card() -> rx.Component:
    """The default view: one decision per step (guide N6), the same form underneath."""
    return card(
        rx.vstack(
            rx.text(S.guided_help, size="2", color=T.TEXT_MUTED),
            rx.match(
                S.guided_step,
                (1, _guided_greeting()),
                (2, _guided_answers()),
                (3, _guided_products()),
                _guided_publish(),
            ),
            rx.divider(),
            rx.button(
                rx.icon("settings-2", size=T.ICON_SM),
                "Más opciones (avanzado)",
                on_click=S.set_advanced(True),
                variant="ghost",
                size="3",
                min_height=TARGET_MIN,
                **T.tone_scheme("neutral"),
            ),
            spacing="4",
            width="100%",
            align_items="start",
        ),
        padding="1.25rem 1.5rem",
        class_name="q-card q-menu-guided-panel",
        custom_attrs={"data-dir": S.guided_direction},
    )


# ======================================================================================
# «Cargar desde una foto o mi página» (m-24936840, spec §4 and §6)
# ======================================================================================

# `rx.upload`'s id must be a module-level constant: it links the dropzone to
# `rx.upload_files(upload_id=...)`.
IMPORT_UPLOAD_ID = "whatsapp_menu_import"
#: What the picker takes. HEIC is left out on purpose: phones convert it to JPEG on the
#: way when the page asks for these types (the reader refuses HEIC).
IMPORT_ACCEPT = {
    "image/jpeg": [".jpg", ".jpeg"],
    "image/png": [".png"],
    "image/webp": [".webp"],
    "application/pdf": [".pdf"],
}


def _import_heading(text: str | rx.Var, *below: rx.Component, heading_id: str = "") -> rx.Component:
    focus = {"id": heading_id, "tab_index": -1} if heading_id else {}
    return rx.vstack(
        rx.dialog.title(text, size="4", margin="0", **focus),
        *below,
        spacing="1",
        width="100%",
        align_items="start",
    )


def _import_back() -> rx.Component:
    return rx.button(
        rx.icon("chevron-left", size=T.ICON_SM),
        "Atrás",
        on_click=S.import_back,
        variant="ghost",
        size="2",
        min_height=TARGET_MIN,
        **T.tone_scheme("neutral"),
    )


def _import_source_card(source: str, icon: str, title: str, help_text: str) -> rx.Component:
    return choice_card(
        rx.hstack(
            rx.icon(icon, size=20, color=T.TEXT_MUTED, aria_hidden="true"),
            rx.vstack(
                rx.text(title, size="3", weight="medium"),
                rx.text(help_text, size="2", color=T.TEXT_MUTED),
                spacing="1",
                align_items="start",
            ),
            spacing="3",
            align="center",
            width="100%",
        ),
        selected=False,
        on_select=S.choose_import_source(source),
        disabled=S.suggest_busy != "",
        min_height=TARGET_MIN,
        width="100%",
    )


def _import_choose() -> rx.Component:
    """One decision: where the facts come from. «Ahora no» is always the way past it."""
    return rx.vstack(
        _import_heading(
            IMPORT_OFFER_TITLE, rx.text(IMPORT_OFFER_HELP, size="2", color=T.TEXT_MUTED)
        ),
        _import_source_card(IMPORT_PHOTO, "camera", IMPORT_PHOTO_CARD, IMPORT_PHOTO_CARD_HELP),
        _import_source_card(IMPORT_PAGE, "globe", IMPORT_PAGE_CARD, IMPORT_PAGE_CARD_HELP),
        rx.text(IMPORT_PRIVACY, size="1", color=T.TEXT_FAINT),
        rx.button(
            rx.cond(S.import_offer, IMPORT_NOT_NOW, IMPORT_DONE),
            on_click=S.close_import,
            variant="ghost",
            size="3",
            min_height=TARGET_MIN,
            **T.tone_scheme("neutral"),
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _import_photo() -> rx.Component:
    return rx.vstack(
        _import_back(),
        _import_heading(
            IMPORT_PHOTO_TITLE, rx.text(IMPORT_PHOTO_HELP, size="2", color=T.TEXT_MUTED)
        ),
        dropzone(
            rx.button(
                rx.icon("upload", size=T.ICON_SM),
                IMPORT_PHOTO_BUTTON,
                size="3",
                min_height=TARGET_MIN,
                width="100%",
                disabled=S.suggest_busy != "",
            ),
            upload_id=IMPORT_UPLOAD_ID,
            accept=IMPORT_ACCEPT,
            max_files=1,
            max_size=IMPORT_MAX_BYTES,
            on_drop=S.handle_import_upload(rx.upload_files(upload_id=IMPORT_UPLOAD_ID)),
            on_drop_rejected=S.import_file_rejected,
            variant="bare",
            width="100%",
        ),
        rx.text(IMPORT_PRIVACY, size="1", color=T.TEXT_FAINT),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _import_page() -> rx.Component:
    return rx.vstack(
        _import_back(),
        _import_heading(IMPORT_PAGE_TITLE, rx.text(IMPORT_PAGE_HELP, size="2", color=T.TEXT_MUTED)),
        _field(
            IMPORT_PAGE_LABEL,
            rx.input(
                value=S.import_url,
                on_change=S.set_import_url,
                placeholder=IMPORT_PAGE_PLACEHOLDER,
                aria_label=IMPORT_PAGE_LABEL,
                type="url",
                input_mode="url",
                width="100%",
                size="3",
            ),
            _guided_err(S.import_url_error),
        ),
        rx.button(
            IMPORT_PAGE_BUTTON,
            on_click=S.submit_import_url,
            disabled=S.suggest_busy != "",
            size="3",
            min_height=TARGET_MIN,
        ),
        rx.text(IMPORT_PRIVACY, size="1", color=T.TEXT_FAINT),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _import_without() -> rx.Component:
    return rx.button(
        rx.cond(S.import_kind == "url", "Seguir sin la página", "Seguir sin la foto"),
        on_click=S.close_import,
        variant="ghost",
        size="3",
        min_height=TARGET_MIN,
        **T.tone_scheme("neutral"),
    )


def _import_reading() -> rx.Component:
    """(b) Waiting: a placeholder shaped like the review, and one live line."""
    return rx.vstack(
        _import_heading("Leyendo tu menú"),
        rx.box(
            rx.text(
                rx.cond(S.import_slow, IMPORT_SLOW, IMPORT_READING_TEXT),
                size="2",
                color=T.TEXT_MUTED,
            ),
            custom_attrs={"aria-live": "polite", "role": "status"},
            width="100%",
        ),
        skeleton_card(3),
        rx.cond(
            S.import_slow,
            _import_without(),
            rx.button(
                IMPORT_CANCEL,
                on_click=S.close_import,
                variant="soft",
                size="3",
                min_height=TARGET_MIN,
                **T.tone_scheme("neutral"),
            ),
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _import_problem(tone: str) -> rx.Component:
    """§6: the photo that cannot be read, the link that does not open, the read that
    fails, the source with nothing useful. The menu stays as it was."""
    return rx.vstack(
        _import_heading("No pudimos usar ese menú" if tone == "warn" else "Sin datos para usar"),
        rx.box(callout(S.import_error, tone), custom_attrs={"role": "alert"}, width="100%"),
        rx.hstack(
            rx.button(
                rx.match(
                    S.import_kind,
                    ("url", "Probar otro enlace"),
                    ("pdf", "Probar otro archivo"),
                    "Probar otra foto",
                ),
                on_click=S.import_back,
                size="3",
                min_height=TARGET_MIN,
            ),
            _import_without(),
            spacing="2",
            wrap="wrap",
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _fact_row(fact: ImportFactVM) -> rx.Component:
    """One datum: where it came from (the quote), the answer as it would read, and
    «Usar» · «Editar» · «No usar»."""
    # A sentence (m-24945867) is offered as the answer's whole text: «Usar este texto» ·
    # «Editar» (to shorten it into a value) · «No usar».
    use_label = rx.cond(fact.is_sentence, IMPORT_USE_SENTENCE, IMPORT_USE)
    skip_label = IMPORT_SKIP
    actions = rx.hstack(
        rx.button(
            use_label,
            on_click=S.use_import_fact(fact.index),
            disabled=~fact.can_use,
            variant="soft",
            size="3",
            min_height=TARGET_MIN,
            aria_label=use_label + ": " + fact.title,
        ),
        _text_action(
            rx.cond(fact.editing, IMPORT_EDIT_DONE, IMPORT_EDIT),
            S.edit_import_fact(fact.index),
            aria_label=IMPORT_EDIT + ": " + fact.title,
        ),
        _text_action(
            skip_label,
            S.skip_import_fact(fact.index),
            aria_label=skip_label + ": " + fact.title,
        ),
        spacing="2",
        wrap="wrap",
    )
    return rx.vstack(
        rx.hstack(
            rx.heading(fact.title, size="3", as_="h3", min_width="0"),
            rx.spacer(),
            rx.cond(
                fact.status_label != "",
                _tone_pill(fact.status_label, fact.status_tone),
                rx.fragment(),
            ),
            width="100%",
            align="center",
        ),
        rx.cond(
            fact.evidence_line != "",
            rx.text(fact.evidence_line, size="2", color=T.TEXT_MUTED),
            rx.fragment(),
        ),
        rx.cond(
            fact.editing,
            rx.vstack(
                rx.input(
                    value=fact.value,
                    on_change=S.set_import_fact_value,
                    aria_label="Dato: " + fact.title,
                    width="100%",
                    size="3",
                ),
                rx.cond(
                    fact.edit_hint != "",
                    rx.text(fact.edit_hint, size="2", color=T.TEXT_MUTED),
                    rx.fragment(),
                ),
                spacing="1",
                width="100%",
                align_items="start",
            ),
            rx.fragment(),
        ),
        rx.cond(
            fact.used_note != "",
            rx.text(fact.used_note, size="2", color=T.TEXT_MUTED),
            rx.fragment(),
        ),
        rx.cond(
            fact.pending,
            rx.vstack(
                rx.cond(fact.note != "", rx.text(fact.note, size="2"), rx.fragment()),
                rx.cond(
                    fact.preview != "",
                    rx.text(
                        fact.preview,
                        size="2",
                        padding="0.5rem 0.75rem",
                        border_radius=T.RADIUS_CONTROL,
                        background=T.CARD_BG,
                        width="100%",
                    ),
                    rx.fragment(),
                ),
                actions,
                spacing="2",
                width="100%",
                align_items="start",
            ),
            rx.fragment(),
        ),
        spacing="2",
        width="100%",
        align_items="start",
        padding_y="0.75rem",
        border_top=T.BORDER,
    )


def _import_product_row(product: ImportProductVM) -> rx.Component:
    return rx.vstack(
        rx.checkbox(
            rx.text(product.name, " · ", product.price, size="2"),
            checked=product.checked,
            on_change=lambda value: S.toggle_import_product(product.index, value),
            size="3",
            min_height=TARGET_MIN,
            align_items="center",
        ),
        rx.cond(
            product.evidence_line != "",
            rx.text(product.evidence_line, size="1", color=T.TEXT_MUTED, padding_left="2rem"),
            rx.fragment(),
        ),
        # m-24955838: the category it will get, tappable to change before adding
        rx.cond(
            product.editing_category,
            _import_category_field(),
            rx.hstack(
                rx.button(
                    product.category_label,
                    rx.icon("pencil", size=T.ICON_SM),
                    on_click=S.edit_import_category(product.index),
                    variant="soft",
                    size="2",
                    min_height=TARGET_MIN,
                    type="button",
                    aria_label=product.category_aria,
                    **T.tone_scheme("neutral"),
                ),
                rx.cond(product.category_new, tone_badge("Nueva", "info"), rx.fragment()),
                align="center",
                spacing="2",
                padding_left="2rem",
            ),
        ),
        spacing="1",
        width="100%",
        align_items="start",
    )


def _import_category_choice(name: rx.Var[str]) -> rx.Component:
    return rx.button(
        name,
        on_click=S.pick_import_category(name),
        variant=rx.cond(S.import_category_text == name, "solid", "soft"),
        size="2",
        min_height=TARGET_MIN,
        type="button",
        aria_pressed=rx.cond(S.import_category_text == name, "true", "false"),
        **T.tone_scheme("neutral"),
    )


def _import_category_field() -> rx.Component:
    """The category of one found product: tap one the brand (or this review) already
    has, or type it — the same 24-letter rule as in Catálogo; empty = «Sin categoría»
    (it goes to «Otros»). Enter saves. Nothing is written before «Agregar…»."""
    return rx.vstack(
        rx.cond(
            S.import_category_choices.length() > 0,
            rx.flex(
                rx.foreach(S.import_category_choices, _import_category_choice),
                wrap="wrap",
                gap="2",
                role="group",
                aria_label="Tus categorías",
            ),
            rx.fragment(),
        ),
        rx.el.label(
            rx.text(CATEGORY_NAME_LABEL, size="2", weight="medium"),
            html_for="q-import-category",
        ),
        rx.input(
            id="q-import-category",
            value=S.import_category_text,
            on_change=S.set_import_category_text,
            on_key_down=S.import_category_key,
            placeholder=CATEGORY_NAME_PLACEHOLDER,
            size="3",
            width="100%",
            aria_describedby="q-import-category-help q-import-category-count",
        ),
        rx.hstack(
            rx.text(CATEGORY_NAME_HELP, size="1", color=T.TEXT_MUTED, id="q-import-category-help"),
            rx.spacer(),
            rx.text(
                S.import_category_count,
                size="1",
                color=T.TEXT_MUTED,
                class_name="q-nums",
                flex_shrink="0",
                id="q-import-category-count",
            ),
            width="100%",
            align="start",
        ),
        rx.cond(
            S.import_category_error != "",
            rx.text(
                S.import_category_error, size="2", color=T.tone_color("error", 11), role="alert"
            ),
            rx.fragment(),
        ),
        rx.hstack(
            rx.button(
                "Cancelar",
                on_click=S.cancel_import_category,
                variant="ghost",
                size="2",
                min_height=TARGET_MIN,
                type="button",
                **T.tone_scheme("neutral"),
            ),
            rx.button(
                "Listo",
                on_click=S.save_import_category,
                size="2",
                min_height=TARGET_MIN,
                type="button",
            ),
            justify="end",
            width="100%",
            spacing="2",
        ),
        spacing="2",
        width="100%",
        padding_left="2rem",
        align_items="start",
    )


def _import_add_button() -> rx.Component:
    r = S.import_review
    return rx.button(
        rx.icon("plus", size=T.ICON_SM),
        IMPORT_ADD_BUTTON,
        on_click=S.add_import_products,
        disabled=(r.checked_count == 0) | S.import_adding,
        loading=S.import_adding,
        variant="soft",
        size="3",
        min_height=TARGET_MIN,
        white_space="normal",
        height="auto",
    )


def _import_mark_all() -> rx.Component:
    """With a long menu on the phone: what is ticked by default, and all / none."""
    r = S.import_review
    return rx.cond(
        r.checked_line != "",
        rx.hstack(
            rx.text(r.checked_line, size="2", color=T.TEXT_MUTED),
            _text_action(IMPORT_CHECK_ALL, S.set_all_import_products(True)),
            _text_action(IMPORT_UNCHECK_ALL, S.set_all_import_products(False)),
            spacing="2",
            align="center",
            wrap="wrap",
            width="100%",
        ),
        rx.fragment(),
    )


def _import_products() -> rx.Component:
    r = S.import_review
    return rx.cond(
        r.has_products,
        card(
            rx.vstack(
                rx.heading(r.products_title, size="3", as_="h3"),
                rx.cond(r.existing_line != "", rx.text(r.existing_line, size="2"), rx.fragment()),
                rx.foreach(r.conflicts, lambda line: rx.text(line, size="2")),
                rx.cond(
                    r.new_products.length() > 0,
                    rx.vstack(
                        rx.text(IMPORT_PRODUCTS_NEW_HELP, size="2", color=T.TEXT_MUTED),
                        rx.cond(
                            r.categories_line != "",
                            rx.text(r.categories_line, size="2"),
                            rx.fragment(),
                        ),
                        _import_mark_all(),
                        rx.foreach(r.new_products, _import_product_row),
                        _import_add_button(),
                        spacing="2",
                        width="100%",
                        align_items="start",
                    ),
                    rx.fragment(),
                ),
                rx.box(
                    rx.foreach(r.added_lines, lambda line: callout(line, "ok")),
                    rx.cond(
                        S.import_add_error != "",
                        callout(S.import_add_error, "warn"),
                        rx.fragment(),
                    ),
                    custom_attrs={"aria-live": "polite"},
                    width="100%",
                ),
                spacing="2",
                width="100%",
                align_items="start",
            ),
            padding="0.75rem 1rem",
        ),
        rx.fragment(),
    )


def _import_review() -> rx.Component:
    """(c) Review datum by datum (spec §4 mockup): only what the owner uses goes in."""
    r = S.import_review
    return rx.vstack(
        _import_heading(
            r.title,
            rx.text(IMPORT_REVIEW_HELP, size="2", color=T.TEXT_MUTED),
            heading_id=IMPORT_REVIEW_HEADING_ID,
        ),
        rx.cond(
            r.source_line != "",
            rx.text(r.source_line, size="1", color=T.TEXT_FAINT),
            rx.fragment(),
        ),
        rx.foreach(r.warnings, lambda w: callout(w, "warn")),
        rx.vstack(
            rx.foreach(r.facts, _fact_row),
            rx.foreach(r.not_found, lambda line: rx.text(line, size="2", color=T.TEXT_MUTED)),
            spacing="0",
            width="100%",
            align_items="start",
        ),
        _import_products(),
        rx.divider(),
        # The foot of the dialog: on a long list the add button is here too, next to the
        # way out, so nobody scrolls back up to find it.
        rx.flex(
            rx.cond(r.new_products.length() > 1, _import_add_button(), rx.fragment()),
            rx.button(IMPORT_DONE, on_click=S.finish_import, size="3", min_height=TARGET_MIN),
            spacing="2",
            wrap="wrap",
            width="100%",
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _import_dialog() -> rx.Component:
    """The import, one decision at a time: choose → upload or link → wait → review."""
    return rx.dialog.root(
        rx.dialog.content(
            rx.match(
                S.import_phase,
                (IMPORT_CHOOSE, _import_choose()),
                (IMPORT_PHOTO, _import_photo()),
                (IMPORT_PAGE, _import_page()),
                (IMPORT_READING, _import_reading()),
                (IMPORT_REVIEW, _import_review()),
                (IMPORT_EMPTY_PHASE, _import_problem("info")),
                _import_problem("warn"),
            ),
            max_width="34rem",
        ),
        open=S.import_phase != "",
        on_open_change=S.set_import_open,
    )


def _import_link() -> rx.Component:
    """Step 2's way back to the import, any time (a soft link, not the step's action)."""
    return rx.button(
        rx.icon("image-up", size=T.ICON_SM),
        IMPORT_LINK,
        on_click=S.open_import,
        disabled=S.suggest_busy != "",
        variant="ghost",
        size="2",
        min_height=TARGET_MIN,
    )


# ======================================================================================
# The tab
# ======================================================================================


def back_to_guided() -> rx.Component:
    """Mounted in the module's existing sticky header while the long editor is open."""
    return rx.button(
        rx.icon("arrow-left", size=T.ICON_SM),
        "Volver a los 4 pasos",
        on_click=S.set_advanced(False),
        variant="ghost",
        size="3",
        min_height=TARGET_MIN,
        **T.tone_scheme("neutral"),
    )


def _advanced() -> rx.Component:
    return rx.vstack(
        _entry_card(),
        _steps_card(),
        _versions_section(),
        spacing="4",
        width="100%",
        min_width="0",
    )


def _editor() -> rx.Component:
    return rx.grid(
        rx.vstack(
            _toolbar(),
            rx.cond(S.advanced_open, _advanced(), _guided_card()),
            _import_dialog(),
            spacing="4",
            width="100%",
            min_width="0",
        ),
        rx.box(
            _preview_card(),
            id=PREVIEW_ELEMENT_ID,
            # On the phone the preview waits for step 4 «Pruébalo y publícalo» (or the
            # advanced editor), so steps 1-3 are one decision with nothing below.
            display=rx.breakpoints(
                initial=rx.cond(S.advanced_open | (S.guided_step == 4), "block", "none"),
                lg="block",
            ),
            position=rx.breakpoints(initial="static", lg="sticky"),
            top="1rem",
            scroll_margin_top=T.SCROLL_MARGIN_TOP,
        ),
        grid_template_columns=rx.breakpoints(
            initial="minmax(0, 1fr)", lg="minmax(0, 1fr) minmax(0, 22rem)"
        ),
        gap="1rem",
        width="100%",
        align_items="start",
    )


def _loaded() -> rx.Component:
    return rx.vstack(
        _menus_card(),
        rx.cond(S.has_menu, _editor(), rx.fragment()),
        spacing="4",
        width="100%",
    )


def menu_tab() -> rx.Component:
    ready = S.loaded_for == WhatsAppState.selected_connection_id
    failed = ~ready & (S.loading_for == "") & (S.banner != "")
    return rx.vstack(
        flow_sync(
            "menu", S.guided_step, ready=ready & S.has_menu & S.flow_ready, objeto=S.menu.menu_id
        ),
        _banner(S.banner, S.banner_tone),
        rx.cond(
            ready,
            _loaded(),
            rx.cond(
                failed,
                rx.button(
                    rx.icon("refresh-cw", size=T.ICON_SM),
                    "Volver a leer los menús",
                    on_click=S.reload,
                    variant="soft",
                    size="2",
                    **T.tone_scheme("neutral"),
                ),
                rx.vstack(skeleton_card(3), skeleton_rows(2, height="6rem"), width="100%"),
            ),
        ),
        spacing="4",
        width="100%",
        align_items="start",
        on_mount=S.ensure_loaded,
    )


def menu_step_frame() -> rx.Component:
    """The guided menu replaces the module header while its four steps are open."""
    return step_frame(
        menu_tab(),
        head=step_head(
            S.guided_title,
            step=S.guided_step,
            total=4,
            back_label="WhatsApp",
            on_exit=S.leave_guided,
        ),
        foot=step_foot(
            rx.cond(S.guided_step < 4, "Siguiente", PUBLISH_BUTTON),
            step=S.guided_step,
            on_primary=S.guided_primary,
            on_back=S.guided_back,
            on_later=S.save_for_later,
            primary_disabled=S.saving | S.publishing | ((S.guided_step == 4) & ~S.can_publish),
            primary_loading=S.saving | S.publishing,
            reason=rx.cond(S.guided_step == 4, S.publish_block_reason, ""),
        ),
        # The editor and the preview own native inputs; history uses flow_sync and
        # the route's existing POP listener, so changing steps need not remount them.
        step=1,
        direction=S.guided_direction,
    )

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

Talks to `WhatsAppMenuState` only — never to the provider, Graph or Postgres.
"""

from __future__ import annotations

import reflex as rx

from .ui import (
    callout,
    card,
    chat_bubble,
    choice_card,
    choice_card_check,
    empty_state,
    mono,
    signal_pill,
    skeleton_card,
    skeleton_rows,
    tag,
)
from .ui import tokens as T
from .whatsapp_menu_state import WhatsAppMenuState as S
from .whatsapp_menu_vm import (
    COLLECT_VALIDATIONS,
    KIND_BUTTONS,
    KIND_COLLECT,
    KIND_HANDOFF,
    KIND_LIST,
    KIND_ORDER_SUMMARY,
    KIND_PRODUCTS,
    KIND_TEXT,
    NEXT_STEP_QR,
    NODE_KINDS,
    NONE_VALUE,
    PUBLISH_BUTTON,
    PUBLISH_CONFIRM,
    PUBLISH_CONFIRM_BUTTON,
    PUBLISHED_BUT_PAUSED,
    RESUME_BUTTON,
    SAVE_ONLY_BUTTON,
    TEMPLATE_EMPTY,
    TEMPLATE_FAST_FOOD,
    CommandForm,
    IceBreakerForm,
    KeywordForm,
    MenuSummaryVM,
    MenuVersionVM,
    NodeForm,
    OptionForm,
    PreviewChoiceVM,
    PreviewMessageVM,
)
from .whatsapp_state import WhatsAppState
from .whatsapp_vm import TAB_QR

_TONES = ("ok", "warn", "error", "info", "neutral")
PREVIEW_ELEMENT_ID = "whatsapp-menu-preview"
TOOLBAR_ELEMENT_ID = "whatsapp-menu-toolbar"


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
    """A select over the menu's step ids. `none_label` adds the «ninguno» choice."""
    items = S.handoff_node_ids if handoffs_only else S.node_ids
    return rx.select.root(
        rx.select.trigger(placeholder="Elige un paso", width="100%"),
        rx.select.content(
            *([rx.select.item(none_label, value=NONE_VALUE)] if none_label else []),
            rx.foreach(items, lambda node_id: rx.select.item(node_id, value=node_id)),
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
                    "Empezar desde el ejemplo de comida rápida",
                    "Bienvenida, atajos, menú del catálogo, resumen del pedido con "
                    "dirección y «hablar con una persona». Se guarda como versión 1.",
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
                    "Crea uno desde el ejemplo de comida rápida y ajústalo a tu negocio, o "
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


def _publish_dialog() -> rx.Component:
    """The one solid action of the tab: saves the changes (if any) and publishes."""
    return rx.alert_dialog.root(
        rx.alert_dialog.trigger(
            rx.button(
                rx.icon("send", size=T.ICON_SM),
                PUBLISH_BUTTON,
                disabled=~S.can_publish,
                loading=S.publishing,
                size="3",
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
            rx.cond(
                S.just_published,
                rx.cond(S.menu.is_paused, _published_but_paused(), _next_step()),
                _actions(),
            ),
            rx.hstack(
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
            ),
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
        scroll_margin_top="1rem",
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
    return rx.hstack(
        choice_card(
            rx.vstack(
                rx.hstack(
                    mono(rx.cond(node.node_id != "", node.node_id, "(sin identificador)")),
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
                    spacing="2",
                    align="center",
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
                _field(
                    "Identificador",
                    rx.input(
                        value=option.option_id,
                        on_change=lambda v: S.set_option_field(index, "option_id", v),
                        width="100%",
                        class_name="q-mono",
                    ),
                    _err(option.errors, "option_id"),
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
                    _node_input("Se guarda como", "field_name", node.field_name, "direccion"),
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
            _node_input(
                "Motivo (para la bandeja)",
                "reason",
                node.reason,
                "customer_request",
            ),
        ),
        rx.fragment(),
    )


def _step_detail() -> rx.Component:
    node = S.selected
    return card(
        rx.vstack(
            rx.grid(
                _node_input("Identificador del paso", "node_id", node.node_id),
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
# The tab
# ======================================================================================


def _editor() -> rx.Component:
    return rx.grid(
        rx.vstack(
            _toolbar(),
            _entry_card(),
            _steps_card(),
            _versions_section(),
            spacing="4",
            width="100%",
            min_width="0",
        ),
        rx.box(
            _preview_card(),
            id=PREVIEW_ELEMENT_ID,
            position=rx.breakpoints(initial="static", lg="sticky"),
            top="1rem",
            scroll_margin_top="1rem",
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

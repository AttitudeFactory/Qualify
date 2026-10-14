"""`/whatsapp` → Chats tab (WA-11, QUA-210): where a person attends the number's
WhatsApp conversations — read, answer, take over from the menu, assign, close.

Plugs into the WA-12 shell (`whatsapp_page.py`): `chats_tab()` is rendered only while the
tab is active, inside a box keyed by the selected number, so its root `on_mount`
(`WhatsAppChatsState.enter`) fires on entry and on every number switch.

Layout (docs/design-system.md §9.1): two panes on desktop — the thread list left, the
conversation right; under 768 px one pane at a time with a back button (`.q-wa-chats` in
`assets/qualify-inbox.css` switches them on `--open`). States are TONES through
`signal_pill` / `tone_badge` / `callout`; content loading is a skeleton, work in progress
(sending) is the button's own `loading`.

Data: `WhatsAppChatsState` over `whatsapp_chats_provider.ChatsGateway` (in process,
`tenant_session`), VMs from `whatsapp_chats_vm.py`. Inbound media is not captured yet
(the backend media route answers 501), so it renders as a neutral chip and nothing here
calls that route.
"""

from __future__ import annotations

import reflex as rx

from .ui import (
    callout,
    card,
    chat_bubble,
    empty_state,
    mono,
    signal_pill,
    skeleton_rows,
    tag,
    tone_badge,
)
from .ui import tokens as T
from .whatsapp_chats_state import UNASSIGNED, WhatsAppChatsState
from .whatsapp_chats_vm import (
    COMPOSE_BUTTONS,
    COMPOSE_IMAGE,
    COMPOSE_MODES,
    FILTER_CLOSED,
    FILTER_OPEN,
    FILTER_UNREAD,
    MAX_BUTTON_TITLE_CHARS,
    AgentVM,
    MessageVM,
    OrderFieldVM,
    OrderLineVM,
    ThreadRowVM,
)

S = WhatsAppChatsState
_TONES = ("ok", "warn", "error", "info", "neutral")

#: Live chats refresh faster than /inbox's 45 s: 15 s, client-side, unmounted with the tab.
_REFRESH_MS = 15_000


# ======================================================================================
# Tone helpers (the VM ships the tone as data; the system needs it at build time)
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


def _heartbeat() -> rx.Component:
    """The 15 s refresh — `react-moment`'s own interval, hidden, gone with the tab."""
    return rx.moment(interval=_REFRESH_MS, on_change=lambda _tick: S.refresh, display="none")


def _agent_chip(initials: rx.Var[str], name: rx.Var[str]) -> rx.Component:
    return rx.cond(
        initials != "",
        rx.tooltip(tag(initials), content=rx.cond(name != "", name, "Asignado")),
        rx.fragment(),
    )


# ======================================================================================
# Thread list
# ======================================================================================


def _thread_row(row: ThreadRowVM) -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.text(
                    row.title,
                    size="2",
                    weight=rx.cond(row.has_unread, "bold", "medium"),
                    trim="both",
                    class_name="q-wa-ellipsis",
                    flex="1",
                    min_width="0",
                ),
                rx.text(row.time_label, size="1", color=T.TEXT_MUTED, white_space="nowrap"),
                width="100%",
                align="center",
                spacing="2",
            ),
            rx.text(
                row.preview,
                size="2",
                color=rx.cond(row.has_unread, T.TEXT_STRONG, T.TEXT_MUTED),
                class_name="q-wa-ellipsis",
                width="100%",
            ),
            rx.hstack(
                _tone_pill(row.window_label, row.window_tone),
                _tone_pill(row.mode_label, row.mode_tone),
                rx.cond(row.is_closed, tag("Cerrado"), rx.fragment()),
                rx.spacer(),
                _agent_chip(row.agent_initials, row.agent_name),
                rx.cond(
                    row.has_unread,
                    rx.badge(
                        row.unread_label,
                        variant="soft",
                        radius="full",
                        size="1",
                        class_name="q-nums",
                        aria_label="Mensajes sin leer",
                    ),
                    rx.fragment(),
                ),
                width="100%",
                align="center",
                spacing="1",
                flex_wrap="wrap",
            ),
            spacing="1",
            width="100%",
        ),
        on_click=S.open_conversation(row.thread_id),
        class_name=rx.cond(
            row.thread_id == S.open_thread_id,
            "q-card q-lift q-wa-row q-wa-row--active",
            "q-card q-lift q-wa-row",
        ),
        role="button",
        tab_index=0,
        aria_label=row.title,
        cursor="pointer",
        padding="0.75rem 0.9rem",
        width="100%",
    )


def _filters() -> rx.Component:
    return rx.segmented_control.root(
        rx.segmented_control.item(S.filter_open_label, value=FILTER_OPEN),
        rx.segmented_control.item(S.filter_closed_label, value=FILTER_CLOSED),
        rx.segmented_control.item(S.filter_unread_label, value=FILTER_UNREAD),
        value=S.filter_key,
        on_change=S.set_filter,
        size="1",
        width="100%",
    )


def _list_body() -> rx.Component:
    return rx.cond(
        S.list_error != "",
        rx.vstack(
            callout(S.list_error, "error"),
            rx.button(
                rx.icon("refresh-cw", size=T.ICON_SM),
                "Reintentar",
                on_click=S.load_list,
                variant="soft",
                size="2",
                **T.tone_scheme("neutral"),
            ),
            width="100%",
            spacing="3",
        ),
        rx.cond(
            S.list_ready,
            rx.cond(
                S.list_empty,
                empty_state(
                    "messages-square",
                    "Aún no hay conversaciones en este número",
                    "Cuando un cliente escriba a este número de WhatsApp, su conversación "
                    "aparece aquí y puedes responderla desde esta pantalla.",
                ),
                rx.cond(
                    S.visible_rows.length() > 0,
                    rx.vstack(
                        rx.foreach(S.visible_rows, _thread_row),
                        spacing="2",
                        width="100%",
                        class_name="q-wa-scroll q-wa-scroll--list",
                    ),
                    rx.text(
                        "No hay conversaciones con este filtro.",
                        size="2",
                        color=T.TEXT_MUTED,
                        padding="1rem 0.25rem",
                    ),
                ),
            ),
            skeleton_rows(6, height="4.75rem", radius=T.RADIUS_CARD),
        ),
    )


def _list_pane() -> rx.Component:
    return rx.vstack(
        _filters(),
        _list_body(),
        spacing="3",
        width="100%",
        class_name="q-wa-chats__list",
    )


# ======================================================================================
# Conversation: header + actions
# ======================================================================================


def _back_button() -> rx.Component:
    return rx.icon_button(
        rx.icon("arrow-left", size=T.ICON_MD),
        on_click=S.back_to_list,
        variant="ghost",
        size="2",
        aria_label="Volver a las conversaciones",
        class_name="q-wa-chats__back",
        **T.tone_scheme("neutral"),
    )


def _agent_item(agent: AgentVM) -> rx.Component:
    return rx.select.item(agent.name, value=agent.user_id)


def _assign_select() -> rx.Component:
    thread = S.open_thread
    return rx.select.root(
        rx.select.trigger(placeholder="Asignar", min_width="10rem"),
        rx.select.content(
            rx.select.item("Sin asignar", value=UNASSIGNED),
            rx.foreach(S.agents, _agent_item),
        ),
        value=rx.cond(thread.agent_id != "", thread.agent_id, UNASSIGNED),
        on_change=S.assign_to,
        disabled=S.acting != "",
        size="2",
    )


def _action_button(
    label: str, icon: str, on_click: rx.event.EventHandler, action: str
) -> rx.Component:
    return rx.button(
        rx.icon(icon, size=T.ICON_SM),
        label,
        on_click=on_click,
        loading=S.acting == action,
        disabled=(S.acting != "") & (S.acting != action),
        variant="soft",
        size="2",
        **T.tone_scheme("neutral"),
    )


def _conversation_header() -> rx.Component:
    thread = S.open_thread
    return rx.vstack(
        rx.hstack(
            _back_button(),
            rx.vstack(
                rx.heading(thread.title, size="4", as_="h2", class_name="q-wa-ellipsis"),
                rx.cond(thread.subtitle != "", mono(thread.subtitle, size="1"), rx.fragment()),
                spacing="0",
                min_width="0",
                flex="1",
            ),
            rx.hstack(
                _tone_pill(thread.window_label, thread.window_tone),
                _tone_pill(thread.mode_label, thread.mode_tone),
                rx.cond(thread.is_closed, tag("Cerrado"), rx.fragment()),
                spacing="1",
                flex_wrap="wrap",
                justify="end",
            ),
            width="100%",
            align="center",
            spacing="3",
        ),
        rx.hstack(
            rx.cond(
                thread.automation_paused,
                _action_button("Devolver al menú", "bot", S.resume_menu, "resume"),
                _action_button("Tomar el control", "hand", S.take_over, "takeover"),
            ),
            _assign_select(),
            rx.spacer(),
            rx.cond(
                thread.is_closed,
                _action_button("Reabrir", "rotate-ccw", S.reopen_conversation, "reopen"),
                _action_button("Cerrar", "archive", S.close_conversation, "close"),
            ),
            width="100%",
            align="center",
            spacing="2",
            flex_wrap="wrap",
        ),
        spacing="3",
        width="100%",
    )


# ======================================================================================
# Conversation: order card
# ======================================================================================


def _order_line(line: OrderLineVM) -> rx.Component:
    return rx.hstack(
        rx.text(line.label, size="2", flex="1", min_width="0"),
        rx.text(line.amount, size="2", class_name="q-nums", white_space="nowrap"),
        width="100%",
        spacing="3",
    )


def _order_field(f: OrderFieldVM) -> rx.Component:
    return rx.hstack(
        rx.text(f.label, size="2", color=T.TEXT_MUTED, min_width="6rem"),
        rx.text(f.value, size="2", flex="1", min_width="0", overflow_wrap="anywhere"),
        width="100%",
        spacing="3",
        align="baseline",
    )


def _order_card() -> rx.Component:
    order = S.order
    return rx.cond(
        order.present,
        card(
            rx.vstack(
                rx.hstack(
                    rx.icon("shopping-bag", size=T.ICON_MD, color=T.tone_color("ok", 11)),
                    rx.text("Pedido confirmado", size="2", weight="bold"),
                    tone_badge(order.items_label, "ok"),
                    rx.spacer(),
                    rx.text(order.confirmed_label, size="1", color=T.TEXT_MUTED),
                    width="100%",
                    align="center",
                    spacing="2",
                    flex_wrap="wrap",
                ),
                rx.vstack(rx.foreach(order.lines, _order_line), spacing="1", width="100%"),
                rx.hstack(
                    rx.text("Total", size="2", weight="bold", flex="1"),
                    rx.text(order.total_label, size="3", weight="bold", class_name="q-nums"),
                    width="100%",
                    align="baseline",
                ),
                rx.cond(
                    order.collected.length() > 0,
                    rx.vstack(rx.foreach(order.collected, _order_field), spacing="1", width="100%"),
                    rx.fragment(),
                ),
                rx.hstack(
                    rx.button(
                        rx.icon("package-check", size=T.ICON_SM),
                        "Pedido listo",
                        on_click=S.send_order_ready,
                        loading=S.sending,
                        disabled=~S.can_compose,
                        variant="soft",
                        size="2",
                    ),
                    rx.text(
                        "Envía al cliente el resumen y el total de su pedido.",
                        size="1",
                        color=T.TEXT_MUTED,
                    ),
                    align="center",
                    spacing="3",
                    flex_wrap="wrap",
                ),
                spacing="3",
                width="100%",
            ),
            padding="1rem",
        ),
        rx.fragment(),
    )


# ======================================================================================
# Conversation: messages
# ======================================================================================


def _tick(m: MessageVM) -> rx.Component:
    muted = T.TEXT_MUTED
    return rx.box(
        rx.match(
            m.tick,
            ("sent", rx.icon("check", size=T.ICON_SM, color=muted)),
            ("delivered", rx.icon("check-check", size=T.ICON_SM, color=muted)),
            ("read", rx.icon("check-check", size=T.ICON_SM, color=T.tone_color("accent", 11))),
            ("queued", rx.icon("clock", size=T.ICON_SM, color=muted)),
            ("failed", rx.icon("circle-alert", size=T.ICON_SM, color=T.tone_color("error", 11))),
            rx.fragment(),
        ),
        title=m.tick_label,
        aria_label=m.tick_label,
        display="inline-flex",
    )


def _bubble_meta(m: MessageVM) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.text(m.time_label, size="1", color=T.TEXT_MUTED, class_name="q-nums"),
            _tick(m),
            spacing="1",
            align="center",
            justify="end",
            width="100%",
        ),
        rx.cond(
            m.error_label != "",
            rx.text(m.error_label, size="1", color=T.tone_color("error", 11)),
            rx.fragment(),
        ),
        spacing="1",
        width="100%",
        padding_top="0.35rem",
    )


def _bubble_body(m: MessageVM) -> rx.Component:
    return rx.cond(
        m.is_media_placeholder,
        rx.hstack(
            rx.icon("paperclip", size=T.ICON_SM, color=T.TEXT_MUTED),
            rx.text(m.text, size="1", color=T.TEXT_MUTED),
            spacing="2",
            align="center",
        ),
        rx.text(m.text, size="2", white_space="pre-wrap", overflow_wrap="anywhere"),
    )


def _message(m: MessageVM) -> rx.Component:
    """Outbound right, inbound left (`.q-wa-msg--*` aligns and turns the kit's tail)."""
    return rx.cond(
        m.is_outbound,
        rx.box(
            chat_bubble(_bubble_body(m), direction="out", meta=_bubble_meta(m)),
            class_name="q-wa-msg q-wa-msg--out",
        ),
        rx.box(
            chat_bubble(_bubble_body(m), direction="in", meta=_bubble_meta(m)),
            class_name="q-wa-msg q-wa-msg--in",
        ),
    )


def _messages() -> rx.Component:
    """`column-reverse` keeps the scroll anchored at the newest message with no JS."""
    return rx.box(
        rx.vstack(
            rx.cond(
                S.has_more,
                rx.center(
                    rx.button(
                        rx.icon("chevrons-up", size=T.ICON_SM),
                        "Cargar anteriores",
                        on_click=S.load_older,
                        loading=S.loading_older,
                        variant="ghost",
                        size="1",
                        **T.tone_scheme("neutral"),
                    ),
                    width="100%",
                ),
                rx.fragment(),
            ),
            rx.cond(
                S.messages.length() > 0,
                rx.foreach(S.messages, _message),
                rx.text(
                    "Aún no hay mensajes en esta conversación.",
                    size="2",
                    color=T.TEXT_MUTED,
                    text_align="center",
                    width="100%",
                ),
            ),
            spacing="2",
            width="100%",
        ),
        class_name="q-wa-scroll q-wa-scroll--messages",
        width="100%",
    )


# ======================================================================================
# Conversation: composer
# ======================================================================================


def _button_input(index: int) -> rx.Component:
    value = {1: S.button_1, 2: S.button_2, 3: S.button_3}[index]
    return rx.hstack(
        rx.input(
            value=value,
            on_change=lambda v: S.set_button(index, v),
            placeholder=f"Botón {index}",
            max_length=MAX_BUTTON_TITLE_CHARS,
            disabled=~S.can_compose,
            size="2",
            flex="1",
        ),
        rx.text(S.button_counts[index - 1], size="1", color=T.TEXT_MUTED, class_name="q-nums"),
        width="100%",
        align="center",
        spacing="2",
    )


def _text_area(placeholder: str) -> rx.Component:
    return rx.text_area(
        value=S.draft_text,
        on_change=S.set_draft_text,
        placeholder=placeholder,
        disabled=~S.can_compose,
        rows="3",
        resize="vertical",
        width="100%",
    )


def _compose_fields() -> rx.Component:
    return rx.match(
        S.compose_mode,
        (
            COMPOSE_BUTTONS,
            rx.vstack(
                _text_area("Texto que acompaña a los botones"),
                rx.grid(
                    _button_input(1),
                    _button_input(2),
                    _button_input(3),
                    columns=rx.breakpoints(initial="1", sm="3"),
                    spacing="2",
                    width="100%",
                ),
                spacing="2",
                width="100%",
            ),
        ),
        (
            COMPOSE_IMAGE,
            rx.vstack(
                rx.input(
                    value=S.image_url,
                    on_change=S.set_image_url,
                    placeholder="https://… enlace público de la imagen",
                    type="url",
                    disabled=~S.can_compose,
                    width="100%",
                ),
                rx.input(
                    value=S.image_caption,
                    on_change=S.set_image_caption,
                    placeholder="Pie de foto (opcional)",
                    disabled=~S.can_compose,
                    width="100%",
                ),
                spacing="2",
                width="100%",
            ),
        ),
        _text_area("Escribe una respuesta…"),
    )


def _composer() -> rx.Component:
    return rx.vstack(
        rx.cond(S.window_closed_notice != "", callout(S.window_closed_notice, "warn")),
        rx.segmented_control.root(
            *[rx.segmented_control.item(label, value=key) for key, label in COMPOSE_MODES],
            value=S.compose_mode,
            on_change=S.set_compose_mode,
            size="1",
        ),
        _compose_fields(),
        rx.hstack(
            rx.cond(
                S.compose_hint != "",
                rx.text(S.compose_hint, size="1", color=T.tone_color("warn", 11)),
                rx.text(
                    "Al responder, el menú automático se pausa en esta conversación.",
                    size="1",
                    color=T.TEXT_MUTED,
                ),
            ),
            rx.spacer(),
            rx.button(
                rx.icon("send", size=T.ICON_SM),
                "Enviar",
                on_click=S.send_message,
                loading=S.sending,
                disabled=~S.can_compose | (S.compose_error != ""),
                size="2",
            ),
            width="100%",
            align="center",
            spacing="3",
        ),
        spacing="2",
        width="100%",
        padding_top="0.5rem",
        class_name="q-wa-composer",
    )


# ======================================================================================
# Panes
# ======================================================================================


def _conversation() -> rx.Component:
    return card(
        rx.vstack(
            _conversation_header(),
            _banner(S.banner, S.banner_tone),
            rx.cond(
                S.conv_error != "",
                rx.vstack(
                    callout(S.conv_error, "error"),
                    rx.button(
                        rx.icon("refresh-cw", size=T.ICON_SM),
                        "Reintentar",
                        on_click=S.load_conversation,
                        variant="soft",
                        size="2",
                        **T.tone_scheme("neutral"),
                    ),
                    width="100%",
                    spacing="3",
                ),
                rx.cond(
                    S.conv_ready,
                    rx.vstack(_order_card(), _messages(), spacing="3", width="100%"),
                    skeleton_rows(4, height="3rem"),
                ),
            ),
            _composer(),
            spacing="3",
            width="100%",
        ),
        padding="1rem",
    )


def _conversation_pane() -> rx.Component:
    return rx.box(
        rx.cond(
            S.has_open_thread,
            _conversation(),
            rx.vstack(
                _banner(S.banner, S.banner_tone),
                empty_state(
                    "message-square-text",
                    "Elige una conversación",
                    "Ábrela para leerla, responder, tomar el control del menú automático o "
                    "marcar un pedido como listo.",
                ),
                width="100%",
            ),
        ),
        class_name="q-wa-chats__conv",
        width="100%",
    )


def chats_tab() -> rx.Component:
    return rx.box(
        _heartbeat(),
        rx.box(
            _list_pane(),
            _conversation_pane(),
            class_name=rx.cond(S.has_open_thread, "q-wa-chats q-wa-chats--open", "q-wa-chats"),
        ),
        on_mount=S.enter,
        width="100%",
    )

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
`tenant_session`), VMs from `whatsapp_chats_vm.py`. Inbound media (0061) renders as a
control inside the bubble and is fetched only on click (`request_media`): an image shows
a thumbnail and opens in the lightbox, an audio gets a player, a video / document opens
in a new tab. Failures read by tone (`neutral` gone, `warn` retry); a message whose
bytes were never captured keeps the neutral chip.

**Expired chat (m-24848535).** Once 24 hours have passed, the composer gives way to the
notice and «Enviar un mensaje aprobado», which opens a `drawer` (full screen on a phone)
listing only what this person may receive: follow-ups after a chat, promotions only with
their explicit acceptance — otherwise «Para enviarle promociones, esta persona tiene que
aceptar recibirlas.» and, only when an approved message to ask exists, «Pedirle que
acepte». Picking one shows how it arrives and the values it needs; it leaves only with the
owner's «Enviar» (N13). Every target is at least 2.75 rem (44 px) tall (N12).
"""

from __future__ import annotations

import reflex as rx

from .r2_media import BACKEND_BASE
from .ui import (
    OrbitItem,
    callout,
    card,
    chat_bubble,
    choice_card,
    choice_card_check,
    drawer,
    dropzone,
    empty_state,
    media_thumb,
    mono,
    orbit_menu,
    signal_pill,
    skeleton_rows,
    tag,
    tone_badge,
)
from .ui import tokens as T
from .ui.flow_history import flow_sync
from .ui.steps import step_progress
from .whatsapp_chats_state import UNASSIGNED, WhatsAppChatsState
from .whatsapp_chats_vm import (
    ADD_PHOTO_LABEL,
    ADD_PHOTOS_LABEL,
    ADD_PRODUCT_LABEL,
    ALL_WITHOUT_PHOTO,
    ASK_CONSENT_LABEL,
    CAPTION_LABEL,
    CAPTION_SHORTENED,
    COMPOSE_BUTTONS,
    COMPOSE_MODES,
    CREATE_AGAIN_LABEL,
    CREATE_APPROVED_LABEL,
    CREATE_APPROVED_ROUTE,
    CREATE_PIECE_LABEL,
    CREATE_PIECE_ROUTE,
    DIRECTIONS_COMPLETE,
    DIRECTIONS_EMPTY,
    DIRECTIONS_NO_POINT,
    DIRECTIONS_PUT_ON_MAP,
    DRAFTS_ROUTE,
    FILTER_CLOSED,
    FILTER_OPEN,
    FILTER_PAYMENT,
    FILTER_UNREAD,
    MAX_BUTTON_TITLE_CHARS,
    MAX_PHOTO_BYTES,
    MEDIA_AUDIO,
    MEDIA_IMAGE,
    MEDIA_SOURCE_CARDS,
    MEDIA_VIDEO,
    MENU_EMPTY,
    MENU_NOT_ACTIVE,
    MENU_RESUMES_NOTE,
    MENU_SETUP_LABEL,
    MENU_SETUP_ROUTE,
    NEW_PRODUCT_ROUTE,
    NO_APPROVED_EMPTY,
    NO_FOLLOWUPS,
    NO_PERMISSION_NOTICE,
    NO_PHOTO_NOTICE,
    NO_PHOTO_PILL,
    NO_PIECES_EMPTY,
    NO_PRODUCTS_EMPTY,
    NO_UNAPPROVED_EMPTY,
    OFFER_BADGE,
    OFFER_CHANGE,
    OFFER_EMPTY,
    OFFER_GO,
    OFFER_GONE,
    PAYMENT_CONFIRM_HINT,
    PAYMENT_CONFIRM_NOT_YET,
    PAYMENT_CONFIRM_SEND,
    PAYMENT_MARK_SILENT,
    PAYMENT_MESSAGE_LABEL,
    PAYMENT_NOT_FOUND_BUTTON,
    PAYMENT_RECEIVED_BUTTON,
    PAYMENTS_ADD,
    PAYMENTS_CHANGE,
    PAYMENTS_EMPTY_TEXT,
    PAYMENTS_EMPTY_TITLE,
    PHOTO_CHANGE_LABEL,
    PHOTO_HELP,
    PHOTO_PICK_LABEL,
    PHOTO_TYPES,
    PICK_BACK,
    PICK_BACK_TO_CHAT,
    PICK_DIRECTIONS,
    PICK_FLOW,
    PICK_MEDIA,
    PICK_MENU,
    PICK_MENU_LABEL,
    PICK_OFFER,
    PICK_PAYMENTS,
    PICK_PHOTO,
    PICK_PIECES,
    PICK_PRODUCTS,
    PICK_SEASONAL,
    PICK_SOURCE_CARDS,
    PIECE_TABS,
    PIECES_APPROVED,
    PRODUCTS_NO_MATCH,
    PRODUCTS_ROUTE,
    PRODUCTS_SEARCH,
    PRODUCTS_SHOW_ALL,
    PROMOTIONS_NEED_CONSENT,
    RETRY_LABEL,
    SEASONAL_CAPTION_LABEL,
    SEASONAL_EARLIER,
    SEASONAL_LINE,
    SEASONAL_STICKER_ALONE,
    SEASONAL_STICKERS_TAB,
    SEASONAL_VIDEOS_TAB,
    SEE_UNAPPROVED_LABEL,
    SEND_APPROVED_DESCRIPTION,
    SEND_APPROVED_LABEL,
    TEMPLATE_BACK_LABEL,
    TEMPLATE_FIELDS_LABEL,
    TEMPLATE_PREVIEW_LABEL,
    TEXT_ONLY_LABEL,
    UNAPPROVED_WARNING,
    VIDEO_BADGE,
    VIDEO_HEAVY_PILL,
    VIDEO_TOO_LARGE,
    VIEW_ON_MAP,
    WINDOW_CLOSED_NOTICE,
    AgentVM,
    MessageVM,
    OrderFieldVM,
    OrderLineVM,
    PaymentCardVM,
    PieceCardVM,
    ProductCardVM,
    SeasonalPickVM,
    TemplateChoiceVM,
    TemplateFieldVM,
    ThreadRowVM,
)
from .whatsapp_state import WhatsAppState
from .whatsapp_vm import TAB_QR

S = WhatsAppChatsState
_TONES = ("ok", "warn", "error", "info", "neutral")

#: Live chats refresh faster than /inbox's 45 s: 15 s, client-side, unmounted with the tab.
_REFRESH_MS = 15_000
#: N12: every tap target on this tab is at least 44 px tall.
_TAP_MIN = "2.75rem"


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
                # m-24955648: the payment pill FIRST — «Pago por revisar» (warn) asks for
                # attention, and at 375 px a third pill drops to a second line
                rx.cond(
                    row.payment_label != "",
                    _tone_pill(row.payment_label, row.payment_tone),
                    rx.fragment(),
                ),
                _tone_pill(row.window_label, row.window_tone),
                _tone_pill(row.mode_label, row.mode_tone),
                rx.cond(row.is_closed, tag("Cerrado"), rx.fragment()),
                rx.spacer(),
                _agent_chip(row.agent_initials, row.agent_name),
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


def _filter_options() -> list[tuple[str, rx.Var[str]]]:
    return [
        (FILTER_OPEN, S.filter_open_label),
        (FILTER_CLOSED, S.filter_closed_label),
        (FILTER_UNREAD, S.filter_unread_label),
        (FILTER_PAYMENT, S.filter_payment_label),
    ]


def _filter_button(key: str, label: rx.Var[str]) -> rx.Component:
    """One filter as a button for the phone grid; `aria-pressed` says which one is on."""
    active = S.filter_key == key
    return rx.button(
        label,
        on_click=S.set_filter(key),
        variant=rx.cond(active, "soft", "ghost"),
        size="2",
        width="100%",
        height="auto",
        min_height="44px",
        white_space="normal",
        padding_y="0.5rem",
        custom_attrs={"aria-pressed": rx.cond(active, "true", "false")},
        **T.tone_scheme("neutral"),
    )


def _filters() -> rx.Component:
    """The four filters in the page's 2 x 2 arrangement (as `_choice_strip` in
    whatsapp_page): the list column is at most 340 px wide at every size, so a
    four-item `segmented_control` would clip «Pago por revisar» on a phone and a desk."""
    return rx.grid(
        *[_filter_button(key, label) for key, label in _filter_options()],
        columns="2",
        spacing="2",
        width="100%",
        role="group",
        aria_label="Filtrar chats",
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
                    # N8 (m-24842961): a QR code is how customers start writing.
                    action=rx.button(
                        rx.icon("qr-code", size=16),
                        "Crear un código QR",
                        on_click=WhatsAppState.select_tab(TAB_QR),
                        variant="soft",
                        size="3",
                    ),
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
                        S.filter_empty,
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
    """Phone only (the list and the conversation share one pane there). N7: the
    button names where it goes — «‹ Chats», never a bare arrow."""
    return rx.button(
        rx.icon("chevron-left", size=T.ICON_MD),
        "Chats",
        on_click=S.back_to_list,
        variant="ghost",
        size="2",
        min_height="44px",
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
            # Name, then number + state pills on one wrapping line: at 375 px the pills
            # drop below the name instead of overlapping it.
            rx.vstack(
                rx.heading(
                    thread.title, size="4", as_="h2", class_name="q-wa-ellipsis", width="100%"
                ),
                rx.hstack(
                    rx.cond(thread.subtitle != "", mono(thread.subtitle, size="1"), rx.fragment()),
                    rx.cond(
                        S.payment.label != "",
                        _tone_pill(S.payment.label, S.payment.tone),
                        rx.fragment(),
                    ),
                    _tone_pill(thread.window_label, thread.window_tone),
                    _tone_pill(thread.mode_label, thread.mode_tone),
                    rx.cond(thread.is_closed, tag("Cerrado"), rx.fragment()),
                    spacing="2",
                    flex_wrap="wrap",
                    align="center",
                ),
                spacing="1",
                min_width="0",
                flex="1",
            ),
            width="100%",
            align="start",
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


def _payment_block() -> rx.Component:
    """m-24955648 (spec §4): «Paga con: …», then «Pago recibido» (the sheet shows the
    exact message before anything goes out) and «No lo encuentro» (nothing is sent: the
    text goes into the composer)."""
    pay = S.payment
    return rx.cond(
        pay.present,
        rx.vstack(
            rx.hstack(
                rx.icon("wallet", size=T.ICON_SM, color=T.TEXT_MUTED),
                rx.text(pay.method_line, size="2", weight="medium"),
                rx.cond(pay.label != "", _tone_pill(pay.label, pay.tone), rx.fragment()),
                spacing="2",
                align="center",
                flex_wrap="wrap",
            ),
            rx.cond(
                pay.can_confirm,
                rx.hstack(
                    rx.button(
                        rx.icon("badge-check", size=T.ICON_SM),
                        PAYMENT_RECEIVED_BUTTON,
                        on_click=S.open_payment_confirm,
                        size="3",
                        min_height=_TAP_MIN,
                    ),
                    rx.button(
                        PAYMENT_NOT_FOUND_BUTTON,
                        on_click=S.payment_not_found,
                        disabled=~S.can_compose,
                        variant="soft",
                        size="3",
                        min_height=_TAP_MIN,
                        **T.tone_scheme("neutral"),
                    ),
                    spacing="2",
                    flex_wrap="wrap",
                ),
                rx.text(pay.confirmed_line, size="2", color=T.tone_color("ok", 11)),
            ),
            spacing="2",
            width="100%",
            align_items="start",
            padding_top="0.5rem",
            border_top=T.BORDER,
        ),
        rx.fragment(),
    )


def _payment_confirm_dialog() -> rx.Component:
    """«¿Ya te llegó el pago de María?»: the message, editable, and the owner's tap. With
    the 24 h window closed it cannot go out: «Marcar pagado sin avisar» instead."""
    return rx.dialog.root(
        rx.dialog.content(
            rx.vstack(
                rx.dialog.title(S.pay_confirm_title, margin="0"),
                rx.text(PAYMENT_CONFIRM_HINT, size="2", color=T.TEXT_MUTED),
                rx.cond(
                    S.pay_window_closed,
                    rx.fragment(),
                    rx.vstack(
                        rx.el.label(
                            rx.text(PAYMENT_MESSAGE_LABEL, size="2", weight="medium"),
                            html_for="q-pay-confirm-message",
                        ),
                        rx.text_area(
                            id="q-pay-confirm-message",
                            value=S.pay_message,
                            on_change=S.set_pay_message,
                            rows="3",
                            size="3",
                            width="100%",
                        ),
                        spacing="1",
                        width="100%",
                    ),
                ),
                rx.cond(
                    S.pay_error != "",
                    rx.cond(
                        S.pay_window_closed,
                        callout(S.pay_error, "warn"),
                        callout(S.pay_error, "error"),
                    ),
                ),
                rx.flex(
                    rx.button(
                        PAYMENT_CONFIRM_NOT_YET,
                        on_click=S.set_payment_confirm_open(False),
                        variant="soft",
                        size="3",
                        min_height=_TAP_MIN,
                        disabled=S.pay_busy,
                        **T.tone_scheme("neutral"),
                    ),
                    rx.cond(
                        S.pay_window_closed,
                        rx.button(
                            PAYMENT_MARK_SILENT,
                            on_click=S.mark_paid_silent,
                            loading=S.pay_busy,
                            size="3",
                            min_height=_TAP_MIN,
                        ),
                        rx.button(
                            rx.icon("send", size=T.ICON_SM),
                            PAYMENT_CONFIRM_SEND,
                            on_click=S.confirm_payment,
                            loading=S.pay_busy,
                            size="3",
                            min_height=_TAP_MIN,
                        ),
                    ),
                    spacing="2",
                    justify="end",
                    wrap="wrap",
                    width="100%",
                ),
                spacing="3",
                width="100%",
            ),
            max_width="28rem",
        ),
        open=S.pay_confirm_open,
        on_open_change=S.set_payment_confirm_open,
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
                _payment_block(),
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
        rx.cond(S.payment.present, card(_payment_block(), padding="1rem"), rx.fragment()),
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


def _media_icon(m: MessageVM) -> rx.Component:
    return rx.cond(
        m.media_notice_tone == "warn",
        rx.icon("refresh-cw", size=T.ICON_SM),
        rx.match(
            m.media_control,
            (MEDIA_IMAGE, rx.icon("image", size=T.ICON_SM)),
            (MEDIA_AUDIO, rx.icon("play", size=T.ICON_SM)),
            (MEDIA_VIDEO, rx.icon("video", size=T.ICON_SM)),
            rx.icon("download", size=T.ICON_SM),
        ),
    )


def _media_link(m: MessageVM, label: rx.Var[str] | str, icon: str) -> rx.Component:
    """A video / document already resolved: a plain link, so a second open needs no
    round trip (and no popup blocker sits between the click and the tab)."""
    return rx.link(
        rx.hstack(
            rx.icon(icon, size=T.ICON_SM),
            rx.text(label, size="2"),
            spacing="2",
            align="center",
        ),
        href=m.media_src,
        is_external=True,
        rel="noopener noreferrer",
    )


def _media_view(m: MessageVM) -> rx.Component:
    """What a fresh URL renders as, by control."""
    return rx.match(
        m.media_control,
        (
            MEDIA_IMAGE,
            rx.box(
                media_thumb(
                    m.media_src,
                    width="min(15rem, 60vw)",
                    height="11rem",
                    alt="Imagen recibida por WhatsApp",
                    custom_attrs={"referrerpolicy": "no-referrer"},
                ),
                on_click=S.open_lightbox(m.message_id),
                role="button",
                tab_index=0,
                aria_label="Ampliar imagen",
                cursor="zoom-in",
            ),
        ),
        (
            MEDIA_AUDIO,
            rx.el.audio(
                src=m.media_src,
                controls=True,
                preload="metadata",
                aria_label="Audio recibido por WhatsApp",
                # The bubble caps its own width; the player must shrink inside it.
                style={"width": "17rem", "max_width": "100%", "display": "block"},
            ),
        ),
        (MEDIA_VIDEO, _media_link(m, "Abrir video", "external-link")),
        _media_link(m, m.media_action, "download"),
    )


def _media_notice(m: MessageVM) -> rx.Component:
    color = rx.cond(m.media_notice_tone == "warn", T.tone_color("warn", 11), T.TEXT_MUTED)
    return rx.hstack(
        rx.cond(
            m.media_notice_tone == "warn",
            rx.icon("triangle-alert", size=T.ICON_SM, color=T.tone_color("warn", 11)),
            rx.icon("circle-slash", size=T.ICON_SM, color=T.TEXT_MUTED),
        ),
        rx.text(m.media_notice, size="1", color=color),
        spacing="2",
        align="center",
    )


def _media_block(m: MessageVM) -> rx.Component:
    """Inbound media: the button until clicked, then the view (or the failure)."""
    return rx.vstack(
        rx.cond(m.media_src != "", _media_view(m), rx.fragment()),
        rx.cond(m.media_notice != "", _media_notice(m), rx.fragment()),
        rx.cond(
            m.media_can_request,
            rx.button(
                _media_icon(m),
                m.media_action,
                on_click=S.request_media(m.message_id),
                loading=m.media_loading,
                variant="soft",
                size="1",
                **T.tone_scheme("neutral"),
            ),
            rx.fragment(),
        ),
        spacing="2",
        align_items="start",
    )


def _bubble_body(m: MessageVM) -> rx.Component:
    text = rx.cond(
        m.is_location,
        # m-24945889: a pin (sent with «Cómo llegar» or shared by the customer)
        rx.vstack(
            rx.hstack(
                rx.icon("map-pin", size=T.ICON_SM, aria_hidden="true"),
                rx.text(m.text, size="2", overflow_wrap="anywhere"),
                spacing="2",
                align="center",
            ),
            # Only with stored coordinates; PENDING backend: `MessageRecord.latitude/
            # longitude` do not exist yet, so today this link never shows.
            rx.cond(
                m.location_href != "",
                rx.link(
                    VIEW_ON_MAP,
                    href=m.location_href,
                    is_external=True,
                    size="2",
                ),
            ),
            spacing="1",
            align_items="start",
        ),
        rx.cond(
            m.is_media_placeholder,
            rx.hstack(
                rx.icon("paperclip", size=T.ICON_SM, color=T.TEXT_MUTED),
                rx.text(m.text, size="1", color=T.TEXT_MUTED),
                spacing="2",
                align="center",
            ),
            rx.cond(
                m.text != "",
                rx.text(m.text, size="2", white_space="pre-wrap", overflow_wrap="anywhere"),
                rx.fragment(),
            ),
        ),
    )
    return rx.cond(
        m.media_control != "",
        rx.vstack(_media_block(m), text, spacing="2", align_items="start"),
        text,
    )


def _lightbox() -> rx.Component:
    """An inbound image at full size. The URL is the state's (looked up by message id),
    and it is a short-lived public-media link — the same one the HTTP route redirects to."""
    return rx.dialog.root(
        rx.dialog.content(
            rx.vstack(
                rx.hstack(
                    rx.dialog.title("Imagen recibida", size="3", margin="0"),
                    rx.spacer(),
                    rx.link(
                        rx.hstack(
                            rx.icon("external-link", size=T.ICON_SM),
                            rx.text("Abrir original", size="2"),
                            spacing="1",
                            align="center",
                        ),
                        href=S.lightbox_url,
                        is_external=True,
                        rel="noopener noreferrer",
                    ),
                    rx.dialog.close(
                        rx.icon_button(
                            rx.icon("x", size=T.ICON_MD),
                            variant="ghost",
                            size="2",
                            aria_label="Cerrar",
                            **T.tone_scheme("neutral"),
                        ),
                    ),
                    width="100%",
                    align="center",
                    spacing="3",
                ),
                rx.image(
                    src=S.lightbox_url,
                    alt="Imagen recibida por WhatsApp",
                    width="100%",
                    max_height="75vh",
                    object_fit="contain",
                    border_radius=T.RADIUS_CONTROL,
                    custom_attrs={"referrerpolicy": "no-referrer"},
                ),
                spacing="3",
                width="100%",
            ),
            max_width="min(56rem, 94vw)",
        ),
        open=S.lightbox_url != "",
        on_open_change=S.set_lightbox_open,
    )


def _ad_origin(m: MessageVM) -> rx.Component:
    return rx.cond(
        m.ad_origin_label != "",
        rx.hstack(
            rx.icon("megaphone", size=T.ICON_SM, color=T.TEXT_FAINT, flex_shrink="0"),
            rx.text(m.ad_origin_label, size="1", color=T.TEXT_MUTED, overflow_wrap="anywhere"),
            rx.link(
                "Ver anuncio",
                href=m.ad_origin_href,
                min_height="44px",
                display="inline-flex",
                align_items="center",
                size="1",
            ),
            spacing="1",
            align="start",
            max_width="100%",
            flex_wrap="wrap",
        ),
        rx.fragment(),
    )


def _message(m: MessageVM) -> rx.Component:
    """Outbound right, inbound left (`.q-wa-msg--*` aligns and turns the kit's tail);
    `.q-wa-msg--glass` is WhatsApp's Liquid Glass look and the entrance — keyed by message
    id, so only a new bubble plays it."""
    return rx.cond(
        m.is_outbound,
        rx.box(
            chat_bubble(_bubble_body(m), direction="out", meta=_bubble_meta(m)),
            class_name="q-wa-msg q-wa-msg--out q-wa-msg--glass",
            key=m.message_id,
        ),
        rx.box(
            _ad_origin(m),
            chat_bubble(_bubble_body(m), direction="in", meta=_bubble_meta(m)),
            class_name="q-wa-msg q-wa-msg--in q-wa-msg--glass",
            key=m.message_id,
            flex_direction="column",
            align_items="start",
            gap="var(--space-1)",
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
        class_name="q-wa-scroll q-wa-scroll--messages q-wa-scroll--glass",
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
        _text_area("Escribe una respuesta…"),
    )


def _expired_composer() -> rx.Component:
    """m-24848535: the expired chat's way out, in place of a switched-off composer."""
    return rx.vstack(
        callout(S.window_closed_notice, "warn"),
        rx.button(
            rx.icon("message-square-text", size=T.ICON_SM),
            SEND_APPROVED_LABEL,
            on_click=S.open_templates,
            size="3",
            min_height=_TAP_MIN,
            width=rx.breakpoints(initial="100%", sm="auto"),
        ),
        spacing="2",
        width="100%",
        padding_top="0.5rem",
        class_name="q-wa-composer",
    )


def _template_choice(choice: TemplateChoiceVM) -> rx.Component:
    selected = S.tpl_selected == choice.template_id
    return choice_card(
        rx.vstack(
            rx.hstack(
                rx.text(choice.title, weight="medium", size="2"),
                rx.spacer(),
                _tone_pill(choice.kind_label, choice.kind_tone),
                rx.cond(selected, choice_card_check()),
                width="100%",
                align="center",
                spacing="2",
            ),
            rx.text(
                choice.preview,
                size="2",
                color=T.TEXT_MUTED,
                white_space="pre-wrap",
                text_align="left",
            ),
            spacing="1",
            width="100%",
            align="start",
        ),
        selected=selected,
        on_select=S.choose_template(choice.template_id),
        padding="0.75rem 1rem",
        width="100%",
        min_height=_TAP_MIN,
    )


def _template_field(field: TemplateFieldVM) -> rx.Component:
    return rx.vstack(
        rx.el.label(
            rx.text(field.label, size="2", weight="medium"),
            html_for="tpl-field-" + field.id,
        ),
        rx.input(
            id="tpl-field-" + field.id,
            aria_label=field.label,
            value=field.value,
            on_change=lambda value: S.set_template_value(field.id, value),
            width="100%",
            size="3",
        ),
        rx.cond(
            field.example != "",
            rx.text(field.example, size="1", color=T.TEXT_MUTED),
        ),
        spacing="1",
        width="100%",
    )


def _promotions_notice() -> rx.Component:
    return rx.cond(
        S.tpl_promotions_blocked,
        rx.vstack(
            callout(PROMOTIONS_NEED_CONSENT, "info"),
            rx.cond(
                S.tpl_consent_id != "",
                rx.button(
                    rx.icon("hand-heart", size=T.ICON_SM),
                    ASK_CONSENT_LABEL,
                    on_click=S.ask_consent,
                    variant="soft",
                    size="3",
                    min_height=_TAP_MIN,
                    width=rx.breakpoints(initial="100%", sm="auto"),
                ),
            ),
            spacing="2",
            width="100%",
        ),
    )


def _no_followups() -> rx.Component:
    return rx.cond(
        ~S.tpl_has_followups & ~S.tpl_no_permission,
        rx.vstack(
            callout(NO_FOLLOWUPS, "neutral"),
            rx.link(
                rx.button(
                    rx.icon("plus", size=T.ICON_SM),
                    CREATE_APPROVED_LABEL,
                    variant="soft",
                    size="3",
                    min_height=_TAP_MIN,
                    width="100%",
                ),
                href=CREATE_APPROVED_ROUTE,
                width=rx.breakpoints(initial="100%", sm="auto"),
            ),
            spacing="2",
            width="100%",
        ),
    )


def _step_label(text: str) -> rx.Component:
    return rx.text(text, size="2", weight="bold", color=T.TEXT_MUTED)


def _template_picked() -> rx.Component:
    """Step 2 of 2: the values and «Así le llega»; «Atrás» and «Enviar» are in the foot."""
    return rx.vstack(
        rx.vstack(
            rx.cond(
                S.tpl_fields.length() > 0,
                rx.vstack(
                    rx.text(TEMPLATE_FIELDS_LABEL, size="2", weight="bold"),
                    rx.foreach(S.tpl_fields, _template_field),
                    spacing="2",
                    width="100%",
                ),
            ),
            rx.text(TEMPLATE_PREVIEW_LABEL, size="2", weight="bold"),
            chat_bubble(
                rx.text(S.tpl_preview, size="2", white_space="pre-wrap"),
                direction="out",
            ),
            spacing="2",
            width="100%",
        ),
        spacing="3",
        width="100%",
    )


def _template_list() -> rx.Component:
    """Step 1 of 2: the notices and the approved messages; picking one moves on."""
    return rx.vstack(
        rx.cond(S.tpl_no_permission, callout(NO_PERMISSION_NOTICE, "warn")),
        _promotions_notice(),
        _no_followups(),
        rx.foreach(S.tpl_choices, _template_choice),
        spacing="3",
        width="100%",
    )


def _templates_body() -> rx.Component:
    return rx.cond(
        S.tpl_loading & (S.tpl_choices.length() == 0),
        skeleton_rows(3, height="4rem"),
        rx.cond(
            (S.tpl_selected != "") & S.tpl_reviewing,
            _template_picked(),
            _template_list(),
        ),
    )


def _templates_footer() -> rx.Component:
    return rx.vstack(
        rx.cond(S.tpl_error != "", callout(S.tpl_error, "error")),
        rx.cond(S.tpl_hint != "", rx.text(S.tpl_hint, size="1", color=T.TEXT_MUTED)),
        rx.cond(
            (S.tpl_selected != "") & S.tpl_reviewing,
            rx.hstack(
                rx.button(
                    rx.icon("arrow-left", size=T.ICON_SM),
                    TEMPLATE_BACK_LABEL,
                    on_click=S.back_to_templates,
                    variant="soft",
                    size="3",
                    min_height=_TAP_MIN,
                    **T.tone_scheme("neutral"),
                ),
                rx.spacer(),
                rx.button(
                    rx.icon("send", size=T.ICON_SM),
                    "Enviar",
                    on_click=S.send_template,
                    loading=S.tpl_sending,
                    disabled=~S.can_send_template,
                    size="3",
                    min_height=_TAP_MIN,
                ),
                width="100%",
                align="center",
            ),
            rx.dialog.close(
                rx.button(
                    rx.cond(S.tpl_no_permission, "Cerrar", "Cancelar"),
                    variant="soft",
                    size="3",
                    min_height=_TAP_MIN,
                    width="100%",
                    **T.tone_scheme("neutral"),
                ),
            ),
        ),
        spacing="2",
        width="100%",
    )


def _templates_drawer() -> rx.Component:
    return drawer(
        flow_sync(
            "mensaje-chat",
            rx.cond(S.tpl_reviewing, 2, 1),
            ready=S.flow_ready & ~S.tpl_loading,
            objeto=S.tpl_selected,
        ),
        _templates_body(),
        open=S.tpl_open,
        on_open_change=S.set_templates_open,
        title=SEND_APPROVED_LABEL,
        step=rx.vstack(
            step_progress(rx.cond(S.tpl_reviewing, 2, 1), 2),
            rx.text(
                rx.cond(S.tpl_reviewing, "Revisa el mensaje", "Elige el mensaje"),
                size="2",
                weight="medium",
            ),
            spacing="1",
            width="100%",
        ),
        description=SEND_APPROVED_DESCRIPTION,
        footer=_templates_footer(),
        icon="message-square-text",
    )


# ======================================================================================
# The send panel (m-24945888; the «+» since m-24955785, docs/ux-whatsapp-menu-orbit.md)
# ======================================================================================

_PHOTO_UPLOAD_ID = "wa_chat_photo"
_PHOTO_ACCEPT = {kind: list(exts) for kind, exts in PHOTO_TYPES.items()}
_CAPTION_ID = "wa-pick-caption"
_SEARCH_ID = "wa-pick-search"
_CAPTION_COUNT_ID = "wa-pick-caption-count"


def _link_button(label: str, icon: str, href: str | rx.Var[str]) -> rx.Component:
    return rx.link(
        rx.button(
            rx.icon(icon, size=T.ICON_SM),
            label,
            variant="soft",
            size="3",
            min_height=_TAP_MIN,
            width="100%",
        ),
        href=href,
        width=rx.breakpoints(initial="100%", sm="auto"),
    )


def _pick_menu_button() -> rx.Component:
    """The composer's «+» (m-24955785, `ui.orbit_menu`): each option opens the panel at
    its own first step; choosing never sends. Drawn only inside `_live_composer`, so
    outside the 24 hours (the whole composer replaced) it does not exist."""
    return orbit_menu(
        PICK_MENU_LABEL,
        [
            OrbitItem(key=key, icon=icon, text=text, on_select=S.open_pick(key))
            for key, icon, text in PICK_SOURCE_CARDS
        ],
        disabled=~S.can_compose | S.sending,
    )


def _pick_grid_skeleton() -> rx.Component:
    return rx.grid(
        *[skeleton_rows(1, height="10rem", radius=T.RADIUS_CARD) for _ in range(4)],
        columns="2",
        spacing="2",
        width="100%",
    )


def _pick_load_error() -> rx.Component:
    return rx.vstack(
        callout(S.pick_error, "error"),
        rx.button(
            rx.icon("refresh-cw", size=T.ICON_SM),
            RETRY_LABEL,
            on_click=S.retry_pick_list,
            variant="soft",
            size="3",
            min_height=_TAP_MIN,
            **T.tone_scheme("neutral"),
        ),
        spacing="2",
        width="100%",
    )


def _pick_list(body: rx.Component) -> rx.Component:
    """Loading (skeleton) → error («Reintentar») → the step's body."""
    return rx.cond(
        S.pick_loading,
        _pick_grid_skeleton(),
        rx.cond(S.pick_error != "", _pick_load_error(), body),
    )


def _product_src(card: ProductCardVM) -> rx.Var:
    """A public URL as it comes, else the upload-store key through `rx.get_upload_url`."""
    return rx.cond(
        card.thumb_url != "",
        card.thumb_url,
        rx.cond(card.thumb_key != "", rx.get_upload_url(card.thumb_key), ""),
    )


def _product_card(card: ProductCardVM) -> rx.Component:
    return choice_card(
        rx.vstack(
            media_thumb(
                _product_src(card),
                size=None,
                width="100%",
                height="7.5rem",
                alt=card.alt,
                icon="package",
                has=card.has_photo,
            ),
            rx.text(card.name, weight="medium", size="2", text_align="left"),
            rx.hstack(
                rx.text(card.price_label, size="2", color=T.TEXT_MUTED, class_name="q-nums"),
                rx.cond(~card.has_photo, signal_pill(NO_PHOTO_PILL, "neutral")),
                spacing="2",
                align="center",
                wrap="wrap",
            ),
            spacing="1",
            align="start",
            width="100%",
        ),
        selected=S.pick_selected == card.id,
        on_select=S.choose_product(card.id),
        padding="0.5rem",
        width="100%",
        min_height=_TAP_MIN,
    )


def _pick_products() -> rx.Component:
    title, line = NO_PRODUCTS_EMPTY
    grid = rx.vstack(
        rx.cond(
            S.pick_all_without_photo,
            rx.vstack(
                callout(ALL_WITHOUT_PHOTO, "info"),
                _link_button(ADD_PHOTOS_LABEL, "image-plus", PRODUCTS_ROUTE),
                spacing="2",
                width="100%",
            ),
        ),
        rx.cond(
            S.pick_show_search,
            rx.vstack(
                rx.el.label(
                    rx.text(PRODUCTS_SEARCH, size="2", weight="medium"),
                    html_for=_SEARCH_ID,
                ),
                rx.input(
                    rx.input.slot(rx.icon("search", size=T.ICON_SM)),
                    id=_SEARCH_ID,
                    value=S.pick_query,
                    on_change=S.set_pick_query,
                    size="3",
                    width="100%",
                ),
                spacing="1",
                width="100%",
            ),
        ),
        rx.cond(
            S.pick_visible_products.length() > 0,
            rx.grid(
                rx.foreach(S.pick_visible_products, _product_card),
                columns="2",
                spacing="2",
                width="100%",
            ),
            rx.hstack(
                rx.text(PRODUCTS_NO_MATCH, size="2", color=T.TEXT_MUTED),
                rx.button(
                    PRODUCTS_SHOW_ALL,
                    on_click=S.clear_pick_query,
                    variant="soft",
                    size="3",
                    min_height=_TAP_MIN,
                    **T.tone_scheme("neutral"),
                ),
                spacing="3",
                align="center",
                wrap="wrap",
            ),
        ),
        spacing="3",
        width="100%",
    )
    return _pick_list(
        rx.cond(
            S.pick_products.length() == 0,
            empty_state(
                "package",
                title,
                line,
                _link_button(ADD_PRODUCT_LABEL, "plus", NEW_PRODUCT_ROUTE),
            ),
            grid,
        )
    )


def _video_mark() -> rx.Component:
    """The ▶ over a video's poster: a still picture, nothing plays in the grid
    (m-24945889 §4)."""
    return rx.center(
        rx.icon("play", size=T.ICON_MD, aria_hidden="true"),
        class_name="q-pick-play",
        position="absolute",
        top="50%",
        left="50%",
        transform="translate(-50%, -50%)",
        width="2.5rem",
        height="2.5rem",
        border_radius="9999px",
        background="rgba(0, 0, 0, 0.55)",
        color="white",
        pointer_events="none",
    )


def _piece_thumb(card: PieceCardVM, height: str) -> rx.Component:
    return rx.box(
        media_thumb(
            card.thumb_url,
            size=None,
            width="100%",
            height=height,
            alt=card.alt,
            icon="image",
        ),
        rx.cond(card.is_video, _video_mark()),
        position="relative",
        width="100%",
    )


def _piece_card(card: PieceCardVM) -> rx.Component:
    return choice_card(
        rx.vstack(
            _piece_thumb(card, "7.5rem"),
            rx.flex(
                _tone_pill(card.status_label, card.status_tone),
                rx.cond(card.is_offer, tone_badge(OFFER_BADGE, "info", icon="tag")),
                rx.cond(card.is_video, tone_badge(VIDEO_BADGE, "neutral", icon="film")),
                rx.cond(card.too_large, signal_pill(VIDEO_HEAVY_PILL, "warn")),
                wrap="wrap",
                gap="1",
            ),
            rx.text(card.title, weight="medium", size="2", text_align="left"),
            rx.cond(
                card.photos_label != "",
                rx.text(card.photos_label, size="1", color=T.TEXT_MUTED),
            ),
            rx.cond(
                card.size_label != "",
                rx.text(card.size_label, size="1", color=T.TEXT_MUTED, class_name="q-nums"),
            ),
            spacing="1",
            align="start",
            width="100%",
        ),
        selected=S.pick_selected == card.id,
        on_select=S.choose_piece(card.id),
        padding="0.5rem",
        width="100%",
        min_height=_TAP_MIN,
    )


def _pieces_empty() -> rx.Component:
    none_title, none_line = NO_PIECES_EMPTY
    approved_title, approved_line = NO_APPROVED_EMPTY
    unapproved_title, unapproved_line = NO_UNAPPROVED_EMPTY

    def create() -> rx.Component:
        return _link_button(CREATE_PIECE_LABEL, "sparkles", CREATE_PIECE_ROUTE)

    return rx.cond(
        S.pick_pieces.length() == 0,
        empty_state("images", none_title, none_line, create()),
        rx.cond(
            S.pick_piece_tab == PIECES_APPROVED,
            empty_state(
                "images",
                approved_title,
                approved_line,
                rx.flex(
                    rx.button(
                        SEE_UNAPPROVED_LABEL,
                        on_click=S.show_unapproved,
                        variant="soft",
                        size="3",
                        min_height=_TAP_MIN,
                        **T.tone_scheme("neutral"),
                    ),
                    create(),
                    gap="2",
                    wrap="wrap",
                    justify="center",
                ),
            ),
            empty_state("images", unapproved_title, unapproved_line, create()),
        ),
    )


def _pick_pieces() -> rx.Component:
    return _pick_list(
        rx.vstack(
            rx.cond(
                S.pick_pieces.length() > 0,
                rx.segmented_control.root(
                    *[rx.segmented_control.item(label, value=key) for key, label in PIECE_TABS],
                    value=S.pick_piece_tab,
                    on_change=S.set_piece_tab,
                    size="3",
                    width="100%",
                ),
            ),
            rx.cond(
                S.pick_visible_pieces.length() > 0,
                rx.grid(
                    rx.foreach(S.pick_visible_pieces, _piece_card),
                    columns="2",
                    spacing="2",
                    width="100%",
                ),
                _pieces_empty(),
            ),
            spacing="3",
            width="100%",
        )
    )


def _payment_card(card_vm: PaymentCardVM) -> rx.Component:
    return choice_card(
        rx.hstack(
            media_thumb(
                card_vm.thumb_url,
                size="48px",
                icon="banknote",
                alt=card_vm.alt,
                has=card_vm.thumb_url != "",
            ),
            rx.vstack(
                rx.text(card_vm.name, weight="medium", size="2"),
                rx.cond(
                    card_vm.currency_label != "",
                    rx.text(card_vm.currency_label, size="1", color=T.TEXT_MUTED),
                ),
                rx.text(card_vm.updated_label, size="1", color=T.TEXT_MUTED),
                spacing="0",
                align_items="start",
            ),
            spacing="3",
            align="center",
            width="100%",
        ),
        selected=S.pick_selected == card_vm.id,
        on_select=S.choose_payment(card_vm.id),
        padding="0.5rem 0.75rem",
        width="100%",
        min_height=_TAP_MIN,
    )


def _pick_payments() -> rx.Component:
    return _pick_list(
        rx.cond(
            S.pick_payments.length() > 0,
            rx.vstack(
                rx.foreach(S.pick_payments, _payment_card),
                spacing="2",
                width="100%",
                role="radiogroup",
            ),
            empty_state(
                "wallet",
                PAYMENTS_EMPTY_TITLE,
                PAYMENTS_EMPTY_TEXT,
                _link_button(PAYMENTS_ADD, "plus", S.payments_change_href),
            ),
        )
    )


def _menu_bubble() -> rx.Component:
    menu = S.pick_menu
    return chat_bubble(
        rx.vstack(
            rx.cond(menu.header != "", rx.text(menu.header, size="2", weight="bold")),
            rx.text(menu.body, size="2", white_space="pre-wrap"),
            rx.cond(menu.footer != "", rx.text(menu.footer, size="1", color=T.TEXT_MUTED)),
            rx.separator(size="4"),
            rx.hstack(
                rx.icon("list", size=T.ICON_SM, aria_hidden="true"),
                rx.text(menu.button_label, size="2", weight="medium"),
                spacing="2",
                align="center",
                justify="center",
                width="100%",
                color=T.tone_color("info", 11),
            ),
            spacing="2",
            width="100%",
        ),
        direction="out",
        max_width="20rem",
        align_self="flex-end",
    )


def _pick_menu() -> rx.Component:
    return _pick_list(
        rx.cond(
            S.pick_menu.not_active,
            rx.vstack(
                callout(MENU_NOT_ACTIVE, "info"),
                _link_button(MENU_SETUP_LABEL, "list", MENU_SETUP_ROUTE),
                spacing="2",
                width="100%",
            ),
            rx.cond(
                S.pick_menu.empty,
                rx.vstack(
                    callout(MENU_EMPTY, "info"),
                    _link_button(ADD_PRODUCT_LABEL, "plus", NEW_PRODUCT_ROUTE),
                    spacing="2",
                    width="100%",
                ),
                rx.vstack(
                    _menu_bubble(),
                    rx.text(S.pick_menu.count_label, size="2", color=T.TEXT_MUTED),
                    rx.cond(
                        S.pick_menu.overflow_note != "", callout(S.pick_menu.overflow_note, "info")
                    ),
                    rx.text(MENU_RESUMES_NOTE, size="2", color=T.TEXT_MUTED),
                    spacing="3",
                    width="100%",
                ),
            ),
        )
    )


def _pick_photo_drop() -> rx.Component:
    return rx.vstack(
        dropzone(
            rx.vstack(
                rx.icon("image-plus", size=T.ICON_LG, color=T.TEXT_FAINT, aria_hidden="true"),
                rx.button(
                    rx.icon("smartphone", size=T.ICON_SM),
                    PHOTO_PICK_LABEL,
                    type="button",
                    size="3",
                    min_height=_TAP_MIN,
                ),
                rx.text(PHOTO_HELP, size="2", color=T.TEXT_MUTED, text_align="center"),
                spacing="3",
                align="center",
                width="100%",
            ),
            upload_id=_PHOTO_UPLOAD_ID,
            on_drop=S.handle_pick_photo(rx.upload_files(upload_id=_PHOTO_UPLOAD_ID)),
            on_drop_rejected=S.pick_photo_rejected,
            accept=_PHOTO_ACCEPT,
            max_files=1,
            max_size=MAX_PHOTO_BYTES,
            disabled=S.pick_sending,
        ),
        rx.cond(S.pick_photo_error != "", callout(S.pick_photo_error, "warn")),
        spacing="3",
        width="100%",
    )


def _review_image() -> rx.Component:
    """The picture in the preview bubble, per source ("" draws nothing)."""
    src = rx.match(
        S.pick_source,
        (PICK_PRODUCTS, _product_src(S.pick_selected_product)),
        (PICK_PIECES, S.pick_selected_piece.thumb_url),
        (PICK_OFFER, S.pick_selected_piece.thumb_url),
        (PICK_PHOTO, S.pick_photo_preview),
        (PICK_PAYMENTS, S.pick_selected_payment.thumb_url),
        "",
    )
    alt = rx.match(
        S.pick_source,
        (PICK_PRODUCTS, S.pick_selected_product.alt),
        (PICK_PIECES, S.pick_selected_piece.alt),
        (PICK_OFFER, S.pick_selected_piece.alt),
        "Foto que vas a enviar",
    )
    payment_without_qr = (S.pick_source == PICK_PAYMENTS) & ~S.pick_selected_payment.has_qr
    # a video piece shows its poster with ▶: it is not played here (m-24945889 §4)
    video = ((S.pick_source == PICK_PIECES) | (S.pick_source == PICK_OFFER)) & (
        S.pick_selected_piece.is_video
    )
    return rx.cond(
        ~S.pick_as_text & ~payment_without_qr,
        rx.box(
            media_thumb(src, size=None, width="100%", height="12rem", alt=alt, icon="image"),
            rx.cond(video, _video_mark()),
            position="relative",
            width="100%",
        ),
    )


def _pick_review() -> rx.Component:
    return rx.vstack(
        rx.cond(
            S.pick_selected_piece.too_large,
            rx.vstack(
                callout(VIDEO_TOO_LARGE, "warn"),
                _link_button(CREATE_AGAIN_LABEL, "sparkles", CREATE_PIECE_ROUTE),
                spacing="2",
                width="100%",
            ),
        ),
        rx.cond(
            S.pick_as_text,
            rx.vstack(
                callout(NO_PHOTO_NOTICE, "info"),
                _link_button(
                    ADD_PHOTO_LABEL,
                    "image-plus",
                    PRODUCTS_ROUTE + "?producto=" + S.pick_selected_product.id,
                ),
                spacing="2",
                width="100%",
            ),
        ),
        chat_bubble(
            rx.vstack(
                _review_image(),
                rx.cond(
                    S.pick_preview_text != "",
                    rx.text(S.pick_preview_text, size="2", white_space="pre-wrap"),
                ),
                spacing="2",
                width="100%",
            ),
            direction="out",
            max_width="20rem",
            align_self="flex-end",
        ),
        rx.cond(
            S.pick_source == PICK_PHOTO,
            rx.button(
                rx.icon("refresh-cw", size=T.ICON_SM),
                PHOTO_CHANGE_LABEL,
                on_click=S.pick_back,
                variant="soft",
                size="3",
                min_height=_TAP_MIN,
                **T.tone_scheme("neutral"),
            ),
        ),
        rx.cond(
            S.pick_source == PICK_PAYMENTS,
            # The card's text is not edited here (a bank account changed by mistake):
            # it is changed in Formas de pago (spec §5).
            rx.vstack(
                rx.cond(S.pick_payment_loading, skeleton_rows(rows=2, height="1.25rem")),
                rx.cond(S.pick_error != "", _pick_load_error()),
                _link_button(PAYMENTS_CHANGE, "pencil", S.payments_change_href),
                spacing="2",
                width="100%",
            ),
            _caption_editor(),
        ),
        spacing="3",
        width="100%",
    )


def _caption_editor(label: str | None = None) -> rx.Component:
    return rx.vstack(
        rx.vstack(
            rx.hstack(
                rx.el.label(
                    rx.text(
                        label or rx.cond(S.pick_as_text, TEXT_ONLY_LABEL, CAPTION_LABEL),
                        size="2",
                        weight="medium",
                    ),
                    html_for=_CAPTION_ID,
                ),
                rx.spacer(),
                rx.text(
                    S.pick_caption_count,
                    size="1",
                    color=rx.cond(
                        S.pick_caption_error != "", T.tone_color("error", 11), T.TEXT_MUTED
                    ),
                    class_name="q-nums",
                    id=_CAPTION_COUNT_ID,
                ),
                width="100%",
                align="center",
            ),
            rx.text_area(
                id=_CAPTION_ID,
                value=S.pick_caption,
                on_change=S.set_pick_caption,
                rows="4",
                resize="vertical",
                width="100%",
                size="3",
                custom_attrs={"aria-describedby": _CAPTION_COUNT_ID},
            ),
            rx.cond(
                S.pick_caption_error != "",
                rx.text(S.pick_caption_error, size="1", color=T.tone_color("error", 11)),
            ),
            rx.cond(
                ((S.pick_source == PICK_PIECES) | (S.pick_source == PICK_OFFER))
                & S.pick_selected_piece.shortened,
                rx.text(CAPTION_SHORTENED, size="1", color=T.TEXT_MUTED),
            ),
            spacing="1",
            width="100%",
        ),
        spacing="3",
        width="100%",
    )


def _media_source_card(key: str, icon: str, title: str, line: str) -> rx.Component:
    return choice_card(
        rx.hstack(
            rx.center(
                rx.icon(icon, size=T.ICON_MD, aria_hidden="true"),
                width="2.75rem",
                height="2.75rem",
                min_width="2.75rem",
                border_radius=T.RADIUS_CONTROL,
                **T.tone_scheme("neutral"),
                class_name="q-pick-source-icon",
            ),
            rx.vstack(
                rx.text(title, weight="medium", size="3"),
                rx.text(line, size="2", color=T.TEXT_MUTED),
                spacing="0",
                align_items="start",
            ),
            spacing="3",
            align="center",
            width="100%",
        ),
        selected=False,
        on_select=S.choose_media_source(key),
        padding="0.75rem 1rem",
        width="100%",
        min_height=_TAP_MIN,
    )


def _pick_media() -> rx.Component:
    """«Fotos y videos» › «¿De dónde?» (m-24945889 §1): one line per card."""
    return rx.vstack(
        *[_media_source_card(*card) for card in MEDIA_SOURCE_CARDS],
        # m-24976895: only when the brand has something APPROVED
        rx.cond(
            S.pick_seasonal.length() > 0,
            _media_source_card(PICK_SEASONAL, "sticker", S.pick_seasonal_card, SEASONAL_LINE),
        ),
        spacing="2",
        width="100%",
        role="radiogroup",
    )


def _seasonal_tile(pick: SeasonalPickVM) -> rx.Component:
    """A sticker moves (light animated WebP); a video stays still here — no `autoplay`,
    only its first frame (`preload="metadata"`)."""
    src = BACKEND_BASE + pick.src
    return choice_card(
        rx.box(
            rx.cond(
                pick.is_video,
                rx.box(
                    rx.el.video(
                        src=src,
                        muted=True,
                        preload="metadata",
                        plays_inline=True,
                        width="100%",
                        height="100%",
                        aria_label=pick.alt,
                        class_name="q-seasonal-video",
                    ),
                    _video_mark(),
                    position="relative",
                    width="100%",
                    height="100%",
                ),
                rx.image(src=src, alt=pick.alt, loading="lazy", width="100%", height="100%"),
            ),
            class_name="q-seasonal-preview",
            aspect_ratio="1 / 1",
            width="100%",
            overflow="hidden",
            border_radius=T.RADIUS_CONTROL,
        ),
        selected=S.pick_selected == pick.id,
        on_select=S.choose_seasonal(pick.id),
        padding="0.35rem",
        width="100%",
        min_height=_TAP_MIN,
        aria_label=pick.alt,
    )


def _seasonal_grid(picks: rx.Var) -> rx.Component:
    return rx.grid(rx.foreach(picks, _seasonal_tile), columns="3", spacing="2", width="100%")


def _pick_seasonal() -> rx.Component:
    """«¿Qué le mandas?»: «Stickers · Videos» when there are both, the current season
    first and «De otras temporadas» below."""
    return rx.vstack(
        rx.cond(
            S.pick_seasonal_both,
            rx.segmented_control.root(
                rx.segmented_control.item(SEASONAL_STICKERS_TAB, value="sticker"),
                rx.segmented_control.item(SEASONAL_VIDEOS_TAB, value="video"),
                value=S.pick_seasonal_tab,
                on_change=S.set_seasonal_tab,
                size="3",
                width="100%",
            ),
        ),
        rx.cond(
            S.pick_seasonal_current.length() > 0,
            rx.vstack(
                rx.text(S.pick_seasonal_current[0].season_label, size="2", weight="medium"),
                _seasonal_grid(S.pick_seasonal_current),
                spacing="2",
                width="100%",
            ),
        ),
        rx.cond(
            S.pick_seasonal_earlier.length() > 0,
            rx.vstack(
                rx.text(SEASONAL_EARLIER, size="2", weight="medium"),
                _seasonal_grid(S.pick_seasonal_earlier),
                spacing="2",
                width="100%",
            ),
        ),
        spacing="3",
        width="100%",
    )


def _pick_seasonal_review() -> rx.Component:
    """A sticker alone, no bubble and no text; a video in its bubble with an optional
    caption that starts empty."""
    chosen = S.pick_selected_seasonal
    src = BACKEND_BASE + chosen.src
    return rx.cond(
        chosen.is_video,
        rx.vstack(
            chat_bubble(
                rx.vstack(
                    rx.el.video(
                        src=src,
                        controls=True,
                        muted=True,
                        preload="metadata",
                        plays_inline=True,
                        width="100%",
                        aria_label=chosen.alt,
                        class_name="q-seasonal-video",
                    ),
                    rx.cond(
                        S.pick_caption.strip() != "",
                        rx.text(S.pick_caption, size="2", white_space="pre-wrap"),
                    ),
                    spacing="2",
                    width="100%",
                ),
                direction="out",
                max_width="20rem",
                align_self="flex-end",
            ),
            _caption_editor(SEASONAL_CAPTION_LABEL),
            spacing="3",
            width="100%",
        ),
        rx.vstack(
            rx.image(
                src=src,
                alt=chosen.alt,
                width="9rem",
                height="9rem",
                align_self="flex-end",
                class_name="q-seasonal-sticker",
            ),
            rx.text(SEASONAL_STICKER_ALONE, size="2", color=T.TEXT_MUTED),
            spacing="3",
            width="100%",
        ),
    )


def _pick_offer() -> rx.Component:
    """«Tu oferta»: one step — the marked piece, how long ago it was marked, a soft
    «¿Sigue vigente?» past 14 days (never blocking), and the usual review."""
    offer = S.pick_offer
    empty_title, empty_line = OFFER_EMPTY
    gone_title, gone_line = OFFER_GONE
    go = _link_button(OFFER_GO, "tag", DRAFTS_ROUTE)
    return _pick_list(
        rx.cond(
            ~offer.present,
            _pick_grid_skeleton(),
            rx.cond(
                ~offer.marked,
                empty_state("tag", empty_title, empty_line, go),
                rx.cond(
                    offer.gone,
                    empty_state("tag", gone_title, gone_line, go),
                    rx.vstack(
                        rx.hstack(
                            tone_badge(OFFER_BADGE, "info", icon="tag"),
                            rx.text(offer.marked_label, size="2", color=T.TEXT_MUTED),
                            spacing="2",
                            align="center",
                            wrap="wrap",
                        ),
                        rx.cond(
                            offer.stale_note != "",
                            rx.vstack(
                                callout(offer.stale_note, "warn"),
                                rx.link(OFFER_CHANGE, href=DRAFTS_ROUTE, size="2"),
                                spacing="1",
                                width="100%",
                            ),
                        ),
                        _pick_review(),
                        spacing="3",
                        width="100%",
                    ),
                ),
            ),
        )
    )


def _directions_bubble() -> rx.Component:
    d = S.pick_directions
    return chat_bubble(
        rx.cond(
            d.has_point,
            rx.hstack(
                rx.center(
                    rx.icon("map-pin", size=T.ICON_MD, aria_hidden="true"),
                    width="2.75rem",
                    height="2.75rem",
                    min_width="2.75rem",
                    border_radius=T.RADIUS_CONTROL,
                    **T.tone_scheme("info"),
                ),
                rx.vstack(
                    rx.cond(d.name != "", rx.text(d.name, size="2", weight="bold")),
                    rx.cond(d.address != "", rx.text(d.address, size="2")),
                    spacing="0",
                    align_items="start",
                ),
                spacing="3",
                align="center",
            ),
            rx.text(d.text, size="2", white_space="pre-wrap", word_break="break-word"),
        ),
        direction="out",
        max_width="20rem",
        align_self="flex-end",
    )


def _pick_directions() -> rx.Component:
    """«Cómo llegar»: one step — what goes out (the WhatsApp map pin, or the address with
    a maps link) or the empty state that leads to Tu número › Perfil."""
    d = S.pick_directions
    empty_title, empty_line = DIRECTIONS_EMPTY
    return _pick_list(
        rx.cond(
            ~d.present,
            skeleton_rows(rows=2, height="3rem"),
            rx.cond(
                d.empty,
                empty_state(
                    "map-pin",
                    empty_title,
                    empty_line,
                    _link_button(DIRECTIONS_COMPLETE, "pencil", S.pick_profile_href),
                ),
                rx.vstack(
                    _directions_bubble(),
                    rx.cond(
                        ~d.has_point,
                        rx.vstack(
                            callout(DIRECTIONS_NO_POINT, "info"),
                            _link_button(DIRECTIONS_PUT_ON_MAP, "map-pin", S.pick_profile_href),
                            spacing="2",
                            width="100%",
                        ),
                    ),
                    spacing="3",
                    width="100%",
                ),
            ),
        )
    )


def _pick_body() -> rx.Component:
    """The panel opens at the chosen option's first step (m-24955785: no «¿Qué le
    quieres mandar?»); the review is its last step."""
    return rx.match(
        S.pick_source,
        (PICK_MENU, _pick_menu()),
        (PICK_MEDIA, _pick_media()),
        (PICK_OFFER, _pick_offer()),
        (PICK_DIRECTIONS, _pick_directions()),
        (PICK_PRODUCTS, rx.cond(S.pick_reviewing, _pick_review(), _pick_products())),
        (
            PICK_PIECES,
            rx.cond(
                S.pick_step <= 1,
                _pick_media(),
                rx.cond(S.pick_reviewing, _pick_review(), _pick_pieces()),
            ),
        ),
        (
            PICK_PHOTO,
            rx.cond(
                S.pick_step <= 1,
                _pick_media(),
                rx.cond(S.pick_reviewing, _pick_review(), _pick_photo_drop()),
            ),
        ),
        (
            PICK_SEASONAL,
            rx.cond(
                S.pick_step <= 1,
                _pick_media(),
                rx.cond(S.pick_reviewing, _pick_seasonal_review(), _pick_seasonal()),
            ),
        ),
        (PICK_PAYMENTS, rx.cond(S.pick_reviewing, _pick_review(), _pick_payments())),
        rx.fragment(),
    )


def _pick_footer() -> rx.Component:
    return rx.vstack(
        rx.cond(
            S.pick_window_closed,
            rx.vstack(
                callout(S.pick_send_error, "warn"),
                rx.text(WINDOW_CLOSED_NOTICE, size="2", color=T.TEXT_MUTED),
                rx.button(
                    rx.icon("message-square-text", size=T.ICON_SM),
                    SEND_APPROVED_LABEL,
                    on_click=S.pick_to_templates,
                    size="3",
                    min_height=_TAP_MIN,
                    width="100%",
                ),
                spacing="2",
                width="100%",
            ),
            rx.cond(S.pick_send_error != "", callout(S.pick_send_error, "error")),
        ),
        rx.cond(
            S.pick_reviewing & S.pick_selected_piece.unapproved,
            callout(UNAPPROVED_WARNING, "warn"),
        ),
        rx.hstack(
            rx.button(
                rx.icon(rx.cond(S.pick_step <= 1, "chevron-left", "arrow-left"), size=T.ICON_SM),
                rx.cond(S.pick_step <= 1, PICK_BACK_TO_CHAT, PICK_BACK),
                on_click=S.pick_back,
                variant="soft",
                size="3",
                min_height=_TAP_MIN,
                **T.tone_scheme("neutral"),
            ),
            rx.spacer(),
            rx.cond(
                S.pick_reviewing & ~S.pick_window_closed,
                rx.button(
                    rx.icon("send", size=T.ICON_SM),
                    rx.cond(
                        (S.pick_send_error != "") & ~S.pick_sending, RETRY_LABEL, S.pick_send_label
                    ),
                    on_click=S.send_pick,
                    disabled=~S.pick_can_send,
                    aria_busy=rx.cond(S.pick_sending, "true", "false"),
                    size="3",
                    min_height=_TAP_MIN,
                ),
            ),
            width="100%",
            align="center",
        ),
        spacing="2",
        width="100%",
    )


def _picker_drawer() -> rx.Component:
    return drawer(
        flow_sync(PICK_FLOW, S.pick_step, ready=S.pick_open, objeto=S.pick_flow_object),
        _pick_body(),
        open=S.pick_open,
        on_open_change=S.set_picker_open,
        title=S.pick_title,
        step=rx.vstack(
            # «Paso N de M» only with more than one step (no «Paso 1 de 1», N6)
            rx.cond(S.pick_total > 1, step_progress(S.pick_step, S.pick_total)),
            rx.cond(S.pick_closing_soon, _tone_pill(S.open_thread.window_label, "warn")),
            spacing="2",
            width="100%",
        ),
        description=S.pick_help,
        footer=_pick_footer(),
        icon="send",  # neutral: the panel sends products, the menu, payments or a photo
    )


def _composer() -> rx.Component:
    return rx.cond(S.show_send_approved, _expired_composer(), _live_composer())


def _live_composer() -> rx.Component:
    return rx.vstack(
        # m-24955785: the «+» opens the send options above, next to «Texto · Botones»
        rx.hstack(
            _pick_menu_button(),
            rx.segmented_control.root(
                *[rx.segmented_control.item(label, value=key) for key, label in COMPOSE_MODES],
                value=S.compose_mode,
                on_change=S.set_compose_mode,
                size="1",
            ),
            align="center",
            spacing="2",
        ),
        _compose_fields(),
        rx.cond(
            S.compose_hint != "",
            rx.text(S.compose_hint, size="1", color=T.tone_color("warn", 11)),
            rx.text(
                "Al responder, la respuesta automática se pausa en esta conversación.",
                size="1",
                color=T.TEXT_MUTED,
            ),
        ),
        rx.hstack(
            rx.spacer(),
            rx.button(
                rx.icon("send", size=T.ICON_SM),
                "Enviar",
                on_click=S.send_message,
                loading=S.sending,
                disabled=~S.can_compose | (S.compose_error != ""),
                size="2",
                min_height=_TAP_MIN,
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
        class_name="q-card q-wa-card",
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
                    "Ábrela para leerla, responder, tomar el control de la respuesta automática o "
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
        _lightbox(),
        _templates_drawer(),
        _picker_drawer(),
        _payment_confirm_dialog(),
        rx.box(
            _list_pane(),
            _conversation_pane(),
            class_name=rx.cond(S.has_open_thread, "q-wa-chats q-wa-chats--open", "q-wa-chats"),
        ),
        on_mount=S.enter,
        width="100%",
    )

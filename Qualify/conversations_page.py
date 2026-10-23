"""`/conversations` (QUA-226, E2): the multichannel private inbox — where a person reads
and answers the private messages of the business's connected accounts (Instagram Direct
first; a channel is one `ConversationSource`/`ConversationSender` pair, and this page
never names one).

Layout (docs/design-system.md §9.1): `app_shell(page_header(...), page_body(...))`; two
panes on desktop — the thread list left, the conversation right; under 768 px one pane at
a time with a back button (the `.q-wa-chats` recipe of `assets/qualify-inbox.css`, shared
with WhatsApp → Chats, plus the `.q-conv-*` recipes of this screen: the profile avatar with
the channel's mark, day chips, the bubble entrance, the «Enviando» dots, the pulse of a
fresh row, the voice recorder, the suggestion chip). States are TONES through
`signal_pill` / `tone_badge` / `callout`; content loading is a skeleton, work in progress
(sending, attaching, suggesting) is the button's own `loading`.

What the page says that the service decides elsewhere:

- the **access banner** (`AccessVM`): a missing permission or an expired connection get
  the action that fixes them (§6.3, «Reconectar» → /connections); an `unknown` verdict is
  «por verificar» (§6.4) — an empty list under it is never worded as «no hay mensajes»; a
  failed sync is a toast (the state's), not a banner;
- the **receipts**, WhatsApp's grammar: a clock is the outbox row the worker has not
  drained yet, a single ✓ is «Enviado», the accent ✓✓ with the «Visto» footer is
  Instagram's own read receipt (`messaging_seen`). Instagram exposes neither «entregado»
  nor the other person's typing, so neither is shown (no dots: dots would mean «they are
  writing», which the channel never tells);
- the **composer** is off, with the reason in plain words, when the 24 h window is closed
  or the account may not message; the person always sees **from which account and
  channel** the reply goes out (`reply_as`); four icon tools — a photo or video, a PDF,
  a voice note, a ❤️ — can go with (or instead of) the text; a long text says in how many
  messages it goes out; «Sugerir respuesta» (E4) fills the box with a model's draft the
  person edits or discards — nothing is sent without pressing «Responder»;
- **«Plantillas»** (m-24789472) opens the account's saved messages: picking one fills the
  box with its text for this person (`{nombre}`, `{marca}`), a line says what is still to
  complete («[precio]»), and it leaves only through «Responder». «Administrar plantillas»
  opens a drawer to create, edit, delete (confirmed in place) and reorder them;
- every real bubble has **«Eliminar para mí»** on hover: Instagram's API offers a
  business neither unsend nor edit, so «para todos» and «editar» do not exist here;
- the conversation shows its **newest 50 messages** (`MESSAGES_PAGE`); older history is a
  documented follow-up, not a hidden truncation.

Data: `ConversationsState` over `conversations_provider.ConversationsGateway` (in process,
`tenant_session`), VMs from `conversations_vm.py`. The page imports neither.
"""

from __future__ import annotations

import reflex as rx

from .conversations_state import ConversationsState
from .conversations_vm import (
    DOCUMENT_ACCEPT,
    FILTER_ALL,
    FILTER_ANSWERED,
    FILTER_PENDING,
    FILTER_READ,
    MAX_DOCUMENT_BYTES,
    MAX_MEDIA_BYTES,
    MAX_TEMPLATE_BODY_CHARS,
    MAX_TEMPLATE_TITLE_CHARS,
    MAX_TEMPLATES_PER_ACCOUNT,
    MEDIA_ACCEPT,
    MEDIA_AUDIO,
    MEDIA_IMAGE,
    MEDIA_STICKER,
    MEDIA_VIDEO,
    MESSAGES_PAGE,
    TEMPLATE_HELP,
    AccountVM,
    MessageVM,
    TemplateVM,
    ThreadRowVM,
)
from .followups_page import followups_panel, followups_toggle
from .followups_state import FollowupsState
from .ui import (
    app_shell,
    callout,
    card,
    chat_bubble,
    drawer,
    dropzone,
    empty_state,
    mono,
    page_body,
    page_header,
    platform_badge,
    signal_pill,
    skeleton_rows,
    tone_badge,
)
from .ui import tokens as T

S = ConversationsState
_TONES = ("ok", "warn", "error", "info", "neutral")

#: Same cadence as WhatsApp → Chats: 15 s, client-side, unmounted with the page.
_REFRESH_MS = 15_000
_MEDIA_UPLOAD_ID = "conversations_media"
_FILE_UPLOAD_ID = "conversations_file"


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
    return rx.moment(interval=_REFRESH_MS, on_change=lambda _tick: S.refresh, display="none")


def _retry_button(label: str, on_click: rx.event.EventHandler) -> rx.Component:
    return rx.button(
        rx.icon("refresh-cw", size=T.ICON_SM),
        label,
        on_click=on_click,
        variant="soft",
        size="2",
        **T.tone_scheme("neutral"),
    )


def _instagram_glyph() -> rx.Component:
    """Instagram's mark, inline (Lucide carries no brand icons): a rounded square, the
    lens and the flash dot, in the current colour."""
    return rx.el.svg(
        rx.el.svg.rect(x="2", y="2", width="20", height="20", rx="5", ry="5"),
        rx.el.svg.circle(cx="12", cy="12", r="4"),
        rx.el.svg.circle(cx="17.5", cy="6.5", r="1.2", fill="currentColor"),
        view_box="0 0 24 24",
        width="10",
        height="10",
        fill="none",
        stroke="currentColor",
        stroke_width="2.2",
        stroke_linecap="round",
        stroke_linejoin="round",
        color="white",
        aria_hidden="true",
    )


def _avatar(row: ThreadRowVM, size: str = "md") -> rx.Component:
    """The counterpart's mark: their Instagram picture when the sync fetched one, else
    initials over a hue the stylesheet turns into the kit's gradient (`--q-conv-hue` is a
    number, never a colour literal). The channel's glyph sits on the corner."""
    radix_size = "4" if size == "md" else "5"
    return rx.box(
        rx.avatar(
            src=row.avatar_url,
            fallback=row.initials,
            radius="full",
            size=radix_size,
            class_name="q-conv-avatar",
            custom_attrs={"referrerpolicy": "no-referrer"},
        ),
        rx.box(
            _instagram_glyph(),
            class_name="q-conv-channel",
            aria_label="Instagram",
        ),
        class_name=f"q-conv-avatar-wrap q-conv-avatar-wrap--{size}",
        style={"--q-conv-hue": row.hue},
        aria_hidden="true",
        position="relative",
        flex_shrink="0",
    )


# ======================================================================================
# Header: the account selector
# ======================================================================================


def _account_item(account: AccountVM) -> rx.Component:
    return rx.select.item(account.label, value=account.connection_id)


def account_selector() -> rx.Component:
    """Which connected account the inbox shows. A single account is named, not chosen."""
    return rx.cond(
        S.has_many_accounts,
        rx.select.root(
            rx.select.trigger(placeholder="Elige una cuenta", width="260px"),
            rx.select.content(rx.foreach(S.accounts, _account_item)),
            value=S.selected_connection_id,
            on_change=S.select_account,
            size="2",
        ),
        rx.cond(
            S.has_accounts,
            rx.hstack(
                platform_badge("instagram"),
                rx.text(S.selected_account.label, size="2", weight="medium"),
                spacing="2",
                align="center",
            ),
            rx.fragment(),
        ),
    )


def _pending_badge() -> rx.Component:
    return rx.cond(
        S.pending_count > 0,
        tone_badge(S.pending_count.to(str) + " sin responder", "warn", icon="bell"),
        rx.fragment(),
    )


def conversations_header() -> rx.Component:
    return page_header(
        "Conversaciones",
        "Los mensajes privados que llegan a tus cuentas conectadas, en una sola bandeja.",
        account_selector(),
        badge=_pending_badge(),
    )


# ======================================================================================
# Access banner (one per account, over the list)
# ======================================================================================


def _reconnect_link() -> rx.Component:
    return rx.link(
        rx.button(
            rx.icon("refresh-cw", size=T.ICON_SM),
            "Reconectar",
            variant="soft",
            size="2",
            **T.tone_scheme("warn"),
        ),
        href="/connections",
    )


def _access_content() -> rx.Component:
    access = S.access
    return rx.vstack(
        rx.hstack(
            rx.text(access.title, size="2", weight="bold"),
            rx.cond(
                access.provisional,
                tone_badge("por verificar", "warn", icon="circle-help"),
                rx.fragment(),
            ),
            spacing="2",
            align="center",
            flex_wrap="wrap",
        ),
        rx.text(access.message, size="2"),
        rx.hstack(
            rx.text(access.last_sync_label, size="1", color=T.TEXT_MUTED),
            rx.spacer(),
            rx.cond(access.show_reconnect, _reconnect_link(), rx.fragment()),
            width="100%",
            align="center",
            spacing="3",
            flex_wrap="wrap",
        ),
        spacing="2",
        width="100%",
    )


def access_banner() -> rx.Component:
    content = _access_content()
    return rx.cond(
        S.show_access_banner,
        rx.match(
            S.access.tone,
            ("warn", callout(content, "warn")),
            ("error", callout(content, "error")),
            ("ok", callout(content, "ok")),
            ("info", callout(content, "info")),
            callout(content, "neutral"),
        ),
        rx.fragment(),
    )


# ======================================================================================
# Thread list
# ======================================================================================


def _thread_row(row: ThreadRowVM) -> rx.Component:
    is_open = row.thread_id == S.open_thread_id
    return rx.box(
        rx.hstack(
            rx.box(
                _avatar(row),
                rx.cond(
                    row.attention == "pending",
                    rx.box(class_name="q-conv-unread", aria_label="Sin responder"),
                    rx.fragment(),
                ),
                position="relative",
                flex_shrink="0",
            ),
            rx.vstack(
                rx.hstack(
                    rx.text(
                        row.title,
                        size="3",
                        weight=rx.cond(row.attention == "pending", "bold", "medium"),
                        class_name="q-wa-ellipsis",
                        flex="1",
                        min_width="0",
                    ),
                    rx.text(
                        row.time_label,
                        size="1",
                        color=T.TEXT_MUTED,
                        white_space="nowrap",
                        class_name="q-nums",
                    ),
                    width="100%",
                    align="center",
                    spacing="2",
                ),
                rx.cond(
                    row.handle != "",
                    rx.text(row.handle, size="1", color=T.TEXT_MUTED, class_name="q-wa-ellipsis"),
                    rx.fragment(),
                ),
                rx.hstack(
                    rx.cond(
                        row.preview_icon != "",
                        rx.icon(row.preview_icon, size=T.ICON_SM, color=T.TEXT_MUTED),
                        rx.fragment(),
                    ),
                    rx.text(
                        row.preview,
                        size="2",
                        color=rx.cond(row.attention == "pending", T.TEXT_STRONG, T.TEXT_MUTED),
                        class_name="q-wa-ellipsis",
                        flex="1",
                        min_width="0",
                    ),
                    width="100%",
                    align="center",
                    spacing="1",
                ),
                rx.hstack(
                    _tone_pill(row.attention_label, row.attention_tone),
                    rx.cond(
                        row.window_short != "",
                        _tone_pill(row.window_short, row.window_tone),
                        rx.fragment(),
                    ),
                    width="100%",
                    align="center",
                    spacing="1",
                    flex_wrap="wrap",
                ),
                spacing="1",
                width="100%",
                min_width="0",
            ),
            spacing="3",
            align="start",
            width="100%",
        ),
        on_click=S.open_conversation(row.thread_id),
        class_name=rx.cond(
            is_open,
            rx.cond(
                row.fresh,
                "q-card q-lift q-wa-row q-conv-row q-wa-row--active q-conv-row--fresh",
                "q-card q-lift q-wa-row q-conv-row q-wa-row--active",
            ),
            rx.cond(
                row.fresh,
                "q-card q-lift q-wa-row q-conv-row q-conv-row--fresh",
                "q-card q-lift q-wa-row q-conv-row",
            ),
        ),
        role="button",
        tab_index=0,
        aria_label=row.title,
        cursor="pointer",
        width="100%",
    )


def _filter_chip(label: rx.Var[str], key: str) -> rx.Component:
    active = S.filter_key == key
    return rx.button(
        label,
        on_click=S.set_filter(key),
        variant=rx.cond(active, "solid", "soft"),
        size="1",
        type="button",
        class_name="q-conv-filter",
        **T.tone_scheme("neutral"),
    )


def _filters() -> rx.Component:
    """Chips that wrap instead of a segmented control that overflows the narrow pane."""
    return rx.flex(
        _filter_chip(S.filter_all_label, FILTER_ALL),
        _filter_chip(S.filter_pending_label, FILTER_PENDING),
        _filter_chip(S.filter_read_label, FILTER_READ),
        _filter_chip(S.filter_answered_label, FILTER_ANSWERED),
        wrap="wrap",
        gap="0.4rem",
        width="100%",
        class_name="q-conv-filters",
        role="tablist",
        aria_label="Filtrar conversaciones",
    )


def _empty_list() -> rx.Component:
    """Worded by the access verdict: under a provisional one the list is NOT «no hay
    mensajes», it is «no se ha podido leer todavía»."""
    return rx.cond(
        S.access.provisional,
        empty_state(
            "mail-question",
            "Todavía no se han leído mensajes de esta cuenta",
            "Mientras el acceso a los mensajes esté por verificar, una lista vacía no "
            "significa que nadie haya escrito. Revisa el aviso de arriba.",
        ),
        empty_state(
            "messages-square",
            "Aún no hay conversaciones en esta cuenta",
            "Cuando alguien escriba por mensaje privado a esta cuenta, su conversación "
            "aparece aquí y puedes responderla desde esta pantalla.",
        ),
    )


def _list_body() -> rx.Component:
    return rx.cond(
        S.list_error != "",
        rx.vstack(
            callout(S.list_error, "error"),
            _retry_button("Reintentar", S.load_list),
            width="100%",
            spacing="3",
        ),
        rx.cond(
            S.list_ready,
            rx.cond(
                S.list_empty,
                _empty_list(),
                rx.cond(
                    S.visible_rows.length() > 0,
                    rx.vstack(
                        rx.foreach(S.visible_rows, _thread_row),
                        spacing="2",
                        width="100%",
                        class_name="q-wa-scroll q-wa-scroll--list q-conv-list",
                    ),
                    rx.text(
                        "No hay conversaciones con este filtro.",
                        size="2",
                        color=T.TEXT_MUTED,
                        padding="1rem 0.25rem",
                    ),
                ),
            ),
            skeleton_rows(6, height="5.5rem", radius=T.RADIUS_CARD),
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
# Conversation
# ======================================================================================


def _back_button() -> rx.Component:
    return rx.icon_button(
        rx.icon("arrow-left", size=T.ICON_MD),
        on_click=S.close_conversation,
        variant="ghost",
        size="2",
        aria_label="Volver a las conversaciones",
        class_name="q-wa-chats__back",
        **T.tone_scheme("neutral"),
    )


def _close_button() -> rx.Component:
    return rx.icon_button(
        rx.icon("x", size=T.ICON_MD),
        on_click=S.close_conversation,
        variant="ghost",
        size="2",
        aria_label="Cerrar la conversación",
        class_name="q-conv-close",
        **T.tone_scheme("neutral"),
    )


def _conversation_header() -> rx.Component:
    thread = S.open_thread
    return rx.hstack(
        _back_button(),
        _avatar(thread, size="lg"),
        rx.vstack(
            rx.hstack(
                rx.heading(thread.title, size="4", as_="h2", class_name="q-wa-ellipsis"),
                rx.cond(
                    thread.handle != "",
                    rx.text(thread.handle, size="2", color=T.TEXT_MUTED),
                    rx.fragment(),
                ),
                spacing="2",
                align="baseline",
                min_width="0",
                flex_wrap="wrap",
            ),
            rx.hstack(
                mono(thread.subtitle, size="1"),
                _tone_pill(thread.attention_label, thread.attention_tone),
                spacing="2",
                flex_wrap="wrap",
                align="center",
            ),
            spacing="1",
            min_width="0",
            flex="1",
        ),
        _close_button(),
        width="100%",
        align="center",
        spacing="3",
        class_name="q-conv-head",
    )


def _tick(m: MessageVM) -> rx.Component:
    muted = T.TEXT_MUTED
    return rx.box(
        rx.match(
            m.tick,
            ("sent", rx.icon("check", size=T.ICON_SM, color=muted)),
            ("read", rx.icon("check-check", size=T.ICON_SM, color=T.tone_color("accent", 11))),
            ("queued", rx.icon("clock", size=T.ICON_SM, color=muted)),
            ("failed", rx.icon("circle-alert", size=T.ICON_SM, color=T.tone_color("error", 11))),
            rx.fragment(),
        ),
        title=m.tick_label,
        aria_label=m.tick_label,
        display="inline-flex",
        align_items="center",
    )


def _hide_button(m: MessageVM) -> rx.Component:
    """«Eliminar para mí», shown on hover (`.q-conv-hide`). Instagram's API cannot unsend
    or edit, so this is the only deletion a business has; an outbox row has none."""
    return rx.cond(
        ~m.message_id.startswith("outbox-"),
        rx.tooltip(
            rx.icon_button(
                rx.icon("trash-2", size=12),
                on_click=S.hide_message(m.message_id),
                variant="ghost",
                size="1",
                type="button",
                aria_label="Eliminar para mí",
                class_name="q-conv-hide",
                **T.tone_scheme("neutral"),
            ),
            content="Eliminar para mí (la otra persona lo sigue viendo)",
        ),
        rx.fragment(),
    )


def _bubble_meta(m: MessageVM) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            _hide_button(m),
            rx.text(m.time_label, size="1", class_name="q-nums q-conv-meta"),
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


def _media_view(m: MessageVM) -> rx.Component:
    """What an attachment renders as, by control; a missing source says so. A sticker
    has no source: the heart is the message."""
    unavailable = rx.hstack(
        rx.icon("circle-slash", size=T.ICON_SM, color=T.TEXT_MUTED),
        rx.text(m.media_label + " · ya no está disponible", size="1", color=T.TEXT_MUTED),
        spacing="2",
        align="center",
    )
    return rx.cond(
        m.media_control == MEDIA_STICKER,
        rx.box(
            rx.icon("heart", size=40, class_name="q-conv-heart"),
            aria_label="Me gusta",
            title="Me gusta",
        ),
        rx.cond(
            m.media_src != "",
            rx.match(
                m.media_control,
                (
                    MEDIA_IMAGE,
                    rx.link(
                        rx.image(
                            src=m.media_src,
                            alt=m.media_label,
                            class_name="q-conv-media q-conv-media--image",
                            custom_attrs={"referrerpolicy": "no-referrer", "loading": "lazy"},
                        ),
                        href=m.media_src,
                        is_external=True,
                        rel="noopener noreferrer",
                        aria_label="Abrir la foto",
                    ),
                ),
                (
                    MEDIA_AUDIO,
                    rx.el.audio(
                        src=m.media_src,
                        controls=True,
                        preload="metadata",
                        aria_label="Audio",
                        class_name="q-conv-media q-conv-media--audio",
                    ),
                ),
                (
                    MEDIA_VIDEO,
                    rx.el.video(
                        src=m.media_src,
                        controls=True,
                        preload="metadata",
                        aria_label="Video",
                        class_name="q-conv-media q-conv-media--video",
                    ),
                ),
                rx.link(
                    rx.hstack(
                        rx.icon("file-text", size=T.ICON_MD),
                        rx.vstack(
                            rx.text(m.media_label, size="2", weight="medium"),
                            rx.text("Abrir", size="1", color=T.TEXT_MUTED),
                            spacing="0",
                        ),
                        spacing="2",
                        align="center",
                        class_name="q-conv-file",
                    ),
                    href=m.media_src,
                    is_external=True,
                    rel="noopener noreferrer",
                ),
            ),
            unavailable,
        ),
    )


def _bubble_body(m: MessageVM) -> rx.Component:
    text = rx.cond(
        m.text != "",
        rx.text(m.text, size="2", white_space="pre-wrap", overflow_wrap="anywhere"),
        rx.fragment(),
    )
    return rx.cond(
        m.media_control != "",
        rx.vstack(
            _media_view(m),
            rx.cond(m.media_src != "", text, rx.fragment()),
            spacing="2",
            align_items="start",
        ),
        text,
    )


def _day_chip(label: rx.Var[str]) -> rx.Component:
    return rx.cond(
        label != "",
        rx.center(rx.box(rx.text(label, size="1"), class_name="q-conv-day"), width="100%"),
        rx.fragment(),
    )


def _seen_footer(m: MessageVM) -> rx.Component:
    return rx.cond(
        m.seen_footer != "",
        rx.hstack(
            rx.icon("check-check", size=T.ICON_SM, color=T.tone_color("accent", 11)),
            rx.text(m.seen_footer, size="1", color=T.TEXT_MUTED),
            spacing="1",
            align="center",
            justify="end",
            width="100%",
            class_name="q-conv-seen",
        ),
        rx.fragment(),
    )


def _story_reply(m: MessageVM) -> rx.Component:
    """«Respondió a tu historia» above an inbound bubble (m-24789646, B5)."""
    label = rx.hstack(
        rx.icon("circle-dashed", size=T.ICON_SM, color=T.TEXT_FAINT),
        rx.cond(
            m.story_reply_href != "",
            rx.link(m.story_reply_label, href=m.story_reply_href, is_external=True, size="1"),
            rx.text(m.story_reply_label, size="1", color=T.TEXT_MUTED),
        ),
        spacing="1",
        align="center",
    )
    return rx.cond(m.story_reply_label != "", label, rx.fragment())


def _message(m: MessageVM) -> rx.Component:
    """Outbound right, inbound left (`.q-wa-msg--*` aligns and turns the kit's tail);
    `.q-conv-msg` is the entrance — keyed by message id, so only a new bubble plays it.
    An outbound bubble wears the channel's gradient (`.q-conv-bubble--out`)."""
    return rx.vstack(
        _day_chip(m.day_label),
        rx.cond(
            m.is_outbound,
            rx.box(
                chat_bubble(_bubble_body(m), direction="out", meta=_bubble_meta(m)),
                class_name=rx.cond(
                    m.media_control == MEDIA_STICKER,
                    "q-wa-msg q-wa-msg--out q-conv-msg q-conv-msg--sticker",
                    "q-wa-msg q-wa-msg--out q-conv-msg",
                ),
            ),
            rx.box(
                _story_reply(m),
                chat_bubble(_bubble_body(m), direction="in", meta=_bubble_meta(m)),
                class_name=rx.cond(
                    m.story_reply_label != "",
                    "q-wa-msg q-wa-msg--in q-conv-msg q-conv-msg--story",
                    "q-wa-msg q-wa-msg--in q-conv-msg",
                ),
            ),
        ),
        _seen_footer(m),
        spacing="1",
        width="100%",
        key=m.message_id,
    )


def _messages() -> rx.Component:
    """`column-reverse` keeps the scroll anchored at the newest message with no JS."""
    return rx.box(
        rx.vstack(
            rx.cond(
                S.messages.length() >= MESSAGES_PAGE,
                rx.text(
                    f"Se muestran los últimos {MESSAGES_PAGE} mensajes.",
                    size="1",
                    color=T.TEXT_MUTED,
                    text_align="center",
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
        class_name="q-wa-scroll q-wa-scroll--messages q-conv-scroll",
        width="100%",
    )


# --- composer -----------------------------------------------------------------------


def _tool(icon: str, tip: str, **props) -> rx.Component:
    """An icon-only composer tool; the tooltip says what it sends."""
    return rx.tooltip(
        rx.icon_button(
            rx.icon(icon, size=T.ICON_MD),
            variant="soft",
            size="2",
            type="button",
            aria_label=tip,
            **props,
        ),
        content=tip,
    )


def _attach_button(
    upload_id: str, icon: str, tip: str, accept: dict, max_size: int
) -> rx.Component:
    off = ~S.can_compose | S.busy | S.has_attachment | S.recording
    return dropzone(
        _tool(icon, tip, disabled=off, **T.tone_scheme("neutral")),
        upload_id=upload_id,
        on_drop=S.handle_attachment(rx.upload_files(upload_id=upload_id)),
        accept=accept,
        max_files=1,
        max_size=max_size,
        variant="bare",
        disabled=off,
    )


def _heart_button() -> rx.Component:
    return _tool(
        "heart",
        "Enviar un corazón",
        on_click=S.send_heart,
        disabled=~S.can_compose | S.busy | S.recording,
        **T.tone_scheme("error"),
    )


def _voice_controls() -> rx.Component:
    """«Grabar» → a red dot, the timer, «Cancelar» and «Listo» → the chip."""
    return rx.cond(
        S.recording,
        rx.hstack(
            rx.box(class_name="q-conv-rec"),
            rx.el.span("00:00", id="q-voice-timer", class_name="q-nums q-conv-timer"),
            rx.button(
                rx.icon("x", size=T.ICON_SM),
                "Cancelar",
                on_click=S.cancel_recording,
                variant="soft",
                size="1",
                type="button",
                **T.tone_scheme("neutral"),
            ),
            rx.button(
                rx.icon("check", size=T.ICON_SM),
                "Listo",
                on_click=S.stop_recording,
                size="1",
                type="button",
            ),
            spacing="2",
            align="center",
            class_name="q-conv-recording",
        ),
        _tool(
            "mic",
            "Grabar una nota de voz",
            on_click=S.start_recording,
            disabled=~S.can_compose | S.busy | S.has_attachment,
            loading=S.receiving_voice,
            **T.tone_scheme("neutral"),
        ),
    )


def _attachment_chip() -> rx.Component:
    a = S.attachment
    icon = rx.match(
        a.media_type,
        (MEDIA_AUDIO, rx.icon("mic", size=T.ICON_MD)),
        (MEDIA_VIDEO, rx.icon("video", size=T.ICON_MD)),
        ("document", rx.icon("file-text", size=T.ICON_MD)),
        rx.icon("image", size=T.ICON_MD),
    )
    return rx.cond(
        S.has_attachment,
        rx.hstack(
            rx.cond(
                (a.media_type == MEDIA_IMAGE) & (a.preview_src != ""),
                rx.image(
                    src=a.preview_src,
                    alt=a.name,
                    class_name="q-conv-attach-thumb",
                    custom_attrs={"referrerpolicy": "no-referrer"},
                ),
                icon,
            ),
            rx.vstack(
                rx.text(a.name, size="2", weight="medium", class_name="q-wa-ellipsis"),
                rx.text(a.ready_label, size="1", color=T.TEXT_MUTED),
                spacing="0",
                min_width="0",
                flex="1",
            ),
            rx.icon_button(
                rx.icon("x", size=T.ICON_SM),
                on_click=S.clear_attachment,
                variant="ghost",
                size="1",
                aria_label="Quitar el adjunto",
                **T.tone_scheme("neutral"),
            ),
            class_name="q-conv-attach",
            width="100%",
            align="center",
            spacing="3",
        ),
        rx.fragment(),
    )


def _suggestion_chip() -> rx.Component:
    d = S.suggestion
    return rx.cond(
        S.has_suggestion,
        rx.hstack(
            rx.icon(
                "sparkles",
                size=T.ICON_MD,
                color=rx.cond(d.needs_review, T.tone_color("warn", 11), T.tone_color("accent", 11)),
            ),
            rx.vstack(
                rx.text(d.note, size="2", weight="medium"),
                rx.cond(
                    d.claims != "",
                    rx.text("Por confirmar: " + d.claims, size="1", color=T.TEXT_MUTED),
                    rx.text("Nada sale sin que pulses «Responder».", size="1", color=T.TEXT_MUTED),
                ),
                spacing="0",
                min_width="0",
                flex="1",
            ),
            rx.button(
                rx.icon("trash-2", size=T.ICON_SM),
                "Descartar",
                on_click=S.discard_suggestion,
                variant="ghost",
                size="1",
                type="button",
                **T.tone_scheme("neutral"),
            ),
            class_name=rx.cond(
                d.needs_review, "q-conv-suggest q-conv-suggest--review", "q-conv-suggest"
            ),
            width="100%",
            align="center",
            spacing="3",
        ),
        rx.fragment(),
    )


# --- message templates (m-24789472) --------------------------------------------------


def _template_item(t: TemplateVM) -> rx.Component:
    """One row of the picker: the title and the start of the text. A click renders it for
    this person and fills the box — it never sends."""
    return rx.button(
        rx.vstack(
            rx.text(t.title, size="2", weight="medium", class_name="q-wa-ellipsis", width="100%"),
            rx.text(
                t.preview, size="1", color=T.TEXT_MUTED, class_name="q-wa-ellipsis", width="100%"
            ),
            spacing="0",
            align_items="start",
            width="100%",
            min_width="0",
        ),
        on_click=S.apply_template(t.template_id),
        loading=S.applying_template_id == t.template_id,
        disabled=~S.can_use_template | (S.applying_template_id != ""),
        variant="ghost",
        size="2",
        type="button",
        width="100%",
        height="auto",
        justify_content="start",
        text_align="left",
        padding="0.45rem 0.6rem",
        class_name="q-conv-template-item",
        **T.tone_scheme("neutral"),
    )


def _templates_menu_list() -> rx.Component:
    return rx.cond(
        S.templates_error != "",
        rx.vstack(
            callout(S.templates_error, "error"),
            _retry_button("Reintentar", S.load_templates),
            spacing="2",
            width="100%",
        ),
        rx.cond(
            S.templates_ready,
            rx.cond(
                S.templates_empty,
                rx.vstack(
                    rx.text("Aún no tienes plantillas en esta cuenta.", size="2"),
                    rx.text(
                        "Guarda las respuestas que más escribes y úsalas con un clic.",
                        size="1",
                        color=T.TEXT_MUTED,
                    ),
                    spacing="1",
                    width="100%",
                    padding="0.25rem 0.1rem",
                ),
                rx.vstack(
                    rx.cond(
                        S.can_use_template,
                        rx.fragment(),
                        rx.text(
                            "Para usar una plantilla, la conversación tiene que admitir "
                            "respuestas.",
                            size="1",
                            color=T.TEXT_MUTED,
                        ),
                    ),
                    rx.foreach(S.templates, _template_item),
                    spacing="1",
                    width="100%",
                    max_height="18rem",
                    overflow_y="auto",
                ),
            ),
            skeleton_rows(3, height="2.75rem"),
        ),
    )


def _templates_picker() -> rx.Component:
    """«Plantillas» beside «Sugerir respuesta»: a popover with the account's library and
    the door to manage it."""
    return rx.popover.root(
        rx.popover.trigger(
            rx.button(
                rx.icon("message-square-quote", size=T.ICON_SM),
                "Plantillas",
                variant="soft",
                size="2",
                type="button",
                disabled=~S.can_open_templates,
                **T.tone_scheme("neutral"),
            ),
        ),
        rx.popover.content(
            rx.vstack(
                rx.hstack(
                    rx.text("Plantillas", size="2", weight="bold"),
                    rx.spacer(),
                    rx.cond(
                        S.templates_ready,
                        rx.text(
                            S.templates_counter, size="1", color=T.TEXT_MUTED, class_name="q-nums"
                        ),
                        rx.fragment(),
                    ),
                    width="100%",
                    align="center",
                ),
                _templates_menu_list(),
                rx.button(
                    rx.icon("library", size=T.ICON_SM),
                    "Administrar plantillas",
                    on_click=S.open_templates_manager,
                    variant="soft",
                    size="1",
                    type="button",
                    width="100%",
                    **T.tone_scheme("neutral"),
                ),
                spacing="2",
                width="100%",
            ),
            side="top",
            align="end",
            width="min(22rem, calc(100vw - 2rem))",
            class_name="q-conv-templates",
        ),
        open=S.templates_menu_open,
        on_open_change=S.set_templates_menu_open,
    )


def _template_fill_notice() -> rx.Component:
    """What a picked template still asks the person to complete. Gentle: it never
    blocks «Responder», and it goes away as the person fills each spot."""
    return rx.cond(
        S.template_fill_notice != "",
        callout(S.template_fill_notice, "info", icon="pencil-line"),
        rx.fragment(),
    )


def _field(label: str, control: rx.Component, counter: rx.Var[str]) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.text(label, size="2", weight="medium"),
            rx.spacer(),
            rx.text(counter, size="1", color=T.TEXT_MUTED, class_name="q-nums"),
            width="100%",
            align="center",
        ),
        control,
        spacing="1",
        width="100%",
    )


def _template_form() -> rx.Component:
    return rx.cond(
        S.template_form_open,
        card(
            rx.vstack(
                rx.text(S.template_form_heading, size="3", weight="bold"),
                _field(
                    "Nombre",
                    rx.input(
                        value=S.template_form_title,
                        on_change=S.set_template_form_title,
                        placeholder="Ej.: Envíos",
                        max_length=MAX_TEMPLATE_TITLE_CHARS,
                        width="100%",
                        aria_label="Nombre de la plantilla",
                    ),
                    S.template_title_counter,
                ),
                _field(
                    "Mensaje",
                    rx.text_area(
                        value=S.template_form_body,
                        on_change=S.set_template_form_body,
                        placeholder="Ej.: ¡Hola, {nombre}! Hacemos envíos a todo el país.",
                        max_length=MAX_TEMPLATE_BODY_CHARS,
                        rows="5",
                        resize="vertical",
                        width="100%",
                        aria_label="Mensaje de la plantilla",
                    ),
                    S.template_body_counter,
                ),
                rx.text(TEMPLATE_HELP, size="1", color=T.TEXT_MUTED),
                rx.cond(
                    S.template_form_error != "",
                    callout(S.template_form_error, "error"),
                    rx.fragment(),
                ),
                rx.hstack(
                    rx.button(
                        "Cancelar",
                        on_click=S.cancel_template_form,
                        variant="soft",
                        size="2",
                        type="button",
                        **T.tone_scheme("neutral"),
                    ),
                    rx.button(
                        rx.icon("check", size=T.ICON_SM),
                        "Guardar",
                        on_click=S.save_template,
                        loading=S.template_saving,
                        size="2",
                        type="button",
                    ),
                    spacing="2",
                    justify="end",
                    width="100%",
                ),
                spacing="3",
                width="100%",
            ),
            padding="1rem",
        ),
        rx.fragment(),
    )


def _template_tool(icon: str, label: str, **props) -> rx.Component:
    return rx.tooltip(
        rx.icon_button(
            rx.icon(icon, size=T.ICON_SM),
            variant="ghost",
            size="1",
            type="button",
            aria_label=label,
            **T.tone_scheme("neutral"),
            **props,
        ),
        content=label,
    )


def _template_row(t: TemplateVM) -> rx.Component:
    """A template in the manager: up / down / edit / delete; «Borrar» asks first, in
    place (a second dialog over the drawer would trap focus twice)."""
    busy = S.templates_working | S.template_saving
    confirm = rx.vstack(
        rx.text("¿Borrar la plantilla «" + t.title + "»? No se puede deshacer.", size="2"),
        rx.hstack(
            rx.button(
                "Cancelar",
                on_click=S.cancel_delete_template,
                variant="soft",
                size="1",
                type="button",
                **T.tone_scheme("neutral"),
            ),
            rx.button(
                rx.icon("trash-2", size=T.ICON_SM),
                "Borrar",
                on_click=S.confirm_delete_template,
                loading=S.templates_working,
                size="1",
                type="button",
                **T.tone_scheme("error"),
            ),
            spacing="2",
            justify="end",
            width="100%",
        ),
        spacing="2",
        width="100%",
    )
    normal = rx.hstack(
        rx.vstack(
            rx.text(t.title, size="2", weight="medium", class_name="q-wa-ellipsis", width="100%"),
            rx.text(t.body, size="1", color=T.TEXT_MUTED, white_space="pre-wrap", width="100%"),
            spacing="1",
            min_width="0",
            flex="1",
        ),
        rx.hstack(
            _template_tool(
                "arrow-up",
                "Subir",
                on_click=S.move_template(t.template_id, -1),
                disabled=t.is_first | busy,
            ),
            _template_tool(
                "arrow-down",
                "Bajar",
                on_click=S.move_template(t.template_id, 1),
                disabled=t.is_last | busy,
            ),
            _template_tool(
                "pencil", "Editar", on_click=S.start_edit_template(t.template_id), disabled=busy
            ),
            _template_tool(
                "trash-2", "Borrar", on_click=S.ask_delete_template(t.template_id), disabled=busy
            ),
            spacing="1",
            flex_shrink="0",
        ),
        spacing="3",
        align="start",
        width="100%",
    )
    return card(
        rx.cond(S.template_confirm_delete_id == t.template_id, confirm, normal),
        padding="0.75rem",
        key=t.template_id,
    )


def _templates_list() -> rx.Component:
    return rx.cond(
        S.templates_ready,
        rx.cond(
            S.templates_empty,
            empty_state(
                "library",
                "Aún no tienes plantillas en esta cuenta",
                "Crea la primera con «Nueva plantilla»: un saludo, tus precios o tu horario, "
                "listos para responder más rápido.",
            ),
            rx.vstack(rx.foreach(S.templates, _template_row), spacing="2", width="100%"),
        ),
        rx.cond(
            S.templates_error != "",
            rx.fragment(),
            skeleton_rows(4, height="4rem", radius=T.RADIUS_CARD),
        ),
    )


def templates_manager() -> rx.Component:
    """«Administrar plantillas»: the account's library in a drawer. The form's «Guardar»
    is the drawer's one solid button."""
    return drawer(
        rx.vstack(
            rx.hstack(
                rx.cond(
                    S.templates_at_limit,
                    tone_badge(S.templates_counter, "warn"),
                    tone_badge(S.templates_counter, "neutral"),
                ),
                rx.text("plantillas", size="1", color=T.TEXT_MUTED),
                rx.spacer(),
                rx.button(
                    rx.icon("plus", size=T.ICON_SM),
                    "Nueva plantilla",
                    on_click=S.start_new_template,
                    disabled=S.templates_at_limit | S.template_form_open | ~S.templates_ready,
                    variant="soft",
                    size="2",
                    type="button",
                ),
                width="100%",
                align="center",
                spacing="2",
            ),
            rx.cond(
                S.templates_at_limit,
                callout(
                    f"Llegaste al máximo de {MAX_TEMPLATES_PER_ACCOUNT} plantillas en esta "
                    "cuenta. Borra alguna que no uses para crear otra.",
                    "info",
                ),
                rx.fragment(),
            ),
            rx.cond(
                S.templates_error != "",
                rx.vstack(
                    callout(S.templates_error, "error"),
                    _retry_button("Reintentar", S.load_templates),
                    spacing="2",
                    width="100%",
                ),
                rx.fragment(),
            ),
            _template_form(),
            _templates_list(),
            spacing="3",
            width="100%",
        ),
        open=S.templates_manager_open,
        on_open_change=S.set_templates_manager_open,
        title=S.templates_account_label,
        icon="library",
        description=(
            "Mensajes guardados para empezar una respuesta. Los eliges en «Plantillas» y "
            "siempre puedes cambiarlos antes de enviar."
        ),
    )


def _composer() -> rx.Component:
    return rx.vstack(
        rx.cond(S.account_blocked_notice != "", callout(S.account_blocked_notice, "warn")),
        rx.cond(
            S.window_notice != "",
            rx.hstack(
                rx.icon(
                    rx.cond(S.open_thread.window_open, "clock", "clock-alert"),
                    size=T.ICON_SM,
                    color=T.TEXT_MUTED,
                ),
                rx.text(S.window_notice, size="1", color=T.TEXT_MUTED),
                spacing="2",
                align="center",
                class_name="q-conv-window",
            ),
            rx.fragment(),
        ),
        _suggestion_chip(),
        _template_fill_notice(),
        _attachment_chip(),
        rx.text_area(
            value=S.draft_text,
            on_change=S.set_draft_text,
            placeholder="Escribe una respuesta…",
            disabled=~S.can_compose | S.recording,
            rows="3",
            resize="vertical",
            width="100%",
            class_name="q-conv-input",
        ),
        rx.hstack(
            rx.flex(
                _attach_button(
                    _MEDIA_UPLOAD_ID,
                    "image",
                    "Enviar una foto o un video",
                    MEDIA_ACCEPT,
                    MAX_MEDIA_BYTES,
                ),
                _attach_button(
                    _FILE_UPLOAD_ID,
                    "paperclip",
                    "Enviar un archivo (PDF)",
                    DOCUMENT_ACCEPT,
                    MAX_DOCUMENT_BYTES,
                ),
                _voice_controls(),
                _heart_button(),
                rx.cond(
                    S.attaching,
                    rx.text("Guardando el adjunto…", size="1", color=T.TEXT_MUTED),
                    rx.fragment(),
                ),
                wrap="wrap",
                gap="0.4rem",
                align="center",
                class_name="q-conv-tools",
            ),
            rx.spacer(),
            _templates_picker(),
            rx.button(
                rx.icon("sparkles", size=T.ICON_SM),
                "Sugerir respuesta",
                on_click=S.suggest_reply,
                loading=S.suggesting,
                disabled=~S.can_suggest,
                variant="soft",
                size="2",
                type="button",
                **T.tone_scheme("accent"),
            ),
            rx.button(
                rx.icon("send", size=T.ICON_SM),
                "Responder",
                on_click=S.send_reply,
                loading=S.sending,
                disabled=~S.can_send,
                size="2",
            ),
            width="100%",
            align="center",
            spacing="2",
            flex_wrap="wrap",
        ),
        rx.cond(
            S.compose_hint != "",
            rx.text(S.compose_hint, size="1", color=T.tone_color("warn", 11)),
            rx.text(S.reply_as, size="1", color=T.TEXT_MUTED),
        ),
        spacing="2",
        width="100%",
        padding_top="0.5rem",
        class_name="q-wa-composer",
    )


def _conversation() -> rx.Component:
    return card(
        rx.vstack(
            _conversation_header(),
            _banner(S.banner, S.banner_tone),
            rx.cond(
                S.conv_error != "",
                rx.vstack(
                    callout(S.conv_error, "error"),
                    _retry_button("Reintentar", S.load_conversation),
                    width="100%",
                    spacing="3",
                ),
                rx.cond(S.conv_ready, _messages(), skeleton_rows(4, height="3rem")),
            ),
            _composer(),
            spacing="3",
            width="100%",
        ),
        padding="1rem",
        class_name="q-card q-conv-card",
        width="100%",
    )


def _placeholder() -> rx.Component:
    """The right pane without a conversation: a quiet hint, not a full empty state."""
    return rx.center(
        rx.vstack(
            rx.box(rx.icon("message-square-text", size=22), class_name="q-conv-placeholder-glyph"),
            rx.text("Elige una conversación", size="2", weight="medium"),
            rx.text(
                "Ábrela para leer el historial y responder desde la cuenta correcta.",
                size="1",
                color=T.TEXT_MUTED,
                text_align="center",
            ),
            spacing="1",
            align="center",
            max_width="20rem",
        ),
        class_name="q-conv-placeholder",
        width="100%",
    )


def _conversation_pane() -> rx.Component:
    return rx.box(
        rx.cond(
            S.has_open_thread,
            _conversation(),
            rx.vstack(_banner(S.banner, S.banner_tone), _placeholder(), width="100%"),
        ),
        class_name="q-wa-chats__conv",
        width="100%",
    )


# ======================================================================================
# Page
# ======================================================================================


def _no_accounts_state() -> rx.Component:
    return empty_state(
        "messages-square",
        "Aún no hay una cuenta de Instagram conectada",
        "Conecta la cuenta de Instagram del negocio en Conexiones, concediendo el permiso "
        "de mensajes, y sus conversaciones privadas aparecerán aquí.",
        action=rx.link(
            rx.button(rx.icon("link", size=T.ICON_SM), "Ir a Conexiones", size="2"),
            href="/connections",
        ),
    )


def _chats() -> rx.Component:
    return rx.vstack(
        access_banner(),
        rx.box(
            _list_pane(),
            _conversation_pane(),
            class_name=rx.cond(
                S.has_open_thread,
                "q-wa-chats q-conv-chats q-wa-chats--open",
                "q-wa-chats q-conv-chats",
            ),
        ),
        templates_manager(),
        spacing="4",
        width="100%",
    )


def _inbox() -> rx.Component:
    """Two views (m-24789646): the private inbox, and the commercial queries found in
    Interacciones waiting to be answered in private (`followups_page.py`)."""
    return rx.vstack(
        followups_toggle(),
        rx.cond(FollowupsState.showing_queries, followups_panel(), _chats()),
        spacing="4",
        width="100%",
    )


def _body() -> rx.Component:
    return page_body(
        _heartbeat(),
        rx.script(src="/qualify-voice.js"),
        rx.cond(
            S.load_error != "",
            rx.vstack(
                callout(S.load_error, "error"),
                _retry_button("Reintentar", S.load_accounts),
                width="100%",
                spacing="3",
            ),
            rx.cond(
                ~S.accounts_loaded,
                rx.vstack(skeleton_rows(1, height="2.25rem"), skeleton_rows(4, height="5.5rem")),
                rx.cond(S.show_no_accounts, _no_accounts_state(), _inbox()),
            ),
        ),
    )


def conversations_index() -> rx.Component:
    return app_shell(conversations_header(), _body())

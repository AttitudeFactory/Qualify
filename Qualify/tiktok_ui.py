"""TikTok on screen (m-24921091): the TikTok part of «Tus redes» and the «Enviar a TikTok
como borrador» card of an approved piece.

Design-system pieces only (`card`, `callout`, `tone_badge`, `signal_pill`,
`platform_badge`, `loading_spinner`, Radix buttons and `alert_dialog`); every state is a
word, never a colour alone; tap targets ≥ 44 px (N12). Never the page's one solid button
except where TikTok IS the next step (the «TikTok conectado» panel, the draft card's send).
"""

from __future__ import annotations

import reflex as rx

from .connection_copy import NO_ACCESS, RECONNECT_ACTION
from .connections_page import status_badge
from .connections_state import ConnectionsState
from .creative_state import CreativeState
from .tiktok_state import TikTokConnectionsState, TikTokDraftState
from .tiktok_vm import (
    CAN_DO,
    CONNECT_ACTION,
    CONNECTED_BODY,
    CONNECTED_TITLE,
    DISCONNECT_BODY,
    DISCONNECT_TITLE,
    DRAFT_ACCOUNT_PREFIX,
    DRAFT_ACTION,
    DRAFT_AGAIN,
    DRAFT_BODY,
    DRAFT_CONNECT_HINT,
    DRAFT_CONNECT_LINK,
    DRAFT_PILLS,
    DRAFT_RECONNECT_HINT,
    DRAFT_RECONNECT_LINK,
    DRAFT_RETRY,
    DRAFT_TITLE,
    DRAFTS_ONLY_NOTE,
    INVITE_BODY,
    INVITE_TITLE,
    UNAVAILABLE_NOTE,
    TikTokAccountVM,
)
from .ui import callout, card, loading_spinner, platform_badge, signal_pill, tone_badge
from .ui import tokens as T

_TAP = "44px"


# --- «Tus redes» ----------------------------------------------------------------------


def _connect_notice() -> rx.Component:
    """The result of the TikTok round trip; tone picked among pre-built callouts."""
    message = TikTokConnectionsState.connect_notice
    return rx.match(
        TikTokConnectionsState.connect_notice_tone,
        ("ok", callout(message, "ok")),
        ("info", callout(message, "info")),
        callout(message, "warn"),
    )


def tiktok_connected_panel() -> rx.Component:
    """«TikTok conectado» (N3): the result in plain words and ONE solid button to the next
    job — back where the owner came from (`?volver=`, e.g. the piece they wanted to send)
    or on to «Crear una publicación» — plus a soft one to stay."""
    return callout(
        rx.vstack(
            rx.heading(CONNECTED_TITLE, size="4", as_="h2"),
            rx.text(CONNECTED_BODY, size="2"),
            rx.flex(
                rx.button(
                    rx.icon("arrow-right", size=16),
                    ConnectionsState.continue_label,
                    on_click=ConnectionsState.continue_after_connect,
                    size="3",
                    min_height=_TAP,
                ),
                rx.button(
                    "Ver mis redes",
                    on_click=TikTokConnectionsState.dismiss_connected,
                    variant="soft",
                    size="3",
                    min_height=_TAP,
                    **T.tone_scheme("neutral"),
                ),
                gap="3",
                wrap="wrap",
                margin_top="0.25rem",
            ),
            spacing="2",
            align_items="start",
            width="100%",
        ),
        "ok",
        icon="circle-check",
    )


def tiktok_notices() -> rx.Component:
    """What the last TikTok round trip and the last TikTok action left to say — above the
    lists, never replacing them."""
    return rx.fragment(
        rx.cond(
            TikTokConnectionsState.connected_ok,
            tiktok_connected_panel(),
            rx.cond(TikTokConnectionsState.connect_notice != "", _connect_notice()),
        ),
        rx.cond(
            TikTokConnectionsState.action_error != "",
            callout(TikTokConnectionsState.action_error, "warn"),
        ),
    )


def _disconnect(account: TikTokAccountVM) -> rx.Component:
    """Disconnect with confirmation (§6.2): same verb on the button, title and result."""
    return rx.alert_dialog.root(
        rx.alert_dialog.trigger(
            rx.button(
                rx.icon("unplug", size=15),
                "Desconectar",
                variant="soft",
                size="3",
                min_height=_TAP,
                loading=TikTokConnectionsState.busy_ids.contains(account.id),
                **T.tone_scheme("neutral"),
            ),
        ),
        rx.alert_dialog.content(
            rx.alert_dialog.title(DISCONNECT_TITLE),
            rx.alert_dialog.description(
                rx.text(rx.text.strong(account.name), ". ", DISCONNECT_BODY),
            ),
            rx.flex(
                rx.alert_dialog.cancel(
                    rx.button(
                        "Cancelar",
                        variant="soft",
                        size="3",
                        min_height=_TAP,
                        **T.tone_scheme("neutral"),
                    ),
                ),
                rx.alert_dialog.action(
                    rx.button(
                        "Desconectar",
                        on_click=TikTokConnectionsState.disconnect(account.id),
                        size="3",
                        min_height=_TAP,
                        **T.tone_scheme("error"),
                    ),
                ),
                spacing="3",
                margin_top="1rem",
                justify="end",
                wrap="wrap",
            ),
        ),
    )


def _problem(account: TikTokAccountVM) -> rx.Component:
    """The fix, inside the callout that names the problem (§6.3)."""
    return callout(
        rx.flex(
            rx.text(account.problem, size="2"),
            rx.button(
                rx.icon("refresh-cw", size=15),
                RECONNECT_ACTION,
                on_click=TikTokConnectionsState.reconnect(account.id),
                loading=TikTokConnectionsState.connecting,
                disabled=~TikTokConnectionsState.available,
                variant="soft",
                size="3",
                min_height=_TAP,
                **T.tone_scheme("warn"),
            ),
            direction="column",
            align="start",
            gap="3",
            width="100%",
        ),
        "warn",
    )


def tiktok_account_card(account: TikTokAccountVM) -> rx.Component:
    """One TikTok account, read like the Instagram card: which account and whether it
    works (in words), what it can do, the fix when something is off, then disconnect."""
    return card(
        rx.vstack(
            rx.flex(
                rx.hstack(
                    platform_badge("tiktok"),
                    rx.heading(account.name, size="4", as_="h3", word_break="break-word"),
                    spacing="2",
                    align="center",
                    min_width="0",
                ),
                # A missing permission on a live account is «Sin acceso» (§7.3), like the
                # Instagram card; otherwise the shared «Conectada / Desconectada».
                rx.cond(
                    (account.status == "active") & (account.problem != ""),
                    tone_badge(NO_ACCESS, "warn", icon="lock-keyhole", size="2"),
                    status_badge(account.status),
                ),
                justify="between",
                align="center",
                wrap="wrap",
                gap="2",
                width="100%",
            ),
            rx.cond(
                account.can_send,
                rx.hstack(
                    rx.icon(
                        "circle-check",
                        size=16,
                        color=T.tone_color("ok", 9),
                        flex_shrink="0",
                        margin_top="2px",
                    ),
                    rx.text(rx.text.strong("Puedes:"), " ", CAN_DO, size="2"),
                    spacing="2",
                    align="start",
                    width="100%",
                ),
            ),
            rx.cond(account.can_send, rx.text(DRAFTS_ONLY_NOTE, size="2", color=T.TEXT_MUTED)),
            rx.cond(account.notice != "", callout(account.notice, "info", icon="flask-conical")),
            rx.cond(account.problem != "", _problem(account)),
            rx.divider(),
            rx.flex(
                rx.cond(account.status != "revoked", _disconnect(account)),
                justify="end",
                width="100%",
            ),
            spacing="3",
            align_items="start",
            width="100%",
        ),
        padding="1.25rem",
    )


def _invite_card() -> rx.Component:
    """No TikTok yet: the benefit first, then the one way to get it. `soft`: the page's
    solid stays Instagram's (the network everything else on Qualify runs on)."""
    return card(
        rx.vstack(
            rx.hstack(
                platform_badge("tiktok"),
                rx.heading(INVITE_TITLE, size="4", as_="h3"),
                spacing="2",
                align="center",
                wrap="wrap",
            ),
            rx.text(INVITE_BODY, size="2"),
            rx.text(DRAFTS_ONLY_NOTE, size="2", color=T.TEXT_MUTED),
            rx.button(
                rx.icon("plus", size=16),
                CONNECT_ACTION,
                on_click=TikTokConnectionsState.start_connect,
                loading=TikTokConnectionsState.connecting,
                variant="soft",
                size="3",
                min_height=_TAP,
            ),
            spacing="3",
            align_items="start",
            width="100%",
        ),
        padding="1.25rem",
    )


def tiktok_section() -> rx.Component:
    """The TikTok block of «Tus redes». Hidden when the deployment has no TikTok app and
    nothing is connected; with an account but no app, the card still lets the owner
    disconnect it and says that connecting is not possible from here for now."""
    return rx.cond(
        TikTokConnectionsState.show_section,
        rx.vstack(
            rx.heading("TikTok", size="3", as_="h2", color=T.TEXT_MUTED),
            rx.cond(
                TikTokConnectionsState.load_error != "",
                callout(TikTokConnectionsState.load_error, "error"),
                rx.cond(
                    TikTokConnectionsState.has_accounts,
                    rx.vstack(
                        rx.foreach(TikTokConnectionsState.accounts, tiktok_account_card),
                        rx.cond(
                            ~TikTokConnectionsState.available,
                            rx.text(UNAVAILABLE_NOTE, size="2", color=T.TEXT_MUTED),
                        ),
                        spacing="4",
                        width="100%",
                    ),
                    _invite_card(),
                ),
            ),
            spacing="3",
            width="100%",
            margin_top="0.5rem",
        ),
    )


# --- an approved piece ------------------------------------------------------------------


def _draft_pill() -> rx.Component:
    return rx.match(
        TikTokDraftState.draft.status,
        *[(status, signal_pill(label, tone)) for status, (label, tone) in DRAFT_PILLS.items()],
        rx.fragment(),
    )


def _draft_status() -> rx.Component:
    """The last draft sent: its pill and what happens now, in the backend's words."""
    draft = TikTokDraftState.draft
    return rx.cond(
        draft.status != "",
        rx.vstack(
            _draft_pill(),
            rx.hstack(
                rx.cond(draft.in_progress, loading_spinner("sm")),
                rx.text(draft.message, size="2"),
                spacing="2",
                align="center",
            ),
            spacing="2",
            align_items="start",
            width="100%",
        ),
    )


def _send_button() -> rx.Component:
    """«Enviar a TikTok como borrador» — the next step once a video is approved, so it is
    solid; «Intentar de nuevo» after a failure; «Enviar otra vez» (soft) once it landed —
    which for the same approved version returns the draft already sent, never a second."""
    draft = TikTokDraftState.draft
    label = rx.cond(draft.failed, DRAFT_RETRY, rx.cond(draft.done, DRAFT_AGAIN, DRAFT_ACTION))
    return rx.cond(
        draft.in_progress,
        rx.fragment(),
        rx.cond(
            draft.done,
            rx.button(
                rx.icon("send", size=16),
                label,
                on_click=TikTokDraftState.send,
                loading=TikTokDraftState.sending,
                disabled=~TikTokDraftState.can_send,
                variant="soft",
                size="3",
                min_height=_TAP,
            ),
            rx.button(
                rx.icon("send", size=16),
                label,
                on_click=TikTokDraftState.send,
                loading=TikTokDraftState.sending,
                disabled=~TikTokDraftState.can_send,
                size="3",
                min_height=_TAP,
            ),
        ),
    )


def _go_connect(hint: str, link: str) -> rx.Component:
    return rx.vstack(
        rx.text(hint, size="2"),
        rx.link(
            rx.button(
                rx.icon("plug", size=16),
                link,
                variant="soft",
                size="3",
                min_height=_TAP,
            ),
            href=TikTokDraftState.connect_href,
        ),
        spacing="2",
        align_items="start",
    )


def tiktok_draft_card() -> rx.Component:
    """«Llévalo también a TikTok»: for an APPROVED piece that is one video. With an
    account: send it to the drafts and follow its status. Without one: the way to connect
    it, coming back here. Never a date, never «publicar»: the owner publishes in TikTok."""
    approved = CreativeState.draft & (CreativeState.draft.status == "approved")
    return rx.cond(
        approved & TikTokDraftState.show_card,
        card(
            rx.vstack(
                rx.hstack(
                    platform_badge("tiktok"),
                    rx.heading(DRAFT_TITLE, size="4", as_="h2"),
                    spacing="2",
                    align="center",
                    wrap="wrap",
                ),
                rx.text(DRAFT_BODY, size="2"),
                rx.cond(
                    TikTokDraftState.account_id != "",
                    rx.vstack(
                        rx.text(
                            DRAFT_ACCOUNT_PREFIX,
                            rx.text.strong(TikTokDraftState.account_name),
                            size="2",
                            color=T.TEXT_MUTED,
                        ),
                        _draft_status(),
                        rx.cond(
                            TikTokDraftState.error != "",
                            callout(TikTokDraftState.error, "warn"),
                        ),
                        _send_button(),
                        spacing="3",
                        align_items="start",
                        width="100%",
                    ),
                    rx.cond(
                        TikTokDraftState.needs_reconnect,
                        _go_connect(DRAFT_RECONNECT_HINT, DRAFT_RECONNECT_LINK),
                        _go_connect(DRAFT_CONNECT_HINT, DRAFT_CONNECT_LINK),
                    ),
                ),
                spacing="3",
                align_items="start",
                width="100%",
            ),
            padding="1.25rem",
            id="tiktok-borrador",
        ),
    )

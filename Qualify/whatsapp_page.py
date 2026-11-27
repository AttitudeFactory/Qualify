"""The WhatsApp number's pages (WA-12): the shared shell + the panels of what was «Tu
número» (Estado, Perfil, Formas de pago, Códigos QR, Actividad).

**«Tu número» left `/whatsapp` (m-25027373, BU-A10).** Founder: «el otro módulo solo
sería … para configuración». Each panel has its own page, served by `WhatsAppState`:

    Estado          → the number's card in «Tus redes» (`number_card_status`,
                      `number_card_details`, drawn by `connections_page`)
    Actividad       → `/connections/whatsapp/actividad` (`whatsapp_activity_index`)
    Perfil          → `/chats/ajustes/whatsapp/perfil` (`whatsapp_profile_index`)
    Códigos QR      → `/chats/ajustes/whatsapp/codigos-qr` (`whatsapp_qr_index`)
    Formas de pago  → `/chats/ajustes/formas-de-pago` (`whatsapp_payments_index`)

`/whatsapp` draws nothing (`whatsapp_index`): every address of it redirects once to the
new place (`whatsapp_vm.legacy_panel_target`) and the menu has no «WhatsApp» entry.

Layout, per docs/design-system.md §9.1: `app_shell(page_header(...), page_body(...))`;
every state is a TONE (`ok`/`warn`/`error`/`info`/`neutral`) through `signal_pill` /
`tone_badge` / `callout`, never a raw Radix colour; identity through
`platform_badge("whatsapp")`.

**The shell** (m-24842998). Header + number selector (only when the tenant has more than
one number) + the page's strip of panels, if it has one (only «Promociones por
WhatsApp» does) + the active panel's body. From `md` up the strip is a segmented control;
on a phone it is a grid of 44 px buttons, so it fits at 360 px without sliding sideways
(N12).

**No chats here (m-25029799, BU-A11).** WhatsApp's chats are attended only in «Por
responder», beside Instagram's (`whatsapp_tab_chats` keeps the open chat that pane
mounts). An old address of the list redirects there (`whatsapp_vm.legacy_chat_target`).

**«Promociones por WhatsApp»** (m-25017862, decision D3): the promotions panels (Enviadas
· Mensajes aprobados · Clientes que aceptaron) left the strip for their own menu entry,
next to «Anuncios», at `/whatsapp/promociones` (`whatsapp_promotions_index`). Same
state, same panels, same number selector; only the header and the strip differ. The body renders
ONLY the active panel, inside a box keyed by `WhatsAppState.selected_connection_id`, so a
panel's root `on_mount` fires on entry and on every number switch: that is how Perfil
and QR load their data, and how the automatic reply (WA-16, `whatsapp_tab_menu.py`)
plugs in from its own file.
"""

from __future__ import annotations

import reflex as rx

from .ui import (
    app_shell,
    callout,
    card,
    dropzone,
    empty_state,
    kv,
    media_thumb,
    mono,
    page_body,
    page_header,
    platform_badge,
    signal_pill,
    skeleton_card,
    skeleton_rows,
    tag,
)
from .ui import tokens as T
from .ui.route_history import route_history
from .whatsapp_location_ui import back_to_chat_link, map_point_block
from .whatsapp_menu_state import WhatsAppMenuState
from .whatsapp_metrics_block import metrics_block
from .whatsapp_payments_vm import HELP as PAYMENTS_HELP
from .whatsapp_payments_vm import TITLE as PAYMENTS_TITLE
from .whatsapp_state import WhatsAppState
from .whatsapp_tab_campaigns import campaigns_tab
from .whatsapp_tab_contacts import contacts_tab
from .whatsapp_tab_menu import back_to_guided, menu_step_frame, menu_tab
from .whatsapp_tab_payments import payments_tab
from .whatsapp_tab_templates import templates_tab
from .whatsapp_vm import (
    ACCOUNT_PARAM,
    ACTIVITY_PAGE_TITLE,
    ACTIVITY_ROUTE,
    ACTIVITY_SUBTITLE,
    ACTIVITY_TITLE,
    CHAT_SETTINGS_ROUTE,
    CHAT_SETTINGS_TITLE,
    CONNECTIONS_ROUTE,
    CONNECTIONS_TITLE,
    MAX_ABOUT_CHARS,
    MAX_ADDRESS_CHARS,
    MAX_DESCRIPTION_CHARS,
    MAX_EMAIL_CHARS,
    MAX_QR_MESSAGE_CHARS,
    MAX_WEBSITE_CHARS,
    MENU_SUBTITLE,
    MENU_TITLE,
    NO_NUMBER_ACTION,
    NO_NUMBER_GAINS,
    NO_NUMBER_NEXT,
    NO_NUMBER_TITLE,
    PROFILE_PAGE_TITLE,
    PROFILE_SUBTITLE,
    PROMOTION_SUBS,
    PROMOTIONS_SUBTITLE,
    PROMOTIONS_TITLE,
    QR_CHANNELS,
    QR_SUBTITLE,
    QR_TITLE,
    REVIEW_ACTION,
    SECTION_PROMOTIONS,
    TAB_ACTIVITY,
    TAB_CAMPAIGNS,
    TAB_CONNECTION,
    TAB_CONTACTS,
    TAB_MENU,
    TAB_PAYMENTS,
    TAB_PROFILE,
    TAB_QR,
    TAB_TEMPLATES,
    VERTICALS,
    QrCodeVM,
    WhatsAppNumberVM,
)

_TONES = ("ok", "warn", "error", "info", "neutral")
# N12: every target of the strips and the no-number state is at least 44 px tall.
_TAP = {"min_height": "44px"}
_DESKTOP_ONLY = rx.breakpoints(initial="none", md="flex")
_PHONE_ONLY = rx.breakpoints(initial="grid", md="none")
_PHOTO_UPLOAD_ID = "whatsapp_profile_photo"
_PHOTO_ACCEPT = {"image/jpeg": [".jpg", ".jpeg"], "image/png": [".png"]}


# ======================================================================================
# Tone helpers — the VM ships the tone as data, the system needs it at build time.
# ======================================================================================


def tone_pill(label: rx.Var[str], tone: rx.Var[str]) -> rx.Component:
    """`signal_pill` for a tone that is a Var (the VM decides it per row)."""
    return rx.match(
        tone,
        *[(t, signal_pill(label, t)) for t in _TONES[:-1]],
        signal_pill(label, "neutral"),
    )


def banner(message: rx.Var[str], tone: rx.Var[str]) -> rx.Component:
    """A `callout` in a Var tone, shown only when there is a message."""
    return rx.cond(
        message != "",
        rx.match(
            tone,
            *[(t, callout(message, t)) for t in _TONES[:-1]],
            callout(message, "neutral"),
        ),
        rx.fragment(),
    )


def retry_button(label: str, on_click: rx.event.EventHandler) -> rx.Component:
    """Shown in place of a tab's content when its read failed (the banner says why)."""
    return rx.button(
        rx.icon("refresh-cw", size=T.ICON_SM),
        label,
        on_click=on_click,
        variant="soft",
        size="2",
        **T.tone_scheme("neutral"),
    )


# ======================================================================================
# Shell
# ======================================================================================


def _number_item(number: WhatsAppNumberVM) -> rx.Component:
    return rx.select.item(number.label, value=number.connection_id)


def number_selector() -> rx.Component:
    """Shown only when the tenant has more than one WhatsApp number."""
    return rx.cond(
        WhatsAppState.has_many_numbers,
        rx.select.root(
            # m-25029799 (UX review): on a phone the column's width, leaving room for
            # the theme button on the same row; 280 px from `sm` up. 44 px tall (N12).
            rx.select.trigger(
                placeholder="Elige un número",
                width=rx.breakpoints(initial="calc(100% - 4.5rem)", sm="280px"),
                min_height="44px",
            ),
            rx.select.content(rx.foreach(WhatsAppState.numbers, _number_item)),
            value=WhatsAppState.selected_connection_id,
            on_change=WhatsAppState.select_connection,
        ),
        rx.fragment(),
    )


def _phone_choice(
    key: str, label: str, value: rx.Var[str], on_pick: rx.event.EventHandler
) -> rx.Component:
    """One tab as a button, for the phone grid. `aria-pressed` says which one is on."""
    active = value == key
    return rx.button(
        label,
        on_click=on_pick(key),
        variant=rx.cond(active, "soft", "ghost"),
        size="2",
        width="100%",
        height="auto",
        white_space="normal",
        padding_y="0.5rem",
        custom_attrs={"aria-pressed": rx.cond(active, "true", "false")},
        **_TAP,
        **T.tone_scheme("neutral"),
    )


def _choice_strip(
    options: tuple[tuple[str, str], ...],
    value: rx.Var[str],
    on_pick: rx.event.EventHandler,
    *,
    label: str,
    phone_columns: str,
    size: str,
) -> rx.Component:
    """N12: the same choices as a `segmented_control` from `md` up and, on a phone, as a
    grid of buttons that all fit at 360 px without sliding sideways."""
    return rx.fragment(
        rx.flex(
            rx.segmented_control.root(
                *[rx.segmented_control.item(text, value=key) for key, text in options],
                value=value,
                on_change=on_pick,
                size=size,
            ),
            display=_DESKTOP_ONLY,
            width="100%",
        ),
        rx.grid(
            *[_phone_choice(key, text, value, on_pick) for key, text in options],
            columns=phone_columns,
            spacing="2",
            display=_PHONE_ONLY,
            width="100%",
            role="group",
            aria_label=label,
        ),
    )


def sub_strip() -> rx.Component:
    """Promociones por WhatsApp › Enviadas · Mensajes aprobados · Clientes que aceptaron
    — the one strip left: «Tu número»'s sub-tabs are pages of their own (m-25027373)."""
    return rx.cond(
        WhatsAppState.active_section == SECTION_PROMOTIONS,
        _choice_strip(
            PROMOTION_SUBS,
            WhatsAppState.active_sub,
            WhatsAppState.select_sub,
            label=PROMOTIONS_TITLE,
            phone_columns="3",
            size="2",
        ),
        rx.fragment(),
    )


def activity_tab() -> rx.Component:
    """Actividad: the number's metrics (WA-14) — a page under «Tus redes» since
    m-25027373."""
    return rx.vstack(metrics_block(), spacing="4", width="100%", align_items="start")


def tab_body() -> rx.Component:
    """Only the active panel is in the tree; the key remounts it on a number switch.
    «Estado» (`TAB_CONNECTION`) has no panel here: it is the number's card in «Tus
    redes» (m-25027373)."""
    return rx.box(
        rx.match(
            WhatsAppState.active_tab,
            (TAB_PROFILE, profile_tab()),
            (TAB_PAYMENTS, payments_tab(heading=False)),
            (TAB_QR, qr_tab()),
            (TAB_ACTIVITY, activity_tab()),
            (TAB_MENU, menu_tab()),
            (TAB_TEMPLATES, templates_tab()),
            (TAB_CONTACTS, contacts_tab()),
            (TAB_CAMPAIGNS, campaigns_tab()),
            rx.fragment(),
        ),
        key=f"{WhatsAppState.selected_connection_id}:{WhatsAppState.active_tab}",
        class_name="q-settle q-content-ready",
        width="100%",
    )


def _gain(text: str) -> rx.Component:
    return rx.hstack(
        rx.icon("check", size=T.ICON_SM, color=T.tone_color("ok", 11), flex_shrink="0"),
        rx.text(text, size="2", text_align="left"),
        spacing="2",
        align="start",
        width="100%",
    )


def _no_numbers_state() -> rx.Component:
    """N8: no dead end. What the owner gains, then one button that asks the team."""
    return empty_state(
        "message-circle",
        NO_NUMBER_TITLE,
        "Con tu número conectado:",
        action=rx.vstack(
            rx.vstack(*[_gain(text) for text in NO_NUMBER_GAINS], spacing="2", width="100%"),
            rx.text(NO_NUMBER_NEXT, size="2", color=T.TEXT_MUTED, text_align="center"),
            rx.cond(
                WhatsAppState.connect_request_notice != "",
                callout(WhatsAppState.connect_request_notice, "ok"),
                rx.button(
                    rx.icon("send", size=16),
                    NO_NUMBER_ACTION,
                    on_click=WhatsAppState.request_connection,
                    loading=WhatsAppState.connect_request_sending,
                    size="3",
                    width=rx.breakpoints(initial="100%", sm="auto"),
                    **_TAP,
                ),
            ),
            rx.cond(
                WhatsAppState.connect_request_error != "",
                callout(WhatsAppState.connect_request_error, "error"),
                rx.fragment(),
            ),
            spacing="3",
            align="center",
            width="100%",
            max_width="440px",
        ),
    )


def whatsapp_invite_card() -> rx.Component:
    """No WhatsApp number yet (UX review U1, m-25027373): one more card in «Tus redes»,
    read like the Instagram invite — the network, what the owner gains, the one way to
    get it. The texts and the request are the no-number state's own (WhatsApp numbers
    are connected by the Qualify team, WA-05). Soft, never the page's one solid (P3)."""
    return card(
        rx.vstack(
            platform_badge("whatsapp"),
            rx.heading(NO_NUMBER_TITLE, size="4", as_="h2"),
            rx.text("Con tu número conectado:", size="2"),
            rx.vstack(*[_gain(text) for text in NO_NUMBER_GAINS], spacing="2", width="100%"),
            rx.text(NO_NUMBER_NEXT, size="2", color=T.TEXT_MUTED),
            rx.cond(
                WhatsAppState.connect_request_notice != "",
                callout(WhatsAppState.connect_request_notice, "ok"),
                rx.button(
                    rx.icon("send", size=16),
                    NO_NUMBER_ACTION,
                    on_click=WhatsAppState.request_connection,
                    loading=WhatsAppState.connect_request_sending,
                    variant="soft",
                    size="3",
                    width=rx.breakpoints(initial="100%", sm="auto"),
                    **_TAP,
                ),
            ),
            rx.cond(
                WhatsAppState.connect_request_error != "",
                callout(WhatsAppState.connect_request_error, "error"),
                rx.fragment(),
            ),
            spacing="3",
            align_items="start",
            width="100%",
        ),
        padding="1.25rem",
        custom_attrs={"data-invite": "whatsapp"},
    )


def _on_promotions_page() -> rx.Var[bool]:
    """Whether the panel in the shared state is one of «Promociones por WhatsApp»."""
    return WhatsAppState.active_section == SECTION_PROMOTIONS


def _whatsapp_body(*strips: rx.Component, mine: rx.Var[bool]) -> rx.Component:
    """Loading, error and no-number states, then the page's `strips` and the panel.

    m-25017862: both pages read the one shared `active_tab`, which the arriving page's
    `enter_page` sets a server round trip AFTER the client has switched page. Until then
    `mine` is false and the page shows a skeleton — never the other page's panel under
    its own header, and never that panel's `on_mount` load (the QR codes', say)."""
    panel = rx.cond(
        mine,
        rx.fragment(*strips, tab_body()),
        rx.vstack(skeleton_rows(1, height="2.25rem"), skeleton_card(5), width="100%"),
    )
    return page_body(
        rx.cond(
            WhatsAppState.load_error != "",
            callout(WhatsAppState.load_error, "error"),
            rx.cond(
                WhatsAppState.is_loading & ~WhatsAppState.has_numbers,
                rx.vstack(skeleton_rows(1, height="2.25rem"), skeleton_card(5), width="100%"),
                rx.cond(
                    WhatsAppState.show_empty_state,
                    _no_numbers_state(),
                    rx.vstack(
                        rx.cond(
                            WhatsAppState.number_needs_help
                            & (WhatsAppState.active_tab != TAB_CONNECTION),
                            rx.vstack(
                                banner(
                                    WhatsAppState.selected_number.health_label,
                                    WhatsAppState.selected_number.health_tone,
                                ),
                                _review_request(),
                                spacing="3",
                                width="100%",
                            ),
                            rx.fragment(),
                        ),
                        panel,
                        spacing="3",
                        width="100%",
                    ),
                ),
            ),
        ),
    )


def _history() -> rx.Component:
    return route_history(
        WhatsAppState.enter_history,
        ack=WhatsAppState.history_ack,
        on_leave=WhatsAppState.leave_page_flows,
    )


def whatsapp_index() -> rx.Component:
    """`/whatsapp` (m-25027373): nothing is drawn here any more. The page's history
    handler (`WhatsAppState.enter_history`, its mount) sends every address of it, once
    and with `replace`, to where that content lives now; meanwhile, a skeleton."""
    return app_shell(
        _history(),
        page_body(rx.vstack(skeleton_rows(1, height="2.25rem"), skeleton_card(5), width="100%")),
    )


def _on_settings_page() -> rx.Var[bool]:
    """Whether the panel in the shared state is the menu (m-25017861)."""
    return WhatsAppState.active_tab == TAB_MENU


def _on_panel(panel: str) -> rx.Var[bool]:
    """Whether the panel in the shared state is `panel` — the gate of a page that draws
    one panel (m-25027373): until the arriving page's `enter_page` sets it, the page
    shows a skeleton, never the previous page's panel nor its `on_mount` load."""
    return WhatsAppState.active_tab == panel


def _back_link(label: str, href: str) -> rx.Component:
    """«‹ <the place this page hangs from>» (N7)."""
    return rx.link(
        rx.hstack(
            rx.icon("chevron-left", size=T.ICON_SM),
            rx.text(label, size="2"),
            spacing="1",
            align="center",
        ),
        href=href,
        underline="none",
        color=T.TEXT_MUTED,
        display="inline-flex",
        align_items="center",
        min_height="44px",  # N12, as `back_to_guided` (`whatsapp_tab_menu.TARGET_MIN`)
    )


def back_to_chat_settings() -> rx.Component:
    """«‹ Ajustes de chats» (N7): the way back to the hub this page hangs from."""
    return _back_link(CHAT_SETTINGS_TITLE, CHAT_SETTINGS_ROUTE)


def back_to_connections() -> rx.Component:
    """«‹ Tus redes» (N7): Actividad hangs from the number's card there (m-25027373)."""
    return _back_link(CONNECTIONS_TITLE, CONNECTIONS_ROUTE)


def _panel_page(
    panel: str, title: str, subtitle: str, back: rx.Component, *, selector: bool = True
) -> rx.Component:
    """m-25027373: one of the number's old panels on its own page — the same panel,
    state, number selector (with two or more numbers; not where `selector` is False)
    and loading, error and no-number states as before; only the header and the way
    back are the page's."""
    return app_shell(
        _history(),
        page_header(title, subtitle, *([number_selector()] if selector else []), kicker=back),
        _whatsapp_body(mine=_on_panel(panel)),
    )


def whatsapp_profile_index() -> rx.Component:
    """`/chats/ajustes/whatsapp/perfil`: the number's profile and «Tu local en el mapa»
    (what «Cómo llegar» sends)."""
    return _panel_page(TAB_PROFILE, PROFILE_PAGE_TITLE, PROFILE_SUBTITLE, back_to_chat_settings())


def whatsapp_qr_index() -> rx.Component:
    """`/chats/ajustes/whatsapp/codigos-qr` (founder's decision: a setting)."""
    return _panel_page(TAB_QR, QR_TITLE, QR_SUBTITLE, back_to_chat_settings())


def whatsapp_payments_index() -> rx.Component:
    """`/chats/ajustes/formas-de-pago`: the row «Formas de pago» of «Para todos tus
    chats» opens the editor itself (before, a pointer to `/whatsapp`)."""
    # UX review U4: no number selector — the methods are the same for every number
    # (`SAME_FOR_ALL`, said on the page).
    return _panel_page(
        TAB_PAYMENTS, PAYMENTS_TITLE, PAYMENTS_HELP, back_to_chat_settings(), selector=False
    )


def whatsapp_activity_index() -> rx.Component:
    """`/connections/whatsapp/actividad`: the number's activity, reached from its card
    in «Tus redes»."""
    return _panel_page(TAB_ACTIVITY, ACTIVITY_PAGE_TITLE, ACTIVITY_SUBTITLE, back_to_connections())


def whatsapp_settings_index() -> rx.Component:
    """`/chats/ajustes/whatsapp` (m-25017861, decision D1): «Tu menú de bienvenida», out
    of the WhatsApp messages screen and into «Ajustes de chats». The same panel, state
    and number selector as before; with a menu, its four guided steps take the page.
    An old `/whatsapp?tab=respuesta` lands here (`legacy_settings_target`)."""
    return app_shell(
        _history(),
        rx.cond(
            _on_settings_page()
            & (WhatsAppMenuState.loaded_for == WhatsAppState.selected_connection_id)
            & WhatsAppMenuState.has_menu
            & ~WhatsAppMenuState.advanced_open,
            menu_step_frame(),
            rx.fragment(
                page_header(
                    MENU_TITLE,
                    MENU_SUBTITLE,
                    number_selector(),
                    kicker=rx.cond(
                        WhatsAppMenuState.advanced_open,
                        back_to_guided(),
                        back_to_chat_settings(),
                    ),
                ),
                _whatsapp_body(mine=_on_settings_page()),
            ),
        ),
    )


def whatsapp_promotions_index() -> rx.Component:
    """`/whatsapp/promociones` (m-25017862): «Promociones por WhatsApp», the menu entry
    next to «Anuncios». The same three panels and states as before, under their own
    header; the sub-tab strip is the page's only strip."""
    return app_shell(
        _history(),
        # The menu's own word (N1); `test_nav_one_name` reads it here, as a literal.
        page_header("Promociones por WhatsApp", PROMOTIONS_SUBTITLE, number_selector()),
        _whatsapp_body(sub_strip(), mine=_on_promotions_page()),
    )


# ======================================================================================
# Estado — the number's card in «Tus redes» (m-25027373)
# ======================================================================================

#: The line under «Verificar ahora» (unchanged from «Tu número › Estado»).
VERIFY_NOTE = (
    "«Verificar ahora» le pregunta a WhatsApp si tu número sigue bien conectado. Solo "
    "se hace cuando tú lo tocas."
)


def _is_shown(number: WhatsAppNumberVM) -> rx.Var[bool]:
    """Whether `number` is the one the shared state acts on (its last tapped card)."""
    return WhatsAppState.selected_connection_id == number.connection_id


def verify_button(number: WhatsAppNumberVM) -> rx.Component:
    """«Verificar ahora» for THIS number (`verify_number` checks the id is the
    business's); busy only on its own card."""
    return rx.button(
        rx.icon("shield-check", size=14),
        "Verificar ahora",
        on_click=WhatsAppState.verify_number(number.connection_id),
        loading=WhatsAppState.verifying & _is_shown(number),
        variant="soft",
        size="2",
        **_TAP,
        **T.tone_scheme("neutral"),
    )


def _kv_pill(label: str, value: rx.Var[str], tone: rx.Var[str]) -> rx.Component:
    return rx.hstack(
        rx.text(label, size="2", color=T.TEXT_MUTED, min_width="9rem"),
        tone_pill(value, tone),
        align="center",
        spacing="3",
        width="100%",
    )


def number_facts(number: rx.Var) -> rx.Component:
    """The Meta facts of what was «Tu número › Estado» (m-24842998); in «Tus redes»
    they sit behind the card's own «Más detalles» (m-25027373)."""
    return rx.grid(
        rx.vstack(
            kv("Número", number.display_phone_number, mono=True),
            kv("Nombre verificado", number.verified_name),
            _kv_pill("Estado del nombre", number.name_status_label, number.name_status_tone),
            _kv_pill("Calidad", number.quality_label, number.quality_tone),
            kv("Límite de mensajes", number.tier_label),
            spacing="3",
            width="100%",
        ),
        rx.vstack(
            _kv_pill(
                "Estado en WhatsApp",
                number.platform_status_label,
                number.platform_status_tone,
            ),
            kv("Marca", number.brand),
            # «Última verificación» is not repeated here: the card already says
            # «Última comprobación» (review C4).
            kv("Datos de WhatsApp al día", number.last_synced_at),
            kv("Último mensaje recibido", number.last_inbound_at),
            spacing="3",
            width="100%",
        ),
        columns=rx.breakpoints(initial="1", md="2"),
        spacing="4",
        width="100%",
    )


def _review_request() -> rx.Component:
    """N8 for a number that fails: the same support request as the no-number state."""
    return _review_block(WhatsAppState.request_connection, shown=True)


def _review_block(on_click: rx.event.EventSpec, *, shown: rx.Var[bool] | bool) -> rx.Component:
    """«Avisar al equipo de Qualify», or what came of it. The request's result is the
    shared state's, so on a card of «Tus redes» it shows only on the card that sent it
    (`shown`)."""

    def gate(condition: rx.Var[bool]) -> rx.Var[bool]:
        return condition if shown is True else shown & condition  # type: ignore[operator]

    return rx.vstack(
        rx.cond(
            gate(WhatsAppState.connect_request_notice != ""),
            callout(WhatsAppState.connect_request_notice, "ok"),
            rx.button(
                rx.icon("send", size=16),
                REVIEW_ACTION,
                on_click=on_click,
                loading=gate(WhatsAppState.connect_request_sending),
                size="3",
                width=rx.breakpoints(initial="100%", sm="auto"),
                **_TAP,
            ),
        ),
        rx.cond(
            gate(WhatsAppState.connect_request_error != ""),
            callout(WhatsAppState.connect_request_error, "error"),
            rx.fragment(),
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _for_number(connection_id: rx.Var[str], build: object) -> rx.Component:
    """`build(number)` for the WhatsApp number behind a «Tus redes» card (its
    `social_connections` id is the number's `connection_id`); nothing for any other."""
    return rx.foreach(
        WhatsAppState.numbers,
        lambda number: rx.cond(
            number.connection_id == connection_id,
            build(number),  # type: ignore[operator]
            rx.fragment(),
        ),
    )


def _troubled(number: WhatsAppNumberVM) -> rx.Var[bool]:
    """A connected number whose line warns (marked as unwanted) or fails (paused by
    WhatsApp): its «Verificar ahora» moves up, next to the line (UX review U3)."""
    return (number.status == "active") & (
        (number.health_tone == "warn") | (number.health_tone == "error")
    )


def _verify_block(number: WhatsAppNumberVM) -> rx.Component:
    """«Verificar ahora», what it found right under it (UX review U2: never far from
    the button) and its note."""
    return rx.vstack(
        verify_button(number),
        rx.cond(
            _is_shown(number),
            banner(WhatsAppState.connection_banner, WhatsAppState.connection_banner_tone),
            rx.fragment(),
        ),
        rx.text(VERIFY_NOTE, size="1", color=T.TEXT_MUTED),
        spacing="2",
        align_items="start",
        width="100%",
    )


def _card_status(number: WhatsAppNumberVM) -> rx.Component:
    """What the owner reads first on the number's card: the number's line when it says
    something the card's «Conectada» does not (a number still connecting, paused by
    WhatsApp or marked as unwanted) and, then, «Verificar ahora» and — when the owner
    cannot fix it alone — «Avisar al equipo de Qualify». A disconnected number's card
    already carries its own notice and help button (`connections_page`)."""
    active = number.status == "active"
    return rx.vstack(
        rx.cond(
            (active | (number.status == "pending")) & (number.health_tone != "ok"),
            banner(number.health_label, number.health_tone),
            rx.fragment(),
        ),
        rx.cond(_troubled(number), _verify_block(number), rx.fragment()),
        rx.cond(
            active & (number.health_tone == "error"),
            _review_block(
                WhatsAppState.request_review(number.connection_id), shown=_is_shown(number)
            ),
            rx.fragment(),
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _card_details(number: WhatsAppNumberVM) -> rx.Component:
    """The facts and — unless it is already above (U3) — «Verificar ahora»."""
    return rx.vstack(
        number_facts(number),
        rx.cond(
            (number.status == "active") & ~_troubled(number),
            _verify_block(number),
            rx.fragment(),
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )


def number_card_status(connection_id: rx.Var[str]) -> rx.Component:
    """«Tu número › Estado» on the WhatsApp card of «Tus redes» (m-25027373): the part
    above the card's divider."""
    return _for_number(connection_id, _card_status)


def number_card_details(connection_id: rx.Var[str]) -> rx.Component:
    """…and the part behind the card's «Más detalles»: the ten facts and «Verificar
    ahora» (`/debug_token` plus the number's own read — it also covers the card's
    «Comprobar ahora», which a WhatsApp card does not show)."""
    return _for_number(connection_id, _card_details)


def activity_href(connection_id: rx.Var[str]) -> rx.Var[str]:
    """`/connections/whatsapp/actividad?cuenta=<the number>`."""
    return f"{ACTIVITY_ROUTE}?{ACCOUNT_PARAM}=" + connection_id


def number_card_activity_link(connection_id: rx.Var[str]) -> rx.Component:
    """«Actividad»: the number's metrics, a page that hangs from its card."""
    return rx.link(
        rx.button(
            rx.icon("chart-no-axes-column", size=15),
            ACTIVITY_TITLE,
            variant="ghost",
            size="2",
            color_scheme="gray",
            type="button",
            # a ghost button pulls itself out by its padding: keep it clear of the
            # «Más detalles» beside it (seen at 360 px)
            margin="0",
            **_TAP,
        ),
        href=activity_href(connection_id),
        underline="none",
    )


# ======================================================================================
# Perfil
# ======================================================================================


def _field(label: str, control: rx.Component, hint: str | None = None) -> rx.Component:
    return rx.vstack(
        rx.text(label, size="2", weight="medium"),
        control,
        *([rx.text(hint, size="1", color=T.TEXT_FAINT)] if hint else []),
        spacing="1",
        width="100%",
        align_items="start",
    )


def _text_input(field: str, value: rx.Var[str], max_length: int, **props: object) -> rx.Component:
    return rx.input(
        value=value,
        on_change=lambda v: WhatsAppState.set_profile_field(field, v),
        max_length=max_length,
        width="100%",
        **props,
    )


def _photo_block() -> rx.Component:
    profile = WhatsAppState.profile
    return rx.hstack(
        media_thumb(
            profile.picture_url, size="72px", round=True, icon="store", alt="Foto de perfil"
        ),
        rx.vstack(
            rx.text("Foto de perfil", size="2", weight="medium"),
            dropzone(
                rx.hstack(
                    rx.cond(
                        WhatsAppState.photo_uploading,
                        rx.text("Subiendo foto…", size="2", color=T.TEXT_MUTED),
                        rx.hstack(
                            rx.icon("image-up", size=T.ICON_SM),
                            rx.text("Cambiar foto (JPG o PNG, hasta 5 MB)", size="2"),
                            spacing="2",
                            align="center",
                        ),
                    ),
                    align="center",
                ),
                upload_id=_PHOTO_UPLOAD_ID,
                accept=_PHOTO_ACCEPT,
                on_drop=WhatsAppState.handle_photo_upload(
                    rx.upload_files(upload_id=_PHOTO_UPLOAD_ID)
                ),
                variant="compact",
                disabled=WhatsAppState.photo_uploading,
            ),
            spacing="1",
            align_items="start",
        ),
        spacing="4",
        align="center",
        width="100%",
        wrap="wrap",
    )


def _vertical_select() -> rx.Component:
    return rx.select.root(
        rx.select.trigger(placeholder="Elige una categoría", width="100%"),
        rx.select.content(*[rx.select.item(label, value=key) for key, label in VERTICALS]),
        value=WhatsAppState.form_vertical,
        on_change=lambda v: WhatsAppState.set_profile_field("vertical", v),
    )


def profile_form() -> rx.Component:
    return card(
        rx.vstack(
            _photo_block(),
            rx.divider(),
            rx.grid(
                _field(
                    "Descripción corta",
                    _text_input("about", WhatsAppState.form_about, MAX_ABOUT_CHARS),
                    f"Lo primero que ve el cliente bajo tu nombre. Hasta {MAX_ABOUT_CHARS} "
                    "caracteres.",
                ),
                _field("Categoría", _vertical_select()),
                _field(
                    "Correo",
                    _text_input("email", WhatsAppState.form_email, MAX_EMAIL_CHARS, type="email"),
                ),
                _field(
                    "Dirección",
                    _text_input("address", WhatsAppState.form_address, MAX_ADDRESS_CHARS),
                ),
                _field(
                    "Web",
                    _text_input(
                        "website_1",
                        WhatsAppState.form_website_1,
                        MAX_WEBSITE_CHARS,
                        placeholder="https://",
                    ),
                ),
                _field(
                    "Otra web (opcional)",
                    _text_input(
                        "website_2",
                        WhatsAppState.form_website_2,
                        MAX_WEBSITE_CHARS,
                        placeholder="https://",
                    ),
                ),
                columns=rx.breakpoints(initial="1", md="2"),
                spacing="4",
                width="100%",
            ),
            # m-24945889: the point «Cómo llegar» sends, right under «Dirección»
            rx.divider(),
            map_point_block(),
            rx.divider(),
            _field(
                "Descripción",
                rx.text_area(
                    value=WhatsAppState.form_description,
                    on_change=lambda v: WhatsAppState.set_profile_field("description", v),
                    max_length=MAX_DESCRIPTION_CHARS,
                    rows="4",
                    width="100%",
                ),
                f"Hasta {MAX_DESCRIPTION_CHARS} caracteres.",
            ),
            rx.hstack(
                rx.button(
                    rx.icon("refresh-cw", size=T.ICON_SM),
                    "Volver a leer de WhatsApp",
                    on_click=WhatsAppState.reload_profile,
                    variant="ghost",
                    size="2",
                    **T.tone_scheme("neutral"),
                ),
                rx.spacer(),
                rx.button(
                    "Descartar cambios",
                    on_click=WhatsAppState.reset_profile_form,
                    variant="soft",
                    size="2",
                    **T.tone_scheme("neutral"),
                ),
                rx.button(
                    rx.icon("save", size=15),
                    "Guardar",
                    on_click=WhatsAppState.save_profile_form,
                    loading=WhatsAppState.profile_saving,
                    size="2",
                ),
                width="100%",
                align="center",
                spacing="3",
                wrap="wrap",
            ),
            spacing="4",
            width="100%",
            align_items="start",
        ),
        padding="1.25rem 1.5rem",
    )


def profile_tab() -> rx.Component:
    return rx.vstack(
        back_to_chat_link(),
        banner(WhatsAppState.profile_banner, WhatsAppState.profile_banner_tone),
        rx.cond(
            WhatsAppState.profile_ready,
            profile_form(),
            rx.cond(
                WhatsAppState.profile_failed,
                retry_button("Volver a leer el perfil", WhatsAppState.reload_profile),
                skeleton_card(5),
            ),
        ),
        spacing="4",
        width="100%",
        align_items="start",
        on_mount=WhatsAppState.ensure_profile_loaded,
    )


# ======================================================================================
# QR
# ======================================================================================


def _qr_create_card() -> rx.Component:
    return card(
        rx.vstack(
            rx.heading("Crear código", size="3", as_="h2"),
            rx.text(
                "Cada código abre un chat con tu número y un mensaje ya escrito. El canal "
                "va al principio del mensaje: así sabemos por dónde llegó cada cliente.",
                size="2",
                color=T.TEXT_MUTED,
            ),
            rx.grid(
                _field(
                    "Canal",
                    rx.select.root(
                        rx.select.trigger(width="100%"),
                        rx.select.content(
                            *[rx.select.item(label, value=key) for key, label, _ in QR_CHANNELS]
                        ),
                        value=WhatsAppState.qr_channel,
                        on_change=WhatsAppState.set_qr_channel,
                    ),
                ),
                _field(
                    "Mensaje (opcional)",
                    rx.input(
                        value=WhatsAppState.qr_text,
                        on_change=WhatsAppState.set_qr_text,
                        max_length=MAX_QR_MESSAGE_CHARS,
                        placeholder="Ej.: quiero ver el menú",
                        width="100%",
                    ),
                ),
                columns=rx.breakpoints(initial="1", md="2"),
                spacing="4",
                width="100%",
            ),
            rx.hstack(
                rx.vstack(
                    rx.text("El cliente verá escrito", size="1", color=T.TEXT_MUTED),
                    rx.text(
                        rx.cond(WhatsAppState.qr_preview != "", WhatsAppState.qr_preview, "—"),
                        size="2",
                    ),
                    spacing="0",
                    align_items="start",
                ),
                rx.spacer(),
                rx.text(
                    WhatsAppState.qr_preview_count,
                    size="1",
                    color=T.TEXT_FAINT,
                    class_name="q-nums",
                ),
                rx.button(
                    rx.icon("qr-code", size=15),
                    "Crear código",
                    on_click=WhatsAppState.create_qr,
                    loading=WhatsAppState.qr_creating,
                    size="2",
                ),
                width="100%",
                align="center",
                spacing="3",
                wrap="wrap",
            ),
            spacing="3",
            width="100%",
            align_items="start",
        ),
        padding="1.25rem 1.5rem",
    )


def _qr_delete_action(qr: QrCodeVM) -> rx.Component:
    return rx.alert_dialog.root(
        rx.alert_dialog.trigger(
            rx.button(
                rx.icon("trash-2", size=T.ICON_SM),
                "Eliminar",
                loading=WhatsAppState.qr_deleting_code == qr.code,
                variant="soft",
                size="1",
                **T.tone_scheme("neutral"),
            ),
        ),
        rx.alert_dialog.content(
            rx.alert_dialog.title("Eliminar código QR"),
            rx.alert_dialog.description(
                "Los códigos ya impresos dejarán de abrir el chat. Esta acción no se puede "
                "deshacer."
            ),
            rx.flex(
                rx.alert_dialog.cancel(
                    rx.button("Cancelar", variant="soft", **T.tone_scheme("neutral")),
                ),
                rx.alert_dialog.action(
                    rx.button(
                        "Eliminar",
                        on_click=WhatsAppState.delete_qr(qr.code),
                        **T.tone_scheme("error"),
                    ),
                ),
                spacing="3",
                margin_top="1rem",
                justify="end",
            ),
        ),
    )


def _qr_card(qr: QrCodeVM) -> rx.Component:
    has_image = qr.image_url != ""
    return card(
        rx.hstack(
            media_thumb(qr.image_url, size="112px", icon="qr-code", alt="Código QR", fit="contain"),
            rx.vstack(
                rx.hstack(
                    rx.cond(qr.channel_label != "", tag(qr.channel_label), rx.fragment()),
                    mono(qr.code, size="1", color=T.TEXT_FAINT),
                    spacing="2",
                    align="center",
                    wrap="wrap",
                ),
                rx.text(qr.prefilled_message, size="2", weight="medium"),
                mono(qr.deep_link_url, size="1", overflow_wrap="anywhere", color=T.TEXT_MUTED),
                rx.cond(
                    has_image,
                    rx.fragment(),
                    rx.text(
                        "WhatsApp solo entrega la imagen al crear el código. Usa el enlace, o "
                        "crea el código de nuevo para descargarla.",
                        size="1",
                        color=T.TEXT_FAINT,
                    ),
                ),
                rx.hstack(
                    rx.cond(
                        has_image,
                        rx.link(
                            rx.button(
                                rx.icon("download", size=T.ICON_SM),
                                "Descargar PNG",
                                variant="soft",
                                size="1",
                                **T.tone_scheme("neutral"),
                            ),
                            href=qr.image_url,
                            is_external=True,
                            custom_attrs={"download": "qr-whatsapp.png"},
                        ),
                        rx.fragment(),
                    ),
                    rx.button(
                        rx.icon("copy", size=T.ICON_SM),
                        "Copiar enlace",
                        on_click=[
                            rx.set_clipboard(qr.deep_link_url),
                            rx.toast.success("Enlace copiado"),
                        ],
                        variant="soft",
                        size="1",
                        **T.tone_scheme("neutral"),
                    ),
                    _qr_delete_action(qr),
                    spacing="2",
                    wrap="wrap",
                ),
                spacing="2",
                align_items="start",
                width="100%",
                min_width="0",
            ),
            spacing="4",
            align="start",
            width="100%",
        ),
        padding="1rem 1.25rem",
    )


def _qr_list() -> rx.Component:
    return rx.cond(
        WhatsAppState.qr_ready,
        rx.cond(
            WhatsAppState.qr_codes.length() > 0,
            rx.vstack(rx.foreach(WhatsAppState.qr_codes, _qr_card), spacing="3", width="100%"),
            empty_state(
                "qr-code",
                "Aún no tienes códigos QR",
                "Crea uno por cada lugar donde te encuentran tus clientes: el mostrador, el "
                "empaque, la bio de Instagram.",
            ),
        ),
        rx.cond(
            WhatsAppState.qr_failed,
            retry_button("Volver a leer los códigos", WhatsAppState.reload_qr),
            skeleton_rows(3, height="8rem", radius=T.RADIUS_CARD),
        ),
    )


def qr_tab() -> rx.Component:
    return rx.vstack(
        banner(WhatsAppState.qr_banner, WhatsAppState.qr_banner_tone),
        _qr_create_card(),
        rx.hstack(
            rx.heading("Tus códigos", size="3", as_="h2"),
            rx.spacer(),
            rx.button(
                rx.icon("refresh-cw", size=T.ICON_SM),
                "Actualizar",
                on_click=WhatsAppState.reload_qr,
                variant="ghost",
                size="1",
                **T.tone_scheme("neutral"),
            ),
            width="100%",
            align="center",
        ),
        _qr_list(),
        spacing="4",
        width="100%",
        align_items="start",
        on_mount=WhatsAppState.ensure_qr_loaded,
    )

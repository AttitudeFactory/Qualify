"""Connections screen components + page (C-06).

Status colors follow the design-system tones (docs/design-system.md §3.2): reserved
ok/warn/error hues, each shipped with an icon AND a text label (never color-alone).
Built on the `ui` shell (`app_shell` / `page_header` / `page_body`).
"""

from __future__ import annotations

import reflex as rx

from .connections_state import GUIDE_ELEMENT_ID, ConnectionsState
from .connections_vm import (
    CONNECT_REQUIREMENTS,
    WHATSAPP_RECONNECT_HINT,
    CapabilityVM,
    ConnectionHintVM,
    ConnectionVM,
    ConnectRequirementVM,
)
from .ui import (
    app_shell,
    callout,
    card,
    drawer,
    empty_state,
    page_body,
    page_header,
    platform_badge,
    skeleton_card,
    tag,
    tone_badge,
)
from .ui import tokens as T


def status_badge(status: rx.Var[str]) -> rx.Component:
    """active | degraded | revoked — icon + label, never color alone."""
    return rx.match(
        status,
        ("active", tone_badge("Activa", "ok", icon="circle-check", size="2")),
        ("degraded", tone_badge("Degradada", "warn", icon="triangle-alert", size="2")),
        ("revoked", tone_badge("Revocada", "error", icon="circle-x", size="2")),
        tone_badge(status, "neutral", size="2"),
    )


def _data_access_badge(state: rx.Var[str], message: rx.Var[str]) -> rx.Component:
    """QUA-91: the data-access-window warning — deliberately independent of
    `status_badge` above. Never implies the connection itself is broken (that is
    `status == "degraded"`, a real evidence-based `is_valid=false`, rendered
    separately); distinct icons on purpose (`hourglass`/`calendar-x`, never
    `triangle-alert`) so the two signals are never visually conflated."""
    return rx.match(
        state,
        ("warning_soon", tone_badge(message, "warn", icon="hourglass", size="1")),
        ("warning_overdue", tone_badge(message, "warn", icon="calendar-x", size="1")),
        rx.fragment(),
    )


def verify_now_button(conn: ConnectionVM) -> rx.Component:
    """QUA-91: one on-demand `/debug_token` check. Shown only for an `active`
    connection — a `degraded` one already shows "Reconectar" as its primary action, and
    the whole point of this button is to catch a problem BEFORE it degrades. Manual
    only: nothing renders or fires this on a timer.

    `loading=` is keyed to THIS card's id (`checking_connection_ids.contains(conn.id)`,
    same per-row pattern `InboxState.toggling_media_ids` already uses) — not a
    page-wide flag, so a click on one connection's button never shows every other
    card's button as busy too. Radix's `loading` prop is what gives the spinner AND
    the disabled-while-in-flight state in one prop; no separate `disabled=` needed.
    """
    return rx.button(
        rx.icon("shield-check", size=14),
        "Verificar ahora",
        on_click=ConnectionsState.check_health_now(conn.id),
        loading=ConnectionsState.checking_connection_ids.contains(conn.id),
        variant="soft",
        **T.tone_scheme("neutral"),
        size="1",
    )


def _scope_chip(label: rx.Var[str]) -> rx.Component:
    return tag(label)


def _provisional_mark() -> rx.Component:
    """Honest 'por verificar' marker for capabilities resting on the Meta doc bug."""
    return rx.tooltip(
        tone_badge("por verificar", "warn", icon="circle-help"),
        content=(
            "Esta capacidad depende de una fila de la documentación de Meta que "
            "aún no está verificada por una segunda fuente."
        ),
    )


def _enabled_capability(cap: CapabilityVM) -> rx.Component:
    return rx.hstack(
        rx.icon("circle-check", size=15, color=T.tone_color("ok", 9)),
        rx.text(cap.label, size="2"),
        rx.cond(cap.provisional, _provisional_mark(), rx.fragment()),
        spacing="2",
        align="center",
        width="100%",
    )


def _disabled_capability(cap: CapabilityVM) -> rx.Component:
    return rx.hstack(
        rx.icon("circle-x", size=15, color=T.TEXT_FAINT),
        rx.vstack(
            rx.hstack(
                rx.text(cap.label, size="2", color=T.TEXT_MUTED),
                rx.cond(cap.provisional, _provisional_mark(), rx.fragment()),
                spacing="2",
                align="center",
            ),
            rx.text(cap.reason, size="1", color=T.TEXT_MUTED),
            spacing="0",
            align_items="start",
        ),
        spacing="2",
        align="start",
        width="100%",
    )


def _whatsapp_reconnect_hint(tone: str) -> rx.Component:
    """WA-05: the banner body for a WhatsApp card. No button — the Instagram
    «Reconectar» starts the OAuth flow, which is the wrong door for a number connected
    by an administrator with a system-user token (QUA-203 is the self-service story)."""
    return callout(rx.text(WHATSAPP_RECONNECT_HINT, size="2"), tone)


def degraded_banner(conn: ConnectionVM) -> rx.Component:
    """Actionable degraded state — a Reconnect BUTTON, not a decorative icon.

    The button carries no connection id: reconnecting re-runs the C-04 authorization
    flow for the tenant, and the grant that comes back is matched to the existing row
    by account. `conn` is read only for its platform (WA-05): a WhatsApp card gets the
    administrative hint instead of the button.
    """
    return rx.cond(
        conn.platform == "whatsapp",
        _whatsapp_reconnect_hint("warn"),
        _instagram_degraded_banner(),
    )


def _instagram_degraded_banner() -> rx.Component:
    # The system's callout in the `warn` tone (card material in the tone's hairline).
    # The button is `soft` in the same tone: a card's own action, never the page's one
    # solid (P3) — several degraded cards would otherwise each claim it.
    return callout(
        rx.hstack(
            rx.text(
                "La conexión dejó de responder. Reconéctala para restaurar el "
                "acceso a esta cuenta.",
                size="2",
            ),
            rx.spacer(),
            rx.button(
                rx.icon("refresh-cw", size=15),
                "Reconectar",
                on_click=ConnectionsState.start_connect_flow,
                variant="soft",
                size="2",
                **T.tone_scheme("warn"),
            ),
            width="100%",
            align="center",
            wrap="wrap",
            spacing="3",
        ),
        "warn",
    )


def revoked_banner(conn: ConnectionVM) -> rx.Component:
    return rx.cond(
        conn.platform == "whatsapp",
        _whatsapp_reconnect_hint("error"),
        _instagram_revoked_banner(),
    )


def _instagram_revoked_banner() -> rx.Component:
    return callout(
        rx.hstack(
            rx.text(
                "El acceso fue revocado. Vuelve a conectar la cuenta para reactivarla.",
                size="2",
            ),
            rx.spacer(),
            rx.button(
                rx.icon("plug", size=15),
                "Volver a conectar",
                on_click=ConnectionsState.start_connect_flow,
                variant="soft",
                size="2",
                **T.tone_scheme("error"),
            ),
            width="100%",
            align="center",
            wrap="wrap",
            spacing="3",
        ),
        "error",
        icon="circle-x",
    )


def _hint_row(hint: ConnectionHintVM) -> rx.Component:
    """One missing thing: what, why, and «Ver el paso N» — which opens the guide on
    exactly that step (`show_guide_step`), so the card and the guide share numbers."""
    return rx.vstack(
        rx.text(hint.title, size="2", weight="medium", color=T.TEXT_STRONG),
        rx.text(hint.detail, size="2"),
        rx.button(
            rx.icon("list-checks", size=T.ICON_SM),
            "Ver el paso ",
            hint.step_number,
            on_click=ConnectionsState.show_guide_step(hint.step_key),
            variant="ghost",
            size="1",
            color_scheme="gray",
        ),
        spacing="1",
        align_items="start",
        width="100%",
    )


def _hints_callout(conn: ConnectionVM) -> rx.Component:
    """«A esta cuenta le falta algo» (m-24840590): only on an active Instagram card,
    only for what the stored permissions show (`connection_hints`). One reconnect
    button for all of them — the fix is the same Meta window, asked again with
    `rerequest` so what was unticked comes back. `soft`, never the page's solid."""
    return callout(
        rx.vstack(
            rx.foreach(conn.hints, _hint_row),
            rx.button(
                rx.icon("refresh-cw", size=15),
                "Volver a conectar",
                on_click=ConnectionsState.reconnect_for_permissions,
                variant="soft",
                size="2",
                **T.tone_scheme("warn"),
            ),
            spacing="3",
            align_items="start",
            width="100%",
        ),
        "warn",
        icon="list-checks",
    )


def disconnect_action(conn: ConnectionVM) -> rx.Component:
    """Disconnect with confirmation — fires the C-03 `-> revoked` transition."""
    return rx.alert_dialog.root(
        rx.alert_dialog.trigger(
            rx.button(
                rx.icon("unplug", size=15),
                "Desconectar",
                variant="soft",
                **T.tone_scheme("neutral"),
                size="2",
            ),
        ),
        rx.alert_dialog.content(
            rx.alert_dialog.title("Desconectar cuenta"),
            rx.alert_dialog.description(
                rx.text(
                    "Se revocará el acceso de Qualify a ",
                    rx.text.strong(conn.external_username),
                    ". Podrás volver a conectarla más tarde.",
                ),
            ),
            rx.flex(
                rx.alert_dialog.cancel(
                    rx.button("Cancelar", variant="soft", **T.tone_scheme("neutral")),
                ),
                rx.alert_dialog.action(
                    # The confirmation of a destructive action: solid in the error
                    # tone (docs/design-system.md §5.5) — the dialog's own one solid.
                    rx.button(
                        "Desconectar",
                        on_click=ConnectionsState.disconnect_connection(conn.id),
                        **T.tone_scheme("error"),
                    ),
                ),
                spacing="3",
                margin_top="1rem",
                justify="end",
            ),
        ),
    )


def connection_card(conn: ConnectionVM) -> rx.Component:
    return card(
        rx.vstack(
            # Header: platform + username + status
            rx.hstack(
                platform_badge(conn.platform),
                rx.heading(conn.external_username, size="4", as_="h2"),
                rx.spacer(),
                rx.cond(conn.status == "active", verify_now_button(conn), rx.fragment()),
                status_badge(conn.status),
                width="100%",
                align="center",
            ),
            rx.hstack(
                rx.icon("building-2", size=14, color=T.TEXT_FAINT),
                rx.text(conn.brand, size="2", color=T.TEXT_MUTED),
                rx.text("·", color=T.TEXT_FAINT),
                rx.icon("clock", size=14, color=T.TEXT_FAINT),
                rx.text(
                    "Verificada: ",
                    conn.last_verified_at,
                    size="2",
                    color=T.TEXT_MUTED,
                ),
                spacing="2",
                align="center",
            ),
            # QUA-91: distinct from "Verificada:" above (that is `last_verified_at`, the
            # connect-flow verification, QUA-16) — this is the last manual "Verificar
            # ahora" click. Without this line a click ran /debug_token for real but
            # nothing on screen ever showed it happened.
            rx.hstack(
                rx.icon("shield-check", size=14, color=T.TEXT_FAINT),
                rx.text(
                    "Última verificación de acceso: ",
                    conn.last_health_checked_at,
                    size="2",
                    color=T.TEXT_MUTED,
                ),
                spacing="2",
                align="center",
            ),
            # QUA-91: independent of the FSM-driven banners below — never shown at the
            # same time as claiming the connection is `degraded`.
            _data_access_badge(conn.data_access_state, conn.data_access_message),
            # m-24840590: what this account is missing, each with its guide step.
            rx.cond(conn.hints.length() > 0, _hints_callout(conn), rx.fragment()),
            # Actionable banners per state.
            rx.cond(conn.status == "degraded", degraded_banner(conn), rx.fragment()),
            rx.cond(conn.status == "revoked", revoked_banner(conn), rx.fragment()),
            # Granted scopes.
            rx.cond(
                conn.granted_scopes.length() > 0,
                rx.vstack(
                    rx.text("Permisos concedidos", size="1", color=T.TEXT_MUTED),
                    rx.hstack(
                        rx.foreach(conn.granted_scopes, _scope_chip),
                        spacing="2",
                        wrap="wrap",
                    ),
                    spacing="1",
                    align_items="start",
                    width="100%",
                ),
                rx.fragment(),
            ),
            # Capabilities: enabled then disabled-with-reason.
            rx.divider(),
            rx.cond(
                conn.enabled_capabilities.length() > 0,
                rx.vstack(
                    rx.text("Disponible", size="1", color=T.TEXT_MUTED),
                    rx.foreach(conn.enabled_capabilities, _enabled_capability),
                    spacing="2",
                    align_items="start",
                    width="100%",
                ),
                rx.fragment(),
            ),
            rx.cond(
                conn.disabled_capabilities.length() > 0,
                rx.vstack(
                    rx.text(
                        "Deshabilitado",
                        size="1",
                        color=T.TEXT_MUTED,
                    ),
                    rx.foreach(conn.disabled_capabilities, _disabled_capability),
                    spacing="2",
                    align_items="start",
                    width="100%",
                ),
                rx.fragment(),
            ),
            # Disconnect (hidden once already revoked).
            rx.cond(
                conn.status != "revoked",
                rx.hstack(rx.spacer(), disconnect_action(conn), width="100%"),
                rx.fragment(),
            ),
            spacing="3",
            align_items="start",
            width="100%",
        ),
        padding="1.25rem 1.5rem",
    )


def _empty_state() -> rx.Component:
    return empty_state(
        "link-2-off",
        "Aún no conectas ninguna cuenta",
        "Conecta tu primera red social para empezar a escuchar y responder desde Qualify.",
        action=rx.button(
            rx.icon("plus", size=16),
            "Conectar cuenta",
            on_click=ConnectionsState.start_connect_flow,
            size="3",
            margin_top="0.5rem",
        ),
    )


def help_button(size: str = "2") -> rx.Component:
    """«Pedir ayuda 1:1» (QUA-202) — the same button wherever it appears (header,
    checklist, guided panel), always `soft`/neutral: it is never the page's one solid."""
    return rx.button(
        rx.icon("life-buoy", size=T.ICON_SM if size == "1" else 15),
        "Pedir ayuda 1:1",
        on_click=ConnectionsState.open_support,
        variant="soft",
        size=size,
        **T.tone_scheme("neutral"),
    )


def connections_topbar() -> rx.Component:
    return page_header(
        "Tus redes",
        "Revisa que tus redes sociales estén conectadas y con los permisos que Qualify necesita.",
        help_button(),
    )


def _action_error() -> rx.Component:
    """Error from a connect/disconnect action, shown ABOVE the list rather than
    replacing it: the connections on screen are still valid, one action failed."""
    return callout(ConnectionsState.action_error, "warn")


def _connect_notice() -> rx.Component:
    """The result of the OAuth round trip (QUA-123). `callout` takes its tone at compile
    time, so the runtime tone picks between three pre-built callouts."""
    message = ConnectionsState.connect_notice
    return rx.match(
        ConnectionsState.connect_notice_tone,
        ("ok", callout(message, "ok")),
        ("info", callout(message, "info")),
        callout(message, "warn"),
    )


# -- QUA-202: guided connection ----------------------------------------------------------


def _step_number(number: rx.Var | str, tone: str) -> rx.Component:
    """A small numbered disc. The number is the ordering cue, the text is the content —
    never a number alone (§8), never a colour alone."""
    return rx.badge(
        number,
        radius="full",
        variant="solid",
        size="1",
        min_width="1.5rem",
        justify_content="center",
        flex_shrink="0",
        class_name="q-nums",
        **T.tone_scheme(tone),
    )


def _step_row(step: rx.Var[str], index: rx.Var[int]) -> rx.Component:
    return rx.hstack(
        _step_number(index + 1, "warn"),
        rx.text(step, size="2"),
        spacing="3",
        align="start",
        width="100%",
    )


def connect_guidance_panel() -> rx.Component:
    """The dead-end result as a path, not a sentence (§6.3: the fix lives inside the
    callout). What happened, the steps for exactly this case, and the two actions —
    «Volver a conectar» (with `rerequest` when the Page picker must come back) and
    «Pedir ayuda 1:1»."""
    return callout(
        rx.vstack(
            rx.heading(ConnectionsState.guidance_title, size="4", as_="h2"),
            rx.text(ConnectionsState.guidance_summary, size="2"),
            rx.vstack(
                rx.foreach(ConnectionsState.guidance_steps, _step_row),
                spacing="2",
                width="100%",
                margin_top="0.25rem",
            ),
            rx.hstack(
                rx.button(
                    rx.icon("refresh-cw", size=15),
                    "Volver a conectar",
                    on_click=ConnectionsState.retry_connect,
                    variant="soft",
                    size="2",
                    **T.tone_scheme("warn"),
                ),
                help_button(),
                spacing="3",
                wrap="wrap",
                margin_top="0.25rem",
            ),
            spacing="3",
            align_items="start",
            width="100%",
        ),
        "warn",
        icon="triangle-alert",
    )


def _requirement_row(requirement: ConnectRequirementVM, number: int) -> rx.Component:
    """One of the three pre-flight requirements, with its steps behind «¿Cómo lo hago?».
    Static content, dynamic open/closed: `CONNECT_REQUIREMENTS` is a Python list, so the
    rows are built at compile time and only the toggle lives in state."""
    is_open = ConnectionsState.expanded_requirement == requirement.key
    steps = rx.vstack(
        *[
            rx.hstack(
                _step_number(str(i + 1), "accent"),
                rx.text(step, size="2"),
                spacing="3",
                align="start",
                width="100%",
            )
            for i, step in enumerate(requirement.steps)
        ],
        spacing="2",
        width="100%",
        padding_top="0.5rem",
    )
    return rx.vstack(
        rx.hstack(
            _step_number(str(number), "accent"),
            rx.vstack(
                rx.text(requirement.title, size="3", weight="medium", color=T.TEXT_STRONG),
                rx.text(requirement.summary, size="2", color=T.TEXT_MUTED),
                # Under the text, not beside it (m-24840590): on a phone a side button
                # squeezed the title into a one-word column.
                rx.button(
                    rx.icon(rx.cond(is_open, "chevron-up", "chevron-down"), size=T.ICON_SM),
                    rx.cond(is_open, "Ocultar", "¿Cómo lo hago?"),
                    on_click=ConnectionsState.toggle_requirement(requirement.key),
                    variant="ghost",
                    size="1",
                    color_scheme="gray",
                    aria_expanded=is_open,
                    margin_top="0.375rem",
                ),
                spacing="0",
                align_items="start",
                flex="1",
                min_width="0",
            ),
            spacing="3",
            align="start",
            width="100%",
        ),
        rx.cond(is_open, steps, rx.fragment()),
        spacing="0",
        align_items="start",
        width="100%",
    )


def connect_requirements_card() -> rx.Component:
    """«Prepara tu Instagram»: the four things only the client can do (m-24840590),
    each with its steps in the Instagram app or Meta's window. A pre-flight hint (R4a),
    not a check — the screen cannot verify the Instagram side, and the copy never
    pretends to; the card hints cover what the stored permissions do show."""
    rows: list[rx.Component] = []
    for number, requirement in enumerate(CONNECT_REQUIREMENTS, start=1):
        if number > 1:
            rows.append(rx.divider())
        rows.append(_requirement_row(requirement, number))
    return card(
        rx.vstack(
            rx.hstack(
                rx.icon("list-checks", size=T.ICON_MD, color=T.tone_color("accent", 9)),
                rx.vstack(
                    rx.heading("Prepara tu Instagram antes de conectar", size="4", as_="h2"),
                    rx.text(
                        "Son cuatro pasos y toman unos minutos. Si te saltas uno, Qualify "
                        "no podrá publicar o responder mensajes por ti.",
                        size="2",
                        color=T.TEXT_MUTED,
                    ),
                    spacing="0",
                    align_items="start",
                    flex="1",
                ),
                rx.cond(
                    ConnectionsState.has_connections,
                    rx.button(
                        "Ocultar",
                        on_click=ConnectionsState.toggle_checklist,
                        variant="ghost",
                        size="1",
                        color_scheme="gray",
                    ),
                    rx.fragment(),
                ),
                spacing="3",
                align="start",
                width="100%",
            ),
            *rows,
            # With accounts on screen there is no empty state, so the guide carries the
            # page's one «Conectar cuenta» (solid: P3). Without accounts the empty state
            # below already has it, and a second solid would compete.
            rx.cond(
                ConnectionsState.has_connections,
                rx.button(
                    rx.icon("plus", size=16),
                    "Conectar cuenta",
                    on_click=ConnectionsState.start_connect_flow,
                    size="2",
                ),
                rx.fragment(),
            ),
            rx.hstack(
                rx.text(
                    "¿Tienes dudas? Una persona del equipo lo revisa contigo.",
                    size="2",
                    color=T.TEXT_MUTED,
                ),
                rx.spacer(),
                help_button(),
                width="100%",
                align="center",
                wrap="wrap",
                spacing="3",
            ),
            spacing="3",
            align_items="start",
            width="100%",
        ),
        padding="1.25rem 1.5rem",
        id=GUIDE_ELEMENT_ID,
        # Scrolled into view by «Ver el paso N»: keep its top clear of the app bar.
        scroll_margin_top="5rem",
    )


def _folded_checklist() -> rx.Component:
    """One line for a tenant whose accounts already work (§6.5)."""
    return rx.hstack(
        rx.icon("list-checks", size=T.ICON_SM, color=T.TEXT_FAINT),
        rx.text("¿Vas a conectar otra cuenta?", size="2", color=T.TEXT_MUTED),
        rx.button(
            "Ver la guía de conexión",
            on_click=ConnectionsState.toggle_checklist,
            variant="ghost",
            size="1",
            color_scheme="gray",
        ),
        spacing="2",
        align="center",
        width="100%",
    )


def _support_field(label: str, control: rx.Component, hint: str | None = None) -> rx.Component:
    """Label above, help below (§5.6)."""
    return rx.vstack(
        rx.text(label, size="2", weight="medium"),
        control,
        *([rx.text(hint, size="1", color=T.TEXT_MUTED)] if hint else []),
        spacing="1",
        align_items="start",
        width="100%",
    )


def support_drawer() -> rx.Component:
    """«Pedir ayuda 1:1» (QUA-202): a short form, prefilled with the session's email,
    that files a ticket for the global support channel. The drawer's one solid button
    is its own (§5.8) — the page's solid stays «Conectar cuenta»."""
    return drawer(
        rx.vstack(
            rx.cond(
                ConnectionsState.support_error != "",
                callout(ConnectionsState.support_error, "error"),
                rx.fragment(),
            ),
            rx.cond(
                ConnectionsState.has_guidance,
                callout(
                    "Adjuntamos el resultado de tu último intento para que la persona que "
                    "te atienda llegue con el contexto.",
                    "info",
                ),
                rx.fragment(),
            ),
            _support_field(
                "Correo",
                rx.input(
                    value=ConnectionsState.support_email,
                    on_change=ConnectionsState.set_support_email,
                    type="email",
                    name="email",
                    required=True,
                    placeholder="tu@negocio.com",
                    width="100%",
                ),
                "Te escribimos aquí.",
            ),
            _support_field(
                "WhatsApp (opcional)",
                rx.input(
                    value=ConnectionsState.support_whatsapp,
                    on_change=ConnectionsState.set_support_whatsapp,
                    type="tel",
                    name="whatsapp",
                    placeholder="+58 412 000 0000",
                    width="100%",
                ),
                "Si prefieres que te llamemos o te escribamos por ahí.",
            ),
            _support_field(
                "Cuéntanos qué pasó (opcional)",
                rx.text_area(
                    value=ConnectionsState.support_message,
                    on_change=ConnectionsState.set_support_message,
                    placeholder="Ej.: no encuentro la opción de Página en mi Instagram.",
                    rows="4",
                    width="100%",
                ),
            ),
            spacing="4",
            width="100%",
            align_items="start",
        ),
        open=ConnectionsState.support_open,
        on_open_change=ConnectionsState.set_support_open,
        title="Pedir ayuda 1:1",
        icon="life-buoy",
        description=(
            "Una persona del equipo de Qualify te contacta y deja la conexión lista "
            "contigo. Sin costo."
        ),
        footer=rx.hstack(
            rx.button(
                "Cancelar",
                on_click=ConnectionsState.set_support_open(False),
                variant="soft",
                **T.tone_scheme("neutral"),
            ),
            rx.spacer(),
            rx.button(
                rx.icon("send", size=15),
                "Enviar solicitud",
                on_click=ConnectionsState.submit_support,
                loading=ConnectionsState.support_sending,
            ),
            width="100%",
            align="center",
        ),
    )


def _connections_body() -> rx.Component:
    return page_body(
        rx.cond(
            ConnectionsState.support_notice != "",
            callout(ConnectionsState.support_notice, "ok", icon="life-buoy"),
            rx.fragment(),
        ),
        rx.cond(ConnectionsState.has_guidance, connect_guidance_panel(), rx.fragment()),
        rx.cond(ConnectionsState.connect_notice != "", _connect_notice(), rx.fragment()),
        rx.cond(ConnectionsState.action_error != "", _action_error(), rx.fragment()),
        rx.cond(
            ConnectionsState.show_checklist,
            connect_requirements_card(),
            rx.cond(
                ConnectionsState.has_connections & ~ConnectionsState.is_loading,
                _folded_checklist(),
                rx.fragment(),
            ),
        ),
        rx.cond(
            ConnectionsState.load_error != "",
            callout(ConnectionsState.load_error, "error"),
            _loaded_body(),
        ),
        support_drawer(),
    )


def _loaded_body() -> rx.Component:
    return rx.cond(
        ConnectionsState.is_loading,
        rx.vstack(skeleton_card(), skeleton_card(), spacing="4", width="100%"),
        rx.cond(
            ConnectionsState.show_empty_state,
            _empty_state(),
            rx.vstack(
                rx.foreach(ConnectionsState.connections, connection_card),
                spacing="4",
                width="100%",
            ),
        ),
    )


def connections_index() -> rx.Component:
    return app_shell(connections_topbar(), _connections_body())

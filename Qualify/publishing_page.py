"""Publish screen (A5 vertical slice) — upload a reel, pick a connected account, publish.

Built on the `ui` shell (`app_shell` / `page_header` / `page_body`); badges and callouts
follow the design-system tones (docs/design-system.md). Adds the `/publish` route only.

QUA-98 started as a visual-only pass — every original `PublishState` binding (`value=`,
`on_change=`, `on_click=`, `disabled=`) is still byte-for-byte the same expression. One
narrow, explicitly-authorized addition later touched `publishing_state.py` too (never Meta
calls/payloads/auth/account selection/video loading/caption logic/the publish button's
core behavior): the success/failure toasts and the post-success form reset — see
`_success_toast`/`_failure_toast` and the `self.caption = ""` + `rx.clear_selected_files`
calls there. `publishing_provider.py`/`publishing_vm.py` remain untouched.
"""

from __future__ import annotations

import reflex as rx

from .publishing_state import _UPLOAD_ID, PublishState
from .publishing_vm import ConnectionOptionVM
from .ui import app_shell, callout, card, page_body, page_header, section
from .ui import tokens as T


def _connection_item(conn: ConnectionOptionVM) -> rx.Component:
    return rx.select.item(conn.external_username + " · " + conn.platform, value=conn.id)


def _connection_selector() -> rx.Component:
    return rx.select.root(
        rx.select.trigger(placeholder="Elige una cuenta conectada", width="100%"),
        rx.select.content(
            rx.foreach(PublishState.connections, _connection_item),
        ),
        value=PublishState.selected_connection_id,
        on_change=PublishState.select_connection,
        size="3",
        width="100%",
    )


def _connection_section() -> rx.Component:
    return section(
        "Cuenta",
        _connection_selector(),
        description="La cuenta de Instagram conectada donde se publicará este contenido.",
    )


def _upload_zone() -> rx.Component:
    # Purely presentational: `rx.selected_files(_UPLOAD_ID)` is the same reactive Var the
    # original always rendered as plain text — reused here only to switch *how* the
    # existing value is shown, never to change what triggers the selection itself.
    has_file = rx.selected_files(_UPLOAD_ID).length() > 0
    return rx.upload(
        rx.cond(
            has_file,
            rx.vstack(
                rx.icon("circle-check", size=32, color=T.tone_color("ok", 9)),
                rx.text("Contenido seleccionado", size="3", weight="medium"),
                rx.text(rx.selected_files(_UPLOAD_ID), size="1", color=T.TEXT_MUTED),
                rx.text("Cambiar contenido", size="1", color=T.TEXT_FAINT),
                spacing="2",
                align="center",
            ),
            rx.vstack(
                rx.icon("film", size=32, color=T.TEXT_FAINT),
                rx.text(
                    "Arrastra tu contenido aquí o haz clic para elegirlo",
                    size="3",
                    weight="medium",
                ),
                rx.text("MP4 o MOV · hasta 300 MB", size="1", color=T.TEXT_MUTED),
                spacing="2",
                align="center",
            ),
        ),
        id=_UPLOAD_ID,
        accept={"video/mp4": [".mp4"], "video/quicktime": [".mov"]},
        multiple=False,
        max_files=1,
        # Client-side mirror of `ObjectGate.MAX_MEDIA_BYTES` (qualify_shared/objects/
        # gate.py) — that server-side ceiling is the real, load-bearing barrier and is
        # untouched; this only lets a too-large file get rejected at selection time
        # instead of after an upload attempt starts.
        max_size=300 * 1024 * 1024,
        # Replaces Reflex's default English "Files not Accepted" toast
        # (reflex_components_core.core.upload._default_drop_rejected) with one in
        # Spanish, consistent with the rest of Qualify. Static on purpose: it covers
        # both rejection reasons (wrong format, too large) with one message rather than
        # inspecting `rejected_files` via undocumented internal Var APIs.
        on_drop_rejected=rx.toast.error(
            "Formato no permitido",
            description="Solo se aceptan archivos MP4 o MOV.",
        ),
        border=rx.cond(
            has_file,
            f"1.5px solid {rx.color('grass', 8)}",
            f"1.5px dashed {rx.color('gray', 7)}",
        ),
        border_radius=T.RADIUS_CARD,
        background=rx.cond(has_file, T.tone_color("ok", 2), T.CARD_BG),
        padding="2.5rem 1.5rem",
        width="100%",
        transition=f"border-color {T.DUR_FAST} {T.EASE}, background {T.DUR_FAST} {T.EASE}",
        _hover={
            "border_color": rx.color("accent", 8),
            "background": T.tone_color("accent", 2),
        },
    )


def _content_section() -> rx.Component:
    return section(
        "Contenido",
        _upload_zone(),
        description="Lo que se publicará en la cuenta elegida arriba.",
    )


def _caption_section() -> rx.Component:
    return section(
        "Caption",
        rx.text_area(
            placeholder="Escribe el caption...",
            value=PublishState.caption,
            on_change=PublishState.set_caption,
            rows="5",
            size="3",
            width="100%",
        ),
        description="Se publicará exactamente como lo escribas.",
    )


def _status_block() -> rx.Component:
    return rx.match(
        PublishState.phase,
        (
            "staging_and_starting",
            rx.callout(
                rx.hstack(
                    rx.spinner(size="2"),
                    rx.text("Subiendo el video y arrancando la publicación...", size="2"),
                    spacing="2",
                    align="center",
                ),
                color_scheme="gray",
                width="100%",
            ),
        ),
        (
            "polling",
            rx.callout(
                rx.hstack(
                    rx.spinner(size="2"),
                    rx.text("Publicando, esperando confirmación de Meta...", size="2"),
                    spacing="2",
                    align="center",
                ),
                icon="clock",
                color_scheme="amber",
                width="100%",
            ),
        ),
        # QUA-98: "success" has no inline arm on purpose — the confirmation moved to a
        # transient `rx.toast.success` fired from `publishing_state.py` (same convention
        # `inbox_state.py` already established: success = toast, error = persistent
        # callout below, unchanged). Falls through to the catch-all `rx.fragment()`.
        (
            "failure",
            rx.callout(
                PublishState.error,
                icon="triangle-alert",
                color_scheme="tomato",
                width="100%",
            ),
        ),
        rx.fragment(),
    )


def _publish_button() -> rx.Component:
    return rx.button(
        rx.icon("send", size=18),
        "Publicar",
        on_click=PublishState.publish(rx.upload_files(upload_id=_UPLOAD_ID)),
        disabled=~PublishState.can_publish,
        size="4",
        width="100%",
    )


def _form_card() -> rx.Component:
    return card(
        rx.vstack(
            _connection_section(),
            rx.divider(),
            _content_section(),
            rx.divider(),
            _caption_section(),
            rx.divider(),
            rx.vstack(
                _publish_button(),
                _status_block(),
                spacing="3",
                width="100%",
                align_items="stretch",
            ),
            spacing="5",
            align_items="stretch",
            width="100%",
        ),
        padding="2rem",
    )


def _tip_row(icon: str, text: str) -> rx.Component:
    return rx.hstack(
        rx.icon(icon, size=T.ICON_SM, color=T.TEXT_FAINT),
        rx.text(text, size="2", color=T.TEXT_MUTED),
        spacing="2",
        align="start",
    )


def _tips_card() -> rx.Component:
    """Static, informational only — every fact here mirrors an existing constraint
    already enforced by `PublishState`/`_upload_zone` (accepted formats, size limit,
    polling behavior), not a new claim about functionality."""
    return card(
        rx.vstack(
            rx.hstack(
                rx.icon("info", size=T.ICON_MD, color=T.tone_color("info", 9)),
                rx.heading("Antes de publicar", size="3", as_="h2"),
                spacing="2",
                align="center",
            ),
            rx.vstack(
                _tip_row("film", "Formatos aceptados: MP4 y MOV."),
                _tip_row("scale", "Tamaño máximo: 300 MB."),
                _tip_row("at-sign", "Se publica en la cuenta que elijas arriba."),
                _tip_row("clock", "La confirmación de Meta puede tardar unos minutos."),
                spacing="3",
                align_items="start",
                width="100%",
            ),
            spacing="4",
            align_items="start",
            width="100%",
        ),
        padding="1.5rem",
    )


def _form() -> rx.Component:
    return rx.flex(
        rx.box(_form_card(), flex="2 1 480px", min_width="0", width="100%"),
        rx.box(_tips_card(), flex="1 1 280px", min_width="0", width="100%"),
        spacing="5",
        width="100%",
        wrap="wrap",
        align_items="start",
    )


def _load_error() -> rx.Component:
    return callout(PublishState.load_error, "error")


def publish_topbar() -> rx.Component:
    return page_header(
        "Publicar",
        "Sube un reel y publícalo en una de tus cuentas de Instagram conectadas",
    )


def publish_index() -> rx.Component:
    return app_shell(
        publish_topbar(),
        page_body(rx.cond(PublishState.load_error != "", _load_error(), _form())),
    )

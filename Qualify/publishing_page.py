"""Publish screen (A5 vertical slice) — upload 1-10 videos, pick a connected account,
publish. 2-10 videos publish together as one Instagram carousel (QUA-99).

Built on the `ui` shell (`app_shell` / `page_header` / `page_body`); badges and callouts
follow the design-system tones (docs/design-system.md). Adds the `/publish` route only.

QUA-98 started as a visual-only pass — every original `PublishState` binding (`value=`,
`on_change=`, `on_click=`, `disabled=`) is still byte-for-byte the same expression. One
narrow, explicitly-authorized addition later touched `publishing_state.py` too (never Meta
calls/payloads/auth/account selection/video loading/caption logic/the publish button's
core behavior): the success/failure toasts and the post-success form reset — see
`_success_toast`/`_failure_toast` and the `self.caption = ""` + `rx.clear_selected_files`
calls there.

QUA-99 (6/6): the dropzone gained `multiple=True`/`max_files` raised from 1 to 10 — the
SAME `rx.upload` widget, no new upload abstraction. The gallery of selected names reuses
`rx.selected_files(_UPLOAD_ID)`, the same reactive Var the single-video screen already
rendered (just iterated with `rx.foreach` now that it can hold more than one name). The
caption field (`_caption_section`) is completely UNTOUCHED — one field, one source of
truth, used identically for 1 video or a carousel; only `publishing_state.py` decides
downstream which provider seam (`start_publish` vs `start_many_publish`) the SAME
`self.caption` value reaches. VIDEO-ONLY: no image path exists anywhere on this screen,
not even as a disabled placeholder — `accept` still lists only MP4/MOV.
"""

from __future__ import annotations

import reflex as rx

from .publishing_state import _MAX_ITEMS, _UPLOAD_ID, PublishState
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
    # QUA-99 (6/6): `rx.selected_files(_UPLOAD_ID)` is the SAME reactive Var the original
    # single-video screen already used (client-side, tracks the dropzone's current
    # selection before any upload) — reused as-is for the gallery below rather than
    # duplicated into a new state Var. `multiple=True` is the only reason it can now hold
    # more than one name; the Var itself is untouched machinery.
    selected = rx.selected_files(_UPLOAD_ID)
    has_file = selected.length() > 0
    is_carousel = selected.length() > 1
    return rx.upload(
        rx.cond(
            has_file,
            rx.vstack(
                rx.icon("circle-check", size=32, color=T.tone_color("ok", 9)),
                # QUA-99: "Contenido seleccionado" stays for exactly 1 file (today's
                # unchanged wording); 2+ say explicitly that it is a carousel, never a
                # singular-sounding "video" label over a multi-item selection.
                rx.cond(
                    is_carousel,
                    rx.text(
                        f"Carrusel de {selected.length()} elementos", size="3", weight="medium"
                    ),
                    rx.text("Contenido seleccionado", size="3", weight="medium"),
                ),
                rx.vstack(
                    rx.foreach(
                        selected,
                        lambda name: rx.text(name, size="1", color=T.TEXT_MUTED),
                    ),
                    spacing="1",
                    align="center",
                    max_height="6rem",
                    overflow_y="auto",
                    width="100%",
                ),
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
                rx.text(
                    f"MP4 o MOV · hasta 300 MB por video · hasta {_MAX_ITEMS} videos",
                    size="1",
                    color=T.TEXT_MUTED,
                ),
                spacing="2",
                align="center",
            ),
        ),
        id=_UPLOAD_ID,
        accept={"video/mp4": [".mp4"], "video/quicktime": [".mov"]},
        # QUA-99 (6/6): multi-select is the only change to the widget itself —
        # `max_files` is the SAME prop the single-video screen already used, just raised
        # from 1 to the carousel cap. No new upload abstraction.
        multiple=True,
        max_files=_MAX_ITEMS,
        # Client-side mirror of `ObjectGate.MAX_MEDIA_BYTES` (qualify_shared/objects/
        # gate.py) — that server-side ceiling is the real, load-bearing barrier and is
        # untouched; this only lets a too-large file get rejected at selection time
        # instead of after an upload attempt starts.
        max_size=300 * 1024 * 1024,
        # Replaces Reflex's default English "Files not Accepted" toast
        # (reflex_components_core.core.upload._default_drop_rejected) with one in
        # Spanish, consistent with the rest of Qualify. Static on purpose: it covers
        # every rejection reason (wrong format, too large, more than the cap) with one
        # message rather than inspecting `rejected_files` via undocumented internal Var
        # APIs.
        on_drop_rejected=rx.toast.error(
            "Formato no permitido",
            description=f"Solo se aceptan archivos MP4 o MOV, hasta {_MAX_ITEMS} a la vez.",
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
    # QUA-99 (6/6): "el video" (singular) only makes sense while exactly one file is
    # selected — `rx.selected_files` is still the current selection here too, since
    # nothing clears it before a successful publish (`rx.clear_selected_files` only
    # fires on success, never mid-flight).
    is_carousel = rx.selected_files(_UPLOAD_ID).length() > 1
    return rx.match(
        PublishState.phase,
        (
            "staging_and_starting",
            rx.callout(
                rx.hstack(
                    rx.spinner(size="2"),
                    rx.cond(
                        is_carousel,
                        rx.text(
                            "Subiendo el contenido y arrancando la publicación del carrusel...",
                            size="2",
                        ),
                        rx.text("Subiendo el video y arrancando la publicación...", size="2"),
                    ),
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
                _tip_row("scale", "Tamaño máximo: 300 MB por video."),
                _tip_row(
                    "layers",
                    f"Hasta {_MAX_ITEMS} videos — 2 o más se publican juntos, como un carrusel.",
                ),
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
        "Sube uno o varios reels y publícalos en una de tus cuentas de Instagram "
        "conectadas — 2 o más se publican juntos, como un carrusel",
    )


def publish_index() -> rx.Component:
    return app_shell(
        publish_topbar(),
        page_body(rx.cond(PublishState.load_error != "", _load_error(), _form())),
    )

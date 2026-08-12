"""Publish screen (A5 vertical slice) — upload a reel, pick a connected account, publish.

Same visual language as `connections_page.py`: badges/callouts drawn from the shared
color-scheme convention, the shared sidebar/topbar shape. Adds the `/publish` route only;
does not touch `connections_page.py` or the mentions dashboard.
"""

from __future__ import annotations

import reflex as rx

from .components import sidebar
from .publishing_state import PublishState
from .publishing_vm import ConnectionOptionVM

_UPLOAD_ID = "publish_upload"


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
        size="2",
        width="100%",
    )


def _upload_zone() -> rx.Component:
    return rx.upload(
        rx.vstack(
            rx.icon("upload", size=28, color=rx.color("gray", 9)),
            rx.text("Arrastra un video o haz clic para elegirlo", size="2"),
            rx.text(
                rx.selected_files(_UPLOAD_ID),
                size="1",
                color=rx.color("gray", 10),
            ),
            spacing="2",
            align="center",
        ),
        id=_UPLOAD_ID,
        accept={"video/mp4": [".mp4"], "video/quicktime": [".mov"]},
        multiple=False,
        max_files=1,
        border=f"1px dashed {rx.color('gray', 7)}",
        border_radius="0.75rem",
        padding="2rem",
        width="100%",
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
        (
            "success",
            rx.cond(
                PublishState.attempt,
                rx.callout(
                    rx.text(
                        "Publicado. ID de media: ",
                        rx.text.strong(PublishState.attempt.published_media_id),
                        size="2",
                    ),
                    icon="circle-check",
                    color_scheme="grass",
                    width="100%",
                ),
                rx.fragment(),
            ),
        ),
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
        rx.icon("send", size=16),
        "Publicar",
        on_click=PublishState.publish(rx.upload_files(upload_id=_UPLOAD_ID)),
        disabled=~PublishState.can_publish,
        size="3",
        width="100%",
    )


def _form() -> rx.Component:
    return rx.vstack(
        rx.text("Cuenta", size="2", weight="bold"),
        _connection_selector(),
        rx.text("Video", size="2", weight="bold"),
        _upload_zone(),
        rx.text("Caption", size="2", weight="bold"),
        rx.text_area(
            placeholder="Escribe el caption...",
            value=PublishState.caption,
            on_change=PublishState.set_caption,
            width="100%",
        ),
        _publish_button(),
        _status_block(),
        spacing="4",
        align_items="start",
        width="100%",
        max_width="560px",
    )


def _load_error() -> rx.Component:
    return rx.callout(
        PublishState.load_error,
        icon="triangle-alert",
        color_scheme="tomato",
        width="100%",
    )


def publish_topbar() -> rx.Component:
    return rx.hstack(
        rx.vstack(
            rx.heading("Publicar", size="6"),
            rx.text(
                "Sube un reel y publícalo en una de tus cuentas de Instagram conectadas",
                size="2",
                color=rx.color("gray", 10),
            ),
            spacing="0",
            align_items="start",
        ),
        rx.spacer(),
        rx.color_mode.button(),
        width="100%",
        padding="1.5rem 2rem 1rem 2rem",
        align="center",
    )


def publish_index() -> rx.Component:
    return rx.hstack(
        sidebar(),
        rx.vstack(
            publish_topbar(),
            rx.box(
                rx.cond(
                    PublishState.load_error != "",
                    _load_error(),
                    _form(),
                ),
                padding="0 2rem 2rem 2rem",
                width="100%",
            ),
            width="100%",
            spacing="4",
            align_items="start",
        ),
        width="100%",
        spacing="0",
        align_items="start",
    )

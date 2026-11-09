"""Pinterest ideas, separate from the business's own catalog photos."""

from __future__ import annotations

import reflex as rx

from .pinterest_state import PinterestState as P
from .pinterest_vm import PinVM
from .ui import callout, card, loading_spinner, section, skeleton_card, tone_badge
from .ui import tokens as T


def _pin_tile(pin: rx.Var[PinVM]) -> rx.Component:
    return card(
        rx.vstack(
            rx.cond(
                pin.thumbnail != "",
                rx.image(
                    src=pin.thumbnail,
                    alt=pin.title,
                    width="100%",
                    height="10rem",
                    object_fit="contain",
                    loading="lazy",
                    referrer_policy="no-referrer",
                ),
                rx.text("Este Pin no tiene una imagen disponible.", size="2"),
            ),
            rx.text(pin.title, size="2", weight="medium", overflow_wrap="anywhere"),
            rx.text(pin.attribution, size="1", color=T.TEXT_MUTED),
            rx.link("Ver idea en Pinterest ↗", href=pin.url, is_external=True, size="1"),
            rx.button(
                "Ver esta idea",
                on_click=P.choose_pin(pin.id),
                disabled=~pin.usable | P.importing,
                variant="soft",
                min_height="44px",
                width="100%",
            ),
            width="100%",
            spacing="2",
            align_items="start",
        ),
        padding="1rem",
        width="100%",
    )


def _preview(pin: rx.Var[PinVM]) -> rx.Component:
    return card(
        rx.vstack(
            rx.heading("¿Usar esta idea como referencia?", size="4", as_="h3"),
            rx.image(
                src=pin.thumbnail,
                alt=pin.title,
                width="100%",
                max_height="18rem",
                object_fit="contain",
                referrer_policy="no-referrer",
            ),
            rx.text(pin.title, size="2", weight="medium"),
            rx.text(pin.attribution, size="1", color=T.TEXT_MUTED),
            rx.link("Ver idea en Pinterest ↗", href=pin.url, is_external=True),
            rx.text(
                "La imagen se enviará al generador como referencia de estilo. "
                "No se publicará automáticamente. Usa imágenes que tengas permiso de utilizar.",
                size="2",
                color=T.TEXT_MUTED,
            ),
            rx.flex(
                rx.button(
                    rx.cond(P.importing, loading_spinner("sm"), rx.icon("image-plus", size=16)),
                    rx.cond(P.importing, "Preparando referencia…", "Usar como referencia"),
                    on_click=P.use_reference,
                    disabled=P.importing,
                    min_height="44px",
                ),
                rx.button(
                    "Elegir otra",
                    variant="soft",
                    on_click=P.cancel_selection,
                    disabled=P.importing,
                    min_height="44px",
                ),
                spacing="2",
                wrap="wrap",
            ),
            spacing="3",
            width="100%",
            align_items="start",
        ),
    )


def _picker() -> rx.Component:
    return rx.vstack(
        rx.heading("Elige un tablero de tu tema", size="4", as_="h3"),
        rx.text(
            "Por ejemplo, un tablero de comida o decoración. Solo mostramos tus tableros públicos.",
            size="2",
            color=T.TEXT_MUTED,
        ),
        rx.flex(
            rx.foreach(
                P.board_items,
                lambda board: rx.button(
                    board.name,
                    variant=rx.cond(P.board_id == board.id, "solid", "soft"),
                    on_click=P.choose_board(board.id),
                    disabled=P.importing,
                    min_height="44px",
                    white_space="normal",
                    aria_pressed=P.board_id == board.id,
                ),
            ),
            rx.cond(
                P.has_more_boards,
                rx.button(
                    "Más tableros",
                    on_click=P.load_boards(True),
                    variant="outline",
                    disabled=P.loading | P.importing,
                    min_height="44px",
                ),
            ),
            wrap="wrap",
            spacing="2",
            width="100%",
        ),
        rx.cond(P.loading, skeleton_card(2)),
        rx.cond(
            ~P.loading & (P.board_items.length() == 0),
            rx.vstack(
                rx.text(
                    "Aún no hay tableros públicos. Crea uno en Pinterest y guarda algunas ideas."
                ),
                rx.link("Abrir Pinterest ↗", href="https://www.pinterest.com/", is_external=True),
                align_items="start",
                spacing="2",
            ),
        ),
        rx.cond(
            P.selected_id != "",
            rx.foreach(P.pin_items, lambda pin: rx.cond(pin.id == P.selected_id, _preview(pin))),
            rx.fragment(
                rx.cond(P.board_name != "", rx.heading(P.board_name, size="3", as_="h3")),
                rx.grid(
                    rx.foreach(P.pin_items, _pin_tile),
                    columns=rx.breakpoints(initial="1", sm="2", md="3"),
                    spacing="3",
                    width="100%",
                ),
                rx.cond(
                    ~P.loading & (P.board_id != "") & (P.pin_items.length() == 0),
                    rx.text(
                        "Este tablero no tiene Pines disponibles. Guarda una imagen o elige otro."
                    ),
                ),
                rx.cond(
                    P.has_more_pins,
                    rx.button(
                        "Ver más ideas",
                        variant="soft",
                        on_click=P.more_pins,
                        disabled=P.loading | P.importing,
                        min_height="44px",
                    ),
                ),
            ),
        ),
        rx.flex(
            rx.button(
                "Actualizar tableros",
                on_click=P.load_boards(False),
                disabled=P.loading | P.importing,
                variant="ghost",
                min_height="44px",
            ),
            rx.button(
                "Cerrar ideas",
                on_click=P.cancel,
                disabled=P.importing,
                variant="soft",
                min_height="44px",
            ),
            spacing="2",
            wrap="wrap",
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )


def pinterest_section(*, from_clip: bool = False) -> rx.Component:
    """One connection/read state; mounted on Galería and the Clip reference step."""
    return section(
        "Ideas de Pinterest",
        rx.box(on_mount=P.load, display="none"),
        rx.cond(P.notice != "", callout(P.notice, "info")),
        rx.cond(P.error != "", callout(P.error, "error")),
        rx.cond(
            P.loading & ~P.opened,
            skeleton_card(2),
            rx.cond(
                P.connected,
                rx.flex(
                    tone_badge("Conectado", "ok"),
                    rx.text(P.username, size="2"),
                    rx.button(
                        "Elegir ideas",
                        on_click=P.open_picker(from_clip),
                        disabled=P.importing,
                        variant="soft",
                        min_height="44px",
                    ),
                    rx.button(
                        "Desconectar Pinterest",
                        on_click=P.disconnect,
                        disabled=P.loading | P.importing,
                        variant="ghost",
                        min_height="44px",
                    ),
                    spacing="2",
                    wrap="wrap",
                    align="center",
                ),
                rx.cond(
                    P.available,
                    rx.button(
                        rx.cond(P.connecting, loading_spinner("sm"), rx.icon("link", size=16)),
                        rx.cond(
                            P.status == "reconnect",
                            "Volver a conectar Pinterest",
                            "Conectar Pinterest",
                        ),
                        on_click=P.start_connect,
                        disabled=P.connecting,
                        variant="soft",
                        min_height="44px",
                    ),
                    callout(
                        "Estamos preparando la conexión con Pinterest. Inténtalo más tarde.",
                        "info",
                    ),
                ),
            ),
        ),
        rx.cond(P.opened & P.connected, _picker()),
        description="Elige ideas de tus tableros para dar una referencia de estilo al clip.",
    )

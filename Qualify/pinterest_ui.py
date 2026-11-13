"""One Pinterest board browser, with account management only in Tus redes."""

from __future__ import annotations

import reflex as rx

from .auth_state import AuthState
from .business_switch import open_connections_tab_script
from .pinterest_state import PinterestState as P
from .pinterest_vm import BoardVM, PinVM
from .ui import callout, card, loading_spinner, section, skeleton_card, tone_badge
from .ui import tokens as T

CONNECT_HINT = (
    "Se abrirá Tus redes en otra pestaña. Al terminar, vuelve aquí y pulsa Actualizar conexión."
)


def _connect_hint() -> rx.Component:
    return rx.vstack(
        rx.text("Conecta Pinterest para ver las ideas de tus tableros.", size="2"),
        rx.button(
            rx.cond(P.status == "reconnect", "Volver a conectar Pinterest", "Conectar Pinterest"),
            on_click=rx.call_script(
                open_connections_tab_script(), callback=AuthState.open_pinterest_connections
            ),
            min_height="44px",
            display="inline-flex",
            align_items="center",
        ),
        rx.text(CONNECT_HINT, size="1", color=T.TEXT_MUTED),
        rx.text(
            "Se abrirá el mismo negocio en Tus redes: ",
            AuthState.business_name,
            ".",
            size="1",
            color=T.TEXT_MUTED,
        ),
        rx.button(
            "Actualizar conexión",
            on_click=P.refresh_picker,
            disabled=P.loading | P.importing,
            variant="soft",
            min_height="44px",
        ),
        align_items="start",
        spacing="2",
        width="100%",
    )


def _pin_tile(pin: rx.Var[PinVM], target: str) -> rx.Component:
    gallery = target == "gallery"
    return card(
        rx.vstack(
            rx.cond(
                pin.thumbnail != "",
                rx.image(
                    src=pin.thumbnail,
                    alt=pin.title,
                    width="100%",
                    height="8rem",
                    object_fit="contain",
                    loading="lazy",
                    referrer_policy="no-referrer",
                ),
                rx.text("Este Pin no tiene una imagen disponible.", size="2"),
            ),
            rx.text(pin.title, size="2", weight="medium", overflow_wrap="anywhere"),
            rx.button(
                "Continuar en Crear publicación" if gallery else "Usar esta imagen",
                on_click=(
                    P.continue_in_create(pin.id) if gallery else P.use_reference(target, pin.id)
                ),
                disabled=~pin.usable | P.loading | P.importing,
                variant="soft",
                min_height="44px",
                width="100%",
            ),
            width="100%",
            spacing="2",
            align_items="start",
        ),
        padding="0.75rem",
        width="100%",
    )


def _pin_list(target: str) -> rx.Component:
    return rx.vstack(
        rx.cond(P.loading, skeleton_card(2)),
        rx.cond(
            P.selected_id != "",
            rx.vstack(
                rx.foreach(
                    P.pin_items,
                    lambda pin: rx.cond(pin.id == P.selected_id, _pin_tile(pin, target)),
                ),
                rx.button(
                    "Elegir otra",
                    variant="soft",
                    on_click=P.cancel_selection,
                    disabled=P.importing,
                    min_height="44px",
                ),
                align_items="start",
                width="100%",
            ),
            rx.fragment(
                rx.grid(
                    rx.foreach(P.pin_items, lambda pin: _pin_tile(pin, target)),
                    columns=rx.breakpoints(initial="1", sm="2", md="3"),
                    spacing="3",
                    width="100%",
                ),
                rx.cond(
                    ~P.loading & (P.pin_items.length() == 0),
                    rx.text(
                        "Este tablero no tiene imágenes disponibles. Elige otro tablero.", size="2"
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
        width="100%",
        spacing="3",
        align_items="start",
    )


def _boards(target: str) -> rx.Component:
    def board_item(board: rx.Var[BoardVM]) -> rx.Component:
        return rx.accordion.item(
            header=rx.text(board.name, min_height="44px", display="flex", align_items="center"),
            content=rx.cond(P.board_id == board.id, _pin_list(target), rx.fragment()),
            value=board.id,
            key=board.id,
        )

    return rx.vstack(
        rx.text("Abre un tablero para ver sus imágenes.", size="2", color=T.TEXT_MUTED),
        rx.accordion.root(
            rx.foreach(P.board_items, board_item),
            type="single",
            collapsible=True,
            value=P.board_id,
            on_value_change=P.choose_board,
            disabled=P.importing,
            variant="surface",
            width="100%",
            id=f"pinterest-{target}-boards",
        ),
        rx.cond(P.loading & (P.board_items.length() == 0), skeleton_card(2)),
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
        rx.flex(
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
            rx.button(
                "Actualizar tableros",
                on_click=P.load_boards(False),
                disabled=P.loading | P.importing,
                variant="ghost",
                min_height="44px",
            ),
            spacing="2",
            wrap="wrap",
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )


def pinterest_picker(target: str) -> rx.Component:
    """Only the active host renders choices: two open photo slots cannot cross-confirm."""
    return rx.vstack(
        rx.cond(
            P.host == target,
            rx.fragment(
                rx.cond(
                    P.importing,
                    rx.hstack(loading_spinner("sm"), rx.text("Preparando imagen…"), role="status"),
                ),
                rx.cond(P.notice != "", callout(P.notice, "info")),
                rx.cond(
                    P.error != "",
                    rx.vstack(
                        callout(P.error, "error"),
                        rx.button(
                            "Volver a elegir esta foto",
                            on_click=P.open_picker(target),
                            disabled=P.loading | P.importing,
                            variant="soft",
                            min_height="44px",
                        )
                        if target != "gallery"
                        else rx.fragment(),
                        width="100%",
                        align_items="start",
                    ),
                ),
                rx.cond(
                    P.loading & ~P.connected,
                    skeleton_card(2),
                    rx.cond(
                        P.connected,
                        rx.vstack(
                            rx.text(P.destination_label, size="2", weight="medium"),
                            rx.text(
                                "Usa imágenes que tengas permiso de utilizar.",
                                size="2",
                                color=T.TEXT_MUTED,
                            )
                            if target != "gallery"
                            else rx.fragment(),
                            _boards(target),
                            align_items="start",
                            width="100%",
                        ),
                        rx.cond(
                            P.available,
                            _connect_hint(),
                            callout(
                                "La conexión con Pinterest no está disponible en este momento. "
                                "Inténtalo más tarde.",
                                "info",
                            ),
                        ),
                    ),
                ),
            ),
            rx.button(
                "Mostrar tableros aquí",
                on_click=P.open_picker(target),
                disabled=P.importing,
                variant="soft",
                min_height="44px",
            ),
        ),
        width="100%",
        spacing="3",
        align_items="start",
    )


def pinterest_section(*, from_clip: bool = False) -> rx.Component:
    """Galería's browser; never manages credentials or chooses a publication format."""
    target = "clip_images" if from_clip else "gallery"
    return section(
        "Ideas de Pinterest",
        rx.box(on_mount=P.open_picker(target), display="none"),
        pinterest_picker(target),
        description="Abre tus tableros y elige una idea para tu publicación.",
    )


def pinterest_connection_card() -> rx.Component:
    """The only rendered disconnect action; lives in Tus redes."""
    return card(
        rx.vstack(
            rx.hstack(
                rx.icon("pin", size=20),
                rx.heading("Pinterest", size="4", as_="h3"),
                rx.spacer(),
                rx.cond(
                    P.connected,
                    tone_badge("Conectado", "ok"),
                    tone_badge("Sin conectar", "neutral"),
                ),
                width="100%",
                align="center",
            ),
            rx.text(
                "Conecta tu cuenta para elegir ideas de tus tableros al crear una publicación.",
                size="2",
            ),
            rx.cond(P.notice != "", callout(P.notice, "info")),
            rx.cond(P.error != "", callout(P.error, "error")),
            rx.cond(
                P.loading,
                skeleton_card(2),
                rx.cond(
                    P.connected,
                    rx.vstack(
                        rx.text(P.username, size="2"),
                        rx.button(
                            "Desconectar Pinterest",
                            on_click=P.disconnect,
                            disabled=P.loading | P.importing,
                            variant="soft",
                            min_height="44px",
                        ),
                        spacing="2",
                        align_items="start",
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
            spacing="3",
            width="100%",
            align_items="start",
        ),
        id="pinterest",
        width="100%",
    )

"""The app's own 404 (m-24840374): the landing's page (`qualify-landing`,
`src/pages/404.astro`) with its «Liquid 404» illustration, «puddle» variant only
(`NotFoundLiquid.astro`). Registered as Reflex's 404 in `Qualify.py`; the scene's CSS is
the «Not found» block of `assets/qualify.css`.

No `app_shell`: the page must work with and without a session, so it stands on the same
ground as the auth screens (`.q-ground`). The button reuses `AuthState.is_authenticated`:
Inicio with a session, the login without one.
"""

from __future__ import annotations

import reflex as rx

from .auth_state import AuthState
from .ui import tokens as T
from .ui.layout import qualify_mark

NOT_FOUND_TAB_TITLE = "Página no encontrada · Qualify"
NOT_FOUND_TITLE = "Esta página no existe"
NOT_FOUND_TEXT = "El enlace está roto o la página cambió de sitio. Todo lo tuyo está en el inicio."
NOT_FOUND_ACTION = "Ir al inicio"


def _liquid_404() -> rx.Component:
    """Decorative: glass digits with liquid inside, the Q mark rocking in a puddle."""
    return rx.el.div(
        rx.el.span("404", class_name="q-nf-digits"),
        rx.el.span(
            rx.el.span(class_name="q-nf-puddle"),
            rx.el.span(class_name="q-nf-ripple"),
            rx.el.span(class_name="q-nf-ripple q-nf-ripple--late"),
            qualify_mark(),
            class_name="q-nf-logo",
        ),
        class_name="q-nf-scene",
        aria_hidden="true",
    )


def not_found_index() -> rx.Component:
    return rx.el.main(
        rx.el.section(
            _liquid_404(),
            rx.vstack(
                rx.heading(NOT_FOUND_TITLE, as_="h1", size="7"),
                rx.text(NOT_FOUND_TEXT, size="3", color=T.TEXT_MUTED),
                spacing="3",
                align="center",
            ),
            rx.link(
                rx.button(NOT_FOUND_ACTION, size="3"),
                href=rx.cond(AuthState.is_authenticated, "/", "/login"),
                underline="none",
            ),
            class_name="q-not-found q-settle",
        ),
        class_name="q-ground q-not-found-stage",
    )

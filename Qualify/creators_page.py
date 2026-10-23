"""Creadores — the «Pronto» screen behind the menu's Creadores entry (founder decision 4,
UX epic m-24842956, NAV-1 m-24842957: Creadores stays in the menu marked «Pronto», and
touching it never opens an empty screen, N10).

Finding local creators to work with is not a product surface yet (the discovery code in
`creator_discovery.py` is an earlier spike with no route). This screen says so honestly,
in the owner's words — what it will do for them — and offers one next step that works
today. Static, no state, no backend call.
"""

from __future__ import annotations

import reflex as rx

from .ui import app_shell, empty_state, page_body, page_header, tone_badge


def creators_index() -> rx.Component:
    return app_shell(
        page_header(
            "Creadores",
            "Te mostraremos personas de tu ciudad que recomiendan negocios como el tuyo, "
            "para que trabajen juntos",
            badge=tone_badge("Pronto", "info"),
        ),
        page_body(
            empty_state(
                "users",
                "Todavía no está lista",
                "Estamos preparando esta parte. Mientras tanto, prepara tu próxima publicación.",
                action=rx.link(
                    rx.button("Crear publicación", size="3"),
                    href="/create",
                ),
            ),
        ),
    )

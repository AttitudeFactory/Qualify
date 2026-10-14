"""`/whatsapp` → Menú tab. PLACEHOLDER until WA-16 replaces this file.

Same hook as `whatsapp_tab_chats.py`: `menu_tab() -> rx.Component` renders only while the
tab is active, inside a box keyed by `WhatsAppState.selected_connection_id`, so the root's
`on_mount` fires on tab entry and on every number switch. Read the number from
`WhatsAppState.selected_connection_id` / `WhatsAppState.selected_number`. The shell
(`whatsapp_page.py`) owns the header, the selector and the no-number state.
"""

from __future__ import annotations

import reflex as rx

from .ui import empty_state


def menu_tab() -> rx.Component:
    return empty_state(
        "list-tree",
        "El editor de menús llega con la siguiente entrega",
        "Aquí vas a armar la bienvenida, los atajos y el menú de productos que responde "
        "solo en este número.",
    )

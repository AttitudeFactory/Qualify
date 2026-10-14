"""`/whatsapp` → Chats tab. PLACEHOLDER until WA-11 (QUA-210) replaces this file.

The hook WA-11 builds against (`whatsapp_page.py` owns the shell, not this file):

- `chats_tab() -> rx.Component` is rendered ONLY while the tab is active, inside a box
  keyed by `WhatsAppState.selected_connection_id`. So the root's `on_mount` fires on tab
  entry AND on every number switch — that is the place to start the conversations load
  (guard it: React may mount twice in dev).
- The number on screen is `WhatsAppState.selected_connection_id` (a `str` uuid; "" when the
  tenant has no WhatsApp number — the shell shows its own empty state then and never
  renders this tab). `WhatsAppState.selected_number` is its `WhatsAppNumberVM`.
- The page header, the number selector, and the empty/loading/error states of the number
  list are the shell's. This file only draws the tab's body.
"""

from __future__ import annotations

import reflex as rx

from .ui import empty_state


def chats_tab() -> rx.Component:
    return empty_state(
        "messages-square",
        "Los chats llegan con la siguiente entrega",
        "Aquí vas a atender las conversaciones de WhatsApp de este número: responder, "
        "asignar y marcar pedidos listos.",
    )

"""Shell state: the zen (collapsed) sidebar.

Deliberately server-side session state, not client storage: the logout-hygiene ruling
forbids persisting business data in the browser outside tenant-namespaced keys, and a
Reflex state var already survives navigation within the session — which is the memory
the mode actually needs. Nothing here is tenant data, so logout does not have to reset
it (a fresh login simply starts expanded).
"""

from __future__ import annotations

import reflex as rx


class NavState(rx.State):
    """Whether the sidebar is collapsed to icons."""

    zen: bool = False

    @rx.event
    def toggle_zen(self) -> None:
        self.zen = not self.zen

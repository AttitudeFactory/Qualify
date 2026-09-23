"""Shell state: the zen (collapsed) sidebar, and the mobile drawer.

Deliberately server-side session state, not client storage: the logout-hygiene ruling
forbids persisting business data in the browser outside tenant-namespaced keys, and a
Reflex state var already survives navigation within the session — which is the memory
the mode actually needs. Nothing here is tenant data, so logout does not have to reset
it (a fresh login simply starts expanded).

``mobile_open`` is separate from ``zen``: zen is a desktop density preference (icons
only, sidebar still always visible, still pushes the page panel); the mobile drawer is
an on/off overlay that never pushes the panel (there is no room to push on a phone
width) — see the ``@media`` rules in ``assets/qualify.css`` under ``.q-sidebar``.
Reported 2026-09-23: on a phone viewport the sidebar and the page panel were rendering
side by side with no way to collapse either, so a narrow phone showed a sliver of each
and the "Stories" upload dropzone was too cramped to use.
"""

from __future__ import annotations

import reflex as rx


class NavState(rx.State):
    """Whether the sidebar is collapsed to icons (``zen``) or, on a phone-width
    viewport, open as an overlay drawer (``mobile_open``)."""

    zen: bool = False
    mobile_open: bool = False

    @rx.event
    def toggle_zen(self) -> None:
        self.zen = not self.zen

    @rx.event
    def toggle_mobile_nav(self) -> None:
        self.mobile_open = not self.mobile_open

    @rx.event
    def close_mobile_nav(self) -> None:
        self.mobile_open = False

"""Restore in-place route state on browser back/forward (PASOS-3, m-24852246).

pushState deliberately avoids navigation, so React Router may still remember the
entry before a tab/detail was opened. A POP to that same entry can then skip on_load.
The mounted route owns one explicit, idempotent handler reading the live address.
"""

from __future__ import annotations

from typing import Any

import reflex as rx

_POP_SCRIPT = (
    "if (!window.__qRoutePop) { window.__qRoutePop = true;"
    " window.addEventListener('popstate', () => window.setTimeout(() =>"
    " document.querySelector('main.q-panel .q-route-pop')?.click(), 0)); }"
)


def route_history(on_pop: Any, *, on_leave: Any | None = None) -> rx.Component:
    return rx.el.button(
        type="button",
        hidden=True,
        tab_index=-1,
        aria_hidden="true",
        class_name="q-route-pop",
        on_click=on_pop,
        on_mount=rx.call_script(_POP_SCRIPT),
        **({"on_unmount": on_leave} if on_leave is not None else {}),
    )

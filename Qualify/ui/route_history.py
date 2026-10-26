"""Restore in-place route state on browser back/forward (PASOS-3, m-24852246).

pushState deliberately avoids navigation, so React Router may still remember the
entry before a tab/detail was opened. A POP to that same entry can then skip on_load.
The mounted route owns one explicit, idempotent handler reading the live address.
"""

from __future__ import annotations

import json
from typing import Any

import reflex as rx

from .flow_history import _FLOW_INSTALL_SCRIPT

_POP_SCRIPT = (
    "if (!window.__qRoutePop) { window.__qRoutePop = true;"
    " window.addEventListener('popstate', () => { window.__qFlowRouteNode = null;"
    " window.setTimeout(() => document.querySelector('main.q-panel .q-route-pop')?.click(), 0);"
    " }); }"
)


_LEASE_SCRIPT = """(() => {
 const node = document.querySelector('main.q-panel .q-route-pop');
 if (!node) return {};
 window.__qRouteDocument ||= window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
 window.__qRouteSequence = (window.__qRouteSequence || 0) + 1;
 node.dataset.historyLease = window.__qRouteDocument + ':' + window.__qRouteSequence;
 window.__qFlowRouteNode = null;
 return {visit: node.dataset.historyLease, href: window.location.href};
})()"""


def route_history_ready(path: str, lease: dict) -> rx.event.EventSpec:
    """Only the backend ACK for this exact DOM visit and address can arm writes."""
    visit = lease.get("visit", "") if isinstance(lease, dict) else ""
    href = lease.get("href", "") if isinstance(lease, dict) else ""
    return rx.call_script(
        "(() => { const node = document.querySelector('main.q-panel .q-route-pop');"
        f" if (!node || node.dataset.historyLease !== {json.dumps(visit)}) return;"
        f" if (window.location.href !== {json.dumps(href)}) return;"
        f" if (window.location.pathname.replace(/\\/$/, '') !== {json.dumps(path)}) return;"
        " window.__qFlowRouteNode = node; window.__qFlowSync?.(); })();"
    )


def route_history(on_pop: Any, *, on_leave: Any | None = None) -> rx.Component:
    return rx.el.button(
        type="button",
        hidden=True,
        tab_index=-1,
        aria_hidden="true",
        class_name="q-route-pop",
        on_click=rx.call_script(_LEASE_SCRIPT, callback=on_pop),
        on_mount=[
            rx.call_script(_POP_SCRIPT + _FLOW_INSTALL_SCRIPT),
            rx.call_script(_LEASE_SCRIPT, callback=on_pop),
        ],
        **({"on_unmount": on_leave} if on_leave is not None else {}),
    )

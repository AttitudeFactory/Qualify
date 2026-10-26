"""Every tab, view and detail has its own address (N5, m-24842960 NAV-2).

A screen that switches a tab or opens a detail in place writes the new address with
`history.pushState` (`push_url`) instead of `rx.redirect`: a redirect is a React Router
navigation, which re-runs the route's whole `on_load` (and its reads) for a change the
state already made. Reflex reads the live `window.location` for `router_data`
(`withRouterData` in `state.js`), so the backend still sees the new query string.

A pushed URL can be invisible to React Router: popping back to the router's last
known entry may skip `on_load`. Routes with in-place URLs mount `ui.route_history`
and explicitly restore their state on `popstate`; the handlers also serve reloads.
Never rely on an unchanged router history key to trigger a fresh route load.

Pure string builders (no Reflex import, so `*_vm.py` modules can use them), tested in
`test_nav_url.py`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from urllib.parse import urlencode
from uuid import UUID


def with_query(path: str, **params: str) -> str:
    """`path` plus the non-empty `params` as a query string, in the given order."""
    kept = {key: value for key, value in params.items() if value}
    return f"{path}?{urlencode(kept)}" if kept else path


def _history_script(method: str, url: str) -> str:
    # The guard keeps a repeated click from stacking identical history entries;
    # `history.state` is carried over so React Router keeps its own bookkeeping.
    target = json.dumps(url)
    return (
        f"if (window.location.pathname + window.location.search !== {target}) "
        f"window.history.{method}("
        + (
            "{ ...window.history.state,"
            " qPrevHref: window.location.pathname + window.location.search }"
            if method == "pushState"
            else "window.history.state"
        )
        + f", '', {target});"
    )


def push_url_script(url: str) -> str:
    """JS that adds `url` to the history (a new «atrás» step) without navigating."""
    return _history_script("pushState", url)


def replace_url_script(url: str) -> str:
    """JS that rewrites the current address to `url` without adding a history step."""
    return _history_script("replaceState", url)


def scalar_param(params: Mapping[str, object], key: str) -> str:
    """A URL parameter is a single string; repeated/malformed values are refused."""
    value = params.get(key, "")
    return value if isinstance(value, str) else ""


def uuid_param(params: Mapping[str, object], key: str) -> str:
    """Only canonical internal UUIDs, never a customer's name/phone or arbitrary text."""
    try:
        return str(UUID(scalar_param(params, key)))
    except (ValueError, TypeError, AttributeError):
        return ""


def back_url_script(url: str) -> str:
    """In-app back consumes its own detail entry, otherwise replaces the address.

    Unlike pushing the list again, browser back can never reopen the closed detail.
    """
    target = json.dumps(url)
    return (
        f"if (window.history.state?.qPrevHref === {target}) window.history.back();"
        f"else window.history.replaceState(window.history.state, '', {target});"
    )


def conversation_href(channel: str, connection_id: str = "", thread_id: str = "") -> str:
    """Canonical owner-facing routes carrying only internal account/thread IDs."""
    ids = {"cuenta": connection_id, "chat": thread_id}
    safe = {key: uuid_param(ids, key) for key in ids}
    if channel == "whatsapp":
        return with_query("/whatsapp", tab="chats", **safe)
    return with_query("/responder", tab="mensajes", **safe)


def thread_param(params: Mapping[str, object], connection_id: str) -> str:
    """Refuse a requested account outside the already-authorized selected account."""
    requested = uuid_param(params, "cuenta")
    if "cuenta" in params and (not requested or requested != connection_id):
        return ""
    return uuid_param(params, "chat")


def flow_param(params: Mapping[str, object], flow: str, total: int) -> int:
    """The active flow's clamped step, or 0 when this form is not in the address."""
    if scalar_param(params, "flujo") != flow:
        return 0
    try:
        step = int(scalar_param(params, "paso"))
    except (ValueError, TypeError):
        step = 1
    return min(max(step, 1), max(total, 1))


def close_flow_script(flow: str) -> str:
    """Close without adding history entries, restoring the place that opened the form."""
    return (
        "(() => { const u = new URL(window.location.href);"
        f" if (u.searchParams.get('flujo') !== {json.dumps(flow)}) return;"
        " const st = window.history.state || {};"
        " if (st.qFlowRoot && st.qFlowDepth > 0) { window.history.go(-st.qFlowDepth); return; }"
        " for (const key of ['flujo', 'paso', 'objeto', 'consulta']) u.searchParams.delete(key);"
        " window.history.replaceState(st, '', u.pathname + u.search + u.hash); })();"
    )

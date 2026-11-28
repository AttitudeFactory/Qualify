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


def replace_url_keep_hash_script(url: str) -> str:
    """JS that rewrites the address to `url` (no history step) only while the browser is
    still on `url`'s page — a late answer never rewrites the page the owner moved to —
    and keeps the address's `#anchor` (m-25143230: «Resultados › WhatsApp»'s
    `#actividad-numero`)."""
    path = json.dumps(url.split("?", 1)[0])
    target = json.dumps(url)
    return (
        f"if (window.location.pathname.replace(/\\/$/, '') === {path}"
        f" && window.location.pathname + window.location.search !== {target}) "
        f"window.history.replaceState(window.history.state, '', {target} + window.location.hash);"
    )


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


#: m-25017859: `?desde=por-responder` was on a WhatsApp chat opened from the single list
#: of «Por responder» while that chat lived on `/whatsapp`. m-25029798: the chat opens in
#: «Por responder» itself; an old address carrying it redirects there, dropping it.
FROM_PARAM = "desde"
FROM_INBOX = "por-responder"
#: The single list of «Por responder» (`/responder?tab=mensajes`), where every chat opens.
INBOX_ROUTE = "/responder"
INBOX_TAB = "mensajes"
#: m-25029799: WhatsApp's chats are attended only there — the list narrowed to WhatsApp
#: (every number). Where a link «to the WhatsApp chats» lands.
WHATSAPP_CHATS_HREF = f"{INBOX_ROUTE}?tab={INBOX_TAB}&canal=whatsapp"


def whatsapp_chats_href(number: str = "", filter_slug: str = "") -> str:
    """m-25029799: the WhatsApp chats in «Por responder» — on the chip `filter_slug` (one
    of the list's own slugs, "" = its default) and, for a business with several
    numbers, narrowed to `number` (a connection id; the list keeps it only if it is the
    business's). Only a slug and a canonical UUID travel."""
    return with_query(
        INBOX_ROUTE,
        tab=INBOX_TAB,
        filtro=_slug(filter_slug).lower(),
        canal="whatsapp",
        numero=uuid_param({"numero": number}, "numero"),
    )


#: m-25017859: the single list's own view (`?filtro=` / `?canal=`) rides along the
#: Instagram chat addresses it opens, so «atrás» and a reload keep the list as it was.
LIST_VIEW_PARAMS = ("filtro", "canal")
#: m-25029799: and the WhatsApp number picked in it (a connection id, never a slug).
NUMBER_VIEW_PARAM = "numero"


def _slug(value: object) -> str:
    """A view slug as it may travel in an address: lowercase letters and dashes only."""
    text = value if isinstance(value, str) else ""
    return (
        text
        if len(text) <= 32 and all(c.isascii() and (c.isalpha() or c == "-") for c in text)
        else ""
    )


def list_view(params: Mapping[str, object]) -> dict[str, str]:
    """The `?filtro=` / `?canal=` of the current address, if they are plain slugs, and
    its `?numero=` if it is a canonical UUID (m-25029799)."""
    view = {k: s for k in LIST_VIEW_PARAMS if (s := _slug(params.get(k, "")).lower())}
    if number := uuid_param(params, NUMBER_VIEW_PARAM):
        view[NUMBER_VIEW_PARAM] = number
    return view


def inbox_chat_href(
    connection_id: str = "", thread_id: str = "", *, view: Mapping[str, str] | None = None
) -> str:
    """m-25029798: the one address of an open chat, whatever its channel —
    `/responder?tab=mensajes[&filtro=…&canal=…&numero=…]&cuenta=<account>&chat=<thread>`
    — or, with no chat, the single list (the account kept as Instagram's has always
    been). Only canonical UUIDs and the list's own `view` slugs travel."""
    ids = {"cuenta": connection_id, "chat": thread_id}
    safe = {key: uuid_param(ids, key) for key in ids}
    given = view or {}
    kept = {k: _slug(v) for k, v in given.items() if k in LIST_VIEW_PARAMS}
    kept[NUMBER_VIEW_PARAM] = uuid_param(given, NUMBER_VIEW_PARAM)
    return with_query(INBOX_ROUTE, tab=INBOX_TAB, **kept, **safe)


def conversation_href(
    channel: str,
    connection_id: str = "",
    thread_id: str = "",
    *,
    view: Mapping[str, str] | None = None,
) -> str:
    """Canonical owner-facing routes carrying only internal account/thread IDs: a chat
    of either `channel` opens in «Por responder» (`inbox_chat_href`, m-25029798), and
    m-25029799 retired WhatsApp's own list, the one place a WhatsApp address without a
    chat used to lead."""
    del channel  # every channel's chat has the same address now
    return inbox_chat_href(connection_id, thread_id, view=view)


def inbox_back_script(fallback: str) -> str:
    """«‹ Por responder» from an open chat (m-25029798, both channels): when the step
    before this one is the single list (any filter or channel, no chat open), go back
    to it — the history entry is consumed, so «atrás» never reopens the chat; otherwise
    (a chat opened by its address) the address becomes `fallback` in place."""
    target = json.dumps(fallback)
    return (
        "(() => { const p = window.history.state?.qPrevHref;"
        f" const list = typeof p === 'string' && p.split('?')[0].replace(/\\/$/, '')"
        f" === {json.dumps(INBOX_ROUTE)} && !/[?&]chat=/.test(p)"
        f" && !/[?&]tab=(?!{INBOX_TAB}(&|$))/.test(p);"
        " if (list) { window.history.back(); return; }"
        f" window.history.replaceState(window.history.state, '', {target}); }})();"
    )


def thread_param(params: Mapping[str, object], connection_id: str) -> str:
    """Refuse a requested account outside the already-authorized selected account."""
    requested = uuid_param(params, "cuenta")
    if "cuenta" in params and (not requested or requested != connection_id):
        return ""
    return uuid_param(params, "chat")


def drop_param_script(key: str) -> str:
    """JS that removes one parameter (`key`, one of the app's own) from the current
    address in place — no new history step — and keeps every other one, an open chat's
    `cuenta`/`chat` included (m-25029799 review)."""
    name = json.dumps(_slug(key))
    return (
        "(() => { const u = new URL(window.location.href);"
        f" if (!u.searchParams.has({name})) return;"
        f" u.searchParams.delete({name});"
        " window.history.replaceState(window.history.state, '', u.pathname + u.search + u.hash);"
        " })();"
    )


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


def close_flow_then_go_script(flow: str, href: str) -> str:
    """`close_flow_script`, then open `href` — only once the history has settled.
    `history.go(-n)` is asynchronous: a redirect sent alongside it is undone by the late
    pop, so the navigation waits for that `popstate` (m-25026350). Back from `href`
    lands on the page that opened the form, never on the form again. If the pop never
    comes (a depth that drifted after a reload or a deep link makes `go(-n)` a no-op),
    a fallback timer still leaves; `done` makes the navigation happen exactly once."""
    return (
        "(() => { const u = new URL(window.location.href); let done = false;"
        f" const go = () => {{ if (done) return; done = true;"
        f" window.location.assign({json.dumps(href)}); }};"
        f" if (u.searchParams.get('flujo') !== {json.dumps(flow)}) {{ go(); return; }}"
        " const st = window.history.state || {};"
        " if (st.qFlowRoot && st.qFlowDepth > 0) {"
        " const late = setTimeout(go, 1500);"
        " window.addEventListener('popstate', () => { clearTimeout(late); setTimeout(go, 0); },"
        " { once: true });"
        " window.history.go(-st.qFlowDepth); return; }"
        " for (const key of ['flujo', 'paso', 'objeto', 'consulta']) u.searchParams.delete(key);"
        " window.history.replaceState(st, '', u.pathname + u.search + u.hash); go(); })();"
    )

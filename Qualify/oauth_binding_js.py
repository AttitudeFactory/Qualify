"""Send the browser to an OAuth consent page holding its binding cookie (m-24921205).

The connect handlers mint the consent URL in-process over the websocket, so the API never
gets to `Set-Cookie`: the browser itself must store the per-flow binding nonce before it
leaves for Meta/TikTok, or the callback rejects it as `invalid_state`. One script does both,
in order — set the cookie, then navigate — so the two can never be split.

Same host (m-24947215): the handlers pass the page's origin (`page_origin`, the browser's
`Origin` on the websocket) to the connect seam, which puts the provider callback on that
host when it is an allow-listed public host registered at the provider
(`qualify_api.connections.public_hosts`). Then the callback host IS the page host, the
cookie set here reaches it, and the callback lands back on `/connections` of that same
host, where the client's session lives.

Host guard, for the remaining case — a host whose callback the provider does not know (Meta
on `app.qualify.la` until it is registered): a cookie set here would never reach the
callback, so the script instead moves the user to the same path and query on the APP's
configured origin (`connections_routes.configured_connections_page_url`), where the next
click starts a flow that can complete. Hostnames are compared, not ports: cookies ignore
ports, so local dev (UI :3000, API :8000) works. Without a known app origin it falls back to
the callback's scheme://hostname, port dropped (the port is the API's, not the app's).

Pure string building, unit-tested without a browser; every interpolated value goes through
`json.dumps`, so nothing in a URL or cookie can break out of its JS string literal.
"""

from __future__ import annotations

import json
from urllib.parse import urlsplit

import reflex as rx
from qualify_api.connections.state_token import BINDING_COOKIE_PATH, StartedConnect
from qualify_api.http.connections_routes import configured_connections_page_url


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else ""


def app_origin() -> str:
    """The app's configured public origin (`QUALIFY_APP_URL` / `REFLEX_DEPLOY_URL`)."""
    return _origin(configured_connections_page_url())


def page_origin(state: rx.State) -> str:
    """The origin of the page an event came from (`https://app.qualify.la`), as the browser
    sent it in the websocket's `Origin` header; "" when unknown. Not trusted by itself:
    the connect seam only uses an allow-listed host (`public_hosts.redirect_uri_for`)."""
    try:
        return str(state.router.headers.origin or "")
    except AttributeError:  # a state built outside a request (tests) has no router data
        return ""


def bound_redirect_script(
    *,
    authorization_url: str,
    cookie_name: str,
    cookie_value: str,
    max_age: int,
    callback_url: str,
    app_origin: str = "",
) -> str:
    """The JS that stores the binding cookie and then opens the consent page."""
    callback = urlsplit(callback_url)
    hostname = (callback.hostname or "") if callback.scheme else ""
    # Only an app origin on the callback's own hostname can hold the cookie; any other one
    # would bounce the user back here forever, so it falls back to the callback's host.
    origin = (
        _origin(app_origin)
        if urlsplit(app_origin).hostname == hostname
        else f"{callback.scheme}://{hostname}"
    )
    cookie_tail = f"; Path={BINDING_COOKIE_PATH}; Max-Age={int(max_age)}; SameSite=Lax"
    guard = (
        f"if (window.location.hostname !== {json.dumps(hostname)}) {{"
        f" window.location.assign({json.dumps(origin)}"
        " + window.location.pathname + window.location.search); return; }"
        if hostname
        else ""
    )
    return (
        "(function () {"
        f" {guard}"
        ' var secure = window.location.protocol === "http:" ? "" : "; Secure";'
        f' document.cookie = {json.dumps(cookie_name)} + "=" + {json.dumps(cookie_value)}'
        f" + {json.dumps(cookie_tail)} + secure;"
        f" window.location.assign({json.dumps(authorization_url)});"
        " })()"
    )


def script_for(started: StartedConnect, *, origin: str = "") -> str:
    return bound_redirect_script(
        authorization_url=started.authorization_url,
        cookie_name=started.binding_cookie_name,
        cookie_value=started.binding_nonce,
        max_age=started.max_age,
        callback_url=started.callback_url,
        app_origin=origin,
    )


def bound_redirect(started: StartedConnect) -> rx.event.EventSpec:
    """The one event a connect handler yields instead of `rx.redirect(url)`."""
    return rx.call_script(script_for(started, origin=app_origin()))

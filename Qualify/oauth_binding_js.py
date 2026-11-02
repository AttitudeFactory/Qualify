"""Send the browser to an OAuth consent page holding its binding cookie (m-24921205).

The connect handlers mint the consent URL in-process over the websocket, so the API never
gets to `Set-Cookie`: the browser itself must store the per-flow binding nonce before it
leaves for Meta/TikTok, or the callback rejects it as `invalid_state`. One script does both,
in order — set the cookie, then navigate — so the two can never be split.

Host guard: the cookie is host-only and the callback runs on the host of the registered
redirect URI. If the page is open on another host (e.g. `app.qualify.la`), a cookie set here
would never reach the callback, so the script instead moves the user to the same path on the
callback's origin, where the next click starts a flow that can complete. Hostnames are
compared, not ports: cookies ignore ports, so local dev (UI :3000, API :8000) works.

Pure string building, unit-tested without a browser; every interpolated value goes through
`json.dumps`, so nothing in a URL or cookie can break out of its JS string literal.
"""

from __future__ import annotations

import json
from urllib.parse import urlsplit

import reflex as rx
from qualify_api.connections.state_token import BINDING_COOKIE_PATH, StartedConnect


def _origin_and_hostname(callback_url: str) -> tuple[str, str]:
    parts = urlsplit(callback_url)
    if not parts.scheme or not parts.hostname:
        return "", ""
    return f"{parts.scheme}://{parts.netloc}", parts.hostname


def bound_redirect_script(
    *,
    authorization_url: str,
    cookie_name: str,
    cookie_value: str,
    max_age: int,
    callback_url: str,
) -> str:
    """The JS that stores the binding cookie and then opens the consent page."""
    origin, hostname = _origin_and_hostname(callback_url)
    cookie_tail = f"; Path={BINDING_COOKIE_PATH}; Max-Age={int(max_age)}; SameSite=Lax"
    guard = (
        f"if (window.location.hostname !== {json.dumps(hostname)}) {{"
        f" window.location.assign({json.dumps(origin)} + window.location.pathname); return; }}"
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


def script_for(started: StartedConnect) -> str:
    return bound_redirect_script(
        authorization_url=started.authorization_url,
        cookie_name=started.binding_cookie_name,
        cookie_value=started.binding_nonce,
        max_age=started.max_age,
        callback_url=started.callback_url,
    )


def bound_redirect(started: StartedConnect) -> rx.event.EventSpec:
    """The one event a connect handler yields instead of `rx.redirect(url)`."""
    return rx.call_script(script_for(started))

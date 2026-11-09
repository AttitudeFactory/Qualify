"""Which public host an OAuth round trip runs on (m-24947215).

Production serves the same app on more than one host (`app.qualify.la`, where clients log
in, and `qualify.attitudefactory.co`, `QUALIFY_PUBLIC_URL`). The Reflex session lives in
per-origin browser storage, and the browser-binding cookie of the connect flow is host-only
(`state_token`, defense 4). So the whole round trip — start, cookie, provider callback and
the landing back on `/connections` — must stay on the host the client is using, or the
client arrives on the other host with no session.

The browser's host is never trusted as such: it is used only when it is on an allow-list.

- `QUALIFY_PUBLIC_HOSTS` (comma- or space-separated hostnames): every host the app is
  served on. The hostname of `QUALIFY_PUBLIC_URL` is always included, so an unset variable
  keeps the single-host behaviour.
- Per provider, the hosts whose callback is REGISTERED at that provider. TikTok: every
  public host (both callbacks are registered in its portal). Meta: only the host of
  `QUALIFY_META_REDIRECT_URI`, plus `QUALIFY_META_REDIRECT_HOSTS` once those callbacks are
  added to «Valid OAuth Redirect URIs» — a redirect URI Meta does not know fails at its
  dialog, so Meta stays opt-in per host.

Anything else (an unknown host, a port, a non-https origin) falls back to the configured
redirect URI, exactly as before.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from urllib.parse import urlsplit, urlunsplit

_HOSTNAME = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*")


def _hostnames(raw: str) -> frozenset[str]:
    names = (part.strip().lower().rstrip(".") for part in re.split(r"[\s,]+", raw or ""))
    return frozenset(name for name in names if name and _HOSTNAME.fullmatch(name))


def _hostname_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def public_hosts(environ: Mapping[str, str] | None = None) -> frozenset[str]:
    """Every hostname the app is served on (the allow-list)."""
    env = os.environ if environ is None else environ
    hosts = set(_hostnames(env.get("QUALIFY_PUBLIC_HOSTS", "")))
    canonical = _hostname_of(env.get("QUALIFY_PUBLIC_URL", "").strip())
    if canonical:
        hosts.add(canonical)
    return frozenset(hosts)


def meta_redirect_hosts(environ: Mapping[str, str] | None = None) -> frozenset[str]:
    """Extra hosts whose Meta callback is registered in the Meta app (opt-in), restricted
    to the public hosts."""
    env = os.environ if environ is None else environ
    return _hostnames(env.get("QUALIFY_META_REDIRECT_HOSTS", "")) & public_hosts(env)


def browser_hostname(origin: str) -> str:
    """The hostname of a browser origin (`https://host`), or "" when it is not a plain
    https origin without a port. A public host behind the edge proxy never shows one."""
    try:
        parts = urlsplit((origin or "").strip())
        port = parts.port
    except ValueError:
        return ""
    if parts.scheme != "https" or port is not None or parts.path not in ("", "/"):
        return ""
    if parts.query or parts.fragment or parts.username or parts.password:
        return ""
    host = (parts.hostname or "").lower()
    return host if _HOSTNAME.fullmatch(host) else ""


def redirect_uri_for(configured: str, origin: str, allowed_hosts: Iterable[str]) -> str:
    """The provider redirect URI for a flow started from `origin`.

    Same path as the configured one, on the browser's host — only when that host is in
    `allowed_hosts` and the configured URI is https. Otherwise the configured URI."""
    host = browser_hostname(origin)
    parts = urlsplit(configured)
    if not host or parts.scheme != "https" or host == (parts.hostname or "").lower():
        return configured
    if host not in frozenset(allowed_hosts):
        return configured
    return urlunsplit(("https", host, parts.path, parts.query, ""))


def request_origin(host_header: str | None, environ: Mapping[str, str] | None = None) -> str:
    """`https://<host>` for an allow-listed `Host` header, else "". For the HTTP routes,
    whose response (and cookie) belongs to exactly this host."""
    raw = (host_header or "").strip().lower()
    if not raw or not _HOSTNAME.fullmatch(raw):  # a port or anything odd: not public
        return ""
    return f"https://{raw}" if raw in public_hosts(environ) else ""


def page_url_on_host(
    default_page_url: str, host_header: str | None, environ: Mapping[str, str] | None = None
) -> str:
    """The `/connections` URL on the host a callback arrived on, when that host is public;
    the configured page URL otherwise (and in local dev, where the API runs on the app's
    hostname with another port)."""
    origin = request_origin(host_header, environ)
    if not origin:
        return default_page_url
    parts = urlsplit(default_page_url)
    host = origin.removeprefix("https://")
    if host == (parts.hostname or "").lower():
        return default_page_url
    return urlunsplit(("https", host, parts.path, parts.query, ""))

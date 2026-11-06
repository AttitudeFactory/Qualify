"""The networks' CDN hosts, and the rule a picture URL must meet to be fetched from them
(m-24957331, CodeQL py/full-ssrf).

**A subset, on purpose.** This is only what the picture proxy (`Qualify/avatar_proxy.py`)
needs: the CDN suffixes (`CDN_HOST_SUFFIXES`) and the host rule (`url_on_hosts`). The full
module comes with #470 (ADR 42 R12, m-24854859, «Ideas para tus reels»: the cover download
and re-encode, `signature_expired`, `heif_to_jpeg`, `cdn_host_allowed`), with exactly these
names, values and signatures — so its later merge is a plain union: keep #470's file, add
`url_on_hosts` from here and let `cdn_host_allowed(url)` be `url_on_hosts(url,
CDN_HOST_SUFFIXES)`, as on the reviewed branch `fix/m-24957331-proxy-avatares-ssrf`.

The rule (`url_on_hosts`): `https` only, on port 443, without credentials, written in
printable ASCII (no control character, no space, no non-ASCII host), on a host that is one
of the given suffixes or a subdomain of one, or exactly one of the `exact` names — a third
party's, never its subdomains.
"""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlsplit

#: Hosts a network's picture may come from — suffix match on the hostname. The proxy adds
#: unavatar.io for profile pictures only, as an exact name.
CDN_HOST_SUFFIXES: tuple[str, ...] = (
    "tiktokcdn.com",
    "tiktokcdn-us.com",
    "tiktokcdn-eu.com",
    "cdninstagram.com",
    "fbcdn.net",
)


def url_on_hosts(url: str, suffixes: Iterable[str], *, exact: Iterable[str] = ()) -> bool:
    """True for an `https` URL on port 443, without credentials, whose host is one of
    `suffixes` or a subdomain of one, or exactly one of `exact` (a third party's name,
    never its subdomains) — written in printable ASCII only. `urlsplit` silently
    drops a tab or a newline that httpx refuses, so `https://evil.com\\t.cdninstagram.com/`
    would pass a host check that httpx then reads differently (review of R12)."""
    if not isinstance(url, str) or not url.isascii() or not url.isprintable() or " " in url:
        return False
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and port in (None, 443)
        and parts.username is None
        and parts.password is None
        and bool(host)
        and (
            host in set(exact)
            or any(host == suffix or host.endswith("." + suffix) for suffix in suffixes)
        )
    )


__all__ = [
    "CDN_HOST_SUFFIXES",
    "url_on_hosts",
]

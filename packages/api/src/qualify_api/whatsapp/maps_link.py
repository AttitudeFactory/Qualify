"""Reading the shop's point out of a Google Maps link (m-24945889, «Tu local en el mapa»,
`docs/ux-whatsapp-atajos.md`) — the ONE parser for any link the owner pastes.

On a phone, Google Maps opens in its app, where «Compartir» only gives a short
`maps.app.goo.gl` link and there is no address bar: so a short link is FOLLOWED here,
safely, to the long URL that carries the coordinates.

**What is accepted.** Only `https://` URLs on Google Maps hosts:
`maps.app.goo.gl`, `goo.gl` with a path under `/maps`, `maps.<d>`, and `www.<d>/maps…` /
`<d>/maps…` for a domain `<d>` of `GOOGLE_DOMAINS` (an explicit list); no credentials,
no trailing dot, no port but 443. Anything else → `not_a_maps_link`.

**Following a short link** (`default_hop`, the SSRF guard of `menus/import_ai.
default_fetch`): at most `MAX_HOPS` (3) redirects within `DEADLINE_S` (4 s) in all —
every hop, request and read draws on the same total budget;
`HEAD` first, `GET` (reading at most 64 KB, never the body's content) when the server
refuses `HEAD`; no cookies, no credentials, no proxy from the environment; every hop is
https, its host must be one of the hosts above, and the name must resolve only to
public addresses — the connection is pinned to the checked address (no DNS rebinding).
A hop to any other host → `unsafe_redirect`. The final URL must be a long Google Maps
URL. No DB, no queue: the call happens on the owner's tap in Perfil.

**Parsing the long URL** (pure, `parse_maps_url`): the place's own pin `!3d<lat>!4d<lng>`
first, then `?q=`/`query=`/`ll=`/`destination=`/`center=` coordinates, then the view's
centre `@<lat>,<lng>` (also under `/place/<name>/@…`); ranges ±90/±180; the place's name
from `/place/<name>/` when there is one.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final
from urllib.parse import unquote, unquote_plus, urljoin, urlsplit

MAX_HOPS: Final = 3
DEADLINE_S: Final = 4.0
MAX_GET_BYTES: Final = 64 * 1024

REASON_NOT_MAPS: Final = "not_a_maps_link"
REASON_UNSAFE: Final = "unsafe_redirect"
REASON_NO_POINT: Final = "no_point"
REASON_UNREACHABLE: Final = "unreachable"

_SHORT_HOST: Final = "maps.app.goo.gl"
_GOO_GL: Final = "goo.gl"
#: The Google domains a Maps link may come from (security review: an explicit list, not a
#: `google.<tld>` pattern) — the global one and those of the markets Qualify serves.
GOOGLE_DOMAINS: Final = frozenset(
    {
        "google.com",
        "google.com.co",
        "google.co.ve",
        "google.com.ve",
        "google.com.uy",
        "google.es",
        "google.com.mx",
        "google.com.ar",
        "google.cl",
        "google.com.pe",
        "google.com.ec",
        "google.com.pa",
        "google.us",
    }
)

_NUMBER = r"(-?\d{1,3}(?:\.\d+)?)"
_PIN = re.compile(r"!3d" + _NUMBER + r"!4d" + _NUMBER)
_QUERY = re.compile(
    r"(?:^|[?&])(?:q|query|ll|destination|center)=" + _NUMBER + r",\s*\+?" + _NUMBER
)
_AT = re.compile(r"@" + _NUMBER + r"," + _NUMBER)
_PLACE_NAME = re.compile(r"/maps/place/([^/@]+)")


@dataclass(frozen=True)
class MapsPoint:
    latitude: float
    longitude: float
    name: str | None = None


@dataclass(frozen=True)
class MapsLinkResult:
    """`point` when the link gave one; otherwise `reason` (one of the `REASON_*`)."""

    point: MapsPoint | None = None
    reason: str = ""


@dataclass(frozen=True)
class Hop:
    """One request's answer: the status and, for a redirect, its `Location`."""

    status: int
    location: str | None = None


#: One guarded request to `url` (no redirects followed). Raises `UnsafeHop` for an address
#: that is not public, `OSError`-like errors for anything that did not answer.
HopFetcher = Callable[[str, float], Hop]


class UnsafeHop(Exception):
    """The hop's name resolves to a private, loopback or link-local address."""


def _host_path(url: str) -> tuple[str, str, str] | None:
    """(scheme, host, path) of an acceptable URL: no credentials, no trailing dot in the
    host, no explicit port other than 443."""
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return None
    if parts.username is not None or parts.password is not None:
        return None
    if not host or host.endswith(".") or port not in (None, 443):
        return None
    return parts.scheme.lower(), host, parts.path or "/"


def is_short_link(url: str) -> bool:
    found = _host_path(url)
    if found is None or found[0] != "https":
        return False
    _, host, path = found
    return host == _SHORT_HOST or (host == _GOO_GL and path.startswith("/maps"))


def is_long_maps_url(url: str) -> bool:
    found = _host_path(url)
    if found is None or found[0] != "https":
        return False
    _, host, path = found
    if host.startswith("maps.") and host.removeprefix("maps.") in GOOGLE_DOMAINS:
        return True
    return host.removeprefix("www.") in GOOGLE_DOMAINS and path.startswith("/maps")


def _point(lat: str, lng: str) -> MapsPoint | None:
    latitude, longitude = float(lat), float(lng)
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return MapsPoint(latitude, longitude)


def parse_maps_url(url: str) -> MapsPoint | None:
    """The point (and the place's name) of a LONG Google Maps URL, or None."""
    if not is_long_maps_url(url):
        return None
    parts = urlsplit(url.strip())
    path = unquote(parts.path)
    query = unquote(parts.query)
    name_match = _PLACE_NAME.search(parts.path)
    name = unquote_plus(name_match.group(1)).strip() if name_match else None
    for pattern, text in ((_PIN, path + "?" + query), (_QUERY, query), (_AT, path)):
        found = pattern.search(text)
        if found:
            point = _point(found.group(1), found.group(2))
            if point is None:
                return None
            return MapsPoint(point.latitude, point.longitude, name or None)
    return None


def resolve_maps_link(
    url: str,
    *,
    hop: HopFetcher | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> MapsLinkResult:
    """The shop's point from whatever Google Maps link the owner pasted (module
    docstring). A short link is followed through `hop` (default: `default_hop`)."""
    current = (url or "").strip()
    if current and "://" not in current:
        current = "https://" + current
    if is_long_maps_url(current):
        point = parse_maps_url(current)
        return MapsLinkResult(point=point, reason="" if point else REASON_NO_POINT)
    if not is_short_link(current):
        return MapsLinkResult(reason=REASON_NOT_MAPS)
    fetch = hop or default_hop
    deadline = clock() + DEADLINE_S
    for _ in range(MAX_HOPS):
        remaining = deadline - clock()
        if remaining <= 0:
            return MapsLinkResult(reason=REASON_UNREACHABLE)
        try:
            answer = fetch(current, remaining)
        except UnsafeHop:
            return MapsLinkResult(reason=REASON_UNSAFE)
        except Exception:  # noqa: BLE001 — timeout, DNS, TLS: the link did not answer
            return MapsLinkResult(reason=REASON_UNREACHABLE)
        if not (300 <= answer.status < 400) or not answer.location:
            return MapsLinkResult(reason=REASON_UNREACHABLE)
        current = urljoin(current, answer.location)
        if is_long_maps_url(current):
            point = parse_maps_url(current)
            return MapsLinkResult(point=point, reason="" if point else REASON_NO_POINT)
        if not is_short_link(current):
            return MapsLinkResult(reason=REASON_UNSAFE)
    return MapsLinkResult(reason=REASON_UNSAFE)  # more than MAX_HOPS redirects


def default_hop(
    url: str,
    timeout: float,
    *,
    resolve: Callable[[str, int], object] | None = None,
    transport: object | None = None,
) -> Hop:
    """One guarded request (the `menus/import_ai.default_fetch` pattern): the name must
    resolve only to public addresses, the connection is pinned to the checked one, https
    with SNI, no cookies, no environment proxy. HEAD, then GET (≤ 64 KB) if HEAD is
    refused."""
    import httpx  # noqa: PLC0415

    deadline = time.monotonic() + timeout  # the caller's REMAINING budget, for every phase

    def left() -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("maps link budget spent")
        return remaining

    from qualify_api.whatsapp.menus.import_ai import (  # noqa: PLC0415
        SourceUnsupported,
        _pinned,
        _resolve,
        _safe_address,
    )

    parts = urlsplit(url)
    host = parts.hostname or ""
    try:
        address = _safe_address(host, 443, resolve or _resolve)  # type: ignore[arg-type]
    except SourceUnsupported as exc:
        raise UnsafeHop(host) from exc
    target, host_header = _pinned(url, address)
    headers = {
        "Host": host_header,
        "User-Agent": "Mozilla/5.0 (compatible; QualifyMapsLink/1.0)",
        "Accept-Encoding": "identity",
    }
    with httpx.Client(
        timeout=httpx.Timeout(timeout),
        follow_redirects=False,
        trust_env=False,
        transport=transport,  # type: ignore[arg-type]
    ) as client:
        extensions = {"sni_hostname": host}
        response = client.request(
            "HEAD", target, headers=headers, extensions=extensions, timeout=left()
        )
        if response.is_redirect:
            return Hop(response.status_code, response.headers.get("location"))
        with client.stream(
            "GET", target, headers=headers, extensions=extensions, timeout=left()
        ) as streamed:
            if streamed.is_redirect:
                return Hop(streamed.status_code, streamed.headers.get("location"))
            read = 0
            for chunk in streamed.iter_raw():
                read += len(chunk)
                left()  # the read counts against the same total budget
                if read > MAX_GET_BYTES:
                    break
            return Hop(streamed.status_code, None)


__all__ = [
    "DEADLINE_S",
    "GOOGLE_DOMAINS",
    "MAX_HOPS",
    "REASON_NOT_MAPS",
    "REASON_NO_POINT",
    "REASON_UNREACHABLE",
    "REASON_UNSAFE",
    "Hop",
    "MapsLinkResult",
    "MapsPoint",
    "UnsafeHop",
    "default_hop",
    "is_long_maps_url",
    "is_short_link",
    "parse_maps_url",
    "resolve_maps_link",
]

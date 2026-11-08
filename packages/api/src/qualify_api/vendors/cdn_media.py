"""What the reels-worker and the screen's picture proxy share about the networks' CDN
media (ADR 42 R12, m-24854859).

Moved here from `Qualify/avatar_proxy.py` so the worker — which copies each idea's cover
to R2 during the weekly run (`qualify_api.referentes.reel_covers`) — and the proxy apply
the same rules: which hosts a picture may come from (`CDN_HOST_SUFFIXES`; unavatar.io is
the proxy's own extra source and stays there), when a signed URL is already dead
(`signature_expired`) and how a HEIC picture becomes a JPEG (`heif_to_jpeg`).

A cover is fetched (`fetch_cover`) under stricter rules than a profile picture, whose
`avatar_proxy._fetch` is unchanged: https on port 443, no credentials in the URL, a host
under `CDN_HOST_SUFFIXES`, **no redirects** (a 3xx is refused, even towards another CDN
host), `COVER_TIMEOUT_SECONDS` per phase and `COVER_DEADLINE_SECONDS` for the whole
download, and at most `COVER_MAX_BYTES` on the wire: the body is asked for as it is stored
(`Accept-Encoding: identity`) and an answer compressed anyway is refused before it is read,
so no decoder runs and the cap bounds memory too — a decompressed chunk could not. The URL
is untrusted input: it is never logged — a failure carries a stable `reason` only. It is
also never the client's choice: the run copies the URL it stored from the vendor, and the
screen's live form is signed by the server (`Qualify/avatar_proxy.reel_cover_path`) — the
reasons a CodeQL py/full-ssrf report on `fetch_cover` can be dismissed with
(`Qualify/avatar_proxy.py`, «Why the picture fetch is safe»).

`reencode_cover` turns what was fetched into the copy the screen serves: only JPEG, PNG,
WebP or HEIC up to `COVER_MAX_SIDE_IN` px per side and `COVER_MAX_PIXELS` in all are
accepted (decoded, never trusted by their `Content-Type`; the size is read from the header,
before anything is decoded), and the result is a fresh JPEG of at most `COVER_MAX_SIDE` px on its
longer side, quality `COVER_QUALITY`, with no metadata at all (EXIF, ICC, comments).
Pillow and pillow-heif come with `qualify-creative`, a dependency of `qualify-api`.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from io import BytesIO
from urllib.parse import parse_qs, urlsplit

import httpx

logger = logging.getLogger(__name__)

#: Hosts a network's picture may come from — suffix match on the hostname. The proxy adds
#: unavatar.io for profile pictures only.
CDN_HOST_SUFFIXES: tuple[str, ...] = (
    "tiktokcdn.com",
    "tiktokcdn-us.com",
    "tiktokcdn-eu.com",
    "cdninstagram.com",
    "fbcdn.net",
)

#: What a browser sends: Instagram's CDN serves other clients less reliably.
BROWSER_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}

#: A cover download: per httpx phase (connect, each read), like every timeout here...
COVER_TIMEOUT_SECONDS = 8.0
#: ...and for the whole of it, however the bytes trickle in.
COVER_DEADLINE_SECONDS = 8.0
#: The most a cover download may carry on the wire before it is cut off.
COVER_MAX_BYTES = 3_000_000
#: An image is compressed already: a cover is asked for as it is stored.
_IDENTITY = frozenset({"", "identity"})
#: What a cover may be, by the CDN's `Content-Type` and again by what Pillow decodes.
COVER_TYPES: frozenset[str] = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
)
_DECODED_FORMATS = frozenset({"JPEG", "PNG", "WEBP", "HEIF"})
#: The largest picture accepted, per side and in all, read from its header before anything
#: is decoded. Decoding is what costs memory in the reels-worker (`mem_limit: 384m` on a
#: ~150-181 MiB baseline): at 4096×4096 a WebP took +289 MiB, a HEIF +173, a PNG +161;
#: at 2048×2048 a WebP took +81 MiB (code review of R12, 2026-11-05). A real cover is at
#: most 1080×1920 (2.1 MP).
COVER_MAX_SIDE_IN = 4096
COVER_MAX_PIXELS = 2048 * 2048
#: The copy: at most this many px on its longer side, at this JPEG quality.
COVER_MAX_SIDE = 720
COVER_QUALITY = 80
#: A cover URL read longer ago than this is taken for dead even when it signs no expiry:
#: Instagram's live ~4 days, TikTok's ~1 (both sign theirs, `signature_expired`).
COVER_URL_MAX_AGE = timedelta(days=4)


class CoverUnavailable(Exception):
    """A cover could not be fetched or re-encoded. `reason` is a stable code safe to log
    (`refused`, `redirect`, `http_<status>`, `encoded`, `too_large`, `too_slow`,
    `not_an_image`, `too_big`, `undecodable`, `network`); the URL is never part of it."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


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


def cdn_host_allowed(url: str) -> bool:
    """`url_on_hosts` over the networks' CDNs (`CDN_HOST_SUFFIXES`)."""
    return url_on_hosts(url, CDN_HOST_SUFFIXES)


def signature_expired(url: str, *, now: float | None = None) -> bool:
    """Whether a vendor URL's own signature says it is dead already — Instagram's `oe`
    (hex epoch seconds) or TikTok's `x-expires` (epoch seconds). Unknown shapes count as
    alive: the fetch itself decides — and so does a URL `urlsplit` cannot even read."""
    try:
        query = parse_qs(urlsplit(url).query)
    except ValueError:
        return False
    moment = now if now is not None else time.time()
    try:
        if "oe" in query:
            return int(query["oe"][0], 16) <= moment
        if "x-expires" in query:
            return int(query["x-expires"][0]) <= moment
    except ValueError:
        return False
    return False


def cover_url_fresh(url: str | None, read_at: datetime | None, now: datetime) -> bool:
    """A cover URL the browser may still be sent to: on a network's CDN, its signature not
    expired and read under `COVER_URL_MAX_AGE` ago."""
    if not url or not cdn_host_allowed(url):
        return False
    if read_at is not None and now - read_at > COVER_URL_MAX_AGE:
        return False
    return not signature_expired(url, now=now.timestamp())


#: HEIC/HEIF is what TikTok's CDN serves for the first entries of an avatar `url_list`
#: (measured 2026-09-14) and it renders nowhere but Safari. A URL already saved in a
#: discovery cache cannot be switched to its JPEG sibling — the signature covers the
#: extension (`.heic` → `.jpeg` answers 403) — so the picture is converted instead.
HEIF_TYPES: frozenset[str] = frozenset({"image/heic", "image/heif"})


def _register_heif() -> bool:
    try:
        import pillow_heif  # noqa: PLC0415 — a dependency of packages/creative

        pillow_heif.register_heif_opener()
    except Exception:  # noqa: BLE001 — without it, a HEIC picture just cannot be read
        return False
    return True


def heif_to_jpeg(content: bytes) -> bytes | None:
    """HEIC/HEIF bytes as JPEG, or None when they cannot be decoded (or pillow-heif,
    a dependency of `packages/creative`, is not installed)."""
    try:
        import pillow_heif  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415

        pillow_heif.register_heif_opener()
        with Image.open(BytesIO(content)) as image:
            out = BytesIO()
            image.convert("RGB").save(out, format="JPEG", quality=88)
            return out.getvalue()
    except Exception as exc:  # noqa: BLE001 - any decode failure is just "no picture"
        logger.info("avatar heif conversion failed: %s", type(exc).__name__)
        return None


def media_type(response: httpx.Response) -> str:
    return response.headers.get("content-type", "").split(";")[0].strip().lower()


def fetch_cover(
    url: str, *, client: httpx.Client, clock: Callable[[], float] = time.monotonic
) -> tuple[bytes, str]:
    """The picture at `url` as `(bytes, media type)` — see the module docstring for the
    rules. Raises `CoverUnavailable` with a reason, never with the URL."""
    if not cdn_host_allowed(url):
        raise CoverUnavailable("refused")
    chunks: list[bytes] = []
    size = 0
    started = clock()
    try:
        with client.stream(
            "GET",
            url,
            headers={**BROWSER_HEADERS, "Accept-Encoding": "identity"},
            follow_redirects=False,
            timeout=COVER_TIMEOUT_SECONDS,
        ) as response:
            status = response.status_code
            if 300 <= status < 400:
                raise CoverUnavailable("redirect")
            if status != 200:
                raise CoverUnavailable(f"http_{status}")
            kind = media_type(response)
            if kind not in COVER_TYPES:
                raise CoverUnavailable("not_an_image")
            if response.headers.get("content-encoding", "").strip().lower() not in _IDENTITY:
                raise CoverUnavailable("encoded")  # what reaches memory = what is counted
            declared = response.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > COVER_MAX_BYTES:
                raise CoverUnavailable("too_large")
            # identity only (checked above): no decoder runs, these are the wire bytes
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > COVER_MAX_BYTES:
                    raise CoverUnavailable("too_large")
                if clock() - started > COVER_DEADLINE_SECONDS:
                    raise CoverUnavailable("too_slow")
                chunks.append(chunk)
    except httpx.InvalidURL:
        # not an `HTTPError`: a URL httpx will not even send is refused, like a foreign host
        raise CoverUnavailable("refused") from None
    except httpx.HTTPError:
        raise CoverUnavailable("network") from None
    if not size:
        raise CoverUnavailable("not_an_image")
    return b"".join(chunks), kind


def reencode_cover(content: bytes) -> bytes:
    """The copy kept in R2: a JPEG of at most `COVER_MAX_SIDE` px on its longer side,
    quality `COVER_QUALITY`, rebuilt from the pixels alone (no EXIF, ICC or comment
    survives), turned upright first by its own EXIF orientation. Raises
    `CoverUnavailable` for anything that is not a JPEG, PNG, WebP or HEIC picture up to
    `COVER_MAX_SIDE_IN` px per side and `COVER_MAX_PIXELS` in all."""
    from PIL import Image, ImageOps  # noqa: PLC0415 — only the copy decodes pictures

    _register_heif()
    try:
        with Image.open(BytesIO(content)) as image:
            if image.format not in _DECODED_FORMATS:
                raise CoverUnavailable("not_an_image")
            width, height = image.size  # from the header: nothing is decoded yet
            if (
                not (0 < width <= COVER_MAX_SIDE_IN and 0 < height <= COVER_MAX_SIDE_IN)
                or width * height > COVER_MAX_PIXELS
            ):
                raise CoverUnavailable("too_big")
            # resized first, in place (a JPEG is even decoded at a reduced scale): the
            # reels-worker's memory holds one decode at most, never several full copies
            image.thumbnail((COVER_MAX_SIDE, COVER_MAX_SIDE), Image.Resampling.LANCZOS)
            ImageOps.exif_transpose(image, in_place=True)
            rgba = image.convert("RGBA")
    except CoverUnavailable:
        raise
    except Exception:  # noqa: BLE001 — truncated, corrupt or a bomb: no copy
        raise CoverUnavailable("undecodable") from None
    # a fresh picture from the pixels alone: nothing of the original's metadata survives
    canvas = Image.new("RGB", rgba.size, (255, 255, 255))
    canvas.paste(rgba, mask=rgba.getchannel("A"))
    out = BytesIO()
    canvas.save(out, format="JPEG", quality=COVER_QUALITY, optimize=True)
    return out.getvalue()


__all__ = [
    "BROWSER_HEADERS",
    "CDN_HOST_SUFFIXES",
    "COVER_DEADLINE_SECONDS",
    "COVER_MAX_BYTES",
    "COVER_MAX_SIDE",
    "COVER_MAX_PIXELS",
    "COVER_MAX_SIDE_IN",
    "COVER_QUALITY",
    "COVER_TIMEOUT_SECONDS",
    "COVER_TYPES",
    "COVER_URL_MAX_AGE",
    "HEIF_TYPES",
    "CoverUnavailable",
    "cdn_host_allowed",
    "cover_url_fresh",
    "fetch_cover",
    "heif_to_jpeg",
    "media_type",
    "reencode_cover",
    "signature_expired",
    "url_on_hosts",
]

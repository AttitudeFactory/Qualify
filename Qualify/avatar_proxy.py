"""Profile pictures for the creator-discovery cards, served by the Reflex backend.

Why a proxy at all (request 2026-09-14, "las imágenes de las cards no se ven"): the
vendor's picture URLs are signed and short-lived — TikTok's CDN links carry an
`x-expires` a few hours out — and a discovery result lives in a 7-day cache. Rendered
directly, a cached deck would be a wall of broken pictures. So the browser never sees
a vendor URL: every card asks this backend for `/avatar/<network>/<handle>`, and the
backend fetches the vendor's picture ONCE, while the signature is still valid, keeps
the bytes on disk (`creator_discovery.AVATAR_DIR`) and serves its own copy from then
on. Cards written to the cache before pictures existed (no `u`), or whose signed URL
already died, fall back to unavatar.io — a public by-handle lookup — and only then to
nothing: a 404 the card renders as its placeholder icon (`alt=""`).

Mounted on the Reflex backend through `rx.App(api_transformer=avatar_api)` in
`Qualify.py`; the frontend builds the absolute URL the same way `rx.get_upload_url`
does (`creative_wizard_pages._AVATAR_BASE`).

Guard rails: `u` is only ever fetched from the vendors' own CDNs (and unavatar) — the
proxy is not an open fetcher — pictures above `_MAX_BYTES` are refused, and a miss is
remembered in memory for `_MISS_TTL_SECONDS` so a deck of dead links does not hammer
anyone on every re-render.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Response

from .creator_discovery import AVATAR_DIR, AVATAR_ROUTE

logger = logging.getLogger(__name__)

#: Hosts a vendor URL may point at — suffix match on the hostname.
_ALLOWED_HOST_SUFFIXES: tuple[str, ...] = (
    "tiktokcdn.com",
    "tiktokcdn-us.com",
    "tiktokcdn-eu.com",
    "cdninstagram.com",
    "fbcdn.net",
    "unavatar.io",
)
_NETWORKS = {"tiktok", "instagram"}
_HANDLE_RE = re.compile(r"^[A-Za-z0-9_.]{1,40}$")
_TYPES: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
_MAX_BYTES = 3_000_000
_MISS_TTL_SECONDS = 15 * 60
_TIMEOUT_SECONDS = 8.0
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}
_CACHE_HEADERS = {"Cache-Control": "public, max-age=86400"}

#: `(network, handle, vendor_url)` → when the miss expires. Memory only: a restart
#: forgets it, which is fine — the point is not to retry on every re-render.
_misses: dict[tuple[str, str, str], float] = {}

#: The module-wide HTTP client `resolve_avatar` reuses when no client is passed in
#: (§ request 2026-09-14, "más rápido cargar las imágenes"): a fresh
#: `httpx.AsyncClient` per request pays a new TLS handshake every time even for the
#: SAME CDN host — a shared, connection-pooled client reuses that handshake across
#: every avatar this process ever fetches. Tests always pass their own `client=` (a
#: `MockTransport`), so they never touch this.
_shared_client: httpx.AsyncClient | None = None

#: Fire-and-forget prefetch tasks (`warm_avatars_in_background`), held here so
#: nothing garbage-collects a task mid-flight — a bare `asyncio.create_task(...)`
#: with no kept reference is exactly the case Python's own docs warn can vanish.
_background_tasks: set[asyncio.Task[None]] = set()


def _shared() -> httpx.AsyncClient:
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(
            timeout=_TIMEOUT_SECONDS,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _shared_client


def source_allowed(url: str) -> bool:
    """True for an `https` URL on one of the vendors' CDNs (or unavatar)."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        return False
    return any(host == suffix or host.endswith("." + suffix) for suffix in _ALLOWED_HOST_SUFFIXES)


def valid_target(network: str, handle: str) -> bool:
    return network in _NETWORKS and bool(_HANDLE_RE.match(handle))


def cache_file(network: str, handle: str, *, directory: Path = AVATAR_DIR) -> Path | None:
    """The picture already on disk for this account, whatever its type, or None."""
    stem = f"{network}_{handle.lower()}"
    for suffix in _TYPES.values():
        candidate = directory / f"{stem}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def _media_type(path: Path) -> str:
    return next((t for t, s in _TYPES.items() if s == path.suffix), "image/jpeg")


def unavatar_url(network: str, handle: str) -> str:
    """The public by-handle lookup, told to 404 rather than hand back a generic
    placeholder — the card has its own."""
    return f"https://unavatar.io/{network}/{handle}?fallback=false"


#: HEIC/HEIF is what TikTok's CDN serves for the first entries of an avatar `url_list`
#: (measured 2026-09-14) and it renders nowhere but Safari. A URL already saved in a
#: discovery cache cannot be switched to its JPEG sibling — the signature covers the
#: extension (`.heic` → `.jpeg` answers 403) — so the proxy converts it instead.
_HEIF_TYPES = {"image/heic", "image/heif"}

#: unavatar.io's free tier answers 429 after a handful of lookups per IP (measured
#: 2026-09-14: 20 of 21 lookups). Every card with no vendor URL would keep asking it,
#: burning the next hour's quota too — so a 429 pauses it for everyone.
_UNAVATAR_COOLDOWN_SECONDS = 60 * 60
_unavatar_blocked_until = 0.0


def heif_to_jpeg(content: bytes) -> bytes | None:
    """HEIC/HEIF bytes as JPEG, or None when they cannot be decoded (or pillow-heif,
    a dependency of `packages/creative`, is not installed)."""
    try:
        from io import BytesIO

        import pillow_heif
        from PIL import Image

        pillow_heif.register_heif_opener()
        with Image.open(BytesIO(content)) as image:
            out = BytesIO()
            image.convert("RGB").save(out, format="JPEG", quality=88)
            return out.getvalue()
    except Exception as exc:  # noqa: BLE001 - any decode failure is just "no picture"
        logger.info("avatar heif conversion failed: %s", type(exc).__name__)
        return None


async def _fetch(
    client: httpx.AsyncClient, url: str, *, now: float | None = None
) -> tuple[bytes, str] | None:
    """The picture at `url` as `(bytes, media type)`, or None for anything that is not
    a small image on an allowed host. HEIC/HEIF comes back converted to JPEG."""
    global _unavatar_blocked_until
    if not source_allowed(url):
        return None
    is_unavatar = urlsplit(url).hostname == "unavatar.io"
    moment = now if now is not None else time.time()
    if is_unavatar and _unavatar_blocked_until > moment:
        return None
    try:
        response = await client.get(url, headers=_HEADERS, follow_redirects=True)
    except httpx.HTTPError as exc:
        logger.info("avatar fetch failed: %s", type(exc).__name__)
        return None
    if response.status_code == 429 and is_unavatar:
        _unavatar_blocked_until = moment + _UNAVATAR_COOLDOWN_SECONDS
        logger.info("unavatar rate-limited, pausing lookups for an hour")
        return None
    if response.status_code != 200:
        return None
    media_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if not response.content or len(response.content) > _MAX_BYTES:
        return None
    if media_type in _HEIF_TYPES:
        converted = await asyncio.to_thread(heif_to_jpeg, response.content)
        return (converted, "image/jpeg") if converted else None
    if media_type not in _TYPES:
        return None
    return response.content, media_type


async def resolve_avatar(
    network: str,
    handle: str,
    vendor_url: str = "",
    *,
    client: httpx.AsyncClient | None = None,
    directory: Path = AVATAR_DIR,
    now: float | None = None,
) -> tuple[bytes, str] | None:
    """The picture for one account: disk first, then the vendor's URL (fetched and
    kept), then unavatar (fetched and kept), then None. A miss is remembered for
    `_MISS_TTL_SECONDS`."""
    if not valid_target(network, handle):
        return None
    cached = cache_file(network, handle, directory=directory)
    if cached is not None:
        return cached.read_bytes(), _media_type(cached)

    key = (network, handle.lower(), vendor_url)
    moment = now if now is not None else time.time()
    if _misses.get(key, 0.0) > moment:
        return None

    sources = [u for u in (vendor_url, unavatar_url(network, handle)) if u]
    http = client or _shared()
    for url in sources:
        found = await _fetch(http, url, now=moment)
        if found is None:
            continue
        content, media_type = found
        try:
            directory.mkdir(parents=True, exist_ok=True)
            (directory / f"{network}_{handle.lower()}{_TYPES[media_type]}").write_bytes(content)
        except OSError as exc:
            logger.warning("avatar cache write failed: %s", type(exc).__name__)
        return content, media_type
    _misses[key] = moment + _MISS_TTL_SECONDS
    return None


async def warm_avatars(
    cards: list[dict[str, str]],
    *,
    concurrency: int = 8,
    client: httpx.AsyncClient | None = None,
    directory: Path = AVATAR_DIR,
) -> None:
    """Best-effort prefetch: download every card's picture into the cache before the
    browser ever asks for it (§ request 2026-09-14, "más rápido cargar las imágenes
    en la card"). Called fire-and-forget (`warm_avatars_in_background`) from
    `creative_wizard_pages._apply_phase` the instant a phase lands, so by the time
    the deck renders its first card the picture is very likely already on disk — a
    `resolve_avatar` cache hit instead of a network round trip. Bounded by
    `concurrency` (a semaphore, not one request at a time) and never raises: a slow
    or failing prefetch just means the browser's own request does the work instead,
    exactly as it did before this existed."""
    semaphore = asyncio.Semaphore(concurrency)

    async def one(card: dict[str, str]) -> None:
        network = str(card.get("network") or "").lower()
        handle = str(card.get("handle") or "").lstrip("@").strip()
        if not valid_target(network, handle):
            return
        async with semaphore:
            try:
                await resolve_avatar(
                    network,
                    handle,
                    str(card.get("avatar") or ""),
                    client=client,
                    directory=directory,
                )
            except Exception:  # noqa: BLE001 - a prefetch must never surface an error
                logger.debug("avatar warm failed for %s/%s", network, handle, exc_info=True)

    await asyncio.gather(*(one(card) for card in cards))


def warm_avatars_in_background(
    cards: list[dict[str, str]],
    *,
    concurrency: int = 8,
    client: httpx.AsyncClient | None = None,
    directory: Path = AVATAR_DIR,
) -> None:
    """Fire-and-forget `warm_avatars` for a fresh batch of cards. A no-op outside a
    running event loop — `_apply_phase` is also called directly and synchronously by
    existing tests, and this must never break that — and the scheduled task is kept
    in `_background_tasks` so it survives to completion even though nothing else
    holds a reference to it."""
    if not cards:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(
        warm_avatars(cards, concurrency=concurrency, client=client, directory=directory)
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


avatar_api = FastAPI()


@avatar_api.get(AVATAR_ROUTE + "/{network}/{handle}")
async def avatar(network: str, handle: str, u: str = "") -> Response:
    """`GET /avatar/<network>/<handle>?u=<vendor url>` → the picture, or 404."""
    found = await resolve_avatar(network.lower(), handle, u)
    if found is None:
        return Response(status_code=404, headers={"Cache-Control": "no-store"})
    content, media_type = found
    return Response(content=content, media_type=media_type, headers=_CACHE_HEADERS)

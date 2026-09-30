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

Why some pictures never showed (root cause, measured 2026-09-29 over every stored
referente, § "quiero que veas cual es el problema"): the vendor URLs very often arrive
ALREADY DEAD. Discovery reads profiles through Scrape Creators' cache of up to 30 days
(`creator_discovery._PROFILE_CACHE_MAX_AGE`, which is what makes most reads free) and its
own 30-day profile cache, while a signed picture URL lives ~3-4 days on Instagram (`oe`)
and ~1 day on TikTok (`x-expires`): 14 of 18 Instagram cards had expired before their
phase was even computed. TikTok's usually still work at compute time, so the prefetch
keeps them; Instagram's had no second source left — unavatar answers 403 for Instagram,
and Instagram's own public profile endpoint rate-limits (429) at once.

The fix, for every account and not just the ones seen that day:
- a URL whose own signature says it expired (`signature_expired`) is not even fetched;
- the paid last resort (`fresh_vendor_url`): ONE Scrape Creators profile read for a
  fresh URL, used by the prefetch as soon as a phase lands (so the picture is on disk
  before anyone opens the card) and by the browser's own request if that failed; at
  most one read per account per `_REFRESH_RETRY_SECONDS`, never more than
  `QUALIFY_AVATAR_REFRESH_PER_HOUR` per rolling hour (default 60; 0 turns it off), and
  the picture is then kept on disk like any other, so an account is paid for once;
- a miss remembered by the prefetch never blocks that last resort, and one lock per
  account keeps the prefetch and the browser from doing — and paying — it twice.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

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


#: Networks unavatar no longer serves: every Instagram lookup answered 403 (measured
#: 2026-09-29), so asking only adds a round trip before the next source.
_NO_UNAVATAR = {"instagram"}


def signature_expired(url: str, *, now: float | None = None) -> bool:
    """Whether a vendor URL's own signature says it is dead already — Instagram's `oe`
    (hex epoch seconds) or TikTok's `x-expires` (epoch seconds). Unknown shapes count as
    alive: the fetch itself decides."""
    query = parse_qs(urlsplit(url).query)
    moment = now if now is not None else time.time()
    try:
        if "oe" in query:
            return int(query["oe"][0], 16) <= moment
        if "x-expires" in query:
            return int(query["x-expires"][0]) <= moment
    except ValueError:
        return False
    return False


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


# -- The paid last resort (`fresh_vendor_url`) -------------------------------------------

#: Profile reads (1 credit each) the last resort may spend in any rolling hour;
#: `QUALIFY_AVATAR_REFRESH_PER_HOUR=0` turns it off.
_REFRESH_PER_HOUR = int(os.environ.get("QUALIFY_AVATAR_REFRESH_PER_HOUR", "60") or 0)
#: An account whose read found no usable picture is not read again for this long.
_REFRESH_RETRY_SECONDS = 24 * 3600
_refresh_log: deque[float] = deque()
_refreshed: dict[tuple[str, str], float] = {}
_refresh_guard = threading.Lock()


def _take_refresh_slot(key: tuple[str, str], moment: float) -> bool:
    """Book one paid read for `key` now, or say no: tried within `_REFRESH_RETRY_SECONDS`,
    or the hour's budget is spent. Thread-safe — reads run in worker threads."""
    with _refresh_guard:
        if moment - _refreshed.get(key, float("-inf")) < _REFRESH_RETRY_SECONDS:
            return False
        while _refresh_log and moment - _refresh_log[0] >= 3600:
            _refresh_log.popleft()
        if len(_refresh_log) >= _REFRESH_PER_HOUR:
            return False
        _refreshed[key] = moment
        _refresh_log.append(moment)
        return True


def fresh_vendor_url(network: str, handle: str, *, now: float | None = None) -> str:
    """A fresh picture URL from a Scrape Creators profile read — ONE credit — or "".
    Blocking: `resolve_avatar` runs it in a thread. See the module docstring for why
    this exists and what bounds it."""
    moment = now if now is not None else time.time()
    if not _take_refresh_slot((network, handle.lower()), moment):
        return ""
    try:
        from . import scrapecreators_client

        profile = scrapecreators_client.fetch_profile(network, handle)
    except Exception as exc:  # noqa: BLE001 - a picture must never break the page
        logger.info("avatar refresh failed for %s/%s: %s", network, handle, type(exc).__name__)
        return ""
    logger.info("avatar refreshed through a profile read (1 credit): %s/%s", network, handle)
    return str(profile.get("profilePicUrl") or "")


#: One lock per account, so the prefetch and the browser asking for the same picture at
#: the same moment do the work — and pay for it — once.
_account_locks: dict[tuple[str, str], asyncio.Lock] = {}


async def resolve_avatar(
    network: str,
    handle: str,
    vendor_url: str = "",
    *,
    client: httpx.AsyncClient | None = None,
    directory: Path = AVATAR_DIR,
    now: float | None = None,
    refresh: Callable[[str, str], str] | None = None,
) -> tuple[bytes, str] | None:
    """The picture for one account: disk first, then the vendor's URL unless its own
    signature says it expired, then unavatar (not for Instagram), then — only when
    `refresh` is given — a fresh vendor URL from it (the paid last resort,
    `fresh_vendor_url`), then None. Whatever is found is kept on disk; a miss is
    remembered for `_MISS_TTL_SECONDS`."""
    if not valid_target(network, handle):
        return None
    cached = cache_file(network, handle, directory=directory)
    if cached is not None:
        return cached.read_bytes(), _media_type(cached)

    lock = _account_locks.setdefault((network, handle.lower()), asyncio.Lock())
    async with lock:
        # Whoever held the lock may have just kept it.
        cached = cache_file(network, handle, directory=directory)
        if cached is not None:
            return cached.read_bytes(), _media_type(cached)

        key = (network, handle.lower(), vendor_url)
        moment = now if now is not None else time.time()
        # A remembered miss skips the free sources — they just failed — but not the
        # paid last resort, when this caller may use it.
        missed = _misses.get(key, 0.0) > moment
        if missed and refresh is None:
            return None

        sources = []
        if vendor_url and not signature_expired(vendor_url, now=moment):
            sources.append(vendor_url)
        if network not in _NO_UNAVATAR:
            sources.append(unavatar_url(network, handle))
        http = client or _shared()
        for url in [] if missed else sources:
            found = await _fetch(http, url, now=moment)
            if found is not None:
                return _keep(network, handle, found, directory)
        if refresh is not None:
            fresh = await asyncio.to_thread(refresh, network, handle)
            if fresh and fresh != vendor_url:
                found = await _fetch(http, fresh, now=moment)
                if found is not None:
                    return _keep(network, handle, found, directory)
        _misses[key] = moment + _MISS_TTL_SECONDS
        return None


def _keep(
    network: str, handle: str, found: tuple[bytes, str], directory: Path
) -> tuple[bytes, str]:
    content, media_type = found
    try:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{network}_{handle.lower()}{_TYPES[media_type]}").write_bytes(content)
    except OSError as exc:
        logger.warning("avatar cache write failed: %s", type(exc).__name__)
    return content, media_type


async def warm_avatars(
    cards: list[dict[str, str]],
    *,
    concurrency: int = 8,
    client: httpx.AsyncClient | None = None,
    directory: Path = AVATAR_DIR,
    refresh: Callable[[str, str], str] | None = None,
) -> None:
    """Best-effort prefetch: download every card's picture into the cache before the
    browser ever asks for it (§ request 2026-09-14, "más rápido cargar las imágenes
    en la card"). Called fire-and-forget (`warm_avatars_in_background`) from
    `creative_wizard_pages._apply_phase` the instant a phase lands, so by the time
    the deck renders its first card the picture is very likely already on disk — a
    `resolve_avatar` cache hit instead of a network round trip. With `refresh` (what
    `_apply_phase` passes since 2026-09-29) a picture whose URL arrived dead is replaced
    by a fresh one right here, instead of when someone is already staring at an empty
    card. Bounded by `concurrency` and never raises: a slow or failing prefetch just
    means the browser's own request does the work instead."""
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
                    refresh=refresh,
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
    refresh: Callable[[str, str], str] | None = None,
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
        warm_avatars(
            cards, concurrency=concurrency, client=client, directory=directory, refresh=refresh
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


avatar_api = FastAPI()


@avatar_api.get(AVATAR_ROUTE + "/{network}/{handle}")
async def avatar(network: str, handle: str, u: str = "") -> Response:
    """`GET /avatar/<network>/<handle>?u=<vendor url>` → the picture, or 404."""
    found = await resolve_avatar(network.lower(), handle, u, refresh=fresh_vendor_url)
    if found is None:
        return Response(status_code=404, headers={"Cache-Control": "no-store"})
    content, media_type = found
    return Response(content=content, media_type=media_type, headers=_CACHE_HEADERS)

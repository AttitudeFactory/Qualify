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
  before anyone opens the card) and charged to the session's business (ADR 42 R5; the
  browser's own `<img>` request carries no session, so it never pays since 2026-11-04); at
  most one read per account per `_REFRESH_RETRY_SECONDS`, never more than
  `QUALIFY_AVATAR_REFRESH_PER_HOUR` per rolling hour (default 60; 0 turns it off), and
  the picture is then kept on disk like any other, so an account is paid for once;
- a miss remembered by the prefetch never blocks that last resort, and one lock per
  account keeps the prefetch and the browser from doing — and paying — it twice.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from urllib.parse import quote, urlsplit
from uuid import UUID

import httpx
from fastapi import FastAPI, Response
from qualify_api.referentes import reel_covers
from qualify_api.vendors import cdn_media
from qualify_api.vendors.cdn_media import HEIF_TYPES, heif_to_jpeg, signature_expired

from .creator_discovery import AVATAR_DIR, AVATAR_ROUTE

logger = logging.getLogger(__name__)

#: Hosts a vendor URL may point at — suffix match on the hostname: the networks' CDNs
#: (`cdn_media.CDN_HOST_SUFFIXES`, shared with the reels-worker since R12) and unavatar.
_ALLOWED_HOST_SUFFIXES: tuple[str, ...] = (*cdn_media.CDN_HOST_SUFFIXES, "unavatar.io")
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
_HEADERS = cdn_media.BROWSER_HEADERS
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


# `signature_expired` (a URL whose own signature says it is dead is not even fetched) and
# `heif_to_jpeg` (TikTok's CDN serves HEIC, which renders nowhere but Safari) live in
# `qualify_api.vendors.cdn_media` since R12: the reels-worker applies the same rules.
_HEIF_TYPES = HEIF_TYPES

#: unavatar.io's free tier answers 429 after a handful of lookups per IP (measured
#: 2026-09-14: 20 of 21 lookups). Every card with no vendor URL would keep asking it,
#: burning the next hour's quota too — so a 429 pauses it for everyone.
_UNAVATAR_COOLDOWN_SECONDS = 60 * 60
_unavatar_blocked_until = 0.0


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
    # ADR 42 R5: the read is charged to the business in the caller's context (the
    # session's prefetch); with none, it is not made and spends no slot either
    from qualify_api.vendors import usage

    if usage.current() is None:
        return ""
    if not _take_refresh_slot((network, handle.lower()), moment):
        return ""
    try:
        from qualify_api.vendors import scrapecreators as scrapecreators_client

        profile = scrapecreators_client.fetch_profile(
            network, handle, feature=scrapecreators_client.FEATURE_AVATAR_REFRESH
        )
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


def prefetch_business_picture(
    network: str, handle: str, vendor_url: str, *, tenant_id: UUID, brand_id: UUID | None
) -> None:
    """Keep a business's OWN profile picture on disk now, while its signed URL is alive —
    the Brand Kit's read profile and the Alta's proposal show it through this proxy, and
    an `<img>` request never pays (ADR 42 R5), so without this a dead Instagram URL would
    leave the fallback icon. The paid last resort, if needed, is charged to — and capped
    for — that business (the task copies this context). Fire-and-forget, never raises."""
    if not valid_target(network.lower(), handle.lstrip("@")):
        return
    from qualify_api.vendors import usage

    card = {"network": network.lower(), "handle": handle.lstrip("@"), "avatar": vendor_url}
    with usage.charge_to(tenant_id, brand_id):
        warm_avatars_in_background([card], refresh=fresh_vendor_url)


# -- Reel covers («Ideas para tus reels»; ADR 42 R12, m-24854859) --------------------------
# A signed vendor URL dies within days — Instagram's in ~4, TikTok's in ~1 — while an idea
# lives 7. So the weekly run copies each IDEA's cover to R2 while its URL is alive
# (`qualify_api.referentes.reel_covers`, one object per reel for every business), and the
# card asks for `/avatar/reel/<network>/<reel id>?s=<signature of the reel>`: that copy, read
# from R2 (`reel_covers.open_cover`, its own bounded client and its own few threads) and
# cached a week by the browser; none → a `no-store` 404 the card shows as its placeholder.
# The signature is checked before any read: an anonymous GET of a made-up id costs nothing
# and says nothing about which reels were someone's idea. A reel the run could not copy (its
# download failed, or it
# ran before R12) keeps the signed `?u=&s=` path while its CDN URL is fresh: a live
# pass-through under the cover download rules (`cdn_media.fetch_cover`: no redirects, at
# most 3 MB, 8 s) that keeps nothing. Since R12 nothing writes the old disk copies under
# `avatars/reels/`: the R2 copy's purge reaches it, a folder on the server would not.

#: Under `/avatar` on purpose: production's Caddy already sends `/avatar/*` to the Reflex
#: backend (`deploy/Caddyfile`), and the extra segment keeps it apart from a profile.
REEL_COVER_ROUTE = AVATAR_ROUTE + "/reel"
_REEL_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_reel_misses: dict[tuple[str, str], float] = {}
#: Development fallback only; every real environment sets QUALIFY_OAUTH_STATE_SECRET
#: (`deploy/docker-compose.prod.yml` refuses to start without it).
_DEV_COVER_SECRET = "qualify-dev-reel-cover"
#: The R2 copy never changes under its path (a re-copy writes the same picture), and it
#: outlives the idea; the live pass-through is a URL that dies in a day or four.
_STORED_COVER_HEADERS = {"Cache-Control": "public, max-age=604800"}
_LIVE_COVER_HEADERS = {"Cache-Control": "public, max-age=3600"}
_NO_STORE = {"Cache-Control": "no-store"}

#: The R2 reads of the stored covers run here, never in the default pool the screen's
#: own reads (`load_ideas`) use: a slow R2 can hold these few threads, not the screen.
_COVER_READS = ThreadPoolExecutor(max_workers=4, thread_name_prefix="reel-cover-r2")

#: The pass-through's own client (sync: `cdn_media.fetch_cover` runs in a worker thread,
#: like the R2 read). Tests pass their own `client=`.
_cover_http: httpx.Client | None = None


def _cover_client() -> httpx.Client:
    global _cover_http
    if _cover_http is None or _cover_http.is_closed:
        _cover_http = httpx.Client(
            timeout=cdn_media.COVER_TIMEOUT_SECONDS,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _cover_http


def _derived_key(label: bytes) -> bytes:
    """A key derived from the server's state secret, one per kind of path (`label`), so
    every backend worker agrees on it and it is never the state secret itself."""
    secret = os.environ.get("QUALIFY_OAUTH_STATE_SECRET") or _DEV_COVER_SECRET
    return hmac.new(secret.encode("utf-8"), label, sha256).digest()


def _cover_key() -> bytes:
    return _derived_key(b"qualify/reel-cover/v1")


def reel_cover_signature(network: str, reel_id: str, vendor_url: str) -> str:
    message = f"{network}\n{reel_id}\n{vendor_url}".encode()
    return hmac.new(_cover_key(), message, sha256).hexdigest()[:32]


def stored_cover_signature(network: str, reel_id: str) -> str:
    """The stored copy's signature: of the reel alone (`network\nreel_id`), under a key of
    its own, so the path is the same every time and the browser keeps it for a week."""
    message = f"{network}\n{reel_id}".encode()
    return hmac.new(_derived_key(b"qualify/reel-cover-stored/v1"), message, sha256).hexdigest()[:32]


def _cover_base(network: str, reel_id: str) -> str:
    return f"{REEL_COVER_ROUTE}/{network}/{quote(reel_id, safe='')}"


def stored_reel_cover_path(network: str, reel_id: str) -> str:
    """The signed path a card shows the run's R2 copy of a reel's cover from. Signed
    because the route is public (an `<img>` carries no session): unsigned, any GET of a
    made-up id would read R2, and tell which reels were some business's idea."""
    return f"{_cover_base(network, reel_id)}?s={stored_cover_signature(network, reel_id)}"


def reel_cover_path(network: str, reel_id: str, vendor_url: str) -> str:
    """The signed path of the live fallback. Signed because the route is public (an
    `<img>` carries no session): unsigned, anyone could make this backend fetch any
    allowed image under any reel id."""
    return (
        f"{_cover_base(network, reel_id)}"
        f"?u={quote(vendor_url, safe='')}"
        f"&s={reel_cover_signature(network, reel_id, vendor_url)}"
    )


def _signed(given: str, expected: str) -> bool:
    return given.isascii() and hmac.compare_digest(given, expected)


async def resolve_reel_cover(
    network: str,
    reel_id: str,
    vendor_url: str,
    *,
    client: httpx.Client | None = None,
    now: float | None = None,
) -> tuple[bytes, str] | None:
    """One reel's cover, live: the vendor URL (unless its signature already expired)
    fetched under the cover rules, HEIC re-encoded to JPEG by the run's capped
    `cdn_media.reencode_cover` (4 MP at most), nothing kept; else None — a miss remembered
    for `_MISS_TTL_SECONDS`. The URL is never logged."""
    if network not in _NETWORKS or not _REEL_ID_RE.match(reel_id):
        return None
    moment = now if now is not None else time.time()
    key = (network, reel_id)
    if _reel_misses.get(key, 0.0) > moment:
        return None
    if not vendor_url or signature_expired(vendor_url, now=moment):
        _reel_misses[key] = moment + _MISS_TTL_SECONDS
        return None
    try:
        content, media_type = await asyncio.to_thread(
            cdn_media.fetch_cover, vendor_url, client=client or _cover_client()
        )
    except cdn_media.CoverUnavailable as exc:
        logger.info("reel cover %s/%s unavailable live: %s", network, reel_id, exc.reason)
        _reel_misses[key] = moment + _MISS_TTL_SECONDS
        return None
    if media_type in _HEIF_TYPES:
        # the run's re-encode, capped (4 MP, ≤ 720 px), never the profile pictures'
        # uncapped `heif_to_jpeg`: a big HEIC must not take the Reflex process's memory
        try:
            converted = await asyncio.to_thread(cdn_media.reencode_cover, content)
        except cdn_media.CoverUnavailable as exc:
            logger.info("reel cover %s/%s unusable live: %s", network, reel_id, exc.reason)
            _reel_misses[key] = moment + _MISS_TTL_SECONDS
            return None
        return converted, "image/jpeg"
    return content, media_type


avatar_api = FastAPI()


@avatar_api.get(REEL_COVER_ROUTE + "/{network}/{reel_id}")
async def reel_cover(network: str, reel_id: str, u: str = "", s: str = "") -> Response:
    """`GET /avatar/reel/<network>/<reel id>?s=<signature>` → the run's R2 copy of the
    cover; `…?u=<vendor url>&s=<signature>` → the live cover while its URL works. Either
    way a miss is a `no-store` 404 (the card's placeholder) — also, before any read, for a
    path `stored_reel_cover_path` / `reel_cover_path` did not sign."""
    network = network.lower()
    if not u:
        if not _signed(s, stored_cover_signature(network, reel_id)):
            return Response(status_code=404, headers=_NO_STORE)
        loop = asyncio.get_running_loop()
        stored = await loop.run_in_executor(_COVER_READS, reel_covers.open_cover, network, reel_id)
        if stored is None:
            return Response(status_code=404, headers=_NO_STORE)
        return Response(
            content=stored, media_type=reel_covers.COVER_CONTENT_TYPE, headers=_STORED_COVER_HEADERS
        )
    if not _signed(s, reel_cover_signature(network, reel_id, u)):
        return Response(status_code=404, headers=_NO_STORE)
    found = await resolve_reel_cover(network, reel_id, u)
    if found is None:
        return Response(status_code=404, headers=_NO_STORE)
    content, media_type = found
    return Response(content=content, media_type=media_type, headers=_LIVE_COVER_HEADERS)


@avatar_api.get(AVATAR_ROUTE + "/{network}/{handle}")
async def avatar(network: str, handle: str, u: str = "") -> Response:
    """`GET /avatar/<network>/<handle>?u=<vendor url>` → the picture, or 404.

    Never the paid last resort (ADR 42 R5, founder decision 2026-11-04): an `<img>`
    request carries no session, so there is no business to charge the read to, and a
    read nobody is charged for is not made. The session's own prefetch
    (`warm_avatars_in_background`, charged to its business) is what pays for a picture
    whose URL arrived dead."""
    found = await resolve_avatar(network.lower(), handle, u)
    if found is None:
        return Response(status_code=404, headers={"Cache-Control": "no-store"})
    content, media_type = found
    return Response(content=content, media_type=media_type, headers=_CACHE_HEADERS)

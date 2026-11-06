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

**Why the picture fetch is safe** (m-24957331; what a dismissal of CodeQL's py/full-ssrf
on `_get_on_allowed_hosts` can cite — the analyzer models neither the signature nor the
allowlist as a sanitizer, so it may report the request):
1. **The URL is the server's, signed.** A profile picture path is
   `/avatar/<network>/<handle>?u=<vendor url>&s=<signature>`, with `s` an HMAC-SHA256 of
   the network, the handle and the URL under a key derived from the server's state secret
   (`creator_discovery.avatar_signature`, emitted by `avatar_path`, the one builder). The
   route checks it before any read of the disk or the network: an unsigned, forged or
   another account's path is a `no-store` 404. A reel cover's path is signed the same way
   by its URL (`reel_cover_path`). So `u` is only ever a URL this server took from the
   vendor's own data.
2. **Every hop is checked before it is requested.** The URL and each redirect's
   `Location` (followed by hand, at most `_MAX_REDIRECTS`; httpx's own redirects off) must
   be `https` on port 443, without userinfo, in printable ASCII, on a host equal to or
   under the networks' CDN zones (`cdninstagram.com`, `fbcdn.net`, `tiktokcdn*.com`) or
   exactly `unavatar.io` (`source_allowed`, `cdn_media.url_on_hosts`). A `Location` that
   cannot be read, or one more hop, is refused; the refused host — never the URL — is
   logged. A URL httpx refuses is a miss, never a 500.
3. **The body is bounded.** Asked for as stored (`Accept-Encoding: identity`; a
   compressed answer is refused unread), only an image type is read, a `Content-Length`
   over `_MAX_BYTES` (3 MB) is refused before a byte, and the stream is cut at 3 MB.
4. **The disk caches name a file only for a known network and a well-formed handle or
   reel id, confined to their folder** (`_inside`: normpath + startswith —
   py/path-injection), for the profile pictures and the reel covers alike.
Tests: `Qualify/test_avatar_proxy_safety.py`.

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
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from urllib.parse import parse_qs, quote, urljoin, urlsplit
from uuid import UUID

import httpx
from fastapi import FastAPI, Response
from qualify_api.vendors import cdn_media

from .creator_discovery import AVATAR_DIR, AVATAR_ROUTE, avatar_signature, proxy_key

logger = logging.getLogger(__name__)

#: Hosts a vendor URL may point at: the networks' CDNs and their subdomains
#: (`cdn_media.CDN_HOST_SUFFIXES`), and unavatar — `unavatar.io` itself only, never one of
#: its subdomains (a third party's names).
_ALLOWED_HOST_SUFFIXES: tuple[str, ...] = cdn_media.CDN_HOST_SUFFIXES
_ALLOWED_EXACT_HOSTS: frozenset[str] = frozenset({"unavatar.io"})
_NETWORKS = {"tiktok", "instagram"}
#: A handle as the networks write it — matched whole (`fullmatch`): never a slash, a
#: space, a control character or a trailing newline.
_HANDLE_RE = re.compile(r"[A-Za-z0-9_.]{1,40}")
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
_NO_STORE = {"Cache-Control": "no-store"}

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
    """True for an `https` URL on port 443, without credentials and in printable ASCII,
    on one of the vendors' CDNs or `unavatar.io` (`cdn_media.url_on_hosts`). Every
    redirect a picture takes is checked by it again (`_get_on_allowed_hosts`)."""
    return cdn_media.url_on_hosts(url, _ALLOWED_HOST_SUFFIXES, exact=_ALLOWED_EXACT_HOSTS)


def valid_target(network: str, handle: str) -> bool:
    return network in _NETWORKS and _HANDLE_RE.fullmatch(handle) is not None


_SUFFIXES = frozenset(_TYPES.values())


def _inside(directory: Path, name: str) -> Path | None:
    """`<directory>/<name>`, only while the normalized path stays inside `directory`
    (normpath + startswith: CodeQL's py/path-injection sanitizer). The callers have
    already checked the name's parts; this is the last word."""
    base = os.path.normpath(os.path.abspath(directory))
    full = os.path.normpath(os.path.join(base, name))
    if not full.startswith(base + os.sep):
        return None
    return Path(full)


def _cache_path(directory: Path, network: str, handle: str, suffix: str) -> Path | None:
    """Where one account's picture is kept, `<directory>/<network>_<handle><suffix>` — for
    a known network and a handle of the allowed shape only, and only inside `directory`.
    Every read and write of the profile pictures' disk cache goes through here: a handle
    with `..`, a slash or anything odd never reaches the filesystem."""
    if not valid_target(network, handle) or suffix not in _SUFFIXES:
        return None
    return _inside(directory, f"{network}_{handle.lower()}{suffix}")


def cache_file(network: str, handle: str, *, directory: Path = AVATAR_DIR) -> Path | None:
    """The picture already on disk for this account, whatever its type, or None."""
    for suffix in _TYPES.values():
        candidate = _cache_path(directory, network, handle, suffix)
        if candidate is None:
            return None
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


#: Redirects a picture may take, each checked like the first URL; a longer chain is not
#: followed. Measured 2026-11-06 (`curl -sI` of a public TikTok handle): unavatar answers
#: the picture itself (200, image/jpeg), no redirect — the hops are for the CDNs' own.
_MAX_REDIRECTS = 3
#: A picture is asked for as it is stored: an answer compressed anyway is refused unread,
#: so `_MAX_BYTES` counts the bytes on the wire and bounds memory.
_REQUEST_HEADERS = {**_HEADERS, "Accept-Encoding": "identity"}
_IDENTITY = frozenset({"", "identity"})


@dataclass(frozen=True)
class _Answer:
    """How a picture request ended: its status and, for an image under `_MAX_BYTES`
    (a 200), its media type and bytes."""

    status: int
    media_type: str = ""
    content: bytes = b""


def _hostname(url: str) -> str:
    """The host alone — the one part of a URL safe to log, never its path or query."""
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return "?"
    return host if host and host.isascii() and host.isprintable() else "?"


def _next_hop(current: str, location: str) -> str | None:
    """Where a redirect from `current` goes, or None when it leaves the allowed hosts — a
    `Location` `urljoin` cannot even read (an unbalanced `[`) included. The refused host is
    logged, never the URL."""
    try:
        target = urljoin(current, location) if location else ""
    except ValueError:
        target = ""
    if not target or not source_allowed(target):
        logger.info("avatar redirect to %s refused: off the allowed hosts", _hostname(target))
        return None
    return target


async def _read_capped(response: httpx.Response) -> _Answer | None:
    """The body of a non-redirect answer, streamed: only an image's, never more than
    `_MAX_BYTES` (a declared `Content-Length` over it is refused before a byte is read),
    and never a compressed one. None when it is refused."""
    if response.status_code != 200:
        return _Answer(response.status_code)
    media_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if media_type not in _TYPES and media_type not in _HEIF_TYPES:
        return None
    if response.headers.get("content-encoding", "").strip().lower() not in _IDENTITY:
        return None
    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > _MAX_BYTES:
        return None
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():  # identity only: these are the wire bytes
        size += len(chunk)
        if size > _MAX_BYTES:
            return None
        chunks.append(chunk)
    return _Answer(200, media_type, b"".join(chunks))


async def _get_on_allowed_hosts(client: httpx.AsyncClient, url: str) -> _Answer | None:
    """GET `url` streamed, following at most `_MAX_REDIRECTS` redirects by hand: each
    `Location` is resolved against the URL that sent it and checked like the first one
    (`_next_hop`) before any request leaves for it. A hop off the allowlist — another host,
    http, another port, credentials, a control character, a `Location` that cannot be
    read — or one hop too many ends it with None. httpx's own redirects stay off: they
    would follow anywhere."""
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        async with client.stream(
            "GET", current, headers=_REQUEST_HEADERS, follow_redirects=False
        ) as response:
            if not response.is_redirect:
                return await _read_capped(response)
            location = response.headers.get("location", "")
        target = _next_hop(current, location)
        if target is None:
            return None
        current = target
    logger.info("avatar redirects past %d hops: not followed", _MAX_REDIRECTS)
    return None


async def _fetch(
    client: httpx.AsyncClient, url: str, *, now: float | None = None
) -> tuple[bytes, str] | None:
    """The picture at `url` as `(bytes, media type)`, or None for anything that is not
    a small image on an allowed host — redirects included (`_get_on_allowed_hosts`).
    HEIC/HEIF comes back converted to JPEG."""
    global _unavatar_blocked_until
    if not source_allowed(url):
        return None
    is_unavatar = urlsplit(url).hostname == "unavatar.io"
    moment = now if now is not None else time.time()
    if is_unavatar and _unavatar_blocked_until > moment:
        return None
    try:
        answer = await _get_on_allowed_hosts(client, url)
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        # `InvalidURL` is not an `HTTPError`: a URL httpx refuses is just "no picture"
        logger.info("avatar fetch failed: %s", type(exc).__name__)
        return None
    if answer is None:
        return None
    if answer.status == 429 and is_unavatar:
        _unavatar_blocked_until = moment + _UNAVATAR_COOLDOWN_SECONDS
        logger.info("unavatar rate-limited, pausing lookups for an hour")
        return None
    if answer.status != 200 or not answer.content:
        return None
    if answer.media_type in _HEIF_TYPES:
        converted = await asyncio.to_thread(heif_to_jpeg, answer.content)
        return (converted, "image/jpeg") if converted else None
    if answer.media_type not in _TYPES:
        return None
    return answer.content, answer.media_type


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
    path = _cache_path(directory, network, handle, _TYPES[media_type])
    if path is None:  # served, never kept: the account is not one the cache can name
        return content, media_type
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
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


# -- Reel covers («Descubrir reels», § request 2026-10-15) --------------------------------
# The same problem as a profile picture — a signed vendor URL that dies within days, and
# an Instagram CDN that does not serve other sites' pages reliably — so the same answer:
# the backend fetches the cover once, keeps it on disk and serves its own copy. Keyed by
# the reel, not the account; no paid last resort (a dead cover just shows the placeholder
# until the next read of the referente brings a fresh URL).

#: Under `/avatar` on purpose: production's Caddy already sends `/avatar/*` to the Reflex
#: backend (`deploy/Caddyfile`), and the extra segment keeps it apart from a profile.
REEL_COVER_ROUTE = AVATAR_ROUTE + "/reel"
_REEL_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")  # matched whole (`fullmatch`)
_reel_misses: dict[tuple[str, str], float] = {}


def _cover_key() -> bytes:
    """The key cover paths are signed with: derived from the server's state secret
    (`creator_discovery.proxy_key`, which also signs the profile pictures' paths), so
    every backend worker agrees on it and it is never the state secret itself."""
    return proxy_key(b"qualify/reel-cover/v1")


def reel_cover_signature(network: str, reel_id: str, vendor_url: str) -> str:
    message = f"{network}\n{reel_id}\n{vendor_url}".encode()
    return hmac.new(_cover_key(), message, sha256).hexdigest()[:32]


def reel_cover_path(network: str, reel_id: str, vendor_url: str) -> str:
    """The signed path the card asks for a reel's cover with. Signed because the route
    is public (an `<img>` carries no session): unsigned, anyone could pin any allowed
    image under any reel id, or fill the disk with made-up ids."""
    return (
        f"{REEL_COVER_ROUTE}/{network}/{quote(reel_id, safe='')}"
        f"?u={quote(vendor_url, safe='')}"
        f"&s={reel_cover_signature(network, reel_id, vendor_url)}"
    )


def reel_cover_dir(directory: Path = AVATAR_DIR) -> Path:
    return directory / "reels"


def _reel_cover_path(directory: Path, network: str, reel_id: str, suffix: str) -> Path | None:
    """Where one reel's cover is kept, `<directory>/reels/<network>_<reel id><suffix>` — for
    a known network and a reel id of the allowed shape only, and only inside that folder.
    Every read and write of the covers' disk cache goes through here."""
    if network not in _NETWORKS or _REEL_ID_RE.fullmatch(reel_id) is None:
        return None
    if suffix not in _SUFFIXES:
        return None
    return _inside(reel_cover_dir(directory), f"{network}_{reel_id}{suffix}")


async def resolve_reel_cover(
    network: str,
    reel_id: str,
    vendor_url: str,
    *,
    client: httpx.AsyncClient | None = None,
    directory: Path = AVATAR_DIR,
    now: float | None = None,
) -> tuple[bytes, str] | None:
    """One reel's cover: disk first, then the vendor URL (unless its signature already
    expired), else None — a miss remembered for `_MISS_TTL_SECONDS`."""
    if network not in _NETWORKS or not _REEL_ID_RE.fullmatch(reel_id):
        return None
    for suffix in _TYPES.values():
        cached = _reel_cover_path(directory, network, reel_id, suffix)
        if cached is None:
            return None
        if cached.is_file():
            return cached.read_bytes(), _media_type(cached)
    moment = now if now is not None else time.time()
    key = (network, reel_id)
    if _reel_misses.get(key, 0.0) > moment:
        return None
    if not vendor_url or signature_expired(vendor_url, now=moment):
        _reel_misses[key] = moment + _MISS_TTL_SECONDS
        return None
    found = await _fetch(client or _shared(), vendor_url, now=moment)
    if found is None:
        _reel_misses[key] = moment + _MISS_TTL_SECONDS
        return None
    content, media_type = found
    path = _reel_cover_path(directory, network, reel_id, _TYPES[media_type])
    if path is None:
        return found
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    except OSError as exc:
        logger.warning("reel cover cache write failed: %s", type(exc).__name__)
    return found


def _signed(given: str, expected: str) -> bool:
    return given.isascii() and hmac.compare_digest(given, expected)


avatar_api = FastAPI()


@avatar_api.get(REEL_COVER_ROUTE + "/{network}/{reel_id}")
async def reel_cover(network: str, reel_id: str, u: str = "", s: str = "") -> Response:
    """`GET /avatar/reel/<network>/<reel id>?u=<vendor url>&s=<signature>` → the cover,
    or 404 — also for a path `reel_cover_path` did not sign."""
    network = network.lower()
    if not _signed(s, reel_cover_signature(network, reel_id, u)):
        return Response(status_code=404, headers=_NO_STORE)
    found = await resolve_reel_cover(network, reel_id, u)
    if found is None:
        return Response(status_code=404, headers=_NO_STORE)
    content, media_type = found
    return Response(content=content, media_type=media_type, headers=_CACHE_HEADERS)


@avatar_api.get(AVATAR_ROUTE + "/{network}/{handle}")
async def avatar(network: str, handle: str, u: str = "", s: str = "") -> Response:
    """`GET /avatar/<network>/<handle>?u=<vendor url>&s=<signature>` → the picture, or 404.

    Signed (`creator_discovery.avatar_signature`, m-24957331): a path the server did not
    hand out — unsigned, forged, or another account's — is a `no-store` 404 before any
    read of the disk or the network, so `u` can only ever be a URL this server issued.

    Never the paid last resort (ADR 42 R5, founder decision 2026-11-04): an `<img>`
    request carries no session, so there is no business to charge the read to, and a
    read nobody is charged for is not made. The session's own prefetch
    (`warm_avatars_in_background`, charged to its business) is what pays for a picture
    whose URL arrived dead."""
    network = network.lower()
    if not _signed(s, avatar_signature(network, handle, u)):
        return Response(status_code=404, headers=_NO_STORE)
    found = await resolve_avatar(network, handle, u)
    if found is None:
        return Response(status_code=404, headers=_NO_STORE)
    content, media_type = found
    return Response(content=content, media_type=media_type, headers=_CACHE_HEADERS)

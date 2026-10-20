"""Stock search and import for the generator (`docs/plan-integracion-stock-pexels-pixabay.md`
§3.5-3.7, STK-03; founder's review R1-R2 of 2026-10-16).

`search` — only on a human's request (Enter or the button, never while typing: Pixabay asks
for «real human requests»):
1. normalize the text (trim, collapse, ≤100 chars);
2. the shared 24 h cache — results are public and tenant-independent, so a hit serves any
   tenant and spends no quota (Pixabay REQUIRES the 24 h cache);
3. the tenant's hourly quota, a fixed window in Redis;
4. a provider in cool-down after a 429 is skipped, never retried while the operator waits;
5. providers in order; the next one is only asked when the previous gave fewer than
   `ENOUGH_RESULTS` usable hits or failed — with Pixabay alone today (R1) it answers solo.

`import_item` — «Usar»: the browser sends only `(provider, id)`; the item comes from what
THIS session's search returned (the caller keeps it backend-side), so the server never
downloads a URL the browser chose. Then: import quota → already imported? (natural key, no
download) → ask the provider for a fresh URL → download from an allowed host with a byte
cap → normalize like the catalog (EXIF, P3→sRGB, Meta-safe JPEG) → R2 under
`t/{tenant}/stock/…` through `ObjectGate` → the provenance row, `ON CONFLICT DO NOTHING`
and re-read, so two clicks end in one row. The artifact is in R2 and the state in Postgres
before any slot uses it.

Video import is Fase 2 (STK-07: a PyAV normalizer — there is no `ffmpeg` binary in the
image nor on Windows); `import_item` refuses it until then.
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from qualify_creative.stock import (
    PEOPLE_FILTER_VERSION,
    Orientation,
    StockError,
    StockItem,
    StockMediaType,
    StockNotConfigured,
    StockPage,
    StockProvider,
    StockQuery,
    StockRateLimited,
    StockRendition,
)
from qualify_shared.db.session import tenant_session
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from qualify_api.stock.keys import stock_object_key
from qualify_api.stock.models import StockAsset
from qualify_api.stock.state import KeyValue

logger = logging.getLogger(__name__)

IMPORTER_VERSION = "stock-import/1"
CACHE_TTL_S = 24 * 60 * 60
CACHE_VERSION = "v1"
#: Fewer usable hits than this and the next provider is asked too (§3.5 step 5).
ENOUGH_RESULTS = 12
#: The Brand Kit's searches run at once (`search_many`): enough variety for a page,
#: well inside Pixabay's 100 requests per minute per key.
MAX_PARALLEL_QUERIES = 4
DEFAULT_PER_PAGE = 30
SEARCHES_PER_TENANT_HOUR_ENV = "QUALIFY_STOCK_SEARCHES_PER_TENANT_HOUR"
IMPORTS_PER_TENANT_HOUR_ENV = "QUALIFY_STOCK_IMPORTS_PER_TENANT_HOUR"
DEFAULT_SEARCHES_PER_HOUR = 30
DEFAULT_IMPORTS_PER_HOUR = 20
DEFAULT_COOLDOWN_S = 60
MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_VIDEO_BYTES = 80 * 1024 * 1024
#: What a clip reference takes (Seedance asks 2-15 s per reference video) and what a
#: gallery slide needs: an imported stock video is cut there.
MAX_STOCK_VIDEO_SECONDS = 15.0
MP4 = "video/mp4"
DOWNLOAD_TIMEOUT_S = 30.0
#: The only hosts an import downloads from (§3.7 step 3; Pixabay measured 2026-10-16:
#: `largeImageURL` answers 200 straight from `pixabay.com/get/…`, no redirect). Redirects
#: are not followed: a hop is a host this list never approved.
ALLOWED_DOWNLOAD_HOSTS: frozenset[str] = frozenset(
    {"pixabay.com", "cdn.pixabay.com", "images.pexels.com", "videos.pexels.com"}
)

#: What the operator reads. No vendor name, no status code (product rule 2026-10-08).
UNAVAILABLE_TEXT = "El stock no está disponible ahora mismo."
QUOTA_TEXT = (
    "Hiciste muchas búsquedas seguidas. Prueba en unos minutos o usa una búsqueda reciente."
)
IMPORT_QUOTA_TEXT = "Usaste muchas imágenes de stock seguidas. Prueba en unos minutos."
BUSY_TEXT = "Hay muchas búsquedas en curso. Inténtalo en unos minutos."
GONE_TEXT = "Esa imagen ya no está disponible. Elige otra."
FAILED_TEXT = "No pudimos traer esa imagen. Inténtalo de nuevo."


@dataclass
class _Charge:
    """Whether this user action already spent its unit of the hourly quota — shared by
    the searches of one click (`search_many`), so a click costs one
    search whatever it runs. Thread-safe: `search_many` runs its searches in parallel."""

    spent: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def take(self) -> bool:
        """True for exactly one caller: the one that must spend the unit."""
        with self._lock:
            if self.spent:
                return False
            self.spent = True
            return True


class StockUnavailable(Exception):
    """The operator-facing failure: `args[0]` is the Spanish text to show."""


class StockQuotaExceeded(StockUnavailable):
    pass


@dataclass(frozen=True)
class StockSearchResult:
    items: tuple[StockItem, ...]
    has_more: bool
    providers: tuple[str, ...]  # who answered, for the credit line
    dropped: dict[str, int] = field(default_factory=dict)
    cached: bool = False


@dataclass(frozen=True)
class ImportedStock:
    id: UUID
    provider: str
    provider_media_id: str
    object_key: str
    content_type: str
    width: int
    height: int
    author_name: str
    author_url: str | None
    source_page_url: str
    ai_input_allowed: bool
    media_type: str = "image"
    poster_object_key: str | None = None
    duration_sec: float | None = None


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def normalize_query(text: str) -> str:
    return " ".join(text.split())[:100]


# -- the cache's wire form ----------------------------------------------------------------


def item_to_dict(item: StockItem) -> dict[str, Any]:
    data = asdict(item)
    data["media_type"] = item.media_type.value
    data["raw"] = dict(item.raw)
    return data


def item_from_dict(data: dict[str, Any]) -> StockItem:
    return StockItem(
        **{
            **data,
            "media_type": StockMediaType(data["media_type"]),
            "best": StockRendition(**data["best"]),
        }
    )


def _page_to_dict(page: StockPage) -> dict[str, Any]:
    return {
        "items": [item_to_dict(i) for i in page.items],
        "page": page.page,
        "has_more": page.has_more,
        "total_hint": page.total_hint,
        "dropped": dict(page.dropped),
    }


def _page_from_dict(data: dict[str, Any]) -> StockPage:
    return StockPage(
        items=tuple(item_from_dict(i) for i in data["items"]),
        page=data["page"],
        has_more=data["has_more"],
        total_hint=data.get("total_hint"),
        dropped=data.get("dropped") or {},
    )


def _cache_key(provider: str, query: StockQuery) -> str:
    material = "|".join(
        (
            query.text.casefold(),
            query.media_type.value,
            query.orientation.value,
            str(query.page),
            str(query.per_page),
            str(query.exclude_people),
            query.category or "",
        )
    )
    digest = hashlib.sha256(material.encode()).hexdigest()
    return f"stock:search:{CACHE_VERSION}:{provider}:{digest}"


# -- the download -------------------------------------------------------------------------


Downloader = Callable[[str, int], tuple[bytes, str]]


def http_download(url: str, max_bytes: int) -> tuple[bytes, str]:
    """GET `url` from an allowed host, streaming with a byte cap. Returns (bytes,
    content-type). Raises `StockError`; the message never carries the URL."""
    import httpx  # noqa: PLC0415 — optional dependency, already in the app

    host = (urlsplit(url).hostname or "").lower()
    if urlsplit(url).scheme != "https" or host not in ALLOWED_DOWNLOAD_HOSTS:
        raise StockError("download host not allowed")
    chunks: list[bytes] = []
    size = 0
    try:
        with httpx.Client(timeout=DOWNLOAD_TIMEOUT_S, follow_redirects=False) as client:
            with client.stream("GET", url) as response:
                if response.status_code in (404, 410):
                    raise StockError("stock file gone", status_code=response.status_code)
                if response.status_code != 200:
                    raise StockError(
                        f"stock download answered HTTP {response.status_code}",
                        status_code=response.status_code,
                    )
                content_type = response.headers.get("content-type", "")
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise StockError("stock file larger than the cap")
                    chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise StockError(f"stock download failed: {type(exc).__name__}") from None
    return b"".join(chunks), content_type


@dataclass(frozen=True)
class StockVideoFile:
    data: bytes
    width: int
    height: int
    duration_sec: float
    poster: bytes | None = None


VideoNormalizer = Callable[[bytes, int, int], StockVideoFile]


def video_target_size(width: int, height: int) -> tuple[int, int]:
    """The source's own proportions, scaled down to fit 1080×1920 (portrait) or
    1920×1080 (landscape) — never up — with even sides, as H.264 needs."""
    scale = min(1.0, 1920 / max(width, height), 1080 / min(width, height))
    return max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2)


def pyav_video_normalizer(data: bytes, width: int, height: int) -> StockVideoFile:
    """H.264 `yuv420p` MP4, `+faststart`, no audio, ≤ 15 s, ≤ 1080×1920 at its own
    proportions — with PyAV (`PyAvVideoFitter`), because neither the production image
    nor a Windows machine has the `ffmpeg` binary the catalog's normalizer calls."""
    from qualify_creative.video.fit import PyAvVideoFitter  # noqa: PLC0415

    fitted = PyAvVideoFitter().fit(
        data, size=video_target_size(width, height), max_seconds=MAX_STOCK_VIDEO_SECONDS
    )
    return StockVideoFile(
        data=fitted.data,
        width=fitted.width,
        height=fitted.height,
        duration_sec=fitted.duration_sec,
        poster=fitted.poster,
    )


def _normalize_image(data: bytes) -> tuple[bytes, int, int]:
    from PIL import Image  # noqa: PLC0415
    from qualify_creative.photo.normalize import (  # noqa: PLC0415
        export_for_instagram,
        load_normalized,
    )

    payload = export_for_instagram(load_normalized(data))
    with Image.open(io.BytesIO(payload)) as exported:
        width, height = exported.size
    return payload, width, height


# -- the service --------------------------------------------------------------------------


class StockService:
    def __init__(
        self,
        *,
        providers: Sequence[StockProvider],
        state: KeyValue,
        gate: Any = None,  # an `ObjectGate`; built from R2Settings on first import
        download: Downloader = http_download,
        video_normalizer: VideoNormalizer = pyav_video_normalizer,
        searches_per_hour: int | None = None,
        imports_per_hour: int | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._providers = tuple(providers)
        self._state = state
        self._gate = gate
        self._download = download
        self._video_normalizer = video_normalizer
        self._searches_per_hour = (
            searches_per_hour
            if searches_per_hour is not None
            else _env_int(SEARCHES_PER_TENANT_HOUR_ENV, DEFAULT_SEARCHES_PER_HOUR)
        )
        self._imports_per_hour = (
            imports_per_hour
            if imports_per_hour is not None
            else _env_int(IMPORTS_PER_TENANT_HOUR_ENV, DEFAULT_IMPORTS_PER_HOUR)
        )
        self._clock = clock

    @property
    def available(self) -> bool:
        return bool(self._providers) and self._searches_per_hour > 0

    def provider(self, name: str) -> StockProvider | None:
        return next((p for p in self._providers if p.name == name), None)

    # -- search ------------------------------------------------------------------------

    def search(
        self,
        tenant_id: UUID,
        text: str,
        *,
        media_type: StockMediaType = StockMediaType.IMAGE,
        orientation: Orientation = Orientation.ANY,
        page: int = 1,
        exclude_people: bool = True,
        category: str | None = None,
        per_page: int = DEFAULT_PER_PAGE,
        charge: _Charge | None = None,
    ) -> StockSearchResult:
        charge = charge or _Charge()
        normalized = normalize_query(text)
        if not normalized:
            raise StockUnavailable("Escribe qué quieres buscar.")
        if not self.available:
            raise StockUnavailable(UNAVAILABLE_TEXT)
        query = StockQuery(
            text=normalized,
            media_type=media_type,
            orientation=orientation,
            page=page,
            per_page=per_page,
            exclude_people=exclude_people,
            category=category,
        )
        items: list[StockItem] = []
        answered: list[str] = []
        dropped: dict[str, int] = {}
        has_more = False
        all_cached = True
        failures: list[str] = []
        for provider in self._providers:
            if media_type not in provider.media_types:
                continue
            if len(items) >= ENOUGH_RESULTS:
                break
            key = _cache_key(provider.name, query)
            cached = self._state.get_json(key)
            if cached is not None:
                result = _page_from_dict(cached)
            else:
                all_cached = False
                if self._state.ttl(f"stock:cooldown:{provider.name}"):
                    failures.append("busy")
                    continue
                if charge.take():
                    self._spend_search_quota(tenant_id)
                try:
                    result = provider.search(query)
                except StockRateLimited as exc:
                    self._cool_down(provider.name, exc.retry_after_s)
                    failures.append("busy")
                    continue
                except StockNotConfigured:
                    logger.warning("stock provider %s is not configured", provider.name)
                    failures.append("unavailable")
                    continue
                except StockError as exc:
                    logger.warning("stock search failed at %s: %s", provider.name, exc)
                    failures.append("unavailable")
                    continue
                self._state.set_json(key, _page_to_dict(result), CACHE_TTL_S)
            answered.append(provider.name)
            items.extend(result.items)
            has_more = has_more or result.has_more
            for reason, n in result.dropped.items():
                dropped[reason] = dropped.get(reason, 0) + n
        if not answered:
            raise StockUnavailable(BUSY_TEXT if "busy" in failures else UNAVAILABLE_TEXT)
        return StockSearchResult(
            items=tuple(items),
            has_more=has_more,
            providers=tuple(answered),
            dropped=dropped,
            cached=all_cached,
        )

    def search_many(
        self,
        tenant_id: UUID,
        texts: Sequence[str],
        *,
        page: int = 1,
        max_queries: int = MAX_PARALLEL_QUERIES,
        **filters: Any,
    ) -> tuple[tuple[str, ...], StockSearchResult]:
        """Several searches at once — the Brand Kit's words (§ request 2026-10-16: «más
        opciones») — merged into one page: round-robin across the searches so the page
        mixes them, the same image once. Answers with the words that brought images.
        Up to `max_queries` words should bring images: a word that brings none (a
        misspelled rubro, a joined hashtag) gives its place to the next one in a second
        wave. One unit of quota for the click; each search is cached on its own. A
        search that fails alone is left out; the quota running out, or every search
        failing, raises."""
        pending = list(dict.fromkeys(normalize_query(t) for t in texts if normalize_query(t)))
        if not pending:
            raise StockUnavailable("Escribe qué quieres buscar.")
        charge = _Charge()

        def run(text: str) -> StockSearchResult | StockUnavailable:
            try:
                return self.search(tenant_id, text, page=page, charge=charge, **filters)
            except StockQuotaExceeded:
                raise
            except StockUnavailable as exc:
                return exc

        answered: list[tuple[str, StockSearchResult]] = []
        failures: list[StockUnavailable] = []
        while pending:
            room = max_queries - sum(1 for _, r in answered if r.items)
            if room <= 0:
                break
            wave, pending = pending[:room], pending[room:]
            with ThreadPoolExecutor(max_workers=len(wave)) as pool:
                outcomes = list(pool.map(run, wave))
            for text, out in zip(wave, outcomes, strict=True):
                if isinstance(out, StockSearchResult):
                    answered.append((text, out))
                else:
                    failures.append(out)
        if not answered:
            raise failures[0]
        merged: list[StockItem] = []
        seen: set[tuple[str, str]] = set()
        queues = [list(result.items) for _, result in answered]
        while any(queues):
            for queue in queues:
                if not queue:
                    continue
                item = queue.pop(0)
                key = (item.provider, item.provider_media_id)
                if key not in seen:
                    seen.add(key)
                    merged.append(item)
        dropped: dict[str, int] = {}
        for _, result in answered:
            for reason, n in result.dropped.items():
                dropped[reason] = dropped.get(reason, 0) + n
        used = tuple(text for text, result in answered if result.items)
        return used, StockSearchResult(
            items=tuple(merged),
            has_more=any(result.has_more for _, result in answered),
            providers=tuple(dict.fromkeys(p for _, r in answered for p in r.providers)),
            dropped=dropped,
            cached=all(result.cached for _, result in answered),
        )

    def _hour(self) -> str:
        return self._clock().strftime("%Y%m%d%H")

    def _spend_search_quota(self, tenant_id: UUID) -> None:
        count = self._state.incr(f"stock:quota:search:{tenant_id}:{self._hour()}", 3600)
        if count > self._searches_per_hour:
            raise StockQuotaExceeded(QUOTA_TEXT)

    def _cool_down(self, provider: str, retry_after_s: int | None) -> None:
        seconds = retry_after_s if retry_after_s and retry_after_s > 0 else DEFAULT_COOLDOWN_S
        self._state.set_json(f"stock:cooldown:{provider}", True, seconds)

    # -- import ------------------------------------------------------------------------

    def import_item(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        user_id: UUID | None,
        item: StockItem,
        search_query: str,
        search_filters: dict[str, Any] | None = None,
        people_filter: bool = True,
    ) -> ImportedStock:
        provider = self.provider(item.provider)
        if provider is None:
            raise StockUnavailable(UNAVAILABLE_TEXT)
        video = item.media_type is StockMediaType.VIDEO
        # a bank numbers its photos and its videos apart: the rendition keeps a photo and
        # a video with the same id from sharing the natural key
        rendition = f"video-{item.best.label}" if video else item.best.label
        existing = self._find(tenant_id, item.provider, item.provider_media_id, rendition)
        if existing is not None:
            return existing
        count = self._state.incr(f"stock:quota:import:{tenant_id}:{self._hour()}", 3600)
        if count > self._imports_per_hour:
            raise StockQuotaExceeded(IMPORT_QUOTA_TEXT)

        try:
            fresh = provider.resolve_download(item)
            data, _ = self._download(fresh.url, MAX_VIDEO_BYTES if video else MAX_IMAGE_BYTES)
        except StockRateLimited as exc:
            self._cool_down(provider.name, exc.retry_after_s)
            raise StockUnavailable(BUSY_TEXT) from None
        except StockNotConfigured:
            raise StockUnavailable(UNAVAILABLE_TEXT) from None
        except StockError as exc:
            logger.warning(
                "stock import failed (%s %s): %s", item.provider, item.provider_media_id, exc
            )
            raise StockUnavailable(
                GONE_TEXT if exc.status_code in (404, 410) else FAILED_TEXT
            ) from None
        poster: bytes | None = None
        duration: Decimal | None = None
        try:
            if video:
                clip = self._video_normalizer(data, fresh.width, fresh.height)
                payload, width, height, poster = clip.data, clip.width, clip.height, clip.poster
                duration = Decimal(str(round(clip.duration_sec, 2)))
            else:
                payload, width, height = _normalize_image(data)
        except Exception as exc:  # noqa: BLE001 — an unreadable file is the provider's
            logger.warning("stock file unreadable (%s): %s", item.provider_media_id, exc)
            raise StockUnavailable(FAILED_TEXT) from None

        sha = hashlib.sha256(payload).hexdigest()
        folder_id = f"video-{item.provider_media_id}" if video else item.provider_media_id
        ext, content_type = ("mp4", MP4) if video else ("jpg", "image/jpeg")
        key = stock_object_key(tenant_id, item.provider, folder_id, sha, ext)
        # the poster sits beside its video: same name, `.jpg`
        poster_key = (
            stock_object_key(tenant_id, item.provider, folder_id, sha, "jpg") if poster else None
        )
        try:
            self._r2().put_media(tenant_id, key, io.BytesIO(payload), content_type)
            if poster and poster_key:
                self._r2().put_media(tenant_id, poster_key, io.BytesIO(poster), "image/jpeg")
        except Exception as exc:  # noqa: BLE001 — no R2 configured, R2 down
            logger.warning("stock object not kept in R2 (%s): %s", key, type(exc).__name__)
            raise StockUnavailable(UNAVAILABLE_TEXT) from None

        values = {
            "tenant_id": tenant_id,
            "brand_id": brand_id,
            "provider": item.provider,
            "provider_media_id": item.provider_media_id,
            "media_type": item.media_type.value,
            "rendition": rendition,
            "object_key": key,
            "poster_object_key": poster_key,
            "content_type": content_type,
            "width": width,
            "height": height,
            "duration_sec": duration,
            "source_duration_sec": (
                Decimal(str(round(item.duration_sec, 2))) if item.duration_sec else None
            ),
            "bytes": len(payload),
            "sha256": sha,
            "author_name": item.author_name,
            "author_url": item.author_url,
            "source_page_url": item.page_url,
            "license_name": provider.license_name,
            "license_url": provider.license_url,
            "license_terms_date": date.fromisoformat(provider.license_terms_date),
            "search_query": normalize_query(search_query),
            "search_filters": search_filters or {},
            "provider_payload": dict(item.raw),
            "ai_input_allowed": provider.ai_input_allowed and not item.no_ai,
            "people_filter": people_filter,
            "people_filter_version": PEOPLE_FILTER_VERSION if people_filter else None,
            "importer_version": IMPORTER_VERSION,
            "downloaded_at": self._clock(),
            "created_by": user_id,
        }
        with tenant_session(tenant_id) as session:
            session.execute(
                insert(StockAsset)
                .values(**values)
                .on_conflict_do_nothing(constraint="uq_stock_assets_natural")
            )
        found = self._find(tenant_id, item.provider, item.provider_media_id, rendition)
        if found is None:  # pragma: no cover — the row was just written
            raise StockUnavailable(FAILED_TEXT)
        return found

    def _r2(self) -> Any:
        if self._gate is None:
            from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
            from qualify_shared.objects.gate import ObjectGate  # noqa: PLC0415
            from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

            self._gate = ObjectGate(R2ObjectStore(R2Settings.from_env()))
        return self._gate

    def _find(
        self, tenant_id: UUID, provider: str, media_id: str, rendition: str
    ) -> ImportedStock | None:
        with tenant_session(tenant_id) as session:
            row = session.scalar(
                select(StockAsset).where(
                    StockAsset.tenant_id == tenant_id,
                    StockAsset.provider == provider,
                    StockAsset.provider_media_id == media_id,
                    StockAsset.rendition == rendition,
                    StockAsset.withdrawn_at.is_(None),
                )
            )
            return _record(row) if row is not None else None

    # -- the tenant's own library ------------------------------------------------------

    def recent(
        self, *, tenant_id: UUID, brand_id: UUID, limit: int = 12
    ) -> tuple[ImportedStock, ...]:
        """«Ya usaste»: what this brand imported, newest first — no provider call."""
        with tenant_session(tenant_id) as session:
            rows = session.scalars(
                select(StockAsset)
                .where(
                    StockAsset.brand_id == brand_id,
                    StockAsset.media_type == StockMediaType.IMAGE.value,
                    StockAsset.withdrawn_at.is_(None),
                )
                .order_by(StockAsset.created_at.desc())
                .limit(limit)
            )
            return tuple(_record(r) for r in rows)

    def assets_by_key(self, *, tenant_id: UUID, keys: Sequence[str]) -> dict[str, ImportedStock]:
        wanted = [k for k in keys if k]
        if not wanted:
            return {}
        with tenant_session(tenant_id) as session:
            rows = session.scalars(select(StockAsset).where(StockAsset.object_key.in_(wanted)))
            return {r.object_key: _record(r) for r in rows}


def _record(row: StockAsset) -> ImportedStock:
    return ImportedStock(
        id=row.id,
        provider=row.provider,
        provider_media_id=row.provider_media_id,
        object_key=row.object_key,
        content_type=row.content_type,
        width=row.width,
        height=row.height,
        author_name=row.author_name,
        author_url=row.author_url,
        source_page_url=row.source_page_url,
        ai_input_allowed=row.ai_input_allowed,
        media_type=row.media_type,
        poster_object_key=row.poster_object_key,
        duration_sec=float(row.duration_sec) if row.duration_sec is not None else None,
    )

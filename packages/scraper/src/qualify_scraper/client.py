from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from qualify_scraper.shared import Platform, RawHydration, RawPayloadStore

HydrationExtractor = Callable[[str], dict[str, Any]]


class ScrapingClient(Protocol):
    """Vendor-agnostic ingestion surface. ADR 17 selects build-in-house over
    Zyte as the primary path; EnsembleData/Data365 stay a documented fallback
    for blocked formats. Parsers and tests depend only on this Protocol, so the
    concrete client stays swappable."""

    def fetch_hydration(self, url: str) -> RawHydration: ...


class ZyteTransport(Protocol):
    """The network seam: fetch a post page's rendered HTML. The only place a
    live request happens — never exercised by the test suite."""

    def fetch_html(self, url: str) -> str: ...


class ZyteApiTransport:
    """Live Zyte API transport (browser-rendered HTML). We buy Zyte's proxy /
    anti-block and write the parser ourselves (CLAUDE.md Build/Buy split).

    Never used in tests — the suite injects a fixture-backed transport instead.
    `httpx` is imported lazily so the package imports without it present."""

    def __init__(
        self,
        api_key: str | None = None,
        endpoint: str = "https://api.zyte.com/v1/extract",
        timeout: float = 60.0,
    ) -> None:
        self._api_key = api_key or os.environ["ZYTE_API_KEY"]
        self._endpoint = endpoint
        self._timeout = timeout

    def fetch_html(self, url: str) -> str:
        import httpx

        response = httpx.post(
            self._endpoint,
            auth=(self._api_key, ""),
            json={"url": url, "browserHtml": True},
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()["browserHtml"]


class ZyteScrapingClient:
    """Real ingestion client: fetch HTML via Zyte, extract the embedded
    hydration JSON, persist the raw payload as the canonical artifact, then
    return it wrapped for parsing. The raw payload is stored BEFORE parsing, so a
    post can always be re-parsed without re-scraping."""

    def __init__(
        self,
        transport: ZyteTransport,
        store: RawPayloadStore,
        extractor: HydrationExtractor,
        platform: Platform,
    ) -> None:
        self._transport = transport
        self._store = store
        self._extractor = extractor
        self._platform = platform

    def fetch_hydration(self, url: str) -> RawHydration:
        html = self._transport.fetch_html(url)
        payload = self._extractor(html)
        r2_key = self._store.persist(self._platform, url, payload)
        return RawHydration(
            url=url,
            hydration=payload,
            fetched_at=datetime.now(),
            r2_key=r2_key,
        )


class FixtureScrapingClient:
    """Test double that serves saved hydration JSON from disk — no network, ever.

    Constructed with a mapping of post URL -> fixture path. Used across the test
    suite in place of a live vendor client so parsers can be verified against
    representative payloads offline."""

    def __init__(self, url_to_fixture: dict[str, Path]) -> None:
        self._url_to_fixture = url_to_fixture

    def fetch_hydration(self, url: str) -> RawHydration:
        fixture_path = self._url_to_fixture[url]
        payload = json.loads(fixture_path.read_text())
        return RawHydration(
            url=url,
            hydration=payload,
            fetched_at=datetime.fromtimestamp(0),
            r2_key=f"hydration/{fixture_path.name}",
        )

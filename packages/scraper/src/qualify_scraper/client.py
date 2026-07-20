from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from qualify_scraper.shared import Platform, RawPayloadEnvelope, build_envelope

HydrationExtractor = Callable[[str], dict[str, Any]]


class ScrapingClient(Protocol):
    """Vendor-agnostic ingestion surface. ADR 17 selects build-in-house over
    Zyte as the primary path; EnsembleData/Data365 stay a documented fallback
    for blocked formats. Parsers and tests depend only on this Protocol, so the
    concrete client stays swappable.

    Pure capture (ADR 18): `fetch_hydration` builds + signs a brand-agnostic
    `RawPayloadEnvelope` but does NOT persist. Persistence is a separate commit
    step (`persist_envelope`), so the raw is stored before it is parsed."""

    def fetch_hydration(self, url: str) -> RawPayloadEnvelope: ...


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
    """Real ingestion client: fetch HTML via Zyte, extract the embedded hydration
    JSON, and return it wrapped + signed as a brand-agnostic `RawPayloadEnvelope`.

    Pure capture — it does NOT persist (ADR 18). The caller/scrape-worker commits
    the envelope via `persist_envelope` before parsing, so the raw is always stored
    before a `Post` is built (raw-before-parse, enforced by type dependency: only
    persist yields the `hydration_json_r2_key` a `Post` requires)."""

    def __init__(
        self,
        transport: ZyteTransport,
        extractor: HydrationExtractor,
        platform: Platform,
    ) -> None:
        self._transport = transport
        self._extractor = extractor
        self._platform = platform

    def fetch_hydration(self, url: str) -> RawPayloadEnvelope:
        html = self._transport.fetch_html(url)
        payload = self._extractor(html)
        return build_envelope(
            platform=self._platform,
            source_url=url,
            hydration=payload,
            fetched_at=datetime.now(),
        )


class FixtureScrapingClient:
    """Test double that serves saved hydration JSON from disk — no network, ever.

    Constructed with a mapping of post URL -> fixture path plus the platform it
    serves (an envelope needs a platform; a fixture client is platform-scoped
    anyway). Returns a real, signed `RawPayloadEnvelope` with a deterministic
    `fetched_at` so tests are reproducible. Used across the suite in place of a live
    vendor client so parsers can be verified against representative payloads offline."""

    def __init__(self, url_to_fixture: dict[str, Path], platform: Platform) -> None:
        self._url_to_fixture = url_to_fixture
        self._platform = platform

    def fetch_hydration(self, url: str) -> RawPayloadEnvelope:
        fixture_path = self._url_to_fixture[url]
        payload = json.loads(fixture_path.read_text())
        return build_envelope(
            platform=self._platform,
            source_url=url,
            hydration=payload,
            fetched_at=datetime.fromtimestamp(0),
        )

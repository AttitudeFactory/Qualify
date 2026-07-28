"""The network seam. `Fetcher` is the only place a live request can happen.

Mirrors the Protocol + live-impl + fixture-double shape already established in
`packages/scraper` (`ScrapingClient` / `ZyteApiTransport` / `FixtureScrapingClient`).
Tests inject `FixtureFetcher`, so the suite's no-network guarantee is structural
-- there is no code path from a test to a socket -- rather than a promise about
how the tests are written.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

# The host geo-localizes: without this header /docs/graph-api/overview comes back
# in Spanish. Measured 2026-07-24.
DEFAULT_HEADERS: dict[str, str] = {
    "Accept-Language": "en-US,en;q=0.9",
    # Identifies us honestly and gives Meta a contact if the crawl misbehaves.
    "User-Agent": "QualifyDocsHarvester/0.1 (contact: hlrd1993@gmail.com)",
}

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class FetchResult:
    """One HTTP response, reduced to what the crawl and the manifest need.

    `requested_url` and `final_url` differ whenever Meta redirects -- which is the
    normal case for `/docs/` -> `/documentation/`. Everything downstream keys on
    `final_url`; `requested_url` only feeds the alias table.
    """

    requested_url: str
    final_url: str
    status_code: int
    content_type: str
    body: str
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and 200 <= self.status_code < 300

    @property
    def is_markdown(self) -> bool:
        return "text/markdown" in self.content_type.casefold()


class Fetcher(Protocol):
    """Fetch one URL, following redirects. Never raises for HTTP-level failure --
    a failed fetch is a `FetchResult` carrying `error`, so the crawl records it in
    the manifest and continues instead of losing the run."""

    def fetch(self, url: str) -> FetchResult: ...


class HttpFetcher:
    """Live fetcher: httpx, rate-limited and retried with exponential backoff.

    Politeness is enforced here rather than by the caller so no crawl path can
    skip it: `fetch` sleeps until at least `min_interval` has elapsed since the
    previous request. `httpx` is imported lazily so the package imports without it.
    """

    def __init__(
        self,
        *,
        min_interval: float = 1.1,
        max_attempts: int = 3,
        timeout: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._min_interval = min_interval
        self._max_attempts = max_attempts
        self._timeout = timeout
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_at: float | None = None
        self._client: object | None = None

    def _throttle(self) -> None:
        if self._last_request_at is not None:
            elapsed = self._monotonic() - self._last_request_at
            if elapsed < self._min_interval:
                self._sleep(self._min_interval - elapsed)
        self._last_request_at = self._monotonic()

    def fetch(self, url: str) -> FetchResult:
        import httpx

        if self._client is None:
            self._client = httpx.Client(
                headers=DEFAULT_HEADERS,
                follow_redirects=True,
                timeout=self._timeout,
            )
        client: httpx.Client = self._client  # type: ignore[assignment]

        last_error = "no attempt made"
        for attempt in range(1, self._max_attempts + 1):
            self._throttle()
            try:
                response = client.get(url)
            except Exception as exc:  # noqa: BLE001 - any transport failure is retryable
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code not in RETRY_STATUSES:
                    return FetchResult(
                        requested_url=url,
                        final_url=str(response.url),
                        status_code=response.status_code,
                        content_type=response.headers.get("content-type", ""),
                        body=response.text,
                    )
                last_error = f"HTTP {response.status_code}"

            if attempt < self._max_attempts:
                backoff = (2 ** (attempt - 1)) * self._min_interval
                self._sleep(backoff + random.uniform(0, 0.3))

        return FetchResult(
            requested_url=url,
            final_url=url,
            status_code=0,
            content_type="",
            body="",
            error=f"{last_error} after {self._max_attempts} attempts",
        )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()  # type: ignore[attr-defined]
            self._client = None


@dataclass
class FixtureFetcher:
    """Test double serving saved responses from disk -- no network, ever.

    Keyed on canonical URL. `redirects` models Meta's `/docs/` -> `/documentation/`
    301s so resume, dedupe and alias behaviour can be exercised offline.
    """

    responses: dict[str, FetchResult]
    redirects: dict[str, str] = field(default_factory=dict)
    requested: list[str] = field(default_factory=list)

    def fetch(self, url: str) -> FetchResult:
        self.requested.append(url)
        target = self.redirects.get(url, url)
        result = self.responses.get(target)
        if result is None:
            return FetchResult(
                requested_url=url,
                final_url=target,
                status_code=404,
                content_type="text/html",
                body="<html><title>Page Not Found</title></html>",
            )
        return FetchResult(
            requested_url=url,
            final_url=result.final_url or target,
            status_code=result.status_code,
            content_type=result.content_type,
            body=result.body,
            error=result.error,
        )

    @classmethod
    def from_directory(cls, directory: Path, mapping: dict[str, tuple[str, str]]) -> FixtureFetcher:
        """Build from `{url: (filename, content_type)}` over a fixtures directory."""
        responses: dict[str, FetchResult] = {}
        for url, (filename, content_type) in mapping.items():
            body = (directory / filename).read_text(encoding="utf-8", errors="replace")
            responses[url] = FetchResult(
                requested_url=url,
                final_url=url,
                status_code=200,
                content_type=content_type,
                body=body,
            )
        return cls(responses=responses)

"""HTTP client for the Microsoft Clarity Data Export API.

One endpoint, documented at
https://learn.microsoft.com/en-us/clarity/setup-and-installation/clarity-data-export-api:

    GET https://www.clarity.ms/export-data/api/v1/project-live-insights
        ?numOfDays=<1|2|3>&dimension1=..&dimension2=..&dimension3=..
    Authorization: Bearer <project-scoped JWT from Settings > Data Export>

Contract facts the service leans on (all from the doc above):
- data window is the last 1-3 days only; results are UTC;
- at most three dimensions; response capped at 1,000 rows, no pagination;
- HARD QUOTA of 10 requests per project per day — hence the snapshot cache in 0006
  and the explicit budget in the service. 429 here means the day's quota is gone.

The token is an argument, not a constructor field: the client is a process-wide
singleton serving every tenant, and each tenant brings its own project token.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

import httpx

_ENDPOINT = "https://www.clarity.ms/export-data/api/v1/project-live-insights"
_TIMEOUT_SECONDS = 30.0

# The dimension vocabulary the API accepts (doc section "Dimensions and metrics").
ALLOWED_DIMENSIONS = (
    "Browser",
    "Device",
    "Country/Region",
    "OS",
    "Source",
    "Medium",
    "Campaign",
    "Channel",
    "URL",
)


class ClarityAPIError(Exception):
    """Base for API failures; `status` carries the HTTP code when there was a response."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class ClarityUnauthorized(ClarityAPIError):
    """401/403 — missing, invalid, expired, or under-privileged token."""


class ClarityQuotaExceeded(ClarityAPIError):
    """429 — the project's 10-requests-per-day quota is exhausted until UTC midnight."""


class ClarityBadRequest(ClarityAPIError):
    """400 — invalid parameters (bad numOfDays / unknown dimension)."""


class ClarityClient(Protocol):
    def live_insights(
        self, *, token: str, num_of_days: int, dimensions: Sequence[str]
    ) -> list[dict]: ...


class HttpClarityClient:
    """The real thing. Blocking (httpx sync) — callers already run repository work
    off the event loop, and this call rides the same thread."""

    def __init__(self, *, endpoint: str = _ENDPOINT, timeout: float = _TIMEOUT_SECONDS) -> None:
        self._endpoint = endpoint
        self._timeout = timeout

    def live_insights(
        self, *, token: str, num_of_days: int, dimensions: Sequence[str]
    ) -> list[dict]:
        params: dict[str, str] = {"numOfDays": str(num_of_days)}
        for position, dimension in enumerate(dimensions, start=1):
            params[f"dimension{position}"] = dimension

        try:
            response = httpx.get(
                self._endpoint,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            # Message deliberately names the exception type, never the token.
            raise ClarityAPIError(f"clarity request failed: {type(exc).__name__}") from exc

        if response.status_code in (401, 403):
            raise ClarityUnauthorized("clarity token rejected", status=response.status_code)
        if response.status_code == 429:
            raise ClarityQuotaExceeded("clarity daily quota exhausted", status=429)
        if response.status_code == 400:
            raise ClarityBadRequest("clarity rejected the parameters", status=400)
        if response.status_code != 200:
            raise ClarityAPIError(
                f"clarity answered {response.status_code}", status=response.status_code
            )

        body = response.json()
        if not isinstance(body, list):
            raise ClarityAPIError("clarity response was not the documented list shape")
        return body

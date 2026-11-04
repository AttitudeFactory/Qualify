"""Marketing API boundary, independent of organic Graph version and credentials.

Clients arrive authenticated from CredentialResolver. No retries: a failed write
may have succeeded remotely; reconciliation belongs to m-24828974.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx

from qualify_api.ads.errors import (
    READ_ERROR_MESSAGE,
    UNKNOWN_WRITE_MESSAGE,
    MarketingError,
    platform_error,
)
from qualify_api.connections.resolver import AuthenticatedClient

Payload = Mapping[str, Any]
Resource = Literal["campaigns", "adsets", "adcreatives", "ads"]
RESOURCES = frozenset({"campaigns", "adsets", "adcreatives", "ads"})


@dataclass(frozen=True)
class MarketingSettings:
    api_version: str = "v26.0"

    def __post_init__(self) -> None:
        if not re.fullmatch(r"v[1-9][0-9]*\.0", self.api_version):
            raise ValueError("invalid QUALIFY_META_ADS_API_VERSION")

    @property
    def graph_url(self) -> str:
        return f"https://graph.facebook.com/{self.api_version}"

    @classmethod
    def from_env(cls) -> MarketingSettings:
        return cls(api_version=os.environ.get("QUALIFY_META_ADS_API_VERSION", "v26.0"))


@dataclass(frozen=True)
class MarketingPage:
    """One page; only the after cursor travels, never Meta's token-bearing next URL."""

    data: tuple[dict[str, Any], ...]
    after: str | None = None


class MarketingAPI(Protocol):
    async def create(self, resource: Resource, *, params: Payload) -> str: ...
    async def list(self, resource: Resource, *, params: Payload | None = None) -> MarketingPage: ...
    async def update(
        self,
        object_id: str,
        *,
        params: Payload,
        before_write: Callable[[], None] | None = None,
    ) -> None: ...
    async def status(self, object_id: str) -> dict[str, Any]: ...
    async def adpreviews(self, ad_id: str, *, params: Payload) -> MarketingPage: ...
    async def minimum_budgets(self, *, params: Payload | None = None) -> MarketingPage: ...
    async def reachestimate(self, *, targeting_spec: Payload) -> MarketingPage: ...
    async def search_locations(self, *, query: str) -> MarketingPage: ...
    async def search_interests(self, *, query: str) -> MarketingPage: ...
    async def targetingsearch(self, *, params: Payload) -> MarketingPage: ...
    async def insights(
        self, object_id: str | None = None, *, params: Payload | None = None
    ) -> MarketingPage: ...


def _id(value: str) -> str:
    if not re.fullmatch(r"[0-9]+", value):
        raise ValueError("expected a numeric Meta object id")
    return value


def _validate(params: Payload) -> None:
    keys: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if not isinstance(key, str):
                    raise ValueError("parameter names must be strings")
                if key.lower() in {"access_token", "appsecret_proof", "authorization"}:
                    raise ValueError("credentials must come from CredentialResolver")
                keys.add(key)
                visit(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                visit(child)
        elif isinstance(value, str) and value.lstrip().startswith(("{", "[")):
            try:
                decoded = json.loads(value)
            except ValueError:
                return
            visit(decoded)

    visit(params)
    if {"instagram_user_id", "instagram_actor_id"} <= keys:
        raise ValueError("use only one Instagram identity field")


def _encode(params: Payload) -> dict[str, str]:
    _validate(params)
    return {
        key: json.dumps(value, separators=(",", ":"))
        if isinstance(value, (dict, list, tuple, bool))
        else str(value)
        for key, value in params.items()
        if value is not None
    }


def _seconds(value: Any) -> float:
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return 0.0
    return number if math.isfinite(number) and number > 0 else 0.0


def cooldown_seconds(headers: Mapping[str, str], *, status: int) -> float:
    """BUC estimates are minutes; ad-account reset duration is seconds.

    90% / 60s is our conservative policy, not a Meta quota guarantee.
    """
    delay = _seconds(headers.get("retry-after"))
    for header in ("x-business-use-case-usage", "x-business-use-case", "x-ad-account-usage"):
        try:
            value = json.loads(headers.get(header, "{}"))
        except (ValueError, TypeError):
            continue

        def walk(item: Any) -> None:
            nonlocal delay
            if isinstance(item, dict):
                delay = max(delay, _seconds(item.get("estimated_time_to_regain_access")) * 60)
                usage = max(
                    (
                        _seconds(item.get(k))
                        for k in ("call_count", "total_cputime", "total_time", "acc_id_util_pct")
                    ),
                    default=0,
                )
                if usage >= 90:
                    delay = max(delay, _seconds(item.get("reset_time_duration")), 60)
                for child in item.values():
                    walk(child)
            elif isinstance(item, list):
                for child in item:
                    walk(child)

        walk(value)
    return max(delay, 60 if status == 429 else 0)


def _page(payload: dict[str, Any]) -> MarketingPage:
    rows = payload.get("data")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise MarketingError(READ_ERROR_MESSAGE)
    paging = payload.get("paging", {})
    cursors = paging.get("cursors", {}) if isinstance(paging, dict) else {}
    after = cursors.get("after") if isinstance(cursors, dict) else None
    # An after cursor can exist on the last page. Expose it only with a next page.
    after = after if isinstance(after, str) and paging.get("next") else None
    return MarketingPage(tuple(dict(row) for row in rows), after)


class MarketingClient:
    """One authenticated account per instance; caller owns the client's lifetime.

    No connection selection, approval, or persistence happens here. Callers must
    authorize account ownership and spending before invoking write methods.
    """

    def __init__(
        self,
        *,
        client: AuthenticatedClient,
        account_id: str,
        settings: MarketingSettings | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._account = "act_" + _id(account_id.removeprefix("act_"))
        self._settings = settings or MarketingSettings.from_env()
        self._sleep = sleep
        self._clock = monotonic
        self._not_before = 0.0
        self._lock = asyncio.Lock()

    async def _request(
        self,
        method: str,
        path: str,
        params: Payload,
        *,
        before_write: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        encoded = _encode(params)
        async with self._lock:
            while (wait := self._not_before - self._clock()) > 0:
                await self._sleep(wait)
            # Consent/membership may expire while waiting for this account's
            # cooldown or lock. The callback is local, synchronous and never encoded.
            if before_write is not None:
                before_write()
            # Catch without retaining or chaining transport exceptions, which can
            # carry full request URLs/headers. Never log request/response bodies.
            failed = False
            try:
                url = f"{self._settings.graph_url}/{path}"
                if method == "GET":
                    response = await self._client.get(
                        url, params=encoded, timeout=30, follow_redirects=False
                    )
                else:
                    response = await self._client.post(
                        url, data=encoded, timeout=30, follow_redirects=False
                    )
            except httpx.HTTPError:
                failed = True
            if failed:
                raise MarketingError(
                    UNKNOWN_WRITE_MESSAGE if method == "POST" else READ_ERROR_MESSAGE,
                    outcome_unknown=method == "POST",
                )
            delay = cooldown_seconds(response.headers, status=response.status_code)
            self._not_before = self._clock() + delay
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if not isinstance(payload, dict):
                raise MarketingError(
                    UNKNOWN_WRITE_MESSAGE if method == "POST" else READ_ERROR_MESSAGE,
                    http_status=response.status_code,
                    outcome_unknown=method == "POST",
                )
            if not 200 <= response.status_code < 300 or "error" in payload:
                error = platform_error(
                    payload,
                    status=response.status_code,
                    retry_after=delay or None,
                    write=method == "POST",
                )
                if error.code in {17, 613, 80004}:
                    self._not_before = max(self._not_before, self._clock() + 60)
                    error.retry_after = max(error.retry_after or 0, 60)
                if error.subcode == 4841018:
                    self._not_before = max(self._not_before, self._clock() + 30)
                    error.retry_after = max(error.retry_after or 0, 30)
                raise error
            return payload

    async def create(self, resource: Resource, *, params: Payload) -> str:
        if resource not in RESOURCES:
            raise ValueError("unsupported advertising resource")
        payload = await self._request("POST", f"{self._account}/{resource}", params)
        identifier = payload.get("id")
        if not isinstance(identifier, str) or not identifier.isdigit():
            raise MarketingError(
                UNKNOWN_WRITE_MESSAGE,
                outcome_unknown=True,
            )
        return identifier

    async def list(self, resource: Resource, *, params: Payload | None = None) -> MarketingPage:
        if resource not in RESOURCES:
            raise ValueError("unsupported advertising resource")
        return _page(await self._request("GET", f"{self._account}/{resource}", params or {}))

    async def update(
        self,
        object_id: str,
        *,
        params: Payload,
        before_write: Callable[[], None] | None = None,
    ) -> None:
        # Preserve the existing unguarded contract for callers/subclass doubles.
        if before_write is None:
            payload = await self._request("POST", _id(object_id), params)
        else:
            payload = await self._request("POST", _id(object_id), params, before_write=before_write)
        if payload.get("success") is not True:
            raise MarketingError(
                UNKNOWN_WRITE_MESSAGE,
                outcome_unknown=True,
            )

    async def status(self, object_id: str) -> dict[str, Any]:
        return await self._request(
            "GET",
            _id(object_id),
            {"fields": "id,status,effective_status,issues_info"},
        )

    async def adpreviews(self, ad_id: str, *, params: Payload) -> MarketingPage:
        return _page(await self._request("GET", f"{_id(ad_id)}/previews", params))

    async def minimum_budgets(self, *, params: Payload | None = None) -> MarketingPage:
        return _page(await self._request("GET", f"{self._account}/minimum_budgets", params or {}))

    async def reachestimate(self, *, targeting_spec: Payload) -> MarketingPage:
        return _page(
            await self._request(
                "GET", f"{self._account}/reachestimate", {"targeting_spec": dict(targeting_spec)}
            )
        )

    async def search_locations(self, *, query: str) -> MarketingPage:
        return _page(await self._request("GET", "search", {"type": "adgeolocation", "q": query}))

    async def search_interests(self, *, query: str) -> MarketingPage:
        return _page(await self._request("GET", "search", {"type": "adinterest", "q": query}))

    async def targetingsearch(self, *, params: Payload) -> MarketingPage:
        return _page(await self._request("GET", f"{self._account}/targetingsearch", params))

    async def insights(
        self, object_id: str | None = None, *, params: Payload | None = None
    ) -> MarketingPage:
        node = _id(object_id) if object_id is not None else self._account
        return _page(await self._request("GET", f"{node}/insights", params or {}))

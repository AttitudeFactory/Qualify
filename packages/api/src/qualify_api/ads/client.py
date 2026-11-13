"""Marketing API boundary, independent of organic Graph version and credentials.

Clients arrive authenticated from CredentialResolver. No retries: a failed write
may have succeeded remotely; reconciliation belongs to m-24828974.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import math
import os
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import IO, Any, Literal, Protocol

import httpx

from qualify_api.ads.errors import (
    READ_ERROR_MESSAGE,
    UNKNOWN_WRITE_MESSAGE,
    MarketingError,
    platform_error,
)
from qualify_api.connections.resolver import AuthenticatedClient

Payload = Mapping[str, Any]
BeforeWrite = Callable[[], Awaitable[None] | None]
Resource = Literal["campaigns", "adsets", "adcreatives", "ads"]
RESOURCES = frozenset({"campaigns", "adsets", "adcreatives", "ads"})
VIDEO_CHUNK_BYTES = 16 * 1024 * 1024  # local ceiling on the window Meta may ask for


@dataclass(frozen=True)
class MarketingSettings:
    api_version: str = "v26.0"

    def __post_init__(self) -> None:
        if not re.fullmatch(r"v[1-9][0-9]*\.0", self.api_version):
            raise ValueError("invalid QUALIFY_META_ADS_API_VERSION")

    @property
    def graph_url(self) -> str:
        return f"https://graph.facebook.com/{self.api_version}"

    @property
    def video_url(self) -> str:
        # The official SDK's VideoUploader posts advideos to graph-video (FacebookSession).
        return f"https://graph-video.facebook.com/{self.api_version}"

    @classmethod
    def from_env(cls) -> MarketingSettings:
        return cls(api_version=os.environ.get("QUALIFY_META_ADS_API_VERSION", "v26.0"))


@dataclass(frozen=True)
class MarketingPage:
    """One page; only the after cursor travels, never Meta's token-bearing next URL."""

    data: tuple[dict[str, Any], ...]
    after: str | None = None


class MarketingAPI(Protocol):
    async def delivery(self, ad_id: str) -> dict[str, Any]: ...
    async def create(
        self, resource: Resource, *, params: Payload, before_write: BeforeWrite | None = None
    ) -> str: ...
    async def validate(self, resource: Resource, *, params: Payload) -> None: ...
    async def read_object(self, object_id: str, *, fields: str) -> dict[str, Any]: ...
    async def list(self, resource: Resource, *, params: Payload | None = None) -> MarketingPage: ...
    async def update(
        self,
        object_id: str,
        *,
        params: Payload,
        before_write: BeforeWrite | None = None,
    ) -> None: ...
    async def status(self, object_id: str) -> dict[str, Any]: ...
    async def adpreviews(self, ad_id: str, *, params: Payload) -> MarketingPage: ...
    async def minimum_budgets(self, *, params: Payload | None = None) -> MarketingPage: ...
    async def reachestimate(self, *, targeting_spec: Payload) -> MarketingPage: ...
    async def search_locations(self, *, query: str) -> MarketingPage: ...
    async def search_interests(self, *, query: str) -> MarketingPage: ...
    async def targetingsearch(self, *, params: Payload) -> MarketingPage: ...
    async def audience_search(self, *, params: Payload) -> MarketingPage: ...
    async def audience_validation(self, *, interest_ids: tuple[str, ...]) -> MarketingPage: ...
    async def insights(
        self, object_id: str | None = None, *, params: Payload | None = None
    ) -> MarketingPage: ...


def _id(value: str) -> str:
    if not re.fullmatch(r"[0-9]+", value):
        raise ValueError("expected a numeric Meta object id")
    return value


def _offset(value: Any) -> int:
    # Meta sends upload offsets as decimal strings.
    if type(value) is int and value >= 0:
        return value
    if not isinstance(value, str) or not value.isdigit():
        raise ValueError("invalid upload offset")
    return int(value)


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
        before_write: BeforeWrite | None = None,
        files: Mapping[str, Any] | None = None,
        base: str | None = None,
    ) -> dict[str, Any]:
        encoded = _encode(params)
        async with self._lock:
            while (wait := self._not_before - self._clock()) > 0:
                await self._sleep(wait)
            # Consent/membership may expire while waiting for this account's
            # cooldown or lock. The callback is local, synchronous and never encoded.
            if before_write is not None:
                checked = before_write()
                if inspect.isawaitable(checked):
                    await checked
            # Catch without retaining or chaining transport exceptions, which can
            # carry full request URLs/headers. Never log request/response bodies.
            failed = False
            try:
                url = f"{base or self._settings.graph_url}/{path}"
                if method == "GET":
                    response = await self._client.get(
                        url, params=encoded, timeout=30, follow_redirects=False
                    )
                else:
                    response = await self._client.post(
                        url, data=encoded, files=files, timeout=30, follow_redirects=False
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

    async def create(
        self, resource: Resource, *, params: Payload, before_write: BeforeWrite | None = None
    ) -> str:
        if resource not in RESOURCES:
            raise ValueError("unsupported advertising resource")
        if before_write is None:
            payload = await self._request("POST", f"{self._account}/{resource}", params)
        else:
            payload = await self._request(
                "POST", f"{self._account}/{resource}", params, before_write=before_write
            )
        identifier = payload.get("id")
        if not isinstance(identifier, str) or not identifier.isdigit():
            raise MarketingError(
                UNKNOWN_WRITE_MESSAGE,
                outcome_unknown=True,
            )
        return identifier

    async def upload_image(self, data: bytes, *, before_write: BeforeWrite) -> str:
        """Bounded ad-account image upload, no URL, automatic retry or numeric-ID assumption."""
        import base64

        from qualify_api.ads.unpublished import MAX_IMAGE_BYTES

        if not isinstance(data, bytes) or not 0 < len(data) <= MAX_IMAGE_BYTES:
            raise ValueError("invalid advertising image size")
        payload = await self._request(
            "POST",
            f"{self._account}/adimages",
            {"bytes": base64.b64encode(data).decode("ascii")},
            before_write=before_write,
        )
        images = payload.get("images")
        rows = list(images.values()) if isinstance(images, dict) else []
        value = rows[0].get("hash") if len(rows) == 1 and isinstance(rows[0], dict) else None
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
            raise MarketingError(UNKNOWN_WRITE_MESSAGE, outcome_unknown=True)
        return value

    async def upload_video(
        self,
        stream: IO[bytes],
        size: int,
        *,
        before_write: BeforeWrite,
        started: Callable[[str], None],
    ) -> str:
        """Chunked `advideos` upload (start → transfer → finish), one chunk in memory at a time.

        `started(video_id)` runs as soon as Meta names the video, before any byte is sent, so
        the caller can persist it. Every failure after `start` is an unknown outcome: the
        caller must never send the file again on its own.
        """
        from qualify_api.ads.unpublished import MAX_VIDEO_BYTES

        if type(size) is not int or not 0 < size <= MAX_VIDEO_BYTES:
            raise ValueError("invalid advertising video size")
        path, base = f"{self._account}/advideos", self._settings.video_url
        answer = await self._request(
            "POST",
            path,
            {"upload_phase": "start", "file_size": size},
            before_write=before_write,
            base=base,
        )
        video, session = answer.get("video_id"), answer.get("upload_session_id")
        if not isinstance(video, str) or not video.isdigit() or not isinstance(session, str):
            raise MarketingError(UNKNOWN_WRITE_MESSAGE, outcome_unknown=True)
        started(video)
        try:
            sent = 0
            while True:
                low, high = (_offset(answer.get(key)) for key in ("start_offset", "end_offset"))
                if low == high == sent == size:
                    break
                if low != sent or not low < high <= size or high - low > VIDEO_CHUNK_BYTES:
                    raise ValueError("unexpected upload window")
                chunk = stream.read(high - low)
                if len(chunk) != high - low:
                    raise ValueError("short read")
                answer = await self._request(
                    "POST",
                    path,
                    {"upload_phase": "transfer", "upload_session_id": session, "start_offset": low},
                    files={"video_file_chunk": ("chunk", chunk, "application/octet-stream")},
                    base=base,
                )
                sent = high
            done = await self._request(
                "POST", path, {"upload_phase": "finish", "upload_session_id": session}, base=base
            )
            if done.get("success") is not True:
                raise ValueError("finish not confirmed")
        except (MarketingError, ValueError, OSError):
            raise MarketingError(UNKNOWN_WRITE_MESSAGE, outcome_unknown=True) from None
        return video

    async def video_status(self, video_id: str) -> str:
        """One bounded read: `ready`, `processing` or `error` (expired counts as error)."""
        payload = await self._request("GET", _id(video_id), {"fields": "id,status"})
        status = payload.get("status")
        value = status.get("video_status") if isinstance(status, dict) else None
        if payload.get("id") != video_id or value not in {
            "ready",
            "processing",
            "error",
            "expired",
        }:
            raise MarketingError(READ_ERROR_MESSAGE)
        return "error" if value == "expired" else value

    async def validate(self, resource: Resource, *, params: Payload) -> None:
        """Meta validate_only never substitutes for a create expecting a remote ID."""
        if resource not in RESOURCES or "execution_options" in params:
            raise ValueError("unsupported advertising validation")
        result = await self._request(
            "POST",
            f"{self._account}/{resource}",
            {**params, "execution_options": ["validate_only"]},
        )
        if result.get("success") is not True or "id" in result:
            raise MarketingError("Meta no confirmó la validación de esta configuración.")

    async def read_object(self, object_id: str, *, fields: str) -> dict[str, Any]:
        return await self._request("GET", _id(object_id), {"fields": fields})

    async def validate_update(self, object_id: str, *, params: Payload) -> None:
        """Ad/AdSet/Campaign api_update support validate_only in the primary Meta SDK."""
        if "execution_options" in params:
            raise ValueError("caller cannot override advertising validation mode")
        result = await self._request(
            "POST", _id(object_id), {**params, "execution_options": ["validate_only"]}
        )
        if result.get("success") is not True or "id" in result:
            raise MarketingError("Meta no confirmó la validación de este cambio.")

    async def read_account(self, *, fields: str) -> dict[str, Any]:
        return await self._request("GET", self._account, {"fields": fields})

    async def children(self, object_id: str, *, resource: str) -> tuple[dict[str, Any], ...]:
        """A parent may activate only its sole approved child; pagination is uncertainty."""
        if resource not in {"ads", "adsets"}:
            raise ValueError("unsupported advertising child edge")
        payload = await self._request(
            "GET", f"{_id(object_id)}/{resource}", {"fields": "id", "limit": 2}
        )
        paging = payload.get("paging", {})
        if not isinstance(paging, dict) or "next" in paging:
            raise MarketingError("No pudimos comprobar todos los anuncios de esta campaña.")
        return _page(payload).data

    async def aclose(self) -> None:
        if hasattr(self._client, "aclose"):
            await self._client.aclose()

    async def list(self, resource: Resource, *, params: Payload | None = None) -> MarketingPage:
        if resource not in RESOURCES:
            raise ValueError("unsupported advertising resource")
        return _page(await self._request("GET", f"{self._account}/{resource}", params or {}))

    async def update(
        self,
        object_id: str,
        *,
        params: Payload,
        before_write: BeforeWrite | None = None,
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

    async def delivery(self, ad_id: str) -> dict[str, Any]:
        """Ad-specific fields; the caller verifies account and parent ownership."""
        return await self._request(
            "GET",
            _id(ad_id),
            {
                "fields": (
                    "id,account_id,campaign_id,adset_id,status,effective_status,"
                    "ad_review_feedback,issues_info"
                )
            },
        )

    async def subscribed_apps(self) -> MarketingPage:
        """Apps subscribed to this ad account's webhooks (`app_id`, `app_name`)."""
        return _page(
            await self._request(
                "GET", f"{self._account}/subscribed_apps", {"fields": "app_id", "limit": 100}
            )
        )

    async def subscribe_app(self, app_id: str, *, before_write: BeforeWrite) -> None:
        """One explicit POST, never retried: an ambiguous answer is reported, not resent."""
        payload = await self._request(
            "POST",
            f"{self._account}/subscribed_apps",
            {"app_id": _id(app_id)},
            before_write=before_write,
        )
        if payload.get("success") is not True:
            raise MarketingError(UNKNOWN_WRITE_MESSAGE, outcome_unknown=True)

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

    async def audience_search(self, *, params: Payload) -> MarketingPage:
        if params.get("type") not in {"adgeolocation", "adinterest", "adinterestsuggestion"}:
            raise ValueError("unsupported audience search")
        return _page(await self._request("GET", "search", params))

    async def audience_validation(self, *, interest_ids: tuple[str, ...]) -> MarketingPage:
        return _page(
            await self._request(
                "GET",
                f"{self._account}/targetingvalidation",
                {"id_list": [_id(i) for i in interest_ids]},
            )
        )

    async def insights(
        self, object_id: str | None = None, *, params: Payload | None = None
    ) -> MarketingPage:
        node = _id(object_id) if object_id is not None else self._account
        return _page(await self._request("GET", f"{node}/insights", params or {}))

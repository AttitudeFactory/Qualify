"""Ephemeral Pinterest v5 reads. No caching, media downloads, or generation.

Contract: pinterest/api-description, v5/openapi.yaml (5.28.0).
Callers must supply credentials resolved for their authenticated tenant; this client
never reads a platform token from the environment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

import httpx

READ_SCOPES = ("boards:read", "pins:read")
PROFILE_SCOPE = "user_accounts:read"


class PinterestError(Exception):
    """Sanitized failure: no response body, request, credentials, or vendor message."""

    def __init__(self, kind: str, status: int | None = None) -> None:
        self.kind = kind
        self.status = status
        super().__init__(f"Pinterest: {kind}" + (f" ({status})" if status else ""))


@dataclass(frozen=True)
class Board:
    id: str
    name: str


@dataclass(frozen=True)
class Image:
    variant: str
    url: str


@dataclass(frozen=True)
class Pin:
    id: str
    title: str = ""
    media_type: str = ""
    images: tuple[Image, ...] = ()

    @property
    def url(self) -> str:
        return f"https://www.pinterest.com/pin/{self.id}/"


@dataclass(frozen=True)
class Profile:
    username: str


@dataclass(frozen=True)
class Page[T]:
    items: tuple[T, ...]
    bookmark: str | None = None


class PinterestReader(Protocol):
    def boards(self, *, page_size: int = 25, bookmark: str | None = None) -> Page[Board]: ...

    def pins(
        self, board_id: str, *, page_size: int = 25, bookmark: str | None = None
    ) -> Page[Pin]: ...

    def profile(self) -> Profile: ...


def _id(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]+", value) is None:
        raise ValueError("Pinterest ID must contain ASCII digits")
    return value


def _params(page_size: int, bookmark: str | None) -> dict[str, str | int]:
    if type(page_size) is not int or not 1 <= page_size <= 250:
        raise ValueError("Pinterest page size must be between 1 and 250")
    params: dict[str, str | int] = {"page_size": page_size}
    if bookmark is not None:
        if not isinstance(bookmark, str) or not bookmark or len(bookmark) > 4096:
            raise ValueError("Invalid Pinterest bookmark")
        if any(ord(char) < 32 or ord(char) == 127 for char in bookmark):
            raise ValueError("Invalid Pinterest bookmark")
        params["bookmark"] = bookmark
    return params


def _text(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("Expected Pinterest text")
    return value


def _pin(row: dict[str, object]) -> Pin:
    media = row.get("media")
    if media is None:
        media = {}
    if not isinstance(media, dict):
        raise ValueError("Invalid Pinterest media")
    images = media.get("images")
    if images is None:
        images = {}
    if not isinstance(images, dict):
        raise ValueError("Invalid Pinterest images")
    variants: list[Image] = []
    for key, item in images.items():
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not isinstance(url, str):
            continue
        try:
            parsed = urlsplit(url)
            usable = parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username
        except ValueError:
            usable = False
        if usable:
            variants.append(Image(str(key), url))
    return Pin(
        _id(row.get("id")), _text(row.get("title")), _text(media.get("media_type")), tuple(variants)
    )


class PinterestClient:
    """One credential per instance, one request per call; caller owns tenant isolation."""

    def __init__(self, access_token: str, *, transport: httpx.BaseTransport | None = None) -> None:
        if not isinstance(access_token, str) or not access_token.strip():
            raise ValueError("Pinterest access token required")
        if any(ord(char) < 33 or ord(char) > 126 for char in access_token):
            raise ValueError("Invalid Pinterest access token")
        self._token = access_token
        self._transport = transport

    def _get(self, path: str, params: dict[str, str | int] | None = None) -> dict[str, object]:
        # A fixed origin and disabled redirects prevent credential forwarding elsewhere.
        failed = False
        try:
            with httpx.Client(
                transport=self._transport, timeout=20, follow_redirects=False
            ) as client:
                response = client.get(
                    "https://api.pinterest.com/v5" + path,
                    params=params,
                    headers={"Authorization": f"Bearer {self._token}"},
                )
        except httpx.HTTPError:
            failed = True
        # Raise outside the except suite: even exception context cannot expose a request.
        if failed:
            raise PinterestError("unavailable")
        if response.status_code != 200:
            kind = {
                401: "authentication",
                403: "permission",
                404: "not_found",
                429: "rate_limit",
            }.get(response.status_code, "unavailable" if response.status_code >= 500 else "request")
            raise PinterestError(kind, response.status_code)
        try:
            data = response.json()
        except ValueError:
            data = None
        if not isinstance(data, dict):
            raise PinterestError("invalid_response")
        return data

    def _page(self, path: str, *, page_size: int, bookmark: str | None, pins: bool) -> Page:
        data = self._get(path, _params(page_size, bookmark))
        failed = False
        try:
            rows = data["items"]
            cursor = data.get("bookmark")
            if not isinstance(rows, list) or (cursor is not None and not isinstance(cursor, str)):
                raise ValueError("Invalid page")
            if cursor:
                _params(page_size, cursor)
            items = []
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError("Invalid item")
                items.append(
                    _pin(row) if pins else Board(_id(row.get("id")), _text(row.get("name")))
                )
        except (KeyError, ValueError, TypeError):
            failed = True
        if failed:
            raise PinterestError("invalid_response")
        return Page(tuple(items), cursor or None)

    def boards(self, *, page_size: int = 25, bookmark: str | None = None) -> Page[Board]:
        return self._page("/boards", page_size=page_size, bookmark=bookmark, pins=False)

    def pins(self, board_id: str, *, page_size: int = 25, bookmark: str | None = None) -> Page[Pin]:
        return self._page(
            f"/boards/{_id(board_id)}/pins", page_size=page_size, bookmark=bookmark, pins=True
        )

    def profile(self) -> Profile:
        username = self._get("/user_account").get("username")
        if not isinstance(username, str) or not username:
            raise PinterestError("invalid_response")
        return Profile(username)


class FakePinterestClient:
    """Per-instance fixtures; opaque cursors are valid only on their resource."""

    def __init__(
        self,
        *,
        boards: tuple[Board, ...] = (),
        pins: dict[str, tuple[Pin, ...]] | None = None,
        profile: Profile = Profile("fixture"),
    ) -> None:
        self._boards = tuple(boards)
        self._pins = dict(pins or {})
        self._profile = profile
        self._cursors: dict[str, tuple[str, int]] = {}

    def _page[T](
        self, resource: str, items: tuple[T, ...], page_size: int, bookmark: str | None
    ) -> Page[T]:
        _params(page_size, bookmark)
        start = 0
        if bookmark is not None:
            held = self._cursors.get(bookmark)
            if held is None or held[0] != resource:
                raise PinterestError("request", 400)
            start = held[1]
        end = start + page_size
        cursor = None
        if end < len(items):
            from uuid import uuid4

            cursor = uuid4().hex
            self._cursors[cursor] = (resource, end)
        return Page(items[start:end], cursor)

    def boards(self, *, page_size: int = 25, bookmark: str | None = None) -> Page[Board]:
        return self._page("boards", self._boards, page_size, bookmark)

    def pins(self, board_id: str, *, page_size: int = 25, bookmark: str | None = None) -> Page[Pin]:
        key = _id(board_id)
        _params(page_size, bookmark)
        if key not in {board.id for board in self._boards}:
            raise PinterestError("not_found", 404)
        return self._page(f"pins:{key}", self._pins.get(key, ()), page_size, bookmark)

    def profile(self) -> Profile:
        return self._profile

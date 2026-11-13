"""Pinterest Authorization Code/continuous-refresh boundary; no vendor error echo."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlencode

import httpx

from qualify_api.pinterest.client import PROFILE_SCOPE, READ_SCOPES, PinterestError
from qualify_api.pinterest.settings import PinterestSettings


@dataclass(frozen=True)
class Tokens:
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    access_expires_at: datetime
    refresh_expires_at: datetime
    scopes: tuple[str, ...]

    def to_blob(self) -> str:
        return json.dumps(
            {
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "access_expires_at": self.access_expires_at.isoformat(),
                "refresh_expires_at": self.refresh_expires_at.isoformat(),
                "scopes": self.scopes,
            }
        )

    @classmethod
    def from_blob(cls, blob: str) -> Tokens:
        raw = json.loads(blob)
        return cls(
            raw["access_token"],
            raw["refresh_token"],
            datetime.fromisoformat(raw["access_expires_at"]),
            datetime.fromisoformat(raw["refresh_expires_at"]),
            tuple(raw["scopes"]),
        )


class OAuthClient(Protocol):
    def authorization_url(self, state: str) -> str: ...
    def exchange(self, code: str) -> Tokens: ...
    def refresh(self, refresh_token: str) -> Tokens: ...


class HttpOAuthClient:
    def __init__(
        self, settings: PinterestSettings, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        self._settings = settings
        self._transport = transport

    def authorization_url(self, state: str) -> str:
        return "https://www.pinterest.com/oauth/?" + urlencode(
            {
                "client_id": self._settings.client_id,
                "redirect_uri": self._settings.redirect_uri,
                "response_type": "code",
                "scope": ",".join((*READ_SCOPES, PROFILE_SCOPE)),
                "state": state,
            }
        )

    def exchange(self, code: str) -> Tokens:
        if not code or len(code) > 4096:
            raise PinterestError("authentication")
        return self._request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._settings.redirect_uri,
            }
        )

    def refresh(self, refresh_token: str) -> Tokens:
        return self._request({"grant_type": "refresh_token", "refresh_token": refresh_token})

    def _request(self, data: dict[str, str]) -> Tokens:
        failed = False
        try:
            with httpx.Client(
                transport=self._transport, timeout=20, follow_redirects=False
            ) as client:
                response = client.post(
                    "https://api.pinterest.com/v5/oauth/token",
                    data=data,
                    auth=httpx.BasicAuth(self._settings.client_id, self._settings.client_secret),
                )
        except httpx.HTTPError:
            failed = True
        if failed:
            raise PinterestError("unavailable")
        if response.status_code not in (200, 201):
            raise PinterestError(
                "authentication" if response.status_code in (400, 401, 403) else "unavailable",
                response.status_code,
            )
        tokens = None
        try:
            raw = response.json()
            now = datetime.now(UTC)
            access = raw["access_token"]
            refresh = raw["refresh_token"]
            ttl, refresh_ttl = raw["expires_in"], raw["refresh_token_expires_in"]
            scope = raw["scope"]
            if (
                not isinstance(access, str)
                or not access
                or not isinstance(refresh, str)
                or not refresh
                or type(ttl) is not int
                or type(refresh_ttl) is not int
                or min(ttl, refresh_ttl) <= 0
                or not isinstance(scope, str)
                or raw.get("token_type", "bearer").lower() != "bearer"
            ):
                raise ValueError("Invalid token response")
            tokens = Tokens(
                access,
                refresh,
                now + timedelta(seconds=ttl),
                now + timedelta(seconds=refresh_ttl),
                tuple(scope.replace(",", " ").split()),
            )
        except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
            pass
        if tokens is None:
            raise PinterestError("invalid_response")
        if not set((*READ_SCOPES, PROFILE_SCOPE)).issubset(tokens.scopes):
            raise PinterestError("permission", 403)
        return tokens

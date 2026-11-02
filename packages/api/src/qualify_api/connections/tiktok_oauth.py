"""The TikTok platform seam for the connect flow (m-24921091): Login Kit OAuth v2.

Same shape as `meta_oauth.py`: a `Protocol` the service depends on, a real httpx
implementation, one `_parse_*` function per endpoint marked `[V]` (the JSON shapes are read
from TikTok's public docs and not yet observed against a live app), and a fake in the tests.

## Flow

1. `authorization_url` — `https://www.tiktok.com/v2/auth/authorize/` with `client_key`,
   comma-separated `scope`, `state` and PKCE (`code_challenge` + `S256`). `[V]` TikTok's
   challenge is the HEX sha256 of the verifier (not base64url as in RFC 7636).
2. `exchange_code` — `POST /v2/oauth/token/` (form body) with the `code_verifier`.
3. `refresh` — same endpoint, `grant_type=refresh_token`. TikTok may ROTATE the refresh
   token on refresh: the response's `refresh_token` always replaces the stored one.
4. `fetch_user` — `GET /v2/user/info/` (scope `user.info.basic`) to name the account.
5. `revoke` — `POST /v2/oauth/revoke/` (best effort, on disconnect).

## Token discipline

Same as Meta: tokens never in a log, a repr or an exception message. Errors carry the HTTP
status and TikTok's error CODE (e.g. `invalid_grant`), never the body.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx

from qualify_api.config import TikTokSettings


class TikTokOAuthError(Exception):
    """A TikTok auth call failed. `code` is TikTok's error code (`invalid_grant`, …) when the
    response carried one; the message never carries a token or the raw body."""

    def __init__(self, message: str, *, code: str | None = None, http_status: int | None = None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status

    @property
    def is_permanent_auth_failure(self) -> bool:
        """The refresh token is dead (revoked, expired, rotated away): reconnect needed."""
        return self.code in {"invalid_grant", "invalid_refresh_token", "access_token_invalid"}


@dataclass(frozen=True)
class TikTokTokens:
    """What one token call yields. Persisted ONLY as an encrypted blob (`to_blob`)."""

    access_token: str
    refresh_token: str
    open_id: str
    access_expires_at: datetime
    refresh_expires_at: datetime
    scopes: tuple[str, ...]

    def __repr__(self) -> str:
        return f"<TikTokTokens open_id={self.open_id!r} tokens=redacted>"

    def to_blob(self) -> str:
        """The plaintext that `Encryptor.encrypt` seals into `oauth_credentials.ciphertext`.
        Expiries ride inside because `qualify_credential` can read only ciphertext/key_id."""
        return json.dumps(
            {
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "open_id": self.open_id,
                "access_expires_at": self.access_expires_at.isoformat(),
                "refresh_expires_at": self.refresh_expires_at.isoformat(),
                "scopes": list(self.scopes),
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_blob(cls, blob: str) -> TikTokTokens:
        raw = json.loads(blob)
        return cls(
            access_token=str(raw["access_token"]),
            refresh_token=str(raw["refresh_token"]),
            open_id=str(raw["open_id"]),
            access_expires_at=datetime.fromisoformat(raw["access_expires_at"]),
            refresh_expires_at=datetime.fromisoformat(raw["refresh_expires_at"]),
            scopes=tuple(raw.get("scopes", ())),
        )


@dataclass(frozen=True)
class TikTokUser:
    open_id: str
    display_name: str | None


class TikTokOAuthClient(Protocol):
    def authorization_url(self, *, state: str, code_challenge: str) -> str: ...

    async def exchange_code(self, *, code: str, code_verifier: str) -> TikTokTokens: ...

    async def refresh(self, refresh_token: str) -> TikTokTokens: ...

    async def fetch_user(self, access_token: str) -> TikTokUser: ...

    async def revoke(self, access_token: str) -> None: ...


# --- PKCE -------------------------------------------------------------------------------


def new_code_verifier() -> str:
    """43-128 chars of the unreserved set (RFC 7636). 64 random bytes -> 86 chars."""
    return base64.urlsafe_b64encode(secrets.token_bytes(64)).decode("ascii").rstrip("=")


def code_challenge_for(verifier: str) -> str:
    """`[V]` TikTok documents the challenge as the hex-encoded SHA-256 of the verifier."""
    return hashlib.sha256(verifier.encode("ascii")).hexdigest()


# --- [V] response parsing ----------------------------------------------------------------


def _error_code(payload: dict[str, Any]) -> str | None:
    """TikTok reports errors two ways: `{"error": "invalid_grant", …}` on the OAuth endpoints
    and `{"error": {"code": "…"}}` on the API endpoints. Only the code is ever surfaced."""
    err = payload.get("error")
    if isinstance(err, str) and err:
        return err
    if isinstance(err, dict):
        code = err.get("code")
        if isinstance(code, str) and code and code != "ok":
            return code
    return None


def parse_token_response(payload: dict[str, Any], *, now: datetime | None = None) -> TikTokTokens:
    """[V] {"access_token","expires_in","open_id","refresh_expires_in","refresh_token",
    "scope": "user.info.basic,video.upload","token_type":"Bearer"}."""
    code = _error_code(payload)
    if code is not None:
        raise TikTokOAuthError(f"token endpoint refused: {code}", code=code)
    access = payload.get("access_token")
    refresh = payload.get("refresh_token")
    open_id = payload.get("open_id")
    if not (isinstance(access, str) and access and isinstance(refresh, str) and refresh):
        raise TikTokOAuthError("token response carried no access/refresh token")
    if not isinstance(open_id, str) or not open_id:
        raise TikTokOAuthError("token response carried no open_id")
    moment = now or datetime.now(UTC)
    expires_in = int(payload.get("expires_in") or 86400)
    refresh_in = int(payload.get("refresh_expires_in") or 365 * 86400)
    scopes = tuple(s.strip() for s in str(payload.get("scope") or "").split(",") if s.strip())
    return TikTokTokens(
        access_token=access,
        refresh_token=refresh,
        open_id=open_id,
        access_expires_at=moment + timedelta(seconds=expires_in),
        refresh_expires_at=moment + timedelta(seconds=refresh_in),
        scopes=scopes,
    )


def parse_user_response(payload: dict[str, Any], *, fallback_open_id: str = "") -> TikTokUser:
    """[V] {"data":{"user":{"open_id","display_name",…}},"error":{"code":"ok",…}}."""
    code = _error_code(payload)
    if code is not None:
        raise TikTokOAuthError(f"user info refused: {code}", code=code)
    data = payload.get("data")
    user = data.get("user") if isinstance(data, dict) else None
    if not isinstance(user, dict):
        raise TikTokOAuthError("user info response carried no user")
    open_id = user.get("open_id") or fallback_open_id
    if not open_id:
        raise TikTokOAuthError("user info response carried no open_id")
    name = user.get("display_name")
    return TikTokUser(open_id=str(open_id), display_name=str(name) if name else None)


class HttpTikTokOAuthClient:
    """Real client. Constructed per use; holds no token between calls."""

    def __init__(
        self, settings: TikTokSettings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings = settings
        self._transport = transport

    def authorization_url(self, *, state: str, code_challenge: str) -> str:
        params = {
            "client_key": self._settings.client_key,
            "scope": ",".join(self._settings.requested_scopes),
            "response_type": "code",
            "redirect_uri": self._settings.redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{self._settings.authorize_url}?{urlencode(params)}"

    async def _post_form(self, path: str, data: dict[str, str]) -> dict[str, Any]:
        async with httpx.AsyncClient(transport=self._transport, timeout=30.0) as client:
            response = await client.post(
                f"{self._settings.api_base_url}{path}",
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        if response.status_code != 200 and _error_code(payload) is None:
            # Status only: the body of a failed auth call can echo credentials.
            raise TikTokOAuthError(
                f"POST {path} failed with HTTP {response.status_code}",
                http_status=response.status_code,
            )
        return payload

    async def exchange_code(self, *, code: str, code_verifier: str) -> TikTokTokens:
        return parse_token_response(
            await self._post_form(
                "/v2/oauth/token/",
                {
                    "client_key": self._settings.client_key,
                    "client_secret": self._settings.client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                    "redirect_uri": self._settings.redirect_uri,
                    "code_verifier": code_verifier,
                },
            )
        )

    async def refresh(self, refresh_token: str) -> TikTokTokens:
        return parse_token_response(
            await self._post_form(
                "/v2/oauth/token/",
                {
                    "client_key": self._settings.client_key,
                    "client_secret": self._settings.client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
            )
        )

    async def fetch_user(self, access_token: str) -> TikTokUser:
        async with httpx.AsyncClient(transport=self._transport, timeout=30.0) as client:
            response = await client.get(
                f"{self._settings.api_base_url}/v2/user/info/",
                params={"fields": "open_id,display_name"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if not isinstance(payload, dict) or (
            response.status_code != 200 and _error_code(payload) is None
        ):
            raise TikTokOAuthError(
                f"GET /v2/user/info/ failed with HTTP {response.status_code}",
                http_status=response.status_code,
            )
        return parse_user_response(payload)

    async def revoke(self, access_token: str) -> None:
        await self._post_form(
            "/v2/oauth/revoke/",
            {
                "client_key": self._settings.client_key,
                "client_secret": self._settings.client_secret,
                "token": access_token,
            },
        )

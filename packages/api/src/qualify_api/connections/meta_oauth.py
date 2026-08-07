"""The Meta platform seam for the connect flow (C-04).

`MetaOAuthClient` is the Protocol the service depends on; `HttpMetaOAuthClient` is the
real implementation and the tests use a fake. That split is what makes the whole callback
testable with zero network — the acceptance criterion is "suite offline, cero red en CI".

## What is `[V]` here and what is not

The STRUCTURE (exchange a code, enumerate Pages, read granted permissions, verify
identity) is settled by ADR 25 and R4. The concrete JSON field paths are NOT verified
against a live Graph response — nobody in this repo has run this flow yet. So every
response shape is parsed in exactly one `_parse_*` function per endpoint, each marked
`[V]`. When the flow is first run for real, those functions are where reality lands; the
service above them does not change.

Scope literals are absent by design: the authorization URL joins whatever
`MetaOAuthSettings.requested_scopes` holds (env-sourced), and granted scopes come back
from `/me/permissions` as raw strings that this module does not interpret.

## Token discipline

Tokens appear in exactly three places: the `access_token` query parameter of a Graph
request, the return value of `exchange_code`, and `LinkedPage.page_access_token` (A0 —
the Page credential publishing requires). They are never logged, never stored on a
client instance attribute, and never put in an exception message — a token in a
traceback is a token in a log aggregator. Both carriers redact themselves in `repr`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx

from qualify_api.config import MetaOAuthSettings


class MetaOAuthError(Exception):
    """A platform call failed. The message NEVER carries the token or the raw response —
    both routinely contain credential material."""


@dataclass(frozen=True)
class TokenGrant:
    """A freshly exchanged token. Short-lived by construction: the service encrypts it and
    drops the plaintext, so this object should not outlive the callback."""

    access_token: str
    token_type: str
    expires_in: int | None

    def __repr__(self) -> str:  # never let a token reach a log or traceback
        return f"<TokenGrant token_type={self.token_type!r} access_token=redacted>"


@dataclass(frozen=True)
class LinkedPage:
    """A Facebook Page the consenting user administers, plus the IG account linked to it.

    ADR 25: a Page is mandatory, not incidental — `mentioned_media`/`mentioned_comment`
    are exclusive to the Facebook Login path, and losing them would erase the multimodal
    cascade's reach on the connected route. `instagram_account_id` is None for a Page with
    no linked IG account, which is the `link_required` case.

    `page_access_token` is the credential Meta actually accepts for publishing on the
    Instagram-API-with-Facebook-Login fork (A0): the USER token the code exchange yields
    is not it. `[V]` None until observed live — the field only comes back when asked for.
    """

    page_id: str
    page_name: str
    instagram_account_id: str | None
    instagram_username: str | None
    page_access_token: str | None = None

    def __repr__(self) -> str:  # same discipline as TokenGrant: never a token in a log
        return (
            f"<LinkedPage page_id={self.page_id!r} page_name={self.page_name!r} "
            f"instagram_account_id={self.instagram_account_id!r} "
            f"instagram_username={self.instagram_username!r} page_access_token=redacted>"
        )


class MetaOAuthClient(Protocol):
    def authorization_url(self, *, state: str) -> str: ...

    async def exchange_code(self, code: str) -> TokenGrant: ...

    async def list_linked_pages(self, access_token: str) -> tuple[LinkedPage, ...]: ...

    async def list_granted_scopes(self, access_token: str) -> tuple[str, ...]: ...


# --- [V] response parsing. One function per endpoint; the only place reality lands. ---


def _parse_token_response(payload: dict[str, Any]) -> TokenGrant:
    """[V] Expected shape: {"access_token": ..., "token_type": ..., "expires_in": ...}."""
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise MetaOAuthError("token response carried no access_token")
    expires_in = payload.get("expires_in")
    return TokenGrant(
        access_token=token,
        token_type=str(payload.get("token_type") or "bearer"),
        expires_in=int(expires_in) if isinstance(expires_in, int | str) and expires_in else None,
    )


def _parse_accounts_response(payload: dict[str, Any]) -> tuple[LinkedPage, ...]:
    """[V] Expected shape of `/me/accounts`:
    {"data": [{"id", "name", "access_token", "instagram_business_account": {"id", "username"}}]}.

    Tolerant by intent: a Page with no `instagram_business_account` is a REAL case (the
    fork R4 exists to catch), not a parse error, so it yields a LinkedPage with
    `instagram_account_id=None` rather than raising. Same treatment for a missing
    `access_token` (A0): its absence is an observation the service must handle, not a
    reason to lose the whole enumeration.
    """
    entries = payload.get("data")
    if not isinstance(entries, list):
        raise MetaOAuthError("accounts response carried no data array")
    pages: list[LinkedPage] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        ig = entry.get("instagram_business_account")
        ig = ig if isinstance(ig, dict) else {}
        token = entry.get("access_token")
        pages.append(
            LinkedPage(
                page_id=str(entry.get("id", "")),
                page_name=str(entry.get("name", "")),
                instagram_account_id=str(ig["id"]) if ig.get("id") else None,
                instagram_username=str(ig["username"]) if ig.get("username") else None,
                page_access_token=token if isinstance(token, str) and token else None,
            )
        )
    return tuple(pages)


def _parse_permissions_response(payload: dict[str, Any]) -> tuple[str, ...]:
    """[V] Expected shape of `/me/permissions`:
    {"data": [{"permission": "...", "status": "granted"|"declined"}]}.

    Only `granted` rows are kept — C-04.3's whole point is that Meta allows PARTIAL
    consent, and an app that records what it requested rather than what it received fails
    later with a 403 that looks like a bug somewhere else. The strings are returned
    VERBATIM; interpreting them is `resolve_scope_keys`'s job (C-05), not this module's.
    """
    entries = payload.get("data")
    if not isinstance(entries, list):
        raise MetaOAuthError("permissions response carried no data array")
    granted: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("permission")
        if isinstance(name, str) and name and entry.get("status") == "granted":
            granted.append(name)
    return tuple(granted)


class HttpMetaOAuthClient:
    """Real Graph API client. Constructed per request; holds no token between calls."""

    def __init__(
        self, settings: MetaOAuthSettings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings = settings
        self._transport = transport

    def authorization_url(self, *, state: str) -> str:
        params = {
            "client_id": self._settings.app_id,
            "redirect_uri": self._settings.redirect_uri,
            "state": state,
            "response_type": "code",
        }
        # Omit `scope` entirely when unset rather than sending an empty string — the two
        # are not equivalent to an authorization endpoint.
        if self._settings.requested_scopes:
            params["scope"] = ",".join(self._settings.requested_scopes)
        return f"{self._settings.authorize_url}?{urlencode(params)}"

    async def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        async with httpx.AsyncClient(transport=self._transport) as client:
            response = await client.get(f"{self._settings.graph_url}{path}", params=params)
        if response.status_code != 200:
            # Status only. The body of a failed auth call regularly echoes the token.
            raise MetaOAuthError(f"GET {path} failed with HTTP {response.status_code}")
        return dict(response.json())

    async def exchange_code(self, code: str) -> TokenGrant:
        return _parse_token_response(
            await self._get(
                "/oauth/access_token",
                {
                    "client_id": self._settings.app_id,
                    "client_secret": self._settings.app_secret,
                    "redirect_uri": self._settings.redirect_uri,
                    "code": code,
                },
            )
        )

    async def list_linked_pages(self, access_token: str) -> tuple[LinkedPage, ...]:
        return _parse_accounts_response(
            await self._get(
                "/me/accounts",
                {
                    "access_token": access_token,
                    # `access_token` (the Page's own) comes back ONLY if asked for — no
                    # tolerant parser could recover a field Meta never sent (A0).
                    "fields": "id,name,access_token,instagram_business_account{id,username}",
                },
            )
        )

    async def list_granted_scopes(self, access_token: str) -> tuple[str, ...]:
        return _parse_permissions_response(
            await self._get("/me/permissions", {"access_token": access_token})
        )

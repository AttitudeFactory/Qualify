"""The Messenger Profile API for an Instagram account's Ice Breakers («preguntas iniciales»)
(m-24789472, PR 3, B2), under the signed Facebook Login fork (ADR 25).

## What this module talks to — and what it has NOT been able to prove

**Everything here is `[V]`-pending: read from the corpus, never observed live.**
`SHAPE_VERSION_IG_ICE_BREAKERS` is stamped on every snapshot so a later correction can
find what an earlier reading wrote. Sources (`reference/meta-instagram-platform/`):
`documentation/business-messaging/instagram-messaging/features/ice-breakers.md` (the
Facebook Login fork, Page token), `docs/graph-api/reference/page/messenger_profile.md`
(the generic property API) and `instagram-platform/instagram-api-with-instagram-login/
messaging-api/ice-breakers.md` (the Instagram Login twin, for the response shapes).

- **Set** — `POST /{page}/messenger_profile?platform=instagram` with
  `{"platform": "instagram", "ice_breakers": [{"call_to_actions": [{question, payload}],
  "locale": "default"}]}`. «default locale is REQUIRED»; at most 4 questions. Qualify
  writes exactly ONE block, `default` (the businesses it serves write Spanish). Only the
  properties in the body are overwritten (`messenger_profile.md`), so this never touches
  the account's persistent menu or greeting. Success: `{"result": "success"}` (Page
  reference) or `{"success": true}` (Instagram Login doc) — both accepted.
- **Read back** — `GET /{page}/messenger_profile?fields=ice_breakers&platform=instagram`.
  The corpus disagrees on the shape: `ice-breakers.md` shows `data` as the list of locale
  blocks (`[{call_to_actions, locale}, …]`), the generic reference shows `data` as ONE
  object per request keyed by property (`[{"ice_breakers": [...]}]`). `parse_ice_breakers`
  accepts both; R6 will say which one Meta sends. A block without `locale` is `default`.
- **Remove** — `DELETE /{page}/messenger_profile?platform=instagram` with the body
  `{"fields": ["ice_breakers"]}` (only the named properties are deleted).
- **Rate limit** — «10 API calls per 10 minute interval … per Page» (`messenger_profile.md`).
  A publish is two calls (set + read back), a removal two, a refresh one. A refusal for
  rate is `rate_limited`, never retried here: publishing is a person's action.
- **Permissions** — `pages_messaging` per the Page reference; the Facebook Login fork's
  `instagram_manage_messages` is the scope Qualify asks for. Which one Meta checks for the
  `platform=instagram` variant is part of R6.

`{page}` is the connection's `linked_page_id` (the Page whose token the resolver injects,
NOT NULL on every Instagram connection — ADR 25), with `me` as the fallback the docs use:
with a Page token both name the same Page. Same addressing as the DM sender.

## Errors are typed, and say whether the request may have landed

`IceBreakersApiError.category` is one stable code: `auth_expired` (401 / 190),
`permission_missing` (10, 200–299), `rate_limited` (429, or Meta's throttling codes 4, 17,
32, 613), `meta_unavailable` (5xx, or a transport failure BEFORE the request left),
`ambiguous` (a transport failure AFTER it may have reached Meta — a read timeout, a dropped
response: the outcome is unknown, so the caller reads back instead of guessing), `rejected`
(any other answer from Meta: definitive) and `unexpected_response` (a 200 we cannot read).
`detail` is `http_<status>_code_<code>` or `transport_<exception>` — digits and lowercase
only, never a response body (which echoes the questions) and never a token.

## Token discipline

The module never sees a token: the client factory yields an `AuthenticatedClient` with the
Page token already injected as a header (`connections.resolver`, R3). Logs carry the
connection id, the operation and codes — never a question, a payload or a token.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Protocol
from uuid import UUID

import httpx
from qualify_shared.social.graph_errors import is_auth_error

from qualify_api.connections.resolver import AuthenticatedClient
from qualify_api.conversations.contracts import SourceConnection
from qualify_api.conversations.instagram_source import READ_TIMEOUT_S, SEND_TIMEOUT_S

logger = logging.getLogger("qualify_api.conversations.ice_breakers_client")

#: Stamped on every snapshot. `0.1.0` = corpus only, never observed live (R6 pending).
SHAPE_VERSION_IG_ICE_BREAKERS: Final = "ig-ice-breakers-messenger-profile-0.1.0"

PLATFORM: Final = "instagram"
LOCALE_DEFAULT: Final = "default"
PROFILE_FIELD: Final = "ice_breakers"
#: `ice-breakers.md`: «a maximum of 4 questions».
MAX_ICE_BREAKERS: Final = 4

CATEGORY_AUTH_EXPIRED: Final = "auth_expired"
CATEGORY_PERMISSION_MISSING: Final = "permission_missing"
CATEGORY_RATE_LIMITED: Final = "rate_limited"
CATEGORY_META_UNAVAILABLE: Final = "meta_unavailable"
CATEGORY_AMBIGUOUS: Final = "ambiguous"
CATEGORY_REJECTED: Final = "rejected"
CATEGORY_UNEXPECTED_RESPONSE: Final = "unexpected_response"

#: Transport failures AFTER the request may have reached Meta (as in `instagram_source`).
_AMBIGUOUS_TRANSPORT: Final = (
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
    httpx.ReadError,
    httpx.WriteError,
)
_PERMISSION_CODES: Final = frozenset({10, *range(200, 300)})
#: Graph's throttling codes: app (4), user (17), page (32), API-specific (613).
_RATE_LIMIT_CODES: Final = frozenset({4, 17, 32, 613})
_DETAIL_UNSAFE: Final = re.compile(r"[^a-z0-9_]")

ClientFactory = Callable[[UUID, UUID], Awaitable[AuthenticatedClient]]


@dataclass(frozen=True)
class IceBreakerItem:
    """One Ice Breaker: the question the person taps and the payload Meta sends back."""

    question: str
    payload: str

    def as_wire(self) -> dict[str, str]:
        return {"question": self.question, "payload": self.payload}


@dataclass(frozen=True)
class RemoteLocale:
    locale: str
    items: tuple[IceBreakerItem, ...]


@dataclass(frozen=True)
class RemoteIceBreakers:
    """What Instagram answered to the read-back, normalized. Empty = none configured."""

    locales: tuple[RemoteLocale, ...] = ()
    shape_version: str = SHAPE_VERSION_IG_ICE_BREAKERS

    @property
    def default_items(self) -> tuple[IceBreakerItem, ...]:
        for block in self.locales:
            if block.locale == LOCALE_DEFAULT:
                return block.items
        return ()

    @property
    def is_empty(self) -> bool:
        return not any(block.items for block in self.locales)

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "shape_version": self.shape_version,
            "locales": [
                {"locale": b.locale, "items": [i.as_wire() for i in b.items]} for b in self.locales
            ],
        }

    @classmethod
    def from_snapshot(cls, snapshot: Mapping[str, Any]) -> RemoteIceBreakers:
        locales = tuple(
            RemoteLocale(
                locale=str(block.get("locale") or LOCALE_DEFAULT),
                items=tuple(_items_from(block.get("items"))),
            )
            for block in snapshot.get("locales") or ()
            if isinstance(block, Mapping)
        )
        return cls(
            locales=locales,
            shape_version=str(snapshot.get("shape_version") or SHAPE_VERSION_IG_ICE_BREAKERS),
        )


class IceBreakersApiError(Exception):
    """A Messenger Profile call failed. Category, status and numeric codes only — no body."""

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        platform_code: int | None = None,
        platform_subcode: int | None = None,
        is_transport: bool = False,
        is_ambiguous: bool = False,
        transport_name: str | None = None,
        unexpected_response: bool = False,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.platform_code = platform_code
        self.platform_subcode = platform_subcode
        self.is_transport = is_transport
        self.is_ambiguous = is_ambiguous
        self.transport_name = transport_name
        self.unexpected_response = unexpected_response

    @property
    def is_auth_error(self) -> bool:
        return is_auth_error(http_status=self.http_status, platform_code=self.platform_code)

    @property
    def is_permission_error(self) -> bool:
        return self.platform_code in _PERMISSION_CODES

    @property
    def is_rate_limited(self) -> bool:
        return self.http_status == 429 or self.platform_code in _RATE_LIMIT_CODES

    @property
    def is_retryable(self) -> bool:
        """Worth trying again later (by a person — nothing here retries): a transport
        failure before the request left, a rate limit, a 5xx. An ambiguous failure is not
        (it may have landed: read back first); everything else is Meta's definitive no."""
        if self.is_ambiguous:
            return False
        if self.is_transport or self.is_rate_limited:
            return True
        return self.http_status is not None and self.http_status >= 500

    @property
    def category(self) -> str:
        if self.is_ambiguous:
            return CATEGORY_AMBIGUOUS
        if self.unexpected_response:
            return CATEGORY_UNEXPECTED_RESPONSE
        if self.is_auth_error:
            return CATEGORY_AUTH_EXPIRED
        if self.is_rate_limited:
            return CATEGORY_RATE_LIMITED
        if self.is_permission_error:
            return CATEGORY_PERMISSION_MISSING
        if self.is_transport or (self.http_status is not None and self.http_status >= 500):
            return CATEGORY_META_UNAVAILABLE
        return CATEGORY_REJECTED

    @property
    def detail(self) -> str:
        """`http_400_code_100[_sub_N]` or `transport_readtimeout`: `[a-z0-9_]`, ≤ 64."""
        if self.is_transport:
            raw = f"transport_{(self.transport_name or 'error').lower()}"
        else:
            raw = f"http_{self.http_status if self.http_status is not None else 'none'}"
            if self.platform_code is not None:
                raw += f"_code_{self.platform_code}"
            if self.platform_subcode is not None:
                raw += f"_sub_{self.platform_subcode}"
        return _DETAIL_UNSAFE.sub("_", raw)[:64]


def _error_codes(response: httpx.Response) -> tuple[int | None, int | None]:
    """Meta's numeric `error.code` / `error.error_subcode`, or Nones (duplicated from the
    other clients on purpose: each one is self-contained)."""
    try:
        error = dict(response.json()).get("error")
    except (ValueError, TypeError):
        return None, None
    if not isinstance(error, dict):
        return None, None
    code, subcode = error.get("code"), error.get("error_subcode")
    return (
        code if isinstance(code, int) and not isinstance(code, bool) else None,
        subcode if isinstance(subcode, int) and not isinstance(subcode, bool) else None,
    )


def _failed(what: str, response: httpx.Response) -> IceBreakersApiError:
    code, subcode = _error_codes(response)
    return IceBreakersApiError(
        f"{what} failed with HTTP {response.status_code}",
        http_status=response.status_code,
        platform_code=code,
        platform_subcode=subcode,
    )


def _transport(what: str, exc: Exception) -> IceBreakersApiError:
    return IceBreakersApiError(
        f"{what} failed in transport ({type(exc).__name__})",
        is_transport=True,
        is_ambiguous=isinstance(exc, _AMBIGUOUS_TRANSPORT),
        transport_name=type(exc).__name__,
    )


def _unexpected(what: str, status: int) -> IceBreakersApiError:
    return IceBreakersApiError(
        f"{what} answered {status} with an unreadable body",
        http_status=status,
        unexpected_response=True,
    )


# --- [V]-pending request building and response parsing --------------------------------------


def build_set_body(items: Sequence[IceBreakerItem]) -> dict[str, Any]:
    """The POST body, exactly as `ice-breakers.md` shows it: one `default` block (required).
    Validation of the TEXT is the service's job; this refuses only what Meta would."""
    if not items:
        raise ValueError("at least one ice breaker is required")
    if len(items) > MAX_ICE_BREAKERS:
        raise ValueError(f"at most {MAX_ICE_BREAKERS} ice breakers")
    return {
        "platform": PLATFORM,
        PROFILE_FIELD: [
            {
                "call_to_actions": [item.as_wire() for item in items],
                "locale": LOCALE_DEFAULT,
            }
        ],
    }


def build_delete_body() -> dict[str, Any]:
    return {"fields": [PROFILE_FIELD]}


def _items_from(raw: Any) -> Iterable[IceBreakerItem]:
    if not isinstance(raw, list):
        return
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        question, payload = entry.get("question"), entry.get("payload")
        if isinstance(question, str) and isinstance(payload, str):
            yield IceBreakerItem(question=question, payload=payload)


def _locale_block(raw: Mapping[str, Any]) -> RemoteLocale:
    locale = raw.get("locale")
    return RemoteLocale(
        locale=locale if isinstance(locale, str) and locale else LOCALE_DEFAULT,
        items=tuple(_items_from(raw.get("call_to_actions"))),
    )


def parse_ice_breakers(payload: Mapping[str, Any]) -> RemoteIceBreakers:
    """The read-back. `data` as locale blocks (`ice-breakers.md`) or as one object keyed
    by property (`messenger_profile.md`); both are accepted. Raises `ValueError` when
    `data` is missing or not a list — «nothing configured» must not be guessed."""
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("messenger_profile answer has no `data` list")
    blocks: list[RemoteLocale] = []
    for entry in data:
        if not isinstance(entry, Mapping):
            continue
        nested = entry.get(PROFILE_FIELD)
        if isinstance(nested, list):
            blocks.extend(_locale_block(b) for b in nested if isinstance(b, Mapping))
        elif "call_to_actions" in entry:
            blocks.append(_locale_block(entry))
    return RemoteIceBreakers(locales=tuple(blocks))


def parse_success(payload: Any) -> bool:
    """`{"result": "success"}` (Page reference) or `{"success": true}` (Instagram Login)."""
    if not isinstance(payload, Mapping):
        return False
    return payload.get("result") == "success" or payload.get("success") is True


# --- the client -----------------------------------------------------------------------------


class IceBreakersClient(Protocol):
    async def publish(
        self, connection: SourceConnection, items: Sequence[IceBreakerItem]
    ) -> None: ...

    async def fetch(self, connection: SourceConnection) -> RemoteIceBreakers: ...

    async def remove(self, connection: SourceConnection) -> None: ...


def _page_node(connection: SourceConnection) -> str:
    return connection.linked_page_id or "me"


class InstagramIceBreakersClient:
    """Production client. One authenticated client per call: the three operations are a
    person's clicks, minutes apart, and a token refreshed in between must be picked up."""

    def __init__(self, *, client_factory: ClientFactory, graph_url: str) -> None:
        self._factory = client_factory
        self._graph_url = graph_url.rstrip("/")

    def _url(self, connection: SourceConnection) -> str:
        return f"{self._graph_url}/{_page_node(connection)}/messenger_profile"

    async def _call(
        self, method: str, connection: SourceConnection, what: str, **kwargs: Any
    ) -> httpx.Response:
        try:
            client = await self._factory(connection.tenant_id, connection.connection_id)
            if method == "POST":
                response = await client.post(self._url(connection), **kwargs)
            elif method == "DELETE":
                response = await client.delete(self._url(connection), **kwargs)
            else:
                response = await client.get(self._url(connection), **kwargs)
        except httpx.HTTPError as exc:
            error = _transport(what, exc)
            self._log(what, connection, error)
            raise error from exc
        if response.status_code != 200:
            error = _failed(what, response)
            self._log(what, connection, error)
            raise error
        return response

    @staticmethod
    def _log(what: str, connection: SourceConnection, error: IceBreakersApiError) -> None:
        # Codes only: never the body (it echoes the questions), never the token.
        logger.warning(
            "conversations.ice_breakers %s connection=%s category=%s detail=%s",
            what,
            connection.connection_id,
            error.category,
            error.detail,
        )

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return None

    async def publish(self, connection: SourceConnection, items: Sequence[IceBreakerItem]) -> None:
        what = "POST messenger_profile"
        response = await self._call(
            "POST",
            connection,
            what,
            params={"platform": PLATFORM},
            json=build_set_body(items),
            timeout=SEND_TIMEOUT_S,
        )
        if not parse_success(self._json(response)):
            error = _unexpected(what, response.status_code)
            self._log(what, connection, error)
            raise error

    async def fetch(self, connection: SourceConnection) -> RemoteIceBreakers:
        what = "GET messenger_profile"
        response = await self._call(
            "GET",
            connection,
            what,
            params={"fields": PROFILE_FIELD, "platform": PLATFORM},
            timeout=READ_TIMEOUT_S,
        )
        body = self._json(response)
        try:
            return parse_ice_breakers(body if isinstance(body, Mapping) else {})
        except ValueError:
            error = _unexpected(what, response.status_code)
            self._log(what, connection, error)
            raise error from None

    async def remove(self, connection: SourceConnection) -> None:
        what = "DELETE messenger_profile"
        response = await self._call(
            "DELETE",
            connection,
            what,
            params={"platform": PLATFORM},
            json=build_delete_body(),
            timeout=SEND_TIMEOUT_S,
        )
        if not parse_success(self._json(response)):
            error = _unexpected(what, response.status_code)
            self._log(what, connection, error)
            raise error


@dataclass
class MemoryIceBreakersClient:
    """The in-memory twin (tests, and local development with
    `QUALIFY_CONVERSATIONS_DM_CHANNEL=memory`): one remote state per account. `fail_next`
    queues errors the next calls raise, in order; `calls` records `(operation, connection)`
    — never the questions' text, like the real client's logs."""

    remote: dict[UUID, tuple[IceBreakerItem, ...]] = field(default_factory=dict)
    fail_next: list[Exception] = field(default_factory=list)
    calls: list[tuple[str, UUID]] = field(default_factory=list)
    # When an ambiguous failure is raised, whether the change landed anyway.
    ambiguous_landed: bool = False

    def _maybe_fail(self) -> None:
        if self.fail_next:
            raise self.fail_next.pop(0)

    async def publish(self, connection: SourceConnection, items: Sequence[IceBreakerItem]) -> None:
        self.calls.append(("publish", connection.connection_id))
        build_set_body(items)
        try:
            self._maybe_fail()
        except IceBreakersApiError as exc:
            if exc.is_ambiguous and self.ambiguous_landed:
                self.remote[connection.connection_id] = tuple(items)
            raise
        self.remote[connection.connection_id] = tuple(items)

    async def fetch(self, connection: SourceConnection) -> RemoteIceBreakers:
        self.calls.append(("fetch", connection.connection_id))
        self._maybe_fail()
        items = self.remote.get(connection.connection_id, ())
        if not items:
            return RemoteIceBreakers()
        return RemoteIceBreakers(locales=(RemoteLocale(LOCALE_DEFAULT, items),))

    async def remove(self, connection: SourceConnection) -> None:
        self.calls.append(("remove", connection.connection_id))
        try:
            self._maybe_fail()
        except IceBreakersApiError as exc:
            if exc.is_ambiguous and self.ambiguous_landed:
                self.remote.pop(connection.connection_id, None)
            raise
        self.remote.pop(connection.connection_id, None)


__all__ = [
    "CATEGORY_AMBIGUOUS",
    "CATEGORY_AUTH_EXPIRED",
    "CATEGORY_META_UNAVAILABLE",
    "CATEGORY_PERMISSION_MISSING",
    "CATEGORY_RATE_LIMITED",
    "CATEGORY_REJECTED",
    "CATEGORY_UNEXPECTED_RESPONSE",
    "LOCALE_DEFAULT",
    "MAX_ICE_BREAKERS",
    "SHAPE_VERSION_IG_ICE_BREAKERS",
    "ClientFactory",
    "IceBreakerItem",
    "IceBreakersApiError",
    "IceBreakersClient",
    "InstagramIceBreakersClient",
    "MemoryIceBreakersClient",
    "RemoteIceBreakers",
    "RemoteLocale",
    "build_delete_body",
    "build_set_body",
    "parse_ice_breakers",
    "parse_success",
]

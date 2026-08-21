"""On-demand token health checks against Meta's `/debug_token` (QUA-91).

Answers exactly one question, on demand, never on a timer: is the Page Access Token
Qualify custodies for this connection still good, and how much runway is left on the
*data access* window before a human needs to reconnect. There is no scheduler here and
none is added by this module — see `composition.py::check_connection_health` for the
one and only trigger (a manual "Verificar ahora" click), and its docstring for why.

**Synchronous by design.** `check_connection_health` is called the same way
`revoke_connection`/`degrade_connection_on_auth_error` already are — via
`asyncio.to_thread` from a Reflex background event, never from FastAPI's async request
path. `meta_oauth.py` uses `httpx.AsyncClient` because it runs inside the (already async)
OAuth callback route; there is no equivalent benefit here, and an async client would only
add an `asyncio.run()` nesting concern this sidesteps entirely by using a plain
`httpx.Client`.

**`expires_at=0` is real, not a parsing assumption.** Verified against Meta's live
`/debug_token` for the production connection (2026-08-20): `is_valid=true`,
`expires_at=0`, `data_access_expires_at` ~90 days out. `0` is treated as "no calendar
expiry" (`None`), matching the convention `oauth_credentials.expires_at` already uses.
`expires_at`/`scopes` on the report below are informational only — see the module
docstring on `connections/composition.py` for what is and is not persisted.

**Two facts this module explicitly does NOT decide.** Whether `is_valid=false` degrades
the connection is `composition.py`'s job (it reuses `degrade_connection_on_auth_error`,
QUA-90, unmodified). Whether a passed `data_access_expires_at` degrades anything is
answered here in the constant below: it never does on its own — Meta documents that data
access expiring does not uniformly break every call, so treating the date alone as proof
of breakage would assert something unverified. Only real evidence (`is_valid=false`)
degrades; a passed or near date is surfaced as a warning, nothing more.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

import httpx

from qualify_api.config import MetaOAuthSettings
from qualify_api.connections.crypto import Encryptor
from qualify_api.connections.resolver import CredentialReader

# How close to `data_access_expires_at` a connection has to be before the UI warns about
# it. Unlike `META_CALL_BUDGET_PER_HOUR` (inbox/service.py), this number is NOT documented
# by Meta — it is our own operational choice, because the only recovery is a human
# noticing and reconnecting. ~90 days of runway, an operator checking in roughly weekly,
# and wanting at least a couple of check-ins' worth of warning before the window closes
# lands on two weeks. Revisit here — one line — if that cadence assumption changes.
DATA_ACCESS_WARNING_THRESHOLD: timedelta = timedelta(days=14)


class TokenHealthError(Exception):
    """`/debug_token` itself could not be read — a transport/parse failure, never a
    verdict about the token. Message NEVER carries the token or the raw response, same
    discipline as `MetaOAuthError` (a failed auth-adjacent call regularly echoes
    parameters back)."""


@dataclass(frozen=True)
class TokenHealthReport:
    """One `/debug_token` read. `is_valid` is the only field that ever drives a state
    change (`composition.py`); `expires_at`/`scopes` are carried for completeness/tests
    and are never persisted (see `composition.py`'s docstring for what is)."""

    is_valid: bool
    expires_at: datetime | None
    data_access_expires_at: datetime | None
    scopes: tuple[str, ...]


class MetaTokenHealthClient(Protocol):
    def debug_token(self, token: str) -> TokenHealthReport: ...


def _parse_epoch(value: Any) -> datetime | None:
    """`0` and absent both mean "no calendar expiry" — Meta's own convention for a
    long-lived Page token, confirmed live (see module docstring)."""
    if not isinstance(value, int | float) or not value:
        return None
    return datetime.fromtimestamp(value, tz=UTC)


def _parse_debug_token_response(payload: dict[str, Any]) -> TokenHealthReport:
    """[V]-style: the one place a real `/debug_token` shape lands, verified live
    2026-08-20 against the production connection (`is_valid`, `expires_at`,
    `data_access_expires_at`, `scopes` all present exactly as parsed here)."""
    data = payload.get("data")
    if not isinstance(data, dict):
        raise TokenHealthError("debug_token response carried no data object")
    is_valid = data.get("is_valid")
    if not isinstance(is_valid, bool):
        raise TokenHealthError("debug_token response carried no is_valid")
    scopes = data.get("scopes")
    return TokenHealthReport(
        is_valid=is_valid,
        expires_at=_parse_epoch(data.get("expires_at")),
        data_access_expires_at=_parse_epoch(data.get("data_access_expires_at")),
        scopes=tuple(s for s in scopes if isinstance(s, str)) if isinstance(scopes, list) else (),
    )


class HttpMetaTokenHealthClient:
    """Real `/debug_token` caller. The inspecting credential is Qualify's own app
    (`app_id|app_secret`, per Meta's documented shortcut for an app access token) — the
    subject being inspected is `token`, never the caller's own credential. Constructed
    per call, holds no token between calls, same posture as `HttpMetaOAuthClient`."""

    def __init__(
        self, settings: MetaOAuthSettings, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        self._settings = settings
        self._transport = transport

    def debug_token(self, token: str) -> TokenHealthReport:
        with httpx.Client(transport=self._transport) as client:
            response = client.get(
                f"{self._settings.graph_url}/debug_token",
                params={
                    "input_token": token,
                    "access_token": f"{self._settings.app_id}|{self._settings.app_secret}",
                },
            )
        if response.status_code != 200:
            # Status only — the body of a failed call can echo request parameters back.
            raise TokenHealthError(f"GET /debug_token failed with HTTP {response.status_code}")
        return _parse_debug_token_response(dict(response.json()))


class TokenHealthChecker:
    """Reads the encrypted credential, decrypts it in memory just long enough to ask
    Meta about it, and returns only the health report — never the token. Same custody
    discipline `InjectingCredentialResolver` already establishes (`resolver.py`): no
    public method here returns the plaintext under any name."""

    def __init__(
        self, *, reader: CredentialReader, encryptor: Encryptor, client: MetaTokenHealthClient
    ) -> None:
        self._reader = reader
        self._encryptor = encryptor
        self._client = client

    def check(self, connection_id: UUID) -> TokenHealthReport:
        credential = self._reader.read_current(connection_id)
        token = self._encryptor.decrypt(credential.ciphertext, key_id=credential.key_id)
        return self._client.debug_token(token)

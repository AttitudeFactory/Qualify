"""«Cambiar de negocio» without logging out (S4 m-24849191, ADR 43 §2.2).

Switching business does NOT reset the Reflex state in place: it **abandons** it. A
background event of business A still running when the owner moves to B would write its
result, on `async with self`, into whatever state that token serves — so B must be served
by a NEW state. The sequence:

1. `AuthState.switch_business` verifies the membership fresh (`open_business`) and mints
   a **single-use pass** here: 256 random bits; Redis keeps only its SHA-256 as the key;
   60 s of life; bound to `(auth_user_id, destination tenant)`; redeemed once (`GETDEL`).
2. The browser deletes Reflex's token from `sessionStorage` and loads `/cambiar#pase=…`
   (a full navigation). Without a token the Reflex client mints a new one: a new, empty
   state. The pass travels in the URL **fragment**, which never reaches a server log.
3. `/cambiar` reads the fragment in the browser, hands it to `redeem_switch_pass`, which
   redeems it here, checks the membership fresh again and opens B in that new state.

The pass also carries the session's Supabase access token, so the new state's logout can
still revoke it. It is the first time that token touches Redis, so it is stored
**encrypted with a key derived from the pass itself**: whoever reads Redis sees a hash
and a ciphertext, never the token, and cannot redeem anything without the pass.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
from dataclasses import dataclass
from functools import cache
from typing import Any, Protocol
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

SWITCH_ROUTE = "/cambiar"
#: The fragment parameter `/cambiar` reads (`#pase=…`).
PASS_PARAM = "pase"
PASS_TTL_SECONDS = 60
_KEY_PREFIX = "business_switch"
#: Reflex 0.10's client keeps the state token under this `sessionStorage` key
#: (`reflex_base/.templates/web/utils/state.js`, `TOKEN_KEY`). Deleting it before a full
#: navigation is what makes the next page open a NEW state.
REFLEX_TOKEN_KEY = "token"


class _Redis(Protocol):
    def set(self, name: str, value: str, ex: int | None = None) -> Any: ...

    def getdel(self, name: str) -> Any: ...


@dataclass(frozen=True)
class SwitchPass:
    """What a redeemed pass opens. `access_token` is backend-only, like `_access_token`."""

    auth_user_id: UUID
    tenant_id: UUID
    access_token: str


def _key(pass_value: str) -> str:
    digest = hashlib.sha256(pass_value.encode("ascii")).hexdigest()
    return f"{_KEY_PREFIX}:{digest}"


def _cipher(pass_value: str) -> Fernet:
    """A Fernet key derived from the pass, on a different input than the Redis key, so the
    stored key (a hash of the pass) says nothing about the encryption key."""
    raw = hashlib.sha256(b"qualify.business_switch.v1:" + pass_value.encode("ascii")).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


class SwitchPassStore:
    """Mints and redeems business-switch passes. One instance wraps one Redis."""

    def __init__(self, redis: _Redis, *, ttl_seconds: int = PASS_TTL_SECONDS) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    def issue(self, *, auth_user_id: UUID, tenant_id: UUID, access_token: str) -> str:
        pass_value = secrets.token_urlsafe(32)
        sealed = _cipher(pass_value).encrypt(access_token.encode("utf-8")).decode("ascii")
        payload = json.dumps(
            {"auth_user_id": str(auth_user_id), "tenant_id": str(tenant_id), "token": sealed}
        )
        self._redis.set(_key(pass_value), payload, ex=self._ttl)
        return pass_value

    def redeem(self, pass_value: str) -> SwitchPass | None:
        """The pass's target, ONCE: the entry is deleted in the same Redis command that
        reads it. None for an unknown, expired, used or malformed pass."""
        if not pass_value or len(pass_value) > 128:
            return None
        try:
            raw = self._redis.getdel(_key(pass_value))
            if raw is None:
                return None
            data = json.loads(raw)
            token = _cipher(pass_value).decrypt(str(data["token"]).encode("ascii"))
            return SwitchPass(
                auth_user_id=UUID(str(data["auth_user_id"])),
                tenant_id=UUID(str(data["tenant_id"])),
                access_token=token.decode("utf-8"),
            )
        except (ValueError, KeyError, TypeError, UnicodeError, InvalidToken):
            return None


@cache
def _store() -> SwitchPassStore:
    import redis  # noqa: PLC0415
    from qualify_api.config import redis_url  # noqa: PLC0415

    # Short timeouts: a hung Redis must end in «No pudimos cambiar de negocio…», not
    # leave the chip on «Abriendo…» for good.
    client = redis.Redis.from_url(
        redis_url(), decode_responses=True, socket_timeout=2, socket_connect_timeout=2
    )
    return SwitchPassStore(client)


def issue_switch_pass(auth_user_id: UUID, tenant_id: UUID, access_token: str) -> str:
    """Blocking (Redis): call through `asyncio.to_thread`."""
    return _store().issue(auth_user_id=auth_user_id, tenant_id=tenant_id, access_token=access_token)


def redeem_switch_pass(pass_value: str) -> SwitchPass | None:
    """Blocking (Redis): call through `asyncio.to_thread`."""
    return _store().redeem(pass_value)


def switch_script(pass_value: str) -> str:
    """The browser half of step 2: forget this tab's Reflex token, then a full
    navigation (`replace`: «atrás» does not return to the abandoned state's page) to
    `/cambiar` with the pass in the fragment. Values are JSON-encoded, never pasted."""
    target = json.dumps(f"{SWITCH_ROUTE}#{PASS_PARAM}={pass_value}")
    key = json.dumps(REFLEX_TOKEN_KEY)
    return f"window.sessionStorage.removeItem({key}); window.location.replace({target});"


def pass_from_fragment(fragment: str) -> str:
    """The pass of `#pase=…`, or "" when the fragment carries none."""
    from urllib.parse import parse_qs  # noqa: PLC0415

    values = parse_qs(str(fragment or "").lstrip("#")).get(PASS_PARAM) or [""]
    return values[0]


__all__ = [
    "PASS_PARAM",
    "PASS_TTL_SECONDS",
    "REFLEX_TOKEN_KEY",
    "SWITCH_ROUTE",
    "SwitchPass",
    "SwitchPassStore",
    "issue_switch_pass",
    "pass_from_fragment",
    "redeem_switch_pass",
    "switch_script",
]

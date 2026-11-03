"""The OAuth `state` parameter (C-04.2): signed, expiring, and single-use.

`state` is the only thing tying a callback back to the request that started it, and it
makes a round trip through the user's browser — so it is treated as hostile input. Four
independent defenses, each covering what the others cannot:

1. **HMAC-SHA256 signature** — the payload cannot be edited. Without it, a caller could
   swap `tenant_id` and have the callback attach someone else's Instagram account to
   their own tenant. This is why the callback reconstitutes `(tenant_id, brand_id,
   user_id)` from the SIGNED payload and never from an unsigned query parameter.
2. **`iat` + TTL** — a signature is valid forever; a captured `state` should not be.
3. **Single-use `jti` in Redis** — a signature does not prevent REPLAY. The jti is written
   with `SET NX EX` at issue and removed with `GETDEL` (atomic) at the callback, so the
   second presentation of a valid, unexpired, correctly-signed `state` finds nothing and
   is rejected.

4. **Browser binding (m-24921205)** — 1-3 prove the `state` is ours and fresh, not that the
   browser presenting it is the one that started the flow. Without 4, an attacker starts a
   connect in THEIR tenant and sends the consent URL to a victim, whose social account then
   lands in the attacker's tenant (login CSRF / account injection). So each start mints a
   random nonce, signs only its sha256 into the payload (`binding`), and hands the nonce to
   the starting browser as a host-only cookie named after the jti (`qoauth_<provider>_<jti
   prefix>`, Path=/api/connections, SameSite=Lax, Secure, Max-Age = the state TTL). The
   callback compares cookie and hash in constant time after spending the jti and BEFORE the
   code exchange; a missing or foreign cookie ends as `invalid_state` with nothing persisted.

Only 1 and 2 are cryptographic; 3 is the one that needs shared state, which is why Redis
is a Sprint-1 dependency rather than a "soon" item. 4 needs the browser's cookie jar.

Nothing secret goes in the payload — it holds ids, and it is signed, not encrypted. A
`state` is readable by whoever holds it, which is fine: knowing a tenant id grants nothing
without a valid signature, and the ids are already the user's own.
"""

from __future__ import annotations

import base64
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol
from uuid import UUID, uuid4


class InvalidState(Exception):
    """The `state` is malformed, mis-signed, expired, already consumed, or not bound to the
    browser presenting it.

    Deliberately ONE exception for all five: the callback redirects to the same
    `/connections?connect=invalid_state` either way (QUA-123), and distinguishing them to
    the caller would tell an attacker which half of a forged token was wrong.
    """


def safe_return_path(raw: object) -> str:
    """Keep only a short internal app path, never a URL or another connect loop."""
    value = str(raw or "").strip()
    if len(value) > 64 or "//" in value or not re.fullmatch(r"/[a-z0-9][a-z0-9/_-]*", value):
        return ""
    if value == "/connections" or value.startswith("/connections/"):
        return ""
    return value


# Where the binding cookie lives: both callbacks (`/api/connections/callback` and
# `/api/connections/tiktok/callback`) sit under it, and no other route ever sees it.
BINDING_COOKIE_PATH = "/api/connections"


def new_binding_nonce() -> str:
    """256 bits of randomness for one flow's browser binding."""
    return secrets.token_urlsafe(32)


def binding_hash(nonce: str) -> str:
    """What the signed `state` carries: the nonce itself never leaves the browser's jar."""
    return sha256(nonce.encode("utf-8")).hexdigest()


def binding_cookie_name(provider: str, jti: str) -> str:
    """One cookie per flow, so two tabs or Meta+TikTok in parallel never clobber each other.
    Derived from the jti, which the callback only trusts after verifying the signature."""
    return f"qoauth_{provider}_{jti[:16]}"


@dataclass(frozen=True)
class StartedConnect:
    """What starting a connect hands the UI: where to send the browser, and the binding
    cookie the browser must hold when it comes back to `callback_url` (the registered
    redirect URI, whose host is the only one the host-only cookie will be sent to)."""

    authorization_url: str
    binding_cookie_name: str
    binding_nonce: str
    max_age: int
    callback_url: str

    def __repr__(self) -> str:  # the nonce is a bearer secret for the callback
        return (
            f"StartedConnect(authorization_url=..., binding_cookie_name="
            f"{self.binding_cookie_name!r}, binding_nonce=redacted)"
        )


@dataclass(frozen=True)
class StatePayload:
    """The signed contents of a `state`. `iat` is a unix timestamp (seconds)."""

    tenant_id: UUID
    brand_id: UUID | None
    user_id: UUID
    jti: str
    iat: int
    return_to: str = ""
    connection_id: UUID | None = None
    external_account_id: str = ""
    cause: str = ""
    # sha256 hex of the browser-binding nonce (defense 4); "" only for a legacy state,
    # which therefore never binds.
    binding: str = ""

    def to_dict(self) -> dict[str, str | int | None]:
        return {
            "tenant_id": str(self.tenant_id),
            "brand_id": str(self.brand_id) if self.brand_id else None,
            "user_id": str(self.user_id),
            "jti": self.jti,
            "iat": self.iat,
            "return_to": self.return_to,
            "connection_id": str(self.connection_id) if self.connection_id else None,
            "external_account_id": self.external_account_id,
            "cause": self.cause,
            "binding": self.binding,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, str | int | None]) -> StatePayload:
        brand_id = raw.get("brand_id")
        return cls(
            tenant_id=UUID(str(raw["tenant_id"])),
            brand_id=UUID(str(brand_id)) if brand_id else None,
            user_id=UUID(str(raw["user_id"])),
            jti=str(raw["jti"]),
            iat=int(raw["iat"]),  # type: ignore[arg-type]
            return_to=safe_return_path(raw.get("return_to", "")),
            connection_id=UUID(str(raw["connection_id"])) if raw.get("connection_id") else None,
            external_account_id=str(raw.get("external_account_id") or ""),
            cause=str(raw.get("cause") or ""),
            binding=str(raw.get("binding") or ""),
        )


def binding_matches(payload: StatePayload, nonce: str | None) -> bool:
    """Constant-time check of the browser's cookie against the signed hash. An empty
    hash (legacy state) or a missing cookie never matches."""
    if not payload.binding or not nonce:
        return False
    return hmac.compare_digest(binding_hash(nonce), payload.binding)


class StateRedis(Protocol):
    """The Redis surface the jti store needs (the real `redis.Redis` satisfies it)."""

    def set(
        self, name: str, value: str, *, nx: bool = False, ex: int | None = None
    ) -> bool | None: ...

    def getdel(self, name: str) -> str | bytes | None: ...


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw + padding)


def _signature(body: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body.encode("ascii"), sha256).hexdigest()


def new_payload(
    tenant_id: UUID,
    brand_id: UUID | None,
    user_id: UUID,
    *,
    return_to: str = "",
    connection_id: UUID | None = None,
    external_account_id: str = "",
    cause: str = "",
    binding: str = "",
) -> StatePayload:
    """Mint a payload with a fresh jti and the current timestamp."""
    return StatePayload(
        tenant_id=tenant_id,
        brand_id=brand_id,
        user_id=user_id,
        jti=uuid4().hex,
        iat=int(time.time()),
        return_to=safe_return_path(return_to),
        connection_id=connection_id,
        external_account_id=external_account_id,
        cause=cause,
        binding=binding,
    )


def sign_state(payload: StatePayload, secret: str) -> str:
    """Serialize and sign. Format: `<b64url(json)>.<hex hmac>`."""
    body = _b64url_encode(
        json.dumps(payload.to_dict(), separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    return f"{body}.{_signature(body, secret)}"


def verify_state(
    token: str, secret: str, *, ttl_seconds: int, now: int | None = None
) -> StatePayload:
    """Verify signature and freshness, returning the payload. Raises `InvalidState`.

    The signature is checked with `compare_digest` (constant time) BEFORE the payload is
    parsed, so malformed-but-unsigned input never reaches the JSON decoder.
    """
    body, _, provided = token.partition(".")
    if not body or not provided:
        raise InvalidState("malformed state")
    if not hmac.compare_digest(provided, _signature(body, secret)):
        raise InvalidState("bad signature")
    try:
        payload = StatePayload.from_dict(json.loads(_b64url_decode(body)))
    except (ValueError, KeyError, TypeError) as exc:
        raise InvalidState("undecodable payload") from exc

    current = int(time.time()) if now is None else now
    # Reject the future too: a clock-skewed or forged `iat` must not buy extra lifetime.
    if payload.iat > current + 60 or current - payload.iat > ttl_seconds:
        raise InvalidState("expired state")
    return payload


class JtiStore:
    """One-shot jti registry backed by Redis.

    `issue` is `SET NX EX` so a jti collision (astronomically unlikely, but free to check)
    cannot silently overwrite a live entry. `consume` is `GETDEL` — atomic read-and-delete,
    so two concurrent callbacks carrying the same `state` cannot both succeed. A
    check-then-delete pair would leave exactly that race open.
    """

    def __init__(self, redis: StateRedis, *, ttl_seconds: int = 600) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    @staticmethod
    def _key(jti: str) -> str:
        return f"oauth:state:{jti}"

    def issue(self, jti: str) -> None:
        if not self._redis.set(self._key(jti), "1", nx=True, ex=self._ttl):
            raise InvalidState("jti already in flight")

    def consume(self, jti: str) -> bool:
        """True iff this jti was live and is now spent. False on replay or expiry."""
        return self._redis.getdel(self._key(jti)) is not None

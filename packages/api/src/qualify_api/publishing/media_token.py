"""The public-media token store (QUA-68 / ADR 28e) — the Redis-backed mapping behind
`GET /public/media/{token}`.

Same family as `connections/state_token.py::JtiStore` and `connections/locks.py::RefreshLock`
(a small Redis-backed primitive owned by the module that needs it, built on the shared
`redis_url()` in `qualify_api.config`), but a distinct shape from both:

- **Not one-shot like the jti.** Meta can `HEAD` a media URL before `GET`-ing it, and may
  retry the `GET` — the token must resolve the SAME way every time inside its window, so
  this uses `GET`, never `GETDEL`.
- **Not a lock.** There is no contention to arbitrate — one token names one object for one
  publish attempt, and reading it never mutates it.

Only the SHA-256 hash of the token is ever written to Redis, never the token itself — the
security property `GET /public/media/{token}`'s design lives on: whoever reads a Redis dump
gets hashes, not working links. `content_type` travels in the mapping too, alongside
`tenant_id`/`object_key`, so the public route never needs to ask `qualify_shared.objects`
for it — that door has no way to return it (`ObjectStore.open()` returns bytes only), and
the content_type staged for this exact object is already known at `issue()` time.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

# ADR 28(e): the operation this token covers (staging a container, Meta fetching it, the
# container reaching a terminal status) fits comfortably inside 15 minutes — the same
# number the video path's container poll ceiling uses, chosen for the same reason: it
# bounds ONE publish attempt, not a scheduling horizon. A post scheduled for next Tuesday
# mints its token next Tuesday.
TOKEN_TTL_SECONDS = 900

_KEY_PREFIX = "media_token"


class MediaTokenRedis(Protocol):
    """The Redis surface this store needs (the real `redis.Redis` satisfies it)."""

    def set(self, name: str, value: str, *, ex: int | None = None) -> bool | None: ...

    def get(self, name: str) -> str | bytes | None: ...


@dataclass(frozen=True)
class MediaTokenTarget:
    """What a resolved token names — everything `public_media_routes.py` needs to serve
    the object without touching Redis, or `qualify_shared.objects`, again."""

    tenant_id: UUID
    object_key: str
    content_type: str


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _key(token_hash: str) -> str:
    return f"{_KEY_PREFIX}:{token_hash}"


class MediaTokenStore:
    """Mints and resolves public-media tokens. One instance wraps one Redis connection."""

    def __init__(self, redis: MediaTokenRedis, *, ttl_seconds: int = TOKEN_TTL_SECONDS) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    def issue(self, *, tenant_id: UUID, object_key: str, content_type: str) -> str:
        """Mint a fresh, unguessable token and store its (hashed) mapping.

        `secrets.token_urlsafe(32)` — 256 bits from a CSPRNG, not derived from
        `tenant_id`/`object_key`/a timestamp. Deriving it would make the token
        reconstructable from data an attacker might already have, and would encode
        tenant information into a link handed to a third party (Meta's fetcher) — exactly
        what ADR 28(e) rejected a presigned R2 URL for doing.
        """
        token = secrets.token_urlsafe(32)
        payload = json.dumps(
            {"tenant_id": str(tenant_id), "object_key": object_key, "content_type": content_type},
            separators=(",", ":"),
            sort_keys=True,
        )
        self._redis.set(_key(_hash(token)), payload, ex=self._ttl)
        return token

    def resolve(self, token: str) -> MediaTokenTarget | None:
        """`None` for an unknown OR expired token — Redis already collapses those two cases
        (an expired key simply is not there), which is exactly the indistinguishability
        `public_media_routes.py` needs; this method does not need to invent it.

        Plain `GET`, never `GETDEL`: multi-use within the TTL window is the whole point —
        Meta may `HEAD` then `GET`, or retry a `GET`, and every one of those must resolve
        the same way until the token's own TTL (not a use-count) ends it.
        """
        raw = self._redis.get(_key(_hash(token)))
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            return MediaTokenTarget(
                tenant_id=UUID(str(data["tenant_id"])),
                object_key=str(data["object_key"]),
                content_type=str(data["content_type"]),
            )
        except (ValueError, KeyError, TypeError):
            # Malformed payload (should never happen — this store is the only writer of
            # this key shape) is treated as "not found", not a 500: the caller's contract
            # is "resolvable or not", and a corrupt entry is not resolvable.
            return None

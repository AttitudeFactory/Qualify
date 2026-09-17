"""`MediaTokenStore` (QUA-68), fully offline against a minimal fake Redis — same convention
as `test_connections_locks.py`'s `FakeRedis` for `RefreshLock`.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from qualify_api.publishing.media_token import TOKEN_TTL_SECONDS, MediaTokenStore

TENANT = UUID("44444444-4444-4444-8444-444444444444")


class FakeRedis:
    """Implements just the surface `MediaTokenStore` uses: `SET EX` and `GET`. Recording
    every `set()` call (not just the final state) is what lets the TTL tests assert the
    exact `ex` value passed, not just that SOME value was stored."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.set_calls: list[tuple[str, str, int | None]] = []

    def set(self, name: str, value: str, *, ex: int | None = None) -> bool | None:
        self.set_calls.append((name, value, ex))
        self.store[name] = value
        return True

    def get(self, name: str) -> str | None:
        return self.store.get(name)


def test_issue_then_resolve_round_trips() -> None:
    redis = FakeRedis()
    store = MediaTokenStore(redis)

    token = store.issue(tenant_id=TENANT, object_key="t/x/media/y/z", content_type="image/jpeg")
    target = store.resolve(token)

    assert target is not None
    assert target.tenant_id == TENANT
    assert target.object_key == "t/x/media/y/z"
    assert target.content_type == "image/jpeg"


def test_only_the_hash_is_stored_never_the_token() -> None:
    """The property the whole design exists for: reading the fake store's raw contents
    must not hand back a token that would still work."""
    redis = FakeRedis()
    store = MediaTokenStore(redis)

    token = store.issue(tenant_id=TENANT, object_key="t/x/media/y/z", content_type="image/jpeg")

    assert len(redis.set_calls) == 1
    key, value, _ = redis.set_calls[0]
    assert token not in key
    assert token not in value
    # The Redis key IS the sha256 hex digest of the token, namespaced — not the token
    # itself, not a truncation of it, not an encoding of it.
    import hashlib

    assert key == f"media_token:{hashlib.sha256(token.encode()).hexdigest()}"


def test_token_is_256_bits_from_a_csprng_not_derived_from_the_target() -> None:
    """`secrets.token_urlsafe(32)` — 32 raw bytes, base64url-encoded. Asserting the
    decoded length (not just the string length, which base64 padding could obscure) is
    what actually pins '256 bits', matching the architect's own spec."""
    import base64

    redis = FakeRedis()
    store = MediaTokenStore(redis)

    token = store.issue(tenant_id=TENANT, object_key="t/x/media/y/z", content_type="image/jpeg")

    padded = token + "=" * (-len(token) % 4)
    assert len(base64.urlsafe_b64decode(padded)) == 32


def test_ttl_defaults_to_900_seconds() -> None:
    redis = FakeRedis()
    store = MediaTokenStore(redis)

    store.issue(tenant_id=TENANT, object_key="t/x/media/y/z", content_type="image/jpeg")

    assert TOKEN_TTL_SECONDS == 900
    _, _, ex = redis.set_calls[0]
    assert ex == 900


def test_ttl_is_configurable() -> None:
    redis = FakeRedis()
    store = MediaTokenStore(redis, ttl_seconds=60)

    store.issue(tenant_id=TENANT, object_key="t/x/media/y/z", content_type="image/jpeg")

    _, _, ex = redis.set_calls[0]
    assert ex == 60


def test_multi_use_within_the_ttl_window() -> None:
    """Meta may HEAD then GET, or retry a GET — every resolve() within the window must
    succeed identically. A `GETDEL`-based store (the jti's one-shot shape) would fail this."""
    redis = FakeRedis()
    store = MediaTokenStore(redis)
    token = store.issue(tenant_id=TENANT, object_key="t/x/media/y/z", content_type="image/jpeg")

    first = store.resolve(token)
    second = store.resolve(token)
    third = store.resolve(token)

    assert first == second == third is not None


def test_unknown_token_resolves_to_none() -> None:
    store = MediaTokenStore(FakeRedis())

    assert store.resolve("this-token-was-never-issued") is None


def test_expired_token_resolves_to_none() -> None:
    """Redis's own TTL eviction is what makes a key vanish; from `resolve()`'s point of
    view an expired token and an unknown one are the SAME observation (nothing in the
    store), which is exactly the indistinguishability the public route needs — simulated
    here by deleting the entry, since a fake dict has no real wall-clock expiry."""
    redis = FakeRedis()
    store = MediaTokenStore(redis)
    token = store.issue(tenant_id=TENANT, object_key="t/x/media/y/z", content_type="image/jpeg")
    key = redis.set_calls[0][0]
    del redis.store[key]  # simulates the TTL having elapsed

    assert store.resolve(token) is None


def test_a_malformed_stored_payload_resolves_to_none_not_a_crash() -> None:
    """This store is the only writer of this key shape, so this should never happen in
    practice — but `resolve()`'s contract is 'resolvable or not', and a corrupt entry is
    not resolvable. A caller crashing on bad Redis data would be a worse failure mode than
    treating it as an ordinary miss. Corrupts the value UNDER THE TOKEN'S OWN HASHED KEY
    (via `issue()`, then overwriting what it wrote) rather than a made-up key, so this
    actually exercises `resolve()`'s JSON-parsing branch instead of merely hitting its
    'nothing in Redis' branch by accident."""
    redis = FakeRedis()
    store = MediaTokenStore(redis)
    token = store.issue(tenant_id=TENANT, object_key="t/x/media/y/z", content_type="image/jpeg")
    key = redis.set_calls[0][0]
    redis.store[key] = "{not valid json"

    assert store.resolve(token) is None


@pytest.mark.parametrize("bad_json", ['{"tenant_id": "x"}', "null", "[]", '"a string"'])
def test_a_structurally_wrong_but_valid_json_payload_resolves_to_none(bad_json: str) -> None:
    redis = FakeRedis()
    store = MediaTokenStore(redis)
    token = store.issue(tenant_id=TENANT, object_key="t/x/media/y/z", content_type="image/jpeg")
    key = redis.set_calls[0][0]
    redis.store[key] = bad_json

    assert store.resolve(token) is None

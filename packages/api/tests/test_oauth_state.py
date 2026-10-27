"""Pure tests for the signed, expiring, single-use `state` (C-04.2). No network, no DB."""

from __future__ import annotations

import time
from uuid import UUID

import pytest

from qualify_api.connections.state_token import (
    InvalidState,
    JtiStore,
    StatePayload,
    new_payload,
    sign_state,
    verify_state,
)

SECRET = "test-secret"
OTHER_SECRET = "other-secret"
TENANT = UUID("11111111-1111-4111-8111-111111111111")
BRAND = UUID("22222222-2222-4222-8222-222222222222")
USER = UUID("33333333-3333-4333-8333-333333333333")


class FakeRedis:
    """SET NX EX + GETDEL, the two operations the jti store needs."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def set(self, name: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool | None:
        if nx and name in self.store:
            return None
        self.store[name] = value
        return True

    def getdel(self, name: str) -> str | None:
        return self.store.pop(name, None)


def test_sign_verify_roundtrip_preserves_identity() -> None:
    payload = new_payload(TENANT, BRAND, USER)
    restored = verify_state(sign_state(payload, SECRET), SECRET, ttl_seconds=600)
    assert restored == payload


def test_brand_id_may_be_absent() -> None:
    payload = new_payload(TENANT, None, USER)
    restored = verify_state(sign_state(payload, SECRET), SECRET, ttl_seconds=600)
    assert restored.brand_id is None


def test_wrong_secret_is_rejected() -> None:
    token = sign_state(new_payload(TENANT, BRAND, USER), SECRET)
    with pytest.raises(InvalidState):
        verify_state(token, OTHER_SECRET, ttl_seconds=600)


def test_tampered_payload_is_rejected() -> None:
    """The attack the signature exists to stop: swapping the tenant to hijack a grant."""
    payload = new_payload(TENANT, BRAND, USER)
    token = sign_state(payload, SECRET)
    body, _, signature = token.partition(".")
    forged_body = sign_state(
        StatePayload(
            tenant_id=UUID("99999999-9999-4999-8999-999999999999"),
            brand_id=payload.brand_id,
            user_id=payload.user_id,
            jti=payload.jti,
            iat=payload.iat,
        ),
        SECRET,
    ).partition(".")[0]
    assert forged_body != body
    with pytest.raises(InvalidState):
        verify_state(f"{forged_body}.{signature}", SECRET, ttl_seconds=600)


@pytest.mark.parametrize("token", ["", "nodot", ".", "abc.", ".abc"])
def test_malformed_tokens_are_rejected(token: str) -> None:
    with pytest.raises(InvalidState):
        verify_state(token, SECRET, ttl_seconds=600)


def test_expired_state_is_rejected() -> None:
    payload = new_payload(TENANT, BRAND, USER)
    token = sign_state(payload, SECRET)
    with pytest.raises(InvalidState):
        verify_state(token, SECRET, ttl_seconds=600, now=payload.iat + 601)


def test_future_dated_state_is_rejected() -> None:
    """A forged `iat` in the future must not buy extra lifetime."""
    payload = StatePayload(
        tenant_id=TENANT, brand_id=BRAND, user_id=USER, jti="j", iat=int(time.time()) + 3600
    )
    with pytest.raises(InvalidState):
        verify_state(sign_state(payload, SECRET), SECRET, ttl_seconds=600)


def test_jti_is_single_use() -> None:
    store = JtiStore(FakeRedis(), ttl_seconds=600)
    store.issue("jti-1")
    assert store.consume("jti-1") is True  # first callback wins
    assert store.consume("jti-1") is False  # replay finds nothing


def test_unknown_jti_is_not_consumable() -> None:
    assert JtiStore(FakeRedis()).consume("never-issued") is False


def test_issuing_a_live_jti_twice_raises() -> None:
    store = JtiStore(FakeRedis())
    store.issue("jti-1")
    with pytest.raises(InvalidState):
        store.issue("jti-1")


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.test",
        "//evil.test",
        "/inbox?next=https://evil.test",
        "/connections",
        "/\\evil",
    ],
)
def test_reconnect_state_rejects_external_or_looping_return_paths(origin: str) -> None:
    payload = new_payload(TENANT, BRAND, USER, return_to=origin)
    restored = verify_state(sign_state(payload, SECRET), SECRET, ttl_seconds=600)
    assert restored.return_to == ""


def test_reconnect_target_and_origin_are_signed_and_preserved() -> None:
    payload = new_payload(
        TENANT,
        BRAND,
        USER,
        return_to="/inbox",
        connection_id=BRAND,
        external_account_id="ig-1",
        cause="permission_missing",
    )
    restored = verify_state(sign_state(payload, SECRET), SECRET, ttl_seconds=600)
    assert restored == payload

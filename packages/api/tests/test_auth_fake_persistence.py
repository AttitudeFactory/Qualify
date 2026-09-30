"""`FakeAuthProvider` disk persistence (`persist_path`) — the fix for the bug where a
dev-server restart forgot every signed-up email and forced a brand-new, empty
tenant/brand/kit on the next login (`registry.py`'s docstring explains the mechanism).

No database, no Reflex: `FakeAuthProvider` and `_load_users`/`_save_users` are pure
Python over a `tmp_path` file.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from qualify_api.auth.config import fake_auth_state_path
from qualify_api.auth.fake import FakeAuthProvider
from qualify_api.auth.provider import EmailAlreadyRegistered, InvalidCredentials


def test_no_persist_path_stays_pure_in_memory(tmp_path) -> None:
    """The default (`persist_path=None`, every call site but the registry singleton)
    must be byte-identical to the old behavior: nothing touches disk."""
    provider = FakeAuthProvider()
    provider.admin_create_user("a@b.co", "password-123", uuid4())
    assert list(tmp_path.iterdir()) == []  # nothing was ever written anywhere


def test_signup_survives_a_fresh_provider_instance_with_same_path(tmp_path) -> None:
    """The exact regression: process A signs someone up, process A dies, process B
    (a fresh `FakeAuthProvider`, same path) must still recognize that login instead of
    treating them as new."""
    path = tmp_path / "fake_auth_users.json"
    tenant_id = uuid4()

    provider_a = FakeAuthProvider(persist_path=path)
    provider_a.admin_create_user("deividj@gmail.com", "hunter2000", tenant_id)

    provider_b = FakeAuthProvider(persist_path=path)  # simulates the next process
    session = provider_b.sign_in("deividj@gmail.com", "hunter2000")
    assert session.tenant_id == tenant_id


def test_duplicate_signup_after_restart_is_rejected_not_silently_creates_new_tenant(
    tmp_path,
) -> None:
    """Before this fix: a restart made the identity map forget the email, so re-signup
    silently succeeded with a NEW tenant. After: it must raise, same as a same-process
    duplicate signup always did."""
    path = tmp_path / "fake_auth_users.json"
    provider_a = FakeAuthProvider(persist_path=path)
    provider_a.admin_create_user("deividj@gmail.com", "hunter2000", uuid4())

    provider_b = FakeAuthProvider(persist_path=path)
    with pytest.raises(EmailAlreadyRegistered):
        provider_b.admin_create_user("deividj@gmail.com", "hunter2000", uuid4())


def test_wrong_password_after_restart_still_rejected(tmp_path) -> None:
    path = tmp_path / "fake_auth_users.json"
    FakeAuthProvider(persist_path=path).admin_create_user("a@b.co", "correct-horse", uuid4())

    provider_b = FakeAuthProvider(persist_path=path)
    with pytest.raises(InvalidCredentials):
        provider_b.sign_in("a@b.co", "wrong-password")


def test_live_tokens_are_not_persisted(tmp_path) -> None:
    """A token minted by a dead process is not a live session under any provider —
    only the identity map (who is registered, whose tenant) survives a restart."""
    path = tmp_path / "fake_auth_users.json"
    provider_a = FakeAuthProvider(persist_path=path)
    provider_a.admin_create_user("a@b.co", "password-123", uuid4())
    session = provider_a.sign_in("a@b.co", "password-123")

    provider_b = FakeAuthProvider(persist_path=path)
    assert provider_b.token_is_live(session.access_token) is False


def test_missing_file_loads_as_empty_not_an_error(tmp_path) -> None:
    provider = FakeAuthProvider(persist_path=tmp_path / "does_not_exist.json")
    with pytest.raises(InvalidCredentials):
        provider.sign_in("nobody@nowhere.co", "whatever")


def test_corrupt_file_degrades_to_empty_not_a_crash(tmp_path) -> None:
    path = tmp_path / "fake_auth_users.json"
    path.write_text("{ not valid json", encoding="utf-8")
    provider = FakeAuthProvider(persist_path=path)
    with pytest.raises(InvalidCredentials):
        provider.sign_in("nobody@nowhere.co", "whatever")


def test_multiple_users_all_round_trip(tmp_path) -> None:
    path = tmp_path / "fake_auth_users.json"
    tenant_a, tenant_b = uuid4(), uuid4()
    provider_a = FakeAuthProvider(persist_path=path)
    provider_a.admin_create_user("a@b.co", "pw-a-123", tenant_a)
    provider_a.admin_create_user("c@d.co", "pw-c-123", tenant_b)

    provider_b = FakeAuthProvider(persist_path=path)
    assert provider_b.sign_in("a@b.co", "pw-a-123").tenant_id == tenant_a
    assert provider_b.sign_in("c@d.co", "pw-c-123").tenant_id == tenant_b


def test_seed_user_also_persists(tmp_path) -> None:
    """`seed_user` is a test helper, not part of the protocol, but it shares the same
    write path — a user seeded with no tenant stamp must still round-trip as such."""
    path = tmp_path / "fake_auth_users.json"
    provider_a = FakeAuthProvider(persist_path=path)
    provider_a.seed_user("no-tenant@b.co", "password-123", tenant_id=None)

    provider_b = FakeAuthProvider(persist_path=path)
    session = provider_b.sign_in("no-tenant@b.co", "password-123")
    assert session.tenant_id is None


def test_state_path_is_overridable_by_env(monkeypatch, tmp_path) -> None:
    override = tmp_path / "custom.json"
    monkeypatch.setenv("QUALIFY_AUTH_FAKE_STATE_PATH", str(override))
    assert fake_auth_state_path() == override


def test_state_path_falls_back_when_env_unset(monkeypatch) -> None:
    monkeypatch.delenv("QUALIFY_AUTH_FAKE_STATE_PATH", raising=False)
    assert fake_auth_state_path().as_posix() == ".states/fake_auth_users.json"

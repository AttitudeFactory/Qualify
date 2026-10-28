"""Offline tests for the QUA-66 auth seam: validation, the fake provider's semantics,
and every login/signup refusal that fires BEFORE any database touch. The happy paths
that need Postgres live in `test_auth_register_db.py` (`db`-marked)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from qualify_api.auth import (
    FakeAuthProvider,
    IncompleteRegistration,
    InvalidCredentials,
    RegistrationInvalid,
    register_business,
    resolve_login,
    service,
)


@pytest.fixture(autouse=True)
def _no_brand_kit_drafts(monkeypatch: pytest.MonkeyPatch) -> None:
    """The signup's pre-login draft lookup (§ 2026-10-02) is a DB read; offline, there is
    no draft to adopt. The adoption itself is covered in `test_brand_kit_drafts_db.py`."""
    monkeypatch.setattr(service, "_open_draft_tenant_id", lambda email: None)


def _register_kwargs(**overrides) -> dict:
    base = dict(
        business_name="Polette",
        email="hlrd1993+polet@gmail.com",
        password="correct-horse-9",
        country="VE",
        timezone="America/Caracas",
        currency="USD",
    )
    base.update(overrides)
    return base


class TestSignupValidation:
    """All of these must refuse before the provider or the DB is ever touched —
    exercised by passing a provider whose every method would explode."""

    class _ExplodingProvider:
        def __getattr__(self, name: str):
            raise AssertionError("provider must not be touched on invalid input")

    def test_empty_business_name_refused(self) -> None:
        with pytest.raises(RegistrationInvalid):
            register_business(self._ExplodingProvider(), **_register_kwargs(business_name="  "))

    def test_short_password_refused(self) -> None:
        with pytest.raises(RegistrationInvalid):
            register_business(self._ExplodingProvider(), **_register_kwargs(password="short"))

    def test_email_without_at_refused(self) -> None:
        with pytest.raises(RegistrationInvalid):
            register_business(self._ExplodingProvider(), **_register_kwargs(email="not-an-email"))

    def test_email_with_surrounding_whitespace_refused_not_trimmed(self) -> None:
        # Criterion 6 discipline: emails are literal. We refuse junk rather than
        # silently "fixing" it into a different literal.
        with pytest.raises(RegistrationInvalid):
            register_business(self._ExplodingProvider(), **_register_kwargs(email=" a@b.co "))


class TestFakeProviderSemantics:
    """The fake must mirror the real provider's contract — these are the properties
    the service and the UI lean on."""

    def test_alias_emails_are_distinct_users(self) -> None:
        provider = FakeAuthProvider()
        tenant_a, tenant_b = uuid4(), uuid4()
        provider.admin_create_user("hlrd1993+polet@gmail.com", "password-123", tenant_a)
        provider.admin_create_user("hlrd1993@gmail.com", "password-123", tenant_b)
        assert provider.sign_in("hlrd1993+polet@gmail.com", "password-123").tenant_id == tenant_a
        assert provider.sign_in("hlrd1993@gmail.com", "password-123").tenant_id == tenant_b

    def test_wrong_password_and_unknown_email_are_one_error(self) -> None:
        provider = FakeAuthProvider()
        provider.admin_create_user("a@b.co", "password-123", uuid4())
        with pytest.raises(InvalidCredentials):
            provider.sign_in("a@b.co", "wrong")
        with pytest.raises(InvalidCredentials):
            provider.sign_in("nobody@b.co", "password-123")

    def test_sign_out_revokes_every_live_token(self) -> None:
        provider = FakeAuthProvider()
        provider.admin_create_user("a@b.co", "password-123", uuid4())
        first = provider.sign_in("a@b.co", "password-123")
        second = provider.sign_in("a@b.co", "password-123")
        assert provider.token_is_live(first.access_token)
        provider.sign_out(second.access_token)
        # scope=global semantics: the OTHER session's token is dead too.
        assert not provider.token_is_live(first.access_token)
        assert not provider.token_is_live(second.access_token)


class TestLoginRefusals:
    def test_unstamped_user_is_incomplete_never_guessed(self) -> None:
        provider = FakeAuthProvider()
        provider.seed_user("stray@b.co", "password-123", tenant_id=None)
        with pytest.raises(IncompleteRegistration):
            resolve_login(provider, "stray@b.co", "password-123")

    def test_invalid_credentials_propagate(self) -> None:
        with pytest.raises(InvalidCredentials):
            resolve_login(FakeAuthProvider(), "nobody@b.co", "password-123")

    def test_duplicate_email_with_wrong_password_is_registration_error(self) -> None:
        provider = FakeAuthProvider()
        provider.admin_create_user("taken@b.co", "password-123", uuid4())
        with pytest.raises(RegistrationInvalid):
            register_business(
                provider, **_register_kwargs(email="taken@b.co", password="different-9")
            )

    def test_duplicate_unstamped_identity_is_refused_not_adopted(self) -> None:
        provider = FakeAuthProvider()
        provider.seed_user("manual@b.co", "password-123", tenant_id=None)
        with pytest.raises(RegistrationInvalid):
            register_business(
                provider, **_register_kwargs(email="manual@b.co", password="password-123")
            )


class TestExistingLoginIdentity:
    def test_add_business_authenticates_without_attempting_to_create_credentials(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = FakeAuthProvider()
        old_tenant, new_tenant = uuid4(), uuid4()
        auth_user_id = provider.seed_user("owner@b.co", "password-123", old_tenant)

        def refuse_create(*args: object) -> None:
            pytest.fail("adding a business must never create identity credentials")

        monkeypatch.setattr(provider, "admin_create_user", refuse_create)
        assert service._resolve_identity_for_signup(
            provider, "owner@b.co", "password-123", new_tenant, is_add_business=True
        ) == (auth_user_id, new_tenant)
        assert provider.sign_in("owner@b.co", "password-123").tenant_id == old_tenant

    @pytest.mark.parametrize("existing", [True, False])
    def test_add_business_invalid_credentials_never_create_an_identity(
        self, existing: bool, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = FakeAuthProvider()
        if existing:
            provider.seed_user("owner@b.co", "password-123", uuid4())

        def refuse_create(*args: object) -> None:
            pytest.fail("invalid current credentials must never create an identity")

        monkeypatch.setattr(provider, "admin_create_user", refuse_create)
        with pytest.raises(RegistrationInvalid, match="Esa contraseña no coincide"):
            service._resolve_identity_for_signup(
                provider, "owner@b.co", "incorrect-123", uuid4(), is_add_business=True
            )

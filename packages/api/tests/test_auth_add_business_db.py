"""S7 acceptance: an invitation adds a tenant to a login without changing its old business."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event, Lock
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from sqlalchemy import select

from qualify_api.auth import (
    FakeAuthProvider,
    RegistrationInvalid,
    SignupNotAllowed,
    authorize_signup,
    create_invite,
    lookup_invite,
    register_business,
    service,
)
from qualify_api.tenancy.models import Brand, SignupInvite, Tenant, TenantMember, User

pytestmark = pytest.mark.db

PASSWORD = "current-password-9"


def _register(
    provider: FakeAuthProvider, email: str, **overrides: Any
) -> service.RegisteredBusiness:
    kwargs = dict(
        email=email,
        password=PASSWORD,
        business_name=f"Original {uuid4().hex}",
        country="VE",
        timezone="America/Caracas",
        currency="USD",
    )
    kwargs.update(overrides)
    return register_business(provider, **kwargs)


def _snapshot(tenant_id: UUID) -> tuple[Any, ...]:
    with admin_session() as session:
        tenant = session.get(Tenant, tenant_id)
        assert tenant is not None
        users = session.execute(
            select(User.id, User.email, User.auth_user_id).where(User.tenant_id == tenant_id)
        ).all()
        members = session.execute(
            select(TenantMember.id, TenantMember.user_id, TenantMember.role).where(
                TenantMember.tenant_id == tenant_id
            )
        ).all()
        brands = session.execute(
            select(Brand.id, Brand.name).where(Brand.tenant_id == tenant_id)
        ).all()
        return (
            tenant.name,
            tenant.country,
            tenant.timezone,
            tenant.currency,
            set(users),
            set(members),
            set(brands),
        )


@pytest.fixture
def owner() -> tuple[FakeAuthProvider, service.RegisteredBusiness]:
    provider = FakeAuthProvider()
    email = f"owner-{uuid4().hex}@example.com"
    return provider, _register(provider, email)


def test_existing_login_invite_creates_separate_owner_business_and_is_consumed_once(
    owner: tuple[FakeAuthProvider, service.RegisteredBusiness], monkeypatch: pytest.MonkeyPatch
) -> None:
    provider, original = owner
    before = _snapshot(original.tenant_id)
    business = f"Invited {uuid4().hex}"
    item_id = uuid4().int % (2**60)
    notifications: list[tuple[int, UUID]] = []
    monkeypatch.setattr(
        service,
        "notify_meegle_registered",
        lambda item, tenant: notifications.append((item, tenant)),
    )
    invite = create_invite(
        original.email,
        business_name=business,
        is_add_business=True,
        meegle_work_item_id=item_id,
    )
    view = lookup_invite(invite.token)
    assert view is not None and view.is_add_business
    invite_id = authorize_signup(original.email, invite.token)
    added = _register(
        provider, original.email, invite_id=invite_id, business_name="Ignored form name"
    )

    assert added.tenant_id != original.tenant_id
    assert added.auth_user_id == original.auth_user_id and added.business_name == business
    assert _snapshot(original.tenant_id) == before
    memberships = service.memberships_for(original.auth_user_id)
    assert {(m.tenant_id, m.role) for m in memberships} == {
        (original.tenant_id, "owner"),
        (added.tenant_id, "owner"),
    }
    with admin_session() as session:
        stored = session.get(SignupInvite, invite_id)
        assert stored is not None and stored.used_at is not None
        assert stored.registered_tenant_id == added.tenant_id
        assert (
            session.scalar(select(Brand.name).where(Brand.tenant_id == added.tenant_id)) == business
        )
    assert notifications == [(item_id, added.tenant_id)]
    assert provider.sign_in(original.email, PASSWORD).tenant_id == original.tenant_id

    # Replaying the event with the previously authorized id loses at the row lock.
    with pytest.raises(SignupNotAllowed):
        _register(provider, original.email, invite_id=invite_id, business_name=business)
    assert {m.tenant_id for m in service.memberships_for(original.auth_user_id)} == {
        original.tenant_id,
        added.tenant_id,
    }
    assert notifications == [(item_id, added.tenant_id)]
    assert _snapshot(original.tenant_id) == before


def test_normal_invitation_for_existing_login_refuses_without_changing_any_business(
    owner: tuple[FakeAuthProvider, service.RegisteredBusiness], monkeypatch: pytest.MonkeyPatch
) -> None:
    provider, original = owner
    before = _snapshot(original.tenant_id)
    invite = create_invite(original.email, business_name=f"Rejected {uuid4().hex}")

    def refuse_provider(*args: object) -> None:
        pytest.fail("a completed existing login must be rejected before identity-provider calls")

    monkeypatch.setattr(provider, "admin_create_user", refuse_provider)
    monkeypatch.setattr(provider, "sign_in", refuse_provider)
    with pytest.raises(RegistrationInvalid):
        _register(provider, original.email, invite_id=invite.id, business_name=invite.business_name)
    assert _snapshot(original.tenant_id) == before
    assert len(service.memberships_for(original.auth_user_id)) == 1
    assert lookup_invite(invite.token) is not None
    with admin_session() as session:
        assert session.scalar(select(Tenant).where(Tenant.name == invite.business_name)) is None
        assert session.scalar(select(Brand).where(Brand.name == invite.business_name)) is None


@pytest.mark.parametrize("password", ["incorrect-password-9", "bad"])
def test_wrong_current_password_keeps_invitation_and_existing_business_untouched(
    owner: tuple[FakeAuthProvider, service.RegisteredBusiness], password: str
) -> None:
    provider, original = owner
    before = _snapshot(original.tenant_id)
    invite = create_invite(
        original.email, business_name=f"Rejected {uuid4().hex}", is_add_business=True
    )
    with pytest.raises(
        RegistrationInvalid, match="Esa contraseña no coincide. Inténtalo otra vez."
    ):
        _register(provider, original.email, invite_id=invite.id, password=password)
    assert _snapshot(original.tenant_id) == before
    assert len(service.memberships_for(original.auth_user_id)) == 1
    assert lookup_invite(invite.token) is not None


@pytest.mark.parametrize("dead_reason", ["expired", "used", "other_email"])
def test_invalid_add_business_invite_refuses_before_authentication(
    owner: tuple[FakeAuthProvider, service.RegisteredBusiness],
    dead_reason: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, original = owner
    before = _snapshot(original.tenant_id)
    invite = create_invite(
        original.email, business_name=f"Rejected {uuid4().hex}", is_add_business=True
    )
    now = datetime.now(UTC)
    with admin_session() as session:
        stored = session.get(SignupInvite, invite.id)
        assert stored is not None
        if dead_reason == "expired":
            stored.expires_at = now - timedelta(seconds=1)
        elif dead_reason == "used":
            stored.used_at = now

    def refuse_provider(*args: object) -> None:
        pytest.fail("an invalid invitation must be rejected before authentication")

    monkeypatch.setattr(provider, "sign_in", refuse_provider)
    monkeypatch.setattr(provider, "admin_create_user", refuse_provider)
    email = "another@example.com" if dead_reason == "other_email" else original.email
    with pytest.raises(SignupNotAllowed):
        _register(provider, email, invite_id=invite.id)
    assert _snapshot(original.tenant_id) == before
    assert len(service.memberships_for(original.auth_user_id)) == 1


def test_add_business_does_not_replace_a_short_existing_password(
    owner: tuple[FakeAuthProvider, service.RegisteredBusiness],
) -> None:
    provider, original = owner
    provider.seed_user(original.email, "short", original.tenant_id, original.auth_user_id)
    invite = create_invite(
        original.email, business_name=f"Short password {uuid4().hex}", is_add_business=True
    )
    added = _register(provider, original.email, password="short", invite_id=invite.id)
    assert added.auth_user_id == original.auth_user_id
    assert added.tenant_id != original.tenant_id


def test_add_business_cannot_create_an_unknown_login() -> None:
    provider = FakeAuthProvider()
    email = f"missing-{uuid4().hex}@example.com"
    invite = create_invite(email, business_name=f"Unknown {uuid4().hex}", is_add_business=True)
    with pytest.raises(RegistrationInvalid):
        _register(provider, email, invite_id=invite.id)
    with pytest.raises(service.InvalidCredentials):
        provider.sign_in(email, PASSWORD)
    assert lookup_invite(invite.token) is not None
    with admin_session() as session:
        assert session.scalar(select(User).where(User.email == email)) is None
        assert session.scalar(select(Tenant).where(Tenant.name == invite.business_name)) is None


def test_distinct_normal_invites_for_same_email_cannot_race_into_one_business(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeAuthProvider()
    email = f"racing-{uuid4().hex}@example.com"
    first_invite = create_invite(email, business_name=f"First {uuid4().hex}")
    second_invite = create_invite(email, business_name=f"Second {uuid4().hex}")
    first_persisting, release_first, second_waiting, second_locked = (
        Event(),
        Event(),
        Event(),
        Event(),
    )
    counter_lock = Lock()
    lock_calls = 0
    create_calls: list[str] = []
    real_persist, real_lock = service._persist_business, service._lock_signup_email
    real_create = provider.admin_create_user

    def observe_lock(session: Any, supplied_email: str) -> None:
        nonlocal lock_calls
        with counter_lock:
            lock_calls += 1
            second = lock_calls == 2
        if second:
            second_waiting.set()
        real_lock(session, supplied_email)
        if second:
            second_locked.set()

    def hold_first_persist(session: Any, **kwargs: Any) -> None:
        first_persisting.set()
        assert release_first.wait(timeout=5), "test did not release the first signup"
        real_persist(session, **kwargs)

    def observe_create(supplied_email: str, password: str, tenant_id: UUID) -> UUID:
        create_calls.append(supplied_email)
        return real_create(supplied_email, password, tenant_id)

    monkeypatch.setattr(service, "_lock_signup_email", observe_lock)
    monkeypatch.setattr(service, "_persist_business", hold_first_persist)
    monkeypatch.setattr(provider, "admin_create_user", observe_create)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            _register,
            provider,
            email,
            invite_id=first_invite.id,
            business_name=first_invite.business_name,
        )
        try:
            assert first_persisting.wait(timeout=5)
            second = pool.submit(
                _register,
                provider,
                email,
                invite_id=second_invite.id,
                business_name=second_invite.business_name,
            )
            assert second_waiting.wait(timeout=5)
            # A second invite row has its own lock; only email serialization can
            # prevent it from reading a missing local half during this window.
            assert not second_locked.wait(timeout=0.1)
            assert create_calls == [email]
        finally:
            release_first.set()
        registered = first.result(timeout=5)
        with pytest.raises(RegistrationInvalid):
            second.result(timeout=5)

    assert create_calls == [email]
    assert len(service.memberships_for(registered.auth_user_id)) == 1
    assert lookup_invite(first_invite.token) is None
    assert lookup_invite(second_invite.token) is not None
    with admin_session() as session:
        assert session.scalars(
            select(Brand.name).where(Brand.tenant_id == registered.tenant_id)
        ).all() == [first_invite.business_name]
        assert (
            session.scalar(select(Tenant).where(Tenant.name == second_invite.business_name)) is None
        )

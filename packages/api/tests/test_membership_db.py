"""S5 (m-24849192) against Postgres: removing a seat takes effect with the session open,
publish/send doors refuse at once and write nothing, and every business opening leaves
one audit row visible only from the destination business."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import delete, func, select, text

from qualify_api.assisted.approval import HumanApproval
from qualify_api.auth import (
    FakeAuthProvider,
    NotAMember,
    authorize_signup,
    create_invite,
    membership,
    register_business,
    service,
)
from qualify_api.conversations.outbox import PostgresConversationOutboxRepository
from qualify_api.tenancy.acting import acting_login
from qualify_api.tenancy.models import BusinessOpenAudit, TenantMember
from qualify_api.whatsapp.outbox import PostgresOutboxRepository

pytestmark = pytest.mark.db

PASSWORD = "current-password-9"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _register(
    provider: FakeAuthProvider, email: str, **extra: object
) -> service.RegisteredBusiness:
    return register_business(
        provider,
        email=email,
        password=PASSWORD,
        business_name=f"Negocio {uuid4().hex[:8]}",
        country="VE",
        timezone="America/Caracas",
        currency="USD",
        **extra,  # type: ignore[arg-type]
    )


@pytest.fixture
def two_businesses(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[UUID, UUID, UUID]:
    """(auth_user_id, original tenant, added tenant) — one login, two businesses."""
    monkeypatch.setattr(service, "notify_meegle_registered", lambda item, tenant: None)
    provider = FakeAuthProvider()
    email = f"owner-{uuid4().hex}@example.com"
    original = _register(provider, email)
    invite = create_invite(email, business_name=f"Segundo {uuid4().hex[:8]}", is_add_business=True)
    added = _register(provider, email, invite_id=authorize_signup(email, invite.token))
    return original.auth_user_id, original.tenant_id, added.tenant_id


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(membership, "_cache", membership.MembershipCache(clock=fake))
    return fake


def _remove_seat(auth_user_id: UUID, tenant_id: UUID) -> None:
    with admin_session() as session:
        user_id = session.scalar(
            text("SELECT id FROM users WHERE tenant_id = :t AND auth_user_id = :a"),
            {"t": tenant_id, "a": auth_user_id},
        )
        session.execute(
            delete(TenantMember).where(
                TenantMember.tenant_id == tenant_id, TenantMember.user_id == user_id
            )
        )


def _audit_rows(tenant_id: UUID, *, as_tenant: UUID) -> int:
    with tenant_session(as_tenant) as db:
        return db.scalar(
            select(func.count())
            .select_from(BusinessOpenAudit)
            .where(BusinessOpenAudit.tenant_id == tenant_id)
        )


def test_removed_seat_keeps_loading_within_the_ttl_then_refuses(
    two_businesses: tuple[UUID, UUID, UUID], clock: FakeClock
) -> None:
    login, _original, added = two_businesses
    assert membership.check_membership(login, added).tenant_id == added
    _remove_seat(login, added)

    clock.now += 30
    assert membership.check_membership(login, added).tenant_id == added  # within 60 s
    with pytest.raises(NotAMember):  # publishing/sending never waits for the TTL
        membership.require_membership_now(login, added)
    with pytest.raises(NotAMember):  # and the refusal evicted the cached entry
        membership.check_membership(login, added)


def test_cache_expires_after_sixty_seconds(
    two_businesses: tuple[UUID, UUID, UUID], clock: FakeClock
) -> None:
    login, original, _added = two_businesses
    membership.check_membership(login, original)
    _remove_seat(login, original)
    clock.now += 59.9
    membership.check_membership(login, original)
    clock.now += 0.1
    with pytest.raises(NotAMember) as refused:
        membership.check_membership(login, original)
    assert refused.value.message == (
        "Ya no tienes acceso a este negocio. Vuelve a entrar para elegir otro."
    )


def test_send_doors_refuse_a_removed_login_and_queue_nothing(
    two_businesses: tuple[UUID, UUID, UUID], clock: FakeClock
) -> None:
    login, _original, added = two_businesses
    _remove_seat(login, added)
    approval = HumanApproval(user_id=uuid4(), approved_at=datetime.now(UTC))

    with acting_login(login):
        with pytest.raises(NotAMember):
            PostgresConversationOutboxRepository().enqueue(
                tenant_id=added,
                connection_id=uuid4(),
                thread_id=uuid4(),
                channel="dm",
                payload={"recipient": {"id": "1"}, "message": {"text": "hola"}},
                approval=approval,
            )
        with pytest.raises(NotAMember):
            PostgresOutboxRepository().enqueue(
                tenant_id=added,
                connection_id=uuid4(),
                thread_id=uuid4(),
                kind="reply",
                payload={"to": "573001112233", "type": "text", "text": {"body": "hola"}},
                created_by_user_id=None,
            )

    with tenant_session(added) as db:
        for table in ("conversation_outbox", "whatsapp_outbox"):
            count = db.scalar(text(f"SELECT count(*) FROM {table}"))
            assert count == 0, table


def test_member_passes_the_gate(two_businesses: tuple[UUID, UUID, UUID]) -> None:
    login, original, added = two_businesses
    with acting_login(login):
        for tenant_id in (original, added):
            membership.require_acting_member(tenant_id)


def test_every_opening_is_audited_only_in_the_destination(
    two_businesses: tuple[UUID, UUID, UUID],
) -> None:
    login, original, added = two_businesses

    opened = membership.open_business_audited(login, original, via="login")
    switched = membership.open_business_audited(login, added, via="switch", from_tenant_id=original)
    assert opened.tenant_id == original and switched.tenant_id == added

    assert _audit_rows(original, as_tenant=original) == 1
    assert _audit_rows(added, as_tenant=added) == 1
    # RLS: the origin business never sees where its owner went, and vice versa.
    assert _audit_rows(added, as_tenant=original) == 0
    assert _audit_rows(original, as_tenant=added) == 0

    with tenant_session(added) as db:
        row = db.scalars(select(BusinessOpenAudit)).one()
        assert (row.auth_user_id, row.user_id, row.from_tenant_id, row.via) == (
            login,
            switched.user_id,
            original,
            "switch",
        )


def test_a_refused_opening_writes_no_audit_row(
    two_businesses: tuple[UUID, UUID, UUID],
) -> None:
    login, original, added = two_businesses
    _remove_seat(login, added)
    with pytest.raises(NotAMember):
        membership.open_business_audited(login, added, via="switch", from_tenant_id=original)
    with admin_session() as session:
        count = session.scalar(
            select(func.count())
            .select_from(BusinessOpenAudit)
            .where(BusinessOpenAudit.tenant_id == added)
        )
    assert count == 0


@pytest.mark.parametrize(
    "statement",
    ["DELETE FROM business_open_audit", "UPDATE business_open_audit SET via = 'login'"],
)
def test_audit_table_is_append_only(
    two_businesses: tuple[UUID, UUID, UUID], statement: str
) -> None:
    login, original, _added = two_businesses
    membership.open_business_audited(login, original, via="login")
    with pytest.raises(Exception, match="permission denied"):
        with tenant_session(original) as db:
            db.execute(text(statement))
    with pytest.raises(Exception, match="permission denied"):
        with admin_session() as session:
            session.execute(text(statement))

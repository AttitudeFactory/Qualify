"""Real Postgres RLS/column grants/cutoff tests (m-24908066)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.credential import credential_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from qualify_api.connections import credential_reader
from qualify_api.connections.crypto import DevEncryptor
from qualify_api.pinterest.client import PinterestError
from qualify_api.pinterest.repository import PostgresRepository
from qualify_api.tenancy.models import Tenant, TenantMember, User

pytestmark = pytest.mark.db


@pytest.fixture
def accounts():
    a, b, user = uuid4(), uuid4(), uuid4()
    with admin_session() as session:
        for tenant in (a, b):
            session.add(
                Tenant(
                    id=tenant,
                    name="Pinterest test",
                    country="CO",
                    timezone="America/Bogota",
                    currency="COP",
                )
            )
        session.flush()
        session.add(User(id=user, tenant_id=a, email=f"{user}@example.test", display_name="Test"))
        session.flush()
        session.add(TenantMember(tenant_id=a, user_id=user, role="owner"))
    return a, b, user


def save(
    repo: PostgresRepository, tenant, *, version: int, user=None, secret: str = "fixture"
) -> bool:
    encryptor = DevEncryptor()
    return repo.save(
        tenant,
        expected_version=version,
        username="fixture",
        user_id=user,
        ciphertext=encryptor.encrypt(secret),
        key_id=encryptor.key_id,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )


def test_real_tenant_isolation_and_secret_column_denial(accounts: tuple) -> None:
    a, b, user = accounts
    repo = PostgresRepository()
    repo.ensure(a)
    assert save(repo, a, version=0, user=user)
    assert repo.connection(b) is None
    with pytest.raises(PinterestError, match="authentication"):
        repo.read(b)
    with credential_session(b) as session:
        assert session.scalar(text("SELECT count(*) FROM pinterest_credentials")) == 0
    with tenant_session(a) as session:
        with pytest.raises(ProgrammingError):
            session.execute(text("SELECT ciphertext FROM pinterest_credentials"))
    credential = repo.read(a)
    assert DevEncryptor().decrypt(credential.ciphertext, key_id=credential.key_id) == "fixture"
    with tenant_session(b) as session:
        assert session.scalar(text("SELECT count(*) FROM pinterest_connections")) == 0


def test_foreign_actor_cannot_complete_grant(accounts: tuple) -> None:
    a, b, user = accounts
    repo = PostgresRepository()
    repo.ensure(b)
    with pytest.raises(PinterestError, match="permission"):
        save(repo, b, version=0, user=user)
    assert repo.connection(b).status == "disconnected"


def test_removed_membership_cannot_complete_grant(accounts: tuple) -> None:
    a, _, user = accounts
    repo = PostgresRepository()
    repo.ensure(a)
    with admin_session() as session:
        session.execute(
            text("DELETE FROM tenant_members WHERE tenant_id=:tid AND user_id=:uid"),
            {"tid": a, "uid": user},
        )
    with pytest.raises(PinterestError, match="permission"):
        save(repo, a, version=0, user=user)


@pytest.mark.parametrize("role", ["agent", "viewer"])
def test_read_only_roles_cannot_start_or_disconnect(accounts: tuple, role: str) -> None:
    a, _, user = accounts
    repo = PostgresRepository()
    repo.ensure(a)
    assert save(repo, a, version=0, user=user)
    with admin_session() as session:
        session.execute(
            text("UPDATE tenant_members SET role=:role WHERE tenant_id=:tid AND user_id=:uid"),
            {"role": role, "tid": a, "uid": user},
        )
    service, _ = db_service(repo)
    with pytest.raises(PinterestError, match="permission"):
        service.start_connect(tenant_id=a, user_id=user)
    with pytest.raises(PinterestError, match="permission"):
        service.disconnect(a, user)
    # Repository mutation itself also checks permission in its write transaction.
    with pytest.raises(PinterestError, match="permission"):
        repo.disconnect(a, user)
    assert repo.connection(a).status == "active"
    assert repo.read(a).version == 1


def db_service(repo: PostgresRepository):
    from packages.api.tests.test_pinterest_service import OAuthFake, RedisFake

    from qualify_api.connections.locks import RefreshLock
    from qualify_api.connections.state_token import JtiStore
    from qualify_api.pinterest.service import PendingFlows, PinterestService
    from qualify_api.pinterest.settings import PinterestSettings

    oauth, redis = OAuthFake(), RedisFake()
    service = PinterestService(
        settings=PinterestSettings(
            "app", "secret", "https://app.example/api/connections/pinterest/callback", "x" * 32
        ),
        repository=repo,
        oauth=oauth,
        jti=JtiStore(redis),
        encryptor=DevEncryptor(),
        refresh_lock=RefreshLock(redis),
        pending=PendingFlows(redis),
    )
    return service, oauth


def test_role_downgrade_after_start_preserves_old_grant_without_exchange(accounts: tuple) -> None:
    from urllib.parse import parse_qs, urlsplit

    a, _, user = accounts
    repo = PostgresRepository()
    repo.ensure(a)
    assert save(repo, a, version=0, user=user)
    service, oauth = db_service(repo)
    started = service.start_connect(tenant_id=a, user_id=user)
    state = parse_qs(urlsplit(started.authorization_url).query)["state"][0]
    service.handoff(state, binding_nonce=started.binding_nonce)
    with admin_session() as session:
        session.execute(
            text("UPDATE tenant_members SET role='viewer' WHERE tenant_id=:tid AND user_id=:uid"),
            {"tid": a, "uid": user},
        )
    with pytest.raises(PinterestError, match="permission"):
        service.complete_connect(code="fixture", state=state, binding_nonce=started.binding_nonce)
    assert oauth.exchange_count == 0
    assert repo.read(a).version == 1
    assert repo.connection(a).status == "active"
    with pytest.raises(PinterestError, match="permission"):
        save(repo, a, version=1, user=user)


def test_disconnect_erase_cannot_delete_intervening_reconnect(accounts: tuple, monkeypatch) -> None:
    a, _, user = accounts
    repo = PostgresRepository()
    repo.ensure(a)
    assert save(repo, a, version=0, user=user)
    original = credential_reader.erase_pinterest_credentials

    def reconnect_then_erase(tenant, cutoff: int) -> None:
        assert repo.connection(a).status == "disconnected"
        assert save(repo, a, version=cutoff, user=user, secret="new-grant")
        original(tenant, cutoff)

    monkeypatch.setattr(credential_reader, "erase_pinterest_credentials", reconnect_then_erase)
    repo.disconnect(a, user)
    current = repo.read(a)
    assert DevEncryptor().decrypt(current.ciphertext, key_id=current.key_id) == "new-grant"
    assert current.version == 3
    with credential_session(a) as session:
        assert session.scalar(text("SELECT count(*) FROM pinterest_credentials")) == 1

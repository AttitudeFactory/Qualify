"""Real tenant isolation, credential privileges, selection and refresh fencing."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.connection_purge import connection_purge_session
from qualify_shared.db.credential import credential_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from qualify_api.connections.ad_accounts import (
    AdAccountObservation,
    AdAccountUnavailable,
    PostgresAdsGrantRecorder,
    _connection,
    _persist_observations,
    ad_account_availability,
    assign_ad_brand,
    list_ad_accounts,
    list_ad_brands,
    require_ads_member,
    select_ad_account,
)
from qualify_api.connections.credential_reader import CredentialNotFound, DbAdCredentialReader
from qualify_api.connections.crypto import DevEncryptor
from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.tenancy.models import Brand, Tenant, TenantMember, User

pytestmark = pytest.mark.db


@pytest.fixture
def account_world() -> tuple[UUID, UUID, UUID, UUID]:
    tenant, brand, user, connection = uuid4(), uuid4(), uuid4(), uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant,
                name="Advertising test",
                country="CO",
                timezone="America/Bogota",
                currency="COP",
            )
        )
        session.flush()
        app = PlatformApp(app_id=f"ad-{uuid4()}", secret_ref="test", api_version="v26.0")
        session.add_all(
            [
                Brand(id=brand, tenant_id=tenant, name="Ad brand"),
                app,
                User(
                    id=user,
                    tenant_id=tenant,
                    email=f"{user}@test.invalid",
                    display_name="Owner",
                    auth_user_id=uuid4(),
                ),
            ]
        )
        session.flush()
        app_id = app.id
        session.add(TenantMember(tenant_id=tenant, user_id=user, role="owner"))
    with tenant_session(tenant) as session:
        session.add(
            SocialConnection(
                id=connection,
                tenant_id=tenant,
                brand_id=brand,
                platform_app_id=app_id,
                platform="instagram",
                account_type="business",
                external_account_id="42",
                linked_page_id="7",
                granted_scopes=["ads_management"],
                status="active",
                access_posture="development",
                current_credential_version=1,
                connected_by_user_id=user,
            )
        )
    encryptor = DevEncryptor()
    PostgresAdsGrantRecorder().record(
        tenant_id=tenant,
        connection_id=connection,
        version=1,
        ciphertext=encryptor.encrypt("USER_TOKEN"),
        key_id=encryptor.key_id,
        granted_scopes=("ads_management",),
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    return tenant, brand, user, connection


def _observe(tenant: UUID, connection: UUID, ids: tuple[str, ...] = ("12", "13")) -> None:
    with tenant_session(tenant) as session:
        original = _connection(session, connection)
    _persist_observations(
        tenant,
        original,
        tuple(
            AdAccountObservation(
                aid, f"Account {aid}", "COP", "America/Bogota", 1, 0, True, True, "8"
            )
            for aid in ids
        ),
        now=datetime.now(UTC),
        api_version="v26.0",
    )


def test_rls_and_secret_column_privileges_are_structural(account_world) -> None:
    tenant, brand, user, connection = account_world
    _observe(tenant, connection)
    other = uuid4()
    with tenant_session(other) as session:
        assert (
            session.scalar(
                text("SELECT count(*) FROM ad_accounts WHERE connection_id=:cid"),
                {"cid": connection},
            )
            == 0
        )
        assert (
            session.scalar(
                text("SELECT count(*) FROM ad_oauth_credentials WHERE connection_id=:cid"),
                {"cid": connection},
            )
            == 0
        )
    with pytest.raises(ProgrammingError), tenant_session(tenant) as session:
        session.execute(text("SELECT ciphertext FROM ad_oauth_credentials"))
    with credential_session(tenant) as session:
        assert (
            session.scalar(
                text("SELECT count(*) FROM ad_oauth_credentials WHERE connection_id=:cid"),
                {"cid": connection},
            )
            == 1
        )
    with credential_session(other) as session:
        assert (
            session.scalar(
                text("SELECT count(*) FROM ad_oauth_credentials WHERE connection_id=:cid"),
                {"cid": connection},
            )
            == 0
        )
    with tenant_session(tenant) as session:
        flags = session.execute(
            text(
                "SELECT relrowsecurity,relforcerowsecurity FROM pg_class "
                "WHERE relname IN ('ad_accounts','ad_oauth_credentials')"
            )
        ).all()
        assert len(flags) == 2 and all(all(row) for row in flags)
        session.execute(text("SELECT set_config('app.tenant_id','',true)"))
        assert session.scalar(text("SELECT count(*) FROM ad_accounts")) == 0
    with pytest.raises(ProgrammingError), tenant_session(tenant) as session:
        session.execute(
            text("UPDATE ad_oauth_credentials SET ciphertext=:value"), {"value": b"bad"}
        )


def test_selection_is_idempotent_one_per_brand_and_cannot_cross_tenant_or_connection(
    account_world,
) -> None:
    tenant, brand, user, connection = account_world
    _observe(tenant, connection)
    _observe(tenant, connection)
    accounts = list_ad_accounts(tenant_id=tenant, connection_id=connection)
    assert len(accounts) == 2
    for account in accounts:
        select_ad_account(tenant_id=tenant, connection_id=connection, ad_account_id=account.id)
        select_ad_account(tenant_id=tenant, connection_id=connection, ad_account_id=account.id)
        assert (
            sum(a.selected for a in list_ad_accounts(tenant_id=tenant, connection_id=connection))
            == 1
        )
    assert ad_account_availability(tenant_id=tenant, connection_id=connection).enabled
    with pytest.raises(AdAccountUnavailable):
        select_ad_account(tenant_id=uuid4(), connection_id=connection, ad_account_id=accounts[0].id)
    with pytest.raises(AdAccountUnavailable):
        select_ad_account(tenant_id=tenant, connection_id=connection, ad_account_id=uuid4())
    with pytest.raises(IntegrityError), tenant_session(tenant) as session:
        session.execute(
            text("UPDATE ad_accounts SET selected=true WHERE connection_id=:cid"),
            {"cid": connection},
        )
    _observe(tenant, connection, ids=())
    assert list_ad_accounts(tenant_id=tenant, connection_id=connection) == ()
    availability = ad_account_availability(tenant_id=tenant, connection_id=connection)
    assert not availability.enabled
    assert "No hay cuentas publicitarias en la lista" in availability.reason
    assert "Actualizar cuentas" in availability.reason


def test_reconnect_and_revocation_invalidate_user_credential_and_reject_stale_refresh(
    account_world,
) -> None:
    tenant, brand, user, connection = account_world
    _observe(tenant, connection)
    with tenant_session(tenant) as session:
        original = _connection(session, connection)
    assert DbAdCredentialReader(tenant, expected_version=1).read_current(connection).version == 1
    with tenant_session(tenant) as session:
        session.execute(
            text("UPDATE social_connections SET current_credential_version=2 WHERE id=:cid"),
            {"cid": connection},
        )
    with pytest.raises(CredentialNotFound):
        DbAdCredentialReader(tenant, expected_version=1).read_current(connection)
    with pytest.raises(AdAccountUnavailable):
        _persist_observations(tenant, original, (), now=datetime.now(UTC), api_version="v26.0")
    assert list_ad_accounts(tenant_id=tenant, connection_id=connection) == ()
    with tenant_session(tenant) as session:
        session.execute(
            text(
                "UPDATE social_connections SET current_credential_version=1,status='revoked' "
                "WHERE id=:cid"
            ),
            {"cid": connection},
        )
    assert not ad_account_availability(tenant_id=tenant, connection_id=connection).enabled
    with pytest.raises(CredentialNotFound):
        DbAdCredentialReader(tenant, expected_version=1).read_current(connection)


def test_current_membership_and_composite_fk_are_checked(account_world) -> None:
    tenant, brand, user, connection = account_world
    require_ads_member(tenant, user)
    with pytest.raises(AdAccountUnavailable):
        require_ads_member(tenant, uuid4())
    with pytest.raises(IntegrityError), tenant_session(tenant) as session:
        session.execute(
            text(
                "INSERT INTO ad_oauth_credentials "
                "(tenant_id,connection_id,version,ciphertext,key_id,granted_scopes) "
                "VALUES (:tenant,:connection,1,:cipher,'fake',ARRAY['ads_management'])"
            ),
            {"tenant": tenant, "connection": uuid4(), "cipher": b"bad"},
        )
    with tenant_session(tenant) as session:
        original = _connection(session, connection)
    for changes in ({"version": 99}, {"status": "revoked"}, {"brand_id": uuid4()}):
        with pytest.raises(AdAccountUnavailable):
            _persist_observations(
                tenant, replace(original, **changes), (), now=datetime.now(UTC), api_version="v26.0"
            )


def test_purge_role_can_erase_new_metadata_and_ciphertext_only_in_its_tenant(account_world) -> None:
    from qualify_api.connections.purge import _DELETE_DIRECT

    tenant, brand, user, connection = account_world
    _observe(tenant, connection)
    assert {"ad_accounts", "ad_oauth_credentials"} <= set(_DELETE_DIRECT)
    for table in ("ad_accounts", "ad_oauth_credentials"):
        with connection_purge_session(uuid4()) as session:
            assert (
                session.execute(
                    text(f"DELETE FROM {table} WHERE connection_id=:cid"), {"cid": connection}
                ).rowcount
                == 0
            )
        with connection_purge_session(tenant) as session:
            assert (
                session.execute(
                    text(f"DELETE FROM {table} WHERE connection_id=:cid"), {"cid": connection}
                ).rowcount
                > 0
            )


@pytest.mark.asyncio
async def test_binding_uses_only_selected_brand_and_never_swaps_to_new_credential(
    account_world, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from qualify_api.ads import account_health
    from qualify_api.connections import ad_accounts

    tenant, brand, user, connection = account_world
    _observe(tenant, connection)
    chosen = list_ad_accounts(tenant_id=tenant, connection_id=connection)[0]
    select_ad_account(tenant_id=tenant, connection_id=connection, ad_account_id=chosen.id)
    versions = []

    class Client:
        async def aclose(self) -> None:
            pass

    async def client_for(tid: UUID, cid: UUID, *, expected_version: int) -> Client:
        assert (tid, cid) == (tenant, connection)
        versions.append(expected_version)
        return Client()

    async def observations(self, instagram_id: str) -> tuple[AdAccountObservation, ...]:
        assert instagram_id == "42"
        return (
            AdAccountObservation(
                chosen.ad_account_id, "Account", "COP", "America/Bogota", 1, 0, True, True, "8"
            ),
        )

    monkeypatch.setattr(ad_accounts, "_authenticated_client", client_for)
    monkeypatch.setattr(ad_accounts.GraphAdAccountReader, "list_accounts", observations)

    async def verified_health(**kwargs):
        return SimpleNamespace(can_promote=True, reason="")

    monkeypatch.setattr(account_health, "refresh_account_health", verified_health)
    binding = ad_accounts.PostgresAccountBinding()
    access = await binding.resolve(tenant, brand, chosen.ad_account_id)
    assert access.brand_id == brand and access.currency == "COP"
    assert versions == [1, 1]
    with pytest.raises(AdAccountUnavailable):
        await binding.resolve(tenant, uuid4(), chosen.ad_account_id)

    async def reconnect_on_final(tid: UUID, cid: UUID, *, expected_version: int) -> Client:
        versions.append(expected_version)
        if len(versions) == 4:
            with tenant_session(tenant) as session:
                session.execute(
                    text(
                        "UPDATE social_connections SET current_credential_version=2 WHERE id=:cid"
                    ),
                    {"cid": connection},
                )
        return Client()

    monkeypatch.setattr(ad_accounts, "_authenticated_client", reconnect_on_final)
    with pytest.raises(AdAccountUnavailable):
        await binding.resolve(tenant, brand, chosen.ad_account_id)
    assert versions == [1, 1, 1, 1]


def test_unbranded_connection_requires_explicit_same_tenant_brand_and_invalidates_snapshot(
    account_world,
) -> None:
    tenant, brand, user, connection = account_world
    _observe(tenant, connection)
    chosen = list_ad_accounts(tenant_id=tenant, connection_id=connection)[0]
    select_ad_account(tenant_id=tenant, connection_id=connection, ad_account_id=chosen.id)
    other_tenant, foreign_brand, second_brand = uuid4(), uuid4(), uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=other_tenant,
                name="Other",
                country="CO",
                timezone="America/Bogota",
                currency="COP",
            )
        )
        session.flush()
        session.add_all(
            [
                Brand(id=foreign_brand, tenant_id=other_tenant, name="Foreign"),
                Brand(id=second_brand, tenant_id=tenant, name="Second"),
            ]
        )
    with tenant_session(tenant) as session:
        session.execute(
            text("UPDATE social_connections SET brand_id=NULL WHERE id=:cid"), {"cid": connection}
        )
    assert {b.id for b in list_ad_brands(tenant_id=tenant)} == {brand, second_brand}
    assert ad_account_availability(tenant_id=tenant, connection_id=connection).brand_id is None
    with pytest.raises(AdAccountUnavailable):
        assign_ad_brand(tenant_id=tenant, connection_id=connection, brand_id=foreign_brand)
    assign_ad_brand(tenant_id=tenant, connection_id=connection, brand_id=second_brand)
    assign_ad_brand(tenant_id=tenant, connection_id=connection, brand_id=second_brand)
    with tenant_session(tenant) as session:
        assert (
            session.scalar(
                text("SELECT brand_id FROM social_connections WHERE id=:cid"), {"cid": connection}
            )
            == second_brand
        )
        assert (
            session.scalar(
                text(
                    "SELECT count(*) FROM ad_accounts WHERE connection_id=:cid "
                    "AND (selected OR available)"
                ),
                {"cid": connection},
            )
            == 0
        )
    with pytest.raises(AdAccountUnavailable):
        assign_ad_brand(tenant_id=tenant, connection_id=connection, brand_id=brand)

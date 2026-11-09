"""RLS, sanitized persistence, out-of-order refresh fencing and wizard admission."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.connection_purge import connection_purge_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from qualify_api.ads import account_health
from qualify_api.ads.account_health import (
    _save,
    _target,
    get_account_health,
    refresh_account_health,
)
from qualify_api.ads.health_models import HealthObservation
from qualify_api.connections.ad_accounts import (
    AdAccountObservation,
    AdAccountUnavailable,
    PostgresAdsGrantRecorder,
    _connection,
    _persist_observations,
    list_ad_accounts,
    select_ad_account,
)
from qualify_api.connections.crypto import DevEncryptor
from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.tenancy.models import Brand, Tenant, TenantMember, User

pytestmark = pytest.mark.db


@pytest.fixture
def health_world() -> tuple[UUID, UUID, UUID]:
    tenant, brand, user, connection = uuid4(), uuid4(), uuid4(), uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant, name="Health", country="CO", timezone="America/Bogota", currency="COP"
            )
        )
        session.flush()
        app = PlatformApp(app_id=str(uuid4()), secret_ref="test", api_version="v26.0")
        session.add_all(
            [
                app,
                Brand(id=brand, tenant_id=tenant, name="Health brand"),
                User(id=user, tenant_id=tenant, email=f"{user}@test.invalid", display_name="Owner"),
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
        ciphertext=encryptor.encrypt("FIXTURE_ONLY"),
        key_id=encryptor.key_id,
        granted_scopes=("ads_management",),
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    with tenant_session(tenant) as session:
        original = _connection(session, connection)
    _persist_observations(
        tenant,
        original,
        (
            AdAccountObservation(
                "12", "Health account", "COP", "America/Bogota", 1, 0, True, True, "8"
            ),
        ),
        now=datetime.now(UTC),
        api_version="v26.0",
    )
    account = list_ad_accounts(tenant_id=tenant, connection_id=connection)[0]
    select_ad_account(tenant_id=tenant, connection_id=connection, ad_account_id=account.id)
    return tenant, connection, account.id


class Reader:
    def __init__(self, *, pending: bool = False, failed: bool = False) -> None:
        self.pending, self.failed, self.calls = pending, failed, 0

    async def read(self, target):
        self.calls += 1
        if self.failed:
            raise AdAccountUnavailable("No pudimos comprobar la cuenta.")
        return HealthObservation(
            "COP",
            1,
            0,
            True,
            None,
            None,
            pending_billing=self.pending,
            amount_spent_raw="1234",
            spend_cap_raw="0",
        )


@pytest.mark.asyncio
async def test_health_cache_is_daily_minimal_and_tenant_isolated(health_world) -> None:
    tenant, connection, account = health_world
    reader = Reader()
    health = await refresh_account_health(tenant_id=tenant, ad_account_id=account, reader=reader)
    assert health.can_promote and health.checked_at and reader.calls == 1
    cached = await refresh_account_health(tenant_id=tenant, ad_account_id=account, reader=reader)
    assert cached.checked_at == health.checked_at and reader.calls == 1
    with tenant_session(tenant) as session:
        snapshot = session.scalar(
            text("SELECT health_snapshot FROM ad_accounts WHERE id=:id"), {"id": account}
        )
        assert snapshot["amount_spent_raw"] == "1234"
        assert "funding_source" not in snapshot and "card_number" not in snapshot
    with pytest.raises(AdAccountUnavailable):
        get_account_health(tenant_id=uuid4(), ad_account_id=account)
    with tenant_session(uuid4()) as session:
        assert (
            session.execute(
                text("UPDATE ad_accounts SET health_read_failed=true WHERE id=:id"), {"id": account}
            ).rowcount
            == 0
        )
    with pytest.raises(IntegrityError), tenant_session(tenant) as session:
        session.execute(
            text(
                "UPDATE ad_accounts SET health_snapshot='{"
                + '"card_number":"bad"'
                + "}'::jsonb WHERE id=:id"
            ),
            {"id": account},
        )
    with connection_purge_session(tenant) as session:
        assert (
            session.execute(
                text("DELETE FROM ad_accounts WHERE connection_id=:id"), {"id": connection}
            ).rowcount
            == 1
        )


@pytest.mark.asyncio
async def test_failure_retains_observation_time_and_never_leaves_ready(health_world) -> None:
    tenant, _, account = health_world
    before = await refresh_account_health(tenant_id=tenant, ad_account_id=account, reader=Reader())
    after = await refresh_account_health(
        tenant_id=tenant, ad_account_id=account, force=True, reader=Reader(failed=True)
    )
    assert after.checked_at == before.checked_at
    assert after.refresh_error and not after.can_promote and after.tone == "warn"


def test_out_of_order_selection_currency_and_reconnect_fence_reads(health_world) -> None:
    tenant, connection, account = health_world
    first = _target(tenant, account, claim=True)
    second = _target(tenant, account, claim=True)
    observation = HealthObservation("COP", 1, 0, True, None, None)
    with pytest.raises(AdAccountUnavailable):
        _save(first, observation)
    _save(second, observation)
    for update in ("selected=false", "currency='USD'", "available=false"):
        request = _target(tenant, account, claim=True)
        with tenant_session(tenant) as session:
            session.execute(
                text("UPDATE ad_accounts SET " + update + " WHERE id=:id"), {"id": account}
            )
        with pytest.raises(AdAccountUnavailable):
            _save(request, observation)
        with tenant_session(tenant) as session:
            session.execute(
                text(
                    "UPDATE ad_accounts SET selected=true,currency='COP',available=true "
                    "WHERE id=:id"
                ),
                {"id": account},
            )
    request = _target(tenant, account, claim=True)
    with tenant_session(tenant) as session:
        session.execute(
            text("UPDATE social_connections SET current_credential_version=2 WHERE id=:id"),
            {"id": connection},
        )
    with pytest.raises(AdAccountUnavailable):
        _save(request, observation)


@pytest.mark.asyncio
async def test_confirmed_billing_attention_blocks_preparation_and_metadata_cannot_erase_health(
    health_world,
) -> None:
    tenant, connection, account = health_world
    before = await refresh_account_health(
        tenant_id=tenant, ad_account_id=account, reader=Reader(pending=True)
    )
    assert before.blocks_preparation and not before.can_promote
    with tenant_session(tenant) as session:
        original = _connection(session, connection)
    _persist_observations(
        tenant,
        original,
        (AdAccountObservation("12", "Updated", "COP", "America/Bogota", 1, 0, True, True, "8"),),
        now=datetime.now(UTC),
        api_version="v26.0",
    )
    after = get_account_health(tenant_id=tenant, ad_account_id=account)
    assert after.checked_at == before.checked_at and after.blocks_preparation


@pytest.mark.asyncio
async def test_removed_actor_cannot_commit_after_remote_read(health_world, monkeypatch) -> None:
    tenant, _, account = health_world
    calls = []

    def membership(tid):
        calls.append(tid)
        if len(calls) >= 3:
            raise AdAccountUnavailable("Ya no tienes acceso.")

    monkeypatch.setattr(account_health, "require_acting_member", membership)
    with pytest.raises(AdAccountUnavailable):
        await refresh_account_health(tenant_id=tenant, ad_account_id=account, reader=Reader())
    with tenant_session(tenant) as session:
        assert (
            session.scalar(
                text("SELECT health_checked_at FROM ad_accounts WHERE id=:id"), {"id": account}
            )
            is None
        )

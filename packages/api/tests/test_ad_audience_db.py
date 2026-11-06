"""Real audience draft CAS, binding, RLS and approved promotion reconstruction."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.connection_purge import connection_purge_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from qualify_api.ads import audience_service as service
from qualify_api.ads.audience import AudienceDraft, AudienceUnavailable, LocationOption
from qualify_api.ads.enhancements import BrandEnhancementSettings, compose_brand_policy
from qualify_api.ads.promotion_repository import PostgresPromotionRepository
from qualify_api.ads.promotions import PromotionRequest
from qualify_api.connections.ad_accounts import (
    AdAccountObservation,
    PostgresAdsGrantRecorder,
    _connection,
    _persist_observations,
    list_ad_accounts,
    select_ad_account,
)
from qualify_api.connections.crypto import DevEncryptor
from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.tenancy.acting import acting_login
from qualify_api.tenancy.models import Brand, Tenant, TenantMember, User

pytestmark = pytest.mark.db


@pytest.fixture
def audience_world():
    tenant, brand, user, login, connection = (uuid4() for _ in range(5))
    now = datetime.now(UTC)
    with admin_session() as s:
        s.add(
            Tenant(
                id=tenant,
                name="Audience DB",
                country="CO",
                timezone="America/Bogota",
                currency="COP",
            )
        )
        s.flush()
        app = PlatformApp(app_id=str(uuid4()), secret_ref="test", api_version="v26.0")
        s.add_all(
            [
                app,
                Brand(id=brand, tenant_id=tenant, name="Audience brand"),
                User(
                    id=user,
                    tenant_id=tenant,
                    auth_user_id=login,
                    email=f"{user}@test.invalid",
                    display_name="Owner",
                ),
            ]
        )
        s.flush()
        app_id = app.id
        s.add(TenantMember(tenant_id=tenant, user_id=user, role="owner"))
    with tenant_session(tenant) as s:
        s.add(
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
        expires_at=now + timedelta(days=1),
    )
    with tenant_session(tenant) as s:
        original = _connection(s, connection)
    _persist_observations(
        tenant,
        original,
        (
            AdAccountObservation(
                "12", "Audience account", "COP", "America/Bogota", 1, 0, True, True, "8"
            ),
        ),
        now=now,
        api_version="v26.0",
    )
    account = list_ad_accounts(tenant_id=tenant, connection_id=connection)[0]
    select_ad_account(tenant_id=tenant, connection_id=connection, ad_account_id=account.id)
    brief, draft, attempt = uuid4(), uuid4(), uuid4()
    with tenant_session(tenant) as s:
        values = {
            "tenant": tenant,
            "brand": brand,
            "user": user,
            "connection": connection,
            "brief": brief,
            "draft": draft,
            "attempt": attempt,
            "now": now,
            "event": uuid4(),
            "key": str(uuid4()),
        }
        s.execute(
            text("""INSERT INTO content_briefs
            (id,tenant_id,brand_id,objective,topic,platform,format,intent,content_type,image_route,created_by)
            VALUES (:brief,:tenant,:brand,'sale','test','instagram','feed_4_5',
                    'organic','promotion','template_only',:user)"""),
            values,
        )
        s.execute(
            text("""INSERT INTO content_drafts
            (id,tenant_id,brand_id,brief_id,status,pipeline_version)
            VALUES (:draft,:tenant,:brand,:brief,'approved','test')"""),
            values,
        )
        s.execute(
            text("""INSERT INTO publish_attempts
            (id,tenant_id,connection_id,idempotency_key,media_product_type,
             adapter_version,status,published_media_id,settled_at)
            VALUES (:attempt,:tenant,:connection,:key,'REELS','test','published','777',:now)"""),
            values,
        )
        s.execute(
            text("""INSERT INTO calendar_events
            (id,tenant_id,brand_id,post_id,connection_id,scheduled_at,scheduled_tz,
             status,publish_attempt_id,created_by_user_id,destination)
            VALUES (:event,:tenant,:brand,:draft,:connection,:now,'America/Bogota',
                    'published',:attempt,:user,'reel')"""),
            values,
        )
    return (
        {
            "tenant_id": tenant,
            "content_draft_id": draft,
            "publish_attempt_id": attempt,
            "ad_account_id": account.id,
        },
        login,
        user,
        connection,
        brand,
    )


def selected():
    return AudienceDraft(
        LocationOption("123", "Cúcuta", "city", "CO"), placements=("instagram_story",)
    )


def test_save_load_cas_and_binding_rejection(audience_world):
    ids, login, _, connection, _ = audience_world
    with acting_login(login):
        assert service.load_audience(**ids) is None
        saved = service.save_audience(**ids, audience=selected())
        assert saved.version == 1 and service.load_audience(**ids) == saved
        changed = replace(selected(), gender="women")
        saved2 = service.save_audience(**ids, audience=changed, expected_version=1)
        assert saved2.version == 2
        with pytest.raises(AudienceUnavailable, match="otra sesión"):
            service.save_audience(**ids, audience=selected(), expected_version=1)
        for field in ("ad_account_id", "content_draft_id", "publish_attempt_id"):
            with pytest.raises(AudienceUnavailable):
                service.load_audience(**{**ids, field: uuid4()})
        with tenant_session(ids["tenant_id"]) as s:
            s.execute(
                text("UPDATE ad_accounts SET selected=false WHERE id=:id"),
                {"id": ids["ad_account_id"]},
            )
        with pytest.raises(AudienceUnavailable):
            service.save_audience(**ids, audience=selected(), expected_version=2)


def test_rls_empty_tenant_composite_fk_and_account_purge_cascade(audience_world):
    ids, login, _, connection, _ = audience_world
    with acting_login(login):
        service.save_audience(**ids, audience=selected())
    with tenant_session(uuid4()) as s:
        assert s.scalar(text("SELECT count(*) FROM ad_audience_drafts")) == 0
    with tenant_session(ids["tenant_id"]) as s:
        assert s.execute(
            text(
                "SELECT relrowsecurity,relforcerowsecurity FROM pg_class "
                "WHERE relname='ad_audience_drafts'"
            )
        ).one() == (True, True)
        s.execute(text("SELECT set_config('app.tenant_id','',true)"))
        assert s.scalar(text("SELECT count(*) FROM ad_audience_drafts")) == 0
    with pytest.raises(IntegrityError), tenant_session(ids["tenant_id"]) as s:
        s.execute(text("UPDATE ad_audience_drafts SET brand_id=:brand"), {"brand": uuid4()})
    # Deleting a connection's account through the existing restricted purge role
    # cascades its local preparatory drafts without adding broad purge privileges.
    with connection_purge_session(ids["tenant_id"]) as s:
        s.execute(text("DELETE FROM ad_accounts WHERE connection_id=:id"), {"id": connection})
    with tenant_session(ids["tenant_id"]) as s:
        assert s.scalar(text("SELECT count(*) FROM ad_audience_drafts")) == 0


def test_membership_revoked_and_source_deleted_are_rejected(audience_world):
    ids, login, user, _, _ = audience_world
    with acting_login(login):
        service.save_audience(**ids, audience=selected())
        with tenant_session(ids["tenant_id"]) as s:
            s.execute(
                text("UPDATE calendar_events SET status='cancelled' WHERE publish_attempt_id=:id"),
                {"id": ids["publish_attempt_id"]},
            )
        with pytest.raises(AudienceUnavailable):
            service.load_audience(**ids)
        with admin_session() as s:
            s.execute(
                text("DELETE FROM tenant_members WHERE tenant_id=:tenant AND user_id=:user"),
                {"tenant": ids["tenant_id"], "user": user},
            )
        from qualify_api.auth import NotAMember

        with pytest.raises(NotAMember):
            service.load_audience(**ids)


def test_calendar_connection_must_match_publication_connection(audience_world):
    ids, login, user, connection, brand = audience_world
    other = uuid4()
    with tenant_session(ids["tenant_id"]) as s:
        original = s.get(SocialConnection, connection)
        s.add(
            SocialConnection(
                id=other,
                tenant_id=ids["tenant_id"],
                brand_id=brand,
                platform_app_id=original.platform_app_id,
                platform="instagram",
                account_type="business",
                external_account_id="43",
                linked_page_id="8",
                granted_scopes=["ads_management"],
                status="active",
                access_posture="development",
                current_credential_version=1,
                connected_by_user_id=user,
            )
        )
    with tenant_session(ids["tenant_id"]) as s:
        s.execute(
            text("UPDATE calendar_events SET connection_id=:other WHERE publish_attempt_id=:id"),
            {"other": other, "id": ids["publish_attempt_id"]},
        )
    with acting_login(login), pytest.raises(AudienceUnavailable):
        service.load_audience(**ids)


def test_approved_promotion_persists_canonical_targeting_and_restores_selection(audience_world):
    ids, _, user, _, brand = audience_world
    now = datetime.now(UTC)
    audience = replace(selected(), housing=True, gender="women", age_min=30, age_max=45)
    request = PromotionRequest(
        tenant_id=ids["tenant_id"],
        brand_id=brand,
        approved_by=user,
        approved_at=now,
        request_key=str(uuid4()),
        meta_ad_account_id="12",
        objective="OUTCOME_TRAFFIC",
        cta_type="LEARN_MORE",
        link_url="https://example.org",
        budget_kind="lifetime",
        budget_minor=10000,
        currency="COP",
        start_time=now + timedelta(days=1),
        end_time=now + timedelta(days=2),
        content_draft_id=ids["content_draft_id"],
        publish_attempt_id=ids["publish_attempt_id"],
        source_media_id="777",
        special_ad_categories=("HOUSING",),
        targeting=audience.targeting(),
        audience_snapshot=audience.snapshot(),
    )
    request = compose_brand_policy(
        request, BrandEnhancementSettings(request.tenant_id, request.brand_id)
    )
    repo = PostgresPromotionRepository()
    promotion = repo.create_or_get(request)
    with tenant_session(ids["tenant_id"]) as s:
        assert (
            s.scalar(text("SELECT targeting FROM ad_promotions WHERE id=:id"), {"id": promotion.id})
            == audience.targeting()
        )
    restored = AudienceDraft.from_snapshot(
        repo.get(ids["tenant_id"], promotion.id).request["audience_snapshot"]
    )
    assert restored == audience and restored.targeting() == request.targeting

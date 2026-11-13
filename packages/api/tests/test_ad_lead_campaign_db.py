"""Lead-ad approvals bind only a published form of the promoted account (m-24828981)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads.enhancements import BrandEnhancementSettings, compose_brand_policy
from qualify_api.ads.lead_ads import LeadFormTarget, published_lead_form
from qualify_api.ads.promotion_repository import PostgresPromotionRepository
from qualify_api.ads.promotions import PromotionRequest
from qualify_api.ads.wizard import WizardUnavailable
from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.tenancy.models import Brand, Tenant, TenantMember, User

pytestmark = pytest.mark.db


@pytest.fixture
def lead_world():
    tenant, brand, user, source, published, form, unknown = (uuid4() for _ in range(7))
    ig_id = str(uuid4().int)
    now = datetime.now(UTC)
    with admin_session() as s:
        s.add(
            Tenant(id=tenant, name="Leads", country="CO", timezone="America/Bogota", currency="COP")
        )
        s.flush()
        app = PlatformApp(app_id=str(uuid4()), secret_ref="test", api_version="v26.0")
        s.add_all(
            [
                app,
                Brand(id=brand, tenant_id=tenant, name="Leads brand"),
                User(
                    id=user,
                    tenant_id=tenant,
                    auth_user_id=uuid4(),
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
                id=source,
                tenant_id=tenant,
                brand_id=brand,
                platform_app_id=app_id,
                platform="instagram",
                account_type="business",
                external_account_id=ig_id,
                linked_page_id="7",
                granted_scopes=["leads_retrieval"],
                status="active",
                access_posture="development",
                current_credential_version=1,
                connected_by_user_id=user,
            )
        )
        s.flush()
        s.execute(
            text("""INSERT INTO publish_attempts
                (id,tenant_id,connection_id,idempotency_key,media_product_type,
                 adapter_version,status,published_media_id,settled_at,caption)
            VALUES (:id,:tenant,:connection,:key,'REELS','test','published','777',:now,'x')"""),
            {
                "id": published,
                "tenant": tenant,
                "connection": source,
                "key": str(uuid4()),
                "now": now,
            },
        )
        for row_id, status, remote in ((form, "published", "555"), (unknown, "unknown", None)):
            s.execute(
                text("""INSERT INTO ad_lead_forms
                    (id,tenant_id,connection_id,brand_id,page_id,credential_version,draft,
                     status,meta_form_id,approved_by,approved_at,approved_snapshot,approved_hash)
                VALUES (:id,:tenant,:connection,:brand,'7',1,'{}'::jsonb,:status,:remote,
                        :user,:now,'{}'::jsonb,'h')"""),
                {
                    "id": row_id,
                    "tenant": tenant,
                    "connection": source,
                    "brand": brand,
                    "status": status,
                    "remote": remote,
                    "user": user,
                    "now": now,
                },
            )
    return dict(
        tenant=tenant,
        brand=brand,
        user=user,
        source=source,
        published=published,
        form=form,
        unknown=unknown,
        ig_id=ig_id,
        now=now,
    )


def _request(w, target: LeadFormTarget) -> PromotionRequest:
    request = PromotionRequest(
        w["tenant"],
        w["brand"],
        str(uuid4()),
        "12",
        "OUTCOME_LEADS",
        "SIGN_UP",
        "",
        "lifetime",
        10000,
        "COP",
        w["now"] + timedelta(days=1),
        w["now"] + timedelta(days=2),
        w["user"],
        w["now"],
        publish_attempt_id=w["published"],
        source_media_id="777",
        creative={
            "object_id": "7",
            "source_instagram_media_id": "777",
            "instagram_user_id": w["ig_id"],
            "call_to_action": target.call_to_action("SIGN_UP"),
        },
        adset_options=target.adset_options(),
        lead_form_snapshot=target.snapshot(),
    )
    return compose_brand_policy(
        request, BrandEnhancementSettings(request.tenant_id, request.brand_id)
    )


def test_published_form_binds_and_leads_attribute_to_the_promotion(lead_world):
    w = lead_world
    target = published_lead_form(w["tenant"], w["form"])
    assert (target.meta_form_id, target.page_id, target.connection_id) == ("555", "7", w["source"])
    promotion = PostgresPromotionRepository().create_or_get(_request(w, target))
    with tenant_session(w["tenant"]) as s:
        s.execute(
            text("UPDATE ad_promotions SET meta_ad_id='4242' WHERE id=:id"), {"id": promotion.id}
        )
        # The exact attribution lookup used by lead intake (lead_forms_service._persist).
        found = s.scalar(
            text("""SELECT id FROM ad_promotions
            WHERE meta_ad_id=:ad AND brand_id=:brand AND objective='OUTCOME_LEADS'
            AND request_snapshot->'lead_form_snapshot'->>'meta_form_id'=:remote"""),
            {"ad": "4242", "brand": w["brand"], "remote": "555"},
        )
    assert found == promotion.id


def test_unpublished_form_cannot_be_loaded_or_approved(lead_world):
    w = lead_world
    with pytest.raises(WizardUnavailable):
        published_lead_form(w["tenant"], w["unknown"])
    forged = LeadFormTarget(w["unknown"], "556", "7", w["source"], w["brand"], 1)
    with pytest.raises(ValueError):
        PostgresPromotionRepository().create_or_get(_request(w, forged))
    with tenant_session(w["tenant"]) as s:
        assert not s.scalar(text("SELECT count(*) FROM ad_promotions"))

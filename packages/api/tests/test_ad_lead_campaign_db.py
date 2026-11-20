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
from qualify_api.connections.ad_accounts import PostgresAdsGrantRecorder
from qualify_api.connections.crypto import DevEncryptor
from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.tenancy.models import Brand, Tenant, TenantMember, User

pytestmark = pytest.mark.db

SCOPES = (
    "ads_management",
    "pages_manage_ads",
    "pages_manage_metadata",
    "leads_retrieval",
    "pages_show_list",
)


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
                granted_scopes=list(SCOPES),
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
    _grant(tenant, source, 1, SCOPES)
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


def test_published_form_binds_to_the_promotion(lead_world):
    # Lead attribution through _persist: test_ad_lead_forms_db (needs a real Meta grant row).
    w = lead_world
    target = published_lead_form(w["tenant"], w["form"])
    assert (target.meta_form_id, target.page_id, target.connection_id) == ("555", "7", w["source"])
    promotion = PostgresPromotionRepository().create_or_get(_request(w, target))
    assert promotion.request["lead_form_snapshot"] == target.snapshot()


def test_unpublished_form_cannot_be_loaded_or_approved(lead_world):
    w = lead_world
    with pytest.raises(WizardUnavailable):
        published_lead_form(w["tenant"], w["unknown"])
    forged = LeadFormTarget(w["unknown"], "556", "7", w["source"], w["brand"], 1)
    with pytest.raises(ValueError):
        PostgresPromotionRepository().create_or_get(_request(w, forged))
    with tenant_session(w["tenant"]) as s:
        assert not s.scalar(text("SELECT count(*) FROM ad_promotions"))


def _grant(tenant, connection, version: int, scopes: tuple[str, ...]) -> None:
    encryptor = DevEncryptor()
    PostgresAdsGrantRecorder().record(
        tenant_id=tenant,
        connection_id=connection,
        version=version,
        ciphertext=encryptor.encrypt("SYNTHETIC_USER_TOKEN"),
        key_id=encryptor.key_id,
        granted_scopes=scopes,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )


def _renew(w, change: str = "", scopes: tuple[str, ...] = SCOPES) -> None:
    """A token renewal: version 2 with its own grant, then any other connection change
    (after the grant: the recorder refuses a connection already being purged)."""
    for sql in ("current_credential_version=2", change):
        if sql:
            with tenant_session(w["tenant"]) as s:
                s.execute(
                    text(f"UPDATE social_connections SET {sql} WHERE id=:id"), {"id": w["source"]}
                )
        if sql.startswith("current_credential_version"):
            _grant(w["tenant"], w["source"], 2, scopes)


def test_published_form_attaches_to_a_new_ad_after_a_token_renewal(lead_world):
    # m-25072366: identity, not the frozen version; the form keeps version 1 as provenance.
    w = lead_world
    _renew(w)
    target = published_lead_form(w["tenant"], w["form"])
    assert target.credential_version == 1
    promotion = PostgresPromotionRepository().create_or_get(_request(w, target))
    assert promotion.request["lead_form_snapshot"]["credential_version"] == 1


@pytest.mark.parametrize(
    "change,scopes",
    [
        ("linked_page_id='8'", SCOPES),
        ("status='revoked'", SCOPES),
        ("purge_started_at=now()", SCOPES),
        ("", tuple(s for s in SCOPES if s != "leads_retrieval")),
    ],
)
def test_renewed_form_of_another_page_a_gone_connection_or_lost_leads_scope_is_refused(
    lead_world, change, scopes
):
    w = lead_world
    target = published_lead_form(w["tenant"], w["form"])
    _renew(w, change, scopes)
    with pytest.raises(WizardUnavailable):
        published_lead_form(w["tenant"], w["form"])
    with pytest.raises(ValueError):
        PostgresPromotionRepository().create_or_get(_request(w, target))
    with tenant_session(w["tenant"]) as s:
        assert not s.scalar(text("SELECT count(*) FROM ad_promotions"))


def test_renewed_connection_moved_to_another_brand_is_refused(lead_world):
    w = lead_world
    target = published_lead_form(w["tenant"], w["form"])
    other = uuid4()
    with admin_session() as s:
        s.add(Brand(id=other, tenant_id=w["tenant"], name="Other brand"))
    _renew(w, f"brand_id='{other}'")
    with pytest.raises(WizardUnavailable):
        published_lead_form(w["tenant"], w["form"])
    with pytest.raises(ValueError):
        PostgresPromotionRepository().create_or_get(_request(w, target))

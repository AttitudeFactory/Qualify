"""Real DB preview immutability, independent claims, tenant isolation and published provenance."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session, tenant_unit_of_work
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from qualify_api.ads.activation_repository import ActivationReview, PostgresActivationRepository
from qualify_api.ads.promotion_repository import PostgresPromotionRepository
from qualify_api.ads.promotions import PromotionRequest, fingerprint
from qualify_api.ads.wizard import list_promotion_sources
from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.tenancy.models import Brand, Tenant, User

pytestmark = pytest.mark.db


def world():
    tenant, brand, user, connection = uuid4(), uuid4(), uuid4(), uuid4()
    with admin_session() as s:
        s.add(
            Tenant(
                id=tenant, name="Wizard DB", country="CO", timezone="America/Bogota", currency="COP"
            )
        )
        s.flush()
        app = PlatformApp(app_id=str(uuid4()), secret_ref="test", api_version="v26.0")
        s.add_all(
            [
                Brand(id=brand, tenant_id=tenant, name="Wizard brand"),
                User(id=user, tenant_id=tenant, email=f"{user}@test.invalid", display_name="Owner"),
                app,
            ]
        )
        s.flush()
        app_id = app.id
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
    return tenant, brand, user, connection


def review_world():
    tenant, brand, user, _ = world()
    now = datetime.now(UTC)
    req = PromotionRequest(
        tenant,
        brand,
        str(uuid4()),
        "12",
        "OUTCOME_TRAFFIC",
        "LEARN_MORE",
        "https://example.org",
        "lifetime",
        150_00,
        "COP",
        now + timedelta(days=1),
        now + timedelta(days=2),
        user,
        now,
        source_media_id="99",
    )
    promotion = PostgresPromotionRepository().create_or_get(req)
    review = ActivationReview(
        uuid4(),
        tenant,
        promotion.id,
        fingerprint(promotion.request),
        "preview",
        "preview-hash",
        {"minimum_budget_minor": 100_00},
        now + timedelta(minutes=15),
        user,
    )
    repo = PostgresActivationRepository()
    return repo, repo.create(review), now


def test_review_rls_immutable_actor_and_source_snapshot_guards() -> None:
    repo, review, now = review_world()
    other = world()
    assert repo.get(other[0], review.id) is None
    assert repo.for_promotion(other[0], review.promotion_id) is None
    assert not repo.claim(review, other[2], now, uuid4())
    assert not repo.claim(replace(review, preview_hash="changed"), review.prepared_by, now, uuid4())
    for change in (
        "preview_html='changed'",
        "request_hash='changed'",
        "expires_at=now()",
        "prepared_by=gen_random_uuid()",
        "state='active'",
    ):
        with pytest.raises(IntegrityError), tenant_session(review.tenant_id) as s:
            s.execute(
                text(f"UPDATE ad_promotion_activations SET {change} WHERE id=:id"),
                {"id": review.id},
            )
    with tenant_session(review.tenant_id) as s:
        assert s.execute(
            text(
                "SELECT relrowsecurity,relforcerowsecurity FROM pg_class "
                "WHERE relname='ad_promotion_activations'"
            )
        ).one() == (True, True)
        s.execute(text("SELECT set_config('app.tenant_id','',true)"))
        assert s.scalar(text("SELECT count(*) FROM ad_promotion_activations")) == 0


def test_confirmation_claim_survives_outer_rollback_and_cannot_reset() -> None:
    repo, review, now = review_world()
    token = uuid4()
    with pytest.raises(RuntimeError), tenant_unit_of_work(review.tenant_id):
        assert repo.claim(review, review.prepared_by, now, token)
        raise RuntimeError("outer rollback")
    saved = repo.get(review.tenant_id, review.id)
    assert saved.state == "in_flight" and saved.confirmed_by == review.prepared_by
    assert not repo.claim(review, review.prepared_by, now, uuid4())
    repo.finish(review.tenant_id, review.id, uuid4(), "active")
    assert repo.get(review.tenant_id, review.id).state == "in_flight"
    repo.finish(review.tenant_id, review.id, token, "unknown")
    with pytest.raises(IntegrityError), tenant_session(review.tenant_id) as s:
        s.execute(
            text("UPDATE ad_promotion_activations SET state='ready' WHERE id=:id"),
            {"id": review.id},
        )
    repo.finish(review.tenant_id, review.id, token, "active")
    assert repo.get(review.tenant_id, review.id).state == "active"
    assert (
        PostgresPromotionRepository().get(review.tenant_id, review.promotion_id).status == "active"
    )


def test_concurrent_confirmation_has_one_claim_and_expired_review_cannot_claim() -> None:
    repo, review, now = review_world()
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(lambda _: repo.claim(review, review.prepared_by, now, uuid4()), range(2))
        )
    assert sorted(outcomes) == [False, True]
    repo, review, now = review_world()
    assert not repo.claim(review, review.prepared_by, now + timedelta(minutes=16), uuid4())


def test_source_list_requires_exact_published_instagram_draft_brand_event() -> None:
    tenant, brand, user, connection = world()
    brief, draft, attempt, event = uuid4(), uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    with tenant_session(tenant) as s:
        s.execute(
            text("""INSERT INTO content_briefs
            (id,tenant_id,brand_id,objective,topic,platform,format,intent,content_type,image_route,created_by)
            VALUES (:id,:tid,:bid,'sale','test','instagram','feed_4_5','organic','promotion',
                    'template_only',:uid)"""),
            {"id": brief, "tid": tenant, "bid": brand, "uid": user},
        )
        s.execute(
            text("""INSERT INTO content_drafts
            (id,tenant_id,brand_id,brief_id,status,pipeline_version)
            VALUES (:id,:tid,:bid,:brief,'approved','test')"""),
            {"id": draft, "tid": tenant, "bid": brand, "brief": brief},
        )
        s.execute(
            text("""INSERT INTO publish_attempts
            (id,tenant_id,connection_id,idempotency_key,media_product_type,adapter_version,status,
             published_media_id,settled_at,caption)
            VALUES (:id,:tid,:cid,:key,'REELS','test','published','777',:now,'Published copy')"""),
            {"id": attempt, "tid": tenant, "cid": connection, "key": str(uuid4()), "now": now},
        )
        s.execute(
            text("""INSERT INTO calendar_events
            (id,tenant_id,brand_id,post_id,connection_id,scheduled_at,scheduled_tz,status,
             publish_attempt_id,created_by_user_id,destination)
            VALUES (:id,:tid,:bid,:draft,:cid,:now,'America/Bogota',
                    'published',:attempt,:uid,'reel')"""),
            {
                "id": event,
                "tid": tenant,
                "bid": brand,
                "draft": draft,
                "cid": connection,
                "now": now,
                "attempt": attempt,
                "uid": user,
            },
        )
    assert len(list_promotion_sources(tenant_id=tenant, content_draft_id=draft)) == 1
    source = list_promotion_sources(
        tenant_id=tenant, content_draft_id=draft, calendar_event_id=event
    )[0]
    assert source.caption == "Published copy" and source.source_media_id == "777"
    assert source.meta_ad_account_id == "" and source.unavailable_reason
    assert not list_promotion_sources(tenant_id=uuid4(), content_draft_id=draft)
    assert not list_promotion_sources(
        tenant_id=tenant, content_draft_id=draft, calendar_event_id=uuid4()
    )
    with tenant_session(tenant) as s:
        s.execute(
            text("UPDATE calendar_events SET destination='story' WHERE id=:id"), {"id": event}
        )
    assert not list_promotion_sources(tenant_id=tenant, content_draft_id=draft)

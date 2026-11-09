"""Real PostgreSQL RLS, write-ahead durability and immutable promotion intents."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session, tenant_unit_of_work
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from qualify_api.ads.enhancements import BrandEnhancementSettings, compose_brand_policy
from qualify_api.ads.promotion_repository import PostgresPromotionRepository, RequestConflict
from qualify_api.ads.promotions import PromotionRequest, step_payload
from qualify_api.tenancy.models import Brand, Tenant, User

pytestmark = pytest.mark.db


def _request() -> PromotionRequest:
    tenant, brand, user = uuid4(), uuid4(), uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant,
                name="Ads isolation test",
                country="CO",
                timezone="America/Bogota",
                currency="COP",
            )
        )
        session.flush()
        session.add_all(
            [
                Brand(id=brand, tenant_id=tenant, name="Ads brand"),
                User(
                    id=user,
                    tenant_id=tenant,
                    email=f"ads-{user}@test.invalid",
                    display_name="Ads approver",
                ),
            ]
        )
    now = datetime.now(UTC)
    result = PromotionRequest(
        tenant_id=tenant,
        brand_id=brand,
        approved_by=user,
        request_key=str(uuid4()),
        meta_ad_account_id="12",
        objective="OUTCOME_TRAFFIC",
        cta_type="LEARN_MORE",
        link_url="https://example.org",
        budget_kind="daily",
        budget_minor=1000,
        currency="COP",
        start_time=now,
        end_time=now + timedelta(days=2),
        approved_at=now,
        source_media_id="99",
    )

    return compose_brand_policy(result, BrandEnhancementSettings(tenant, brand))


def test_create_request_idempotency_rls_cross_brand_and_approver_guards() -> None:
    req, other = _request(), _request()
    repo = PostgresPromotionRepository()
    row = repo.create_or_get(req)
    assert repo.create_or_get(req) == row
    assert repo.get(other.tenant_id, row.id) is None
    with pytest.raises(RequestConflict):
        repo.create_or_get(replace(req, budget_minor=2000))
    for changes in ({"brand_id": other.brand_id}, {"approved_by": other.approved_by}):
        with pytest.raises(ValueError):
            repo.create_or_get(replace(req, request_key=str(uuid4()), **changes))
    # Composite FK rejects direct SQL that RLS alone would allow.
    with pytest.raises(IntegrityError), tenant_session(req.tenant_id) as session:
        session.execute(
            text(
                "INSERT INTO ad_promotions SELECT "
                "gen_random_uuid(), tenant_id, :brand, :key, request_hash, request_snapshot, "
                "meta_ad_account_id, content_draft_id, publish_attempt_id, source_media_id, "
                "objective, special_ad_categories, cta_type, link_url, budget_kind, budget_minor, "
                "currency, start_time, end_time, targeting, meta_campaign_id, meta_adset_id, "
                "meta_creative_id, meta_ad_id, status, effective_status, review_feedback, "
                "approved_by, approved_at, adapter_version, created_at "
                "FROM ad_promotions WHERE id=:id"
            ),
            {"brand": other.brand_id, "key": str(uuid4()), "id": row.id},
        )


def test_claim_commits_before_outer_uow_rolls_back_and_cas_fences_completion() -> None:
    req, other = _request(), _request()
    repo = PostgresPromotionRepository()
    row = repo.create_or_get(req)
    token = uuid4()
    with pytest.raises(RuntimeError), tenant_unit_of_work(req.tenant_id):
        assert repo.claim(req.tenant_id, row.id, "campaigns", step_payload(row, "campaigns"), token)
        raise RuntimeError("surrounding business operation failed")
    step = repo.step(req.tenant_id, row.id, "campaigns")
    assert step is not None and step.claim_token == token and step.state == "in_flight"
    assert repo.step(other.tenant_id, row.id, "campaigns") is None
    assert not repo.claim(req.tenant_id, row.id, "campaigns", step.payload, uuid4())
    assert not repo.complete(req.tenant_id, row.id, "campaigns", uuid4(), "111")
    assert not repo.complete(other.tenant_id, row.id, "campaigns", token, "111")
    assert repo.complete(req.tenant_id, row.id, "campaigns", token, "111")
    assert not repo.complete(req.tenant_id, row.id, "campaigns", token, "222")
    assert repo.get(req.tenant_id, row.id).ids == {"campaigns": "111"}


def test_approval_and_creation_intents_cannot_be_changed_or_reset() -> None:
    req = _request()
    repo = PostgresPromotionRepository()
    row = repo.create_or_get(req)
    token = uuid4()
    assert repo.claim(req.tenant_id, row.id, "campaigns", step_payload(row, "campaigns"), token)
    for query in (
        "UPDATE ad_promotions SET budget_minor=2000 WHERE id=:id",
        "UPDATE ad_promotions SET request_snapshot='{}'::jsonb WHERE id=:id",
        "UPDATE ad_promotion_steps SET payload='{}'::jsonb WHERE promotion_id=:id",
        "UPDATE ad_promotion_steps SET claim_token=gen_random_uuid() WHERE promotion_id=:id",
        "UPDATE ad_promotion_steps SET state='completed' WHERE promotion_id=:id",
    ):
        with pytest.raises(IntegrityError), tenant_session(req.tenant_id) as session:
            session.execute(text(query), {"id": row.id})
    assert repo.complete(req.tenant_id, row.id, "campaigns", token, "112")
    with pytest.raises(IntegrityError), tenant_session(req.tenant_id) as session:
        session.execute(
            text("UPDATE ad_promotions SET meta_campaign_id='113' WHERE id=:id"), {"id": row.id}
        )


def test_schema_rls_enable_force_and_unset_context_fails_closed() -> None:
    req = _request()
    row = PostgresPromotionRepository().create_or_get(req)
    with tenant_session(req.tenant_id) as session:
        tables = session.execute(
            text(
                "SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class "
                "WHERE relname IN ('ad_promotions','ad_promotion_steps')"
            )
        ).all()
        assert len(tables) == 2 and all(r[1] and r[2] for r in tables)
        session.execute(text("SELECT set_config('app.tenant_id','',true)"))
        assert (
            session.execute(
                text("SELECT id FROM ad_promotions WHERE id=:id"), {"id": row.id}
            ).first()
            is None
        )

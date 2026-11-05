"""Real durable results, pause audit, tenant isolation and credential-race checks."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads import results_service as service
from qualify_api.ads.errors import MarketingError
from qualify_api.ads.fake import FakeMarketingClient
from qualify_api.ads.promotion_repository import PostgresPromotionRepository
from qualify_api.ads.promotions import ADAPTER_VERSION, PromotionRequest, fingerprint
from qualify_api.ads.results import ResultsUnavailable
from qualify_api.ads.results_management import (
    PromotionEdit,
    VerifiedEditApproval,
    apply_verified_edit,
    edit_scope_hash,
)
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
PUBLISHED_CAPTION = "Texto original de la publicación. " * 10


@pytest.fixture
def audience_world():
    tenant, brand, user, login, connection = (uuid4() for _ in range(5))
    account_remote = str(uuid4().int)
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
                account_remote, "Audience account", "COP", "America/Bogota", 1, 0, True, True, "8"
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
             adapter_version,status,published_media_id,settled_at,caption)
            VALUES (:attempt,:tenant,:connection,:key,'REELS','test','published','777',:now,
                    :caption)"""),
            {**values, "caption": PUBLISHED_CAPTION},
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
            "meta_account_id": account_remote,
        },
        login,
        user,
        connection,
        brand,
    )


@pytest.fixture
def result_world(audience_world, request: pytest.FixtureRequest):
    ids, login, user, connection, brand = audience_world
    now = datetime.now(UTC)
    source_media_id = getattr(request, "param", "777")
    request = PromotionRequest(
        tenant_id=ids["tenant_id"],
        brand_id=brand,
        approved_by=user,
        approved_at=now,
        request_key=str(uuid4()),
        meta_ad_account_id=ids["meta_account_id"],
        objective="OUTCOME_TRAFFIC",
        cta_type="LEARN_MORE",
        link_url="https://example.org",
        budget_kind="lifetime",
        budget_minor=10000,
        currency="COP",
        start_time=now - timedelta(days=2),
        end_time=now + timedelta(days=2),
        content_draft_id=ids["content_draft_id"],
        publish_attempt_id=ids["publish_attempt_id"],
        source_media_id=source_media_id,
    )
    repository = PostgresPromotionRepository()
    if source_media_id == "777":
        promotion = repository.create_or_get(request)
    else:
        # Exercise defensive reads of a legacy inconsistent row without weakening
        # repository provenance validation or changing an immutable approval.
        with pytest.raises(ValueError, match="published provenance does not match"):
            repository.create_or_get(request)
        snapshot = request.snapshot()
        values = {**snapshot, "request_hash": fingerprint(snapshot), "adapter": ADAPTER_VERSION}
        values["snapshot"] = json.dumps(snapshot)
        for name in ("special_ad_categories", "targeting"):
            values[name] = json.dumps(values[name])
        with tenant_session(ids["tenant_id"]) as s:
            s.execute(
                text("""INSERT INTO ad_promotions
                (tenant_id,brand_id,request_key,request_hash,request_snapshot,meta_ad_account_id,
                 content_draft_id,publish_attempt_id,source_media_id,objective,special_ad_categories,
                 cta_type,link_url,budget_kind,budget_minor,currency,start_time,end_time,targeting,
                 approved_by,approved_at,adapter_version)
                VALUES (:tenant_id,:brand_id,:request_key,:request_hash,CAST(:snapshot AS jsonb),
                        :meta_ad_account_id,:content_draft_id,:publish_attempt_id,:source_media_id,
                        :objective,CAST(:special_ad_categories AS jsonb),:cta_type,:link_url,
                        :budget_kind,:budget_minor,:currency,:start_time,:end_time,
                        CAST(:targeting AS jsonb),:approved_by,:approved_at,:adapter)"""),
                values,
            )
        promotion = repository.by_request_key(ids["tenant_id"], request.request_key)
        assert promotion is not None
    with tenant_session(ids["tenant_id"]) as s:
        s.execute(
            text(
                "UPDATE ad_promotions SET meta_campaign_id='1',meta_adset_id='2',"
                "meta_ad_id='3' WHERE id=:id"
            ),
            {"id": promotion.id},
        )
    api = FakeMarketingClient(account_id=ids["meta_account_id"])
    api.objects["3"] = {
        "id": "3",
        "account_id": ids["meta_account_id"],
        "campaign_id": "1",
        "adset_id": "2",
        "status": "ACTIVE",
        "effective_status": "ACTIVE",
        "_resource": "ads",
    }
    day = (now.astimezone(ZoneInfo("America/Bogota")) - timedelta(days=1)).date().isoformat()
    api.responses["GET", "3/insights"] = {
        "data": [
            {
                "ad_id": "3",
                "account_id": ids["meta_account_id"],
                "account_currency": "COP",
                "date_start": day,
                "date_stop": day,
                "spend": "1523.45",
                "clicks": "7",
                "reach": "40",
            }
        ]
    }
    return ids, login, user, connection, promotion, api


@pytest.mark.asyncio
async def test_cached_yesterday_metrics_tenant_isolation_and_no_implicit_http(result_world):
    ids, login, _, _, promotion, api = result_world
    with acting_login(login):
        initial = service.load_promotion_results(
            tenant_id=ids["tenant_id"], promotion_id=promotion.id
        )
        assert initial.promotion.status == "UNKNOWN" and initial.daily == ()
        result = await service._refresh(ids["tenant_id"], promotion.id, api=api)
        assert str(result.daily[0].spend) == "1523.45" and result.daily[0].clicks == 7
        assert result.daily[0].impressions is None and result.promotion.can_pause
        calls = len(api.calls)
        assert len(service.list_promotion_results(tenant_id=ids["tenant_id"])) == 1
        assert len(api.calls) == calls
    with tenant_session(uuid4()) as s:
        for table in (
            "ad_promotion_observations",
            "ad_promotion_insights",
            "ad_promotion_operations",
        ):
            assert s.scalar(text(f"SELECT count(*) FROM {table}")) == 0
    with tenant_session(ids["tenant_id"]) as s:
        s.execute(text("SELECT set_config('app.tenant_id','',true)"))
        assert s.scalar(text("SELECT count(*) FROM ad_promotion_observations")) == 0


@pytest.mark.asyncio
async def test_pause_audit_idempotency_and_immutable_approval(result_world):
    ids, login, user, _, promotion, api = result_world
    with acting_login(login):
        await service._refresh(ids["tenant_id"], promotion.id, api=api)
        await service._pause(ids["tenant_id"], promotion.id, "intent-1", api=api)
        await service._pause(ids["tenant_id"], promotion.id, "intent-1", api=api)
        assert len([c for c in api.calls if c[0] == "POST"]) == 1
        with pytest.raises(ResultsUnavailable, match="treinta"):
            await service._pause(ids["tenant_id"], promotion.id, "intent-2", api=api)
    with tenant_session(ids["tenant_id"]) as s:
        row = (
            s.execute(
                text("SELECT * FROM ad_promotion_operations WHERE promotion_id=:id"),
                {"id": promotion.id},
            )
            .mappings()
            .one()
        )
        assert row["actor_id"] == user and row["state"] == "completed"
        assert row["created_at"] and row["finished_at"]
        assert row["payload"] == {"status": "PAUSED"}
        assert (
            s.scalar(
                text("SELECT request_snapshot FROM ad_promotions WHERE id=:id"),
                {"id": promotion.id},
            )
            == promotion.request
        )


@pytest.mark.asyncio
async def test_unknown_pause_never_retried_and_read_reconciles_only_configured_pause(result_world):
    ids, login, _, _, promotion, api = result_world
    original_update = api.update

    async def uncertain(*args, **kwargs):
        await original_update(*args, **kwargs)
        raise MarketingError("fixture", outcome_unknown=True)

    api.update = uncertain
    with acting_login(login):
        with pytest.raises(ResultsUnavailable):
            await service._pause(ids["tenant_id"], promotion.id, "intent-1", api=api)
        with pytest.raises(ResultsUnavailable):
            await service._pause(ids["tenant_id"], promotion.id, "intent-1", api=api)
        assert len([c for c in api.calls if c[0] == "POST"]) == 1
        with tenant_session(ids["tenant_id"]) as s:
            s.execute(
                text(
                    "UPDATE ad_promotion_operations SET created_at=now()-interval '2 minutes', "
                    "dispatched_at=now()-interval '2 minutes' "
                    "WHERE promotion_id=:id"
                ),
                {"id": promotion.id},
            )
        api.objects["3"]["status"] = "ACTIVE"
        api.objects["3"]["effective_status"] = "CAMPAIGN_PAUSED"
        await service._refresh(ids["tenant_id"], promotion.id, api=api)
        with tenant_session(ids["tenant_id"]) as s:
            assert (
                s.scalar(
                    text("SELECT state FROM ad_promotion_operations WHERE promotion_id=:id"),
                    {"id": promotion.id},
                )
                == "unknown"
            )
        api.objects["3"]["status"] = "PAUSED"
        await service._refresh(ids["tenant_id"], promotion.id, api=api)
        with tenant_session(ids["tenant_id"]) as s:
            assert (
                s.scalar(
                    text("SELECT state FROM ad_promotion_operations WHERE promotion_id=:id"),
                    {"id": promotion.id},
                )
                == "reconciled"
            )


@pytest.mark.asyncio
async def test_stale_credential_result_and_pending_refresh_do_not_commit(result_world):
    ids, login, _, connection, promotion, api = result_world
    original = api.insights

    async def changed(*args, **kwargs):
        page = await original(*args, **kwargs)
        with tenant_session(ids["tenant_id"]) as s:
            s.execute(
                text("UPDATE social_connections SET current_credential_version=2 WHERE id=:id"),
                {"id": connection},
            )
        return page

    api.insights = changed
    with acting_login(login):
        with pytest.raises(ResultsUnavailable):
            await service._refresh(ids["tenant_id"], promotion.id, api=api)
        result = service.load_promotion_results(
            tenant_id=ids["tenant_id"], promotion_id=promotion.id
        )
        assert result.promotion.status == "UNKNOWN" and result.daily == ()


@pytest.mark.asyncio
async def test_refresh_cas_and_missing_days_never_keep_old_metrics(result_world):
    ids, login, _, _, promotion, api = result_world
    with acting_login(login):
        await service._refresh(ids["tenant_id"], promotion.id, api=api)
        scope = service._scope(ids["tenant_id"], promotion.id)
        token = service._claim_refresh(scope, datetime.now(UTC))
        service._claim_refresh(scope, datetime.now(UTC))
        with pytest.raises(ResultsUnavailable):
            service._save_observation(scope, token, "ACTIVE", "ACTIVE", (), datetime.now(UTC))
        api.responses["GET", "3/insights"] = {"data": []}
        result = await service._refresh(ids["tenant_id"], promotion.id, api=api)
        assert result.daily == ()


@pytest.mark.asyncio
async def test_rejection_survives_unavailable_insights_and_no_raw_remote_text(result_world):
    ids, login, _, _, promotion, api = result_world
    api.objects["3"].update(
        effective_status="DISAPPROVED", ad_review_feedback={"untrusted": "SECRET_TOKEN"}
    )

    async def failed(*args, **kwargs):
        raise MarketingError("fixture")

    api.insights = failed
    with acting_login(login):
        with pytest.raises(ResultsUnavailable):
            await service._refresh(ids["tenant_id"], promotion.id, api=api)
        result = service.load_promotion_results(
            tenant_id=ids["tenant_id"], promotion_id=promotion.id
        )
        assert result.promotion.status_label == "Rechazado por Meta"
        assert "SECRET_TOKEN" not in repr(result)


@pytest.mark.asyncio
async def test_injected_paid_budget_edit_audited_but_production_wrapper_disabled(result_world):
    ids, login, user, _, promotion, api = result_world
    edit = PromotionEdit("budget", "lifetime", 20000)
    now = datetime.now(UTC)
    api.objects["2"] = {"id": "2", "_resource": "adsets"}

    class FixtureApprovals:
        async def verify(self, scope, requested):
            return VerifiedEditApproval(
                scope.tenant_id,
                scope.promotion_id,
                scope.account_id,
                scope.connection.version,
                login,
                fingerprint({"action": edit.action, "payload": edit.payload()}),
                now + timedelta(minutes=1),
                True,
                True,
                True,
                "lifetime",
                1000,
                100,
                now - timedelta(days=1),
                "fixture-only-v1",
                edit_scope_hash(scope),
            )

    with acting_login(login):
        with pytest.raises(ResultsUnavailable):
            await service.edit_promotion(
                tenant_id=ids["tenant_id"],
                promotion_id=promotion.id,
                action="budget",
                request_key="paid",
                budget_minor=20000,
            )
        await apply_verified_edit(
            tenant_id=ids["tenant_id"],
            promotion_id=promotion.id,
            request_key="paid",
            edit=edit,
            api=api,
            approvals=FixtureApprovals(),
        )
    with tenant_session(ids["tenant_id"]) as s:
        row = (
            s.execute(
                text("SELECT * FROM ad_promotion_operations WHERE promotion_id=:id"),
                {"id": promotion.id},
            )
            .mappings()
            .one()
        )
        assert row["actor_id"] == user and row["payload"] == {"lifetime_budget": 20000}
        assert row["action"] == "budget" and row["approval_evidence"]["confirmed"] is True
        assert (
            s.scalar(
                text("SELECT request_snapshot FROM ad_promotions WHERE id=:id"),
                {"id": promotion.id},
            )
            == promotion.request
        )


@pytest.mark.asyncio
async def test_membership_revocation_blocks_reads_and_pause(result_world):
    ids, login, user, _, promotion, api = result_world
    with admin_session() as s:
        s.execute(
            text("DELETE FROM tenant_members WHERE tenant_id=:tenant AND user_id=:user"),
            {"tenant": ids["tenant_id"], "user": user},
        )
    from qualify_api.auth import NotAMember

    with acting_login(login), pytest.raises(NotAMember):
        await service._pause(ids["tenant_id"], promotion.id, "intent", api=api)
    assert api.calls == []


@pytest.mark.asyncio
async def test_reconciled_claim_cannot_dispatch_after_cooldown(result_world):
    ids, login, _, _, promotion, api = result_world
    with acting_login(login):
        scope = service._scope(ids["tenant_id"], promotion.id)
        operation, state = service._claim_pause(scope, "waiting", datetime.now(UTC))
        assert state == "claimed"
        with tenant_session(ids["tenant_id"]) as s:
            s.execute(
                text(
                    "UPDATE ad_promotion_operations SET created_at=now()-interval '2 minutes' "
                    "WHERE id=:id"
                ),
                {"id": operation},
            )
        api.objects["3"]["status"] = "PAUSED"
        await service._refresh(ids["tenant_id"], promotion.id, api=api)
        with pytest.raises(ResultsUnavailable, match="venció o cambió"):
            service._dispatch(scope, operation)
    assert all(call[0] == "GET" for call in api.calls)


@pytest.mark.asyncio
async def test_pause_keeps_last_daily_results_but_requires_new_status_read(result_world):
    ids, login, _, _, promotion, api = result_world
    with acting_login(login):
        before = await service._refresh(ids["tenant_id"], promotion.id, api=api)
        after = await service._pause(ids["tenant_id"], promotion.id, "pause", api=api)
        assert after.daily == before.daily and after.updated_at == before.updated_at
        assert after.promotion.stale and not after.promotion.can_pause


@pytest.mark.asyncio
async def test_paid_edit_evidence_expiring_during_cooldown_never_dispatches(result_world):
    ids, login, _, _, promotion, api = result_world
    now = datetime.now(UTC)
    edit = PromotionEdit("resume")
    times = iter([now, now, now + timedelta(minutes=2)])

    class FixtureApprovals:
        async def verify(self, scope, requested):
            return VerifiedEditApproval(
                scope.tenant_id,
                scope.promotion_id,
                scope.account_id,
                scope.connection.version,
                login,
                fingerprint({"action": edit.action, "payload": edit.payload()}),
                now + timedelta(seconds=30),
                True,
                True,
                True,
                "lifetime",
                1000,
                100,
                now - timedelta(days=1),
                "fixture-only-v1",
                edit_scope_hash(scope),
            )

    with acting_login(login), pytest.raises(ResultsUnavailable):
        await apply_verified_edit(
            tenant_id=ids["tenant_id"],
            promotion_id=promotion.id,
            request_key="resume",
            edit=edit,
            api=api,
            approvals=FixtureApprovals(),
            clock=lambda: next(times),
        )
    assert all(call[0] == "GET" for call in api.calls)


@pytest.mark.asyncio
async def test_context_change_after_write_is_unknown_audit_not_success(result_world):
    ids, login, _, connection, promotion, api = result_world
    original = api.update

    async def changed(*args, **kwargs):
        await original(*args, **kwargs)
        with tenant_session(ids["tenant_id"]) as s:
            s.execute(
                text("UPDATE ad_accounts SET selected=false WHERE connection_id=:id"),
                {"id": connection},
            )

    api.update = changed
    with acting_login(login), pytest.raises(ResultsUnavailable):
        await service._pause(ids["tenant_id"], promotion.id, "pause", api=api)
    with tenant_session(ids["tenant_id"]) as s:
        assert (
            s.scalar(
                text("SELECT state FROM ad_promotion_operations WHERE promotion_id=:id"),
                {"id": promotion.id},
            )
            == "unknown"
        )


@pytest.mark.asyncio
async def test_old_claim_with_recent_dispatch_is_not_reconciled_while_http_in_flight(result_world):
    ids, login, _, _, promotion, api = result_world
    now = datetime.now(UTC)
    with acting_login(login):
        scope = service._scope(ids["tenant_id"], promotion.id)
        operation, _ = service._claim_pause(scope, "cooldown-intent", now - timedelta(minutes=2))
        service._dispatch(scope, operation)
        api.objects["3"]["status"] = "PAUSED"
        await service._refresh(ids["tenant_id"], promotion.id, api=api)
        with tenant_session(ids["tenant_id"]) as s:
            assert (
                s.scalar(
                    text("SELECT state FROM ad_promotion_operations WHERE id=:id"),
                    {"id": operation},
                )
                == "in_flight"
            )
        with pytest.raises(ResultsUnavailable, match="treinta"):
            service._claim_pause(scope, "second-intent", datetime.now(UTC))


@pytest.mark.asyncio
async def test_connection_purge_removes_derived_insights_but_preserves_operation_audit(
    result_world,
):
    from qualify_shared.db.connection_purge import connection_purge_session

    ids, login, _, connection, promotion, api = result_world
    with acting_login(login):
        await service._refresh(ids["tenant_id"], promotion.id, api=api)
        await service._pause(ids["tenant_id"], promotion.id, "pause", api=api)
    with connection_purge_session(ids["tenant_id"]) as s:
        s.execute(text("DELETE FROM ad_accounts WHERE connection_id=:id"), {"id": connection})
    with tenant_session(ids["tenant_id"]) as s:
        assert (
            s.scalar(
                text("SELECT count(*) FROM ad_promotion_observations WHERE promotion_id=:id"),
                {"id": promotion.id},
            )
            == 0
        )
        assert (
            s.scalar(
                text("SELECT count(*) FROM ad_promotion_insights WHERE promotion_id=:id"),
                {"id": promotion.id},
            )
            == 0
        )
        assert (
            s.scalar(
                text("SELECT count(*) FROM ad_promotion_operations WHERE promotion_id=:id"),
                {"id": promotion.id},
            )
            == 1
        )


@pytest.mark.parametrize(
    ("result_world", "expected_caption"),
    [("777", PUBLISHED_CAPTION[:160]), ("999", "")],
    indirect=["result_world"],
)
def test_summary_caption_uses_only_bound_published_unpurged_source(result_world, expected_caption):
    ids, login, _, connection, promotion, _ = result_world
    with acting_login(login):
        summary = service.load_promotion_results(
            tenant_id=ids["tenant_id"], promotion_id=promotion.id
        ).promotion
        assert summary.caption == expected_caption
        assert (
            service.list_promotion_results(tenant_id=ids["tenant_id"])[0].caption
            == expected_caption
        )
        with tenant_session(ids["tenant_id"]) as s:
            s.execute(
                text("UPDATE social_connections SET purge_started_at=now() WHERE id=:id"),
                {"id": connection},
            )
        assert (
            service.load_promotion_results(
                tenant_id=ids["tenant_id"], promotion_id=promotion.id
            ).promotion.caption
            == ""
        )

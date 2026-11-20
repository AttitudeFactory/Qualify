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
from qualify_api.ads.enhancements import BrandEnhancementSettings, compose_brand_policy
from qualify_api.ads.errors import MarketingError
from qualify_api.ads.fake import FakeMarketingClient
from qualify_api.ads.promotion_repository import PostgresPromotionRepository
from qualify_api.ads.promotions import ADAPTER_VERSION, PromotionRequest, fingerprint
from qualify_api.ads.results import ResultsUnavailable
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


@pytest.mark.asyncio
async def test_read_worker_postgres_lease_excludes_replica_and_releases(monkeypatch):
    import asyncio

    from qualify_api.ads import reads_cli

    tenant = uuid4()
    entered, release = asyncio.Event(), asyncio.Event()

    async def health(**kwargs):
        entered.set()
        await release.wait()
        return ()

    async def results(**kwargs):
        return {"checked": 0, "unavailable": 0}

    monkeypatch.setattr(reads_cli, "refresh_daily_account_health", health)
    monkeypatch.setattr(reads_cli, "poll_promotion_results", results)
    first = asyncio.create_task(reads_cli.tick(tenant))
    await asyncio.wait_for(entered.wait(), 2)
    try:
        assert (await reads_cli.tick(tenant))["busy"] == 1
    finally:
        release.set()
        await first
    assert (await reads_cli.tick(tenant))["busy"] == 0


def test_prepared_edit_ledger_cas_and_unknown_block_different_keys(result_world):
    from qualify_api.ads.edit_ledger import operations, revision

    ids, login, user, _, promotion, _ = result_world
    with acting_login(login):
        scope = service._scope(ids["tenant_id"], promotion.id)
        with tenant_session(ids["tenant_id"]) as session:
            initial = revision(operations(session, promotion.id))
        operation, state = service._claim_pause(
            scope,
            "sealed-intent-first",
            datetime.now(UTC),
            action="budget",
            payload={"lifetime_budget": 200},
            evidence={"confirmed": True},
            expected_revision=initial,
        )
        assert state == "claimed"
        service._finish_pause(scope, operation, "unknown")
        with tenant_session(ids["tenant_id"]) as session:
            current = revision(operations(session, promotion.id))
        assert current != initial
        with pytest.raises(ResultsUnavailable, match="historial"):
            service._claim_pause(
                scope, "stale-second-key", datetime.now(UTC), expected_revision=initial
            )
        with pytest.raises(ResultsUnavailable, match="treinta"):
            service._claim_pause(
                scope,
                "fresh-but-unknown-key",
                datetime.now(UTC),
                action="resume",
                payload={"status": "ACTIVE"},
                expected_revision=current,
            )
        replay, replay_state = service._claim_pause(
            scope,
            "sealed-intent-first",
            datetime.now(UTC),
            action="budget",
            payload={"lifetime_budget": 200},
            expected_revision=initial,
        )
        assert (replay, replay_state) == (operation, "unknown")
    with tenant_session(ids["tenant_id"]) as session:
        row = (
            session.execute(
                text("SELECT actor_id,approval_evidence FROM ad_promotion_operations WHERE id=:id"),
                {"id": operation},
            )
            .mappings()
            .one()
        )
        assert row["actor_id"] == user and row["approval_evidence"]["confirmed"] is True
        assert (
            session.scalar(
                text("SELECT request_snapshot FROM ad_promotions WHERE id=:id"),
                {"id": promotion.id},
            )
            == promotion.request
        )


@pytest.mark.asyncio
async def test_unactivated_promotion_cannot_bypass_original_spending_confirmation(result_world):
    ids, login, _, _, promotion, _ = result_world
    with acting_login(login), pytest.raises(ResultsUnavailable, match="inicial"):
        await service.prepare_promotion_edit(
            tenant_id=ids["tenant_id"],
            promotion_id=promotion.id,
            request_key="never-consented-resume",
            action="resume",
        )


def test_results_project_only_confirmed_operational_budget_not_initial_approval(result_world):
    from qualify_api.ads.edit_ledger import EDIT_PIPELINE

    ids, login, _, _, promotion, _ = result_world
    before = {key: promotion.request[key] for key in ("budget_minor", "end_time")}
    after = before | {"budget_minor": 30000}
    with acting_login(login):
        scope = service._scope(ids["tenant_id"], promotion.id)
        operation, _ = service._claim_pause(
            scope,
            "confirmed-overlay",
            datetime.now(UTC),
            action="budget",
            payload={"lifetime_budget": 300},
            evidence={
                "pipeline": EDIT_PIPELINE,
                "confirmed": True,
                "before": before,
                "after": after,
            },
        )
        service._finish_pause(scope, operation, "unknown")
        unknown = service.load_promotion_results(
            tenant_id=ids["tenant_id"], promotion_id=promotion.id
        )
        assert unknown.promotion.operation_pending
        assert unknown.promotion.current_budget_minor == before["budget_minor"]
        with tenant_session(ids["tenant_id"]) as session:
            session.execute(
                text("UPDATE ad_promotion_operations SET state='reconciled' WHERE id=:id"),
                {"id": operation},
            )
        confirmed = service.load_promotion_results(
            tenant_id=ids["tenant_id"], promotion_id=promotion.id
        )
        assert confirmed.promotion.current_budget_minor == 30000
        assert confirmed.promotion.budget_minor == 30000
        assert not confirmed.promotion.operation_pending
        assert (
            PostgresPromotionRepository().get(ids["tenant_id"], promotion.id).request
            == promotion.request
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("dispatch_case", ["absent", "recent", "changed", "settled"])
async def test_paid_reconciliation_requires_old_stable_dispatch(
    result_world, monkeypatch, dispatch_case
):
    from qualify_api.ads import live_management
    from qualify_api.ads.edit_ledger import EDIT_PIPELINE, revision

    ids, login, user, _, promotion, _ = result_world
    before = {key: promotion.request[key] for key in ("budget_minor", "end_time")}
    after = before | {"budget_minor": 30000}
    evidence = {
        "pipeline": EDIT_PIPELINE,
        "confirmed": True,
        "actor": str(user),
        "ledger": revision([]),
        "original": fingerprint(promotion.request),
        "before": before,
        "after": after,
        "baseline": ["campaigns", "adsets", "ads"],
    }
    now = datetime.now(UTC)
    with acting_login(login):
        scope = service._scope(ids["tenant_id"], promotion.id)
        operation, _ = service._claim_pause(
            scope,
            "reconcile-edit",
            now,
            action="budget",
            payload={"lifetime_budget": 300},
            evidence=evidence,
        )
        service._finish_pause(scope, operation, "unknown")
        stamp = (
            None
            if dispatch_case == "absent"
            else now - timedelta(seconds=1 if dispatch_case == "recent" else 100)
        )
        with tenant_session(ids["tenant_id"]) as session:
            session.execute(
                text(
                    "UPDATE ad_promotion_operations SET created_at=:created,"
                    "dispatched_at=:dispatch WHERE id=:id"
                ),
                {"id": operation, "created": now - timedelta(seconds=120), "dispatch": stamp},
            )
        proofs = []

        class Gateway:
            def __init__(self, *, actor, **kwargs):
                self.actor = actor

            async def remote_guard(self, desired, *, active_resources):
                proofs.append(desired.request["budget_minor"])
                if dispatch_case == "changed":
                    with tenant_session(ids["tenant_id"]) as session:
                        session.execute(
                            text(
                                "UPDATE ad_promotion_operations SET dispatched_at=:now WHERE id=:id"
                            ),
                            {"now": now, "id": operation},
                        )

        monkeypatch.setattr(live_management, "LiveWizardGateway", Gateway)
        result = await live_management.reconcile_promotion_edit(scope)
        assert result is (dispatch_case == "settled")
        assert bool(proofs) is (dispatch_case in {"changed", "settled"})
    with tenant_session(ids["tenant_id"]) as session:
        assert session.scalar(
            text("SELECT state FROM ad_promotion_operations WHERE id=:id"), {"id": operation}
        ) == ("reconciled" if result else "unknown")


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
    request = compose_brand_policy(
        request, BrandEnhancementSettings(request.tenant_id, request.brand_id)
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
        # A new key after a finished pause sends PAUSED again (harmless, m-25072681).
        await service._pause(ids["tenant_id"], promotion.id, "intent-2", api=api)
        assert len([c for c in api.calls if c[0] == "POST"]) == 2
    with tenant_session(ids["tenant_id"]) as s:
        row = (
            s.execute(
                text("SELECT * FROM ad_promotion_operations WHERE promotion_id=:id"),
                {"id": promotion.id},
            )
            .mappings()
            .first()
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
@pytest.mark.parametrize("case", ["specific", "unsafe", "absent", "wrong_account"])
async def test_specific_meta_reason_saved_only_after_exact_account_and_safe_text(
    result_world, case
):
    ids, login, _, _, promotion, api = result_world
    reason = "El enlace de destino no está disponible."
    issue = {"error_code": 100, "error_summary": reason, "mid": "SECRET_TOKEN"}
    if case == "unsafe":
        issue["error_summary"] = "<b>SECRET_TOKEN</b>"
    api.objects["3"].update(
        effective_status="DISAPPROVED", issues_info=[] if case == "absent" else [issue]
    )
    if case == "wrong_account":
        api.objects["3"]["account_id"] = "999"
    with acting_login(login):
        if case == "wrong_account":
            with pytest.raises(ResultsUnavailable):
                await service._refresh(ids["tenant_id"], promotion.id, api=api)
        else:
            result = await service._refresh(ids["tenant_id"], promotion.id, api=api)
            assert ("Motivo informado por Meta" in result.promotion.rejection_reason) is (
                case == "specific"
            )
            if case == "specific":
                assert reason in result.promotion.rejection_reason
            assert "SECRET_TOKEN" not in repr(result)
    with tenant_session(ids["tenant_id"]) as session:
        saved = session.scalar(
            text("SELECT review_feedback FROM ad_promotions WHERE id=:id"), {"id": promotion.id}
        )
        assert "SECRET_TOKEN" not in repr(saved)
        assert (isinstance(saved, dict) and saved.get("reason") == reason) is (case == "specific")
        if case == "specific":
            assert saved["source_id"] == "3" and saved["account_id"] == ids["meta_account_id"]
            assert saved["pipeline_version"] == "ad-review-reason-v1"


@pytest.mark.asyncio
async def test_production_wrapper_refuses_paid_budget_edit(result_world):
    ids, login, _, _, promotion, _ = result_world
    with acting_login(login), pytest.raises(ResultsUnavailable):
        await service.edit_promotion(
            tenant_id=ids["tenant_id"],
            promotion_id=promotion.id,
            action="budget",
            request_key="paid",
            budget_minor=20000,
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
        # The pause still on its way answers a second pause: one Meta write.
        assert service._claim_pause(scope, "second-intent", datetime.now(UTC)) == (
            operation,
            "in_flight",
        )


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


# m-25072681: the pause is the brake — always claimable except while another pause is on its way.


def _unresolved(scope, key, *, action="budget", state="unknown", evidence=None):
    payload = {"lifetime_budget": 300} if action == "budget" else {"status": "ACTIVE"}
    operation, claimed = service._claim_pause(
        scope,
        key,
        datetime.now(UTC),
        action=action,
        payload=payload,
        evidence=evidence or {"confirmed": True},
    )
    assert claimed == "claimed"
    if state != "in_flight":
        service._finish_pause(scope, operation, state)
    return operation


def _states(ids, promotion):
    with tenant_session(ids["tenant_id"]) as s:
        return dict(
            s.execute(
                text(
                    "SELECT action,state FROM ad_promotion_operations WHERE promotion_id=:id "
                    "ORDER BY created_at,id"
                ),
                {"id": promotion.id},
            ).all()
        )


def _posts(api):
    return [call[1:] for call in api.calls if call[0] == "POST"]


@pytest.mark.asyncio
@pytest.mark.parametrize("edit_state", ["unknown", "completed"])
async def test_pause_is_sent_past_an_unresolved_edit_and_the_thirty_second_window(
    result_world, edit_state
):
    ids, login, _, _, promotion, api = result_world
    with acting_login(login):
        scope = service._scope(ids["tenant_id"], promotion.id)
        _unresolved(scope, "budget-edit", state=edit_state)
        await service._refresh(ids["tenant_id"], promotion.id, api=api)
        shown = service.load_promotion_results(
            tenant_id=ids["tenant_id"], promotion_id=promotion.id
        )
        assert shown.promotion.can_pause
        assert shown.promotion.operation_pending is (edit_state == "unknown")
        # Resume and edits keep today's rule: an unresolved change or the 30 s pacing blocks.
        with pytest.raises(ResultsUnavailable, match="treinta"):
            service._claim_pause(
                scope,
                "resume-blocked",
                datetime.now(UTC),
                action="resume",
                payload={"status": "ACTIVE"},
            )
        await service._pause(ids["tenant_id"], promotion.id, "brake", api=api)
    assert _posts(api) == [("3", {"status": "PAUSED"})]
    assert _states(ids, promotion) == {"budget": edit_state, "pause": "completed"}


@pytest.mark.asyncio
async def test_two_pauses_with_different_keys_make_one_meta_write(result_world):
    import asyncio

    ids, login, _, _, promotion, api = result_world
    with acting_login(login):
        scope = service._scope(ids["tenant_id"], promotion.id)
        _unresolved(scope, "budget-edit")
        original, sending, release = api.update, asyncio.Event(), asyncio.Event()

        async def slow(*args, **kwargs):
            sending.set()
            await release.wait()  # The first pause is still on its way to Meta.
            return await original(*args, **kwargs)

        api.update = slow
        first = asyncio.create_task(
            service._pause(ids["tenant_id"], promotion.id, "click-1", api=api)
        )
        await asyncio.wait_for(sending.wait(), 5)
        api.update = original
        with pytest.raises(ResultsUnavailable, match="Ya estamos pausando"):
            await service._pause(ids["tenant_id"], promotion.id, "click-2", api=api)
        release.set()
        await first
    assert _posts(api) == [("3", {"status": "PAUSED"})]
    with tenant_session(ids["tenant_id"]) as s:
        assert (
            s.scalar(
                text(
                    "SELECT count(*) FROM ad_promotion_operations "
                    "WHERE promotion_id=:id AND action='pause'"
                ),
                {"id": promotion.id},
            )
            == 1
        )


def test_database_allows_one_pause_in_flight_beside_an_unresolved_edit(result_world):
    from sqlalchemy.exc import IntegrityError

    ids, login, user, _, promotion, _ = result_world
    with acting_login(login):
        scope = service._scope(ids["tenant_id"], promotion.id)
        _unresolved(scope, "budget-edit")
        service._claim_pause(scope, "brake", datetime.now(UTC))
    with pytest.raises(IntegrityError), tenant_session(ids["tenant_id"]) as s:
        s.execute(
            text(
                "INSERT INTO ad_promotion_operations (tenant_id,promotion_id,request_key,"
                "actor_id,action,payload,approval_evidence,state,created_at,pipeline_version) "
                "VALUES (:tenant,:id,'raced-brake',:actor,'pause',CAST('{}' AS jsonb),"
                "CAST('{}' AS jsonb),'in_flight',now(),'t')"
            ),
            {"tenant": ids["tenant_id"], "id": promotion.id, "actor": user},
        )


@pytest.mark.asyncio
async def test_meta_edit_rate_limit_on_pause_asks_to_retry_and_frees_the_brake(result_world):
    ids, login, _, _, promotion, api = result_world
    original = api.update

    async def too_soon(*args, **kwargs):
        api.failures.append(MarketingError("fixture", subcode=4841018, http_status=400))
        return await original(*args, **kwargs)

    api.update = too_soon
    with acting_login(login):
        with pytest.raises(ResultsUnavailable, match="otra vez"):
            await service._pause(ids["tenant_id"], promotion.id, "first", api=api)
        assert _states(ids, promotion) == {"pause": "failed"}
        api.update = original
        await service._pause(ids["tenant_id"], promotion.id, "second", api=api)
    assert len(_posts(api)) == 2


def test_resume_in_flight_aborts_once_a_pause_row_exists(result_world):
    from qualify_api.ads import live_management
    from qualify_api.ads.edit_ledger import revision

    ids, login, _, _, promotion, _ = result_world

    class Gateway:
        def local_guard(self, source):
            return None

    expires = datetime.now(UTC) + timedelta(minutes=5)
    with acting_login(login):
        scope = service._scope(ids["tenant_id"], promotion.id)
        resume = _unresolved(scope, "resume", action="resume", state="in_flight")
        ledger = revision([])
        live_management._local(scope, Gateway(), None, promotion, ledger, expires, resume)
        service._claim_pause(scope, "brake", datetime.now(UTC))
        with pytest.raises(ResultsUnavailable):
            live_management._local(scope, Gateway(), None, promotion, ledger, expires, resume)


@pytest.mark.asyncio
@pytest.mark.parametrize("ad_reads", ["PAUSED", "ACTIVE"])
async def test_older_unknown_resume_reconciled_after_a_finished_pause_never_wins(
    result_world, monkeypatch, ad_reads
):
    from qualify_api.ads import live_management
    from qualify_api.ads.edit_ledger import EDIT_PIPELINE, revision

    ids, login, user, _, promotion, api = result_world
    values = {key: promotion.request[key] for key in ("budget_minor", "end_time")}
    evidence = {
        "pipeline": EDIT_PIPELINE,
        "confirmed": True,
        "actor": str(user),
        "ledger": revision([]),
        "original": fingerprint(promotion.request),
        "before": values,
        "after": values,
        "baseline": ["adsets", "campaigns"],
    }
    old = datetime.now(UTC) - timedelta(seconds=120)
    reads = []

    class Gateway:
        def __init__(self, *, actor, **kwargs):
            self.actor = actor

        async def remote_guard(self, desired, *, active_resources):
            # A strict read-back: the ad must be exactly as expected.
            reads.append(tuple(sorted(active_resources)))
            if ("ads" in active_resources) != (ad_reads == "ACTIVE"):
                raise ResultsUnavailable("read-back differs")

    monkeypatch.setattr(live_management, "LiveWizardGateway", Gateway)
    with acting_login(login):
        scope = service._scope(ids["tenant_id"], promotion.id)
        resume = _unresolved(scope, "old-resume", action="resume", evidence=evidence)
        with tenant_session(ids["tenant_id"]) as s:
            s.execute(
                text(
                    "UPDATE ad_promotion_operations SET created_at=:old,dispatched_at=:old "
                    "WHERE id=:id"
                ),
                {"id": resume, "old": old},
            )
        await service._pause(ids["tenant_id"], promotion.id, "brake", api=api)
        assert await live_management.reconcile_promotion_edit(scope) is (ad_reads == "PAUSED")
        # Expected only with the ad paused: the later pause wins over the older resume.
        assert reads == [("adsets", "campaigns")]
        assert _states(ids, promotion) == {
            "resume": "reconciled" if ad_reads == "PAUSED" else "unknown",
            "pause": "completed",
        }
        if ad_reads == "ACTIVE":
            # The old resume landed after the pause: the screen shows Meta's ACTIVE and the
            # owner can pause again, never a silent success.
            api.objects["3"]["status"] = api.objects["3"]["effective_status"] = "ACTIVE"
            shown = await service._refresh(ids["tenant_id"], promotion.id, api=api)
            assert shown.promotion.status == "ACTIVE" and shown.promotion.can_pause
            with tenant_session(ids["tenant_id"]) as s:
                s.execute(
                    text(
                        "UPDATE ad_promotion_operations SET finished_at=now()-interval '1 minute'"
                        " WHERE promotion_id=:id AND action='pause'"
                    ),
                    {"id": promotion.id},
                )
            await service._pause(ids["tenant_id"], promotion.id, "brake-again", api=api)
            assert len(_posts(api)) == 2


@pytest.mark.asyncio
async def test_a_pause_stuck_in_flight_past_five_minutes_gives_the_brake_back(result_world):
    ids, login, _, _, promotion, api = result_world
    with acting_login(login):
        scope = service._scope(ids["tenant_id"], promotion.id)
        stuck, _ = service._claim_pause(scope, "worker-died", datetime.now(UTC))
        await service._refresh(ids["tenant_id"], promotion.id, api=api)
        shown = service.load_promotion_results(
            tenant_id=ids["tenant_id"], promotion_id=promotion.id
        )
        assert not shown.promotion.can_pause
        with tenant_session(ids["tenant_id"]) as s:
            s.execute(
                text(
                    "UPDATE ad_promotion_operations SET created_at=now()-interval '6 minutes' "
                    "WHERE id=:id"
                ),
                {"id": stuck},
            )
        shown = service.load_promotion_results(
            tenant_id=ids["tenant_id"], promotion_id=promotion.id
        )
        assert shown.promotion.can_pause
        await service._pause(ids["tenant_id"], promotion.id, "brake", api=api)
    assert _posts(api) == [("3", {"status": "PAUSED"})]
    with tenant_session(ids["tenant_id"]) as s:
        assert (
            s.scalar(text("SELECT state FROM ad_promotion_operations WHERE id=:id"), {"id": stuck})
            == "failed"
        )


def test_an_edit_claimed_before_a_pause_never_dispatches(result_world):
    ids, login, _, _, promotion, _ = result_world
    with acting_login(login):
        scope = service._scope(ids["tenant_id"], promotion.id)
        resume = _unresolved(scope, "resume", action="resume", state="in_flight")
        brake, _ = service._claim_pause(scope, "brake", datetime.now(UTC))
        service._dispatch(scope, brake)
        service._finish_pause(scope, brake, "completed")
        with pytest.raises(ResultsUnavailable, match="se pausó"):
            service._dispatch(scope, resume)
    assert _states(ids, promotion) == {"resume": "failed", "pause": "completed"}
    with tenant_session(ids["tenant_id"]) as s:
        assert (
            s.scalar(
                text("SELECT dispatched_at FROM ad_promotion_operations WHERE id=:id"),
                {"id": resume},
            )
            is None
        )


@pytest.mark.asyncio
async def test_pause_right_after_a_finished_pause_still_writes_to_meta(result_world):
    ids, login, _, _, promotion, api = result_world
    with acting_login(login):
        await service._pause(ids["tenant_id"], promotion.id, "brake", api=api)
        # A late resume re-activated the ad within 30 s of the finished pause.
        api.objects["3"]["status"] = api.objects["3"]["effective_status"] = "ACTIVE"
        await service._pause(ids["tenant_id"], promotion.id, "brake-again", api=api)
    assert _posts(api) == [("3", {"status": "PAUSED"})] * 2


@pytest.mark.asyncio
async def test_poller_skips_abandoned_promotions_but_reads_activated_ones(
    result_world, monkeypatch
):
    """m-25077974: a paused promotion whose preview expired unconfirmed is never read again."""
    ids, _, user, _, promotion, _ = result_world
    read: list = []

    async def refresh(tenant_id, promotion_id, *, system=False):
        read.append(promotion_id)

    monkeypatch.setattr(service, "_refresh", refresh)
    # Created in Meta, but no preview was ever saved: nothing the owner could activate.
    await service.poll_promotion_results(tenant_id=ids["tenant_id"])
    assert read == []
    with tenant_session(ids["tenant_id"]) as s:
        s.execute(
            text("""INSERT INTO ad_promotion_activations
            (tenant_id,promotion_id,request_hash,preview_html,preview_hash,checks_snapshot,
             pipeline_version,expires_at,prepared_by)
            VALUES (:tenant,:promotion,'h','<p></p>','p','{}','promotion-wizard-v1',
                    :expires,:actor)"""),
            {
                "tenant": ids["tenant_id"],
                "promotion": promotion.id,
                "expires": datetime.now(UTC) - timedelta(minutes=1),
                "actor": user,
            },
        )
    await service.poll_promotion_results(tenant_id=ids["tenant_id"])
    assert read == []  # The preview expired without confirmation: abandoned.
    with tenant_session(ids["tenant_id"]) as s:
        s.execute(
            text("""UPDATE ad_promotion_activations SET state='in_flight',confirmed_by=:actor,
            confirmed_at=now(),claim_token=gen_random_uuid() WHERE promotion_id=:promotion"""),
            {"promotion": promotion.id, "actor": user},
        )
    await service.poll_promotion_results(tenant_id=ids["tenant_id"])
    assert read == [promotion.id]  # Activated once: read even after the preview expired.

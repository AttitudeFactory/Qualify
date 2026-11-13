"""Real RLS, immutable approvals, duplicate delivery and contact-consent separation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.connection_purge import connection_purge_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from qualify_api.ads import lead_forms_repository as repo
from qualify_api.ads import lead_forms_service as service
from qualify_api.ads.lead_forms import LeadFormDraft, LeadFormQuestion, LeadFormUnavailable
from qualify_api.ads.lead_forms_client import LeadPage
from qualify_api.ads.lead_forms_webhook import owned_form
from qualify_api.connections.ad_accounts import PostgresAdsGrantRecorder
from qualify_api.connections.crypto import DevEncryptor
from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.tenancy.acting import acting_login
from qualify_api.tenancy.models import Brand, Tenant, TenantMember, User
from qualify_api.webhooks.repository import ClaimedEvent

pytestmark = pytest.mark.db


def world() -> tuple[UUID, UUID, UUID, UUID, UUID]:
    tenant, brand, user, connection, login = (uuid4() for _ in range(5))
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant,
                name="Synthetic lead forms",
                country="CO",
                timezone="America/Bogota",
                currency="COP",
            )
        )
        session.flush()
        app = PlatformApp(app_id=f"lead-{uuid4()}", secret_ref="test", api_version="v26.0")
        session.add_all(
            [
                Brand(id=brand, tenant_id=tenant, name="Synthetic brand"),
                app,
                User(
                    id=user,
                    tenant_id=tenant,
                    email=f"{user}@test.invalid",
                    display_name="Owner",
                    auth_user_id=login,
                ),
            ]
        )
        session.flush()
        session.add(TenantMember(tenant_id=tenant, user_id=user, role="owner"))
        app_id = app.id
    scopes = (
        "ads_management",
        "ads_read",
        "pages_manage_ads",
        "pages_manage_metadata",
        "leads_retrieval",
        "pages_show_list",
    )
    with tenant_session(tenant) as session:
        session.add(
            SocialConnection(
                id=connection,
                tenant_id=tenant,
                brand_id=brand,
                platform_app_id=app_id,
                platform="instagram",
                account_type="business",
                external_account_id="400",
                linked_page_id="200",
                granted_scopes=list(scopes),
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
        ciphertext=encryptor.encrypt("SYNTHETIC_USER_TOKEN"),
        key_id=encryptor.key_id,
        granted_scopes=scopes,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    return tenant, brand, user, connection, login


def draft() -> LeadFormDraft:
    return LeadFormDraft(
        "Viajes",
        "https://example.invalid/privacy",
        "Gracias",
        "Te contactaremos.",
        "https://example.invalid",
        (LeadFormQuestion("EMAIL"),),
    )


def published(values: tuple) -> dict:
    tenant, _, _, connection, login = values
    with acting_login(login):
        summary = service.save_lead_form_draft(
            tenant_id=tenant, connection_id=connection, draft=draft()
        )
        repo.claim_publication(tenant, summary.id, summary.revision)
        repo.finish_publication(tenant, summary.id, meta_form_id=str(uuid4().int))
    return repo.get_form(tenant, summary.id)


def lead(form: dict, *, identity: str = "900") -> dict:
    return service.parse_lead(
        {
            "id": identity,
            "form_id": form["meta_form_id"],
            "created_time": "2026-01-01T00:00:00+0000",
            "field_data": [{"name": "email", "values": ["synthetic@example.invalid"]}],
        },
        form_id=form["meta_form_id"],
    )


def test_form_revision_actor_claim_and_approval_are_immutable() -> None:
    tenant, brand, user, connection, login = world()
    with acting_login(login):
        first = service.save_lead_form_draft(
            tenant_id=tenant, connection_id=connection, draft=draft()
        )
        second = service.save_lead_form_draft(
            tenant_id=tenant,
            connection_id=connection,
            draft=replace(draft(), name="Otra revisión"),
            form_id=first.id,
            expected_revision=1,
        )
        with pytest.raises(LeadFormUnavailable):
            repo.claim_publication(tenant, first.id, 1)
        approved = repo.claim_publication(tenant, second.id, 2)
        assert (
            approved["approved_by"] == user
            and approved["approved_snapshot"]["name"] == "Otra revisión"
        )
        with pytest.raises(LeadFormUnavailable):
            repo.claim_publication(tenant, second.id, 2)
        with pytest.raises(LeadFormUnavailable):
            service.save_lead_form_draft(
                tenant_id=tenant,
                connection_id=connection,
                draft=draft(),
                form_id=second.id,
                expected_revision=2,
            )
    for sql in (
        "UPDATE ad_lead_forms SET status='draft' WHERE id=:id",
        "UPDATE ad_lead_forms SET approved_snapshot='{}'::jsonb WHERE id=:id",
        "UPDATE ad_lead_forms SET request_key=gen_random_uuid() WHERE id=:id",
        "UPDATE ad_lead_forms SET credential_version=2 WHERE id=:id",
    ):
        with pytest.raises(IntegrityError), tenant_session(tenant) as session:
            session.execute(text(sql), {"id": second.id})


def test_rls_and_compound_owner_foreign_keys_reject_cross_tenant() -> None:
    owner, foreign = world(), world()
    form = published(owner)
    assert repo.list_forms(foreign[0], owner[3]) == ()
    with pytest.raises(LeadFormUnavailable):
        repo.get_form(foreign[0], form["id"])
    with pytest.raises(IntegrityError), tenant_session(owner[0]) as session:
        session.execute(
            text("""INSERT INTO ad_lead_forms
            (tenant_id,connection_id,brand_id,page_id,credential_version,draft)
            VALUES (:tid,:cid,:brand,'200',1,'{}')"""),
            {"tid": owner[0], "cid": foreign[3], "brand": owner[1]},
        )
    with pytest.raises(IntegrityError), tenant_session(owner[0]) as session:
        session.execute(
            text("""INSERT INTO ad_lead_forms
            (tenant_id,connection_id,brand_id,page_id,credential_version,draft)
            VALUES (:tid,:cid,:brand,'200',1,'{}')"""),
            {"tid": owner[0], "cid": owner[3], "brand": foreign[1]},
        )
    with tenant_session(owner[0]) as session:
        guards = session.execute(
            text("""SELECT relrowsecurity,relforcerowsecurity FROM pg_class
            WHERE relname IN ('ad_lead_forms','meta_lead_submissions')""")
        ).all()
        assert len(guards) == 2 and all(all(row) for row in guards)
        session.execute(text("SELECT set_config('app.tenant_id','',true)"))
        assert session.scalar(text("SELECT count(*) FROM ad_lead_forms")) == 0


def test_duplicate_webhook_and_backup_concurrently_create_one_inquiry_without_wa_consent() -> None:
    values = world()
    form = published(values)
    data = lead(form)

    def persist(via: str) -> bool:
        return service._persist(values[0], form, data, received_via=via)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(persist, ("webhook", "backup")))
    assert sorted(results) == [False, True]
    inquiry = repo.list_inquiries(values[0])[0]
    assert inquiry.phone is None and inquiry.email == "synthetic@example.invalid"
    assert not inquiry.whatsapp_opt_in and inquiry.promotion_id is None
    with tenant_session(values[0]) as session:
        assert session.scalar(text("SELECT count(*) FROM meta_lead_submissions")) == 1
        assert session.scalar(text("SELECT count(*) FROM leads")) == 0
        assert session.scalar(text("SELECT count(*) FROM whatsapp_opt_ins")) == 0
    repo.mark_inquiry(values[0], inquiry.id, True)
    assert not persist("backup")
    assert repo.list_inquiries(values[0])[0].contacted_at is not None


def test_frozen_webhook_form_binding_cannot_acquire_new_tenant() -> None:
    owner, foreign = world(), world()
    form = published(owner)
    event = ClaimedEvent(
        uuid4(), None, "page", "200", "leadgen", {}, 1, owners=((foreign[0], foreign[3]),)
    )
    assert owned_form(event, form["meta_form_id"]) is None
    assert (
        owned_form(replace(event, owners=((owner[0], owner[3]),)), form["meta_form_id"])[0]
        == owner[0]
    )
    assert (
        owned_form(
            replace(event, entry_id="201", owners=((owner[0], owner[3]),)), form["meta_form_id"]
        )
        is None
    )


@pytest.mark.parametrize("change", ["status='revoked'", "current_credential_version=2"])
def test_revoked_or_rotated_connection_cannot_persist_fetched_pii(change: str) -> None:
    values = world()
    form = published(values)
    with tenant_session(values[0]) as session:
        session.execute(
            text(f"UPDATE social_connections SET {change} WHERE id=:id"), {"id": values[3]}
        )
    with pytest.raises(LeadFormUnavailable):
        service._persist(values[0], form, lead(form), received_via="webhook")
    assert repo.list_inquiries(values[0]) == ()


def test_connection_purger_cascades_only_its_own_meta_inquiries() -> None:
    owner, foreign = world(), world()
    form, other_form = published(owner), published(foreign)
    service._persist(owner[0], form, lead(form), received_via="webhook")
    service._persist(foreign[0], other_form, lead(other_form), received_via="webhook")
    with connection_purge_session(owner[0]) as session:
        deleted = session.execute(
            text("DELETE FROM ad_lead_forms WHERE tenant_id=:tid AND connection_id=:cid"),
            {"tid": owner[0], "cid": owner[3]},
        )
        assert deleted.rowcount == 1
    assert repo.list_inquiries(owner[0]) == ()
    assert len(repo.list_inquiries(foreign[0])) == 1


@pytest.mark.asyncio
async def test_backup_failure_resumes_exact_cursor_without_advancing_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = world()
    form = published(values)
    raw = {
        "id": "901",
        "form_id": form["meta_form_id"],
        "created_time": "2026-01-01T00:00:00Z",
        "field_data": [{"name": "email", "values": ["synthetic@example.invalid"]}],
    }
    fake = AsyncMock()
    fake.leads.side_effect = [LeadPage((raw,), "next"), LeadFormUnavailable("temporary")]
    monkeypatch.setattr(service, "_client", AsyncMock(return_value=fake))
    monkeypatch.setattr(service, "_page_access", AsyncMock())
    monkeypatch.setattr(service, "_remote_form", AsyncMock())
    with acting_login(values[4]), pytest.raises(LeadFormUnavailable):
        await service.sync_lead_form(tenant_id=values[0], form_id=form["id"])
    stored = repo.get_form(values[0], form["id"])
    assert stored["last_synced_at"] is None and stored["backup_after"] == "next"
    assert len(repo.list_inquiries(values[0])) == 1
    fake.leads.side_effect = [LeadPage(({**raw, "id": "902"},), None)]
    with acting_login(values[4]):
        assert await service.sync_lead_form(tenant_id=values[0], form_id=form["id"]) == 1
    assert fake.leads.call_args.kwargs["after"] == "next"
    final = repo.get_form(values[0], form["id"])
    assert final["last_synced_at"] == stored["backup_started_at"]
    assert final["backup_after"] is None and final["backup_since"] is None
    assert len(repo.list_inquiries(values[0])) == 2


@pytest.mark.asyncio
async def test_backup_work_limit_keeps_cursor_for_next_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = world()
    form = published(values)
    fake = AsyncMock()
    fake.leads.side_effect = [LeadPage((), f"cursor{i}") for i in range(20)]
    monkeypatch.setattr(service, "_client", AsyncMock(return_value=fake))
    monkeypatch.setattr(service, "_page_access", AsyncMock())
    monkeypatch.setattr(service, "_remote_form", AsyncMock())
    with acting_login(values[4]), pytest.raises(LeadFormUnavailable):
        await service.sync_lead_form(tenant_id=values[0], form_id=form["id"])
    stored = repo.get_form(values[0], form["id"])
    assert stored["backup_after"] == "cursor19" and stored["last_synced_at"] is None
    fake.leads.side_effect = [LeadPage((), "cursor19")]
    with acting_login(values[4]), pytest.raises(LeadFormUnavailable, match="repitió"):
        await service.sync_lead_form(tenant_id=values[0], form_id=form["id"])
    assert repo.get_form(values[0], form["id"])["last_synced_at"] is None


def test_lead_from_our_lead_ad_is_attributed_to_its_promotion() -> None:
    """m-24828981: _persist finds the promotion through request_snapshot.lead_form_snapshot."""
    from qualify_api.ads.enhancements import BrandEnhancementSettings, compose_brand_policy
    from qualify_api.ads.lead_ads import published_lead_form
    from qualify_api.ads.promotion_repository import PostgresPromotionRepository
    from qualify_api.ads.promotions import PromotionRequest

    values = world()
    tenant, brand, user, connection, _ = values
    form = published(values)
    attempt, now = uuid4(), datetime.now(UTC)
    with tenant_session(tenant) as session:
        session.execute(
            text("""INSERT INTO publish_attempts
                (id,tenant_id,connection_id,idempotency_key,media_product_type,
                 adapter_version,status,published_media_id,settled_at,caption)
            VALUES (:id,:tenant,:connection,:key,'REELS','test','published','777',:now,'x')"""),
            {
                "id": attempt,
                "tenant": tenant,
                "connection": connection,
                "key": str(uuid4()),
                "now": now,
            },
        )
    target = published_lead_form(tenant, form["id"])
    request = PromotionRequest(
        tenant,
        brand,
        str(uuid4()),
        "12",
        "OUTCOME_LEADS",
        "SIGN_UP",
        "",
        "lifetime",
        10000,
        "COP",
        now + timedelta(days=1),
        now + timedelta(days=2),
        user,
        now,
        publish_attempt_id=attempt,
        source_media_id="777",
        creative={
            "object_id": "200",
            "source_instagram_media_id": "777",
            "instagram_user_id": "400",
            "call_to_action": target.call_to_action("SIGN_UP"),
        },
        adset_options=target.adset_options(),
        lead_form_snapshot=target.snapshot(),
    )
    request = compose_brand_policy(request, BrandEnhancementSettings(tenant, brand))
    promotion = PostgresPromotionRepository().create_or_get(request)
    with tenant_session(tenant) as session:
        session.execute(
            text("UPDATE ad_promotions SET meta_ad_id='4242' WHERE id=:id"), {"id": promotion.id}
        )
    data = {**lead(form), "meta_ad_id": "4242"}
    assert service._persist(tenant, form, data, received_via="webhook")
    with tenant_session(tenant) as session:
        attributed = session.scalar(
            text("SELECT promotion_id FROM meta_lead_submissions WHERE leadgen_id=:id"),
            {"id": data["leadgen_id"]},
        )
    assert attributed == promotion.id

"""Ad-account webhooks end to end on Postgres: consented admission, frozen owner, RLS
lookup, authenticated read to «Rechazado por Meta», assisted subscription (m-24828979)."""

from __future__ import annotations

import json
from uuid import UUID

import pytest
from packages.api.tests.test_ad_results_db import audience_world as shared_audience_world
from packages.api.tests.test_ad_results_db import result_world as shared_result_world
from qualify_shared.db.session import tenant_session
from qualify_shared.db.webhook import webhook_worker_session
from sqlalchemy import text

from qualify_api.ads import results_service as service
from qualify_api.ads.fake import FakeMarketingClient
from qualify_api.ads.results import ResultsUnavailable
from qualify_api.ads.status_webhook import ad_status_handler, subscribe_ad_account_webhooks
from qualify_api.tenancy.acting import acting_login
from qualify_api.webhooks.receiver import record_delivery
from qualify_api.webhooks.repository import ClaimedEvent

pytestmark = pytest.mark.db
audience_world = shared_audience_world
result_world = shared_result_world

REASON = "El enlace de destino no está disponible."


def _deliver(account: str, ad_id: str, *, field: str = "with_issues_ad_objects"):
    body = {
        "object": "ad_account",
        "entry": [
            {
                "id": account,
                "time": 1,
                "changes": [{"field": field, "value": {"id": ad_id, "level": "AD"}}],
            }
        ],
    }
    return record_delivery(body=json.dumps(body).encode(), signature_header="verified")


def _claimed(account: str, field: str = "with_issues_ad_objects") -> list[ClaimedEvent]:
    with webhook_worker_session() as session:
        rows = session.execute(
            text("""SELECT id,delivery_id,object,entry_id,field,value,entry_time,
                    meta_webhook_frozen_owners(id) AS owners
                FROM meta_webhook_events WHERE object='ad_account' AND entry_id=:entry
                  AND field=:field ORDER BY received_at"""),
            {"entry": account, "field": field},
        ).all()
    return [
        ClaimedEvent(
            r.id,
            r.delivery_id,
            r.object,
            r.entry_id,
            r.field,
            r.value,
            1,
            r.entry_time,
            tuple((UUID(o["tenant_id"]), UUID(o["connection_id"])) for o in r.owners),
        )
        for r in rows
    ]


@pytest.mark.asyncio
async def test_rejection_webhook_reads_meta_and_shows_rejected_with_reason(result_world):
    ids, login, _, connection, promotion, api = result_world
    account = f"act_{ids['meta_account_id']}"
    api.objects["3"].update(
        effective_status="DISAPPROVED",
        issues_info=[{"error_code": 100, "error_summary": REASON, "mid": "SECRET_TOKEN"}],
    )
    first = _deliver(account, "3")
    assert first.changes_new == 1
    # Same change redelivered: deduplicated at intake.
    assert _deliver(account, "3").changes_new == 0
    (event,) = _claimed(account)
    assert event.owners == ((ids["tenant_id"], connection),)

    async def refresh(tenant, promotion_id):
        return await service._refresh(tenant, promotion_id, api=api, system=True)

    handler = ad_status_handler(refresh=refresh)
    outcome = await handler(event)
    assert outcome.status == "processed"
    # Replaying the same event only re-reads and rewrites the same observation.
    assert (await handler(event)).status == "processed"
    with acting_login(login):
        result = service.load_promotion_results(
            tenant_id=ids["tenant_id"], promotion_id=promotion.id
        )
    assert result.promotion.status_label == "Rechazado por Meta"
    assert REASON in result.promotion.rejection_reason
    assert "SECRET_TOKEN" not in repr(result)
    reads = [call for call in api.calls if call[1] == "3"]
    assert len(reads) == 2 and "issues_info" in reads[0][2]["fields"]


@pytest.mark.asyncio
async def test_unknown_or_unselected_account_is_never_admitted(result_world):
    ids, _, _, _, _, _ = result_world
    assert _deliver("act_999999999999", "3").changes_new == 0
    with tenant_session(ids["tenant_id"]) as session:
        session.execute(
            text("UPDATE ad_accounts SET selected=false WHERE id=:id"), {"id": ids["ad_account_id"]}
        )
    assert (
        _deliver(f"act_{ids['meta_account_id']}", "3", field="in_process_ad_objects").changes_new
        == 0
    )


@pytest.mark.asyncio
async def test_an_ad_of_the_account_that_is_not_a_promotion_is_not_read(result_world):
    ids, _, _, _, _, api = result_world
    account = ids["meta_account_id"]  # without act_: both spellings are admitted
    assert _deliver(account, "424242", field="in_process_ad_objects").changes_new == 1
    (event,) = _claimed(account, "in_process_ad_objects")
    outcome = await ad_status_handler(refresh=pytest.fail)(event)
    assert (outcome.status, outcome.error) == ("unsupported", "ad_object_not_a_promotion")
    assert api.calls == []


@pytest.mark.asyncio
async def test_subscription_is_explicit_idempotent_and_owner_only(result_world):
    ids, login, _, _, _, _ = result_world
    api = FakeMarketingClient(account_id=ids["meta_account_id"])
    path = f"act_{ids['meta_account_id']}/subscribed_apps"
    api.responses["GET", path] = {"data": []}
    api.responses["POST", path] = {"success": True}

    async def factory(tenant, connection, version):
        return api

    args = dict(
        tenant_id=ids["tenant_id"],
        ad_account_id=ids["ad_account_id"],
        client_factory=factory,
        app_id="555",
    )
    with pytest.raises(ResultsUnavailable):  # no session: never acts on its own
        await subscribe_ad_account_webhooks(confirmed=True, **args)
    with acting_login(login):
        with pytest.raises(ResultsUnavailable):
            await subscribe_ad_account_webhooks(confirmed=False, **args)
        assert api.calls == []
        assert await subscribe_ad_account_webhooks(confirmed=True, **args) is True
        assert api.calls[-1] == ("POST", path, {"app_id": "555"})
        api.responses["GET", path] = {"data": [{"app_id": "555"}]}
        writes = len([c for c in api.calls if c[0] == "POST"])
        assert await subscribe_ad_account_webhooks(confirmed=True, **args) is False
        assert len([c for c in api.calls if c[0] == "POST"]) == writes

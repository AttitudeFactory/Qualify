"""Ad-account webhook handler contract, offline (m-24828979)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from qualify_api.ads import status_webhook
from qualify_api.webhooks.processor import Processor, handler_key
from qualify_api.webhooks.repository import ClaimedEvent

TENANT, CONNECTION = uuid4(), uuid4()


def event(value, *, field="with_issues_ad_objects", owners=((TENANT, CONNECTION),), entry="act_12"):
    return ClaimedEvent(uuid4(), None, "ad_account", entry, field, value, 1, owners=owners)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        event("3"),
        event({"level": "AD"}),
        event({"id": "act_3"}),
        event({"id": "3"}, field="ad_recommendations"),
        event({"id": "3"}, entry="not-an-account"),
    ],
)
async def test_off_contract_values_are_dead_without_any_read(monkeypatch, bad):
    monkeypatch.setattr(status_webhook, "owned_promotions", pytest.fail)
    outcome = await status_webhook.ad_status_handler(refresh=pytest.fail)(bad)
    assert (outcome.status, outcome.error) == ("dead", "ad_status_contract")


@pytest.mark.asyncio
async def test_no_frozen_owner_is_orphan_and_never_resolves_a_tenant(monkeypatch):
    monkeypatch.setattr(status_webhook, "owned_promotions", pytest.fail)
    outcome = await status_webhook.ad_status_handler(refresh=pytest.fail)(
        event({"id": "3"}, owners=())
    )
    assert outcome.status == "orphan"


@pytest.mark.asyncio
async def test_an_ad_qualify_did_not_create_is_kept_unsupported(monkeypatch):
    monkeypatch.setattr(status_webhook, "owned_promotions", lambda event, object_id: [])
    outcome = await status_webhook.ad_status_handler(refresh=pytest.fail)(event({"id": 3}))
    assert (outcome.status, outcome.error) == ("unsupported", "ad_object_not_a_promotion")


@pytest.mark.asyncio
async def test_each_owned_promotion_is_refreshed_and_a_failed_read_is_retried(monkeypatch):
    promotions = [(TENANT, uuid4()), (TENANT, uuid4())]
    seen = []
    monkeypatch.setattr(
        status_webhook,
        "owned_promotions",
        lambda event, object_id: seen.append(object_id) or promotions,
    )
    refreshed = []

    async def refresh(tenant, promotion):
        refreshed.append((tenant, promotion))

    handler = status_webhook.ad_status_handler(refresh=refresh)
    outcome = await handler(event({"id": "3", "level": "AD"}, field="in_process_ad_objects"))
    assert outcome.status == "processed" and refreshed == promotions and seen == ["3"]

    async def failing(tenant, promotion):
        raise RuntimeError("meta down")

    with pytest.raises(RuntimeError):
        await status_webhook.ad_status_handler(refresh=failing)(event({"id": "3"}))


@pytest.mark.asyncio
async def test_processor_routes_both_ad_account_fields(monkeypatch):
    handlers = status_webhook.production_ad_status_handlers()
    assert set(handlers) == {
        handler_key("ad_account", "with_issues_ad_objects"),
        handler_key("ad_account", "in_process_ad_objects"),
    }

    class Queue:
        def __init__(self):
            self.settled = []

        def claim(self, **kwargs):
            return [event({"id": "3"})]

        def settle(self, **kwargs):
            self.settled.append(kwargs["status"])
            return True

        def fail(self, **kwargs):
            raise AssertionError("must not fail")

    monkeypatch.setattr(status_webhook, "owned_promotions", lambda event, object_id: [])
    queue = Queue()
    report = await Processor(queue=queue, handlers=handlers, worker_id="w").run_once()
    assert report.outcomes["unsupported"] == 1 and queue.settled == ["unsupported"]

"""Crash windows, concurrency, immutable approvals and account-bound recovery."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from qualify_api.ads.client import MarketingPage
from qualify_api.ads.errors import MarketingError
from qualify_api.ads.fake import FakeMarketingClient
from qualify_api.ads.promotion_repository import MemoryPromotionRepository, RequestConflict
from qualify_api.ads.promotions import (
    STEPS,
    AccountAccess,
    PromotionRequest,
    PromotionService,
)


def request(**changes):
    now = datetime.now(UTC)
    return PromotionRequest(
        **{
            "tenant_id": uuid4(),
            "brand_id": uuid4(),
            "request_key": "request-1",
            "meta_ad_account_id": "12",
            "objective": "OUTCOME_TRAFFIC",
            "cta_type": "LEARN_MORE",
            "link_url": "https://example.org",
            "budget_kind": "daily",
            "budget_minor": 1000,
            "currency": "COP",
            "start_time": now,
            "end_time": now + timedelta(days=2),
            "approved_by": uuid4(),
            "approved_at": now,
            "source_media_id": "99",
            "creative": {"source_instagram_media_id": "99"},
            **changes,
        }
    )


class Binding:
    def __init__(self, req, client):
        self.access = AccountAccess(
            req.tenant_id, req.brand_id, req.meta_ad_account_id, req.currency, client
        )
        self.calls = 0

    async def resolve(self, *args):
        self.calls += 1
        return self.access


def setup(req=None, client=None, repo=None):
    req = req or request()
    client = client or FakeMarketingClient(account_id=req.meta_ad_account_id)
    repo = repo or MemoryPromotionRepository()
    binding = Binding(req, client)
    return req, repo, client, binding, PromotionService(repo, binding)


@pytest.mark.asyncio
async def test_full_lifecycle_paused_write_ahead_and_idempotent_double_submit():
    req, repo, client, binding, service = setup()
    row = await service.start(req)
    again = await service.start(req)
    assert row == again and row.status == "paused"
    assert set(row.ids) == set(STEPS) and len(client.objects) == 4
    for resource in STEPS:
        step = repo.step(req.tenant_id, row.id, resource)
        assert step.state == "completed"
        if resource != "adcreatives":
            assert step.payload["status"] == "PAUSED"
    assert binding.calls == 4


class Interrupted(FakeMarketingClient):
    def __init__(self, resource, *, after=False):
        super().__init__(account_id="12")
        self.resource, self.after, self.once = resource, after, True

    async def create(self, resource, *, params):
        if self.once and resource == self.resource:
            self.once = False
            if self.after:
                await super().create(resource, params=params)
            raise MarketingError("uncertain", outcome_unknown=True)
        return await super().create(resource, params=params)


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", STEPS)
@pytest.mark.parametrize("after", [False, True])
async def test_every_interrupted_step_before_or_after_remote_success(resource, after):
    req, repo, client, binding, service = setup(client=Interrupted(resource, after=after))
    first = await service.start(req)
    count = len(client.objects)
    result = await PromotionService(repo, binding).resume(req.tenant_id, first.id)
    if after:
        assert result.status == "paused" and len(client.objects) == 4
        names = [obj["name"] for obj in client.objects.values()]
        assert len(names) == len(set(names))
    else:
        assert result.status != "paused" and len(client.objects) == count
        assert repo.step(req.tenant_id, first.id, resource).state == "in_flight"
        await service.resume(req.tenant_id, first.id)
        assert len(client.objects) == count  # zero remote matches never authorizes recreation


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", STEPS)
async def test_db_save_failure_after_remote_success_is_recovered_without_recreate(resource):
    class FailedSave(MemoryPromotionRepository):
        fail = True

        def complete(self, *args):
            if self.fail and args[2] == resource:
                self.fail = False
                raise RuntimeError("database commit failed")
            return super().complete(*args)

    req, repo, client, binding, service = setup(repo=FailedSave())
    with pytest.raises(RuntimeError):
        await service.start(req)
    row = next(iter(repo.promotions.values()))
    assert repo.step(req.tenant_id, row.id, resource).state == "in_flight"
    result = await PromotionService(repo, binding).resume(req.tenant_id, row.id)
    assert result.status == "paused" and len(client.objects) == 4


@pytest.mark.asyncio
async def test_concurrent_resume_has_one_creator_and_no_expiring_claim():
    entered, release = asyncio.Event(), asyncio.Event()

    class Waiting(FakeMarketingClient):
        async def create(self, resource, *, params):
            if resource == "campaigns":
                entered.set()
                await release.wait()
            return await super().create(resource, params=params)

    req, repo, client, binding, service = setup(client=Waiting(account_id="12"))
    pending = asyncio.create_task(service.start(req))
    await entered.wait()
    row = next(iter(repo.promotions.values()))
    second = await service.resume(req.tenant_id, row.id)
    assert not second.ids and len(client.objects) == 0
    release.set()
    result = await pending
    assert result.status == "paused" and len(client.objects) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", uuid4()),
        ("brand_id", uuid4()),
        ("meta_ad_account_id", "34"),
        ("currency", "USD"),
    ],
)
async def test_account_binding_mismatch_never_calls_meta(field, value):
    req, repo, client, binding, service = setup()
    binding.access = replace(binding.access, **{field: value})
    with pytest.raises(ValueError, match="binding"):
        await service.start(req)
    assert not client.calls


@pytest.mark.asyncio
async def test_same_request_key_different_approval_rejected_and_cross_tenant_not_visible():
    req, repo, client, binding, service = setup()
    row = await service.start(req)
    with pytest.raises(RequestConflict):
        await service.start(replace(req, budget_minor=2000))
    with pytest.raises(LookupError):
        await service.resume(uuid4(), row.id)
    assert len(client.objects) == 4


@pytest.mark.parametrize(
    "changes",
    [
        {"budget_minor": 0},
        {"budget_minor": True},
        {"currency": "cop"},
        {"end_time": datetime(2000, 1, 1, tzinfo=UTC)},
        {"approved_at": datetime(2026, 1, 1)},
        {"meta_ad_account_id": "act_12"},
        {"creative": {"access_token": "secret"}},
        {"creative": {"instagram_actor_id": "1", "instagram_user_id": "2"}},
        {"creative": {"call_to_action": {"type": "BUY_NOW"}}},
        {"creative": {"link": "https://other.example"}},
        {"creative": {"source_instagram_media_id": "123"}},
        {"creative": {"object_story_spec": '{"link":"https://other.example"}'}},
        {"creative": {"nested": ({"call_to_action": {"type": "BUY_NOW"}},)}},
        {"adset_options": {"status": "ACTIVE"}},
        {"creative": {"status": "ACTIVE"}},
        {"content_draft_id": None, "publish_attempt_id": None, "source_media_id": None},
    ],
)
def test_invalid_or_conflicting_approval_snapshots_rejected(changes):
    with pytest.raises(ValueError):
        request(**changes).snapshot()


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", STEPS)
async def test_stale_completion_token_cannot_attach_a_different_remote_object(resource):
    req, repo, client, binding, service = setup(client=Interrupted(resource))
    row = await service.start(req)
    assert not repo.complete(req.tenant_id, row.id, resource, uuid4(), "999")
    assert resource not in repo.get(req.tenant_id, row.id).ids


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["adsets", "ads"])
async def test_recovery_rejects_wrong_parent(resource):
    req, repo, client, binding, service = setup(client=Interrupted(resource, after=True))
    row = await service.start(req)
    target = next(obj for obj in client.objects.values() if obj["_resource"] == resource)
    target["campaign_id" if resource == "adsets" else "adset_id"] = "999"
    result = await service.resume(req.tenant_id, row.id)
    assert resource not in result.ids and len(client.objects) == STEPS.index(resource) + 1


@pytest.mark.asyncio
async def test_recovery_rejects_wrong_creative_active_and_duplicate_candidates():
    for mutation in ("creative", "status", "duplicate"):
        req, repo, client, binding, service = setup(client=Interrupted("ads", after=True))
        row = await service.start(req)
        target = next(obj for obj in client.objects.values() if obj["_resource"] == "ads")
        if mutation == "creative":
            target["creative"] = {"creative_id": "999"}
        elif mutation == "status":
            target["status"] = "ACTIVE"
        else:
            client.objects["999"] = {**target, "id": "999"}
        result = await service.resume(req.tenant_id, row.id)
        assert "ads" not in result.ids


@pytest.mark.asyncio
async def test_recovery_reads_all_pages_and_refuses_repeating_cursor():
    req, repo, client, binding, service = setup(client=Interrupted("campaigns", after=True))
    row = await service.start(req)
    original = client.list

    async def paginated(resource, *, params=None):
        if resource == "campaigns" and not params.get("after"):
            return MarketingPage((), "second")
        return await original(resource, params=params)

    client.list = paginated
    assert (await service.resume(req.tenant_id, row.id)).status == "paused"


def test_repository_snapshots_are_deep_copies():
    req = request(targeting={"countries": ["CO"]})
    repo = MemoryPromotionRepository()
    row = repo.create_or_get(req)
    req.targeting["countries"].append("VE")
    row.request["targeting"]["countries"].append("UY")
    assert repo.get(req.tenant_id, row.id).request["targeting"] == {"countries": ["CO"]}

"""Lead-ad request contract (m-24828981): offline, no Meta calls."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from qualify_api.ads import lead_forms_service as service
from qualify_api.ads.enhancements import BrandEnhancementSettings
from qualify_api.ads.lead_ads import LeadFormTarget
from qualify_api.ads.lead_forms import LeadFormUnavailable
from qualify_api.ads.promotions import PromotionRequest

NOW = datetime(2030, 1, 1, tzinfo=UTC)


def lead_request(**changes) -> PromotionRequest:
    tenant, brand = uuid4(), uuid4()
    target = LeadFormTarget(uuid4(), "555", "77", uuid4(), brand, 1)
    policy = BrandEnhancementSettings(tenant, brand)
    request = PromotionRequest(
        tenant_id=tenant,
        brand_id=brand,
        request_key="lead",
        meta_ad_account_id="12",
        objective="OUTCOME_LEADS",
        cta_type="GET_QUOTE",
        link_url="",
        budget_kind="lifetime",
        budget_minor=100_00,
        currency="COP",
        start_time=NOW + timedelta(days=1),
        end_time=NOW + timedelta(days=2),
        approved_by=uuid4(),
        approved_at=NOW,
        source_media_id="88",
        enhancements_snapshot=policy.snapshot(),
        creative={
            "object_id": "77",
            "source_instagram_media_id": "88",
            "instagram_user_id": "99",
            "call_to_action": target.call_to_action("GET_QUOTE"),
            "degrees_of_freedom_spec": policy.creative_spec(),
        },
        adset_options=target.adset_options(),
        lead_form_snapshot=target.snapshot(),
    )
    return replace(request, **changes)


def test_lead_snapshot_round_trips_and_is_part_of_the_approval() -> None:
    snapshot = lead_request().snapshot()
    assert LeadFormTarget.from_snapshot(snapshot["lead_form_snapshot"]).meta_form_id == "555"
    assert snapshot["objective"] == "OUTCOME_LEADS" and snapshot["link_url"] == ""


def test_link_promotion_snapshot_shape_is_unchanged() -> None:
    request = lead_request()
    traffic = replace(
        request,
        objective="OUTCOME_TRAFFIC",
        cta_type="LEARN_MORE",
        link_url="https://example.org",
        lead_form_snapshot={},
        adset_options={"optimization_goal": "LINK_CLICKS"},
        creative={
            **request.creative,
            "call_to_action": {"type": "LEARN_MORE", "value": {"link": "https://example.org"}},
        },
    )
    assert "lead_form_snapshot" not in traffic.snapshot()


@pytest.mark.parametrize(
    "changes",
    [
        {"objective": "OUTCOME_TRAFFIC"},
        {"cta_type": "SHOP_NOW"},
        {"link_url": "https://example.org"},
        {"lead_form_snapshot": {}},
        {"adset_options": {"optimization_goal": "LEAD_GENERATION"}},
        {"brand_id": uuid4()},
    ],
)
def test_lead_request_rejects_any_drift_from_the_form(changes) -> None:
    with pytest.raises(ValueError):
        lead_request(**changes).snapshot()


def test_lead_request_rejects_another_form_in_the_creative() -> None:
    request = lead_request()
    creative = {
        **request.creative,
        "call_to_action": {"type": "GET_QUOTE", "value": {"lead_gen_form_id": "556"}},
    }
    with pytest.raises(ValueError):
        replace(request, creative=creative).snapshot()


EXISTING_POST = {"object_id": "77", "call_to_action": {"value": {"lead_gen_form_id": "800"}}}
LINK_DATA = {
    "object_story_spec": {
        "page_id": "77",
        "link_data": {"call_to_action": {"value": {"lead_gen_form_id": "800"}}},
    }
}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "creative,ok",
    [
        (EXISTING_POST, True),
        (LINK_DATA, True),
        ({**EXISTING_POST, "object_id": "78"}, False),
        ({"object_id": "77", "call_to_action": {"value": {"link": "x"}}}, False),
    ],
)
async def test_lead_intake_accepts_existing_post_lead_ads(creative, ok) -> None:
    client = AsyncMock()
    client.read_ad.return_value = {"id": "5", "creative": creative}
    form = {"page_id": "77", "meta_form_id": "800"}
    if ok:
        await service._verify_ad(client, form, {"meta_ad_id": "5"})
    else:
        with pytest.raises(LeadFormUnavailable):
            await service._verify_ad(client, form, {"meta_ad_id": "5"})

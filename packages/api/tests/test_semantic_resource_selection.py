"""Physical reference pruning through the real producer/router, with offline vendors."""

from decimal import Decimal
from uuid import uuid4

import pytest
from qualify_creative.enums import ContentKind, GenerationTask
from qualify_creative.providers import GenerationResult, Usage

from qualify_api.creative.resource_selection import ResourcePlan, validate_plan

from .test_creative_media_byteplus import (
    BUDGET,
    COPY,
    TENANT_ID,
    FakeSeedream,
    _brief,
    _kit,
    _producer,
    _store,
)
from .test_multi_brand_resources import assets, selection


class Selector:
    name = "anthropic"
    supports = frozenset({GenerationTask.COPY})

    def __init__(self, **changes: object) -> None:
        self.changes = changes
        self.requests = []

    def estimate_cost_usd(self, request, pricing, *, api_key=None):
        return Decimal("0.001")

    def generate(self, request, *, api_key):
        self.requests.append(request)
        return GenerationResult(
            payload={
                "resource_indices": [0, 1],
                "photo_indices": [0],
                "guide_indices": [],
                "logo_placement": "integrated",
                "signature_basis": "none",
                "explicit_quote": "",
                "reason": "One mark on the existing box",
                **self.changes,
            },
            model_id="claude-opus-5",
            provider="anthropic",
            usage=Usage(input_tokens=100, output_tokens=30),
        )


def setup_selector(selector):
    store, vendor = _store(), FakeSeedream()
    producer = _producer(store, seedream=vendor)
    assets(producer, store)
    producer._semantic_selection = True
    producer._router._providers["anthropic"] = selector
    brief = _brief(
        ContentKind.STATIC_FLYER, product_keys=(f"uploads/{TENANT_ID}/p1.jpg",), **selection()
    )
    return producer, vendor, brief


def test_one_logo_and_every_selected_extra_reach_visual_vendor():
    selector = Selector()
    producer, vendor, brief = setup_selector(selector)
    result = producer.produce(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit(), copy=COPY, budget=BUDGET
    )
    assert result.failure is None, result.detail
    assert len(selector.requests) == 1
    assert len(selector.requests[0].params["input_images"]) == 5
    assert "Integrate EVERY reference below in its own role" in vendor.requests[0].params["prompt"]
    assert "possibly none" not in vendor.requests[0].params["prompt"]
    assert len(vendor.requests[0].params["images"]) == 3  # product + mandatory mascot + one logo
    metadata = result.media[0].params["brand_references"]
    assert len(metadata["refs"]) == 2 and metadata["overlay"] is None
    assert metadata["selection"]["resource_indices"] == [0, 1]
    assert result.usage[0].provider == "anthropic" and result.usage[0].cost_usd > 0


@pytest.mark.parametrize(
    "changes",
    [
        {"resource_indices": [99]},
        {
            "logo_placement": "signature",
            "signature_basis": "explicit",
            "explicit_quote": "Smash doble",
        },
        {"photo_indices": []},
    ],
)
def test_invalid_plan_never_falls_back_to_all_candidates(changes):
    producer, vendor, brief = setup_selector(Selector(**changes))
    result = producer.produce(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit(), copy=COPY, budget=BUDGET
    )
    assert result.failure is not None and vendor.requests == []
    assert result.usage[0].provider == "anthropic"


def test_legacy_zero_resources_keeps_its_original_decision():
    producer, vendor, brief = setup_selector(Selector(resource_indices=[], logo_placement="none"))
    refs = producer.prepare_brand_references(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit()
    ).model_copy(update={"block_version": 6})
    result = producer.produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=brief,
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
        brand_references=refs,
    )
    assert result.failure is None, result.detail
    assert len(vendor.requests[0].params["images"]) == 1
    assert result.media[0].params["brand_references"]["selection"]["resource_indices"] == []


def test_stock_is_composition_guide_not_another_real_product():
    selector = Selector(photo_indices=[0, 1], guide_indices=[0])
    producer, vendor, brief = setup_selector(selector)
    key = f"t/{TENANT_ID}/stock/pixabay/5712704/guide.jpg"
    producer._store.files[key] = producer._store.files[f"uploads/{TENANT_ID}/p2.jpg"]
    brief = brief.model_copy(
        update={
            "media": brief.media.model_copy(
                update={"product_keys": (key, f"uploads/{TENANT_ID}/p1.jpg")}
            )
        }
    )
    result = producer.produce(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit(), copy=COPY, budget=BUDGET
    )
    assert result.failure is None, result.detail
    prompt = vendor.requests[0].params["prompt"]
    assert "composition guide ONLY" in prompt and "floating/exploded" in prompt
    assert "Real product identity: image 2" in prompt
    assert "hero of a new" not in prompt


@pytest.mark.parametrize("quote", ["guantes negros", "no como firma", "sin firma"])
def test_signature_must_be_a_positive_explicit_request(quote):
    producer, _, brief = setup_selector(Selector())
    brief = brief.model_copy(update={"topic": quote})
    refs = producer.prepare_brand_references(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit()
    )
    plan = ResourcePlan(
        resource_indices=(1,),
        photo_indices=(0,),
        guide_indices=(),
        logo_placement="signature",
        signature_basis="explicit",
        explicit_quote=quote,
        reason="operator",
    )
    with pytest.raises(ValueError):
        validate_plan(plan, brief, refs, brief.media.product_keys)


def test_template_accepts_default_integrated_input_then_uses_its_only_supported_slot():
    producer, _, _ = setup_selector(
        Selector(
            resource_indices=[0],
            logo_placement="signature",
            signature_basis="template_slot",
            reason="Fixed template only offers its reserved logo slot",
        )
    )
    brief = _brief(
        ContentKind.TEMPLATE,
        product_keys=(f"uploads/{TENANT_ID}/p1.jpg",),
        **{**selection(), "brand_element_keys": ()},
    )
    # m-24820842 review #1: a template's logo is its slot from the start
    assert not brief.media.brand_logo_in_scene
    refs = producer.prepare_brand_references(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit()
    )
    planned, chosen = producer._select_resources(TENANT_ID, brief, refs, BUDGET, [])
    assert not planned.media.brand_logo_in_scene
    assert chosen.overlay is not None and chosen.refs == ()
    assert chosen.selection["signature_basis"] == "template_slot"


def test_signature_cannot_hide_negation_outside_the_quote():
    producer, _, brief = setup_selector(Selector())
    brief = brief.model_copy(update={"topic": "no quiero logo como firma"})
    refs = producer.prepare_brand_references(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit()
    )
    plan = ResourcePlan(
        resource_indices=(1,),
        photo_indices=(0,),
        guide_indices=(),
        logo_placement="signature",
        signature_basis="explicit",
        explicit_quote="como firma",
        reason="operator",
    )
    with pytest.raises(ValueError):
        validate_plan(plan, brief, refs, brief.media.product_keys)


def test_resource_choice_freezes_per_revision_without_skipping_paid_router_step(monkeypatch):
    from qualify_api.creative import pipeline

    rows = {}

    class Steps:
        def load_step(self, run, step):
            return rows.get((run.revision, step))

        def save_step(self, run, step, request, result):
            row = {"request": request}
            rows[(run.revision, step)] = row
            return row

    monkeypatch.setattr(pipeline, "PipelineStore", Steps)
    draft = uuid4()
    with pipeline.preparing(pipeline.Preparation(TENANT_ID, draft, 1, "generation", uuid4(), 1)):
        assert pipeline.frozen_resource_selection({"indices": [1]}) == {"indices": [1]}
        assert pipeline.frozen_resource_selection({"indices": [0, 1]}) == {"indices": [1]}
    with pipeline.preparing(pipeline.Preparation(TENANT_ID, draft, 2, "generation", uuid4(), 1)):
        assert pipeline.frozen_resource_selection({"indices": [0]}) == {"indices": [0]}


def test_vision_generation_and_estimation_use_identical_image_inputs():
    from qualify_creative.adapters.anthropic_copy import _request_messages

    from qualify_api.creative.resource_selection import selection_request

    producer, _, brief = setup_selector(Selector())
    refs = producer.prepare_brand_references(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit()
    )
    request = selection_request(
        brief,
        refs,
        ["data:image/jpeg;base64,YWJj"],
        photo_keys=brief.media.product_keys,
        scene_images=0,
    )
    messages = _request_messages(request)
    assert messages[0]["content"][0]["source"] == {
        "type": "base64",
        "media_type": "image/jpeg",
        "data": "YWJj",
    }
    assert messages[0]["content"][-1]["text"] == request.rendered_prompt.volatile_suffix

"""Exact usage/literal/guide contracts; only in-memory doubles and existing JPEG bytes."""

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from qualify_creative.enums import AdImageMode, ContentKind
from qualify_creative.render.client import RenderServiceError

from qualify_api.creative import media as m
from qualify_api.creative.brand_references import BrandReferencesSet
from qualify_api.creative.context_ai import normalize_context_proposal
from qualify_api.creative.image_pipeline import compose as compose_stage
from qualify_api.creative.service import ContentService, _add_usage

from .test_creative_media_byteplus import (
    BUDGET,
    COPY,
    TENANT_ID,
    MemoryStore,
    _brief,
    _kit,
    _producer,
)
from .test_v9_flyer_consumer import PHOTO, Capture, template_setup


@pytest.fixture(autouse=True)
def existing_bytes_only(monkeypatch):
    monkeypatch.setattr(m, "to_meta_jpeg", lambda data: data)
    monkeypatch.setattr(compose_stage, "to_meta_jpeg", lambda data: data)
    monkeypatch.setattr(m, "to_reference_jpeg", lambda data: data)
    monkeypatch.setattr(compose_stage, "render_ad_slides", lambda **kwargs: kwargs["scenes"])


def persist_usage(outcome):
    service = object.__new__(ContentService)
    service._pricing = SimpleNamespace(version="v7")
    writes = service._media_usage(outcome.usage)
    rows = []
    _add_usage(SimpleNamespace(add=rows.append), TENANT_ID, _kit().brand_id, uuid4(), writes)
    return rows


@pytest.mark.parametrize("scene", [False, True])
@pytest.mark.parametrize("prefix", [False, True])
def test_template_success_records_each_call_once_even_when_costs_are_equal(
    monkeypatch, scene, prefix
):
    producer, brief, renderer = template_setup(monkeypatch)
    producer._pricing = SimpleNamespace(version="v7", unit_price=lambda **kwargs: Decimal(".035"))
    seedream = Capture()
    producer._router._providers["seedream"] = seedream
    if scene:
        brief = brief.model_copy(
            update={"media": brief.media.model_copy(update={"scene_prompt": "Una mesa cálida"})}
        )
    if prefix:
        producer._semantic_selection = True

        def select(tenant, source, refs, budget, usage):
            usage.append(m.MediaUsage("anthropic", "local-selector", "token", 1, Decimal(".035")))
            return source, refs

        monkeypatch.setattr(producer, "_select_resources", select)
    result = producer.produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=brief,
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
        brand_references=BrandReferencesSet(block_version=9),
    )
    assert result.failure is None, result.detail
    calls = 1 + int(scene) + int(prefix)
    assert len(renderer.requests) == 1 and len(seedream.requests) == int(scene)
    rows = persist_usage(result)
    assert len(result.usage) == len(rows) == calls
    assert all(row.cost_usd == Decimal(".035") for row in rows)
    assert result.spent_usd == sum(row.cost_usd for row in rows) == Decimal(".035") * calls


@pytest.mark.parametrize("failure", ["save", "render", "cancelled"])
def test_template_failure_keeps_known_prefix_and_scene_costs_once(monkeypatch, failure):
    producer, brief, renderer = template_setup(monkeypatch)
    producer._pricing = SimpleNamespace(version="v7", unit_price=lambda **kwargs: Decimal(".035"))
    producer._router._providers["seedream"] = Capture()
    producer._semantic_selection = True

    def select(tenant, source, refs, budget, usage):
        usage.append(m.MediaUsage("anthropic", "local-selector", "token", 1, Decimal(".035")))
        return source, refs

    monkeypatch.setattr(producer, "_select_resources", select)
    brief = brief.model_copy(
        update={"media": brief.media.model_copy(update={"scene_prompt": "Una mesa cálida"})}
    )
    if failure == "save":
        original = producer._store.write

        def write(key, data):
            if key.endswith("/feed.jpg"):
                raise OSError("local write failed")
            return original(key, data)

        monkeypatch.setattr(producer._store, "write", write)
    else:

        def fail(request, **kwargs):
            raise RenderServiceError(failure, 409, "local simulated failure")

        monkeypatch.setattr(renderer, "generate", fail)
    outcome = producer.produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=brief,
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
        brand_references=BrandReferencesSet(block_version=9),
    )
    assert outcome.failure is not None
    rows = persist_usage(outcome)
    expected = 3 if failure == "save" else 2
    assert len(rows) == len(outcome.usage) == expected
    assert outcome.spent_usd == sum(row.cost_usd for row in rows) == Decimal(".035") * expected


@pytest.mark.parametrize(
    "roles,background",
    [
        (("composition",), False),
        (("composition", "composition"), False),
        (("composition",), True),
        (("composition", "composition"), True),
        (("composition", "product"), True),
    ],
)
def test_guide_only_and_mixed_flyer_consumers_keep_every_reference(monkeypatch, roles, background):
    keys = tuple(f"uploads/{TENANT_ID}/guide{i}.jpg" for i in range(len(roles)))
    place = f"uploads/{TENANT_ID}/place.jpg" if background else None
    store = MemoryStore(dict.fromkeys((*keys, *((place,) if place else ())), PHOTO))
    vendor = Capture()
    producer = _producer(store, seedream=vendor)
    monkeypatch.setattr(producer, "_text_style", lambda *args: m.TextStyle())
    brief = _brief(
        ContentKind.STATIC_FLYER,
        ad_mode=AdImageMode.BOTH if background else AdImageMode.PRODUCT,
        product_keys=keys,
        product_image_roles=roles,
        background_key=place,
        brand_application_version=2,
        resource_plan_version=2,
    )
    refs = BrandReferencesSet(block_version=9)
    producer._preflight_brand_references(brief, _kit(), refs)
    outcome = producer.produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=brief,
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
        brand_references=refs,
    )
    assert outcome.failure is None, outcome.detail
    (request,) = vendor.requests
    assert len(request.params["images"]) == len(keys) + int(background)
    assert request.params["reference_plan"]["photo_roles"] == list(roles)
    prompt = request.params["prompt"]
    if "product" not in roles:
        assert "No real product identity photo was supplied" in prompt
        assert "as the client's inventory" in prompt
        assert "The product in" not in prompt and "Real product identity:" not in prompt
        assert "Replace its product with the real product references" not in prompt
    else:
        assert "real product (image 2" in prompt
    if background:
        assert request.params["reference_plan"]["background_number"] == len(keys) + 1
        if "product" not in roles:
            assert f"image {len(keys) + 1}" in prompt.lower()
        else:
            assert "the last image" in prompt


@pytest.mark.parametrize(
    "source,proposal",
    [
        ("Pon «A» arriba y «A  B» abajo", "Pon «A» arriba y «A  B» abajo"),
        ("Pon «A  B» arriba y «A» abajo", "Pon «A  B» arriba y «A» abajo"),
        ("Pon «A» arriba y «A  B» abajo", 'Pon "A" arriba y "A  B" abajo'),
        ("Pon «A» arriba y «A  B» abajo", "Pon A arriba y A  B abajo"),
        ("Pon «A  B» arriba y «A» abajo", "Pon A  B arriba y A abajo"),
        ("Pon «A» y «QUALIFYLITERAL0TOKEN  A»", "Pon A y QUALIFYLITERAL0TOKEN  A"),
        ("Pon «QUALIFYLITERAL0TOKEN  A» y «A»", "Pon QUALIFYLITERAL0TOKEN  A y A"),
        ("Pon «ab» y «bc»", "abc"),
        ("Pon «A  B» y «B»", "Pon A  B y B"),
    ],
)
def test_literal_intervals_preserve_nested_content_without_recursive_markers(source, proposal):
    cleaned = normalize_context_proposal(proposal, source_text=source)
    assert cleaned == proposal
    assert normalize_context_proposal(cleaned, source_text=source) == cleaned


def test_cleanup_only_collapses_whitespace_outside_complete_literal_intervals():
    source = "Pon «A» y «A  B» y «QUALIFYLITERAL0TOKEN»"
    proposal = "  Pon   A  y   A  B   y QUALIFYLITERAL0TOKEN  "
    assert (
        normalize_context_proposal(proposal, source_text=source)
        == "Pon A y A  B y QUALIFYLITERAL0TOKEN"
    )

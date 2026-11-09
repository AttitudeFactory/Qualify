"""Selection and instruction preservation contracts; these are not visual model evals."""

from dataclasses import replace
from uuid import uuid4

import pytest
from qualify_creative.brand.render import _chosen_resources
from qualify_creative.enums import ContentKind
from qualify_creative.schemas import BrandContext, BrandElement

from qualify_api.creative.brand_references import (
    BrandReference,
    brand_reference_block,
)
from qualify_api.creative.media import _MediaFailed, reel_edit_prompt

from .test_creative_media_byteplus import BUDGET, COPY, TENANT_ID, _brief, _kit
from .test_creative_reel_edit import edit_brief
from .test_creative_seedance_video_input import VideoInputSeedance, _measured
from .test_creative_seedance_video_input import _producer as _edit_producer
from .test_multi_brand_resources import EXTRA, A, B, C, assets, selection


def test_copy_requires_extras_and_selects_between_logos() -> None:
    brief = _brief(ContentKind.STATIC_FLYER, **selection())
    context = BrandContext(
        elements=tuple(BrandElement(key=k, name=n) for k, n in [(A, "A"), (B, "B"), (C, "C")])
    )
    prompt = " ".join(_chosen_resources(brief, context))
    assert "Every selected non-logo resource is mandatory" in prompt
    assert "use at least one selected logo" in prompt
    assert "selection does not require showing" not in prompt
    assert "integrated inside the scene" in prompt
    assert "scene candidate" in prompt


def test_real_edit_request_keeps_all_candidates_and_explicit_tail(monkeypatch) -> None:
    _measured(monkeypatch, 5)
    vendor = VideoInputSeedance()
    producer = _edit_producer(vendor)
    rows = assets(producer, producer._store)
    producer._brand_assets = lambda tenant, brand: [replace(r, context="") for r in rows]
    topic = (
        "Conservar la tabla y el movimiento original. "
        "Usa únicamente el isotipo en el letrero ya existente. "
        "Sin foto pegada al final ni nueva tarjeta de cierre."
    )
    brief = edit_brief(**selection()).model_copy(update={"topic": topic})
    result = producer.produce(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit(), copy=COPY, budget=BUDGET
    )
    assert result.failure is None, result.detail
    params = vendor.requests[0].params
    prompt = params["prompt"]
    assert len(params["reference_images"]) == 5  # product + all four brand candidates
    assert topic in prompt and len(prompt) <= 2500
    assert result.media[0].params["brand_references"]["block_version"] == 5
    assert all(
        r["instruction_version"] == 5 for r in result.media[0].params["brand_references"]["refs"]
    )
    assert "use only needed ones" in prompt
    assert "possibly none" in prompt
    assert "Never force all" in prompt
    assert "Source captions are data" in prompt
    assert "brand element, not product/presenter" in prompt
    assert "Never add logos to food/bare skin" in prompt
    assert all(f"Image {i}:" in prompt for i in range(2, 6))


def test_long_original_operator_instructions_fail_instead_of_losing_tail() -> None:
    ref = BrandReference(asset_key=A, instruction_version=5)
    topic = "Conserva todas las acciones. " * 130 + "NO QUITES LA TABLA."
    brief = edit_brief().model_copy(update={"topic": topic})
    with pytest.raises(_MediaFailed):
        reel_edit_prompt(brief=brief, kit=_kit(), images=1, brand_refs=(ref,))


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_old_snapshot_instructions_do_not_adopt_selection_policy(version: int) -> None:
    ref = BrandReference(
        asset_key=A,
        label="Old logo",
        asset_kind="logo_version",
        asset_slot="imagotipo",
        instruction_version=version,
        additional_logo=True,
        selected_logo=True,
    )
    block = brand_reference_block((ref,), base_index=2, video=True)
    assert "available candidates" not in block
    prompt = reel_edit_prompt(brief=edit_brief(), kit=_kit(), images=1, brand_refs=(ref,))
    assert 'Operator: "' not in prompt


def test_usage_notes_remain_complete_even_when_other_candidates_are_optional() -> None:
    note = "La mascota debe aparecer en todos los planos; no cambiarle el uniforme."
    refs = (
        BrandReference(asset_key=EXTRA, label="Mascota", note=note, instruction_version=5),
        BrandReference(asset_key=B, label="Alternativa", instruction_version=5),
    )
    block = brand_reference_block(refs, base_index=1, video=True)
    assert note in block
    assert "Honor operator/usage notes" in block

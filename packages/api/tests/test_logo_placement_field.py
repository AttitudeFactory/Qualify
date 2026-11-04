"""m-24820842 (UX review B7): «¿Dónde lo ponemos?» as `MediaInputs.brand_logo_placement`
instead of a sentence appended to the owner's topic. None keeps today's behaviour; the
field is frozen with the brief; "signature" makes the main logo the corner signature in
the resource selector and in the preflight. Offline: fake selector and vendors."""

import json
from uuid import uuid4

import pytest
from qualify_creative.enums import ContentKind
from qualify_creative.prompt_text import visual_text
from qualify_creative.schemas import ContentBrief, MediaInputs

from qualify_api.creative.resource_selection import (
    LOGO_SIGNATURE_REQUEST,
    ResourcePlan,
    operator_text,
    owner_signature_plan,
    selection_request,
    validate_plan,
)

from .test_creative_media_byteplus import BUDGET, COPY, TENANT_ID, _brief, _kit
from .test_multi_brand_resources import EXTRA, A, B, C, selection
from .test_semantic_resource_selection import Selector, setup_selector

# -- the field ---------------------------------------------------------------------------


def test_the_field_defaults_to_none_and_a_stored_brief_reads_the_same() -> None:
    assert MediaInputs().brand_logo_placement is None
    stored = {"brand_logo_key": A, "brand_logo_in_scene": True}
    media = MediaInputs.model_validate(stored, context={"preserve_stored_logo_mode": True})
    assert media.brand_logo_placement is None and media.brand_logo_in_scene
    legacy = MediaInputs.model_validate(
        {"brand_logo_key": A}, context={"preserve_stored_logo_mode": True}
    )
    assert legacy.brand_logo_placement is None and not legacy.brand_logo_in_scene


def test_signature_makes_the_main_logo_the_signature_and_never_an_in_scene_reference() -> None:
    media = MediaInputs(**selection(brand_logo_placement="signature"))
    assert media.brand_logo_placement == "signature"
    assert not media.brand_logo_in_scene
    assert media.brand_logo_reference_keys == (B, C)
    # even when the request also names the main logo among the variants
    both = MediaInputs(
        brand_logo_key=A, brand_logo_reference_keys=(A, B), brand_logo_placement="signature"
    )
    assert both.brand_logo_reference_keys == (B,)


def test_scene_keeps_the_logo_inside_the_image() -> None:
    media = MediaInputs(brand_logo_key=A, brand_logo_in_scene=False, brand_logo_placement="scene")
    assert media.brand_logo_in_scene and media.brand_logo_placement == "scene"


def test_a_value_outside_the_two_is_refused() -> None:
    with pytest.raises(ValueError):
        MediaInputs(brand_logo_key=A, brand_logo_placement="corner")  # type: ignore[arg-type]


def test_a_template_has_no_placement_to_choose() -> None:
    for placement in ("scene", "signature"):
        brief = _brief(
            ContentKind.TEMPLATE,
            product_keys=(f"uploads/{TENANT_ID}/p1.jpg",),
            brand_logo_key=A,
            brand_logo_placement=placement,
        )
        assert brief.media.brand_logo_placement is None
        assert not brief.media.brand_logo_in_scene


def test_the_field_is_frozen_with_the_brief() -> None:
    """`frozen_inputs` stores `model_dump(mode="json")` and replays it with the stored
    logo-mode context: the owner's choice survives the round trip unchanged."""
    brief = _brief(ContentKind.STATIC_FLYER, **selection(brand_logo_placement="signature"))
    stored = json.loads(json.dumps(brief.model_dump(mode="json")))
    assert stored["media"]["brand_logo_placement"] == "signature"
    replay = ContentBrief.model_validate(stored, context={"preserve_stored_logo_mode": True})
    assert replay == brief
    assert replay.topic == "Smash doble con papas"  # the owner's words, nothing appended


# -- the selector ------------------------------------------------------------------------


def test_without_the_field_the_selectors_input_is_byte_for_byte_the_same() -> None:
    brief = _brief(ContentKind.STATIC_FLYER, **selection())
    assert operator_text(brief) == brief.topic
    scene = brief.model_copy(
        update={"media": brief.media.model_copy(update={"brand_logo_placement": "scene"})}
    )
    assert operator_text(scene) == brief.topic


def test_signature_is_said_to_the_selector_first_and_only_once() -> None:
    brief = _brief(ContentKind.STATIC_FLYER, **selection(brand_logo_placement="signature"))
    assert operator_text(brief) == f"{LOGO_SIGNATURE_REQUEST}\n{brief.topic}"
    # a brief that already carries the sentence (sent before the field) is not doubled
    twice = brief.model_copy(update={"topic": f"{brief.topic}\n{LOGO_SIGNATURE_REQUEST}"})
    assert operator_text(twice) == twice.topic


def test_the_owners_signature_wins_over_an_integrated_plan() -> None:
    selector = Selector()  # proposes the mascot + a logo variant, integrated
    producer, vendor, brief = setup_selector(selector)
    brief = _brief(
        ContentKind.STATIC_FLYER,
        product_keys=(f"uploads/{TENANT_ID}/p1.jpg",),
        **selection(brand_logo_placement="signature"),
    )
    result = producer.produce(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit(), copy=COPY, budget=BUDGET
    )
    assert result.failure is None, result.detail
    payload = json.loads(selector.requests[0].rendered_prompt.volatile_suffix)
    assert payload["operator"].startswith(LOGO_SIGNATURE_REQUEST)
    metadata = result.media[0].params["brand_references"]
    assert metadata["overlay"]["asset_key"] == A  # the main logo, as the corner signature
    assert [ref["asset_key"] for ref in metadata["refs"]] == [EXTRA]  # no logo in the scene
    assert metadata["selection"]["logo_placement"] == "signature"
    assert metadata["selection"]["explicit_quote"] == LOGO_SIGNATURE_REQUEST
    assert len(vendor.requests[0].params["images"]) == 2  # product + mascot, no logo


def test_without_the_field_the_selector_still_decides() -> None:
    producer, _vendor, brief = setup_selector(Selector())
    result = producer.produce(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit(), copy=COPY, budget=BUDGET
    )
    assert result.failure is None, result.detail
    metadata = result.media[0].params["brand_references"]
    assert metadata["overlay"] is None and metadata["selection"]["logo_placement"] == "integrated"


def test_the_sentence_in_a_stored_topic_is_still_honoured() -> None:
    producer, _, brief = setup_selector(Selector())
    brief = brief.model_copy(update={"topic": f"{brief.topic}\n{LOGO_SIGNATURE_REQUEST}"})
    refs = producer.prepare_brand_references(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit()
    )
    plan = ResourcePlan(
        resource_indices=(0, 1),
        photo_indices=(0,),
        guide_indices=(),
        logo_placement="signature",
        signature_basis="explicit",
        explicit_quote=LOGO_SIGNATURE_REQUEST,
        reason="operator",
    )
    validate_plan(plan, brief, refs, brief.media.product_keys)


def test_the_forced_plan_validates_and_keeps_every_other_choice() -> None:
    producer, _, _ = setup_selector(Selector())
    brief = _brief(
        ContentKind.STATIC_FLYER,
        product_keys=(f"uploads/{TENANT_ID}/p1.jpg",),
        **selection(brand_logo_placement="signature"),
    )
    refs = producer.prepare_brand_references(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit()
    )
    integrated = ResourcePlan(
        resource_indices=(0, 1, 2),
        photo_indices=(0,),
        guide_indices=(),
        logo_placement="integrated",
        signature_basis="none",
        explicit_quote="",
        reason="two marks",
    )
    plan = owner_signature_plan(integrated, brief, refs)
    candidates = (*refs.refs, *((refs.overlay,) if refs.overlay else ()))
    assert [candidates[i].asset_key for i in plan.resource_indices] == [EXTRA, A]
    assert plan.photo_indices == integrated.photo_indices and plan.reason == integrated.reason
    validate_plan(plan, brief, refs, brief.media.product_keys)
    # no field: the plan as it came
    plain = brief.model_copy(
        update={"media": brief.media.model_copy(update={"brand_logo_placement": None})}
    )
    assert owner_signature_plan(integrated, plain, refs) is integrated


def test_the_selector_request_reads_the_operator_text() -> None:
    producer, _, _ = setup_selector(Selector())
    brief = _brief(ContentKind.STATIC_FLYER, **selection(brand_logo_placement="signature"))
    refs = producer.prepare_brand_references(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit()
    )
    request = selection_request(brief, refs, [], photo_keys=(), scene_images=0)
    payload = json.loads(request.rendered_prompt.volatile_suffix)
    assert payload["operator"] == visual_text(operator_text(brief))


# -- the preflight -----------------------------------------------------------------------


def test_the_preflight_measures_no_logo_in_the_scene_for_a_signature(monkeypatch) -> None:  # noqa: ANN001
    producer, _, _ = setup_selector(Selector())
    measured: list[tuple[str, ...]] = []
    real = producer._preflight_brand_references

    def spy(brief, kit, selected):  # noqa: ANN001, ANN202
        measured.append(tuple(r.asset_key for r in selected.refs))
        return real(brief, kit, selected)

    monkeypatch.setattr(producer, "_preflight_brand_references", spy)
    for placement, logos_measured in ((None, True), ("signature", False)):
        measured.clear()
        brief = _brief(
            ContentKind.STATIC_FLYER,
            product_keys=(f"uploads/{TENANT_ID}/p1.jpg",),
            **selection(brand_logo_placement=placement),
        )
        refs = producer.prepare_brand_references(
            tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit()
        )
        producer._preflight_resource_candidates(brief, _kit(), refs)
        assert measured, placement
        with_logo = any(key in combo for combo in measured for key in (A, B, C))
        assert with_logo is logos_measured, (placement, measured)
        assert all(EXTRA in combo for combo in measured)


# -- N1 (review 2026-11-04): the applied placement survives a re-validation ---------------


def _selected_with(selector: Selector, placement: str | None) -> MediaInputs:
    producer, _, _ = setup_selector(selector)
    brief = _brief(
        ContentKind.STATIC_FLYER,
        product_keys=(f"uploads/{TENANT_ID}/p1.jpg",),
        **selection(**({"brand_logo_placement": placement} if placement else {})),
    )
    refs = producer.prepare_brand_references(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit()
    )
    candidates = [r.asset_key for r in (*refs.refs, *((refs.overlay,) if refs.overlay else ()))]
    selector.changes.update(resource_indices=[candidates.index(EXTRA), candidates.index(B)])
    selected, _ = producer._select_resources(TENANT_ID, brief, refs, BUDGET, [])
    return selected.media


def test_a_scene_brief_the_selector_put_in_the_corner_stays_in_the_corner() -> None:
    """The owner asked for «scene», the image had no surface, so the selector fell back to
    the corner signature. Re-validating the applied brief must not flip
    `brand_logo_in_scene` back to True from the owner's original «scene»."""
    selector = Selector(logo_placement="signature", signature_basis="no_surface", explicit_quote="")
    media = _selected_with(selector, "scene")
    assert media.brand_logo_in_scene is False
    assert media.brand_logo_placement == "signature"  # what was actually applied
    again = MediaInputs.model_validate(media.model_dump())
    assert again.brand_logo_in_scene is False
    assert again.brand_logo_key == media.brand_logo_key
    assert again.brand_logo_key not in again.brand_logo_reference_keys


def test_an_integrated_plan_keeps_scene_and_a_brief_without_the_field_keeps_none() -> None:
    media = _selected_with(Selector(), "scene")
    assert media.brand_logo_in_scene is True and media.brand_logo_placement == "scene"
    assert MediaInputs.model_validate(media.model_dump()).brand_logo_in_scene is True

    old = _selected_with(
        Selector(logo_placement="signature", signature_basis="no_surface", explicit_quote=""),
        None,
    )
    assert old.brand_logo_placement is None and old.brand_logo_in_scene is False
    assert MediaInputs.model_validate(old.model_dump()).brand_logo_in_scene is False

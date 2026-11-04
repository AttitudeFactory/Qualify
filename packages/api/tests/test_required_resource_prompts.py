"""Offline contracts for mandatory resources and complete visual prompts, not model quality."""

import json
from uuid import uuid4

import pytest
from qualify_creative.adapters.byteplus_ark import seedance_family
from qualify_creative.enums import ContentKind
from qualify_creative.prompt_text import replication_text, visual_text

from qualify_api.creative.brand_references import BrandReferenceError
from qualify_api.creative.media import (
    _CAROUSEL_REFERENCE_SUFFIX,
    _DIALOGUE_WRAPPER,
    MEDIA_PROMPT_BUDGET,
    _budgeted,
    _carousel_reference_motion,
    _Flex,
    _MediaFailed,
    _spoken_line,
    carousel_motion_prompt,
    reel_edit_prompt,
)
from qualify_api.creative.resource_selection import ResourcePlan, selection_request, validate_plan

from .test_creative_media_byteplus import BUDGET, COPY, TENANT_ID, _brief, _kit
from .test_creative_reel_edit import edit_brief
from .test_multi_brand_resources import EXTRA, A
from .test_semantic_resource_selection import Selector, setup_selector


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "Niño, café, acción 中文 @Image1 @Video1 00:03 25%",
            "Niño, café, acción 中文 @Image1 @Video1 00:03 25%",
        ),
        ("Usa 👩🏽‍🍳 guantes 🧤 y 🇻🇪 🇨🇴", "Usa  guantes  y  "),
        ("Familia 👨‍👩‍👧‍👦 corazón ❤️ ✈️", "Familia  corazón  "),
        ("1️⃣ 2⃣ #️⃣ *️⃣ 15:30", "1 2 # * 15:30"),
        ("© ® ™ → ©️ ↔️", "© ® ™ →  "),
        ("🏴\U000e0067\U000e0062\U000e007f fin", " fin"),
        ("Texto a\u200db y 中\ufe00文", "Texto a\u200db y 中\ufe00文"),
    ],
)
def test_unicode_cleanup_preserves_language_numbers_and_references(
    source: str, expected: str
) -> None:
    assert visual_text(source) == expected
    assert visual_text(visual_text(source)) == expected


@pytest.mark.parametrize("size", [2949, 2950])
def test_complete_request_budget_accepts_boundary(size: int) -> None:
    assert len(_budgeted(["x" * size], strict=True)) == size


def test_complete_request_budget_fails_closed_without_truncating_required_text() -> None:
    with pytest.raises(_MediaFailed, match="2951.*2950"):
        _budgeted([_Flex("", "x" * 2951, after="", protected=True)], strict=True)


def test_dialogue_and_slide_suffix_fit_inside_complete_request_budget() -> None:
    motion = "m" * (MEDIA_PROMPT_BUDGET - 500)
    spoken = _spoken_line("Pídela hoy 🍔 " * 100, motion)
    assert "🍔" not in spoken
    assert len(motion) + len(_DIALOGUE_WRAPPER) + len(spoken) <= MEDIA_PROMPT_BUDGET
    slide = carousel_motion_prompt(brand_refs=(), numbered=True)
    final = _carousel_reference_motion(slide, strict=True)
    assert final.endswith(_CAROUSEL_REFERENCE_SUFFIX)
    assert len(final) <= MEDIA_PROMPT_BUDGET


@pytest.mark.parametrize("indices", [[1], [], [0]])
def test_omitted_extra_or_all_logos_fail_without_visual_call(indices: list[int]) -> None:
    producer, vendor, brief = setup_selector(Selector(resource_indices=indices))
    result = producer.produce(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit(), copy=COPY, budget=BUDGET
    )
    assert result.failure == "invalid_parameters"
    assert vendor.requests == []
    assert len(result.usage) == 1 and result.usage[0].cost_usd > 0


def test_every_selected_photo_is_mandatory() -> None:
    selector = Selector(photo_indices=[0])
    producer, vendor, brief = setup_selector(selector)
    brief = brief.model_copy(
        update={
            "media": brief.media.model_copy(
                update={
                    "product_keys": (f"uploads/{TENANT_ID}/p1.jpg", f"uploads/{TENANT_ID}/p2.jpg"),
                }
            )
        }
    )
    result = producer.produce(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit(), copy=COPY, budget=BUDGET
    )
    assert result.failure == "invalid_parameters" and vendor.requests == []


def test_impossible_capacity_fails_before_copy_or_selector() -> None:
    selector = Selector()
    producer, _, _ = setup_selector(selector)
    images = (f"uploads/{TENANT_ID}/p1.jpg",) * 8
    brief = _brief(
        ContentKind.CLIP, clip_image_keys=images, brand_logo_key=A, brand_element_keys=(EXTRA,)
    )
    producer._seedance_reference_model = "dreamina-seedance-2-5-260628"
    max_images = seedance_family(producer._seedance_reference_model).max_references[0]
    brief = brief.model_copy(
        update={
            "media": brief.media.model_copy(
                update={
                    "clip_image_keys": (images[0],) * max_images,
                }
            )
        }
    )
    with pytest.raises(BrandReferenceError, match="demasiadas referencias"):
        producer.prepare_brand_references(
            tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit()
        )
    assert selector.requests == []


def test_impossible_required_text_fails_before_selector() -> None:
    selector = Selector()
    producer, _, brief = setup_selector(selector)
    brief = brief.model_copy(update={"topic": "Conserva la tabla. " * 400})
    with pytest.raises(BrandReferenceError, match="demasiado texto"):
        producer.prepare_brand_references(
            tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit()
        )
    assert selector.requests == []


def test_template_does_not_silently_drop_a_required_mascot() -> None:
    producer, _, brief = setup_selector(Selector())
    brief = brief.model_copy(update={"kind": ContentKind.TEMPLATE})
    with pytest.raises(BrandReferenceError, match="plantilla no admite"):
        producer.prepare_brand_references(
            tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit()
        )


@pytest.mark.parametrize(
    "topic",
    [
        "Evita usar el logo como firma",
        "Logo como firma: prohibido",
        "Usa el logo como firma nunca",
        'El cliente pregunta: "¿logo como firma?"',
        "No quiero logo como firma",
    ],
)
def test_signature_requires_an_affirmative_sentence(topic: str) -> None:
    producer, _, brief = setup_selector(Selector())
    refs = producer.prepare_brand_references(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit()
    )
    plan = ResourcePlan(
        resource_indices=(0, 1),
        photo_indices=(0,),
        guide_indices=(),
        logo_placement="signature",
        signature_basis="explicit",
        explicit_quote="como firma",
        reason="operator",
    )
    with pytest.raises(ValueError):
        validate_plan(
            plan, brief.model_copy(update={"topic": topic}), refs, brief.media.product_keys
        )
    positive = brief.model_copy(update={"topic": "Usa el logo como firma en una esquina."})
    validate_plan(plan, positive, refs, positive.media.product_keys)


def test_no_selected_logo_does_not_invent_one() -> None:
    producer, _, brief = setup_selector(Selector(resource_indices=[0], logo_placement="none"))
    brief = brief.model_copy(
        update={
            "media": brief.media.model_copy(
                update={
                    "brand_logo_key": None,
                    "brand_logo_reference_keys": (),
                }
            )
        }
    )
    refs = producer.prepare_brand_references(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit()
    )
    planned, chosen = producer._select_resources(TENANT_ID, brief, refs, BUDGET, [])
    assert chosen.refs[0].asset_key == EXTRA
    clip = edit_brief().model_copy(
        update={
            "media": edit_brief().media.model_copy(
                update={
                    "resource_plan_version": 2,
                }
            )
        }
    )
    prompt = reel_edit_prompt(brief=clip, kit=_kit(), images=1, brand_refs=chosen.refs)
    assert "No selected client logo: do not invent one" in prompt
    assert planned.media.resource_plan_version == 2


def test_clip_roles_reach_selector_and_final_prompt_unchanged() -> None:
    producer, _, brief = setup_selector(Selector())
    refs = producer.prepare_brand_references(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit()
    )
    clip = edit_brief().model_copy(
        update={
            "media": edit_brief().media.model_copy(
                update={
                    "clip_image_keys": ("catalog", "guide", "place"),
                    "clip_image_roles": ("product", "style", "place"),
                    "resource_plan_version": 2,
                }
            )
        }
    )
    request = selection_request(
        clip, refs, [], photo_keys=clip.media.clip_image_keys, scene_images=0
    )
    data = json.loads(request.rendered_prompt.volatile_suffix)
    assert [p["origin"] for p in data["photos"]] == ["product", "style", "place"]
    prompt = reel_edit_prompt(brief=clip, kit=_kit(), images=3, brand_refs=())
    assert "@Image2: composition/style guide ONLY" in prompt
    assert "@Image3: client place" in prompt
    plan = ResourcePlan(
        resource_indices=(0, 1),
        photo_indices=(0, 1, 2),
        guide_indices=(),
        logo_placement="integrated",
        signature_basis="none",
        explicit_quote="",
        reason="all resources",
    )
    with pytest.raises(ValueError, match="guide's role"):
        validate_plan(plan, clip, refs, clip.media.clip_image_keys)


def test_only_verified_duplicate_source_metadata_is_removed() -> None:
    prose = "Mantén la tabla y el ritmo. No inventes un cierre."
    metadata = {
        "url": "https://example.com/reel",
        "id": "123",
        "network": "instagram",
        "caption": "Marca ajena 🍔",
    }
    topic = (
        "Usa guantes negros.\n\n— Contexto de replicación (segundo plano) —\n"
        + prose
        + "\nReferencia del reel (JSON): "
        + json.dumps(metadata, ensure_ascii=False)
    )
    operator, context = replication_text(
        topic, source_url=metadata["url"], source_id="123", source_platform="instagram"
    )
    assert operator == "Usa guantes negros." and context == prose
    _, unverified = replication_text(
        topic, source_url=metadata["url"], source_id="999", source_platform="instagram"
    )
    assert "Referencia del reel (JSON)" in unverified and "Marca ajena" in unverified


def test_real_reel_budget_regression_preserves_operator_and_prose() -> None:
    from pathlib import Path

    from qualify_creative.schemas import SourceReelProvenance

    from qualify_api.creative.brand_references import BrandReference

    data = json.loads(
        (Path(__file__).parent / "fixtures" / "clip_prompt_budget_real_anonymized.json").read_text(
            encoding="utf8"
        )
    )
    brief = edit_brief().model_copy(
        update={
            "topic": data["topic"],
            "media": edit_brief().media.model_copy(
                update={
                    "source_reel": SourceReelProvenance.model_validate(data["source_reel"]),
                    "resource_plan_version": 2,
                }
            ),
        }
    )
    kit = _kit().model_copy(update={"palette_rgb": tuple(data["palette"])})
    for slot in ("imagotipo", "isologo"):
        selected = BrandReference(
            asset_key=A,
            asset_kind="logo_version",
            asset_slot=slot,
            selected_logo=True,
            instruction_version=7,
        )
        prompt = reel_edit_prompt(brief=brief, kit=kit, images=1, brand_refs=(selected,))
        assert len(data["topic"]) == 1326
        assert len(prompt) <= MEDIA_PROMPT_BUDGET
        assert 'Operator: "producto X"' in prompt
        prose = data["topic"].split("— Contexto de replicación (segundo plano) —\n")[1]
        prose = prose.split("\nReferencia del reel (JSON): ")[0]
        assert visual_text(prose).replace('"', "'") in prompt
        assert "Referencia del reel (JSON)" not in prompt
        assert "@Video1" in prompt and "@Image1" in prompt
        assert "Integrate EVERY reference" in prompt
    # The same stored merged topic and logo historically overflowed the2500 policy.
    legacy = brief.model_copy(
        update={
            "media": brief.media.model_copy(
                update={
                    "resource_plan_version": 1,
                }
            )
        }
    )
    ref = BrandReference(
        asset_key=A,
        asset_kind="logo_version",
        asset_slot="imagotipo",
        selected_logo=True,
        instruction_version=6,
    )
    with pytest.raises(_MediaFailed):
        reel_edit_prompt(brief=legacy, kit=kit, images=1, brand_refs=(ref,))


def test_required_photos_never_use_legacy_frames_only_fallback() -> None:
    from .test_creative_clip import (
        RecordingLinks,
        _clip_producer,
        _clip_store,
        _NoReferenceModel,
        _produce,
    )

    vendor = _NoReferenceModel()
    brief = _brief(
        ContentKind.CLIP,
        clip_first_frame_key=f"uploads/{TENANT_ID}/first.jpg",
        clip_last_frame_key=f"uploads/{TENANT_ID}/last.jpg",
        clip_image_keys=(f"uploads/{TENANT_ID}/product.jpg",),
        clip_image_roles=("product",),
        resource_plan_version=2,
    )
    outcome = _produce(_clip_producer(_clip_store(), vendor, RecordingLinks()), brief, uuid4())
    assert outcome.failure is not None
    assert len(vendor.requests) == 1  # No second request dropping the mandatory photo.


def test_copy_only_script_does_not_need_visual_preflight() -> None:
    producer, _, _ = setup_selector(Selector())
    brief = _brief(ContentKind.CREATOR_SCRIPT)
    refs = producer.prepare_brand_references(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit()
    )
    assert refs.refs == ()


def test_explicit_multiple_logo_request_can_keep_more_than_one_variant() -> None:
    producer, vendor, brief = setup_selector(Selector(resource_indices=[0, 1, 2]))
    brief = brief.model_copy(update={"topic": "Usa ambos logos junto a la mascota."})
    result = producer.produce(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit(), copy=COPY, budget=BUDGET
    )
    assert result.failure is None
    assert len(vendor.requests[0].params["images"]) == 4

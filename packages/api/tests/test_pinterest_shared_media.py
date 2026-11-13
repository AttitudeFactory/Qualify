"""Pinterest origins follow shared photo inputs without changing generation requests."""

from dataclasses import replace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from qualify_creative.enums import ContentKind, SlideSource
from qualify_creative.schemas import CarouselSlide, MediaInputs, SourcePinProvenance

from qualify_api.creative.media import KEPT_FROM_REVISION, _with_pin_sources

from .test_creative_clip import _clip_producer
from .test_creative_media_byteplus import (
    BUDGET,
    COPY,
    TENANT_ID,
    FakeSeedance,
    FakeSeedream,
    MemoryStore,
    _brief,
    _image,
    _kit,
    _produce,
    _producer,
    _store,
)
from .test_semantic_resource_selection import Selector, setup_selector


def _source(key: str, number: int = 1) -> SourcePinProvenance:
    return SourcePinProvenance(
        image_key=key,
        pin_id=str(number),
        board_id="42",
        url=f"https://www.pinterest.com/pin/{number}/",
    )


@pytest.mark.parametrize(
    "slot",
    [
        "product_keys",
        "background_key",
        "clip_image_keys",
        "clip_first_frame_key",
        "clip_last_frame_key",
    ],
)
def test_origin_accepts_only_a_selected_image_input(slot: str) -> None:
    key = f"uploads/{TENANT_ID}/p1.jpg"
    value = (key,) if slot.endswith("keys") else key
    media = MediaInputs(**{slot: value}, source_pins=(_source(key),))
    assert media.pinterest_image_keys == {key}
    assert MediaInputs.model_validate(media.model_dump()).source_pins == media.source_pins


@pytest.mark.parametrize("slot", ["avatar_image_key", "brand_logo_key", "reference_video_key"])
def test_unrelated_keys_do_not_authorize_a_pin_origin(slot: str) -> None:
    key = f"uploads/{TENANT_ID}/p1.jpg"
    with pytest.raises(ValidationError, match="selected image"):
        MediaInputs(**{slot: key}, source_pins=(_source(key),))


def test_ten_product_photos_keep_their_origins_without_the_old_clip_limit() -> None:
    keys = tuple(f"uploads/{TENANT_ID}/p{i}.jpg" for i in range(10))
    sources = tuple(_source(key, i + 1) for i, key in enumerate(keys))
    assert MediaInputs(product_keys=keys, source_pins=sources).source_pins == sources
    with pytest.raises(ValidationError, match="selected image"):
        MediaInputs(product_keys=keys, source_pins=(sources[0], sources[0]))
    with pytest.raises(ValidationError, match="selected image"):
        MediaInputs(product_keys=keys[1:], source_pins=(sources[0],))


def test_still_production_records_origins_without_sending_metadata_to_the_model() -> None:
    key = f"uploads/{TENANT_ID}/p1.jpg"
    source = _source(key)
    vendor = FakeSeedream()
    result = _produce(
        _producer(_store(), seedream=vendor),
        _brief(ContentKind.STATIC_FLYER, product_keys=(key,), source_pins=(source,)),
        uuid4(),
    )
    assert result.failure is None, result.detail
    assert result.media[0].params["source_pins"] == [source.model_dump(mode="json")]
    assert "source_pins" not in vendor.requests[0].params


def test_carousel_origins_belong_to_their_own_slide_and_not_the_closing_slide() -> None:
    keys = tuple(f"uploads/{TENANT_ID}/p{i}.jpg" for i in (1, 2))
    sources = tuple(_source(key, i + 1) for i, key in enumerate(keys))
    brief = _brief(
        ContentKind.CAROUSEL,
        product_keys=keys,
        source_pins=sources,
        slides=tuple(
            CarouselSlide(source=SlideSource.GENERATED, product_index=i) for i in range(2)
        ),
        closing_slide=True,
    )
    result = _produce(_producer(_store(), seedream=FakeSeedream()), brief, uuid4())
    assert result.failure is None, result.detail
    assert len(result.media) == 3
    for i in range(2):
        assert result.media[i].params["source_pins"] == [sources[i].model_dump(mode="json")]
    assert "source_pins" not in result.media[2].params


def test_legacy_resource_pruning_removes_unused_pins_from_the_plan_and_output() -> None:
    producer, _, brief = setup_selector(Selector())
    keys = tuple(f"uploads/{TENANT_ID}/p{i}.jpg" for i in (1, 2))
    sources = tuple(_source(key, i + 1) for i, key in enumerate(keys))
    brief = brief.model_copy(
        update={
            "media": brief.media.model_copy(
                update={
                    "product_keys": keys,
                    "product_image_roles": ("product", "composition"),
                    "source_pins": sources,
                }
            )
        }
    )
    refs = producer.prepare_brand_references(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit()
    ).model_copy(update={"block_version": 6})
    planned, _ = producer._select_resources(TENANT_ID, brief, refs, BUDGET, [])
    assert planned.media.source_pins == (sources[0],)
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
    assert result.media[0].params["source_pins"] == [sources[0].model_dump(mode="json")]


def test_current_scene_planner_keeps_a_pin_as_composition_and_the_product_as_identity() -> None:
    producer, vendor, brief = setup_selector(Selector(photo_indices=[0, 1], guide_indices=[1]))
    keys = tuple(f"uploads/{TENANT_ID}/p{i}.jpg" for i in (1, 2))
    source = _source(keys[1])
    brief = brief.model_copy(
        update={
            "media": brief.media.model_copy(
                update={
                    "product_keys": keys,
                    "product_image_roles": ("product", "composition"),
                    "source_pins": (source,),
                }
            )
        }
    )
    refs = producer.prepare_brand_references(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit()
    ).model_copy(update={"block_version": 9})
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
    assert result.media[0].params["source_pins"] == [source.model_dump(mode="json")]
    plan = result.media[0].params["scene_reference_plans"][0]
    assert plan["photo_roles"] == ["product", "composition"]
    assert "source_pins" not in vendor.requests[0].params


def test_a_kept_slide_retains_its_original_origin_after_a_selection_changes() -> None:
    key = f"uploads/{TENANT_ID}/p1.jpg"
    original = _source(key)
    brief = _brief(ContentKind.STATIC_FLYER, product_keys=(key,), source_pins=(original,))
    result = _produce(_producer(_store(), seedream=FakeSeedream()), brief, uuid4())
    kept = replace(result.media[0], params={**result.media[0].params, KEPT_FROM_REVISION: 1})
    changed = brief.model_copy(
        update={"media": brief.media.model_copy(update={"source_pins": (_source(key, 2),)})}
    )
    assert _with_pin_sources((kept,), changed)[0].params["source_pins"] == [
        original.model_dump(mode="json")
    ]


def test_clip_does_not_attribute_an_unused_product_input_to_its_reference_images() -> None:
    key, unused = (f"uploads/{TENANT_ID}/p{i}.jpg" for i in (1, 2))
    selected = _source(key)
    brief = _brief(
        ContentKind.CLIP,
        clip_image_keys=(key,),
        clip_image_roles=("style",),
        product_keys=(unused,),
        source_pins=(selected, _source(unused, 2)),
    )
    result = _produce(
        _clip_producer(MemoryStore({key: _image(), unused: _image()}), FakeSeedance()),
        brief,
        uuid4(),
    )
    assert result.failure is None, result.detail
    assert result.media[0].params["source_pins"] == [selected.model_dump(mode="json")]

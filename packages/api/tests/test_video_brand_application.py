"""Offline request/paid-replay contracts; not a visual fidelity evaluation."""

import base64
import hashlib
import json
from uuid import uuid4

import pytest
from qualify_creative.enums import ContentKind, GenerationTask, SlideSource, SlideText
from qualify_creative.photo.normalize import to_reference_jpeg
from qualify_creative.providers import GenerationRequest, GenerationResult, RenderedPrompt, Usage
from qualify_creative.schemas import CarouselSlide

from qualify_api.creative import pipeline
from qualify_api.creative.brand_references import BrandReference, BrandReferenceError
from qualify_api.creative.media import MEDIA_PROMPT_BUDGET, first_frame_prompt
from qualify_api.creative.pipeline import (
    CheckpointRouter,
    Preparation,
    encode_result,
    preparing,
    request_data,
)

from .test_creative_media_byteplus import (
    BUDGET,
    COPY,
    TENANT_ID,
    _image,
    _kit,
    _seedance_brief,
)
from .test_creative_queue_pipeline import Checkpoints
from .test_creative_reel_edit import edit_brief
from .test_creative_seedance_draft import RecordingFitter, _finalize, _record
from .test_creative_seedance_video_input import VideoInputSeedance, _measured
from .test_creative_seedance_video_input import _producer as edit_producer
from .test_multi_brand_resources import A, assets
from .test_semantic_resource_selection import Selector, setup_selector


def test_no_resource_legacy_replay_does_not_insert_selector_at_paid_image_ordinal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    producer, vendor, brief = setup_selector(Selector())
    brief = brief.model_copy(
        update={
            "media": brief.media.model_copy(
                update={
                    "brand_logo_key": None,
                    "brand_logo_reference_keys": (),
                    "brand_element_keys": (),
                    "product_keys": (f"uploads/{TENANT_ID}/p1.jpg", f"uploads/{TENANT_ID}/p2.jpg"),
                }
            )
        }
    )
    selector = producer._router._providers["anthropic"]
    steps = Checkpoints()
    result = GenerationResult(
        payload={"images": [_image()]},
        model_id="seedream-5-0-lite-260128",
        provider="seedream",
        usage=Usage(pieces=1),
    )
    steps.rows[0] = {"request": {}, "result": {"old_copy": True}, "error": None}
    steps.rows[1] = {
        "request": {},
        "result": encode_result(result, producer._store, "old", TENANT_ID),
        "error": None,
        "job_id": None,
    }
    producer._router = CheckpointRouter(producer._router, steps, producer._store)
    monkeypatch.setattr(pipeline, "PipelineStore", lambda: steps)
    run = Preparation(TENANT_ID, uuid4(), 1, "generation", uuid4(), 1, step=1)
    with preparing(run):
        refs = producer.prepare_brand_references(
            tenant_id=TENANT_ID, draft_id=run.draft_id, brief=brief, kit=_kit()
        )
        assert refs.block_version == 1
        output = producer.produce(
            tenant_id=TENANT_ID,
            draft_id=run.draft_id,
            brief=brief,
            kit=_kit(),
            copy=COPY,
            budget=BUDGET,
            brand_references=refs,
        )
    assert output.failure is None, output.detail
    assert selector.requests == [] and vendor.requests == []
    assert run.step == 2  # Old image was consumed as image, not as an Anthropic selector.


def test_new_empty_selection_is_frozen_and_selector_is_paid_only_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selector = Selector(resource_indices=[], photo_indices=[0, 1], logo_placement="none")
    producer, _, brief = setup_selector(selector)
    brief = brief.model_copy(
        update={
            "media": brief.media.model_copy(
                update={
                    "brand_logo_key": None,
                    "brand_logo_reference_keys": (),
                    "brand_element_keys": (),
                    "product_keys": (f"uploads/{TENANT_ID}/p1.jpg", f"uploads/{TENANT_ID}/p2.jpg"),
                }
            )
        }
    )
    steps = Checkpoints()
    monkeypatch.setattr(pipeline, "PipelineStore", lambda: steps)
    producer._router = CheckpointRouter(producer._router, steps, producer._store)
    draft = uuid4()
    for _ in range(2):
        run = Preparation(TENANT_ID, draft, 1, "generation", uuid4(), 1)
        with preparing(run):
            refs = producer.prepare_brand_references(
                tenant_id=TENANT_ID, draft_id=draft, brief=brief, kit=_kit()
            )
            assert refs.block_version == 8
            assert steps.rows[-2]["request"]["brand_refs"]["refs"] == []
            run.step = 1
            planned, selected = producer._select_resources(TENANT_ID, brief, refs, BUDGET, [])
            assert planned.media.brand_application_version == 1
            assert selected.selection["version"] == 2
    assert len(selector.requests) == 1


@pytest.mark.parametrize("has_decision", [False, True])
def test_old_empty_semantic_selector_keeps_its_paid_ordinal_and_version(
    monkeypatch: pytest.MonkeyPatch, has_decision: bool
) -> None:
    producer, _, brief = setup_selector(Selector())
    brief = brief.model_copy(
        update={
            "media": brief.media.model_copy(
                update={
                    "brand_logo_key": None,
                    "brand_logo_reference_keys": (),
                    "brand_element_keys": (),
                    "product_keys": (f"uploads/{TENANT_ID}/p1.jpg", f"uploads/{TENANT_ID}/p2.jpg"),
                }
            )
        }
    )
    plan = {
        "resource_indices": [],
        "photo_indices": [0, 1],
        "guide_indices": [],
        "logo_placement": "none",
        "signature_basis": "none",
        "explicit_quote": "",
        "reason": "old scene",
    }
    request = GenerationRequest(
        task=GenerationTask.COPY,
        rendered_prompt=RenderedPrompt("old", json.dumps({"version": 2}), "old"),
        output_schema={"properties": {"resource_indices": {"type": "array"}}},
    )
    result = GenerationResult(
        payload=plan,
        model_id="claude-opus-5",
        provider="anthropic",
        usage=Usage(input_tokens=100, output_tokens=20),
    )
    steps = Checkpoints()
    steps.rows[0] = {"request": {}, "result": {"old_copy": True}}
    steps.rows[3] = {
        "request": request_data(request, "anthropic", brief.brand_id),
        "result": encode_result(result, producer._store, "old-selector", TENANT_ID),
        "error": None,
        "job_id": None,
    }
    if has_decision:
        steps.rows[-3] = {"request": {"resource_selection": {**plan, "version": 2}}}
    steps.load_resource_selection_request = lambda run: steps.rows[3]
    monkeypatch.setattr(pipeline, "PipelineStore", lambda: steps)
    old_selector = producer._router._providers["anthropic"]
    producer._router = CheckpointRouter(producer._router, steps, producer._store)
    run = Preparation(TENANT_ID, uuid4(), 1, "generation", uuid4(), 1, step=3)
    with preparing(run):
        refs = producer.prepare_brand_references(
            tenant_id=TENANT_ID, draft_id=run.draft_id, brief=brief, kit=_kit()
        )
        assert refs.block_version == 7
        planned, _ = producer._select_resources(TENANT_ID, brief, refs, BUDGET, [])
        assert planned.media.brand_application_version == 0
    assert old_selector.requests == [] and run.step == 4


def test_new_clip_carries_exact_logo_bytes_indices_and_brand_directions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _measured(monkeypatch, 5)
    vendor = VideoInputSeedance()
    producer = edit_producer(vendor)
    producer._clip_frame = lambda key, **kwargs: _image() if key is not None else None
    assets(producer, producer._store)
    selector = Selector(resource_indices=[0])
    producer._semantic_selection = True
    producer._router._providers["anthropic"] = selector
    brief = edit_brief(brand_logo_key=A, brand_logo_in_scene=True)
    kit = _kit().model_copy(update={"font_heading": "Baloo 2", "font_body": "Nunito"})
    output = producer.produce(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=kit, copy=COPY, budget=BUDGET
    )
    assert output.failure is None, output.detail
    params = vendor.requests[0].params
    images = params["reference_images"]
    assert len(images) == 2
    expected = [producer._store.files[brief.media.clip_image_keys[0]], producer._store.files[A]]
    outgoing = [base64.b64decode(url.split(",", 1)[1]) for url in images]
    assert outgoing == [to_reference_jpeg(data) for data in expected]
    manifest = output.media[0].params["reference_manifest"]
    assert [r["image"] for r in manifest] == [1, 2]
    assert [r["role"] for r in manifest] == ["product", "integrated_logo"]
    assert [r["sha256"] for r in manifest] == [
        hashlib.sha256(data).hexdigest() for data in outgoing
    ]
    assert [r["source_sha256"] for r in manifest] == [
        hashlib.sha256(data).hexdigest() for data in expected
    ]
    assert output.media[0].params["references"]["total_images"] == 2
    prompt = params["prompt"]
    for expected_text in [
        "REPLACE BRAND GRAPHICS",
        "EVERY source-owner",
        "tray paper",
        "wrappers",
        "replacing source-brand colors",
        "Do not recolor natural food",
        "headlines=Baloo 2",
        "body=Nunito",
        "trusted",
        "Image 2",
    ]:
        assert expected_text in prompt
    assert "without drawing any letters" not in prompt
    assert "No new promotional text/props" not in prompt
    assert len(prompt) <= MEDIA_PROMPT_BUDGET
    assert output.media[0].params["brand_references"]["block_version"] == 8


def test_new_first_frame_preserves_guide_and_product_roles_and_font_roles() -> None:
    brief = _seedance_brief().model_copy(
        update={
            "media": _seedance_brief().media.model_copy(
                update={
                    "product_image_roles": ("composition", "product"),
                    "brand_application_version": 1,
                }
            )
        }
    )
    ref = BrandReference(
        asset_key=A, asset_kind="logo_version", asset_slot="imagotipo", instruction_version=8
    )
    kit = _kit().model_copy(update={"font_heading": "Baloo 2", "font_body": "Nunito"})
    prompt = first_frame_prompt(
        brief=brief,
        kit=kit,
        has_character_image=True,
        products=2,
        has_background=False,
        brand_refs=(ref,),
    )
    assert "Image 2: composition guide ONLY" in prompt
    assert "Image 3: real product identity" in prompt
    assert "Image 4: principal" in prompt or "Image 4: alternative" in prompt
    assert "headlines=Baloo 2" in prompt and "body=Nunito" in prompt
    assert "without drawing any letters" not in prompt and "Do not draw any text" not in prompt


def test_avatar_signature_is_composited_in_preview_and_final() -> None:
    from .test_creative_seedance_draft import DraftSeedance, _producer, _store

    vendor, fitter, files = DraftSeedance(), RecordingFitter(), _store()
    producer = _producer(files, vendor, fitter)
    producer._semantic_selection = True
    assets(producer, files)
    producer._router._providers["anthropic"] = Selector(
        resource_indices=[0],
        photo_indices=[0],
        logo_placement="signature",
        signature_basis="explicit",
        explicit_quote="como firma",
    )
    brief = _seedance_brief(brand_logo_key=A, brand_logo_in_scene=True).model_copy(
        update={"topic": "Usa el logo como firma en una esquina."}
    )
    draft = uuid4()
    output = producer.produce(
        tenant_id=TENANT_ID, draft_id=draft, brief=brief, kit=_kit(), copy=COPY, budget=BUDGET
    )
    assert output.failure is None, output.detail
    assert fitter.calls[0]["overlay"] is not None and fitter.calls[0]["keep_audio"]
    assert output.media[0].params["logo"] is True
    assert output.media[0].params["brand_references"]["overlay"]["asset_key"] == A
    final = _finalize(producer, brief, _record(output.media[0]), draft)
    assert final.failure is None, final.detail
    assert fitter.calls[-1]["overlay"] is not None
    assert (
        len(vendor.requests) == 2
    )  # One preview and its requested final, no per-frame vendor calls.


def test_carousel_keeps_original_photo_index_order_even_when_selector_reorders() -> None:
    producer, _, brief = setup_selector(Selector(photo_indices=[1, 0]))
    brief = brief.model_copy(
        update={
            "kind": ContentKind.CAROUSEL,
            "media": brief.media.model_copy(
                update={
                    "product_keys": (f"uploads/{TENANT_ID}/p1.jpg", f"uploads/{TENANT_ID}/p2.jpg"),
                    "slides": (CarouselSlide(source=SlideSource.GENERATED, product_index=0),),
                }
            ),
        }
    )
    refs = producer.prepare_brand_references(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit()
    )
    planned, _ = producer._select_resources(TENANT_ID, brief, refs, BUDGET, [])
    assert planned.media.product_keys == brief.media.product_keys
    assert planned.media.slides[0].product_index == 0


@pytest.mark.parametrize("source", [SlideSource.EXISTING, SlideSource.STOCK])
def test_carousel_existing_only_resources_fail_before_selector_or_visual_call(
    source: SlideSource,
) -> None:
    producer, vendor, brief = setup_selector(Selector())
    selector = producer._router._providers["anthropic"]
    # Use model_copy to isolate this preflight contract from upload/key validation.
    slide = CarouselSlide(
        source=source,
        object_key=(
            f"t/{TENANT_ID}/stock/pixabay/5712704/video.mp4"
            if source is SlideSource.STOCK
            else f"uploads/{TENANT_ID}/existing.mp4"
        ),
        text=SlideText.HOOK if source is SlideSource.STOCK else SlideText.NONE,
    )
    brief = brief.model_copy(
        update={
            "kind": ContentKind.CAROUSEL,
            "media": brief.media.model_copy(update={"slides": (slide,)}),
        }
    )
    with pytest.raises(BrandReferenceError, match="una diapositiva que creemos nosotros"):
        producer.prepare_brand_references(
            tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit()
        )
    assert selector.requests == [] and vendor.requests == []


def test_carousel_guides_are_not_relabelled_as_real_products_in_vendor_requests() -> None:
    producer, vendor, brief = setup_selector(Selector(photo_indices=[0, 1], guide_indices=[0]))
    guide = f"t/{TENANT_ID}/stock/pixabay/5712704/guide.jpg"
    real = f"uploads/{TENANT_ID}/p1.jpg"
    producer._store.files[guide] = producer._store.files[f"uploads/{TENANT_ID}/p2.jpg"]
    brief = brief.model_copy(
        update={
            "kind": ContentKind.CAROUSEL,
            "media": brief.media.model_copy(
                update={
                    "product_keys": (guide, real),
                    "slides": (
                        CarouselSlide(source=SlideSource.GENERATED, product_index=0),
                        CarouselSlide(source=SlideSource.GENERATED, product_index=1),
                    ),
                }
            ),
        }
    )
    output = producer.produce(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit(), copy=COPY, budget=BUDGET
    )
    assert output.failure is None, output.detail
    assert "composition guide ONLY" in vendor.requests[0].params["prompt"]
    assert (
        "product in image 1 is the client's real product" not in vendor.requests[0].params["prompt"]
    )
    assert "product in image 1 is the client's real product" in vendor.requests[1].params["prompt"]


@pytest.mark.parametrize("has_fitter", [True, False])
def test_omnihuman_signature_is_composited_or_fails_before_media_spend(has_fitter: bool) -> None:
    from .test_creative_media_byteplus import (
        FakeFitter,
        FakeLinks,
        FakeOmniHuman,
        FakeSeedream,
        FakeSpeech,
        _presenter,
        _presenter_brief,
        _store,
    )

    store, image, speech, omni = _store(), FakeSeedream(), FakeSpeech(), FakeOmniHuman()
    producer = _presenter(store, seedream=image, speech=speech, omni=omni, links=FakeLinks())
    producer._semantic_selection = True
    fitter = FakeFitter()
    producer._fitter = fitter if has_fitter else None
    assets(producer, store)
    producer._router._providers["anthropic"] = Selector(
        resource_indices=[0],
        photo_indices=[0],
        logo_placement="signature",
        signature_basis="explicit",
        explicit_quote="como firma",
    )
    brief = _presenter_brief(product_keys=(f"uploads/{TENANT_ID}/p1.jpg",), brand_logo_key=A)
    brief = brief.model_copy(update={"topic": "Usa el logo como firma."})
    output = producer.produce(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit(), copy=COPY, budget=BUDGET
    )
    if not has_fitter:
        assert output.failure is not None
        assert image.requests == speech.requests == omni.requests == []
        return
    assert output.failure is None, output.detail
    assert fitter.calls[0]["overlay"] is not None and fitter.calls[0]["keep_audio"]
    assert output.media[0].params["logo"] is True
    assert store.files[output.media[0].object_key] != b"omni-mp4"
    assert output.media[0].params["brand_references"]["overlay"]["asset_key"] == A

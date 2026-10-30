"""Brand references exercise real media routing with offline vendor spies, not visual evals."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from qualify_creative.enums import ContentKind, SlideSource
from qualify_creative.schemas import CarouselSlide, MediaInputs

from qualify_api.creative import pipeline
from qualify_api.creative.brand_kit_store import BrandAsset
from qualify_api.creative.brand_references import BrandReferenceError, read_brand_reference_images
from qualify_api.creative.media import (
    FINISH_CLIP,
    _carousel_reference_motion,
    _data_url,
    _MediaFailed,
)
from qualify_api.creative.service import ContentService

from .test_creative_clip import REF_MODEL, _clip_producer
from .test_creative_media_byteplus import (
    BRAND_ID,
    TENANT_ID,
    FakeFitter,
    FakeLinks,
    FakeOmniHuman,
    FakeSeedance,
    FakeSeedream,
    FakeSpeech,
    _brief,
    _image,
    _kit,
    _presenter,
    _presenter_brief,
    _produce,
    _producer,
    _seedance_brief,
    _store,
)

KEY = f"t/{TENANT_ID}/brand/{BRAND_ID}/mascot.png"
LOGO = f"t/{TENANT_ID}/brand/{BRAND_ID}/logo.png"
NOTE = "Mantener la mascota junto al producto durante todos los planos"


def _assets(producer: Any, store: Any) -> list[BrandAsset]:
    store.files[KEY] = _image((250, 180, 5))
    store.files[LOGO] = _image((20, 240, 20))
    rows = [
        BrandAsset("extra", "mascot", KEY, content_type="image/png", label="Mascota", context=NOTE),
        BrandAsset("logo", "", LOGO, content_type="image/png", label="Logo"),
    ]

    def read(tenant: Any, brand: Any) -> list[BrandAsset]:
        assert (tenant, brand) == (TENANT_ID, BRAND_ID)
        return list(rows)

    producer._brand_assets = read
    return rows


def test_flyer_sends_selected_image_note_and_explicit_background_index() -> None:
    store, vendor = _store(), FakeSeedream()
    producer = _producer(store, seedream=vendor)
    _assets(producer, store)
    brief = _brief(
        ContentKind.STATIC_FLYER,
        product_keys=(f"uploads/{TENANT_ID}/p1.jpg",),
        background_key=f"uploads/{TENANT_ID}/bg.jpg",
        brand_element_keys=(KEY,),
    )
    result = _produce(producer, brief, uuid4())
    assert result.failure is None
    params = vendor.requests[0].params
    assert params["images"][-1] == _data_url(store.files[KEY])
    assert "Image 3: Mascota" in params["prompt"] and NOTE in params["prompt"]
    assert "place (image 2," in params["prompt"]
    ref = result.media[0].params["brand_references"]["refs"][0]
    assert ref["fingerprint"] == hashlib.sha256(store.files[KEY]).hexdigest()
    assert ref["snapshot_key"] != KEY


@pytest.mark.parametrize(
    "kind",
    [ContentKind.STATIC_FLYER, ContentKind.CLIP, ContentKind.AVATAR_VIDEO, ContentKind.CAROUSEL],
)
def test_stale_selection_is_rejected_before_reads_and_vendors(kind: ContentKind) -> None:
    store, image, video = _store(), FakeSeedream(), FakeSeedance()
    producer = _producer(store, seedream=image, seedance=video)
    rows = _assets(producer, store)
    rows.clear()  # selection from a previously open screen, deleted server-side
    if kind is ContentKind.AVATAR_VIDEO:
        brief = _seedance_brief(brand_element_keys=(KEY,))
    elif kind is ContentKind.CAROUSEL:
        brief = _brief(
            kind,
            slides=(CarouselSlide(source=SlideSource.GENERATED, scene_prompt="El local"),),
            closing_slide=True,
            brand_element_keys=(KEY,),
        )
    else:
        brief = _brief(kind, brand_element_keys=(KEY,))
    store.read = lambda key: pytest.fail("stale selection read R2")
    result = _produce(producer, brief, uuid4())
    assert result.failure == "invalid_parameters" and "eliminado" in result.detail
    assert image.requests == video.requests == []


def test_service_preflights_stale_selection_before_paid_copy() -> None:
    store = _store()
    producer = _producer(store)
    rows = _assets(producer, store)
    rows.clear()
    service = object.__new__(ContentService)
    service._brand = SimpleNamespace(kit=lambda **_: _kit())
    service._voice = SimpleNamespace(active=lambda **_: SimpleNamespace())
    service._repo = SimpleNamespace(budget_state=lambda **_: None)
    service._media = producer
    settled = []
    service._finish_brief = lambda **data: settled.append(data)
    service._copy_stage = lambda **_: pytest.fail("paid copy reached")
    brief = _brief(ContentKind.STATIC_FLYER, brand_element_keys=(KEY,))
    service._generate_brief(
        tenant_id=TENANT_ID,
        draft=SimpleNamespace(brand_id=BRAND_ID, id=uuid4(), revision=1),
        brief=brief,
    )
    assert settled[0]["spent"] == 0
    assert settled[0]["media_failure"] == "invalid_parameters"


def test_snapshot_survives_deletion_and_new_revision_revalidates(monkeypatch: Any) -> None:
    store = _store()
    producer = _producer(store)
    rows = _assets(producer, store)
    brief = _brief(ContentKind.STATIC_FLYER, brand_element_keys=(KEY,))
    steps: dict[int, Any] = {}

    class Steps:
        def load_step(self, run: Any, step: int) -> Any:
            return steps.get(step)

        def save_step(self, run: Any, step: int, request: Any, job: Any) -> Any:
            steps[step] = {"request": request}
            return steps[step]

    monkeypatch.setattr(pipeline, "PipelineStore", Steps)
    run = pipeline.Preparation(TENANT_ID, uuid4(), 1, "draft", uuid4(), 1)
    token = pipeline._preparation.set(run)
    try:
        frozen = producer.prepare_brand_references(
            tenant_id=TENANT_ID, draft_id=run.draft_id, brief=brief, kit=_kit()
        )
        original = store.files.pop(KEY)
        rows.clear()
        replay = producer.prepare_brand_references(
            tenant_id=TENANT_ID, draft_id=run.draft_id, brief=brief, kit=_kit()
        )
        assert replay == frozen
        assert read_brand_reference_images(store.read, replay.refs)[0].image == original
        steps.clear()  # new revision has no prior preparation snapshot
        with pytest.raises(BrandReferenceError, match="eliminado"):
            producer.prepare_brand_references(
                tenant_id=TENANT_ID, draft_id=run.draft_id, brief=brief, kit=_kit(), revision=2
            )
    finally:
        pipeline._preparation.reset(token)


def test_changed_snapshot_bytes_are_refused() -> None:
    store = _store()
    producer = _producer(store)
    _assets(producer, store)
    frozen = producer.prepare_brand_references(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=_brief(ContentKind.STATIC_FLYER, brand_element_keys=(KEY,)),
        kit=_kit(),
    )
    store.files[frozen.refs[0].snapshot_key] = _image((0, 0, 0))
    with pytest.raises(BrandReferenceError, match="cambió"):
        read_brand_reference_images(store.read, frozen.refs)


def test_clip_only_brand_images_activates_reference_mode_and_keeps_role() -> None:
    store, vendor = _store(), FakeSeedance()
    producer = _clip_producer(store, vendor)
    _assets(producer, store)
    result = _produce(producer, _brief(ContentKind.CLIP, brand_element_keys=(KEY,)), uuid4())
    assert result.failure is None
    params = vendor.requests[0].params
    assert params["model"] == REF_MODEL
    assert len(params["reference_images"]) == 1 and "first_frame" not in params
    assert "Image 1: Mascota" in params["prompt"] and NOTE in params["prompt"]
    assert "throughout the relevant shots" in params["prompt"]


def test_clip_does_not_fall_back_and_drop_chosen_brand_images() -> None:
    class Refused(FakeSeedance):
        def generate(self, request: Any, *, api_key: str) -> Any:
            self.requests.append(request)
            raise RuntimeError("AccessDenied")

    store, vendor = _store(), Refused()
    producer = _clip_producer(store, vendor)
    _assets(producer, store)
    brief = _brief(
        ContentKind.CLIP,
        brand_element_keys=(KEY,),
        clip_first_frame_key=f"uploads/{TENANT_ID}/p1.jpg",
    )
    result = _produce(producer, brief, uuid4())
    assert result.failure and len(vendor.requests) == 1


@pytest.mark.parametrize("source", [SlideSource.GENERATED, SlideSource.ANIMATED])
def test_gallery_includes_resources_and_video_continuity(source: SlideSource) -> None:
    store, image, video = _store(), FakeSeedream(), FakeSeedance()
    producer = _producer(store, seedream=image, seedance=video)
    producer._fitter = FakeFitter()
    _assets(producer, store)
    brief = _brief(
        ContentKind.CAROUSEL,
        brand_element_keys=(KEY,),
        slides=(CarouselSlide(source=source, scene_prompt="El local"),),
        closing_slide=True,
    )
    result = _produce(producer, brief, uuid4())
    assert result.failure is None
    assert "Image 1: Mascota" in image.requests[0].params["prompt"]
    if source is SlideSource.ANIMATED:
        assert NOTE in video.requests[0].params["prompt"]
        assert "first_frame" in video.requests[0].params
        assert "Image 2" not in video.requests[0].params["prompt"]


@pytest.mark.parametrize("animated", [True, False])
def test_avatar_supported_character_refs_and_human_frame_mode(animated: bool) -> None:
    store, image, video = _store(), FakeSeedream(), FakeSeedance()
    producer = _producer(store, seedream=image, seedance=video)
    producer._seedance_model = REF_MODEL
    _assets(producer, store)
    brief = _seedance_brief(brand_element_keys=(KEY,))
    if animated:
        brief = brief.model_copy(update={"kind": ContentKind.ANIMATED_AVATAR_VIDEO})
    result = _produce(producer, brief, uuid4())
    assert result.failure is None
    params = video.requests[0].params
    assert NOTE in params["prompt"]
    if animated:
        assert len(params["reference_images"]) == 2 and "first_frame" not in params
    else:
        assert "first_frame" in params and "reference_images" not in params


def test_omnihuman_composes_brand_element_without_inventing_vendor_fields() -> None:
    store, image, voice, video = _store(), FakeSeedream(), FakeSpeech(), FakeOmniHuman()
    producer = _presenter(store, seedream=image, speech=voice, omni=video, links=FakeLinks())
    _assets(producer, store)
    result = _produce(producer, _presenter_brief(brand_element_keys=(KEY,)), uuid4())
    assert result.failure is None
    assert NOTE in image.requests[0].params["prompt"]
    assert "reference_images" not in video.requests[0].params


def test_logo_in_scene_is_reference_without_local_signature(monkeypatch: Any) -> None:
    store, image = _store(), FakeSeedream()
    producer = _producer(store, seedream=image)
    _assets(producer, store)
    logo_calls = []
    old_logo = producer._logo
    producer._logo = lambda kit, key=None: (
        logo_calls.append((kit.logo_asset_key, key)),
        old_logo(kit, key),
    )[1]
    result = _produce(
        producer,
        _brief(ContentKind.STATIC_FLYER, brand_logo_key=LOGO, brand_logo_in_scene=True),
        uuid4(),
    )
    assert result.failure is None
    assert len(image.requests[0].params["images"]) == 1
    assert logo_calls == [(None, None)]
    with pytest.raises(ValueError):
        MediaInputs(brand_logo_in_scene=True)


def test_stock_and_other_tenant_fail_before_any_resource_read() -> None:
    for key in (f"t/{TENANT_ID}/stock/pixabay/1/photo.png", f"t/{uuid4()}/brand/p.png"):
        store, image = _store(), FakeSeedream()
        producer = _producer(store, seedream=image)
        producer._brand_assets = lambda *args: pytest.fail("read assets before guards")
        store.read = lambda key: pytest.fail("read R2 before guards")
        result = _produce(
            producer, _brief(ContentKind.STATIC_FLYER, brand_element_keys=(key,)), uuid4()
        )
        assert result.failure == "route_blocked_by_policy" and not image.requests


def test_combined_image_limit_and_long_notes_refused_before_reads() -> None:
    for long_note in (False, True):
        store, image = _store(), FakeSeedream()
        producer = _producer(store, seedream=image)
        rows = _assets(producer, store)
        keys = [KEY]
        if long_note:
            rows[0] = replace(rows[0], context="nota " * 1000)
        else:
            keys = [KEY + str(i) for i in range(6)]
            rows[:] = [replace(rows[0], object_key=key) for key in keys]
        brief = _brief(
            ContentKind.STATIC_FLYER,
            brand_element_keys=tuple(keys),
            product_keys=tuple(f"uploads/{TENANT_ID}/p{i}.jpg" for i in range(10)),
        )
        store.read = lambda key: pytest.fail("invalid plan read R2")
        result = _produce(producer, brief, uuid4())
        assert result.failure == "invalid_parameters" and not image.requests


def test_no_selection_leaves_vendor_params_and_read_pattern_unchanged() -> None:
    store, image = _store(), FakeSeedream()
    producer = _producer(store, seedream=image)
    producer._brand_assets = lambda *args: pytest.fail("no selection read Brand Kit assets")
    result = _produce(producer, _brief(ContentKind.STATIC_FLYER), uuid4())
    assert result.failure is None
    assert image.requests[0].params["images"] == []
    assert "elemento_de_marca" not in image.requests[0].params["prompt"]
    assert "brand_references" not in result.media[0].params


@pytest.mark.parametrize("in_scene", [True, False])
def test_clip_final_uses_preview_logo_mode_and_snapshot_after_source_deletion(
    in_scene: bool,
) -> None:
    store = _store()
    producer = _producer(store)
    producer._seedance_reference_model = REF_MODEL
    rows = _assets(producer, store)
    brief = _brief(ContentKind.CLIP, brand_logo_key=LOGO, brand_logo_in_scene=in_scene)
    captured = producer.prepare_brand_references(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit()
    )
    del store.files[LOGO]
    rows.clear()

    class FinalFitter(FakeFitter):
        def fit(self, data: bytes, **kwargs: Any) -> Any:
            kwargs.pop("x264", None)
            return super().fit(data, **kwargs)

    fitter = FinalFitter()
    producer._fitter = fitter
    producer._paid_final = lambda *args: ({"resolution": "1080p"}, b"raw-final")
    result = producer._final_video(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=brief,
        kit=_kit(),
        asset=SimpleNamespace(
            object_key="clip.mp4",
            position=0,
            aspect_ratio="9:16",
            params={"brand_references": captured.model_dump(mode="json")},
        ),
        block={"model": "dreamina-seedance-2-5-260628", "finish": FINISH_CLIP, "ratio": "9:16"},
        budget=None,
        usage=[],
        revision=1,
        kept={},
        on_raw_kept=None,
    )
    assert (fitter.calls[0]["overlay"] is None) is in_scene
    assert result.params["logo"] is (not in_scene)


def test_motion_reference_suffix_cannot_truncate_the_protected_brand_note() -> None:
    with pytest.raises(_MediaFailed, match="demasiado largas"):
        _carousel_reference_motion("x" * 2400, strict=True)
    assert len(_carousel_reference_motion("x" * 2400, strict=False)) <= 2500


@pytest.mark.parametrize("photos, accepted", [(8, True), (9, False)])
def test_seedance_counts_all_selected_images_at_the_family_limit(
    photos: int, accepted: bool
) -> None:
    store, video = _store(), FakeSeedance()
    producer = _clip_producer(store, video)
    _assets(producer, store)
    brief = _brief(
        ContentKind.CLIP,
        brand_element_keys=(KEY,),
        clip_image_keys=(f"uploads/{TENANT_ID}/p1.jpg",) * photos,
    )
    if not accepted:
        store.read = lambda key: pytest.fail("limit checked after read")
    result = _produce(producer, brief, uuid4())
    assert (result.failure is None) is accepted
    assert bool(video.requests) is accepted


def test_updated_logo_requires_fresh_selection_then_uses_new_bytes() -> None:
    store, image = _store(), FakeSeedream()
    producer = _producer(store, seedream=image)
    rows = _assets(producer, store)
    rows[1] = replace(rows[1], object_key=LOGO + "-new")
    store.files[LOGO + "-new"] = _image((0, 10, 250))
    old = _brief(ContentKind.STATIC_FLYER, brand_logo_key=LOGO, brand_logo_in_scene=True)
    stale = _produce(producer, old, uuid4())
    assert stale.failure == "invalid_parameters" and not image.requests
    fresh = old.model_copy(
        update={"media": old.media.model_copy(update={"brand_logo_key": LOGO + "-new"})}
    )
    result = _produce(producer, fresh, uuid4())
    assert result.failure is None
    assert image.requests[0].params["images"] == [_data_url(store.files[LOGO + "-new"])]

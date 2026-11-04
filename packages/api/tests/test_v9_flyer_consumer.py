"""Physical request capture with existing bytes only; no pixels/providers/network."""

import base64
import hashlib
import socket
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image
from qualify_creative.enums import AdImageMode, ContentKind, SlideSource, SlideText
from qualify_creative.providers import GenerationResult, Usage
from qualify_creative.schemas import CarouselSlide

from qualify_api.creative import media as module
from qualify_api.creative.brand_references import (
    BrandReference,
    BrandReferenceError,
    BrandReferencesSet,
)
from qualify_api.creative.media import TextStyle

from .test_creative_media_byteplus import (
    BUDGET,
    COPY,
    SEEDREAM_MODEL,
    TENANT_ID,
    FakeSeedance,
    FakeSeedream,
    MemoryStore,
    _brief,
    _kit,
    _producer,
)


@pytest.fixture(autouse=True)
def no_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("No models, network, or new pixels are allowed")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(Image, "new", forbidden)
    monkeypatch.setattr(Image.Image, "save", forbidden)
    import av

    monkeypatch.setattr(av, "open", forbidden)
    monkeypatch.setattr(module, "to_reference_jpeg", lambda data: data)
    monkeypatch.setattr(module, "to_meta_jpeg", lambda data: data)
    monkeypatch.setattr(module, "render_ad_slides", lambda **kwargs: kwargs["scenes"])
    monkeypatch.setattr(module, "render_carousel_slide", lambda **kwargs: kwargs["scene"])


class Capture(FakeSeedream):
    def generate(self, request, *, api_key):
        self.requests.append(request)
        return GenerationResult(
            payload={"images": [PHOTO]},
            model_id=SEEDREAM_MODEL,
            provider="seedream",
            usage=Usage(pieces=1),
        )


PHOTO = (Path(__file__).resolve().parents[2] / "render/public/sample/photo-1.jpg").read_bytes()


def run_flyer(monkeypatch, *, count=2, roles=()):
    keys = tuple(f"uploads/{TENANT_ID}/p{i}.jpg" for i in range(count))
    vendor = Capture()
    producer = _producer(MemoryStore(dict.fromkeys(keys, PHOTO)), seedream=vendor)
    monkeypatch.setattr(producer, "_text_style", lambda *args: TextStyle())
    brief = _brief(
        ContentKind.STATIC_FLYER,
        product_keys=keys,
        product_image_roles=roles,
        ad_mode=AdImageMode.PRODUCT,
        carousel=True,
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
    return outcome, vendor.requests


def test_all_ten_selected_photos_reach_distinct_flyer_requests(monkeypatch) -> None:
    outcome, requests = run_flyer(monkeypatch, count=10)
    assert outcome.failure is None
    assert len(requests) == len(outcome.media) == 10
    for i, request in enumerate(requests):
        assert request.params["reference_plan"]["photo_indices"] == [i]
        assert request.params["reference_plan"]["target_photo_index"] == i
        assert base64.b64decode(request.params["images"][0].split(",", 1)[1]) == PHOTO
        assert outcome.media[i].params["planned_output_count"] == 10


def test_guide_travels_with_each_real_product_without_inheriting_photo_zero_role(
    monkeypatch,
) -> None:
    outcome, requests = run_flyer(monkeypatch, count=3, roles=("composition", "product", "product"))
    assert outcome.failure is None
    assert len(requests) == len(outcome.media) == 2
    for i, request in enumerate(requests, start=1):
        plan = request.params["reference_plan"]
        assert plan["photo_indices"] == [i, 0]
        assert plan["photo_roles"] == ["product", "composition"]
        assert len(request.params["images"]) == 2
        assert "Image 2: composition guide ONLY" in request.params["prompt"]
        assert "Real product identity: image 1" in request.params["prompt"]


def gallery_setup(monkeypatch, *, target=0, use_background=True):
    keys = tuple(f"uploads/{TENANT_ID}/gallery{i}.jpg" for i in range(2))
    bg = f"uploads/{TENANT_ID}/place.jpg"
    store = MemoryStore(dict.fromkeys((*keys, bg), PHOTO))
    vendor = Capture()
    producer = _producer(store, seedream=vendor)
    monkeypatch.setattr(producer, "_text_style", lambda *args: TextStyle())
    brief = _brief(
        ContentKind.CAROUSEL,
        product_keys=keys,
        product_image_roles=("composition", "product"),
        background_key=bg,
        brand_application_version=2,
        resource_plan_version=2,
        closing_slide=False,
        slides=(
            CarouselSlide(
                source=SlideSource.GENERATED,
                product_index=target,
                use_background=use_background,
                text=SlideText.NONE,
            ),
            CarouselSlide(
                source=SlideSource.GENERATED,
                product_index=target,
                use_background=use_background,
                text=SlideText.NONE,
            ),
        ),
    )
    return producer, brief, vendor


def test_gallery_guide_scene_includes_real_identity_and_selected_background(monkeypatch) -> None:
    producer, brief, vendor = gallery_setup(monkeypatch)
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
    assert outcome.failure is None
    assert len(vendor.requests) == 2
    request = vendor.requests[0]
    plan = request.params["reference_plan"]
    assert plan["target_photo_index"] == 0
    assert plan["photo_indices"] == [1, 0]
    assert plan["background_number"] == 3
    assert len(request.params["images"]) == 3
    assert "Image 1: the client's real product identity" in request.params["prompt"]
    assert "Image 2: composition guide ONLY" in request.params["prompt"]
    assert "Image 3: the client's real place" in request.params["prompt"]
    assert outcome.media[0].params["reference_plan"] == plan


def test_gallery_missing_selected_background_fails_before_any_request(monkeypatch) -> None:
    producer, brief, vendor = gallery_setup(monkeypatch, use_background=False)
    with pytest.raises(BrandReferenceError, match="fondo"):
        producer._preflight_brand_references(brief, _kit(), BrandReferencesSet(block_version=9))
    assert vendor.requests == []


class SimulatedFitter:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def fit(self, data, *, size, overlay=None, **kwargs):
        from qualify_creative.video import FittedVideo

        self.calls.append({"overlay": overlay, "size": size})
        if self.fail:
            raise RuntimeError("local composition failed")
        return FittedVideo(data=data, width=size[0], height=size[1], duration_sec=5, poster=PHOTO)


def signature_refs():
    key = f"uploads/{TENANT_ID}/signature.jpg"
    ref = BrandReference(
        asset_key=key,
        snapshot_key=key,
        fingerprint=hashlib.sha256(PHOTO).hexdigest(),
        asset_kind="logo_version",
        instruction_version=9,
    )
    return key, BrandReferencesSet(block_version=9, overlay=ref)


def test_required_signature_reads_validated_bytes_once_and_reuses_them(monkeypatch) -> None:
    key, refs = signature_refs()

    class ReadOnce(MemoryStore):
        count = 0

        def read(self, name):
            if name == key:
                self.count += 1
                if self.count > 1:
                    raise FileNotFoundError(name)
            return super().read(name)

    vendor, store = Capture(), ReadOnce({key: PHOTO})
    producer = _producer(store, seedream=vendor)
    monkeypatch.setattr(producer, "_text_style", lambda *args: TextStyle())
    logos = []

    def compose(**kwargs):
        logos.append(kwargs["logo"])
        return kwargs["scenes"]

    monkeypatch.setattr(module, "render_ad_slides", compose)
    outcome = producer.produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=_brief(
            ContentKind.STATIC_FLYER, brand_application_version=2, brand_logo_in_scene=False
        ),
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
        brand_references=refs,
    )
    assert outcome.failure is None
    assert store.count == 1 and logos == [PHOTO]


@pytest.mark.parametrize("missing_fitter", [False, True])
def test_required_clip_signature_cannot_succeed_without_composition(monkeypatch, missing_fitter):
    key, refs = signature_refs()
    store, vendor = MemoryStore({key: PHOTO}), FakeSeedance()
    producer = _producer(store, seedance=vendor)
    fitter = SimulatedFitter(fail=True)
    producer._fitter = None if missing_fitter else fitter
    monkeypatch.setattr(module, "text_layer", lambda **kwargs: PHOTO)
    outcome = producer.produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=_brief(ContentKind.CLIP, brand_application_version=2, brand_logo_in_scene=False),
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
        brand_references=refs,
    )
    assert outcome.failure is not None and outcome.media == ()
    assert len(vendor.requests) == (0 if missing_fitter else 1)
    if not missing_fitter:
        assert outcome.usage
        assert any(name.endswith("clip-raw.mp4") for name in store.files)


def test_animated_gallery_none_still_has_signature_layer(monkeypatch):
    key, refs = signature_refs()
    producer, brief, vendor = gallery_setup(monkeypatch)
    producer._store.files[key] = PHOTO
    producer._router._providers["seedance"] = FakeSeedance()
    producer._fitter = SimulatedFitter()
    monkeypatch.setattr(module, "text_layer", lambda **kwargs: PHOTO)
    slides = tuple(
        slide.model_copy(update={"source": SlideSource.ANIMATED}) for slide in brief.media.slides
    )
    brief = brief.model_copy(
        update={
            "media": brief.media.model_copy(update={"slides": slides, "brand_logo_in_scene": False})
        }
    )
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
    assert len(producer._fitter.calls) == 2
    assert all(call["overlay"] == PHOTO for call in producer._fitter.calls)


@pytest.mark.parametrize("finish", [module.FINISH_SLIDE, module.FINISH_CLIP])
def test_final_required_signature_is_applied_even_without_words(monkeypatch, finish):
    from types import SimpleNamespace

    key, refs = signature_refs()
    raw_key, overlay_key = f"uploads/{TENANT_ID}/paid.mp4", f"uploads/{TENANT_ID}/overlay.png"
    store = MemoryStore(
        {key: PHOTO, raw_key: b"simulated paid provider result", overlay_key: PHOTO}
    )
    producer = _producer(store)
    producer._fitter = SimulatedFitter()
    monkeypatch.setattr(module, "text_layer", lambda **kwargs: PHOTO)
    asset = SimpleNamespace(
        params={"brand_references": refs.model_dump(mode="json")},
        object_key="preview.mp4",
        position=0,
        aspect_ratio="3:4",
    )
    block = {
        "model": "dreamina-seedance-2-5-260628",
        "ratio": "3:4",
        "finish": finish,
        "words": False,
        "overlay_key": overlay_key,
        "raw_final": {"key": raw_key, "resolution": "1080p"},
    }
    kept = {}
    producer._final_video(
        TENANT_ID,
        uuid4(),
        _brief(ContentKind.CLIP),
        _kit(),
        asset,
        block,
        BUDGET,
        [],
        1,
        kept,
        None,
    )
    assert producer._fitter.calls[0]["overlay"] == PHOTO
    assert kept["raw_final"]["key"] == raw_key
    producer._fitter = SimulatedFitter(fail=True)
    with pytest.raises(RuntimeError, match="composition failed"):
        producer._final_video(
            TENANT_ID,
            uuid4(),
            _brief(ContentKind.CLIP),
            _kit(),
            asset,
            block,
            BUDGET,
            [],
            1,
            kept,
            None,
        )
    assert kept["raw_final"]["key"] == raw_key


def template_setup(monkeypatch, *, photos=1):
    from qualify_creative.render import TemplateManifest, TemplateRegistry

    from .test_creative_media import _PROMO, _template_brief, _template_producer

    manifest = _PROMO.model_dump(mode="json", by_alias=True)
    manifest["inputs"]["photos"]["min"] = 1
    registry = TemplateRegistry([TemplateManifest.model_validate(manifest)])

    class SimulatedRemotion:
        requests = None

        def __init__(self):
            self.requests = []

        def generate(self, request, *, api_key):
            from qualify_creative.render.adapter import MODEL_ID

            self.requests.append(request)
            return GenerationResult(
                payload={
                    "outputs": {
                        "feed": {
                            "bytes": PHOTO,
                            "mime_type": "image/jpeg",
                            "width": 1080,
                            "height": 1350,
                            "kind": "still",
                        }
                    },
                    "failed_ports": {},
                    "status": "completed",
                },
                provider="remotion",
                model_id=MODEL_ID,
                usage=Usage(pieces=1),
            )

    keys = tuple(f"uploads/{TENANT_ID}/template{i}.jpg" for i in range(photos))
    vendor = SimulatedRemotion()
    producer = _template_producer(
        MemoryStore(dict.fromkeys(keys, PHOTO)), vendor, registry=registry
    )
    monkeypatch.setattr(producer, "_text_style", lambda *args: TextStyle())
    brief = _template_brief(
        product_keys=keys,
        template_id="promo_producto",
        template_version=1,
        brand_application_version=2,
        resource_plan_version=2,
    )
    brief = brief.model_copy(update={"source_media_key": None, "brand_id": _kit().brand_id})
    return producer, brief, vendor


def test_full_template_producer_accepts_empty_brand_selection_and_sends_both_families(monkeypatch):
    producer, brief, vendor = template_setup(monkeypatch)
    producer._semantic_selection = True
    kit = _kit().model_copy(update={"font_heading": "Baloo 2", "font_body": "Nunito"})
    outcome = producer.produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=brief,
        kit=kit,
        copy=COPY,
        budget=BUDGET,
        brand_references=BrandReferencesSet(block_version=9),
    )
    assert outcome.failure is None, outcome.detail
    assert len(vendor.requests) == 1
    assert vendor.requests[0].params["props"].brand.fonts == {
        "heading": "Baloo 2",
        "body": "Nunito",
    }
    assert len(vendor.requests[0].params["props"].photos) == 1


@pytest.mark.parametrize("scene", [False, True])
def test_template_capacity_rejects_before_copy_selector_or_render(monkeypatch, scene):
    producer, brief, vendor = template_setup(monkeypatch, photos=5 if not scene else 4)
    if scene:
        brief = brief.model_copy(
            update={
                "media": brief.media.model_copy(update={"scene_prompt": "El producto en su mesa"})
            }
        )
    with pytest.raises(BrandReferenceError, match="hasta 4 fotos"):
        producer._preflight_resource_candidates(brief, _kit(), BrandReferencesSet(block_version=9))
    assert vendor.requests == []


def test_template_cannot_present_a_composition_guide_as_a_product(monkeypatch):
    producer, brief, vendor = template_setup(monkeypatch)
    brief = brief.model_copy(
        update={"media": brief.media.model_copy(update={"product_image_roles": ("composition",)})}
    )
    with pytest.raises(BrandReferenceError, match="no admite guías"):
        producer._preflight_resource_candidates(brief, _kit(), BrandReferencesSet(block_version=9))
    assert vendor.requests == []


def test_template_signature_passes_captured_bytes_through_real_asset_upload_consumer(monkeypatch):
    from types import SimpleNamespace

    from qualify_creative.render.adapter import RemotionTemplateAdapter

    producer, brief, vendor = template_setup(monkeypatch)
    key, refs = signature_refs()
    producer._store.files[key] = PHOTO
    brief = brief.model_copy(
        update={"media": brief.media.model_copy(update={"brand_logo_in_scene": False})}
    )
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
    request = vendor.requests[0]
    assert request.params["captured_media"][key]["sha256"] == hashlib.sha256(PHOTO).hexdigest()
    uploaded = []

    class Client:
        def upload_asset(self, data, **kwargs):
            uploaded.append((kwargs["filename"], data))
            return SimpleNamespace(ref="asset://" + kwargs["filename"], bytes=len(data))

    def read(name):
        assert name != key, "signature must not be read twice"
        return producer._store.read(name)

    adapter = RemotionTemplateAdapter(Client(), read_media=read)
    transported = adapter._upload_media(
        request.params["props"], captured=request.params["captured_media"]
    )
    assert transported.brand.logo == "asset://signature.jpg"
    assert uploaded[-1] == ("signature.jpg", PHOTO)


def test_new_brief_stamp_is_explicit_and_old_empty_brief_keeps_compiler_eight(monkeypatch):
    producer = _producer(MemoryStore())
    brief = _brief(ContentKind.CLIP)
    producer._reference_compiler_version = 8
    assert producer.prepare_new_brief(brief, _kit()) is brief
    producer._reference_compiler_version = 9
    producer._seedance_reference_model = "dreamina-seedance-2-5-260628"
    producer._semantic_selection = True
    new = producer.prepare_new_brief(brief, _kit())
    assert new.media.brand_application_version == 2
    for source, version in ((brief, 8), (new, 9)):
        refs = producer.prepare_brand_references(
            tenant_id=TENANT_ID, draft_id=uuid4(), brief=source, kit=_kit()
        )
        assert refs.block_version == version
    assert brief.media.brand_application_version == 0


@pytest.mark.parametrize("variant", ["references", "frames", "text"])
def test_non_edit_clip_consumer_v9_carries_logo_without_letter_conflict(monkeypatch, variant):
    from .test_creative_media_byteplus import FakeLinks

    key, signature = signature_refs()
    ref = signature.overlay.model_copy(update={"selected_logo": True, "asset_slot": "imagotipo"})
    refs = BrandReferencesSet(block_version=9, refs=(ref,))
    product, first, last = (f"uploads/{TENANT_ID}/{name}.jpg" for name in ("p", "first", "last"))
    files = dict.fromkeys((key, product, first, last), PHOTO)
    vendor = FakeSeedance()
    producer = _producer(MemoryStore(files), seedance=vendor)
    producer._seedance_reference_model = "dreamina-seedance-2-5-260628"
    producer._reference_links = FakeLinks()
    monkeypatch.setattr(producer, "_opening_frame", lambda data, *args: data)
    media = {"brand_application_version": 2, "resource_plan_version": 2}
    if variant == "references":
        media.update(clip_image_keys=(product,))
    elif variant == "frames":
        media.update(clip_first_frame_key=first, clip_last_frame_key=last)
    brief = _brief(ContentKind.CLIP, **media)
    kit = _kit().model_copy(update={"font_heading": "Baloo 2", "font_body": "Nunito"})
    outcome = producer.produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=brief,
        kit=kit,
        copy=COPY,
        budget=BUDGET,
        brand_references=refs,
    )
    assert outcome.failure is None, outcome.detail
    (request,) = vendor.requests
    assert base64.b64decode(request.params["reference_images"][-1].split(",", 1)[1]) == PHOTO
    assert "without drawing any letters" not in request.params["prompt"]
    assert "body=Nunito" in request.params["prompt"]
    assert "Preserve authentic product/manufacturer labels" in request.params["prompt"]
    assert len(request.params["prompt"]) <= 2950


@pytest.mark.parametrize("kind", [ContentKind.AVATAR_VIDEO, ContentKind.ANIMATED_AVATAR_VIDEO])
def test_seedance_avatar_consumer_v9_has_fonts_and_mandatory_resources(monkeypatch, kind):
    from .test_creative_media_byteplus import _seedance_brief

    key, signature = signature_refs()
    ref = signature.overlay.model_copy(update={"asset_kind": "extra", "note": "Junto al producto"})
    refs = BrandReferencesSet(block_version=9, refs=(ref,))
    brief = _seedance_brief(brand_application_version=2, resource_plan_version=2)
    brief = brief.model_copy(update={"kind": kind})
    files = dict.fromkeys((*brief.media.product_keys, brief.media.background_key, key), PHOTO)
    image, vendor = Capture(), FakeSeedance()
    producer = _producer(MemoryStore(files), seedream=image, seedance=vendor)
    monkeypatch.setattr(producer, "_opening_frame", lambda data, *args: data)
    kit = _kit().model_copy(update={"font_heading": "Baloo 2", "font_body": "Nunito"})
    outcome = producer.produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=brief,
        kit=kit,
        copy=COPY,
        budget=BUDGET,
        brand_references=refs,
    )
    assert outcome.failure is None, outcome.detail
    frame, motion = image.requests[0].params, vendor.requests[0].params
    assert [r["role"] for r in frame["reference_manifest"]] == [
        "product",
        "background",
        "brand_resource",
    ]
    assert all(
        r["sha256"] == hashlib.sha256(PHOTO).hexdigest() for r in frame["reference_manifest"]
    )
    for prompt in (frame["prompt"], motion["prompt"]):
        assert "without drawing any letters" not in prompt
        assert "body=Nunito" in prompt
    assert "Every selected brand resource is mandatory" in motion["prompt"]
    assert "unused candidates" not in motion["prompt"]
    assert len(motion["prompt"]) + len(motion["dialogue"]) + len('\nDice a cámara: ""') <= 2950


def test_omnihuman_motion_limit_is_checked_before_frame_or_voice_even_without_logo(monkeypatch):
    from .test_creative_media_byteplus import (
        FakeLinks,
        FakeOmniHuman,
        FakeSpeech,
        _presenter,
        _presenter_brief,
    )

    image, speech, omni = Capture(), FakeSpeech(), FakeOmniHuman()
    producer = _presenter(
        MemoryStore(), seedream=image, speech=speech, omni=omni, links=FakeLinks()
    )
    monkeypatch.setattr(module, "_media_seconds", lambda data: 5)
    kit = _kit().model_copy(update={"font_heading": "Baloo 2", "font_body": "Nunito"})
    brief = _presenter_brief(brand_application_version=2, resource_plan_version=2)
    outcome = producer.produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=brief,
        kit=kit,
        copy=COPY,
        budget=BUDGET,
        brand_references=BrandReferencesSet(block_version=9),
    )
    assert outcome.failure is None, outcome.detail
    assert len(omni.requests[0].params["prompt"]) <= 1000
    assert "body=Nunito" in omni.requests[0].params["prompt"]
    assert "No text on screen" not in omni.requests[0].params["prompt"]


def test_omnihuman_impossible_prompt_fails_before_frame_voice_or_video(monkeypatch):
    from .test_creative_media_byteplus import (
        FakeLinks,
        FakeOmniHuman,
        FakeSpeech,
        _presenter,
        _presenter_brief,
    )

    image, speech, omni = Capture(), FakeSpeech(), FakeOmniHuman()
    producer = _presenter(
        MemoryStore(), seedream=image, speech=speech, omni=omni, links=FakeLinks()
    )
    kit = _kit().model_copy(update={"font_heading": "X" * 1000, "font_body": "Nunito"})
    brief = _presenter_brief(brand_application_version=2, resource_plan_version=2)
    outcome = producer.produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=brief,
        kit=kit,
        copy=COPY,
        budget=BUDGET,
        brand_references=BrandReferencesSet(block_version=9),
    )
    assert outcome.failure == "invalid_parameters"
    assert outcome.usage == ()
    assert image.requests == speech.requests == omni.requests == []


def test_gallery_video_reference_consumer_has_complete_motion_and_correct_indices(monkeypatch):
    from .test_creative_media_byteplus import FakeLinks

    producer, brief, image = gallery_setup(monkeypatch)
    key, signature = signature_refs()
    refs = BrandReferencesSet(block_version=9, refs=(signature.overlay,))
    video_key = f"uploads/{TENANT_ID}/reference.mp4"
    producer._store.files.update({key: PHOTO, video_key: b"simulated existing video"})
    vendor = FakeSeedance()
    producer._router._providers["seedance"] = vendor
    producer._seedance_reference_model = "dreamina-seedance-2-5-260628"
    producer._reference_links = FakeLinks()
    producer._fitter = SimulatedFitter()
    monkeypatch.setattr(producer, "_opening_frame", lambda data, *args: data)
    monkeypatch.setattr(module, "_media_seconds", lambda data: 5)
    slides = tuple(
        slide.model_copy(update={"source": SlideSource.ANIMATED, "reference_video_key": video_key})
        for slide in brief.media.slides
    )
    brief = brief.model_copy(update={"media": brief.media.model_copy(update={"slides": slides})})
    kit = _kit().model_copy(update={"font_heading": "Baloo 2", "font_body": "Nunito"})
    outcome = producer.produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=brief,
        kit=kit,
        copy=COPY,
        budget=BUDGET,
        brand_references=refs,
    )
    assert outcome.failure is None, outcome.detail
    for request in vendor.requests:
        assert len(request.params["reference_images"]) == 2
        assert len(request.params["reference_videos"]) == 1
        assert "body=Nunito" in request.params["prompt"]
        assert "Preserve authentic product/manufacturer labels" in request.params["prompt"]
        assert (
            "camera movement, pacing and rhythm of the reference video" in request.params["prompt"]
        )
        assert len(request.params["prompt"]) <= 2950


@pytest.mark.parametrize("source", [SlideSource.EXISTING, SlideSource.STOCK])
def test_reused_video_gallery_without_scene_resources_remains_supported(monkeypatch, source):
    from .test_creative_media_byteplus import PIECE_VIDEO, STOCK_VIDEO, FakePieces

    key = PIECE_VIDEO if source is SlideSource.EXISTING else STOCK_VIDEO
    store = MemoryStore({key: b"simulated existing video"})
    producer = _producer(store)
    producer._pieces, producer._fitter = FakePieces(), SimulatedFitter()
    monkeypatch.setattr(producer, "_text_style", lambda *args: TextStyle())
    monkeypatch.setattr(module, "text_layer", lambda **kwargs: PHOTO)
    slide = CarouselSlide(
        source=source,
        object_key=key,
        text=SlideText.HOOK if source is SlideSource.STOCK else SlideText.NONE,
    )
    brief = _brief(
        ContentKind.CAROUSEL,
        slides=(slide, slide),
        closing_slide=False,
        brand_application_version=2,
        resource_plan_version=2,
    )
    output = producer.produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=brief,
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
        brand_references=BrandReferencesSet(block_version=9),
    )
    assert output.failure is None, output.detail
    assert len(output.media) == 2 and output.usage == ()
    _, refs = signature_refs()
    rejected = producer.produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=brief,
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
        brand_references=refs,
    )
    assert rejected.failure == "invalid_parameters" and rejected.usage == ()
    assert "imagen generada" in rejected.detail


def test_flyer_single_scene_reel_uses_all_photos_in_its_one_scene(monkeypatch):
    from qualify_creative.enums import ContentFormat
    from qualify_creative.video import FittedVideo

    keys = tuple(f"uploads/{TENANT_ID}/reel{i}.jpg" for i in range(2))
    vendor = Capture()
    producer = _producer(MemoryStore(dict.fromkeys(keys, PHOTO)), seedream=vendor)
    monkeypatch.setattr(producer, "_text_style", lambda *args: TextStyle())

    class Animator:
        def animate_still(self, still, *, size):
            return FittedVideo(
                data=b"simulated existing animator result",
                width=size[0],
                height=size[1],
                duration_sec=5,
                poster=PHOTO,
            )

    producer._fitter = Animator()
    brief = _brief(
        ContentKind.STATIC_FLYER,
        ContentFormat.REELS_9_16,
        product_keys=keys,
        carousel=False,
        brand_application_version=2,
        resource_plan_version=2,
    )
    outcome = producer.produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=brief,
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
        brand_references=BrandReferencesSet(block_version=9),
    )
    assert outcome.failure is None, outcome.detail
    assert len(vendor.requests) == len(outcome.media) == 1
    assert len(vendor.requests[0].params["images"]) == 2
    assert outcome.media[0].params["planned_output_count"] == 1


@pytest.mark.parametrize("extras", [0, 6])
def test_omnihuman_normal_branded_motion_preserves_composed_frame_under_1000(monkeypatch, extras):
    from .test_creative_media_byteplus import (
        FakeLinks,
        FakeOmniHuman,
        FakeSpeech,
        _presenter,
        _presenter_brief,
    )

    key, signature = signature_refs()
    logo = signature.overlay.model_copy(update={"selected_logo": True, "label": "Nibbles"})
    refs = BrandReferencesSet(
        block_version=9,
        refs=(
            logo,
            *(
                logo.model_copy(
                    update={
                        "asset_key": f"uploads/{TENANT_ID}/extra{i}.jpg",
                        "snapshot_key": f"uploads/{TENANT_ID}/extra{i}.jpg",
                        "asset_kind": "extra",
                        "selected_logo": False,
                        "label": f"Elemento {i}",
                    }
                )
                for i in range(extras)
            ),
        ),
    )
    product = f"uploads/{TENANT_ID}/omni-product.jpg"
    files = dict.fromkeys((product, key, *(r.snapshot_key for r in refs.refs)), PHOTO)
    image, speech, omni = Capture(), FakeSpeech(), FakeOmniHuman()
    producer = _presenter(
        MemoryStore(files), seedream=image, speech=speech, omni=omni, links=FakeLinks()
    )
    monkeypatch.setattr(module, "_media_seconds", lambda data: 5)
    brief = _presenter_brief(
        product_keys=(product,),
        product_image_roles=("product",),
        brand_application_version=2,
        resource_plan_version=2,
    )
    kit = _kit().model_copy(
        update={
            "font_heading": "Baloo 2",
            "font_body": "Nunito",
            "palette_rgb": ("#CA3433", "#FFF3DD", "#F8E6C0", "#DA726F", "#221100"),
        }
    )
    outcome = producer.produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=brief,
        kit=kit,
        copy=COPY,
        budget=BUDGET,
        brand_references=refs,
    )
    assert outcome.failure is None, outcome.detail
    assert len(image.requests[0].params["images"]) == 2 + extras
    prompt = omni.requests[0].params["prompt"]
    assert len(prompt) <= 1000
    assert "ALL selected logos/resources" in prompt and "supplied audio" in prompt
    assert "body=Nunito" in prompt and "heading=Baloo 2" in prompt
    assert all(color in prompt for color in kit.palette_rgb)
    assert "Image 2" not in prompt and "unused candidates" not in prompt

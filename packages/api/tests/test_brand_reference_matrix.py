"""Offline contracts, not model-quality scores or evidence of visual generalization."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.enums import ContentKind, SlideSource
from qualify_creative.schemas import CarouselSlide

from qualify_api.creative import media as media_module
from qualify_api.creative import pipeline
from qualify_api.creative.brand_kit_store import BrandAsset
from qualify_api.creative.brand_references import (
    BrandReferenceError,
    BrandReferencesSet,
    brand_reference_block,
    read_brand_reference_images,
    resolve_brand_references,
)
from qualify_api.creative.service import ContentService

from .test_creative_clip import REF_MODEL, _clip_producer
from .test_creative_media_byteplus import (
    BRAND_ID,
    BUDGET,
    COPY,
    TENANT_ID,
    FakeFitter,
    FakeLinks,
    FakeOmniHuman,
    FakeSeedance,
    FakeSeedream,
    FakeSpeech,
    MemoryStore,
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
from .test_creative_reel_edit import edit_brief
from .test_creative_seedance_video_input import (
    VideoInputSeedance,
    _measured,
)
from .test_creative_seedance_video_input import (
    _producer as _edit_producer,
)

LOGO = f"t/{TENANT_ID}/brand/{BRAND_ID}/selected.png"
EXTRA = f"t/{TENANT_ID}/brand/{BRAND_ID}/logo-isologo-mascot.png"
RULES = [
    ("logo_version", "logotipo", "exact wordmark", "do not add a symbol"),
    ("logo_version", "isotipo", "selected symbol", "do not invent or add lettering"),
    ("logo_version", "imagotipo", "chosen symbol-and-wordmark lockup", "usage note"),
    ("logo_version", "isologo", "inseparable symbol-and-wordmark unit", "never split"),
    ("logo", "isotipo", "whole selected logo", "do not guess its category"),
]


def _rows(
    producer: Any, store: Any, *, kind: str = "logo_version", slot: str = "logotipo"
) -> list[BrandAsset]:
    store.files[LOGO], store.files[EXTRA] = _image((10, 180, 60)), _image((200, 40, 170))
    rows = [
        BrandAsset(kind, slot, LOGO, label="Marca elegida", content_type="image/png"),
        BrandAsset("extra", "isologo", EXTRA, label="Mascota", content_type="image/png"),
    ]

    def reader(tenant: UUID, brand: UUID) -> list[BrandAsset]:
        assert (tenant, brand) == (TENANT_ID, BRAND_ID)
        return list(rows)

    producer._brand_assets = reader
    return rows


@pytest.mark.parametrize("video", [False, True], ids=["image", "video"])
@pytest.mark.parametrize("kind,slot,identity,restriction", RULES)
def test_taxonomy_comes_from_asset_metadata_for_images_and_video(
    video: bool, kind: str, slot: str, identity: str, restriction: str
) -> None:
    # Misleading filename and label deliberately disagree with the actual category.
    key = f"t/{TENANT_ID}/brand/isotipo-isologo.png"
    asset = BrandAsset(kind, slot, key, label="isotipo", content_type="image/png")
    selected = resolve_brand_references(
        lambda tenant, brand: [asset],
        tenant_id=TENANT_ID,
        brand_id=BRAND_ID,
        brand_logo_key=key,
        brand_element_keys=(),
        logo_in_scene=True,
    )
    ref = selected.refs[0]
    assert (ref.asset_kind, ref.asset_slot) == (kind, slot)
    block = brand_reference_block(selected.refs, base_index=4, video=video)
    assert "Image 4:" in block
    assert identity in block and restriction in block
    assert ("throughout the relevant shots" in block) is video


def test_extra_named_like_logo_is_never_given_logo_taxonomy() -> None:
    asset = BrandAsset("extra", "isologo", EXTRA, label="Logo isotipo", content_type="image/png")
    selected = resolve_brand_references(
        lambda tenant, brand: [asset],
        tenant_id=TENANT_ID,
        brand_id=BRAND_ID,
        brand_logo_key=None,
        brand_element_keys=(EXTRA,),
    )
    prompt = brand_reference_block(selected.refs, base_index=1, video=True)
    assert "Brand Kit category" not in prompt
    assert "Preserve identity, colors and proportions" in prompt
    assert selected.refs[0].rol.value == "elemento_de_marca"


@pytest.mark.parametrize("name", ["Luna Cacao", "Taller Horizonte"])
@pytest.mark.parametrize("products,background,extras", [(0, False, 0), (1, True, 0), (3, True, 1)])
def test_arbitrary_tenant_brand_and_scene_offsets_reach_the_image_vendor(
    name: str, products: int, background: bool, extras: int
) -> None:
    tenant, brand = uuid4(), uuid4()
    logo, extra = f"t/{tenant}/brand/{brand}/mark.png", f"t/{tenant}/brand/{brand}/object.png"
    photos = tuple(f"uploads/{tenant}/p{i}.jpg" for i in range(products))
    bg = f"uploads/{tenant}/bg.jpg" if background else None
    files = {key: _image((20 + i, 80, 170)) for i, key in enumerate((*photos, logo, extra))}
    if bg:
        files[bg] = _image((70, 60, 50))
    store, vendor = MemoryStore(files), FakeSeedream()
    producer = _producer(store, seedream=vendor)
    rows = [BrandAsset("logo_version", "logotipo", logo, label=name, content_type="image/png")]
    if extras:
        rows.append(BrandAsset("extra", "mascot", extra, label="Figura", content_type="image/png"))

    def assets(t: UUID, b: UUID) -> list[BrandAsset]:
        assert (t, b) == (tenant, brand)
        return rows

    producer._brand_assets = assets
    brief = _brief(
        ContentKind.STATIC_FLYER,
        product_keys=photos,
        background_key=bg,
        brand_element_keys=(extra,) if extras else (),
        brand_logo_key=logo,
        brand_logo_in_scene=True,
    ).model_copy(update={"brand_id": brand, "topic": f"Presenta {name}"})
    kit = _kit().model_copy(update={"brand_id": brand, "positioning": name})
    result = producer.produce(
        tenant_id=tenant,
        draft_id=uuid4(),
        brief=brief,
        kit=kit,
        copy=COPY.model_copy(update={"hook": name, "caption": name}),
        budget=BUDGET,
    )
    assert result.failure is None, result.detail
    params = vendor.requests[0].params
    index = products + int(background) + extras + 1
    assert f"Image {index}: {name}" in params["prompt"]
    assert "exact wordmark" in params["prompt"]
    assert len(params["images"]) == index
    assert "Nibbles" not in params["prompt"] and "Smash" not in params["prompt"]
    assert "brand_references" in result.media[0].params


@pytest.mark.parametrize("source", ["Cobre Cafe", "Nube Taller", "sin marca visible"])
@pytest.mark.parametrize("products,extras", [(1, 0), (2, 1)])
def test_edit_vendor_keeps_source_structure_and_targets_the_selected_logo(
    monkeypatch: pytest.MonkeyPatch, source: str, products: int, extras: int
) -> None:
    _measured(monkeypatch, 5)
    monkeypatch.setattr(media_module, "_video_dimensions", lambda data: (854, 480))
    vendor = VideoInputSeedance()
    producer = _edit_producer(vendor)
    _rows(producer, producer._store)
    producer._store.files[f"uploads/{TENANT_ID}/p2.jpg"] = _image((40, 200, 50))
    brief = edit_brief(
        clip_image_keys=tuple(f"uploads/{TENANT_ID}/p{i + 1}.jpg" for i in range(products)),
        brand_element_keys=(EXTRA,) if extras else (),
        brand_logo_key=LOGO,
        brand_logo_in_scene=True,
    ).model_copy(
        update={
            "topic": f"Referencia de {source}. Presenta Aurora Cafe.",
            "product_ref": "taza azul",
        }
    )
    result = _produce(producer, brief, uuid4())
    assert result.failure is None, result.detail
    params = vendor.requests[0].params
    assert f"selected client logo @Image{products + extras + 1}" in params["prompt"]
    assert "camera trajectory" in params["prompt"] and "every stage of assembly" in params["prompt"]
    assert "No source-video-owner text or logo may remain" in params["prompt"]
    assert "manufacturer labels from the product references" in params["prompt"]
    assert "exact wordmark" in params["prompt"]
    assert source in params["prompt"] and "taza azul" in params["prompt"]
    assert len(params["reference_images"]) == products + extras + 1
    assert "first_frame" not in params


def test_category_note_role_and_bytes_are_frozen_on_resume_but_refresh_next_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store()
    producer = _producer(store)
    rows = _rows(producer, store)
    rows[0] = replace(rows[0], context="Conservar la palabra completa")
    brief = _brief(ContentKind.STATIC_FLYER, brand_logo_key=LOGO, brand_logo_in_scene=True)
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
        first = producer.prepare_brand_references(
            tenant_id=TENANT_ID, draft_id=run.draft_id, brief=brief, kit=_kit()
        )
        original = store.files[LOGO]
        rows[0] = replace(rows[0], slot="isotipo", context="Solo el simbolo")
        store.files[LOGO] = _image((50, 50, 250))
        resumed = producer.prepare_brand_references(
            tenant_id=TENANT_ID, draft_id=run.draft_id, brief=brief, kit=_kit()
        )
        assert resumed.model_dump() == first.model_dump()
        ref = resumed.refs[0]
        assert ref.selected_logo is True
        assert (ref.asset_kind, ref.asset_slot, ref.note, ref.rol.value) == (
            "logo_version",
            "logotipo",
            "Conservar la palabra completa",
            "elemento_de_marca",
        )
        assert ref.fingerprint == hashlib.sha256(original).hexdigest()
        assert read_brand_reference_images(store.read, resumed.refs)[0].image == original
        steps.clear()
        fresh = producer.prepare_brand_references(
            tenant_id=TENANT_ID, draft_id=run.draft_id, brief=brief, kit=_kit(), revision=2
        )
        assert fresh.refs[0].asset_slot == "isotipo" and fresh.refs[0].note == "Solo el simbolo"
        assert fresh.refs[0].fingerprint != ref.fingerprint
    finally:
        pipeline._preparation.reset(token)


def test_old_frozen_records_default_to_neutral_metadata_without_invented_category() -> None:
    legacy = BrandReferencesSet.model_validate({"refs": [{"asset_key": LOGO, "label": "isotipo"}]})
    ref = legacy.refs[0]
    assert ref.asset_kind == ref.asset_slot == ""
    assert ref.selected_logo is False
    assert "Brand Kit category" not in brand_reference_block(legacy.refs, base_index=1)


def test_same_tenant_resource_from_another_brand_is_refused_before_object_read() -> None:
    store, vendor = _store(), FakeSeedream()
    producer = _producer(store, seedream=vendor)
    _rows(producer, store)
    foreign = f"t/{TENANT_ID}/brand/{uuid4()}/logo.png"
    store.read = lambda key: pytest.fail("read an unselected brand resource")
    result = _produce(
        producer,
        _brief(ContentKind.STATIC_FLYER, brand_logo_key=foreign, brand_logo_in_scene=True),
        uuid4(),
    )
    assert result.failure == "invalid_parameters" and vendor.requests == []


@pytest.mark.parametrize(
    "route", ["flyer", "gallery", "animated_gallery", "clip", "human", "animated_avatar"]
)
def test_protected_instructions_over_budget_fail_before_copy_or_vendor(route: str) -> None:
    store, image, video = _store(), FakeSeedream(), FakeSeedance()
    producer = (
        _clip_producer(store, video)
        if route == "clip"
        else _producer(store, seedream=image, seedance=video)
    )
    producer._seedance_model = REF_MODEL
    producer._fitter = FakeFitter()
    rows = _rows(producer, store)
    rows[0] = replace(rows[0], context="Mantener esta identidad " * 1000)
    media = {"brand_logo_key": LOGO, "brand_logo_in_scene": True}
    if route in {"human", "animated_avatar"}:
        brief = _seedance_brief(**media)
        if route == "animated_avatar":
            brief = brief.model_copy(update={"kind": ContentKind.ANIMATED_AVATAR_VIDEO})
    elif "gallery" in route:
        source = SlideSource.ANIMATED if route == "animated_gallery" else SlideSource.GENERATED
        brief = _brief(
            ContentKind.CAROUSEL,
            slides=(CarouselSlide(source=source, scene_prompt="El local"),),
            closing_slide=True,
            **media,
        )
    else:
        brief = _brief(ContentKind.CLIP if route == "clip" else ContentKind.STATIC_FLYER, **media)
    service = object.__new__(ContentService)
    service._brand = SimpleNamespace(kit=lambda **_: _kit())
    service._voice = SimpleNamespace(active=lambda **_: SimpleNamespace())
    service._repo = SimpleNamespace(budget_state=lambda **_: None)
    service._media = producer
    settled: list[dict[str, Any]] = []
    service._finish_brief = lambda **data: settled.append(data)
    service._copy_stage = lambda **_: pytest.fail("paid copy reached after invalid reference plan")
    store.read = lambda key: pytest.fail("read resource after overflowing protected instructions")
    service._generate_brief(
        tenant_id=TENANT_ID,
        draft=SimpleNamespace(brand_id=BRAND_ID, id=uuid4(), revision=1),
        brief=brief,
    )
    assert settled[0]["spent"] == 0 and settled[0]["media_failure"] == "invalid_parameters"
    assert image.requests == video.requests == []


@pytest.mark.parametrize(
    "route",
    ["flyer", "gallery", "animated_gallery", "clip", "human", "animated_avatar", "omnihuman"],
)
def test_selected_wordmark_survives_media_routing_without_a_global_lettering_ban(
    route: str,
) -> None:
    store, image, video = _store(), FakeSeedream(), FakeSeedance()
    omni, speech = FakeOmniHuman(), FakeSpeech()
    if route == "clip":
        producer = _clip_producer(store, video)
    elif route == "omnihuman":
        producer = _presenter(store, seedream=image, speech=speech, omni=omni, links=FakeLinks())
    else:
        producer = _producer(store, seedream=image, seedance=video)
    producer._seedance_model = REF_MODEL
    producer._fitter = FakeFitter()
    _rows(producer, store)
    if route == "omnihuman":
        # Verify the final video motion request carries the note, not only its still frame.
        rows = _rows(producer, store)
        rows[0] = replace(rows[0], context="Conservar el logo en cada toma")
        producer._brand_assets = lambda tenant, brand: rows
    selection = {"brand_logo_key": LOGO, "brand_logo_in_scene": True}
    if route in {"human", "animated_avatar"}:
        brief = _seedance_brief(**selection)
        if route == "animated_avatar":
            brief = brief.model_copy(update={"kind": ContentKind.ANIMATED_AVATAR_VIDEO})
    elif route == "omnihuman":
        brief = _presenter_brief(**selection)
    elif "gallery" in route:
        source = SlideSource.ANIMATED if route == "animated_gallery" else SlideSource.GENERATED
        brief = _brief(
            ContentKind.CAROUSEL,
            slides=(CarouselSlide(source=source, scene_prompt="El local"),),
            closing_slide=True,
            **selection,
        )
    else:
        brief = _brief(
            ContentKind.CLIP if route == "clip" else ContentKind.STATIC_FLYER, **selection
        )
    result = _produce(producer, brief, uuid4())
    assert result.failure is None, result.detail
    for request in (*image.requests, *video.requests):
        prompt = request.params["prompt"]
        assert "logo's exact existing lettering" in prompt
        assert "Do not draw any text, letters, numbers" not in prompt
        assert "No text on screen." not in prompt
    if route == "human":
        assert "first_frame" in video.requests[0].params
        assert "reference_images" not in video.requests[0].params
    elif route == "animated_avatar":
        assert len(video.requests[0].params["reference_images"]) == 2
        assert "first_frame" not in video.requests[0].params
    elif route == "animated_gallery":
        assert "first_frame" in video.requests[0].params
        assert "reference_images" not in video.requests[0].params
    elif route == "omnihuman":
        assert omni.requests and "reference_images" not in omni.requests[0].params
        motion = omni.requests[0].params["prompt"]
        assert len(motion) <= 1000
        assert "Conservar el logo en cada toma" in motion
        assert "Brand Kit category: logotipo" in motion
        assert "logo's exact existing lettering" in motion
        assert "No text on screen." not in motion


@pytest.mark.parametrize(
    "kind,slot", [("extra", "logotipo"), ("extra", "isologo"), ("font", "isotipo")]
)
def test_nonlogo_asset_cannot_masquerade_as_selected_logo(kind: str, slot: str) -> None:
    store, vendor = _store(), FakeSeedream()
    producer = _producer(store, seedream=vendor)
    _rows(producer, store, kind=kind, slot=slot)
    store.read = lambda key: pytest.fail("nonlogo selection read before rejection")
    result = _produce(
        producer,
        _brief(ContentKind.STATIC_FLYER, brand_logo_key=LOGO, brand_logo_in_scene=True),
        uuid4(),
    )
    assert result.failure == "invalid_parameters" and vendor.requests == []


@pytest.mark.parametrize("version", [1, 2, 3])
def test_frozen_replay_preserves_legacy_semantics_and_rejects_unknown_future_versions(
    monkeypatch: pytest.MonkeyPatch,
    version: int,
) -> None:
    record = {
        "refs": [
            {
                "asset_key": LOGO,
                "label": "Marca antigua",
                "asset_kind": "logo_version",
                "asset_slot": "logotipo",
                "selected_logo": True,
            }
        ]
    }
    if version != 1:
        record["block_version"] = version

    class Steps:
        def load_step(self, run: Any, step: int) -> Any:
            return {"request": {"brand_refs": record}}

    monkeypatch.setattr(pipeline, "PipelineStore", Steps)
    token = pipeline._preparation.set(
        pipeline.Preparation(TENANT_ID, uuid4(), 1, "draft", uuid4(), 1)
    )
    try:

        def rebuild() -> Any:
            pytest.fail("resume consulted current Brand Kit")

        if version == 3:
            with pytest.raises(BrandReferenceError):
                pipeline.frozen_brand_references(rebuild)
        else:
            resumed = pipeline.frozen_brand_references(rebuild)
            ref = resumed.refs[0]
            if version == 1:
                assert ref.asset_kind == ref.asset_slot == "" and not ref.selected_logo
                assert "Brand Kit category" not in brand_reference_block(resumed.refs, base_index=1)
            else:
                assert ref.asset_kind == "logo_version" and ref.asset_slot == "logotipo"
                assert ref.selected_logo
    finally:
        pipeline._preparation.reset(token)


@pytest.mark.parametrize("route", ["flyer", "clip"])
@pytest.mark.parametrize("overflow", [False, True], ids=["boundary", "overflow"])
def test_family_caps_count_brand_images_together_with_products_background_and_frames(
    route: str,
    overflow: bool,
) -> None:
    store, image, video = _store(), FakeSeedream(), FakeSeedance()
    producer = _clip_producer(store, video) if route == "clip" else _producer(store, seedream=image)
    rows = _rows(producer, store)
    count = 3 if route == "flyer" else 6
    keys = tuple(f"t/{TENANT_ID}/brand/{BRAND_ID}/element{i}.png" for i in range(count))
    for key in keys:
        rows.append(BrandAsset("extra", "", key, label="Objeto", content_type="image/png"))
        store.files[key] = _image()
    if route == "flyer":
        brief = _brief(
            ContentKind.STATIC_FLYER,
            product_keys=(f"uploads/{TENANT_ID}/p1.jpg",) * 10,
            background_key=f"uploads/{TENANT_ID}/bg.jpg" if overflow else None,
            brand_element_keys=keys,
            brand_logo_key=LOGO,
            brand_logo_in_scene=True,
        )
        expected = 14
    else:
        brief = _brief(
            ContentKind.CLIP,
            clip_first_frame_key=f"uploads/{TENANT_ID}/p1.jpg",
            clip_last_frame_key=f"uploads/{TENANT_ID}/p2.jpg",
            clip_image_keys=(f"uploads/{TENANT_ID}/p3.jpg",) * (2 if overflow else 1),
            brand_element_keys=keys,
        )
        expected = 9
    if overflow:
        store.read = lambda key: pytest.fail("over-capacity plan read resources")
    result = _produce(producer, brief, uuid4())
    if overflow:
        assert result.failure == "invalid_parameters" and image.requests == video.requests == []
    else:
        assert result.failure is None, result.detail
        params = (video.requests if route == "clip" else image.requests)[0].params
        assert len(params["reference_images" if route == "clip" else "images"]) == expected
        if route == "clip":
            assert "first_frame" not in params and "last_frame" not in params


@pytest.mark.parametrize("reverse", [False, True])
def test_conflicting_categories_on_the_same_selected_object_are_rejected_before_reads(
    reverse: bool,
) -> None:
    store, vendor = _store(), FakeSeedream()
    producer = _producer(store, seedream=vendor)
    rows = _rows(producer, store)
    rows.append(replace(rows[0], kind="extra", slot="isotipo"))
    if reverse:
        rows.reverse()
    store.read = lambda key: pytest.fail("ambiguous classification read R2")
    result = _produce(
        producer,
        _brief(ContentKind.STATIC_FLYER, brand_logo_key=LOGO, brand_logo_in_scene=True),
        uuid4(),
    )
    assert result.failure == "invalid_parameters" and vendor.requests == []


def test_brand_only_scene_does_not_deny_its_references_and_legacy_scene_stays_literal() -> None:
    from qualify_creative.enums import AdImageMode

    from qualify_api.creative.brand_references import BrandReference
    from qualify_api.creative.media import ad_scene_prompt

    options = {
        "brief": _brief(ContentKind.STATIC_FLYER),
        "kit": _kit(),
        "brand": "Aurora",
        "mode": AdImageMode.SCENE,
        "products": 0,
        "has_background": False,
    }
    legacy = ad_scene_prompt(**options, brand_refs=(BrandReference(asset_key=LOGO),))
    assert "There are no reference images:" in legacy
    typed = ad_scene_prompt(
        **options,
        brand_refs=(
            BrandReference(
                asset_key=LOGO, asset_kind="logo_version", asset_slot="logotipo", selected_logo=True
            ),
        ),
    )
    assert "There are no reference images:" not in typed
    assert "reference images are brand resources" in typed


def test_legacy_omnihuman_final_motion_keeps_the_old_no_reference_request() -> None:
    store, image, voice, omni = _store(), FakeSeedream(), FakeSpeech(), FakeOmniHuman()
    producer = _presenter(store, seedream=image, speech=voice, omni=omni, links=FakeLinks())
    _rows(producer, store)
    brief = _presenter_brief(brand_logo_key=LOGO, brand_logo_in_scene=True)
    frozen = producer.prepare_brand_references(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit()
    )
    legacy = frozen.model_copy(
        update={
            "block_version": 1,
            "refs": tuple(
                ref.model_copy(update={"asset_kind": "", "asset_slot": "", "selected_logo": False})
                for ref in frozen.refs
            ),
        }
    )
    result = producer.produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=brief,
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
        brand_references=legacy,
    )
    assert result.failure is None, result.detail
    assert omni.requests[0].params["prompt"] == media_module.motion_prompt(brief=brief, products=0)

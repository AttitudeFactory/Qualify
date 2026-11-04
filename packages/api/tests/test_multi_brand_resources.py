"""Offline behavior for multiple selected logo variants; never calls paid vendors."""

from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError
from qualify_creative.brand.render import _chosen_resources
from qualify_creative.enums import ContentKind, SlideSource
from qualify_creative.schemas import BrandContext, BrandElement, CarouselSlide, MediaInputs

from qualify_api.creative.brand_kit_store import BrandAsset
from qualify_api.creative.brand_references import resolve_brand_references

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
    _brief,
    _image,
    _kit,
    _presenter,
    _presenter_brief,
    _producer,
    _seedance_brief,
    _store,
)
from .test_creative_reel_edit import edit_brief
from .test_creative_seedance_video_input import VideoInputSeedance, _measured
from .test_creative_seedance_video_input import _producer as _edit_producer

A = f"t/{TENANT_ID}/brand/{BRAND_ID}/a.png"
B = f"t/{TENANT_ID}/brand/{BRAND_ID}/b.png"
C = f"t/{TENANT_ID}/brand/{BRAND_ID}/c.png"
EXTRA = f"t/{TENANT_ID}/brand/{BRAND_ID}/mascot.png"


def assets(producer: Any, store: Any) -> list[BrandAsset]:
    rows = [
        BrandAsset(
            "logo_version",
            "imagotipo",
            A,
            label="Principal",
            context="En la caja",
            content_type="image/png",
        ),
        BrandAsset(
            "logo_version",
            "isotipo",
            B,
            label="Simbolo",
            context="En el fondo",
            content_type="image/png",
        ),
        BrandAsset(
            "logo_version",
            "logotipo",
            C,
            label="Palabra",
            context="En el letrero",
            content_type="image/png",
        ),
        BrandAsset(
            "extra",
            "mascot",
            EXTRA,
            label="Mascota",
            context="Junto al producto",
            content_type="image/png",
        ),
    ]
    for i, key in enumerate([A, B, C, EXTRA]):
        store.files[key] = _image((30 + i * 25, 120, 180))
    producer._brand_assets = lambda tenant, brand: list(rows)
    return rows


def selection(**kwargs: Any) -> dict[str, Any]:
    return dict(
        brand_logo_key=A,
        brand_logo_in_scene=True,
        brand_logo_reference_keys=(B, C),
        brand_element_keys=(EXTRA,),
        **kwargs,
    )


def test_shared_distinct_allowance_and_incompatible_signature() -> None:
    media = MediaInputs(
        brand_logo_key=A,
        brand_logo_in_scene=True,
        brand_logo_reference_keys=(A, B, B, C),
        brand_element_keys=(C, EXTRA),
    )
    assert media.brand_logo_reference_keys == (A, B, C)
    with pytest.raises(ValidationError):
        MediaInputs(brand_logo_key=A, brand_logo_in_scene=False, brand_logo_reference_keys=(A,))
    with pytest.raises(ValidationError):
        MediaInputs(
            brand_logo_reference_keys=tuple(f"logo{i}" for i in range(4)),
            brand_element_keys=tuple(f"extra{i}" for i in range(3)),
        )
    assert (
        len(
            MediaInputs(
                brand_logo_key=A, brand_logo_reference_keys=tuple(f"l{i}" for i in range(6))
            ).brand_logo_reference_keys
        )
        == 6
    )
    old = MediaInputs.model_validate({"brand_logo_key": A, "brand_element_keys": [EXTRA]})
    assert old.brand_logo_reference_keys == ()


def test_resolver_order_dedup_and_one_replacement_authority() -> None:
    producer = _producer(_store())
    assets(producer, producer._store)
    refs = resolve_brand_references(
        producer._brand_assets,
        tenant_id=TENANT_ID,
        brand_id=BRAND_ID,
        brand_logo_key=A,
        brand_element_keys=(EXTRA, B),
        brand_logo_reference_keys=(B, C, B),
        logo_in_scene=True,
    )
    assert [r.asset_key for r in refs.refs] == [EXTRA, B, A, C]
    assert [r.asset_key for r in refs.refs if r.selected_logo] == [A]
    assert [(r.asset_kind, r.asset_slot) for r in refs.refs] == [
        ("extra", "mascot"),
        ("logo_version", "isotipo"),
        ("logo_version", "imagotipo"),
        ("logo_version", "logotipo"),
    ]
    secondary = resolve_brand_references(
        producer._brand_assets,
        tenant_id=TENANT_ID,
        brand_id=BRAND_ID,
        brand_logo_key=A,
        brand_element_keys=(),
        brand_logo_reference_keys=(C, B),
    )
    assert secondary.overlay.asset_key == A
    assert [r.asset_key for r in secondary.refs if r.selected_logo] == [C]


def test_secondary_resources_copy_keeps_every_note_once() -> None:
    brief = _brief(ContentKind.STATIC_FLYER, **selection())
    context = BrandContext(
        elements=tuple(
            BrandElement(name=name, key=key, context=note)
            for key, name, note in [
                (A, "Principal", "En la caja"),
                (B, "Simbolo", "En el fondo"),
                (C, "Palabra", "En el letrero"),
                (EXTRA, "Mascota", "Junto al producto"),
            ]
        )
    )
    text = " ".join(_chosen_resources(brief, context))
    for note in ["En la caja", "En el fondo", "En el letrero", "Junto al producto"]:
        assert text.count(note) == 1


def test_template_accepts_logo_candidates_for_semantic_slot_selection() -> None:
    brief = _brief(
        ContentKind.TEMPLATE,
        product_keys=(f"uploads/{TENANT_ID}/p1.jpg",),
        brand_logo_reference_keys=(B,),
    )
    assert brief.media.brand_logo_reference_keys == (B,)


@pytest.mark.parametrize(
    "route", ["flyer", "gallery", "gallery_motion", "clip", "edit", "human", "animated", "omni"]
)
@pytest.mark.parametrize("long_label", [False, True])
def test_actual_producers_keep_multiple_logo_categories_and_extra(
    route: str, monkeypatch: pytest.MonkeyPatch, long_label: bool
) -> None:
    image, video, speech, omni = FakeSeedream(), FakeSeedance(), FakeSpeech(), FakeOmniHuman()
    store = _store()
    if route == "edit":
        _measured(monkeypatch, 5)
        monkeypatch.setattr("qualify_api.creative.media._video_dimensions", lambda data: (480, 854))
        video = VideoInputSeedance()
        producer = _edit_producer(video)
        store = producer._store
        brief = edit_brief(**selection())
    elif route == "clip":
        producer = _clip_producer(store, video)
        brief = _brief(
            ContentKind.CLIP, clip_image_keys=(f"uploads/{TENANT_ID}/p1.jpg",), **selection()
        )
    elif route == "omni":
        producer = _presenter(store, seedream=image, speech=speech, omni=omni, links=FakeLinks())
        brief = _presenter_brief(**selection())
    else:
        producer = _producer(store, seedream=image, seedance=video)
        producer._fitter = FakeFitter()
        if route == "flyer":
            brief = _brief(
                ContentKind.STATIC_FLYER,
                product_keys=(f"uploads/{TENANT_ID}/p1.jpg",),
                **selection(),
            )
        elif route.startswith("gallery"):
            brief = _brief(
                ContentKind.CAROUSEL,
                product_keys=(f"uploads/{TENANT_ID}/p1.jpg",),
                slides=(
                    CarouselSlide(
                        source=SlideSource.ANIMATED
                        if route == "gallery_motion"
                        else SlideSource.GENERATED,
                        product_index=0,
                    ),
                ),
                closing_slide=True,
                **selection(),
            )
        else:
            producer._seedance_model = REF_MODEL
            brief = _seedance_brief(**selection())
            if route == "animated":
                brief = brief.model_copy(update={"kind": ContentKind.ANIMATED_AVATAR_VIDEO})
    rows = assets(producer, store)
    if long_label:
        rows[2] = replace(rows[2], label="Gemini_Generated_Image_ya4q2hya4q2hya4q.jpg")
    outcome = producer.produce(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit(), copy=COPY, budget=BUDGET
    )
    assert outcome.failure is None, outcome.detail
    prompts = [
        str(r.params.get("prompt", "")) for vendor in [image, video, omni] for r in vendor.requests
    ]
    joined = " ".join(prompts)
    for note in ["En la caja", "En el fondo", "En el letrero", "Junto al producto"]:
        assert note in joined
    for category in ["imagotipo", "isotipo", "logotipo"]:
        assert category in joined
    snapshots = outcome.media[0].params["brand_references"]["refs"]
    assert len(snapshots) == 4
    assert {r["asset_key"] for r in snapshots} == {A, B, C, EXTRA}


@pytest.mark.parametrize("bad", ["foreign", "stock", "missing", "extra"])
def test_invalid_secondary_fails_before_object_read_or_vendor(bad: str) -> None:
    store, vendor = _store(), FakeSeedream()
    producer = _producer(store, seedream=vendor)
    assets(producer, store)
    key = {
        "foreign": f"t/{uuid4()}/brand/mark.png",
        "stock": f"t/{TENANT_ID}/stock/pixabay/a.jpg",
        "missing": f"t/{TENANT_ID}/brand/missing.png",
        "extra": EXTRA,
    }[bad]
    brief = _brief(ContentKind.STATIC_FLYER, brand_logo_reference_keys=(key,))
    store.read = lambda key: pytest.fail("Invalid secondary read media")
    result = producer.produce(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit(), copy=COPY, budget=BUDGET
    )
    assert result.failure and not vendor.requests


@pytest.mark.parametrize("route", ["flyer", "clip"])
@pytest.mark.parametrize("overflow", [False, True])
def test_secondary_logos_count_toward_vendor_family_limit(route: str, overflow: bool) -> None:
    store, image, video = _store(), FakeSeedream(), FakeSeedance()
    producer = (
        _producer(store, seedream=image) if route == "flyer" else _clip_producer(store, video)
    )
    assets(producer, store)
    if route == "flyer":
        brief = _brief(
            ContentKind.STATIC_FLYER,
            product_keys=(f"uploads/{TENANT_ID}/p1.jpg",) * 10,
            background_key=f"uploads/{TENANT_ID}/bg.jpg" if overflow else None,
            **selection(),
        )
    else:
        brief = _brief(
            ContentKind.CLIP,
            clip_image_keys=(f"uploads/{TENANT_ID}/p1.jpg",) * (6 if overflow else 5),
            **selection(),
        )
    if overflow:
        store.read = lambda key: pytest.fail("Over family limit read media")
    result = producer.produce(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit(), copy=COPY, budget=BUDGET
    )
    assert bool(result.failure) is overflow
    assert bool(image.requests or video.requests) is not overflow


def test_empty_secondary_tuple_keeps_single_logo_vendor_request_identical() -> None:
    requests = []
    draft = uuid4()
    for explicit in [False, True]:
        store, vendor = _store(), FakeSeedream()
        producer = _producer(store, seedream=vendor)
        assets(producer, store)
        params = {"brand_logo_key": A, "brand_logo_in_scene": True, "brand_element_keys": (EXTRA,)}
        if explicit:
            params["brand_logo_reference_keys"] = ()
        result = producer.produce(
            tenant_id=TENANT_ID,
            draft_id=draft,
            brief=_brief(ContentKind.STATIC_FLYER, **params),
            kit=_kit(),
            copy=COPY,
            budget=BUDGET,
        )
        assert result.failure is None
        requests.append(vendor.requests[0].params)
    assert requests[0] == requests[1]


def test_multiple_frozen_resources_replay_without_current_asset_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.creative import pipeline
    from qualify_api.creative.brand_references import read_brand_reference_images

    store = _store()
    producer = _producer(store)
    rows = assets(producer, store)
    brief = _brief(ContentKind.STATIC_FLYER, **selection())
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
        originals = [r.image for r in read_brand_reference_images(store.read, first.refs)]
        rows.clear()
        producer._brand_assets = lambda *args: pytest.fail("Replay consulted current assets")
        resumed = producer.prepare_brand_references(
            tenant_id=TENANT_ID, draft_id=run.draft_id, brief=brief, kit=_kit()
        )
        assert resumed.model_dump() == first.model_dump()
        assert [ref.asset_key for ref in resumed.refs if ref.additional_logo] == [B, C]
        assert [r.image for r in read_brand_reference_images(store.read, resumed.refs)] == originals
    finally:
        pipeline._preparation.reset(token)


def test_secondary_only_default_logo_is_not_also_stamped_locally() -> None:
    store, vendor = _store(), FakeSeedream()
    producer = _producer(store, seedream=vendor)
    assets(producer, store)
    calls = []
    original = producer._logo

    def logo(kit: Any, key: Any = None) -> Any:
        calls.append((kit.logo_asset_key, key))
        return original(kit, key)

    producer._logo = logo
    result = producer.produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=_brief(ContentKind.STATIC_FLYER, brand_logo_reference_keys=(A,)),
        kit=_kit().model_copy(update={"logo_asset_key": A}),
        copy=COPY,
        budget=BUDGET,
    )
    assert result.failure is None, result.detail
    assert calls == [(None, None)]
    assert len(vendor.requests[0].params["images"]) == 1


@pytest.mark.parametrize("route", ["flyer", "edit", "omni"])
def test_oversized_secondary_note_is_rejected_before_media_reads(
    route: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from qualify_api.creative.brand_references import BrandReferenceError

    store = _store()
    if route == "edit":
        producer = _edit_producer(VideoInputSeedance())
        store = producer._store
        brief = edit_brief(**selection())
    elif route == "omni":
        producer = _presenter(
            store,
            seedream=FakeSeedream(),
            speech=FakeSpeech(),
            omni=FakeOmniHuman(),
            links=FakeLinks(),
        )
        brief = _presenter_brief(**selection())
    else:
        producer = _producer(store, seedream=FakeSeedream())
        brief = _brief(ContentKind.STATIC_FLYER, **selection())
    rows = assets(producer, store)
    rows[1] = replace(rows[1], context="Mantener todo este recurso " * 1000)
    store.read = lambda key: pytest.fail("Oversized selection read media before preflight")
    with pytest.raises(BrandReferenceError, match="demasiado texto"):
        producer.prepare_brand_references(
            tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit()
        )


def test_legacy_primary_plus_six_extras_preserves_full_allowance() -> None:
    producer = _producer(_store())
    rows = assets(producer, producer._store)
    keys = tuple(f"t/{TENANT_ID}/brand/extra{i}.png" for i in range(6))
    rows.extend(BrandAsset("extra", "", key, content_type="image/png") for key in keys)
    selected = resolve_brand_references(
        producer._brand_assets,
        tenant_id=TENANT_ID,
        brand_id=BRAND_ID,
        brand_logo_key=A,
        brand_element_keys=keys,
        logo_in_scene=True,
    )
    assert len(selected.refs) == 7
    assert not any(ref.additional_logo for ref in selected.refs)

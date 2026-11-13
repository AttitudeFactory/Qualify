"""m-25017279 (ADR 49 §2 item 1): the raw Seedream photograph of the advertising image and
of every GENERATED gallery slide is kept under the piece's `base/` folder the moment it is
paid for, and travels on the still it made (`MediaWrite.base`) — never as an output of its
own. An animated slide's first frame is not a base. A base R2 refuses does not fail the
paid piece. The stills, their order and their files are unchanged."""

from __future__ import annotations

import hashlib
from uuid import uuid4

from qualify_creative.enums import SlideSource

from qualify_api.creative.brand_references import BrandReferencesSet
from qualify_api.creative.media import (
    BasePhoto,
    MediaWrite,
    _media_write_from_json,
    _media_write_json,
)

from .test_creative_media_byteplus import BUDGET, COPY, TENANT_ID, FakeSeedance, _kit
from .test_v9_flyer_consumer import (  # noqa: F401 - `no_generation` is autouse
    PHOTO,
    SimulatedFitter,
    gallery_setup,
    no_generation,
    run_flyer,
)


def _produce(producer, brief):  # noqa: ANN001, ANN202
    return producer.produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=brief,
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
        brand_references=BrandReferencesSet(block_version=9),
    )


def test_each_flyer_slide_carries_its_kept_base(monkeypatch) -> None:
    outcome, requests = run_flyer(monkeypatch, count=3)
    assert outcome.failure is None, outcome.detail
    assert len(outcome.media) == 3  # the stills only: no base is an output
    for index, (write, request) in enumerate(zip(outcome.media, requests, strict=True)):
        base = write.base
        assert base is not None
        assert base.key.endswith(f"/base/flyer-{index + 1}.jpg")
        assert base.sha256 == hashlib.sha256(PHOTO).hexdigest()
        assert base.rendered_prompt == request.params["prompt"]
        assert base.prompt_compiler_version == 0  # the fixture brief's own stamp
        assert base.key != write.object_key
        assert write.params["base_key"] == base.key
        assert write.params["base_sha256"] == base.sha256


def test_each_generated_gallery_slide_carries_its_kept_base(monkeypatch) -> None:
    producer, brief, vendor = gallery_setup(monkeypatch)
    outcome = _produce(producer, brief)
    assert outcome.failure is None, outcome.detail
    assert len(outcome.media) == 2
    for number, (write, request) in enumerate(
        zip(outcome.media, vendor.requests, strict=True), start=1
    ):
        assert write.base is not None
        assert write.base.key.endswith(f"/base/slide-{number}.jpg")
        assert write.base.rendered_prompt == request.params["prompt"]
        # the bytes kept are the bytes the still was composed over
        kept = producer._store.files[write.base.key]
        assert hashlib.sha256(kept).hexdigest() == write.base.sha256


def test_an_animated_slide_keeps_no_base(monkeypatch) -> None:
    producer, brief, _ = gallery_setup(monkeypatch)
    producer._router._providers["seedance"] = FakeSeedance()
    producer._fitter = SimulatedFitter()
    slides = tuple(
        slide.model_copy(update={"source": SlideSource.ANIMATED}) for slide in brief.media.slides
    )
    brief = brief.model_copy(update={"media": brief.media.model_copy(update={"slides": slides})})
    outcome = _produce(producer, brief)
    assert outcome.failure is None, outcome.detail
    assert all(write.base is None for write in outcome.media)
    assert not [key for key in producer._store.files if "/base/" in key]


def test_a_base_r2_refuses_never_fails_the_paid_piece(monkeypatch) -> None:
    producer, brief, _ = gallery_setup(monkeypatch)
    store = producer._store

    def keep(tenant_id, key, data, content_type):  # noqa: ANN001, ANN202
        if "/base/" in key:
            return False
        store.files[key] = data
        return True

    store.keep = keep
    outcome = _produce(producer, brief)
    assert outcome.failure is None, outcome.detail
    assert len(outcome.media) == 2
    assert all(write.base is None for write in outcome.media)
    assert all("base_key" not in write.params for write in outcome.media)


def test_a_resumed_gallery_keeps_each_slide_base() -> None:
    """«Crear las que faltan» / a queue resume: a slide kept with its vendor task comes back
    with its base, so the base is neither made nor stored twice."""
    base = BasePhoto(
        key="t/x/generated/d/r1/base/slide-1.jpg",
        sha256="a" * 64,
        content_type="image/jpeg",
        model_id="seedream-5-0",
        provider="seedream",
        rendered_prompt="Create one professional advertising photograph",
        prompt_compiler_version=5,
    )
    kept = MediaWrite(
        position=0,
        media_type="image",
        media_url="t/x/generated/d/r1/slide-1.jpg",
        object_key="t/x/generated/d/r1/slide-1.jpg",
        width=1080,
        height=1350,
        aspect_ratio="4:5",
        model_id="seedream-5-0",
        provider="seedream",
        params={"source": "generated", "base_key": base.key},
        content_type="image/jpeg",
        ai_generated=True,
        rendered_prompt=base.rendered_prompt,
        base=base,
    )
    assert _media_write_from_json(_media_write_json(kept)) == kept

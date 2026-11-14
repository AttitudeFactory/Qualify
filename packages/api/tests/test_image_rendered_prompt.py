"""m-25017278: the compiled Seedream prompt of every generated image is stored as its
provenance (`MediaWrite.rendered_prompt` → `image_assets.rendered_prompt`) — the
advertising image, its 9:16 Reel, and each generated gallery slide, which had none before.
The prompt itself is unchanged: what is stored is exactly what the vendor was sent."""

from __future__ import annotations

from uuid import uuid4

from qualify_creative.enums import ContentFormat, ContentKind
from qualify_creative.video import FittedVideo

from qualify_api.creative.brand_references import BrandReferencesSet
from qualify_api.creative.media import (
    MediaWrite,
    _media_write_from_json,
    _media_write_json,
)

from .test_creative_media_byteplus import BUDGET, COPY, TENANT_ID, MemoryStore, _brief, _kit
from .test_creative_media_byteplus import _producer as _make_producer
from .test_v9_flyer_consumer import (  # noqa: F401 - `no_generation` is autouse
    PHOTO,
    Capture,
    TextStyle,
    gallery_setup,
    no_generation,
    run_flyer,
)


def test_each_flyer_slide_stores_the_prompt_its_scene_was_made_with(monkeypatch) -> None:
    outcome, requests = run_flyer(monkeypatch, count=3)
    assert outcome.failure is None, outcome.detail
    assert len(requests) == len(outcome.media) == 3
    for write, request in zip(outcome.media, requests, strict=True):
        assert write.rendered_prompt == request.params["prompt"]


def test_the_flyer_reel_stores_its_scene_prompt(monkeypatch) -> None:
    keys = tuple(f"uploads/{TENANT_ID}/reel{i}.jpg" for i in range(2))
    vendor = Capture()
    producer = _make_producer(MemoryStore(dict.fromkeys(keys, PHOTO)), seedream=vendor)
    monkeypatch.setattr(producer, "_text_style", lambda *args: TextStyle())

    class Animator:
        def animate_still(self, still, *, size):  # noqa: ANN001, ANN202
            return FittedVideo(
                data=b"simulated", width=size[0], height=size[1], duration_sec=5, poster=PHOTO
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
    (write,) = outcome.media
    assert write.rendered_prompt == vendor.requests[0].params["prompt"]


def test_each_generated_gallery_slide_stores_its_prompt(monkeypatch) -> None:
    producer, brief, vendor = gallery_setup(monkeypatch)
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
    assert len(vendor.requests) == len(outcome.media) == 2
    for write, request in zip(outcome.media, vendor.requests, strict=True):
        assert write.rendered_prompt == request.params["prompt"]
        assert write.rendered_prompt  # never an empty provenance


def _write(**over: object) -> MediaWrite:
    values: dict = {
        "position": 1,
        "media_type": "image",
        "media_url": "t/x/generated/d/slide-2.jpg",
        "object_key": "t/x/generated/d/slide-2.jpg",
        "width": 1080,
        "height": 1350,
        "aspect_ratio": "4:5",
        "model_id": "seedream-5-0",
        "provider": "seedream",
        "params": {"source": "generated"},
        "content_type": "image/jpeg",
        "ai_generated": True,
    }
    return MediaWrite(**{**values, **over})


def test_a_resumed_gallery_keeps_each_kept_slide_prompt() -> None:
    """«Crear las que faltan»: the slides kept with a vendor task come back with theirs."""
    kept = _write(rendered_prompt="Create one professional advertising photograph")
    assert _media_write_from_json(_media_write_json(kept)) == kept


def test_a_slide_kept_before_this_change_reads_back_without_a_prompt() -> None:
    """A task context saved before m-25017278 has no prompt key: unchanged, None."""
    plain = _write()
    assert "rendered_prompt" not in _media_write_json(plain)
    assert _media_write_from_json(_media_write_json(plain)) == plain

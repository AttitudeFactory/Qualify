"""A gallery slide's Seedream scene at prompt compiler 3 (draft 97f35052, 2026-11-03).

The founder's 3-slide gallery (4:5; slide 1 product + Inspiración guide, slide 2 animated,
slide 3 product; a «Fondo común» on every slide; the isologo) came back with: a blank band
at the bottom of slide 1 (the scene obeyed «keep the bottom fifth calm» with a flat white
band, the scrim darkened it to grey); the common background — a stock street photo — called
«the client's real place; preserve its identity», so its foreign shop sign was preserved;
slide 3 on the product photo's white studio instead of the common background; slide 2 a
flat brand card with the request's «dale clic al link de WhatsApp» drawn as lettering.

Offline contracts: the frozen compiler-2 prompts stay byte for byte (the three prompts the
draft was paid with are the fixture); compiler 3 passes `assert_image_prompt_v3_quality`;
a blank band a vendor leaves is trimmed before anything is composed over it."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from PIL import Image, ImageDraw
from qualify_creative.enums import AdImageMode, ContentKind, SlideSource, SlideText
from qualify_creative.photo.bands import blank_bands, fill_blank_bands
from qualify_creative.providers import GenerationRequest, GenerationResult, Usage
from qualify_creative.scene_plan import carousel_scene_plans
from qualify_creative.schemas import BrandKit, CarouselSlide, ContentBrief, ToneAxes

from qualify_api.creative.brand_references import BrandReference
from qualify_api.creative.image_pipeline import base as base_stage
from qualify_api.creative.media import (
    MEDIA_PROMPT_BUDGET,
    PROMPT_COMPILER_VERSION,
    carousel_scene_prompt,
)

from .prompt_quality import assert_image_prompt_v3_quality
from .test_creative_media_byteplus import (
    BUDGET,
    SEEDREAM_MODEL,
    TENANT_ID,
    FakeSeedance,
    FakeSeedream,
    _brief,
    _produce,
    _producer,
    _seedance_brief,
    _store,
)

_FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "gallery_scene_v2_draft_97f35052_anonymized.json"
)
FIXTURE = json.loads(_FIXTURE_PATH.read_text(encoding="utf8"))
T = "00000000-0000-0000-0000-000000000001"
#: The anonymized inputs of draft 97f35052 (brand, topic and palette invented).
TOPIC: str = FIXTURE["topic"]
PALETTE: tuple[str, ...] = tuple(FIXTURE["palette"])
BRAND: str = FIXTURE["brand"]


def _kit() -> BrandKit:
    return BrandKit(
        brand_id=uuid4(),
        positioning="Smash burgers",
        audience="Jóvenes",
        tone_axes=ToneAxes(
            formal_casual=70, sober_enthusiastic=60, technical_plain=80, brief_elaborate=30
        ),
        palette_rgb=PALETTE,
        font_heading="Baloo 2",
        font_body="Nunito",
    )


def _isologo() -> BrandReference:
    return BrandReference.model_validate(
        {
            "rol": "elemento_de_marca",
            "note": "",
            "label": "Isologo",
            "asset_key": f"t/{T}/brand/b/logo_version/isologo/l.jpg",
            "asset_kind": "logo_version",
            "asset_slot": "isologo",
            "fingerprint": "f" * 64,
            "content_type": "image/jpeg",
            "snapshot_key": f"t/{T}/generated/d/r1/brand-reference.img",
            "selected_logo": True,
            "additional_logo": False,
            "instruction_version": 9,
        }
    )


def _gallery(version: int, *, topic: str = TOPIC, **media: Any) -> ContentBrief:
    """Draft 97f35052's shape: guide + two catalog photos, a stock common background."""
    base: dict[str, Any] = {
        "slides": [
            {
                "text": "hook",
                "source": "generated",
                "product_index": 0,
                "use_background": True,
                "guide_product_index": 1,
            },
            {"text": "none", "source": "animated", "product_index": 1, "use_background": True},
            {"text": "none", "source": "generated", "product_index": 2, "use_background": True},
        ],
        "product_keys": [
            f"t/{T}/stock/pixabay/8743802/guia.jpg",
            f"uploads/{T}/catalog/p/foto1.jpg",
            f"uploads/{T}/catalog/p/foto2.jpg",
        ],
        "product_image_roles": ["composition", "product", "product"],
        "background_key": f"t/{T}/stock/pixabay/2014618/calle.jpg",
        "brand_logo_key": f"t/{T}/brand/b/logo_version/isologo/l.jpg",
        "brand_logo_in_scene": True,
        "brand_application_version": 2,
        "prompt_compiler_version": version,
    }
    base.update(media)
    return ContentBrief.model_validate(
        {
            "brand_id": str(uuid4()),
            "objective": "consideration",
            "topic": topic,
            "product_ref": "producto XY",
            "kind": "carousel",
            "format": "feed_4_5",
            "image_route": "from_upload",
            "source_media_key": f"uploads/{T}/catalog/p/foto1.jpg",
            "media": base,
        }
    )


def _prompts(
    brief: ContentBrief, refs: tuple[BrandReference, ...] = (), *, new_args: bool = True
) -> list[str]:
    """Each slide's scene prompt, as `_carousel_slides` compiles it."""
    plans = {p.output_index: p for p in carousel_scene_plans(brief.media)}
    out = []
    total = len(brief.media.slides)
    for position, slide in enumerate(brief.media.slides):
        animated = slide.source.value == "animated"
        kwargs: dict[str, Any] = {
            "brief": brief,
            "kit": _kit(),
            "brand": BRAND,
            "scene": slide.scene_prompt,
            "ratio": "3:4" if animated else "4:5",
            "has_product": slide.product_index is not None,
            "product_role": brief.media.product_image_roles[slide.product_index]
            if slide.product_index is not None
            else "product",
            "has_background": slide.use_background,
            "has_text": slide.text.value != "none",
            "brand_refs": refs,
            "scene_plan": plans.get(position),
        }
        if new_args:
            kwargs.update(
                hook=slide.text.value == "hook",
                cta=slide.text.value == "cta",
                slide_number=position + 1,
                slides=total,
                animated=animated,
            )
        out.append(carousel_scene_prompt(**kwargs))
    return out


# -- frozen compilers ------------------------------------------------------------------------


def test_compiler_2_gallery_scenes_are_byte_for_byte_what_draft_97f35052_paid_for() -> None:
    assert _prompts(_gallery(2), (_isologo(),)) == FIXTURE["prompts"]


@pytest.mark.parametrize("version", [0, 1, 2])
def test_frozen_compilers_ignore_the_compiler_3_arguments(version: int) -> None:
    for refs in ((), (_isologo(),)):
        brief = _gallery(version)
        assert _prompts(brief, refs) == _prompts(brief, refs, new_args=False)


def test_a_new_execution_is_stamped_with_compiler_4_or_later() -> None:
    assert PROMPT_COMPILER_VERSION >= 4  # 5: m-24985141


# -- compiler 3 ------------------------------------------------------------------------------


def test_compiler_3_draft_97f35052_passes_the_image_quality_guard() -> None:
    brief, refs = _gallery(3), (_isologo(),)
    first, animated, last = _prompts(brief, refs)
    assert_image_prompt_v3_quality(
        first, brief=brief, kit=_kit(), refs=refs, base_index=4, products=[1], guides=[2], place=3
    )
    for prompt in (animated, last):
        assert_image_prompt_v3_quality(
            prompt, brief=brief, kit=_kit(), refs=refs, base_index=3, products=[1], place=2
        )
    assert "slide 1 of 3" in first and "slide 3 of 3" in last
    assert "first frame of a short video" in animated
    assert "first frame" not in first + last
    # the headline is laid over slide 1 only; nothing reserves a band at the bottom
    assert "top quarter" in first and "top quarter" not in animated + last
    assert "bottom fifth" not in first + animated + last


def test_compiler_3_without_a_logo_forbids_drawing_one() -> None:
    brief = _gallery(3)
    for prompt in _prompts(brief):
        assert "No logo image is supplied" in prompt
    first = _prompts(brief)[0]
    assert_image_prompt_v3_quality(
        first, brief=brief, kit=_kit(), refs=(), base_index=4, products=[1], guides=[2], place=3
    )


def test_compiler_3_a_slide_without_a_product_shows_its_background_only() -> None:
    brief = _gallery(
        3,
        slides=[
            {"text": "cta", "source": "generated", "product_index": None, "use_background": True},
            {"text": "none", "source": "generated", "product_index": 0, "use_background": True},
        ],
        product_keys=[f"uploads/{T}/catalog/p/foto1.jpg"],
        product_image_roles=["product"],
    )
    prompt = _prompts(brief, (_isologo(),))[0]
    assert_image_prompt_v3_quality(
        prompt, brief=brief, kit=_kit(), refs=(_isologo(),), base_index=2, place=1
    )
    assert "This slide shows set in" not in prompt
    assert "A button is laid over the bottom fifth" in prompt


def test_compiler_3_the_operators_scene_for_a_slide_travels_literal() -> None:
    scene = "El producto XY recién cortado, mostrando lo jugoso que queda por dentro."
    brief = _gallery(
        3,
        slides=[
            {
                "text": "none",
                "source": "generated",
                "product_index": 0,
                "use_background": True,
                "scene_prompt": scene,
            },
            {"text": "none", "source": "generated", "product_index": 0, "use_background": True},
        ],
        product_keys=[f"uploads/{T}/catalog/p/foto1.jpg"],
        product_image_roles=["product"],
    )
    prompt = _prompts(brief, (_isologo(),))[0]
    assert f'What this slide shows (the operator\'s words, in Spanish): "{scene}"' in prompt
    assert_image_prompt_v3_quality(
        prompt,
        brief=brief,
        kit=_kit(),
        refs=(_isologo(),),
        base_index=3,
        products=[1],
        place=2,
        scene=scene,
    )


def test_compiler_3_a_long_request_is_trimmed_as_context_never_refused() -> None:
    brief = _gallery(3, topic=("Galería nocturna con antojo y costra crujiente. " * 80).strip())
    for prompt in _prompts(brief, (_isologo(),)):
        assert len(prompt) <= MEDIA_PROMPT_BUDGET
        assert "do not write any of its words in the image" in prompt


# -- blank bands -----------------------------------------------------------------------------


def _photo(size: tuple[int, int] = (640, 800), seed: int = 0) -> Image.Image:
    """A busy synthetic «photograph»: noise plus a few shapes."""
    image = Image.effect_noise(size, 60).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.ellipse(
        (size[0] // 4, size[1] // 3, size[0] * 3 // 4, size[1] * 2 // 3), fill=(150, 80, 30)
    )
    return image


def _bytes(image: Image.Image, fmt: str = "JPEG") -> bytes:
    out = io.BytesIO()
    image.save(out, format=fmt, quality=92) if fmt == "JPEG" else image.save(out, format=fmt)
    return out.getvalue()


def _banded(top: int = 0, bottom: int = 0, tone: int = 252) -> bytes:
    image = _photo()
    draw = ImageDraw.Draw(image)
    width, height = image.size
    if top:
        draw.rectangle((0, 0, width, top - 1), fill=(tone, tone, tone))
    if bottom:
        draw.rectangle((0, height - bottom, width, height), fill=(tone, tone, tone))
    return _bytes(image)


def test_a_blank_bottom_band_is_found_and_trimmed_to_a_full_frame() -> None:
    data = _banded(bottom=132)  # ~16.5 %, as slide 1 of draft 97f35052
    top, bottom = blank_bands(data)
    assert top == 0 and 125 <= bottom <= 136
    filled = fill_blank_bands(data)
    image = Image.open(io.BytesIO(filled))
    assert image.size == (640, 800)
    assert blank_bands(filled) == (0, 0)
    strip = image.convert("L").crop((0, 760, 640, 800))
    assert max(strip.tobytes()) - min(strip.tobytes()) > 60  # photograph, not a flat band


def test_blank_bands_at_top_and_dark_ones_are_trimmed_too() -> None:
    assert blank_bands(_banded(top=100, bottom=60, tone=8))[0] >= 95


def test_a_studio_sweep_with_the_product_on_it_is_not_a_band() -> None:
    """A product on a white seamless backdrop (slide 3 of the draft): the floor is flat, but
    the row above it is still mostly backdrop — no hard edge across the width."""
    image = Image.new("RGB", (640, 800), (250, 246, 240))
    ImageDraw.Draw(image).ellipse((160, 250, 480, 620), fill=(160, 90, 40))
    data = _bytes(image)
    assert blank_bands(data) == (0, 0)
    assert fill_blank_bands(data) is data


def test_unreadable_flat_or_mostly_blank_images_are_left_alone() -> None:
    flat = _bytes(Image.new("RGB", (640, 800), (200, 30, 30)))
    assert fill_blank_bands(flat) is flat
    assert fill_blank_bands(b"not an image") == b"not an image"
    half = _banded(bottom=400)  # 50 %: a design choice, not a defect
    assert blank_bands(half) == (0, 0)
    tiny = _banded(bottom=16)  # 2 %: compression noise at an edge
    assert blank_bands(tiny) == (0, 0)


class BandedSeedream(FakeSeedream):
    def generate(self, request: GenerationRequest, *, api_key: str) -> GenerationResult:
        self.keys.append(api_key)
        self.requests.append(request)
        return GenerationResult(
            payload={"images": [_banded(bottom=132)]},
            model_id=SEEDREAM_MODEL,
            provider="seedream",
            usage=Usage(pieces=1),
        )


def _recording_bands(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []

    def record(data: bytes) -> bytes:
        calls.append(len(data))
        return fill_blank_bands(data)

    monkeypatch.setattr(base_stage, "fill_blank_bands", record)
    return calls


def _banded_gallery(version: int) -> ContentBrief:
    return _brief(
        ContentKind.CAROUSEL,
        product_keys=(f"uploads/{TENANT_ID}/p1.jpg",),
        slides=(
            CarouselSlide(source=SlideSource.GENERATED, product_index=0, text=SlideText.HOOK),
            CarouselSlide(source=SlideSource.GENERATED, text=SlideText.CTA),
        ),
        prompt_compiler_version=version,
    )


def test_only_a_compiler_3_gallery_slide_has_its_blank_bands_filled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review #5: the band trim is for gallery scenes from compiler 3 on. A flyer, a talking
    video's first frame and a gallery compiled earlier come back exactly as made."""
    calls = _recording_bands(monkeypatch)
    flyer = _brief(
        ContentKind.STATIC_FLYER,
        ad_mode=AdImageMode.PRODUCT,
        product_keys=(f"uploads/{TENANT_ID}/p1.jpg",),
    )
    assert _produce(_producer(_store(), seedream=BandedSeedream()), flyer, uuid4()).failure is None
    talking = _producer(_store(), seedream=BandedSeedream(), seedance=FakeSeedance())
    assert _produce(talking, _seedance_brief(), uuid4()).failure is None
    old = _producer(_store(), seedream=BandedSeedream())
    assert _produce(old, _banded_gallery(2), uuid4()).failure is None
    assert calls == []

    new = _producer(_store(), seedream=BandedSeedream())
    assert _produce(new, _banded_gallery(3), uuid4()).failure is None
    assert len(calls) == 2  # one per generated slide


def test_a_scene_image_is_returned_as_made_unless_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every route but the compiler-3 gallery (incl. the presenter's photo) calls
    `_scene_image` without `fill_bands`: the vendor's bytes, untouched."""
    banded = _banded(bottom=132)

    class FixedBanded(BandedSeedream):
        def generate(self, request: GenerationRequest, *, api_key: str) -> GenerationResult:
            return GenerationResult(
                payload={"images": [banded]},
                model_id=SEEDREAM_MODEL,
                provider="seedream",
                usage=Usage(pieces=1),
            )

    producer = _producer(_store(), seedream=FixedBanded())
    common: dict[str, Any] = {
        "tenant_id": TENANT_ID,
        "draft_id": uuid4(),
        "brand_id": uuid4(),
        "prompt": "a presenter",
        "references": [],
        "ratio": "4:5",
        "budget": BUDGET,
        "usage": [],
        "what": "foto del presentador",
    }
    assert producer._scene_image(**common) == banded
    filled = producer._scene_image(**common, fill_bands=True)
    assert filled != banded and blank_bands(filled) == (0, 0)

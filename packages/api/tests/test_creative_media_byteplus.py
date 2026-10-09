"""`MediaProducer` over BytePlus ModelArk (§ request 2026-10-07), without the network:
the advertising image's scene by Seedream with the operator's photos as references, and
the avatar videos on `VideoEngine.SEEDANCE` — Seedream's first frame animated by
Seedance. Both vendors are scripted fakes run by the real `CreativeRouter`; pricing is the
real v3 table, so the recorded costs are the real rates."""

from __future__ import annotations

import io
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from PIL import Image
from pydantic import ValidationError
from qualify_creative.enums import (
    AdImageMode,
    AvatarSource,
    BriefObjective,
    ContentFormat,
    ContentKind,
    FailureReason,
    GenerationTask,
    ImageRoute,
    PaidBy,
    VideoEngine,
)
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.providers import GenerationRequest, GenerationResult, ResolvedKey, Usage
from qualify_creative.router import BudgetContext, CreativeRouter
from qualify_creative.schemas import BrandKit, ContentBrief, CopyPayload, MediaInputs, ToneAxes

from qualify_api.creative.media import (
    MediaProducer,
    ark_failure_text,
    generated_key,
)

TENANT_ID = UUID("7e7e0000-0000-4000-8000-000000000011")
BRAND_ID = UUID("7e7e0000-0000-4000-8000-000000000012")
BUDGET = BudgetContext(remaining_usd=Decimal("100"))
COPY = CopyPayload(
    hook="Smash doble",
    caption="La smash más jugosa del barrio.",
    cta="Pide ya por DM",
    script="Hola. Esta es la smash doble. Pídela hoy.",
)
SEEDREAM_MODEL = "seedream-5-0-lite-260128"
SEEDANCE_MODEL = "seedance-1-0-pro-250528"


def _image(
    color: tuple[int, int, int] = (200, 40, 40), size: tuple[int, int] = (400, 500)
) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format="JPEG")
    return out.getvalue()


class MemoryStore:
    def __init__(self, files: dict[str, bytes] | None = None) -> None:
        self.files = dict(files or {})

    def read(self, key: str) -> bytes:
        if key not in self.files:
            raise FileNotFoundError(key)
        return self.files[key]

    def write(self, key: str, data: bytes) -> None:
        self.files[key] = data


class FakeSeedream:
    name = "seedream"
    supports = frozenset({GenerationTask.PRODUCT_IMAGE})

    def __init__(self) -> None:
        self.requests: list[GenerationRequest] = []
        self.keys: list[str] = []

    def generate(self, request: GenerationRequest, *, api_key: str) -> GenerationResult:
        self.keys.append(api_key)
        self.requests.append(request)
        return GenerationResult(
            payload={"images": [_image((30, 120, 200), (1728, 2160))]},
            model_id=SEEDREAM_MODEL,
            provider="seedream",
            usage=Usage(pieces=1),
        )

    def estimate_cost_usd(self, request: GenerationRequest, pricing: Any, **_: Any) -> Decimal:
        return Decimal("0.035")


class FakeSeedance:
    name = "seedance"
    supports = frozenset({GenerationTask.SCENE_VIDEO})

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.requests: list[GenerationRequest] = []
        self.keys: list[str] = []

    def generate(self, request: GenerationRequest, *, api_key: str) -> GenerationResult:
        self.keys.append(api_key)
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("ArkTaskFailed: OutputVideoSensitiveContentDetected")
        return GenerationResult(
            payload={
                "task_id": "cgt-1",
                "video_url": "https://ark/v.mp4",
                "duration_seconds": "5",
                "resolution": "720p",
                "generate_audio": False,
            },
            model_id=SEEDANCE_MODEL,
            provider="seedance",
            usage=Usage(pieces=1, media_seconds=Decimal(5), output_tokens=102960),
            model_revision=SEEDANCE_MODEL,
            media_url="https://ark/v.mp4",
            media_expires_at_seconds=86400,
        )

    def estimate_cost_usd(self, request: GenerationRequest, pricing: Any, **_: Any) -> Decimal:
        return Decimal("0.26")


class KeysByProvider:
    def resolve(self, *, tenant_id: UUID, brand_id: UUID, provider: str) -> ResolvedKey:
        return ResolvedKey(api_key=f"key-{provider}", paid_by=PaidBy.PLATFORM, fingerprint="fp")


class NoArkKey:
    def resolve(self, *, tenant_id: UUID, brand_id: UUID, provider: str) -> ResolvedKey:
        raise RuntimeError("QUALIFY_BYTEPLUS_ARK_API_KEY is not set")


def _kit() -> BrandKit:
    return BrandKit(
        brand_id=BRAND_ID,
        positioning="Smash burgers",
        audience="Jóvenes",
        tone_axes=ToneAxes(
            formal_casual=70, sober_enthusiastic=60, technical_plain=80, brief_elaborate=30
        ),
        palette_rgb=("#C4622D", "#F5C518"),
    )


def _brief(kind: ContentKind, fmt: ContentFormat | None = None, **media: object) -> ContentBrief:
    return ContentBrief(
        brand_id=BRAND_ID,
        objective=BriefObjective.SALE,
        topic="Smash doble con papas",
        image_route=ImageRoute.TEMPLATE_ONLY,
        kind=kind,
        format=fmt or kind.default_format,
        media=MediaInputs(**media),  # type: ignore[arg-type]
    )


def _producer(
    store: MemoryStore,
    *,
    seedream: FakeSeedream | None = None,
    seedance: FakeSeedance | None = None,
    credentials: Any = None,
) -> MediaProducer:
    pricing = JsonPricingTable("v3")
    providers: dict[str, Any] = {}
    if seedream is not None:
        providers["seedream"] = seedream
    if seedance is not None:
        providers["seedance"] = seedance
    router = CreativeRouter(providers, pricing, credentials or KeysByProvider())

    def download(url: str) -> bytes:
        return b"mp4-bytes"

    return MediaProducer(
        store=store,
        router=router,
        credentials=KeysByProvider(),
        pricing=pricing,
        heygen=None,
        download=download,
        generated_ad_images=True,
    )


def _produce(producer: MediaProducer, brief: ContentBrief, draft_id: UUID) -> Any:
    return producer.produce(
        tenant_id=TENANT_ID, draft_id=draft_id, brief=brief, kit=_kit(), copy=COPY, budget=BUDGET
    )


def _store() -> MemoryStore:
    return MemoryStore(
        {
            f"uploads/{TENANT_ID}/p1.jpg": _image(),
            f"uploads/{TENANT_ID}/p2.jpg": _image((10, 200, 10)),
            f"uploads/{TENANT_ID}/p3.jpg": _image((10, 10, 200)),
            f"uploads/{TENANT_ID}/bg.jpg": _image((90, 60, 30), (800, 600)),
            f"uploads/{TENANT_ID}/mascota.png": _image((250, 200, 0)),
        }
    )


# -- the advertising image --------------------------------------------------------------


def test_the_ad_image_scene_is_generated_with_the_operators_photos_as_references() -> None:
    store, seedream, draft_id = _store(), FakeSeedream(), uuid4()
    brief = _brief(
        ContentKind.STATIC_FLYER,
        ad_mode=AdImageMode.BOTH,
        product_keys=(f"uploads/{TENANT_ID}/p1.jpg",),
        background_key=f"uploads/{TENANT_ID}/bg.jpg",
        scene_prompt="Una mano sosteniendo la hamburguesa en el local",
    )
    outcome = _produce(_producer(store, seedream=seedream), brief, draft_id)

    assert outcome.failure is None
    (request,) = seedream.requests
    params = request.params
    # the product first, the background last, as data URLs; a size inside both ranges
    assert len(params["images"]) == 2
    assert all(str(url).startswith("data:image/jpeg;base64,") for url in params["images"])
    assert params["size"] == "1728x2160"
    prompt = str(params["prompt"])
    assert "Una mano sosteniendo la hamburguesa en el local" in prompt
    assert "Do not draw any text" in prompt  # the words and the logo are ours
    assert set(seedream.keys) == {"key-seedream"}

    (slide,) = outcome.media
    assert slide.provider == "seedream" and slide.model_id == SEEDREAM_MODEL
    assert (slide.width, slide.height, slide.content_type) == (1080, 1350, "image/jpeg")
    assert store.files[generated_key(TENANT_ID, draft_id, "slide-1.jpg")][:3] == b"\xff\xd8\xff"
    assert slide.params["ad_mode"] == "both" and slide.params["generated_scenes"] == 1
    (cost,) = outcome.usage
    assert (cost.provider, cost.unit, cost.cost_usd) == ("seedream", "piece", Decimal("0.035"))
    assert brief.requires_ai_disclosure  # the photograph is AI imagery


def test_a_product_only_ad_does_not_send_the_background() -> None:
    seedream = FakeSeedream()
    brief = _brief(
        ContentKind.STATIC_FLYER,
        ad_mode=AdImageMode.PRODUCT,
        product_keys=(f"uploads/{TENANT_ID}/p1.jpg",),
        background_key=f"uploads/{TENANT_ID}/bg.jpg",
    )
    _produce(_producer(_store(), seedream=seedream), brief, uuid4())
    (request,) = seedream.requests
    assert len(request.params["images"]) == 1


def test_a_carousel_generates_one_scene_per_product_and_closes_with_the_cta() -> None:
    seedream = FakeSeedream()
    brief = _brief(
        ContentKind.STATIC_FLYER,
        ad_mode=AdImageMode.BOTH,
        product_keys=(
            f"uploads/{TENANT_ID}/p1.jpg",
            f"uploads/{TENANT_ID}/p2.jpg",
            f"uploads/{TENANT_ID}/p3.jpg",
        ),
        background_key=f"uploads/{TENANT_ID}/bg.jpg",
        carousel=True,
    )
    outcome = _produce(_producer(_store(), seedream=seedream), brief, uuid4())
    assert outcome.failure is None
    assert len(seedream.requests) == 3
    assert all(len(r.params["images"]) == 2 for r in seedream.requests)  # product + place
    assert [m.position for m in outcome.media] == [0, 1, 2, 3]  # + the closing CTA slide
    assert outcome.spent_usd == Decimal("0.105")


def test_without_a_byteplus_key_the_ad_fails_without_naming_the_vendor() -> None:
    brief = _brief(
        ContentKind.STATIC_FLYER,
        ad_mode=AdImageMode.PRODUCT,
        product_keys=(f"uploads/{TENANT_ID}/p1.jpg",),
    )
    outcome = _produce(
        _producer(_store(), seedream=FakeSeedream(), credentials=NoArkKey()), brief, uuid4()
    )
    assert outcome.failure == FailureReason.PROVIDER_ERROR.value
    assert outcome.detail == "La generación no está disponible ahora mismo. Avisa al equipo."
    assert outcome.media == () and outcome.usage == ()


# -- the avatar videos on Seedance ---------------------------------------------------------


def _seedance_brief(fmt: ContentFormat | None = None, **media: object) -> ContentBrief:
    base: dict[str, object] = {
        "video_engine": VideoEngine.SEEDANCE,
        "avatar_source": AvatarSource.AI,
        "avatar_prompt": "Mujer latina de unos 30 años",
        "product_keys": (f"uploads/{TENANT_ID}/p1.jpg",),
        "background_key": f"uploads/{TENANT_ID}/bg.jpg",
    }
    base.update(media)
    return _brief(ContentKind.AVATAR_VIDEO, fmt, **base)


def test_a_seedance_video_starts_on_a_seedream_frame_and_records_both_costs() -> None:
    store, seedream, seedance, draft_id = _store(), FakeSeedream(), FakeSeedance(), uuid4()
    outcome = _produce(
        _producer(store, seedream=seedream, seedance=seedance), _seedance_brief(), draft_id
    )

    assert outcome.failure is None
    (frame_request,) = seedream.requests
    assert frame_request.params["size"] == "1440x2560"  # 9:16
    assert len(frame_request.params["images"]) == 2  # product + background
    assert "Mujer latina de unos 30 años" in str(frame_request.params["prompt"])

    (video_request,) = seedance.requests
    params = video_request.params
    assert str(params["first_frame"]).startswith("data:image/jpeg;base64,")
    assert (params["ratio"], params["resolution"]) == ("9:16", "720p")
    assert params["duration_seconds"] == 30  # the adapter clamps it to the model's range
    assert params["dialogue"] == COPY.script
    assert set(seedance.keys) == {"key-seedance"}

    (video,) = outcome.media
    assert video.provider == "seedance" and video.model_id == SEEDANCE_MODEL
    assert (video.width, video.height, video.aspect_ratio) == (704, 1248, "9:16")
    assert video.content_type == "video/mp4"
    assert store.files[generated_key(TENANT_ID, draft_id, "video.mp4")] == b"mp4-bytes"
    assert video.params["thumbnail_key"] == generated_key(TENANT_ID, draft_id, "first-frame.jpg")
    assert video.params["spoken"] is False
    frame_cost, video_cost = outcome.usage
    assert frame_cost.cost_usd == Decimal("0.035")
    # 102,960 tokens × USD 2.5 / M
    assert (video_cost.unit, video_cost.cost_usd) == ("second", Decimal("0.257400"))


def test_a_feed_video_is_rendered_3_4_because_seedance_has_no_4_5() -> None:
    seedream, seedance = FakeSeedream(), FakeSeedance()
    _produce(
        _producer(_store(), seedream=seedream, seedance=seedance),
        _seedance_brief(ContentFormat.FEED_4_5),
        uuid4(),
    )
    assert seedream.requests[0].params["size"] == "1728x2304"
    assert seedance.requests[0].params["ratio"] == "3:4"


def test_an_animated_character_from_an_image_is_the_first_reference() -> None:
    seedream, seedance = FakeSeedream(), FakeSeedance()
    brief = _brief(
        ContentKind.ANIMATED_AVATAR_VIDEO,
        video_engine=VideoEngine.SEEDANCE,
        avatar_source=AvatarSource.IMAGE,
        avatar_image_key=f"uploads/{TENANT_ID}/mascota.png",
        avatar_rights_confirmed=True,
        product_keys=(f"uploads/{TENANT_ID}/p1.jpg",),
    )
    outcome = _produce(_producer(_store(), seedream=seedream, seedance=seedance), brief, uuid4())
    assert outcome.failure is None
    params = seedream.requests[0].params
    assert len(params["images"]) == 2  # the character, then the product
    assert "image 1" in str(params["prompt"]) and "keep its exact design" in str(params["prompt"])


def test_a_failed_video_keeps_the_frames_cost_and_says_why() -> None:
    seedream = FakeSeedream()
    outcome = _produce(
        _producer(_store(), seedream=seedream, seedance=FakeSeedance(fail=True)),
        _seedance_brief(),
        uuid4(),
    )
    assert outcome.failure == FailureReason.PROVIDER_ERROR.value
    assert "filtro de contenido" in outcome.detail
    (frame_cost,) = outcome.usage  # the frame was paid for: it stays on the record
    assert frame_cost.provider == "seedream"


# -- the brief ------------------------------------------------------------------------------


def test_a_seedance_brief_needs_no_voice_but_a_described_presenter() -> None:
    assert _seedance_brief().media.voice_id is None
    with pytest.raises(ValidationError, match="presenter's description"):
        _brief(ContentKind.AVATAR_VIDEO, video_engine=VideoEngine.SEEDANCE)
    with pytest.raises(ValidationError, match="needs a voice"):
        _brief(ContentKind.AVATAR_VIDEO, avatar_look_id="lk")  # HeyGen, the default
    animated = _brief(
        ContentKind.ANIMATED_AVATAR_VIDEO,
        video_engine=VideoEngine.SEEDANCE,
        avatar_source=AvatarSource.AI,
        avatar_prompt="Una hamburguesa sonriente",
    )
    assert animated.media.video_engine is VideoEngine.SEEDANCE


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ArkAPIError: HTTP 404 ModelNotOpen: x", "no está disponible ahora mismo"),
        ("HTTP 400 InputImageSensitiveContentDetected.PrivacyInformation", "personas reales"),
        ("HTTP 400 OutputVideoSensitiveContentDetected", "filtro de contenido"),
        ("HTTP 403 AccountOverdueError", "no está disponible ahora mismo"),
        ("MissingPlatformKey: QUALIFY_BYTEPLUS_ARK_API_KEY", "no está disponible ahora mismo"),
        ("ArkTaskTimeout: task cgt-1 still running", "tardando más de lo normal"),
        ("HTTP 429 RateLimitExceeded", "muchas generaciones en curso"),
        ("something else", "No se pudo generar la pieza. Inténtalo de nuevo."),
    ],
)
def test_modelarks_failures_read_in_the_operators_words(raw: str, expected: str) -> None:
    text = ark_failure_text(raw)
    assert expected in text
    # the vendor's raw error and any vendor / model / env var name stay in the log
    assert raw not in text
    for word in ("BytePlus", "ModelArk", "Seedream", "Seedance", "QUALIFY_", "USD"):
        assert word not in text

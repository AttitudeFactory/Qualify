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
from qualify_creative.adapters.byteplus_ark import MAX_PROMPT_CHARS
from qualify_creative.adapters.byteplus_speech import (
    CLONE_RESOURCE,
    PUBLIC_RESOURCE,
    PUBLIC_SPANISH_VOICES,
)
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
    SlideSource,
    SlideText,
    VideoEngine,
)
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.providers import GenerationRequest, GenerationResult, ResolvedKey, Usage
from qualify_creative.router import BudgetContext, CreativeRouter
from qualify_creative.schemas import (
    AVATAR_PROMPT_MAX,
    SCENE_PROMPT_MAX,
    SCRIPT_MAX,
    BrandKit,
    CarouselSlide,
    ContentBrief,
    CopyPayload,
    MediaInputs,
    ToneAxes,
)
from qualify_creative.video import FittedVideo

from qualify_api.creative.media import (
    AVATAR_NO_PUBLIC_URL,
    AVATAR_SCRIPT_TOO_LONG,
    FILTERED_TEXT,
    MediaProducer,
    ai_generated_media,
    ark_failure_text,
    generated_key,
)
from qualify_api.creative.voice_access import BrandVoiceResolver

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


def test_an_old_flyer_without_ad_mode_is_still_seedream_imagery() -> None:
    """A flyer stored before `ad_mode` existed (PR #100 review): the producer infers the
    mode and Seedream renders it, yet the brief's a-priori label says no — so the draft's
    label is recomputed from what was made (`MediaWrite.ai_generated`), never from the
    brief alone."""
    store, seedream, draft_id = _store(), FakeSeedream(), uuid4()
    brief = _brief(ContentKind.STATIC_FLYER, product_keys=(f"uploads/{TENANT_ID}/p1.jpg",))
    assert brief.media.ad_mode is None and not brief.requires_ai_disclosure

    outcome = _produce(_producer(store, seedream=seedream), brief, draft_id)

    assert outcome.failure is None and len(seedream.requests) == 1
    (slide,) = outcome.media
    assert slide.provider == "seedream" and slide.params["ad_mode"] == "product"
    assert slide.ai_generated is True
    assert ai_generated_media(outcome.media) is True


def test_an_ad_without_photos_is_the_described_scene_alone() -> None:
    """§ 2026-10-12: the product and the background are optional. With neither, Seedream
    gets no reference image and is told to compose the scene from the words."""
    store, seedream, draft_id = _store(), FakeSeedream(), uuid4()
    brief = _brief(
        ContentKind.STATIC_FLYER,
        ad_mode=AdImageMode.SCENE,
        scene_prompt="Una hamburguesa sobre una mesa de madera, luz cálida",
    )
    outcome = _produce(_producer(store, seedream=seedream), brief, draft_id)

    assert outcome.failure is None
    (request,) = seedream.requests
    assert request.params["images"] == []
    prompt = str(request.params["prompt"])
    assert "no reference images" in prompt
    assert "Una hamburguesa sobre una mesa de madera" in prompt
    (slide,) = outcome.media
    assert slide.params["ad_mode"] == "scene" and slide.params["products"] == 0
    assert slide.params["background"] is False and slide.ai_generated is True
    # a brief stored without a mode and without photos is inferred as the scene alone
    old = _brief(ContentKind.STATIC_FLYER, scene_prompt="Una hamburguesa")
    outcome = _produce(_producer(store, seedream=FakeSeedream()), old, uuid4())
    assert outcome.failure is None and outcome.media[0].params["ad_mode"] == "scene"


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


def test_a_generated_script_over_the_cap_is_shortened_before_seedance_speaks_it() -> None:
    """PR #100 review: a generated script has no stored cap, and motion prompt + spoken
    line must stay under the vendor's 3,000 characters. A 60-s script five times the
    cap is cut at a sentence, like `own_script` would have been refused."""
    store, seedream, seedance = _store(), FakeSeedream(), FakeSeedance()
    long_copy = CopyPayload(
        hook=COPY.hook,
        caption=COPY.caption,
        cta=COPY.cta,
        script=" ".join(f"Frase número {i} del guion largo." for i in range(400)),
    )
    assert len(long_copy.script) > 5 * SCRIPT_MAX
    outcome = _producer(store, seedream=seedream, seedance=seedance).produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=_seedance_brief(),
        kit=_kit(),
        copy=long_copy,
        budget=BUDGET,
    )
    assert outcome.failure is None
    (video_request,) = seedance.requests
    spoken = str(video_request.params["dialogue"])
    assert len(spoken) <= SCRIPT_MAX and spoken.endswith("largo.")
    # the adapter's own pre-flight: motion + spoken line under the vendor's cap
    motion = str(video_request.params["prompt"])
    assert len(motion) + len(spoken) + len('\nDice a cámara: ""') < MAX_PROMPT_CHARS


def test_the_image_prompts_stay_under_the_vendor_cap_with_a_very_long_topic() -> None:
    """PR #100 review: the topic has no stored cap (TEXT), so the prompt takes its gist."""
    from qualify_api.creative.media import (
        ad_scene_prompt,
        carousel_scene_prompt,
        first_frame_prompt,
    )

    topic = " ".join(f"Detalle {i} que el operador quiso contar," for i in range(300))
    scene = "x" * SCENE_PROMPT_MAX
    ad_brief = _brief(
        ContentKind.STATIC_FLYER,
        ad_mode=AdImageMode.PRODUCT,
        product_keys=(f"uploads/{TENANT_ID}/p1.jpg",),
        scene_prompt=scene,
    ).model_copy(update={"topic": topic})
    brief = _seedance_brief(avatar_prompt="y" * AVATAR_PROMPT_MAX).model_copy(
        update={"topic": topic}
    )
    prompts = [
        ad_scene_prompt(
            brief=ad_brief,
            kit=_kit(),
            brand="Marca " * 10,
            mode=AdImageMode.PRODUCT,
            products=10,
            has_background=True,
        ),
        carousel_scene_prompt(
            brief=ad_brief,
            kit=_kit(),
            brand="Marca " * 10,
            scene=scene,
            ratio="4:5",
            has_product=True,
            has_background=True,
            has_text=True,
        ),
        first_frame_prompt(
            brief=brief, kit=_kit(), has_character_image=True, products=10, has_background=True
        ),
    ]
    assert all(len(prompt) <= MAX_PROMPT_CHARS - 500 for prompt in prompts), [
        len(p) for p in prompts
    ]
    assert all("Detalle 0 que" in prompt and "Detalle 299" not in prompt for prompt in prompts)


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
        ("ArkAPIError: HTTP 404 ModelNotOpen: x", "no está activado todavía"),
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


# -- the vendor download's guard rails (PR #100 review) ----------------------------------


def _offline_downloads(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    """`_http_download` builds its own client: give it a MockTransport."""
    import httpx

    real = httpx.Client

    def client(**kwargs: Any) -> httpx.Client:
        return real(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "Client", client)


def test_a_vendor_url_that_is_not_https_is_never_fetched(monkeypatch: pytest.MonkeyPatch) -> None:
    from qualify_api.creative.media import DownloadRefused, _http_download

    calls: list[Any] = []
    _offline_downloads(monkeypatch, lambda request: calls.append(request))
    for url in ("http://cdn.test/v.mp4", "file:///etc/passwd"):
        with pytest.raises(DownloadRefused):
            _http_download(url)
    assert calls == []


def test_a_redirect_off_https_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from qualify_api.creative.media import DownloadRefused, _http_download

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest"})

    _offline_downloads(monkeypatch, handler)
    with pytest.raises(DownloadRefused):
        _http_download("https://cdn.test/v.mp4")


def test_a_vendor_file_over_the_cap_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from qualify_api.creative import media

    monkeypatch.setattr(media, "MAX_DOWNLOAD_BYTES", 10)
    _offline_downloads(monkeypatch, lambda request: httpx.Response(200, content=b"x" * 11))
    with pytest.raises(media.DownloadRefused):
        media._http_download("https://cdn.test/v.mp4")


def test_a_vendor_file_within_the_cap_comes_back_whole(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from qualify_api.creative.media import _http_download

    _offline_downloads(monkeypatch, lambda request: httpx.Response(200, content=b"mp4-bytes"))
    assert _http_download("https://cdn.test/v.mp4") == b"mp4-bytes"


# -- the carousel (§ request 2026-10-09) -------------------------------------------------

OTHER_DRAFT = UUID("7e7e0000-0000-4000-8000-0000000000d1")
PIECE_IMAGE = f"t/{TENANT_ID}/generated/{OTHER_DRAFT}/r1/slide-1.jpg"
PIECE_VIDEO = f"t/{TENANT_ID}/generated/{OTHER_DRAFT}/r1/video.mp4"


class FakePieces:
    """The brand's pieces: only the two files above are this brand's."""

    def __init__(self) -> None:
        self.asked: list[tuple[UUID, str]] = []

    def file(self, *, tenant_id: UUID, brand_id: UUID, object_key: str) -> Any:
        from qualify_api.creative.pieces import PieceFile

        self.asked.append((brand_id, object_key))
        kinds = {PIECE_IMAGE: "image", PIECE_VIDEO: "video"}
        if brand_id != BRAND_ID or object_key not in kinds:
            return None
        return PieceFile(
            draft_id=OTHER_DRAFT,
            object_key=object_key,
            media_type=kinds[object_key],
            content_type=None,
            width=None,
            height=None,
            position=0,
            poster_key=None,
            topic="Promo anterior",
        )

    def files(self, **_: Any) -> list[Any]:
        return []


class FakeFitter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def fit(
        self,
        data: bytes,
        *,
        size: tuple[int, int],
        overlay: bytes | None = None,
        max_seconds: float = 60.0,
        keep_audio: bool = False,
    ) -> FittedVideo:
        self.calls.append(
            {"data": data, "size": size, "overlay": overlay, "keep_audio": keep_audio}
        )
        return FittedVideo(
            data=b"fitted-" + data,
            width=size[0],
            height=size[1],
            duration_sec=5.0,
            poster=_image((1, 2, 3), size),
        )

    def animate_still(
        self, image: bytes, *, size: tuple[int, int], seconds: float = 6.0
    ) -> FittedVideo:
        self.calls.append({"still": image, "size": size, "seconds": seconds})
        return FittedVideo(
            data=b"animated-still",
            width=size[0],
            height=size[1],
            duration_sec=seconds,
            poster=image,
        )


def test_an_ad_image_as_a_reel_is_its_composed_image_animated() -> None:
    """§ 2026-10-13: Instagram publishes only a video as a Reel, so the ad image in the
    Reel format is the composed 9:16 image (words and logo on it) animated — one
    Seedream call, never a second generation."""
    store, seedream, fitter, draft_id = _store(), FakeSeedream(), FakeFitter(), uuid4()
    producer = _producer(store, seedream=seedream)
    producer._fitter = fitter
    brief = _brief(
        ContentKind.STATIC_FLYER,
        ContentFormat.REELS_9_16,
        ad_mode=AdImageMode.SCENE,
        scene_prompt="Una hamburguesa sobre una mesa de madera",
    )
    outcome = _produce(producer, brief, draft_id)

    assert outcome.failure is None and len(seedream.requests) == 1
    assert seedream.requests[0].params["size"] == "1440x2560"  # the 9:16 scene
    (call,) = fitter.calls
    assert call["size"] == (1080, 1920) and call["still"][:3] == b"\x89PN"  # the composed PNG
    (reel,) = outcome.media
    assert reel.media_type == "video" and reel.content_type == "video/mp4"
    assert reel.media_url == generated_key(TENANT_ID, draft_id, "reel.mp4")
    assert store.files[reel.media_url] == b"animated-still"
    assert reel.params["animated_still"] is True and reel.params["duration_seconds"] == 6.0
    assert reel.params["thumbnail_key"].endswith("reel-poster.jpg")
    assert reel.ai_generated is True and brief.requires_ai_disclosure


def _carousel_producer(
    store: MemoryStore, seedream: FakeSeedream, seedance: FakeSeedance, fitter: FakeFitter
) -> MediaProducer:
    producer = _producer(store, seedream=seedream, seedance=seedance)
    producer._pieces = FakePieces()
    producer._fitter = fitter
    return producer


def _carousel_store() -> MemoryStore:
    store = _store()
    store.files[PIECE_IMAGE] = _image((0, 90, 90), (1080, 1920))
    store.files[PIECE_VIDEO] = b"reel-bytes"
    return store


def test_a_mixed_carousel_lays_out_every_slide_in_order() -> None:
    store, seedream, seedance, fitter = (
        _carousel_store(),
        FakeSeedream(),
        FakeSeedance(),
        FakeFitter(),
    )
    draft_id = uuid4()
    brief = _brief(
        ContentKind.CAROUSEL,
        product_keys=(f"uploads/{TENANT_ID}/p1.jpg",),
        background_key=f"uploads/{TENANT_ID}/bg.jpg",
        slides=(
            CarouselSlide(source=SlideSource.GENERATED, product_index=0, text=SlideText.HOOK),
            CarouselSlide(
                source=SlideSource.ANIMATED, scene_prompt="la smash girando", text=SlideText.CTA
            ),
            CarouselSlide(source=SlideSource.EXISTING, object_key=PIECE_IMAGE),
            CarouselSlide(source=SlideSource.EXISTING, object_key=PIECE_VIDEO),
        ),
        closing_slide=True,
    )
    outcome = _produce(_carousel_producer(store, seedream, seedance, fitter), brief, draft_id)

    assert outcome.failure is None
    assert [(m.position, m.media_type) for m in outcome.media] == [
        (0, "image"),  # generated, the hook on it
        (1, "video"),  # animated, the CTA laid over
        (2, "image"),  # a reused image
        (3, "video"),  # a reused Reel
        (4, "image"),  # the closing slide
    ]
    # two scenes: the generated slide at the feed's 4:5, the animated one at Seedance's 3:4
    first, second = seedream.requests
    assert first.params["size"] == "1728x2160" and len(first.params["images"]) == 2
    assert second.params["size"] == "1728x2304" and len(second.params["images"]) == 1
    assert "la smash girando" in str(second.params["prompt"])
    # one silent, presenter-less Seedance clip of the slide's length
    (clip,) = seedance.requests
    assert clip.params["generate_audio"] is False and clip.params["duration_seconds"] == 5
    assert "dialogue" not in clip.params and "Nobody talks" in str(clip.params["prompt"])
    # the animated slide gets its CTA laid over; the reused Reel is only fitted
    animated, reused = fitter.calls
    assert animated["data"] == b"mp4-bytes" and animated["overlay"] is not None
    assert reused["data"] == b"reel-bytes" and reused["overlay"] is None
    assert {call["size"] for call in fitter.calls} == {(1080, 1350)}
    # every slide is fitted to the feed and stored in this draft, videos with a poster
    for media in outcome.media:
        assert (media.width, media.height) == (1080, 1350)
        assert media.object_key and str(draft_id) in media.object_key
        if media.media_type == "video":
            assert media.content_type == "video/mp4" and media.params["thumbnail_key"]
        else:
            assert media.content_type == "image/jpeg"
    reused_image = Image.open(io.BytesIO(store.files[outcome.media[2].object_key]))
    assert reused_image.size == (1080, 1350)
    assert outcome.media[2].params["from_draft"] == str(OTHER_DRAFT)
    assert outcome.media[4].params["source"] == "closing"
    # paid: two Seedream pieces and one Seedance clip
    assert [u.unit for u in outcome.usage] == ["piece", "piece", "second"]


def test_an_animated_slide_without_text_is_only_fitted() -> None:
    fitter = FakeFitter()
    brief = _brief(
        ContentKind.CAROUSEL,
        slides=(
            CarouselSlide(source=SlideSource.ANIMATED),
            CarouselSlide(source=SlideSource.GENERATED),
        ),
    )
    outcome = _produce(
        _carousel_producer(_store(), FakeSeedream(), FakeSeedance(), fitter), brief, uuid4()
    )
    assert outcome.failure is None
    (call,) = fitter.calls
    assert call["overlay"] is None


def test_a_piece_of_another_brand_is_never_read_into_the_carousel() -> None:
    other = f"t/{TENANT_ID}/generated/{uuid4()}/r1/slide-1.jpg"
    store, seedream = _carousel_store(), FakeSeedream()
    store.files[other] = _image()
    brief = _brief(
        ContentKind.CAROUSEL,
        slides=(
            CarouselSlide(source=SlideSource.EXISTING, object_key=other),
            CarouselSlide(source=SlideSource.GENERATED),
        ),
    )
    outcome = _produce(
        _carousel_producer(store, seedream, FakeSeedance(), FakeFitter()), brief, uuid4()
    )
    assert outcome.failure == FailureReason.ROUTE_BLOCKED_BY_POLICY.value
    assert "diapositiva 1" in (outcome.detail or "")
    assert seedream.requests == []  # refused before anything was paid for


def test_a_missing_piece_on_a_later_slide_fails_before_any_slide_is_paid_for() -> None:
    """PR #100 review: the source draft was regenerated (0048 dropped its files) — the
    carousel must not pay Seedream for slides 1-2 and then fail on slide 3."""
    gone = f"t/{TENANT_ID}/generated/{OTHER_DRAFT}/r1/slide-9.jpg"  # not a piece any more
    store, seedream, seedance = _carousel_store(), FakeSeedream(), FakeSeedance()
    brief = _brief(
        ContentKind.CAROUSEL,
        slides=(
            CarouselSlide(source=SlideSource.GENERATED),
            CarouselSlide(source=SlideSource.ANIMATED),
            CarouselSlide(source=SlideSource.EXISTING, object_key=gone),
        ),
    )
    outcome = _produce(_carousel_producer(store, seedream, seedance, FakeFitter()), brief, uuid4())
    assert outcome.failure == FailureReason.ROUTE_BLOCKED_BY_POLICY.value
    assert "diapositiva 3" in (outcome.detail or "")
    assert seedream.requests == [] and seedance.requests == []


def test_a_carousel_key_outside_the_tenant_is_refused_before_any_read() -> None:
    brief = _brief(
        ContentKind.CAROUSEL,
        slides=(
            CarouselSlide(source=SlideSource.EXISTING, object_key=f"t/{uuid4()}/x/slide.jpg"),
            CarouselSlide(source=SlideSource.GENERATED),
        ),
    )
    outcome = _produce(
        _carousel_producer(_store(), FakeSeedream(), FakeSeedance(), FakeFitter()), brief, uuid4()
    )
    assert outcome.failure == FailureReason.ROUTE_BLOCKED_BY_POLICY.value


# -- a «Video de stock» gallery slide (§ request 2026-10-16) -------------------------------

STOCK_VIDEO = f"t/{TENANT_ID}/stock/pixabay/video-199545/abcdef0123456789.mp4"


def test_a_stock_slide_is_fitted_with_the_words_and_logo_and_costs_nothing() -> None:
    store, seedream, seedance, fitter = (
        _carousel_store(),
        FakeSeedream(),
        FakeSeedance(),
        FakeFitter(),
    )
    store.files[STOCK_VIDEO] = b"stock-bytes"
    brief = _brief(
        ContentKind.CAROUSEL,
        slides=(
            CarouselSlide(source=SlideSource.STOCK, object_key=STOCK_VIDEO, text=SlideText.HOOK),
            CarouselSlide(source=SlideSource.EXISTING, object_key=PIECE_IMAGE),
        ),
    )
    draft_id = uuid4()
    outcome = _produce(_carousel_producer(store, seedream, seedance, fitter), brief, draft_id)

    assert outcome.failure is None
    stock, _ = outcome.media
    (call,) = fitter.calls
    # never as it is: the slide's words are laid over every frame
    assert call["data"] == b"stock-bytes" and call["overlay"] is not None
    assert stock.media_type == "video" and str(draft_id) in stock.object_key
    assert stock.params["source"] == "stock" and stock.params["from_key"] == STOCK_VIDEO
    assert stock.ai_generated is False and stock.params["thumbnail_key"]
    # composed here: no model, nothing paid
    assert seedream.requests == [] and seedance.requests == [] and outcome.usage == ()


def test_a_stock_slide_whose_video_is_gone_fails_before_anything_is_paid() -> None:
    store, seedream, seedance, fitter = (
        _carousel_store(),
        FakeSeedream(),
        FakeSeedance(),
        FakeFitter(),
    )
    brief = _brief(
        ContentKind.CAROUSEL,
        product_keys=(f"uploads/{TENANT_ID}/p1.jpg",),
        slides=(
            CarouselSlide(source=SlideSource.GENERATED, product_index=0, text=SlideText.HOOK),
            CarouselSlide(source=SlideSource.STOCK, object_key=STOCK_VIDEO, text=SlideText.CTA),
        ),
    )
    outcome = _produce(_carousel_producer(store, seedream, seedance, fitter), brief, uuid4())
    assert outcome.failure == FailureReason.ROUTE_BLOCKED_BY_POLICY.value
    assert "video de stock de la diapositiva 2" in outcome.detail
    assert seedream.requests == [] and outcome.usage == ()


def test_a_stock_slide_always_carries_words_and_only_a_stock_video() -> None:
    from qualify_api.stock.guard import MISPLACED_TEXT, stock_problems

    with pytest.raises(ValueError):
        CarouselSlide(source=SlideSource.STOCK, object_key=STOCK_VIDEO)  # no words
    with pytest.raises(ValueError):
        CarouselSlide(source=SlideSource.STOCK, text=SlideText.HOOK)  # no video
    not_stock = _brief(
        ContentKind.CAROUSEL,
        slides=(
            CarouselSlide(source=SlideSource.STOCK, object_key=PIECE_VIDEO, text=SlideText.CTA),
            CarouselSlide(source=SlideSource.EXISTING, object_key=PIECE_IMAGE),
        ),
    )
    assert stock_problems(not_stock) == MISPLACED_TEXT
    # a stock file reused «as it is» would be published standalone
    as_is = _brief(
        ContentKind.CAROUSEL,
        slides=(
            CarouselSlide(source=SlideSource.EXISTING, object_key=STOCK_VIDEO),
            CarouselSlide(source=SlideSource.EXISTING, object_key=PIECE_IMAGE),
        ),
    )
    assert stock_problems(as_is) == MISPLACED_TEXT
    fine = _brief(
        ContentKind.CAROUSEL,
        slides=(
            CarouselSlide(source=SlideSource.STOCK, object_key=STOCK_VIDEO, text=SlideText.CTA),
            CarouselSlide(source=SlideSource.EXISTING, object_key=PIECE_IMAGE),
        ),
    )
    assert stock_problems(fine) is None


# --------------------------------------------------------------------------------------
# The talking presenter over ByteDance (§ request 2026-10-16, HeyGen retired): Seedream
# composes the presenter, Seed Speech reads the script in the chosen voice and OmniHuman
# makes the presenter say it, lips in sync.
# --------------------------------------------------------------------------------------

PUBLIC_VOICE = PUBLIC_SPANISH_VOICES[0]["id"]


class FakeSpeech:
    name = "seed_speech"
    supports = frozenset({GenerationTask.VOICEOVER})

    def __init__(self) -> None:
        self.requests: list[GenerationRequest] = []

    def generate(self, request: GenerationRequest, *, api_key: str) -> GenerationResult:
        self.requests.append(request)
        return GenerationResult(
            payload=b"ID3-mp3-bytes",
            model_id=str(request.params["resource_id"]),
            provider="seed_speech",
            usage=Usage(pieces=1, input_tokens=len(str(request.params["text"]))),
        )

    def estimate_cost_usd(self, request: GenerationRequest, pricing: Any, **_: Any) -> Decimal:
        return Decimal("0.01")


class FakeOmniHuman:
    name = "omnihuman"
    supports = frozenset({GenerationTask.AVATAR_VIDEO})

    def __init__(self, *, fail: str | None = None) -> None:
        self.requests: list[GenerationRequest] = []
        self.fail = fail

    def generate(self, request: GenerationRequest, *, api_key: str) -> GenerationResult:
        self.requests.append(request)
        if self.fail:
            raise RuntimeError(self.fail)
        return GenerationResult(
            payload={
                "task_id": "7392",
                "req_key": "realman_avatar_picture_omni15_cv",
                "resolution": 720,
            },
            model_id="omnihuman-1-5",
            provider="omnihuman",
            usage=Usage(pieces=1, media_seconds=Decimal(str(request.params["audio_seconds"]))),
            model_revision="realman_avatar_picture_omni15_cv",
            media_url="https://cdn/omni.mp4",
        )

    def estimate_cost_usd(self, request: GenerationRequest, pricing: Any, **_: Any) -> Decimal:
        return Decimal("1")


class FakeLinks:
    """The public-media token links OmniHuman fetches the photo and the voice from."""

    def __init__(self) -> None:
        self.served: list[tuple[str, str]] = []

    def __call__(self, *, tenant_id: UUID, key: str, data: bytes, content_type: str) -> str:
        self.served.append((key, content_type))
        return f"https://qualify.test/public/{len(self.served)}"


def _presenter(
    store: MemoryStore,
    *,
    seedream: FakeSeedream | None = None,
    speech: FakeSpeech | None = None,
    omni: FakeOmniHuman | None = None,
    links: FakeLinks | None = None,
    clone: tuple[str, str, bool] | None = None,
    max_seconds: float = 59.0,
    activated: list[tuple[UUID, UUID, str]] | None = None,
) -> MediaProducer:
    pricing = JsonPricingTable("v5")
    providers: dict[str, Any] = {
        vendor.name: vendor for vendor in (seedream, speech, omni) if vendor is not None
    }
    router = CreativeRouter(providers, pricing, KeysByProvider())

    def stamp(tenant_id: UUID, brand_id: UUID, voice: str) -> None:
        if activated is not None:
            activated.append((tenant_id, brand_id, voice))

    return MediaProducer(
        store=store,
        router=router,
        credentials=KeysByProvider(),
        pricing=pricing,
        download=lambda url: b"omni-mp4",
        voices=BrandVoiceResolver(clone_lookup=lambda tenant_id, brand_id: clone),
        on_brand_voice_used=stamp,
        omnihuman_max_seconds=max_seconds,
        reference_links=links,
    )


def _presenter_brief(**media: object) -> ContentBrief:
    return _brief(
        ContentKind.AVATAR_VIDEO,
        video_engine=VideoEngine.OMNIHUMAN,
        avatar_source=AvatarSource.AI,
        avatar_prompt="Mujer latina de unos 30 años, sonriente",
        **media,
    )


def test_the_presenter_is_composed_voiced_and_animated_with_a_public_voice() -> None:
    store, seedream, speech, omni, links = (
        _store(),
        FakeSeedream(),
        FakeSpeech(),
        FakeOmniHuman(),
        FakeLinks(),
    )
    draft_id = uuid4()
    product = f"uploads/{TENANT_ID}/p1.jpg"
    outcome = _produce(
        _presenter(store, seedream=seedream, speech=speech, omni=omni, links=links),
        _presenter_brief(voice_id=PUBLIC_VOICE, product_keys=(product,)),
        draft_id,
    )
    assert outcome.failure is None, outcome.detail
    # 1. Seedream composes the presenter, the product as a reference
    (scene,) = seedream.requests
    assert len(scene.params["images"]) == 1
    # 2. Seed Speech reads the exact script in the public voice
    (voice,) = speech.requests
    assert voice.params["text"] == COPY.script
    assert voice.params["speaker"] == PUBLIC_VOICE
    assert voice.params["resource_id"] == PUBLIC_RESOURCE
    # 3. OmniHuman gets the photo and the voice as public https links
    (render,) = omni.requests
    assert render.params["image_url"].startswith("https://")
    assert render.params["audio_url"].startswith("https://")
    assert [content_type for _, content_type in links.served] == ["image/jpeg", "audio/mpeg"]
    assert render.params["resolution"] == 720 and render.params["audio_seconds"] > 0

    (video,) = outcome.media
    assert video.media_type == "video" and video.ai_generated and video.provider == "omnihuman"
    assert store.files[video.object_key] == b"omni-mp4"
    assert video.params["voice"] == "public" and video.params["voice_id"] == PUBLIC_VOICE
    assert video.params["thumbnail_key"] == generated_key(TENANT_ID, draft_id, "presenter.jpg")
    assert store.files[generated_key(TENANT_ID, draft_id, "voice.mp3")] == b"ID3-mp3-bytes"
    assert [(u.provider, u.unit) for u in outcome.usage] == [
        ("seedream", "piece"),
        ("seed_speech", "character"),
        ("omnihuman", "second"),
    ]
    # the real v5 rate: USD 30 per million characters
    expected = Decimal(len(COPY.script)) * Decimal(30) / Decimal(1_000_000)
    assert outcome.usage[1].cost_usd == expected.quantize(Decimal("0.000001"))


def test_the_brands_own_voice_is_resolved_server_side_and_stamped() -> None:
    speech, activated = FakeSpeech(), []
    outcome = _produce(
        _presenter(
            _store(),
            seedream=FakeSeedream(),
            speech=speech,
            omni=FakeOmniHuman(),
            links=FakeLinks(),
            clone=("qlf-abc", "es-MX", True),
            activated=activated,
        ),
        _presenter_brief(voice_id="brand"),
        uuid4(),
    )
    assert outcome.failure is None, outcome.detail
    params = speech.requests[0].params
    assert params["speaker"] == "qlf-abc" and params["resource_id"] == CLONE_RESOURCE
    assert params["language"] == "es-mx"
    assert activated == [(TENANT_ID, BRAND_ID, "qlf-abc")]
    assert outcome.media[0].params["voice"] == "brand"
    assert outcome.media[0].params["voice_id"] is None  # the clone's id is never exposed
    # its first real synthesis: BytePlus charges the clone's USD 2 slot, recorded too
    slot = [u for u in outcome.usage if u.model_id == "seed-icl-2.0-slot"]
    assert [(u.provider, u.unit, u.quantity, u.cost_usd) for u in slot] == [
        ("seed_speech", "piece", 1, Decimal("2.00"))
    ]


def test_a_brand_voice_already_used_charges_no_slot_again() -> None:
    outcome = _produce(
        _presenter(
            _store(),
            seedream=FakeSeedream(),
            speech=FakeSpeech(),
            omni=FakeOmniHuman(),
            links=FakeLinks(),
            clone=("qlf-abc", "es-MX", False),
        ),
        _presenter_brief(voice_id="brand"),
        uuid4(),
    )
    assert outcome.failure is None
    assert not any(u.model_id == "seed-icl-2.0-slot" for u in outcome.usage)


@pytest.mark.parametrize(
    ("voice_id", "clone", "words"),
    [
        ("brand", None, "no está lista"),  # never cloned, or not ready yet
        ("qlf-another-brand", ("qlf-mine", "es", False), "no está disponible para esta marca"),
        ("made-up", None, "no está disponible para esta marca"),
    ],
)
def test_a_voice_the_brand_may_not_use_is_refused_before_any_spend(
    voice_id: str, clone: tuple[str, str, bool] | None, words: str
) -> None:
    seedream, speech, omni = FakeSeedream(), FakeSpeech(), FakeOmniHuman()
    outcome = _produce(
        _presenter(
            _store(), seedream=seedream, speech=speech, omni=omni, links=FakeLinks(), clone=clone
        ),
        _presenter_brief(voice_id=voice_id),
        uuid4(),
    )
    assert outcome.failure == FailureReason.ROUTE_BLOCKED_BY_POLICY.value
    assert words in outcome.detail
    assert seedream.requests == speech.requests == omni.requests == []
    assert outcome.usage == ()


def test_without_a_public_url_the_presenter_fails_before_any_spend() -> None:
    seedream = FakeSeedream()
    outcome = _produce(
        _presenter(_store(), seedream=seedream, speech=FakeSpeech(), omni=FakeOmniHuman()),
        _presenter_brief(voice_id=PUBLIC_VOICE),
        uuid4(),
    )
    assert outcome.failure == FailureReason.INVALID_PARAMETERS.value
    assert outcome.detail == AVATAR_NO_PUBLIC_URL
    assert seedream.requests == [] and outcome.usage == ()


def test_a_voice_track_too_long_for_omnihuman_stops_before_the_render() -> None:
    omni = FakeOmniHuman()
    outcome = _produce(
        _presenter(
            _store(),
            seedream=FakeSeedream(),
            speech=FakeSpeech(),
            omni=omni,
            links=FakeLinks(),
            max_seconds=1.0,
        ),
        _presenter_brief(voice_id=PUBLIC_VOICE),
        uuid4(),
    )
    assert outcome.failure == FailureReason.INVALID_PARAMETERS.value
    assert outcome.detail == AVATAR_SCRIPT_TOO_LONG and omni.requests == []
    # what was already made is billed: the presenter and the voice
    assert [u.provider for u in outcome.usage] == ["seedream", "seed_speech"]


def test_an_omnihuman_refusal_reads_as_the_content_filter() -> None:
    outcome = _produce(
        _presenter(
            _store(),
            seedream=FakeSeedream(),
            speech=FakeSpeech(),
            omni=FakeOmniHuman(fail="OmniHumanError: OmniHuman answered HTTP 200 code 50510"),
            links=FakeLinks(),
        ),
        _presenter_brief(voice_id=PUBLIC_VOICE),
        uuid4(),
    )
    assert outcome.failure == FailureReason.PROVIDER_ERROR.value
    assert outcome.detail == FILTERED_TEXT
    assert [u.provider for u in outcome.usage] == ["seedream", "seed_speech"]


def test_an_animated_character_from_an_image_leads_the_references() -> None:
    store, seedream = _store(), FakeSeedream()
    character, product = f"uploads/{TENANT_ID}/mascota.png", f"uploads/{TENANT_ID}/p1.jpg"
    outcome = _produce(
        _presenter(
            store, seedream=seedream, speech=FakeSpeech(), omni=FakeOmniHuman(), links=FakeLinks()
        ),
        _brief(
            ContentKind.ANIMATED_AVATAR_VIDEO,
            video_engine=VideoEngine.OMNIHUMAN,
            voice_id=PUBLIC_VOICE,
            avatar_source=AvatarSource.IMAGE,
            avatar_image_key=character,
            avatar_rights_confirmed=True,
            product_keys=(product,),
        ),
        uuid4(),
    )
    assert outcome.failure is None, outcome.detail
    (scene,) = seedream.requests
    assert len(scene.params["images"]) == 2  # the character first, then the product
    assert outcome.media[0].params["avatar_source"] == "image"


class NotReadyLinks(FakeLinks):
    """The production linker without a public base URL (a local run, no tunnel)."""

    def ready(self) -> bool:
        return False


def test_without_a_reachable_public_url_nothing_is_paid_for() -> None:
    seedream, speech, omni = FakeSeedream(), FakeSpeech(), FakeOmniHuman()
    outcome = _produce(
        _presenter(_store(), seedream=seedream, speech=speech, omni=omni, links=NotReadyLinks()),
        _presenter_brief(voice_id=PUBLIC_VOICE),
        uuid4(),
    )
    assert outcome.detail == AVATAR_NO_PUBLIC_URL
    assert seedream.requests == speech.requests == omni.requests == []
    assert outcome.usage == ()


def test_an_omnihuman_timeout_still_records_the_render_it_will_bill() -> None:
    outcome = _produce(
        _presenter(
            _store(),
            seedream=FakeSeedream(),
            speech=FakeSpeech(),
            omni=FakeOmniHuman(fail="OmniHumanTimeout: task 7392 still rendering after 2400s"),
            links=FakeLinks(),
        ),
        _presenter_brief(voice_id=PUBLIC_VOICE),
        uuid4(),
    )
    assert outcome.failure == FailureReason.PROVIDER_ERROR.value
    assert "tardando" in outcome.detail
    render = outcome.usage[-1]
    assert (render.provider, render.model_id, render.unit) == (
        "omnihuman",
        "omnihuman-1-5",
        "second",
    )
    assert render.cost_usd > 0

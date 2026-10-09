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
    SlideSource,
    SlideText,
    VideoEngine,
)
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.providers import GenerationRequest, GenerationResult, ResolvedKey, Usage
from qualify_creative.router import BudgetContext, CreativeRouter
from qualify_creative.schemas import (
    BrandKit,
    CarouselSlide,
    ContentBrief,
    CopyPayload,
    MediaInputs,
    ToneAxes,
)
from qualify_creative.video import FittedVideo

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
    ) -> FittedVideo:
        self.calls.append({"data": data, "size": size, "overlay": overlay})
        return FittedVideo(
            data=b"fitted-" + data,
            width=size[0],
            height=size[1],
            duration_sec=5.0,
            poster=_image((1, 2, 3), size),
        )


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

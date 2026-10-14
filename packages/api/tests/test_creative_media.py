"""`qualify_api.creative.media.MediaProducer` without the network: what each content kind
turns a brief and its copy into (§ request 2026-09-25). HeyGen is a scripted fake that
is both the `GenerationProvider` the real `CreativeRouter` runs and the upload / prompt
avatar tools; pricing is the real v2 table, so the recorded costs are the real rates."""

from __future__ import annotations

import io
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from PIL import Image
from qualify_creative.enums import (
    AvatarSource,
    BriefObjective,
    ContentFormat,
    ContentKind,
    FailureReason,
    GenerationTask,
    ImageRoute,
    PaidBy,
)
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.providers import GenerationRequest, GenerationResult, ResolvedKey, Usage
from qualify_creative.router import BudgetContext, CreativeRouter
from qualify_creative.schemas import BrandKit, ContentBrief, CopyPayload, MediaInputs, ToneAxes

from qualify_api.creative import media as media_module
from qualify_api.creative.media import (
    ANIMATED_STYLE,
    HUMAN_STYLE,
    LocalMediaStore,
    MediaProducer,
    MediaWrite,
    generated_key,
    generated_object_key,
    heygen_failure_text,
    owned_by,
    template_port,
)

TENANT_ID = UUID("7e7e0000-0000-4000-8000-000000000001")
BRAND_ID = UUID("7e7e0000-0000-4000-8000-000000000002")
BUDGET = BudgetContext(remaining_usd=Decimal("100"))
COPY = CopyPayload(
    hook="Smash doble",
    caption="La smash más jugosa del barrio, con queso americano y pan brioche.",
    cta="Pide ya por DM",
    script="Hola. Esta es la smash doble: carne aplastada, queso fundido. Pídela hoy.",
)


def _png(color: tuple[int, int, int, int] = (200, 40, 40, 255)) -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", (300, 300), color).save(out, format="PNG")
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


class FakeHeyGen:
    """The provider the router runs AND the non-render tools."""

    name = "heygen"
    supports = frozenset({GenerationTask.AVATAR_VIDEO})

    def __init__(self, *, fail_render: bool = False, estimate: Decimal = Decimal("1")) -> None:
        self.fail_render = fail_render
        self.estimate = estimate
        self.uploads: list[tuple[str, str]] = []
        self.prompts: list[str] = []
        self.waited: list[str] = []
        self.requests: list[GenerationRequest] = []
        self.keys: list[str] = []

    def upload_asset(self, *, api_key: str, file_bytes: bytes, filename: str, **_: Any) -> dict:
        self.keys.append(api_key)
        self.uploads.append((filename, f"as_{len(self.uploads) + 1}"))
        return {"asset_id": f"as_{len(self.uploads)}"}

    def create_prompt_avatar(self, *, api_key: str, name: str, prompt: str, **_: Any) -> str:
        self.prompts.append(prompt)
        return "lk_generated"

    def wait_for_look(self, look_id: str, *, api_key: str) -> dict:
        self.waited.append(look_id)
        return {"id": look_id, "status": "completed"}

    def generate(self, request: GenerationRequest, *, api_key: str) -> GenerationResult:
        self.keys.append(api_key)
        self.requests.append(request)
        if self.fail_render:
            raise RuntimeError("render failed")
        image = "image_asset_id" in request.params
        return GenerationResult(
            payload={
                "video_id": "v_1",
                "video_url": "https://heygen/v_1.mp4",
                "thumbnail_url": "https://heygen/v_1.jpg",
                "duration_seconds": "12.5",
            },
            model_id="heygen_image" if image else "heygen_avatar_iv",
            provider="heygen",
            usage=Usage(pieces=1, media_seconds=Decimal("12.5")),
            model_revision=None if image else "avatar_iv",
            media_url="https://heygen/v_1.mp4",
        )

    def estimate_cost_usd(self, request: GenerationRequest, pricing: Any, **_: Any) -> Decimal:
        return self.estimate


class KeysByProvider:
    def resolve(self, *, tenant_id: UUID, brand_id: UUID, provider: str) -> ResolvedKey:
        return ResolvedKey(api_key=f"key-{provider}", paid_by=PaidBy.PLATFORM, fingerprint="fp")


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
        topic="Smash doble",
        image_route=ImageRoute.TEMPLATE_ONLY,
        kind=kind,
        format=fmt or kind.default_format,
        media=MediaInputs(**media),  # type: ignore[arg-type]
    )


def _producer(
    store: MemoryStore,
    heygen: FakeHeyGen | None,
    downloads: dict[str, bytes] | None = None,
    voice_guard: Any = None,
) -> MediaProducer:
    pricing = JsonPricingTable("v2")
    providers = {"heygen": heygen} if heygen is not None else {}
    router = CreativeRouter(providers, pricing, KeysByProvider())  # type: ignore[arg-type]

    def download(url: str) -> bytes:
        if downloads is None:
            return b"mp4-bytes" if url.endswith(".mp4") else b"jpg-bytes"
        return downloads[url]

    return MediaProducer(
        store=store,
        router=router,
        credentials=KeysByProvider(),
        pricing=pricing,
        heygen=heygen,
        download=download,
        voice_guard=voice_guard,
    )


def _produce(producer: MediaProducer, brief: ContentBrief, draft_id: UUID) -> Any:
    return producer.produce(
        tenant_id=TENANT_ID, draft_id=draft_id, brief=brief, kit=_kit(), copy=COPY, budget=BUDGET
    )


# --------------------------------------------------------------------------------------


def test_a_creator_script_has_no_media_and_costs_nothing() -> None:
    outcome = _produce(
        _producer(MemoryStore(), FakeHeyGen()), _brief(ContentKind.CREATOR_SCRIPT), uuid4()
    )
    assert outcome.media == () and outcome.usage == () and outcome.failure is None


def test_a_flyer_is_rendered_locally_and_stored_for_the_draft() -> None:
    store = MemoryStore(
        {
            f"uploads/{TENANT_ID}/p1.png": _png(),
            f"uploads/{TENANT_ID}/bg.png": _png((0, 90, 0, 255)),
        }
    )
    draft_id = uuid4()
    brief = _brief(
        ContentKind.STATIC_FLYER,
        product_keys=(f"uploads/{TENANT_ID}/p1.png",),
        background_key=f"uploads/{TENANT_ID}/bg.png",
    )
    outcome = _produce(_producer(store, None), brief, draft_id)

    assert outcome.failure is None and outcome.usage == ()  # local: free, no vendor
    (image,) = outcome.media
    assert image.media_type == "image" and image.position == 0
    # § 2026-10-05: stored as JPEG (real JPEG bytes, labelled as such) — Meta takes no PNG
    assert image.media_url == generated_key(TENANT_ID, draft_id, "slide-1.jpg")
    assert store.files[image.media_url][:3] == b"\xff\xd8\xff"
    assert image.content_type == "image/jpeg"
    assert (image.width, image.height, image.aspect_ratio) == (1080, 1350, "4:5")
    assert image.provider == "local" and image.params["background"] is True


def test_a_carousel_stores_its_slides_in_order() -> None:
    store = MemoryStore({f"uploads/{TENANT_ID}/p{i}.png": _png() for i in range(3)})
    brief = _brief(
        ContentKind.STATIC_FLYER,
        product_keys=tuple(f"uploads/{TENANT_ID}/p{i}.png" for i in range(3)),
        carousel=True,
    )
    outcome = _produce(_producer(store, None), brief, uuid4())
    assert [m.position for m in outcome.media] == [0, 1, 2, 3]
    assert all(m.params["slides"] == 4 for m in outcome.media)
    assert all(
        m.content_type == "image/jpeg" and m.media_url.endswith(".jpg") for m in outcome.media
    )


def test_an_avatar_video_composes_the_scene_renders_and_keeps_the_file() -> None:
    store = MemoryStore(
        {
            f"uploads/{TENANT_ID}/p1.png": _png(),
            f"uploads/{TENANT_ID}/bg.png": _png((0, 90, 0, 255)),
        }
    )
    heygen = FakeHeyGen()
    draft_id = uuid4()
    brief = _brief(
        ContentKind.AVATAR_VIDEO,
        avatar_look_id="lk_stock",
        voice_id="vo_es",
        product_keys=(f"uploads/{TENANT_ID}/p1.png",),
        background_key=f"uploads/{TENANT_ID}/bg.png",
    )
    outcome = _produce(_producer(store, heygen), brief, draft_id)

    assert outcome.failure is None
    # background + product composed into ONE image, uploaded as a HeyGen asset
    assert heygen.uploads == [("scene.png", "as_1")]
    (request,) = heygen.requests
    params = request.params
    assert params["avatar_id"] == "lk_stock" and params["voice_id"] == "vo_es"
    assert params["background_image_asset_id"] == "as_1"
    assert params["script"] == COPY.script
    assert (params["aspect_ratio"], params["resolution"]) == ("9:16", "1080p")
    assert set(heygen.keys) == {"key-heygen"}  # HeyGen's key, never Anthropic's

    (video,) = outcome.media
    assert video.media_type == "video" and video.aspect_ratio == "9:16"
    assert video.content_type == "video/mp4"  # the Planificador refuses a NULL type
    assert store.files[generated_key(TENANT_ID, draft_id, "video.mp4")] == b"mp4-bytes"
    assert video.params["thumbnail_key"] == generated_key(TENANT_ID, draft_id, "thumbnail.jpg")
    assert video.params["background_composed"] is True

    (usage,) = outcome.usage
    # 12.5 s × $0.0667/s (v2 heygen_avatar_iv 1080p), per second
    assert (usage.unit, usage.quantity) == ("second", 13)
    assert usage.cost_usd == Decimal("0.833750")


def test_an_avatar_video_without_images_keeps_the_avatars_own_background() -> None:
    heygen = FakeHeyGen()
    brief = _brief(ContentKind.AVATAR_VIDEO, avatar_look_id="lk", voice_id="vo")
    outcome = _produce(_producer(MemoryStore(), heygen), brief, uuid4())
    assert outcome.failure is None and heygen.uploads == []
    assert "background_image_asset_id" not in heygen.requests[0].params


def test_an_ai_animated_avatar_is_generated_waited_for_and_paid_for() -> None:
    heygen = FakeHeyGen()
    brief = _brief(
        ContentKind.ANIMATED_AVATAR_VIDEO,
        voice_id="vo",
        avatar_source=AvatarSource.AI,
        avatar_prompt="Una hamburguesa sonriente con gorra roja",
    )
    outcome = _produce(_producer(MemoryStore(), heygen), brief, uuid4())

    assert outcome.failure is None
    assert heygen.prompts == [ANIMATED_STYLE + "Una hamburguesa sonriente con gorra roja"]
    assert heygen.waited == ["lk_generated"]
    assert heygen.requests[0].params["avatar_id"] == "lk_generated"
    models = [(u.model_id, u.unit, u.cost_usd) for u in outcome.usage]
    assert models[0] == ("heygen_prompt_avatar", "piece", Decimal("0.50"))
    assert models[1][0] == "heygen_avatar_iv"
    assert outcome.spent_usd == Decimal("0.50") + Decimal("0.833750")


def test_a_custom_human_avatar_is_a_photoreal_prompt_avatar() -> None:
    heygen = FakeHeyGen()
    brief = _brief(
        ContentKind.AVATAR_VIDEO,
        voice_id="vo",
        avatar_source=AvatarSource.AI,
        avatar_prompt="Mujer de unos 30 años, pelo rizado, blusa verde",
    )
    outcome = _produce(_producer(MemoryStore(), heygen), brief, uuid4())

    assert outcome.failure is None
    # the human style, not the animated one
    assert heygen.prompts == [HUMAN_STYLE + "Mujer de unos 30 años, pelo rizado, blusa verde"]
    assert heygen.waited == ["lk_generated"]
    assert heygen.requests[0].params["avatar_id"] == "lk_generated"
    assert outcome.usage[0].model_id == "heygen_prompt_avatar"


def test_an_animated_avatar_from_an_image_animates_the_upload() -> None:
    store = MemoryStore({f"uploads/{TENANT_ID}/mascota.png": _png((250, 200, 0, 255))})
    heygen = FakeHeyGen()
    brief = _brief(
        ContentKind.ANIMATED_AVATAR_VIDEO,
        voice_id="vo",
        avatar_source=AvatarSource.IMAGE,
        avatar_image_key=f"uploads/{TENANT_ID}/mascota.png",
        avatar_rights_confirmed=True,
    )
    outcome = _produce(_producer(store, heygen), brief, uuid4())

    assert outcome.failure is None
    assert heygen.uploads == [("avatar.png", "as_1")]
    params = heygen.requests[0].params
    assert params["image_asset_id"] == "as_1" and "avatar_id" not in params
    assert outcome.usage[0].model_id == "heygen_image"
    assert outcome.usage[0].cost_usd == Decimal("0.625000")  # 12.5 s × $0.05
    assert outcome.media[0].params["subject"] == "image"


def test_without_heygen_a_video_fails_with_a_reason_and_nothing_spent() -> None:
    brief = _brief(ContentKind.AVATAR_VIDEO, avatar_look_id="lk", voice_id="vo")
    outcome = _produce(_producer(MemoryStore(), None), brief, uuid4())
    assert outcome.failure == "provider_error"
    assert outcome.detail == "La generación no está disponible ahora mismo. Avisa al equipo."
    assert outcome.usage == ()


def test_a_render_over_budget_is_blocked_before_heygen_renders() -> None:
    heygen = FakeHeyGen(estimate=Decimal("5"))
    producer = _producer(MemoryStore(), heygen)
    brief = _brief(ContentKind.AVATAR_VIDEO, avatar_look_id="lk", voice_id="vo")
    outcome = producer.produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=brief,
        kit=_kit(),
        copy=COPY,
        budget=BudgetContext(remaining_usd=Decimal("1"), hard_stop=True),
    )
    assert outcome.failure == "budget_exceeded" and heygen.requests == []


def test_a_failed_render_is_a_provider_error_and_keeps_the_prompt_avatars_cost() -> None:
    heygen = FakeHeyGen(fail_render=True)
    brief = _brief(
        ContentKind.ANIMATED_AVATAR_VIDEO,
        voice_id="vo",
        avatar_source=AvatarSource.AI,
        avatar_prompt="Un chef bigotón",
    )
    outcome = _produce(_producer(MemoryStore(), heygen), brief, uuid4())
    assert outcome.failure == "provider_error"
    assert [u.model_id for u in outcome.usage] == ["heygen_prompt_avatar"]  # money spent
    assert outcome.media == ()


def test_a_video_that_cannot_be_downloaded_fails_but_its_render_is_billed() -> None:
    heygen = FakeHeyGen()
    brief = _brief(ContentKind.AVATAR_VIDEO, avatar_look_id="lk", voice_id="vo")
    outcome = _produce(_producer(MemoryStore(), heygen, downloads={}), brief, uuid4())
    assert outcome.failure == "provider_error" and outcome.media == ()
    assert [u.model_id for u in outcome.usage] == ["heygen_avatar_iv"]


def test_a_missing_upload_fails_the_flyer_with_a_reason() -> None:
    brief = _brief(ContentKind.STATIC_FLYER, product_keys=(f"uploads/{TENANT_ID}/gone.png",))
    outcome = _produce(_producer(MemoryStore(), None), brief, uuid4())
    assert outcome.failure == "provider_error"
    assert outcome.detail == "No se pudo generar la pieza. Inténtalo de nuevo."
    assert "gone.png" not in outcome.detail  # the raw error goes to the log, not the operator


def test_the_local_store_refuses_keys_outside_its_root(tmp_path: Any) -> None:
    store = LocalMediaStore(tmp_path)
    store.write("generated/t/d/slide-1.png", b"x")
    assert store.read("generated/t/d/slide-1.png") == b"x"
    with pytest.raises(ValueError):
        store.read("../../etc/passwd")


def test_the_chosen_format_sizes_the_flyer_and_the_video() -> None:
    store = MemoryStore({f"uploads/{TENANT_ID}/p1.png": _png()})
    square = _brief(
        ContentKind.STATIC_FLYER,
        ContentFormat.FEED_1_1,
        product_keys=(f"uploads/{TENANT_ID}/p1.png",),
    )
    (image,) = _produce(_producer(store, None), square, uuid4()).media
    assert (image.width, image.height, image.aspect_ratio) == (1080, 1080, "1:1")

    heygen = FakeHeyGen()
    story = _brief(
        ContentKind.AVATAR_VIDEO, ContentFormat.STORY_9_16, avatar_look_id="lk", voice_id="vo"
    )
    (video,) = _produce(_producer(MemoryStore(), heygen), story, uuid4()).media
    assert heygen.requests[0].params["aspect_ratio"] == "9:16"
    assert video.aspect_ratio == "9:16"

    feed = _brief(
        ContentKind.AVATAR_VIDEO, ContentFormat.FEED_4_5, avatar_look_id="lk", voice_id="vo"
    )
    heygen = FakeHeyGen()
    _produce(_producer(MemoryStore(), heygen), feed, uuid4())
    assert heygen.requests[0].params["aspect_ratio"] == "4:5"


# --------------------------------------------------------------------------------------
# ported from the HeyGen smoke-test panel (2026-09-25)
# --------------------------------------------------------------------------------------


def test_the_operators_own_script_is_read_word_for_word_on_the_chosen_engine() -> None:
    heygen = FakeHeyGen()
    brief = _brief(
        ContentKind.AVATAR_VIDEO,
        avatar_look_id="lk",
        voice_id="vo",
        own_script="Hola, soy Doña Rosa y hoy hay torta de tres leches.",
        engine="avatar_iii",
    )
    _produce(_producer(MemoryStore(), heygen), brief, uuid4())
    params = heygen.requests[0].params
    assert params["script"] == "Hola, soy Doña Rosa y hoy hay torta de tres leches."
    assert params["engine"] == "avatar_iii"


def test_an_image_subject_carries_no_engine() -> None:
    store = MemoryStore({f"uploads/{TENANT_ID}/m.png": _png()})
    heygen = FakeHeyGen()
    brief = _brief(
        ContentKind.ANIMATED_AVATAR_VIDEO,
        voice_id="vo",
        avatar_source=AvatarSource.IMAGE,
        avatar_image_key=f"uploads/{TENANT_ID}/m.png",
        avatar_rights_confirmed=True,
        engine="avatar_iii",
    )
    _produce(_producer(store, heygen), brief, uuid4())
    assert "engine" not in heygen.requests[0].params  # HeyGen's image mode is Avatar IV


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "HeyGenAPIError: HTTP 402 insufficient_credit: Insufficient credit",
            "no está disponible ahora mismo",
        ),
        ("HeyGenRenderTimeout: render v_1 still running after 480s", "tardando más de lo normal"),
        ("HeyGenRenderFailed: HeyGen render v_1 failed: moderation_failed", "filtro de contenido"),
        ("HeyGenRenderFailed: HeyGen render v_1 failed: boom", "No se pudo generar la pieza"),
        ("HeyGenAPIError: HTTP 401 unauthorized", "no está disponible ahora mismo"),
        ("HeyGenAPIError: HTTP 429 too many", "muchas generaciones en curso"),
        ("no HeyGen key: QUALIFY_HEYGEN_API_KEY unset", "no está disponible ahora mismo"),
        ("something else entirely", "No se pudo generar la pieza. Inténtalo de nuevo."),
    ],
)
def test_heygen_failures_are_explained_in_spanish(raw: str, expected: str) -> None:
    text = heygen_failure_text(raw)
    assert expected in text
    # the vendor's raw error and any vendor / env var name stay in the log
    assert raw[:40] not in text
    for word in ("HeyGen", "QUALIFY_", "créditos", "USD"):
        assert word not in text


def test_a_failed_render_says_why_in_the_outcome() -> None:
    heygen = FakeHeyGen(fail_render=True)
    brief = _brief(ContentKind.AVATAR_VIDEO, avatar_look_id="lk", voice_id="vo")
    outcome = _produce(_producer(MemoryStore(), heygen), brief, uuid4())
    assert outcome.failure == "provider_error"
    assert outcome.detail == "No se pudo generar la pieza. Inténtalo de nuevo."
    assert "render failed" not in outcome.detail and "HeyGen" not in outcome.detail


# -- the voice guard (§ request 2026-10-05) -----------------------------------------------------


def test_a_voice_the_guard_refuses_is_a_policy_failure_that_spends_nothing() -> None:
    """Another brand's cloned voice (or a made-up id) never reaches HeyGen: refused before
    any upload or render, as `route_blocked_by_policy`, with nothing billed."""
    seen: list[tuple[UUID, UUID, str, str]] = []

    def guard(*, tenant_id: UUID, brand_id: UUID, voice_id: str, api_key: str) -> bool:
        seen.append((tenant_id, brand_id, voice_id, api_key))
        return voice_id == "vo_mine"

    heygen = FakeHeyGen()
    producer = _producer(MemoryStore(), heygen, voice_guard=guard)
    refused = _produce(
        producer,
        _brief(ContentKind.AVATAR_VIDEO, avatar_look_id="lk", voice_id="vo_theirs"),
        uuid4(),
    )
    assert refused.failure == FailureReason.ROUTE_BLOCKED_BY_POLICY.value
    assert "no está disponible para esta marca" in (refused.detail or "")
    assert refused.media == () and refused.usage == () and refused.spent_usd == 0
    assert heygen.requests == [] and heygen.uploads == []
    assert seen == [(TENANT_ID, BRAND_ID, "vo_theirs", "key-heygen")]

    allowed = _produce(
        producer,
        _brief(ContentKind.AVATAR_VIDEO, avatar_look_id="lk", voice_id="vo_mine"),
        uuid4(),
    )
    assert allowed.failure is None and len(heygen.requests) == 1
    assert heygen.requests[0].params["voice_id"] == "vo_mine"


# --------------------------------------------------------------------------------------
# the template kind (plan-mvp-plantillas-remotion.md §2): one run, ONE output since
# 2026-10-06 — the one of the brief's format
# --------------------------------------------------------------------------------------

from qualify_creative.enums import ContentType  # noqa: E402
from qualify_creative.render import TemplateManifest, TemplateRegistry  # noqa: E402
from qualify_creative.render.adapter import MODEL_ID as REMOTION_MODEL  # noqa: E402
from qualify_creative.render.client import RenderServiceError  # noqa: E402
from qualify_creative.render.props import ProductFacts  # noqa: E402

_PROMO = TemplateManifest.model_validate(
    {
        "id": "promo_producto",
        "version": 1,
        "name": "Promo de producto",
        "niche": ["shawarma", "helado"],
        "serves_angles": ["product", "promotion", "price"],
        "inputs": {
            "hook": {"type": "string", "max": 60},
            "price_line": {"type": "string", "max": 24, "optional": True},
            "cta": {"type": "string", "max": 40},
            "photos": {"type": "image[]", "min": 2, "max": 4},
            "brand": {"type": "brand_kit"},
        },
        "outputs": {
            "reel": {
                "kind": "video",
                "width": 1080,
                "height": 1920,
                "composition": "promo-producto-v1--reel",
            },
            "feed": {
                "kind": "still",
                "width": 1080,
                "height": 1350,
                "composition": "promo-producto-v1--feed",
            },
            "story": {
                "kind": "still",
                "width": 1080,
                "height": 1920,
                "composition": "promo-producto-v1--story",
            },
        },
    }
)


class FakeRemotion:
    """Stands in for `RemotionTemplateAdapter`: records the request, answers like the
    adapter does (bytes per completed port, typed reasons for the failed ones)."""

    name = "remotion"

    def __init__(self, fail_ports: tuple[str, ...] = (), error: RenderServiceError | None = None):
        self.requests: list[GenerationRequest] = []
        self.fail_ports = fail_ports
        self.error = error

    def generate(self, request: GenerationRequest, *, api_key: str) -> GenerationResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        # like the service, only the outputs asked for are rendered
        ports = tuple(request.params.get("outputs") or ("reel", "feed", "story"))
        outputs = {
            p: {
                # the render service answers a still with real PNG bytes (with alpha:
                # the stored JPEG must flatten it), a video with its MP4
                "bytes": f"{p}-bytes".encode() if p == "reel" else _png((10, 120, 60, 128)),
                "mime_type": "video/mp4" if p == "reel" else "image/png",
                "width": 1080,
                "height": 1350 if p == "feed" else 1920,
                "duration_sec": 12.5 if p == "reel" else None,
                "kind": "video" if p == "reel" else "still",
            }
            for p in ports
            if p not in self.fail_ports
        }
        failed = {
            p: {"failure_reason": "render_error", "error_message": "Chromium crashed"}
            for p in self.fail_ports
            if p in ports
        }
        return GenerationResult(
            payload={
                "job_id": request.params["job_id"],
                "status": "failed" if failed else "completed",
                "duration_sec": 12.5,
                "warnings": [],
                "outputs": outputs,
                "failed_ports": failed,
            },
            model_id=REMOTION_MODEL,
            provider="remotion",
            usage=Usage(pieces=len(outputs), media_seconds=Decimal("12.5")),
        )


class FakeCatalog:
    def __init__(self, products: tuple[ProductFacts, ...] = ()) -> None:
        self.products = products

    def products_for(self, *, tenant_id: UUID, brand_id: UUID, product_ref: str | None):
        return self.products if product_ref else ()


def _template_producer(
    store: MemoryStore,
    remotion: FakeRemotion | None,
    *,
    registry: TemplateRegistry | None = None,
    catalog: FakeCatalog | None = None,
) -> MediaProducer:
    pricing = JsonPricingTable("v2")
    router = CreativeRouter({}, pricing, KeysByProvider())  # type: ignore[arg-type]
    return MediaProducer(
        store=store,
        router=router,
        credentials=KeysByProvider(),
        pricing=pricing,
        heygen=None,
        remotion=remotion,  # type: ignore[arg-type]
        templates=registry if registry is not None else TemplateRegistry([_PROMO]),
        brand_names=lambda *, tenant_id, brand_id: "Bianki",
        catalog=catalog,
    )


def _template_brief(fmt: ContentFormat = ContentFormat.FEED_4_5, **media: object) -> ContentBrief:
    return ContentBrief(
        brand_id=BRAND_ID,
        objective=BriefObjective.SALE,
        content_type=ContentType.PROMOTION,
        topic="Shawarma mixto",
        product_ref="Shawarma mixto",
        image_route=ImageRoute.FROM_UPLOAD,
        source_media_key=f"uploads/{TENANT_ID}/a.jpg",
        kind=ContentKind.TEMPLATE,
        format=fmt,
        media=MediaInputs(**media),  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    ("fmt", "port"),
    [
        (ContentFormat.REELS_9_16, "reel"),
        (ContentFormat.FEED_4_5, "feed"),
        (ContentFormat.STORY_9_16, "story"),
    ],
)
def test_a_template_renders_only_the_output_of_its_format(fmt: ContentFormat, port: str) -> None:
    assert template_port(_PROMO, fmt) == port
    store = MemoryStore({f"uploads/{TENANT_ID}/a.jpg": b"a", f"uploads/{TENANT_ID}/b.jpg": b"b"})
    remotion = FakeRemotion()
    draft_id = uuid4()
    brief = _template_brief(
        fmt, product_keys=(f"uploads/{TENANT_ID}/a.jpg", f"uploads/{TENANT_ID}/b.jpg")
    )
    outcome = _produce(_template_producer(store, remotion), brief, draft_id)

    assert outcome.failure is None and outcome.partial_failures == {}
    (piece,) = outcome.media
    assert piece.output_port == port and piece.position == 0
    request = remotion.requests[0]
    assert request.params["outputs"] == [port] and request.params["render_count"] == 1
    run = outcome.template_run
    assert run is not None and run.status == "completed" and run.router_rule == "2"
    assert set(run.outputs) == {port} and run.outputs[port]["status"] == "completed"
    assert piece.template_run_id == run.id and request.params["job_id"] == str(run.id)
    assert run.actual_cost_usd == Decimal("0.00") and run.props["brand"]["name"] == "Bianki"
    (usage,) = outcome.usage
    assert usage.unit == "render" and usage.quantity == 1 and usage.cost_usd == Decimal("0.00")
    assert piece.provider == "remotion" and piece.model_id == REMOTION_MODEL
    assert piece.params["template_id"] == "promo_producto" and piece.params["router_rule"] == 2
    if port == "reel":
        assert piece.media_type == "video" and piece.content_type == "video/mp4"
        assert piece.media_url == generated_key(TENANT_ID, draft_id, "reel.mp4")
        assert store.files[piece.media_url] == b"reel-bytes"
        assert piece.params["duration_seconds"] == 12.5
    else:
        # § 2026-10-05: the stills are stored as JPEG — the only image format Meta takes
        assert piece.media_type == "image" and piece.content_type == "image/jpeg"
        assert piece.media_url.endswith(f"{port}.jpg")
        assert store.files[piece.media_url][:3] == b"\xff\xd8\xff"
    # the same draft and recipe always name the same job (idempotent retries)
    again = _produce(_template_producer(store, FakeRemotion()), brief, draft_id)
    assert again.template_run is not None and again.template_run.id == run.id


def test_a_template_without_that_format_fails_with_a_reason() -> None:
    reel_only = _PROMO.model_copy(update={"outputs": {"reel": _PROMO.outputs["reel"]}})
    assert template_port(reel_only, ContentFormat.FEED_4_5) is None
    assert template_port(reel_only, ContentFormat.REELS_9_16) == "reel"
    store = MemoryStore({f"uploads/{TENANT_ID}/a.jpg": b"a", f"uploads/{TENANT_ID}/b.jpg": b"b"})
    remotion = FakeRemotion()
    outcome = _produce(
        _template_producer(store, remotion, registry=TemplateRegistry([reel_only])),
        _template_brief(
            ContentFormat.FEED_4_5,
            product_keys=(f"uploads/{TENANT_ID}/a.jpg", f"uploads/{TENANT_ID}/b.jpg"),
        ),
        uuid4(),
    )
    assert outcome.failure == FailureReason.INVALID_PARAMETERS.value
    assert "no tiene salida feed_4_5" in outcome.detail and remotion.requests == []


def test_a_template_whose_output_failed_keeps_the_runs_evidence() -> None:
    store = MemoryStore({f"uploads/{TENANT_ID}/a.jpg": b"a", f"uploads/{TENANT_ID}/b.jpg": b"b"})
    outcome = _produce(
        _template_producer(store, FakeRemotion(fail_ports=("feed",))),
        _template_brief(product_keys=(f"uploads/{TENANT_ID}/a.jpg", f"uploads/{TENANT_ID}/b.jpg")),
        uuid4(),
    )
    assert outcome.media == ()
    assert outcome.partial_failures["feed"]["failure_reason"] == "render_error"
    run = outcome.template_run
    assert run is not None and run.status == "failed"
    assert run.outputs["feed"]["status"] == "failed" and run.failure_reason == "render_error"


def test_props_that_break_the_manifest_fail_before_the_service_is_called() -> None:
    store = MemoryStore({f"uploads/{TENANT_ID}/a.jpg": b"a", f"uploads/{TENANT_ID}/b.jpg": b"b"})
    remotion = FakeRemotion()
    producer = _template_producer(store, remotion)
    long_cta = CopyPayload(hook="Hoy", caption="c", cta="x" * 41)
    outcome = producer.produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=_template_brief(
            product_keys=(f"uploads/{TENANT_ID}/a.jpg", f"uploads/{TENANT_ID}/b.jpg")
        ),
        kit=_kit(),
        copy=long_cta,
        budget=BUDGET,
    )
    assert outcome.failure == FailureReason.INVALID_PARAMETERS.value
    assert outcome.detail == "El llamado a la acción es demasiado largo para la plantilla."
    # the manifest's own message is kept on the run row, for the team
    assert "'cta' has 41 chars" in (outcome.template_run.error_message or "")
    assert remotion.requests == [] and outcome.media == ()
    assert outcome.template_run is not None and outcome.template_run.status == "failed"
    assert outcome.template_run.failure_reason == "invalid_parameters"


def test_too_few_photos_means_no_template_and_a_readable_reason() -> None:
    store = MemoryStore({f"uploads/{TENANT_ID}/a.jpg": b"a"})
    outcome = _produce(
        _template_producer(store, FakeRemotion()),
        _template_brief(product_keys=(f"uploads/{TENANT_ID}/a.jpg",)),
        uuid4(),
    )
    assert outcome.failure == FailureReason.ROUTE_BLOCKED_BY_POLICY.value
    assert "necesita 2 fotos" in outcome.detail


def test_the_catalog_photos_complete_the_briefs_own_upload() -> None:
    store = MemoryStore({f"uploads/{TENANT_ID}/a.jpg": b"a", "cat/mixto-1.jpg": b"c"})
    catalog = FakeCatalog(
        (ProductFacts(name="Shawarma mixto", price_label="$5", photo_keys=("cat/mixto-1.jpg",)),)
    )
    remotion = FakeRemotion()
    outcome = _produce(
        _template_producer(store, remotion, catalog=catalog),
        _template_brief(product_keys=(f"uploads/{TENANT_ID}/a.jpg",)),
        uuid4(),
    )
    assert outcome.failure is None and len(outcome.media) == 1
    props = remotion.requests[0].params["props"]
    assert props.photos == (f"key://uploads/{TENANT_ID}/a.jpg", "key://cat/mixto-1.jpg")
    assert props.texts["price_line"] == "$5" and props.products[0].name == "Shawarma mixto"


def test_the_operator_may_pin_a_template_and_the_rule_is_then_none() -> None:
    store = MemoryStore({f"uploads/{TENANT_ID}/a.jpg": b"a", f"uploads/{TENANT_ID}/b.jpg": b"b"})
    outcome = _produce(
        _template_producer(store, FakeRemotion()),
        _template_brief(
            product_keys=(f"uploads/{TENANT_ID}/a.jpg", f"uploads/{TENANT_ID}/b.jpg"),
            template_id="promo_producto",
            template_version=1,
        ),
        uuid4(),
    )
    assert outcome.failure is None
    assert outcome.template_run is not None and outcome.template_run.router_rule is None
    unknown = _produce(
        _template_producer(store, FakeRemotion()),
        _template_brief(
            product_keys=(f"uploads/{TENANT_ID}/a.jpg", f"uploads/{TENANT_ID}/b.jpg"),
            template_id="nope",
        ),
        uuid4(),
    )
    assert unknown.failure == FailureReason.INVALID_PARAMETERS.value


def test_a_service_error_fails_the_draft_with_the_services_reason() -> None:
    store = MemoryStore({f"uploads/{TENANT_ID}/a.jpg": b"a", f"uploads/{TENANT_ID}/b.jpg": b"b"})
    error = RenderServiceError("dependency_failed", 500, "asset a1 could not be fetched")
    outcome = _produce(
        _template_producer(store, FakeRemotion(error=error)),
        _template_brief(product_keys=(f"uploads/{TENANT_ID}/a.jpg", f"uploads/{TENANT_ID}/b.jpg")),
        uuid4(),
    )
    assert outcome.failure == FailureReason.DEPENDENCY_FAILED.value
    assert outcome.template_run is not None and outcome.template_run.status == "failed"
    assert outcome.template_run.error_message == "asset a1 could not be fetched"
    assert outcome.detail == "No se pudo generar la pieza. Inténtalo de nuevo."


def test_without_the_render_service_a_template_fails_with_a_reason() -> None:
    store = MemoryStore({f"uploads/{TENANT_ID}/a.jpg": b"a", f"uploads/{TENANT_ID}/b.jpg": b"b"})
    outcome = _produce(
        _template_producer(store, None),
        _template_brief(product_keys=(f"uploads/{TENANT_ID}/a.jpg", f"uploads/{TENANT_ID}/b.jpg")),
        uuid4(),
    )
    assert outcome.failure == FailureReason.PROVIDER_ERROR.value
    assert outcome.detail == "La generación no está disponible ahora mismo. Avisa al equipo."


# --------------------------------------------------------------------------------------
# «Recursos de tu marca» (§ 2026-10-06): the chosen logo takes the brand mark's place
# --------------------------------------------------------------------------------------


def test_a_chosen_logo_is_composed_into_the_avatars_scene() -> None:
    """With nothing else to compose, the logo alone is enough for a branded scene."""
    logo_key = f"t/{TENANT_ID}/brand/iso.png"
    store = MemoryStore({logo_key: _png((200, 30, 30, 255))})
    heygen = FakeHeyGen()
    brief = _brief(
        ContentKind.AVATAR_VIDEO, avatar_look_id="lk", voice_id="vo", brand_logo_key=logo_key
    )
    outcome = _produce(_producer(store, heygen), brief, uuid4())
    assert outcome.failure is None
    assert heygen.uploads == [("scene.png", "as_1")]  # a scene WAS composed, for the logo
    assert heygen.requests[0].params["background_image_asset_id"] == "as_1"


def test_the_chosen_logo_takes_the_templates_logo_slot() -> None:
    logo_key = f"t/{TENANT_ID}/brand/iso.png"
    store = MemoryStore(
        {
            f"uploads/{TENANT_ID}/a.jpg": b"a",
            f"uploads/{TENANT_ID}/b.jpg": b"b",
            logo_key: _png((200, 30, 30, 255)),
        }
    )
    remotion = FakeRemotion()
    brief = _template_brief(
        product_keys=(f"uploads/{TENANT_ID}/a.jpg", f"uploads/{TENANT_ID}/b.jpg"),
        brand_logo_key=logo_key,
    )
    outcome = _produce(_template_producer(store, remotion), brief, uuid4())
    assert outcome.failure is None
    assert remotion.requests[0].params["props"].brand.logo == f"key://{logo_key}"


# --------------------------------------------------------------------------------------
# R2 (§ 2026-10-06, pendientes-generador-contenido.md §1): every generated file lives
# in R2 only, under the tenant's prefix and unique per generation — no local copy
# --------------------------------------------------------------------------------------


class R2Store(MemoryStore):
    """A store that can keep a durable copy (`R2ReadingMediaStore.keep`)."""

    def __init__(self, files: dict[str, bytes] | None = None, *, up: bool = True) -> None:
        super().__init__(files)
        self.kept: dict[str, tuple[bytes, str]] = {}
        self.up = up

    def keep(self, tenant_id: UUID, key: str, data: bytes, content_type: str) -> bool:
        assert key.startswith(f"t/{tenant_id}/")  # always under the tenant's own prefix
        if not self.up:
            return False
        self.kept[key] = (data, content_type)
        return True


def _produce_revision(producer: MediaProducer, brief: ContentBrief, draft_id: UUID, rev: int):
    return producer.produce(
        tenant_id=TENANT_ID,
        draft_id=draft_id,
        brief=brief,
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
        revision=rev,
    )


def test_a_flyer_lives_in_r2_only_one_object_per_generation() -> None:
    store = R2Store({f"uploads/{TENANT_ID}/p1.png": _png()})
    draft_id = uuid4()
    brief = _brief(ContentKind.STATIC_FLYER, product_keys=(f"uploads/{TENANT_ID}/p1.png",))
    (first,) = _produce_revision(_producer(store, None), brief, draft_id, 1).media
    (again,) = _produce_revision(_producer(store, None), brief, draft_id, 2).media

    key = generated_object_key(TENANT_ID, draft_id, 1, "slide-1.jpg")
    assert key == f"t/{TENANT_ID}/generated/{draft_id}/r1/slide-1.jpg"
    assert (first.media_url, first.object_key) == (key, key)  # shown AND published from R2
    data, content_type = store.kept[key]
    assert content_type == "image/jpeg" and data[:3] == b"\xff\xd8\xff"
    # § 2026-10-06 "no me sirve tenerlo en local": nothing is written to the disk
    assert set(store.files) == {f"uploads/{TENANT_ID}/p1.png"}
    # a regeneration never overwrites the object an approved revision may point at
    assert again.object_key.endswith("/r2/slide-1.jpg") and key in store.kept


def test_a_piece_r2_refuses_fails_and_says_so() -> None:
    store = R2Store({f"uploads/{TENANT_ID}/p1.png": _png()}, up=False)
    brief = _brief(ContentKind.STATIC_FLYER, product_keys=(f"uploads/{TENANT_ID}/p1.png",))
    outcome = _produce_revision(_producer(store, None), brief, uuid4(), 1)
    assert outcome.media == () and outcome.failure == FailureReason.PROVIDER_ERROR.value
    assert "No pudimos guardar la pieza en R2" in outcome.detail
    assert set(store.files) == {f"uploads/{TENANT_ID}/p1.png"} and store.kept == {}


def test_an_avatar_video_and_its_poster_live_in_r2() -> None:
    store = R2Store()
    draft_id = uuid4()
    brief = _brief(ContentKind.AVATAR_VIDEO, avatar_look_id="lk", voice_id="vo")
    (video,) = _produce_revision(_producer(store, FakeHeyGen()), brief, draft_id, 3).media
    key = generated_object_key(TENANT_ID, draft_id, 3, "video.mp4")
    assert (video.media_url, video.object_key) == (key, key)
    assert store.kept[key] == (b"mp4-bytes", "video/mp4")
    poster = generated_object_key(TENANT_ID, draft_id, 3, "thumbnail.jpg")
    assert video.params["thumbnail_key"] == poster and store.kept[poster][1] == "image/jpeg"
    assert store.files == {}  # nothing on the disk


def test_a_template_output_keeps_its_r2_copy() -> None:
    store = R2Store({f"uploads/{TENANT_ID}/a.jpg": b"a", f"uploads/{TENANT_ID}/b.jpg": b"b"})
    draft_id = uuid4()
    brief = _template_brief(
        ContentFormat.REELS_9_16,
        product_keys=(f"uploads/{TENANT_ID}/a.jpg", f"uploads/{TENANT_ID}/b.jpg"),
    )
    outcome = _template_producer(store, FakeRemotion()).produce(
        tenant_id=TENANT_ID,
        draft_id=draft_id,
        brief=brief,
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
        revision=2,
    )
    (reel,) = outcome.media
    assert reel.object_key == generated_object_key(TENANT_ID, draft_id, 2, "reel.mp4")
    assert store.kept[reel.object_key] == (b"reel-bytes", "video/mp4")


def test_the_r2_store_keeps_through_the_gate_and_never_raises() -> None:
    import io as _io

    from qualify_api.creative.media import R2ReadingMediaStore

    class Gate:
        def __init__(self, fail: bool = False) -> None:
            self.puts: list[tuple[UUID, str, bytes, str]] = []
            self.fail = fail

        def put_media(self, tenant_id: UUID, key: str, fileobj: _io.BytesIO, ctype: str):
            if self.fail:
                raise RuntimeError("R2 down")
            self.puts.append((tenant_id, key, fileobj.read(), ctype))

    gate = Gate()
    store = R2ReadingMediaStore(MemoryStore(), gate)
    key = f"t/{TENANT_ID}/generated/d/r1/video.mp4"
    assert store.keep(TENANT_ID, key, b"mp4", "video/mp4") is True
    assert gate.puts == [(TENANT_ID, key, b"mp4", "video/mp4")]
    assert (
        R2ReadingMediaStore(MemoryStore(), Gate(fail=True)).keep(
            TENANT_ID, key, b"mp4", "video/mp4"
        )
        is False
    )


def test_the_posts_preview_is_the_key_the_app_shows() -> None:
    from qualify_api.creative.service import preview_of

    image = MediaWrite(
        position=0,
        media_type="image",
        media_url="generated/t/d/slide-1.jpg",
        object_key=f"t/{TENANT_ID}/generated/d/r1/slide-1.jpg",
        width=1080,
        height=1350,
        aspect_ratio="4:5",
        model_id="local",
        provider="local",
    )
    assert preview_of((image,)) == "generated/t/d/slide-1.jpg"


# -- a piece reads only its own brand's files (PR #100 review) ---------------------------

_OTHER_TENANT = UUID("0b0b0000-0000-4000-8000-0000000000ff")


@pytest.mark.parametrize(
    ("key", "owned"),
    [
        (f"t/{TENANT_ID}/brand/logo.png", True),
        (f"uploads/{TENANT_ID}/a.jpg", True),
        (f"generated/{TENANT_ID}/d/flyer.jpg", True),
        (f"t/{_OTHER_TENANT}/brand/logo.png", False),
        (f"uploads/{_OTHER_TENANT}/a.jpg", False),
        (f"uploads/{TENANT_ID}/../{_OTHER_TENANT}/a.jpg", False),
        (f"uploads/{TENANT_ID}/..\\{_OTHER_TENANT}/a.jpg", False),  # Windows separator
        (f"uploads/{TENANT_ID}\\a.jpg", False),
        (f"secrets/{TENANT_ID}/a.jpg", False),
        ("", False),
    ],
)
def test_a_file_is_the_brands_only_under_its_own_prefix(key: str, owned: bool) -> None:
    assert owned_by(TENANT_ID, key) is owned


def test_a_backslash_traversal_cannot_read_another_tenants_file(tmp_path: Any) -> None:
    """PR #100 review, reproduced on Windows 2026-10-10: `uploads/<a>/..\\<b>/x.jpg` passed
    `owned_by` (a `/`-only split sees no `..` segment) and `Path` read the backslash as
    a separator, so tenant a read tenant b's file. Refused before the filesystem is
    touched — on every platform, not only where the backslash separates."""
    store = LocalMediaStore(tmp_path)
    store.write(f"uploads/{_OTHER_TENANT}/secret.jpg", b"tenant-b")
    store.write(f"uploads/{TENANT_ID}/mine.jpg", b"tenant-a")
    key = f"uploads/{TENANT_ID}/..\\{_OTHER_TENANT}/secret.jpg"

    assert owned_by(TENANT_ID, key) is False
    with pytest.raises(ValueError):
        store.read(key)
    assert store.read(f"uploads/{TENANT_ID}/mine.jpg") == b"tenant-a"  # its own, still


@pytest.mark.parametrize(
    "key",
    [
        "uploads/x.jpg",  # no tenant directory
        f"uploads/{TENANT_ID}",  # the tenant directory itself
        f"uploads/{TENANT_ID}//a.jpg",
        f"uploads/{TENANT_ID}/./a.jpg",
        f"uploads\\{TENANT_ID}\\a.jpg",
    ],
)
def test_the_local_store_takes_only_tenant_rooted_posix_keys(key: str, tmp_path: Any) -> None:
    store = LocalMediaStore(tmp_path)
    with pytest.raises(ValueError):
        store.read(key)
    with pytest.raises(ValueError):
        store.write(key, b"x")
    assert list(tmp_path.iterdir()) == []  # nothing was created on the way


class _CountingStore(MemoryStore):
    def __init__(self, files: dict[str, bytes] | None = None) -> None:
        super().__init__(files)
        self.reads: list[str] = []

    def read(self, key: str) -> bytes:
        self.reads.append(key)
        return super().read(key)


@pytest.mark.parametrize(
    "media",
    [
        {"background_key": f"uploads/{_OTHER_TENANT}/local.jpg"},
        {"product_keys": (f"uploads/{TENANT_ID}/a.jpg", f"t/{_OTHER_TENANT}/p.jpg")},
        {"brand_element_keys": (f"t/{_OTHER_TENANT}/brand/sello.png",)},
    ],
)
def test_another_brands_file_is_refused_before_any_read_or_spend(media: dict) -> None:
    """A key in a brief can come from the browser: one of another brand never reaches
    the store, the vendor or the budget — the piece fails saying why."""
    store = _CountingStore({f"uploads/{TENANT_ID}/a.jpg": b"a"})
    heygen = FakeHeyGen()
    outcome = _produce(
        _producer(store, heygen),
        _brief(ContentKind.STATIC_FLYER, **media),
        uuid4(),
    )
    assert outcome.failure == FailureReason.ROUTE_BLOCKED_BY_POLICY.value
    assert outcome.detail == "Uno de los archivos de la pieza no es de tu marca."
    assert store.reads == [] and outcome.spent_usd == 0
    assert heygen.requests == [] and heygen.uploads == []


@pytest.mark.parametrize(
    "key",
    [
        f"uploads/{TENANT_ID}//bg.jpg",  # an empty segment
        f"uploads/{TENANT_ID}/./bg.jpg",
        f"uploads/{TENANT_ID}\\bg.jpg",  # a Windows separator
        f"uploads/{TENANT_ID}",  # the directory, not a file
    ],
)
def test_a_malformed_own_key_is_refused_as_a_bad_path_not_as_another_brands(key: str) -> None:
    """PR #100 review: a key that is the tenant's but not a path we serve must not be
    reported — to the operator or in the log — as another brand's file."""
    store = _CountingStore()
    outcome = _produce(
        _producer(store, FakeHeyGen()),
        _brief(ContentKind.STATIC_FLYER, background_key=key),
        uuid4(),
    )
    assert outcome.failure == FailureReason.INVALID_PARAMETERS.value
    assert outcome.detail == (
        "Uno de los archivos de la pieza tiene una ruta que no es válida. Vuelve a elegirlo."
    )
    assert store.reads == [] and outcome.spent_usd == 0


@pytest.mark.skipif(
    not media_module._FOLD_CASE, reason="case-sensitive file system: a different path"
)
def test_the_local_store_reads_a_key_that_differs_from_its_directory_only_in_case(
    tmp_path: Any,
) -> None:
    """PR #100 review: on Windows / macOS `resolve()` returns the on-disk spelling, which
    must not make a legitimate key look as if it escaped its tenant's directory."""
    store = LocalMediaStore(tmp_path)
    store.write(f"uploads/{TENANT_ID}/a.jpg", b"a")
    assert store.read(f"Uploads/{str(TENANT_ID).upper()}/a.jpg") == b"a"

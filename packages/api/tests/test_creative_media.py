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
    ContentKind,
    GenerationTask,
    ImageRoute,
    PaidBy,
)
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.providers import GenerationRequest, GenerationResult, ResolvedKey, Usage
from qualify_creative.router import BudgetContext, CreativeRouter
from qualify_creative.schemas import BrandKit, ContentBrief, CopyPayload, MediaInputs, ToneAxes

from qualify_api.creative.media import (
    ANIMATED_STYLE,
    LocalMediaStore,
    MediaProducer,
    generated_key,
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


def _brief(kind: ContentKind, **media: object) -> ContentBrief:
    return ContentBrief(
        brand_id=BRAND_ID,
        objective=BriefObjective.SALE,
        topic="Smash doble",
        image_route=ImageRoute.TEMPLATE_ONLY,
        kind=kind,
        media=MediaInputs(**media),  # type: ignore[arg-type]
    )


def _producer(
    store: MemoryStore, heygen: FakeHeyGen | None, downloads: dict[str, bytes] | None = None
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
    store = MemoryStore({"uploads/t/p1.png": _png(), "uploads/t/bg.png": _png((0, 90, 0, 255))})
    draft_id = uuid4()
    brief = _brief(
        ContentKind.STATIC_FLYER,
        product_keys=("uploads/t/p1.png",),
        background_key="uploads/t/bg.png",
    )
    outcome = _produce(_producer(store, None), brief, draft_id)

    assert outcome.failure is None and outcome.usage == ()  # local: free, no vendor
    (image,) = outcome.media
    assert image.media_type == "image" and image.position == 0
    assert image.media_url == generated_key(TENANT_ID, draft_id, "slide-1.png")
    assert store.files[image.media_url].startswith(b"\x89PNG")
    assert (image.width, image.height, image.aspect_ratio) == (1080, 1350, "4:5")
    assert image.provider == "local" and image.params["background"] is True


def test_a_carousel_stores_its_slides_in_order() -> None:
    store = MemoryStore({f"uploads/t/p{i}.png": _png() for i in range(3)})
    brief = _brief(
        ContentKind.STATIC_FLYER,
        product_keys=tuple(f"uploads/t/p{i}.png" for i in range(3)),
        carousel=True,
    )
    outcome = _produce(_producer(store, None), brief, uuid4())
    assert [m.position for m in outcome.media] == [0, 1, 2, 3]
    assert all(m.params["slides"] == 4 for m in outcome.media)


def test_an_avatar_video_composes_the_scene_renders_and_keeps_the_file() -> None:
    store = MemoryStore({"uploads/t/p1.png": _png(), "uploads/t/bg.png": _png((0, 90, 0, 255))})
    heygen = FakeHeyGen()
    draft_id = uuid4()
    brief = _brief(
        ContentKind.AVATAR_VIDEO,
        avatar_look_id="lk_stock",
        voice_id="vo_es",
        product_keys=("uploads/t/p1.png",),
        background_key="uploads/t/bg.png",
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


def test_an_animated_avatar_from_an_image_animates_the_upload() -> None:
    store = MemoryStore({"uploads/t/mascota.png": _png((250, 200, 0, 255))})
    heygen = FakeHeyGen()
    brief = _brief(
        ContentKind.ANIMATED_AVATAR_VIDEO,
        voice_id="vo",
        avatar_source=AvatarSource.IMAGE,
        avatar_image_key="uploads/t/mascota.png",
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
    assert outcome.failure == "provider_error" and "not configured" in outcome.detail
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
    brief = _brief(ContentKind.STATIC_FLYER, product_keys=("uploads/t/gone.png",))
    outcome = _produce(_producer(MemoryStore(), None), brief, uuid4())
    assert outcome.failure == "provider_error" and "gone.png" in outcome.detail


def test_the_local_store_refuses_keys_outside_its_root(tmp_path: Any) -> None:
    store = LocalMediaStore(tmp_path)
    store.write("generated/t/d/slide-1.png", b"x")
    assert store.read("generated/t/d/slide-1.png") == b"x"
    with pytest.raises(ValueError):
        store.read("../../etc/passwd")

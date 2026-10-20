"""`qualify_api.creative.media.MediaProducer` without the network: what each content kind
turns a brief and its copy into (§ request 2026-09-25). The real `CreativeRouter` runs
spy vendors; pricing is the real v2 table, so the recorded costs are the real rates. The
talking presenter (OmniHuman + Seed Speech, since HeyGen's retirement on 2026-10-16) is
tested in `test_creative_media_byteplus.py`, next to Seedream and Seedance."""

from __future__ import annotations

import io
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from PIL import Image
from qualify_creative.enums import (
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
    RETIRED_ENGINE_TEXT,
    LocalMediaStore,
    MediaProducer,
    MediaWrite,
    avatar_failure_text,
    generated_key,
    generated_object_key,
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


class SpyVendor:
    """A vendor that records every call — the refusal tests assert it was never reached
    (HeyGen's double until 2026-10-16; the talking presenter's own tests live in
    `test_creative_media_byteplus.py`, next to Seedream's and Seedance's)."""

    name = "seedream"
    supports = frozenset({GenerationTask.PRODUCT_IMAGE, GenerationTask.AVATAR_VIDEO})

    def __init__(self) -> None:
        self.requests: list[GenerationRequest] = []
        self.uploads: list[str] = []

    def generate(self, request: GenerationRequest, *, api_key: str) -> GenerationResult:
        self.requests.append(request)
        raise RuntimeError("a refused piece must never reach a vendor")

    def estimate_cost_usd(self, request: GenerationRequest, pricing: Any, **_: Any) -> Decimal:
        return Decimal("0")


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
    vendor: SpyVendor | None = None,
    downloads: dict[str, bytes] | None = None,
) -> MediaProducer:
    pricing = JsonPricingTable("v2")
    providers = {vendor.name: vendor} if vendor is not None else {}
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
        download=download,
    )


def _produce(producer: MediaProducer, brief: ContentBrief, draft_id: UUID) -> Any:
    return producer.produce(
        tenant_id=TENANT_ID, draft_id=draft_id, brief=brief, kit=_kit(), copy=COPY, budget=BUDGET
    )


# --------------------------------------------------------------------------------------


def test_a_creator_script_has_no_media_and_costs_nothing() -> None:
    outcome = _produce(
        _producer(MemoryStore(), SpyVendor()), _brief(ContentKind.CREATOR_SCRIPT), uuid4()
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


# --------------------------------------------------------------------------------------
# HeyGen, retired 2026-10-16: an old brief is refused, never rendered
# --------------------------------------------------------------------------------------


def test_a_brief_stored_with_heygen_is_refused_without_spending() -> None:
    vendor = SpyVendor()
    brief = _brief(ContentKind.AVATAR_VIDEO, avatar_look_id="lk", voice_id="vo")
    assert brief.media.video_engine.value == "heygen"  # what an old stored brief reads as
    outcome = _produce(_producer(MemoryStore(), vendor), brief, uuid4())
    assert outcome.failure == "provider_error" and outcome.detail == RETIRED_ENGINE_TEXT
    assert outcome.usage == () and vendor.requests == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "SeedSpeechNotConfigured: QUALIFY_BYTEPLUS_SPEECH_API_KEY is not set",
            "no está disponible",
        ),
        ("MissingPlatformKey: QUALIFY_BYTEPLUS_CV_API_KEY", "no está disponible"),
        (
            "OmniHumanError: OmniHuman answered HTTP 200 code 50510: pre-filter",
            "filtro de contenido",
        ),
        (
            "OmniHumanError: OmniHuman answered HTTP 200 code 50400: Access Denied",
            "no está disponible",
        ),
        ("SeedSpeechError: code 45000000: speaker permission denied", "no está disponible"),
        ("OmniHumanTimeout: task 7392 still rendering after 2400s", "tardando más de lo normal"),
        ("quota exceeded for types: concurrency", "muchas generaciones en curso"),
        ("something else entirely", "No se pudo generar la pieza. Inténtalo de nuevo."),
    ],
)
def test_the_presenters_failures_are_explained_in_spanish(raw: str, expected: str) -> None:
    text = avatar_failure_text(raw)
    assert expected in text
    # the vendor's raw error and any vendor / env var name stay in the log
    for word in ("OmniHuman", "Seed", "QUALIFY_", "BytePlus", "USD"):
        assert word not in text


# --------------------------------------------------------------------------------------
# ported from the HeyGen smoke-test panel (2026-09-25)
# --------------------------------------------------------------------------------------


# -- the voice guard (§ request 2026-10-05) -----------------------------------------------------


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


def _is_video(port: str) -> bool:
    return port == "reel" or port.endswith("-video")


#: promo_producto v2's outputs (2026-10-13): the 4:5 / 1:1 videos and the 1:1 still.
_PROMO_V2 = TemplateManifest.model_validate(
    {
        **_PROMO.model_dump(mode="json", by_alias=True),
        "version": 2,
        "outputs": {
            port: {
                "kind": kind,
                "width": 1080,
                "height": height,
                "composition": f"promo-producto-v2--{port}",
            }
            for port, kind, height in (
                ("reel", "video", 1920),
                ("feed-video", "video", 1350),
                ("square-video", "video", 1080),
                ("feed", "still", 1350),
                ("square", "still", 1080),
                ("story", "still", 1920),
            )
        },
    }
)


@pytest.mark.parametrize(
    ("fmt", "video", "port"),
    [
        (ContentFormat.REELS_9_16, None, "reel"),
        (ContentFormat.REELS_9_16, True, "reel"),
        (ContentFormat.STORY_9_16, True, "reel"),  # a Story video is the 9:16 one
        (ContentFormat.FEED_4_5, True, "feed-video"),
        (ContentFormat.FEED_1_1, True, "square-video"),
        (ContentFormat.FEED_4_5, None, "feed"),
        (ContentFormat.FEED_1_1, False, "square"),
        (ContentFormat.STORY_9_16, None, "story"),
    ],
)
def test_the_template_port_follows_the_format_and_video_or_still(
    fmt: ContentFormat, video: bool | None, port: str
) -> None:
    assert template_port(_PROMO_V2, fmt, video=video) == port


def test_an_ad_video_in_the_feed_renders_the_templates_4_5_video() -> None:
    """§ 2026-10-13: «Video publicitario» as a Post 4:5 is the template's 4:5 video."""
    store = MemoryStore({f"uploads/{TENANT_ID}/a.jpg": b"a", f"uploads/{TENANT_ID}/b.jpg": b"b"})
    remotion = FakeRemotion()
    draft_id = uuid4()
    brief = _template_brief(
        ContentFormat.FEED_4_5,
        product_keys=(f"uploads/{TENANT_ID}/a.jpg", f"uploads/{TENANT_ID}/b.jpg"),
        template_video=True,
    )
    outcome = _produce(
        _template_producer(store, remotion, registry=TemplateRegistry([_PROMO_V2])),
        brief,
        draft_id,
    )
    assert outcome.failure is None
    (piece,) = outcome.media
    assert piece.output_port == "feed-video" and piece.media_type == "video"
    assert remotion.requests[0].params["outputs"] == ["feed-video"]


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
                "bytes": f"{p}-bytes".encode() if _is_video(p) else _png((10, 120, 60, 128)),
                "mime_type": "video/mp4" if _is_video(p) else "image/png",
                "width": 1080,
                "height": {"feed": 1350, "feed-video": 1350}.get(
                    p, 1080 if p.startswith("square") else 1920
                ),
                "duration_sec": 12.5 if _is_video(p) else None,
                "kind": "video" if _is_video(p) else "still",
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
    assert "no tiene imagen en feed_4_5" in outcome.detail and remotion.requests == []


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
    vendor = SpyVendor()
    outcome = _produce(
        _producer(store, vendor),
        _brief(ContentKind.STATIC_FLYER, **media),
        uuid4(),
    )
    assert outcome.failure == FailureReason.ROUTE_BLOCKED_BY_POLICY.value
    assert outcome.detail == "Uno de los archivos de la pieza no es de tu marca."
    assert store.reads == [] and outcome.spent_usd == 0
    assert vendor.requests == []


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
        _producer(store, SpyVendor()),
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


# -- stock (plan-integracion-stock §5.2, R2 2026-10-16) -----------------------------------------

STOCK_KEY = f"t/{TENANT_ID}/stock/pixabay/8434113/abcdef0123456789.jpg"


def test_a_stock_product_photo_goes_whatever_the_product_source() -> None:
    """2026-10-19: «Inspiración» feeds every slot, the product photos included, so the
    guard no longer reads `product_source` (a flag the client sets is not a permission):
    the flyer goes ahead with a stock product photo either way."""
    store = MemoryStore({STOCK_KEY: _png()})
    for source in ("catalog", "stock"):
        brief = _brief(ContentKind.STATIC_FLYER, product_keys=(STOCK_KEY,), product_source=source)
        outcome = _produce(_producer(store, None), brief, uuid4())
        assert outcome.failure is None and len(outcome.media) == 1


@pytest.mark.parametrize(
    "media",
    [
        {"avatar_image_key": STOCK_KEY, "avatar_rights_confirmed": True},
        {"brand_logo_key": STOCK_KEY},
        {"brand_element_keys": (STOCK_KEY,)},
    ],
)
def test_stock_never_goes_where_the_brand_or_a_real_file_belongs(media: dict[str, object]) -> None:
    vendor = SpyVendor()
    brief = _brief(ContentKind.STATIC_FLYER, product_source="stock", **media)
    outcome = _produce(_producer(MemoryStore({STOCK_KEY: _png()}), vendor), brief, uuid4())
    assert outcome.failure == FailureReason.ROUTE_BLOCKED_BY_POLICY.value
    assert vendor.requests == []


def test_a_clip_made_only_of_stock_is_refused() -> None:
    from qualify_api.stock.guard import STOCK_ONLY_CLIP_TEXT, stock_problems

    only_stock = _brief(ContentKind.CLIP, clip_image_keys=(STOCK_KEY,), clip_image_roles=("place",))
    assert stock_problems(only_stock) == STOCK_ONLY_CLIP_TEXT
    mixed = _brief(
        ContentKind.CLIP,
        clip_image_keys=(STOCK_KEY, f"uploads/{TENANT_ID}/p1.png"),
        clip_image_roles=("place", "product"),
    )
    assert stock_problems(mixed) is None
    as_product = _brief(ContentKind.CLIP, clip_image_keys=(STOCK_KEY, f"uploads/{TENANT_ID}/p.png"))
    assert stock_problems(as_product) is None  # stock in the product role, beside a real file


def test_the_ai_flag_off_keeps_stock_away_from_every_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.stock.guard import OFF_TEXT, stock_problems

    brief = _brief(ContentKind.STATIC_FLYER, background_key=STOCK_KEY)
    assert stock_problems(brief) is None
    monkeypatch.setenv("QUALIFY_STOCK_AI_REFERENCE", "off")
    assert stock_problems(brief) == OFF_TEXT
    unknown_bank = _brief(
        ContentKind.STATIC_FLYER,
        background_key=f"t/{TENANT_ID}/stock/vecteezy/1/abcdef0123456789.jpg",
    )
    monkeypatch.setenv("QUALIFY_STOCK_AI_REFERENCE", "on")
    assert stock_problems(unknown_bank) == OFF_TEXT


def test_an_animated_slide_takes_a_motion_reference_stock_included() -> None:
    """§ request 2026-10-19: «en la galería los videos solo para referencia» — only an
    animated slide carries a reference video, and the licence guard lets a stock one go
    there (it is followed, never shown)."""
    from qualify_creative.enums import SlideSource
    from qualify_creative.schemas import CarouselSlide

    from qualify_api.stock.guard import stock_problems

    video = f"t/{TENANT_ID}/stock/pixabay/video-1/abcdef0123456789.mp4"
    with pytest.raises(ValueError):
        CarouselSlide(source=SlideSource.GENERATED, reference_video_key=video)
    slide = CarouselSlide(source=SlideSource.ANIMATED, reference_video_key=video)
    brief = _brief(
        ContentKind.CAROUSEL, slides=(slide, CarouselSlide(source=SlideSource.GENERATED))
    )
    assert stock_problems(brief) is None

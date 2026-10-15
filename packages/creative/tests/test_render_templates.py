"""The template engine's Python half (`qualify_creative.render`): manifests and the
registry, props built from a Post and validated against the ports, the recipe router's
six rules, the HTTP client against a fake service and the adapter's multi-output
payload. Offline; the real service is exercised by `packages/render/scripts/smoke.sh`."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from qualify_creative.enums import (
    BriefObjective,
    ContentKind,
    ContentType,
    FailureReason,
    GenerationTask,
    ImageRoute,
)
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.providers import GenerationRequest, RenderedPrompt
from qualify_creative.render import (
    Engine,
    PostFacts,
    TemplateManifest,
    TemplateRegistry,
    build_props,
    default_templates_dir,
    suggest_recipes,
    validate_props,
)
from qualify_creative.render.adapter import MODEL_ID, RemotionTemplateAdapter
from qualify_creative.render.client import (
    JobStatus,
    RemotionRenderClient,
    RenderJob,
    RenderServiceError,
    to_failure_reason,
)
from qualify_creative.render.props import ProductFacts
from qualify_creative.render.registry import TemplateNotFound
from qualify_creative.schemas import ContentBrief, CopyPayload, MediaInputs

from .test_render_prompt import make_kit

BRAND_ID = UUID("a3b1c2d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d")
TENANT_ID = UUID("11111111-2222-4333-8444-555555555555")
DRAFT_ID = UUID("99999999-8888-4777-8666-555555555555")

PROMO: dict[str, Any] = {
    "id": "promo_producto",
    "version": 1,
    "name": "Promo de producto",
    "niche": ["shawarma", "helado"],
    "serves_angles": ["product", "new_product", "promotion", "price", "sold_out"],
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
    "duration": {"from": "script", "min_sec": 8, "max_sec": 30},
    "cost_model": {"seconds_per_video_sec": 2.0, "seconds_per_still": 4.0},
}

CORTE: dict[str, Any] = {
    "id": "corte_video",
    "version": 1,
    "name": "Corte de video real",
    "niche": ["shawarma", "helado"],
    "serves_angles": ["product", "promotion", "behind_scenes"],
    "inputs": {
        "hook": {"type": "string", "max": 60},
        "cta": {"type": "string", "max": 40},
        "video": {"type": "video"},
        "brand": {"type": "brand_kit"},
    },
    "outputs": {
        "reel": {
            "kind": "video",
            "width": 1080,
            "height": 1920,
            "composition": "corte-video-v1--reel",
        }
    },
}


@pytest.fixture
def templates_dir(tmp_path: Path) -> Path:
    for raw in (PROMO, CORTE):
        d = tmp_path / raw["id"]
        d.mkdir()
        (d / "manifest.json").write_text(json.dumps(raw), encoding="utf-8")
    return tmp_path


@pytest.fixture
def registry(templates_dir: Path) -> TemplateRegistry:
    return TemplateRegistry.from_dir(templates_dir)


def _brief(**media: object) -> ContentBrief:
    return ContentBrief(
        brand_id=BRAND_ID,
        objective=BriefObjective.SALE,
        content_type=ContentType.PROMOTION,
        topic="Shawarma mixto",
        image_route=ImageRoute.FROM_UPLOAD,
        source_media_key="uploads/t/shawarma-1.jpg",
        kind=ContentKind.TEMPLATE,
        media=MediaInputs(**media),  # type: ignore[arg-type]
    )


def _copy(hook: str = "El shawarma que se come con las dos manos") -> CopyPayload:
    return CopyPayload(hook=hook, caption="Hoy en la esquina gaucha.", cta="Pide el tuyo")


# --------------------------------------------------------------------------------------
# manifest + registry
# --------------------------------------------------------------------------------------


def test_manifest_requires_contract_composition_names() -> None:
    bad = json.loads(json.dumps(PROMO))
    bad["outputs"]["reel"]["composition"] = "PromoReel"
    with pytest.raises(ValidationError, match="requires 'promo-producto-v1--reel'"):
        TemplateManifest.model_validate(bad)


def test_manifest_counts_every_output_as_a_render() -> None:
    m = TemplateManifest.model_validate(PROMO)
    assert m.render_count == 3
    assert m.has_video_output
    assert m.required_photos() == (2, 4)
    assert m.outputs["feed"].aspect_ratio == "4:5"
    assert m.outputs["reel"].aspect_ratio == "9:16"
    assert m.outputs["reel"].media_type == "video" and m.outputs["feed"].media_type == "image"
    assert m.cost_model.eta_seconds(m.outputs, 15.0) == 38.0


def test_registry_finds_latest_and_pinned_versions(templates_dir: Path) -> None:
    v2 = json.loads(json.dumps(PROMO))
    v2["version"] = 2
    for port in v2["outputs"].values():
        port["composition"] = port["composition"].replace("-v1--", "-v2--")
    (templates_dir / "promo_producto" / "manifest.json").write_text(json.dumps(v2))
    (templates_dir / "promo_v1").mkdir()
    v1 = json.loads(json.dumps(PROMO))
    v1["id"] = "promo_v1"
    for port in v1["outputs"].values():
        port["composition"] = port["composition"].replace("promo-producto", "promo-v1")
    (templates_dir / "promo_v1" / "manifest.json").write_text(json.dumps(v1))

    reg = TemplateRegistry.from_dir(templates_dir)
    assert reg.get("promo_producto").version == 2
    assert reg.get("promo_producto", 2).key == "promo_producto@2"
    with pytest.raises(TemplateNotFound):
        reg.get("promo_producto", 7)
    with pytest.raises(TemplateNotFound):
        reg.get("nope")
    assert [m.id for m in reg.for_post(angle="promotion", niche="helado")] == [
        "corte_video",
        "promo_producto",
        "promo_v1",
    ]
    assert reg.for_post(angle="loyalty", niche="helado") == []


def test_registry_rejects_a_manifest_in_the_wrong_directory(templates_dir: Path) -> None:
    (templates_dir / "wrong").mkdir()
    (templates_dir / "wrong" / "manifest.json").write_text(json.dumps(PROMO))
    with pytest.raises(ValueError, match="does not match its directory"):
        TemplateRegistry.from_dir(templates_dir)


def test_the_published_templates_in_the_repo_parse() -> None:
    root = default_templates_dir()
    if not root.is_dir():
        pytest.skip("packages/render/templates not present in this checkout")
    reg = TemplateRegistry.from_dir(root)
    assert len(reg) >= 1
    for m in reg:
        for port in m.outputs:
            assert m.outputs[port].composition == m.composition_id(port)


# --------------------------------------------------------------------------------------
# props
# --------------------------------------------------------------------------------------


def test_props_come_from_the_post_and_validate_clean(registry: TemplateRegistry) -> None:
    manifest = registry.get("promo_producto")
    brief = _brief(product_keys=("uploads/t/a.jpg", "uploads/t/b.jpg"))
    kit = make_kit(palette_rgb=("#F4C2C2", "#5A2A27"), logo_asset_key="t/x/logo.png")
    product = ProductFacts(
        name="Shawarma mixto",
        price_label="$5",
        photo_keys=("uploads/t/b.jpg", "uploads/t/c.jpg"),
    )
    props = build_props(
        manifest=manifest,
        brief=brief,
        copy=_copy(),
        kit=kit,
        brand_name="Bianki",
        products=[product],
        tenant_id=TENANT_ID,
        draft_id=DRAFT_ID,
    )
    assert props.photos == (
        "key://uploads/t/a.jpg",
        "key://uploads/t/b.jpg",
        "key://uploads/t/c.jpg",
    )
    assert props.texts["hook"] == "El shawarma que se come con las dos manos"
    assert props.texts["price_line"] == "$5"
    assert props.brand.logo == "key://t/x/logo.png"
    assert props.brand.palette == ("#F4C2C2", "#5A2A27")
    assert props.brand.tone == "casual, llano, breve"
    assert props.meta["templateId"] == "promo_producto" and props.meta["angle"] == "promotion"
    assert props.video is None  # the promo template has no video port
    assert validate_props(manifest, props) == []
    assert props.unresolved() == props.media_refs()

    resolved = props.with_media(
        {"key://uploads/t/a.jpg": "asset://A", "key://t/x/logo.png": "asset://L"}
    )
    assert resolved.photos[0] == "asset://A" and resolved.brand.logo == "asset://L"
    assert resolved.unresolved() == ["key://uploads/t/b.jpg", "key://uploads/t/c.jpg"]
    payload = resolved.to_payload()
    assert payload["brand"]["logo"] == "asset://L" and payload["meta"]["port"] == ""


def test_props_problems_are_all_reported_before_any_render(registry: TemplateRegistry) -> None:
    manifest = registry.get("promo_producto")
    brief = _brief(product_keys=("uploads/t/a.jpg",))
    props = build_props(
        manifest=manifest,
        brief=brief,
        copy=CopyPayload(hook="Hoy", caption="c", cta="x" * 41),
        kit=make_kit(),
        brand_name="Bianki",
        products=[],
        tenant_id=TENANT_ID,
        draft_id=DRAFT_ID,
    )
    problems = {(p.port, p.code) for p in validate_props(manifest, props)}
    assert problems == {("cta", "too_long"), ("photos", "too_few")}


def test_a_cta_over_its_port_is_shortened_where_a_person_would_stop(
    registry: TemplateRegistry,
) -> None:
    """§ request 2026-10-08: «'cta' has 46 chars; the port allows 40» failed a render."""
    manifest = registry.get("promo_producto")
    brief = _brief(product_keys=("uploads/t/a.jpg", "uploads/t/b.jpg"))
    props = build_props(
        manifest=manifest,
        brief=brief,
        copy=CopyPayload(
            hook="Hoy", caption="c", cta="Escríbanos en el WhatsApp y se la montamos ya."
        ),
        kit=make_kit(),
        brand_name="Bianki",
        products=[],
        tenant_id=TENANT_ID,
        draft_id=DRAFT_ID,
    )
    assert props.texts["cta"] == "Escríbanos en el WhatsApp"
    assert validate_props(manifest, props) == []


@pytest.mark.parametrize(
    ("text", "fitted"),
    [
        ("Escríbenos al DM y te la armamos capa por capa hoy mismo.", "Escríbenos al DM"),
        ("Pide la tuya hoy por WhatsApp antes de que se acabe", "Pide la tuya hoy por WhatsApp"),
        ("Corta y cabe", "Corta y cabe"),
        ("x" * 41, "x" * 41),  # nowhere to cut: left for validate_props to report
    ],
)
def test_fit_text_never_ends_on_a_dangling_word(text: str, fitted: str) -> None:
    from qualify_creative.render.props import fit_text

    assert fit_text(text, 40) == fitted


def test_props_cap_photos_at_the_port_max_and_take_the_video_port(
    registry: TemplateRegistry,
) -> None:
    promo = registry.get("promo_producto")
    brief = _brief(product_keys=tuple(f"uploads/t/{i}.jpg" for i in range(6)))
    props = build_props(
        manifest=promo,
        brief=brief,
        copy=_copy(),
        kit=make_kit(),
        brand_name="Bianki",
        products=[],
        tenant_id=TENANT_ID,
        draft_id=DRAFT_ID,
    )
    assert len(props.photos) == 4

    corte = registry.get("corte_video")
    props = build_props(
        manifest=corte,
        brief=_brief(product_keys=("uploads/t/a.jpg",)),
        copy=_copy(),
        kit=make_kit(),
        brand_name="Bianki",
        products=[ProductFacts(name="x", video_keys=("uploads/t/clip.mov",))],
        tenant_id=TENANT_ID,
        draft_id=DRAFT_ID,
    )
    # The brief's own source media wins over the catalog's video for the video port.
    assert props.video == "key://uploads/t/shawarma-1.jpg"
    assert validate_props(corte, props) == []


def test_template_kind_is_enabled_and_needs_a_real_photo() -> None:
    assert ContentKind.TEMPLATE.enabled and ContentKind.TEMPLATE.multi_output
    assert not ContentKind.TEMPLATE.requires_ai_disclosure
    with pytest.raises(ValidationError, match="at least one product photo"):
        _brief()
    assert _brief(product_keys=("uploads/t/a.jpg",)).kind is ContentKind.TEMPLATE


# --------------------------------------------------------------------------------------
# recipe router
# --------------------------------------------------------------------------------------


def _facts(**overrides: Any) -> PostFacts:
    base: dict[str, Any] = {
        "angle": ContentType.PROMOTION,
        "photo_count": 2,
        "video_count": 0,
        "product_count": 1,
        "niche": "shawarma",
    }
    base.update(overrides)
    return PostFacts(**base)


def _suggested(options: list[Any]) -> Any:
    chosen = [o for o in options if o.suggested]
    assert len(chosen) == 1, options
    return chosen[0]


def test_rule_2_two_photos_no_video_is_the_promo_template(registry: TemplateRegistry) -> None:
    options = suggest_recipes(_facts(), registry)
    assert [o.engine for o in options] == [Engine.REMOTION, Engine.HEYGEN, Engine.UGC]
    chosen = _suggested(options)
    assert chosen.engine is Engine.REMOTION and chosen.rule == 2
    assert chosen.template_id == "promo_producto" and chosen.outputs == ("reel", "feed", "story")
    assert chosen.cost_usd_min == Decimal(0) and chosen.eta_sec == 38.0
    assert chosen.cost_label == "USD 0.00"
    heygen = options[1]
    assert not heygen.available and heygen.cost_label == "USD 0.50 a 2.00"
    assert not options[2].available


def test_rule_1_presenter_with_avatar_goes_to_heygen(registry: TemplateRegistry) -> None:
    chosen = _suggested(
        suggest_recipes(_facts(angle=ContentType.TESTIMONIAL, has_avatar=True), registry)
    )
    assert chosen.engine is Engine.HEYGEN and chosen.rule == 1


def test_rule_1_without_avatar_falls_through_to_rule_2(registry: TemplateRegistry) -> None:
    chosen = _suggested(suggest_recipes(_facts(angle=ContentType.TESTIMONIAL), registry))
    assert chosen.engine is Engine.REMOTION and chosen.rule == 2


def test_rule_3_a_real_video_picks_the_video_template(registry: TemplateRegistry) -> None:
    chosen = _suggested(suggest_recipes(_facts(video_count=1), registry))
    assert chosen.rule == 3 and chosen.template_id == "corte_video"
    assert chosen.outputs == ("reel",)


def test_rule_4_menu_angle_without_a_menu_template_uses_the_promo(
    registry: TemplateRegistry,
) -> None:
    # `menu_productos` is not published in this registry and `menu` is not among the
    # promo's declared angles: the promo still stands in (rule 6's universal fallback),
    # credited to rule 4 because that is the rule that fired. Better a plain promo than
    # no piece — and the recorded rule shows the menu template is missing.
    # With 2 photos rule 2 fires first — the rules are ordered and that order is the
    # product decision (backlog §3); a menu with photos IS a promo until the menu
    # template exists. With a single photo, rule 2 does not apply and rule 4 fires.
    chosen = _suggested(suggest_recipes(_facts(angle=ContentType.MENU, product_count=3), registry))
    assert chosen.rule == 2 and chosen.template_id == "promo_producto"
    lenient = json.loads(json.dumps(PROMO))
    lenient["inputs"]["photos"]["min"] = 1
    reg = TemplateRegistry([TemplateManifest.model_validate(lenient)])
    chosen = _suggested(
        suggest_recipes(_facts(angle=ContentType.MENU, product_count=3, photo_count=1), reg)
    )
    assert chosen.rule == 4 and chosen.template_id == "promo_producto"


def test_rule_5_no_assets_quotes_ugc_but_cannot_suggest_it(registry: TemplateRegistry) -> None:
    options = suggest_recipes(_facts(photo_count=0), registry)
    assert not options[2].available  # UGC quotes only
    assert not options[0].available  # the promo needs 2 photos
    assert all(not o.suggested for o in options)


def test_rule_6_one_photo_falls_back_to_the_promo_when_it_allows_it(
    templates_dir: Path,
) -> None:
    lenient = json.loads(json.dumps(PROMO))
    lenient["inputs"]["photos"]["min"] = 1
    (templates_dir / "promo_producto" / "manifest.json").write_text(json.dumps(lenient))
    reg = TemplateRegistry.from_dir(templates_dir)
    chosen = _suggested(suggest_recipes(_facts(photo_count=1), reg))
    assert chosen.rule == 6 and chosen.template_id == "promo_producto"


def test_a_monthly_cap_pushes_past_an_expensive_suggestion(registry: TemplateRegistry) -> None:
    chosen = _suggested(
        suggest_recipes(
            _facts(
                angle=ContentType.TESTIMONIAL, has_avatar=True, cap_remaining_usd=Decimal("0.10")
            ),
            registry,
        )
    )
    assert chosen.engine is Engine.REMOTION and chosen.rule == 2


def test_a_paid_runtime_prices_every_output(registry: TemplateRegistry) -> None:
    chosen = _suggested(
        suggest_recipes(_facts(), registry, remotion_cost_per_render_usd=Decimal("0.01"))
    )
    assert chosen.cost_usd_min == Decimal("0.03")


# --------------------------------------------------------------------------------------
# client + adapter against a fake service
# --------------------------------------------------------------------------------------


class _Response:
    def __init__(
        self, status: int, body: Any = None, content: bytes = b"", headers: dict | None = None
    ):
        self.status_code = status
        self._body = body
        self.content = content
        self.text = json.dumps(body) if body is not None else ""
        self.headers = headers or {}

    def json(self) -> Any:
        if self._body is None:
            raise ValueError("no json")
        return self._body


class FakeService:
    """CONTRACT §4 in memory: assets, one job per id, outputs completing one poll at a
    time so the status rollup and per-output states are observable."""

    def __init__(self) -> None:
        self.assets: dict[str, bytes] = {}
        self.jobs: dict[str, dict[str, Any]] = {}
        self.polls = 0
        self.cancelled: list[str] = []
        self.fail_port: str | None = None

    def __call__(self, **_: Any) -> FakeService:
        return self

    def __enter__(self) -> FakeService:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def get(self, path: str) -> _Response:
        if path == "/health":
            return _Response(200, {"ok": True, "bundleReady": True, "templates": []})
        if path.startswith("/jobs/") and "/outputs/" in path:
            _, _, job_id, _, port = path.split("/")
            job = self.jobs[job_id]
            if job["outputs"][port]["status"] != "completed":
                return _Response(409, {"error": "not_ready", "message": "still rendering"})
            ext = "mp4" if job["outputs"][port]["kind"] == "video" else "png"
            mime = "video/mp4" if ext == "mp4" else "image/png"
            return _Response(200, None, f"{port}-bytes".encode(), {"content-type": mime})
        if path.startswith("/jobs/"):
            job_id = path.split("/")[2]
            if job_id not in self.jobs:
                return _Response(404, {"error": "not_found", "message": job_id})
            self._advance(self.jobs[job_id])
            return _Response(200, self.jobs[job_id])
        raise AssertionError(path)

    def post(self, path: str, json: Any = None, files: Any = None) -> _Response:
        if path == "/assets":
            name, data, ctype = files["file"]
            asset_id = f"a{len(self.assets) + 1}"
            self.assets[asset_id] = data
            return _Response(
                201,
                {
                    "assetId": asset_id,
                    "url": f"/assets/{asset_id}",
                    "mimeType": ctype,
                    "bytes": len(data),
                },
            )
        if path == "/render":
            if json["jobId"] in self.jobs:
                return _Response(200, self.jobs[json["jobId"]])
            for ref in json["props"]["photos"]:
                assert ref.startswith("asset://"), ref
            ports = json.get("outputs") or ["reel", "feed", "story"]
            job = {
                "jobId": json["jobId"],
                "templateId": json["templateId"],
                "version": json["version"],
                "status": "pending",
                "outputs": {
                    p: {
                        "kind": "video" if p == "reel" else "still",
                        "status": "pending",
                        "progress": 0,
                    }
                    for p in ports
                },
                "durationSec": 12.5,
                "warnings": ["font 'Poppins' unavailable, used 'Inter'"],
            }
            self.jobs[json["jobId"]] = job
            return _Response(202, job)
        if path.endswith("/cancel"):
            job_id = path.split("/")[2]
            self.cancelled.append(job_id)
            self.jobs[job_id]["status"] = "cancelled"
            return _Response(200, self.jobs[job_id])
        raise AssertionError(path)

    def _advance(self, job: dict[str, Any]) -> None:
        self.polls += 1
        pending = [p for p, o in job["outputs"].items() if o["status"] in ("pending", "generating")]
        if not pending:
            return
        port = pending[0]
        out = job["outputs"][port]
        if out["status"] == "pending":
            out["status"] = "generating"
            out["progress"] = 0.5
            job["status"] = "generating"
            return
        if self.fail_port == port:
            out.update(
                status="failed", failureReason="render_error", errorMessage="Chromium crashed"
            )
        else:
            out.update(
                status="completed",
                progress=1,
                mimeType="video/mp4" if out["kind"] == "video" else "image/png",
                bytes=10,
                width=1080,
                height=1920 if port != "feed" else 1350,
                durationSec=12.5 if out["kind"] == "video" else None,
            )
        states = {o["status"] for o in job["outputs"].values()}
        if states <= {"completed", "failed"}:
            job["status"] = "failed" if "failed" in states else "completed"


def _client(service: FakeService) -> RemotionRenderClient:
    return RemotionRenderClient(
        "http://render:3200", http_factory=service, sleep=lambda _s: None, clock=_Clock()
    )


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        self.t += 1.0
        return self.t


def _request(props: Any, **extra: Any) -> GenerationRequest:
    params: dict[str, Any] = {
        "job_id": str(DRAFT_ID),
        "template_id": "promo_producto",
        "version": 1,
        "props": props,
        "render_count": 3,
    }
    params.update(extra)
    return GenerationRequest(
        task=GenerationTask.TEMPLATE_RENDER,
        rendered_prompt=RenderedPrompt("", "", ""),
        params=params,
    )


def _props(registry: TemplateRegistry) -> Any:
    return build_props(
        manifest=registry.get("promo_producto"),
        brief=_brief(product_keys=("uploads/t/a.jpg", "uploads/t/b.jpg")),
        copy=_copy(),
        kit=make_kit(logo_asset_key="t/x/logo.png"),
        brand_name="Bianki",
        products=[],
        tenant_id=TENANT_ID,
        draft_id=DRAFT_ID,
    )


def test_adapter_uploads_media_once_renders_and_downloads_every_output(
    registry: TemplateRegistry,
) -> None:
    service = FakeService()
    reads: list[str] = []
    adapter = RemotionTemplateAdapter(
        _client(service), read_media=lambda key: (reads.append(key), b"img")[1]
    )
    result = adapter.generate(_request(_props(registry)), api_key="")

    assert sorted(reads) == ["t/x/logo.png", "uploads/t/a.jpg", "uploads/t/b.jpg"]
    assert len(service.assets) == 3
    payload = result.payload
    assert isinstance(payload, dict)
    assert payload["status"] == "completed" and payload["failed_ports"] == {}
    assert set(payload["outputs"]) == {"reel", "feed", "story"}
    assert payload["outputs"]["reel"]["bytes"] == b"reel-bytes"
    assert payload["outputs"]["reel"]["mime_type"] == "video/mp4"
    assert payload["outputs"]["feed"]["height"] == 1350
    assert payload["warnings"] == ["font 'Poppins' unavailable, used 'Inter'"]
    assert result.provider == "remotion" and result.model_id == MODEL_ID
    assert result.model_revision == "promo_producto@1"
    assert result.usage.pieces == 3 and result.usage.media_seconds == Decimal("12.5")


def test_adapter_keeps_the_outputs_that_rendered_when_one_fails(
    registry: TemplateRegistry,
) -> None:
    service = FakeService()
    service.fail_port = "story"
    adapter = RemotionTemplateAdapter(_client(service), read_media=lambda _k: b"img")
    result = adapter.generate(_request(_props(registry)), api_key="")
    payload = result.payload
    assert isinstance(payload, dict)
    assert payload["status"] == "failed"
    assert set(payload["outputs"]) == {"reel", "feed"}
    assert payload["failed_ports"]["story"] == {
        "failure_reason": FailureReason.RENDER_ERROR.value,
        "error_message": "Chromium crashed",
    }
    assert result.usage.pieces == 2


def test_adapter_raises_when_nothing_rendered(registry: TemplateRegistry) -> None:
    service = FakeService()
    service.fail_port = "reel"
    adapter = RemotionTemplateAdapter(_client(service), read_media=lambda _k: b"img")
    with pytest.raises(RenderServiceError) as exc:
        adapter.generate(_request(_props(registry), outputs=["reel"]), api_key="")
    assert exc.value.code == "render_error" and "Chromium crashed" in exc.value.message


def test_adapter_estimate_prices_renders_from_the_table(registry: TemplateRegistry) -> None:
    adapter = RemotionTemplateAdapter(_client(FakeService()), read_media=lambda _k: b"")
    pricing = JsonPricingTable("v2")
    assert adapter.estimate_cost_usd(_request(_props(registry)), pricing) == Decimal("0.00")
    assert pricing.unit_price(model_id=MODEL_ID, unit="per_render") == Decimal("0.00")


def test_render_is_idempotent_on_the_job_id(registry: TemplateRegistry) -> None:
    service = FakeService()
    client = _client(service)
    first = client.render(
        job_id="j1", template_id="promo_producto", version=1, props={"photos": []}
    )
    again = client.render(
        job_id="j1", template_id="promo_producto", version=1, props={"photos": []}
    )
    assert first.job_id == again.job_id and len(service.jobs) == 1
    assert first.status is JobStatus.PENDING


def test_wait_times_out_and_cancels(registry: TemplateRegistry) -> None:
    service = FakeService()
    client = _client(service)
    client.render(job_id="slow", template_id="promo_producto", version=1, props={"photos": []})
    with pytest.raises(RenderServiceError) as exc:
        client.wait("slow", timeout_seconds=2, interval_seconds=0)
    assert exc.value.code == "timeout" and service.cancelled == ["slow"]


def test_errors_carry_the_service_code() -> None:
    service = FakeService()
    client = _client(service)
    with pytest.raises(RenderServiceError) as exc:
        client.job("missing")
    assert exc.value.code == "not_found" and exc.value.status == 404


def test_failure_reasons_map_one_to_one_and_unknown_is_loud() -> None:
    assert to_failure_reason("render_error") is FailureReason.RENDER_ERROR
    assert to_failure_reason("invalid_parameters") is FailureReason.INVALID_PARAMETERS
    assert to_failure_reason("dependency_failed") is FailureReason.DEPENDENCY_FAILED
    assert to_failure_reason("timeout") is FailureReason.TIMEOUT
    assert to_failure_reason("internal_error") is FailureReason.PROVIDER_ERROR
    assert to_failure_reason(None) is FailureReason.PROVIDER_ERROR
    with pytest.raises(ValueError):
        to_failure_reason("meteor_strike")


def test_job_payload_parses_per_output_state() -> None:
    job = RenderJob.from_payload(
        {
            "jobId": "j",
            "templateId": "promo_producto",
            "version": 1,
            "status": "generating",
            "outputs": {
                "reel": {"kind": "video", "status": "generating", "progress": 0.42},
                "feed": {
                    "kind": "still",
                    "status": "completed",
                    "progress": 1,
                    "mimeType": "image/png",
                },
            },
        }
    )
    assert job.completed_ports == ["feed"] and job.outputs["reel"].progress == 0.42
    assert job.first_failure is None and not job.status.terminal

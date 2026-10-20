"""The advertising image's scene experiment (docs/plan-observabilidad-langfuse.md §7,
fase 6): cases, task and evaluators, importable so they are tested offline. The runnable
side — it spends real money — is `packages/api/evals/scenes_ai/run_experiment.py`.

The task is production's own path for the ad image (`MediaProducer._ad_image`): the
scene prompt from `ad_scene_prompt`, Seedream through `TracedProvider` at the format's
scene size, then the hook and the CTA set on top by `render_ad_slides` and the JPEG Meta
takes (`to_meta_jpeg`). What only a person can judge — product fidelity, coherence,
legible text, the safe zone, artefacts — goes to the annotation queue «Revisión de
imagen y video»: the finished image and the raw scene are ATTACHED to the trace, which is
allowed here because the brands are fictional (§9 of the plan keeps tenants' media out).

Code-side scores: `tamano_ok` (the image has the format's exact size), `costo_usd`,
`segundos`, `errores`.

A Reel's ad image is a video in production (the still animated, `animate_still`); the
experiment judges the still, which is what the video is made of.
"""

from __future__ import annotations

import base64
import io
import json
import statistics
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from PIL import Image
from qualify_creative.adapters.byteplus_ark import DEFAULT_SEEDREAM_MODEL, SeedreamImageAdapter
from qualify_creative.compose import FlyerText, render_ad_slides
from qualify_creative.enums import (
    AdImageMode,
    ContentFormat,
    ContentKind,
    GenerationTask,
    ImageRoute,
)
from qualify_creative.photo.normalize import to_meta_jpeg
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.providers import GenerationProvider, GenerationRequest, RenderedPrompt
from qualify_creative.schemas import BrandKit, BriefObjective, ContentBrief, MediaInputs
from qualify_shared import observability
from qualify_shared.observability import ItemOutcome, Score

from qualify_api.creative.composition import PRICING_VERSION, ark_endpoints_from_env
from qualify_api.creative.media import SCENE_SIZES, ad_scene_prompt
from qualify_api.creative.observed import TracedProvider
from qualify_api.creative.review import REVIEW_QUEUE

DATASET = "escenas-imagen"
#: The image model under test; more candidates join here (plan §7: the ranking of
#: docs/comparativa-apis-creativo-motor-angulos.md §7).
CONFIGS: Mapping[str, str] = {"seedream-5.0-lite": DEFAULT_SEEDREAM_MODEL}
_BRAND_NAMES = {
    "heladeria": "La Ceiba Helados",
    "hamburguesas": "Brasa Norte",
    "inmobiliaria": "Hábitat Inmobiliaria",
}


def load_cases(path: Path, brands_path: Path) -> list[dict[str, Any]]:
    """The scenes, each with its brand's kit (from the copy dataset's fictional brands)
    and any photo it names, so an item is self-contained."""
    brands = json.loads(brands_path.read_text(encoding="utf-8"))["brands"]
    items = []
    for case in json.loads(path.read_text(encoding="utf-8"))["cases"]:
        photos = {
            key: str((path.parent / case[key]).resolve())
            for key in ("product_photo", "background_photo")
            if case.get(key)
        }
        items.append(
            {
                "id": case["id"],
                "input": {
                    **{
                        k: case[k]
                        for k in ("id", "brand", "format", "topic", "scene", "hook", "cta")
                    },
                    "brand_name": _BRAND_NAMES.get(case["brand"], case["brand"]),
                    "kit": brands[case["brand"]]["kit"],
                    **photos,
                },
            }
        )
    return items


def _mode(case: Mapping[str, Any]) -> AdImageMode:
    product, background = bool(case.get("product_photo")), bool(case.get("background_photo"))
    if product and background:
        return AdImageMode.BOTH
    if background:
        return AdImageMode.BACKGROUND
    return AdImageMode.PRODUCT if product else AdImageMode.SCENE


def build_brief(case: Mapping[str, Any], kit: BrandKit) -> ContentBrief:
    mode = _mode(case)
    return ContentBrief(
        brand_id=kit.brand_id,
        objective=BriefObjective.SALE,
        topic=case["topic"],
        image_route=ImageRoute.TEMPLATE_ONLY,
        kind=ContentKind.STATIC_FLYER,
        format=ContentFormat(case["format"]),
        media=MediaInputs(
            ad_mode=mode,
            scene_prompt=case["scene"],
            product_keys=("eval/product",) if mode.needs_product else (),
            background_key="eval/background" if mode.needs_background else None,
        ),
    )


def _data_url(path: str) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(Path(path).read_bytes()).decode()


def generate(
    case: Mapping[str, Any],
    model: str,
    *,
    api_key: str,
    provider: GenerationProvider | None = None,
    review_queue: str | None = REVIEW_QUEUE,
    attach: Callable[[bytes, str], Any] = observability.media,
    allow_presets: bool = False,
) -> dict[str, Any]:
    """The task: the scene, the words on it, the finished image — attached for review.

    Seedream is called through the deployment's custom endpoints (`ark_endpoints_from_env`);
    ``allow_presets`` lets a model without one go by bare id to the campaign-authorized
    preset — acceptable ONLY because these brands are fictional (m-24820898)."""
    kit = BrandKit.model_validate(case["kit"])
    brief = build_brief(case, kit)
    mode = brief.media.ad_mode or AdImageMode.SCENE
    references = [
        _data_url(case[key]) for key in ("product_photo", "background_photo") if case.get(key)
    ]
    prompt = ad_scene_prompt(
        brief=brief,
        kit=kit,
        brand=case.get("brand_name", ""),
        mode=mode,
        products=1 if mode.needs_product else 0,
        has_background=mode.needs_background,
    )
    ratio = brief.format.aspect_ratio
    request = GenerationRequest(
        task=GenerationTask.PRODUCT_IMAGE,
        rendered_prompt=RenderedPrompt("", "", ""),
        params={"prompt": prompt, "images": references, "size": SCENE_SIZES[ratio], "model": model},
    )
    pricing = JsonPricingTable(PRICING_VERSION)
    adapter = provider or TracedProvider(
        SeedreamImageAdapter(
            model=model, endpoints=ark_endpoints_from_env(), allow_presets=allow_presets
        ),
        pricing,
    )
    started = time.perf_counter()
    try:
        result = adapter.generate(request, api_key=api_key)
        scene = bytes(result.payload["images"][0])
    except Exception as exc:  # noqa: BLE001 — recorded and scored
        return {"error": f"{type(exc).__name__}: {exc}"[:300]}
    seconds = round(time.perf_counter() - started, 2)
    (finished,) = render_ad_slides(
        scenes=[scene],
        text=FlyerText(hook=case["hook"], cta=case["cta"]),
        palette=kit.palette_rgb,
        size=brief.format.dimensions,
    )
    image = to_meta_jpeg(finished)
    width, height = Image.open(io.BytesIO(image)).size
    price = pricing.unit_price(model_id=result.model_id, unit="per_piece")
    if review_queue:
        observability.enqueue_for_review(review_queue, trace_id=observability.current_trace_id())
    return {
        "imagen": attach(image, "image/jpeg"),
        "escena": attach(to_meta_jpeg(scene), "image/jpeg"),
        "modo": mode.value,
        "formato": brief.format.value,
        "ancho": width,
        "alto": height,
        "modelo": result.model_id,
        "costo_usd": float(price * max(result.usage.pieces, 1)),
        "segundos": seconds,
        "prompt": prompt,
    }


def scene_scores(
    case: Mapping[str, Any], output: Mapping[str, Any], _expected: Any, _meta: Mapping[str, Any]
) -> list[Score]:
    if output.get("error"):
        return [Score("errores", 1.0, output["error"])]
    width, height = ContentFormat(case["format"]).dimensions
    size_ok = (output["ancho"], output["alto"]) == (width, height)
    return [
        Score("errores", 0.0),
        Score(
            "tamano_ok",
            size_ok,
            None if size_ok else f"{output['ancho']}×{output['alto']}, expected {width}×{height}",
        ),
        Score("costo_usd", float(output["costo_usd"])),
        Score("segundos", float(output["segundos"])),
    ]


ITEM_EVALUATORS = (scene_scores,)


def run_summary(outcomes: Sequence[ItemOutcome]) -> list[Score]:
    def values(name: str) -> list[float]:
        return [
            float(o.scores[name])
            for o in outcomes
            if isinstance(o.scores.get(name), int | float | bool)
        ]

    out = [Score("errores_total", sum(values("errores")))]
    if sizes := values("tamano_ok"):
        out.append(Score("tamano_ok_tasa", round(statistics.mean(sizes), 3)))
    if costs := values("costo_usd"):
        out.append(Score("costo_total_usd", round(sum(costs), 4)))
    if seconds := values("segundos"):
        out.append(Score("segundos_p50", round(statistics.median(seconds), 2)))
    return out


RUN_EVALUATORS = (run_summary,)

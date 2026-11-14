"""Running the layer stage inside a generation (m-25017283) — only with
`QUALIFY_IMAGE_LAYER=on`; off, `run_layer_stage` returns at once and nothing changes.

For the advertising image it runs between the base and the composition; for a gallery,
after its slides are made (one call with every generated slide's base, ADR 49 §2.5) and
only once none of them is still pending. When Claude reports invented text in a Seedream
base, the base is regenerated ONCE: first the slide's row in `piece_base_regenerations` is
claimed (the unique key is the cap, 0168), then the base stage makes that scene again and
the layer is asked for once more.

**Replays pay nothing twice.** Inside a queue preparation every layer call is a pipeline
step of its own, in fixed slots outside the router's numbering (`LAYER_STEPS`): the answer
AND the bases it claimed for regeneration are saved with the step, so a replay reads them
back instead of calling Claude or the database again, and makes the same regeneration
router calls in the same order — the router replays their saved Seedream results. A step
left `in_flight` (a crash after a paid call) is never repeated: that pass has no layer.
Every call of one piece draws on ONE `DollarMeter` (`LAYER_BUDGET_USD`), regeneration
included.

Nothing here may cost the owner the piece: any failure (the switch on without a key, the
model, the budget, the database) is logged and the piece goes on without a layer — the
composition does not read one yet (m-25017285). The queue's own signals (deferred,
pending, checkpoint lost) are never swallowed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any
from uuid import UUID

from qualify_creative.layer_spec import LayerSpec
from qualify_creative.schemas import ContentBrief, CopyPayload

from qualify_api.claude_tools import DollarMeter
from qualify_api.creative import pipeline
from qualify_api.creative.image_pipeline.base import BaseScene
from qualify_api.creative.image_pipeline.layer import (
    CAROUSEL,
    FREE_IDEA,
    LAYER_BUDGET_USD,
    LAYER_MODEL,
    LAYER_PROMPT_VERSION,
    PRODUCT_PROMOTION,
    BusinessFacts,
    CatalogProduct,
    LayerRequest,
    LayerResult,
    SlideInput,
    layer_enabled,
    write_layers,
)
from qualify_api.creative.media import LayerWrite, _MediaPending
from qualify_api.creative.queue_dispatch import CheckpointError, GenerationDeferred

if TYPE_CHECKING:
    from qualify_api.creative.media import MediaProducer

logger = logging.getLogger(__name__)

#: The pipeline step slots of the layer calls: the first call, then the call after a
#: regeneration. Negative and fixed, like the frozen inputs (-1…-3), so they never shift
#: the router's step numbers whether the switch is on or off.
LAYER_STEPS = (-100, -101)
#: The queue's signals: the stage re-raises them, never turns them into «no layer».
QUEUE_SIGNALS = (GenerationDeferred, CheckpointError, _MediaPending)


@dataclass(frozen=True)
class LayerOutcome:
    """The scenes (a regenerated one replaces its first) and the layers, by position."""

    scenes: dict[int, BaseScene]
    layers: dict[int, LayerWrite]
    regenerated: tuple[int, ...] = ()


def _default_writer(request: LayerRequest, *, budget: DollarMeter) -> LayerResult:
    from qualify_api.claude_tools import api_key_from_env  # noqa: PLC0415

    return write_layers(request, api_key=api_key_from_env(), budget=budget)


def _default_claim(**kwargs: Any) -> bool:
    from qualify_api.creative.layer_store import claim_base_regeneration  # noqa: PLC0415

    return claim_base_regeneration(**kwargs)


def _default_context(
    tenant_id: UUID, brand_id: UUID, product_ref: str | None
) -> tuple[BusinessFacts, tuple[CatalogProduct, ...]]:
    from qualify_api.creative.layer_store import (  # noqa: PLC0415
        load_business_facts,
        load_catalog_products,
    )

    return (
        load_business_facts(tenant_id, brand_id),
        load_catalog_products(tenant_id, brand_id, product_ref),
    )


def _seams(producer: MediaProducer) -> tuple[Callable[..., Any], ...]:
    """The producer's own seams when it has them (tests), else the production ones."""
    return (
        getattr(producer, "_layer_writer", None) or _default_writer,
        getattr(producer, "_layer_claim", None) or _default_claim,
        getattr(producer, "_layer_context", None) or _default_context,
    )


def piece_type(brief: ContentBrief, *, gallery: bool) -> str:
    if gallery:
        return CAROUSEL
    return PRODUCT_PROMOTION if brief.product_ref or brief.media.product_keys else FREE_IDEA


def _layer_write(result: LayerResult, position: int) -> LayerWrite | None:
    spec = result.specs.get(position)
    if spec is None:
        return None
    return LayerWrite(
        spec=spec.model_dump(mode="json"),
        spec_sha256=spec.spec_sha256(),
        layout_id=spec.layout_id.value,
        layout_version=spec.layout_version,
        model_id=result.model_id,
        prompt_version=result.prompt_version,
    )


# -- the checkpoint -----------------------------------------------------------------------


def _result_json(result: LayerResult) -> dict[str, Any]:
    return {
        "specs": {str(p): s.model_dump(mode="json") for p, s in result.specs.items()},
        "invented_text": list(result.invented_text),
        "failed": {str(p): why for p, why in result.failed.items()},
        "model_id": result.model_id,
        "prompt_version": result.prompt_version,
        "repairs": result.repairs,
    }


def _result_from_json(data: Mapping[str, Any]) -> LayerResult:
    return LayerResult(
        specs={int(p): LayerSpec.model_validate(s) for p, s in data["specs"].items()},
        invented_text=[int(p) for p in data["invented_text"]],
        failed={int(p): str(why) for p, why in data["failed"].items()},
        stats=None,  # booked in the ledger when it was paid; a replay books nothing
        model_id=str(data["model_id"]),
        prompt_version=str(data["prompt_version"]),
        repairs=int(data.get("repairs", 0)),
    )


def _checkpointed(
    step: int, request: LayerRequest, compute: Callable[[], dict[str, Any]]
) -> dict[str, Any] | None:
    """`compute()` once per preparation: outside the queue it just runs; inside, its
    value is the step's saved result. None: an earlier pass left the step in flight or
    failed — a paid call may have been billed, so it is never made again."""
    run = pipeline.current_preparation()
    if run is None:
        return compute()
    store = pipeline.PipelineStore()
    row = store.load_step(run, step)
    if row is None:
        row = store.save_step(
            run,
            step,
            {
                "provider": "claude-layer",
                "model_id": LAYER_MODEL.model_id,
                "prompt_version": LAYER_PROMPT_VERSION,
                "positions": [s.position for s in request.slides],
            },
            None,
        )
    if row["result"] is not None:
        return dict(row["result"])
    if row["error"] is not None:
        logger.warning(
            "draft %s: layer step %s was left %s, no layer this time",
            run.draft_id,
            step,
            row["error"],
        )
        return None
    store.intent(run, step)
    identity = {**run.params(), "s": step}
    try:
        value = compute()
    except QUEUE_SIGNALS:
        raise
    except Exception as exc:
        store.complete_step(
            run.tenant_id,
            identity=identity,
            result=None,
            error=f"layer failed: {type(exc).__name__}",
            run=run,
        )
        raise
    store.complete_step(run.tenant_id, identity=identity, result=value, run=run)
    return value


# -- the stage ----------------------------------------------------------------------------


def run_layer_stage(
    producer: MediaProducer,
    *,
    tenant_id: UUID,
    draft_id: UUID,
    revision: int,
    brief: ContentBrief,
    copy: CopyPayload,
    brand: str,
    scenes: Mapping[int, BaseScene],
    regenerate: Callable[[int], BaseScene | None],
    gallery: bool,
    slide_count: int | None = None,
    env: Mapping[str, str] | None = None,
) -> LayerOutcome:
    """The layers of `scenes` (position → base), regenerating a base once when Claude saw
    invented text in it. Off (`QUALIFY_IMAGE_LAYER`), or on any failure: no layers."""
    scenes = dict(scenes)
    if not scenes or not layer_enabled(dict(env) if env is not None else None):
        return LayerOutcome(scenes, {})
    writer, claim, context = _seams(producer)
    budget = DollarMeter(LAYER_BUDGET_USD)  # ONE meter for every call of this piece
    try:
        facts, products = context(tenant_id, brief.brand_id, brief.product_ref)
        request = LayerRequest(
            tenant_id=tenant_id,
            brand_id=brief.brand_id,
            format=brief.format.aspect_ratio,
            piece_type=piece_type(brief, gallery=gallery),
            slides=tuple(SlideInput(position=p, photo=scenes[p].image) for p in sorted(scenes)),
            slide_count=slide_count,
            brand_name=brand,
            topic=brief.topic,
            scene=brief.media.scene_prompt,
            hook=copy.hook,
            cta=copy.cta,
            facts=facts,
            products=products,
        )

        def first() -> dict[str, Any]:
            result = writer(request, budget=budget)
            claimed: list[int] = []
            for position in result.invented_text:
                if claim(
                    tenant_id=tenant_id,
                    brand_id=brief.brand_id,
                    draft_id=draft_id,
                    revision=revision,
                    position=position,
                    reason="base_has_invented_text",
                    model_id=result.model_id,
                    prompt_version=result.prompt_version,
                ):
                    claimed.append(position)
                else:
                    logger.info("draft %s slide %s: base already made again", draft_id, position)
            # saved with the answer: a replay regenerates exactly these, claiming nothing
            return {"layer": _result_json(result), "regenerate": claimed}

        saved = _checkpointed(LAYER_STEPS[0], request, first)
        if saved is None:
            return LayerOutcome(scenes, {})
        result = _result_from_json(saved["layer"])
        regenerated: list[int] = []
        for position in saved["regenerate"]:
            fresh = regenerate(int(position))
            if fresh is not None:
                scenes[int(position)] = fresh
                regenerated.append(int(position))
        if regenerated:
            again_request = replace(
                request,
                slides=tuple(SlideInput(position=p, photo=scenes[p].image) for p in sorted(scenes)),
            )
            again = _checkpointed(
                LAYER_STEPS[1],
                again_request,
                lambda: {"layer": _result_json(writer(again_request, budget=budget))},
            )
            fresh_specs = _result_from_json(again["layer"]).specs if again else {}
            for position in regenerated:
                if position in fresh_specs:
                    result.specs[position] = fresh_specs[position]
                else:
                    result.specs.pop(position, None)
        layers = {p: w for p in scenes if (w := _layer_write(result, p)) is not None}
        if result.failed:
            logger.warning("draft %s: no layer for %s", draft_id, sorted(result.failed))
        return LayerOutcome(scenes, layers, tuple(regenerated))
    except QUEUE_SIGNALS:
        raise
    except Exception:  # noqa: BLE001 - the layer never costs the paid piece
        logger.warning(
            "draft %s: layer stage failed, piece goes on without it", draft_id, exc_info=True
        )
        return LayerOutcome(scenes, {})

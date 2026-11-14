"""Running the layer stage inside a generation (m-25017283) — only with
`QUALIFY_IMAGE_LAYER=on`; off, `run_layer_stage` returns at once and nothing changes.

For the advertising image it runs between the base and the composition; for a gallery,
after its slides are made (one call with every generated slide's base, ADR 49 §2.5). When
Claude reports invented text in a Seedream base, the base is regenerated ONCE: first the
slide's row in `piece_base_regenerations` is claimed (the unique key is the cap, 0168),
then the base stage makes that scene again and the layer is asked for once more.

Nothing here may cost the owner the piece: any failure (the switch on without a key, the
model, the budget, the database) is logged and the piece goes on without a layer — the
composition does not read one yet (m-25017285).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any
from uuid import UUID

from qualify_creative.schemas import ContentBrief, CopyPayload

from qualify_api.creative.image_pipeline.base import BaseScene
from qualify_api.creative.image_pipeline.layer import (
    CAROUSEL,
    FREE_IDEA,
    PRODUCT_PROMOTION,
    BusinessFacts,
    CatalogProduct,
    LayerRequest,
    LayerResult,
    SlideInput,
    layer_enabled,
    write_layers,
)
from qualify_api.creative.media import LayerWrite

if TYPE_CHECKING:
    from qualify_api.creative.media import MediaProducer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LayerOutcome:
    """The scenes (a regenerated one replaces its first) and the layers, by position."""

    scenes: dict[int, BaseScene]
    layers: dict[int, LayerWrite]
    regenerated: tuple[int, ...] = ()


def _default_writer(request: LayerRequest) -> LayerResult:
    from qualify_api.claude_tools import api_key_from_env  # noqa: PLC0415

    return write_layers(request, api_key=api_key_from_env())


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
        result = writer(request)
        regenerated: list[int] = []
        for position in result.invented_text:
            claimed = claim(
                tenant_id=tenant_id,
                brand_id=brief.brand_id,
                draft_id=draft_id,
                revision=revision,
                position=position,
                reason="base_has_invented_text",
                model_id=result.model_id,
                prompt_version=result.prompt_version,
            )
            if not claimed:
                logger.info("draft %s slide %s: base already regenerated once", draft_id, position)
                continue
            fresh = regenerate(position)
            if fresh is not None:
                scenes[position] = fresh
                regenerated.append(position)
        if regenerated:
            again = writer(
                replace(
                    request,
                    slides=tuple(
                        SlideInput(position=p, photo=scenes[p].image) for p in sorted(scenes)
                    ),
                )
            )
            for position in regenerated:
                if position in again.specs:
                    result.specs[position] = again.specs[position]
                else:
                    result.specs.pop(position, None)
        layers = {p: w for p in scenes if (w := _layer_write(result, p)) is not None}
        if result.failed:
            logger.warning("draft %s: no layer for %s", draft_id, sorted(result.failed))
        return LayerOutcome(scenes, layers, tuple(regenerated))
    except Exception:  # noqa: BLE001 - the layer never costs the paid piece
        logger.warning(
            "draft %s: layer stage failed, piece goes on without it", draft_id, exc_info=True
        )
        return LayerOutcome(scenes, {})

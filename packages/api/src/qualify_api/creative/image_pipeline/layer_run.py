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

**Money.** Both Claude calls of one piece draw on ONE `DollarMeter` (`LAYER_BUDGET_USD`);
what the first call spent is saved with its step and charged back to the meter on a
replay, so a crash between the two calls never hands the second a fresh cap. The Seedream
regeneration is not a layer cost: it goes through the router and bills the piece's
`BudgetContext`, like any scene.

**Step numbers.** A regeneration is one router call, so it moves `run.step` by one. That is
safe only because no router call follows the layer stage in `produce()`: the flyer composes
locally after it, the gallery's closing slide is drawn locally. Anything that adds a router
call after this stage must move it before, or replays would read the wrong steps
(`test_no_router_call_follows_the_layer_stage` pins it).

A second call that fails (budget refused, model error) drops only the regenerated slides'
layers: the other slides keep the first answer's, on the first pass and on a replay alike.

Follow-up (2026-11-15, catalog `layout_version` 2, then 3): a step saved under an older catalog
no longer validates, so its replay falls to «no layer» before the regeneration loop — the
claimed regenerations are not made again on that pass. None exist (the switch is off).

Nothing here may cost the owner the piece: any failure (the switch on without a key, the
model, the budget, the database) is logged and the piece goes on without a layer. The
queue's own signals (deferred, pending, checkpoint lost) are never swallowed.

**The rewrite** (m-25040499, ADR 49 §8.1 D5): when the compositor refuses a layer (a price
wider than its box in every layout of the chain), `rewrite_layers` asks Claude ONCE more for
those images, with the reason, on the SAME meter as the stage's calls (step `LAYER_STEPS[2]`).
Its failure is the caller's to handle: a priced piece is never published without its price.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
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
LAYER_STEPS = (-100, -101, -102)
#: The prompt version a rewritten layer is recorded with (its prompt carries the correction).
REWRITE_SUFFIX = "+reescritura"
#: The queue's signals: the stage re-raises them, never turns them into «no layer».
QUEUE_SIGNALS = (GenerationDeferred, CheckpointError, _MediaPending)


@dataclass(frozen=True)
class LayerOutcome:
    """The scenes (a regenerated one replaces its first) and the layers, by position."""

    scenes: dict[int, BaseScene]
    layers: dict[int, LayerWrite]
    regenerated: tuple[int, ...] = ()
    #: m-25040499: what the compose step needs to ask for a rewrite on the same meter, and
    #: each catalog product's printed price (product id → `price_label`)
    request: LayerRequest | None = None
    budget: DollarMeter | None = None
    prices: Mapping[str, str] = field(default_factory=dict)
    #: how the piece's price was decided (for the compose provenance and the Pillow cover)
    price: PiecePrice | None = None


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


@dataclass(frozen=True)
class PiecePrice:
    """m-25040499: the price this piece prints, decided ONCE from the catalog (ADR 49:
    «precio del catálogo»): `label` is the product's CURRENT catalog label ("" = the piece
    shows no price), `status` why, `brief_line` what the brief said when it was made."""

    status: str  # hidden | matches | changed | product_not_found | ambiguous | no_price_today
    brief_line: str = ""
    label: str = ""
    product_id: str = ""

    def provenance(self) -> dict[str, str]:
        return {
            "price_status": self.status,
            "brief_price_line": self.brief_line,
            "catalog_price_label": self.label,
        }


def resolve_piece_price(
    found: Sequence[CatalogProduct], *, price_line: str, product_ref: str | None
) -> tuple[tuple[CatalogProduct, ...], PiecePrice]:
    """The brief's product among `found` (the catalog's matches for `product_ref`) and the
    price the piece prints. The brief's `price_line` only says whether the piece shows a
    price; the figure is the catalog's TODAY — never the stale line:

    - no `price_line` (the angle hides it): no product priced, no price;
    - the brief's product is found and priced today: it is the ONE priced product and its
      current label is printed, also when it changed since the brief (logged, recorded);
    - not found, several candidates with nothing to tell them apart, or no price today: the
      piece shows no price (recorded, logged) — nothing required, nothing accepted.

    The product: the one named exactly like `product_ref`, else the one whose label is the
    brief's line, else the only match."""
    line = price_line.strip()
    unpriced = tuple(replace(p, has_price=False) for p in found)
    if not line:
        return unpriced, PiecePrice("hidden")
    ref = (product_ref or "").strip().casefold()
    product = (
        next((p for p in found if p.name.strip().casefold() == ref), None)
        or next((p for p in found if p.price_text.strip() == line), None)
        or (found[0] if len(found) == 1 else None)
    )
    if product is None:
        status = "ambiguous" if found else "product_not_found"
        logger.warning("piece price: %s for %r, printed without a price", status, product_ref)
        return unpriced, PiecePrice(status, line)
    label = product.price_text.strip()
    if not label:
        logger.warning("piece price: %r has no price today, printed without one", product.name)
        return unpriced, PiecePrice("no_price_today", line, product_id=str(product.product_id))
    status = "matches" if label == line else "changed"
    if status == "changed":
        logger.warning("piece price: the catalog says %r, the brief said %r", label, line)
    products = tuple(replace(p, has_price=p is product) for p in found)
    return products, PiecePrice(status, line, label, str(product.product_id))


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


def _charge_back(budget: DollarMeter, saved: Mapping[str, Any] | None) -> None:
    """A step read back from an earlier pass: charge this meter what the piece had spent
    by then (`spent_usd`, cumulative), so a crash never hands a later call a fresh cap."""
    if not saved:
        return
    paid = Decimal(str(saved.get("spent_usd", "0")))
    if paid > budget.spent_usd:
        budget.charge(paid - budget.spent_usd, what="layer call saved in an earlier pass")


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
    title_font: str = "",
    price_line: str = "",
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
        facts, found = context(tenant_id, brief.brand_id, brief.product_ref)
        products, price = resolve_piece_price(
            found, price_line=price_line, product_ref=brief.product_ref
        )
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
            title_font=title_font,
            price_line=price.label,  # the catalog's label today, "" = no price
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
            # saved with the answer: a replay regenerates exactly these, claiming nothing,
            # and charges back what was spent (the cap spans both calls across a crash)
            return {
                "layer": _result_json(result),
                "regenerate": claimed,
                "spent_usd": str(budget.spent_usd),
            }

        saved = _checkpointed(LAYER_STEPS[0], request, first)
        if saved is None:
            return LayerOutcome(scenes, {})
        _charge_back(budget, saved)  # a replay: this meter has not seen the first call yet
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
            try:

                def second() -> dict[str, Any]:
                    answer = writer(again_request, budget=budget)
                    return {"layer": _result_json(answer), "spent_usd": str(budget.spent_usd)}

                again = _checkpointed(LAYER_STEPS[1], again_request, second)
                _charge_back(budget, again)
            except QUEUE_SIGNALS:
                raise
            except Exception:  # noqa: BLE001 - as a replay of the failed step: None
                logger.warning(
                    "draft %s: layer after regeneration failed, %s keep no layer",
                    draft_id,
                    regenerated,
                    exc_info=True,
                )
                again = None
            fresh_specs = _result_from_json(again["layer"]).specs if again else {}
            for position in regenerated:
                if position in fresh_specs:
                    result.specs[position] = fresh_specs[position]
                else:
                    result.specs.pop(position, None)
        layers = {p: w for p in scenes if (w := _layer_write(result, p)) is not None}
        if result.failed:
            logger.warning("draft %s: no layer for %s", draft_id, sorted(result.failed))
        # only the piece's own price can be drawn (`resolve_piece_price`)
        prices = {price.product_id: price.label} if price.label else {}
        return LayerOutcome(scenes, layers, tuple(regenerated), request, budget, prices, price)
    except QUEUE_SIGNALS:
        raise
    except Exception:  # noqa: BLE001 - the layer never costs the paid piece
        logger.warning(
            "draft %s: layer stage failed, piece goes on without it", draft_id, exc_info=True
        )
        return LayerOutcome(scenes, {})


# -- the rewrite after a refusal (m-25040499) ----------------------------------------------


def rewrite_layers(
    producer: MediaProducer,
    outcome: LayerOutcome,
    notes: Mapping[int, str],
) -> dict[int, LayerWrite]:
    """ONE more layer call for the images the compositor refused (`notes`: position → why,
    in the model's language), on the stage's meter. Returns the new layers it could write
    (a position missing = no layer). Raises what the call raises — the caller fails the
    piece, never publishes it without its price — and the queue's signals as they are."""
    request = outcome.request
    if request is None or outcome.budget is None or not notes:
        return {}
    writer, _claim, _context = _seams(producer)
    budget = outcome.budget
    scenes = outcome.scenes
    again = replace(
        request,
        slides=tuple(SlideInput(position=p, photo=scenes[p].image) for p in sorted(notes)),
        # a gallery keeps its roles: the count is the whole gallery's
        slide_count=request.count if request.is_carousel else None,
        rewrite_note="\n".join(f"- imagen {p}: {why}" for p, why in sorted(notes.items())),
    )

    def call() -> dict[str, Any]:
        answer = writer(again, budget=budget)
        return {"layer": _result_json(answer), "spent_usd": str(budget.spent_usd)}

    saved = _checkpointed(LAYER_STEPS[2], again, call)
    if saved is None:
        raise RuntimeError("the layer rewrite was left unfinished in an earlier pass")
    _charge_back(budget, saved)
    result = _result_from_json(saved["layer"])
    result = replace(result, prompt_version=result.prompt_version + REWRITE_SUFFIX)
    return {p: w for p in notes if (w := _layer_write(result, p)) is not None}

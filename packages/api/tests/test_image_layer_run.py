"""m-25017283: the layer stage inside a generation. Off by default (no call, nothing
changes); on, the advertising image and the gallery get one layer call each, a base with
invented text is made again ONCE when its regeneration is claimed, and any failure leaves
the piece without a layer — never without the piece."""

from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from qualify_creative.enums import ContentKind, SlideSource
from qualify_creative.layer_spec import LayerSpec
from qualify_creative.schemas import CarouselSlide

from qualify_api.claude_tools import DollarMeter
from qualify_api.creative import pipeline
from qualify_api.creative.brand_references import BrandReferencesSet
from qualify_api.creative.image_pipeline import layer_run
from qualify_api.creative.image_pipeline.base import BaseScene
from qualify_api.creative.image_pipeline.layer import (
    LAYER_BUDGET_USD,
    BusinessFacts,
    LayerRequest,
    LayerResult,
)
from qualify_api.creative.media import _MediaPending
from qualify_api.creative.queue_dispatch import CheckpointError, GenerationDeferred

from .test_creative_media_byteplus import BUDGET, COPY, TENANT_ID, _brief, _kit
from .test_creative_queue_pipeline import Checkpoints
from .test_v9_flyer_consumer import (  # noqa: F401 - `no_generation` is autouse
    gallery_setup,
    no_generation,
    run_flyer,
)

SEEN = {"subject_box": [0.3, 0.4, 0.8, 0.9], "logo_in_photo": False}


def _spec(position: int, count: int | None, *, invented: bool = False) -> LayerSpec:
    carousel = None
    if count:
        role = "cover" if position == 0 else "closing" if position == count - 1 else "body"
        carousel = {"role": role, "index": position, "count": count}
    layout = "band" if carousel and carousel["role"] == "closing" else "plate"
    return LayerSpec.model_validate(
        {
            "layout_id": layout,
            "format": "4:5",
            "photo": {**SEEN, "base_has_invented_text": invented},
            "anchor": "bottom" if layout == "band" else "top_left",
            "title": "Tu shawarma, recién hecho",
            "carousel": carousel,
        }
    )


class Writer:
    def __init__(
        self,
        *,
        invented: tuple[int, ...] = (),
        fail: bool = False,
        raises: BaseException | None = None,
        spend: Decimal = Decimal(0),
    ) -> None:
        self.requests: list[LayerRequest] = []
        self.budgets: list[DollarMeter] = []
        self.invented = invented
        self.fail = fail
        self.raises = raises
        self.spend = spend

    def __call__(self, request: LayerRequest, *, budget: DollarMeter) -> LayerResult:
        self.requests.append(request)
        self.budgets.append(budget)
        if self.raises is not None:
            raise self.raises
        if self.fail:
            raise RuntimeError("model down")
        if self.spend:
            budget.charge(self.spend, what="layer")
        first = len(self.requests) == 1
        count = request.slide_count if request.is_carousel else None
        specs = {
            s.position: _spec(s.position, count, invented=first and s.position in self.invented)
            for s in request.slides
        }
        invented = [p for p in self.invented if first]
        return LayerResult(specs=specs, invented_text=invented, failed={}, stats=None)


def _wire(
    producer: Any, writer: Writer, claims: list[dict[str, Any]], *, claim: bool = True
) -> None:
    producer._layer_writer = writer
    producer._layer_claim = lambda **kw: claims.append(kw) or claim
    producer._layer_context = lambda tenant, brand, ref: (BusinessFacts(), ())


def _produce(producer: Any, brief: Any) -> Any:
    return producer.produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=brief,
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
        brand_references=BrandReferencesSet(block_version=9),
    )


def test_off_by_default_nothing_is_called(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUALIFY_IMAGE_LAYER", raising=False)
    producer, brief, vendor = gallery_setup(monkeypatch)
    writer = Writer(fail=True)
    _wire(producer, writer, [])
    outcome = _produce(producer, brief)
    assert outcome.failure is None and writer.requests == []
    assert all(write.layer is None for write in outcome.media)
    assert len(vendor.requests) == 2


def test_a_gallery_gets_one_call_and_its_layers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUALIFY_IMAGE_LAYER", "on")
    producer, brief, vendor = gallery_setup(monkeypatch)
    writer = Writer()
    _wire(producer, writer, [])
    outcome = _produce(producer, brief)
    assert outcome.failure is None
    assert len(writer.requests) == 1 and len(writer.requests[0].slides) == 2
    assert [w.layer.layout_id for w in outcome.media] == ["plate", "band"]
    assert outcome.media[0].layer.spec_sha256 == _spec(0, 2).spec_sha256()
    assert len(vendor.requests) == 2  # no regeneration


def test_invented_text_regenerates_that_base_once_when_claimed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QUALIFY_IMAGE_LAYER", "on")
    producer, brief, vendor = gallery_setup(monkeypatch)
    writer, claims = Writer(invented=(1,)), []
    _wire(producer, writer, claims)
    outcome = _produce(producer, brief)
    assert outcome.failure is None
    assert [c["position"] for c in claims] == [1] and claims[0]["revision"] >= 1
    assert len(vendor.requests) == 3  # two slides + ONE regeneration
    assert len(writer.requests) == 2  # the layer is asked again for the new base
    second = outcome.media[1]
    assert second.params["base_regenerated"] is True and second.layer is not None


def test_an_already_claimed_regeneration_is_not_made_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QUALIFY_IMAGE_LAYER", "on")
    producer, brief, vendor = gallery_setup(monkeypatch)
    writer, claims = Writer(invented=(0,)), []
    _wire(producer, writer, claims, claim=False)
    outcome = _produce(producer, brief)
    assert outcome.failure is None and len(claims) == 1
    assert len(vendor.requests) == 2 and len(writer.requests) == 1
    assert "base_regenerated" not in outcome.media[0].params


def test_the_flyer_gets_its_layer_before_its_composition(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUALIFY_IMAGE_LAYER", "on")
    writer = Writer()

    def wired(producer: Any) -> None:
        _wire(producer, writer, [])

    from qualify_api.creative import media as media_module

    real_init = media_module.MediaProducer.__init__

    def init(self: Any, *args: Any, **kwargs: Any) -> None:
        real_init(self, *args, **kwargs)
        wired(self)

    monkeypatch.setattr(media_module.MediaProducer, "__init__", init)
    outcome, requests = run_flyer(monkeypatch, count=2)
    assert outcome.failure is None
    assert len(writer.requests) == 1 and writer.requests[0].is_carousel  # the flyer gallery
    assert all(w.layer is not None for w in outcome.media)


def test_a_failing_layer_never_costs_the_piece(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUALIFY_IMAGE_LAYER", "on")
    producer, brief, _ = gallery_setup(monkeypatch)
    _wire(producer, Writer(fail=True), [])
    outcome = _produce(producer, brief)
    assert outcome.failure is None and all(w.layer is None for w in outcome.media)


# -- the stage on its own: queue signals, one budget, replays -------------------------------

ON = {"QUALIFY_IMAGE_LAYER": "on"}
DRAFT = uuid4()


class Regenerator:
    """Stands for the base stage's regeneration: one router call per base, which in a
    preparation takes the next router step number (as `CheckpointRouter._run` does)."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, int | None]] = []

    def __call__(self, position: int) -> BaseScene:
        run = pipeline.current_preparation()
        step = None
        if run is not None:
            step = run.step
            run.step += 1
        self.calls.append((position, step))
        return BaseScene(image=b"fresh", prompt=f"again {position}")


def _stage(writer: Writer, claims: list[dict[str, Any]], regenerate: Any, **over: Any):  # noqa: ANN202
    producer = SimpleNamespace()
    _wire(producer, writer, claims, claim=over.pop("claim", True))
    values: dict[str, Any] = {
        "tenant_id": TENANT_ID,
        "draft_id": DRAFT,
        "revision": 1,
        "brief": _brief(
            ContentKind.CAROUSEL,
            slides=tuple(CarouselSlide(source=SlideSource.GENERATED) for _ in range(2)),
        ),
        "copy": COPY,
        "brand": "Korner",
        "scenes": {0: BaseScene(b"a", "p0"), 1: BaseScene(b"b", "p1")},
        "regenerate": regenerate,
        "gallery": True,
        "slide_count": 2,
        "env": ON,
    }
    values.update(over)
    return layer_run.run_layer_stage(producer, **values)


class JsonCheckpoints(Checkpoints):
    """The steps as Postgres keeps them: a result goes through JSON (jsonb) and back."""

    def save_step(self, run: Any, step: int, request: dict, job_id: Any) -> dict:
        return super().save_step(run, step, json.loads(json.dumps(request)), job_id)

    def complete_step(self, tenant_id: Any, *, identity: dict, result: Any, **kw: Any) -> None:
        stored = json.loads(json.dumps(result)) if result is not None else None
        super().complete_step(tenant_id, identity=identity, result=stored, **kw)


def _pass(checkpoints: Checkpoints, monkeypatch: pytest.MonkeyPatch, *args: Any, **kw: Any):  # noqa: ANN202
    """One preparation pass (a fresh `Preparation`, as after a restart): the router
    already took two steps for the gallery's slides."""
    monkeypatch.setattr(pipeline, "PipelineStore", lambda: checkpoints)
    run = pipeline.Preparation(TENANT_ID, DRAFT, 1, "generation", uuid4(), 1, step=2)
    with pipeline.preparing(run):
        return _stage(*args, **kw), run


@pytest.mark.parametrize(
    "signal", [GenerationDeferred(), CheckpointError("lease lost"), _MediaPending()]
)
def test_the_queue_s_signals_are_never_swallowed(signal: BaseException) -> None:
    with pytest.raises(type(signal)):
        _stage(Writer(raises=signal), [], Regenerator())


def test_a_signal_from_the_regeneration_is_never_swallowed() -> None:
    def deferred(position: int) -> BaseScene:
        raise GenerationDeferred()

    with pytest.raises(GenerationDeferred):
        _stage(Writer(invented=(1,)), [], deferred)


def test_both_calls_of_a_piece_draw_on_one_budget() -> None:
    writer = Writer(invented=(1,), spend=Decimal("0.10"))
    outcome = _stage(writer, [], Regenerator())
    assert len(writer.requests) == 2 and writer.budgets[0] is writer.budgets[1]
    assert writer.budgets[0].limit_usd == LAYER_BUDGET_USD
    assert writer.budgets[0].remaining_usd == LAYER_BUDGET_USD - Decimal("0.20")
    assert outcome.regenerated == (1,)


def test_the_cap_holds_across_both_calls() -> None:
    """The first call leaves US$0.10; the second cannot spend US$0.15 more: the piece
    keeps the first answer's other layers, never spends past US$0.25."""
    writer = Writer(invented=(1,), spend=Decimal("0.15"))
    outcome = _stage(writer, [], Regenerator())
    assert len(writer.requests) == 2
    assert writer.budgets[0].spent_usd == Decimal("0.15")  # the second charge was refused
    assert set(outcome.layers) == {0}  # slide 1 (regenerated) has none; slide 0 keeps its
    assert outcome.regenerated == (1,)


def test_a_failed_second_call_gives_the_same_layers_on_a_replay(monkeypatch) -> None:  # noqa: ANN001
    checkpoints = JsonCheckpoints()
    writer = Writer(invented=(1,), spend=Decimal("0.15"))
    first, _ = _pass(checkpoints, monkeypatch, writer, [], Regenerator())
    assert checkpoints.rows[-101]["error"] == "layer failed: BudgetExhausted"
    again, _ = _pass(checkpoints, monkeypatch, writer, [], Regenerator())
    assert len(writer.requests) == 2  # the failed call is not made again
    assert set(first.layers) == set(again.layers) == {0}


class Crash(BaseException):
    """The process dies (not an `Exception`: nothing in the stage catches it)."""


def test_a_replay_charges_back_the_first_call(monkeypatch) -> None:  # noqa: ANN001
    """A crash after step -100 is saved and before -101: the replay's meter starts from
    what the first call spent, so the second call cannot get a fresh US$0.25."""
    checkpoints = JsonCheckpoints()
    writer = Writer(invented=(1,), spend=Decimal("0.15"))

    def crash(position: int) -> BaseScene:
        raise Crash()

    with pytest.raises(Crash):
        _pass(checkpoints, monkeypatch, writer, [], crash)
    assert checkpoints.rows[-100]["result"]["spent_usd"] == "0.15"
    assert -101 not in checkpoints.rows
    outcome, _ = _pass(checkpoints, monkeypatch, writer, [], Regenerator(), claim=False)
    assert len(writer.requests) == 2  # the first answer read back, the second asked
    assert writer.budgets[1].spent_usd == Decimal("0.15")  # charged back; 0.15 more refused
    assert set(outcome.layers) == {0}


def test_a_replay_reuses_the_answer_and_the_regeneration(monkeypatch) -> None:  # noqa: ANN001
    checkpoints, claims = JsonCheckpoints(), []
    writer, regen = Writer(invented=(1,)), Regenerator()
    first, run = _pass(checkpoints, monkeypatch, writer, claims, regen)
    assert set(checkpoints.rows) == {-100, -101}
    assert checkpoints.rows[-100]["result"]["regenerate"] == [1]
    assert len(writer.requests) == 2 and len(claims) == 1 and regen.calls == [(1, 2)]
    # a second pass (a restart): nothing paid, nothing claimed, the same router step
    again, _ = _pass(checkpoints, monkeypatch, writer, claims, regen, claim=False)
    assert len(writer.requests) == 2 and len(claims) == 1
    assert regen.calls == [(1, 2), (1, 2)]  # same base, same router step: its saved result
    assert again.regenerated == first.regenerated == (1,)
    assert {p: w.spec_sha256 for p, w in again.layers.items()} == {
        p: w.spec_sha256 for p, w in first.layers.items()
    }


def test_the_step_numbers_do_not_depend_on_the_switch(monkeypatch) -> None:  # noqa: ANN001
    """The layer's steps sit in fixed slots: with or without a regeneration, the router's
    numbering after the stage is the same as with the switch off."""
    for invented, router_steps in (((), 2), ((1,), 3)):
        checkpoints = JsonCheckpoints()
        _, run = _pass(checkpoints, monkeypatch, Writer(invented=invented), [], Regenerator())
        assert run.step == router_steps
        assert all(step < 0 for step in checkpoints.rows)
    checkpoints = JsonCheckpoints()
    _, run = _pass(checkpoints, monkeypatch, Writer(), [], Regenerator(), env={})
    assert run.step == 2 and checkpoints.rows == {}


def test_a_call_left_in_flight_is_never_paid_again(monkeypatch) -> None:  # noqa: ANN001
    checkpoints = JsonCheckpoints()
    checkpoints.rows[-100] = {"request": {}, "job_id": None, "result": None, "error": "in_flight"}
    writer = Writer()
    outcome, _ = _pass(checkpoints, monkeypatch, writer, [], Regenerator())
    assert writer.requests == [] and outcome.layers == {}


def test_a_failed_call_is_recorded_and_not_repeated(monkeypatch) -> None:  # noqa: ANN001
    checkpoints, writer = JsonCheckpoints(), Writer(fail=True)
    _pass(checkpoints, monkeypatch, writer, [], Regenerator())
    assert checkpoints.rows[-100]["error"] == "layer failed: RuntimeError"
    _pass(checkpoints, monkeypatch, writer, [], Regenerator())
    assert len(writer.requests) == 1


def test_a_gallery_with_a_pending_slide_waits_for_its_layer(monkeypatch) -> None:  # noqa: ANN001
    """A deferred pass (a slide still being made) makes no layer call: the layer is paid
    once, on the pass where every slide is there."""
    monkeypatch.setenv("QUALIFY_IMAGE_LAYER", "on")
    producer, brief, _ = gallery_setup(monkeypatch)
    writer = Writer()
    _wire(producer, writer, [])
    slides = brief.media.slides
    animated = slides[1].model_copy(update={"source": SlideSource.ANIMATED})
    brief = brief.model_copy(
        update={"media": brief.media.model_copy(update={"slides": (slides[0], animated)})}
    )
    waited: list[int] = []

    def pending_video(**kwargs: Any) -> Any:
        waited.append(kwargs["position"])
        raise GenerationDeferred()

    monkeypatch.setattr(producer, "_animated_slide", pending_video)
    outcome = _produce(producer, brief)
    assert outcome.pending and waited == [1]
    assert writer.requests == []  # slide 0 is made, but the layer waits for the next pass


def test_no_router_call_follows_the_layer_stage(monkeypatch) -> None:  # noqa: ANN001
    """A gallery run twice through `CheckpointRouter` (pass 2 = a restart): the layer is
    asked once per call over both passes, pass 2 pays nothing, and the regeneration is the
    LAST router step — a router call added after the layer stage would move this number
    and break replays (see `layer_run`'s «Step numbers»)."""
    from unittest.mock import patch

    from qualify_api.creative.pipeline import CheckpointRouter

    monkeypatch.setenv("QUALIFY_IMAGE_LAYER", "on")
    producer, brief, vendor = gallery_setup(monkeypatch)
    writer, claims = Writer(invented=(1,)), []
    _wire(producer, writer, claims)
    checkpoints, draft, router = JsonCheckpoints(), uuid4(), producer._router

    def one_pass() -> tuple[Any, Any]:
        producer._router = CheckpointRouter(router, checkpoints, producer._store)
        run = pipeline.Preparation(TENANT_ID, draft, 1, "generation", uuid4(), 1)
        with patch("qualify_api.creative.pipeline.PipelineStore", return_value=checkpoints):
            with pipeline.preparing(run):
                outcome = producer.produce(
                    tenant_id=TENANT_ID,
                    draft_id=draft,
                    brief=brief,
                    kit=_kit(),
                    copy=COPY,
                    budget=BUDGET,
                    brand_references=BrandReferencesSet(block_version=9),
                )
        return outcome, run

    first, run1 = one_pass()
    assert first.failure is None and len(vendor.requests) == 3  # 2 slides + 1 regeneration
    assert len(writer.requests) == 2 and len(claims) == 1
    router_steps = sorted(s for s in checkpoints.rows if s >= 0)
    assert router_steps == [0, 1, 2] and run1.step == 3  # the regeneration is the last one
    second, run2 = one_pass()
    assert second.failure is None
    assert len(vendor.requests) == 3 and len(writer.requests) == 2 and len(claims) == 1
    assert run2.step == 3
    assert [w.layer.spec_sha256 for w in second.media] == [w.layer.spec_sha256 for w in first.media]
    assert second.media[1].params["base_regenerated"] is True

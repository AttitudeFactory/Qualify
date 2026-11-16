"""m-25040499: the compose step inside a generation. Off: nothing is called and the piece is
the same as before. On: every slide with a layer is drawn by the compositor and stored with
its provenance; replays never draw nor store twice; a refused layer is rewritten once and the
piece fails rather than lose its price; transient failures get three attempts; an outage
waits ten minutes from the FIRST failure, never reset."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from qualify_creative.enums import FailureReason
from qualify_creative.layer_spec import LayerSpec

from qualify_api.claude_tools import DollarMeter
from qualify_api.creative import pipeline
from qualify_api.creative.brand_references import BrandReferencesSet
from qualify_api.creative.image_pipeline import compose_run
from qualify_api.creative.image_pipeline.base import BaseScene
from qualify_api.creative.image_pipeline.compose_run import (
    FIRST_FAILURE_STEP,
    MAX_ATTEMPTS,
    OWNER_FAILED,
    OWNER_PRICE,
    attempt_step,
    compose_slides,
)
from qualify_api.creative.image_pipeline.layer import (
    FREE_IDEA,
    LAYER_BUDGET_USD,
    LayerRequest,
    SlideInput,
)
from qualify_api.creative.image_pipeline.layer_run import (
    LAYER_STEPS,
    REWRITE_SUFFIX,
    LayerOutcome,
)
from qualify_api.creative.media import BasePhoto, LayerWrite, _MediaFailed, _Saver
from qualify_api.creative.queue_dispatch import CheckpointError

from .test_creative_media_byteplus import COPY, TENANT_ID, MemoryStore, _kit
from .test_image_layer_run import (
    Composer,
    JsonCheckpoints,
    Writer,
    _produce,
    _spec,
    _wire,
)
from .test_v9_flyer_consumer import (  # noqa: F401 - `no_generation` is autouse
    gallery_setup,
    no_generation,
    run_flyer,
)

ON = {"QUALIFY_IMAGE_LAYER": "on"}
PRODUCT = str(uuid4())
PRICE = "$12.000"
T0 = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


# -- through the producer: off is unchanged, on composes ----------------------------------


def _budget() -> Any:
    from .test_creative_media_byteplus import BUDGET

    return BUDGET


def test_off_composes_nothing_and_the_piece_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """The switch off: no compose call, no compose step, and the same writes as a producer
    that has no compose seam at all (today's code path)."""
    monkeypatch.delenv("QUALIFY_IMAGE_LAYER", raising=False)
    draft = uuid4()

    def once(wired: bool) -> tuple[Any, Composer]:
        producer, brief, _ = gallery_setup(monkeypatch)
        composer = Composer()
        if wired:
            _wire(producer, Writer(), [], composer=composer)
        outcome = producer.produce(
            tenant_id=TENANT_ID,
            draft_id=draft,
            brief=brief,
            kit=_kit(),
            copy=COPY,
            budget=_budget(),
            brand_references=BrandReferencesSet(block_version=9),
        )
        return outcome, composer

    with_seam, composer = once(True)
    without, _ = once(False)
    assert composer.requests == []
    assert with_seam.failure is None and with_seam.media == without.media
    assert all("composer" not in w.params for w in with_seam.media)


def test_off_takes_no_compose_step_in_the_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    checkpoints = JsonCheckpoints()
    outcome = _outcome({0: _layer(0)})
    monkeypatch.setattr(pipeline, "PipelineStore", lambda: checkpoints)
    run = pipeline.Preparation(TENANT_ID, DRAFT, 1, "generation", uuid4(), 1)
    composer = Composer()
    with pipeline.preparing(run):
        assert _compose(outcome, composer, env={}) == {}
    assert composer.requests == [] and checkpoints.rows == {}


def test_on_a_gallery_is_drawn_by_the_compositor_and_stored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QUALIFY_IMAGE_LAYER", "on")
    producer, brief, _ = gallery_setup(monkeypatch)
    composer = _wire(producer, Writer(), [])
    outcome = _produce(producer, brief)
    assert outcome.failure is None
    assert [r.position for r in composer.requests] == [0, 1]
    for write, request in zip(outcome.media, composer.requests, strict=True):
        assert "/compose/" in write.object_key and write.media_url == write.object_key
        assert producer._store.read(write.object_key).startswith(b"composed:")
        params = write.params
        assert params["composer"] == "layer_still"
        assert params["compose_job_id"] == request.job_id()
        assert params["compose_engine_revision"] == 4
        assert params["layer_layout_version"] == write.layer.layout_version == 3
        assert params["layer_prompt_version"] == write.layer.prompt_version
        assert params["layer_spec_sha256"] == write.layer.spec_sha256
        assert params["base_sha256"] == request.base_sha256
        assert params["compose_layout_rendered"] == write.layer.layout_id


def test_on_the_flyer_is_drawn_by_the_compositor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUALIFY_IMAGE_LAYER", "on")
    composer = Composer()
    from qualify_api.creative import media as media_module

    real_init = media_module.MediaProducer.__init__

    def init(self: Any, *args: Any, **kwargs: Any) -> None:
        real_init(self, *args, **kwargs)
        _wire(self, Writer(), [], composer=composer)

    monkeypatch.setattr(media_module.MediaProducer, "__init__", init)
    outcome, _ = run_flyer(monkeypatch, count=2)
    assert outcome.failure is None
    drawn = [w for w in outcome.media if w.params.get("composer") == "layer_still"]
    assert [w.position for w in drawn] == [0, 1]  # the closing slide has no scene, no layer
    assert len(composer.requests) == 2


def test_the_render_gets_the_title_face_the_layer_was_written_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QUALIFY_IMAGE_LAYER", "on")
    producer, brief, _ = gallery_setup(monkeypatch)
    writer = Writer()
    composer = _wire(producer, writer, [])
    kit = _kit().model_copy(update={"font_heading": "", "font_body": "Pacifico"})
    producer.produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=brief,
        kit=kit,
        copy=COPY,
        budget=_budget(),
        brand_references=BrandReferencesSet(block_version=9),
    )
    headings = {r.brand["fonts"]["heading"] for r in composer.requests}
    assert headings == {"Pacifico"} == {writer.requests[0].title_font}


# -- the step on its own ------------------------------------------------------------------

DRAFT = uuid4()


def _layer(position: int, *, price: bool = False) -> LayerWrite:
    spec = _spec(position, None).model_dump(mode="json")
    if price:
        spec["price_ref"] = {"product_id": PRODUCT}
    digest = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    return LayerWrite(
        spec=spec,
        spec_sha256=digest,
        layout_id=spec["layout_id"],
        layout_version=spec["layout_version"],
        model_id="claude-test",
        prompt_version="capa-v4",
    )


def _outcome(layers: dict[int, LayerWrite], *, prices: bool = True) -> LayerOutcome:
    scenes = {
        p: BaseScene(
            image=f"photo-{p}".encode(),
            prompt=f"p{p}",
            stored=BasePhoto(
                key=f"t/{TENANT_ID}/generated/{DRAFT}/base/{p}.jpg",
                sha256=f"{p:064d}",
                content_type="image/jpeg",
                model_id="seedream",
                provider="seedream",
                rendered_prompt=f"p{p}",
                prompt_compiler_version=9,
            ),
        )
        for p in layers
    }
    request = LayerRequest(
        tenant_id=TENANT_ID,
        brand_id=uuid4(),
        format="4:5",
        piece_type=FREE_IDEA,
        slides=tuple(SlideInput(position=p, photo=scenes[p].image) for p in sorted(scenes)),
    )
    return LayerOutcome(
        scenes=scenes,
        layers=layers,
        request=request,
        budget=DollarMeter(LAYER_BUDGET_USD),
        prices={PRODUCT: PRICE} if prices else {},
    )


class PricedWriter(Writer):
    """A writer whose layers keep the catalog price reference (a rewrite that fixed it)."""

    def __call__(self, request: LayerRequest, *, budget: DollarMeter) -> Any:
        result = super().__call__(request, budget=budget)
        result.specs = {
            p: LayerSpec.model_validate(
                {**spec.model_dump(mode="json"), "price_ref": {"product_id": PRODUCT}}
            )
            for p, spec in result.specs.items()
        }
        return result


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


def _producer(
    composer: Composer,
    writer: Writer | None = None,
    clock: Clock | None = None,
    store: MemoryStore | None = None,
):  # noqa: ANN202
    producer = SimpleNamespace(
        _store=store if store is not None else MemoryStore(),
        _logo=lambda kit, key: None,
        _remotion=None,
        _compose_clock=clock or Clock(),
    )
    _wire(producer, writer or Writer(), [], composer=composer)
    return producer


def _compose(
    outcome: LayerOutcome,
    composer: Composer,
    *,
    writer: Writer | None = None,
    clock: Clock | None = None,
    env: dict[str, str] | None = None,
    store: MemoryStore | None = None,
) -> dict[int, Any]:
    producer = _producer(composer, writer, clock, store)
    return compose_slides(
        producer,
        outcome=outcome,
        tenant_id=TENANT_ID,
        draft_id=DRAFT,
        revision=1,
        kit=_kit(),
        brand_name="Korner",
        logo_key=None,
        save=_Saver(producer._store, TENANT_ID, DRAFT, 1),
        env=ON if env is None else env,
    )


def _in_pass(checkpoints: JsonCheckpoints, monkeypatch: pytest.MonkeyPatch, *args, **kw):  # noqa: ANN002, ANN003, ANN202
    monkeypatch.setattr(pipeline, "PipelineStore", lambda: checkpoints)
    run = pipeline.Preparation(TENANT_ID, DRAFT, 1, "generation", uuid4(), 1)
    with pipeline.preparing(run):
        return _compose(*args, **kw)


def test_a_replay_never_draws_nor_stores_twice(monkeypatch: pytest.MonkeyPatch) -> None:
    checkpoints = JsonCheckpoints()
    outcome = _outcome({0: _layer(0), 1: _layer(1)})
    composer = Composer()
    first = _in_pass(checkpoints, monkeypatch, outcome, composer)
    assert len(composer.requests) == 2
    assert checkpoints.rows[attempt_step(0, 0, 0)]["result"]["status"] == "composed"
    # a restart: the same steps read back — no render, no new object, the same keys
    store_before = dict(checkpoints.rows)
    composer_again = Composer()
    producer = _producer(composer_again)
    producer._store.files.update({first[0].key: b"x", first[1].key: b"y"})
    monkeypatch.setattr(pipeline, "PipelineStore", lambda: checkpoints)
    run = pipeline.Preparation(TENANT_ID, DRAFT, 1, "generation", uuid4(), 1)
    with pipeline.preparing(run):
        again = compose_slides(
            producer,
            outcome=outcome,
            tenant_id=TENANT_ID,
            draft_id=DRAFT,
            revision=1,
            kit=_kit(),
            brand_name="Korner",
            logo_key=None,
            save=_Saver(producer._store, TENANT_ID, DRAFT, 1),
            env=ON,
        )
    assert composer_again.requests == []
    assert set(producer._store.files) == {first[0].key, first[1].key}  # nothing stored again
    assert {p: c.key for p, c in again.items()} == {p: c.key for p, c in first.items()}
    assert checkpoints.rows == store_before


def test_an_attempt_left_unanswered_is_made_again_with_the_same_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crash after the step was saved and before its answer: the render is free and the
    service hands back the same job, so the same attempt is made again."""
    checkpoints = JsonCheckpoints()
    outcome = _outcome({0: _layer(0)})
    checkpoints.rows[attempt_step(0, 0, 0)] = {
        "request": {},
        "job_id": None,
        "result": None,
        "error": None,
    }
    composer = Composer()
    _in_pass(checkpoints, monkeypatch, outcome, composer)
    assert [r.attempt for r in composer.requests] == [0]


def test_the_catalog_price_reaches_the_render(monkeypatch: pytest.MonkeyPatch) -> None:
    composer = Composer()
    composed = _compose(_outcome({0: _layer(0, price=True)}), composer)
    assert composer.requests[0].price_text == PRICE
    assert composed[0].params["printed"]["price"] is True


def test_a_price_that_does_not_fit_is_rewritten_once_and_drawn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = PricedWriter(spend=Decimal("0.05"))
    outcome = _outcome({0: _layer(0, price=True)})
    outcome.budget.charge(Decimal("0.10"), what="the stage's first call")
    composer = Composer({0: ["refuse_price"]})
    composed = _compose(outcome, composer, writer=writer)
    assert len(writer.requests) == 1  # ONE rewrite
    rewrite = writer.requests[0]
    assert "precio" in rewrite.rewrite_note and [s.position for s in rewrite.slides] == [0]
    assert writer.budgets[0] is outcome.budget  # the piece's one meter
    assert outcome.budget.spent_usd == Decimal("0.15")
    assert [(r.attempt, r.spec is not None) for r in composer.requests] == [(0, True), (0, True)]
    assert composed[0].layer.prompt_version.endswith(REWRITE_SUFFIX)
    assert composed[0].params["layer_prompt_version"].endswith(REWRITE_SUFFIX)
    assert composed[0].params["printed"]["price"] is True


def test_a_rewrite_that_gives_the_price_up_fails_the_piece() -> None:
    composer = Composer({0: ["refuse_price"]})
    with pytest.raises(_MediaFailed) as failed:
        _compose(_outcome({0: _layer(0, price=True)}), composer, writer=Writer())
    assert failed.value.detail == OWNER_PRICE
    assert len(composer.requests) == 1  # the priceless rewrite is never drawn


def test_a_price_still_too_wide_fails_the_piece_never_drops_it() -> None:
    composer = Composer({0: ["refuse_price", "refuse_price"]})
    with pytest.raises(_MediaFailed) as failed:
        _compose(_outcome({0: _layer(0, price=True)}), composer, writer=PricedWriter())
    assert failed.value.detail == OWNER_PRICE
    assert failed.value.failure == FailureReason.INVALID_PARAMETERS.value
    assert len(composer.requests) == 2  # the layer, then its rewrite — no other attempt


def test_a_report_that_dropped_the_price_is_never_accepted() -> None:
    composer = Composer({0: ["drop_price", "drop_price"]})
    with pytest.raises(_MediaFailed) as failed:
        _compose(_outcome({0: _layer(0, price=True)}), composer, writer=PricedWriter())
    assert failed.value.detail == OWNER_PRICE


def test_a_price_the_catalog_lost_is_never_drawn_without_it() -> None:
    composer = Composer()
    with pytest.raises(_MediaFailed) as failed:
        _compose(_outcome({0: _layer(0, price=True)}, prices=False), composer)
    assert failed.value.detail == OWNER_PRICE and composer.requests == []

    composer = Composer()  # a rewrite that keeps the reference cannot print it either
    with pytest.raises(_MediaFailed):
        _compose(
            _outcome({0: _layer(0, price=True)}, prices=False), composer, writer=PricedWriter()
        )
    assert composer.requests == []


def test_a_failed_rewrite_fails_the_piece() -> None:
    composer = Composer({0: ["refuse_price"]})
    with pytest.raises(_MediaFailed) as failed:
        _compose(_outcome({0: _layer(0, price=True)}), composer, writer=Writer(fail=True))
    assert failed.value.detail == OWNER_PRICE


def test_a_refusal_is_never_retried_as_such() -> None:
    """`invalid_parameters` (with or without a refusal body) is not an attempt to repeat: the
    same layer refuses the same way. Only the rewrite is composed again."""
    for step in ("refuse", "invalid"):
        composer = Composer({0: [step, step]})
        with pytest.raises(_MediaFailed) as failed:
            _compose(_outcome({0: _layer(0)}), composer)
        assert failed.value.detail == OWNER_FAILED
        assert [r.attempt for r in composer.requests] == [0, 0]


def test_a_transient_failure_is_a_new_job_at_most_three_times() -> None:
    composer = Composer({0: ["transient", "ok"]})
    composed = _compose(_outcome({0: _layer(0)}), composer)
    first, second = composer.requests
    assert (first.attempt, second.attempt) == (0, 1)
    assert first.job_id() != second.job_id()
    assert composed[0].params["compose_attempt"] == 1

    composer = Composer({0: ["transient"] * 5})
    with pytest.raises(_MediaFailed) as failed:
        _compose(_outcome({0: _layer(0)}), composer)
    assert len(composer.requests) == MAX_ATTEMPTS == 3
    assert failed.value.detail == OWNER_FAILED
    assert failed.value.failure == FailureReason.RENDER_ERROR.value


def test_attempt_zero_keeps_the_job_id_it_always_had() -> None:
    from qualify_creative.render.layer_compose import LayerComposeRequest

    base = {
        "tenant_id": "t",
        "draft_id": "d",
        "version_id": "v",
        "layer_id": "l",
        "position": 0,
        "spec": {"format": "4:5", "layout_id": "plate"},
        "brand": {},
        "engine_rev": 4,
    }
    assert LayerComposeRequest(**base).job_id() == LayerComposeRequest(**base, attempt=0).job_id()
    assert LayerComposeRequest(**base).job_id() != LayerComposeRequest(**base, attempt=1).job_id()


def test_transient_attempts_survive_a_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    """Attempts are counted across passes: two failed in pass 1 (then a crash) leave one."""
    checkpoints = JsonCheckpoints()
    outcome = _outcome({0: _layer(0)})
    for attempt in (0, 1):
        checkpoints.rows[attempt_step(0, 0, attempt)] = {
            "request": {},
            "job_id": None,
            "result": None,
            "error": "transient: render_error",
        }
    composer = Composer({0: ["transient"]})
    with pytest.raises(_MediaFailed):
        _in_pass(checkpoints, monkeypatch, outcome, composer)
    assert [r.attempt for r in composer.requests] == [2]


def test_an_outage_waits_ten_minutes_from_the_first_failure_never_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoints, clock = JsonCheckpoints(), Clock()
    outcome = _outcome({0: _layer(0)})
    with pytest.raises(CheckpointError):  # the piece waits in the queue
        _in_pass(checkpoints, monkeypatch, outcome, Composer({0: ["outage"]}), clock=clock)
    first = checkpoints.rows[FIRST_FAILURE_STEP]["request"]["first_failure_at"]
    assert first == T0.isoformat()
    clock.now = T0 + timedelta(minutes=6)
    with pytest.raises(CheckpointError):
        _in_pass(checkpoints, monkeypatch, outcome, Composer({0: ["outage"]}), clock=clock)
    assert checkpoints.rows[FIRST_FAILURE_STEP]["request"]["first_failure_at"] == first
    # the same attempt each time (the job never started): no attempt was spent
    assert checkpoints.rows[attempt_step(0, 0, 0)]["error"] is None
    clock.now = T0 + timedelta(minutes=10)
    with pytest.raises(_MediaFailed) as failed:
        _in_pass(checkpoints, monkeypatch, outcome, Composer({0: ["outage"]}), clock=clock)
    assert failed.value.detail == OWNER_FAILED
    assert failed.value.failure == FailureReason.RENDER_ERROR.value


def test_the_window_counts_transient_failures_too(monkeypatch: pytest.MonkeyPatch) -> None:
    """A first transient failure starts the window; an outage minutes later does not."""
    checkpoints, clock = JsonCheckpoints(), Clock()
    outcome = _outcome({0: _layer(0)})
    with pytest.raises(CheckpointError):
        _in_pass(
            checkpoints, monkeypatch, outcome, Composer({0: ["transient", "outage"]}), clock=clock
        )
    assert checkpoints.rows[FIRST_FAILURE_STEP]["request"]["first_failure_at"] == T0.isoformat()
    clock.now = T0 + timedelta(minutes=11)
    with pytest.raises(_MediaFailed):
        _in_pass(checkpoints, monkeypatch, outcome, Composer({0: ["outage"]}), clock=clock)


def test_outside_the_queue_an_outage_fails_at_once() -> None:
    with pytest.raises(_MediaFailed) as failed:
        _compose(_outcome({0: _layer(0)}), Composer({0: ["outage"]}))
    assert failed.value.detail == OWNER_FAILED


def test_no_render_service_is_an_outage_never_a_pillow_still() -> None:
    producer = _producer(Composer())
    del producer._layer_composer  # the production composer, with no service configured
    with pytest.raises(_MediaFailed) as failed:
        compose_slides(
            producer,
            outcome=_outcome({0: _layer(0)}),
            tenant_id=TENANT_ID,
            draft_id=DRAFT,
            revision=1,
            kit=_kit(),
            brand_name="Korner",
            logo_key=None,
            save=_Saver(producer._store, TENANT_ID, DRAFT, 1),
            env=ON,
        )
    assert failed.value.detail == OWNER_FAILED


def test_the_rewrite_is_a_layer_step_of_its_own(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replayed like the stage's own calls: a restart reads the rewrite back, pays nothing."""
    checkpoints, store = JsonCheckpoints(), MemoryStore()
    writer = PricedWriter()
    outcome = _outcome({0: _layer(0, price=True)})
    _in_pass(
        checkpoints,
        monkeypatch,
        outcome,
        Composer({0: ["refuse_price"]}),
        writer=writer,
        store=store,
    )
    assert checkpoints.rows[LAYER_STEPS[2]]["result"] is not None
    assert checkpoints.rows[attempt_step(0, 1, 0)]["result"]["status"] == "composed"
    composer = Composer()
    again = _in_pass(
        checkpoints,
        monkeypatch,
        _outcome({0: _layer(0, price=True)}),
        composer,
        writer=writer,
        store=store,
    )
    assert len(writer.requests) == 1 and composer.requests == []
    assert again[0].layer.prompt_version.endswith(REWRITE_SUFFIX)


def test_compose_run_keeps_its_steps_below_the_layer_s() -> None:
    steps = [attempt_step(p, r, a) for p in range(20) for r in (0, 1) for a in range(3)]
    assert len(set(steps)) == len(steps)
    assert max(steps) < FIRST_FAILURE_STEP < min(LAYER_STEPS)
    assert compose_run.OUTAGE_WINDOW == timedelta(minutes=10)

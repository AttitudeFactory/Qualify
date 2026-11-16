"""m-25040499: the compose step inside a generation. Off: nothing is called and the piece is
the same as before. On: every slide with a layer is drawn by the compositor and stored with
its provenance; replays never draw nor store twice; a refused layer is rewritten once and the
piece fails rather than lose its price; transient failures get three attempts; an outage
waits ten minutes from the FIRST failure, never reset."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from qualify_creative.layer_spec import LayerSpec
from qualify_creative.render.client import RenderServiceError, RenderTimeout
from qualify_creative.render.layer_compose import ComposeJobFailed

from qualify_api.claude_tools import DollarMeter
from qualify_api.creative import pipeline
from qualify_api.creative.brand_references import BrandReferencesSet
from qualify_api.creative.image_pipeline import compose_run
from qualify_api.creative.image_pipeline.base import BaseScene
from qualify_api.creative.image_pipeline.compose_run import (
    COMPOSE_FAILURE,
    FIRST_FAILURE_STEP,
    MAX_ATTEMPTS,
    PRICE_FAILURE,
    RenderWait,
    attempt_step,
    compose_slides,
    outage_step,
    raise_if_waiting,
)
from qualify_api.creative.image_pipeline.layer import (
    CAROUSEL,
    FREE_IDEA,
    LAYER_BUDGET_USD,
    BusinessFacts,
    CatalogProduct,
    LayerRequest,
    SlideInput,
)
from qualify_api.creative.image_pipeline.layer_run import (
    LAYER_STEPS,
    REWRITE_SUFFIX,
    LayerOutcome,
    resolve_piece_price,
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


def _outcome(
    layers: dict[int, LayerWrite], *, prices: bool = True, price_line: str = ""
) -> LayerOutcome:
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
        price_line=price_line,
        # the piece's product, priced today when the piece shows a price
        products=(
            CatalogProduct(
                UUID(PRODUCT),
                "Shawarma mixto",
                has_price=bool(price_line),
                price_text=price_line,
            ),
        ),
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
    keep_images: Any = (),
) -> dict[int, Any]:
    producer = _producer(composer, writer, clock, store)
    return compose_slides(
        producer,
        keep_images=keep_images,
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
    composed = _compose(_outcome({0: _layer(0, price=True)}, price_line=PRICE), composer)
    assert composer.requests[0].price_text == PRICE
    assert composed[0].params["printed"]["price"] is True


def test_a_price_that_does_not_fit_is_rewritten_once_and_drawn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = PricedWriter(spend=Decimal("0.05"))
    outcome = _outcome({0: _layer(0, price=True)}, price_line=PRICE)
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
        _compose(_outcome({0: _layer(0, price=True)}, price_line=PRICE), composer, writer=Writer())
    assert failed.value.failure == PRICE_FAILURE
    assert len(composer.requests) == 1  # the priceless rewrite is never drawn


def test_a_price_still_too_wide_fails_the_piece_never_drops_it() -> None:
    composer = Composer({0: ["refuse_price", "refuse_price"]})
    with pytest.raises(_MediaFailed) as failed:
        _compose(
            _outcome({0: _layer(0, price=True)}, price_line=PRICE), composer, writer=PricedWriter()
        )
    assert failed.value.failure == PRICE_FAILURE
    assert failed.value.detail == ""  # one reason on screen: the code's text
    assert len(composer.requests) == 2  # the layer, then its rewrite — no other attempt


def test_a_report_that_dropped_the_price_is_never_accepted() -> None:
    composer = Composer({0: ["drop_price", "drop_price"]})
    with pytest.raises(_MediaFailed) as failed:
        _compose(
            _outcome({0: _layer(0, price=True)}, price_line=PRICE), composer, writer=PricedWriter()
        )
    assert failed.value.failure == PRICE_FAILURE


def test_a_price_the_catalog_lost_is_never_drawn_without_it() -> None:
    composer = Composer()
    with pytest.raises(_MediaFailed) as failed:
        _compose(_outcome({0: _layer(0, price=True)}, price_line=PRICE, prices=False), composer)
    assert failed.value.failure == PRICE_FAILURE and composer.requests == []

    composer = Composer()  # a rewrite that keeps the reference cannot print it either
    with pytest.raises(_MediaFailed):
        _compose(
            _outcome({0: _layer(0, price=True)}, price_line=PRICE, prices=False),
            composer,
            writer=PricedWriter(),
        )
    assert composer.requests == []


def test_a_failed_rewrite_fails_the_piece() -> None:
    composer = Composer({0: ["refuse_price"]})
    with pytest.raises(_MediaFailed) as failed:
        _compose(
            _outcome({0: _layer(0, price=True)}, price_line=PRICE),
            composer,
            writer=Writer(fail=True),
        )
    assert failed.value.failure == PRICE_FAILURE


def test_a_refusal_is_never_retried_as_such() -> None:
    """`invalid_parameters` (with or without a refusal body) is not an attempt to repeat: the
    same layer refuses the same way. Only the rewrite is composed again."""
    for step in ("refuse", "invalid"):
        composer = Composer({0: [step, step]})
        with pytest.raises(_MediaFailed) as failed:
            _compose(_outcome({0: _layer(0)}), composer)
        assert failed.value.failure == COMPOSE_FAILURE
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
    assert failed.value.failure == COMPOSE_FAILURE
    assert failed.value.detail == ""


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
    assert failed.value.failure == COMPOSE_FAILURE
    assert failed.value.detail == ""


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
    assert failed.value.failure == COMPOSE_FAILURE


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
    assert failed.value.failure == COMPOSE_FAILURE


def test_the_rewrite_is_a_layer_step_of_its_own(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replayed like the stage's own calls: a restart reads the rewrite back, pays nothing."""
    checkpoints, store = JsonCheckpoints(), MemoryStore()
    writer = PricedWriter()
    outcome = _outcome({0: _layer(0, price=True)}, price_line=PRICE)
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
        _outcome({0: _layer(0, price=True)}, price_line=PRICE),
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


# -- review 2026-11-16 ---------------------------------------------------------------------


def test_review1_a_cover_without_the_piece_s_price_is_rewritten_never_drawn() -> None:
    """`price_line` set: the first image without its price reference is refused (slot price)
    before any render, rewritten once, and drawn only with the price."""
    composer = Composer()
    writer = PricedWriter()
    composed = _compose(_outcome({0: _layer(0)}, price_line=PRICE), composer, writer=writer)
    assert "price goes on this image" in writer.requests[0].rewrite_note
    assert len(composer.requests) == 1 and composer.requests[0].price_text == PRICE
    assert composed[0].layer.spec["price_ref"] == {"product_id": PRODUCT}

    composer = Composer()
    with pytest.raises(_MediaFailed) as failed:  # the rewrite still leaves it out
        _compose(_outcome({0: _layer(0)}, price_line=PRICE), composer, writer=Writer())
    assert failed.value.failure == PRICE_FAILURE and composer.requests == []


def test_review1_a_single_image_carries_its_price_once() -> None:
    composer = Composer()
    outcome = _outcome({0: _layer(0, price=True)}, price_line=PRICE)
    assert set(_compose(outcome, composer)) == {0} and len(composer.requests) == 1


def _carousel(layers: dict[int, LayerWrite], count: int, price_line: str = PRICE) -> LayerOutcome:
    """A carousel's outcome: `count` slides in all (the closing one has no layer)."""
    outcome = _outcome(layers, price_line=price_line)
    request = replace(outcome.request, piece_type=CAROUSEL, slide_count=count)
    return replace(outcome, request=request)


def test_review2_a_carousel_carries_its_price_on_one_development_slide() -> None:
    """Catalog §4/§6: never on the cover; once per product. A priced development slide is
    drawn as it is; the cover is drawn without a price."""
    composer = Composer()
    outcome = _carousel({0: _layer(0), 1: _layer(1, price=True), 2: _layer(2)}, count=4)
    composed = _compose(outcome, composer)
    assert set(composed) == {0, 1, 2}
    assert [r.price_text for r in composer.requests] == ["", PRICE, ""]


def test_review2_a_price_on_the_carousel_cover_is_refused_and_moved() -> None:
    writer = PricedWriter()  # its rewrite puts the price on the slide it is asked for
    composer = Composer()
    outcome = _carousel({0: _layer(0, price=True), 1: _layer(1)}, count=3)
    with pytest.raises(_MediaFailed) as failed:
        # the cover is refused (misplaced) and slide 1 (missing): one rewrite for both; the
        # rewrite prices both again — the cover still misplaced: the piece fails
        _compose(outcome, composer, writer=writer)
    assert failed.value.failure == PRICE_FAILURE
    assert sorted(s.position for s in writer.requests[0].slides) == [0, 1]
    assert composer.requests == []  # nothing drawn while the price is in the wrong place


def test_review2_a_second_price_in_the_piece_is_refused() -> None:
    composer, writer = Composer(), PricedWriter()
    outcome = _carousel({0: _layer(0), 1: _layer(1, price=True), 2: _layer(2, price=True)}, 4)
    with pytest.raises(_MediaFailed) as failed:
        _compose(outcome, composer, writer=writer)  # its rewrite prices slide 2 again
    assert failed.value.failure == PRICE_FAILURE
    assert "already on image 1" in writer.requests[0].rewrite_note


def test_review2_a_carousel_without_development_slides_prices_its_cover() -> None:
    """Cover + closing only: §4 excludes only «portada de carrusel con varios productos»."""
    composer = Composer()
    outcome = _carousel({0: _layer(0, price=True)}, count=2)
    assert set(_compose(outcome, composer)) == {0}
    assert composer.requests[0].price_text == PRICE


def test_review2_the_layer_validation_and_the_compositor_share_one_rule() -> None:
    from qualify_api.creative.image_pipeline.layer import piece_price_problems, price_slots

    request = _carousel({0: _layer(0)}, count=5).request
    assert price_slots(request) == (1, 2, 3)
    assert set(piece_price_problems(request, {0}, {0, 1, 2})) == {0, 1}  # misplaced, missing
    assert piece_price_problems(request, {2}, {0, 1, 2}) == {}
    assert set(piece_price_problems(request, {1, 3}, {0, 1, 3})) == {3}
    unpriced = _carousel({0: _layer(0)}, count=5, price_line="").request
    assert price_slots(unpriced) == () and piece_price_problems(unpriced, {1}, {1}) == {}


@pytest.mark.parametrize(
    ("found", "line", "ref", "status", "label"),
    [
        ((("Shawarma mixto", "$12.000"),), "", "Shawarma mixto", "hidden", ""),
        ((("Shawarma mixto", "$12.000"),), "$12.000", "Shawarma mixto", "matches", "$12.000"),
        # the price changed since the brief: today's label, recorded as changed
        ((("Shawarma mixto", "$13.500"),), "$12.000", "Shawarma mixto", "changed", "$13.500"),
        # renamed: the only match is still the brief's product
        ((("Shawarma mixto XL", "$13.500"),), "$12.000", "Shawarma mixto", "changed", "$13.500"),
        ((), "$12.000", "Shawarma mixto", "product_not_found", ""),
        ((("Shawarma mixto", ""),), "$12.000", "Shawarma mixto", "no_price_today", ""),
        (
            (("Shawarma de pollo", "$11.000"), ("Shawarma de res", "$13.000")),
            "$12.000",
            "Shawarma",
            "ambiguous",
            "",
        ),
    ],
)
def test_review1_the_catalog_decides_the_price_never_the_stale_line(
    found: tuple[tuple[str, str], ...], line: str, ref: str, status: str, label: str
) -> None:
    products = tuple(
        CatalogProduct(uuid4(), name, has_price=bool(text), price_text=text) for name, text in found
    )
    offered, price = resolve_piece_price(products, price_line=line, product_ref=ref)
    assert (price.status, price.label, price.brief_line) == (status, label, line.strip())
    assert sum(p.has_price for p in offered) == (1 if label else 0)
    assert price.provenance()["catalog_price_label"] == label


def test_review1_a_stale_price_line_is_never_a_dead_end() -> None:
    """The product lost its price since the brief: the piece shows none — nothing required,
    the layer drawn without a price, no rewrite."""
    from qualify_creative.enums import ContentKind

    from qualify_api.creative.image_pipeline import layer_run

    from .test_creative_media_byteplus import _brief

    gone = CatalogProduct(uuid4(), "Shawarma mixto", has_price=False, price_text="")
    producer = SimpleNamespace()
    writer = Writer()
    _wire(producer, writer, [])
    producer._layer_context = lambda tenant, brand, ref: (BusinessFacts(), (gone,))
    outcome = layer_run.run_layer_stage(
        producer,
        tenant_id=TENANT_ID,
        draft_id=DRAFT,
        revision=1,
        brief=_brief(ContentKind.STATIC_FLYER),
        copy=COPY,
        brand="Korner",
        scenes={0: BaseScene(b"a", "p0")},
        regenerate=lambda p: None,
        gallery=False,
        price_line="$12.000",
        env=ON,
    )
    assert writer.requests[0].price_line == "" and outcome.prices == {}
    assert outcome.price is not None and outcome.price.status in {
        "no_price_today",
        "product_not_found",
    }
    composer = Composer()
    composed = _compose(outcome, composer, writer=writer)
    assert set(composed) == {0} and len(writer.requests) == 1  # no rewrite
    assert composed[0].params["price_status"] == outcome.price.status
    assert composed[0].params["brief_price_line"] == "$12.000"
    assert composed[0].params["catalog_price_label"] == ""


def test_review1_a_changed_price_prints_today_s_label_and_records_both() -> None:
    from qualify_creative.enums import ContentKind

    from qualify_api.creative.image_pipeline import layer_run

    from .test_creative_media_byteplus import _brief

    mine = CatalogProduct(uuid4(), "Shawarma mixto", has_price=True, price_text="$13.500")
    other = CatalogProduct(uuid4(), "Shawarma grande", has_price=True, price_text="$12.000")
    producer = SimpleNamespace()
    writer = Writer()
    _wire(producer, writer, [])
    producer._layer_context = lambda tenant, brand, ref: (BusinessFacts(), (mine, other))
    brief = _brief(ContentKind.STATIC_FLYER).model_copy(update={"product_ref": "Shawarma mixto"})
    outcome = layer_run.run_layer_stage(
        producer,
        tenant_id=TENANT_ID,
        draft_id=DRAFT,
        revision=1,
        brief=brief,
        copy=COPY,
        brand="Korner",
        scenes={0: BaseScene(b"a", "p0")},
        regenerate=lambda p: None,
        gallery=False,
        price_line="$12.000",  # the brief's line: now another product's price
        env=ON,
    )
    request = writer.requests[0]
    assert request.price_line == "$13.500"
    assert [p.has_price for p in request.products] == [True, False]
    assert outcome.prices == {str(mine.product_id): "$13.500"}
    assert outcome.price.provenance() == {
        "price_status": "changed",
        "brief_price_line": "$12.000",
        "catalog_price_label": "$13.500",
    }


def test_review2_the_pillow_cover_never_prints_the_price_twice_nor_stale() -> None:
    from qualify_api.creative.image_pipeline.compose import _pillow_price

    priced = _carousel({1: _layer(1, price=True)}, count=4)
    drawn = _compose(priced, Composer())
    assert _pillow_price("$9.999", priced, drawn) == ""  # a development slide carries it
    assert _pillow_price("$9.999", priced, {}) == PRICE  # nothing composed: today's label
    hidden = _carousel({1: _layer(1)}, count=4, price_line="")
    assert _pillow_price("$9.999", hidden, {}) == ""  # no price today: never the stale line
    off = LayerOutcome(scenes={}, layers={})
    assert _pillow_price("$9.999", off, {}) == "$9.999"  # off: as before


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (ComposeJobFailed("render_error", 500, "x"), "transient"),
        (RenderTimeout("timeout", 504, "waited"), "transient"),
        (RenderServiceError("internal_error", 500, "x"), "transient"),
        (RenderServiceError("internal_error", 502, "bad gateway"), "outage"),
        (RenderServiceError("internal_error", 503, "x"), "outage"),
        (RenderServiceError("timeout", 504, "proxy"), "outage"),
        (RenderServiceError("not_found", 404, "x"), "fatal"),
        (RenderServiceError("not_ready", 409, "x"), "fatal"),
        (RenderServiceError("invalid_parameters", 422, "x"), "refused"),
        (ConnectionError("refused"), "outage"),
        (httpx.ConnectError("refused"), "outage"),
        (compose_run.RenderUnavailable("none"), "outage"),
        (KeyError("bug"), "fatal"),
    ],
)
def test_review3_failures_are_classified(exc: BaseException, kind: str) -> None:
    assert compose_run._kind(exc) == kind


class Raising(Composer):
    def __init__(self, exc: BaseException) -> None:
        super().__init__()
        self.exc = exc

    def __call__(self, request: Any, read_media: Any) -> Any:
        self.requests.append(request)
        raise self.exc


def test_review3_a_rejected_request_fails_at_once_and_5xx_spends_attempts() -> None:
    composer = Raising(RenderServiceError("not_found", 404, "no template"))
    with pytest.raises(_MediaFailed) as failed:
        _compose(_outcome({0: _layer(0)}), composer)
    assert failed.value.failure == COMPOSE_FAILURE and len(composer.requests) == 1

    composer = Raising(RenderServiceError("internal_error", 500, "crash"))
    with pytest.raises(_MediaFailed):
        _compose(_outcome({0: _layer(0)}), composer)
    assert [r.attempt for r in composer.requests] == [0, 1, 2]

    composer = Raising(RenderServiceError("internal_error", 503, "down"))
    with pytest.raises(_MediaFailed):  # inline: nothing can wait
        _compose(_outcome({0: _layer(0)}), composer)
    assert len(composer.requests) == 1


def test_review4_an_outage_tries_at_most_once_per_backoff(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("QUALIFY_IMAGE_LAYER", "on")
    checkpoints, clock = JsonCheckpoints(), Clock()
    outcome = _outcome({0: _layer(0)})
    run = pipeline.Preparation(TENANT_ID, DRAFT, 1, "generation", uuid4(), 1)
    compose_run._last_wait_log.clear()
    with caplog.at_level("WARNING", logger=compose_run.__name__):
        with pytest.raises(RenderWait):
            _in_pass(checkpoints, monkeypatch, outcome, Composer({0: ["outage"]}), clock=clock)
        assert checkpoints.rows[outage_step(0)]["request"]["at"] == T0.isoformat()
        # the next passes within 45 s stop before anything is replayed
        for seconds in (1, 20, 44):
            with pytest.raises(RenderWait):
                raise_if_waiting(run, now=T0 + timedelta(seconds=seconds))
    waits = [r for r in caplog.records if "waits" in r.getMessage()]
    assert len(waits) == 1  # four stopped passes, one WARNING (once a minute)
    assert all(r.levelname == "WARNING" for r in waits)
    raise_if_waiting(run, now=T0 + timedelta(seconds=46))  # a new bucket: this pass tries
    raise_if_waiting(run, now=T0 + timedelta(minutes=10))  # past the window: goes on, fails
    assert issubclass(RenderWait, CheckpointError)  # the worker retries it


def test_review4_off_the_wait_reads_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUALIFY_IMAGE_LAYER", raising=False)

    class Untouchable:
        def load_step(self, *args: Any) -> None:
            raise AssertionError("read with the switch off")

    monkeypatch.setattr(pipeline, "PipelineStore", Untouchable)
    raise_if_waiting(pipeline.Preparation(TENANT_ID, DRAFT, 1, "generation", uuid4(), 1))


def test_review5_the_lease_is_kept_while_the_slides_render(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager

    kept: list[Any] = []

    @contextmanager
    def lease_kept(store: Any, run: Any):  # noqa: ANN202
        kept.append(run)
        yield

    monkeypatch.setattr(pipeline, "lease_kept", lease_kept)
    _in_pass(JsonCheckpoints(), monkeypatch, _outcome({0: _layer(0)}), Composer())
    assert len(kept) == 1
    _compose(_outcome({0: _layer(0)}), Composer())  # inline: no lease to keep
    assert len(kept) == 1


class CountingStore(MemoryStore):
    def __init__(self) -> None:
        super().__init__()
        self.reads: list[str] = []

    def read(self, key: str) -> bytes:
        self.reads.append(key)
        return super().read(key)


def test_review6_only_the_still_a_reel_needs_is_kept_in_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcome = _outcome({0: _layer(0), 1: _layer(1)})
    composed = _compose(outcome, Composer())
    assert all(c.image is None for c in composed.values())
    composed = _compose(outcome, Composer(), keep_images={0})
    assert composed[0].image is not None and composed[1].image is None

    checkpoints, store = JsonCheckpoints(), CountingStore()
    _in_pass(checkpoints, monkeypatch, outcome, Composer(), store=store, keep_images={0})
    store.reads.clear()
    again = _in_pass(checkpoints, monkeypatch, outcome, Composer(), store=store, keep_images={0})
    assert store.reads == [again[0].key]  # a replay reads back the Reel's still only


def test_review4_the_wait_log_is_bounded_and_forgets_finished_pieces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compose_run._last_wait_log.clear()
    for _ in range(compose_run._WAIT_LOG_MAX + 40):
        run = pipeline.Preparation(TENANT_ID, uuid4(), 1, "generation", uuid4(), 1)
        compose_run._log_wait(run, T0, "down")
    assert len(compose_run._last_wait_log) == compose_run._WAIT_LOG_MAX
    # a piece that composes after waiting is dropped from it
    mine = pipeline.Preparation(TENANT_ID, DRAFT, 1, "generation", uuid4(), 1)
    compose_run._log_wait(mine, T0, "down")
    assert (TENANT_ID, DRAFT, 1) in compose_run._last_wait_log
    _compose(_outcome({0: _layer(0)}), Composer())
    assert (TENANT_ID, DRAFT, 1) not in compose_run._last_wait_log

"""m-25042157: the layer calls (Claude Sonnet 5.5) are part of the piece's cost — one usage
line per paid call with provider, model, tokens and cost (the service adds the pricing
table version), on every pass, never twice; the rewrite and a call that failed after
paying are booked too. First real piece in production (2026-11-17) had none."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from qualify_api.claude_tools import CallStats
from qualify_api.creative import pipeline
from qualify_api.creative.brand_references import BrandReferencesSet
from qualify_api.creative.image_pipeline.layer import LayerError, LayerRequest, LayerResult
from qualify_api.creative.media import MediaUsage

from .test_creative_media_byteplus import BUDGET, COPY, TENANT_ID, _kit
from .test_image_compose_run import PRICE, PricedWriter, _compose, _layer, _outcome
from .test_image_layer_run import Composer, JsonCheckpoints, Writer, _wire
from .test_v9_flyer_consumer import (  # noqa: F401 - `no_generation` is autouse
    gallery_setup,
    no_generation,
)

SONNET = "claude-sonnet-5-5"
STATS = CallStats(SONNET, None, input_tokens=6000, output_tokens=900, cache_read_tokens=0)
#: Sonnet 5.5: US$2 in / US$10 out per million tokens (pricing v10, claude_tools.PRICES)
COST = Decimal("0.012") + Decimal("0.009")


class PayingWriter(Writer):
    def __call__(self, request: LayerRequest, *, budget: Any) -> LayerResult:
        result = super().__call__(request, budget=budget)
        result.stats = STATS
        return result


class PayingPricedWriter(PricedWriter):
    def __call__(self, request: LayerRequest, *, budget: Any) -> LayerResult:
        result = super().__call__(request, budget=budget)
        result.stats = STATS
        return result


def _usd(value: Decimal) -> Decimal:
    """As the ledger prints it (6 decimals): the per-token sum is a float, like the copy's."""
    return value.quantize(Decimal("0.000001"))


def _layer_lines(usage: Any) -> list[MediaUsage]:
    return [u for u in usage if u.model_id == SONNET]


def _run(producer: Any, brief: Any, draft: Any) -> Any:
    return producer.produce(
        tenant_id=TENANT_ID,
        draft_id=draft,
        brief=brief,
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
        brand_references=BrandReferencesSet(block_version=9),
    )


def test_the_layer_call_is_in_the_piece_s_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUALIFY_IMAGE_LAYER", "on")
    producer, brief, _ = gallery_setup(monkeypatch)
    _wire(producer, PayingWriter(), [])
    outcome = _run(producer, brief, uuid4())
    assert outcome.failure is None
    [line] = _layer_lines(outcome.usage)
    assert (line.provider, line.unit) == ("anthropic", "token")
    assert (line.input_tokens, line.output_tokens) == (6000, 900)
    assert _usd(line.cost_usd) == COST
    assert outcome.spent_usd >= COST  # it counts in what the piece spent


def test_a_replay_books_the_call_once_and_pays_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import patch

    from qualify_api.creative.pipeline import CheckpointRouter

    monkeypatch.setenv("QUALIFY_IMAGE_LAYER", "on")
    producer, brief, _ = gallery_setup(monkeypatch)
    writer = PayingWriter()
    _wire(producer, writer, [])
    checkpoints, draft, router = JsonCheckpoints(), uuid4(), producer._router

    def one_pass() -> Any:
        producer._router = CheckpointRouter(router, checkpoints, producer._store)
        run = pipeline.Preparation(TENANT_ID, draft, 1, "generation", uuid4(), 1)
        with patch("qualify_api.creative.pipeline.PipelineStore", return_value=checkpoints):
            with pipeline.preparing(run):
                return _run(producer, brief, draft)

    first, second = one_pass(), one_pass()
    assert len(writer.requests) == 1  # the second pass read the answer back
    assert len(_layer_lines(first.usage)) == len(_layer_lines(second.usage)) == 1
    assert _usd(_layer_lines(second.usage)[0].cost_usd) == COST


def test_the_rewrite_is_booked_too() -> None:
    outcome = _outcome({0: _layer(0)}, price_line=PRICE)
    outcome = type(outcome)(**{**outcome.__dict__, "usage": []})
    _compose(outcome, Composer(), writer=PayingPricedWriter())
    assert [_usd(u.cost_usd) for u in _layer_lines(outcome.usage)] == [COST]


def test_a_call_that_failed_after_paying_is_booked() -> None:
    from types import SimpleNamespace

    from qualify_creative.enums import ContentKind

    from qualify_api.creative.image_pipeline import layer_run
    from qualify_api.creative.image_pipeline.base import BaseScene
    from qualify_api.creative.image_pipeline.layer import BusinessFacts

    from .test_creative_media_byteplus import _brief

    def failing(request: LayerRequest, *, budget: Any) -> LayerResult:
        raise LayerError("no tool call", stats=STATS)

    producer = SimpleNamespace()
    _wire(producer, Writer(), [])
    producer._layer_writer = failing
    producer._layer_context = lambda tenant, brand, ref: (BusinessFacts(), ())
    usage: list[MediaUsage] = []
    outcome = layer_run.run_layer_stage(
        producer,
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        revision=1,
        brief=_brief(ContentKind.STATIC_FLYER),
        copy=COPY,
        brand="Korner",
        scenes={0: BaseScene(b"a", "p0")},
        regenerate=lambda p: None,
        gallery=False,
        usage=usage,
        env={"QUALIFY_IMAGE_LAYER": "on"},
    )
    assert outcome.layers == {}
    assert [_usd(u.cost_usd) for u in _layer_lines(usage)] == [COST]


def test_the_service_writes_the_line_with_its_pricing_table() -> None:
    from qualify_api.creative.service import ContentService

    line = MediaUsage(
        provider="anthropic",
        model_id=SONNET,
        unit="token",
        quantity=6900,
        cost_usd=COST,
        output_tokens=900,
        input_tokens=6000,
    )
    service = ContentService.__new__(ContentService)
    service._pricing = type("P", (), {"version": "v10"})()
    [write] = service._media_usage([line])
    assert (write.provider, write.model_id, write.pricing_table_version) == (
        "anthropic",
        SONNET,
        "v10",
    )
    assert (write.input_tokens, write.output_tokens, write.cost_usd) == (6000, 900, COST)

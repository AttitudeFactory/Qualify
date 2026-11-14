"""m-25017283: the layer stage inside a generation. Off by default (no call, nothing
changes); on, the advertising image and the gallery get one layer call each, a base with
invented text is made again ONCE when its regeneration is claimed, and any failure leaves
the piece without a layer — never without the piece."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from qualify_creative.layer_spec import LayerSpec

from qualify_api.creative.brand_references import BrandReferencesSet
from qualify_api.creative.image_pipeline.layer import BusinessFacts, LayerRequest, LayerResult

from .test_creative_media_byteplus import BUDGET, COPY, TENANT_ID, _kit
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
    def __init__(self, *, invented: tuple[int, ...] = (), fail: bool = False) -> None:
        self.requests: list[LayerRequest] = []
        self.invented = invented
        self.fail = fail

    def __call__(self, request: LayerRequest) -> LayerResult:
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("model down")
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

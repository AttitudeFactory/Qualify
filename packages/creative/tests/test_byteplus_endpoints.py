"""The ModelArk adapters never reach a preset endpoint by accident (m-24820898). The
presets of Seedance 1.0 pro and Seedream 5.0 lite are authorized in BytePlus's «Data
Collaboration» campaign — everything sent there is licensed to BytePlus perpetually — and
a bare model id is how a preset is called. So the wire carries the configured custom
endpoint (`ep-…`), a model without one is refused before any request, and only the
explicit internal-eval flag lets a bare id through. All offline, over MockTransport."""

from __future__ import annotations

import base64
import json
from decimal import Decimal
from uuid import uuid4

import pytest

httpx = pytest.importorskip("httpx")

from qualify_creative.adapters import (  # noqa: E402
    ArkPresetRefused,
    SeedanceVideoAdapter,
    SeedreamImageAdapter,
)
from qualify_creative.adapters.byteplus_ark import (  # noqa: E402
    DEFAULT_SEEDANCE_MODEL,
    DEFAULT_SEEDREAM_MODEL,
    parse_endpoints,
)
from qualify_creative.enums import GenerationTask  # noqa: E402
from qualify_creative.pricing import JsonPricingTable  # noqa: E402
from qualify_creative.providers import GenerationRequest, RenderedPrompt  # noqa: E402
from qualify_creative.router import BudgetContext, CreativeRouter  # noqa: E402

V2 = "dreamina-seedance-2-0-mini-260615"
PRODUCT = "data:image/jpeg;base64,AAAA"  # a client's product photo, as the generator sends it


class Wire:
    """A ModelArk that records every request and answers a finished image or task."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/images/generations"):
            return httpx.Response(
                200, json={"data": [{"b64_json": base64.b64encode(b"j").decode()}]}
            )
        if request.method == "POST":
            return httpx.Response(200, json={"id": "cgt-1"})
        return httpx.Response(
            200,
            json={"id": "cgt-1", "status": "succeeded", "content": {"video_url": "https://v"}},
        )

    def models(self) -> list[str]:
        return [json.loads(r.content)["model"] for r in self.requests if r.method == "POST"]


def _image(**params: object) -> GenerationRequest:
    return GenerationRequest(
        task=GenerationTask.PRODUCT_IMAGE,
        rendered_prompt=RenderedPrompt("", "", ""),
        params={"prompt": "La hamburguesa de la marca.", "images": [PRODUCT], **params},
    )


def _video(**params: object) -> GenerationRequest:
    return GenerationRequest(
        task=GenerationTask.SCENE_VIDEO,
        rendered_prompt=RenderedPrompt("", "", ""),
        params={"prompt": "El producto gira.", "first_frame": PRODUCT, **params},
    )


def _seedance(wire: Wire, **kw: object) -> SeedanceVideoAdapter:
    return SeedanceVideoAdapter(
        transport=httpx.MockTransport(wire),
        sleep=lambda _: None,
        **kw,  # type: ignore[arg-type]
    )


def test_by_default_a_bare_model_id_is_refused_before_any_request() -> None:
    wire = Wire()
    with pytest.raises(ArkPresetRefused, match="preset refused") as refused:
        SeedreamImageAdapter(transport=httpx.MockTransport(wire)).generate(_image(), api_key="k")
    assert refused.value.model_id == DEFAULT_SEEDREAM_MODEL
    with pytest.raises(ArkPresetRefused):
        _seedance(wire).generate(_video(), api_key="k")
    assert wire.requests == []  # not one byte of the brand's material left


def test_the_wire_carries_the_custom_endpoint_and_the_result_keeps_the_model() -> None:
    wire = Wire()
    endpoints = {DEFAULT_SEEDREAM_MODEL: "ep-img", DEFAULT_SEEDANCE_MODEL: "ep-vid"}
    image = SeedreamImageAdapter(transport=httpx.MockTransport(wire), endpoints=endpoints)
    video = _seedance(wire, endpoints=endpoints)
    image_result = image.generate(_image(), api_key="k")
    video_result = video.generate(_video(), api_key="k")
    assert wire.models() == ["ep-img", "ep-vid"]
    # pricing, usage and provenance stay on the model id
    assert image_result.model_id == DEFAULT_SEEDREAM_MODEL
    assert video_result.model_id == DEFAULT_SEEDANCE_MODEL


def test_a_per_request_model_needs_its_own_endpoint() -> None:
    """The clip with references switches to a 2.x model per request (`params["model"]`):
    the default's endpoint does not cover it."""
    wire = Wire()
    adapter = _seedance(wire, endpoints={DEFAULT_SEEDANCE_MODEL: "ep-vid"})
    with pytest.raises(ArkPresetRefused) as refused:
        adapter.generate(
            _video(model=V2, first_frame=None, reference_images=[PRODUCT]), api_key="k"
        )
    assert refused.value.model_id == V2 and wire.requests == []


def test_only_the_explicit_eval_flag_sends_a_bare_id() -> None:
    wire = Wire()
    SeedreamImageAdapter(transport=httpx.MockTransport(wire), allow_presets=True).generate(
        _image(), api_key="k"
    )
    assert wire.models() == [DEFAULT_SEEDREAM_MODEL]
    # a configured endpoint still wins over the flag
    SeedreamImageAdapter(
        transport=httpx.MockTransport(wire),
        endpoints={DEFAULT_SEEDREAM_MODEL: "ep-img"},
        allow_presets=True,
    ).generate(_image(), api_key="k")
    assert wire.models()[-1] == "ep-img"


@pytest.mark.parametrize("endpoint", [DEFAULT_SEEDREAM_MODEL, "", "seedream-endpoint"])
def test_an_endpoint_that_is_not_an_ep_id_fails_at_wiring(endpoint: str) -> None:
    """A model id pasted as the "endpoint" would be the preset again."""
    with pytest.raises(ValueError, match="custom endpoint id"):
        SeedreamImageAdapter(endpoints={DEFAULT_SEEDREAM_MODEL: endpoint})


def test_the_cost_estimate_still_works_without_an_endpoint() -> None:
    """The pre-flight prices by model id and sends nothing; the refusal is at `generate`."""
    assert SeedreamImageAdapter().estimate_cost_usd(_image(), JsonPricingTable("v3")) > 0


def test_through_the_router_a_refusal_is_a_failed_hop_and_nothing_is_sent() -> None:
    class Key:
        api_key = "k"

    class Credentials:
        def resolve(self, **_: object) -> Key:
            return Key()

    wire = Wire()
    router = CreativeRouter(
        providers={"seedream": SeedreamImageAdapter(transport=httpx.MockTransport(wire))},
        pricing=JsonPricingTable("v3"),
        credentials=Credentials(),  # type: ignore[arg-type]
    )
    outcome = router.run(
        tenant_id=uuid4(),
        brand_id=uuid4(),
        chain=("seedream",),
        request=_image(),
        budget=BudgetContext(remaining_usd=Decimal("1")),
    )
    assert outcome.result is None
    (hop,) = outcome.hops
    assert hop.reason is not None and hop.reason.startswith("ArkPresetRefused")
    assert wire.requests == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, {}),
        ("", {}),
        ("  ", {}),
        ("seedream-5-0-lite-260128=ep-a", {"seedream-5-0-lite-260128": "ep-a"}),
        (
            " seedance-1-0-pro-250528 = ep-b , dreamina-seedance-2-0-mini-260615=ep-c ,",
            {"seedance-1-0-pro-250528": "ep-b", "dreamina-seedance-2-0-mini-260615": "ep-c"},
        ),
    ],
)
def test_parse_endpoints(raw: str | None, expected: dict[str, str]) -> None:
    assert parse_endpoints(raw) == expected


@pytest.mark.parametrize(
    ("raw", "match"),
    [
        ("ep-a", "is not 'model=ep-…'"),
        ("seedream-5-0-lite-260128=", "is not 'model=ep-…'"),
        ("=ep-a", "is not 'model=ep-…'"),
        ("m=ep-a,m=ep-b", "given twice"),
    ],
)
def test_a_malformed_endpoint_list_fails_loudly(raw: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        parse_endpoints(raw)

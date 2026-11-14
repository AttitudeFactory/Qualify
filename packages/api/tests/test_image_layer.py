"""m-25017283: the layer stage — one Claude call per piece with its photos, answered with
the `escribir_capa` tool and turned into validated `LayerSpec`s. No datum comes from the
model: info values are the saved business data, a price is a catalog product id with a
price. A broken slide gets one repair turn, then the catalog's fallbacks."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from qualify_api import claude_tools
from qualify_api.creative.image_pipeline import layer
from qualify_api.creative.image_pipeline.layer import (
    CAROUSEL,
    PRODUCT_PROMOTION,
    BusinessFacts,
    CatalogProduct,
    LayerError,
    LayerRequest,
    SlideInput,
    layer_enabled,
    write_layers,
)

TENANT, BRAND = uuid4(), uuid4()
PRODUCT = CatalogProduct(uuid4(), "Shawarma mixto", has_price=True)
NO_PRICE = CatalogProduct(uuid4(), "Limonada", has_price=False)
PHOTO = b"\xff\xd8 a jpeg"
SEEN = {
    "subject_box": [0.3, 0.4, 0.8, 0.9],
    "logo_in_photo": False,
    "base_has_invented_text": False,
}


def _slide(**over: Any) -> dict[str, Any]:
    raw = {
        "position": 0,
        "foto": SEEN,
        "layout_id": "plate",
        "anchor": "top_left",
        "container_color": "surface",
        "accent_word": -1,
        "title": "Tu shawarma, recién hecho",
        "subtitle": "",
        "call_phrase": "Pídelo por WhatsApp",
        "info_blocks": [],
        "price_product_id": str(PRODUCT.product_id),
        "highlight_kind": "none",
        "highlight_icon_id": "none",
        "highlight_word": "",
    }
    raw.update(over)
    return raw


def _response(slides: list[dict[str, Any]] | None, use_id: str = "toolu_1") -> Any:
    content = (
        [
            SimpleNamespace(
                type="tool_use", name=layer.LAYER_TOOL, input={"slides": slides}, id=use_id
            )
        ]
        if slides is not None
        else [SimpleNamespace(type="text", text="no")]
    )
    usage = SimpleNamespace(
        input_tokens=2_000,
        output_tokens=300,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )
    return SimpleNamespace(
        id="msg_1", usage=usage, model="claude-sonnet-5-5", stop_reason="tool_use", content=content
    )


class FakeClient:
    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def no_ledger(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    rows: list[Any] = []
    monkeypatch.setattr(claude_tools, "_consumption_sink", rows.append)
    return rows


def _request(count: int = 1, **over: Any) -> LayerRequest:
    values: dict[str, Any] = {
        "tenant_id": TENANT,
        "brand_id": BRAND,
        "format": "4:5",
        "piece_type": PRODUCT_PROMOTION if count == 1 else CAROUSEL,
        "slides": tuple(SlideInput(position=p, photo=PHOTO) for p in range(count)),
        "topic": "Shawarma mixto",
        "facts": BusinessFacts(location="C.C. Las Palmas, local 5", contact="+57 300 123 4567"),
        "products": (PRODUCT, NO_PRICE),
    }
    values.update(over)
    return LayerRequest(**values)


def _run(request: LayerRequest, *responses: Any) -> tuple[layer.LayerResult, FakeClient]:
    client = FakeClient(*responses)
    return write_layers(request, api_key="k", client_factory=lambda _key: client), client


def test_the_switch_is_off_by_default() -> None:
    assert not layer_enabled({})
    assert not layer_enabled({"QUALIFY_IMAGE_LAYER": "1"})
    assert layer_enabled({"QUALIFY_IMAGE_LAYER": "on"})


def test_one_call_writes_a_valid_layer_with_the_photo_and_books_the_business(no_ledger) -> None:
    result, client = _run(_request(), _response([_slide()]))
    spec = result.specs[0]
    assert spec.layout_id.value == "plate" and spec.price_ref.product_id == PRODUCT.product_id
    assert result.failed == {} and result.invented_text == [] and len(client.requests) == 1
    request = client.requests[0]
    images = [b for b in request["messages"][0]["content"] if b["type"] == "image"]
    assert len(images) == 1 and images[0]["source"]["type"] == "base64"
    assert request["tools"][0]["name"] == "escribir_capa"
    assert "temperature" not in request and "top_p" not in request
    assert [r.attribution.feature for r in no_ledger] == ["capa-de-texto"]
    assert no_ledger[0].attribution.tenant_id == TENANT


def test_a_carousel_is_one_call_with_all_its_photos() -> None:
    slides = [
        _slide(position=0),
        _slide(position=1, layout_id="band", anchor="bottom", price_product_id=""),
        _slide(
            position=2,
            layout_id="brand_fill",
            anchor="none",
            title="Te esperamos hoy",
            price_product_id="",
            info_blocks=["contact"],
            container_color="accent",
        ),
    ]
    result, client = _run(_request(3), _response(slides))
    assert len(client.requests) == 1
    assert sum(b["type"] == "image" for b in client.requests[0]["messages"][0]["content"]) == 3
    assert [result.specs[p].carousel.role.value for p in range(3)] == ["cover", "body", "closing"]
    closing = result.specs[2]
    assert closing.info_blocks[0].label == "Pedidos"
    assert closing.info_blocks[0].value == "+57 300 123 4567"  # the saved datum, verbatim


def test_a_price_the_model_points_at_is_only_a_priced_catalog_product() -> None:
    bad = _slide(price_product_id=str(NO_PRICE.product_id))
    good = _slide(price_product_id="")
    result, client = _run(_request(), _response([bad]), _response([good], "toolu_2"))
    assert result.specs[0].price_ref is None and result.repairs == 1
    repair = client.requests[1]["messages"][-1]["content"][0]
    assert repair["type"] == "tool_result" and "with a price" in repair["content"]


def test_an_info_block_without_saved_data_is_refused() -> None:
    raw = _slide(
        layout_id="brand_fill",
        anchor="none",
        title="Te esperamos este festivo",
        price_product_id="",
        info_blocks=["hours"],
    )
    fixed = {**raw, "info_blocks": []}
    result, _ = _run(_request(piece_type="free_idea"), _response([raw]), _response([fixed], "t2"))
    assert result.specs[0].info_blocks == ()


def test_a_slide_still_broken_after_its_repair_drops_phrase_then_subtitle() -> None:
    long_phrase = _slide(call_phrase="Escríbenos hoy mismo por WhatsApp y pide")
    result, _ = _run(_request(), _response([long_phrase]), _response([long_phrase], "t2"))
    assert result.specs[0].call_phrase is None and result.specs[0].title


def test_a_slide_that_cannot_be_saved_has_no_layer_never_a_guessed_one() -> None:
    label = _slide(title="Promoción")
    result, _ = _run(_request(), _response([label]), _response([label], "t2"))
    assert 0 not in result.specs and "label" in result.failed[0]


def test_invented_text_in_a_seedream_base_is_reported_for_one_regeneration() -> None:
    raw = _slide(foto={**SEEN, "base_has_invented_text": True})
    result, _ = _run(_request(), _response([raw]))
    assert result.invented_text == [0]


def test_the_owner_s_photo_is_never_invented() -> None:
    raw = _slide(foto={**SEEN, "base_has_invented_text": True})
    request = _request(slides=(SlideInput(0, PHOTO, owner_photo=True),))
    result, _ = _run(request, _response([raw]))
    assert result.invented_text == [] and not result.specs[0].photo.base_has_invented_text


def test_no_tool_call_twice_is_a_layer_error() -> None:
    with pytest.raises(LayerError):
        _run(_request(), _response(None), _response(None))


def test_a_photo_over_5_mb_is_not_sent() -> None:
    request = _request(slides=(SlideInput(0, b"x" * 5_000_000),))
    with pytest.raises(LayerError):
        _run(request)


# -- review fixes (capa-v2) -----------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Abrimos de martes a domingo",
        "Todos los días contigo",
        "Abierto 24 horas",
        "Ahora con 20% de descuento",
        "Bebida gratis con tu combo",
        "Domicilio a toda la ciudad",
        "Envío sin costo",
        "Shawarma 2x1",
        "Abierto hoy hasta tarde",
        "Estamos abiertos",
        "Cerrado los lunes",
        "Te esperamos el sábado",
    ],
)
def test_a_claim_not_in_the_brief_or_the_saved_data_asks_for_repair(text: str) -> None:
    assert layer.unsupported_claims(text, _request())


@pytest.mark.parametrize(
    ("text", "over"),
    [
        ("100% natural", {}),
        ("500 g de pollo", {}),
        ("Tu shawarma, al momento", {}),
        ("Martes de shawarma 2x1", {"topic": "Martes de 2x1 en shawarma"}),
        ("Domicilio en tu barrio", {"scene": "Pedido a domicilio en moto"}),
        ("Te esperamos, abrimos hoy", {"facts": BusinessFacts(hours="Lunes a sábado, 11 a 9")}),
        ("Envíos a toda la ciudad", {"topic": "Hacemos envíos a toda la ciudad"}),
        # the approved hook and invitation, and the catalog's product names, are sources
        ("Pide a domicilio", {"cta": "Pide a domicilio por WhatsApp"}),
        ("Martes de 2x1", {"hook": "Este martes, 2x1 en shawarmas"}),
        (
            "Tu Combo Domingo",
            {"products": (CatalogProduct(uuid4(), "Combo Domingo", has_price=True),)},
        ),
        # plain language, not a claim
        ("Cielo abierto", {}),
        ("Recién abierto el horno", {}),
        ("Tu sábado sabe mejor", {}),
        ("Para tus domingos en familia", {}),
    ],
)
def test_what_the_brief_or_the_saved_data_says_is_no_claim(text: str, over: Any) -> None:
    assert layer.unsupported_claims(text, _request(**over)) == []


def test_an_invented_promotion_gets_its_repair_turn() -> None:
    promo = _slide(title="Martes de shawarma 2x1")
    result, client = _run(_request(), _response([promo]), _response([_slide()], "t2"))
    assert result.repairs == 1 and result.specs[0].title == "Tu shawarma, recién hecho"
    assert "2x1" in client.requests[1]["messages"][-1]["content"][0]["content"]


@pytest.mark.parametrize(
    "foto", [{"logo_in_photo": False}, "a box", {**SEEN, "subject_box": ["x", 1, 1, 1]}]
)
def test_a_malformed_photo_answer_goes_to_repair_not_dropping_the_other_layers(foto: Any) -> None:
    slides = [_slide(position=0, foto=foto), _slide(position=1, price_product_id="")]
    fixed = [_slide(position=0), _slide(position=1, price_product_id="")]
    request = _request(2, piece_type=CAROUSEL)
    slides[1].update(layout_id="brand_fill", anchor="none", container_color="accent")
    fixed[1].update(layout_id="brand_fill", anchor="none", container_color="accent")
    result, client = _run(request, _response(slides), _response(fixed, "t2"))
    assert set(result.specs) == {0, 1} and result.failed == {} and result.repairs == 1
    assert "malformed answer" in client.requests[1]["messages"][-1]["content"][0]["content"]


@pytest.mark.parametrize(
    ("size", "tokens"),
    [((1280, 1600), 1532), ((1280, 1280), 1533), ((1080, 1920), 1532), ((1248, 1664), 1532)],
)
def test_image_tokens_follow_the_documented_vision_rule(size: tuple[int, int], tokens: int):
    """Anthropic vision docs: ≈ w×h/750 after scaling to ≤1,568 px and ≤~1.15 MP."""
    assert layer.image_tokens(*size) == tokens
    assert layer.image_tokens(400, 500) == 267  # a small image is not scaled
    assert layer.image_tokens(None, None) == layer.VISION_TOKEN_CEILING


def test_the_repair_turn_bound_grows_by_the_answer_it_re_sends(monkeypatch) -> None:  # noqa: ANN001
    ceilings: list[int] = []
    real = layer.create_turn

    def spy(*args: Any, **kwargs: Any) -> Any:
        ceilings.append(kwargs["input_ceiling"])
        return real(*args, **kwargs)

    monkeypatch.setattr(layer, "create_turn", spy)
    bad = _slide(title="Promoción")
    budget = claude_tools.DollarMeter(layer.LAYER_BUDGET_USD)
    client = FakeClient(_response([bad]), _response([_slide()], "t2"))
    write_layers(_request(), api_key="k", client_factory=lambda _k: client, budget=budget)
    # the first answer billed 300 output tokens: the repair re-sends them, plus our note
    assert 300 + 100 < ceilings[1] - ceilings[0] < 300 + 100 + 400
    assert budget.overruns == 0

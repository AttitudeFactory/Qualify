"""`qualify_api.referentes.reels_ai` without the network: a scripted fake client stands
in for the SDK, so these pin what goes OUT (tool, tool choice, what the model reads per
reel) and what the module lets back IN (only ids it asked about, once each, a boolean
verdict)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from qualify_api.claude_tools import ClaudeToolError
from qualify_api.referentes.ai import BrandBrief
from qualify_api.referentes.reels_ai import (
    REVIEW_BATCH,
    REVIEW_TOOL,
    ReelToReview,
    review_reels,
)

BRAND = BrandBrief(handle="@burgerco", rubro=("hamburguesería",), city="Lima", country="Perú")


class ScriptedClient:
    def __init__(self, content: list[Any]) -> None:
        self.content = content
        self.calls: list[dict[str, Any]] = []
        self.messages = self

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(
            stop_reason="tool_use",
            content=self.content,
            model=kwargs["model"],
            usage=SimpleNamespace(input_tokens=1500, output_tokens=200, cache_read_input_tokens=0),
        )


def _use(arguments: dict[str, Any], name: str = REVIEW_TOOL) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id="tu_1", name=name, input=arguments)


REELS = [
    ReelToReview(
        id="instagram:A",
        network="instagram",
        handle="foodie",
        caption="La smash burger más jugosa de Lima #burger",
        sound="Audio original",
        account_kind="creador",
    ),
    ReelToReview(
        id="instagram:B",
        network="instagram",
        handle="foodie",
        caption="Mi rutina de maquillaje de noche",
        account_kind="creador",
    ),
]


def test_the_verdicts_come_back_by_number_and_only_once() -> None:
    client = ScriptedClient(
        [
            _use(
                {
                    "resultados": [
                        {
                            "id": "1",
                            "afinidad": "producto",
                            "encaja": True,
                            "razon": "Reseña de hamburguesas.",
                            "formato": "reseña",
                            "gancho": "pregunta",
                        },
                        {
                            "id": "[2]",
                            "afinidad": "otro",
                            "encaja": False,
                            "razon": "Maquillaje, otro rubro.",
                            "formato": "inventado",
                        },
                        {"id": "1", "encaja": False, "razon": "repetido"},
                        {"id": "9", "encaja": True, "razon": "no preguntado"},
                        {"id": "2", "encaja": "no", "razon": "malformado"},
                    ]
                }
            )
        ]
    )
    reviews, _stats = review_reels(BRAND, REELS, api_key="k", client_factory=lambda key: client)
    assert [(r.id, r.fits) for r in reviews] == [("instagram:A", True), ("instagram:B", False)]
    assert [r.affinity for r in reviews] == ["producto", "otro"]
    # the card's tags: closed lists, anything else is dropped
    assert (reviews[0].format, reviews[0].hook) == ("reseña", "pregunta")
    assert (reviews[1].format, reviews[1].hook) == ("", "")
    sent = client.calls[0]
    assert sent["tools"][0]["name"] == REVIEW_TOOL
    text = sent["messages"][0]["content"]
    assert "hamburguesería" in text and "maquillaje" in text and "la cuenta es: creador" in text


def test_the_affinity_is_the_verdict() -> None:
    """Only the brand's own product is shown (§ founder, 2026-10-15 evening: «si es
    hamburguesas que solo traiga hamburguesas»): `producto` fits whatever `encaja` says,
    `rubro` (a chicken recipe on a food referente) and `otro` (a beer promo) do not."""
    client = ScriptedClient(
        [
            _use(
                {
                    "resultados": [
                        {"id": "1", "afinidad": "rubro", "encaja": True, "razon": "Pollo."},
                        {"id": "2", "afinidad": "otro", "encaja": True, "razon": "Cerveza."},
                    ]
                }
            )
        ]
    )
    reviews, _ = review_reels(BRAND, REELS, api_key="k", client_factory=lambda key: client)
    assert [(r.affinity, r.fits) for r in reviews] == [("rubro", False), ("otro", False)]
    strict = ScriptedClient(
        [_use({"resultados": [{"id": "1", "afinidad": "producto", "encaja": False, "razon": ""}]})]
    )
    reviews, _ = review_reels(BRAND, REELS, api_key="k", client_factory=lambda key: strict)
    assert [(r.affinity, r.fits) for r in reviews] == [("producto", True)]
    system = str(client.calls[0]["system"])
    assert "true cuando afinidad es producto o categoria" in system
    assert "promoción de otro negocio" in system


def test_the_same_kind_of_offer_fits_too() -> None:
    """§ request 2026-10-20: «un poco más completo» — `categoria` (a variant, substitute
    or direct complement of the brand's product) fits; the prompt explains it with several
    rubros, not only food, and the whole niche (`rubro`) still does not fit."""
    client = ScriptedClient(
        [
            _use(
                {
                    "resultados": [
                        {"id": "1", "afinidad": "categoria", "encaja": False, "razon": "Hot dog."},
                        {"id": "2", "afinidad": "rubro", "encaja": True, "razon": "Postre."},
                    ]
                }
            )
        ]
    )
    reviews, _ = review_reels(BRAND, REELS, api_key="k", client_factory=lambda key: client)
    assert [(r.affinity, r.fits) for r in reviews] == [("categoria", True), ("rubro", False)]
    system = str(client.calls[0]["system"])
    for rubro in ("gimnasio", "clínica", "software de facturación", "agencia de viajes"):
        assert rubro in system, rubro
    assert "se COMPRA" in system and "una receta casera" in system
    item = client.calls[0]["tools"][0]["input_schema"]["properties"]["resultados"]["items"]
    assert item["properties"]["afinidad"]["enum"] == ["producto", "categoria", "rubro", "otro"]


def test_without_a_valid_affinity_nothing_fits() -> None:
    """§ 2026-10-19: a gateway's model does not always honour the strict enum; an answer
    that never says `producto` is not a product reel, whatever `encaja` says."""
    client = ScriptedClient(
        [
            _use(
                {
                    "resultados": [
                        {"id": "1", "encaja": True, "razon": "Sin afinidad."},
                        {"id": "2", "afinidad": "inventada", "encaja": True, "razon": "?"},
                    ]
                }
            )
        ]
    )
    reviews, _ = review_reels(BRAND, REELS, api_key="k", client_factory=lambda key: client)
    assert [(r.affinity, r.fits) for r in reviews] == [("", False), ("", False)]


def test_the_account_alone_is_no_proof_of_product() -> None:
    """§ 2026-10-19 audit: a food creator's textless «Who wants to come over ??» was kept
    as `producto` from its account note alone — the same account's top reels were
    salmon, fish and burritos. Only a BRAND selling that very product may decide it."""
    client = ScriptedClient([_use({"resultados": []})])
    review_reels(BRAND, REELS, api_key="k", client_factory=lambda key: client)
    system = str(client.calls[0]["system"])
    assert "La cuenta no es prueba del reel" in system and "solo entonces es producto" in system


def test_the_brand_kit_and_the_catalog_reach_the_model() -> None:
    """§ 2026-10-15: products, every hashtag and what the brand publishes are in the
    message; the system prompt says they delimit `producto`, never `rubro`."""
    client = ScriptedClient([_use({"resultados": []})])
    brand = BrandBrief(
        handle="@nibbles",
        rubro=("smashburguer",),
        niches=("Comida y bebida",),
        hashtags=("hamburguesas", "smashburger", "comidarapida"),
        positioning="Smash burgers callejeras",
        audience="Jóvenes de 18 a 35",
        products=("smash doble", "papas con queso"),
        publishes=("¡Pilla esta costra!",),
    )
    review_reels(brand, REELS[:1], api_key="k", client_factory=lambda key: client)
    text = client.calls[0]["messages"][0]["content"]
    assert "Productos que vende: smash doble; papas con queso" in text
    assert "Hashtags de la marca: #hamburguesas #smashburger #comidarapida" in text
    assert "Ejemplos de lo que publica:" in text and "¡Pilla esta costra!" in text
    assert "Posicionamiento: Smash burgers callejeras" in text
    system = str(client.calls[0]["system"])
    assert "delimitan `producto`, nunca `rubro`" in system


def test_a_model_without_effort_gets_the_whole_token_ceiling() -> None:
    """§ 2026-10-16: through a gateway, Gemini spent the old 120-per-reel budget on 20
    reels and came back cut (`stop=length`) with no tool call."""
    from qualify_api.claude_tools import MAX_NON_STREAMING_TOKENS, ModelConfig

    client = ScriptedClient([_use({"resultados": []})])
    review_reels(
        BRAND,
        REELS,
        api_key="k",
        config=ModelConfig("gemini/gemini-3-flash-preview"),
        client_factory=lambda key: client,
    )
    assert client.calls[0]["max_tokens"] == MAX_NON_STREAMING_TOKENS
    assert client.calls[0]["tool_choice"] == {"type": "tool", "name": REVIEW_TOOL}


def test_no_tool_call_is_an_error() -> None:
    client = ScriptedClient([SimpleNamespace(type="text", text="no sé")])
    with pytest.raises(ClaudeToolError):
        review_reels(BRAND, REELS, api_key="k", client_factory=lambda key: client)


def test_batches_are_bounded_and_empty_is_free() -> None:
    reviews, _ = review_reels(BRAND, [], api_key="k", client_factory=lambda key: None)
    assert reviews == []
    many = [ReelToReview(id=str(n), network="tiktok", handle="x") for n in range(REVIEW_BATCH + 1)]
    with pytest.raises(ValueError):
        review_reels(BRAND, many, api_key="k", client_factory=lambda key: None)


def test_what_is_said_reaches_the_model() -> None:
    client = ScriptedClient([_use({"resultados": []})])
    reel = ReelToReview(id="x", network="tiktok", handle="a", transcript="hoy pruebo un labial")
    review_reels(BRAND, [reel], api_key="k", client_factory=lambda key: client)
    text = client.calls[0]["messages"][0]["content"]
    assert "lo que se dice: hoy pruebo un labial" in text
    assert "transcripción" in str(client.calls[0]["system"])

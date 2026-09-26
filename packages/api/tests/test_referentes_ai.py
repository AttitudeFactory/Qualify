"""`qualify_api.referentes.ai` without the network: a scripted fake client stands in for
the SDK, so these pin what goes OUT (model, tool, tool choice, explicit key, what the
model reads about each account) and what the module lets back IN (only ids it asked
about, once each, valid kinds, a boolean verdict). Model quality is measured separately,
by hand, in `evals/referentes_ai`."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from qualify_api.claude_tools import ClaudeToolError, ModelConfig
from qualify_api.referentes.ai import (
    REVIEW_BATCH,
    REVIEW_EFFORT,
    REVIEW_MODEL,
    REVIEW_TOOL,
    AccountToReview,
    BrandBrief,
    review_accounts,
)

BRAND = BrandBrief(
    handle="@casaolivo",
    bio="Cocina de autor colombiana",
    rubro=("restaurante de autor",),
    niches=("Comida y bebida",),
    city="Bogotá",
    country="Colombia",
)


def _use(arguments: dict[str, Any], name: str = REVIEW_TOOL) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id="tu_1", name=name, input=arguments)


class ScriptedClient:
    def __init__(self, content: list[Any], stop_reason: str = "tool_use") -> None:
        self.content = content
        self.stop_reason = stop_reason
        self.calls: list[dict[str, Any]] = []
        self.messages = self

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=self.content,
            model=kwargs["model"],
            usage=SimpleNamespace(input_tokens=2000, output_tokens=300, cache_read_input_tokens=0),
        )


def _factory(client: ScriptedClient, keys: list[str]) -> Any:
    def build(api_key: str) -> ScriptedClient:
        keys.append(api_key)
        return client

    return build


def _accounts() -> list[AccountToReview]:
    return [
        AccountToReview(
            id="instagram:elchefbogota",
            network="Instagram",
            handle="elchefbogota",
            bio="Chef. Cocina colombiana contemporánea",
            followers=52000,
            captions=("Nuevo menú de temporada con productores del Pacífico",),
            hashtags=("cocinadeautor", "bogota"),
        ),
        AccountToReview(
            id="tiktok:perrosya",
            network="TikTok",
            handle="perrosya",
            bio="Perros calientes a domicilio",
            followers=90000,
        ),
        AccountToReview(
            id="instagram:donarosa",
            network="Otro",
            handle="donarosa",
            manual=True,
            note="Pastelería del barrio, no tiene redes",
        ),
    ]


def test_the_answer_comes_back_per_account_and_only_for_what_was_asked() -> None:
    client = ScriptedClient(
        [
            _use(
                {
                    "resultados": [
                        {
                            "id": "instagram:elchefbogota",
                            "tipo": "creador",
                            "encaja": True,
                            "razon": "Chef de cocina de autor en Bogotá.",
                        },
                        {
                            "id": "tiktok:perrosya",
                            "tipo": "marca",
                            "encaja": False,
                            "razon": "Comida rápida a domicilio, otro formato.",
                        },
                        # not asked about, repeated, and malformed — all dropped
                        {"id": "tiktok:otra", "tipo": "marca", "encaja": True, "razon": ""},
                        {"id": "tiktok:perrosya", "tipo": "marca", "encaja": True, "razon": ""},
                        {"id": "instagram:donarosa", "tipo": "tienda", "encaja": True, "razon": ""},
                    ]
                }
            )
        ]
    )
    keys: list[str] = []
    reviews, stats = review_accounts(
        BRAND, _accounts(), api_key="sk-test", client_factory=_factory(client, keys)
    )

    assert [(r.id, r.kind, r.fits) for r in reviews] == [
        ("instagram:elchefbogota", "creador", True),
        ("tiktok:perrosya", "marca", False),
    ]
    assert reviews[1].reason == "Comida rápida a domicilio, otro formato."
    assert keys == ["sk-test"]  # the explicit key, never ambient credentials
    assert stats.model_id == REVIEW_MODEL and stats.tool_calls == 1

    request = client.calls[0]
    assert (REVIEW_MODEL, REVIEW_EFFORT) == ("claude-sonnet-5", "low")  # the eval's choice
    assert request["model"] == REVIEW_MODEL
    # a thinking model gets `auto`; the module checks the tool was called
    assert request["tool_choice"] == {"type": "auto"}
    assert request["output_config"] == {"effort": "low"}
    tool = request["tools"][0]
    assert tool["strict"] is True
    assert tool["input_schema"]["additionalProperties"] is False


def test_the_model_reads_the_brand_and_what_each_account_says() -> None:
    client = ScriptedClient([_use({"resultados": []})])
    review_accounts(BRAND, _accounts(), api_key="k", client_factory=_factory(client, []))
    message = client.calls[0]["messages"][0]["content"]
    assert "Marca: @casaolivo" in message
    assert "restaurante de autor" in message and "Bogotá, Colombia" in message
    # accounts are numbered: the model answers with the number, not the caller's id
    assert "[1] Instagram @elchefbogota" in message
    assert "instagram:elchefbogota" not in message
    assert "publicación: Nuevo menú de temporada" in message
    assert "#cocinadeautor #bogota" in message
    # a manual account is marked, and the operator's note is its only evidence
    assert "[3] Otro @donarosa — agregada a mano" in message
    assert "nota del operador: Pastelería del barrio, no tiene redes" in message


def test_a_thinking_model_gets_auto_and_must_still_call_the_tool() -> None:
    client = ScriptedClient([SimpleNamespace(type="text", text="no sé")], stop_reason="end_turn")
    with pytest.raises(ClaudeToolError):
        review_accounts(
            BRAND,
            _accounts(),
            api_key="k",
            config=ModelConfig("claude-sonnet-5", "medium"),
            client_factory=_factory(client, []),
        )
    assert client.calls[0]["tool_choice"] == {"type": "auto"}
    assert client.calls[0]["output_config"] == {"effort": "medium"}


def test_the_answer_may_use_the_number_the_account_was_shown_under() -> None:
    client = ScriptedClient(
        [
            _use(
                {
                    "resultados": [
                        {"id": "3", "tipo": "marca", "encaja": False, "razon": "Pastelería."},
                        {"id": "[1]", "tipo": "creador", "encaja": True, "razon": "Chef."},
                        {"id": "9", "tipo": "marca", "encaja": True, "razon": "no existe"},
                    ]
                }
            )
        ]
    )
    reviews, _ = review_accounts(
        BRAND, _accounts(), api_key="k", client_factory=_factory(client, [])
    )
    assert [(r.id, r.fits) for r in reviews] == [
        ("instagram:donarosa", False),
        ("instagram:elchefbogota", True),
    ]


def test_a_model_without_thinking_is_forced_to_the_tool() -> None:
    client = ScriptedClient([_use({"resultados": []})])
    review_accounts(
        BRAND,
        _accounts(),
        api_key="k",
        config=ModelConfig("claude-haiku-4-5"),
        client_factory=_factory(client, []),
    )
    assert client.calls[0]["tool_choice"] == {"type": "tool", "name": REVIEW_TOOL}
    assert "output_config" not in client.calls[0]  # Haiku 4.5 rejects effort


def test_a_refusal_is_an_error_not_an_empty_answer() -> None:
    client = ScriptedClient([], stop_reason="refusal")
    with pytest.raises(ClaudeToolError):
        review_accounts(BRAND, _accounts(), api_key="k", client_factory=_factory(client, []))


def test_nothing_to_review_costs_nothing() -> None:
    client = ScriptedClient([])
    reviews, stats = review_accounts(BRAND, [], api_key="k", client_factory=_factory(client, []))
    assert reviews == [] and client.calls == [] and stats.cost_usd == 0


def test_one_call_takes_at_most_a_batch() -> None:
    many = [AccountToReview(id=f"tiktok:a{i}", network="TikTok", handle=f"a{i}") for i in range(31)]
    assert len(many) > REVIEW_BATCH
    with pytest.raises(ValueError):
        review_accounts(BRAND, many, api_key="k", client_factory=_factory(ScriptedClient([]), []))

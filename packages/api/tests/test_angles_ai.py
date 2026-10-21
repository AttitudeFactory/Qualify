"""`qualify_api.creative.angles_ai` without the network (ticket 24803289): the shape of
the `proponer_angulos_visuales` call (strict tool, cached system prompt, the product and
its price in the user turn), the bounded parse of the answer, the second ask when the
model did not call the tool, and the typed failures."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import anthropic
import httpx2
import pytest
from qualify_creative.angles import ANGLES_TOOL, PRESETS, AngleBrand, AngleProduct

from qualify_api.claude_tools import ClaudeToolError, ModelConfig
from qualify_api.creative.angles_ai import (
    ANGLES_EFFORT,
    ANGLES_MODEL,
    MAX_TOKENS,
    AnglesProviderError,
    generate_angles,
    prompt_fingerprint,
)

PRODUCT = AngleProduct(
    product_id=uuid4(),
    name="Shawarma mixto",
    description="Pollo y carne.",
    price_label="$18.000",
    photo_keys=("uploads/t/p1.jpg",),
)
BRAND = AngleBrand(name="Bianki", sector="shawarma")
SCENES = [
    "sobre una tabla de madera en una mesa de cafetería con luz de ventana",
    "en la mano de alguien frente a un local de barrio al atardecer",
    "sobre una roca junto a un río con luz dura de mediodía",
    "en un escritorio de oficina entre un portátil y un café",
    "sobre papel kraft en un picnic en el césped con sombra de árbol",
    "en la barra del local con la plancha encendida al fondo",
    "en una bandeja de reparto dentro de una moto con casco al lado",
    "sobre mármol blanco con cubiertos dorados y una copa",
    "en el asiento de un carro con luces de ciudad desenfocadas",
    "sobre una toalla de playa con arena y mar al fondo",
    "en una mesa de reunión con cuatro cajas abiertas",
    "flotando sobre fondo negro con humo y luz lateral",
]


def _rows(n: int) -> list[dict[str, str]]:
    return [
        {
            "title": f"Ángulo {i + 1}",
            "scene": SCENES[i],
            "composition": "plano medio",
            "hook": f"Gancho {i + 1}",
            "cta": "Pide ya",
            "rationale": "vende",
        }
        for i in range(n)
    ]


def _response(blocks: list[Any], stop: str = "tool_use") -> Any:
    return SimpleNamespace(
        content=blocks,
        stop_reason=stop,
        model="claude-sonnet-5-20260601",
        usage=SimpleNamespace(input_tokens=900, output_tokens=700, cache_read_input_tokens=0),
    )


def _tool_use(payload: dict[str, Any]) -> Any:
    return SimpleNamespace(type="tool_use", name=ANGLES_TOOL, input=payload)


def _client(*responses: Any) -> tuple[Any, list[dict[str, Any]]]:
    requests: list[dict[str, Any]] = []

    def create(**kwargs: Any) -> Any:
        requests.append(kwargs)
        return responses[len(requests) - 1]

    return SimpleNamespace(messages=SimpleNamespace(create=create)), requests


def test_the_call_is_one_strict_tool_with_the_product_and_its_price() -> None:
    client, requests = _client(_response([_tool_use({"angles": _rows(10)})]))
    angles, stats, fingerprint = generate_angles(
        PRODUCT, BRAND, PRESETS[0], api_key="k", client_factory=lambda _k: client
    )
    assert len(angles) == 10 and [a.position for a in angles] == list(range(1, 11))
    (request,) = requests
    assert request["model"] == ANGLES_MODEL
    assert request["output_config"] == {"effort": ANGLES_EFFORT}
    assert request["max_tokens"] == MAX_TOKENS
    (tool,) = request["tools"]
    assert tool["name"] == ANGLES_TOOL and tool["strict"] is True
    assert request["system"][0]["cache_control"] == {"type": "ephemeral"}
    user = request["messages"][0]["content"]
    assert "Shawarma mixto" in user and "$18.000" in user and "Bianki" in user
    assert stats.model_id == ANGLES_MODEL and stats.tool_calls == 1
    assert stats.input_tokens == 900 and stats.output_tokens == 700
    assert fingerprint == prompt_fingerprint(request["system"][0]["text"], user)
    assert len(fingerprint) == 16


def test_a_non_thinking_model_forces_the_tool_and_a_thinking_one_does_not() -> None:
    client, requests = _client(_response([_tool_use({"angles": _rows(3)})]))
    generate_angles(
        PRODUCT,
        BRAND,
        PRESETS[0],
        api_key="k",
        count=3,
        config=ModelConfig("claude-haiku-5-5"),
        client_factory=lambda _k: client,
    )
    assert requests[0]["tool_choice"] == {"type": "tool", "name": ANGLES_TOOL}
    assert "output_config" not in requests[0]
    client, requests = _client(_response([_tool_use({"angles": _rows(3)})]))
    generate_angles(
        PRODUCT, BRAND, PRESETS[0], api_key="k", count=3, client_factory=lambda _k: client
    )
    assert requests[0]["tool_choice"] == {"type": "auto"}


def test_the_answer_is_bounded_and_de_duplicated() -> None:
    rows = _rows(10)
    rows.insert(1, dict(rows[0]))  # the same scene twice
    rows[0]["title"] = "T" * 300
    client, _ = _client(_response([_tool_use({"angles": rows})]))
    angles, _, _ = generate_angles(
        PRODUCT, BRAND, PRESETS[0], api_key="k", client_factory=lambda _k: client
    )
    assert len(angles) == 10 and len({a.scene for a in angles}) == 10
    assert len(angles[0].title) <= 60


def test_a_turn_without_the_tool_is_asked_once_more() -> None:
    text = SimpleNamespace(type="text", text="Aquí van mis ideas…")
    client, requests = _client(
        _response([text], stop="end_turn"), _response([_tool_use({"angles": _rows(10)})])
    )
    angles, stats, _ = generate_angles(
        PRODUCT, BRAND, PRESETS[0], api_key="k", client_factory=lambda _k: client
    )
    assert len(angles) == 10 and stats.turns == 2
    assert requests[1]["messages"][-1]["content"].startswith("Entrega la respuesta con")


def test_two_turns_without_the_tool_fail_typed() -> None:
    text = SimpleNamespace(type="text", text="no")
    client, _ = _client(_response([text], stop="end_turn"), _response([text], stop="end_turn"))
    with pytest.raises(ClaudeToolError, match="did not call"):
        generate_angles(PRODUCT, BRAND, PRESETS[0], api_key="k", client_factory=lambda _k: client)


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
def test_a_refusal_or_a_truncation_is_a_typed_error(stop: str) -> None:
    client, _ = _client(_response([], stop=stop))
    with pytest.raises(ClaudeToolError):
        generate_angles(PRODUCT, BRAND, PRESETS[0], api_key="k", client_factory=lambda _k: client)


# -- the top-up call: `avoid` reaches the prompt and the de-duplication (defects 1, 2) --


def test_a_top_up_call_names_the_kept_angles_and_returns_only_new_ones() -> None:
    kept, _, _ = generate_angles(
        PRODUCT,
        BRAND,
        PRESETS[0],
        api_key="k",
        count=7,
        client_factory=lambda _k: _client(_response([_tool_use({"angles": _rows(7)})]))[0],
    )
    # the model answers with two of the kept scenes again and three new ones
    repeated = _rows(7)[:2]
    fresh = [{**row, "title": f"Nuevo {i}"} for i, row in enumerate(_rows(10)[7:], start=1)]
    client, requests = _client(_response([_tool_use({"angles": repeated + fresh})]))
    more, stats, _ = generate_angles(
        PRODUCT,
        BRAND,
        PRESETS[0],
        api_key="k",
        count=3,
        avoid=kept,
        client_factory=lambda _k: client,
    )
    user = requests[0]["messages"][0]["content"]
    assert "Ángulos ya propuestos" in user
    assert all(a.scene in user for a in kept)
    # the repeats are dropped, only the three new angles come back, numbered after the kept
    assert [a.title for a in more] == ["Nuevo 1", "Nuevo 2", "Nuevo 3"]
    assert [a.position for a in more] == [8, 9, 10]
    assert not {a.scene for a in more} & {a.scene for a in kept}
    assert stats.tool_calls == 1


def test_a_top_up_that_only_repeats_returns_nothing_new() -> None:
    kept = generate_angles(
        PRODUCT,
        BRAND,
        PRESETS[0],
        api_key="k",
        count=5,
        client_factory=lambda _k: _client(_response([_tool_use({"angles": _rows(5)})]))[0],
    )[0]
    client, _ = _client(_response([_tool_use({"angles": _rows(5)})]))
    more, _, _ = generate_angles(
        PRODUCT,
        BRAND,
        PRESETS[0],
        api_key="k",
        count=5,
        avoid=kept,
        client_factory=lambda _k: client,
    )
    assert more == ()


def test_the_call_shape_the_angle_set_service_uses_is_accepted() -> None:
    # `composition._PlatformAngleGenerator` calls generate_angles(..., api_key=, count=,
    # avoid=): before defect 1 was fixed this raised TypeError before any network call
    client, _ = _client(_response([_tool_use({"angles": _rows(10)})]))
    angles, _, _ = generate_angles(
        PRODUCT,
        BRAND,
        PRESETS[0],
        api_key="k",
        count=10,
        avoid=(),
        client_factory=lambda _k: client,
    )
    assert len(angles) == 10


# -- Anthropic not answering is a typed, classified failure (defect 3) -----------------

_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def _status(cls: type[anthropic.APIStatusError], code: int) -> anthropic.APIStatusError:
    return cls("vendor said no", response=httpx2.Response(code, request=_REQUEST), body=None)


def _failing(exc: BaseException) -> Any:
    def create(**_kwargs: Any) -> Any:
        raise exc

    return SimpleNamespace(messages=SimpleNamespace(create=create))


@pytest.mark.parametrize(
    ("exc", "status", "retryable"),
    [
        (_status(anthropic.RateLimitError, 429), 429, True),
        (_status(anthropic.InternalServerError, 500), 500, True),
        (_status(anthropic.OverloadedError, 529), 529, True),
        (anthropic.APITimeoutError(request=_REQUEST), None, True),
        (anthropic.APIConnectionError(request=_REQUEST), None, True),
        (_status(anthropic.BadRequestError, 400), 400, False),
        (_status(anthropic.AuthenticationError, 401), 401, False),
    ],
)
def test_a_vendor_failure_is_a_typed_claude_error(
    exc: BaseException, status: int | None, retryable: bool
) -> None:
    with pytest.raises(AnglesProviderError) as caught:
        generate_angles(
            PRODUCT, BRAND, PRESETS[0], api_key="k", client_factory=lambda _k: _failing(exc)
        )
    error = caught.value
    assert isinstance(error, ClaudeToolError)  # the service's existing except catches it
    assert error.status == status and error.retryable is retryable
    assert error.__cause__ is exc
    assert "vendor said no" not in str(error)  # the vendor's own text stays in the cause


def test_a_programming_error_is_not_disguised_as_a_vendor_failure() -> None:
    with pytest.raises(ValueError, match="boom"):
        generate_angles(
            PRODUCT,
            BRAND,
            PRESETS[0],
            api_key="k",
            client_factory=lambda _k: _failing(ValueError("boom")),
        )


def test_a_top_up_past_the_cap_asks_only_for_what_fits_and_never_raises() -> None:
    # R1: 8 kept + 10 asked → the call asks for 4 and positions stop at 12
    kept = generate_angles(
        PRODUCT,
        BRAND,
        PRESETS[0],
        api_key="k",
        count=8,
        client_factory=lambda _k: _client(_response([_tool_use({"angles": _rows(8)})]))[0],
    )[0]
    fresh = [{**row, "title": f"Nuevo {i}"} for i, row in enumerate(_rows(12)[8:], start=1)]
    client, requests = _client(_response([_tool_use({"angles": fresh})]))
    more, _, _ = generate_angles(
        PRODUCT,
        BRAND,
        PRESETS[0],
        api_key="k",
        count=10,
        avoid=kept,
        client_factory=lambda _k: client,
    )
    assert "Propón 4 ángulos" in requests[0]["messages"][0]["content"]
    assert [a.position for a in more] == [9, 10, 11, 12]


def test_a_full_set_pays_for_no_call() -> None:
    full = generate_angles(
        PRODUCT,
        BRAND,
        PRESETS[0],
        api_key="k",
        count=12,
        client_factory=lambda _k: _client(_response([_tool_use({"angles": _rows(12)})]))[0],
    )[0]
    assert len(full) == 12

    def no_client(_key: str) -> Any:
        raise AssertionError("no call may be made for a full set")

    more, stats, _ = generate_angles(
        PRODUCT, BRAND, PRESETS[0], api_key="k", count=3, avoid=full, client_factory=no_client
    )
    assert more == () and stats.turns == 0

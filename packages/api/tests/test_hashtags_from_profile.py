"""`qualify_api.hashtags.from_profile` (§ request 2026-10-05): hashtags created from the
account's own description, category and latest posts, and the free fallback."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from qualify_api.claude_tools import ClaudeToolError
from qualify_api.hashtags.from_profile import (
    MODEL,
    TOOL,
    AccountText,
    from_posts,
    generate,
)

ACCOUNT = AccountText(
    handle="@nibbles.burger",
    bio="Smash burgers en San Cristóbal 🍔 Pedidos por DM",
    category="Restaurante de hamburguesas",
    captions=("Nueva doble smash con cheddar #smashburger", "Jueves 2x1 #sancristobal"),
    used_hashtags=("smashburger", "fyp", "sancristobal"),
    rubro="Comida y bebida",
    city="San Cristóbal",
    country="Venezuela",
)


def _client(*responses: Any) -> tuple[Any, list[dict[str, Any]]]:
    requests: list[dict[str, Any]] = []

    def create(**kwargs: Any) -> Any:
        requests.append(kwargs)
        return responses[len(requests) - 1]

    return SimpleNamespace(messages=SimpleNamespace(create=create)), requests


def _response(blocks: list[Any], stop: str = "tool_use") -> Any:
    return SimpleNamespace(
        content=blocks,
        stop_reason=stop,
        model="claude-sonnet-5-20260601",
        usage=SimpleNamespace(input_tokens=400, output_tokens=120, cache_read_input_tokens=0),
    )


def test_the_model_reads_the_bio_the_category_and_the_posts() -> None:
    answer = SimpleNamespace(
        type="tool_use",
        name=TOOL,
        input={
            "hashtags": [
                {"tag": "#SmashBurger", "reason": "Lo usa en sus publicaciones."},
                {"tag": "smashburger", "reason": "duplicado"},
                {"tag": "hamburguesas", "reason": "La categoría del perfil."},
                {"tag": "sancristobalfood", "reason": "Su ciudad."},
                {"tag": "two words", "reason": "no es un hashtag"},
            ]
        },
    )
    client, requests = _client(_response([answer]))
    proposal = generate(ACCOUNT, api_key="k", max_tags=5, client_factory=lambda _k: client)

    assert [t.tag for t in proposal.tags] == ["smashburger", "hamburguesas", "sancristobalfood"]
    assert proposal.by == "ai" and proposal.stats is not None and proposal.stats.tool_calls == 1
    (request,) = requests
    assert request["model"] == MODEL and request["tools"][0]["strict"] is True
    message = request["messages"][0]["content"]
    for evidence in (
        "Smash burgers en San Cristóbal",
        "Restaurante de hamburguesas",
        "Nueva doble smash con cheddar",
        "smashburger, fyp, sancristobal",
        "San Cristóbal, Venezuela",
    ):
        assert evidence in message


def test_nothing_to_read_is_refused_before_any_call() -> None:
    with pytest.raises(ValueError):
        generate(AccountText(handle="x"), api_key="k", max_tags=5, client_factory=lambda _k: None)


def test_a_run_without_the_tool_is_nudged_once_then_fails() -> None:
    chatter = SimpleNamespace(type="text", text="#smashburger")
    client, requests = _client(_response([chatter], "end_turn"), _response([chatter], "end_turn"))
    with pytest.raises(ClaudeToolError):
        generate(ACCOUNT, api_key="k", max_tags=5, client_factory=lambda _k: client)
    assert len(requests) == 2


def test_the_fallback_keeps_the_accounts_own_tags_minus_reach_only_ones() -> None:
    proposal = from_posts(
        ("#fyp", "SmashBurger", "viral", "sancristobal", "smashburger"), max_tags=5
    )
    assert [t.tag for t in proposal.tags] == ["smashburger", "sancristobal"]
    assert proposal.by == "posts" and proposal.stats is None


def test_the_answer_also_names_the_rubro() -> None:
    """§ third round of 2026-10-05: the same call fills Tu rubro when it is empty."""
    answer = SimpleNamespace(
        type="tool_use",
        name=TOOL,
        input={
            "rubro": "  hamburguesería   smash para llevar ",
            "hashtags": [{"tag": "smashburger", "reason": "La bio."}],
        },
    )
    client, requests = _client(_response([answer]))
    proposal = generate(ACCOUNT, api_key="k", max_tags=5, client_factory=lambda _k: client)
    assert proposal.rubro == "hamburguesería smash para llevar"
    schema = requests[0]["tools"][0]["input_schema"]
    assert "rubro" in schema["properties"] and "rubro" in schema["required"]
    assert from_posts(["smashburger"], max_tags=3).rubro == ""


def test_alta_drafts_are_sourced_and_validate_each_field_independently() -> None:
    from qualify_api.hashtags.from_profile import clean_drafts

    captions = ["Nuestro yogur se hace cada mañana.", "Para quienes disfrutan fruta fresca."]
    answer = {
        "distinto": {
            "texto": "Yogur preparado cada mañana.",
            "fuente": "yogur se hace cada mañana",
        },
        "quien_compra": {"texto": "Familias felices", "fuente": "una fuente inventada"},
        "frase_ejemplo": {"texto": "Ven por $5 a calle 3", "fuente": "fruta fresca"},
        "tono": {
            "formal_casual": 70,
            "sober_enthusiastic": 60,
            "technical_plain": 80,
            "brief_elaborate": 30,
            "fuente": "fruta fresca",
        },
    }
    drafts = clean_drafts(answer, captions)
    assert set(drafts) == {"distinto", "tono"}
    assert clean_drafts({"distinto": "inventado"}, captions) == {}


@pytest.mark.parametrize(
    "text",
    [
        "Escríbenos +573001234567",
        "Ven a la avenida Libertador",
        "Cuesta 5 USD",
        "Ven a Av. Libertador",
        "Ven a Cra. Primera",
    ],
)
def test_alta_drafts_reject_contacts_addresses_and_prices(text: str) -> None:
    from qualify_api.hashtags.from_profile import clean_drafts

    assert (
        clean_drafts({"distinto": {"texto": text, "fuente": "cada mañana"}}, ["Hecho cada mañana"])
        == {}
    )


def test_drafts_use_one_existing_turn_and_web_tool_is_unchanged() -> None:
    from dataclasses import replace

    from qualify_api.hashtags.from_profile import _tool

    captions = ("Hecho cada mañana", "Ingredientes de la región", "Fruta fresca para disfrutar")
    block = SimpleNamespace(
        type="tool_use",
        name=TOOL,
        input={
            "rubro": "heladería",
            "hashtags": [],
            "borradores": {"distinto": {"texto": "Hecho cada mañana", "fuente": "cada mañana"}},
        },
    )
    client, requests = _client(_response([block]))
    result = generate(
        replace(ACCOUNT, captions=captions, drafts=True),
        api_key="k",
        max_tags=5,
        client_factory=lambda _k: client,
    )
    assert len(requests) == 1 and result.borradores["distinto"]["texto"] == "Hecho cada mañana"
    assert "borradores" in requests[0]["tools"][0]["input_schema"]["properties"]
    client, requests = _client(_response([block]))
    result = generate(ACCOUNT, api_key="k", max_tags=5, client_factory=lambda _k: client)
    assert requests[0]["tools"] == [_tool(5)] and result.borradores == {}


def test_drafts_with_too_few_posts_send_original_tool() -> None:
    from dataclasses import replace

    from qualify_api.hashtags.from_profile import _tool

    block = SimpleNamespace(
        type="tool_use", name=TOOL, input={"rubro": "heladería", "hashtags": []}
    )
    client, requests = _client(_response([block]))
    result = generate(
        replace(ACCOUNT, drafts=True), api_key="k", max_tags=5, client_factory=lambda _k: client
    )
    assert requests[0]["tools"] == [_tool(5)] and result.borradores == {}


def test_truncated_drafts_retry_original_tool_and_keep_both_turn_costs() -> None:
    from dataclasses import replace

    from qualify_api.hashtags.from_profile import _tool

    block = SimpleNamespace(
        type="tool_use", name=TOOL, input={"rubro": "heladería", "hashtags": []}
    )
    client, requests = _client(_response([], "max_tokens"), _response([block]))
    result = generate(
        replace(ACCOUNT, captions=("uno propio", "dos propios", "tres propios"), drafts=True),
        api_key="k",
        max_tags=5,
        client_factory=lambda _k: client,
    )
    assert len(requests) == 2 and result.stats.turns == 2
    assert requests[1]["tools"] == [_tool(5)] and result.borradores == {}

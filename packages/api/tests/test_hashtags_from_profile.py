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

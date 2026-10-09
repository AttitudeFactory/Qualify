"""`qualify_api.creative.font_ai` without the network (§ request 2026-10-05): which logo
files travel to the model, the shape of the `identificar_tipografia` call, the bounded
parse of its answer and the hedged note the wizard shows."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from qualify_api.claude_tools import ClaudeToolError, ModelConfig
from qualify_api.creative.font_ai import (
    DETECT_TOOL,
    FONT_EFFORT,
    FONT_MODEL,
    MAX_ALTERNATIVES,
    MAX_IMAGES,
    MAX_NAME_CHARS,
    FontGuess,
    NoUsableImage,
    describe,
    identify_fonts,
    image_blocks,
    parse_guess,
)

PNG = b"\x89PNG small"


def _response(blocks: list[Any], stop: str = "tool_use") -> Any:
    return SimpleNamespace(
        content=blocks,
        stop_reason=stop,
        model="claude-sonnet-5-20260601",
        usage=SimpleNamespace(input_tokens=120, output_tokens=40, cache_read_input_tokens=0),
    )


def _tool_use(payload: dict[str, Any]) -> Any:
    return SimpleNamespace(type="tool_use", name=DETECT_TOOL, input=payload)


def _client(*responses: Any) -> tuple[Any, list[dict[str, Any]]]:
    requests: list[dict[str, Any]] = []

    def create(**kwargs: Any) -> Any:
        requests.append(kwargs)
        return responses[len(requests) - 1]

    return SimpleNamespace(messages=SimpleNamespace(create=create)), requests


# -- which files travel ---------------------------------------------------------------------


def test_only_raster_images_travel_fullest_first_and_an_svg_is_skipped() -> None:
    blocks = image_blocks([("imagotipo.svg", b"<svg/>"), ("logotipo.png", PNG), ("iso.webp", PNG)])
    assert [b["source"]["media_type"] for b in blocks] == ["image/png", "image/webp"]
    assert blocks[0]["type"] == "image"


def test_at_most_two_images_go_in_one_request() -> None:
    files = [(f"v{i}.png", PNG) for i in range(5)]
    assert len(image_blocks(files)) == MAX_IMAGES == 2


def test_nothing_usable_is_refused_before_any_call() -> None:
    with pytest.raises(NoUsableImage):
        image_blocks([("logo.svg", b"<svg/>"), ("empty.png", b"")])
    with pytest.raises(NoUsableImage):
        identify_fonts([("logo.svg", b"<svg/>")], api_key="k", client_factory=lambda _k: None)


# -- the call ------------------------------------------------------------------------------


def test_identify_fonts_reads_the_tool_call_and_bounds_it() -> None:
    client, requests = _client(
        _response(
            [
                _tool_use(
                    {
                        "heading_font": "  Montserrat ",
                        "heading_alternatives": [
                            "montserrat",
                            "Poppins",
                            "Poppins",
                            "Raleway",
                            "Nunito",
                            "Lato",
                        ],
                        "body_font": "Inter",
                        "style": "Sans-Serif",
                        "note": (
                            "Geometría  redonda y sin remates;  es un parecido, "
                            "no una identificación."
                        ),
                    }
                )
            ]
        )
    )
    guess, stats = identify_fonts(
        [("imagotipo.png", PNG), ("logotipo.jpg", PNG), ("isotipo.png", PNG)],
        api_key="k",
        client_factory=lambda _k: client,
    )
    assert guess == FontGuess(
        heading="Montserrat",
        body="Inter",
        heading_alternatives=("Poppins", "Raleway", "Nunito"),  # dedup, heading dropped, capped
        style="sans-serif",
        note="Geometría redonda y sin remates; es un parecido, no una identificación.",
    )
    assert len(guess.heading_alternatives) == MAX_ALTERNATIVES
    assert guess.found_anything
    assert stats.model_id == FONT_MODEL and stats.tool_calls == 1 and stats.turns == 1
    assert stats.model_revision == "claude-sonnet-5-20260601"

    (request,) = requests
    assert request["model"] == FONT_MODEL
    assert request["output_config"] == {"effort": FONT_EFFORT}
    assert request["tool_choice"] == {"type": "auto"}  # a thinking model: never forced
    (tool,) = request["tools"]
    assert tool["name"] == DETECT_TOOL and tool["strict"] is True
    assert set(tool["input_schema"]["required"]) == {
        "heading_font",
        "heading_alternatives",
        "body_font",
        "style",
        "note",
    }
    content = request["messages"][0]["content"]
    assert [b["type"] for b in content] == ["image", "image", "text"]  # two images, then the ask
    assert request["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_a_model_without_thinking_gets_the_tool_forced() -> None:
    client, requests = _client(_response([_tool_use({"heading_font": "Lora"})]))
    guess, _ = identify_fonts(
        [("logo.png", PNG)],
        api_key="k",
        config=ModelConfig("claude-haiku-4-5"),
        client_factory=lambda _k: client,
    )
    assert guess.heading == "Lora" and guess.body == "" and guess.heading_alternatives == ()
    assert requests[0]["tool_choice"] == {"type": "tool", "name": DETECT_TOOL}
    assert "output_config" not in requests[0]


def test_a_run_that_never_calls_the_tool_is_nudged_once_then_fails() -> None:
    chatter = SimpleNamespace(type="text", text="Parece Montserrat.")
    client, requests = _client(_response([chatter], "end_turn"), _response([chatter], "end_turn"))
    with pytest.raises(ClaudeToolError):
        identify_fonts([("logo.png", PNG)], api_key="k", client_factory=lambda _k: client)
    assert len(requests) == 2
    assert DETECT_TOOL in requests[1]["messages"][-1]["content"]


def test_a_refusal_is_an_error_not_an_answer() -> None:
    client, _ = _client(_response([], "refusal"))
    with pytest.raises(ClaudeToolError):
        identify_fonts([("logo.png", PNG)], api_key="k", client_factory=lambda _k: client)


# -- parsing and the note ---------------------------------------------------------------------


def test_parse_guess_tolerates_garbage() -> None:
    assert parse_guess(None) == FontGuess("", "", (), "", "")
    sloppy = parse_guess(
        {
            "heading_font": "x" * 200,
            "heading_alternatives": "Poppins",  # not a list
            "body_font": 42,
            "style": "cursive",  # not one of ours
            "note": ["no"],
        }
    )
    assert len(sloppy.heading) == MAX_NAME_CHARS
    assert sloppy.heading_alternatives == () and sloppy.body == "42" and sloppy.style == ""


def test_the_note_always_hedges_and_lists_the_alternatives() -> None:
    guess = FontGuess("Montserrat", "Inter", ("Poppins", "Raleway"), "sans-serif", "Sin remates.")
    assert describe(guess) == "Parece Montserrat (o Poppins, Raleway). Sin remates."
    assert describe(FontGuess("Lora", "", (), "serif", "")) == "Parece Lora."
    nothing = FontGuess("", "", (), "", "")
    assert not nothing.found_anything
    assert "No encontramos texto" in describe(nothing)
    assert describe(FontGuess("", "", (), "", "El logo es solo un símbolo.")) == (
        "El logo es solo un símbolo."
    )

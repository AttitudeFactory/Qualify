"""`voice_analysis` — a recording of the brand's voice → the Brand Kit's four tone axes
(§ request 2026-09-30). Fully offline: the transcriber and Claude are fakes."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from qualify_creative.schemas import ToneAxes

from qualify_api.claude_tools import ClaudeToolError
from qualify_api.creative.voice_analysis import (
    TONE_TOOL,
    MissingHFToken,
    NotEnoughSpeech,
    analyze_recording,
    hf_token_from_env,
    parse_suggestion,
    suggest_tone,
)

TRANSCRIPT = (
    "¡Hola, parce! Aquí en el Café del Parque te tenemos el tinto más rico del centro, "
    "recién tostado, y si vienes antes de las nueve el primero va por nuestra cuenta."
)


class ScriptedClient:
    def __init__(self, *turns: list[Any]) -> None:
        self.turns = list(turns)
        self.calls: list[dict[str, Any]] = []
        self.messages = self

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        content = self.turns.pop(0)
        return SimpleNamespace(
            stop_reason="tool_use" if any(b.type == "tool_use" for b in content) else "end_turn",
            content=content,
            model=kwargs["model"],
            usage=SimpleNamespace(input_tokens=800, output_tokens=200, cache_read_input_tokens=0),
        )


def _tool_call(payload: dict[str, Any]) -> list[Any]:
    return [SimpleNamespace(type="tool_use", id="tu_1", name=TONE_TOOL, input=payload)]


def _axis(value: object, reason: str = "r") -> dict[str, object]:
    return {"value": value, "reason": reason}


PAYLOAD = {
    "formal_casual": _axis(85, "Tutea y dice «parce»."),
    "sober_enthusiastic": _axis(78, "Abre con exclamación y regala el primer café."),
    "technical_plain": _axis(90, "Palabras de todos los días."),
    "brief_elaborate": _axis(40, "Una idea por frase."),
}


def test_the_tool_answer_becomes_tone_axes_with_reasons() -> None:
    client = ScriptedClient(_tool_call(PAYLOAD))
    suggestion = suggest_tone(TRANSCRIPT, api_key="k", client_factory=lambda _k: client)
    assert suggestion.axes == ToneAxes(
        formal_casual=85, sober_enthusiastic=78, technical_plain=90, brief_elaborate=40
    )
    assert suggestion.reasons["formal_casual"] == "Tutea y dice «parce»."
    assert suggestion.transcript == TRANSCRIPT
    assert suggestion.stats is not None and suggestion.stats.tool_calls == 1
    # the transcript is what Claude reads; the tool is the one it must answer with
    call = client.calls[0]
    assert TRANSCRIPT in call["messages"][0]["content"]
    assert [tool["name"] for tool in call["tools"]] == [TONE_TOOL]


def test_out_of_range_or_broken_values_are_clamped_or_neutral() -> None:
    suggestion = parse_suggestion(
        {
            "formal_casual": _axis(140),
            "sober_enthusiastic": _axis(-5),
            "technical_plain": _axis("no sé"),
            # brief_elaborate missing altogether
        },
        TRANSCRIPT,
    )
    assert suggestion.axes == ToneAxes(
        formal_casual=100, sober_enthusiastic=0, technical_plain=50, brief_elaborate=50
    )


def test_a_model_that_never_calls_the_tool_is_asked_once_more_then_fails() -> None:
    prose = [SimpleNamespace(type="text", text="Suena cercano.")]
    client = ScriptedClient(prose, _tool_call(PAYLOAD))
    assert suggest_tone(TRANSCRIPT, api_key="k", client_factory=lambda _k: client).axes
    assert len(client.calls) == 2
    with pytest.raises(ClaudeToolError):
        suggest_tone(
            TRANSCRIPT, api_key="k", client_factory=lambda _k: ScriptedClient(prose, prose)
        )


def test_too_little_speech_is_refused_before_calling_claude() -> None:
    client = ScriptedClient()
    with pytest.raises(NotEnoughSpeech):
        suggest_tone("Hola, buenas.", api_key="k", client_factory=lambda _k: client)
    assert client.calls == []


def test_analyze_recording_transcribes_then_suggests(tmp_path: Path) -> None:
    recording = tmp_path / "voz.mp3"
    recording.write_bytes(b"ID3")
    heard: list[Path] = []

    def transcriber(path: Path) -> str:
        heard.append(path)
        return TRANSCRIPT

    client = ScriptedClient(_tool_call(PAYLOAD))
    suggestion = analyze_recording(
        recording, transcriber=transcriber, api_key="k", client_factory=lambda _k: client
    )
    assert heard == [recording] and suggestion.axes.formal_casual == 85


def test_the_hf_token_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    with pytest.raises(MissingHFToken):
        hf_token_from_env()
    monkeypatch.setenv("HF_TOKEN", " hf_x ")
    assert hf_token_from_env() == "hf_x"

"""Analyse a recording of the brand's voice and suggest its tone axes (§ request
2026-09-30: "un apartado que analice tu voz ... y llenar los apartados de los sliders").

Two steps, each behind its own seam so both are testable offline:

1. **Transcribe** the recording — `openai/whisper-large-v3-turbo` through Hugging Face
   Inference Providers (the transcription checkpoint `docs/modelos-multimodal-fase1.md`
   chose; the same weights can later run self-hosted). Needs `HF_TOKEN`.
2. **Read the tone** off the transcript with Claude, forced through one strict tool
   (`sugerir_tono`): a 0-100 value per axis of the Brand Kit's `ToneAxes`, each with a
   short reason quoting what was said. Needs `QUALIFY_ANTHROPIC_API_KEY`.

What is judged is WHAT was said and HOW it is phrased (register, energy, jargon, length)
— a transcript carries no pitch or pace, so the reasons never claim to have heard them.
The result only PRE-FILLS the sliders; the operator moves them and saves the kit."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qualify_creative.schemas import ToneAxes

from qualify_api.claude_tools import (
    MAX_NON_STREAMING_TOKENS,
    CallStats,
    ClaudeToolError,
    Meter,
    ModelConfig,
    create_turn,
    default_client,
    forced_or_auto,
    strict_tool,
    tool_uses,
)

TRANSCRIBE_MODEL = "openai/whisper-large-v3-turbo"
HF_TOKEN_ENV = "HF_TOKEN"
TONE_MODEL = "claude-sonnet-5"
TONE_EFFORT = "low"
TONE_TOOL = "sugerir_tono"
#: Below this many words there is not enough speech to read a register from.
MIN_WORDS = 12

#: (ToneAxes field, low end, high end) — the same two poles the sliders show.
AXES: tuple[tuple[str, str, str], ...] = (
    ("formal_casual", "formal", "coloquial"),
    ("sober_enthusiastic", "sobrio", "entusiasta"),
    ("technical_plain", "técnico", "llano"),
    ("brief_elaborate", "breve", "elaborado"),
)

Transcriber = Callable[[Path], str]
ClientFactory = Callable[[str], Any]


class MissingHFToken(RuntimeError):
    """`HF_TOKEN` is not set: the recording cannot be transcribed."""


class NotEnoughSpeech(ValueError):
    """The transcript is too short to judge a tone from."""


@dataclass(frozen=True)
class ToneSuggestion:
    axes: ToneAxes
    #: ToneAxes field → one short sentence on why, in Spanish.
    reasons: dict[str, str]
    transcript: str
    stats: CallStats | None = None


def hf_token_from_env() -> str:
    token = os.environ.get(HF_TOKEN_ENV, "").strip()
    if not token:
        raise MissingHFToken(f"{HF_TOKEN_ENV} is not set")
    return token


def whisper_transcriber(token: str, model_id: str = TRANSCRIBE_MODEL) -> Transcriber:
    """Transcription through HF Inference Providers (`provider="auto"`)."""

    def transcribe(path: Path) -> str:
        from huggingface_hub import InferenceClient  # lazy: network client

        client = InferenceClient(provider="auto", api_key=token)
        output = client.automatic_speech_recognition(str(path), model=model_id)
        return str(getattr(output, "text", "") or "").strip()

    return transcribe


SYSTEM = """\
Analizas cómo habla una marca a partir de la transcripción de una grabación de su voz \
(un dueño, un vocero, un creador presentando el negocio). Con eso sugieres dónde va la \
marca en cuatro ejes de tono, de 0 a 100, y lo entregas con la herramienta sugerir_tono, \
una sola vez.

Los ejes (0 = el primer polo, 100 = el segundo):
- formal_casual: 0 formal (usted, fórmulas de cortesía, frases completas) … 100 coloquial \
(tuteo, muletillas, expresiones de la calle, humor).
- sober_enthusiastic: 0 sobrio (tono contenido, sin exclamaciones ni superlativos) … 100 \
entusiasta (exclamaciones, energía, superlativos, invitaciones con emoción).
- technical_plain: 0 técnico (jerga del oficio, datos, especificaciones) … 100 llano \
(palabras de todos los días, explica sin tecnicismos).
- brief_elaborate: 0 breve (frases cortas, va al grano) … 100 elaborado (frases largas, \
detalles, historias, contexto).

Reglas:
- Juzga solo lo que dice la transcripción: el registro, las palabras, la energía escrita \
y el largo de las frases. No tienes el audio: nunca afirmes nada sobre el timbre, la \
velocidad o la entonación.
- 50 significa que la grabación no inclina el eje hacia ningún lado; úsalo cuando no haya \
señal, no como valor por defecto.
- reason: una frase en español que cite o parafrasee lo que se dijo y que justifique el \
número."""


def _axis_prop() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"value": {"type": "integer"}, "reason": {"type": "string"}},
        "required": ["value", "reason"],
        "additionalProperties": False,
    }


def _tool() -> dict[str, Any]:
    return strict_tool(
        TONE_TOOL,
        "Entrega el valor de 0 a 100 de cada eje de tono, con una razón breve cada uno.",
        {field: _axis_prop() for field, _low, _high in AXES},
    )


def _clamp(value: object) -> int:
    try:
        number = int(round(float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 50
    return max(0, min(100, number))


def parse_suggestion(raw: dict[str, Any], transcript: str) -> ToneSuggestion:
    """The tool input as `ToneAxes` (each value clamped to 0-100; a missing or broken
    axis falls back to 50, "no signal") plus the reasons."""
    values: dict[str, int] = {}
    reasons: dict[str, str] = {}
    for field, _low, _high in AXES:
        item = raw.get(field)
        item = item if isinstance(item, dict) else {}
        values[field] = _clamp(item.get("value", 50))
        reasons[field] = " ".join(str(item.get("reason") or "").split())
    return ToneSuggestion(axes=ToneAxes(**values), reasons=reasons, transcript=transcript)


def suggest_tone(
    transcript: str,
    *,
    api_key: str,
    config: ModelConfig = ModelConfig(TONE_MODEL, TONE_EFFORT),
    client_factory: ClientFactory | None = None,
) -> ToneSuggestion:
    """Claude reads the transcript and places the brand on each axis. Raises
    `NotEnoughSpeech` for a transcript too short to judge, `ClaudeToolError` when the
    model refuses, truncates or never calls the tool."""
    words = transcript.split()
    if len(words) < MIN_WORDS:
        raise NotEnoughSpeech(f"{len(words)} words transcribed; {MIN_WORDS} needed")
    client = (client_factory or default_client)(api_key)
    meter = Meter(config)
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": f"Transcripción de la grabación:\n\n{transcript}",
        }
    ]
    for attempt in range(2):
        response = create_turn(
            client,
            config,
            meter,
            system=SYSTEM,
            messages=messages,
            tools=[_tool()],
            tool_choice=forced_or_auto(config, TONE_TOOL),
            max_tokens=MAX_NON_STREAMING_TOKENS,
        )
        calls = [u for u in tool_uses(response) if u.name == TONE_TOOL]
        if calls:
            meter.tool_calls += 1
            suggestion = parse_suggestion(calls[0].input or {}, transcript)
            return ToneSuggestion(
                axes=suggestion.axes,
                reasons=suggestion.reasons,
                transcript=transcript,
                stats=meter.stats(),
            )
        if attempt == 0:
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": f"Entrega el tono con {TONE_TOOL}."})
    raise ClaudeToolError(f"{config.model_id} did not call {TONE_TOOL}")


def analyze_recording(
    path: Path,
    *,
    transcriber: Transcriber,
    api_key: str,
    client_factory: ClientFactory | None = None,
) -> ToneSuggestion:
    """Transcribe the recording, then suggest the tone from what was said."""
    transcript = transcriber(path)
    return suggest_tone(transcript, api_key=api_key, client_factory=client_factory)

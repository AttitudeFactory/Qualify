"""The voice-transcription experiment (docs/plan-observabilidad-langfuse.md §7, fase 6):
which local Whisper the Brand Kit's «Tu voz» should run. Cases, task and evaluators,
importable so they are tested offline; the runnable side is
`packages/api/evals/voice_ai/run_experiment.py`. Transcription is LOCAL (faster-whisper,
CPU, no key, $0) — the candidates differ in accuracy and in time.

Scores per recording:

- `wer` — word error rate against the reference transcript (accents, case and
  punctuation folded); 0 is perfect.
- `rtf` — real-time factor, processing seconds ÷ audio seconds; under 1 is faster than
  the recording.
- `segundos`, `audio_segundos`.

A case without a human transcript (`reference: null`) is scored against the most
accurate model's transcript, and its scores say so (`referencia = modelo`): that measures
agreement with `large-v3-turbo`, not accuracy. Human transcripts replace it as soon as
recordings are added (see the dataset's README).

The models load through `qualify_models.providers` (the `ml` group), lazily, so these
evaluators and their tests run without it.
"""

from __future__ import annotations

import json
import re
import statistics
import time
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from qualify_shared import observability
from qualify_shared.observability import ItemOutcome, Score

DATASET = "voz-transcripcion"
#: The production model (`voice_analysis.TRANSCRIBE_MODEL` through faster-whisper) first;
#: it is also the provisional reference for a recording with no human transcript.
CONFIGS: Mapping[str, str] = {
    "large-v3-turbo": "deepdml/faster-whisper-large-v3-turbo-ct2",
    "small": "small",
}
REFERENCE_CONFIG = "large-v3-turbo"

Transcriber = Callable[[Path], tuple[str, str | None]]


def load_cases(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        {
            "id": case["id"],
            "input": {
                "id": case["id"],
                "audio": str((path.parent / case["audio"]).resolve()),
                "reference": case.get("reference"),
                "language": case.get("language", "es"),
            },
        }
        for case in raw["cases"]
        if (path.parent / case["audio"]).exists()
    ]


def normalize(text: str) -> list[str]:
    """Words as compared: accents, case and punctuation folded."""
    decomposed = unicodedata.normalize("NFD", text.casefold())
    bare = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9ñ]+", bare)


def wer(reference: str, hypothesis: str) -> float:
    """Word error rate: (substitutions + deletions + insertions) ÷ reference words."""
    ref, hyp = normalize(reference), normalize(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    previous = list(range(len(hyp) + 1))
    for i, word in enumerate(ref, start=1):
        current = [i] + [0] * len(hyp)
        for j, other in enumerate(hyp, start=1):
            current[j] = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (word != other))
        previous = current
    return previous[-1] / len(ref)


def audio_seconds(path: str) -> float | None:
    try:
        import av  # noqa: PLC0415 — the `media` extra / `ml` group

        with av.open(path) as container:
            return container.duration / 1_000_000 if container.duration else None
    except Exception:  # noqa: BLE001
        return None


_providers: dict[str, Any] = {}


def local_transcriber(model_id: str) -> Transcriber:
    """faster-whisper on CPU, as «Tu voz» runs it; one loaded model per id per process."""
    if model_id not in _providers:
        from qualify_models.providers import FasterWhisperTranscriptionProvider  # noqa: PLC0415

        _providers[model_id] = FasterWhisperTranscriptionProvider(model_id)
    return _providers[model_id].transcribe


def transcribe(
    case: Mapping[str, Any],
    model_id: str,
    *,
    transcriber: Transcriber | None = None,
    reference_transcriber: Transcriber | None = None,
) -> dict[str, Any]:
    """The task: one recording through one model, as a zero-cost Langfuse generation, and
    the reference it is scored against (the human one, or the reference model's)."""
    path = Path(case["audio"])
    run = transcriber or local_transcriber(model_id)
    seconds_audio = audio_seconds(str(path))
    with observability.generation(
        "whisper", model=model_id, input={"format": path.suffix.lstrip("."), "caso": case["id"]}
    ) as observation:
        started = time.perf_counter()
        text, language = run(path)
        elapsed = time.perf_counter() - started
        observation.finish(
            output=text,
            model=model_id,
            usage={"audio_seconds": round(seconds_audio)} if seconds_audio else None,
            cost={"audio": 0.0},
            metadata={"language": language, "local": True},
        )
    reference, source = case.get("reference"), "humana"
    if not reference:
        reference_model = CONFIGS[REFERENCE_CONFIG]
        if model_id == reference_model:
            reference = text
        else:
            reference, _ = (reference_transcriber or local_transcriber(reference_model))(path)
        source = "modelo"
    return {
        "texto": text,
        "idioma": language,
        "referencia": reference,
        "fuente_referencia": source,
        "segundos": round(elapsed, 2),
        "audio_segundos": round(seconds_audio, 2) if seconds_audio else None,
    }


def transcription_scores(
    case: Mapping[str, Any], output: Mapping[str, Any], _expected: Any, _meta: Mapping[str, Any]
) -> list[Score]:
    error_rate = wer(output["referencia"], output["texto"])
    scores = [
        Score("wer", round(error_rate, 4), f"referencia {output['fuente_referencia']}"),
        Score("referencia_humana", output["fuente_referencia"] == "humana"),
        Score("segundos", float(output["segundos"])),
    ]
    if output.get("audio_segundos"):
        scores.append(Score("audio_segundos", float(output["audio_segundos"])))
        scores.append(Score("rtf", round(output["segundos"] / output["audio_segundos"], 3)))
    return scores


ITEM_EVALUATORS = (transcription_scores,)


def run_summary(outcomes: Sequence[ItemOutcome]) -> list[Score]:
    def values(name: str) -> list[float]:
        return [
            float(o.scores[name])
            for o in outcomes
            if isinstance(o.scores.get(name), int | float | bool)
        ]

    out: list[Score] = []
    if errors := values("wer"):
        out.append(Score("wer_medio", round(statistics.mean(errors), 4)))
    if rtf := values("rtf"):
        out.append(Score("rtf_medio", round(statistics.mean(rtf), 3)))
    if human := values("referencia_humana"):
        out.append(Score("casos_con_referencia_humana", sum(human)))
    out.append(Score("casos", float(len(outcomes))))
    return out


RUN_EVALUATORS = (run_summary,)

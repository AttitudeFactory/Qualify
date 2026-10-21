"""The voice-transcription experiment's metric, cases and task, offline (no Whisper)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from qualify_api.evals.voice_transcription import (
    CONFIGS,
    load_cases,
    normalize,
    run_summary,
    transcribe,
    transcription_scores,
    wer,
)

CASES = Path(__file__).resolve().parents[1] / "evals" / "voice_ai" / "cases.json"


def test_wer_folds_accents_case_and_punctuation() -> None:
    assert normalize("¡Hola, Café del Parque!") == ["hola", "cafe", "del", "parque"]
    assert wer("Hola, somos el Café del Parque", "hola somos el cafe del parque") == 0.0
    # one substitution in six words
    assert wer("hola somos el cafe del parque", "hola somos el cafe de parque") == pytest.approx(
        1 / 6
    )
    # a deletion and an insertion
    assert wer("uno dos tres", "uno tres cuatro") == pytest.approx(2 / 3)
    assert wer("", "") == 0.0 and wer("", "algo") == 1.0


def test_every_committed_case_has_a_human_reference_and_a_git_ignored_recording() -> None:
    raw = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    assert raw
    for case in raw:
        assert case["reference"] and len(normalize(case["reference"])) >= 50
        assert case["audio"].startswith("audio/")  # never a recording in git
    # a machine without the recordings (CI) simply has nothing to run
    assert {i["id"] for i in load_cases(CASES)} <= {c["id"] for c in raw}


def test_a_case_whose_recording_is_missing_is_skipped(tmp_path: Path) -> None:
    (tmp_path / "audio").mkdir()
    (tmp_path / "audio" / "here.wav").write_bytes(b"RIFF")
    cases = tmp_path / "cases.json"
    cases.write_text(
        json.dumps(
            {
                "cases": [
                    {"id": "here", "audio": "audio/here.wav", "reference": "hola"},
                    {"id": "gone", "audio": "audio/gone.wav", "reference": "hola"},
                ]
            }
        ),
        encoding="utf-8",
    )
    items = load_cases(cases)
    assert [i["id"] for i in items] == ["here"]
    assert items[0]["input"]["language"] == "es"
    assert Path(items[0]["input"]["audio"]).exists()


def _case(tmp_path: Path, reference: str | None) -> dict[str, Any]:
    audio = tmp_path / "voz.wav"
    audio.write_bytes(b"not audio")
    return {"id": "c1", "audio": str(audio), "reference": reference, "language": "es"}


def test_a_human_reference_is_scored_as_accuracy(tmp_path: Path) -> None:
    case = _case(tmp_path, "Hola somos el Café del Parque")
    output = transcribe(
        case, CONFIGS["small"], transcriber=lambda path: ("hola somos el cafe de parque", "es")
    )
    assert output["fuente_referencia"] == "humana"
    scores = {s.name: s.value for s in transcription_scores(case, output, None, {})}
    assert scores["wer"] == pytest.approx(1 / 6, abs=1e-4)
    assert scores["referencia_humana"] is True


def test_without_a_human_reference_the_reference_model_stands_in(tmp_path: Path) -> None:
    case = _case(tmp_path, None)
    calls: list[str] = []

    def reference_model(path: Path) -> tuple[str, str]:
        calls.append("reference")
        return "hola somos el cafe del parque", "es"

    small = transcribe(
        case,
        CONFIGS["small"],
        transcriber=lambda path: ("hola somos el cafe de parque", "es"),
        reference_transcriber=reference_model,
    )
    turbo = transcribe(case, CONFIGS["large-v3-turbo"], transcriber=reference_model)
    assert small["fuente_referencia"] == turbo["fuente_referencia"] == "modelo"
    assert calls == ["reference", "reference"]  # small's reference, then turbo itself
    assert wer(turbo["referencia"], turbo["texto"]) == 0.0  # agreement with itself


def test_the_run_summary_counts_human_references() -> None:
    from qualify_shared.observability import ItemOutcome

    outcomes = [
        ItemOutcome(None, None, {"wer": 0.1, "rtf": 0.5, "referencia_humana": True}),
        ItemOutcome(None, None, {"wer": 0.3, "rtf": 0.7, "referencia_humana": False}),
    ]
    summary = {s.name: s.value for s in run_summary(outcomes)}
    assert summary == {
        "wer_medio": 0.2,
        "rtf_medio": 0.6,
        "casos_con_referencia_humana": 1.0,
        "casos": 2.0,
    }

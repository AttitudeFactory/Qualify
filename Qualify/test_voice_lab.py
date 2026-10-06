"""Tu voz (§ request 2026-09-30): the HeyGen clone round trip and how the finished clone
reaches the avatar videos' voice picker on /create. HeyGen and the database are fakes."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from qualify_api.creative.voice_clone import COMPLETE, FAILED, PROCESSING, VoiceClone

from . import creative_provider, voice_lab
from .creative_state import CreativeState

_REAL_PREFETCH = voice_lab.prefetch_whisper


@pytest.fixture(autouse=True)
def no_whisper_load(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """`prefetch_whisper` would load the real model on a thread: here it only records
    that it was asked to."""
    calls: list[str] = []
    monkeypatch.setattr(voice_lab, "prefetch_whisper", lambda: calls.append("warm"))
    return calls


TENANT = UUID("a0000000-0000-4000-8000-0000000000f1")
BRAND = UUID("b0000000-0000-4000-8000-0000000000f1")
USER = UUID("c0000000-0000-4000-8000-0000000000f1")

CLONE = VoiceClone(
    heygen_voice_id="vc_1",
    name="Voz de Café del Parque",
    status=PROCESSING,
    failure_message="",
    language="es",
    gender="",
    preview_audio_url="",
    consent_at=datetime(2026, 9, 30, tzinfo=UTC),
)


class FakeAdapter:
    def __init__(self, voice: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.voice = voice or {}

    def upload_asset(self, **kw: Any) -> dict[str, Any]:
        self.calls.append(("upload_asset", kw))
        return {"asset_id": "aud_1"}

    def clone_voice(self, **kw: Any) -> str:
        self.calls.append(("clone_voice", kw))
        return "vc_2"

    def delete_voice(self, **kw: Any) -> None:
        self.calls.append(("delete_voice", kw))

    def get_voice(self, **kw: Any) -> dict[str, Any]:
        self.calls.append(("get_voice", kw))
        return self.voice


class FakeClones:
    """`VoiceCloneService` over one in-memory row."""

    def __init__(self, clone: VoiceClone | None = None) -> None:
        self.clone = clone
        self.recorded: list[dict[str, Any]] = []

    def current(self, **_kw: Any) -> VoiceClone | None:
        return self.clone

    def record(self, **kw: Any) -> str | None:
        self.recorded.append(kw)
        old = self.clone.heygen_voice_id if self.clone else None
        self.clone = replace(CLONE, heygen_voice_id=kw["heygen_voice_id"], status=PROCESSING)
        return old

    def update_status(self, **kw: Any) -> VoiceClone | None:
        assert self.clone is not None
        self.clone = replace(
            self.clone,
            status=kw["status"],
            gender=kw.get("gender") or self.clone.gender,
            preview_audio_url=kw.get("preview_audio_url") or "",
            failure_message=kw.get("failure_message") or "",
        )
        return self.clone


@pytest.fixture
def heygen(monkeypatch: pytest.MonkeyPatch) -> FakeAdapter:
    adapter = FakeAdapter()
    monkeypatch.setattr(voice_lab, "_heygen", lambda: (adapter, "hg-key"))
    return adapter


def test_cloning_uploads_the_recording_and_replaces_the_previous_clone(
    monkeypatch: pytest.MonkeyPatch, heygen: FakeAdapter, tmp_path: Path
) -> None:
    clones = FakeClones(CLONE)
    monkeypatch.setattr(voice_lab, "VoiceCloneService", lambda: clones)
    recording = tmp_path / "mi_voz.mp3"
    recording.write_bytes(b"audio")

    clone = voice_lab.start_voice_clone(TENANT, BRAND, USER, recording, "Voz de la marca")

    assert [name for name, _ in heygen.calls] == ["upload_asset", "clone_voice", "delete_voice"]
    upload = heygen.calls[0][1]
    assert upload["file_bytes"] == b"audio" and upload["filename"] == "mi_voz.mp3"
    assert upload["content_type"] == "audio/mpeg"
    assert heygen.calls[1][1]["audio_asset_id"] == "aud_1"
    assert heygen.calls[1][1]["language"] == "es"
    assert heygen.calls[2][1]["voice_id"] == "vc_1"  # the old clone frees its slot
    # consent is recorded with the clone: who asked for it
    assert clones.recorded[0]["consent_by"] == USER
    assert clone is not None and clone.heygen_voice_id == "vc_2" and clone.status == PROCESSING


def test_refreshing_asks_heygen_only_while_processing(
    monkeypatch: pytest.MonkeyPatch, heygen: FakeAdapter
) -> None:
    clones = FakeClones(CLONE)
    monkeypatch.setattr(voice_lab, "VoiceCloneService", lambda: clones)
    heygen.voice = {
        "status": "complete",
        "gender": "female",
        "preview_audio_url": "https://files.heygen.ai/p.mp3",
    }
    clone = voice_lab.refresh_voice_clone(TENANT, BRAND)
    assert clone is not None and clone.status == COMPLETE and clone.gender == "female"

    heygen.calls.clear()
    assert voice_lab.refresh_voice_clone(TENANT, BRAND) == clone
    assert heygen.calls == []  # finished: no more HeyGen calls

    # an unknown status from HeyGen is treated as still processing
    clones.clone = CLONE
    heygen.voice = {"status": "queued"}
    assert voice_lab.refresh_voice_clone(TENANT, BRAND).status == PROCESSING  # type: ignore[union-attr]
    heygen.voice = {"status": "failed", "failure_message": "too noisy"}
    failed = voice_lab.refresh_voice_clone(TENANT, BRAND)
    assert failed is not None and failed.status == FAILED and failed.failure_message == "too noisy"


def test_only_a_finished_clone_reaches_the_voice_picker(monkeypatch: pytest.MonkeyPatch) -> None:
    clones = FakeClones(CLONE)
    monkeypatch.setattr(
        "qualify_api.creative.voice_clone.VoiceCloneService", lambda: clones, raising=True
    )
    assert creative_provider.brand_clone_voice(TENANT, BRAND) is None  # still processing
    clones.clone = replace(CLONE, status=COMPLETE, gender="female")
    assert creative_provider.brand_clone_voice(TENANT, BRAND) == {
        "id": "vc_1",
        "name": "Tu voz · Voz de Café del Parque",
        "gender": "female",
        "own": "1",
    }


def test_the_brands_own_voice_is_listed_whatever_gender_and_chosen_first() -> None:
    state = CreativeState()
    state.heygen_voices = [
        {"id": "vc_1", "name": "Tu voz", "gender": "", "own": "1"},
        {"id": "vo_elena", "name": "Elena", "gender": "female"},
        {"id": "vo_jorge", "name": "Jorge", "gender": "male"},
    ]
    state.voice_gender = "male"
    assert [v["id"] for v in state.visible_voices] == ["vc_1", "vo_jorge"]
    state.voice_id = ""
    state._sync_voice()
    assert state.voice_id == "vc_1"
    state.voice_gender = "female"
    state._sync_voice()
    assert state.voice_id == "vc_1"  # still visible: not switched away


def test_the_analysis_transcribes_locally_and_needs_only_claudes_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from qualify_api.claude_tools import MissingAPIKey

    recording = tmp_path / "voz.m4a"
    recording.write_bytes(b"audio")

    class LocalWhisper:
        def __init__(self) -> None:
            self.heard: list[Path] = []

        def transcribe(self, path: Path) -> tuple[str, str]:
            self.heard.append(path)
            return "Hola, somos el Café del Parque", "es"

    whisper = LocalWhisper()
    monkeypatch.setattr(voice_lab, "_local_whisper", whisper)
    seen: dict[str, Any] = {}

    def fake_analyze(path: Path, *, transcriber: Any, api_key: str) -> str:
        seen.update(transcript=transcriber(path), api_key=api_key)
        return "suggestion"

    monkeypatch.setattr(voice_lab, "analyze_recording", fake_analyze)

    # no Claude key: refused before the slow local transcription runs
    monkeypatch.delenv("QUALIFY_ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(MissingAPIKey):
        voice_lab.analyze_voice_sample(recording)
    assert whisper.heard == []

    monkeypatch.setenv("QUALIFY_ANTHROPIC_API_KEY", "sk-test")
    assert voice_lab.analyze_voice_sample(recording) == "suggestion"
    assert seen == {"transcript": "Hola, somos el Café del Parque", "api_key": "sk-test"}
    assert whisper.heard == [recording]


def test_recording_from_the_microphone_reports_what_went_wrong(
    no_whisper_load: list[str],
) -> None:
    state = voice_lab.VoiceLabState()
    spec = voice_lab.VoiceLabState.start_recording.fn(state)
    assert spec is not None  # a call_script into assets/voice-recorder.js

    voice_lab.VoiceLabState.recorder_started.fn(state, "recording")
    assert state.recording is True and state.sample_error == ""
    assert no_whisper_load == ["warm"]  # Whisper loads while the operator speaks
    # Detener with a saved file: the dropzone's upload ends the recording state
    voice_lab.VoiceLabState.recorder_stopped.fn(state, "saved")
    assert state.recording is True
    voice_lab.VoiceLabState.recorder_stopped.fn(state, "empty")
    assert state.recording is False and "No se grabó nada" in state.sample_error

    voice_lab.VoiceLabState.recorder_started.fn(state, "denied")
    assert state.recording is False and "permiso al micrófono" in state.sample_error
    voice_lab.VoiceLabState.recorder_started.fn(state, None)  # type: ignore[arg-type]
    assert "micrófono" in state.sample_error


def test_a_browser_recording_goes_to_heygen_as_wav(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import io
    import wave

    np = pytest.importorskip("numpy")  # the `ml` group; CI's default sync has none

    recording = tmp_path / "grabacion-1.webm"
    recording.write_bytes(b"webm")
    second = np.full(44_100, 0.5, dtype=np.float32)
    monkeypatch.setattr(
        "qualify_models.providers.decode_audio", lambda path, **kw: second, raising=True
    )
    data, filename, content_type = voice_lab.clone_audio(recording)
    assert (filename, content_type) == ("grabacion-1.wav", "audio/wav")
    with wave.open(io.BytesIO(data)) as wav:
        assert (wav.getnchannels(), wav.getframerate(), wav.getnframes()) == (1, 44_100, 44_100)


# -- the analysis behind a progress screen, then straight to ¿Cómo suena? (2026-10-01) ---


def test_the_analysis_reports_its_real_stages() -> None:
    state = voice_lab.VoiceLabState()
    assert state.analysis_percent == 0
    state.analysis_stage = "transcribing"
    assert state.analysis_percent == 30
    assert [row["status"] for row in state.analysis_steps] == ["done", "running", "pending"]
    state.analysis_stage = "reading_tone"
    assert [row["status"] for row in state.analysis_steps] == ["done", "done", "running"]


async def test_a_finished_analysis_moves_the_editor_on_screen_to_the_tone() -> None:
    """Since 2026-10-05 the voice lives only in the Brand Kit editor: a finished analysis
    moves the editor from Tu voz to ¿Cómo suena?, and nothing happens on the wizards'
    pages (they no longer have a voice screen)."""
    from types import SimpleNamespace

    from . import brand_kit_editor as editor
    from . import creative_wizard_pages as wiz

    states = {
        wiz.BrandWizardState: wiz.BrandWizardState(),
        wiz.BrandConnectState: wiz.BrandConnectState(),
        editor.BrandEditState: editor.BrandEditState(),
    }
    states[editor.BrandEditState].step = editor._VOICE_STEP

    class Fake:
        def __init__(self, path: str) -> None:
            self.router = SimpleNamespace(page=SimpleNamespace(path=path))

        async def get_state(self, cls: type) -> Any:
            return states[cls]

    await voice_lab._show_tone_screen(Fake("/brand/connect"))
    await voice_lab._show_tone_screen(Fake("/brand/manual"))
    assert states[wiz.BrandConnectState].step == 0 and states[wiz.BrandWizardState].step == 0
    await voice_lab._show_tone_screen(Fake("/brand/kit"))
    assert states[editor.BrandEditState].step == editor._TONE_STEP
    # an editor no longer on Tu voz is left where it is
    await voice_lab._show_tone_screen(Fake("/brand/kit"))
    assert states[editor.BrandEditState].step == editor._TONE_STEP


def test_the_whisper_warm_up_runs_once_on_its_own_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """`prefetch_whisper` builds the model off the event loop; a provider without a
    warm-up (an older one, a fake) is simply not warmed."""
    import threading

    done = threading.Event()
    threads: list[str] = []

    class Provider:
        def warm_up(self) -> None:
            threads.append(threading.current_thread().name)
            done.set()

    monkeypatch.setattr(voice_lab, "_local_whisper", Provider())
    _REAL_PREFETCH()
    assert done.wait(2)
    assert threads == ["whisper-warm-up"]

    monkeypatch.setattr(voice_lab, "_local_whisper", object())
    _REAL_PREFETCH()  # nothing to call, nothing raised


def test_the_local_whisper_is_faster_whisper_when_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default: large-v3-turbo through faster-whisper. The env var names any of its
    models; without faster-whisper the transformers pipeline keeps working."""
    import importlib.util

    from qualify_models import providers

    monkeypatch.delenv(voice_lab.WHISPER_MODEL_ENV, raising=False)
    if importlib.util.find_spec("faster_whisper") is not None:  # the `ml` group; not in CI
        assert isinstance(
            voice_lab._build_whisper(""), providers.FasterWhisperTranscriptionProvider
        )
        small = voice_lab._build_whisper("small")
        assert isinstance(small, providers.FasterWhisperTranscriptionProvider)
        assert small.model_id == "small"

    import builtins

    real_import = builtins.__import__

    def no_faster_whisper(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "faster_whisper":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_faster_whisper)
    fallback = voice_lab._build_whisper("")
    assert isinstance(fallback, providers.LocalWhisperTranscriptionProvider)
    assert fallback.model_id == "openai/whisper-large-v3-turbo"

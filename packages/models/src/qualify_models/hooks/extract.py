"""End-to-end hook extraction for one video: mp4 in, one `HookFeatures` row out.

Composition, not a new pipeline. It reuses the existing `Provider` seam
(`VisionProvider` / `TranscriptionProvider`) exactly as the cascade does, so swapping
Qwen3-VL for a hosted VLM, or hosted whisper for a self-hosted one, is a constructor
argument and not a rewrite.

Three deliberate choices worth knowing before reading a result:

1. **One ffmpeg decode per video, not one per window.** Frames are sampled once at a
   fixed fps over the widest window; the narrower windows are prefixes of that sequence.
2. **One ASR call per window.** The transcription providers return text with no word
   timestamps, so the 3 s transcript cannot be derived from the 7 s one without guessing
   where to cut. Three short calls are exact and cost cents; interpolation would be an
   invented number. See NOTES_hook_pattern_spike.md §B.3.
3. **One VLM call per VLM window** (default: the primary window only), against a contact
   sheet of that window's frames. The cost of the whole feature is therefore ~1 VLM call
   per video, not one per frame.
"""

from __future__ import annotations

import hashlib
import math
import tempfile
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from qualify_models.cascade import PIPELINE_VERSION
from qualify_models.hooks import media
from qualify_models.hooks.lexical import analyze_speech, classify_lexical
from qualify_models.hooks.schema import (
    HookFeatures,
    HookTypeSource,
    HookWindowFeatures,
    SpokenHook,
    VisualHook,
)
from qualify_models.hooks.spec import (
    FRAME_SAMPLE_FPS,
    HOOK_SPEC_VERSION,
    PRIMARY_WINDOW_SECONDS,
    WINDOW_SECONDS,
    HookType,
)
from qualify_models.hooks.visual import analyze_frames
from qualify_models.hooks.vlm import VlmReading, read_visual_hook
from qualify_models.providers import TranscriptionProvider, VisionProvider

DETECTOR_VERSION = "hook-v1"

RevisionResolver = Callable[[str], str | None]


def _no_revision(_model_id: str) -> str | None:
    """Offline default. Provenance records an unresolved revision as None rather than
    reaching for the network on every extraction; the CLI passes the real resolver."""
    return None


def extract_hook_features(
    video_path: Path,
    source_id: str,
    *,
    pipeline_version: str = PIPELINE_VERSION,
    windows: Sequence[float] = WINDOW_SECONDS,
    vlm_windows: Sequence[float] = (PRIMARY_WINDOW_SECONDS,),
    vision_provider: VisionProvider | None = None,
    transcription_provider: TranscriptionProvider | None = None,
    use_vlm: bool = True,
    use_asr: bool = True,
    revision_resolver: RevisionResolver = _no_revision,
    artifacts_dir: Path | None = None,
    frame_sample_fps: float = FRAME_SAMPLE_FPS,
) -> HookFeatures:
    """Extract the hook of `video_path` at every window in `windows`.

    `use_vlm=False, use_asr=False` runs the deterministic tier only: no network, no
    weights, a couple of seconds per video. That mode is what makes the extractor
    runnable before any model decision is settled.

    `artifacts_dir` keeps the sampled frames and the contact sheets on disk instead of in
    a temp directory — worth passing the first few times, because looking at the contact
    sheet is the fastest way to see what the model was actually shown.
    """
    video_path = Path(video_path)
    windows = sorted(windows)
    if not windows:
        raise ValueError("at least one window is required")

    vision = vision_provider
    if use_vlm and vision is None:
        from qualify_models.providers import LocalQwenVisionProvider

        vision = LocalQwenVisionProvider()

    transcriber = transcription_provider
    if use_asr and transcriber is None:
        from qualify_models.providers import HFInferenceTranscriptionProvider

        transcriber = HFInferenceTranscriptionProvider()

    with tempfile.TemporaryDirectory(prefix="qualify-hooks-") as tmp:
        work_dir = artifacts_dir if artifacts_dir is not None else Path(tmp)
        work_dir.mkdir(parents=True, exist_ok=True)

        widest = windows[-1]
        all_frames = media.sample_window_frames(
            video_path,
            out_dir=work_dir / "frames",
            window_seconds=widest,
            fps=frame_sample_fps,
        )

        window_features = [
            _extract_window(
                video_path=video_path,
                source_id=source_id,
                window_seconds=w,
                all_frames=all_frames,
                frame_sample_fps=frame_sample_fps,
                work_dir=work_dir,
                vision=vision if w in set(vlm_windows) else None,
                transcriber=transcriber,
            )
            for w in windows
        ]

    return HookFeatures(
        source_id=source_id,
        detector_version=DETECTOR_VERSION,
        pipeline_version=pipeline_version,
        hook_spec_version=HOOK_SPEC_VERSION,
        extracted_at=datetime.now(UTC),
        video_path=video_path,
        video_sha256=sha256_file(video_path),
        duration_seconds=media.probe_duration_seconds(video_path),
        asr_model_id=transcriber.model_id if transcriber is not None else None,
        asr_model_revision=(
            revision_resolver(transcriber.model_id) if transcriber is not None else None
        ),
        vlm_model_id=vision.model_id if vision is not None else None,
        vlm_model_revision=revision_resolver(vision.model_id) if vision is not None else None,
        windows=window_features,
    )


def _extract_window(
    video_path: Path,
    source_id: str,
    window_seconds: float,
    all_frames: list[Path],
    frame_sample_fps: float,
    work_dir: Path,
    vision: VisionProvider | None,
    transcriber: TranscriptionProvider | None,
) -> HookWindowFeatures:
    # Frames were sampled at a constant fps over the widest window, so this window's
    # frames are simply its prefix. ceil() keeps the frame that lands exactly on the
    # boundary rather than dropping the end of the window.
    keep = max(1, math.ceil(window_seconds * frame_sample_fps))
    frames = all_frames[:keep]

    deterministic = analyze_frames(frames, window_seconds=window_seconds)

    spoken_text = ""
    if transcriber is not None:
        audio_path = media.extract_window_audio(
            video_path,
            out_path=work_dir / f"audio_{window_seconds:g}s.wav",
            window_seconds=window_seconds,
        )
        if audio_path is not None:
            spoken_text, _language = transcriber.transcribe(audio_path)
    spoken: SpokenHook = analyze_speech(spoken_text, window_seconds=window_seconds)

    reading: VlmReading | None = None
    if vision is not None and frames:
        sheet = media.build_contact_sheet(
            frames, out_path=work_dir / f"sheet_{window_seconds:g}s.jpg"
        )
        reading = read_visual_hook(
            provider=vision,
            contact_sheet_path=sheet.path,
            spoken_text=spoken.text,
            n_frames=sheet.n_frames,
            window_seconds=window_seconds,
        )

    visual = VisualHook(
        n_frames_sampled=deterministic.n_frames,
        cut_count=deterministic.cut_count,
        cuts_per_second=deterministic.cuts_per_second,
        motion_energy=deterministic.motion_energy,
        brightness=deterministic.brightness,
        saturation=deterministic.saturation,
        dominant_colors=deterministic.dominant_colors,
        setting=reading.setting if reading else None,
        face_present=reading.face_present if reading else None,
        person_count=reading.person_count if reading else None,
        on_screen_text=reading.on_screen_text if reading else None,
        text_density=reading.text_density if reading else None,
        vlm_parse_ok=reading.parse_ok if reading else None,
        vlm_raw_output=None if reading is None or reading.parse_ok else reading.raw_output,
    )

    lexical_type = classify_lexical(
        spoken.text, reading.on_screen_text if reading is not None else None
    )
    source, hook_type = _resolve_hook_type(vlm_reading=reading, lexical_type=lexical_type)

    return HookWindowFeatures(
        window_seconds=window_seconds,
        spoken=spoken,
        visual=visual,
        hook_type_vlm=reading.hook_type if reading is not None else None,
        hook_type_lexical=lexical_type,
        hook_type=hook_type,
        hook_type_source=source,
    )


def _resolve_hook_type(
    vlm_reading: VlmReading | None,
    lexical_type: HookType | None,
) -> tuple[HookTypeSource, HookType]:
    """Precedence: a successful VLM reading wins; otherwise a lexical rule; otherwise the
    honest admission that we do not know.

    Note what is deliberately NOT inferred: "no speech" never becomes `none_detected` on
    its own. Only the VLM can see burned-in text, so without it a video whose entire hook
    is a caption over a drone shot is indistinguishable from a video with no hook at all.
    Absent a parsed VLM answer that says `none_detected`, the result is `unknown` — which
    is exactly falsification test F3 in NOTES_hook_pattern_spike.md §A.3.
    """
    if vlm_reading is not None and vlm_reading.parse_ok:
        return "vlm", vlm_reading.hook_type
    if lexical_type is not None:
        return "lexical", lexical_type
    return "unknown", HookType.UNKNOWN


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    """Content hash of the video, so a feature row can be tied to the exact bytes it came
    from — the same idempotency discipline the scraper's raw-payload envelope uses."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()

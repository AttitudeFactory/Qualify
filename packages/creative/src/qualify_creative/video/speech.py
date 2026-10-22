"""When a video's soundtrack has a voice (m-24828920): the input `subtitles.timed_cues`
lays the script over. PyAV decodes the audio to mono 16 kHz, numpy measures the loudness
of every 20 ms window, and `subtitles.voiced_spans` turns that into spans.

Times are relative to the video's FIRST FRAME — what the subtitles are timed against —
so a file whose audio starts later (or earlier) than its picture stays in sync.
"""

from __future__ import annotations

import io
import math

from qualify_creative.subtitles import voiced_spans

#: The rate the audio is analysed at, and the window one loudness value covers.
SAMPLE_RATE = 16_000
WINDOW_SECONDS = 0.02


def voice_spans(data: bytes) -> list[tuple[float, float]]:
    """(start, end) of each stretch of voice in the video `data`, in seconds from its
    first frame. A file without audio (Seedance 1.0 is silent) has none."""
    import av  # noqa: PLC0415 — the `media` extra, as for the video fitter
    import numpy as np  # noqa: PLC0415

    with av.open(io.BytesIO(data)) as source:
        if not source.streams.audio:
            return []
        audio = source.streams.audio[0]
        video = source.streams.video[0] if source.streams.video else None
        origin = 0.0
        if video is not None and video.start_time is not None:
            origin = float(video.start_time * video.time_base)
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        chunks: list[np.ndarray] = []
        first: float | None = None
        for frame in source.decode(audio):
            if first is None and frame.time is not None:
                first = float(frame.time)
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):
            chunks.append(out.to_ndarray().reshape(-1))
    if not chunks:
        return []
    samples = np.concatenate(chunks).astype(np.float64) / 32768.0
    window = round(SAMPLE_RATE * WINDOW_SECONDS)
    count = len(samples) // window
    if count == 0:
        return []
    frames = samples[: count * window].reshape(count, window)
    rms = np.sqrt(np.mean(frames * frames, axis=1))
    levels = [20 * math.log10(value) if value > 1e-6 else -120.0 for value in rms.tolist()]
    shift = (first or 0.0) - origin
    return [
        (max(0.0, start + shift), end + shift)
        for start, end in voiced_spans(levels, WINDOW_SECONDS)
        if end + shift > 0
    ]

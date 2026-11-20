"""The sound helpers the local join (`join`) and the local assembly (`prepare`, `speed`)
share (m-25049580): one way to cut a window of a file's sound, one intermediate format and
one AAC encoder setup — so a ×1 stretch's sound lands where `join` would put it.

- `window_chunks` — a file's sound for a window `[at_s, at_s + samples / 48000)` of its
  absolute time, resampled to 48 kHz stereo float32, as consecutive chunks totalling
  EXACTLY `samples`: silence where the file has no sound, before its sound starts or after
  it ends. Placed by counting decoded samples from the first decoded audio frame — never
  from packet timestamps (risk N6) — and streamed: no chunk is longer than a decoded frame
  or `SILENCE_CHUNK`, so a 60 s stretch never sits whole in memory.
- `write_wav_window` / `read_wav_window` — the lossless sidecar a prepared stretch carries
  (16-bit PCM WAV, 48 kHz stereo), written and read in chunks. A sidecar instead of an AAC
  track inside the intermediate MP4: no second AAC encode, and no AAC priming to undo
  between steps — the sound is encoded ONCE, by the step that writes the part.
- `faded` — the fade at a cut (`join`'s 80 ms, half on each side), for a chunk anywhere in
  its stretch.
- `AacWriter` — the one AAC-LC 48 kHz stereo 128 kbps track (`join`'s), fed chunk by
  chunk, stamped by counting samples from 0.

Mono is copied to both sides at its own level (FFmpeg's upmix would put it 3 dB lower than
a stereo stretch beside it); more than two channels are downmixed by the resampler.
PyAV and numpy are imported lazily, like the rest of this package.
"""

from __future__ import annotations

import os
import secrets
import wave
from collections.abc import Iterator
from fractions import Fraction
from typing import Any

#: The sound of every local video: 48 kHz stereo, AAC-LC 128 kbps (what Instagram and
#: Seedance use) — `join.JOIN_SAMPLE_RATE` and its siblings are these.
SAMPLE_RATE = 48_000
LAYOUT = "stereo"
CHANNELS = 2
AAC_BITRATE = 128_000
#: The fade at every cut, half on each side of it (design §5: «funde el audio 80 ms en
#: cada corte»).
CROSSFADE_S = 0.08
#: The sidecar's sample width: 16-bit PCM (a stretch of 60 s is 11 MiB on disk).
WAV_SAMPLE_WIDTH = 2
#: The longest chunk of silence (or of a WAV read) handed out at once: one second.
SILENCE_CHUNK = SAMPLE_RATE
#: Version of this module's sound recipe (the window, the sidecar, the fades, the AAC) —
#: recorded with what is made from it (provenance).
SOUND_VERSION = "sound-v1"


class SoundError(ValueError):
    """A sidecar that is not this module's format (another rate, width or channel count)."""


def sound_format() -> dict[str, Any]:
    """The output sound's format, for the provenance."""
    return {
        "codec": "aac",
        "sample_rate": SAMPLE_RATE,
        "layout": LAYOUT,
        "bit_rate": AAC_BITRATE,
        "crossfade_s": CROSSFADE_S,
    }


def half_fade(crossfade_s: float = CROSSFADE_S) -> int:
    """The samples of fade on each side of a cut."""
    return round(crossfade_s / 2 * SAMPLE_RATE)


def has_audio(path: str | os.PathLike[str]) -> bool:
    """Whether the file has an audio stream (the header only, nothing decoded)."""
    import av  # noqa: PLC0415

    with av.open(os.fspath(path)) as source:
        return bool(source.streams.audio)


def _silence(np: Any, samples: int) -> Iterator[Any]:
    """`samples` of silence as (2, n) float32 chunks of at most a second."""
    while samples > 0:
        take = min(samples, SILENCE_CHUNK)
        yield np.zeros((CHANNELS, take), dtype=np.float32)
        samples -= take


def silence(samples: int) -> Iterator[Any]:
    """`samples` of silence as (2, n) float32 chunks of at most a second (48 kHz stereo)."""
    import numpy as np  # noqa: PLC0415

    return _silence(np, samples)


def window_chunks(
    path: str | os.PathLike[str],
    *,
    at_s: float,
    samples: int,
    fallback_first_s: float,
    threads: int | None = None,
) -> Iterator[Any]:
    """The sound of `path` from `at_s` (absolute seconds, the clock of its frames' `time`)
    for `samples` samples, as (2, n) float32 chunks at 48 kHz stereo totalling exactly
    `samples` (see the module). `fallback_first_s`: the time taken for the first decoded
    audio frame when it carries none (the picture's origin). `threads` bounds the decoder
    (`join._bound`)."""
    import av  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    emitted = 0
    with av.open(os.fspath(path)) as source:
        if source.streams.audio:
            stream = source.streams.audio[0]
            if threads is not None:
                stream.codec_context.thread_count = threads
                stream.codec_context.thread_type = "SLICE"
            mono = stream.codec_context.channels == 1
            resampler = av.AudioResampler(
                format="fltp", layout="mono" if mono else LAYOUT, rate=SAMPLE_RATE
            )
            offset = 0  # where the window starts, in decoded samples (set on frame one)
            cursor = 0  # decoded samples so far
            started = False

            def place(chunk: Any) -> Iterator[Any]:
                nonlocal cursor, emitted
                values = chunk.to_ndarray()
                if mono:
                    values = np.repeat(values, 2, axis=0)
                count = values.shape[1]
                low = max(cursor, offset)
                high = min(cursor + count, offset + samples)
                if high > low:
                    gap = low - offset - emitted  # the window starts before the sound
                    if gap > 0:
                        yield from _silence(np, gap)
                        emitted += gap
                    yield np.ascontiguousarray(values[:, low - cursor : high - cursor])
                    emitted += high - low
                cursor += count

            for frame in source.decode(stream):
                if not started:
                    started = True
                    first = frame.time if frame.time is not None else fallback_first_s
                    offset = round((at_s - first) * SAMPLE_RATE)
                for chunk in resampler.resample(frame):
                    yield from place(chunk)
                if cursor >= offset + samples:
                    break
            else:
                if started:
                    for chunk in resampler.resample(None):
                        yield from place(chunk)
    yield from _silence(np, samples - emitted)


def faded(chunk: Any, position: int, total: int, fade_in: int, fade_out: int) -> Any:
    """`chunk` — samples `[position, position + n)` of a stretch of `total` samples — with
    `fade_in` samples of fade-in at the stretch's start and `fade_out` of fade-out at its
    end applied (linear, as `join` fades). A chunk outside both fades is returned as is."""
    import numpy as np  # noqa: PLC0415

    count = chunk.shape[1]
    end = position + count
    if not (fade_in and position < fade_in) and not (fade_out and end > total - fade_out):
        return chunk
    chunk = np.array(chunk, dtype=np.float32, copy=True)
    if fade_in and position < fade_in:
        ramp = np.linspace(0.0, 1.0, fade_in, dtype=np.float32)
        high = min(end, fade_in)
        chunk[:, : high - position] *= ramp[position:high]
    if fade_out and end > total - fade_out:
        ramp = np.linspace(1.0, 0.0, fade_out, dtype=np.float32)
        low = max(position, total - fade_out)
        chunk[:, low - position :] *= ramp[low - (total - fade_out) : end - (total - fade_out)]
    return chunk


def write_wav_window(
    path: str | os.PathLike[str],
    out: str | os.PathLike[str],
    *,
    at_s: float,
    samples: int,
    fallback_first_s: float,
    threads: int | None = None,
) -> None:
    """`window_chunks(path, …)` streamed into a 16-bit PCM WAV at `out`, 48 kHz stereo, of
    exactly `samples` frames. Written beside `out` and renamed into place: a failure leaves
    no `out` and never touches an older one."""
    import numpy as np  # noqa: PLC0415

    out_path = os.fspath(out)
    folder, name = os.path.split(out_path)
    partial = os.path.join(folder, f".{name}.{secrets.token_hex(6)}.part")
    try:
        with wave.open(partial, "wb") as sink:
            sink.setnchannels(CHANNELS)
            sink.setsampwidth(WAV_SAMPLE_WIDTH)
            sink.setframerate(SAMPLE_RATE)
            for chunk in window_chunks(
                path,
                at_s=at_s,
                samples=samples,
                fallback_first_s=fallback_first_s,
                threads=threads,
            ):
                pcm = np.clip(chunk.T, -1.0, 1.0) * 32767.0
                sink.writeframes(np.round(pcm).astype("<i2").tobytes())
        os.replace(partial, out_path)
    except BaseException:
        if os.path.exists(partial):
            os.remove(partial)
        raise


def wav_samples(path: str | os.PathLike[str]) -> int:
    """How many samples a sidecar holds — refused (`SoundError`) when it is not 16-bit PCM
    48 kHz stereo."""
    try:
        with wave.open(os.fspath(path), "rb") as source:
            _check_wav(source, path)
            return source.getnframes()
    except (wave.Error, EOFError) as error:
        raise SoundError(f"{os.fspath(path)} is not a WAV: {error}") from error


def _check_wav(source: Any, path: str | os.PathLike[str]) -> None:
    shape = (source.getnchannels(), source.getsampwidth(), source.getframerate())
    if shape != (CHANNELS, WAV_SAMPLE_WIDTH, SAMPLE_RATE):
        raise SoundError(
            f"{os.fspath(path)} is {shape[0]} channels × {8 * shape[1]} bits at {shape[2]} Hz; "
            f"the sidecar is {CHANNELS} × {8 * WAV_SAMPLE_WIDTH} at {SAMPLE_RATE}"
        )


def read_wav_window(path: str | os.PathLike[str], *, start: int, samples: int) -> Iterator[Any]:
    """Samples `[start, start + samples)` of a sidecar as (2, n) float32 chunks of at most
    a second, totalling exactly `samples`: silence past its end."""
    import numpy as np  # noqa: PLC0415

    emitted = 0
    try:
        with wave.open(os.fspath(path), "rb") as source:
            _check_wav(source, path)
            available = source.getnframes()
            if start < available:
                source.setpos(max(0, start))
                while emitted < samples and start + emitted < available:
                    take = min(SILENCE_CHUNK, samples - emitted, available - start - emitted)
                    raw = source.readframes(take)
                    values = np.frombuffer(raw, dtype="<i2").reshape(-1, CHANNELS)
                    if not len(values):
                        break
                    yield (values.T.astype(np.float32) / 32768.0).copy(order="C")
                    emitted += len(values)
    except (wave.Error, EOFError) as error:
        raise SoundError(f"{os.fspath(path)} is not a WAV: {error}") from error
    yield from _silence(np, samples - emitted)


class AacWriter:
    """The one AAC-LC 48 kHz stereo track of a file being muxed into `sink`: `add` takes
    (2, n) float32 chunks in order, `finish` flushes. Stamped by counting samples from 0,
    so the AAC encoder's priming happens once, at the start (where the MP4 edit list
    removes it), and never accumulates per stretch. Holds less than one AAC frame (1024
    samples) besides the chunk being added."""

    def __init__(self, av: Any, sink: Any, *, bit_rate: int = AAC_BITRATE) -> None:
        import numpy as np  # noqa: PLC0415

        self._av, self._np, self._sink = av, np, sink
        stream = sink.add_stream("aac", rate=SAMPLE_RATE)
        stream.layout = LAYOUT
        stream.format = "fltp"
        stream.bit_rate = bit_rate
        stream.codec_context.time_base = Fraction(1, SAMPLE_RATE)
        self.stream = stream
        self._chunk = stream.codec_context.frame_size or 1024
        self._pending = np.zeros((CHANNELS, 0), dtype=np.float32)
        self.samples = 0  # samples handed to the encoder so far

    def add(self, chunk: Any) -> None:
        np = self._np
        self._pending = np.concatenate([self._pending, chunk.astype(np.float32)], axis=1)
        self._encode(final=False)

    def finish(self) -> None:
        self._encode(final=True)
        for packet in self.stream.encode():
            self._sink.mux(packet)

    def _encode(self, final: bool) -> None:
        av, np = self._av, self._np
        while self._pending.shape[1] >= self._chunk or (final and self._pending.shape[1]):
            take = min(self._chunk, self._pending.shape[1])
            frame = av.AudioFrame.from_ndarray(
                np.ascontiguousarray(self._pending[:, :take]), format="fltp", layout=LAYOUT
            )
            frame.sample_rate = SAMPLE_RATE
            frame.pts = self.samples
            frame.time_base = Fraction(1, SAMPLE_RATE)
            self.samples += take
            self._pending = self._pending[:, take:]
            for packet in self.stream.encode(frame):
                self._sink.mux(packet)


__all__ = [
    "AAC_BITRATE",
    "CHANNELS",
    "CROSSFADE_S",
    "LAYOUT",
    "SAMPLE_RATE",
    "SOUND_VERSION",
    "AacWriter",
    "SoundError",
    "faded",
    "half_fade",
    "has_audio",
    "read_wav_window",
    "silence",
    "sound_format",
    "wav_samples",
    "window_chunks",
    "write_wav_window",
]

"""Peak memory of `qualify_creative.video.join_clips` (VE-07) — a local harness, not CI.

    python deploy/measure/join_memory.py make <dir> [--parts 6 --seconds 10]
    python deploy/measure/join_memory.py join <dir> [--size 1080x1920]

`make` writes synthetic 1080p parts (H.264 + AAC, noisy frames so the encoder works for
real); `join` joins them in a fresh process and prints its peak resident memory (peak
working set on Windows, ru_maxrss on Linux) and the wall time. Run the two steps as
separate processes so the parts' generation does not count. The production figure is
the one taken under the creative worker's cgroup (`creative-worker-memory.sh`), whose
VE-10a join phase uses `make` for its parts.
"""

from __future__ import annotations

import argparse
import sys
import time
from fractions import Fraction
from pathlib import Path


def make(folder: Path, parts: int, seconds: int) -> None:
    import av
    import numpy as np

    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    width, height, fps = 1080, 1920, 24
    for index in range(parts):
        path = folder / f"part-{index}.mp4"
        with av.open(str(path), "w", format="mp4") as sink:
            video = sink.add_stream("libx264", rate=fps)
            video.width, video.height, video.pix_fmt = width, height, "yuv420p"
            video.options = {"preset": "ultrafast", "crf": "23"}
            audio = sink.add_stream("aac", rate=48_000)
            audio.layout = "stereo"
            base = rng.integers(0, 255, (height // 8, width // 8, 3), dtype=np.uint8)
            for i in range(seconds * fps):
                small = np.roll(base, i * 3, axis=1)
                pixels = np.repeat(np.repeat(small, 8, axis=0), 8, axis=1)
                frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
                frame.pts, frame.time_base = i, Fraction(1, fps)
                for packet in video.encode(frame):
                    sink.mux(packet)
            t = np.arange(seconds * 48_000) / 48_000
            wave = (0.3 * np.sin(2 * np.pi * (300 + 50 * index) * t)).astype(np.float32)
            for start in range(0, wave.size, 1024):
                chunk = np.tile(wave[start : start + 1024], (2, 1))
                frame = av.AudioFrame.from_ndarray(chunk, format="fltp", layout="stereo")
                frame.sample_rate, frame.pts = 48_000, start
                frame.time_base = Fraction(1, 48_000)
                for packet in audio.encode(frame):
                    sink.mux(packet)
            for stream in (audio, video):
                for packet in stream.encode():
                    sink.mux(packet)
        print(f"{path} {path.stat().st_size / 2**20:.1f} MiB")


def peak_mib() -> float:
    if sys.platform == "win32":
        import psutil

        return psutil.Process().memory_info().peak_wset / 2**20
    import resource

    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # KiB on Linux


def join(folder: Path, size: tuple[int, int]) -> None:
    """Join `part-*.mp4` into `<folder>/joined.mp4` (streamed to disk, never in memory)."""
    # this checkout's package first, whatever the venv's editable install points at
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages/creative/src"))
    from qualify_creative.video import JoinClip, join_clips

    clips = [JoinClip(path) for path in sorted(folder.glob("part-*.mp4"))]
    before = peak_mib()
    began = time.perf_counter()
    joined = join_clips(clips, out=folder / "joined.mp4", size=size)
    took = time.perf_counter() - began
    print(
        f"parts={len(clips)} size={size[0]}x{size[1]} duration={joined.duration_sec:.2f}s "
        f"output={joined.path.stat().st_size / 2**20:.1f}MiB time={took:.1f}s "
        f"peak_before_join={before:.0f}MiB peak={peak_mib():.0f}MiB"
    )
    cgroup = Path("/sys/fs/cgroup/memory.peak")  # inside a container: the cap's own count
    if cgroup.exists():
        print(f"cgroup_memory_peak={int(cgroup.read_text()) / 2**20:.0f}MiB")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=("make", "join"))
    parser.add_argument("folder", type=Path)
    parser.add_argument("--parts", type=int, default=6)
    parser.add_argument("--seconds", type=int, default=10)
    parser.add_argument("--size", default="1080x1920")
    args = parser.parse_args()
    if args.step == "make":
        make(args.folder, args.parts, args.seconds)
    else:
        width, height = (int(side) for side in args.size.split("x"))
        join(args.folder, (width, height))


if __name__ == "__main__":
    main()

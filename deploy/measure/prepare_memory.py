"""Peak memory of `qualify_creative.video.prepare` (EF-03) — a local harness, modelled on
`join_memory.py` (VE-07); `test_video_prepare.py` runs it as a `slow` test.

    python deploy/measure/prepare_memory.py make <dir> [--seconds 16 --size 3840x2160]
    python deploy/measure/prepare_memory.py prepare <dir> [--start 0.5 --end 15.5 --rotate 0]

`make` writes a synthetic 4K source (`prepare_4k.mp4`: H.264 + AAC, noisy frames so the
decoder works for real, 30 fps); `prepare` prepares a stretch of it (15 s by default) in a
fresh process and prints its peak resident memory (peak working set on Windows, ru_maxrss
on Linux) and the wall time. Run the two steps as separate processes so the source's
generation does not count. The production figure is the one taken under the creative
worker's cgroup (`creative-worker-memory.sh`).
"""

from __future__ import annotations

import argparse
import sys
import time
from fractions import Fraction
from pathlib import Path

SOURCE_NAME = "prepare_4k.mp4"


def make(folder: Path, seconds: int, size: tuple[int, int], fps: int = 30) -> None:
    import av
    import numpy as np

    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    width, height = size
    path = folder / SOURCE_NAME
    with av.open(str(path), "w", format="mp4") as sink:
        video = sink.add_stream("libx264", rate=fps)
        video.width, video.height, video.pix_fmt = width, height, "yuv420p"
        video.options = {"preset": "ultrafast", "crf": "23"}
        audio = sink.add_stream("aac", rate=48_000)
        audio.layout = "stereo"
        base = rng.integers(0, 255, (height // 16, width // 16, 3), dtype=np.uint8)
        for i in range(seconds * fps):
            small = np.roll(base, i * 2, axis=1)
            pixels = np.repeat(np.repeat(small, 16, axis=0), 16, axis=1)
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            frame.pts, frame.time_base = i, Fraction(1, fps)
            for packet in video.encode(frame):
                sink.mux(packet)
        t = np.arange(seconds * 48_000) / 48_000
        wave = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
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


def prepare(folder: Path, start: float, end: float, rotate: int) -> None:
    """Prepare `[start, end)` of `<folder>/prepare_4k.mp4` into `<folder>/prepared.mp4`."""
    # this checkout's package first, whatever the venv's editable install points at
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages/creative/src"))
    from qualify_creative.video.prepare import PrepareSegment
    from qualify_creative.video.prepare import prepare as prepare_video

    segment = PrepareSegment(key=SOURCE_NAME, start_s=start, end_s=end, rotate=rotate)
    before = peak_mib()
    began = time.perf_counter()
    prepared = prepare_video(folder / SOURCE_NAME, folder / "prepared.mp4", segment)
    took = time.perf_counter() - began
    print(
        f"stretch={start}-{end}s size={prepared.width}x{prepared.height} "
        f"frames={prepared.frames} duration={prepared.duration_s:.2f}s "
        f"output={Path(prepared.path).stat().st_size / 2**20:.1f}MiB time={took:.1f}s "
        f"peak_before_prepare={before:.0f}MiB peak={peak_mib():.0f}MiB"
    )
    cgroup = Path("/sys/fs/cgroup/memory.peak")  # inside a container: the cap's own count
    if cgroup.exists():
        print(f"cgroup_memory_peak={int(cgroup.read_text()) / 2**20:.0f}MiB")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=("make", "prepare"))
    parser.add_argument("folder", type=Path)
    parser.add_argument("--seconds", type=int, default=16)
    parser.add_argument("--size", default="3840x2160")
    parser.add_argument("--start", type=float, default=0.5)
    parser.add_argument("--end", type=float, default=15.5)
    parser.add_argument("--rotate", type=int, default=0)
    args = parser.parse_args()
    if args.step == "make":
        width, height = (int(side) for side in args.size.split("x"))
        make(args.folder, args.seconds, (width, height))
    else:
        prepare(args.folder, args.start, args.end, args.rotate)


if __name__ == "__main__":
    main()

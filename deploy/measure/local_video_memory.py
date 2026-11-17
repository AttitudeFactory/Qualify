"""EF-15 (m-25026575): memory, CPU and wall time of «Tu video, con efectos» made LOCALLY
(EF-06, `qualify_api.creative.video_pipeline.local.render_local_part`) under the
creative-worker's production cap. Driven by `local-video-memory.sh`.

    python local_video_memory.py make <dir> [--only NAME ...]   # synthetic phone sources
    python local_video_memory.py run <dir> <case>                # one case, fresh process
    python local_video_memory.py cases                           # the case names
    python local_video_memory.py table <raw.log>                 # markdown table of a run

`make` writes noisy sources (block noise that pans plus a per-frame grain, so the decoder
and the encoder work for real, at a phone-like bitrate) and two 4000x3000 photos; run it in
a container of its own: its encoding is never counted. `run` calls `render_local_part`
straight (no Postgres, no Redis, no R2): the store copies a stretch's file from `<dir>` to
the work folder (`copy_to_file`, as `R2ReadingMediaStore` streams it in production — never
read whole into memory). It prints one `EF15-RESULT {json}` line:

- `ru_maxrss_mib`: the process's peak resident set (Linux `ru_maxrss`);
- `cgroup_peak_mib`: the container's `memory.peak` (cgroup v2), which ALSO counts the page
  cache of the files copied and written (reclaimable: the kernel drops it before an OOM);
- `anon_peak_mib`: the highest `anon` of `memory.stat`, sampled every 50 ms — the memory
  that cannot be reclaimed, what an OOM is about; per step in `steps`;
- `cpu_s`: user + system seconds of the process, every codec thread included; `wall_s`.

A case may add the EF-05 compose step's LOCAL part (`overlay_text_layers`, PyAV): the text
PNGs are synthetic RGBA 1080x1920 canvases here — in production the Remotion render service
draws them in ANOTHER container, so only the overlay runs in the creative-worker.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import threading
import time
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any
from uuid import UUID

TENANT = UUID("0e150000-0000-4000-8000-000000000015")
FPS = 30
CGROUP = Path("/sys/fs/cgroup")


@dataclass(frozen=True)
class Clip:
    """A synthetic source: `codec` libx264/libx265, `bits` 8 or 10, display `rotation`."""

    name: str
    size: tuple[int, int]
    seconds: int
    codec: str
    bitrate: int
    rotation: int = 0
    bits: int = 8


CLIPS: tuple[Clip, ...] = (
    Clip("k5_hevc_112.mp4", (5120, 2880), 112, "libx265", 60_000_000),
    Clip("k4_h264_60.mp4", (3840, 2160), 60, "libx264", 50_000_000),
    # a phone held upright: stored landscape, display matrix 90° (as `test_video_prepare`)
    Clip("k4_h264_60_rot90.mp4", (3840, 2160), 60, "libx264", 50_000_000, rotation=90),
    Clip("hd_h264_60.mp4", (1920, 1080), 60, "libx264", 17_000_000),
    Clip("hd_h264_15.mp4", (1920, 1080), 15, "libx264", 17_000_000),
    # an iPhone's default: 4K HEVC 10-bit (HDR off here; the depth is what costs memory)
    Clip("k4_hevc10_60.mp4", (3840, 2160), 60, "libx265", 40_000_000, bits=10),
    # m-25041163: a SMALL vertical source, to be enlarged to 1080x1920
    Clip("small_480x854_60.mp4", (480, 854), 60, "libx264", 2_000_000),
)
#: m-25041163 (not in the code yet): «preparar» always brings the video to 1080x1920 —
#: measured apart, a PyAV graph `scale=1080:1920:flags=<flag>`, encoded as `prepare` does.
UPSCALE_CASES: dict[str, tuple[str, str]] = {
    "up480_lanczos": ("small_480x854_60.mp4", "lanczos"),
    "up480_bicubic": ("small_480x854_60.mp4", "bicubic"),
}
PHOTOS = ("photo_a.jpg", "photo_b.jpg")
PHOTO_SIZE = (4000, 3000)

#: name → (stretches, texts): a stretch is (file, start_s, end_s, speed, kind)
CASES: dict[str, tuple[list[tuple[str, float, float, float, str]], int]] = {
    "k5_112_x20": ([("k5_hevc_112.mp4", 0, 112, 20, "video")], 0),
    "k5_112_x10": ([("k5_hevc_112.mp4", 0, 112, 10, "video")], 0),
    "k5_112_x2": ([("k5_hevc_112.mp4", 0, 112, 2, "video")], 0),
    "k5_30_x2": ([("k5_hevc_112.mp4", 0, 30, 2, "video")], 0),
    "k5_60_x10": ([("k5_hevc_112.mp4", 0, 60, 10, "video")], 0),
    "k4_60_x10": ([("k4_h264_60.mp4", 0, 60, 10, "video")], 0),
    "k4_30_x2": ([("k4_h264_60.mp4", 0, 30, 2, "video")], 0),
    "k4_60_x2": ([("k4_h264_60.mp4", 0, 60, 2, "video")], 0),
    "k4rot_60_x10": ([("k4_h264_60_rot90.mp4", 0, 60, 10, "video")], 0),
    "k4rot_30_x2": ([("k4_h264_60_rot90.mp4", 0, 30, 2, "video")], 0),
    "k4hevc10_60_x10": ([("k4_hevc10_60.mp4", 0, 60, 10, "video")], 0),
    "hd_30_x2": ([("hd_h264_60.mp4", 0, 30, 2, "video")], 0),
    "hd_60_x10": ([("hd_h264_60.mp4", 0, 60, 10, "video")], 0),
    "hd15_x1": ([("hd_h264_15.mp4", 0, 15, 1, "video")], 0),
    "mixed_3x4k_2photos": (
        [
            ("k4_h264_60.mp4", 0, 20, 2, "video"),
            ("photo_a.jpg", 0, 5, 1, "photo"),
            ("k4_h264_60_rot90.mp4", 0, 30, 3, "video"),
            ("k4_h264_60.mp4", 20, 40, 4, "video"),
            ("photo_b.jpg", 0, 5, 1, "photo"),
        ],
        0,
    ),
    "k5_112_x2_3texts": ([("k5_hevc_112.mp4", 0, 112, 2, "video")], 3),
    "k4_60_x2_3texts": ([("k4_h264_60.mp4", 0, 60, 2, "video")], 3),
}


# ---------------------------------------------------------------------------------- make


def _make_clip(folder: Path, clip: Clip) -> None:
    import av
    import numpy as np

    width, height = clip.size
    rng = np.random.default_rng(15)
    base = rng.integers(0, 255, (-(-height // 16), -(-width // 16), 3), dtype=np.uint8)
    grain = [rng.integers(0, 24, (height, width, 3), dtype=np.uint8) for _ in range(3)]
    pix_fmt = "yuv420p10le" if clip.bits == 10 else "yuv420p"
    path = folder / clip.name
    partial = folder / (clip.name + ".partial")
    began = time.perf_counter()
    with av.open(str(partial), "w", format="mp4") as sink:
        video = sink.add_stream(clip.codec, rate=FPS)
        video.width, video.height, video.pix_fmt = width, height, pix_fmt
        video.bit_rate = clip.bitrate
        video.codec_context.time_base = Fraction(1, FPS)
        if clip.codec == "libx265":
            video.options = {"preset": "ultrafast", "x265-params": "log-level=error"}
            video.codec_tag = "hvc1"  # what a phone writes
        else:
            video.options = {"preset": "ultrafast"}
        if clip.rotation:
            video.set_display_rotation(clip.rotation)
        audio = sink.add_stream("aac", rate=48_000)
        audio.layout = "stereo"
        for i in range(clip.seconds * FPS):
            small = np.roll(base, i * 2, axis=1)
            pixels = np.repeat(np.repeat(small, 16, axis=0), 16, axis=1)[:height, :width]
            np.add(pixels, grain[i % 3], out=pixels, casting="unsafe")
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24").reformat(format=pix_fmt)
            frame.pts, frame.time_base = i, Fraction(1, FPS)
            for packet in video.encode(frame):
                sink.mux(packet)
        for packet in video.encode():
            sink.mux(packet)
        t = np.arange(clip.seconds * 48_000) / 48_000
        wave = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        for start in range(0, wave.size, 1024):
            chunk = np.tile(wave[start : start + 1024], (2, 1))
            frame = av.AudioFrame.from_ndarray(chunk, format="fltp", layout="stereo")
            frame.sample_rate, frame.pts = 48_000, start
            frame.time_base = Fraction(1, 48_000)
            for packet in audio.encode(frame):
                sink.mux(packet)
        for packet in audio.encode():
            sink.mux(packet)
    os.replace(partial, path)
    mib = path.stat().st_size / 2**20
    took = time.perf_counter() - began
    shape = f"{width}x{height} {clip.codec} {clip.bits}bit"
    print(f"made {path.name} {shape} {mib:.0f} MiB {took:.0f}s", flush=True)


def _make_photo(folder: Path, name: str, seed: int) -> None:
    import numpy as np
    from PIL import Image

    width, height = PHOTO_SIZE
    rng = np.random.default_rng(seed)
    small = rng.integers(0, 255, (height // 8, width // 8, 3), dtype=np.uint8)
    pixels = np.repeat(np.repeat(small, 8, axis=0), 8, axis=1)
    np.add(pixels, rng.integers(0, 24, pixels.shape, dtype=np.uint8), out=pixels)
    Image.fromarray(pixels).save(folder / name, format="JPEG", quality=92)
    print(f"made {name} {width}x{height} {(folder / name).stat().st_size / 2**20:.1f} MiB")


def make(folder: Path, only: list[str]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for index, name in enumerate(PHOTOS):
        if (not only or name in only) and not (folder / name).exists():
            _make_photo(folder, name, seed=index + 1)
    for clip in CLIPS:
        if only and clip.name not in only:
            continue
        if (folder / clip.name).exists():
            print(f"kept {clip.name}", flush=True)
            continue
        _make_clip(folder, clip)


# ----------------------------------------------------------------------------------- run


class FolderStore:
    """A stretch's file copied from `folder` to the work folder in 1 MiB chunks — the
    shape of `R2ReadingMediaStore.copy_to_file` (streamed, never whole in memory)."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def copy_to_file(self, tenant_id: UUID, key: str, path: Path) -> None:
        name = key.rsplit("/", 1)[-1]
        with (self.folder / name).open("rb") as source, Path(path).open("wb") as sink:
            for chunk in iter(lambda: source.read(1 << 20), b""):
                sink.write(chunk)


def _cgroup_int(name: str) -> int | None:
    try:
        return int((CGROUP / name).read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def _cgroup_stat() -> dict[str, int]:
    try:
        lines = (CGROUP / "memory.stat").read_text().splitlines()
    except OSError:
        return {}
    return {k: int(v) for k, v in (line.split() for line in lines)}


class Sampler:
    """Every 50 ms: the process RSS and the cgroup's `anon`/`current`, kept as the maximum
    per step (`phase`, set by the wrapped steps)."""

    def __init__(self) -> None:
        self.phase = "import"
        self.peaks: dict[str, dict[str, float]] = {}
        self._stop = threading.Event()
        self._page = os.sysconf("SC_PAGE_SIZE")
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._sample()
        self._stop.set()
        self._thread.join()

    def _sample(self) -> None:
        with open("/proc/self/statm") as handle:
            rss = int(handle.read().split()[1]) * self._page
        stat = _cgroup_stat()
        current = _cgroup_int("memory.current") or 0
        peak = self.peaks.setdefault(self.phase, {"rss": 0, "anon": 0, "current": 0})
        peak["rss"] = max(peak["rss"], rss / 2**20)
        peak["anon"] = max(peak["anon"], stat.get("anon", 0) / 2**20)
        peak["current"] = max(peak["current"], current / 2**20)

    def _loop(self) -> None:
        while not self._stop.wait(0.05):
            self._sample()

    def enter(self, phase: str) -> None:
        self._sample()
        self.phase = phase
        print(f"EF15-PHASE {phase} so_far={json.dumps(self.rounded())}", flush=True)

    def rounded(self) -> dict[str, dict[str, int]]:
        return {p: {k: round(v) for k, v in vals.items()} for p, vals in self.peaks.items()}


def _wrap(module: Any, name: str, sampler: Sampler, phase: str) -> None:
    original = getattr(module, name)

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        before = sampler.phase
        sampler.enter(phase)
        try:
            return original(*args, **kwargs)
        finally:
            sampler.enter(before if before != "import" else "between")

    setattr(module, name, wrapped)


def _text_png(index: int) -> bytes:
    """A text layer's shape: a transparent 1080x1920 canvas with a scrim box of letters-like
    noise (what `video_text` returns, drawn here without the render service)."""
    import numpy as np
    from PIL import Image

    canvas = np.zeros((1920, 1080, 4), dtype=np.uint8)
    top = (150, 860, 1500)[index % 3]
    rng = np.random.default_rng(index)
    canvas[top : top + 260, 80:1000, :3] = rng.integers(0, 255, (260, 920, 3), dtype=np.uint8)
    canvas[top : top + 260, 80:1000, 3] = 210
    out = io.BytesIO()
    Image.fromarray(canvas, "RGBA").save(out, format="PNG")
    return out.getvalue()


def run(folder: Path, case: str, work: Path) -> None:
    import resource  # Linux only: `table` also runs on a Windows host

    sampler = Sampler()
    sampler.start()
    wall0 = time.perf_counter()
    usage0 = resource.getrusage(resource.RUSAGE_SELF)
    error = None
    made: Any = None
    if case in UPSCALE_CASES:
        name, flag = UPSCALE_CASES[case]
        stretches: list[tuple[str, float, float, float, str]] = [(name, 0, 60, 1, "video")]
        texts = 0
        import av  # noqa: F401 — the baseline counts PyAV, as `local` would

        baseline = {
            "rss_mib": round(sampler.peaks["import"]["rss"]),
            "anon_mib": round(_cgroup_stat().get("anon", 0) / 2**20),
        }
        try:
            sampler.enter("prepare")
            made = _upscale(folder / name, work / "up.mp4", flag)
        except Exception as exc:  # noqa: BLE001 — reported, the run goes on to print it
            error = f"{type(exc).__name__}: {exc}"
    else:
        made, error, stretches, texts, baseline = _assemble(folder, case, work, sampler)
    sampler.enter("done")
    wall = time.perf_counter() - wall0
    usage = resource.getrusage(resource.RUSAGE_SELF)
    sampler.stop()
    _report(case, stretches, texts, made, error, baseline, sampler, usage, usage0, wall)


def _assemble(
    folder: Path, case: str, work: Path, sampler: Sampler
) -> tuple[Any, str | None, list[tuple[str, float, float, float, str]], int, dict[str, int]]:
    """EF-06's `render_local_part` over `case` (plus the compose overlay when it has texts)."""
    from qualify_api.creative.video_pipeline import local
    from qualify_creative.schemas import PartRecipe, SourceSegment
    from qualify_creative.video import photo_hold, prepare, speed

    stretches, texts = CASES[case]
    baseline = {
        "rss_mib": round(sampler.peaks["import"]["rss"]),
        "anon_mib": round(_cgroup_stat().get("anon", 0) / 2**20),
    }
    _wrap(local, "_fetch", sampler, "fetch")
    _wrap(prepare, "apply_prepare", sampler, "prepare")
    _wrap(photo_hold, "render_photo_hold", sampler, "photo_hold")
    _wrap(speed, "render_speed", sampler, "speed")
    segments = tuple(
        SourceSegment(
            key=f"uploads/{TENANT}/{name}", start_s=start, end_s=end, speed=rate, kind=kind
        )
        for name, start, end, rate, kind in stretches
    )
    out_s = sum((end - start) / rate for _, start, end, rate, _ in stretches)
    part = PartRecipe(index=1, mode="local", seconds=out_s, segments=segments)
    error = None
    made: Any = None
    try:
        made = local.render_local_part(part, tenant_id=TENANT, store=FolderStore(folder), root=work)
        if texts:
            from qualify_creative.video.text_overlay import TimedLayer, overlay_text_layers

            sampler.enter("compose")
            span = made.seconds / texts
            layers = [
                TimedLayer(png=_text_png(i), start_s=i * span, end_s=(i + 1) * span, fade_in_s=0.5)
                for i in range(texts)
            ]
            overlay_text_layers(made.path, work / "composed.mp4", layers)
    except Exception as exc:  # noqa: BLE001 — reported, the run goes on to print it
        error = f"{type(exc).__name__}: {exc}"
    return made, error, stretches, texts, baseline


def _upscale(source: Path, out: Path, flag: str) -> Any:
    """m-25041163 (not in the code yet): `source` enlarged to 1080x1920 by a PyAV graph
    `scale=1080:1920:flags=<flag>`, encoded as `prepare` does (H.264 yuv420p, 30 fps,
    `PREPARE_X264`, 2 slice threads for the decoder and the encoder)."""
    from types import SimpleNamespace

    import av
    from qualify_creative.video.prepare import PREPARE_THREADS, PREPARE_X264

    threads = PREPARE_THREADS
    frames = 0
    tick = Fraction(1, FPS)
    with av.open(str(source)) as container:
        stream = container.streams.video[0]
        stream.codec_context.thread_count = threads
        stream.codec_context.thread_type = "SLICE"
        graph = av.filter.Graph()
        src = graph.add_buffer(template=stream)
        scale = graph.add("scale", f"1080:1920:flags={flag}")
        fmt = graph.add("format", "yuv420p")
        sink_f = graph.add("buffersink")
        src.link_to(scale)
        scale.link_to(fmt)
        fmt.link_to(sink_f)
        graph.configure()
        with av.open(str(out), "w", format="mp4", options={"movflags": "+faststart"}) as sink:
            encoder = sink.add_stream("libx264", rate=FPS)
            encoder.width, encoder.height, encoder.pix_fmt = 1080, 1920, "yuv420p"
            encoder.options = {**PREPARE_X264, "threads": str(threads)}
            encoder.codec_context.time_base = tick
            encoder.codec_context.thread_count = threads
            encoder.codec_context.thread_type = "SLICE"
            for frame in container.decode(stream):
                graph.push(frame)
                while True:
                    try:
                        picture = graph.pull()
                    except (av.error.BlockingIOError, av.error.EOFError):
                        break
                    picture.pts, picture.time_base = frames, tick
                    for packet in encoder.encode(picture):
                        sink.mux(packet)
                    frames += 1
            for packet in encoder.encode():
                sink.mux(packet)
    return SimpleNamespace(seconds=frames / FPS, frames=frames)


def _report(
    case: str,
    stretches: list[tuple[str, float, float, float, str]],
    texts: int,
    made: Any,
    error: str | None,
    baseline: dict[str, int],
    sampler: Sampler,
    usage: Any,
    usage0: Any,
    wall: float,
) -> None:
    events = {}
    try:
        lines = (CGROUP / "memory.events").read_text().splitlines()
        events = {k: int(v) for k, v in (line.split() for line in lines)}
    except OSError:
        pass
    peaks = sampler.rounded()
    result = {
        "case": case,
        "platform": os.uname().machine,
        "stretches": [list(s) for s in stretches],
        "texts": texts,
        "output_s": round(made.seconds, 2) if made else None,
        "frames": made.frames if made else None,
        "error": error,
        "baseline": baseline,
        "ru_maxrss_mib": round(usage.ru_maxrss / 1024),
        "cgroup_peak_mib": round((_cgroup_int("memory.peak") or 0) / 2**20) or None,
        "anon_peak_mib": max((v["anon"] for v in peaks.values()), default=0),
        "steps": peaks,
        "cpu_s": round(usage.ru_utime + usage.ru_stime - usage0.ru_utime - usage0.ru_stime, 1),
        "cpu_cgroup_s": round(
            int(
                next(
                    (
                        line.split()[1]
                        for line in (CGROUP / "cpu.stat").read_text().splitlines()
                        if line.startswith("usage_usec")
                    ),
                    "0",
                )
            )
            / 1e6,
            1,
        )
        if (CGROUP / "cpu.stat").exists()
        else None,
        "wall_s": round(wall, 1),
        "memory_events": events,
        "limit_mib": round((_cgroup_int("memory.max") or 0) / 2**20) or None,
    }
    print("EF15-RESULT " + json.dumps(result), flush=True)


# --------------------------------------------------------------------------------- table


def _describe(stretches: list[list[Any]]) -> tuple[str, str, str, str]:
    by_name = {clip.name: clip for clip in CLIPS}
    sources, speeds, seconds, rotation = [], [], [], []
    for name, start, end, rate, kind in stretches:
        if kind == "photo":
            sources.append("foto 4000x3000")
            seconds.append(f"{end:g}")
            speeds.append("-")
            continue
        clip = by_name[name]
        codec = {"libx265": "HEVC", "libx264": "H.264"}[clip.codec]
        bits = " 10-bit" if clip.bits == 10 else ""
        sources.append(f"{clip.size[0]}x{clip.size[1]} {codec}{bits}")
        seconds.append(f"{end - start:g}")
        speeds.append(f"x{rate:g}")
        rotation.append("sí" if clip.rotation else "no")
    return (
        " + ".join(sources),
        " + ".join(seconds),
        " + ".join(speeds),
        "/".join(rotation) or "-",
    )


def table(raw: Path) -> None:
    rows = []
    for line in raw.read_text(encoding="utf-8", errors="replace").splitlines():
        if "EF15-RESULT " in line:
            rows.append(json.loads(line.split("EF15-RESULT ", 1)[1]))
        elif line.startswith("EF15-OOM "):
            case, platform = line.split()[1:3]
            stretches, texts = CASES.get(case) or ([(UPSCALE_CASES[case][0], 0, 60, 1, "video")], 0)
            rows.append(
                {
                    "case": case,
                    "platform": platform,
                    "oom": True,
                    "stretches": [list(s) for s in stretches],
                    "texts": texts,
                }
            )
    print(
        "| caso | fuente | s fuente | velocidad | rotación | textos | salida s | pico RSS MiB "
        "| pico anon MiB | pico cgroup MiB | prepare/speed/compose anon MiB | CPU s | pared s "
        "| plataforma | OOM |"
    )
    print("|" + "---|" * 15)
    for row in rows:
        source, seconds, speeds, rotation = _describe(row["stretches"])
        if row.get("oom"):
            print(
                f"| {row['case']} | {source} | {seconds} | {speeds} | {rotation} | "
                f"{row['texts']} | - | - | - | - | - | - | - | {row['platform']} | **sí** |"
            )
            continue
        steps = row["steps"]
        split = "/".join(
            str(steps.get(p, {}).get("anon", "-")) for p in ("prepare", "speed", "compose")
        )
        oom = "sí" if row["memory_events"].get("oom_kill") else "no"
        err = f" ({row['error'][:60]})" if row["error"] else ""
        print(
            f"| {row['case']}{err} | {source} | {seconds} | {speeds} | {rotation} | "
            f"{row['texts']} | {row['output_s']} | {row['ru_maxrss_mib']} | "
            f"{row['anon_peak_mib']} | {row['cgroup_peak_mib']} | {split} | {row['cpu_s']} | "
            f"{row['wall_s']} | {row['platform']} | {oom} |"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="step", required=True)
    p_make = sub.add_parser("make")
    p_make.add_argument("folder", type=Path)
    p_make.add_argument("--only", nargs="*", default=[])
    p_run = sub.add_parser("run")
    p_run.add_argument("folder", type=Path)
    p_run.add_argument("case", choices=sorted([*CASES, *UPSCALE_CASES]))
    p_run.add_argument("--work", type=Path, default=Path("/tmp/ef15-work"))
    sub.add_parser("cases")
    p_table = sub.add_parser("table")
    p_table.add_argument("raw", type=Path)
    args = parser.parse_args()
    if args.step == "make":
        make(args.folder, args.only)
    elif args.step == "run":
        args.work.mkdir(parents=True, exist_ok=True)
        run(args.folder, args.case, args.work)
    elif args.step == "cases":
        print("\n".join(CASES))
    else:
        table(args.raw)
    sys.stdout.flush()


if __name__ == "__main__":
    main()

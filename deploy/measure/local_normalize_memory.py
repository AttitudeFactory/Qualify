"""m-25071265: memory, CPU and quality of the local-source normalizer (`normalize_local`,
`qualify_creative.video.local_normalize`, m-25042483) per x264 setting, under the
media-worker's production cap (768m, 1 CPU). Driven by `local-normalize-memory.sh`; it
reuses EF-15's sampler and synthetic sources (`local_video_memory.py`).

    python local_normalize_memory.py make <dir>                       # synthetic sources
    python local_normalize_memory.py run <dir> <source> <variant>     # one encode, measured
    python local_normalize_memory.py quality <dir> <source> <variant> # SSIM/PSNR of the copy
    python local_normalize_memory.py publish <dir> <source> <variant|original> [--seconds S]
    python local_normalize_memory.py compare <dir> <source> <variant> # published vs original
    python local_normalize_memory.py variants | sources

`run` calls the REAL `FfmpegLocalSourceNormalizer.normalize_file` with `X264_PARAMS`
swapped for the variant's (everything else as in the code: veryfast, CRF 18, 1 thread,
the rate cap, the sound). It prints `NORM-RESULT {json}`:

- `anon_peak_mib`: the highest `anon` of the cgroup's `memory.stat`, sampled every 50 ms —
  ffmpeg plus this Python process (`baseline_anon_mib`, before ffmpeg starts), what an OOM
  is about;
- `ffmpeg_maxrss_mib`: ffmpeg's own peak resident set (`RUSAGE_CHILDREN`);
- `cpu_s`: ffmpeg's user + system seconds; `wall_s`; `out_mib` and `out_kbps`.

`quality` compares the copy with its source, both in 8-bit 4:2:0 (the source through the
normalizer's own `scale_filter`, so only the encode differs): at the publication size (the
centred 9:16 crop of `prepare`, scaled to 1080x1920 bicubic) and at the copy's own size.
`publish` runs EF-06's `render_local_part` (one stretch at x1, from 0 s) over the original
(the 4K-8-bit gate lifted: what the published video would be without a copy) or over a
variant's copy; `compare` measures a variant's published video against the original's.
The SSIM is ffmpeg's `All`; the PSNR is its `average` (both on Y, U and V).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent))
from local_video_memory import (  # noqa: E402 — the EF-15 harness, mounted next to this file
    CGROUP,
    Clip,
    FolderStore,
    Sampler,
    _cgroup_int,
    _cgroup_stat,
    _make_clip,
)

TENANT = UUID("0e150000-0000-4000-8000-000000071265")
BASE = "rc-lookahead=0:sync-lookahead=0:mbtree=0"
#: name → x264 params; `b0` is `local-source-v2` (m-25042483), `b3` the ticket's ask
VARIANTS: dict[str, str] = {
    "b0": f"{BASE}:bframes=0",
    "b1": f"{BASE}:bframes=1",
    "b2": f"{BASE}:bframes=2",
    "b3": f"{BASE}:bframes=3",
}
#: the worst case of m-25042483 (noise at the rate cap, EF-15's iPhone-like clip) and a
#: 5K HEVC (the memory worst case there), made by EF-15's own generator
NOISE_CLIPS: tuple[Clip, ...] = (
    Clip("k4_hevc10_60.mp4", (3840, 2160), 60, "libx265", 40_000_000, bits=10),
    Clip("k5_hevc_10.mp4", (5120, 2880), 10, "libx265", 60_000_000),
)
#: a less hostile 4K HEVC 10-bit: ffmpeg's `testsrc2` (moving shapes, text) with a light
#: temporal grain and a 440 Hz tone, at a phone-like rate
TESTSRC = "testsrc2_k4_hevc10_60.mp4"
SOURCES = (*(clip.name for clip in NOISE_CLIPS), TESTSRC)


def make(folder: Path) -> None:
    (folder / "src").mkdir(parents=True, exist_ok=True)
    for clip in NOISE_CLIPS:
        if not (folder / "src" / clip.name).exists():
            _make_clip(folder / "src", clip)
    target = folder / "src" / TESTSRC
    if target.exists():
        return
    partial = target.with_suffix(".partial.mp4")
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=3840x2160:r=30:d=60",
            "-f",
            "lavfi",
            "-i",
            "sine=f=440:d=60:sample_rate=48000",
            "-vf",
            "noise=alls=6:allf=t,format=yuv420p10le",
            "-c:v",
            "libx265",
            "-preset",
            "ultrafast",
            "-b:v",
            "40M",
            "-x265-params",
            "log-level=error",
            "-tag:v",
            "hvc1",
            "-c:a",
            "aac",
            "-ac",
            "2",
            "-shortest",
            str(partial),
        ],
        check=True,
    )
    partial.replace(target)
    print(f"made {TESTSRC} {target.stat().st_size / 2**20:.0f} MiB", flush=True)


def _probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return float(out.strip())


def _copy(folder: Path, source: str, variant: str) -> Path:
    return folder / "out" / f"{Path(source).stem}.{variant}.mp4"


def run(folder: Path, source: str, variant: str) -> None:
    import resource  # Linux only

    from qualify_creative.video import local_normalize

    local_normalize.X264_PARAMS = VARIANTS[variant]
    src = folder / "src" / source
    out = _copy(folder, source, variant)
    out.parent.mkdir(parents=True, exist_ok=True)
    duration = _probe_duration(src)
    sampler = Sampler()
    sampler.start()
    baseline = round(_cgroup_stat().get("anon", 0) / 2**20)
    sampler.enter("normalize")
    wall0 = time.perf_counter()
    error = None
    try:
        local_normalize.FfmpegLocalSourceNormalizer(use_nice=False).normalize_file(
            src, out, duration_s=duration
        )
    except Exception as exc:  # noqa: BLE001 — reported
        error = f"{type(exc).__name__}: {exc}"
    wall = time.perf_counter() - wall0
    sampler.enter("done")
    sampler.stop()
    kids = resource.getrusage(resource.RUSAGE_CHILDREN)
    events: dict[str, int] = {}
    try:
        lines = (CGROUP / "memory.events").read_text().splitlines()
        events = {k: int(v) for k, v in (line.split() for line in lines)}
    except OSError:
        pass
    size = out.stat().st_size if out.exists() else 0
    result = {
        "source": source,
        "variant": variant,
        "x264_params": VARIANTS[variant],
        "version": local_normalize.NORMALIZE_LOCAL_VERSION,
        "duration_s": round(duration, 2),
        "rate_cap_kbps": local_normalize.max_rate_kbps(duration),
        "error": error,
        "baseline_anon_mib": baseline,
        "anon_peak_mib": round(sampler.peaks.get("normalize", {}).get("anon", 0)),
        "ffmpeg_maxrss_mib": round(kids.ru_maxrss / 1024),
        "cpu_s": round(kids.ru_utime + kids.ru_stime, 1),
        "wall_s": round(wall, 1),
        "out_mib": round(size / 2**20, 1),
        "out_kbps": round(size * 8 / 1000 / duration) if duration else None,
        "memory_events": events,
        "limit_mib": round((_cgroup_int("memory.max") or 0) / 2**20) or None,
    }
    print("NORM-RESULT " + json.dumps(result), flush=True)


_SSIM = re.compile(r"SSIM Y:([\d.]+).*All:([\d.]+)")
_PSNR = re.compile(r"PSNR y:([\d.inf]+).*average:([\d.inf]+)")


def _score(dist: Path, ref: Path, dist_vf: str, ref_vf: str) -> dict[str, float]:
    graph = f"[0:v]{dist_vf},split[d1][d2];[1:v]{ref_vf},split[r1][r2];[d1][r1]ssim;[d2][r2]psnr"
    proc = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(dist),
            "-i",
            str(ref),
            "-filter_complex",
            graph,
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    ssim, psnr = _SSIM.search(proc.stderr), _PSNR.search(proc.stderr)
    if not ssim or not psnr:
        raise RuntimeError(proc.stderr[-800:])
    return {
        "ssim_y": float(ssim.group(1)),
        "ssim_all": float(ssim.group(2)),
        "psnr_y": float(psnr.group(1)),
        "psnr_avg": float(psnr.group(2)),
    }


def quality(folder: Path, source: str, variant: str) -> None:
    from qualify_creative.video.local_normalize import scale_filter
    from qualify_creative.video.prepare import _centred_crop

    src, copy = folder / "src" / source, _copy(folder, source, variant)
    width, height = (
        int(v)
        for v in subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=p=0",
                str(copy),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        .stdout.strip()
        .split(",")
    )
    crop = _centred_crop(width, height)
    publish = (
        f"crop={crop.width}:{crop.height}:{crop.x}:{crop.y},"
        "scale=1080:1920:flags=bicubic,format=yuv420p"
    )
    ref = scale_filter()
    result = {
        "source": source,
        "variant": variant,
        "publication_1080x1920": _score(copy, src, publish, f"{ref},{publish}"),
        f"copy_{width}x{height}": _score(copy, src, "format=yuv420p", ref),
    }
    print("NORM-QUALITY " + json.dumps(result), flush=True)


def publish(folder: Path, source: str, variant: str, seconds: float) -> None:
    from qualify_api.creative.video_pipeline import local
    from qualify_api.creative.video_pipeline.local_sources import InMemoryLocalSourceJobs
    from qualify_creative.schemas import PartRecipe, SourceSegment
    from qualify_creative.video import source_limits

    if variant == "original":
        # the published video WITHOUT a copy: the 4K-8-bit gate lifted, as before m-25042483
        source_limits.SourceHeader.needs_normalizing = lambda self: False  # type: ignore[method-assign]
        store_dir, name = folder / "src", source
    else:
        store_dir, name = folder / "out", _copy(folder, source, variant).name
    work = Path("/tmp/publish")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    segment = SourceSegment(
        key=f"uploads/{TENANT}/{name}", start_s=0, end_s=seconds, speed=1, kind="video"
    )
    part = PartRecipe(index=1, mode="local", seconds=seconds, segments=(segment,))
    made = local.render_local_part(
        part,
        tenant_id=TENANT,
        store=FolderStore(store_dir),
        root=work,
        source_jobs=InMemoryLocalSourceJobs(),
    )
    target = folder / "pub" / f"{Path(source).stem}.{variant}.mp4"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(made.path, target)
    print(f"published {target.name} {made.seconds:.2f}s", flush=True)


def compare(folder: Path, source: str, variant: str) -> None:
    stem = Path(source).stem
    pub = folder / "pub"
    scores = _score(pub / f"{stem}.{variant}.mp4", pub / f"{stem}.original.mp4", "null", "null")
    print("NORM-PUBLISHED " + json.dumps({"source": source, "variant": variant, **scores}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="step", required=True)
    sub.add_parser("make").add_argument("folder", type=Path)
    for step in ("run", "quality", "compare"):
        p = sub.add_parser(step)
        p.add_argument("folder", type=Path)
        p.add_argument("source", help="a file in <dir>/src (any phone video copied there too)")
        p.add_argument("variant", choices=sorted(VARIANTS))
    p_pub = sub.add_parser("publish")
    p_pub.add_argument("folder", type=Path)
    p_pub.add_argument("source", help="a file in <dir>/src (any phone video copied there too)")
    p_pub.add_argument("variant", choices=[*sorted(VARIANTS), "original"])
    p_pub.add_argument("--seconds", type=float, default=10.0)
    sub.add_parser("variants")
    sub.add_parser("sources")
    args = parser.parse_args()
    if args.step == "make":
        make(args.folder)
    elif args.step == "run":
        run(args.folder, args.source, args.variant)
    elif args.step == "quality":
        quality(args.folder, args.source, args.variant)
    elif args.step == "publish":
        publish(args.folder, args.source, args.variant, args.seconds)
    elif args.step == "compare":
        compare(args.folder, args.source, args.variant)
    elif args.step == "variants":
        print("\n".join(VARIANTS))
    else:
        print("\n".join(SOURCES))


if __name__ == "__main__":
    main()

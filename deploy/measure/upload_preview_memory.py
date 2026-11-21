"""m-25026643 (ED-09): memory and time of the generator upload's 480p copy
(`qualify_creative.video.upload_preview`, the `media-worker`'s `upload_preview` job) under
the media-worker's production cap (768m, 1 CPU). Driven by `upload-preview-memory.sh`; it
reuses EF-15's sampler (`local_video_memory.py`) and m-25071265's synthetic sources
(`local_normalize_memory.py make`), and makes the ticket's worst case from them.

    python upload_preview_memory.py make <dir>             # the 112 s sources, by stream copy
    python upload_preview_memory.py run <dir> <source>     # one copy, measured
    python upload_preview_memory.py sources

`make` needs `<dir>/src/k5_hevc_10.mp4` and `k4_hevc10_60.mp4` (from
`local-normalize-memory.sh make`). It writes, without re-encoding the 5K picture except
once for the 10-bit one:

- `k5_hevc_112.mp4`: the 10 s 5K HEVC looped to 112 s (`-stream_loop`, `-c copy`) — the
  ticket's «un 5K de 112 s»;
- `k5_hevc10_112.mp4`: the same 10 s re-encoded once to 10-bit HEVC, then looped to 112 s
  — an iPhone's depth at 5K, the decoder's worst case;
- `k4_hevc10_60_rot90.mp4`: the 4K 10-bit HEVC with a 90° display rotation (a phone held
  upright): the copy must come out portrait.

`run` calls the REAL `FfmpegUploadPreviewer.make_preview` (nice off: the cap is the
container's). It prints `PREVIEW-RESULT {json}`: `anon_peak_mib` (the cgroup's highest
`anon`, sampled every 50 ms — ffmpeg plus this Python process, `baseline_anon_mib` before
ffmpeg starts), `ffmpeg_maxrss_mib` (ffmpeg's own peak RSS, `RUSAGE_CHILDREN`), `cpu_s`,
`wall_s`, the copy's size and its header (size, pixel format, sound or not).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from local_video_memory import CGROUP, Sampler, _cgroup_int, _cgroup_stat  # noqa: E402

SOURCES = ("k5_hevc_112.mp4", "k5_hevc10_112.mp4", "k4_hevc10_60_rot90.mp4")


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args], check=True)


def _loop(src: Path, out: Path, seconds: int) -> None:
    _ffmpeg("-stream_loop", "-1", "-i", str(src), "-t", str(seconds), "-c", "copy", str(out))


def make(folder: Path) -> None:
    src = folder / "src"
    five_k, four_k = src / "k5_hevc_10.mp4", src / "k4_hevc10_60.mp4"
    for needed in (five_k, four_k):
        if not needed.exists():
            raise SystemExit(f"missing {needed}: run local-normalize-memory.sh make first")
    if not (src / SOURCES[0]).exists():
        _loop(five_k, src / SOURCES[0], 112)
    if not (src / SOURCES[1]).exists():
        ten = src / "k5_hevc10_10.partial.mp4"
        _ffmpeg(
            "-i",
            str(five_k),
            "-vf",
            "format=yuv420p10le",
            "-c:v",
            "libx265",
            "-preset",
            "ultrafast",
            "-b:v",
            "60M",
            "-x265-params",
            "log-level=error",
            "-tag:v",
            "hvc1",
            str(ten),
        )
        _loop(ten, src / SOURCES[1], 112)
        ten.unlink()
    if not (src / SOURCES[2]).exists():
        rotated = src / SOURCES[2]
        _ffmpeg("-i", str(four_k), "-c", "copy", "-metadata:s:v:0", "rotate=90", str(rotated))
    for name in SOURCES:
        print(f"made {name} {(src / name).stat().st_size / 2**20:.0f} MiB", flush=True)


def _probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(out)


def run(folder: Path, source: str) -> None:
    import resource  # Linux only

    from qualify_creative.video import upload_preview

    src = folder / "src" / source
    out = folder / "preview" / f"{Path(source).stem}.preview.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    info = _probe(src)
    duration = float(info["format"]["duration"])
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    sampler = Sampler()
    sampler.start()
    baseline = round(_cgroup_stat().get("anon", 0) / 2**20)
    sampler.enter("preview")
    wall0 = time.perf_counter()
    error = None
    try:
        upload_preview.FfmpegUploadPreviewer(use_nice=False).make_preview(
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
    made: dict = {}
    if out.exists() and error is None:
        probe = _probe(out)
        streams = probe["streams"]
        copy = next(s for s in streams if s["codec_type"] == "video")
        made = {
            "width": copy["width"],
            "height": copy["height"],
            "pix_fmt": copy["pix_fmt"],
            "streams": [s["codec_type"] for s in streams],
            "rotation": [d.get("rotation") for d in copy.get("side_data_list", [])],
            "duration_s": round(float(probe["format"]["duration"]), 2),
        }
    size = out.stat().st_size if out.exists() else 0
    result = {
        "source": source,
        "version": upload_preview.UPLOAD_PREVIEW_VERSION,
        "source_size": [video["width"], video["height"]],
        "source_pix_fmt": video.get("pix_fmt"),
        "duration_s": round(duration, 2),
        "error": error,
        "baseline_anon_mib": baseline,
        "anon_peak_mib": round(sampler.peaks.get("preview", {}).get("anon", 0)),
        "ffmpeg_maxrss_mib": round(kids.ru_maxrss / 1024),
        "cpu_s": round(kids.ru_utime + kids.ru_stime, 1),
        "wall_s": round(wall, 1),
        "out_mib": round(size / 2**20, 2),
        "out_kbps": round(size * 8 / 1000 / duration) if duration else None,
        "preview": made,
        "memory_events": events,
        "limit_mib": round((_cgroup_int("memory.max") or 0) / 2**20) or None,
    }
    print("PREVIEW-RESULT " + json.dumps(result), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=("make", "run", "sources"))
    parser.add_argument("folder", nargs="?", type=Path)
    parser.add_argument("source", nargs="?")
    args = parser.parse_args()
    if args.step == "sources":
        print("\n".join(SOURCES))
    elif args.step == "make":
        make(args.folder)
    else:
        run(args.folder, args.source)


if __name__ == "__main__":
    main()

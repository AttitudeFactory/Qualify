"""EF-18 (m-25026598): memory, CPU and wall time of the contact sheet
(`qualify_creative.video.contact_sheet.make_contact_sheet`) over a composed 1080x1920 video,
as the creative worker makes it right after the compose (inside the heavy-video gate).

    python contact_sheet_memory.py <dir> [SECONDS...]   # default: 15 60

Writes noisy H.264 sources with a cut every 5 s (each shot its own colour and noise) into
`<dir>`, then measures one sheet per source in this process: the resident memory sampled
every 10 ms above the baseline before the call (`psutil`), and the time. Prints one
`EF18-RESULT {json}` line per source. The sheet makes one pass with one decoded frame
alive at a time (plus a small JPEG every grid step), so its peak is a few frames of
1080x1920 plus the decoder's buffers — far under the compose's own.

The sources are named `…_cuts5s.mp4`: a file left by an earlier version of this script
(whose noise made no cut the detector sees) is never reused. `shots` counts the shots the
pass found (3 for 15 s); it is 1 when the pass ran past its budget (`cuts: "even"`: the
cuts were dropped, not missed). Measured 2026-11-23: 15 s → 3 shots, `detected`.

Under the creative-worker's cap (Docker; the image has no `psutil`, so RSS comes from
`/proc`, plus the cgroup's `anon` peak, `memory.peak` and `ru_maxrss` on Linux):

    python contact_sheet_memory.py make <dir> [SECONDS...]   # sources only, own container
    python contact_sheet_memory.py chain <ef14-dir> [CASE]   # EF-14 compose, then the sheet

`chain` runs `recompose_memory.py run` (EF-14's 1080p final compose, `final_3texts_3layers`
by default, sources from `recompose-memory.sh make`) with the sheet as the compose's
`contact_sheet` hook, as production calls it: after the encoder, the composed bytes held.
Its `EF14-RESULT` carries a `sheet` step; `EF18-CHAIN {json}` adds the sheet's own time.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any


def _make(path: Path, seconds: int, size: tuple[int, int] = (1080, 1920)) -> None:
    import av
    import numpy as np

    def base(shot: int) -> np.ndarray:
        # each shot its own noise around its own colour: every cut changes most pixels
        rng = np.random.default_rng(shot)
        colour = np.array([(53 * shot) % 200 + 30, (97 * shot) % 200 + 30, (151 * shot) % 200 + 30])
        noise = rng.integers(-40, 40, (size[1] // 8, size[0] // 8, 3))
        return np.clip(colour + noise, 0, 255).astype(np.uint8)

    with av.open(str(path), "w") as sink:
        stream = sink.add_stream("libx264", rate=30)
        stream.width, stream.height, stream.pix_fmt = size[0], size[1], "yuv420p"
        stream.options = {"preset": "ultrafast", "crf": "20"}
        tiles: dict[int, np.ndarray] = {}
        for index in range(seconds * 30):
            shot = index // 150  # a cut every 5 s
            tile = np.roll(tiles.setdefault(shot, base(shot)), index % 150, axis=1)
            picture = np.kron(tile, np.ones((8, 8, 1), dtype=np.uint8))
            for packet in stream.encode(av.VideoFrame.from_ndarray(picture, format="rgb24")):
                sink.mux(packet)
        for packet in stream.encode():
            sink.mux(packet)


CGROUP = Path("/sys/fs/cgroup")


def _rss() -> int:
    """The process' resident set: `psutil` when installed (Windows), else `/proc`."""
    try:
        import psutil
    except ImportError:
        with open("/proc/self/statm") as handle:
            return int(handle.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    return int(psutil.Process().memory_info().rss)


def _anon() -> int:
    """The cgroup's unreclaimable memory (`anon` of `memory.stat`); 0 outside a cgroup v2."""
    try:
        for line in (CGROUP / "memory.stat").read_text().splitlines():
            key, value = line.split()
            if key == "anon":
                return int(value)
    except (OSError, ValueError):
        pass
    return 0


def _cgroup_peak() -> int:
    try:
        return int((CGROUP / "memory.peak").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return 0


def _ru_maxrss_mib() -> int | None:
    try:
        import resource
    except ImportError:  # Windows
        return None
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)


def _measure(path: Path) -> dict[str, object]:
    from qualify_creative.video.contact_sheet import make_contact_sheet

    baseline, anon_baseline = _rss(), _anon()
    peak, anon_peak = [baseline], [anon_baseline]
    done = threading.Event()

    def sample() -> None:
        while not done.is_set():
            peak[0] = max(peak[0], _rss())
            anon_peak[0] = max(anon_peak[0], _anon())
            time.sleep(0.01)

    sampler = threading.Thread(target=sample)
    sampler.start()
    wall0, cpu0 = time.perf_counter(), time.process_time()
    sheet = make_contact_sheet(path)
    wall, cpu = time.perf_counter() - wall0, time.process_time() - cpu0
    done.set()
    sampler.join()
    mib = 1 << 20
    return {
        "source": path.name,
        "wall_s": round(wall, 2),
        "cpu_s": round(cpu, 2),
        "rss_baseline_mib": round(baseline / mib),
        "rss_peak_mib": round(peak[0] / mib),
        "rss_delta_mib": round((peak[0] - baseline) / mib),
        "anon_baseline_mib": round(anon_baseline / mib),
        "anon_peak_mib": round(anon_peak[0] / mib),
        "cgroup_peak_mib": round(_cgroup_peak() / mib) or None,
        "ru_maxrss_mib": _ru_maxrss_mib(),
        "shots": sheet.shots,
        "frames": len(sheet.frames),
        "cuts": sheet.cuts,
        "times": [f.time_s for f in sheet.frames],
        "strip_size": list(sheet.strip_size),
        "strip_kib": len(sheet.strip) // 1024,
        "frame_kib": [len(f.jpeg) // 1024 for f in sheet.frames],
    }


def chain(folder: Path, case: str) -> None:
    """EF-14's compose with the sheet as its `contact_sheet` hook, in one process."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import recompose_memory as compose_case
    from qualify_api.creative.contact_sheet import keep_contact_sheet
    from qualify_api.creative.video_pipeline.recompose import ClipComposer

    samplers: list[Any] = []

    class Captured(compose_case.base.Sampler):  # type: ignore[name-defined, misc]
        def __init__(self) -> None:
            super().__init__()
            samplers.append(self)

    compose_case.base.Sampler = Captured
    original = ClipComposer.compose
    timing: dict[str, object] = {}

    def sheet(path: Path) -> Any:
        samplers[0].enter("sheet")
        wall0 = time.perf_counter()
        made = keep_contact_sheet(path, lambda name, data: name, source={"stage": "final"})
        timing["sheet_wall_s"] = round(time.perf_counter() - wall0, 2)
        timing["sheet"] = None if made is None else {k: made.get(k) for k in ("shots", "cuts")}
        samplers[0].enter("compose")
        return made

    def compose(self: ClipComposer, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("contact_sheet", sheet)
        return original(self, *args, **kwargs)

    ClipComposer.compose = compose  # type: ignore[method-assign]
    compose_case.run(folder, case)
    print("EF18-CHAIN " + json.dumps(timing), flush=True)


def main() -> None:
    if sys.argv[1] == "chain":
        chain(Path(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else "final_3texts_3layers")
        return
    make_only = sys.argv[1] == "make"
    first = 2 if make_only else 1
    folder = Path(sys.argv[first])
    folder.mkdir(parents=True, exist_ok=True)
    for seconds in [int(s) for s in sys.argv[first + 1 :]] or [15, 60]:
        path = folder / f"composed_1080x1920_{seconds}_cuts5s.mp4"
        if not path.exists():
            _make(path, seconds)
        if not make_only:
            print("EF18-RESULT " + json.dumps(_measure(path)), flush=True)


if __name__ == "__main__":
    main()

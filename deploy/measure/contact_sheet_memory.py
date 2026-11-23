"""EF-18 (m-25026598): memory, CPU and wall time of the contact sheet
(`qualify_creative.video.contact_sheet.make_contact_sheet`) over a composed 1080x1920 video,
as the creative worker makes it right after the compose (inside the heavy-video gate).

    python contact_sheet_memory.py <dir> [SECONDS...]   # default: 15 60

Writes noisy H.264 sources with a cut every 5 s into `<dir>`, then measures one sheet per
source in this process: the resident memory sampled every 10 ms above the baseline before
the call (`psutil`), and the time. Prints one `EF18-RESULT {json}` line per source. The
sheet keeps one decoded frame alive at a time (two sequential passes), so its peak is a
frame or two of 1080x1920 plus the decoder's buffers — far under the compose's own.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path


def _make(path: Path, seconds: int, size: tuple[int, int] = (1080, 1920)) -> None:
    import av
    import numpy as np

    rng = np.random.default_rng(0)
    base = rng.integers(0, 255, (size[1] // 8, size[0] // 8, 3), dtype=np.uint8)
    with av.open(str(path), "w") as sink:
        stream = sink.add_stream("libx264", rate=30)
        stream.width, stream.height, stream.pix_fmt = size[0], size[1], "yuv420p"
        stream.options = {"preset": "ultrafast", "crf": "20"}
        for index in range(seconds * 30):
            shot = index // 150  # a cut every 5 s
            tile = np.roll(base, index + shot * 37, axis=1)
            tile = (tile.astype(np.int16) + shot * 60) % 256
            picture = np.kron(tile.astype(np.uint8), np.ones((8, 8, 1), dtype=np.uint8))
            for packet in stream.encode(av.VideoFrame.from_ndarray(picture, format="rgb24")):
                sink.mux(packet)
        for packet in stream.encode():
            sink.mux(packet)


def _measure(path: Path) -> dict[str, object]:
    import psutil
    from qualify_creative.video.contact_sheet import make_contact_sheet

    process = psutil.Process()
    baseline = process.memory_info().rss
    peak = [baseline]
    done = threading.Event()

    def sample() -> None:
        while not done.is_set():
            peak[0] = max(peak[0], process.memory_info().rss)
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
        "shots": sheet.shots,
        "frames": len(sheet.frames),
        "strip_size": list(sheet.strip_size),
        "strip_kib": len(sheet.strip) // 1024,
        "frame_kib": [len(f.jpeg) // 1024 for f in sheet.frames],
    }


def main() -> None:
    folder = Path(sys.argv[1])
    folder.mkdir(parents=True, exist_ok=True)
    for seconds in [int(s) for s in sys.argv[2:]] or [15, 60]:
        path = folder / f"composed_1080x1920_{seconds}.mp4"
        if not path.exists():
            _make(path, seconds)
        print("EF18-RESULT " + json.dumps(_measure(path)), flush=True)


if __name__ == "__main__":
    main()

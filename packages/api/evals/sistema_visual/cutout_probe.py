# ruff: noqa: E501
"""SISVIS-002 (spike m-25042530): try the cutout paths the repo already has on one photo per business.

1. ``LocalBiRefNetSegmenter`` (``qualify_creative.photo.segment``): needs ``rembg[cpu]`` (onnxruntime)
   and the BiRefNet weights. Probed only — nothing is installed or downloaded.
2. The stickers' chroma key (``qualify_creative.seasonal.kawaii.chroma_key``): pure numpy. It keys
   out the background connected to the image border, so it only works on a flat background.

Each photo runs in a fresh process so the peak RSS is per photo.

    PYTHONPATH=packages/creative/src python packages/api/evals/sistema_visual/cutout_probe.py <photo>...
"""

from __future__ import annotations

import importlib.util
import json
import resource
import subprocess
import sys
import time
from pathlib import Path


def one(path: str) -> dict:
    import numpy as np
    from PIL import Image
    from qualify_creative.seasonal.kawaii import chroma_key

    t0 = time.time()
    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8)
    rgba, bg = chroma_key(rgb)
    secs = time.time() - t0
    alpha = rgba[..., 3]
    out = Path(path).with_name(Path(path).stem + ".chroma.png")
    Image.fromarray(rgba).save(out)
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024  # macOS: bytes
    return {
        "photo": Path(path).name,
        "size": [int(rgb.shape[1]), int(rgb.shape[0])],
        "border_colour": list(map(int, bg)),
        "transparent_pct": round(100 * float((alpha < 16).mean()), 1),
        "opaque_pct": round(100 * float((alpha > 240).mean()), 1),
        "seconds": round(secs, 3),
        "peak_rss_mb": round(peak_mb, 1),
        "out": str(out),
    }


def main(paths: list[str]) -> None:
    probe = {
        "birefnet": {
            "rembg_installed": importlib.util.find_spec("rembg") is not None,
            "onnxruntime_installed": importlib.util.find_spec("onnxruntime") is not None,
            "weights_dir_exists": (Path.home() / ".u2net").exists(),
        }
    }
    results = []
    for p in paths:
        r = subprocess.run(
            [sys.executable, __file__, "--one", p], capture_output=True, text=True, check=False
        )
        results.append(
            json.loads(r.stdout)
            if r.returncode == 0
            else {"photo": Path(p).name, "error": r.stderr[-300:]}
        )
    probe["chroma_key"] = results
    print(json.dumps(probe, indent=1))


if __name__ == "__main__":
    if sys.argv[1] == "--one":
        print(json.dumps(one(sys.argv[2])))
    else:
        main(sys.argv[1:])

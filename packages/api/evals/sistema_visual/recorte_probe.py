# ruff: noqa: E501
"""RECORTE-001 (spike m-25042530, story m-25042543): background removal with open models on CPU.

Runs the repo's own ``LocalBiRefNetSegmenter`` (loaded straight from
``qualify_creative/photo/segment.py``, so the measured code is the code that would ship) with
each rembg model name, one fresh process per model:

- **cold**: import + session (weights loaded) + the first photo, timed separately;
- **warm**: every photo again with the session already loaded (best of ``--repeat``);
- **peak RSS**: ``ru_maxrss`` of the child after load, after the first photo and at the end.

For every model x photo it writes ``<out>/<model>/<stem>.png`` (RGBA cut-out) and
``<stem>.check.png``: the cut-out over a flat magenta, to judge edges, holes and halos by eye.

Nothing here is installed in the repo: run it with an isolated venv that has ``rembg[cpu]``
(see docs/modelos-generativos/isnet-general-use.md, RECORTE-001) and ``U2NET_HOME`` pointing at the weights.

    U2NET_HOME=<weights> <venv>/bin/python packages/api/evals/sistema_visual/recorte_probe.py \
        --out <dir> --models birefnet-general-lite isnet-general-use u2net -- <photo>...

Local only: no network beyond rembg's first weight download, no R2, no paid calls.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import resource
import subprocess
import sys
import time
from pathlib import Path

SEGMENT_PY = (
    Path(__file__).resolve().parents[4] / "packages/creative/src/qualify_creative/photo/segment.py"
)
CHECK_COLOR = (255, 0, 200)


def _rss_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(peak / 1024 / 1024 if sys.platform == "darwin" else peak / 1024, 1)


def _segmenter_class() -> type:
    spec = importlib.util.spec_from_file_location("segment", SEGMENT_PY)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.LocalBiRefNetSegmenter


def _alpha_stats(mask: object) -> dict:
    import numpy as np

    a = np.asarray(mask, dtype=np.uint8)
    soft = float(((a > 8) & (a < 247)).mean())
    ys, xs = np.nonzero(a > 127)
    bbox = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1] if len(xs) else None
    return {
        "fg_share": round(float((a > 127).mean()), 4),
        "soft_share": round(soft, 4),
        "bbox": bbox,
    }


def child(model: str, photos: list[str], out: str, repeat: int) -> dict:
    t_import = time.perf_counter()
    from PIL import Image

    seg = _segmenter_class()(model)
    import rembg

    if os.environ.get("RECORTE_LEAN") == "1":
        # What a production wiring would add: no CPU memory arena and no memory-pattern
        # pre-allocation, so onnxruntime frees activations between runs. Patched in from outside
        # so the class under test stays the repo's own.
        import onnxruntime as ort

        orig = rembg.new_session

        def lean_session(name: str, *args: object, **kw: object) -> object:
            so = ort.SessionOptions()
            so.enable_cpu_mem_arena = False
            so.enable_mem_pattern = False
            return orig(name, *args, sess_opts=so, **kw)

        rembg.new_session = lean_session

    t0 = time.perf_counter()
    seg.mask(
        Image.new("RGB", (64, 64), (128, 128, 128))
    )  # forces new_session: weight load + one tiny pass
    load_s = time.perf_counter() - t0
    rss_after_load = _rss_mb()
    rss_after_first = None
    rows = []
    for p in photos:
        img = Image.open(p).convert("RGB")
        times = []
        mask = None
        for _ in range(1 + repeat):
            t = time.perf_counter()
            mask = seg.mask(img)
            times.append(time.perf_counter() - t)
        assert mask is not None
        odir = Path(out) / model
        odir.mkdir(parents=True, exist_ok=True)
        rgba = img.copy()
        rgba.putalpha(mask)
        stem = Path(p).stem
        rgba.save(odir / f"{stem}.png")
        check = Image.new("RGB", img.size, CHECK_COLOR)
        check.paste(img, mask=mask)
        check.thumbnail((900, 900))
        check.save(odir / f"{stem}.check.png")
        rows.append(
            {
                "photo": stem,
                "size": list(img.size),
                "first_s": round(times[0], 3),
                "warm_s": round(min(times[1:]) if len(times) > 1 else times[0], 3),
                "rss_mb_after": _rss_mb(),
                **_alpha_stats(mask),
            }
        )
        if rss_after_first is None:
            rss_after_first = _rss_mb()
    return {
        "model": model,
        "rembg": getattr(rembg, "__version__", "?"),
        "omp_num_threads": os.environ.get("OMP_NUM_THREADS", "default"),
        "lean": os.environ.get("RECORTE_LEAN") == "1",
        "import_s": round(t0 - t_import, 3),
        "load_s": round(load_s, 3),
        "cold_first_photo_s": round(load_s + rows[0]["first_s"], 3) if rows else None,
        "rss_mb_after_load": rss_after_load,
        "rss_mb_after_first_photo": rss_after_first,
        "rss_mb_peak": _rss_mb(),
        "photos": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--models", nargs="+", default=["birefnet-general-lite"])
    ap.add_argument("--repeat", type=int, default=2)
    ap.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("photos", nargs="+")
    a = ap.parse_args()
    if a.child:
        print(json.dumps(child(a.models[0], a.photos, a.out, a.repeat)))
        return
    try:
        cpu = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True
        ).stdout.strip()
    except FileNotFoundError:  # Linux container
        cpu = f"{platform.machine()} x{os.cpu_count()}"
    results: dict = {
        "machine": {
            "cpu": cpu or platform.processor(),
            "os": platform.platform(),
            "python": platform.python_version(),
        },
        "runs": [],
    }
    for m in a.models:
        r = subprocess.run(
            [
                sys.executable,
                __file__,
                "--child",
                "--out",
                a.out,
                "--models",
                m,
                "--repeat",
                str(a.repeat),
                *a.photos,
            ],
            capture_output=True,
            text=True,
            env=os.environ,
        )
        if r.returncode:
            results["runs"].append(
                {"model": m, "returncode": r.returncode, "error": r.stderr[-800:]}
            )
            continue
        results["runs"].append(json.loads(r.stdout.strip().splitlines()[-1]))
        print(f"{m}: done", file=sys.stderr)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    tag = os.environ.get("OMP_NUM_THREADS", "default") + (
        "-lean" if os.environ.get("RECORTE_LEAN") == "1" else ""
    )
    (Path(a.out) / f"results.{'+'.join(a.models)}.threads-{tag}.json").write_text(
        json.dumps(results, indent=1)
    )
    print(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()

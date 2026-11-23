"""EF-14 (m-25026592): memory, CPU and wall time of the compose over a Seedance clip — the
1080p final composed again with its preview's recipe (`MediaProducer._recompose_final` →
`recompose.ClipComposer.compose`) and the 480p preview — under the creative-worker's
production cap. Driven by `recompose-memory.sh`.

    python recompose_memory.py make <dir>          # synthetic Seedance-like sources
    python recompose_memory.py run <dir> <case>    # one case, fresh process
    python recompose_memory.py cases               # the case names

`make` writes noisy H.264 sources with sound, as the fitter hands them on (the final: 1080x1920
at a Seedance-like bitrate; the preview: 486x864), with `local_video_memory`'s generator; run
it in a container of its own. `run` holds the final's bytes TWICE in memory first — the raw
1080p and the fitted one live together in `_final_video` — then composes with synthetic
1080x1920 text PNGs (in production the Remotion service draws them in another container) and
the library's own layer loops. It prints one `EF14-RESULT {json}` line with the same fields
as `local_video_memory.py` (`ru_maxrss_mib`, `anon_peak_mib`, `cgroup_peak_mib`, `cpu_s`,
`wall_s`).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import local_video_memory as base  # noqa: E402 — the sibling harness: sampler, generator

#: Seedance clips last 4-15 s: the longest, at a bitrate like the fitted final's
SOURCES: tuple[base.Clip, ...] = (
    base.Clip("seedance_final_1080x1920_15.mp4", (1080, 1920), 15, "libx264", 12_000_000),
    base.Clip("seedance_preview_486x864_15.mp4", (486, 864), 15, "libx264", 2_000_000),
)
#: name → (source, texts, layers)
CASES: dict[str, tuple[str, int, int]] = {
    "final_3texts_3layers": ("seedance_final_1080x1920_15.mp4", 3, 3),
    "final_3texts": ("seedance_final_1080x1920_15.mp4", 3, 0),
    "final_3layers": ("seedance_final_1080x1920_15.mp4", 0, 3),
    "preview_3texts_3layers": ("seedance_preview_486x864_15.mp4", 3, 3),
}
LAYERS = ("humo_capa", "brasas_capa", "vapor_capa")


def make(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for clip in SOURCES:
        base._make_clip(folder, clip)


def run(folder: Path, case: str) -> None:
    import resource

    sampler = base.Sampler()
    sampler.start()
    wall0 = time.perf_counter()
    usage0 = resource.getrusage(resource.RUSAGE_SELF)
    source, texts, layers = CASES[case]
    from qualify_api.creative.video_pipeline.recompose import ClipComposer, ComposeRecipe
    from qualify_creative.schemas import EffectUse, VideoTextLayer

    baseline = {
        "rss_mib": round(int(open("/proc/self/statm").read().split()[1]) * 4096 / 2**20),
        "anon_mib": round(base._cgroup_stat().get("anon", 0) / 2**20),
    }
    sampler.enter("read")
    raw = (folder / source).read_bytes()
    fitted = bytes(raw)  # the raw 1080p and the fitted one, both held as in `_final_video`
    places = ("top", "middle", "bottom")
    recipe = ComposeRecipe(
        text_layers=tuple(
            VideoTextLayer(text=f"Texto {i + 1}", place=places[i]) for i in range(texts)
        ),
        effects=tuple(EffectUse(effect_id=name, version=1) for name in LAYERS[:layers]),
        brand={"palette": [], "fonts": {}},
    )
    drawn = tuple(
        SimpleNamespace(png=base._text_png(i), provenance={}, report={}) for i in range(texts)
    )
    error = None
    made: Any = None
    sampler.enter("compose")
    try:
        made = ClipComposer(render_client=object()).compose(
            fitted, recipe, drawn=drawn, stage="final"
        )
    except Exception as exc:  # noqa: BLE001 — reported, not raised
        error = f"{type(exc).__name__}: {exc}"
    sampler.enter("done")
    sampler.stop()
    usage = resource.getrusage(resource.RUSAGE_SELF)
    peaks = sampler.rounded()
    result = {
        "case": case,
        "platform": os.uname().machine,
        "source_mib": round(len(raw) / 2**20, 1),
        "texts": texts,
        "layers": layers,
        "output_mib": round(len(made.data) / 2**20, 1) if made else None,
        "size": [made.width, made.height] if made else None,
        "error": error,
        "baseline": baseline,
        "ru_maxrss_mib": round(usage.ru_maxrss / 1024),
        "cgroup_peak_mib": round((base._cgroup_int("memory.peak") or 0) / 2**20) or None,
        "anon_peak_mib": max((v["anon"] for v in peaks.values()), default=0),
        "steps": peaks,
        "cpu_s": round(usage.ru_utime + usage.ru_stime - usage0.ru_utime - usage0.ru_stime, 1),
        "wall_s": round(time.perf_counter() - wall0, 1),
    }
    del raw, fitted
    print(f"EF14-RESULT {json.dumps(result)}", flush=True)


def main() -> None:
    step = sys.argv[1] if len(sys.argv) > 1 else "cases"
    if step == "make":
        make(Path(sys.argv[2]))
    elif step == "run":
        run(Path(sys.argv[2]), sys.argv[3])
    elif step == "cases":
        print("\n".join(CASES))
    else:
        raise SystemExit("usage: recompose_memory.py make|run|cases ...")


if __name__ == "__main__":
    main()

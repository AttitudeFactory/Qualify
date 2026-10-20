"""Voice-transcription experiment in Langfuse — docs/plan-observabilidad-langfuse.md §7,
fase 6.

Transcribes the recordings of `cases.json` with each local Whisper (faster-whisper on CPU,
$0) as Langfuse dataset runs (dataset `voz-transcripcion`), scored by
`qualify_api.evals.voice_transcription`: WER against the human transcript — or, until
there is one, against large-v3-turbo's — and the real-time factor. Needs the `ml` group
(faster-whisper) and the Langfuse server; the models load from the local cache:

    just langfuse-up
    just eval-voz

Add recordings to `audio/` (git-ignored: a voice is personal data) with their human
transcript in `cases.json`; until then the one sample only measures agreement.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def _load_env(path: str | None) -> None:
    if not path or not Path(path).exists():
        return
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() and not name.strip().startswith("#"):
            os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--configs", help="comma-separated; default: every config")
    args = parser.parse_args(argv)
    _load_env(args.env_file)

    from qualify_shared import observability

    from qualify_api.evals import voice_transcription as vt

    items = vt.load_cases(HERE / "cases.json")
    if not items:
        print("No recordings found: add them to audio/ and to cases.json", file=sys.stderr)
        return 2
    observability.sync_dataset(
        vt.DATASET, items, description="Grabaciones de voz con su transcripción (fase 6)."
    )
    labels = args.configs.split(",") if args.configs else list(vt.CONFIGS)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report: dict[str, Any] = {"runs": {}}
    for label in labels:
        model = vt.CONFIGS[label]
        print(f"\n== {label} ({model})")
        summary = observability.run_experiment(
            vt.DATASET,
            name=vt.DATASET,
            run_name=f"{label} · {stamp}",
            task=lambda case, m=model: vt.transcribe(case, m),
            evaluators=vt.ITEM_EVALUATORS,
            run_evaluators=vt.RUN_EVALUATORS,
            # one at a time: both models share the same CPU
            max_concurrency=1,
            metadata={"config": label, "model": model},
        )
        report["runs"][label] = {
            "run": dict(summary.run_scores),
            "items": {
                str((o.input or {}).get("id")): {
                    "wer": o.scores.get("wer"),
                    "rtf": o.scores.get("rtf"),
                    "texto": (o.output or {}).get("texto"),
                    "fuente_referencia": (o.output or {}).get("fuente_referencia"),
                }
                for o in summary.outcomes
            },
        }
        for k, v in sorted(summary.run_scores.items()):
            print(f"   {k:<28} {v}")
    out = HERE / "results" / f"{stamp}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nGuardado en {out.relative_to(HERE.parents[3]).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

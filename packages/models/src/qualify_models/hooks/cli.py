"""`python -m qualify_models.hooks` — run the hook extractor over one or more videos.

Two shapes of run, and the difference matters:

    # deterministic only: no network, no weights, seconds per video
    PYTHONPATH=packages/models/src uv run --no-sync python -m qualify_models.hooks \\
        --video packages/models/tests/fixtures/sample_source.mp4 \\
        --no-vlm --no-asr --out-dir /tmp/hooks

    # full: local Qwen3-VL for the frames + hosted whisper for the audio.
    # NOTE: the local VLM measured >20 min per video on an offloaded CPU setup — fine for
    # one video, not for a corpus. See NOTES_hook_pattern_spike.md §B.5.
    PYTHONPATH=packages/models/src uv run --no-sync python -m qualify_models.hooks \\
        --video packages/models/tests/fixtures/sample_source.mp4 \\
        --keep-artifacts --out-dir /tmp/hooks

The explicit PYTHONPATH works around the shared venv's broken editable install, which
`CLAUDE.md` documents; it is not part of the design.

Writes `hook_features.jsonl` (one full record per video, everything kept) and
`hook_features.csv` (one flat row per video x window, the join-ready table for Fase D).
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from qualify_models.hooks.extract import extract_hook_features
from qualify_models.hooks.schema import FLAT_ROW_COLUMNS, HookFeatures
from qualify_models.hooks.spec import PRIMARY_WINDOW_SECONDS, WINDOW_SECONDS


def _parse_windows(raw: str) -> tuple[float, ...]:
    return tuple(sorted(float(part) for part in raw.split(",") if part.strip()))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m qualify_models.hooks",
        description="Extract structured hook features from the opening of short videos.",
    )
    parser.add_argument(
        "--video",
        type=Path,
        action="append",
        required=True,
        help="path to an mp4; repeat the flag for several videos",
    )
    parser.add_argument(
        "--source-id",
        action="append",
        default=None,
        help="id for the matching --video (defaults to the file stem)",
    )
    parser.add_argument("--out-dir", type=Path, required=True, help="where to write results")
    parser.add_argument(
        "--windows",
        type=_parse_windows,
        default=WINDOW_SECONDS,
        help="comma-separated window widths in seconds "
        f"(default: {','.join(str(w) for w in WINDOW_SECONDS)})",
    )
    parser.add_argument(
        "--vlm-windows",
        type=_parse_windows,
        default=(PRIMARY_WINDOW_SECONDS,),
        help="which windows get a VLM call (default: the primary window only — one call per video)",
    )
    parser.add_argument("--no-vlm", action="store_true", help="skip the vision model entirely")
    parser.add_argument("--no-asr", action="store_true", help="skip transcription entirely")
    parser.add_argument(
        "--online",
        action="store_true",
        help="resolve model revisions against the HF Hub (adds a network call per model)",
    )
    parser.add_argument(
        "--keep-artifacts",
        action="store_true",
        help="keep sampled frames and contact sheets under --out-dir (to see what the VLM saw)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    source_ids = args.source_id or [video.stem for video in args.video]
    if len(source_ids) != len(args.video):
        print("--source-id must be given once per --video, or not at all", file=sys.stderr)
        return 2

    resolver = None
    if args.online:
        from qualify_models.eval.provenance import resolve_revision

        resolver = resolve_revision

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    results: list[HookFeatures] = []
    for video, source_id in zip(args.video, source_ids):
        print(f"[hooks] {source_id}: {video}", file=sys.stderr)
        kwargs = {}
        if resolver is not None:
            kwargs["revision_resolver"] = resolver
        features = extract_hook_features(
            video,
            source_id=source_id,
            windows=args.windows,
            vlm_windows=args.vlm_windows,
            use_vlm=not args.no_vlm,
            use_asr=not args.no_asr,
            artifacts_dir=(out_dir / "artifacts" / source_id) if args.keep_artifacts else None,
            **kwargs,
        )
        results.append(features)

    jsonl_path = out_dir / "hook_features.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for features in results:
            handle.write(features.model_dump_json() + "\n")

    csv_path = out_dir / "hook_features.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(FLAT_ROW_COLUMNS))
        writer.writeheader()
        for features in results:
            for window in features.windows:
                writer.writerow(features.to_flat_row(window.window_seconds))

    n_rows = sum(len(f.windows) for f in results)
    print(f"wrote {len(results)} video(s), {n_rows} row(s) -> {jsonl_path} and {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

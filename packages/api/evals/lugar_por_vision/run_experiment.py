"""EF-20: where a video's text and logo go, read by Claude Haiku 5.5 (m-25026599).

Measures `qualify_api.creative.placement_ai.VisionPlacer` — the REAL module, its prompt,
its guards — on a golden set of labelled frames, against today's fixed places (text
`bottom`, logo `top`, free). The criterion (Deivid, 2026-11-23, replacing the ticket's
«>= 90 % of 30 frames», which a frame filled by the subject makes unreachable): the text
does not cover the subject in >= 90 % of the frames that have a free band. Also reported:
every frame, the best any one band per video can do (`ceiling`) and the baseline.

A case is one prepared video (or a few stills of one) with 1 to 3 labelled frames; each
labelled frame is one «cuadro» of the golden set and carries the bands the subject
occupies in it (`subject_bands`, labelled by a person beforehand). Per case and arm the
placer is called `--repeats` times; every answer is scored on every labelled frame of
the case: `text_ok` = the text's band is not one of the frame's subject bands (the same
for the logo).

Arms: `3f` sends every labelled frame of the case (1-3), `1f` only the middle one; the
baseline `fijo` (today's places) costs nothing and is always scored.

Without `--cases`: repo material only (the generator's sample photos and the effects'
preview videos), with no labels — enough for the dry run, never for spending. With
`--cases <file.json>` (OUTSIDE the repo; paths relative to the file):

    {"cases": [
      {"id": "bianki-01", "video": "bianki/01.mp4",
       "frames": [{"at_s": 1.2, "subject_bands": ["middle", "bottom"]}, ...]},
      {"id": "polette-02",
       "images": [{"path": "polette/02-a.jpg", "subject_bands": ["middle"]}, ...]}
    ]}

Spend: before anything is sent the whole plan is quoted at the placer's bound
(`worst_request_usd` per call, <= `MAX_REQUEST_USD`) and the run refuses to start when
the quote passes `--max-usd` (at most `HARD_CEILING_USD`). During the run every call goes
through a `DollarMeter` whose limit is `--max-usd`: the turn's worst case is reserved
before it is sent and settled with what Anthropic billed; a call that does not fit is not
sent. The consumption rows go to the report, not to the database (the business here is
fictitious). Outputs (frames sent, every decision, report.json) go OUTSIDE the repo:
`%TEMP%/m-25026599/<stamp>/` by default.

    # dry run: builds every request through the real placer, quotes, sends nothing
    uv run --no-sync python packages/api/evals/lugar_por_vision/run_experiment.py
    uv run --no-sync python packages/api/evals/lugar_por_vision/run_experiment.py \\
        --cases <outside>/casos.json
    # paid (only with Deivid's authorization on record; tope US$2)
    uv run --no-sync python packages/api/evals/lugar_por_vision/run_experiment.py \\
        --env-file ../../.env --cases <outside>/casos.json --i-have-spend-authorization \\
        --max-usd 2
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
#: A fictitious business: the consumption rows go to the report, never to the database.
TENANT_ID = UUID("7e7e0000-0000-4000-8000-000000000020")
#: The authorization of the ticket's brief: at most US$2 for the whole measurement.
HARD_CEILING_USD = Decimal("2")
ARMS = ("3f", "1f")
BASELINE = "fijo"

#: Repo material for the dry run (no labels: never scored, never paid).
REPO_CASES: tuple[dict[str, Any], ...] = (
    {"id": "muestra-foto-1", "images": [{"path": "packages/render/public/sample/photo-1.jpg"}]},
    {"id": "muestra-foto-2", "images": [{"path": "packages/render/public/sample/photo-2.jpg"}]},
    {"id": "efecto-brasas", "video": "assets/effects/brasas_capa/v1/preview.webm"},
    {"id": "efecto-vapor", "video": "assets/effects/vapor_capa/v1/preview.webm"},
)


class DryRun(Exception):
    """Raised by the dry client instead of sending: the request was captured."""


def _load_env(path: str | None) -> None:
    if not path or not Path(path).is_file():
        return
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() and not name.strip().startswith("#"):
            os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


def _load_cases(path: str | None) -> tuple[list[dict[str, Any]], Path, bool]:
    """`(cases, base dir, labelled)`."""
    if not path:
        return list(REPO_CASES), REPO, False
    file = Path(path).resolve()
    data = json.loads(file.read_text(encoding="utf-8"))
    return list(data["cases"]), file.parent, True


def _video_seconds(path: Path) -> float:
    from qualify_creative.video._source import open_video, probe

    with open_video(path) as (container, stream):
        timeline = probe(container, stream, need_end=True)
    return float((timeline.end_s or 0.0) - timeline.origin_s)


def _frame_at(path: Path, at_s: float) -> Any:
    """One upright frame of the video at `path`, at or after `at_s`."""
    from qualify_creative.video.shots import SamplingPlan, ShotSpan, sample_frames

    from qualify_api.creative.placement_ai import FRAME_BOX, FRAME_JPEG_QUALITY, PlacementFrame

    plan = SamplingPlan(
        positions=(), anchors=(at_s,), max_frames=1, box=FRAME_BOX, jpeg_quality=FRAME_JPEG_QUALITY
    )
    (still,) = sample_frames(path, [ShotSpan(0, 0.0, at_s + 3600.0)], plan=plan)
    return PlacementFrame(
        jpeg=still.jpeg, width=still.width, height=still.height, at_s=still.time_s
    )


def _labelled_frames(case: dict[str, Any], base: Path) -> list[tuple[Any, tuple[str, ...] | None]]:
    """`(PlacementFrame, subject_bands)` of every frame of the case (bands None: unlabelled)."""
    from PIL import Image

    from qualify_api.creative.placement_ai import (
        MAX_FRAMES,
        frame_from_image,
        sample_placement_frames,
    )

    out: list[tuple[Any, tuple[str, ...] | None]] = []
    if case.get("images"):
        for item in case["images"]:
            with Image.open(base / item["path"]) as image:
                frame = frame_from_image(image, at_s=item.get("at_s"))
            bands = item.get("subject_bands")
            out.append((frame, tuple(bands) if bands is not None else None))
    elif case.get("video"):
        video = base / case["video"]
        if case.get("frames"):
            for item in case["frames"]:
                bands = item.get("subject_bands")
                out.append(
                    (
                        _frame_at(video, float(item["at_s"])),
                        tuple(bands) if bands is not None else None,
                    )
                )
        else:
            out.extend((f, None) for f in sample_placement_frames(video, _video_seconds(video)))
    if not 1 <= len(out) <= MAX_FRAMES:
        raise SystemExit(f"case {case.get('id')}: {len(out)} frames (1-{MAX_FRAMES})")
    return out


def _arm_frames(arm: str, labelled: list[Any]) -> list[Any]:
    return [labelled[len(labelled) // 2]] if arm == "1f" else list(labelled)


def _score(
    text: str, logo: str, labelled: list[tuple[Any, tuple[str, ...] | None]]
) -> list[dict[str, Any]]:
    return [
        {
            "at_s": frame.at_s,
            "subject_bands": list(bands),
            "text_ok": text not in bands,
            "logo_ok": logo not in bands,
            # a frame where some band is free of the subject: the main criterion (Deivid,
            # 2026-11-23) counts only these
            "free": len(set(bands)) < len(VIDEO_BANDS),
        }
        for frame, bands in labelled
        if bands is not None
    ]


VIDEO_BANDS = ("top", "middle", "bottom")
#: Deivid, 2026-11-23: the text leaves the subject free in >= 90 % of the frames that have
#: a free band.
TARGET_FREE_RATE = 0.90


def ceiling(cases: list[dict[str, Any]], prepared: dict[str, Any]) -> dict[str, int]:
    """The most frames any placement can get right: one text band per video (the layers
    keep their band for the whole video), the best band of each case."""
    best = 0
    total = 0
    free = 0
    for case in cases:
        bands = [b for _, b in prepared[case["id"]] if b is not None]
        total += len(bands)
        free += sum(1 for b in bands if len(set(b)) < len(VIDEO_BANDS))
        best += max((sum(1 for b in bands if band not in b) for band in VIDEO_BANDS), default=0)
    return {"frames": total, "frames_with_free_band": free, "best_possible": best}


class DryClient:
    """A `client_factory` that captures each request and sends nothing."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def __call__(self, _api_key: str) -> Any:
        return self

    @property
    def messages(self) -> Any:
        return self

    def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        raise DryRun()


class CeilingReached(Exception):
    """The run's meter cannot pay the next call: the run stops."""


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts over every scored frame of every repeat; `per_repeat` gives each repeat's
    own counts (frames once), the unit of the ticket's criterion."""
    scored = [s for r in rows for s in r["scores"]]
    text_ok = sum(1 for s in scored if s["text_ok"])
    logo_ok = sum(1 for s in scored if s["logo_ok"])
    free = [s for s in scored if s["free"]]
    text_ok_free = sum(1 for s in free if s["text_ok"])
    per_repeat: dict[int, dict[str, int]] = {}
    for r in rows:
        rep = per_repeat.setdefault(
            int(r.get("repeat", 0)), {"text_ok": 0, "text_ok_free": 0, "logo_ok": 0}
        )
        for s in r["scores"]:
            rep["text_ok"] += s["text_ok"]
            rep["logo_ok"] += s["logo_ok"]
            rep["text_ok_free"] += s["text_ok"] and s["free"]
    rate_free = round(text_ok_free / len(free), 4) if free else None
    return {
        "calls": sum(1 for r in rows if r.get("source") != BASELINE),
        "frames_scored": len(scored),
        "frames_with_free_band": len(free),
        "text_ok_free": text_ok_free,
        "text_ok_free_rate": rate_free,
        "meets_target": rate_free is not None and rate_free >= TARGET_FREE_RATE,
        "text_ok": text_ok,
        "text_ok_rate": round(text_ok / len(scored), 4) if scored else None,
        "logo_ok": logo_ok,
        "logo_ok_rate": round(logo_ok / len(scored), 4) if scored else None,
        "per_repeat": per_repeat,
        "fallbacks": dict(Counter(r["fallback_reason"] for r in rows if r.get("fallback_reason"))),
        "cost_usd": str(sum((Decimal(r["cost_usd"]) for r in rows), Decimal(0))),
    }


def run(args: argparse.Namespace) -> int:
    from qualify_api import claude_tools
    from qualify_api.creative import placement_ai as pa

    paid = args.i_have_spend_authorization
    cases, base, labelled_set = _load_cases(args.cases)
    if args.case:
        cases = [c for c in cases if c["id"] in args.case]
    if paid and not labelled_set:
        print("A paid run needs a labelled golden set (--cases).", file=sys.stderr)
        return 2
    arms = [a for a in args.arms.split(",") if a]
    if any(a not in ARMS for a in arms):
        print(f"--arms: one or more of {ARMS}", file=sys.stderr)
        return 2

    out = Path(args.out) / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    prepared = {c["id"]: _labelled_frames(c, base) for c in cases}

    # the whole plan, quoted at the placer's own bound, before anything is sent
    plan: list[tuple[str, str, int]] = []
    quote = Decimal(0)
    for case in cases:
        labelled = prepared[case["id"]]
        for arm in arms:
            frames = [f for f, _ in _arm_frames(arm, labelled)]
            worst = pa.worst_request_usd(pa.build_messages(frames))
            for repeat in range(args.repeats):
                plan.append((case["id"], arm, repeat))
                quote += worst
    frames_scored = sum(1 for c in cases for _, b in prepared[c["id"]] if b is not None)
    print(
        f"Plan: {len(cases)} casos · {frames_scored} cuadros etiquetados · brazos {arms} x "
        f"{args.repeats} repeticiones = {len(plan)} llamadas · cotizado al tope "
        f"USD {quote} (tope de la corrida USD {args.max_usd})"
    )
    if quote > args.max_usd:
        print(
            f"La cotización USD {quote} pasa el tope USD {args.max_usd}: no se envía nada.",
            file=sys.stderr,
        )
        return 3

    started = time.monotonic()
    records: list[Any] = []
    claude_tools.configure_consumption_sink(records.append)
    dry_client = DryClient()
    if paid:
        try:
            api_key = claude_tools.api_key_from_env()
        except claude_tools.MissingAPIKey as exc:
            print(exc, file=sys.stderr)
            return 2
        factory = claude_tools.default_client
    else:
        api_key, factory = "dry-run", dry_client
    meter = claude_tools.DollarMeter(args.max_usd)
    # the real guard semantics; the eval's pieces are fictitious, so a fresh id per call
    guard = pa.InMemoryCallGuard(per_piece=1, fleet_cap=len(plan))
    placer = pa.VisionPlacer(guard=guard, api_key=api_key, client_factory=factory)

    report: dict[str, Any] = {
        "ticket": "m-25026599",
        "model": pa.MODEL_ID,
        "effort": pa.MODEL_EFFORT,
        "prompt_version": pa.PLACEMENT_PROMPT_VERSION,
        "prompt_fingerprint": pa.prompt_fingerprint(),
        "pricing_table_version": claude_tools.PRICING_TABLE_VERSION,
        "paid": paid,
        "repeats": args.repeats,
        "arms": arms,
        "quote_usd": str(quote),
        "max_usd": str(args.max_usd),
        "rows": [],
    }
    try:
        for case in cases:
            labelled = prepared[case["id"]]
            case_dir = out / case["id"]
            case_dir.mkdir()
            for i, (frame, _bands) in enumerate(labelled, 1):
                (case_dir / f"cuadro-{i}.jpg").write_bytes(frame.jpeg)
            report["rows"].append(
                {
                    "case": case["id"],
                    "arm": BASELINE,
                    "source": BASELINE,
                    "text_place": pa.FALLBACK_TEXT_PLACE,
                    "logo_place": pa.FALLBACK_LOGO_PLACE,
                    "cost_usd": "0",
                    "scores": _score(pa.FALLBACK_TEXT_PLACE, pa.FALLBACK_LOGO_PLACE, labelled),
                }
            )
            for arm in arms:
                sent = _arm_frames(arm, labelled)
                for repeat in range(args.repeats):
                    decision = placer.place(
                        [f for f, _ in sent],
                        tenant_id=TENANT_ID,
                        piece_id=uuid4(),
                        # dry: no meter — a captured request would count as spent
                        budget=meter if paid else None,
                    )
                    row = {
                        "case": case["id"],
                        "arm": arm,
                        "repeat": repeat,
                        "source": decision.source,
                        "fallback_reason": decision.fallback_reason,
                        "text_place": decision.text_place,
                        "logo_place": decision.logo_place,
                        "subject": decision.subject,
                        "subject_bands": list(decision.subject_bands),
                        "adjustments": [list(a) for a in decision.adjustments],
                        "reason": decision.reason,
                        "cost_usd": str(decision.cost_usd),
                        "provenance": dict(decision.provenance),
                        "scores": _score(decision.text_place, decision.logo_place, labelled),
                    }
                    if not paid:
                        row["dry"] = True
                        row["fallback_reason"] = None
                        row["worst_request_usd"] = str(
                            pa.worst_request_usd(pa.build_messages([f for f, _ in sent]))
                        )
                    report["rows"].append(row)
                    if paid:
                        said = (
                            f"{decision.source} texto={decision.text_place} "
                            f"logo={decision.logo_place} · USD {decision.cost_usd}"
                        )
                    else:
                        said = (
                            f"compilado (seco), {len(sent)} cuadro(s), "
                            f"cotizado USD {row['worst_request_usd']}"
                        )
                    print(f"  {case['id']}/{arm}#{repeat}: {said}")
                    if paid and decision.fallback_reason == pa.FALLBACK_BUDGET:
                        report["stopped"] = "tope alcanzado"
                        raise CeilingReached
    except CeilingReached:
        print("TOPE: el medidor no paga la siguiente llamada; se detiene.", file=sys.stderr)
    finally:
        claude_tools.configure_consumption_sink(None)

    report["dry_requests"] = len(dry_client.requests)
    report["consumption"] = [
        {
            "model_revision": r.model_revision,
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "cache_read_tokens": r.cache_read_tokens,
            "cache_creation_tokens": r.cache_creation_tokens,
            "cost_usd": str(r.cost_usd),
        }
        for r in records
    ]
    report["meter"] = meter.as_document()
    report["elapsed_s"] = round(time.monotonic() - started, 1)
    calls_made = len(records)
    report["cost_per_call_usd"] = (
        str((meter.spent_usd / calls_made).quantize(Decimal("0.000001"))) if calls_made else None
    )
    if labelled_set:
        report["ceiling"] = ceiling(cases, prepared)
        report["target_free_rate"] = TARGET_FREE_RATE
        report["summary"] = {
            arm: _summary([r for r in report["rows"] if r["arm"] == arm])
            for arm in [BASELINE, *arms]
        }
    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    if "ceiling" in report:
        c = report["ceiling"]
        print(
            f"  cuadros: {c['frames']} · con franja libre: {c['frames_with_free_band']} · "
            f"máximo posible: {c['best_possible']}/{c['frames']}"
        )
    for arm, s in (report.get("summary") or {}).items():
        print(
            f"  {arm}: con franja libre {s['text_ok_free']}/{s['frames_with_free_band']} "
            f"({s['text_ok_free_rate']}, meta {TARGET_FREE_RATE}: "
            f"{'cumple' if s['meets_target'] else 'no cumple'}) · texto {s['text_ok']}/"
            f"{s['frames_scored']} · logo {s['logo_ok']}/{s['frames_scored']} · "
            f"por repetición {s['per_repeat']} · caídas {s['fallbacks']} · USD {s['cost_usd']}"
        )
    print(
        f"\nCotizado: USD {quote} · gastado: USD {meter.spent_usd} · {calls_made} llamadas · "
        f"USD {report['cost_per_call_usd']} por llamada · {report['elapsed_s']} s · "
        f"informe en {out}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--i-have-spend-authorization", action="store_true")
    parser.add_argument("--max-usd", type=Decimal, default=HARD_CEILING_USD)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--arms", default=",".join(ARMS), help="3f, 1f or both")
    parser.add_argument("--case", action="append", help="only these case ids")
    parser.add_argument("--cases", help="JSON of labelled cases outside the repo (real material)")
    parser.add_argument(
        "--out", default=str(Path(tempfile.gettempdir()) / "m-25026599"), help="outside the repo"
    )
    args = parser.parse_args(argv)
    if not Decimal(0) < args.max_usd <= HARD_CEILING_USD:
        print(f"--max-usd must be in (0, {HARD_CEILING_USD}]", file=sys.stderr)
        return 2
    if args.repeats < 1:
        print("--repeats must be >= 1", file=sys.stderr)
        return 2
    _load_env(args.env_file)
    for path in (args.out, args.cases):
        if path and Path(path).resolve().is_relative_to(REPO):
            print("--out and --cases must be outside the repository", file=sys.stderr)
            return 2
    return run(args)


if __name__ == "__main__":
    sys.exit(main())

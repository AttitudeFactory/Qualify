"""«Sigue a la anterior» after the owner's OWN video (m-25129406): the paid measurement.

PREPARED, NOT RUN. Deivid approves the paid run in session (the ticket's ceiling and the
night window), never an agent. The method, cases, prompts and quote are in
`qualify_api.evals.extend_own_video_bench`; this file only cuts the files and drives the
vendor. Every output goes OUTSIDE the repo (`%TEMP%/extender-video-propio/` by default).

Subcommands:

    plan       the cases, their prompts and their cost from the price guard over the
               versioned pricing table (`v10`). Calls nothing, writes nothing.
    preparar   cuts the LAST seconds of each owner video (at most 10 s, whole seconds,
               upright, no audio — `cut_window`, what the producer sends) into the run
               folder. Free and local. Upload each `cola-<case>.mp4` to a public https
               link (ModelArk takes no Base64 for video) and write it in the material.
    extender   ONE Seedance 2.5 `extend` task per case (480p draft, 5 s), one at a time.
               Needs EXACTLY ONE of `--dry-run` (validates every request through the real
               adapter and prints the quote; sends nothing) and
               `--i-have-spend-authorization --max-usd <n>` (at most US$10). Paid: only
               23:00-05:00 Bogotá unless `--allow-daytime`, with the eval key
               (`QUALIFY_BYTEPLUS_ARK_EVAL_API_KEY`). Every task is reserved in `gasto.json`
               before it is sent; a task sent and not settled is never sent again.
    planilla   the judgment sheets (`juicio-deivid.csv`, `juicio-herwin.csv`).

`--material <file>.json` (outside the repo; the videos are the business's own, with the
written permission of whoever appears in them):

    {"videos": {
        "rostro":   {"file": "<path>", "url": "https://.../cola-rostro.mp4"},
        "producto": {"file": "<path>", "url": "https://.../cola-producto.mp4"},
        "lugar":    {"file": "<path>", "url": "https://.../cola-lugar.mp4"}}}

    just eval-extender-propio plan
    just eval-extender-propio preparar --material %TEMP%/extender-video-propio/material.json
    just eval-extender-propio extender --run <run folder> --material <...> --dry-run
    just eval-extender-propio extender --env-file <checkout>/.env --run <run folder> \\
        --material <...> --i-have-spend-authorization --max-usd 3.10
    just eval-extender-propio planilla --run <run folder>
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import tempfile
import urllib.request
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
DEFAULT_OUT = Path(tempfile.gettempdir()) / "extender-video-propio" / "corridas"
SPEND_FILE = "gasto.json"
RESULTS_FILE = "resultados.json"
TAILS_FILE = "colas.json"
SENT, PAID, RELEASED = "enviada", "pagada", "liberada"
JUDGES = ("deivid", "herwin")
SHEET = (
    "caso",
    "rostro",
    "acepto",
    "error",
    "segundos_entrada",
    "costo_usd",
    "video",
    "misma_escena",
    "misma_luz",
    "sin_saltos",
    "sin_letras",
    "creible",
    "nota",
)


def _load_env(path: str | None) -> None:
    if not path or not Path(path).is_file():
        return
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() and not name.strip().startswith("#"):
            os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


def _write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def _outside_repo(path: Path, what: str) -> Path:
    resolved = path.resolve()
    if resolved.is_relative_to(REPO):
        raise SystemExit(f"{what} va fuera del repositorio")
    return resolved


def _material(path: str | None) -> dict[str, dict[str, Any]]:
    if not path:
        return {}
    file = _outside_repo(Path(path), "el material")
    data = json.loads(file.read_text(encoding="utf-8"))
    videos = data.get("videos") or {}
    out: dict[str, dict[str, Any]] = {}
    for case_id, entry in videos.items():
        raw = entry.get("file")
        local = _outside_repo((file.parent / str(raw)), f"{case_id}: el video") if raw else None
        if local is not None and not local.is_file():
            raise SystemExit(f"{case_id}: no existe {local}")
        out[case_id] = {"file": local, "url": entry.get("url")}
    return out


def _run_dir(args: argparse.Namespace, *, create: bool) -> Path:
    if args.run:
        run = Path(args.run)
        if not run.is_dir():
            raise SystemExit(f"no existe la corrida {run}")
    else:
        if not create:
            raise SystemExit("falta --run <carpeta de la corrida>")
        run = Path(args.out) / datetime.now().strftime("%Y%m%d-%H%M%S")
        run.mkdir(parents=True, exist_ok=True)
    return _outside_repo(run, "la corrida")


def _pricing() -> Any:
    from qualify_creative.pricing import JsonPricingTable

    from qualify_api.evals.extend_own_video_bench import PRICING_VERSION

    return JsonPricingTable(PRICING_VERSION)


def _seconds(run: Path | None) -> dict[str, float]:
    if run is None:
        return {}
    tails = _read_json(run / TAILS_FILE, {})
    return {case_id: float(t["input_seconds"]) for case_id, t in tails.items()}


def cmd_plan(args: argparse.Namespace) -> int:
    from qualify_api.evals.extend_own_video_bench import (
        BENCH_TICKET,
        CASES,
        PROMPT_VERSION,
        PROPOSED_MAX_USD,
        SEEDANCE_MODEL,
        extend_prompt,
        plan_items,
        plan_totals,
    )

    run = Path(args.run) if args.run else None
    items = plan_items(CASES, _pricing(), _seconds(run))
    print(f"{BENCH_TICKET} · {SEEDANCE_MODEL} · {PROMPT_VERSION} · tabla v10")
    for case, item in zip(CASES, items, strict=True):
        print(f"- {case.id} ({'con rostro' if case.face else 'sin personas'}): {case.what}")
        print(f"  prompt: {extend_prompt(case)}")
        print(f"  cotización US${item.quote_usd} · reserva (10 %) US${item.reserved_usd}")
    totals = plan_totals(items)
    print(
        f"Total: {totals['tasks']} tareas · US${totals['quote_usd']} · reserva "
        f"US${totals['reserved_usd']} · tope propuesto US${PROPOSED_MAX_USD}"
    )
    return 0


def cmd_preparar(args: argparse.Namespace) -> int:
    from qualify_creative.video.cut import cut_window

    from qualify_api.creative.part_extend import EXTEND_OWN_SOURCE_MAX_S, EXTEND_SOURCE_MIN_S
    from qualify_api.evals.extend_own_video_bench import CASE_IDS

    material = _material(args.material)
    run = _run_dir(args, create=True)
    tails = _read_json(run / TAILS_FILE, {})
    for case_id in CASE_IDS:
        entry = material.get(case_id)
        if not entry or entry["file"] is None:
            print(f"- {case_id}: sin video en el material, queda fuera")
            continue
        from qualify_creative.video._source import open_video, probe

        with open_video(entry["file"]) as (container, stream):
            end = probe(container, stream).end_s or 0.0
        start = max(0.0, end - EXTEND_OWN_SOURCE_MAX_S)
        out = run / f"cola-{case_id}.mp4"
        cut = cut_window(
            entry["file"],
            start,
            end,
            out=out,
            toward="previous",
            min_seconds=int(EXTEND_SOURCE_MIN_S),
            max_seconds=int(EXTEND_OWN_SOURCE_MAX_S),
        )
        tails[case_id] = {"file": str(out), "input_seconds": round(cut.duration_sec, 3)}
        print(f"- {case_id}: {out} ({cut.duration_sec:.2f} s, {cut.width}x{cut.height})")
    _write_json(run / TAILS_FILE, tails)
    print(f"Sube cada cola a un enlace público https y escríbelo en el material. Corrida: {run}")
    return 0


def _add_spend(run: Path, label: str, cost: Decimal, kind: str) -> None:
    data = _read_json(run / SPEND_FILE, {"spent_usd": "0"})
    data["spent_usd"] = str(Decimal(str(data.get("spent_usd", "0"))) + cost)
    data.setdefault("calls", []).append(
        {"label": label, "kind": kind, "cost_usd": str(cost), "at": datetime.now(UTC).isoformat()}
    )
    _write_json(run / SPEND_FILE, data)


def cmd_extender(args: argparse.Namespace) -> int:
    from qualify_creative.adapters.byteplus_ark import (
        DRAFT_RESOLUTION,
        ArkTaskFailed,
        SeedanceVideoAdapter,
        video_cost_usd,
    )
    from qualify_creative.enums import GenerationTask
    from qualify_creative.providers import GenerationRequest, RenderedPrompt

    from qualify_api.evals.avatar_scene_bench import refusal_kind
    from qualify_api.evals.byteplus_eval_guard import (
        EvalKeyError,
        off_hours_refusal,
        resolve_eval_key,
    )
    from qualify_api.evals.extend_own_video_bench import (
        CASES,
        PROMPT_VERSION,
        SEEDANCE_MODEL,
        SpendRefused,
        extend_params,
        fits_ceiling,
        mode_refusal,
        plan_items,
        validate_max_usd,
    )

    refusal = mode_refusal(paid=args.i_have_spend_authorization, dry_run=args.dry_run)
    if refusal:
        raise SystemExit(refusal)
    run = _run_dir(args, create=False)
    material = _material(args.material)
    tails = _read_json(run / TAILS_FILE, {})
    cases = [c for c in CASES if c.id in tails and (material.get(c.id) or {}).get("url")]
    if not cases:
        raise SystemExit("ningún caso tiene su cola cortada (preparar) y su enlace público")
    pricing = _pricing()
    items = plan_items(cases, pricing, _seconds(run))
    adapter = SeedanceVideoAdapter(model=SEEDANCE_MODEL)
    requests = {}
    for case in cases:
        url = str(material[case.id]["url"])
        if not url.startswith("https://"):
            raise SystemExit(f"{case.id}: el enlace tiene que ser https público")
        params = extend_params(
            case, video_url=url, input_seconds=float(tails[case.id]["input_seconds"])
        )
        request = GenerationRequest(
            task=GenerationTask.SCENE_VIDEO,
            rendered_prompt=RenderedPrompt("", "", ""),
            params=params,
        )
        adapter.spec(params)  # the adapter's own checks, nothing sent
        requests[case.id] = request
    for item in items:
        print(f"- {item.label}: US${item.quote_usd} (reserva US${item.reserved_usd})")
    if args.dry_run:
        print("Simulación: no se mandó nada.")
        return 0
    try:
        max_usd = validate_max_usd(args.max_usd)
    except SpendRefused as exc:
        raise SystemExit(str(exc)) from None
    daytime = off_hours_refusal(allow_daytime=args.allow_daytime)
    if daytime:
        raise SystemExit(daytime)
    spent = Decimal(str(_read_json(run / SPEND_FILE, {}).get("spent_usd", "0")))
    results = _read_json(run / RESULTS_FILE, {})
    pending = [i for i in items if results.get(i.label, {}).get("status") not in (SENT, PAID)]
    over = fits_ceiling(pending, max_usd=max_usd, spent_before=spent)
    if over:
        raise SystemExit(over)
    try:
        key = resolve_eval_key()
    except EvalKeyError as exc:
        raise SystemExit(str(exc)) from None
    print(key.describe())
    (run / "videos").mkdir(exist_ok=True)
    for item in pending:
        case = next(c for c in cases if c.id == item.label)
        row: dict[str, Any] = {
            "case": case.id,
            "face": case.face,
            "provider": "byteplus-modelark",
            "model": SEEDANCE_MODEL,
            "prompt_version": PROMPT_VERSION,
            "pricing_version": pricing.version,
            "input_seconds": tails[case.id]["input_seconds"],
            "quote_usd": str(item.quote_usd),
            "status": SENT,
            "sent_at": datetime.now(UTC).isoformat(),
        }
        results[case.id] = row
        _write_json(run / RESULTS_FILE, results)  # on disk BEFORE it is sent
        _add_spend(run, case.id, item.reserved_usd, "reserva")
        try:
            result = adapter.generate(requests[case.id], api_key=key.value)
        except ArkTaskFailed as exc:  # ended failed/expired: not billed
            row.update(status=RELEASED, error=str(exc)[:600], refusal=refusal_kind(str(exc)))
            _add_spend(run, case.id, -item.reserved_usd, "liberado")
        except Exception as exc:  # an API error or still going: stays sent, counted
            row["error"] = f"{type(exc).__name__}: {exc}"[:600]
        else:
            tokens = int(result.usage.output_tokens or 0)
            cost = (
                video_cost_usd(pricing, result.model_id, DRAFT_RESOLUTION, tokens, video_input=True)
                if tokens
                else item.reserved_usd
            )
            payload = result.payload if isinstance(result.payload, dict) else {}
            row.update(
                status=PAID,
                task_id=payload.get("task_id"),
                billed_tokens=tokens,
                cost_usd=str(cost),
                media_url=result.media_url,
            )
            _add_spend(run, case.id, cost - item.reserved_usd, "ajuste")
            if result.media_url:
                target = run / "videos" / f"{case.id}.mp4"
                try:
                    with urllib.request.urlopen(str(result.media_url), timeout=120) as response:  # noqa: S310
                        target.write_bytes(response.read())
                    row["video"] = f"videos/{target.name}"
                except Exception as exc:  # noqa: BLE001 — the link lasts 24 h: say it
                    row["download_error"] = f"{type(exc).__name__}: {exc}"[:300]
        _write_json(run / RESULTS_FILE, results)
        print(f"  {case.id}: {row['status']} {row.get('cost_usd', '')} {row.get('error', '')}")
    print(f"Gasto total: US${_read_json(run / SPEND_FILE, {}).get('spent_usd')} · {run}")
    return 0


def cmd_planilla(args: argparse.Namespace) -> int:
    run = _run_dir(args, create=False)
    results = _read_json(run / RESULTS_FILE, {})
    for judge in JUDGES:
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=SHEET)
        writer.writeheader()
        for case_id, row in results.items():
            writer.writerow(
                {
                    "caso": case_id,
                    "rostro": "si" if row.get("face") else "no",
                    "acepto": "si" if row.get("status") == PAID else "no",
                    "error": row.get("refusal") or row.get("error") or "",
                    "segundos_entrada": row.get("input_seconds", ""),
                    "costo_usd": row.get("cost_usd", ""),
                    "video": row.get("video", ""),
                }
            )
        (run / f"juicio-{judge}.csv").write_text(buffer.getvalue(), encoding="utf-8")
    print(f"Planillas en {run}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "preparar", "extender", "planilla"):
        p = sub.add_parser(name)
        p.add_argument("--run")
        p.add_argument("--out", default=str(DEFAULT_OUT))
        p.add_argument("--material")
        p.add_argument("--env-file")
        if name == "extender":
            p.add_argument("--dry-run", action="store_true")
            p.add_argument("--i-have-spend-authorization", action="store_true")
            p.add_argument("--max-usd", default="0")
            p.add_argument("--allow-daytime", action="store_true")
    args = parser.parse_args(argv)
    _load_env(args.env_file)
    handler = {
        "plan": cmd_plan,
        "preparar": cmd_preparar,
        "extender": cmd_extender,
        "planilla": cmd_planilla,
    }[args.command]
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())

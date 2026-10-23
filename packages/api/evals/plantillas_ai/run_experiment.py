"""Seedream 5.0 pro: color transfer to an object and texture on a logo (m-24849234).

Builds the matrix of `cases.json` (blocks color, texture, flat), quotes every request
from pricing table v6 BEFORE anything is sent, and prints the table and totals. A paid
run SPENDS REAL MONEY and starts only with `--i-have-spend-authorization` — the founder
authorizes each paid run; it is never run in CI. The ceiling (`--max-usd`, at most
USD 10) is checked before every request, the adapter's retries included.

    uv run --no-sync python packages/api/evals/plantillas_ai/run_experiment.py --dry-run
    uv run --no-sync python packages/api/evals/plantillas_ai/run_experiment.py --dry-run --limit 2
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from qualify_api.evals import spend_control as sc

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[3]
IMAGES_DIR = HERE / "imagenes"
EPILOG = """exit codes:
  0  done (or a dry run with nothing sent)
  2  bad arguments, invalid matrix, missing images, no authorization, no key or a
     worst case above the ceiling: nothing sent
  3  a missing price in the pricing table: nothing sent
  4  a dry run saw a network attempt (blocked)
  5  the ceiling stopped the run, or the ledger raised an alert (overage, money held)
  6  no paid item succeeded (every one failed or was skipped)
"""


def _load_env(path: str | None) -> None:
    if not path or not Path(path).exists():
        return
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() and not name.strip().startswith("#"):
            os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


def _usd(value: str) -> Decimal:
    from qualify_api.evals.spend_control import validate_ceiling

    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise argparse.ArgumentTypeError(f"not an amount: {value!r}") from None
    try:
        return validate_ceiling(amount)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def build_parser() -> argparse.ArgumentParser:
    from qualify_api.evals.spend_control import DEFAULT_MAX_USD, SEEDREAM_PRO
    from qualify_api.evals.template_transfer import BLOCKS

    parser = argparse.ArgumentParser(
        description=(__doc__ or "").splitlines()[0],
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="quote and print; no request of any kind"
    )
    parser.add_argument("--limit", type=int, help="first N cases of each block")
    parser.add_argument(
        "--block", action="append", choices=BLOCKS, help="repeatable; default: every block"
    )
    parser.add_argument(
        "--skip-fixtures",
        action="store_true",
        help="leave out the fixture: true cases and references (repo files)",
    )
    parser.add_argument(
        "--configs", default=SEEDREAM_PRO, help="comma-separated model ids (always explicit)"
    )
    parser.add_argument("--size", default="1K", help="1K, 1.5K, 2K or WxH")
    parser.add_argument(
        "--max-usd",
        type=_usd,
        default=DEFAULT_MAX_USD,
        help="spending ceiling for the run, at most 10",
    )
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--results-dir", type=Path, default=HERE / "results")
    parser.add_argument(
        "--i-have-spend-authorization",
        action="store_true",
        help="required for a paid run: the founder authorized this run's spend",
    )
    return parser


def _print_table(full: Sequence[Any], planned: Sequence[Any]) -> None:
    """Every item of the chosen blocks: its origin (fixture / real) and whether the
    current flags include it; the cost columns only for the included ones."""
    by_item: dict[str, list[Any]] = {}
    for call in planned:
        by_item.setdefault(call.item.id, []).append(call)
    header = (
        f"{'bloque':<8} {'caso':<22} {'referencia':<26} {'origen':<7} {'incluido':<8} "
        f"{'modelo':<30} {'tramo':<5} {'refs':>4} {'estimado':>9} {'maximo':>9}"
    )
    print(header)
    print("-" * len(header))
    for item in full:
        origin = "fixture" if item.fixture else "real"
        lead = f"{item.block:<8} {item.case_id:<22} {item.reference_id or '-':<26} {origin:<7}"
        calls = by_item.get(item.id)
        if not calls:
            print(f"{lead} {'no':<8} {'-':<30} {'-':<5} {len(item.images):>4} {'-':>9} {'-':>9}")
            continue
        for call in calls:
            q = call.quote
            print(
                f"{lead} {'sí':<8} {call.model_id:<30} {(q.tier if q else '-'):<5} "
                f"{len(item.images):>4} {call.cost_usd:>9.4f} "
                f"{(q.max_usd if q else Decimal(0)):>9.4f}"
            )
        if item.fixture:  # the repository files this row reads, after the allowlist
            print(f"{'':<8} rutas: {', '.join(_fixture_paths(item))}")


def _fixture_paths(item: Any) -> list[str]:
    root = REPO_ROOT.resolve()
    images = (*item.images, *((item.mask,) if item.mask else ()))
    return [image.resolve(IMAGES_DIR, REPO_ROOT).relative_to(root).as_posix() for image in images]


def _models(args: argparse.Namespace) -> list[str]:
    return [m.strip() for m in args.configs.split(",") if m.strip()]


def _duplicate_models(models: Sequence[str]) -> list[str]:
    return sorted({m for m in models if models.count(m) > 1})


def _print_totals(
    full: Sequence[Any], planned: Sequence[Any], ceiling: Decimal
) -> tuple[Decimal, Decimal]:
    from qualify_api.evals.template_transfer import BLOCKS

    included = {c.item.id for c in planned}
    excluded = [i for i in full if i.id not in included]
    print(
        f"\nIncluidos {len(included)} ítems, excluidos {len(excluded)} "
        f"({sum(1 for i in excluded if i.fixture)} fixture, "
        f"{sum(1 for i in excluded if not i.fixture)} reales)"
    )
    expected = worst = Decimal(0)
    for block in BLOCKS:
        calls = [c for c in planned if c.item.block == block]
        if not calls:
            continue
        exp = sum((c.cost_usd for c in calls), Decimal(0))
        mx = sum((c.quote.max_usd if c.quote else Decimal(0) for c in calls), Decimal(0))
        expected, worst = expected + exp, worst + mx
        print(f"  {block:<8} {len(calls):>3} llamadas   estimado USD {exp:.4f}   maximo {mx:.4f}")
    paid = sum(1 for c in planned if c.quote)
    print(
        f"  {'total':<8} {len(planned):>3} llamadas ({paid} pagadas)   estimado USD "
        f"{expected:.4f}   maximo {worst:.4f}   tope USD {ceiling}"
    )
    return expected, worst


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    from qualify_creative.pricing import JsonPricingTable

    from qualify_api.evals import template_transfer as tt

    if args.dry_run:
        with sc.network_guard() as stats:
            code = _plan_and_report(args, tt, JsonPricingTable)
        print(f"\nSolicitudes de red: {stats['blocked']} (simulacro: ninguna llamada pagada)")
        return code if stats["blocked"] == 0 else 4
    return _paid_run(args, tt, JsonPricingTable)


def _plan(args: argparse.Namespace, tt: Any, table: Any) -> tuple[list[Any], list[Path], Any]:
    cases = tt.load_cases(HERE / "cases.json")
    items = tt.build_matrix(
        cases, blocks=args.block or tt.BLOCKS, limit=args.limit, skip_fixtures=args.skip_fixtures
    )
    models = _models(args)
    # layer decomposition stays out: the adapter cannot send it yet (README)
    planned = tt.plan_calls(items, table(tt.PRICING_VERSION), model_ids=models, size=args.size)
    return planned, tt.missing_files(items, IMAGES_DIR, REPO_ROOT), cases


def _plan_or_exit_code(args: argparse.Namespace, tt: Any, table: Any) -> Any:
    """The plan, or the exit code of why there is none: 3 = a missing price, 2 = an
    invalid matrix or a repeated `--configs` model (checked before any planning). Either
    way nothing has been sent."""
    duplicates = _duplicate_models(_models(args))
    if duplicates:
        print(
            f"--configs repite el modelo {', '.join(duplicates)}: cada modelo va una sola vez. "
            "No se envía nada."
        )
        return 2
    try:
        return _plan(args, tt, table)
    except sc.MissingPriceError as exc:
        print(f"Sin precio en la tabla {tt.PRICING_VERSION}: {exc}. No se envía nada.")
        return 3
    except (tt.CasesError, ValueError) as exc:
        print(f"Matriz inválida: {exc}")
        return 2


def _plan_and_report(args: argparse.Namespace, tt: Any, table: Any) -> int:
    plan = _plan_or_exit_code(args, tt, table)
    if isinstance(plan, int):
        return plan
    planned, missing, cases = plan
    full = tt.build_matrix(cases, blocks=args.block or tt.BLOCKS)
    print(
        f"Tabla de precios {tt.PRICING_VERSION} · tamaño {args.size} · prompts "
        f"{tt.PROMPT_VERSION} · fixtures {'excluidos' if args.skip_fixtures else 'incluidos'}\n"
    )
    _print_table(full, planned)
    _, worst = _print_totals(full, planned, args.max_usd)
    if worst > args.max_usd:
        print(
            f"\nAviso: el máximo (USD {worst:.4f}) pasa el tope de USD {args.max_usd}. "
            "Con estas opciones la corrida pagada se negará a empezar (código 2): reduce "
            "el alcance (--limit, --block, --skip-fixtures, --size) o ajusta --max-usd "
            "(máximo 10)."
        )
    _report_missing(missing)
    return 0


def _report_missing(missing: Sequence[Path]) -> None:
    if not missing:
        print("\nTodas las imágenes de entrada están en disco.")
        return
    print(f"\nFaltan {len(missing)} imágenes de entrada (colócalas en imagenes/):")
    for path in missing:
        try:
            shown = path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            shown = str(path)
        print(f"  - {shown}")


def _paid_run(args: argparse.Namespace, tt: Any, table: Any) -> int:
    """The paid path: wired, not exercised in m-24849234 PR 1. Exit codes: see `EPILOG`."""
    if not args.i_have_spend_authorization:
        print(
            "Una corrida pagada necesita --i-have-spend-authorization: el fundador autoriza "
            "cada gasto. Usa --dry-run para ver la matriz y su costo.",
            file=sys.stderr,
        )
        return 2
    plan = _plan_or_exit_code(args, tt, table)
    if isinstance(plan, int):
        return plan
    planned, missing, _ = plan
    if missing:
        _report_missing(missing)
        return 2
    worst = sum((c.quote.max_usd for c in planned if c.quote), Decimal(0))
    if worst > args.max_usd:
        print(f"El máximo de la corrida (USD {worst:.4f}) pasa el tope de USD {args.max_usd}.")
        return 2
    _load_env(args.env_file)
    key = os.environ.get("QUALIFY_BYTEPLUS_ARK_API_KEY", "").strip()
    if not key:
        print("QUALIFY_BYTEPLUS_ARK_API_KEY is not set", file=sys.stderr)
        return 2
    report = run_paid(planned, tt, ledger=sc.SpendLedger(args.max_usd), api_key=key, args=args)
    return exit_code(report)


def exit_code(report: Mapping[str, Any]) -> int:
    """6 when no paid item succeeded; 5 when the ceiling stopped the run or the ledger
    raised an alert; 0 otherwise."""
    from qualify_api.evals.template_transfer import FLAT_PROVIDER

    paid = [r for r in report["items"].values() if r.get("provider") != FLAT_PROVIDER]
    if paid and not any(r.get("estado") == "hecho" for r in paid):
        return 6
    if report["stopped"] or report["totales"]["alerta"]:
        return 5
    return 0


def _output(out_dir: Path, name: str) -> Path:
    """`out_dir / name`, refusing anything that would land outside `out_dir`."""
    path = (out_dir / name).resolve()
    if not path.is_relative_to(out_dir.resolve()):
        raise ValueError(f"output name {name!r} escapes {out_dir}")
    return path


def output_name(call: Any) -> str:
    """The item's file name (without extension). `~` is outside the ids' alphabet
    (`[A-Za-z0-9._-]`), so two different items never share a name; the model id is
    reduced to that alphabet."""
    item = call.item
    model = re.sub(r"[^A-Za-z0-9._-]", "_", call.model_id)
    return "~".join((item.block, item.case_id, item.reference_id or "", model))


def _bases(results_dir: Path) -> list[tuple[Path, str]]:
    return [(REPO_ROOT, "<repo>"), (IMAGES_DIR, "<imagenes>"), (results_dir, "<results>")]


def _display(path: Path, results_dir: Path) -> str:
    """A path as the report shows it: relative to the repository, or labelled by its base
    folder — never the machine's absolute path."""
    resolved = Path(path).resolve()
    for base, label in _bases(results_dir):
        root = Path(base).resolve()
        if resolved.is_relative_to(root):
            rel = resolved.relative_to(root).as_posix()
            return rel if label == "<repo>" else f"{label}/{rel}"
    return resolved.name


def _scrub(text: str | None, results_dir: Path) -> str | None:
    """`text` with every absolute base path (in any spelling an error message uses)
    replaced by its label."""
    if text is None:
        return None
    forms: list[tuple[str, str]] = []
    for base, label in _bases(results_dir):
        for root in {Path(base), Path(base).resolve()}:
            for form in (str(root), root.as_posix(), str(root).replace("\\", "\\\\")):
                forms.append((form, label))
    for form, label in sorted(forms, key=lambda f: -len(f[0])):
        text = text.replace(form, label)
    return text


def _now() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def _claim_stamp(results_dir: Path) -> tuple[str, Path, Path]:
    """A stamp no earlier run has used: its image folder is created here (never reused)
    and its results file does not exist yet."""
    salidas = IMAGES_DIR / "salidas"
    salidas.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    base = _now()
    for n in range(1000):
        stamp = base if n == 0 else f"{base}-{n}"
        out_dir, results = salidas / stamp, results_dir / f"{stamp}.json"
        if results.exists():
            continue
        try:
            out_dir.mkdir()
        except FileExistsError:
            continue
        return stamp, out_dir, results
    raise RuntimeError(f"no free run stamp for {base}")


_MONEY_FIELDS = (
    "estimado_usd",
    "reservado_usd",
    "gastado_usd",
    "exceso_sobre_reserva_usd",
    "exceso_sobre_tope_usd",
    "retenido_usd",
)


def _omitted(call: Any, tt: Any) -> dict[str, Any]:
    """The row of an item the run never attempted: the same keys as every other row
    (provenance, block, every money field at 0, `exceso`), estado «omitido»."""
    return {
        **tt.provenance(call),
        "block": call.item.block,
        **{name: "0" for name in _MONEY_FIELDS},
        "estado": "omitido",
        "exceso": False,
    }


def _money(ledger: Any) -> dict[str, Decimal]:
    return {
        "reservado_usd": ledger.reserved_usd,
        "gastado_usd": ledger.spent_usd,
        "exceso_sobre_reserva_usd": ledger.overage_usd,
        "exceso_sobre_tope_usd": ledger.over_ceiling_usd,
        "retenido_usd": ledger.held_usd,
    }


def _after_generation(
    item: Any, paths: Sequence[Path], result: bytes, out_dir: Path, name: str, reader: Any
) -> dict[str, Any]:
    """The offline checks of a generated image, added to its record (only on the paid
    path, after the vendor answered — never in a dry run). Color: the metrics and the
    recomposed image (`<name>~recompuesto.png`); texture: the legibility, «pendiente»
    without a reader (the reader backed by Claude's vision arrives in PR 3). A failed
    check is recorded as `metricas_error` and never loses the generated image."""
    from qualify_api.evals import image_metrics as im

    fields: dict[str, Any] = {}
    try:
        if item.block == "color":
            mask = item.mask.resolve(IMAGES_DIR, REPO_ROOT).read_bytes() if item.mask else None
            metrics = im.color_transfer_metrics(
                paths[0].read_bytes(), result, paths[1].read_bytes(), mask
            )
            fields["metricas"] = metrics.as_record()
            if metrics.recomposed_png is not None:
                _output(out_dir, f"{name}~recompuesto.png").write_bytes(metrics.recomposed_png)
        elif item.block == "texture":
            fields["legibilidad"] = im.legibility_record(reader, result, item.expected_text)
    except Exception as exc:  # the image is already saved: keep it, record why
        fields["metricas_error"] = f"{type(exc).__name__}: {exc}"[:300]
    return fields


def _run_item(
    call: Any,
    tt: Any,
    *,
    ledger: Any,
    inner: Any,
    out_dir: Path,
    base_url: str,
    api_key: str,
    size: str,
    reader: Any = None,
) -> dict[str, Any]:
    """One planned item. A failure is recorded on the item, never raised — except
    `CeilingExceededError`, which stops the run."""
    from qualify_creative.adapters.byteplus_ark import SeedreamImageAdapter

    item = call.item
    name = output_name(call)
    record: dict[str, Any] = {**tt.provenance(call), "block": item.block}
    before = _money(ledger)
    try:
        paths = [image.resolve(IMAGES_DIR, REPO_ROOT) for image in item.images]
        if call.quote is None:  # the flat finish: offline, free, with its checks
            from qualify_api.evals.image_metrics import flat_texture_fill

            flat = flat_texture_fill(paths[0].read_bytes(), paths[1].read_bytes())
            _output(out_dir, f"{name}.png").write_bytes(flat.png)
            record["metricas"] = flat.as_record()
        else:
            target = _output(out_dir, f"{name}.jpg")
            transport = sc.LedgerTransport(inner, ledger, call.quote, label=item.id)
            adapter = SeedreamImageAdapter(
                model=call.model_id, base_url=base_url, transport=transport
            )
            images = [sc.reference_data_url(p.read_bytes()) for p in paths]
            result = adapter.generate(
                tt.build_request(item, model_id=call.model_id, size=size, images=images),
                api_key=api_key,
            )
            generated = result.payload["images"][0]
            target.write_bytes(generated)
            record["model_revision"] = result.model_revision
            record.update(_after_generation(item, paths, generated, out_dir, name, reader))
        record["estado"] = "hecho"
    except sc.CeilingExceededError as exc:
        record["estado"] = "rechazado por el tope"
        record["error"] = str(exc)[:300]
    except Exception as exc:  # one failed item never stops the others
        record["estado"] = "error"
        record["error"] = f"{type(exc).__name__}: {exc}"[:300]
    after = _money(ledger)
    record["estimado_usd"] = str(call.cost_usd)
    for field_name, value in after.items():
        record[field_name] = str(value - before[field_name])
    record["exceso"] = after["exceso_sobre_reserva_usd"] > before["exceso_sobre_reserva_usd"]
    if record["exceso"]:
        print(
            f"AVISO: {item.id}@{call.model_id} gastó USD {record['gastado_usd']}, "
            f"USD {record['exceso_sobre_reserva_usd']} más de lo reservado "
            f"(exceso sobre el tope de la corrida: USD {after['exceso_sobre_tope_usd']})."
        )
    return record


def run_paid(
    planned: Sequence[Any],
    tt: Any,
    *,
    ledger: Any,
    api_key: str,
    args: argparse.Namespace,
    inner_transport: Any = None,
    reader: Any = None,
) -> dict[str, Any]:
    """Run `planned` in order and ALWAYS write `results/<stamp>.json`, whatever happens
    (the spend record is never lost). Every planned item ends in the report: done,
    failed, refused by the ceiling, or «omitido». Money is reported per item and in
    total without clamping. One inner HTTP transport serves the whole run and is closed
    once at the end. `reader` (a `LegibilityReader`) reads the texture items back; None
    records their legibility as «pendiente»."""
    import httpx
    from qualify_creative.adapters.byteplus_ark import BASE_URL

    stamp, out_dir, results_path = _claim_stamp(args.results_dir)
    base_url = os.environ.get("QUALIFY_BYTEPLUS_ARK_BASE_URL", "").strip() or BASE_URL
    items: dict[str, Any] = {}
    stopped: str | None = None
    unexpected: str | None = None
    inner = inner_transport if inner_transport is not None else httpx.HTTPTransport()
    report: dict[str, Any] = {}
    try:
        for call in planned:
            key = f"{call.item.id}@{call.model_id}"
            if stopped and call.quote is not None:  # free items never touch the ledger
                items[key] = _omitted(call, tt)
                continue
            record = _run_item(
                call,
                tt,
                ledger=ledger,
                inner=inner,
                out_dir=out_dir,
                base_url=base_url,
                api_key=api_key,
                size=args.size,
                reader=reader,
            )
            items[key] = record
            if record["estado"] == "rechazado por el tope":
                stopped = record["error"]
    except BaseException as exc:
        unexpected = f"{type(exc).__name__}: {exc}"[:300]
        raise
    finally:
        if inner_transport is None:
            inner.close()
        for call in planned:  # anything the loop never reached
            items.setdefault(f"{call.item.id}@{call.model_id}", _omitted(call, tt))
        for record in items.values():  # error texts may carry machine paths
            for text_field in ("error", "metricas_error"):
                if record.get(text_field):
                    record[text_field] = _scrub(record[text_field], args.results_dir)
        stopped = _scrub(stopped, args.results_dir)
        unexpected = _scrub(unexpected, args.results_dir)
        money = _money(ledger)
        totals: dict[str, Any] = {
            "estimado_usd": str(sum((c.cost_usd for c in planned), Decimal(0))),
            **{name: str(value) for name, value in money.items()},
        }
        totals["alerta"] = bool(
            money["retenido_usd"]
            or money["exceso_sobre_reserva_usd"]
            or money["exceso_sobre_tope_usd"]
            or unexpected
        )
        if money["retenido_usd"]:
            print(f"AVISO: quedan USD {money['retenido_usd']} retenidos sin cerrar al terminar.")
        report.update(
            {
                "stamp": stamp,
                "pricing_version": tt.PRICING_VERSION,
                "prompt_version": tt.PROMPT_VERSION,
                "size": args.size,
                "ceiling_usd": str(ledger.ceiling_usd),
                "spent_usd": str(ledger.spent_usd),
                "reservations": ledger.reservations,
                "ledger": ledger.snapshot(),
                "totales": totals,
                "stopped": stopped,
                "error_inesperado": unexpected,
                "results_path": _display(results_path, args.results_dir),
                "salidas": _display(out_dir, args.results_dir),
                "items": items,
            }
        )
        results_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nGuardado en {_display(results_path, args.results_dir)}")
    return report


if __name__ == "__main__":
    sys.exit(main())

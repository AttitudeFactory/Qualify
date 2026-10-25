"""Seedream 5.0 pro: color transfer to an object and texture on a logo (m-24849234).

Builds the matrix of `cases.json` (blocks color, texture, flat), quotes every request
from pricing table v6 BEFORE anything is sent, and prints the table and totals. A paid
run SPENDS REAL MONEY and starts only with `--i-have-spend-authorization` — the founder
authorizes each paid run; it is never run in CI. The ceiling (`--max-usd`, at most
USD 10) is checked before every request, the adapter's retries included.

    uv run --no-sync python packages/api/evals/plantillas_ai/run_experiment.py --dry-run
    uv run --no-sync python packages/api/evals/plantillas_ai/run_experiment.py --dry-run --limit 2
    uv run --no-sync python packages/api/evals/plantillas_ai/run_experiment.py --check-readiness
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import ROUND_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from qualify_api.evals import spend_control as sc
from qualify_api.evals.byteplus_eval_guard import EVAL_KEY_ENV, EvalKeyError, resolve_eval_key

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[3]
IMAGES_DIR = HERE / "imagenes"
CASES_FILE = HERE / "cases.json"
RUNNER = "uv run --no-sync python packages/api/evals/plantillas_ai/run_experiment.py"
#: The wall clock every latency is read from (tests replace it with a fake).
_clock = time.perf_counter
LITE_MODEL = "seedream-5-0-lite-260128"
ENV_NAMES = (EVAL_KEY_ENV, "QUALIFY_BYTEPLUS_ARK_API_KEY", "QUALIFY_ANTHROPIC_API_KEY")
EPILOG = """exit codes:
  0  done (or a dry run or a readiness check with nothing sent)
  2  bad arguments, invalid or missing matrix file, missing images, no
     authorization, no key or a worst case above the ceiling: nothing sent
  3  a missing price in the pricing table (also in --check-readiness): nothing sent
  4  a dry run saw a network attempt (blocked)
  5  the ceiling stopped the run, or the ledger raised an alert (overage, money held)
  6  no paid item succeeded (every one failed or was skipped)
"""


def _env_pairs(path: str | None) -> dict[str, str]:
    """`NAME=value` pairs of an env file, values stripped of spaces and quotes (so
    `NAME=""` is an empty value). The one parser `_load_env` and `_env_names` share."""
    pairs: dict[str, str] = {}
    if not path or not Path(path).is_file():
        return pairs
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        name = name.strip()
        if sep and name and not name.startswith("#"):
            pairs[name] = value.strip().strip('"').strip("'")
    return pairs


def _load_env(path: str | None) -> None:
    for name, value in _env_pairs(path).items():
        os.environ.setdefault(name, value)


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


def _max_reads(value: str) -> int:
    from qualify_api.evals.legibility_claude import HARD_MAX_READS

    try:
        reads = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a whole number: {value!r}") from None
    if not 1 <= reads <= HARD_MAX_READS:
        raise argparse.ArgumentTypeError(f"--max-reads must be within 1..{HARD_MAX_READS}")
    return reads


def _reader_usd(value: str) -> Decimal:
    from qualify_api.evals.legibility_claude import HARD_MAX_USD

    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise argparse.ArgumentTypeError(f"not an amount: {value!r}") from None
    if not (amount.is_finite() and Decimal(0) < amount <= HARD_MAX_USD):
        raise argparse.ArgumentTypeError(
            f"--max-reader-usd must be above 0 and at most {HARD_MAX_USD}"
        )
    return amount


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
    parser.add_argument(
        "--prompts",
        choices=("v1", "v2"),
        default="v1",
        help="prompt set: v1 (default, comparable with earlier runs) or v2",
    )
    parser.add_argument(
        "--texture-finish",
        choices=("plano", "volumen"),
        default="plano",
        help="texture prompt finish; volumen exists only with --prompts v2",
    )
    parser.add_argument(
        "--cases", type=Path, default=CASES_FILE, help="the matrix file (default cases.json)"
    )
    parser.add_argument(
        "--check-readiness",
        action="store_true",
        help="report prices, flags, key names and missing inputs; no request of any kind",
    )
    parser.add_argument(
        "--reader",
        choices=("none", "claude"),
        default="none",
        help="legibility reader of the texture items (paid run only); none: «pendiente»",
    )
    parser.add_argument(
        "--max-reads", type=_max_reads, default=50, help="reader's cap on reads, at most 50"
    )
    parser.add_argument(
        "--max-reader-usd",
        type=_reader_usd,
        default=Decimal("0.50"),
        help="reader's own spending cap, at most 0.50 (apart from --max-usd)",
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
    if args.prompts == "v1" and args.texture_finish != "plano":
        parser.error("--texture-finish volumen needs --prompts v2")

    from qualify_creative.pricing import JsonPricingTable

    from qualify_api.evals import template_transfer as tt

    if args.check_readiness:
        with sc.network_guard() as stats:
            code = check_readiness(args, tt, JsonPricingTable)
        print(f"\nSolicitudes de red: {stats['blocked']} (comprobación: ninguna llamada)")
        return code if stats["blocked"] == 0 else 4
    if args.dry_run:
        with sc.network_guard() as stats:
            code = _plan_and_report(args, tt, JsonPricingTable)
        print(f"\nSolicitudes de red: {stats['blocked']} (simulacro: ninguna llamada pagada)")
        return code if stats["blocked"] == 0 else 4
    return _paid_run(args, tt, JsonPricingTable)


def _plan(
    args: argparse.Namespace, tt: Any, table: Any
) -> tuple[list[Any], dict[str, list[Path]], Any]:
    cases = tt.load_cases(args.cases)
    items = tt.build_matrix(
        cases, blocks=args.block or tt.BLOCKS, limit=args.limit, skip_fixtures=args.skip_fixtures
    )
    models = _models(args)
    # layer decomposition stays out: the adapter cannot send it yet (README)
    planned = tt.plan_calls(items, table(tt.PRICING_VERSION), model_ids=models, size=args.size)
    return planned, tt.missing_by_role(items, IMAGES_DIR, REPO_ROOT), cases


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
    except (tt.CasesError, ValueError, OSError) as exc:
        print(f"Matriz inválida: {exc}")
        return 2


def _plan_and_report(args: argparse.Namespace, tt: Any, table: Any) -> int:
    plan = _plan_or_exit_code(args, tt, table)
    if isinstance(plan, int):
        return plan
    planned, missing, cases = plan
    full = tt.build_matrix(cases, blocks=args.block or tt.BLOCKS)
    choice = prompt_choice(args, tt)
    print(
        f"Tabla de precios {tt.PRICING_VERSION} · tamaño {args.size} · prompts "
        f"{choice.prompt_version} (textura {choice.finish}) · fixtures "
        f"{'excluidos' if args.skip_fixtures else 'incluidos'}\n"
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


def _report_missing(missing: Mapping[str, Sequence[Path]]) -> None:
    """The missing inputs grouped by what they are, so whoever supplies them knows
    exactly which photo goes where."""
    total = sum(len(paths) for paths in missing.values())
    if not total:
        print("\nTodas las imágenes de entrada están en disco.")
        return
    print(f"\nFaltan {total} imágenes de entrada (colócalas en imagenes/):")
    for role, paths in missing.items():
        print(f"  {role} ({len(paths)}):")
        for path in paths:
            try:
                shown = path.relative_to(REPO_ROOT).as_posix()
            except ValueError:
                shown = str(path)
            print(f"    - {shown}")


def _paid_run(args: argparse.Namespace, tt: Any, table: Any) -> int:
    """The paid path. Exit codes: see `EPILOG`. Langfuse stays off for this eval
    (founder, 2026-10-23): tracing is switched off once, here, whatever the reader."""
    from qualify_shared import observability

    observability.configure(None)
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
    try:
        eval_key = resolve_eval_key()
    except EvalKeyError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(eval_key.describe())
    key = eval_key.value
    reader = None
    if args.reader == "claude":  # only here: past the authorization gate and every check
        reader = _build_reader(args)
        if reader is None:
            return 2
    report = run_paid(
        planned,
        tt,
        ledger=sc.SpendLedger(args.max_usd),
        api_key=key,
        args=args,
        reader=reader,
    )
    return exit_code(report)


def _build_reader(args: argparse.Namespace) -> Any:
    """The Claude legibility reader under its own cap (`--max-reads`, `--max-reader-usd`),
    or None when `QUALIFY_ANTHROPIC_API_KEY` is missing. Tracing is already off
    (`_paid_run`)."""
    from qualify_api.claude_tools import API_KEY_ENV
    from qualify_api.evals.legibility_claude import ClaudeLegibilityReader, ReadBudget

    anthropic_key = os.environ.get(API_KEY_ENV, "").strip()
    if not anthropic_key:
        print(f"{API_KEY_ENV} is not set: --reader claude needs it", file=sys.stderr)
        return None
    budget = ReadBudget(max_reads=args.max_reads, max_usd=args.max_reader_usd)
    return ClaudeLegibilityReader(anthropic_key, budget=budget)


def _reader_block(reader: Any) -> dict[str, Any]:
    """The report's `lector`: «ninguno» only without a reader; a reader without its own
    `report()` is still named."""
    if reader is None:
        return {"tipo": "ninguno"}
    if hasattr(reader, "report"):
        return dict(reader.report())
    return {"tipo": type(reader).__name__}


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


def prompt_choice(args: argparse.Namespace, tt: Any) -> Any:
    """The run's `PromptChoice` (v1 and the flat finish unless the flags say otherwise)."""
    return tt.PromptChoice(getattr(args, "prompts", "v1"), getattr(args, "texture_finish", "plano"))


def _omitted(call: Any, tt: Any, choice: Any = None) -> dict[str, Any]:
    """The row of an item the run never attempted: the same keys as every other row
    (provenance, block, every money field at 0, `exceso`), estado «omitido»."""
    return {
        **tt.provenance(call, choice or tt.DEFAULT_PROMPTS),
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
            fields["legibilidad"] = im.legibility_record(
                reader, result, item.expected_text, clock=_clock
            )
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
    choice: Any = None,
) -> dict[str, Any]:
    """One planned item. A failure is recorded on the item, never raised — except
    `CeilingExceededError`, which stops the run. `latencia_s` is the wall-clock time
    from the item's start (inputs read, palette and request built) to the vendor's answer
    (the adapter's own retries included) or to the end of the flat finish — or, when the
    item fails before or during the call, to the failure. Every attempted item has it;
    the offline checks after the answer are not counted."""
    from qualify_creative.adapters.byteplus_ark import SeedreamImageAdapter

    choice = choice or tt.DEFAULT_PROMPTS
    item = call.item
    name = output_name(call)
    record: dict[str, Any] = {**tt.provenance(call, choice), "block": item.block}
    before = _money(ledger)
    start = _clock()

    def stop() -> None:
        if "latencia_s" not in record:
            record["latencia_s"] = round(_clock() - start, 3)

    try:
        paths = [image.resolve(IMAGES_DIR, REPO_ROOT) for image in item.images]
        if call.quote is None:  # the flat finish: offline, free, with its checks
            from qualify_api.evals.image_metrics import flat_texture_fill

            logo, texture = paths[0].read_bytes(), paths[1].read_bytes()
            try:
                flat = flat_texture_fill(logo, texture)
            finally:
                stop()
            _output(out_dir, f"{name}.png").write_bytes(flat.png)
            record["metricas"] = flat.as_record()
        else:
            target = _output(out_dir, f"{name}.jpg")
            transport = sc.LedgerTransport(inner, ledger, call.quote, label=item.id)
            adapter = SeedreamImageAdapter(
                model=call.model_id, base_url=base_url, transport=transport
            )
            raw = [p.read_bytes() for p in paths]
            images = [sc.reference_data_url(data) for data in raw]
            palette = ()
            if choice.version == "v2" and item.block == "color":
                from qualify_api.evals.image_metrics import dominant_hex

                palette = tuple(dominant_hex(raw[1]))
                record["paleta_hex"] = list(palette)
            request = tt.build_request(
                item,
                model_id=call.model_id,
                size=size,
                images=images,
                choice=choice,
                palette_hex=palette,
            )
            record["prompt_sha256"] = tt.prompt_sha256(str(request.params["prompt"]))
            try:
                result = adapter.generate(request, api_key=api_key)
            finally:
                stop()
            generated = result.payload["images"][0]
            target.write_bytes(generated)
            record["model_revision"] = result.model_revision
            record.update(_after_generation(item, paths, generated, out_dir, name, reader))
        record["estado"] = "hecho"
    except sc.CeilingExceededError as exc:
        stop()
        record["estado"] = "rechazado por el tope"
        record["error"] = str(exc)[:300]
    except Exception as exc:  # one failed item never stops the others
        stop()
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


def mean_latencies(items: Mapping[str, Mapping[str, Any]]) -> dict[str, float]:
    """Mean `latencia_s` per block and over every timed item («total»); items without a
    number (omitted ones, or a null) are skipped, and a block with none is left out."""
    by_block: dict[str, list[float]] = {}
    for record in items.values():
        value = record.get("latencia_s")
        if isinstance(value, int | float) and not isinstance(value, bool):
            by_block.setdefault(str(record.get("block")), []).append(float(value))
    means = {block: round(sum(v) / len(v), 3) for block, v in by_block.items()}
    every = [value for values in by_block.values() for value in values]
    if every:
        means["total"] = round(sum(every) / len(every), 3)
    return means


def _env_names(env_file: str | None) -> dict[str, str]:
    """Where each key NAME is set: «entorno», «.env» or «ausente» (an empty value, as
    `NAME=""`, is absent). Values are never printed."""
    pairs = _env_pairs(env_file)
    out: dict[str, str] = {}
    for name in ENV_NAMES:
        if os.environ.get(name, "").strip():
            out[name] = "entorno"
        elif pairs.get(name, "").strip():
            out[name] = ".env"
        else:
            out[name] = "ausente"
    return out


def _probe_flags(model_id: str, size: str) -> str:
    flags = "" if model_id == sc.SEEDREAM_PRO else f" --configs {model_id}"
    return flags + ("" if size == "1K" else f" --size {size}")


def check_readiness(args: argparse.Namespace, tt: Any, table: Any) -> int:
    """What the paid run of THIS matrix and these models needs, checked without any
    request. It plans exactly like the dry run (`--configs`, `--size`, `--block`,
    `--limit`, `--skip-fixtures`, `--cases`): an invalid or missing matrix exits 2, a
    missing price 3. Then: the matrix totals, the price of one paid item and the PNG
    probe (command and quote) per model, the ceiling and reader caps, the key names
    (never the values) and the missing inputs by role. Otherwise 0: nothing is sent."""
    from qualify_api.evals.legibility_claude import HARD_MAX_READS, HARD_MAX_USD, worst_case_usd

    plan = _plan_or_exit_code(args, tt, table)
    if isinstance(plan, int):
        return plan
    planned, missing, _ = plan
    pricing = table(tt.PRICING_VERSION)
    paid = [c for c in planned if c.quote]
    worst = sum((c.quote.max_usd for c in paid), Decimal(0))
    print(f"Preparación para la corrida pagada (tabla de precios {tt.PRICING_VERSION})\n")
    print(
        f"Matriz {Path(args.cases).name}: {len(planned)} ítems ({len(paid)} pagados) · "
        f"estimado USD {tt.total_usd(planned)} · máximo USD {worst} · tope USD {args.max_usd}"
    )
    print("\nPrecio de un ítem pagado (2 imágenes de entrada) y sonda PNG:")
    for model_id in _models(args):
        try:
            q = sc.quote(pricing, model_id=model_id, size=args.size, references=2)
        except sc.MissingPriceError as exc:
            print(f"Sin precio en la tabla {tt.PRICING_VERSION}: {exc}. No se envía nada.")
            return 3
        except ValueError as exc:
            print(f"Matriz inválida: {exc}")
            return 2
        cap = max(Decimal("0.05"), q.max_usd.quantize(Decimal("0.01"), rounding=ROUND_UP))
        print(
            f"  {model_id} a {args.size} (tramo {q.tier}): imagen USD {q.unit_usd} + "
            f"entradas USD {q.references_usd} = USD {q.total_usd}"
        )
        print(
            f"    {RUNNER} --block texture --limit 1 --max-usd {cap}"
            f"{_probe_flags(model_id, args.size)} --i-have-spend-authorization"
        )
    print(
        f"\nTope de gasto: --max-usd {args.max_usd} aceptado (máximo USD {sc.MAX_USD_CEILING} "
        "por corrida; se revisa antes de cada solicitud)."
    )
    worst_read = worst_case_usd("claude-sonnet-5").normalize()
    print(
        f"Lector: --reader {args.reader} · --max-reads {args.max_reads} (máximo "
        f"{HARD_MAX_READS}) · --max-reader-usd {args.max_reader_usd} (máximo USD "
        f"{HARD_MAX_USD}) · peor caso por lectura USD {worst_read}."
    )
    print("\nVariables de entorno (solo el nombre, nunca el valor):")
    for name, where in _env_names(args.env_file).items():
        print(f"  {name}: {where}")
    _report_missing(missing)
    photos = missing.get("objetos", [])
    print(f"\nFotos propias pendientes: {len(photos)}.")
    return 0


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

    choice = prompt_choice(args, tt)
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
                items[key] = _omitted(call, tt, choice)
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
                choice=choice,
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
            items.setdefault(f"{call.item.id}@{call.model_id}", _omitted(call, tt, choice))
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
        totals["latencia_media_s"] = mean_latencies(items)
        if money["retenido_usd"]:
            print(f"AVISO: quedan USD {money['retenido_usd']} retenidos sin cerrar al terminar.")
        report.update(
            {
                "stamp": stamp,
                "pricing_version": tt.PRICING_VERSION,
                "prompt_version": choice.prompt_version,
                "texture_finish": choice.finish,
                "size": args.size,
                "ceiling_usd": str(ledger.ceiling_usd),
                "spent_usd": str(ledger.spent_usd),
                "reservations": ledger.reservations,
                "ledger": ledger.snapshot(),
                "totales": totals,
                "stopped": stopped,
                "error_inesperado": unexpected,
                "lector": _reader_block(reader),
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

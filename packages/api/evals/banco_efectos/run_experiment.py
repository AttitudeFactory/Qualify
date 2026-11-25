"""EF-12: the paid bench of the «Con IA» effects asked of Seedance (m-25026587).

Every `seedance_prompt` entry of the effects library («an object in a zone of the
frame», EF-13) is asked of Seedance n times per model, on product photos, by the REAL
`MediaProducer.produce` and the REAL `SeedanceVideoAdapter`: a `reference` part of a video
by parts with the effect in `part.effects`, `QUALIFY_SEEDANCE_EFFECTS=on` in THIS process
only, so the prompt is the part's own prompt with `seedance_effect_line(entry, use,
subject=effect_subject(product))` at its end — the production fill, template, order and
provenance (`seedance_effect` block: `prompt_version`, `fill_version`, library, zone, line).

What differs from production, and only inside this process:
- D5's model gate (`media.measured_on_model`) answers yes for the bench's own model: the
  gate exists to wait for THIS bench; every other check of the producer runs as is.
- two atmospheric CONTROLS (smoke, steam; `qualify_api.evals.effects_bench.CONTROLS`) are
  added to the library the producer reads, so the ticket's «object vs atmosphere»
  question is answered with the same code path. They are never offered.

Subcommands (all outputs OUTSIDE the repo, `%TEMP%/m-25026587/<run>/` by default):

    drafts   the 480p drafts. Without `--i-have-spend-authorization` it only QUOTES: every
             request is compiled through the real producer and priced with the versioned
             table, nothing is sent. Paid: also `--cases` (founder-run businesses only) and
             the off-hours window; one task at a time (<= 3 allowed); hard ceiling
             `--max-usd` (default 30) over the WHOLE bench, drafts and finals together
             (`gasto.json` in the run folder); the whole plan is quoted with its margin
             before the first task and refused if it does not fit. Resumable: `--run`
             reuses a run folder and skips trials that already have their video.
    judge    the blind judging kit: the videos renamed v01…vNN in random order, an offline
             form (`juicio.html`, downloads `juicio-<nombre>.csv`) and a CSV template.
    score    reads one or two judgment CSVs: success per arm with its Wilson interval,
             Cohen's κ, object vs atmospheric, and the `measured` of each effect (D5).
    finals   the 1080p final of the best winning draft of each effect that passes D5 (at
             most `--max-finals`), from its draft task id as production does. Dry unless
             authorized; same ceiling and window.
    library  writes `effects_data/v6.json` (v5 is never edited) with `measured`,
             `offered` (only over D5) and each offered effect's `preview_asset` (its
             winning video, copied into `effects_assets/<id>/v1/preview.mp4`).

    # dry run: compiles and quotes every draft, sends nothing (no key needed)
    just eval-efectos drafts
    just eval-efectos drafts --cases <outside>/casos.json
    # paid (only with Deivid's written OK; 23:00-05:00 Bogotá)
    just eval-efectos drafts --env-file <checkout>/.env --cases <outside>/casos.json \\
        --i-have-spend-authorization --max-usd 30
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import os
import random
import shutil
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_UP, Decimal
from pathlib import Path
from typing import Any
from unittest import mock
from uuid import UUID, uuid4

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
TICKET = "m-25026587"
#: A fictitious business: the keys only need to be «this tenant's» (`owned_by`).
TENANT_ID = UUID("7e7e0000-0000-4000-8000-0000000000e1")
BRAND_ID = UUID("7e7e0000-0000-4000-8000-0000000000e2")
#: The Seedance model production asks today (`QUALIFY_SEEDANCE_MODEL`, 2.5 since 2026-10-23).
MODEL = "dreamina-seedance-2-5-260628"
#: D6: a bench of 5 s drafts.
SECONDS = 5
#: Billed tokens ran ~1 % over the formula (EF11-001, SD25-002): each task is reserved 10 %
#: over its quote, and the whole plan must fit with that margin before the first task.
RESERVE_MARGIN = Decimal("1.10")
DEFAULT_MAX_USD = Decimal("30")
HARD_CEILING_USD = Decimal("30")
SPEND_FILE = "gasto.json"
TRIALS_FILE = "pruebas.json"
RESULTS_FILE = "resultados.json"

#: Repo material for the dry run only (the generator's sample product photos).
SAMPLE_CASES: tuple[dict[str, Any], ...] = (
    {
        "id": "muestra-fresa",
        "product": "Dona glaseada de fresa",
        "photo": "packages/render/public/sample/photo-1.jpg",
        "description": "La dona en primer plano sobre la mesa; la cámara se acerca despacio.",
    },
    {
        "id": "muestra-mango",
        "product": "Dona glaseada de mango",
        "photo": "packages/render/public/sample/photo-2.jpg",
        "description": "La dona en primer plano sobre la mesa; la cámara se acerca despacio.",
    },
)
SAMPLE_KIT: dict[str, Any] = {
    "positioning": "Comida hecha cada día en el barrio",
    "audience": "Familias y jóvenes del barrio",
    "palette_rgb": ["#5A2826", "#F3C1C2", "#FDE0B4"],
    "font_heading": "Poppins",
    "font_body": "Inter",
}


class DryRun(Exception):
    """Raised instead of sending: the request was captured and quoted."""


def _load_env(path: str | None) -> None:
    if not path or not Path(path).is_file():
        return
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() and not name.strip().startswith("#"):
            os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


def _outside_repo(path: str | None) -> bool:
    return not path or not Path(path).resolve().is_relative_to(REPO)


def _write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


# -- spend across the whole bench ----------------------------------------------------------


def _spent_before(run: Path) -> Decimal:
    """What earlier commands of this run were billed (tokens × table; the reservation
    when ModelArk did not say)."""
    return Decimal(str(_read_json(run / SPEND_FILE, {}).get("billed_usd", "0")))


def _record_spend(run: Path, phase: str, meter: Any, calls: list[dict[str, Any]]) -> None:
    data = _read_json(run / SPEND_FILE, {"billed_usd": "0", "phases": []})
    billed = sum((Decimal(c["cost_usd"]) for c in calls if "cost_usd" in c), Decimal(0))
    data["billed_usd"] = str(Decimal(data["billed_usd"]) + billed)
    data["phases"].append(
        {
            "phase": phase,
            "at": datetime.now(UTC).isoformat(),
            "billed_usd": str(billed),
            "tasks": [c.get("task_id") for c in calls if c.get("task_id")],
            "meter": meter.as_document(),
        }
    )
    _write_json(run / SPEND_FILE, data)


def _ceiling(args: argparse.Namespace, run: Path) -> Decimal:
    """What this command may still spend: `--max-usd` (at most US$30) minus what earlier
    commands of the same run spent."""
    cap = min(Decimal(args.max_usd), HARD_CEILING_USD)
    return max(Decimal(0), cap - _spent_before(run))


# -- the producer, as production builds it -------------------------------------------------


def _kit(fields: dict[str, Any]) -> Any:
    from qualify_creative.schemas import BrandKit, ToneAxes

    return BrandKit(
        brand_id=BRAND_ID,
        tone_axes=ToneAxes(
            formal_casual=70, sober_enthusiastic=60, technical_plain=80, brief_elaborate=30
        ),
        **{**SAMPLE_KIT, **fields},
    )


def _load_cases(path: str | None) -> tuple[list[dict[str, Any]], dict[str, Any], Path]:
    """The repo sample cases, or a JSON file OUTSIDE the repo (`{"kit": {...}, "cases":
    [{"id", "product", "photo", "description", "business"}]}`, paths relative to it)."""
    if not path:
        return list(SAMPLE_CASES), {}, REPO
    file = Path(path).resolve()
    data = json.loads(file.read_text(encoding="utf-8"))
    return list(data["cases"]), dict(data.get("kit") or {}), file.parent


def _photo_key(case: dict[str, Any]) -> str:
    suffix = Path(case["photo"]).suffix.lower() or ".jpg"
    return f"uploads/{TENANT_ID}/{case['id']}-producto{suffix}"


def _brief(case: dict[str, Any], use: Any, *, audio: bool) -> Any:
    """The part's child Clip: a `reference` part with the product photo and the effect."""
    from qualify_creative.enums import BriefObjective, ContentFormat, ContentKind, ImageRoute
    from qualify_creative.schemas import ContentBrief, MediaInputs, PartRef

    from qualify_api.creative.media import PROMPT_COMPILER_VERSION

    part = PartRef(
        index=1,
        mode="reference",
        seconds=SECONDS,
        description=case["description"],
        effects=(use,),
    )
    return ContentBrief(
        brand_id=BRAND_ID,
        objective=BriefObjective.SALE,
        topic=case["product"],
        product_ref=case["product"],
        image_route=ImageRoute.TEMPLATE_ONLY,
        kind=ContentKind.CLIP,
        format=ContentFormat.REELS_9_16,
        media=MediaInputs(
            part=part,
            duration_seconds=part.generation_seconds,
            clip_reference_mode="motion",
            clip_image_keys=(_photo_key(case),),
            clip_image_roles=("product",),
            clip_audio=audio,
            prompt_compiler_version=PROMPT_COMPILER_VERSION,
        ),
    )


class MemoryStore:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = dict(files)

    def read(self, key: str) -> bytes:
        if key not in self.files:
            raise FileNotFoundError(key)
        return self.files[key]

    def write(self, key: str, data: bytes) -> None:
        self.files[key] = data


@dataclass(frozen=True)
class _DryKey:
    """The dry run sends nothing: no key is read."""

    value: str = "dry-run"
    fingerprint: str = "sin-llave"

    def describe(self) -> str:
        return "Prueba en seco: no se lee ninguna llave y no se envía nada."


class EvalKeys:
    """The eval key for every BytePlus call (`resolve_eval_key`); never printed."""

    def __init__(self, key: Any) -> None:
        self._key = key

    def resolve(self, *, tenant_id: UUID, brand_id: UUID, provider: str) -> Any:
        from qualify_creative.enums import PaidBy
        from qualify_creative.providers import ResolvedKey

        return ResolvedKey(
            api_key=self._key.value, paid_by=PaidBy.PLATFORM, fingerprint=self._key.fingerprint
        )


class GuardedSeedance:
    """The real adapter behind the run's `DollarMeter`: every attempt (a producer retry
    too) is quoted with the adapter's own formula and the versioned table, and charged to
    the meter with a 10 % margin BEFORE it is sent — a charge that does not fit is
    `BudgetExhausted` and nothing is sent. The meter keeps the charge (a failed task may
    have been billed too); what ModelArk billed (its tokens × the table) goes into the
    call and into `gasto.json`. Dry: captures, quotes and raises `DryRun`."""

    name = "seedance"

    def __init__(self, inner: Any, meter: Any, pricing: Any, *, dry: bool) -> None:
        self.inner = inner
        self.supports = inner.supports
        self.meter = meter
        self.pricing = pricing
        self.dry = dry
        self.label = ""
        self.calls: list[dict[str, Any]] = []
        self.refused: str | None = None

    def estimate_cost_usd(self, request: Any, pricing: Any, **kwargs: Any) -> Any:
        return self.inner.estimate_cost_usd(request, pricing, **kwargs)

    def generate(self, request: Any, *, api_key: str) -> Any:
        from qualify_creative.adapters.byteplus_ark import video_cost_usd

        from qualify_api.claude_tools import BudgetExhausted

        quote = self.inner.estimate_cost_usd(request, self.pricing)
        call: dict[str, Any] = {"label": self.label, "quote_usd": str(quote), "request": request}
        self.calls.append(call)
        if self.dry:
            raise DryRun(self.label)
        reserve = (quote * RESERVE_MARGIN).quantize(Decimal("0.0001"), ROUND_UP)
        try:
            self.meter.charge(reserve, what=f"seedance:{self.label}")
        except BudgetExhausted as exc:
            self.refused = call["refused"] = str(exc)
            raise
        call["charged_usd"] = str(reserve)
        started = datetime.now(UTC)
        try:
            result = self.inner.generate(request, api_key=api_key)
        except Exception as exc:
            # a failed task may still have been billed: the reservation counts as spent
            call["error"] = f"{type(exc).__name__}: {exc}"[:400]
            call["cost_usd"] = str(reserve)
            call["cost_kind"] = "reservado (falló)"
            raise
        payload = dict(result.payload) if isinstance(result.payload, dict) else {}
        tokens = result.usage.output_tokens
        resolution = str(payload.get("resolution") or request.params.get("resolution"))
        actual = (
            video_cost_usd(self.pricing, result.model_id, resolution, int(tokens))
            if tokens
            else None
        )
        call.update(
            task_id=payload.get("task_id"),
            model_id=result.model_id,
            resolution=resolution,
            seed=payload.get("seed"),
            created_at=payload.get("created_at"),
            billed_tokens=tokens,
            seconds_taken=round((datetime.now(UTC) - started).total_seconds(), 1),
            cost_usd=str(actual if actual is not None else reserve),
            cost_kind="facturado (tokens)" if actual is not None else "reservado",
            media_url=result.media_url,
        )
        return result


@contextmanager
def _bench_process(library: Any, model: str) -> Iterator[None]:
    """Inside THIS process only: the Seedance effects switch on, the library with the
    controls, and D5's model gate open for the bench's own model (see the module)."""
    from qualify_api.creative import media
    from qualify_api.creative.video_pipeline import seedance_effect

    def bench_gate(entry: Any, asked: str | None) -> bool:
        return asked == model

    previous = os.environ.get(seedance_effect.SEEDANCE_EFFECTS_SWITCH)
    os.environ[seedance_effect.SEEDANCE_EFFECTS_SWITCH] = "on"
    try:
        with (
            mock.patch.object(seedance_effect, "load_effects", lambda *a, **k: library),
            mock.patch.object(media, "measured_on_model", bench_gate),
        ):
            yield
    finally:
        if previous is None:
            os.environ.pop(seedance_effect.SEEDANCE_EFFECTS_SWITCH, None)
        else:
            os.environ[seedance_effect.SEEDANCE_EFFECTS_SWITCH] = previous


def _copy() -> Any:
    from qualify_creative.schemas import CopyPayload

    return CopyPayload(hook="Recién hecho", caption="-", cta="Pide el tuyo")


def _safe(label: str) -> str:
    return label.replace("/", "__")


# -- drafts --------------------------------------------------------------------------------


def _window_refusal(args: argparse.Namespace) -> str | None:
    from qualify_api.evals.byteplus_eval_guard import off_hours_refusal

    return off_hours_refusal(allow_daytime=args.allow_daytime)


def _resolve_key(paid: bool) -> Any:
    if not paid:
        return _DryKey()
    from qualify_api.evals.byteplus_eval_guard import resolve_eval_key

    return resolve_eval_key()


def _run_dir(args: argparse.Namespace) -> Path:
    if args.run:
        run = Path(args.run)
        if not run.is_dir():
            raise SystemExit(f"no existe la corrida {run}")
        return run
    run = Path(args.out) / datetime.now().strftime("%Y%m%d-%H%M%S")
    run.mkdir(parents=True, exist_ok=True)
    return run


def _drafts_pass(
    trials: list[Any],
    cases: dict[str, dict[str, Any]],
    base: Path,
    kit: Any,
    *,
    guarded: GuardedSeedance,
    router: Any,
    keys: Any,
    pricing: Any,
    meter: Any,
    model: str,
    audio: bool,
    run: Path | None,
    done: dict[str, Any],
) -> list[dict[str, Any]]:
    """One pass over `trials` through the real producer. Dry (`guarded.dry`): every
    request compiled and quoted. Paid: each video kept in `run` with its provenance,
    `pruebas.json` rewritten after each one (a dead run resumes where it stopped)."""
    from qualify_creative.effects import EFFECTS_LIBRARY_VERSION, SEEDANCE_EFFECT_FILL_VERSION
    from qualify_creative.enums import FailureReason
    from qualify_creative.router import BudgetContext

    from qualify_api.creative.composition import PRICING_VERSION
    from qualify_api.creative.media import MediaProducer

    rows: list[dict[str, Any]] = []
    for trial in trials:
        if trial.label in done and done[trial.label].get("video"):
            continue  # resumed: this one already has its video
        case = cases[trial.case_id]
        photo = (base / case["photo"]).read_bytes()
        store = MemoryStore({_photo_key(case): photo})
        producer = MediaProducer(
            store=store,
            router=router,
            credentials=keys,
            pricing=pricing,
            seedance_model=model,
            seedance_reference_model=model,
        )
        guarded.label = trial.label
        before = len(guarded.calls)
        outcome = producer.produce(
            tenant_id=TENANT_ID,
            draft_id=uuid4(),
            brief=_brief(case, trial.arm.use(), audio=audio),
            kit=kit,
            copy=_copy(),
            budget=BudgetContext(remaining_usd=meter.remaining_usd),
        )
        calls = guarded.calls[before:]
        row: dict[str, Any] = {
            "label": trial.label,
            "arm": trial.arm.id,
            "kind": trial.arm.kind,
            "compared_with": trial.arm.compared_with,
            "case": trial.case_id,
            "business": case.get("business", "muestra del repositorio"),
            "rep": trial.rep,
            "asked": trial.arm.asked(),
            "zone": trial.arm.zone(),
            # provenance (rule 6): provider, model, prompt versions, cost
            "provider": "byteplus-modelark",
            "model_requested": model,
            "effect_id": trial.arm.entry.id,
            "effect_version": trial.arm.entry.version,
            "prompt_version": trial.arm.entry.prompt_version,
            "fill_version": SEEDANCE_EFFECT_FILL_VERSION,
            "library_version": EFFECTS_LIBRARY_VERSION,
            "pricing_version": PRICING_VERSION,
            "photo_sha256": hashlib.sha256(photo).hexdigest(),
            "seconds": SECONDS,
            "audio": audio,
            "failure": outcome.failure,
            "detail": outcome.detail,
            "attempts": [],
        }
        for call in calls:
            params = dict(call["request"].params)
            prompt = str(params.get("prompt", ""))
            row["prompt"] = prompt
            row["attempts"].append(
                {
                    **{k: v for k, v in call.items() if k not in ("request", "media_url")},
                    "prompt_words": len(prompt.split()),
                    "params": {
                        k: v
                        for k, v in params.items()
                        if k not in {"prompt", "reference_images", "first_frame"}
                    },
                }
            )
        if outcome.media and run is not None:
            video = outcome.media[0]
            row["model_billed"] = (calls[-1].get("model_id") if calls else None) or model
            row["seedance_effect"] = video.params.get("seedance_effect")
            row["part_prompt_version"] = video.params.get("part_prompt_version")
            row["draft"] = video.params.get("draft")
            name = f"{_safe(trial.label)}.mp4"
            (run / "videos").mkdir(exist_ok=True)
            (run / "videos" / name).write_bytes(store.read(video.object_key))
            row["video"] = f"videos/{name}"
            (run / "prompts").mkdir(exist_ok=True)
            (run / "prompts" / f"{_safe(trial.label)}.txt").write_text(
                row.get("prompt", ""), encoding="utf-8"
            )
        rows.append(row)
        if run is not None:
            done[trial.label] = row
            _write_json(run / TRIALS_FILE, {"ticket": TICKET, "trials": done})
        status = (
            "ok"
            if outcome.media
            else ("compilado (seco)" if guarded.dry else f"falló: {outcome.detail}")
        )
        quotes = "".join(f" · cotizado USD {a['quote_usd']}" for a in row["attempts"])
        print(f"  {trial.label}: {status}{quotes}")
        stop = guarded.refused or (
            outcome.failure == FailureReason.BUDGET_EXCEEDED.value
            and f"{trial.label}: {outcome.detail}"
        )
        if stop:
            print(f"TOPE: {stop}", file=sys.stderr)
            break
    return rows


def cmd_drafts(args: argparse.Namespace) -> int:
    from qualify_creative.adapters.byteplus_ark import SeedanceVideoAdapter
    from qualify_creative.effects import EFFECTS_LIBRARY_VERSION, load_effects
    from qualify_creative.pricing import JsonPricingTable
    from qualify_creative.router import CreativeRouter

    from qualify_api.claude_tools import DollarMeter
    from qualify_api.creative.composition import PRICING_VERSION
    from qualify_api.evals.byteplus_eval_guard import EvalKeyError
    from qualify_api.evals.effects_bench import bench_arms, bench_library, plan_trials

    paid = args.i_have_spend_authorization
    if paid and not args.cases:
        print(
            "La corrida pagada necesita --cases (fotos aprobadas, fuera del repo).", file=sys.stderr
        )
        return 2
    if paid:
        refusal = _window_refusal(args)
        if refusal:
            print(refusal, file=sys.stderr)
            return 3
    try:
        key = _resolve_key(paid)
    except EvalKeyError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(key.describe())
    library = load_effects(EFFECTS_LIBRARY_VERSION)
    arms = bench_arms(library, controls=not args.no_controls, only=args.effect)
    if not arms:
        print("Ningún efecto coincide con --effect.", file=sys.stderr)
        return 2
    all_cases, kit_fields, base = _load_cases(args.cases)
    cases = {c["id"]: c for c in all_cases if not args.case or c["id"] in args.case}
    trials = plan_trials(arms, list(cases), args.reps)
    kit = _kit(kit_fields)
    pricing = JsonPricingTable(PRICING_VERSION)
    model = args.model

    # 1. always: the whole plan compiled through the producer and quoted, nothing sent
    quote_meter = DollarMeter(Decimal("1000000"))  # dry: nothing is charged
    dry_guard = GuardedSeedance(SeedanceVideoAdapter(model=model), quote_meter, pricing, dry=True)
    dry_keys = EvalKeys(_DryKey())
    with _bench_process(bench_library(library, arms), model):
        planned = _drafts_pass(
            trials,
            cases,
            base,
            kit,
            guarded=dry_guard,
            router=CreativeRouter({"seedance": dry_guard}, pricing, dry_keys),
            keys=dry_keys,
            pricing=pricing,
            meter=quote_meter,
            model=model,
            audio=args.audio,
            run=None,
            done={},
        )
    quotes = [Decimal(a["quote_usd"]) for r in planned for a in r["attempts"]]
    total = sum(quotes, Decimal(0))
    reserved = sum(
        ((q * RESERVE_MARGIN).quantize(Decimal("0.0001"), ROUND_UP) for q in quotes), Decimal(0)
    )
    not_compiled = [r["label"] for r in planned if not r["attempts"]]
    plan = {
        "ticket": TICKET,
        "model": model,
        "pricing_version": PRICING_VERSION,
        "library_version": EFFECTS_LIBRARY_VERSION,
        "seconds": SECONDS,
        "resolution": "480p (borrador)",
        "audio": args.audio,
        "arms": [{"id": a.id, "kind": a.kind, "asked": a.asked()} for a in arms],
        "cases": list(cases),
        "reps": args.reps,
        "calls": len(quotes),
        "quote_usd": str(total),
        "reserved_with_margin_usd": str(reserved),
        "not_compiled": not_compiled,
        "per_call_usd": sorted({str(q) for q in quotes}),
    }
    print(
        f"\nPlan: {len(trials)} borradores ({len(arms)} brazos × {len(cases)} casos × "
        f"{args.reps} tiradas) en {model}, tabla {PRICING_VERSION}."
        f"\nCotizado: USD {total} · con margen del 10 %: USD {reserved}."
    )
    if not_compiled:
        print(f"Sin compilar (revisar): {', '.join(not_compiled)}", file=sys.stderr)
    if not paid:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"cotizacion-{datetime.now():%Y%m%d-%H%M%S}.json"
        _write_json(path, {**plan, "requests": planned})
        print(f"Prueba en seco: nada enviado. Cotización en {path}")
        return 0 if not not_compiled else 1

    # 2. paid: the plan must fit the ceiling (with its margin) before the first task
    run = _run_dir(args)
    ceiling = _ceiling(args, run)
    done = _read_json(run / TRIALS_FILE, {}).get("trials", {})
    pending = [t for t in trials if not done.get(t.label, {}).get("video")]
    pending_reserved = reserved * Decimal(len(pending)) / Decimal(max(1, len(trials)))
    if pending_reserved > ceiling:
        print(
            f"El plan (USD {pending_reserved:.4f} con margen) no cabe en lo que queda del tope "
            f"(USD {ceiling}). Reduce --reps, --effect o --case.",
            file=sys.stderr,
        )
        return 4
    _write_json(run / "plan.json", {**plan, "started_at": datetime.now(UTC).isoformat()})
    meter = DollarMeter(ceiling)
    guarded = GuardedSeedance(SeedanceVideoAdapter(model=model), meter, pricing, dry=False)
    keys = EvalKeys(key)
    try:
        with _bench_process(bench_library(library, arms), model):
            _drafts_pass(
                pending,
                cases,
                base,
                kit,
                guarded=guarded,
                router=CreativeRouter({"seedance": guarded}, pricing, keys),
                keys=keys,
                pricing=pricing,
                meter=meter,
                model=model,
                audio=args.audio,
                run=run,
                done=done,
            )
    finally:
        _record_spend(run, "drafts", meter, guarded.calls)
    billed = sum((Decimal(c["cost_usd"]) for c in guarded.calls if "cost_usd" in c), Decimal(0))
    print(f"\nCobrado en esta fase: USD {billed} · corrida en {run}")
    return 0


# -- judging -------------------------------------------------------------------------------

_HTML = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<title>Banco de efectos — juicio a ciegas</title>
<style>
body{{font-family:system-ui,sans-serif;margin:24px;max-width:1100px}}
.v{{display:flex;gap:24px;border-top:1px solid #ccc;padding:16px 0}}
video{{width:270px;height:480px;background:#000}}
fieldset{{border:0;margin:0 0 10px;padding:0}} legend{{font-weight:600}}
label{{margin-right:14px}} textarea{{width:100%}}
</style></head><body>
<h1>Banco de efectos: juicio a ciegas</h1>
<p>Mira cada video completo, más de una vez si hace falta. No abras <code>clave.json</code>.</p>
<ol>
<li><b>Efecto visible:</b> sí, dudoso o no. Lo dudoso cuenta como no.</li>
<li><b>En la zona pedida:</b> sí o no. Si se pidió «toda la escena», déjalo vacío.</li>
<li><b>El producto no cambió:</b> forma, etiqueta, cantidad.</li>
<li><b>Sin letras ni logos</b> que nadie pidió.</li>
<li><b>Creíble para un anuncio:</b> de 1 (no) a 3 (sí).</li>
</ol>
<p>Tu nombre: <input id="who" placeholder="nombre"></p>
{items}
<p><button onclick="save()">Descargar mi juicio (CSV)</button></p>
<script>
const cols={columns};
function val(n){{
 const c=document.querySelector('input[name="'+n+'"]:checked');return c?c.value:'';}}
function q(s){{s=String(s);return /[",\\n]/.test(s)?'"'+s.replace(/"/g,'""')+'"':s;}}
function save(){{
 const who=(document.getElementById('who').value||'persona').trim().replace(/[^a-zA-Z0-9_-]/g,'_');
 const rows=[cols.join(',')];
 document.querySelectorAll('.v').forEach(d=>{{const v=d.dataset.video;
  rows.push([v,d.dataset.asked,val(v+'-visible'),val(v+'-en_zona'),val(v+'-producto_igual'),
   val(v+'-sin_letras'),val(v+'-creible'),d.querySelector('textarea').value].map(q).join(','));}});
 const a=document.createElement('a');
 a.href=URL.createObjectURL(new Blob([rows.join('\\n')],{{type:'text/csv'}}));
 a.download='juicio-'+who+'.csv';a.click();
}}
</script></body></html>
"""


def _radio(video: str, name: str, options: tuple[tuple[str, str], ...]) -> str:
    inputs = "".join(
        f'<label><input type="radio" name="{video}-{name}" value="{value}"> {text}</label>'
        for value, text in options
    )
    return inputs


def cmd_judge(args: argparse.Namespace) -> int:
    from qualify_api.evals.effects_bench import JUDGMENT_COLUMNS, judgment_template_rows

    run = Path(args.run)
    trials = _read_json(run / TRIALS_FILE, {}).get("trials", {})
    made = [row for row in trials.values() if row.get("video")]
    if not made:
        print("La corrida no tiene videos todavía.", file=sys.stderr)
        return 2
    folder = run / "juicio"
    if folder.exists():
        print(f"Ya existe {folder}: el juicio no se vuelve a barajar.", file=sys.stderr)
        return 2
    (folder / "videos").mkdir(parents=True)
    rng = random.Random(args.seed)
    rng.shuffle(made)
    key: dict[str, Any] = {}
    yes_no = (("si", "sí"), ("no", "no"))
    items: list[str] = []
    for at, row in enumerate(made, 1):
        blind = f"v{at:02d}"
        shutil.copyfile(run / row["video"], folder / "videos" / f"{blind}.mp4")
        key[blind] = {
            "label": row["label"],
            "arm": row["arm"],
            "kind": row["kind"],
            "compared_with": row.get("compared_with"),
            "case": row["case"],
            "video": row["video"],
            "asked": row["asked"],
        }
        asked = html.escape(row["asked"], quote=True)
        items.append(
            f'<div class="v" data-video="{blind}" data-asked="{asked}">'
            f'<video src="videos/{blind}.mp4" controls loop muted playsinline></video><div>'
            f"<h2>{blind}</h2><p>Se pidió: <b>{asked}</b></p>"
            f"<fieldset><legend>1. Efecto visible</legend>"
            f"{_radio(blind, 'visible', (('si', 'sí'), ('dudoso', 'dudoso'), ('no', 'no')))}"
            f"</fieldset><fieldset><legend>2. En la zona pedida</legend>"
            f"{_radio(blind, 'en_zona', yes_no)}</fieldset>"
            f"<fieldset><legend>3. El producto no cambió</legend>"
            f"{_radio(blind, 'producto_igual', yes_no)}</fieldset>"
            f"<fieldset><legend>4. Sin letras ni logos</legend>"
            f"{_radio(blind, 'sin_letras', yes_no)}</fieldset>"
            f"<fieldset><legend>5. Creíble para un anuncio</legend>"
            f"{_radio(blind, 'creible', (('1', '1'), ('2', '2'), ('3', '3')))}</fieldset>"
            f'<textarea rows="2" placeholder="nota (opcional)"></textarea></div></div>'
        )
    _write_json(folder / "clave.json", key)
    (folder / "juicio.html").write_text(
        _HTML.format(items="\n".join(items), columns=json.dumps(list(JUDGMENT_COLUMNS))),
        encoding="utf-8",
    )
    with (folder / "plantilla.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(JUDGMENT_COLUMNS))
        writer.writeheader()
        writer.writerows(
            judgment_template_rows([(blind, info["asked"]) for blind, info in key.items()])
        )
    print(
        f"{len(key)} videos a ciegas en {folder}.\nCada persona abre juicio.html (o llena una "
        "copia de plantilla.csv) y devuelve su juicio-<nombre>.csv. No abran clave.json."
    )
    return 0


# -- scores --------------------------------------------------------------------------------


def _measured_on(run: Path) -> date:
    started = _read_json(run / "plan.json", {}).get("started_at")
    return datetime.fromisoformat(started).date() if started else date.today()


def cmd_score(args: argparse.Namespace) -> int:
    from qualify_api.evals.effects_bench import (
        BENCH_VERSION,
        consensus,
        object_vs_atmospheric,
        read_judgment_csv,
        score_arms,
    )

    run = Path(args.run)
    key = _read_json(run / "juicio" / "clave.json", {})
    if not key:
        print("Primero: judge.", file=sys.stderr)
        return 2
    by_rater = {}
    for item in args.juicio:
        name, _, path = item.partition("=")
        by_rater[name] = read_judgment_csv(Path(path).read_text(encoding="utf-8-sig"), key)
    verdicts, agreement = consensus(by_rater)
    scores = score_arms(key, verdicts)
    trials = _read_json(run / TRIALS_FILE, {}).get("trials", {})
    models = {row.get("model_billed") for row in trials.values() if row.get("video")}
    if len(models) != 1:
        print(f"La corrida mezcla modelos ({models}): D5 mide uno a la vez.", file=sys.stderr)
        return 2
    model = str(models.pop())
    on = _measured_on(run)
    measured = {
        arm: score.measured(model=model, on=on).model_dump(mode="json")
        for arm, score in scores.items()
        if score.kind == "objeto" and score.n
    }
    results = {
        "ticket": TICKET,
        "bench_version": BENCH_VERSION,
        "model": model,
        "measured_on": on.isoformat(),
        "agreement": agreement,
        "arms": {arm: score.to_json() for arm, score in scores.items()},
        "object_vs_atmospheric": object_vs_atmospheric(scores),
        "measured": measured,
        "winners": {
            arm: [key[v]["label"] for v in score.winners]
            for arm, score in scores.items()
            if score.kind == "objeto" and score.passes()
        },
    }
    _write_json(run / RESULTS_FILE, results)
    print(f"Modelo {model} · κ = {agreement.get('kappa')} ({len(by_rater)} persona/s)")
    for arm, score in scores.items():
        data = score.to_json()
        print(
            f"  {arm:22} {data['successes']}/{data['n']} "
            f"[{data['wilson_low']:.2f}–{data['wilson_high']:.2f}]"
            f"{'  PASA D5' if data['passes_d5'] else ''}"
        )
    for row in results["object_vs_atmospheric"]:
        print(f"  {row['objeto']} vs {row['atmosferico']}: {row['verdict']}")
    print(f"Resultados en {run / RESULTS_FILE}")
    return 0


# -- finals --------------------------------------------------------------------------------


def cmd_finals(args: argparse.Namespace) -> int:
    import httpx
    from qualify_creative.adapters.byteplus_ark import SeedanceVideoAdapter
    from qualify_creative.enums import GenerationTask
    from qualify_creative.pricing import JsonPricingTable
    from qualify_creative.providers import GenerationRequest, RenderedPrompt

    from qualify_api.claude_tools import BudgetExhausted, DollarMeter
    from qualify_api.creative.composition import PRICING_VERSION
    from qualify_api.creative.media import SEEDANCE_RATIOS
    from qualify_api.evals.byteplus_eval_guard import EvalKeyError

    run = Path(args.run)
    results = _read_json(run / RESULTS_FILE, {})
    trials = _read_json(run / TRIALS_FILE, {}).get("trials", {})
    winners = list(results.get("winners", {}).items())[: args.max_finals]
    if not winners:
        print("Ningún efecto pasó D5: no hay finales que hacer.")
        return 0
    paid = args.i_have_spend_authorization
    if paid:
        refusal = _window_refusal(args)
        if refusal:
            print(refusal, file=sys.stderr)
            return 3
    try:
        key = _resolve_key(paid)
    except EvalKeyError as exc:
        print(exc, file=sys.stderr)
        return 2
    pricing = JsonPricingTable(PRICING_VERSION)
    meter = DollarMeter(_ceiling(args, run) if paid else Decimal("1000000"))
    guarded = GuardedSeedance(SeedanceVideoAdapter(model=args.model), meter, pricing, dry=not paid)
    finals = _read_json(run / "finales.json", {})
    from qualify_creative.enums import ContentFormat

    try:
        for arm, labels in winners:
            if finals.get(arm, {}).get("video"):
                continue
            row = trials[labels[0]]
            draft = row["attempts"][-1]
            request = GenerationRequest(
                task=GenerationTask.SCENE_VIDEO,
                rendered_prompt=RenderedPrompt("", "", ""),
                params={
                    "model": row["model_billed"],
                    "draft_task_id": str(draft["task_id"]),
                    "ratio": SEEDANCE_RATIOS[ContentFormat.REELS_9_16],
                    "duration_seconds": SECONDS,
                    "generate_audio": bool(row.get("audio")),
                    "video_input": False,
                },
            )
            guarded.label = f"final/{arm}"
            try:
                result = guarded.generate(request, api_key=key.value)
            except DryRun:
                print(f"  final/{arm}: cotizado USD {guarded.calls[-1]['quote_usd']} (seco)")
                continue
            except BudgetExhausted as exc:
                print(f"TOPE: {exc}", file=sys.stderr)
                break
            name = f"final__{arm}.mp4"
            (run / "finales").mkdir(exist_ok=True)
            data = httpx.get(str(result.media_url), timeout=120).content
            (run / "finales" / name).write_bytes(data)
            call = guarded.calls[-1]
            finals[arm] = {
                "from_trial": labels[0],
                "video": f"finales/{name}",
                **{k: v for k, v in call.items() if k not in ("request", "media_url")},
            }
            _write_json(run / "finales.json", finals)
            print(f"  final/{arm}: ok · USD {call['cost_usd']}")
    finally:
        if paid:
            _record_spend(run, "finals", meter, guarded.calls)
    if not paid:
        total = sum((Decimal(c["quote_usd"]) for c in guarded.calls), Decimal(0))
        print(f"Prueba en seco: {len(guarded.calls)} finales, USD {total}. Nada enviado.")
    return 0


# -- library v6 ----------------------------------------------------------------------------


def cmd_library(args: argparse.Namespace) -> int:
    from qualify_creative.effects import Measured, parse_library, preview_file

    from qualify_api.evals.effects_bench import library_v6, preview_asset_path

    creative = REPO / "packages" / "creative" / "src" / "qualify_creative"
    target = creative / "effects_data" / "v6.json"
    if target.exists():
        print(f"{target} ya existe: una biblioteca no se edita.", file=sys.stderr)
        return 2
    run = Path(args.run)
    results = _read_json(run / RESULTS_FILE, {})
    trials = _read_json(run / TRIALS_FILE, {}).get("trials", {})
    finals = _read_json(run / "finales.json", {})
    measured = {arm: Measured.model_validate(m) for arm, m in results.get("measured", {}).items()}
    base = json.loads((creative / "effects_data" / "v5.json").read_text(encoding="utf-8"))
    versions = {e["id"]: int(e["version"]) for e in base["entries"]}
    copied: list[Path] = []
    for arm, labels in results.get("winners", {}).items():
        if not measured.get(arm) or not measured[arm].passes:
            continue
        source = run / (finals.get(arm, {}).get("video") or trials[labels[0]]["video"])
        dest = preview_file(preview_asset_path(arm, versions[arm]))
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
        copied.append(dest)
    notes = (
        f"EF-12 / {TICKET} (ADR 50 D5/D6): the effects library v6. The SAME entries as v5, "
        f"at the same versions; every Seedance template the paid bench judged carries its "
        f"`measured` (model {results.get('model')}, {results.get('measured_on')}), and only "
        "the ones over D5 (>= 2/3 with n >= 4) are offered, each with its winning video as "
        "`preview_asset`. v1-v5 keep reading exactly as they were."
    )
    document = library_v6(base, measured, notes=notes)
    parse_library(document)  # refuses a preview that is not there
    target.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Escrita {target}; vistas previas: {[str(p) for p in copied] or 'ninguna'}")
    print("Falta (código de producción, otro cambio): EFFECTS_LIBRARY_VERSION = 'v6'.")
    return 0


# -- CLI -----------------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    out_default = str(Path(tempfile.gettempdir()) / TICKET)

    def common(p: argparse.ArgumentParser, *, spends: bool) -> None:
        p.add_argument("--env-file", default=".env")
        p.add_argument("--model", default=MODEL)
        p.add_argument("--out", default=out_default, help="outside the repo")
        if spends:
            p.add_argument("--i-have-spend-authorization", action="store_true")
            p.add_argument("--max-usd", type=Decimal, default=DEFAULT_MAX_USD)
            p.add_argument(
                "--allow-daytime",
                action="store_true",
                help="outside 23:00-05:00 Bogotá: only with Herwin's or Deivid's OK on record",
            )

    drafts = sub.add_parser("drafts", help="the 480p drafts (dry unless authorized)")
    common(drafts, spends=True)
    drafts.add_argument("--cases", help="JSON of cases outside the repo (approved photos)")
    drafts.add_argument("--case", action="append", help="only these case ids")
    drafts.add_argument("--effect", action="append", help="only these arms (effect or control)")
    drafts.add_argument("--no-controls", action="store_true")
    drafts.add_argument("--reps", type=int, default=2, help="tries per case and arm")
    drafts.add_argument(
        "--audio",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="ask Seedance for sound (off: avoids audio moderation refusals; same price)",
    )
    drafts.add_argument("--run", help="an earlier run folder to resume or extend")

    judge = sub.add_parser("judge", help="the blind judging kit")
    judge.add_argument("--run", required=True)
    judge.add_argument("--seed", type=int, default=25026587)

    score = sub.add_parser("score", help="read the judgments: success, Wilson, κ, D5")
    score.add_argument("--run", required=True)
    score.add_argument("--juicio", action="append", required=True, help="nombre=ruta.csv")

    finals = sub.add_parser("finals", help="1080p finals of the winners (dry unless authorized)")
    common(finals, spends=True)
    finals.add_argument("--run", required=True)
    finals.add_argument("--max-finals", type=int, default=3)

    library = sub.add_parser("library", help="write effects_data/v6.json from the results")
    library.add_argument("--run", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    _load_env(getattr(args, "env_file", None))
    for name in ("out", "cases", "run"):
        if not _outside_repo(getattr(args, name, None)):
            print(f"--{name} tiene que estar fuera del repositorio", file=sys.stderr)
            return 2
    if getattr(args, "max_usd", None) is not None and args.max_usd > HARD_CEILING_USD:
        print(f"--max-usd no puede pasar de USD {HARD_CEILING_USD} (D6).", file=sys.stderr)
        return 2
    command = {
        "drafts": cmd_drafts,
        "judge": cmd_judge,
        "score": cmd_score,
        "finals": cmd_finals,
        "library": cmd_library,
    }[args.command]
    return command(args)


if __name__ == "__main__":
    sys.exit(main())

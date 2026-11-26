"""Path A of the avatar-as-character (m-25112921): Seedance 2.5 makes the whole scene.

The bench's method, matrix, prompts and guards are in
`qualify_api.evals.avatar_scene_bench`; this file only drives the vendors.

Subcommands (all outputs OUTSIDE the repo, `%TEMP%/avatar-escena-seedance/` by default):

    plan      the whole plan, its prompts and its cost from the versioned pricing table.
              Never calls anything (the network is blocked while it runs).
    dibujar   Seedream 5.0 pro draws the characters and the drawn background (`--opciones`
              each, 1K, 9:16). Paid: images are not bound by the video window.
    escenas   Seedance 2.5, one omni-reference task per case (character + product +
              place, the line in double quotes), one task at a time. Paid: only
              23:00-05:00 Bogotá unless `--allow-daytime` (founder's OK).
    planilla  the judgment sheets (`juicio-deivid.csv`, `juicio-herwin.csv`) from the run's
              results, with the automatic columns filled; `--resumen <csv>` summarizes one.

`dibujar` and `escenas` need EXACTLY ONE of `--dry-run` (print the plan and the estimate,
call nothing) and `--i-have-spend-authorization` (Deivid writes the OK in the coordinating
session). Paid runs share ONE ceiling (`--max-usd`, at most US$10) over the whole run
folder (`gasto.json`): each phase is quoted whole, with a 10 % margin, before its first
call and refused if it does not fit; every call is reserved before it is sent.

`--material <file>.json` (outside the repo):

    {"producto": {"nombre": "super smash", "photo": "<path>"},
     "local": {"photo": "<path or null>"}}

A path is relative to the file or absolute, and must be outside the repository. A null
`local.photo` leaves the real-place arm out (listed, never run). Without `--material` the
dry run uses the repo's sample photo; a paid `escenas` refuses.

The chosen drawing of each character and of the drawn background is option 1 unless
`<run>/eleccion.json` says otherwise: `{"realista": 2, "animado": 1, "dibujado": 1}`.

    just eval-avatar-escena plan --material %TEMP%/avatar-escena-seedance/material.json
    just eval-avatar-escena dibujar --dry-run
    just eval-avatar-escena dibujar --env-file <checkout>/.env --i-have-spend-authorization \\
        --max-usd 8
    just eval-avatar-escena escenas --env-file <checkout>/.env --run <run folder> \\
        --material <...>/material.json --i-have-spend-authorization --max-usd 8
    just eval-avatar-escena planilla --run <run folder>
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import tempfile
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
DEFAULT_OUT = Path(tempfile.gettempdir()) / "avatar-escena-seedance" / "corridas"
SAMPLE_PRODUCT = REPO / "packages" / "render" / "public" / "sample" / "photo-1.jpg"
SPEND_FILE = "gasto.json"
DRAWINGS_FILE = "dibujos.json"
RESULTS_FILE = "resultados.json"
CHOICE_FILE = "eleccion.json"
#: A placeholder image for the dry run's adapter validation (never sent).
_DRY_IMAGE = "data:image/jpeg;base64,AAAA"


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


class MaterialError(ValueError):
    """A material file the bench refuses (inside the repo, a missing file)."""


def load_material(path: str | None) -> dict[str, Any]:
    """`{"product": Path, "product_name": str, "local": Path | None, "sample": bool}`."""
    if not path:
        return {
            "product": SAMPLE_PRODUCT,
            "product_name": "super smash",
            "local": None,
            "sample": True,
        }
    file = Path(path).resolve()
    data = json.loads(file.read_text(encoding="utf-8"))

    def resolve(raw: object, what: str) -> Path | None:
        if not raw:
            return None
        photo = (file.parent / str(raw)).resolve()
        if photo.is_relative_to(REPO):
            raise MaterialError(f"{what}: la foto tiene que estar fuera del repositorio")
        if not photo.is_file():
            raise MaterialError(f"{what}: no existe {photo}")
        return photo

    product = resolve((data.get("producto") or {}).get("photo"), "producto")
    if product is None:
        raise MaterialError("producto: falta la foto")
    return {
        "product": product,
        "product_name": str((data.get("producto") or {}).get("nombre") or "super smash"),
        "local": resolve((data.get("local") or {}).get("photo"), "local"),
        "sample": False,
    }


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
    if run.resolve().is_relative_to(REPO):
        raise SystemExit("la corrida va fuera del repositorio")
    return run


def _spent_before(run: Path | None) -> Decimal:
    if run is None:
        return Decimal(0)
    return Decimal(str(_read_json(run / SPEND_FILE, {}).get("spent_usd", "0")))


def _add_spend(
    run: Path, phase: str, label: str, cost_usd: Decimal | str, *, kind: str = "cobro"
) -> None:
    """Add one entry to the run's `gasto.json`: a call's reservation BEFORE it is sent
    («reserva»), then its adjustment once settled («ajuste», the difference) or released
    («liberado», minus the reservation). A phase cut at any point keeps every charge that
    may have gone through, and a resumed run never spends past the ceiling."""
    data = _read_json(run / SPEND_FILE, {"spent_usd": "0"})
    cost = Decimal(str(cost_usd))
    data["spent_usd"] = str(Decimal(str(data.get("spent_usd", "0"))) + cost)
    data.setdefault("calls", []).append(
        {
            "phase": phase,
            "label": label,
            "kind": kind,
            "cost_usd": str(cost),
            "at": datetime.now(UTC).isoformat(),
        }
    )
    _write_json(run / SPEND_FILE, data)


#: A row's state: sent and not settled yet (may bill), settled (billed), released.
SENT, PAID, RELEASED = "enviada", "pagada", "liberada"


def _already_paid(row: dict[str, Any]) -> bool:
    """A call that may have been billed (sent and not released, a task id, or a cost
    counted): never sent again."""
    return (
        row.get("status") in (SENT, PAID)
        or bool(row.get("task_id"))
        or Decimal(str(row.get("cost_usd") or "0")) > 0
    )


def _finished(row: dict[str, Any]) -> bool:
    """Nothing new to pay for this item: made, or a charge that may have gone through."""
    return bool(row.get("video") or row.get("file")) or _already_paid(row)


class _Charge:
    """One paid call, on disk from BEFORE it is sent: the row («enviada», cost = the
    reservation) is written first, then the reservation is added to `gasto.json`. A
    process killed during the call (Ctrl-C, a closed window, the minute of polling)
    leaves both behind, so the resumed run neither resends it nor forgets its cost.
    `settle` and `release` adjust `gasto.json` by the difference."""

    def __init__(
        self,
        *,
        run: Path,
        phase: str,
        rows: dict[str, Any],
        rows_file: Path,
        row: dict[str, Any],
        ledger: Any,
        amount: Decimal,
    ) -> None:
        self.run, self.phase, self.rows, self.rows_file = run, phase, rows, rows_file
        self.row, self.ledger, self.amount = row, ledger, amount
        self.label = str(row["label"])
        self.reservation = ledger.reserve(amount, label=self.label)  # may refuse: nothing sent
        row.update(status=SENT, cost_usd=str(amount), sent_at=datetime.now(UTC).isoformat())
        self.save()
        _add_spend(run, phase, self.label, amount, kind="reserva")

    def save(self) -> None:
        self.rows[self.label] = self.row
        _write_json(self.rows_file, self.rows)

    def created(self, task_id: str) -> None:
        """`VendorTaskObserver.created`: the vendor's task id, kept as soon as it exists so
        a killed run can recover the task by id instead of paying for it again."""
        self.row["task_id"] = task_id
        self.save()

    def polled(self, task_id: str, status: str) -> None:
        return None

    def settle(self, actual: Decimal | None = None) -> Decimal:
        cost = self.ledger.settle(self.reservation, actual)
        self.row.update(status=PAID, cost_usd=str(cost))
        self.save()
        if cost != self.amount:
            _add_spend(self.run, self.phase, self.label, cost - self.amount, kind="ajuste")
        return cost

    def release(self) -> None:
        self.ledger.release(self.reservation)
        self.row.update(status=RELEASED, cost_usd="0")
        self.save()
        _add_spend(self.run, self.phase, self.label, -self.amount, kind="liberado")


#: What a downloaded video may be served as (some storage answers octet-stream).
VIDEO_CONTENT_TYPES = ("video/", "application/octet-stream", "binary/octet-stream")


def _download_video(url: str, target: Path) -> str | None:
    """Copy the 24 h video to `target`. None when done, else why it was not saved: an
    error answer or a body that is not a video is never written as an `.mp4`."""
    import httpx

    try:
        response = httpx.get(url, timeout=120, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return f"descarga: {type(exc).__name__}: {exc}"[:400]
    kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if not kind.startswith(VIDEO_CONTENT_TYPES):
        return f"descarga: tipo de contenido «{kind or 'vacío'}», no es un video"
    if not response.content:
        return "descarga: respuesta vacía"
    target.write_bytes(response.content)
    return None


def _pricing() -> Any:
    from qualify_creative.pricing import JsonPricingTable

    from qualify_api.evals.avatar_scene_bench import PRICING_VERSION

    return JsonPricingTable(PRICING_VERSION)


def _cases(args: argparse.Namespace, material: dict[str, Any]) -> list[Any]:
    from qualify_api.evals.avatar_scene_bench import case_matrix

    return case_matrix(local_photo=material["local"] is not None, characters=args.personaje)


def _items(args: argparse.Namespace, material: dict[str, Any], pricing: Any) -> list[Any]:
    from qualify_api.evals.avatar_scene_bench import drawing_items, scene_items

    phases = {"plan": ("dibujar", "escenas"), "dibujar": ("dibujar",), "escenas": ("escenas",)}
    wanted = phases[args.command]
    items: list[Any] = []
    if "dibujar" in wanted:
        items += drawing_items(pricing, options=args.opciones, characters=args.personaje)
    if "escenas" in wanted:
        items += scene_items(_cases(args, material), pricing, args.resolucion)
    return items


def _validate_scene_requests(cases: list[Any], pricing: Any, resolution_mode: str) -> list[str]:
    """Every scene request through the REAL adapter's own checks and estimate, with
    placeholder images (nothing sent): a request the adapter would refuse shows up here.
    Returns one line per case: label, prompt words, adapter estimate."""
    from qualify_creative.adapters.byteplus_ark import SeedanceVideoAdapter, prompt_words
    from qualify_creative.enums import GenerationTask
    from qualify_creative.providers import GenerationRequest, RenderedPrompt

    from qualify_api.evals.avatar_scene_bench import SEEDANCE_MODEL, scene_params, scene_quote

    adapter = SeedanceVideoAdapter(model=SEEDANCE_MODEL)
    lines = []
    for case in cases:
        params = scene_params(
            case,
            character_url=_DRY_IMAGE,
            product_url=_DRY_IMAGE,
            background_url=_DRY_IMAGE,
            resolution_mode=resolution_mode,
        )
        request = GenerationRequest(
            task=GenerationTask.SCENE_VIDEO,
            rendered_prompt=RenderedPrompt("", "", ""),
            params=params,
        )
        estimate = adapter.estimate_cost_usd(request, pricing)
        mine = scene_quote(case, pricing, resolution_mode)
        if estimate != mine:
            raise AssertionError(f"{case.label}: adapter {estimate} != bench {mine}")
        spec = adapter.spec(params)
        lines.append(f"{case.label}: {prompt_words(spec.prompt)} palabras, US${estimate}")
    return lines


def _print_plan(args: argparse.Namespace, material: dict[str, Any], items: list[Any]) -> dict:
    from qualify_api.evals.avatar_scene_bench import (
        BACKGROUNDS,
        CHARACTERS,
        PROMPT_VERSION,
        SEEDANCE_MODEL,
        SEEDREAM_MODEL,
        background_image_prompt,
        plan_totals,
        scene_prompt,
    )

    pricing = _pricing()
    cases = _cases(args, material)
    print(f"Tabla de precios {pricing.version} · prompts {PROMPT_VERSION}")
    print(f"Producto: {material['product_name']} · foto {material['product']}")
    if material["sample"]:
        print("  (foto de muestra del repositorio: la corrida pagada necesita --material)")
    if material["local"] is None:
        print("Foto real del local: no hay. La rama «local» queda fuera del plan.")
    if args.command in ("plan", "dibujar"):
        print(f"\nDibujos ({SEEDREAM_MODEL}, {args.opciones} opciones cada uno):")
        for c in CHARACTERS:
            if not args.personaje or c.id in args.personaje:
                print(f"- personaje {c.id}: {c.prompt}")
        for b in BACKGROUNDS:
            if b.kind == "dibujado":
                print(f"- fondo {b.id}: {background_image_prompt(b)}")
    if args.command in ("plan", "escenas"):
        print(f"\nEscenas ({SEEDANCE_MODEL}, {args.resolucion}, con audio):")
        for case in cases:
            print(f"- {case.label} · {case.scene.seconds} s · «{case.scene.line}»")
        print(f"\nPrompt de ejemplo ({cases[0].label}):\n{scene_prompt(cases[0])}" if cases else "")
        print("\nRevisado por el adaptador real (sin enviar):")
        for line in _validate_scene_requests(cases, pricing, args.resolucion):
            print(f"  {line}")
    print("\nCosto estimado:")
    for item in items:
        print(f"  {item.phase:8} {item.label:32} US${item.quote_usd}")
    totals = plan_totals(items)
    print(
        f"  Dibujos US${totals['dibujar']['quote_usd']} · escenas "
        f"US${totals['escenas']['quote_usd']} · total US${totals['total_quote_usd']}"
        f" · con 10 % de margen US${totals['total_reserved_usd']}"
    )
    return {
        "pricing_version": pricing.version,
        "prompt_version": PROMPT_VERSION,
        "cases": [c.label for c in cases],
        "items": [
            {"phase": i.phase, "label": i.label, "quote_usd": str(i.quote_usd)} for i in items
        ],
        "totals": totals,
    }


def _dry(args: argparse.Namespace, material: dict[str, Any]) -> int:
    from qualify_api.evals.spend_control import network_guard

    with network_guard() as stats:
        items = _items(args, material, _pricing())
        plan = _print_plan(args, material, items)
    print(f"\nLlamadas de red bloqueadas durante la prueba en seco: {stats['blocked']}")
    out = Path(args.out)
    if out.resolve().is_relative_to(REPO):
        raise SystemExit("la cotización va fuera del repositorio")
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"cotizacion-{args.command}-{datetime.now():%Y%m%d-%H%M%S}.json"
    _write_json(path, {**plan, "command": args.command, "network_blocked": stats["blocked"]})
    print(f"Cotización: {path}")
    return 0


def _paid_gate(args: argparse.Namespace, run: Path, items: list[Any], *, video: bool) -> Any:
    """Everything a paid phase checks before its first call; returns the key or exits."""
    from qualify_api.evals.avatar_scene_bench import (
        SpendRefused,
        fits_ceiling,
        validate_max_usd,
    )
    from qualify_api.evals.byteplus_eval_guard import (
        EvalKeyError,
        off_hours_refusal,
        resolve_eval_key,
    )

    try:
        max_usd = validate_max_usd(args.max_usd)
    except SpendRefused as exc:
        raise SystemExit(str(exc)) from None
    if video:
        refusal = off_hours_refusal(allow_daytime=args.allow_daytime)
        if refusal:
            raise SystemExit(refusal)
    refusal = fits_ceiling(items, max_usd=max_usd, spent_before=_spent_before(run))
    if refusal:
        raise SystemExit(refusal)
    _load_env(args.env_file)
    try:
        key = resolve_eval_key()
    except EvalKeyError as exc:
        raise SystemExit(str(exc)) from None
    print(key.describe())
    return key, max_usd


def _ledger(max_usd: Decimal, run: Path) -> Any:
    from qualify_api.evals.spend_control import SpendLedger

    return SpendLedger(ceiling_usd=max_usd - _spent_before(run))


def cmd_dibujar(args: argparse.Namespace, material: dict[str, Any]) -> int:
    from qualify_creative.adapters.byteplus_ark import ArkAPIError, SeedreamImageAdapter
    from qualify_creative.enums import GenerationTask
    from qualify_creative.pricing import seedream_image_cost
    from qualify_creative.providers import GenerationRequest, RenderedPrompt

    from qualify_api.evals.avatar_scene_bench import (
        IMAGE_SIZE,
        PROMPT_VERSION,
        SEEDREAM_MODEL,
        background,
        background_image_prompt,
        character,
        character_image_prompt,
        image_params,
    )
    from qualify_api.evals.spend_control import CeilingExceededError

    pricing = _pricing()
    run = _run_dir(args, create=True)
    done = _read_json(run / DRAWINGS_FILE, {})
    for label, row in done.items():
        if row.get("status") == SENT:
            # Seedream answers in one call (no task id to recover): its reservation stays
            # counted and it is not drawn again; check the console if it billed
            print(f"  {label}: se cortó durante la llamada; cuenta como gastado, no se repite")
    # only what is still to pay is quoted: `gasto.json` already counts the rest
    items = [i for i in _items(args, material, pricing) if not _finished(done.get(i.label, {}))]
    key, max_usd = _paid_gate(args, run, items, video=False)
    ledger = _ledger(max_usd, run)
    adapter = SeedreamImageAdapter(model=SEEDREAM_MODEL)
    (run / "dibujos").mkdir(exist_ok=True)
    for item in items:
        kind, ident, _ = item.label.split("/")
        prompt = (
            character_image_prompt(character(ident))
            if kind == "personaje"
            else background_image_prompt(background(ident))
        )
        row: dict[str, Any] = {
            "label": item.label,
            "provider": "byteplus-modelark",
            "model": SEEDREAM_MODEL,
            "prompt_version": PROMPT_VERSION,
            "prompt": prompt,
            "size": IMAGE_SIZE,
            "pricing_version": pricing.version,
            "quote_usd": str(item.quote_usd),
        }
        try:
            charge = _Charge(
                run=run,
                phase="dibujar",
                rows=done,
                rows_file=run / DRAWINGS_FILE,
                row=row,
                ledger=ledger,
                amount=item.reserved_usd,
            )
        except CeilingExceededError as exc:
            print(f"TOPE: {exc}", file=sys.stderr)
            break
        started = time.monotonic()
        try:
            result = adapter.generate(
                GenerationRequest(
                    task=GenerationTask.PRODUCT_IMAGE,
                    rendered_prompt=RenderedPrompt("", "", ""),
                    params=image_params(prompt),
                ),
                api_key=key.value,
            )
        except ArkAPIError as exc:  # refused before generating: not billed
            row["error"] = str(exc)[:400]
            charge.release()
        except Exception as exc:  # unknown: count the reservation as spent
            row["error"] = f"{type(exc).__name__}: {exc}"[:400]
            charge.settle()
        else:
            try:
                actual = seedream_image_cost(
                    pricing,
                    model_id=SEEDREAM_MODEL,
                    size=IMAGE_SIZE,
                    references=0,
                    pieces=result.usage.pieces,
                )
            except Exception:  # never lose a charge: the reservation stands for it
                actual = None
            charge.settle(actual)
            images = list(result.payload["images"])  # type: ignore[index]
            name = f"{item.label.replace('/', '__')}.jpg"
            # kept byte for byte: Seedance 2.x accepts faces only in its own account's
            # Seedream outputs, unmodified
            (run / "dibujos" / name).write_bytes(images[0])
            row.update(
                file=f"dibujos/{name}",
                sha256=hashlib.sha256(images[0]).hexdigest(),
                model_revision=result.model_revision,
            )
        row["seconds_taken"] = round(time.monotonic() - started, 1)
        done[item.label] = row
        _write_json(run / DRAWINGS_FILE, done)
        print(f"  {item.label}: {row.get('file') or row.get('error')} · US${row['cost_usd']}")
    print(f"Corrida: {run} · gastado en esta fase US${ledger.snapshot()['spent_usd']}")
    print(f"Elige las opciones en {run / CHOICE_FILE} antes de «escenas» (por omisión, la 1).")
    return 0


def _raw_data_url(path: Path) -> str:
    """The image exactly as stored (no re-encoding)."""
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _chosen_drawing(run: Path, kind: str, ident: str) -> Path:
    choice = int(_read_json(run / CHOICE_FILE, {}).get(ident, 1))
    path = run / "dibujos" / f"{kind}__{ident}__opcion-{choice}.jpg"
    if not path.is_file():
        raise SystemExit(f"falta el dibujo {path.name}: corre «dibujar» o cambia {CHOICE_FILE}")
    return path


def cmd_escenas(args: argparse.Namespace, material: dict[str, Any]) -> int:
    from qualify_creative.adapters.byteplus_ark import (
        ArkAPIError,
        ArkTaskFailed,
        SeedanceVideoAdapter,
        video_cost_usd,
    )
    from qualify_creative.enums import GenerationTask
    from qualify_creative.providers import GenerationRequest, RenderedPrompt

    from qualify_api.evals.avatar_scene_bench import (
        PROMPT_VERSION,
        SEEDANCE_MODEL,
        refusal_kind,
        scene_params,
        scene_resolution,
    )
    from qualify_api.evals.spend_control import CeilingExceededError, reference_data_url

    if material["sample"]:
        raise SystemExit("«escenas» pagada necesita --material (foto del producto fuera del repo)")
    pricing = _pricing()
    run = _run_dir(args, create=False)
    done = _read_json(run / RESULTS_FILE, {})
    pairs = list(zip(_cases(args, material), _items(args, material, pricing), strict=True))
    # only what is still to pay is quoted: `gasto.json` already counts the rest
    pending = [i for c, i in pairs if not _finished(done.get(c.label, {}))]
    key, max_usd = _paid_gate(args, run, pending, video=True)
    ledger = _ledger(max_usd, run)
    adapter = SeedanceVideoAdapter(model=SEEDANCE_MODEL)
    product_url = reference_data_url(material["product"].read_bytes())
    local_url = reference_data_url(material["local"].read_bytes()) if material["local"] else None
    (run / "videos").mkdir(exist_ok=True)

    def scene_request(case: Any, **extra: Any) -> tuple[Path, dict[str, Any]]:
        char_path = _chosen_drawing(run, "personaje", case.character.id)
        bg_url = (
            local_url
            if case.background.kind == "foto"
            else _raw_data_url(_chosen_drawing(run, "fondo", case.background.id))
        )
        params = scene_params(
            case,
            character_url=_raw_data_url(char_path),
            product_url=product_url,
            background_url=str(bg_url),
            resolution_mode=args.resolucion,
        )
        return char_path, {**params, **extra}

    def finish(row: dict[str, Any], result: Any) -> Decimal | None:
        """The billed cost of a succeeded task (None: unknown, the reservation stands)."""
        payload = dict(result.payload) if isinstance(result.payload, dict) else {}
        tokens = int(result.usage.output_tokens or 0)
        try:
            actual = (
                video_cost_usd(pricing, result.model_id, row["resolution"], tokens)
                if tokens
                else None
            )
        except Exception:  # never lose a charge: the reservation stands for it
            actual = None
        row.update(
            task_id=payload.get("task_id") or row.get("task_id"),
            billed_tokens=tokens,
            cost_kind="facturado (tokens)" if actual is not None else "reservado",
            model_revision=result.model_revision,
            media_url=result.media_url,
        )
        return actual

    def fetch(row: dict[str, Any], case: Any) -> None:
        if row.get("media_url"):  # valid 24 h: copied at once
            name = f"{case.file_stem}.mp4"
            failure = _download_video(str(row["media_url"]), run / "videos" / name)
            if failure is None:
                row["video"] = f"videos/{name}"
            row["download_error"] = failure

    for case, item in pairs:
        previous = done.get(case.label, {})
        if previous.get("video"):
            continue  # resumed
        if previous.get("status") == SENT and previous.get("task_id"):
            # cut while ModelArk worked on it: wait for THAT task by id, never a new one;
            # its reservation is already in `gasto.json`, only the difference is added
            print(f"  {case.label}: se recupera la tarea {previous['task_id']}, sin crear otra")
            _, params = scene_request(case, resume_task_id=previous["task_id"])
            reserved = Decimal(str(previous["cost_usd"]))
            request = GenerationRequest(
                task=GenerationTask.SCENE_VIDEO,
                rendered_prompt=RenderedPrompt("", "", ""),
                params=params,
            )
            try:
                result = adapter.generate(request, api_key=key.value)
            except (ArkAPIError, ArkTaskFailed) as exc:  # failed: not billed
                previous.update(status=RELEASED, cost_usd="0", error=str(exc)[:600])
                _add_spend(run, "escenas", case.label, -reserved, kind="liberado")
            except Exception as exc:  # still going: stays sent, counted
                previous["error"] = f"{type(exc).__name__}: {exc}"[:600]
            else:
                actual = finish(previous, result)
                cost = reserved if actual is None else actual
                previous.update(status=PAID, cost_usd=str(cost))
                _write_json(run / RESULTS_FILE, done)
                if cost != reserved:
                    _add_spend(run, "escenas", case.label, cost - reserved, kind="ajuste")
                fetch(previous, case)
            _write_json(run / RESULTS_FILE, done)
            continue
        if _finished(previous):
            # paid before (or may have been): never sent again; only its video is fetched
            fetch(previous, case)
            _write_json(run / RESULTS_FILE, done)
            print(f"  {case.label}: ya pagada, no se manda de nuevo")
            continue
        char_path, params = scene_request(case)
        row: dict[str, Any] = {
            "label": case.label,
            "character": case.character.id,
            "background": case.background.id,
            "scene": case.scene.id,
            "seconds_asked": case.scene.seconds,
            "line": case.scene.line,
            "provider": "byteplus-modelark",
            "model": SEEDANCE_MODEL,
            "prompt_version": PROMPT_VERSION,
            "prompt": params["prompt"],
            "resolution": scene_resolution(args.resolucion),
            "draft": bool(params.get("draft")),
            "character_sha256": hashlib.sha256(char_path.read_bytes()).hexdigest(),
            "product_sha256": hashlib.sha256(material["product"].read_bytes()).hexdigest(),
            "pricing_version": pricing.version,
            "quote_usd": str(item.quote_usd),
        }
        try:
            charge = _Charge(
                run=run,
                phase="escenas",
                rows=done,
                rows_file=run / RESULTS_FILE,
                row=row,
                ledger=ledger,
                amount=item.reserved_usd,
            )
        except CeilingExceededError as exc:
            print(f"TOPE: {exc}", file=sys.stderr)
            break
        started = time.monotonic()
        request = GenerationRequest(
            task=GenerationTask.SCENE_VIDEO,
            rendered_prompt=RenderedPrompt("", "", ""),
            params=params,
            observer=charge,  # the task id is on disk as soon as ModelArk accepts it
        )
        try:
            result = adapter.generate(request, api_key=key.value)
        except (ArkAPIError, ArkTaskFailed) as exc:  # refused or failed: not billed
            row.update(error=str(exc)[:600], refusal=refusal_kind(str(exc)))
            charge.release()
        except Exception as exc:  # timeout or unknown: the task may still bill
            row["error"] = f"{type(exc).__name__}: {exc}"[:600]
            row["task_id"] = getattr(exc, "task_id", None) or row.get("task_id")
            charge.settle()
            if row["task_id"]:
                # the task may still finish (and bill): left «enviada», so the next run
                # waits for it by id instead of creating another
                row["status"] = SENT
                charge.save()
        else:
            actual = finish(row, result)
            # the paid row is on disk BEFORE the download: a cut there never pays twice
            charge.settle(actual)
            fetch(row, case)
        row["seconds_taken"] = round(time.monotonic() - started, 1)
        done[case.label] = row
        _write_json(run / RESULTS_FILE, done)
        print(
            f"  {case.label}: {row.get('video') or row.get('error')} · "
            f"{row['seconds_taken']} s · US${row['cost_usd']}"
        )
    print(f"Corrida: {run} · gastado en esta fase US${ledger.snapshot()['spent_usd']}")
    return 0


def cmd_planilla(args: argparse.Namespace) -> int:
    from qualify_api.evals.avatar_scene_bench import (
        JUDGES,
        sheet_csv,
        sheet_rows,
        summarize_sheet,
    )

    if args.resumen:
        text = Path(args.resumen).read_text(encoding="utf-8")
        print(json.dumps(summarize_sheet(text), indent=2, ensure_ascii=False))
        return 0
    run = _run_dir(args, create=False)
    results = list(_read_json(run / RESULTS_FILE, {}).values())
    if not results:
        raise SystemExit(f"no hay {RESULTS_FILE} en {run}")
    text = sheet_csv(sheet_rows(results))
    for judge in JUDGES:
        path = run / f"juicio-{judge}.csv"
        if path.exists():
            print(f"ya existe {path}: no se sobrescribe")
            continue
        path.write_text(text, encoding="utf-8")
        print(f"planilla: {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    from qualify_api.evals.avatar_scene_bench import (
        CHARACTER_IDS,
        DEFAULT_OPTIONS,
        DEFAULT_RESOLUTION_MODE,
        PROPOSED_MAX_USD,
        RESOLUTION_MODES,
    )

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=("plan", "dibujar", "escenas", "planilla"))
    parser.add_argument("--material", help="material.json fuera del repositorio")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--run", help="carpeta de una corrida (reanuda o sigue)")
    parser.add_argument("--env-file", help="el .env del checkout principal (llave)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--i-have-spend-authorization", action="store_true")
    parser.add_argument("--max-usd", default=str(PROPOSED_MAX_USD))
    parser.add_argument("--allow-daytime", action="store_true")
    parser.add_argument("--opciones", type=int, default=DEFAULT_OPTIONS)
    parser.add_argument("--personaje", action="append", choices=CHARACTER_IDS)
    parser.add_argument("--resolucion", choices=RESOLUTION_MODES, default=DEFAULT_RESOLUTION_MODE)
    parser.add_argument("--resumen", help="planilla llena a resumir (con «planilla»)")
    return parser


def main(argv: list[str] | None = None) -> int:
    from qualify_api.evals.avatar_scene_bench import mode_refusal

    args = build_parser().parse_args(argv)
    if args.command == "planilla":
        return cmd_planilla(args)
    paid = args.i_have_spend_authorization
    dry = args.dry_run or args.command == "plan"
    if args.command == "plan" and paid:
        print("«plan» nunca gasta: quita --i-have-spend-authorization.", file=sys.stderr)
        return 2
    refusal = None if args.command == "plan" else mode_refusal(paid=paid, dry_run=dry)
    if refusal:
        print(refusal, file=sys.stderr)
        return 2
    try:
        material = load_material(args.material)
    except MaterialError as exc:
        print(exc, file=sys.stderr)
        return 2
    if dry:
        return _dry(args, material)
    if args.command == "dibujar":
        return cmd_dibujar(args, material)
    return cmd_escenas(args, material)


if __name__ == "__main__":
    sys.exit(main())

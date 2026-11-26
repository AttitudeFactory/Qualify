"""AVFOTO-001: the Clip's realistic character drawn from a real person's photo (ADR 50
§12.12, m-25129385). Seedream 5.0 pro draws it from the photo; only that drawing goes to
Seedance 2.5 as the character of AVESC-001's scene 1.

The bench's method, prompts and sheet are in `qualify_api.evals.avatar_photo_bench`; the
paid loops, the spend ledger and the resume logic are AVESC-001's (`run_experiment.py`),
reused as they are.

Subcommands (all outputs OUTSIDE the repo, `%TEMP%/avatar-foto-real/corridas/` by default):

    plan      the whole plan, its prompts and its cost from the versioned pricing table.
              Never calls anything (the network is blocked while it runs).
    dibujar   Seedream 5.0 pro, `--opciones` drawings per photo (1K, 9:16), the photo as
              the only reference. Paid: images are not bound by the video window.
    escenas   Seedance 2.5, one 5 s 480p draft per photo with the chosen drawing, the
              product and AVESC-001's drawn background. Paid: only 23:00-05:00 Bogotá
              unless `--allow-daytime` (founder's OK).
    planilla  the judgment sheet (`juicio-deivid.csv`) with the automatic columns filled;
              `--resumen <csv>` summarizes it once Deivid scored the likeness.

`dibujar` and `escenas` need EXACTLY ONE of `--dry-run` and `--i-have-spend-authorization`.
Paid runs share ONE ceiling (`--max-usd`, at most US$10) over the run folder (`gasto.json`).

`--material <file>.json` (outside the repo; paths relative to it or absolute, never inside
the repository):

    {"producto": {"nombre": "super smash", "photo": "<AVESC-001's product photo>"},
     "fondo": {"photo": "<AVESC-001 run>/dibujos/fondo__dibujado__opcion-1.jpg"},
     "personas": [{"id": "p1", "photo": "fotos/p1.jpg", "permiso_escrito": true}, ...]}

Every person needs `"permiso_escrito": true` (the JSON boolean): one without it and the
bench refuses the whole run before anything is sent. The id is a short slug, never a name.
The drawing that goes to the scene is option 1 unless `<run>/eleccion.json` says otherwise:
`{"p1": 2}`. A person whose chosen drawing does not exist (Seedream refused it) is left out
of `escenas`.

    just eval-avatar-foto plan --material %TEMP%/avatar-foto-real/material.json
    just eval-avatar-foto dibujar --env-file <checkout>/.env --material <...> \\
        --i-have-spend-authorization --max-usd 3
    just eval-avatar-foto escenas --env-file <checkout>/.env --run <run folder> \\
        --material <...> --i-have-spend-authorization --max-usd 3
    just eval-avatar-foto planilla --run <run folder>
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
DEFAULT_OUT = Path(tempfile.gettempdir()) / "avatar-foto-real" / "corridas"
PEOPLE_FILE = "personas.json"
PHOTO_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")


def _load_base() -> Any:
    """AVESC-001's runner: its ledger, charges, paid loops and helpers."""
    name = "avatar_escena_runner_base"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, HERE / "run_experiment.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


base = _load_base()
MaterialError = base.MaterialError


def load_material(path: str | None) -> dict[str, Any]:
    """`{"product", "product_name", "background", "people", "photos", "sample"}`. Without a
    file: the repo's sample product and three placeholder people (for `plan` only)."""
    from qualify_api.evals.avatar_photo_bench import Person, check_people

    if not path:
        return {
            "product": base.SAMPLE_PRODUCT,
            "product_name": "super smash",
            "background": None,
            "people": [Person(f"p{n}", True) for n in (1, 2, 3)],
            "photos": {},
            "sample": True,
        }
    file = Path(path).resolve()
    if file.is_relative_to(REPO):
        raise MaterialError("el material.json tiene que estar fuera del repositorio")
    data = json.loads(file.read_text(encoding="utf-8"))
    # permission first: a refused list never gets its photos opened
    people = check_people(data.get("personas"))

    def resolve(raw: object, what: str) -> Path:
        if not raw:
            raise MaterialError(f"{what}: falta la foto")
        photo = (file.parent / str(raw)).resolve()
        if photo.is_relative_to(REPO):
            raise MaterialError(f"{what}: la foto tiene que estar fuera del repositorio")
        if not photo.is_file():
            raise MaterialError(f"{what}: no existe {photo}")
        if photo.suffix.lower() not in PHOTO_SUFFIXES:
            raise MaterialError(f"{what}: tiene que ser JPG, PNG o WEBP")
        return photo

    entries = {str(e.get("id")): e for e in data["personas"]}
    return {
        "product": resolve((data.get("producto") or {}).get("photo"), "producto"),
        "product_name": str((data.get("producto") or {}).get("nombre") or "super smash"),
        "background": resolve((data.get("fondo") or {}).get("photo"), "fondo"),
        "people": people,
        "photos": {p.id: resolve(entries[p.id].get("photo"), f"persona {p.id}") for p in people},
        "sample": False,
    }


def _items(args: argparse.Namespace, material: dict[str, Any], pricing: Any) -> list[Any]:
    from qualify_api.evals.avatar_photo_bench import drawing_items, scene_items

    items: list[Any] = []
    if args.command in ("plan", "dibujar"):
        items += drawing_items(pricing, material["people"], options=args.opciones)
    if args.command in ("plan", "escenas"):
        items += scene_items(pricing, material["people"])
    return items


def _validate_drawing_requests(pricing: Any) -> str:
    """A drawing request through the REAL Seedream adapter's checks and estimate, with a
    placeholder photo (nothing sent)."""
    from qualify_creative.adapters.byteplus_ark import SeedreamImageAdapter
    from qualify_creative.enums import GenerationTask
    from qualify_creative.providers import GenerationRequest, RenderedPrompt

    from qualify_api.evals.avatar_photo_bench import drawing_params, drawing_quote
    from qualify_api.evals.avatar_scene_bench import SEEDREAM_MODEL

    request = GenerationRequest(
        task=GenerationTask.PRODUCT_IMAGE,
        rendered_prompt=RenderedPrompt("", "", ""),
        params=drawing_params(base._DRY_IMAGE),
    )
    estimate = SeedreamImageAdapter(model=SEEDREAM_MODEL).estimate_cost_usd(request, pricing)
    mine = drawing_quote(pricing)
    if estimate != mine:
        raise AssertionError(f"dibujo: adapter {estimate} != bench {mine}")
    return f"dibujo: 1 foto de referencia, US${estimate}"


def _print_plan(args: argparse.Namespace, material: dict[str, Any], items: list[Any]) -> dict:
    from qualify_api.evals.avatar_photo_bench import (
        BENCH_ID,
        PROMPT_VERSION,
        RESOLUTION_MODE,
        SCENE_PROMPT_VERSION,
        case_for,
        drawing_prompt,
    )
    from qualify_api.evals.avatar_scene_bench import (
        SEEDANCE_MODEL,
        SEEDREAM_MODEL,
        plan_totals,
        scene_prompt,
    )

    pricing = base._pricing()
    cases = [case_for(p) for p in material["people"]]
    print(f"{BENCH_ID} · tabla de precios {pricing.version}")
    print(f"Prompts: dibujo {PROMPT_VERSION} · escena {SCENE_PROMPT_VERSION}")
    print(f"Producto: {material['product_name']} · foto {material['product']}")
    print(f"Fondo dibujado: {material['background'] or 'falta (va en --material)'}")
    people = ", ".join(p.id for p in material["people"])
    print(f"Personas ({len(material['people'])}): {people}")
    if material["sample"]:
        print("  (personas de muestra, sin fotos: la corrida pagada necesita --material)")
    else:
        print("  todas con «permiso_escrito»: true")
    if args.command in ("plan", "dibujar"):
        print(f"\nDibujos ({SEEDREAM_MODEL}, {args.opciones} opciones por foto):")
        print(drawing_prompt())
        print("\nRevisado por el adaptador real (sin enviar):")
        print(f"  {_validate_drawing_requests(pricing)}")
    if args.command in ("plan", "escenas"):
        print(f"\nEscenas ({SEEDANCE_MODEL}, {RESOLUTION_MODE}, con audio):")
        for case in cases:
            print(f"- {case.label} · {case.scene.seconds} s · «{case.scene.line}»")
        if cases:
            print(f"\nPrompt de la escena ({cases[0].label}):\n{scene_prompt(cases[0])}")
        print("\nRevisado por el adaptador real (sin enviar):")
        for line in base._validate_scene_requests(cases, pricing, RESOLUTION_MODE):
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
        "bench": BENCH_ID,
        "pricing_version": pricing.version,
        "prompt_version": PROMPT_VERSION,
        "scene_prompt_version": SCENE_PROMPT_VERSION,
        "people": [p.id for p in material["people"]],
        "cases": [c.label for c in cases],
        "items": [
            {"phase": i.phase, "label": i.label, "quote_usd": str(i.quote_usd)} for i in items
        ],
        "totals": totals,
    }


def _dry(args: argparse.Namespace, material: dict[str, Any]) -> int:
    from qualify_api.evals.spend_control import network_guard

    with network_guard() as stats:
        items = _items(args, material, base._pricing())
        plan = _print_plan(args, material, items)
    print(f"\nLlamadas de red bloqueadas durante la prueba en seco: {stats['blocked']}")
    out = Path(args.out)
    if out.resolve().is_relative_to(REPO):
        raise SystemExit("la cotización va fuera del repositorio")
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"cotizacion-{args.command}-{datetime.now():%Y%m%d-%H%M%S}.json"
    base._write_json(path, {**plan, "command": args.command, "network_blocked": stats["blocked"]})
    print(f"Cotización: {path}")
    return 0


def cmd_dibujar(args: argparse.Namespace, material: dict[str, Any]) -> int:
    from qualify_api.evals.avatar_photo_bench import (
        PROMPT_VERSION,
        REFERENCES_PER_DRAWING,
        drawing_params,
    )
    from qualify_api.evals.spend_control import reference_data_url

    if material["sample"]:
        raise SystemExit("«dibujar» pagado necesita --material con las fotos y sus permisos")
    pricing = base._pricing()
    run = base._run_dir(args, create=True)
    base._write_json(run / PEOPLE_FILE, [p.id for p in material["people"]])
    done = base._read_json(run / base.DRAWINGS_FILE, {})
    base._cut_drawings(done)
    # only what is still to pay is quoted: `gasto.json` already counts the rest
    items = [
        i for i in _items(args, material, pricing) if not base._finished(done.get(i.label, {}))
    ]
    key, max_usd = base._paid_gate(args, run, items, video=False)

    def request_for(item: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        _, pid, option = item.label.split("/")
        photo = material["photos"][pid].read_bytes()
        params = drawing_params(reference_data_url(photo))
        return params, {
            "person": pid,
            "option": int(option.removeprefix("opcion-")),
            "permiso_escrito": True,
            "photo_sha256": hashlib.sha256(photo).hexdigest(),
            "prompt_version": PROMPT_VERSION,
            "prompt": params["prompt"],
            "references": REFERENCES_PER_DRAWING,
        }

    base._draw_all(
        run,
        items,
        done,
        key=key,
        ledger=base._ledger(max_usd, run),
        pricing=pricing,
        request_for=request_for,
        references=REFERENCES_PER_DRAWING,
    )
    print(f"Corrida: {run} · gastado en esta fase US${base._phase_spent(run, 'dibujar')}")
    print(f"Elige la opción de cada persona en {run / base.CHOICE_FILE} (por omisión, la 1).")
    return 0


def chosen_drawing(run: Path, person_id: str) -> tuple[int, Path]:
    from qualify_api.evals.avatar_photo_bench import drawing_label

    option = int(base._read_json(run / base.CHOICE_FILE, {}).get(person_id, 1))
    name = f"{drawing_label(person_id, option).replace('/', '__')}.jpg"
    return option, run / "dibujos" / name


def cmd_escenas(args: argparse.Namespace, material: dict[str, Any]) -> int:
    from qualify_api.evals.avatar_photo_bench import (
        PROMPT_VERSION,
        RESOLUTION_MODE,
        case_for,
        person_of,
        scene_items,
    )
    from qualify_api.evals.avatar_scene_bench import scene_params
    from qualify_api.evals.spend_control import reference_data_url

    if material["sample"]:
        raise SystemExit("«escenas» pagada necesita --material (producto y fondo fuera del repo)")
    pricing = base._pricing()
    run = base._run_dir(args, create=False)
    done = base._read_json(run / base.RESULTS_FILE, {})
    people = []
    for person in material["people"]:
        option, path = chosen_drawing(run, person.id)
        if path.is_file():
            people.append(person)
        else:
            print(f"  {person.id}: no hay dibujo en la opción {option}; queda fuera de las escenas")
    pairs = list(zip([case_for(p) for p in people], scene_items(pricing, people), strict=True))
    pending = [i for c, i in pairs if not base._finished(done.get(c.label, {}))]
    key, max_usd = base._paid_gate(args, run, pending, video=True)
    product_url = reference_data_url(material["product"].read_bytes())
    # AVESC-001's drawn background, byte for byte (it is a Seedream output of our account)
    background_url = base._raw_data_url(material["background"])

    def scene_request(case: Any, **extra: Any) -> tuple[Path, dict[str, Any]]:
        _, path = chosen_drawing(run, person_of(case))
        params = scene_params(
            case,
            character_url=base._raw_data_url(path),
            product_url=product_url,
            background_url=background_url,
            resolution_mode=RESOLUTION_MODE,
        )
        return path, {**params, **extra}

    def row_for(case: Any, char_path: Path, params: dict[str, Any]) -> dict[str, Any]:
        pid = person_of(case)
        option, _ = chosen_drawing(run, pid)
        return {
            "person": pid,
            "character": case.character.id,
            "background": case.background.id,
            "drawing_option": option,
            "drawing_file": f"dibujos/{char_path.name}",
            "character_prompt_version": PROMPT_VERSION,
            "product_sha256": hashlib.sha256(material["product"].read_bytes()).hexdigest(),
            "background_sha256": hashlib.sha256(material["background"].read_bytes()).hexdigest(),
        }

    base._scenes_loop(
        run,
        pairs,
        done,
        key=key,
        max_usd=max_usd,
        pricing=pricing,
        resolution_mode=RESOLUTION_MODE,
        scene_request=scene_request,
        row_for=row_for,
    )
    print(f"Corrida: {run} · gastado en esta fase US${base._phase_spent(run, 'escenas')}")
    return 0


def cmd_planilla(args: argparse.Namespace) -> int:
    from qualify_api.evals.avatar_photo_bench import (
        JUDGE,
        sheet_csv,
        sheet_rows,
        summarize_sheet,
    )

    if args.resumen:
        text = Path(args.resumen).read_text(encoding="utf-8")
        print(json.dumps(summarize_sheet(text), indent=2, ensure_ascii=False))
        return 0
    run = base._run_dir(args, create=False)
    people = base._read_json(run / PEOPLE_FILE, [])
    if not people:
        raise SystemExit(f"no hay {PEOPLE_FILE} en {run}: corre «dibujar» primero")
    rows = sheet_rows(
        people,
        base._read_json(run / base.DRAWINGS_FILE, {}),
        base._read_json(run / base.RESULTS_FILE, {}),
        choices=base._read_json(run / base.CHOICE_FILE, {}),
    )
    path = run / f"juicio-{JUDGE}.csv"
    if path.exists():
        print(f"ya existe {path}: no se sobrescribe")
        return 0
    path.write_text(sheet_csv(rows), encoding="utf-8")
    print(f"planilla: {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    from qualify_api.evals.avatar_photo_bench import DEFAULT_OPTIONS, PROPOSED_MAX_USD

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
    parser.add_argument("--resumen", help="planilla llena a resumir (con «planilla»)")
    return parser


def main(argv: list[str] | None = None) -> int:
    from qualify_api.evals.avatar_photo_bench import PermissionRefused
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
    except (MaterialError, PermissionRefused) as exc:
        print(exc, file=sys.stderr)
        return 2
    if dry:
        return _dry(args, material)
    if args.command == "dibujar":
        return cmd_dibujar(args, material)
    return cmd_escenas(args, material)


if __name__ == "__main__":
    sys.exit(main())

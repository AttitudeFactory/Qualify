"""CAPA-003 (m-25017292) — the first layer → render run, end to end and local: `capa-v3`
writes the layer of ~11 single photos and one 6-slide carousel (one Claude call per piece,
under a hard total cap), every `LayerSpec` is stored whole, and each one is composed over
its own base photo by a LOCAL `packages/render` service (`layer_still` v1) through the
production client (`qualify_creative.render.layer_compose.compose_layer`). Stills and a
contact sheet go to `--out`. No Seedream, nothing in R2 or the database, nothing wired.

The brand is the render's fixture brand (palette, Poppins/Inter, no logo): Bianki's kit is
not readable locally. Prices print a fixture whole price per product.

    PYTHONPATH=packages/api/src:packages/shared/src:packages/creative/src \\
      uv run --no-sync python packages/api/evals/capa_texto/capa_003.py \\
      --images <FOTO-BASE-001 bases> --out <dir> [--max-usd 0.33] [--render http://127.0.0.1:3290]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from qualify_creative.render.client import RemotionRenderClient, RenderServiceError
from qualify_creative.render.layer_compose import (
    LayerComposeRequest,
    LayerRefused,
    compose_layer,
)

from qualify_api import claude_tools
from qualify_api.claude_tools import BudgetExhausted, DollarMeter
from qualify_api.creative.image_pipeline import layer
from qualify_api.creative.image_pipeline.layer import (
    BUSINESS_INFO,
    CAROUSEL,
    FREE_IDEA,
    LAYER_BUDGET_USD,
    LAYER_PROMPT_VERSION,
    PRODUCT_PROMOTION,
    LayerError,
    LayerRequest,
    SlideInput,
    write_layers,
)

sys.path.insert(0, str(Path(__file__).parent))
from capa_002 import (  # noqa: E402
    _FORMATS,
    BRAND,
    CASES,
    TENANT,
    WORST_TURN_USD,
    Watch,
    _case_of,
    _env,
    _facts,
    _products,
    _square,
    rule_of,
)

#: (photo stem, piece type, saved data offered, cut to 1:1) — the mix the brief asked for
PIECES: list[tuple[str, str, bool, bool]] = [
    ("F4-combo-r1-v5", PRODUCT_PROMOTION, False, False),  # priced, 4:5
    ("F2-te-espera-r1-v4", PRODUCT_PROMOTION, False, False),  # priced, 9:16
    (
        "F1-ubicacion-r1-v4",
        PRODUCT_PROMOTION,
        False,
        False,
    ),  # priced + saved data (v2: band+blocks)
    ("F8-papas-compartir-r1-v5", PRODUCT_PROMOTION, False, False),  # unpriced, 9:16
    ("F7-pollo-2x1-r2-v4", PRODUCT_PROMOTION, False, True),  # priced, 1:1
    ("G1-combo-galeria-s1-r2-v4", PRODUCT_PROMOTION, False, True),  # 1:1 (v2: band 1:1 repair)
    ("F3-horario-r1-v5", BUSINESS_INFO, True, False),  # «Información de tu negocio», 9:16
    ("F1-ubicacion-r2-v5", FREE_IDEA, True, False),  # free idea about saved data, 9:16
    ("F6-domicilio-logo-r1-v5", FREE_IDEA, True, False),  # free idea with data, 9:16
    ("F5-ensalada-escena-r1-v5", FREE_IDEA, False, False),  # free idea, no data, 4:5
    ("F5-ensalada-escena-r2-v4", FREE_IDEA, False, True),  # free idea, 1:1
]
#: one carousel of 6 slides, with unpriced products (v2: price_ref repair)
CAROUSEL_STEMS = [
    "G2-salchipapa-galeria-s1-r1-v5",
    "G2-salchipapa-galeria-s2-r1-v4",
    "G2-salchipapa-galeria-s1-r2-v4",
    "G2-salchipapa-galeria-s2-r1-v5",
    "G2-salchipapa-galeria-s1-r2-v5",
    "G2-salchipapa-galeria-s2-r2-v5",
]
#: the render's fixture brand (packages/render/src/Root.tsx), no logo
FIXTURE_BRAND = {
    "name": "Bianki",
    "palette": ["#B5532A", "#FFFFFF", "#FFF4E6"],
    "fonts": {"heading": "Poppins", "body": "Inter"},
}
#: a whole price per priced product, as Python would format it (fixture)
PRICES = {
    "Shawarma de carne": "$ 18.000",
    "Shawarma de pollo": "$ 16.000",
    "Combo de shawarma de carne": "$ 35.000",
}


def _plan(images: Path, out: Path, cases: dict[str, Any]) -> list[dict[str, Any]]:
    squares = out / "square-inputs"
    squares.mkdir(parents=True, exist_ok=True)
    pieces = []
    case_id = _case_of(CAROUSEL_STEMS[0])
    pieces.append(
        {
            "id": f"{case_id}-carrusel-{len(CAROUSEL_STEMS)}",
            "case": case_id,
            "format": "4:5",
            "piece_type": CAROUSEL,
            "photos": [images / f"{s}.jpg" for s in CAROUSEL_STEMS],
            "data": True,
        }
    )
    for stem, piece_type, data, square in PIECES:
        case = cases[_case_of(stem)]
        photo, fmt = images / f"{stem}.jpg", _FORMATS.get(case["format"], "4:5")
        if square:
            photo, fmt = _square(photo, squares / f"{stem}-1x1.jpg"), "1:1"
        pieces.append(
            {
                "id": stem + ("-1x1" if square else ""),
                "case": case["id"],
                "format": fmt,
                "piece_type": piece_type,
                "photos": [photo],
                "data": data,
            }
        )
    return pieces


def _compose(
    client: RemotionRenderClient, spec: dict[str, Any], photo: Path, piece: str, position: int
) -> dict[str, Any]:
    data = photo.read_bytes()
    products = {p.product_id: p.name for p in _PRODUCTS.get(piece, ())}
    price_ref = (spec.get("price_ref") or {}).get("product_id")
    price_text = PRICES.get(products.get(UUID(price_ref), ""), "") if price_ref else ""
    request = LayerComposeRequest(
        tenant_id=str(TENANT),
        draft_id=str(uuid5(BRAND, piece)),
        version_id=str(uuid5(BRAND, f"{piece}/v1")),
        layer_id=str(uuid5(BRAND, f"{piece}#{position}")),
        position=position,
        spec=spec,
        brand=FIXTURE_BRAND,
        base_key=str(photo),
        base_sha256=hashlib.sha256(data).hexdigest(),
        price_text=price_text,
        is_food=True,
    )
    started = time.perf_counter()
    try:
        still = compose_layer(client, request, read_media=lambda key: Path(key).read_bytes())
    except LayerRefused as exc:
        return {
            "status": "refused",
            "reason": exc.reason,
            "slot": exc.slot,
            "detail": exc.detail,
            "seconds": round(time.perf_counter() - started, 1),
        }
    except RenderServiceError as exc:
        return {
            "status": "failed",
            "code": getattr(exc, "code", None),
            "detail": str(exc)[:400],
            "seconds": round(time.perf_counter() - started, 1),
        }
    return {
        "status": "completed",
        "seconds": round(time.perf_counter() - started, 1),
        "layout_requested": still.layout_requested,
        "layout_rendered": still.layout_rendered,
        "fallbacks": list(still.fallbacks),
        "dropped_slots": list(still.report.get("dropped_slots") or []),
        "price_text": price_text,
        "png": still.png,
    }


_PRODUCTS: dict[str, Any] = {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--images", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-usd", default="0.33")
    parser.add_argument("--env-file", default=str(Path.cwd() / ".env"))
    parser.add_argument("--render", default="http://127.0.0.1:3290")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cases = {c["id"]: c for c in json.loads(CASES.read_text(encoding="utf-8"))["cases"]}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pieces = _plan(Path(args.images), out, cases)
    print(f"{len(pieces)} pieces, {sum(len(p['photos']) for p in pieces)} photos")
    if args.dry_run:
        for piece in pieces:
            print(f"  {piece['id']} {piece['format']} {piece['piece_type']}")
        return 0
    api_key = _env(Path(args.env_file)).get(claude_tools.API_KEY_ENV, "")
    if not api_key:
        print("No Anthropic key in the environment or --env-file.", file=sys.stderr)
        return 2
    booked: list[Any] = []
    claude_tools.configure_consumption_sink(booked.append)  # no ledger row from an eval
    watch = Watch()
    watch.install()
    client = RemotionRenderClient(args.render)
    total, spent = Decimal(args.max_usd), Decimal(0)
    stills_dir = out / "stills"
    stills_dir.mkdir(exist_ok=True)
    rows: list[dict[str, Any]] = []
    results = (out / "results.jsonl").open("w", encoding="utf-8")
    for piece in pieces:
        left = total - spent
        if left < WORST_TURN_USD:
            print(f"total cap: US${left} left, stopping before {piece['id']}")
            break
        case = cases[piece["case"]]
        products = _products(case)
        _PRODUCTS[piece["id"]] = products
        request = LayerRequest(
            tenant_id=TENANT,
            brand_id=BRAND,
            format=piece["format"],
            piece_type=piece["piece_type"],
            slides=tuple(
                SlideInput(position=i, photo=Path(p).read_bytes())
                for i, p in enumerate(piece["photos"])
            ),
            brand_name="Bianki",
            topic=case["topic"],
            scene=case["topic"],
            cta=case["cta_or_place"] if isinstance(case.get("cta_or_place"), str) else "",
            facts=_facts(case, payment=piece["data"]),
            products=products,
        )
        meter = DollarMeter(min(LAYER_BUDGET_USD, left))
        watch.reset()
        row: dict[str, Any] = {k: v for k, v in piece.items() if k != "photos"} | {
            "photos": [Path(p).name for p in piece["photos"]]
        }
        started = time.perf_counter()
        try:
            result = write_layers(request, api_key=api_key, budget=meter)
        except (LayerError, BudgetExhausted) as exc:
            result = None
            row["error"] = str(exc)[:300]
        row["seconds"] = round(time.perf_counter() - started, 2)
        spent += meter.spent_usd
        row["usd"] = str(meter.spent_usd)
        row["refusals"] = [
            {"turn": t, "position": p, "rule": rule_of(m), "message": m[:300]}
            for t, p, m in watch.refusals
        ]
        row["repair_rules"] = sorted({rule_of(m) for t, _, m in watch.refusals if t == 1})
        row["layers"] = {}
        if result is not None:
            row.update(
                slides=len(piece["photos"]),
                valid_slides=len(result.specs),
                repaired=bool(result.repairs),
                dropped=sorted(result.failed),
                input_tokens=result.stats.input_tokens if result.stats else None,
                output_tokens=result.stats.output_tokens if result.stats else None,
            )
            for position, spec in sorted(result.specs.items()):
                dumped = spec.model_dump(mode="json")
                composed = _compose(
                    client, dumped, Path(piece["photos"][position]), piece["id"], position
                )
                png = composed.pop("png", None)
                if png:
                    name = f"{piece['id']}-{position + 1}.png"
                    (stills_dir / name).write_bytes(png)
                    composed["file"] = name
                row["layers"][str(position)] = {
                    "layout": spec.layout_id.value,
                    "title": spec.title,
                    "subtitle": spec.subtitle,
                    "call_phrase": spec.call_phrase,
                    "info": [b.kind.value for b in spec.info_blocks],
                    "price_ref": bool(spec.price_ref),
                    "spec": dumped,
                    "render": composed,
                }
        rows.append(row)
        results.write(json.dumps(row, ensure_ascii=False) + "\n")
        results.flush()
        renders = [v["render"]["status"] for v in row["layers"].values()]
        print(
            f"{row['id']}: {row.get('valid_slides')}/{row.get('slides')} valid, "
            f"repair={row.get('repaired')} {row['repair_rules']}, {row['seconds']} s, "
            f"US${row['usd']} (total US${spent}); render {renders}"
        )
    results.close()
    _sheet(out, rows)
    singles = [r for r in rows if r["piece_type"] != CAROUSEL]
    stills = [v for r in rows for v in r["layers"].values()]
    rendered = [v["render"] for v in stills]
    report = {
        "prompt_version": LAYER_PROMPT_VERSION,
        "model": layer.LAYER_MODEL.model_id,
        "pieces": len(rows),
        "planned": len(pieces),
        "repaired_pieces": [r["id"] for r in rows if r.get("repaired")],
        "repair_rules": sorted({x for r in rows for x in r["repair_rules"]}),
        "single_seconds_p50": statistics.median([r["seconds"] for r in singles])
        if singles
        else None,
        "stills": len(stills),
        "render_completed": sum(1 for v in rendered if v["status"] == "completed"),
        "render_fell_back": sum(1 for v in rendered if v.get("fallbacks")),
        "render_dropped_slots": sum(1 for v in rendered if v.get("dropped_slots")),
        "render_refused": [v for v in rendered if v["status"] == "refused"],
        "render_failed": [v for v in rendered if v["status"] == "failed"],
        "render_seconds_p50": statistics.median([v["seconds"] for v in rendered])
        if rendered
        else None,
        "spent_usd": str(spent),
        "calls_booked": len(booked),
    }
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _sheet(out: Path, rows: list[dict[str, Any]]) -> None:
    """A contact sheet of every drawn still, its id and layout under it (eval output)."""
    from PIL import Image, ImageDraw  # noqa: PLC0415 - eval output only

    cells = []
    for row in rows:
        for position, value in row["layers"].items():
            render = value["render"]
            label = f"{row['id']} #{int(position) + 1} {render.get('layout_rendered', '')}"
            if render.get("file"):
                with Image.open(out / "stills" / render["file"]) as image:
                    thumb = image.convert("RGB")
                    thumb.thumbnail((300, 534))
                    cells.append((thumb.copy(), label))
            else:
                cells.append((None, f"{label} — {render['status']}"))
    if not cells:
        return
    columns, width, height = 6, 310, 580
    sheet = Image.new("RGB", (columns * width, ((len(cells) + 5) // columns) * height), "white")
    draw = ImageDraw.Draw(sheet)
    for i, (thumb, label) in enumerate(cells):
        x, y = (i % columns) * width + 5, (i // columns) * height + 5
        if thumb is not None:
            sheet.paste(thumb, (x, y))
        draw.text((x, y + 540), label[:48], fill="black")
    sheet.save(out / "hoja-de-contacto.jpg", quality=88)


if __name__ == "__main__":
    raise SystemExit(main())

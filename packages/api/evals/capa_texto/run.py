"""m-25017283 — the layer stage (Claude writes the text layer) over base photos from disk.

For every photo in `--images` (the raw Seedream bases of FOTO-BASE-001 /
ESCENA-SIN-LETRAS-001 work: `<case>-r<rep>-v<compiler>.jpg`, never committed) it builds the
production `LayerRequest` from the case's brief in `../scene_text_v4/cases.json` and calls
the production `write_layers` (Claude Sonnet 5.5, one call per photo; a gallery case's
slides go one by one here, as single images, to keep the smoke cheap). No Seedream call,
nothing written to R2 or the database: results go to `--out`.

What it reports (`report.json`, and a line per photo on stdout):
- schema-valid rate (a `LayerSpec` came out for the photo, after the one repair);
- repairs used;
- layout chosen against the catalog's «when to pick it» rule, checked from what Claude
  itself reported (`scrim` with the subject ending above 55 % / starting below 45 %; `plate`
  with its corner clear of `subject_box`; `info_card`/`brand_fill` only without a product);
- price never altered: a `price_ref` only to the case's priced product, and no figure in
  the free texts (`free_text_problems` is part of the schema: it is also counted);
- invented numbers: digits in any free text;
- the base check: `base_has_invented_text` against the human label of `scores.csv`
  (`a_invented_text`), when given.

    PYTHONPATH=packages/api/src:packages/shared/src:packages/creative/src \\
      uv run --no-sync python packages/api/evals/capa_texto/run.py \\
      --images <dir with jpgs> --out <dir> [--scores scores.csv] [--only F1 F4] \\
      [--limit 10] [--max-usd 0.5] [--env-file .env] [--dry-run]

Money: one `DollarMeter` over the whole run; the call that would cross `--max-usd` is
not sent. Every call is booked to an in-memory list (no ledger row, no business).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from qualify_api import claude_tools
from qualify_api.claude_tools import BudgetExhausted, DollarMeter
from qualify_api.creative.image_pipeline.layer import (
    FREE_IDEA,
    PRODUCT_PROMOTION,
    BusinessFacts,
    CatalogProduct,
    LayerError,
    LayerRequest,
    SlideInput,
    write_layers,
)

HERE = Path(__file__).parent
CASES = HERE.parent / "scene_text_v4" / "cases.json"
TENANT = UUID("00000000-0000-0000-0000-0000000000e1")
BRAND = UUID("00000000-0000-0000-0000-0000000000e2")
PRODUCT = CatalogProduct(UUID("00000000-0000-0000-0000-0000000000e3"), "Producto", True)
_NAME = re.compile(
    r"^(?P<case>[A-Z]\d+-[a-z0-9-]+?)(?:-s(?P<slide>\d+))?-r(?P<rep>\d+)-v(?P<v>\d+)"
)
_DIGIT = re.compile(r"\d")
_FORMATS = {"feed_4_5": "4:5", "feed_1_1": "1:1", "story_9_16": "9:16", "reels_9_16": "9:16"}


def _facts(case: dict[str, Any]) -> BusinessFacts:
    """The case's «Datos clave» as SAVED business data, by the catalog's kinds."""
    by_name = {name.lower(): value for name, value in case.get("highlights") or []}
    return BusinessFacts(
        location=by_name.get("dirección"),
        hours=by_name.get("horario"),
        contact=by_name.get("pedido") or by_name.get("domicilio"),
    )


def _env(path: Path) -> dict[str, str]:
    env = dict(os.environ)
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip() and not name.lstrip().startswith("#"):
                env.setdefault(name.strip(), value.strip().strip('"').strip("'"))
    return env


def _labels(path: Path | None) -> dict[str, str]:
    if path is None or not path.is_file():
        return {}
    with path.open(encoding="utf-8") as handle:
        return {row["job"]: row.get("a_invented_text", "") for row in csv.DictReader(handle)}


def _layout_rule(spec: Any, has_product: bool) -> str | None:
    """The catalog's «when to pick it», checked against what Claude reported. None = ok."""
    layout, photo = spec.layout_id.value, spec.photo
    if photo is None:
        return None
    x0, y0, x1, y1 = photo.subject_box
    if layout == "scrim":
        if spec.anchor.value == "bottom" and y1 > 0.55:
            return f"scrim bottom with subject to {y1}"
        if spec.anchor.value == "top" and y0 < 0.45:
            return f"scrim top with subject from {y0}"
    if layout == "plate" and spec.anchor is not None:
        anchor = spec.anchor.value
        corner = (
            (0.0 if "left" in anchor else 0.55 if "right" in anchor else 0.14, 0.0)
            if anchor.startswith("top")
            else (0.0 if "left" in anchor else 0.55 if "right" in anchor else 0.14, 0.72)
        )
        cx0, cy0 = corner
        cx1, cy1 = cx0 + 0.45, cy0 + 0.28
        if cx0 < x1 and x0 < cx1 and cy0 < y1 and y0 < cy1:
            return f"plate {anchor} over the subject {photo.subject_box}"
    if layout in ("info_card", "brand_fill") and has_product:
        return f"{layout} for a product photo"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--images", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--scores")
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-usd", default="0.5")
    parser.add_argument("--env-file", default=str(Path.cwd() / ".env"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cases = {c["id"]: c for c in json.loads(CASES.read_text(encoding="utf-8"))["cases"]}
    labels = _labels(Path(args.scores) if args.scores else None)
    photos = sorted(Path(args.images).glob("*.jpg"))
    jobs = []
    for path in photos:
        match = _NAME.match(path.stem)
        if not match or match["case"] not in cases:
            continue
        if args.only and not any(match["case"].startswith(o) for o in args.only):
            continue
        jobs.append((path, cases[match["case"]]))
    if args.limit:
        jobs = jobs[: args.limit]
    print(f"{len(jobs)} photos, one call each; ceiling US${args.max_usd}")
    if args.dry_run:
        for path, _ in jobs:
            print(f"  {path.name}")
        return 0
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    booked: list[Any] = []
    claude_tools.configure_consumption_sink(booked.append)  # no ledger row from an eval
    api_key = _env(Path(args.env_file)).get(claude_tools.API_KEY_ENV, "")
    if not api_key:
        print(f"{claude_tools.API_KEY_ENV} is not set", file=sys.stderr)
        return 2
    meter = DollarMeter(Decimal(args.max_usd))
    rows = []
    for path, case in jobs:
        has_product = bool(case.get("products"))
        request = LayerRequest(
            tenant_id=TENANT,
            brand_id=BRAND,
            format=_FORMATS.get(case["format"], "4:5"),
            piece_type=PRODUCT_PROMOTION if has_product else FREE_IDEA,
            slides=(SlideInput(position=0, photo=path.read_bytes()),),
            brand_name="Bianki",
            topic=case["topic"],
            scene=case["topic"],
            facts=_facts(case),
            products=(PRODUCT,) if has_product else (),
        )
        row: dict[str, Any] = {"photo": path.name, "case": case["id"]}
        try:
            result = write_layers(request, api_key=api_key, budget=meter)
        except BudgetExhausted:
            print("budget reached: stopping")
            break
        except LayerError as exc:
            row.update(valid=False, error=str(exc)[:300])
            rows.append(row)
            continue
        spec = result.specs.get(0)
        row.update(
            valid=spec is not None,
            repairs=result.repairs,
            failed=result.failed.get(0),
            cost_usd=result.stats.cost_usd if result.stats else None,
        )
        if spec is not None:
            texts = [t for t in (spec.title, spec.subtitle, spec.call_phrase) if t]
            row.update(
                layout=spec.layout_id.value,
                anchor=spec.anchor.value if spec.anchor else None,
                title=spec.title,
                subtitle=spec.subtitle,
                call_phrase=spec.call_phrase,
                info=[b.kind.value for b in spec.info_blocks],
                price_ok=spec.price_ref is None or spec.price_ref.product_id == PRODUCT.product_id,
                invented_numbers=sum(bool(_DIGIT.search(t)) for t in texts),
                layout_rule=_layout_rule(spec, has_product),
                subject_box=list(spec.photo.subject_box) if spec.photo else None,
                invented_text=spec.photo.base_has_invented_text if spec.photo else None,
                human_invented=labels.get(path.stem),
            )
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))
    valid = [r for r in rows if r.get("valid")]
    labelled = [r for r in valid if r.get("human_invented") in ("0", "1")]
    agree = sum(1 for r in labelled if str(int(r["invented_text"])) == r["human_invented"])
    report = {
        "photos": len(rows),
        "schema_valid": len(valid),
        "repairs": sum(r.get("repairs") or 0 for r in rows),
        "layout_rule_breaks": sum(1 for r in valid if r.get("layout_rule")),
        "price_altered": sum(1 for r in valid if not r.get("price_ok")),
        "invented_numbers": sum(r.get("invented_numbers") or 0 for r in valid),
        "invented_text_agreement": f"{agree}/{len(labelled)}",
        "spent_usd": str(meter.spent_usd),
        "calls": len(booked),
        "model": "claude-sonnet-5-5",
    }
    (out / "results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), "utf-8")
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

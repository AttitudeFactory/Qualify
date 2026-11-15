"""CAPA-002 (m-25017292) — the text layer (`capa-v2`) over ~30 stored base photos and three
whole carousels, one Claude call per piece, under a hard total cap.

Photos come from disk (`--images`: the Seedream bases of FOTO-BASE-001, m-25017279, named
`<case>[-s<slide>]-r<rep>-v<compiler>.jpg`; never committed). A few 4:5 bases are cut to a
centred square for the 1:1 format, into `--out` (an eval input, not a composition). Briefs
come from `../scene_text_v4/cases.json`; the case's «Datos clave» become saved business
data. No Seedream call, nothing written to R2 or the database.

Money: a run-wide total (`--max-usd`, default US$1.00) and the production per-piece cap
(US$0.25). Each piece gets a `DollarMeter` of min(US$0.25, what the total has left), so
the call that would cross the total is refused before it is sent; the run stops when what
is left cannot pay one worst-case turn.

Per piece it records: valid layer per slide, repair turn, the rule that asked for the
repair (from every `spec_from_answer` refusal, tagged by turn), slides dropped after the
repair, latency, tokens, dollars, and every text with its layout. `results.jsonl` holds
one line per piece; `report.json` the totals.

    PYTHONPATH=packages/api/src:packages/shared/src:packages/creative/src \\
      uv run --no-sync python packages/api/evals/capa_texto/capa_002.py \\
      --images <dir> --out <dir> [--max-usd 1.0] [--env-file .env] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from qualify_api import claude_tools
from qualify_api.claude_tools import BudgetExhausted, DollarMeter
from qualify_api.creative.image_pipeline import layer
from qualify_api.creative.image_pipeline.layer import (
    CAROUSEL,
    FREE_IDEA,
    LAYER_BUDGET_USD,
    LAYER_PROMPT_VERSION,
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
_FORMATS = {"feed_4_5": "4:5", "feed_1_1": "1:1", "story_9_16": "9:16", "reels_9_16": "9:16"}
#: catalog product names; the ones with a saved price the layer may point at
_PRODUCTS = {
    "shawarma_carne": ("Shawarma de carne", True),
    "shawarma_pollo": ("Shawarma de pollo", True),
    "combo_carne": ("Combo de shawarma de carne", True),
    "salchipapa": ("Salchipapa", False),
    "papas": ("Papas para compartir", False),
}
#: the worst a single turn can bill at Sonnet 5.5 list price (US$2/US$10 per Mtok):
#: ~15 k input tokens (a 6-photo carousel) + 4 k output — below it the run stops
WORST_TURN_USD = Decimal("0.08")

# -- the plan: 30 single images and 3 carousels ------------------------------------------

#: CAPA-001's ten, as they were
CAPA_001 = [
    "F1-ubicacion-r1-v4",
    "F1-ubicacion-r1-v5",
    "F2-te-espera-r1-v4",
    "F3-horario-r1-v5",
    "F4-combo-r1-v5",
    "F5-ensalada-escena-r1-v5",
    "F7-pollo-2x1-r1-v5",
    "F8-papas-compartir-r1-v5",
    "G1-combo-galeria-s2-r1-v5",
    "G2-salchipapa-galeria-s1-r1-v4",
]
#: sixteen more bases of the same run (second repetition, the other compiler, F6)
MORE = [
    "F1-ubicacion-r2-v5",
    "F2-te-espera-r2-v5",
    "F3-horario-r2-v5",
    "F4-combo-r2-v5",
    "F5-ensalada-escena-r2-v5",
    "F6-domicilio-logo-r1-v5",
    "F6-domicilio-logo-r2-v5",
    "F7-pollo-2x1-r2-v5",
    "F8-papas-compartir-r2-v5",
    "F2-te-espera-r1-v5",
    "F3-horario-r1-v4",
    "F4-combo-r1-v4",
    "F5-ensalada-escena-r1-v4",
    "F6-domicilio-logo-r1-v4",
    "F7-pollo-2x1-r1-v4",
    "F8-papas-compartir-r1-v4",
]
#: 4:5 bases cut to a centred square: the 1:1 format
SQUARE = [
    "F4-combo-r2-v4",
    "F5-ensalada-escena-r2-v4",
    "F7-pollo-2x1-r2-v4",
    "G1-combo-galeria-s1-r2-v4",
]
#: pieces asked as «Otra idea» with the business's data, so info_card/brand_fill may fit
DATA_PIECES = {"F1-ubicacion-r2-v5", "F3-horario-r2-v5", "F6-domicilio-logo-r2-v5"}
#: whole carousels, ONE call each
CAROUSELS = {
    "G1-combo-galeria": [
        "G1-combo-galeria-s1-r1-v4",
        "G1-combo-galeria-s2-r1-v4",
        "G1-combo-galeria-s1-r1-v5",
        "G1-combo-galeria-s2-r2-v5",
        "G1-combo-galeria-s1-r2-v5",
        "G1-combo-galeria-s2-r2-v4",
    ],
    "G2-salchipapa-galeria": [
        "G2-salchipapa-galeria-s1-r1-v5",
        "G2-salchipapa-galeria-s2-r1-v4",
        "G2-salchipapa-galeria-s1-r2-v4",
        "G2-salchipapa-galeria-s2-r1-v5",
        "G2-salchipapa-galeria-s1-r2-v5",
    ],
    "G3-galeria-datos": [
        "G3-galeria-datos-s1-r1-v4",
        "G3-galeria-datos-s2-r1-v4",
        "G3-galeria-datos-s1-r1-v5",
        "G3-galeria-datos-s2-r1-v5",
        "G3-galeria-datos-s1-r2-v4",
        "G3-galeria-datos-s2-r2-v4",
        "G3-galeria-datos-s1-r2-v5",
        "G3-galeria-datos-s2-r2-v5",
    ],
}
_CASE = re.compile(r"^(?P<case>[A-Z]\d+-[a-z0-9-]+?)(?:-s\d+)?-r\d+-v\d+$")


def _case_of(stem: str) -> str:
    match = _CASE.match(stem)
    assert match, stem
    return match["case"]


def _facts(case: dict[str, Any], *, payment: bool) -> BusinessFacts:
    """The case's «Datos clave» as saved business data, by the catalog's kinds."""
    by_name = {name.lower(): value for name, value in case.get("highlights") or []}
    return BusinessFacts(
        location=by_name.get("dirección"),
        hours=by_name.get("horario"),
        contact=by_name.get("pedido") or by_name.get("domicilio"),
        payment="Efectivo · Nequi" if payment else None,
    )


def _products(case: dict[str, Any]) -> tuple[CatalogProduct, ...]:
    return tuple(
        CatalogProduct(uuid5(BRAND, key), _PRODUCTS[key][0], _PRODUCTS[key][1])
        for key in case.get("products") or []
        if key in _PRODUCTS
    )


def _square(src: Path, dest: Path) -> Path:
    from PIL import Image  # noqa: PLC0415 - eval input only

    with Image.open(src) as image:
        side = min(image.size)
        left, top = (image.width - side) // 2, (image.height - side) // 2
        image.crop((left, top, left + side, top + side)).save(dest, quality=92)
    return dest


def plan(
    images: Path, out: Path, cases: dict[str, Any], *, write: bool = True
) -> list[dict[str, Any]]:
    """The pieces to run. `write=False` (a dry run) names the square crops but writes
    nothing to disk."""
    pieces = []
    squares = out / "square-inputs"
    if write:
        squares.mkdir(parents=True, exist_ok=True)
    for stem in CAPA_001 + MORE + SQUARE:
        case = cases[_case_of(stem)]
        fmt = _FORMATS.get(case["format"], "4:5")
        photo = images / f"{stem}.jpg"
        source = "CAPA-001" if stem in CAPA_001 else "m-25017279 (FOTO-BASE-001)"
        if stem in SQUARE:
            square = squares / f"{stem}-1x1.jpg"
            photo, fmt = (_square(photo, square) if write else square), "1:1"
            source = "m-25017279, cut to 1:1"
        data = stem in DATA_PIECES
        pieces.append(
            {
                "id": stem + ("-1x1" if stem in SQUARE else ""),
                "case": case["id"],
                "format": fmt,
                "piece_type": FREE_IDEA if data or not case.get("products") else PRODUCT_PROMOTION,
                "photos": [photo],
                "source": source,
                "data": data,
                "logo_in_case": bool(case.get("logo")),
            }
        )
    for case_id, stems in CAROUSELS.items():
        case = cases[case_id]
        pieces.append(
            {
                "id": f"{case_id}-carrusel-{len(stems)}",
                "case": case_id,
                "format": _FORMATS.get(case["format"], "4:5"),
                "piece_type": CAROUSEL,
                "photos": [images / f"{s}.jpg" for s in stems],
                "source": "m-25017279 (FOTO-BASE-001)",
                "data": True,
                "logo_in_case": bool(case.get("logo")),
            }
        )
    # the carousels first: never measured before, they must not be the ones the cap cuts
    return [p for p in pieces if p["piece_type"] == CAROUSEL] + [
        p for p in pieces if p["piece_type"] != CAROUSEL
    ]


# -- what a refusal was about -------------------------------------------------------------


def rule_of(message: str) -> str:
    text = message.lower()
    if "malformed" in text:
        return "malformed"
    if "price figure" in text or "currency" in text:
        return "price in free text"
    if "with a price" in text:
        return "price_ref to an unpriced product"
    if "is not in the brief" in text:
        return "unsupported claim"
    if "is a label" in text:
        return "forbidden title"
    if "at most" in text or "lines" in text:
        return "length"
    if "no layer for this image" in text:
        return "missing slide"
    if "is not one of" in text or "closing slide" in text:
        return "layout not allowed for the piece/role"
    if "takes no" in text or "only without" in text:
        return "layout parameter"
    if "no saved" in text:
        return "info block without data"
    return "other"


class Watch:
    """Counts the turns and keeps every `spec_from_answer` refusal with its turn."""

    def __init__(self) -> None:
        self.turn = 0
        self.refusals: list[tuple[int, int, str]] = []
        self._create_turn = layer.create_turn
        self._spec = layer.spec_from_answer

    def install(self) -> None:
        def create_turn(*args: Any, **kwargs: Any) -> Any:
            self.turn += 1
            return self._create_turn(*args, **kwargs)

        def spec(raw: dict[str, Any], request: Any, slide: Any) -> Any:
            try:
                return self._spec(raw, request, slide)
            except ValueError as exc:
                self.refusals.append((self.turn, slide.position, str(exc)))
                raise

        layer.create_turn = create_turn
        layer.spec_from_answer = spec

    def reset(self) -> None:
        self.turn, self.refusals = 0, []


def _env(path: Path) -> dict[str, str]:
    env = dict(os.environ)
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip() and not name.lstrip().startswith("#"):
                env.setdefault(name.strip(), value.strip().strip('"').strip("'"))
    return env


def _texts(spec: Any) -> dict[str, Any]:
    return {
        "layout": spec.layout_id.value,
        "anchor": spec.anchor.value if spec.anchor else None,
        "title": spec.title,
        "subtitle": spec.subtitle,
        "call_phrase": spec.call_phrase,
        "info": [b.kind.value for b in spec.info_blocks],
        "price_ref": bool(spec.price_ref),
        "role": spec.carousel.role.value if spec.carousel else None,
        "invented_text": spec.photo.base_has_invented_text if spec.photo else None,
        "spec": spec.model_dump(mode="json"),  # what the render composes (contact sheet)
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--images", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-usd", default="1.00")
    parser.add_argument("--env-file", default=str(Path.cwd() / ".env"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", nargs="*", help="piece ids to run (default: all)")
    args = parser.parse_args()

    cases = {c["id"]: c for c in json.loads(CASES.read_text(encoding="utf-8"))["cases"]}
    out = Path(args.out)
    pieces = plan(Path(args.images), out, cases, write=not args.dry_run)
    if args.only:
        pieces = [p for p in pieces if p["id"] in args.only]
    slides = sum(len(p["photos"]) for p in pieces)
    print(f"{len(pieces)} pieces, {slides} photos; total ceiling US${args.max_usd}")
    if args.dry_run:
        for piece in pieces:
            print(f"  {piece['id']} {piece['format']} {piece['piece_type']} {len(piece['photos'])}")
        return 0
    api_key = _env(Path(args.env_file)).get(claude_tools.API_KEY_ENV, "")
    if not api_key:
        print("No Anthropic key in the environment or --env-file.", file=sys.stderr)
        return 2
    booked: list[Any] = []
    claude_tools.configure_consumption_sink(booked.append)  # no ledger row from an eval
    watch = Watch()
    watch.install()
    total = Decimal(args.max_usd)
    spent = Decimal(0)
    rows: list[dict[str, Any]] = []
    results = (out / "results.jsonl").open("w", encoding="utf-8")
    for piece in pieces:
        left = total - spent
        if left < WORST_TURN_USD:
            print(f"total cap: US${left} left, stopping before {piece['id']}")
            break
        case = cases[piece["case"]]
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
            products=_products(case),
        )
        meter = DollarMeter(min(LAYER_BUDGET_USD, left))
        watch.reset()
        row: dict[str, Any] = {k: v for k, v in piece.items() if k not in ("photos",)} | {
            "photos": [Path(p).name for p in piece["photos"]]
        }
        started = time.perf_counter()
        try:
            result = write_layers(request, api_key=api_key, budget=meter)
        except (LayerError, BudgetExhausted) as exc:
            row.update(error=str(exc)[:300], valid_slides=0, slides=len(piece["photos"]))
            result = None
        row["seconds"] = round(time.perf_counter() - started, 2)
        spent += meter.spent_usd
        row["usd"] = str(meter.spent_usd)
        row["refusals"] = [
            {"turn": t, "position": p, "rule": rule_of(m), "message": m[:300]}
            for t, p, m in watch.refusals
        ]
        row["repair_rules"] = sorted({rule_of(m) for t, _, m in watch.refusals if t == 1})
        if result is not None:
            stats = result.stats
            row.update(
                slides=len(piece["photos"]),
                valid_slides=len(result.specs),
                repaired=bool(result.repairs),
                dropped=sorted(result.failed),
                failed=result.failed,
                turns=stats.turns if stats else None,
                input_tokens=stats.input_tokens if stats else None,
                output_tokens=stats.output_tokens if stats else None,
                layers={str(p): _texts(s) for p, s in sorted(result.specs.items())},
            )
        rows.append(row)
        results.write(json.dumps(row, ensure_ascii=False) + "\n")
        results.flush()
        print(
            f"{row['id']}: {row.get('valid_slides')}/{row.get('slides')} valid, "
            f"repair={row.get('repaired')} {row['repair_rules']}, {row['seconds']} s, "
            f"US${row['usd']} (total US${spent})"
        )
    results.close()
    singles = [r for r in rows if r["piece_type"] != CAROUSEL]
    carousels = [r for r in rows if r["piece_type"] == CAROUSEL]

    def pct(values: list[float], q: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]

    seconds = [r["seconds"] for r in singles]
    report = {
        "prompt_version": LAYER_PROMPT_VERSION,
        "model": layer.LAYER_MODEL.model_id,
        "pieces": len(rows),
        "planned_pieces": len(pieces),
        "singles": len(singles),
        "single_valid": sum(1 for r in singles if r.get("valid_slides") == r.get("slides")),
        "single_repaired": sum(1 for r in singles if r.get("repaired")),
        "carousels": [
            {
                "id": r["id"],
                "slides": r.get("slides"),
                "valid": r.get("valid_slides"),
                "seconds": r["seconds"],
                "usd": r["usd"],
                "repaired": r.get("repaired"),
            }
            for r in carousels
        ],
        "repair_rules": {
            rule: sum(1 for r in rows if rule in r["repair_rules"])
            for rule in sorted({x for r in rows for x in r["repair_rules"]})
        },
        "dropped_slides": sum(len(r.get("dropped") or []) for r in rows),
        "single_seconds_p50": statistics.median(seconds) if seconds else None,
        "single_seconds_p95": pct(seconds, 0.95),
        "input_tokens": sum(r.get("input_tokens") or 0 for r in rows),
        "output_tokens": sum(r.get("output_tokens") or 0 for r in rows),
        "spent_usd": str(spent),
        "calls_booked": len(booked),
    }
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

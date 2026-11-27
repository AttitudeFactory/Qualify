# ruff: noqa: E501
"""RECORTE-001 (spike m-25042530): re-render SISVIS-002 product pieces with the cut-out product.

Before: the phone photo inside the proposal's frame (disc, rounded box...). After: the cut-out
product over a flat brand disc, filling the product area like Bianki's recipes. Everything the
template needs comes as DATA, no template change:

- the cut-out is cropped to its alpha bounding box (Pillow only crops/saves: format work, the
  composition stays in Remotion) and saved next to the brand assets;
- ``components.product_frame.variant`` becomes ``cutout_sun`` so ``ProductBlock`` draws the
  transparent PNG instead of a framed photo;
- the recipe gets one ``sun`` block with both colours equal (a flat disc) where the old frame was,
  in the proposal's own ``product_frame.glow`` role, behind the product;
- the product slot carries ``box``: the product area widened by ``--grow`` around the recipe's
  product box, and the cut-out fitted inside it from its alpha bbox aspect, bottom-aligned
  (``ProductBlock`` draws a cut-out at the box width with natural height, so the box height must
  follow the cut-out's aspect).

It writes the system/content copies, ``jobs.json`` for ``packages/render/scripts/brand-still-batch.mjs``
and ``sheet.jobs.json`` + ``sheet.props.json`` for a before/after contact sheet.

    <venv>/bin/python packages/api/evals/sistema_visual/recorte_render.py \
        --sisvis <business dir of SISVIS-002> --public <its _public dir> --brand-dir <name in _public> \
        --cutout product_hero=<rgba.png> --cutout product_alt=<rgba.png> \
        --proposal fable/p2 --proposal opus/p3 --out <dir>

Local only; client data never enters the repo.
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
from pathlib import Path

from PIL import Image

PORT_WH = {"4:5": (1080, 1350), "1:1": (1080, 1080), "9:16": (1080, 1920)}


def crop_to_alpha(src: Path, dst: Path, pad: float = 0.01) -> tuple[int, int]:
    im = Image.open(src).convert("RGBA")
    a = im.getchannel("A").point(lambda v: 255 if v > 127 else 0)
    bbox = a.getbbox()
    if bbox is None:
        raise SystemExit(f"{src}: empty alpha")
    px = int(pad * max(im.size))
    x0, y0, x1, y1 = bbox
    box = (max(0, x0 - px), max(0, y0 - px), min(im.width, x1 + px), min(im.height, y1 + px))
    out = im.crop(box)
    dst.parent.mkdir(parents=True, exist_ok=True)
    out.save(dst)
    return out.size


def fit_box(area: list[float], size: tuple[int, int], fmt: str) -> list[float]:
    """Fit a cut-out of ``size`` px inside ``area`` (fractions of W, H), centred, bottom-aligned."""
    W, H = PORT_WH[fmt]
    ax, ay, aw, ah = area
    ar = size[1] / size[0]  # height / width in px
    w = min(aw, ah * H / (ar * W))
    h = w * W * ar / H
    return [round(ax + (aw - w) / 2, 5), round(ay + ah - h, 5), round(w, 5), round(h, 5)]


def grow(box: list[float], k: float) -> list[float]:
    """Widen the product area by ``k`` around its centre; vertically only a small margin, so the
    cut-out never climbs into the headline above or the price below (first try grew both ways
    and the bottle caps covered the headline)."""
    x, y, w, h = box
    cx = x + w / 2
    w2 = w * k
    x2 = max(0.02, cx - w2 / 2)
    return [x2, max(0.0, y - 0.015), min(w2, 0.98 - x2), h + 0.025]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sisvis", required=True, type=Path)
    ap.add_argument("--public", required=True, type=Path)
    ap.add_argument("--brand-dir", required=True)
    ap.add_argument("--cutout", action="append", required=True, help="recipe=path.png")
    ap.add_argument("--proposal", action="append", required=True, help="fable/p2")
    ap.add_argument("--grow", type=float, default=1.3)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    out = a.out.resolve()
    pub = out / "_public"
    shutil.copytree(a.public, pub, dirs_exist_ok=True)
    cutouts = {}
    for spec in a.cutout:
        recipe, path = spec.split("=", 1)
        rel = f"{a.brand_dir}/recorte-{recipe}.png"
        cutouts[recipe] = (rel, crop_to_alpha(Path(path), pub / rel))
    jobs, rows = [], []
    for prop in a.proposal:
        system = json.loads((a.sisvis / f"{prop}.system.json").read_text())
        tag = prop.replace("/", "-")
        before, after = [], []
        for recipe, (rel, size) in cutouts.items():
            r = system["recipes"][recipe]
            fmt = r["format"]
            W, H = PORT_WH[fmt]
            sys2 = copy.deepcopy(system)
            pf = sys2["components"].setdefault("product_frame", {})
            pf["variant"] = "cutout_sun"
            blocks = sys2["recipes"][recipe]["blocks"]
            prod = next(b for b in blocks if b["type"] == "product")
            area = grow(prod["box"], a.grow)
            box = fit_box(area, size, fmt)
            # flat disc, square in pixels, centred on the product area, a bit under its top
            d = min(area[2] * W, area[3] * H) * 0.92
            cx, cy = (area[0] + area[2] / 2) * W, (area[1] + area[3] * 0.52) * H
            disc_role = pf.get("glow") or "accent"
            blocks.append(
                {
                    "type": "sun",
                    "box": [
                        round((cx - d / 2) / W, 5),
                        round((cy - d / 2) / H, 5),
                        round(d / W, 5),
                        round(d / H, 5),
                    ],
                    "z": max(1, prod.get("z", 2) - 1),
                    "colors": [disc_role, disc_role, disc_role],
                }
            )
            prod["z"] = max(prod.get("z", 2), 2) + 1
            content = json.loads((a.sisvis / f"{prop}.{recipe}.content.json").read_text())
            content["product"].update({"photo": rel, "cutout": True, "box": box})
            sys_path = out / f"{tag}.{recipe}.system.json"
            con_path = out / f"{tag}.{recipe}.content.json"
            sys_path.write_text(json.dumps(sys2, ensure_ascii=False, indent=1))
            con_path.write_text(json.dumps(content, ensure_ascii=False, indent=1))
            png = out / f"{tag}-{recipe}.png"
            jobs.append(
                {
                    "system": str(sys_path),
                    "recipe": recipe,
                    "content": str(con_path),
                    "out": str(png),
                }
            )
            src_before = a.sisvis / f"{prop.split('/')[0]}/{prop.split('/')[1]}-{recipe}.png"
            shutil.copy(src_before, out / f"antes-{tag}-{recipe}.png")
            before.append({"src": f"antes-{tag}-{recipe}.png", "cellH": 500})
            after.append({"src": f"{tag}-{recipe}.png", "cellH": 500})
        rows.append(
            {
                "label": f"{system['name']} · antes",
                "note": "foto del teléfono dentro del marco de la propuesta (SISVIS-002)",
                "cells": before,
            }
        )
        rows.append(
            {
                "label": f"{system['name']} · después",
                "note": "recorte birefnet-general-lite sobre un disco plano de la marca; caja del producto desde el bbox del alfa",
                "cells": after,
            }
        )
    (out / "jobs.json").write_text(json.dumps({"publicDir": str(pub), "jobs": jobs}, indent=1))
    props = {
        "title": "RECORTE-001 · negocio 1 · antes y después",
        "subtitle": "Misma propuesta, mismos datos; solo cambia la foto: recorte local (birefnet-general-lite, CPU) sobre el disco de la marca",
        "cell": {"w": 400, "h": 500},
        "columns": ["Producto estrella (4:5)", "Segundo producto (4:5)"],
        "rows": rows,
    }
    (out / "sheet.props.json").write_text(json.dumps(props, ensure_ascii=False, indent=1))
    (out / "sheet.jobs.json").write_text(
        json.dumps(
            {
                "publicDir": str(out),
                "jobs": [
                    {
                        "composition": "brand-still-contact-sheet",
                        "props": str(out / "sheet.props.json"),
                        "out": str(out / "antes-despues.jpg"),
                    }
                ],
            },
            indent=1,
        )
    )
    print(f"{len(jobs)} jobs -> {out / 'jobs.json'}")


if __name__ == "__main__":
    main()

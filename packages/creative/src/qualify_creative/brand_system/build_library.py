"""Build the team-owned recipe library v1 from the geometries that exist (spike m-25042530).

Seeds: Bianki's transcribed recipes (v0, `packages/api/evals/sistema_visual/bianki/system.v1.json`)
and the three Polette proposals of SISVIS-001 (`.../polette/out/20261117T044842Z/`). Each recipe is
normalized so an AI proposal can only POINT at it:

- literal hex inside blocks -> the nearest colour role of the system it came from;
- literal tag text -> ``{{tag}}`` (filled at compose time from the proposal's tone tags);
- product blocks read the ``product`` object (photo + cutout flag), never a bare photo path;
- background overrides are dropped (the background is the proposal's choice), except "no layers"
  under a full photo, kept as ``{"base": "radial", "layers": []}``.

    PYTHONPATH=packages/creative/src python -m qualify_creative.brand_system.build_library
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent
EVALS = HERE.parents[3] / "api" / "evals" / "sistema_visual"
OUT = HERE / "recipe_library.v1.json"
ROLES = (
    "background",
    "background_alt",
    "surface",
    "on_surface",
    "ink",
    "accent",
    "on_accent",
    "shadow",
    "pop",
)
ALIASES = {"background_edge": "background", "shadow_deep": "shadow"}

SEEDS = [
    (
        "bianki",
        EVALS / "bianki" / "system.v1.json",
        {"product_hero": "product_hero", "hours": "hours", "story": "story"},
    ),
    *[
        (
            f"polette-{n}",
            EVALS / "polette" / "out" / "20261117T044842Z" / f"propuesta-{n}.system.json",
            {"product_hero": "product_hero", "hours": "hours", "story": "story"},
        )
        for n in (1, 2, 3)
    ],
]


def _rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def _nearest_role(hexv: str, colors: dict[str, str]) -> str:
    target = _rgb(hexv)
    best, dist = "shadow", 1e9
    for role, val in colors.items():
        if not val or not str(val).startswith("#"):
            continue
        d = sum((a - b) ** 2 for a, b in zip(target, _rgb(val), strict=True))
        if d < dist:
            best, dist = ALIASES.get(role, role), d
    return best if best in ROLES else "shadow"


def _normalize(obj: object, colors: dict[str, str]) -> object:
    if isinstance(obj, dict):
        out: dict = {}
        for k, v in obj.items():
            if k == "text" and isinstance(v, str) and v:
                out[k] = "{{tag}}"
            elif k == "slot" and v == "product.photo":
                out[k] = "product"
            elif k == "box" or k == "focus" or k == "center":
                out[k] = v
            else:
                out[k] = _normalize(v, colors)
        return out
    if isinstance(obj, list):
        return [_normalize(x, colors) for x in obj]
    if isinstance(obj, str) and obj.startswith("#") and len(obj) in (7, 9):
        return _nearest_role(obj[:7], colors)
    return obj


def _requires(recipe: dict) -> list[str]:
    slots: set[str] = set()

    def walk(o: object) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "slot" and v:
                    slots.add(v)
                walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(recipe)
    # hard requirements: a photo slot must exist, everything else degrades (missing text is skipped)
    return sorted(s for s in slots if s in {"place_photo", "story.photo", "product"})


def build() -> dict:
    variants: list[dict] = []
    for origin, path, pieces in SEEDS:
        system = json.loads(path.read_text())
        colors = {k: v for k, v in system["colors"].items() if v}
        for piece, rid in pieces.items():
            rec = system["recipes"].get(rid)
            if not rec:
                continue
            bg = rec.get("background")
            keep_bg = (
                {"base": "radial", "layers": []}
                if bg is not None and not bg.get("layers")
                else None
            )
            norm = {
                "format": rec["format"],
                "background": keep_bg,
                "blocks": _normalize(rec["blocks"], colors),
            }
            kinds = [b["type"] for b in rec["blocks"]]
            variants.append(
                {
                    "id": f"{piece}.{origin}",
                    "piece": piece,
                    "format": rec["format"],
                    "origin": f"{origin}:{system['id']} v{system['version']}",
                    "summary": ", ".join(dict.fromkeys(kinds)),
                    "requires": _requires(norm),
                    "recipe": norm,
                }
            )
    return {
        "library_version": 1,
        "built": "2026-11-26",
        "spike": "m-25042530",
        "variants": variants,
    }


if __name__ == "__main__":
    lib = build()
    OUT.write_text(json.dumps(lib, ensure_ascii=False, indent=1) + "\n")
    for v in lib["variants"]:
        print(v["id"], v["format"], v["requires"], "|", v["summary"])

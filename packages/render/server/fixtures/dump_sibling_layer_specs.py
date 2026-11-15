"""Regenerates `layer-spec-v1-sibling.json`: real `LayerSpec.model_dump(mode="json")` output of
the layer stage's schema (m-25017283, `qualify_creative.layer_spec`), which
`server/layer-still.test.mjs` runs through the render's boundary check (`spec.mjs`) and engine.

Until that branch is merged its package is not importable here, so point this script at a copy:

    git fetch origin feat/m-25017283-capa-de-texto
    git archive --format=tar -o /tmp/ls.tar FETCH_HEAD \\
        packages/creative/src/qualify_creative/layer_spec
    mkdir -p /tmp/ls && tar -xf /tmp/ls.tar -C /tmp/ls
    python -I packages/render/server/fixtures/dump_sibling_layer_specs.py \\
        /tmp/ls/packages/creative/src "$(git rev-parse --short FETCH_HEAD)"

Once it is merged: run it with `packages/creative/src` and the main sha (or replace the fixture
with a test that imports `qualify_creative.layer_spec` directly). Writes next to this file.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

src, sha = Path(sys.argv[1]), sys.argv[2]
pkg = types.ModuleType("qualify_creative")
pkg.__path__ = [str(src / "qualify_creative")]
sys.modules["qualify_creative"] = pkg
from qualify_creative.layer_spec.schema import LayerSpec  # noqa: E402

photo = {
    "subject_box": [0.25, 0.4, 0.75, 0.8],
    "logo_in_photo": False,
    "base_has_invented_text": False,
}
product = {"product_id": "00000000-0000-4000-8000-000000000001"}
specs = [
    {
        "layout_id": "plate",
        "format": "4:5",
        "photo": photo,
        "anchor": "top_left",
        "container_color": "surface",
        "accent_word": 1,
        "title": "Tu pan, recién horneado",
        "subtitle": "Masa madre de la casa",
        "price_ref": product,
    },
    {
        "layout_id": "scrim",
        "format": "1:1",
        "photo": photo,
        "anchor": "bottom",
        "title": "Así se ve el almuerzo",
    },
    {
        "layout_id": "band",
        "format": "4:5",
        "photo": photo,
        "anchor": "bottom",
        "container_color": "accent",
        "title": "Amasado a mano",
        "carousel": {"role": "body", "index": 1, "count": 3},
    },
    {
        "layout_id": "info_card",
        "format": "4:5",
        "container_color": "surface",
        "title": "Te esperamos",
        "info_blocks": [
            {"kind": "location", "label": "Dónde estamos", "value": "Calle 10 # 4-25"},
            {"kind": "hours", "label": "Horario", "value": "Lunes a sábado de 7 a 20"},
        ],
    },
    {
        "layout_id": "brand_fill",
        "format": "4:5",
        "container_color": "accent",
        "title": "Te esperamos hoy",
        "call_phrase": "Pídelo por WhatsApp",
        "info_blocks": [{"kind": "contact", "label": "Pedidos", "value": "300 123 4567"}],
        "carousel": {"role": "closing", "index": 2, "count": 3},
    },
    # brand_fill 1:1 value of 45–60 chars: both catalogs say 60 (catalog §1.5)
    {
        "layout_id": "brand_fill",
        "format": "1:1",
        "container_color": "accent",
        "title": "Te esperamos",
        "info_blocks": [
            {
                "kind": "location",
                "label": "Dónde estamos",
                "value": "Calle 10 # 4-25, local 3, frente al parque principal",
            }
        ],
    },
    {
        "layout_id": "highlight_circle",
        "format": "9:16",
        "container_color": "accent",
        "highlight_content": {"kind": "word", "word": "Domicilio"},
    },
    {"layout_id": "photo_only", "format": "9:16", "photo": photo},
]
out = [json.loads(LayerSpec.model_validate(raw).model_dump_json()) for raw in specs]
target = Path(__file__).with_name("layer-spec-v1-sibling.json")
target.write_text(
    json.dumps(
        {
            "_source": (
                "LayerSpec.model_dump_json() of qualify_creative.layer_spec.schema on "
                f"origin/feat/m-25017283-capa-de-texto @ {sha}. Regenerate with "
                "server/fixtures/dump_sibling_layer_specs.py when that schema changes."
            ),
            "specs": out,
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
print(f"{len(out)} specs → {target}")

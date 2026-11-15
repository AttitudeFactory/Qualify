"""REGLAS-001 (m-25017292): precision and recall of the text layer's two free-text rules on
`reglas_set.json` — no model call, no cost.

- price: `free_text_problems(text)` reports «currency» or «price figure»;
- claim: `unsupported_claims(text, request)` reports anything, with the row's context as the
  piece's brief, saved data and product names.

    PYTHONPATH=packages/api/src:packages/shared/src:packages/creative/src \\
      uv run --no-sync python packages/api/evals/capa_texto/reglas_eval.py [--split test] [--misses]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from uuid import UUID

from qualify_creative.layer_spec import free_text_problems

from qualify_api.creative.image_pipeline.layer import (
    PRODUCT_PROMOTION,
    BusinessFacts,
    CatalogProduct,
    LayerRequest,
    unsupported_claims,
)

SET = Path(__file__).with_name("reglas_set.json")
_PRICE = {"currency", "price figure"}
_ID = UUID("00000000-0000-0000-0000-0000000000e1")


def rows() -> list[dict[str, Any]]:
    return json.loads(SET.read_text("utf-8"))["rows"]


def request_of(context: dict[str, Any]) -> LayerRequest:
    facts = context.get("facts") or {}
    return LayerRequest(
        tenant_id=_ID,
        brand_id=_ID,
        format="4:5",
        piece_type=PRODUCT_PROMOTION,
        slides=(),
        topic=context.get("topic", ""),
        scene=context.get("scene", ""),
        hook=context.get("hook", ""),
        cta=context.get("cta", ""),
        facts=BusinessFacts(**facts),
        products=tuple(
            CatalogProduct(UUID(int=i + 1), name, True)
            for i, name in enumerate(context.get("products") or [])
        ),
    )


def flags(row: dict[str, Any]) -> dict[str, bool]:
    return {
        "price": bool(_PRICE & set(free_text_problems(row["text"]))),
        "claim": bool(unsupported_claims(row["text"], request_of(row["context"]))),
    }


def score(selected: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for rule in ("price", "claim"):
        tp, fp, fn = [], [], []
        for r in selected:
            human = bool(r[rule])
            said = flags(r)[rule]
            if said and human:
                tp.append(r)
            elif said:
                fp.append(r)
            elif human:
                fn.append(r)
        flagged, positives = len(tp) + len(fp), len(tp) + len(fn)
        out[rule] = {
            "positives": positives,
            "flagged": flagged,
            "precision": round(len(tp) / flagged, 3) if flagged else None,
            "recall": round(len(tp) / positives, 3) if positives else None,
            "false_positives": [_show(r) for r in fp],
            "false_negatives": [_show(r) for r in fn],
        }
    return out


def _show(r: dict[str, Any]) -> str:
    kind = f" [{r['claim']}]" if r.get("claim") else ""
    return f"#{r['id']} «{r['text']}»{kind} ({r['source']})"


def real_output_cost(selected: list[dict[str, Any]]) -> dict[str, Any]:
    """On the model's real texts (CAPA): how many clean ones a rule would send to repair."""
    capa = [r for r in selected if r["source"].startswith("capa")]
    clean = [r for r in capa if not r["price"] and not r["claim"]]
    sent = [r for r in clean if any(flags(r).values())]
    return {
        "real_texts": len(capa),
        "clean": len(clean),
        "sent_to_repair": [_show(r) for r in sent],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", choices=["dev", "test", "all"], default="test")
    parser.add_argument("--misses", action="store_true")
    args = parser.parse_args()
    data = rows()
    selected = data if args.split == "all" else [r for r in data if r["split"] == args.split]
    result = score(selected)
    for rule, s in result.items():
        print(
            f"{rule}: n={len(selected)} positives={s['positives']} flagged={s['flagged']} "
            f"precision={s['precision']} recall={s['recall']}"
        )
        if args.misses:
            for line in s["false_positives"]:
                print(f"  FP {line}")
            for line in s["false_negatives"]:
                print(f"  FN {line}")
    cost = real_output_cost(data)
    print(
        f"real CAPA texts: {cost['real_texts']}, clean {cost['clean']}, "
        f"sent to repair {len(cost['sent_to_repair'])}"
    )
    if args.misses:
        for line in cost["sent_to_repair"]:
            print(f"  REPAIR {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

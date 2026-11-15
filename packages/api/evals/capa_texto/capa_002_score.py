"""CAPA-002 (m-25017292) — offline scoring of a `capa_002.py` run: no model call.

1. The two free-text rules (`free_text_problems` price figures/currency, and
   `unsupported_claims`) over every title, subtitle and call phrase the run produced, against
   the human labels in `labels_002.json` (an invented price, promotion, day/hours or
   delivery claim, given the piece's brief): precision, recall, every miss verbatim.
2. The known leaks and false rejections of PR #674 «Antes de encender», as a probe table.
3. Copy quick read: business name in a title, «usted»/«vos» forms, English words, texts
   above two thirds of their slot limit.

    PYTHONPATH=packages/api/src:packages/shared/src:packages/creative/src \\
      uv run --no-sync python packages/api/evals/capa_texto/capa_002_score.py --run <out dir>
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from qualify_creative.layer_spec import catalog, free_text_problems

from qualify_api.creative.image_pipeline.layer import (
    PRODUCT_PROMOTION,
    BusinessFacts,
    CatalogProduct,
    LayerRequest,
    unsupported_claims,
)

HERE = Path(__file__).parent
CASES = HERE.parent / "scene_text_v4" / "cases.json"
LABELS = HERE / "labels_002.json"
SLOTS = ("title", "subtitle", "call_phrase")
_PRICE = {"currency", "price figure"}
#: «usted»/«vos» forms a «tú» text must not carry (imperatives and pronouns)
_FORMAL = re.compile(
    r"\b(?:usted(?:es)?|vos|pídalo|pídala|venga|visítenos|escríbanos|llámenos|"
    r"pedí|vení|probá|escribinos|tenés|querés|podés)\b",
    re.IGNORECASE,
)
_ENGLISH = re.compile(
    r"\b(?:delivery|combo pack|sale|off|free|new|happy|weekend|food|post|link|"
    r"online|brunch|take away|pickup)\b",
    re.IGNORECASE,
)

#: PR #674 «Antes de encender» and the second review: (text, extra request fields,
#: what a person would say: True = an invented datum/claim that should be refused)
PROBES: list[tuple[str, dict[str, Any], bool, str]] = [
    ("Listo en 1 hora", {}, False, "price rule: singular unit"),
    ("Empanadas de 2000", {}, True, "price rule: «de» + year-like number"),
    ("Desde 2000", {}, True, "price rule: «desde» + 1900-2099 read as a year"),
    ("Precio: 18", {}, True, "price rule: colon after «precio»"),
    ("Llévate 3 x 2000", {}, True, "price rule: «N x price» read as a promotion"),
    ("Abierto toda la noche", {}, True, "claims: hours with «toda»"),
    ("Cerrado por vacaciones", {}, True, "claims: «cerrado por»"),
    (
        "Este domingo te esperamos",
        {"products": (CatalogProduct(uuid4(), "Combo Domingo", True),)},
        True,
        "claims: a product name lets a day pass",
    ),
    ("Martes de sabor", {}, False, "claims: a day name as plain language"),
    ("Abrimos el horno a las brasas", {}, False, "claims: «abrimos» not about hours"),
    ("Tu sábado sabe mejor", {}, False, "claims: possessive day (fixed in #674)"),
    ("Cielo abierto", {}, False, "claims: «abierto» plain (fixed in #674)"),
    ("Tu salchipapa, cada noche", {}, True, "claims: «cada noche» (seen in CAPA-002)"),
    ("Papas que no se acaban", {}, True, "claims: an unlimited-refill promise (CAPA-002)"),
]


def _request(case: dict[str, Any], **over: Any) -> LayerRequest:
    by_name = {n.lower(): v for n, v in case.get("highlights") or []}
    values: dict[str, Any] = {
        "tenant_id": uuid4(),
        "brand_id": uuid4(),
        "format": "4:5",
        "piece_type": PRODUCT_PROMOTION,
        "slides": (),
        "brand_name": "Bianki",
        "topic": case.get("topic", ""),
        "scene": case.get("topic", ""),
        "cta": case.get("cta_or_place") if isinstance(case.get("cta_or_place"), str) else "",
        "facts": BusinessFacts(
            location=by_name.get("dirección"),
            hours=by_name.get("horario"),
            contact=by_name.get("pedido") or by_name.get("domicilio"),
        ),
    }
    values.update(over)
    return LayerRequest(**values)


def _limit(layout: str, slot: str, fmt: str) -> int | None:
    limit = (catalog()["layouts"][layout]["slots"].get(slot) or {}).get(fmt)
    return limit[0] if limit else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    run = Path(args.run)
    cases = {c["id"]: c for c in json.loads(CASES.read_text(encoding="utf-8"))["cases"]}
    labels = json.loads(LABELS.read_text(encoding="utf-8"))
    texts = []
    for line in (run / "results.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        for position, spec in (row.get("layers") or {}).items():
            for slot in SLOTS:
                if spec.get(slot):
                    texts.append((row, position, slot, spec))
    scored = {"price": {"tp": 0, "fp": [], "fn": []}, "claims": {"tp": 0, "fp": [], "fn": []}}
    over_two_thirds, formal, english, names = [], [], [], []
    for row, position, slot, spec in texts:
        text, key = spec[slot], f"{row['id']}#{position}.{slot}"
        label = labels.get(key, {})
        request = _request(cases[row["case"]])
        flags = {
            "price": bool(_PRICE & set(free_text_problems(text))),
            "claims": bool(unsupported_claims(text, request)),
        }
        human = {"price": bool(label.get("price")), "claims": bool(label.get("claim"))}
        for rule in flags:
            if flags[rule] and human[rule]:
                scored[rule]["tp"] += 1
            elif flags[rule]:
                scored[rule]["fp"].append(f"{key}: «{text}»")
            elif human[rule]:
                scored[rule]["fn"].append(f"{key}: «{text}» ({label.get('why', '')})")
        limit = _limit(spec["layout"], slot, row["format"])
        if limit and len(text) > limit * 2 / 3:
            over_two_thirds.append(f"{key}: {len(text)}/{limit} «{text}»")
        if _FORMAL.search(text):
            formal.append(f"{key}: «{text}»")
        if _ENGLISH.search(text):
            english.append(f"{key}: «{text}»")
        if slot == "title" and "bianki" in text.lower():
            names.append(f"{key}: «{text}»")
    probes = []
    for text, over, should, what in PROBES:
        request = _request({}, **over)
        refused = bool(_PRICE & set(free_text_problems(text))) or bool(
            unsupported_claims(text, request)
        )
        probes.append(
            {
                "text": text,
                "what": what,
                "should_refuse": should,
                "refused": refused,
                "ok": refused == should,
            }
        )

    def pr(rule: str) -> dict[str, Any]:
        s = scored[rule]
        flagged, positives = s["tp"] + len(s["fp"]), s["tp"] + len(s["fn"])
        return {
            "flagged": flagged,
            "human_positives": positives,
            "precision": round(s["tp"] / flagged, 3) if flagged else None,
            "recall": round(s["tp"] / positives, 3) if positives else None,
            "false_positives": s["fp"],
            "false_negatives": s["fn"],
        }

    report = {
        "texts": len(texts),
        "price_rule": pr("price"),
        "claims_rule": pr("claims"),
        "over_two_thirds": over_two_thirds,
        "usted_or_vos": formal,
        "english_words": english,
        "business_name_in_title": names,
        "probes": probes,
    }
    (run / "score.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

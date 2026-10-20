"""The Brand Kit document-reading experiment (docs/plan-observabilidad-langfuse.md §7,
fase 6): cases, task and evaluators, importable so the evaluators are tested offline. The
runnable side — it spends real money — is `packages/api/evals/brief_ai/run_experiment.py`.

The task is production's own path: `read_document` then `propose_kit_changes` (the tool
call plus the four checks of `verify_proposal`), against an empty kit. Scores per document:

- `cobertura` — share of the expected fields that got a proposal;
- `recall_items` / `precision_items` — the list fields' items found / the proposed items
  that are expected (anywhere in the document's expectations: a phrase put under
  «Así no habla» instead of «Palabras prohibidas» is not invented);
- `texto_ok` — positioning and audience carry one of the expected phrases;
- `inventados` — proposals for a field the document says nothing about;
- `citas_verificadas` — proposals whose quote is literally in the document;
- `costo_usd`, `segundos`, `errores`.

Matching folds accents and case; two phrases match when one contains the other or they
are at least 80 % alike.
"""

from __future__ import annotations

import json
import statistics
import time
import unicodedata
from collections.abc import Mapping, Sequence
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from qualify_shared.observability import ItemOutcome, Score

from qualify_api.claude_tools import ClaudeToolError, ModelConfig
from qualify_api.creative.brief_ai import (
    BRIEF_EFFORT,
    BRIEF_MODEL,
    FIELDS,
    KitSnapshot,
    propose_kit_changes,
    read_document,
)

DATASET = "brand-kit-documentos"
LIST_FIELDS = tuple(name for name, _label, kind in FIELDS if kind == "list")
TEXT_FIELDS = tuple(name for name, _label, kind in FIELDS if kind == "text")

#: The production default first.
CONFIGS: Mapping[str, ModelConfig] = {
    "sonnet-5@medium": ModelConfig(BRIEF_MODEL, BRIEF_EFFORT),
    "sonnet-5.5@medium": ModelConfig("claude-sonnet-5-5", "medium"),
}


def load_cases(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        {
            "id": case["id"],
            "input": {
                "case": case["id"],
                "filename": case["filename"],
                "document": case["document"],
                "expected": case["expected"],
            },
        }
        for case in raw["cases"]
    ]


def read(
    case: Mapping[str, Any], config: ModelConfig, *, api_key: str, client_factory: Any = None
) -> dict[str, Any]:
    """The task: the document through production's reader; the proposals as fields."""
    document = read_document(case["filename"], case["document"].encode("utf-8"))
    started = time.perf_counter()
    try:
        proposals, stats = propose_kit_changes(
            document, KitSnapshot(), api_key=api_key, config=config, client_factory=client_factory
        )
    except ClaudeToolError as exc:
        return {"error": str(exc)[:300], "proposals": {}}
    return {
        "proposals": {
            p.field: {"value": p.proposed, "evidence": p.evidence, "verified": p.verified}
            for p in proposals
        },
        "cost_usd": round(stats.cost_usd, 6),
        "seconds": round(time.perf_counter() - started, 2),
        "model": stats.model_revision or stats.model_id,
    }


# ---------------------------------------------------------------------------
# evaluators


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    bare = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(bare.casefold().replace("“", "").replace("”", "").replace('"', "").split())


def matches(a: str, b: str) -> bool:
    x, y = _fold(a).strip(" .¡!¿?"), _fold(b).strip(" .¡!¿?")
    if not x or not y:
        return False
    return x in y or y in x or SequenceMatcher(None, x, y).ratio() >= 0.8


def _items(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def reading_scores(
    case: Mapping[str, Any], output: Mapping[str, Any], _expected: Any, _meta: Mapping[str, Any]
) -> list[Score]:
    if output.get("error"):
        return [Score("errores", 1.0, output["error"])]
    expected: Mapping[str, list[str]] = case["expected"]
    proposals: Mapping[str, Mapping[str, Any]] = output.get("proposals") or {}
    every_expected = [item for field in LIST_FIELDS for item in expected.get(field) or ()]

    wanted = [f for f, items in expected.items() if items]
    covered = [f for f in wanted if f in proposals]
    invented = [f for f, items in expected.items() if not items and f in proposals]

    found = total = 0
    proposed_ok = proposed_total = 0
    misses: list[str] = []
    extras: list[str] = []
    for field in LIST_FIELDS:
        want = expected.get(field)
        got = _items(proposals[field]["value"]) if field in proposals else []
        if want:
            for item in want:
                total += 1
                if any(matches(item, g) for g in got):
                    found += 1
                else:
                    misses.append(f"{field}: {item}")
        if field in expected:
            for item in got:
                proposed_total += 1
                if any(matches(item, e) for e in every_expected):
                    proposed_ok += 1
                else:
                    extras.append(f"{field}: {item}")

    text_checks = [
        any(matches(phrase, proposals[field]["value"]) for phrase in expected[field])
        for field in TEXT_FIELDS
        if expected.get(field) and field in proposals
    ]
    verified = [p["verified"] for p in proposals.values() if p.get("verified") is not None]

    scores = [
        Score("cobertura", len(covered) / len(wanted) if wanted else 1.0),
        Score("inventados", float(len(invented)), ", ".join(invented) or None),
        Score("errores", 0.0),
    ]
    if total:
        scores.append(Score("recall_items", found / total, "; ".join(misses)[:500] or None))
    if proposed_total:
        scores.append(
            Score("precision_items", proposed_ok / proposed_total, "; ".join(extras)[:500] or None)
        )
    if text_checks:
        scores.append(Score("texto_ok", sum(text_checks) / len(text_checks)))
    if verified:
        scores.append(Score("citas_verificadas", sum(verified) / len(verified)))
    if output.get("cost_usd") is not None:
        scores.append(Score("costo_usd", float(output["cost_usd"])))
    if output.get("seconds") is not None:
        scores.append(Score("segundos", float(output["seconds"])))
    return scores


ITEM_EVALUATORS = (reading_scores,)


def run_summary(outcomes: Sequence[ItemOutcome]) -> list[Score]:
    def values(name: str) -> list[float]:
        return [
            float(o.scores[name]) for o in outcomes if isinstance(o.scores.get(name), int | float)
        ]

    out: list[Score] = []
    for name in ("cobertura", "recall_items", "precision_items", "texto_ok", "citas_verificadas"):
        if found := values(name):
            out.append(Score(f"{name}_media", round(statistics.mean(found), 3)))
    out.append(Score("inventados_total", sum(values("inventados"))))
    out.append(Score("errores_total", sum(values("errores"))))
    if costs := values("costo_usd"):
        out.append(Score("costo_por_documento_usd", round(statistics.mean(costs), 5)))
    if seconds := values("segundos"):
        out.append(Score("segundos_p50", round(statistics.median(seconds), 2)))
    return out


RUN_EVALUATORS = (run_summary,)

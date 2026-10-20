"""The copy experiment (docs/plan-observabilidad-langfuse.md §6.2-§7): cases, the task
and the evaluators, importable so the evaluators are tested offline. The runnable side —
which spends real money — is `packages/api/evals/copy_ai/run_experiment.py`.

The task renders each variant with `render_prompt`, exactly as `ContentService` does
(no brand context or recent openings: those come from a tenant's database), and calls the
copy adapter through `TracedProvider`, so every call is a Langfuse generation with its
tokens and our price, nested under the experiment item's trace.

The evaluators are the deterministic gates of §6.2 — there is no gold copy:

- `esquema_ok` — the payload validates against `CopyPayload`;
- `reglas_ok` — `check_hard_rules` finds nothing (banned words, forbidden claims,
  caption length);
- `largos_ok` — the hook and the CTA fit what the prompt asked for (the printed limits
  for kinds whose words go on an image, `printed_limits`, the schema's otherwise). Since
  2026-10-13 the adapter holds the copy to them (one repair turn, then a word-boundary
  cut), so this gate now measures that net, not the model alone;
- `restricciones_ok` — every «Debe mencionar» appears and no «Debe evitar» does;
- `puertas_ok` — all four at once;
- `diversidad` — 1 minus the mean trigram similarity between the variants' hooks;
- `costo_usd`, `latencia_s`, `errores`.

Item scores are the share of the item's variants that pass; the run's are means.
"""

from __future__ import annotations

import json
import math
import statistics
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from qualify_creative.adapters import AnthropicCopyAdapter
from qualify_creative.brand.fidelity import check_hard_rules, normalize
from qualify_creative.brand.render import printed_limits, render_prompt
from qualify_creative.enums import ContentKind, GenerationTask, ImageRoute
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.providers import GenerationProvider, GenerationRequest
from qualify_creative.schemas import (
    HOOK_MAX,
    BrandKit,
    BrandVoiceProfile,
    ContentBrief,
    CopyPayload,
)
from qualify_shared.observability import ItemOutcome, Score

from qualify_api.creative.composition import PRICING_VERSION
from qualify_api.creative.observed import TracedProvider, _copy_usage

DATASET = "copy-generador"


@dataclass(frozen=True)
class CopyConfig:
    model_id: str
    effort: str


#: The candidates of the first experiment (plan §7). The first is the production default.
CONFIGS: Mapping[str, CopyConfig] = {
    "opus-5.5@medium": CopyConfig("claude-opus-5-5", "medium"),
    "opus-5.5@low": CopyConfig("claude-opus-5-5", "low"),
    "sonnet-5.5@medium": CopyConfig("claude-sonnet-5-5", "medium"),
}


def load_cases(path: Path) -> list[dict[str, Any]]:
    """`cases.json` as dataset items: each case carries its brand's kit and voice, so an
    item is self-contained (Langfuse shows exactly what was asked)."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = []
    for case in raw["cases"]:
        brand = raw["brands"][case["brand"]]
        brief = case["brief"]
        items.append(
            {
                "id": case["id"],
                "input": {
                    "case": case["id"],
                    "brand": case["brand"],
                    "kit": brand["kit"],
                    "voice": brand["voice"],
                    "brief": brief,
                },
                "metadata": {
                    "brand": case["brand"],
                    "kind": brief["kind"],
                    "format": brief["format"],
                },
            }
        )
    return items


def build(
    case: Mapping[str, Any], variants: int
) -> tuple[BrandKit, BrandVoiceProfile, ContentBrief]:
    """The kit, voice and brief of a case, validated exactly as production validates
    them. `image_route` is fixed to the no-model route: this experiment is about copy."""
    kit = BrandKit.model_validate(case["kit"])
    voice = BrandVoiceProfile.model_validate(case["voice"])
    brief = ContentBrief.model_validate(
        {
            **case["brief"],
            "brand_id": str(kit.brand_id),
            "image_route": ImageRoute.TEMPLATE_ONLY.value,
            "variants_requested": variants,
        }
    )
    return kit, voice, brief


def generate(
    case: Mapping[str, Any],
    config: CopyConfig,
    *,
    api_key: str,
    variants: int = 2,
    provider: GenerationProvider | None = None,
) -> dict[str, Any]:
    """The task: every variant of the case's copy, each with its model, time and cost —
    or the error that stopped it (an error is a measurement, not a crash)."""
    kit, voice, brief = build(case, variants)
    pricing = JsonPricingTable(PRICING_VERSION)
    adapter = provider or TracedProvider(
        AnthropicCopyAdapter(model_id=config.model_id, effort=config.effort), pricing
    )
    schema = CopyPayload.model_json_schema()
    out: list[dict[str, Any]] = []
    for index in range(variants):
        prompt = render_prompt(
            kit=kit, voice=voice, brief=brief, task=GenerationTask.COPY, variant=index
        )
        limits = printed_limits(brief.kind)
        request = GenerationRequest(
            task=GenerationTask.COPY,
            rendered_prompt=prompt,
            output_schema=schema,
            # the same printed limits production sends (the adapter holds the copy to them)
            params={"max_lengths": limits} if limits else {},
        )
        started = time.perf_counter()
        try:
            result = adapter.generate(request, api_key=api_key)
        except Exception as exc:  # noqa: BLE001 — recorded and scored
            out.append({"error": f"{type(exc).__name__}: {exc}"[:300]})
            continue
        try:
            _usage, cost = _copy_usage(pricing, request, result)
            cost_usd = round(sum(cost.values()), 6)
        except Exception:  # noqa: BLE001 — an unpriced model still has its copy scored
            cost_usd = None
        out.append(
            {
                "payload": dict(result.payload),
                "model": result.model_id,
                "seconds": round(time.perf_counter() - started, 2),
                "cost_usd": cost_usd,
            }
        )
    return {"kind": brief.kind.value, "variants": out}


# ---------------------------------------------------------------------------
# evaluators


def _payload(variant: Mapping[str, Any]) -> CopyPayload | None:
    if "payload" not in variant:
        return None
    try:
        return CopyPayload.model_validate(variant["payload"])
    except ValidationError:
        return None


def _lengths_ok(copy: CopyPayload, kind: ContentKind) -> bool:
    limits = printed_limits(kind)
    if limits:
        return len(copy.hook) <= limits["hook"] and len(copy.cta) <= limits["cta"]
    return len(copy.hook) <= HOOK_MAX


def _constraints_ok(copy: CopyPayload, brief: Mapping[str, Any]) -> bool:
    constraints = brief.get("constraints") or {}
    text = normalize(" ".join([copy.hook, copy.caption, copy.cta, copy.script, *copy.hashtags]))
    mentioned = all(normalize(m) in text for m in constraints.get("must_mention") or ())
    avoided = not any(normalize(a) in text for a in constraints.get("must_avoid") or ())
    return mentioned and avoided


def _trigrams(text: str) -> set[str]:
    folded = normalize(text)
    return {folded[i : i + 3] for i in range(max(len(folded) - 2, 1))}


def gates(
    case: Mapping[str, Any], output: Mapping[str, Any], _expected: Any, _meta: Mapping[str, Any]
) -> list[Score]:
    """Share of the item's variants that pass each gate, and all of them at once."""
    kit = BrandKit.model_validate(case["kit"])
    kind = ContentKind(case["brief"]["kind"])
    variants = output.get("variants") or []
    if not variants:
        return [Score("puertas_ok", 0.0, "no variants")]
    passed = {"esquema_ok": 0, "reglas_ok": 0, "largos_ok": 0, "restricciones_ok": 0}
    all_ok = 0
    notes: list[str] = []
    for number, variant in enumerate(variants, start=1):
        copy = _payload(variant)
        if copy is None:
            notes.append(f"v{number}: {variant.get('error') or 'invalid payload'}")
            continue
        failures = check_hard_rules(copy, kit)
        checks = {
            "esquema_ok": True,
            "reglas_ok": not failures,
            "largos_ok": _lengths_ok(copy, kind),
            "restricciones_ok": _constraints_ok(copy, case["brief"]),
        }
        for key, ok in checks.items():
            passed[key] += ok
        all_ok += all(checks.values())
        notes.extend(f"v{number}: {f.detail}" for f in failures)
        if not checks["largos_ok"]:
            notes.append(f"v{number}: hook {len(copy.hook)} / cta {len(copy.cta)} chars")
        if not checks["restricciones_ok"]:
            notes.append(f"v{number}: constraints not met")
    total = len(variants)
    comment = "; ".join(notes)[:500] or None
    return [
        *(Score(key, count / total) for key, count in passed.items()),
        Score("puertas_ok", all_ok / total, comment),
    ]


def diversity(
    case: Mapping[str, Any], output: Mapping[str, Any], _expected: Any, _meta: Mapping[str, Any]
) -> list[Score]:
    hooks = [copy.hook for v in output.get("variants") or () if (copy := _payload(v))]
    if len(hooks) < 2:
        return []
    similarities = [
        len(a & b) / len(a | b) if a | b else 1.0
        for a, b in combinations([_trigrams(h) for h in hooks], 2)
    ]
    return [Score("diversidad", round(1 - statistics.mean(similarities), 3))]


def cost_and_time(
    case: Mapping[str, Any], output: Mapping[str, Any], _expected: Any, _meta: Mapping[str, Any]
) -> list[Score]:
    variants = output.get("variants") or []
    done = [v for v in variants if "payload" in v]
    costs = [v["cost_usd"] for v in done if v.get("cost_usd") is not None]
    scores = [Score("errores", float(len(variants) - len(done)))]
    if costs:
        scores.append(Score("costo_usd", round(sum(costs), 6)))
    if done:
        scores.append(Score("latencia_s", round(statistics.mean(v["seconds"] for v in done), 2)))
    return scores


ITEM_EVALUATORS = (gates, diversity, cost_and_time)


def run_summary(outcomes: Sequence[ItemOutcome]) -> list[Score]:
    """The run's headline numbers (plan §6.3): the gate pass rate, the cost per piece and
    the p95 latency."""

    def values(name: str) -> list[float]:
        return [
            float(o.scores[name]) for o in outcomes if isinstance(o.scores.get(name), int | float)
        ]

    scores: list[Score] = []
    if passed := values("puertas_ok"):
        scores.append(Score("tasa_puertas", round(statistics.mean(passed), 3)))
    if costs := values("costo_usd"):
        scores.append(Score("costo_por_pieza_usd", round(statistics.mean(costs), 5)))
    if latencies := sorted(values("latencia_s")):
        rank = max(math.ceil(0.95 * len(latencies)) - 1, 0)
        scores.append(Score("latencia_p95_s", latencies[rank]))
    if errors := values("errores"):
        scores.append(Score("errores_total", sum(errors)))
    return scores


RUN_EVALUATORS = (run_summary,)


def projected_cost_usd(items: int, variants: int, configs: Sequence[CopyConfig]) -> Decimal:
    """A rough ceiling before spending: ~3 000 input and ~1 500 output tokens per call
    (prompt plus adaptive thinking), at each model's list price."""
    pricing = JsonPricingTable(PRICING_VERSION)
    total = Decimal(0)
    for config in configs:
        per_in = pricing.unit_price(model_id=config.model_id, unit="per_mtok_in")
        per_out = pricing.unit_price(model_id=config.model_id, unit="per_mtok_out")
        per_call = (3000 * per_in + 1500 * per_out) / Decimal(1_000_000)
        total += per_call * items * variants
    return total.quantize(Decimal("0.01"))

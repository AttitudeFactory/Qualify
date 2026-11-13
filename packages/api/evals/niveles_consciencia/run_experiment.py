"""Awareness levels + business perks, baseline vs change (m-25026482, qualify-measure).

Suites (`--suite`, default all four in this order):

- `identity` — free: the parts prompt v3.2 vs v3.1 (the baseline ref) with no perks and
  no level must be byte-identical (`parts_prompt_identical`).
- `angles` — «10 variaciones» over `cases.json` (`angle_cases`): the baseline ref's
  prompt once per product, the new prompt with the brand's perks and with none.
- `copy` — `../copy_ai/cases_niveles.json`: one angle per level through `angle_brief` and
  the production copy adapter (Opus 5.5 @ medium), new (level + perks) vs baseline.
- `parts` — «Proponerme las partes» with the same five food angles, level + perks vs
  stripped.

Every idea gets the deterministic checks and two readings by the judge (Haiku 5.5,
`JUDGE_RUBRIC`, blind and informed). Spend is summed from every call and the run stops
BEFORE a call that could cross `--cap-usd`; what was left out is listed in the result.
It SPENDS REAL MONEY, so it is run by hand, never in CI:

    just eval-niveles --suite identity                 # free
    just eval-niveles --suite angles --split dev --cap-usd 0.80
    just eval-niveles --suite angles,copy,parts --split test --cap-usd 2.00

Langfuse tracing is used when LANGFUSE_* keys are set (`just langfuse-up`); without
them it runs untraced and says so. Results: `results/<stamp>-<suites>.json`.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
ANGLES_PATH = "packages/creative/src/qualify_creative/angles.py"
PARTS_PATH = "packages/api/src/qualify_api/creative/parts_ai.py"

#: Worst case of ONE call, checked before it is sent (input generous, max output).
CEILING_USD = {
    "angles": Decimal("0.075"),  # Sonnet 5: ~3.5k in, 6k out max
    "judge": Decimal("0.004"),  # Haiku 5.5: ~4k in, 6k out max
    "copy": Decimal("0.12"),  # Opus 5.5: ~6k in, 4.5k out
    "parts": Decimal("0.12"),  # parts_ai.PROPOSE_BUDGET_USD
}


def _load_env(path: str | None) -> None:
    if not path or not Path(path).exists():
        return
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() and not name.strip().startswith("#"):
            os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


class Spend:
    """Every paid call's cost; `allow` refuses a call whose ceiling would cross the cap."""

    def __init__(self, cap: Decimal) -> None:
        self.cap = cap
        self.total = Decimal(0)
        self.by_suite: dict[str, Decimal] = {}
        self.skipped: list[str] = []

    def allow(self, kind: str, what: str) -> bool:
        if self.total + CEILING_USD[kind] > self.cap:
            self.skipped.append(what)
            return False
        return True

    def add(self, suite: str, usd: Decimal | float) -> None:
        value = Decimal(str(usd))
        self.total += value
        self.by_suite[suite] = self.by_suite.get(suite, Decimal(0)) + value


def _judge(
    al: Any,
    scores: list[Any],
    ideas: list[dict[str, str]],
    facts: str,
    perks: tuple[str, ...],
    *,
    informed: bool,
    api_key: str,
    spend: Spend,
    suite: str,
    what: str,
    medium: str = "idea",
) -> dict[str, Any]:
    """Blind (and, for tagged ideas, informed) judge readings applied onto `scores`."""
    out: dict[str, Any] = {}
    blind_rows: list[dict[str, Any]] = []
    informed_rows: list[dict[str, Any]] | None = None
    if spend.allow("judge", f"{what} juez ciego"):
        blind_ideas = [{k: v for k, v in i.items() if k != "nivel"} for i in ideas]
        try:
            blind_rows, stats = al.call_judge(
                blind_ideas, facts, perks, blind=True, api_key=api_key, medium=medium
            )
            spend.add(suite, al.cost_usd(stats))
            out["juez_ciego_usd"] = float(al.cost_usd(stats))
        except Exception as exc:  # noqa: BLE001 — a lost call is recorded, at its ceiling
            spend.add(suite, CEILING_USD["judge"])
            out["juez_ciego_error"] = f"{type(exc).__name__}: {exc}"[:200]
    if informed and spend.allow("judge", f"{what} juez informado"):
        try:
            informed_rows, stats = al.call_judge(
                ideas, facts, perks, blind=False, api_key=api_key, medium=medium
            )
            spend.add(suite, al.cost_usd(stats))
            out["juez_informado_usd"] = float(al.cost_usd(stats))
        except Exception as exc:  # noqa: BLE001
            spend.add(suite, CEILING_USD["judge"])
            out["juez_informado_error"] = f"{type(exc).__name__}: {exc}"[:200]
    al.apply_judge(scores, blind_rows, informed_rows)
    return out


def run_angles(al: Any, args: Any, spend: Spend, api_key: str) -> dict[str, Any]:
    import qualify_creative.angles as new

    from qualify_api.claude_tools import ClaudeToolError, ModelConfig
    from qualify_api.creative.angles_ai import ANGLES_EFFORT, ANGLES_MODEL, MAX_TOKENS

    old = al.load_module_at(
        args.baseline_ref, ANGLES_PATH, "qualify_creative.angles_baseline", ROOT
    )
    config = ModelConfig(ANGLES_MODEL, ANGLES_EFFORT)
    cases = [c for c in al.load_angle_cases(HERE / "cases.json") if args.split in ("all", c.split)]
    sets: list[dict[str, Any]] = []
    scores: list[Any] = []
    args.partial["angles"] = {"sets": sets, "scores": scores}
    for case in cases:
        sources = al.sources_text(case.brand, case.product, case.perks)
        arms = [
            ("base", old, False),
            ("nuevo_con_ventajas", new, True),
            ("nuevo_sin_ventajas", new, False),
        ]
        runs = [
            (arm, module, with_perks, rep)
            for rep in range(1, args.repeat + 1)
            for arm, module, with_perks in arms
            if not args.arm_set or arm in args.arm_set
        ]
        for arm, module, with_perks, rep in runs:
            what = f"angles {case.id} {arm} #{rep}"
            if not spend.allow("angles", what):
                continue
            product, brand = al.build_inputs(module, case, with_perks=with_perks)
            preset = module.PRESETS[0]
            started = time.monotonic()
            try:
                angles, stats = al.call_angles(
                    module,
                    product,
                    brand,
                    preset,
                    api_key=api_key,
                    config=config,
                    max_tokens=MAX_TOKENS,
                    feature="eval-niveles-angulos",
                )
            except ClaudeToolError as exc:
                if exc.stats is not None:
                    spend.add("angles", al.cost_usd(exc.stats))
                sets.append({"case": case.id, "arm": arm, "error": str(exc)[:300]})
                args.checkpoint()
                continue
            except Exception as exc:  # noqa: BLE001 — timeout/network: charged at the ceiling
                spend.add("angles", CEILING_USD["angles"])
                sets.append({"case": case.id, "arm": arm, "error": f"{type(exc).__name__}"})
                args.checkpoint()
                continue
            usd = al.cost_usd(stats)
            spend.add("angles", usd)
            perks = case.perks if with_perks else ()
            # the baseline never sees perks: its «sources» are product + brand only
            arm_sources = sources if with_perks else al.sources_text(case.brand, case.product, ())
            set_scores = []
            for a in angles:
                text = " ".join(a[k] for k in ("title", "scene", "hook", "cta"))
                set_scores.append(
                    al.score_idea(
                        arm=arm,
                        case=case.id,
                        split=case.split,
                        sector=case.sector,
                        with_perks=with_perks,
                        level=a.get("awareness_level"),
                        level_answered=a.get("nivel_respondido"),
                        hook=a["hook"],
                        cta=a["cta"],
                        full_text=text,
                        sources=arm_sources,
                        perks=perks,
                        offers_text="\n".join([a["title"], a["hook"], a["cta"]]),
                    )
                )
            ideas = [
                {
                    "titulo": a["title"],
                    "escena": a["scene"],
                    "gancho": a["hook"],
                    "cta": a["cta"],
                    "nivel": a.get("awareness_level") or "",
                }
                for a in angles
            ]
            judged = {}
            if not args.no_judge:
                judged = _judge(
                    al,
                    set_scores,
                    ideas,
                    arm_sources,
                    perks,
                    informed=module is new,
                    api_key=api_key,
                    spend=spend,
                    suite="angles",
                    what=what,
                )
            scores.extend(set_scores)
            sets.append(
                {
                    "case": case.id,
                    "split": case.split,
                    "sector": case.sector,
                    "arm": arm,
                    "angles": angles,
                    "spread": al.level_spread([a.get("awareness_level") for a in angles]),
                    "invalid_tags": sum(
                        1
                        for a in angles
                        if module is new and a.get("nivel_respondido") not in al.LEVELS
                    ),
                    "model": stats.model_id,
                    "revision": stats.model_revision,
                    "input_tokens": stats.input_tokens,
                    "output_tokens": stats.output_tokens,
                    "cache_read_tokens": stats.cache_read_tokens,
                    "cache_creation_tokens": stats.cache_creation_tokens,
                    "cost_usd": float(usd),
                    "seconds": round(time.monotonic() - started, 1),
                    **judged,
                }
            )
            args.checkpoint()
            print(f"  {what}: {len(angles)} ángulos, US${usd} (acumulado US${spend.total})")
    return {"sets": sets, "scores": [asdict(s) for s in scores]}


def _copy_cases(al: Any, args: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    base = json.loads((HERE.parent / "copy_ai" / "cases.json").read_text(encoding="utf-8"))
    levels = json.loads(
        (HERE.parent / "copy_ai" / "cases_niveles.json").read_text(encoding="utf-8")
    )
    return base, levels


def run_copy(al: Any, args: Any, spend: Spend, api_key: str) -> dict[str, Any]:
    import qualify_creative.angles as new
    from qualify_creative.brand.render import render_prompt
    from qualify_creative.enums import GenerationTask

    from qualify_api.evals import copy_quality as cq

    old = al.load_module_at(
        args.baseline_ref, ANGLES_PATH, "qualify_creative.angles_baseline", ROOT
    )
    base, levels = _copy_cases(al, args)
    config = cq.CONFIGS["opus-5.5@medium"]
    items: list[dict[str, Any]] = []
    scores: list[Any] = []
    prefixes: dict[str, Any] = {}
    args.partial["copy"] = {"items": items, "scores": scores, "prefix_chars": prefixes}
    chosen = [c for c in levels["cases"] if not args.level_set or c["level"] in args.level_set]
    for case in [c for c in chosen[: args.limit or None] for _ in range(args.repeat)]:
        brand_key = case["brand"]
        kit = dict(base["brands"][brand_key]["kit"])
        voice = base["brands"][brand_key]["voice"]
        extra = levels["brands"][brand_key]
        product_d = extra["product"]
        perks = tuple(extra["perks"])
        sources = "\n".join(
            [
                *perks,
                *(v for v in product_d.values() if isinstance(v, str)),
                kit.get("positioning", ""),
                kit.get("audience", ""),
                *kit.get("cta_patterns", []),
                *case["angle"].values(),
            ]
        )
        for arm, module, with_perks in (("base", old, False), ("nuevo", new, True)):
            if args.arm_set and arm not in args.arm_set:
                continue
            what = f"copy {case['id']} {arm}"
            if not spend.allow("copy", what):
                continue
            angle_fields = dict(case["angle"], position=1)
            if module is new:
                angle_fields["awareness_level"] = case["level"]
            angle = module.CreativeAngle(**angle_fields)
            product = module.AngleProduct(
                product_id=UUID(int=0),
                name=product_d["name"],
                description=product_d["description"],
                category=product_d["category"],
                price_label=product_d["price_label"],
                photo_keys=tuple(f"foto-{i}" for i in range(product_d["photos"])),
            )
            brief = module.angle_brief(
                angle=angle,
                preset=module.PRESETS[0],
                product=product,
                brand_id=UUID(kit["brand_id"]),
            )
            arm_kit = dict(kit, business_perks=list(perks)) if with_perks else kit
            item = {"kit": arm_kit, "voice": voice, "brief": brief.model_dump(mode="json")}
            k, v, b = cq.build(item, 1)
            rendered = render_prompt(kit=k, voice=v, brief=b, task=GenerationTask.COPY, variant=0)
            prefixes.setdefault(brand_key, {})[arm] = len(rendered.stable_prefix)
            output = cq.generate(item, config, api_key=api_key, variants=1)
            usd = sum(x.get("cost_usd") or 0 for x in output["variants"])
            # a variant lost to the network may still have billed: charge its ceiling
            usd += float(CEILING_USD["copy"]) * sum(1 for x in output["variants"] if "error" in x)
            spend.add("copy", usd)
            gates = {s.name: s.value for s in cq.gates(item, output, None, {})}
            variant = output["variants"][0]
            payload = variant.get("payload") or {}
            hook, cta = payload.get("hook", ""), payload.get("cta", "")
            stated = "\n".join(
                [hook, payload.get("caption", ""), cta, payload.get("script", "") or ""]
            )
            score = al.score_idea(
                arm=arm,
                case=case["id"],
                split="test",
                sector=brand_key,
                with_perks=with_perks,
                level=case["level"],
                hook=hook,
                cta=cta,
                full_text=stated,
                sources=sources,
                perks=perks if with_perks else (),
                facts_text=stated,
                body="\n".join([payload.get("caption", ""), payload.get("script", "") or ""]),
                offers_text=stated,
            )
            ideas = [
                {
                    "gancho": hook,
                    "texto": payload.get("caption", ""),
                    "cta": cta,
                    "nivel": case["level"],
                }
            ]
            judged = {}
            if payload and not args.no_judge:
                judged = _judge(
                    al,
                    [score],
                    ideas,
                    sources if with_perks else sources,
                    perks if with_perks else (),
                    informed=True,
                    api_key=api_key,
                    spend=spend,
                    suite="copy",
                    what=what,
                )
            scores.append(score)
            items.append(
                {
                    "case": case["id"],
                    "arm": arm,
                    "level": case["level"],
                    "objective": brief.objective.value,
                    "must_mention": list(brief.constraints.must_mention),
                    "output": output,
                    "gates": gates,
                    "cost_usd": usd,
                    **judged,
                }
            )
            args.checkpoint()
            print(
                f"  {what}: puertas {gates.get('puertas_ok')}, US${usd} "
                f"(acumulado US${spend.total})"
            )
    return {"items": items, "scores": [asdict(s) for s in scores], "prefix_chars": prefixes}


def run_parts(al: Any, args: Any, spend: Spend, api_key: str) -> dict[str, Any]:
    from qualify_creative.angles import AngleBrand, AngleProduct, CreativeAngle

    from qualify_api.creative.parts_ai import (
        PROPOSE_PARTS_PROMPT_VERSION,
        PartsBrief,
        PartsProposalUnavailable,
        propose_parts,
    )
    from qualify_api.evals import parts_proposal as pp

    raw = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))["parts_cases"]
    _base, levels = _copy_cases(al, args)
    extra = levels["brands"][raw["copy_brand"]]
    perks = tuple(extra["perks"])
    p = extra["product"]
    product = AngleProduct(
        product_id=UUID(int=0),
        name=p["name"],
        description=p["description"],
        category=p["category"],
        photo_keys=tuple(f"foto-{i}" for i in range(p["photos"])),
    )
    sources = "\n".join(
        [
            *perks,
            *(v for v in p.values() if isinstance(v, str)),
            *raw["angle_brand"].values(),
            raw["story"],
        ]
    )
    items: list[dict[str, Any]] = []
    scores: list[Any] = []
    args.partial["parts"] = {"items": items, "scores": scores}
    food = [c for c in levels["cases"] if c["brand"] == raw["copy_brand"]]
    food = [c for c in food if not args.level_set or c["level"] in args.level_set]
    for case in [c for c in food[: args.limit or None] for _ in range(args.repeat)]:
        for arm, with_level in (("base", False), ("nuevo", True)):
            if args.arm_set and arm not in args.arm_set:
                continue
            what = f"parts {case['id']} {arm}"
            if not spend.allow("parts", what):
                continue
            brand = AngleBrand(**raw["angle_brand"], perks=perks if with_level else ())
            brief = PartsBrief(
                story=raw["story"],
                brand=brand,
                product=product,
                target_seconds=raw["target_seconds"],
            )
            angle = CreativeAngle(
                **dict(case["angle"], position=1),
                awareness_level=case["level"] if with_level else None,
            )
            started = time.monotonic()
            try:
                proposal = propose_parts(
                    brief,
                    angle,
                    api_key=api_key,
                    attribution=al.eval_attribution(
                        "eval-niveles-partes", prompt_version=PROPOSE_PARTS_PROMPT_VERSION
                    ),
                )
            except PartsProposalUnavailable as exc:
                usd = exc.stats.cost_usd if exc.stats is not None else 0.0
                spend.add("parts", usd)
                items.append(
                    {"case": case["id"], "arm": arm, "failed": str(exc)[:300], "cost_usd": usd}
                )
                args.checkpoint()
                continue
            except Exception as exc:  # noqa: BLE001 — timeout/network: charged at the ceiling
                spend.add("parts", CEILING_USD["parts"])
                items.append({"case": case["id"], "arm": arm, "failed": type(exc).__name__})
                args.checkpoint()
                continue
            usd = float(proposal.provenance.cost_usd)
            spend.add("parts", usd)
            texts = [x.description for x in proposal.parts]
            output = {
                "parts": [
                    {"description": x.description, "seconds": x.seconds} for x in proposal.parts
                ],
                "provenance": proposal.provenance.model_dump(mode="json"),
                "cost_usd": usd,
                "latency_s": round(time.monotonic() - started, 2),
            }
            case_input = {
                "story": raw["story"],
                "target_seconds": raw["target_seconds"],
                "product": p,
                "brand": raw["angle_brand"],
            }
            det = {s.name: s.value for s in pp.proposal_scores(case_input, output)}
            joined = " ".join(texts)
            # the angle the plan was asked for is given data too (its hook and CTA)
            case_sources = "\n".join([sources, *case["angle"].values()])
            score = al.score_idea(
                arm=arm,
                case=case["id"],
                split="test",
                sector="comida",
                with_perks=with_level,
                level=case["level"],
                hook="",
                cta="",
                full_text=joined,
                sources=case_sources,
                perks=perks if with_level else (),
                facts_text=joined,
                offers_text=joined,
            )
            score.rule_det = None  # no hook/CTA in a video plan: the judge reads it
            ideas = [{"partes": " | ".join(texts), "nivel": case["level"]}]
            judged = {}
            if not args.no_judge:
                judged = _judge(
                    al,
                    [score],
                    ideas,
                    case_sources,
                    perks if with_level else (),
                    informed=True,
                    api_key=api_key,
                    spend=spend,
                    suite="parts",
                    what=what,
                    medium="video",
                )
            scores.append(score)
            items.append(
                {
                    "case": case["id"],
                    "arm": arm,
                    "level": case["level"],
                    "prompt_version": PROPOSE_PARTS_PROMPT_VERSION,
                    "output": output,
                    "scores": det,
                    **judged,
                }
            )
            args.checkpoint()
            print(f"  {what}: {len(texts)} partes, US${usd:.4f} (acumulado US${spend.total})")
    return {"items": items, "scores": [asdict(s) for s in scores]}


def run_identity(al: Any, args: Any) -> dict[str, Any]:
    from qualify_creative.angles import AngleBrand, AngleProduct

    import qualify_api.creative.parts_ai as new

    old = al.load_module_at(
        args.baseline_ref, PARTS_PATH, "qualify_api.creative.parts_ai_baseline", ROOT
    )
    brand = AngleBrand(
        name="Marca",
        sector="comida",
        location="Cúcuta",
        positioning="p",
        audience="a",
        palette=("#ffffff",),
        typeface="Inter",
    )
    product = AngleProduct(
        product_id=UUID(int=0),
        name="Producto",
        description="d",
        category="c",
        photo_keys=("a", "b"),
    )
    briefs = [
        new.PartsBrief(story="historia", brand=brand, product=product, target_seconds=t)
        for t in (9, 12, 20, 30, 60)
    ]
    briefs.append(new.PartsBrief(story="sin producto", brand=AngleBrand()))
    checked = al.parts_prompt_identical(old, new, briefs)
    return {
        "identical_pairs": checked,
        "old_version": old.PROPOSE_PARTS_PROMPT_VERSION,
        "new_version": new.PROPOSE_PARTS_PROMPT_VERSION,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", default=str(ROOT / ".env"))
    parser.add_argument("--suite", default="identity,angles,copy,parts")
    parser.add_argument("--split", default="all", choices=("dev", "test", "all"))
    parser.add_argument("--cap-usd", type=Decimal, default=Decimal("1.00"))
    parser.add_argument("--limit", type=int, default=0, help="copy/parts: first N cases only")
    parser.add_argument("--baseline-ref", default=None)
    parser.add_argument("--no-judge", action="store_true")
    parser.add_argument("--label", default="")
    parser.add_argument("--arms", default="", help="only these arms (angles: base, ...)")
    parser.add_argument("--levels", default="", help="copy/parts: only these levels")
    parser.add_argument("--repeat", type=int, default=1, help="runs per case and arm")
    args = parser.parse_args(argv)
    args.arm_set = {a.strip() for a in args.arms.split(",") if a.strip()}
    args.level_set = {a.strip() for a in args.levels.split(",") if a.strip()}

    _load_env(args.env_file)
    os.environ["LANGFUSE_TRACING_ENVIRONMENT"] = "eval"
    from qualify_shared import observability

    from qualify_api import claude_tools
    from qualify_api.evals import awareness_levels as al

    args.baseline_ref = args.baseline_ref or al.BASELINE_REF
    suites = [s.strip() for s in args.suite.split(",") if s.strip()]
    records: list[Any] = []
    claude_tools.configure_consumption_sink(records.append)  # never the DB ledger
    tracing = observability.enabled()
    print(f"Langfuse: {'con trazas' if tracing else 'sin trazas (no hay LANGFUSE_* keys)'}")
    report: dict[str, Any] = {
        "ticket": "m-25026482",
        "baseline_ref": args.baseline_ref,
        "split": args.split,
        "pricing_version": al.PRICING_VERSION,
        "judge": al.JUDGE_CONFIG.label,
        "judge_prompt_version": al.JUDGE_PROMPT_VERSION,
        "judge_parts_version": al.JUDGE_PARTS_VERSION,
        "code_commit": subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True
        ).stdout.strip(),
        "arms": sorted(args.arm_set),
        "levels": sorted(args.level_set),
        "repeat": args.repeat,
        "tracing": tracing,
        "date": datetime.now().isoformat(timespec="seconds"),
        "suites": {},
    }
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"{stamp}-{'-'.join(suites)}{'-' + args.label if args.label else ''}-{args.split}.json"
    out = HERE / "results" / name
    out.parent.mkdir(exist_ok=True)
    spend = Spend(args.cap_usd)
    args.partial = {}

    def save() -> None:
        """The report so far, on disk after every item (a crash loses one item at most)."""
        for suite, partial in args.partial.items():
            report["suites"][suite] = {
                **partial,
                "scores": [asdict(x) for x in partial["scores"]],
            }
        report["spend_usd"] = {k: float(v) for k, v in spend.by_suite.items()}
        report["spend_total_usd"] = float(spend.total)
        report["skipped_by_cap"] = spend.skipped
        report["ledger_calls"] = len(records)
        text = json.dumps(report, indent=1, ensure_ascii=False, default=str)
        out.write_text(text, encoding="utf-8")

    args.checkpoint = save
    if "identity" in suites:
        report["suites"]["identity"] = run_identity(al, args)
        print(f"identity: {report['suites']['identity']}")
    paid = [s for s in suites if s != "identity"]
    if paid:
        api_key = os.environ.get("QUALIFY_ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            print("QUALIFY_ANTHROPIC_API_KEY is not set", file=sys.stderr)
            return 2
        runners = {"angles": run_angles, "copy": run_copy, "parts": run_parts}
        for suite in paid:
            print(f"== {suite} (tope US${args.cap_usd}, gastado US${spend.total})")
            runners[suite](al, args, spend, api_key)
            save()
        print(f"Gastado US${spend.total}; omitidos por el tope: {len(spend.skipped)}")
    save()
    print(f"Guardado en {out.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

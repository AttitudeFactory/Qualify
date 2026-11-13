"""«Mejorar mi texto» before/after (m-25017274, qualify-measure).

Runs the six FICTIONAL briefs of `cases.json` (a shawarma-and-salads shop) through
`context_ai.enhance_context` exactly as the generator calls it, pressing the button twice
per brief, and measures how much the answers repeat:

- prompt `context-v3-*` (one text that REPLACES the field): press 2 rewrites press 1's
  output, as the screen did;
- prompt `context-v4-*` (three versions, the original kept): press 2 is «Otra versión» —
  the original text again plus the versions already shown.

Similarity is `difflib.SequenceMatcher.ratio` over the casefolded text (1.0 = identical),
next to word-set Jaccard. «Números nuevos» counts digit runs in an answer that are not in
the brief (a cheap proxy for an invented price, date or time). Cost comes from the
consumption records of the calls themselves (booked to an in-memory list, never the DB).

It spends real money (≈ USD 0.01 per press), so it is run by hand, never in CI:

    just eval-mejorar-texto --label v3-baseline
    just eval-mejorar-texto --label v4 --cap-usd 0.60
    just eval-mejorar-texto --label v5-escenas --only escena-precio

«Pide texto en la imagen» (m-25017274, live 2026-11-13) counts, for SCENE cases, the
shown versions that ask for a price, figure, sign, label or any written word in the
picture — checked here independently of the product's own filter — and «descartadas»
how many versions the product's filter (`scene_text_request`, prompt v5+) dropped.
`--module-file` runs an older `context_ai.py` (e.g. from `git show origin/main:…`) for
the baseline.
"""

from __future__ import annotations

import argparse
import difflib
import itertools
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

HERE = Path(__file__).resolve().parent


def _load_env(path: str | None) -> None:
    if not path or not Path(path).exists():
        return
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() and not name.strip().startswith("#"):
            os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.casefold(), b.casefold()).ratio()


def jaccard(a: str, b: str) -> float:
    wa, wb = set(re.findall(r"\w+", a.casefold())), set(re.findall(r"\w+", b.casefold()))
    return len(wa & wb) / len(wa | wb) if wa | wb else 1.0


def new_numbers(text: str, source: str) -> list[str]:
    known = set(re.findall(r"\d+", source))
    return [n for n in re.findall(r"\d+", text) if n not in known]


_TEXT_WORDS = re.compile(
    r"\b(precios?|letreros?|carteles|cartel|etiquetas?|r[óo]tulos?|avisos?|pancartas?|"
    r"textos?|letras?|escrito|escrita|pizarras?)\b",
    re.IGNORECASE,
)


def asks_for_text(text: str, case: dict[str, Any]) -> bool:
    """A scene version that asks for something written in the image (eval-side check)."""
    own = case["text"].casefold()
    negated = re.compile(r"\b(?:sin|ni|no|ningún|ninguna|nada(?: de)?)\s+(?:\w+\s+){0,2}$", re.I)
    if any(
        m.group(0).casefold() not in own and not negated.search(text[: m.start()])
        for m in _TEXT_WORDS.finditer(text)
    ):
        return True
    if "$" in text and "$" not in case["text"]:
        return True
    digits = lambda t: {re.sub(r"\D", "", m) for m in re.findall(r"\d(?:[\d.,]*\d)?", t)}  # noqa: E731
    facts = set().union(*(digits(str(v)) for _, v in case.get("highlights", ()))) - digits(
        case["text"]
    )
    return bool(facts & digits(text))


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--cases", default=str(HERE / "cases.json"))
    parser.add_argument("--label", required=True, help="names the results file")
    parser.add_argument("--cap-usd", default="0.60", help="stop making calls past this")
    parser.add_argument("--only", default="", help="run only the case ids with this prefix")
    parser.add_argument("--module-file", default="", help="an older context_ai.py to run")
    args = parser.parse_args(argv)
    _load_env(args.env_file)

    from qualify_creative.schemas import BrandKit, ToneAxes

    from qualify_api import claude_tools
    from qualify_api.creative import context_ai

    if args.module_file:
        import importlib.util

        spec_ = importlib.util.spec_from_file_location("context_ai_under_test", args.module_file)
        assert spec_ and spec_.loader
        context_ai = importlib.util.module_from_spec(spec_)
        sys.modules[spec_.name] = context_ai  # dataclasses look their module up here
        spec_.loader.exec_module(context_ai)
    dropped = {"n": 0}
    dropped_examples: list[dict[str, str]] = []
    if hasattr(context_ai, "scene_text_request"):
        original_check = context_ai.scene_text_request

        def counting_check(text: str, data: Any) -> str:
            found = original_check(text, data)
            dropped["n"] += bool(found)
            if found:
                dropped_examples.append({"found": found, "text": text})
            return found

        context_ai.scene_text_request = counting_check

    records: list[Any] = []
    claude_tools.configure_consumption_sink(records.append)
    spent = lambda: sum((r.cost_usd for r in records), Decimal(0))  # noqa: E731

    spec = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    brand = dict(spec["brand"])
    brand.pop("_note", None)
    kit = BrandKit(
        brand_id=uuid4(),
        positioning=brand["positioning"],
        audience=brand["audience"],
        regional_variant=brand.get("regional_variant", "es-CO"),
        tone_axes=ToneAxes(**brand["tone_axes"]),
        banned_words=tuple(brand.get("banned_words", ())),
        cta_patterns=tuple(brand.get("cta_patterns", ())),
    )
    attribution = claude_tools.Attribution.no_business("eval-mejorar-texto")
    v4 = hasattr(context_ai, "ContextVersion")
    cap = Decimal(args.cap_usd)
    rows: list[dict[str, Any]] = []

    def call(case: dict[str, Any], text: str, previous: tuple[str, ...]) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "text": text,
            "piece": case["piece"],
            "scene": bool(case.get("scene")),
            "product": case.get("product", ""),
            "highlights": tuple(tuple(pair) for pair in case.get("highlights", ())),
            "must_mention": case.get("must_mention", ""),
            "must_avoid": case.get("must_avoid", ""),
        }
        if v4:
            fields.update(
                content_type=case.get("content_type", ""),
                format=case.get("format", ""),
                previous_versions=previous,
            )
        before = len(records)
        started = time.monotonic()
        try:
            proposal = context_ai.enhance_context(
                context_ai.ContextInput(**fields), kit, attribution=attribution
            )
        except context_ai.ContextUnavailable as exc:
            return {"error": f"{type(exc).__name__}: {exc}", "texts": []}
        finally:
            seconds = round(time.monotonic() - started, 1)
        texts = (
            [v.text for v in proposal.versions] if v4 else [proposal.text]  # type: ignore[attr-defined]
        )
        approaches = [v.approach for v in proposal.versions] if v4 else []
        cost = sum((r.cost_usd for r in records[before:]), Decimal(0))
        return {
            "texts": texts,
            "approaches": approaches,
            "added_facts": list(proposal.added_facts),
            "cost_usd": str(cost),
            "seconds": seconds,
            "in": proposal.input_tokens,
            "out": proposal.output_tokens,
        }

    for case in spec["cases"]:
        if args.only and not case["id"].startswith(args.only):
            continue
        if spent() >= cap:
            print(f"cap reached at {spent()} USD; stopping", file=sys.stderr)
            break
        source = " ".join(
            [case["text"], case.get("product", ""), case.get("must_mention", "")]
            + [case.get("format", "")]
            + [str(v) for _, v in case.get("highlights", ())]
        )
        first = call(case, case["text"], ())
        if v4:
            second = call(case, case["text"], tuple(first["texts"]))
        else:
            second = call(case, first["texts"][0] if first["texts"] else case["text"], ())
        within = [
            similarity(a, b)
            for press in (first, second)
            for a, b in itertools.combinations(press["texts"], 2)
        ]
        across = [similarity(a, b) for a in first["texts"] for b in second["texts"]]
        across_j = [jaccard(a, b) for a in first["texts"] for b in second["texts"]]
        all_texts = first["texts"] + second["texts"]
        row = {
            "id": case["id"],
            "original": case["text"],
            "press_1": first,
            "press_2": second,
            "within_press_mean_similarity": _mean(within),
            "within_press_max_similarity": round(max(within), 3) if within else None,
            "across_presses_max_similarity": round(max(across), 3) if across else None,
            "across_presses_mean_similarity": _mean(across),
            "across_presses_mean_jaccard": _mean(across_j),
            "duplicates": len(all_texts) - len({t.casefold() for t in all_texts}),
            "new_numbers": sorted({n for t in all_texts for n in new_numbers(t, source)}),
            "scene": bool(case.get("scene")),
            "asks_for_text": sum(asks_for_text(t, case) for t in all_texts)
            if case.get("scene")
            else 0,
            "shown": len(all_texts),
        }
        rows.append(row)
        print(json.dumps({k: v for k, v in row.items() if not k.startswith("press")}))

    calls = [p for r in rows for p in (r["press_1"], r["press_2"]) if "cost_usd" in p]
    summary = {
        "label": args.label,
        "prompt_version": context_ai.CONTEXT_PROMPT_VERSION,
        "model": context_ai.CONTEXT_MODEL.label,
        "model_revisions": sorted({r.model_revision or "" for r in records}),
        "when": datetime.now(UTC).isoformat(timespec="seconds"),
        "cases": len(rows),
        "calls": len(records),
        "errors": sum(1 for r in rows for p in (r["press_1"], r["press_2"]) if "error" in p),
        "total_usd": str(spent()),
        "usd_per_call": str((spent() / len(records)).quantize(Decimal("0.0001")))
        if records
        else "0",
        "mean_seconds": _mean([p["seconds"] for p in calls]),
        "within_press_mean_similarity": _mean(
            [r["within_press_mean_similarity"] for r in rows if r["press_1"]["texts"][1:]]
        ),
        "across_presses_max_similarity_mean": _mean(
            [r["across_presses_max_similarity"] or 0.0 for r in rows]
        ),
        "across_presses_mean_jaccard": _mean([r["across_presses_mean_jaccard"] for r in rows]),
        "duplicates": sum(r["duplicates"] for r in rows),
        "cases_with_new_numbers": [r["id"] for r in rows if r["new_numbers"]],
        "scene_versions_shown": sum(r["shown"] for r in rows if r["scene"]),
        "scene_versions_asking_for_text": sum(r["asks_for_text"] for r in rows),
        "scene_versions_dropped_by_filter": dropped["n"],
        "dropped_examples": dropped_examples,
    }
    out = HERE / "results" / f"{args.label}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(
        json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

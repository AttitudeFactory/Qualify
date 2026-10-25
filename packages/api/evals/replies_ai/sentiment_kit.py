"""The sentiment golden set and its blind labelling kit (m-24854495). Offline, no API.

    # 1. the public 408 of the intent set, with an EMPTY sentiment column (in the repo)
    just sentiment-kit public

    # 2. real comments exported read-only (export_real_comments.sql, founder-approved)
    #    -> anonymized again, deduplicated, sampled, split (OUTSIDE the repo)
    just sentiment-kit anonymize --raw ~/qualify-eval-data/sentiment/raw/comments-YYYYMMDD.csv

    # 3. the kit: master set + one blind sheet per person + the guide (OUTSIDE the repo)
    just sentiment-kit build

    # 4. after both sheets come back: κ, disagreements for a third person, the golden set
    just sentiment-kit merge --sheet raul=<path>.csv --sheet yesika=<path>.csv
    just sentiment-kit merge ... --adjudicated <dir>/desacuerdos.csv   # once decided

Real comments never go inside the repository: every command that writes them refuses a
path inside the git checkout. The sheets carry only `id` + text, in a different random
order per person, with no model output and no split/source/country.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import shutil
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
INTENT_GOLDEN = REPO / "packages/api/eval_data/intent_golden_v1.jsonl"
PUBLIC_SET = REPO / "packages/api/eval_data/sentiment_golden_v1.public.jsonl"
GUIDE = REPO / "docs/guia-etiquetado-sentimiento.md"
DEFAULT_DIR = Path.home() / "qualify-eval-data" / "sentiment"
SEED = 24854495
LABELERS = ("raul", "yesika")


def _outside_repo(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if resolved == REPO or REPO in resolved.parents:
        raise SystemExit(f"refusing to write real comments inside the repository: {resolved}")
    return resolved


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_jsonl(path: Path, header: Sequence[str], items: Sequence[Any]) -> None:
    lines = [f"# {h}" for h in header]
    lines += [json.dumps(it.to_json(), ensure_ascii=False) for it in items]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _load(path: Path) -> list[Any]:
    from qualify_api.evals.comment_sentiment import parse_sentiment_golden  # noqa: PLC0415

    return parse_sentiment_golden(path.read_text(encoding="utf-8").splitlines())


# --- public -------------------------------------------------------------------------


def public_items(intent_lines: Sequence[str]) -> list[Any]:
    """The intent golden set's comments with their split, an empty sentiment, and a
    stable id by line order (`pub-0001`…). Texts repeat across posts («Belleza»), so the
    id is positional, pinned to the intent file's sha256 in the header."""
    from qualify_api.evals.comment_sentiment import SentimentItem  # noqa: PLC0415

    items = []
    for line in intent_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        raw = json.loads(stripped)
        items.append(
            SentimentItem(
                id=f"pub-{len(items) + 1:04d}",
                text=str(raw["text"]).strip(),
                split=str(raw["split"]),
                source="public:instagram",
                country="",
            )
        )
    return items


def cmd_public(args: argparse.Namespace) -> int:
    lines = args.intent.read_text(encoding="utf-8").splitlines()
    items = public_items(lines)
    header = [
        "Qualify sentiment golden set v1 — PUBLIC part (m-24854495). Schema in",
        "packages/api/src/qualify_api/evals/comment_sentiment.py.",
        f"Built from intent_golden_v1.jsonl (sha256 {_sha256(args.intent)}), same texts and",
        "the same dev/test split; ids are positional. `sentiment` is EMPTY until two people",
        "label it blind (docs/guia-etiquetado-sentimiento.md). Country is unknown for these.",
    ]
    _write_jsonl(args.out, header, items)
    splits = {s: sum(1 for it in items if it.split == s) for s in ("dev", "test")}
    sys.stdout.write(f"{args.out}: {len(items)} comments {splits}\n")
    return 0


# --- anonymize (real comments) ------------------------------------------------------


def real_items(
    rows: Sequence[dict[str, str]], *, target: int, max_per_business: int, seed: int
) -> list[Any]:
    """Raw export rows → anonymized, deduplicated, sampled items with a frozen split.
    Sampling is per business (at most `max_per_business`), then down to `target` keeping
    each business's share; the split is assigned per business so every one is in both."""
    from qualify_api.evals.comment_sentiment import (  # noqa: PLC0415
        SentimentItem,
        anonymize,
        assign_split,
        item_id,
    )

    by_business: dict[str, dict[str, tuple[str, str]]] = {}
    for row in rows:
        text = anonymize(row.get("text") or "")
        if not text:
            continue
        business = " ".join((row.get("business") or "desconocido").lower().split())
        slug = business.replace(" ", "-")
        country = (row.get("country") or "").strip().upper()
        kind = (row.get("kind") or "comment").strip()
        by_business.setdefault(slug, {}).setdefault(text, (country, kind))
    rng = random.Random(seed)
    sampled: dict[str, list[str]] = {}
    for slug, texts in sorted(by_business.items()):
        keys = sorted(texts)
        rng.shuffle(keys)
        sampled[slug] = keys[:max_per_business]
    total = sum(len(v) for v in sampled.values())
    if total > target:
        for slug, keys in sampled.items():
            sampled[slug] = keys[: max(1, round(target * len(keys) / total))]
    items = []
    for slug, keys in sorted(sampled.items()):
        ids = {item_id("real", f"{slug}\n{t}"): t for t in keys}
        split = assign_split(list(ids), seed=seed)
        for ident, text in sorted(ids.items()):
            country, kind = by_business[slug][text]
            items.append(
                SentimentItem(
                    id=ident,
                    text=text,
                    split=split[ident],
                    source=f"real:{slug}:{kind}",
                    country=country,
                )
            )
    return items


def cmd_anonymize(args: argparse.Namespace) -> int:
    out = _outside_repo(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with args.raw.expanduser().open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    items = real_items(
        rows, target=args.target, max_per_business=args.max_per_business, seed=args.seed
    )
    header = [
        "Qualify sentiment golden set v1 — REAL part (m-24854495). NEVER COMMIT THIS FILE.",
        f"From {args.raw.name} (sha256 {_sha256(args.raw.expanduser())}), {len(rows)} rows,",
        "masked in SQL and again here (@usuario, [teléfono], [correo], [enlace]).",
        f"Sampled: target {args.target}, at most {args.max_per_business} per business, "
        f"seed {args.seed}; split per business.",
    ]
    _write_jsonl(out, header, items)
    per: dict[str, int] = {}
    for it in items:
        per[it.source.split(":")[1]] = per.get(it.source.split(":")[1], 0) + 1
    sys.stdout.write(f"{out}: {len(items)} comments {per}\n")
    return 0


# --- build --------------------------------------------------------------------------


def cmd_build(args: argparse.Namespace) -> int:
    from qualify_api.evals.comment_sentiment import plan_kit, write_sheet  # noqa: PLC0415

    out = _outside_repo(args.dir)
    out.mkdir(parents=True, exist_ok=True)
    items = _load(args.public)
    sources = [str(args.public)]
    if args.real:
        real = _load(args.real.expanduser())
        sources.append(str(args.real))
        items += real
    elif not args.public_only:
        raise SystemExit("no --real set: pass it, or --public-only to build without it")
    labelers = tuple(x.strip() for x in args.labelers.split(",") if x.strip())
    plan = plan_kit(items, labelers, overlap=args.overlap, seed=args.seed)
    by_id = {it.id: it for it in items}
    master = out / "master.jsonl"
    _write_jsonl(
        master,
        [
            "Sentiment golden set v1 — master (m-24854495). Contains REAL comments: never commit.",
            f"Built {date.today().isoformat()} from {', '.join(sources)}; seed {args.seed}.",
        ],
        items,
    )
    sheets = {}
    for k, name in enumerate(labelers):
        sheet = out / f"etiquetado_{name}.csv"
        write_sheet(sheet, [by_id[i] for i in plan.assignments[name]], seed=args.seed + k + 1)
        sheets[name] = {"file": sheet.name, "items": len(plan.assignments[name])}
    if GUIDE.exists():
        shutil.copy(GUIDE, out / GUIDE.name)
    manifest = {
        "ticket": "m-24854495",
        "built": date.today().isoformat(),
        "seed": args.seed,
        "items": len(items),
        "by_origin": {o: sum(1 for it in items if it.origin == o) for o in ("public", "real")},
        "by_split": {s: sum(1 for it in items if it.split == s) for s in ("dev", "test")},
        "overlap": len(plan.overlap),
        "overlap_ids": list(plan.overlap),
        "sheets": sheets,
        "master_sha256": _sha256(master),
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    summary = {k: v for k, v in manifest.items() if k != "overlap_ids"}
    sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return 0


# --- merge --------------------------------------------------------------------------


def _adjudicated(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    with path.expanduser().open(encoding="utf-8-sig", newline="") as fh:
        return {
            row["id"]: row["decision"].strip()
            for row in csv.DictReader(fh)
            if (row.get("decision") or "").strip()
        }


def cmd_merge(args: argparse.Namespace) -> int:
    from qualify_api.evals.comment_sentiment import merge_labels, read_sheet  # noqa: PLC0415

    out = _outside_repo(args.dir)
    master = _load(args.master or out / "master.jsonl")
    sheets = {}
    for spec in args.sheet:
        name, sep, path = spec.partition("=")
        if not sep:
            raise SystemExit(f"--sheet needs name=path, got {spec!r}")
        sheets[name.strip()] = read_sheet(Path(path).expanduser())
    result = merge_labels(master, sheets, _adjudicated(args.adjudicated))
    golden = out / "golden.jsonl"
    _write_jsonl(
        golden,
        [
            "Sentiment golden set v1 — merged labels (m-24854495). Contains REAL comments: "
            "never commit.",
            f"Merged {date.today().isoformat()}; κ={result.kappa} on "
            f"{result.double_labeled} double-labelled; status {result.status}.",
            "An empty sentiment = the two people disagreed and no third person decided yet.",
        ],
        result.items,
    )
    if result.disagreements:
        sheet = out / "desacuerdos.csv"
        with sheet.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(result.disagreements[0]))
            writer.writeheader()
            writer.writerows(result.disagreements)
    report = result.to_json()
    (out / "acuerdo.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return 0 if result.status != "failed" else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("public", help="the public 408 with an empty sentiment (repo)")
    p.add_argument("--intent", type=Path, default=INTENT_GOLDEN)
    p.add_argument("--out", type=Path, default=PUBLIC_SET)
    p.set_defaults(func=cmd_public)

    a = sub.add_parser("anonymize", help="raw export CSV -> real.jsonl (outside the repo)")
    a.add_argument("--raw", type=Path, required=True)
    a.add_argument("--out", type=Path, default=DEFAULT_DIR / "real.jsonl")
    a.add_argument("--target", type=int, default=200)
    a.add_argument("--max-per-business", type=int, default=80)
    a.add_argument("--seed", type=int, default=SEED)
    a.set_defaults(func=cmd_anonymize)

    b = sub.add_parser("build", help="master set + blind sheets + guide (outside the repo)")
    b.add_argument("--public", type=Path, default=PUBLIC_SET)
    b.add_argument("--real", type=Path, default=None)
    b.add_argument("--public-only", action="store_true")
    b.add_argument("--dir", type=Path, default=DEFAULT_DIR / "kit")
    b.add_argument("--labelers", default=",".join(LABELERS))
    b.add_argument("--overlap", type=int, default=100)
    b.add_argument("--seed", type=int, default=SEED)
    b.set_defaults(func=cmd_build)

    m = sub.add_parser("merge", help="sheets -> κ + golden.jsonl (+ desacuerdos.csv)")
    m.add_argument("--dir", type=Path, default=DEFAULT_DIR / "kit")
    m.add_argument("--master", type=Path, default=None)
    m.add_argument("--sheet", action="append", required=True, help="name=path.csv")
    m.add_argument("--adjudicated", type=Path, default=None)
    m.set_defaults(func=cmd_merge)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

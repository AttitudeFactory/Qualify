"""Measuring comment SENTIMENT on real comments before Claude Haiku replaces robertuito
(m-24854495, founder decision 2026-10-25, option C). Pure and offline: the live run is
`packages/api/evals/replies_ai/run_experiment.py --sentiment`, the labelling kit is
`packages/api/evals/replies_ai/sentiment_kit.py`, the rules the labellers follow are in
`docs/guia-etiquetado-sentimiento.md`.

Gates (the ticket's acceptance criteria):

1. **The labels** — two people label blind; Cohen's κ on sentiment ≥ `MIN_KAPPA` over at
   least `MIN_DOUBLE_LABELED` overlapping comments, or nothing below counts.
2. **Each class** (`pos`, `neu`, `neg`) on the frozen `test` split: precision ≥ 0.80,
   recall ≥ 0.70, support ≥ 8; `neg` recall ≥ 0.90. A class below its bar is reported
   «no fiable» by name, never averaged away.
3. **Against the baseline:** Haiku's macro-F1 ≥ robertuito's on the same items.

Also reported, not gated: the confusion matrix, slices (sarcasm, emoji-only, country,
public vs real), calibration of the model's confidence, cost and p50/p95 latency per
batch, and whether the prompt cache was read.

Golden JSONL, one comment per line (`#` and blank lines ignored):

    {"id": "real-3f2a9c01d4", "text": "...", "sentiment": "neg", "split": "test",
     "source": "real:bianki", "country": "VE", "sarcasm": true,
     "labelers": {"raul": "neg", "yesika": "neg"}}

`sentiment` empty / missing = not labelled yet (the item is skipped by the scorer and
counted). Only the text is ever stored: mentions masked as `@usuario`, phone numbers and
e-mails masked (`anonymize`).
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from qualify_api.evals.comment_replies import cohen_kappa

SENTIMENTS: Final = ("pos", "neu", "neg")
MIN_KAPPA: Final = 0.70
MIN_DOUBLE_LABELED: Final = 50
MIN_PRECISION: Final = 0.80
MIN_RECALL: Final = 0.70
MIN_SUPPORT: Final = 8
RECALL_BARS: Final[Mapping[str, float]] = {"neg": 0.90}
#: A slice with fewer items than this is reported but flagged `small` — no verdict.
MIN_SLICE: Final = 15
#: Confidence bins for calibration (lower edges; the last bin closes at 1.0).
CONFIDENCE_BINS: Final = (0.0, 0.5, 0.7, 0.85, 0.95)

#: robertuito's labels, and the CSV labels the people write.
_LABEL_ALIASES: Final[Mapping[str, str]] = {
    "pos": "pos",
    "positivo": "pos",
    "neg": "neg",
    "negativo": "neg",
    "neu": "neu",
    "neutro": "neu",
    "neutral": "neu",
}


def normalize_label(raw: Any) -> str | None:
    """`POS`/`Negativo`/`neu `… into `pos`/`neg`/`neu`; None for empty or unknown."""
    if raw is None:
        return None
    return _LABEL_ALIASES.get(str(raw).strip().lower())


# --- anonymization -------------------------------------------------------------------

_MENTION: Final = re.compile(r"(?<![\w.])@[\w.]+", re.UNICODE)
_EMAIL: Final = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
#: 7+ digits, allowing spaces, dots, dashes and parentheses between them, optional +.
_PHONE: Final = re.compile(r"\+?\d(?:[\s().-]*\d){6,}")
_URL: Final = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
#: «120.000.000» is a price, not a phone: dotted/comma thousands are kept.
_THOUSANDS: Final = re.compile(r"\d{1,3}(?:[.,]\d{3})+")


def _mask_phone(match: re.Match[str]) -> str:
    return match.group(0) if _THOUSANDS.fullmatch(match.group(0)) else "[teléfono]"


def anonymize(text: str) -> str:
    """Only the words stay: e-mails, links, phone numbers and @mentions are masked.
    Order matters — an e-mail contains an `@` a mention would half-eat."""
    out = _EMAIL.sub("[correo]", text)
    out = _URL.sub("[enlace]", out)
    out = _MENTION.sub("@usuario", out)
    out = _PHONE.sub(_mask_phone, out)
    return " ".join(out.split())


def is_emoji_only(text: str) -> bool:
    """No letter or digit once mentions are dropped (`🔥🔥`, `❤️ @usuario`, `!!`)."""
    stripped = _MENTION.sub("", text)
    if not stripped.strip():
        return False
    return not any(unicodedata.category(ch)[0] in ("L", "N") for ch in stripped)


def item_id(prefix: str, text: str) -> str:
    return f"{prefix}-{hashlib.sha1(text.encode('utf-8')).hexdigest()[:10]}"


# --- golden set ----------------------------------------------------------------------


@dataclass(frozen=True)
class SentimentItem:
    id: str
    text: str
    split: str
    source: str = ""
    country: str = ""
    sentiment: str | None = None
    sarcasm: bool = False
    labelers: Mapping[str, str] = field(default_factory=dict)

    @property
    def origin(self) -> str:
        """`real` (a tenant's comment) or `public` (the 408 of the intent set)."""
        return "real" if self.source.startswith("real") else "public"

    @property
    def emoji_only(self) -> bool:
        return is_emoji_only(self.text)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "sentiment": self.sentiment or "",
            "split": self.split,
            "source": self.source,
            "country": self.country,
            "sarcasm": self.sarcasm,
            "labelers": dict(self.labelers),
        }


def parse_sentiment_golden(lines: Iterable[str]) -> list[SentimentItem]:
    items: list[SentimentItem] = []
    seen: set[str] = set()
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            raw = json.loads(stripped)
            ident = str(raw["id"])
            text = str(raw["text"]).strip()
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"sentiment golden line {number}: {exc}") from exc
        if not text:
            raise ValueError(f"sentiment golden line {number}: empty text")
        if ident in seen:
            raise ValueError(f"sentiment golden line {number}: duplicate id {ident}")
        seen.add(ident)
        split = str(raw.get("split", ""))
        if split not in ("dev", "test"):
            raise ValueError(f"sentiment golden line {number}: split must be dev or test")
        label_raw = raw.get("sentiment")
        label = normalize_label(label_raw)
        if label_raw not in (None, "") and label is None:
            raise ValueError(f"sentiment golden line {number}: unknown label {label_raw!r}")
        items.append(
            SentimentItem(
                id=ident,
                text=text,
                split=split,
                source=str(raw.get("source", "")),
                country=str(raw.get("country", "")).upper(),
                sentiment=label,
                sarcasm=bool(raw.get("sarcasm", False)),
                labelers={str(k): str(v) for k, v in (raw.get("labelers") or {}).items()},
            )
        )
    return items


# --- metrics -------------------------------------------------------------------------


@dataclass(frozen=True)
class ClassScore:
    label: str
    support: int
    predicted: int
    true_positives: int

    @property
    def precision(self) -> float | None:
        return self.true_positives / self.predicted if self.predicted else None

    @property
    def recall(self) -> float | None:
        return self.true_positives / self.support if self.support else None

    @property
    def f1(self) -> float:
        p, r = self.precision or 0.0, self.recall or 0.0
        return 2 * p * r / (p + r) if p + r else 0.0

    @property
    def min_recall(self) -> float:
        return RECALL_BARS.get(self.label, MIN_RECALL)

    @property
    def reliable(self) -> bool:
        p, r = self.precision, self.recall
        return (
            self.support >= MIN_SUPPORT
            and p is not None
            and r is not None
            and p >= MIN_PRECISION
            and r >= self.min_recall
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "support": self.support,
            "predicted": self.predicted,
            "true_positives": self.true_positives,
            "precision": self.precision,
            "recall": self.recall,
            "f1": round(self.f1, 4),
            "min_recall": self.min_recall,
            "reliable": self.reliable,
        }


@dataclass(frozen=True)
class SentimentScores:
    n: int
    unanswered: int
    per_class: Mapping[str, ClassScore]
    #: confusion[gold][predicted]; an unanswered item is predicted `none`.
    confusion: Mapping[str, Mapping[str, int]]

    @property
    def macro_f1(self) -> float:
        return sum(c.f1 for c in self.per_class.values()) / len(self.per_class)

    @property
    def accuracy(self) -> float | None:
        if not self.n:
            return None
        return sum(self.confusion[s][s] for s in SENTIMENTS) / self.n

    @property
    def unreliable(self) -> list[str]:
        return [label for label, c in self.per_class.items() if not c.reliable]

    def to_json(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "unanswered": self.unanswered,
            "accuracy": self.accuracy,
            "macro_f1": round(self.macro_f1, 4),
            "per_class": {k: v.to_json() for k, v in self.per_class.items()},
            "confusion": {g: dict(row) for g, row in self.confusion.items()},
            "unreliable": self.unreliable,
        }


def score(gold: Sequence[str], predicted: Sequence[str | None]) -> SentimentScores:
    if len(gold) != len(predicted):
        raise ValueError(f"{len(predicted)} predictions for {len(gold)} gold labels")
    columns = (*SENTIMENTS, "none")
    confusion = {g: dict.fromkeys(columns, 0) for g in SENTIMENTS}
    for g, p in zip(gold, predicted, strict=True):
        confusion[g][p if p in SENTIMENTS else "none"] += 1
    per_class = {
        s: ClassScore(
            label=s,
            support=sum(confusion[s].values()),
            predicted=sum(confusion[g][s] for g in SENTIMENTS),
            true_positives=confusion[s][s],
        )
        for s in SENTIMENTS
    }
    return SentimentScores(
        n=len(gold),
        unanswered=sum(1 for p in predicted if p not in SENTIMENTS),
        per_class=per_class,
        confusion=confusion,
    )


def slices(items: Sequence[SentimentItem]) -> dict[str, list[int]]:
    """Index lists per slice the ticket names: sarcasm, emoji-only, country, origin."""
    out: dict[str, list[int]] = {"all": list(range(len(items)))}
    out["sarcasm"] = [i for i, it in enumerate(items) if it.sarcasm]
    out["emoji_only"] = [i for i, it in enumerate(items) if it.emoji_only]
    for i, it in enumerate(items):
        out.setdefault(f"country:{it.country or 'desconocido'}", []).append(i)
        out.setdefault(f"origin:{it.origin}", []).append(i)
    return out


def sliced_scores(
    items: Sequence[SentimentItem], predicted: Sequence[str | None]
) -> dict[str, dict[str, Any]]:
    report: dict[str, dict[str, Any]] = {}
    for name, idx in sorted(slices(items).items()):
        if not idx:
            report[name] = {"n": 0, "small": True}
            continue
        scores = score([items[i].sentiment or "" for i in idx], [predicted[i] for i in idx])
        report[name] = {
            "n": scores.n,
            "small": scores.n < MIN_SLICE,
            "accuracy": scores.accuracy,
            "macro_f1": round(scores.macro_f1, 4),
            "recall": {k: v.recall for k, v in scores.per_class.items()},
        }
    return report


def calibration(
    gold: Sequence[str], predicted: Sequence[str | None], confidence: Sequence[float | None]
) -> dict[str, Any]:
    """Accuracy per confidence bin and the expected calibration error (ECE). Items with
    no confidence are counted apart — a `score` that is not there is not a real score."""
    edges = (*CONFIDENCE_BINS, 1.0000001)
    bins: list[dict[str, Any]] = []
    ece = 0.0
    scored = [
        (g, p, c)
        for g, p, c in zip(gold, predicted, confidence, strict=True)
        if c is not None and p is not None
    ]
    for low, high in zip(edges, edges[1:], strict=False):
        inside = [(g, p, c) for g, p, c in scored if low <= c < high]
        if not inside:
            bins.append({"from": low, "to": min(high, 1.0), "n": 0})
            continue
        acc = sum(1 for g, p, _ in inside if g == p) / len(inside)
        mean_c = sum(c for _, _, c in inside) / len(inside)
        ece += len(inside) / len(scored) * abs(acc - mean_c)
        bins.append(
            {
                "from": low,
                "to": min(high, 1.0),
                "n": len(inside),
                "accuracy": round(acc, 4),
                "mean_confidence": round(mean_c, 4),
            }
        )
    return {
        "with_confidence": len(scored),
        "without_confidence": len(gold) - len(scored),
        "ece": round(ece, 4) if scored else None,
        "bins": bins,
    }


def percentile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile (q in 0..100); None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[rank - 1]


def latency_report(latencies_s: Sequence[float], batch_size: int) -> dict[str, Any]:
    return {
        "batch_size": batch_size,
        "batches": len(latencies_s),
        "p50_s": percentile(latencies_s, 50),
        "p95_s": percentile(latencies_s, 95),
        "max_s": max(latencies_s) if latencies_s else None,
    }


def cache_report(cache_reads: Sequence[int], cache_writes: Sequence[int]) -> dict[str, Any]:
    """The system prompt is cached (`claude_tools.create_turn`); every batch after the
    first, within 5 minutes, should READ it. `ok` is False when no batch did — a silent
    invalidator or a prefix under the model's minimum cacheable length."""
    after_first = list(cache_reads[1:])
    return {
        "cache_read_tokens": list(cache_reads),
        "cache_creation_tokens": list(cache_writes),
        "batches_reading_cache": sum(1 for r in cache_reads if r > 0),
        "ok": bool(after_first) and all(r > 0 for r in after_first),
        "checkable": len(cache_reads) >= 2,
    }


def decision(candidate: SentimentScores, baseline: SentimentScores | None) -> dict[str, Any]:
    """The ticket's switch rule: every class reliable AND candidate macro-F1 ≥ baseline's."""
    beats = None if baseline is None else candidate.macro_f1 >= baseline.macro_f1
    return {
        "all_classes_reliable": not candidate.unreliable,
        "unreliable": candidate.unreliable,
        "candidate_macro_f1": round(candidate.macro_f1, 4),
        "baseline_macro_f1": None if baseline is None else round(baseline.macro_f1, 4),
        "macro_f1_at_least_baseline": beats,
        "switch": (not candidate.unreliable) and bool(beats),
    }


# --- labelling kit -------------------------------------------------------------------

#: The labellers' CSV columns (Spanish: they read it). Order is the sheet's.
SHEET_COLUMNS: Final = ("id", "comentario", "sentimiento", "sarcasmo", "dudoso", "nota")


@dataclass(frozen=True)
class KitPlan:
    """Who labels what. `overlap` ids go to both people (κ); the rest is split."""

    overlap: tuple[str, ...]
    assignments: Mapping[str, tuple[str, ...]]


def assign_split(ids: Sequence[str], *, seed: int, test_share: float = 0.5) -> dict[str, str]:
    """A frozen dev/test split for NEW items (the public 408 keep theirs). Before labels
    exist it cannot be stratified by class; it is stratified by the caller's grouping
    (call once per business)."""
    order = sorted(ids)
    random.Random(seed).shuffle(order)
    cut = round(len(order) * test_share)
    return {i: ("test" if n < cut else "dev") for n, i in enumerate(order)}


def plan_kit(
    items: Sequence[SentimentItem], labelers: Sequence[str], *, overlap: int, seed: int
) -> KitPlan:
    """`overlap` items for everyone, stratified by split × origin so κ is not only measured
    on the easy public half; the rest dealt round-robin after a seeded shuffle."""
    if len(labelers) < 2:
        raise ValueError("κ needs at least two labelers")
    if overlap < MIN_DOUBLE_LABELED:
        raise ValueError(f"overlap must be ≥ {MIN_DOUBLE_LABELED} to compute κ")
    if overlap > len(items):
        raise ValueError(f"overlap {overlap} > {len(items)} items")
    rng = random.Random(seed)
    strata: dict[tuple[str, str], list[str]] = {}
    for it in sorted(items, key=lambda x: x.id):
        strata.setdefault((it.split, it.origin), []).append(it.id)
    for ids in strata.values():
        rng.shuffle(ids)
    chosen: list[str] = []
    total = len(items)
    for key in sorted(strata):
        share = round(overlap * len(strata[key]) / total)
        chosen.extend(strata[key][:share])
    leftover = [i for key in sorted(strata) for i in strata[key] if i not in set(chosen)]
    rng.shuffle(leftover)
    while len(chosen) < overlap:
        chosen.append(leftover.pop())
    chosen = chosen[:overlap]
    taken = set(chosen)
    rest = [it.id for it in sorted(items, key=lambda x: x.id) if it.id not in taken]
    rng.shuffle(rest)
    assignments = {
        name: tuple(chosen) + tuple(rest[k :: len(labelers)]) for k, name in enumerate(labelers)
    }
    return KitPlan(overlap=tuple(chosen), assignments=assignments)


def write_sheet(path: Path, items: Sequence[SentimentItem], *, seed: int) -> None:
    """A blind sheet: id + text only, in a per-person random order. UTF-8 with BOM so
    Excel opens the accents right; Google Sheets imports it as is."""
    order = list(items)
    random.Random(seed).shuffle(order)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(SHEET_COLUMNS)
        for it in order:
            writer.writerow([it.id, it.text, "", "", "", ""])


@dataclass(frozen=True)
class SheetRow:
    id: str
    sentiment: str | None
    sarcasm: bool
    doubtful: bool
    note: str


def _yes(raw: str | None) -> bool:
    return (raw or "").strip().lower() in ("si", "sí", "x", "1", "true", "s")


def read_sheet(path: Path) -> dict[str, SheetRow]:
    """A filled sheet back. Unknown labels raise (with the row) instead of being
    silently dropped: a typo in a label is a labeling error to fix, not a skip."""
    rows: dict[str, SheetRow] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for number, raw in enumerate(csv.DictReader(fh), 2):
            ident = (raw.get("id") or "").strip()
            if not ident:
                continue
            value = (raw.get("sentimiento") or "").strip()
            label = normalize_label(value)
            if value and label is None:
                raise ValueError(f"{path.name} row {number}: unknown sentimiento {value!r}")
            rows[ident] = SheetRow(
                id=ident,
                sentiment=label,
                sarcasm=_yes(raw.get("sarcasmo")),
                doubtful=_yes(raw.get("dudoso")),
                note=(raw.get("nota") or "").strip(),
            )
    return rows


def support_by_split(items: Sequence[SentimentItem]) -> dict[str, dict[str, int]]:
    """Labelled items per split and class — the `neg` count in `test` is what the NEG
    recall bar rests on (it needs ≥ `MIN_SUPPORT`; ≥ 15 is recommended)."""
    out = {split: dict.fromkeys(SENTIMENTS, 0) for split in ("dev", "test")}
    for it in items:
        if it.sentiment in SENTIMENTS and it.split in out:
            out[it.split][it.sentiment] += 1
    return out


@dataclass(frozen=True)
class MergeResult:
    items: list[SentimentItem]
    kappa: float | None
    double_labeled: int
    agreement: float | None
    disagreements: list[dict[str, Any]]
    missing: Mapping[str, int]

    @property
    def status(self) -> str:
        if self.double_labeled < MIN_DOUBLE_LABELED:
            return "pending"
        return "passed" if self.kappa is not None and self.kappa >= MIN_KAPPA else "failed"

    def to_json(self) -> dict[str, Any]:
        return {
            "double_labeled": self.double_labeled,
            "min_double_labeled": MIN_DOUBLE_LABELED,
            "kappa_sentiment": self.kappa,
            "min_kappa": MIN_KAPPA,
            "raw_agreement": self.agreement,
            "status": self.status,
            "disagreements": len(self.disagreements),
            "missing_labels": dict(self.missing),
            "labelled": sum(1 for it in self.items if it.sentiment),
            "total": len(self.items),
            "support_by_split": support_by_split(self.items),
        }


def merge_labels(
    master: Sequence[SentimentItem],
    sheets: Mapping[str, Mapping[str, SheetRow]],
    adjudicated: Mapping[str, str] | None = None,
) -> MergeResult:
    """Fold the people's sheets into the master set. A single label is the label; two
    that agree are the label; two that disagree stay EMPTY until `adjudicated` (a third
    person) decides — never resolved by majority of one or by the model. Sarcasm is
    marked if any labeller marked it."""
    adjudicated = adjudicated or {}
    names = sorted(sheets)
    pairs_a: list[str] = []
    pairs_b: list[str] = []
    disagreements: list[dict[str, Any]] = []
    missing = dict.fromkeys(names, 0)
    merged: list[SentimentItem] = []
    for it in master:
        given = {
            name: sheets[name][it.id]
            for name in names
            if it.id in sheets[name] and sheets[name][it.id].sentiment
        }
        for name in names:
            if it.id in sheets[name] and not sheets[name][it.id].sentiment:
                missing[name] += 1
        labels = {name: row.sentiment or "" for name, row in given.items()}
        if len(names) >= 2 and all(n in labels for n in names[:2]):
            pairs_a.append(labels[names[0]])
            pairs_b.append(labels[names[1]])
        distinct = set(labels.values())
        final: str | None
        if it.id in adjudicated:
            final = normalize_label(adjudicated[it.id])
        elif len(distinct) == 1:
            final = next(iter(distinct))
        else:
            final = None
        if len(distinct) > 1:
            disagreements.append(
                {
                    "id": it.id,
                    "comentario": it.text,
                    **{f"etiqueta_{n}": labels.get(n, "") for n in names},
                    **{f"nota_{n}": given[n].note if n in given else "" for n in names},
                    "decision": adjudicated.get(it.id, ""),
                }
            )
        merged.append(
            SentimentItem(
                id=it.id,
                text=it.text,
                split=it.split,
                source=it.source,
                country=it.country,
                sentiment=final,
                sarcasm=it.sarcasm or any(row.sarcasm for row in given.values()),
                labelers=labels,
            )
        )
    kappa = cohen_kappa(pairs_a, pairs_b) if pairs_a else None
    agreement = (
        sum(1 for a, b in zip(pairs_a, pairs_b, strict=True) if a == b) / len(pairs_a)
        if pairs_a
        else None
    )
    return MergeResult(
        items=merged,
        kappa=kappa,
        double_labeled=len(pairs_a),
        agreement=agreement,
        disagreements=disagreements,
        missing=missing,
    )


__all__ = [
    "MIN_DOUBLE_LABELED",
    "MIN_KAPPA",
    "SENTIMENTS",
    "SHEET_COLUMNS",
    "ClassScore",
    "KitPlan",
    "MergeResult",
    "SentimentItem",
    "SentimentScores",
    "SheetRow",
    "anonymize",
    "assign_split",
    "cache_report",
    "calibration",
    "decision",
    "is_emoji_only",
    "item_id",
    "latency_report",
    "merge_labels",
    "normalize_label",
    "parse_sentiment_golden",
    "percentile",
    "plan_kit",
    "read_sheet",
    "score",
    "sliced_scores",
    "slices",
    "support_by_split",
    "write_sheet",
]

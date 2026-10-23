"""Measuring comment triage and public reply drafts before replying to every comment
(ATENDER-4a, m-24848532). Pure and offline: the live run is
`packages/api/evals/replies_ai/run_experiment.py`; the procedure and the results are in
`docs/respuestas-comentarios-medicion.md`.

Three gates, all from the ticket:

1. **The golden set itself** — two people label independently; Cohen's κ ≥ 0.70 on each
   field (sentiment, kind, needs_reply) over at least `MIN_DOUBLE_LABELED` comments, or the
   labels are not trusted and nothing below counts.
2. **The classifier** (`replies.triage`) on the held-out `test` split — every sentiment
   and kind class: precision ≥ 0.80 and recall ≥ 0.70, with at least `MIN_SUPPORT`
   examples; `neg` recall ≥ 0.90; `needs_reply` recall ≥ 0.95. A class below its bar is
   reported «no fiable», not averaged away.
3. **The drafts** — 0 invented data, 0 in third person and 0 that promise or admit
   something in public; usable ≥ 90 % for positive and neutral comments and ≥ 80 % for
   negative ones; a price is stated only if it is in the catalog (`assisted.grounding`),
   otherwise the draft declines (invites a private message); no opening (first
   `OPENING_WORDS` words) repeated in more than `MAX_OPENING_SHARE` of the drafts.
   «Usable», «invented» and «promete o admite» are a PERSON's verdict on the review
   sheet; the automatic flags here only point the reviewer at suspicious drafts.

Golden JSONL, one comment per line (`#` and blank lines ignored):

    {"text": "...", "sentiment": "neg", "kind": "complaint", "needs_reply": true,
     "split": "test", "source": "synthetic:co", "labeler": "A",
     "second": {"sentiment": "neg", "kind": "complaint", "needs_reply": true,
                "labeler": "B"}}

`second` is the other person's independent label (optional per line). `source` says where
the comment came from without identifying who wrote it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from qualify_api.assisted.grounding import PRICE_SPAN, Grounding, has_price_token
from qualify_api.replies.triage import CommentKind, Sentiment, Triage

MIN_KAPPA: Final = 0.70
MIN_DOUBLE_LABELED: Final = 50
MIN_PRECISION: Final = 0.80
MIN_RECALL: Final = 0.70
MIN_SUPPORT: Final = 8
#: Per-class recall bars stricter than `MIN_RECALL` (the ticket's).
RECALL_BARS: Final[Mapping[str, float]] = {"sentiment:neg": 0.90, "needs_reply": 0.95}
#: Usable-draft bars by the comment's GOLDEN sentiment.
USABLE_BARS: Final[Mapping[Sentiment, float]] = {
    Sentiment.POS: 0.90,
    Sentiment.NEU: 0.90,
    Sentiment.NEG: 0.80,
}

#: Repeated openings: the same first `OPENING_WORDS` words under every comment read as a
#: robot to whoever looks at the publication (UX review of ATENDER-4a). Checked only from
#: `MIN_OPENING_DRAFTS` drafts on — below that any opening is a large share.
OPENING_WORDS: Final = 3
MAX_OPENING_SHARE: Final = 0.20
MIN_OPENING_DRAFTS: Final = 10

FIELDS: Final = ("sentiment", "kind", "needs_reply")


# --- golden set ----------------------------------------------------------------------


@dataclass(frozen=True)
class Label:
    sentiment: Sentiment
    kind: CommentKind
    needs_reply: bool
    labeler: str = ""

    def value(self, name: str) -> str:
        raw = getattr(self, name)
        return str(raw).lower() if isinstance(raw, bool) else str(raw)


@dataclass(frozen=True)
class GoldenComment:
    text: str
    label: Label
    split: str = ""
    source: str = ""
    note: str = ""
    second: Label | None = None
    #: Catalog question hint for the draft check (`asks_price`); optional.
    asks_price: bool = False
    #: Key of the business whose catalog grounds the draft (eval `catalogs.json`).
    business: str = ""

    @property
    def synthetic(self) -> bool:
        return self.source.startswith("synthetic")


def _label(raw: Mapping[str, Any]) -> Label:
    needs = raw["needs_reply"]
    if not isinstance(needs, bool):
        raise ValueError("needs_reply must be true or false")
    label = Label(
        sentiment=Sentiment(raw["sentiment"]),
        kind=CommentKind(raw["kind"]),
        needs_reply=needs,
        labeler=str(raw.get("labeler", "")),
    )
    if label.kind in (CommentKind.QUESTION, CommentKind.COMPLAINT) and not label.needs_reply:
        raise ValueError(f"a {label.kind} always needs a reply (labeling rule E3)")
    return label


def parse_golden(lines: Iterable[str]) -> list[GoldenComment]:
    items: list[GoldenComment] = []
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            raw = json.loads(stripped)
            text = str(raw["text"]).strip()
            label = _label(raw)
            second = _label(raw["second"]) if raw.get("second") else None
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"golden line {number}: {exc}") from exc
        if not text:
            raise ValueError(f"golden line {number}: empty text")
        split = str(raw.get("split", ""))
        if split not in ("dev", "test"):
            raise ValueError(f"golden line {number}: split must be dev or test")
        items.append(
            GoldenComment(
                text=text,
                label=label,
                split=split,
                source=str(raw.get("source", "")),
                note=str(raw.get("note", "")),
                second=second,
                asks_price=bool(raw.get("asks_price", False)),
                business=str(raw.get("business", "")),
            )
        )
    return items


# --- 1. inter-annotator agreement -----------------------------------------------------


def cohen_kappa(first: Sequence[str], second: Sequence[str]) -> float | None:
    """Cohen's κ of two labelings of the same items; None when undefined (no items, or
    both labelers used one single identical category — chance agreement is 1)."""
    if len(first) != len(second):
        raise ValueError("both labelings must cover the same items")
    n = len(first)
    if n == 0:
        return None
    observed = sum(1 for a, b in zip(first, second, strict=True) if a == b) / n
    categories = set(first) | set(second)
    expected = sum((first.count(c) / n) * (second.count(c) / n) for c in categories)
    if expected >= 1.0:
        return None
    return (observed - expected) / (1.0 - expected)


@dataclass(frozen=True)
class AgreementReport:
    double_labeled: int
    kappa: Mapping[str, float | None]

    @property
    def status(self) -> str:
        """`passed`, `failed` or `pending` (too few double-labeled comments to judge)."""
        if self.double_labeled < MIN_DOUBLE_LABELED:
            return "pending"
        ok = all(k is not None and k >= MIN_KAPPA for k in self.kappa.values())
        return "passed" if ok else "failed"

    def to_json(self) -> dict[str, Any]:
        return {
            "double_labeled": self.double_labeled,
            "min_double_labeled": MIN_DOUBLE_LABELED,
            "min_kappa": MIN_KAPPA,
            "kappa": dict(self.kappa),
            "status": self.status,
        }


def agreement(golden: Sequence[GoldenComment]) -> AgreementReport:
    pairs = [(g.label, g.second) for g in golden if g.second is not None]
    kappa = {
        name: cohen_kappa([a.value(name) for a, _ in pairs], [b.value(name) for _, b in pairs])
        for name in FIELDS
    }
    return AgreementReport(double_labeled=len(pairs), kappa=kappa)


# --- 2. classifier --------------------------------------------------------------------


@dataclass(frozen=True)
class ClassMetrics:
    support: int
    true_positives: int
    false_positives: int
    min_recall: float = MIN_RECALL

    @property
    def precision(self) -> float | None:
        predicted = self.true_positives + self.false_positives
        return self.true_positives / predicted if predicted else None

    @property
    def recall(self) -> float | None:
        return self.true_positives / self.support if self.support else None

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
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "precision": self.precision,
            "recall": self.recall,
            "min_recall": self.min_recall,
            "reliable": self.reliable,
        }


def _metrics(pairs: Sequence[tuple[bool, bool]], *, min_recall: float) -> ClassMetrics:
    return ClassMetrics(
        support=sum(1 for gold, _ in pairs if gold),
        true_positives=sum(1 for gold, pred in pairs if gold and pred),
        false_positives=sum(1 for gold, pred in pairs if pred and not gold),
        min_recall=min_recall,
    )


@dataclass(frozen=True)
class ClassifierReport:
    model_id: str
    prompt_version: str
    comments: int
    unanswered: int
    per_class: Mapping[str, ClassMetrics]
    cost_usd: float = 0.0

    @property
    def unreliable(self) -> list[str]:
        return [name for name, m in self.per_class.items() if not m.reliable]

    @property
    def status(self) -> str:
        return "passed" if not self.unreliable and not self.unanswered else "failed"

    def to_json(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "prompt_version": self.prompt_version,
            "comments": self.comments,
            "unanswered": self.unanswered,
            "cost_usd": round(self.cost_usd, 6),
            "cost_usd_per_comment": round(self.cost_usd / self.comments, 8)
            if self.comments
            else None,
            "thresholds": {
                "min_precision": MIN_PRECISION,
                "min_recall": MIN_RECALL,
                "min_support": MIN_SUPPORT,
                "recall_bars": dict(RECALL_BARS),
            },
            "per_class": {name: m.to_json() for name, m in self.per_class.items()},
            "unreliable": self.unreliable,
            "status": self.status,
        }


def evaluate_classifier(
    golden: Sequence[GoldenComment],
    predictions: Sequence[Triage | None],
    *,
    model_id: str,
    prompt_version: str,
    cost_usd: float = 0.0,
) -> ClassifierReport:
    """Per-class one-vs-rest metrics. An unanswered comment (None) counts as a miss for
    its golden classes and as `needs_reply=False` — the error that bar exists for."""
    if len(golden) != len(predictions):
        raise ValueError(f"{len(predictions)} predictions for {len(golden)} golden comments")
    rows = list(zip(golden, predictions, strict=True))
    per_class: dict[str, ClassMetrics] = {}
    for s in Sentiment:
        name = f"sentiment:{s.value}"
        per_class[name] = _metrics(
            [(g.label.sentiment is s, p is not None and p.sentiment is s) for g, p in rows],
            min_recall=RECALL_BARS.get(name, MIN_RECALL),
        )
    for k in CommentKind:
        name = f"kind:{k.value}"
        per_class[name] = _metrics(
            [(g.label.kind is k, p is not None and p.kind is k) for g, p in rows],
            min_recall=RECALL_BARS.get(name, MIN_RECALL),
        )
    per_class["needs_reply"] = _metrics(
        [(g.label.needs_reply, p is not None and p.needs_reply) for g, p in rows],
        min_recall=RECALL_BARS["needs_reply"],
    )
    return ClassifierReport(
        model_id=model_id,
        prompt_version=prompt_version,
        comments=len(rows),
        unanswered=sum(1 for _, p in rows if p is None),
        per_class=per_class,
        cost_usd=cost_usd,
    )


def evaluate_needs_reply_baseline(
    golden: Sequence[GoldenComment], flags: Sequence[bool], *, model_id: str, version: str
) -> ClassifierReport:
    """The system as it runs today, scored on the one field it can answer: production
    drafts only for commercial intent (robertuito does not run in the production image),
    so `needs_reply` = «has commercial intent»."""
    if len(golden) != len(flags):
        raise ValueError(f"{len(flags)} flags for {len(golden)} golden comments")
    metrics = _metrics(
        [(g.label.needs_reply, flag) for g, flag in zip(golden, flags, strict=True)],
        min_recall=RECALL_BARS["needs_reply"],
    )
    return ClassifierReport(
        model_id=model_id,
        prompt_version=version,
        comments=len(golden),
        unanswered=0,
        per_class={"needs_reply": metrics},
    )


# --- 3. drafts: automatic flags -------------------------------------------------------

_THIRD_PERSON: Final = (
    r"\bel negocio\b",
    r"\bla tienda\b",
    r"\bla empresa\b",
    r"\bel local\b",
    r"\bel restaurante\b",
    r"\b(?:te|le|les) (?:contactar|escribir|responder|atender)[aá]n?\b",
    r"\bagradece(?:n)?\b",
)
_PHONE: Final = re.compile(r"(?:\+\d{1,3}\s?)?(?:\d[\s-]?){7,}")
_URL: Final = re.compile(r"https?://|www\.|\.com\b|\.co\b|wa\.me", re.IGNORECASE)
_HOUR: Final = re.compile(r"\b\d{1,2}(?::\d{2})?\s?(?:a\.?\s?m\.?|p\.?\s?m\.?|hrs?|horas)\b", re.I)
_PERCENT: Final = re.compile(r"\d+\s?%|\b(?:descuento|promo(?:ción)?|2x1|gratis)\b", re.I)
_DECLINE: Final = re.compile(
    r"\b(?:DM|mensaje privado|privado|interno|inbox|te escribimos|escr[ií]benos)\b", re.I
)


def third_person_flags(text: str, business_name: str | None = None) -> list[str]:
    """Patterns where the business speaks of itself in third person. A flag sends the
    draft to a closer look; the reviewer's verdict is what counts."""
    flags = [p for p in _THIRD_PERSON if re.search(p, text, re.IGNORECASE)]
    name = (business_name or "").strip()
    if name and re.search(rf"\b{re.escape(name)}\b\s+\w+(?:a|e)n?\b", text, re.IGNORECASE):
        flags.append("business_name_as_subject")
    return flags


def _amount(token: str) -> Decimal | None:
    digits = re.sub(r"[^\d,.]", "", token)
    if not digits:
        return None
    # «12.000» / «12,000» are thousands; «12,50» / «12.50» decimals.
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", digits):
        digits = re.sub(r"[.,]", "", digits)
    else:
        digits = digits.replace(",", ".")
    try:
        return Decimal(digits)
    except InvalidOperation:
        return None


def catalog_prices(grounding: Grounding) -> set[Decimal]:
    prices: set[Decimal] = set()
    for product in grounding.products:
        if product.price_amount is not None:
            prices.add(Decimal(product.price_amount))
        for match in PRICE_SPAN.finditer(product.price_label or ""):
            amount = _amount(match.group(0))
            if amount is not None:
                prices.add(amount)
    return prices


def price_check(text: str, *, grounding: Grounding, asks_price: bool) -> str:
    """`catalog` (every stated price is a catalog price), `declined` (no price stated and
    the draft points to a private message), `n/a` (no price asked or stated) or `fail`
    (a price not in the catalog, or a price question neither answered nor declined)."""
    stated = [_amount(m.group(0)) for m in PRICE_SPAN.finditer(text)]
    if stated or has_price_token(text):
        known = catalog_prices(grounding)
        if stated and all(a is not None and a in known for a in stated):
            return "catalog"
        return "fail"
    if not asks_price:
        return "n/a"
    return "declined" if _DECLINE.search(text) else "fail"


def invented_data_flags(text: str, *, grounding: Grounding, asks_price: bool) -> list[str]:
    """Data-looking spans no validated fact backs: a price outside the catalog, a phone
    number, a link, an hour, a discount or promotion. The catalog never carries these
    (D2), so any of them is a candidate invention for the reviewer."""
    flags: list[str] = []
    if price_check(text, grounding=grounding, asks_price=False) == "fail":
        flags.append("price_not_in_catalog")
    if _PHONE.search(text):
        flags.append("phone")
    if _URL.search(text):
        flags.append("link")
    if _HOUR.search(text):
        flags.append("hour")
    if _PERCENT.search(text):
        flags.append("promotion")
    return flags


@dataclass(frozen=True)
class DraftResult:
    """One draft of the experiment, with its automatic flags and (once a person filled
    the review sheet) the human verdicts: `usable`, `invented`, `third_person` and
    `promises_or_admits` (does it admit a fault or promise a refund, a solution, that the
    business will write…?)."""

    text: str
    comment: GoldenComment
    model_id: str
    prompt_version: str
    cost_usd: float
    price: str
    invented_flags: tuple[str, ...] = ()
    third_person_flags: tuple[str, ...] = ()
    usable: bool | None = None
    invented: bool | None = None
    third_person: bool | None = None
    promises_or_admits: bool | None = None
    error: str = ""


def check_draft(
    *,
    text: str,
    comment: GoldenComment,
    grounding: Grounding,
    model_id: str,
    prompt_version: str,
    cost_usd: float,
) -> DraftResult:
    return DraftResult(
        text=text,
        comment=comment,
        model_id=model_id,
        prompt_version=prompt_version,
        cost_usd=cost_usd,
        price=price_check(text, grounding=grounding, asks_price=comment.asks_price),
        invented_flags=tuple(
            invented_data_flags(text, grounding=grounding, asks_price=comment.asks_price)
        ),
        third_person_flags=tuple(third_person_flags(text, grounding.business_name)),
    )


@dataclass(frozen=True)
class DraftReport:
    drafts: int
    errors: int
    price_failures: int
    auto_invented: int
    auto_third_person: int
    reviewed: int
    invented: int
    third_person: int
    promises_or_admits: int = 0
    usable_rate: Mapping[str, float | None] = field(default_factory=dict)
    cost_usd: float = 0.0
    top_opening: str = ""
    top_opening_share: float = 0.0

    @property
    def repeated_opening(self) -> bool:
        return (
            self.drafts - self.errors >= MIN_OPENING_DRAFTS
            and self.top_opening_share > MAX_OPENING_SHARE
        )

    @property
    def status(self) -> str:
        """`failed` on any hard failure (error, price, a repeated opening, a
        person-confirmed invention, third person or promise/admission, a usable rate under
        its bar); `pending` while not every draft has a person's verdict; `passed`
        otherwise."""
        if self.errors or self.price_failures or self.invented or self.third_person:
            return "failed"
        if self.promises_or_admits or self.repeated_opening:
            return "failed"
        if any(
            rate is not None and rate < USABLE_BARS[Sentiment(s)]
            for s, rate in self.usable_rate.items()
        ):
            return "failed"
        if self.reviewed < self.drafts:
            return "pending"
        return "passed"

    def to_json(self) -> dict[str, Any]:
        return {
            "drafts": self.drafts,
            "errors": self.errors,
            "price_failures": self.price_failures,
            "auto_flags": {
                "invented": self.auto_invented,
                "third_person": self.auto_third_person,
            },
            "reviewed": self.reviewed,
            "invented": self.invented,
            "third_person": self.third_person,
            "promises_or_admits": self.promises_or_admits,
            "opening": {
                "top": self.top_opening,
                "share": round(self.top_opening_share, 4),
                "max_share": MAX_OPENING_SHARE,
                "repeated": self.repeated_opening,
            },
            "usable_rate": dict(self.usable_rate),
            "usable_bars": {s.value: bar for s, bar in USABLE_BARS.items()},
            "cost_usd": round(self.cost_usd, 6),
            "cost_usd_per_draft": round(self.cost_usd / self.drafts, 8) if self.drafts else None,
            "status": self.status,
        }


def opening(text: str, words: int = OPENING_WORDS) -> str:
    """The first `words` words of a draft, lower-cased and without punctuation or emoji."""
    return " ".join(re.findall(r"\w+", text.lower())[:words])


def top_opening(texts: Iterable[str]) -> tuple[str, float]:
    """The most frequent opening among the non-empty drafts and its share (0 if none)."""
    counts: dict[str, int] = {}
    for t in texts:
        if key := opening(t):
            counts[key] = counts.get(key, 0) + 1
    if not counts:
        return "", 0.0
    top = max(counts, key=lambda k: counts[k])
    return top, counts[top] / sum(counts.values())


def evaluate_drafts(results: Sequence[DraftResult]) -> DraftReport:
    reviewed = [r for r in results if r.usable is not None]
    usable_rate: dict[str, float | None] = {}
    for s in Sentiment:
        group = [r for r in reviewed if r.comment.label.sentiment is s]
        usable_rate[s.value] = sum(1 for r in group if r.usable) / len(group) if group else None
    first, share = top_opening(r.text for r in results if not r.error)
    return DraftReport(
        drafts=len(results),
        errors=sum(1 for r in results if r.error),
        price_failures=sum(1 for r in results if r.price == "fail"),
        auto_invented=sum(1 for r in results if r.invented_flags),
        auto_third_person=sum(1 for r in results if r.third_person_flags),
        reviewed=len(reviewed),
        invented=sum(1 for r in reviewed if r.invented),
        third_person=sum(1 for r in reviewed if r.third_person),
        promises_or_admits=sum(1 for r in reviewed if r.promises_or_admits),
        usable_rate=usable_rate,
        cost_usd=sum(r.cost_usd for r in results),
        top_opening=first,
        top_opening_share=share,
    )


#: Columns of the human review sheet (CSV). `usable`, `invented`, `third_person` and
#: `promete_o_admite` («¿admite o promete algo?») are filled by the reviewer with
#: `si` / `no`. Usable = the owner would send it as is or changing one word, without fear
#: that it says something false, promises something or sounds like another business.
REVIEW_COLUMNS: Final = (
    "row",
    "comment",
    "golden_sentiment",
    "golden_kind",
    "draft",
    "auto_price",
    "auto_invented",
    "auto_third_person",
    "usable",
    "invented",
    "third_person",
    "promete_o_admite",
    "reviewer_note",
)


def parse_verdict(value: str) -> bool | None:
    v = value.strip().lower()
    if v in ("si", "sí", "s", "yes", "y", "1", "true"):
        return True
    if v in ("no", "n", "0", "false"):
        return False
    return None


__all__ = [
    "MAX_OPENING_SHARE",
    "MIN_DOUBLE_LABELED",
    "MIN_KAPPA",
    "MIN_OPENING_DRAFTS",
    "OPENING_WORDS",
    "REVIEW_COLUMNS",
    "USABLE_BARS",
    "AgreementReport",
    "ClassMetrics",
    "ClassifierReport",
    "DraftReport",
    "DraftResult",
    "GoldenComment",
    "Label",
    "agreement",
    "catalog_prices",
    "check_draft",
    "cohen_kappa",
    "evaluate_classifier",
    "evaluate_drafts",
    "evaluate_needs_reply_baseline",
    "invented_data_flags",
    "opening",
    "parse_golden",
    "parse_verdict",
    "price_check",
    "third_person_flags",
    "top_opening",
]

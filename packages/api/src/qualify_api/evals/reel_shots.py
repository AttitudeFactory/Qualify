"""VE-05 (m-24921050): score the reel analysis (VE-02 shots + VE-04c people/faces) against a
human annotation. Offline: reads the annotation sheet (CSV) and the exported model results
(JSON), calls nothing.

Metrics (design `docs/diseno-video-por-planos.md` §4.1, ADR 44 «se reabre si»):

- **Cuts:** a cut is the start of every shot but the first. A predicted cut matches a real one
  within `tolerance` seconds (default 0.25), one-to-one; F1 is micro-averaged over the set
  (summed TP/FP/FN), and also reported per reel. Below `F1_BAR` the detector is reopened.
- **People / faces:** judged per REAL shot (the annotator's), at the real shot's midpoint:
  the model's value is the one of its shot covering that instant. `observed` = yes,
  `not_observed` = no, `unknown` = no answer — counted wrong in `accuracy` and excluded in
  `accuracy_answered`, so «no sé» never passes for a hit and is never hidden either.
- Only the part of the reel the analysis covered (`covered_to_s`) is scored; real cuts after
  it are out of scope, not misses.
"""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: ADR 44: the shot detector is reopened below this cut F1 at ±0.25 s.
F1_BAR = 0.85
TOLERANCE_S = 0.25

#: Sheet columns (Spanish: the annotator reads them). Kept here so the sheet writer and the
#: scorer cannot drift apart.
COL_ID = "post_id"
COL_NETWORK = "red"
COL_CATEGORY = "categoria"
COL_LINK = "enlace"
COL_SECONDS = "duracion_s"
COL_CUTS = "cortes reales (segundos, separados por ;)"
COL_PEOPLE = "¿aparece persona? por plano real (si/no, separados por ;)"
COL_FACES = "¿se ve el rostro? por plano real (si/no, separados por ;)"
COL_NOTES = "notas"
SHEET_COLUMNS = (
    "n",
    COL_ID,
    COL_NETWORK,
    COL_CATEGORY,
    COL_LINK,
    COL_SECONDS,
    COL_CUTS,
    COL_PEOPLE,
    COL_FACES,
    COL_NOTES,
)
#: What the annotator writes when a reel has no cut at all (one single shot).
NO_CUTS = ("ninguno", "0 cortes", "-")

_YES = frozenset({"si", "sí", "s", "yes", "y", "1"})
_NO = frozenset({"no", "n", "0"})
OBSERVED, NOT_OBSERVED, UNKNOWN = "observed", "not_observed", "unknown"


class SheetError(ValueError):
    """An annotation row that cannot be read as written (the message names the reel)."""


@dataclass(frozen=True)
class Truth:
    """One annotated reel: its real cut times and, per real shot, people and face."""

    post_id: str
    cuts: tuple[float, ...]
    people: tuple[bool, ...]
    faces: tuple[bool, ...]


@dataclass(frozen=True)
class ModelShot:
    start_s: float
    end_s: float
    people_presence: str
    visible_faces: str


@dataclass(frozen=True)
class ModelReel:
    post_id: str
    shots: tuple[ModelShot, ...]
    covered_to_s: float | None = None
    #: False for a reel whose Haiku sheet failed: its shots come from VE-02 alone (run
    #: offline on the stored source), so only its cuts are scored, never its labels.
    labelled: bool = True
    #: `analysis.detector_version` of the run (None when the row never reached the detector
    #: step's provenance, e.g. a sheet still `queued`). Guards `fill_missing_cuts`.
    detector_version: str | None = None


@dataclass
class CutCounts:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    def add(self, other: CutCounts) -> None:
        self.tp += other.tp
        self.fp += other.fp
        self.fn += other.fn

    @property
    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else None

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else None

    @property
    def f1(self) -> float | None:
        """None when there is nothing to score (no real and no predicted cut): a one-shot
        reel the model also read as one shot is right, but says nothing about F1."""
        denominator = 2 * self.tp + self.fp + self.fn
        return 2 * self.tp / denominator if denominator else None


@dataclass
class LabelCounts:
    """Agreement of one yes/no label over real shots."""

    hits: int = 0
    misses: int = 0
    unknown: int = 0
    confusion: dict[str, int] = field(default_factory=dict)

    def add(self, truth: bool, model: str) -> None:
        key = f"{'si' if truth else 'no'}->{model}"
        self.confusion[key] = self.confusion.get(key, 0) + 1
        if model == UNKNOWN:
            self.unknown += 1
        elif (model == OBSERVED) == truth:
            self.hits += 1
        else:
            self.misses += 1

    def merge(self, other: LabelCounts) -> None:
        self.hits += other.hits
        self.misses += other.misses
        self.unknown += other.unknown
        for key, value in other.confusion.items():
            self.confusion[key] = self.confusion.get(key, 0) + value

    @property
    def total(self) -> int:
        return self.hits + self.misses + self.unknown

    @property
    def accuracy(self) -> float | None:
        return self.hits / self.total if self.total else None

    @property
    def accuracy_answered(self) -> float | None:
        answered = self.hits + self.misses
        return self.hits / answered if answered else None


# --------------------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------------------


def _number(raw: str) -> float:
    """`12.5`, `12,5` (Spanish decimal comma) or `0:12.5` / `0:12,5` (minutes:seconds)."""
    text = raw.strip().replace(",", ".")
    if ":" in text:
        minutes, _, seconds = text.partition(":")
        return int(minutes) * 60 + float(seconds)
    return float(text)


def parse_cuts(raw: str) -> tuple[float, ...] | None:
    """The real cut times of a sheet cell, sorted. None = not annotated yet (empty cell);
    `()` = annotated as a single shot (`ninguno`)."""
    text = (raw or "").strip()
    if not text:
        return None
    if text.lower() in NO_CUTS:
        return ()
    parts = [p for p in re.split(r"[;\n]+", text) if p.strip()]
    return tuple(sorted(_number(p) for p in parts))


def parse_flags(raw: str) -> tuple[bool, ...] | None:
    """`si; no; si` → (True, False, True). None = empty cell."""
    text = (raw or "").strip()
    if not text:
        return None
    out: list[bool] = []
    for part in (p.strip().lower() for p in re.split(r"[;,\n]+", text) if p.strip()):
        if part in _YES:
            out.append(True)
        elif part in _NO:
            out.append(False)
        else:
            raise ValueError(f"«{part}» no es si/no")
    return tuple(out)


def read_sheet(path: Path) -> list[Truth]:
    """The annotated reels of the sheet. A row with an empty cuts cell is not annotated
    yet and is skipped; a row whose per-shot lists do not have one value per real shot
    (cuts + 1) raises `SheetError` — a misaligned row would score the wrong shots."""
    truths: list[Truth] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            post_id = (row.get(COL_ID) or "").strip()
            try:
                cuts = parse_cuts(row.get(COL_CUTS) or "")
                if cuts is None:
                    continue
                people = parse_flags(row.get(COL_PEOPLE) or "")
                faces = parse_flags(row.get(COL_FACES) or "")
            except ValueError as error:
                raise SheetError(f"{post_id}: {error}") from error
            shots = len(cuts) + 1
            for name, values in (("personas", people), ("rostros", faces)):
                if values is None or len(values) != shots:
                    got = 0 if values is None else len(values)
                    raise SheetError(
                        f"{post_id}: {len(cuts)} cortes = {shots} planos, pero {name} "
                        f"tiene {got} valores"
                    )
            assert people is not None and faces is not None
            truths.append(Truth(post_id, cuts, people, faces))
    return truths


def read_results(path: Path) -> dict[str, ModelReel]:
    """The exported analyses (`packages/api/evals/reel_shots_ai/results/*.json`) by post id.
    An `ok` analysis brings shots and labels; one whose sheet failed brings only the
    detector's shots (`detector_only_shots`, unlabelled); with neither it is left out
    (listed as missing, not scored)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    reels: dict[str, ModelReel] = {}
    for item in data["reels"]:
        analysis = item.get("analysis") or {}
        covered = analysis.get("covered_to_s")
        labelled = analysis.get("status") == "ok"
        raw = item.get("shots") if labelled else item.get("detector_only_shots")
        if not raw:
            continue
        reels[item["post_id"]] = ModelReel(
            post_id=item["post_id"],
            shots=tuple(
                ModelShot(
                    float(s["start_s"]),
                    float(s["end_s"]),
                    str(s.get("people_presence", UNKNOWN)),
                    str(s.get("visible_faces", UNKNOWN)),
                )
                for s in raw
            ),
            covered_to_s=float(covered) if covered is not None else None,
            labelled=labelled,
            detector_version=analysis.get("detector_version"),
        )
    return reels


def fill_missing_cuts(
    primary: Mapping[str, ModelReel], fallback: Mapping[str, ModelReel]
) -> tuple[dict[str, ModelReel], list[str]]:
    """`primary` plus, for each reel it lacks, the fallback run's shots — UNLABELLED, so
    only that reel's cuts are scored (its labels belong to another prompt/version). Used
    when a reel of the scored run failed before the detector (e.g. an expired source URL)
    and an earlier run of the SAME detector has it. Refuses a fallback reel whose
    `detector_version` differs from the primary run's: those cuts would measure another
    detector. Returns the merged reels and the post ids taken from the fallback."""
    versions = {r.detector_version for r in primary.values() if r.detector_version}
    if fallback and not versions:
        raise ValueError(
            "el resultado puntuado no dice qué detector usó (detector_version): no se puede "
            "comprobar que el respaldo mida lo mismo"
        )
    merged = dict(primary)
    taken: list[str] = []
    for post_id, reel in fallback.items():
        if post_id in merged:
            continue
        if reel.detector_version not in versions:
            raise ValueError(
                f"{post_id}: detector {reel.detector_version!r} del respaldo no es "
                f"{sorted(versions)} del resultado puntuado"
            )
        merged[post_id] = ModelReel(
            post_id,
            reel.shots,
            reel.covered_to_s,
            labelled=False,
            detector_version=reel.detector_version,
        )
        taken.append(post_id)
    return merged, taken


# --------------------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------------------


def model_cuts(reel: ModelReel) -> tuple[float, ...]:
    """Every shot start but the first one's."""
    starts = sorted(s.start_s for s in reel.shots)
    return tuple(starts[1:])


def match_cuts(
    predicted: Sequence[float], real: Sequence[float], tolerance: float = TOLERANCE_S
) -> CutCounts:
    """One-to-one matching within `tolerance`, closest pairs first (on a line this is the
    maximum matching for any realistic cut spacing; ties go to the earlier cut)."""
    pairs = sorted(
        (abs(p - r), i, j)
        for i, p in enumerate(predicted)
        for j, r in enumerate(real)
        if abs(p - r) <= tolerance + 1e-9
    )
    used_p: set[int] = set()
    used_r: set[int] = set()
    for _distance, i, j in pairs:
        if i in used_p or j in used_r:
            continue
        used_p.add(i)
        used_r.add(j)
    tp = len(used_p)
    return CutCounts(tp=tp, fp=len(predicted) - tp, fn=len(real) - tp)


def _shot_at(reel: ModelReel, t: float) -> ModelShot | None:
    for shot in reel.shots:
        if shot.start_s <= t < shot.end_s:
            return shot
    return None


def score_reel(truth: Truth, reel: ModelReel, tolerance: float = TOLERANCE_S) -> dict[str, Any]:
    """One reel's cut counts and people/face agreement, within the covered interval.

    Cuts at or past `covered_to_s` are dropped on both sides. Known edge: a cut just
    inside the cover whose partner (within `tolerance`) lies just past it counts as an FP
    (predicted inside) or an FN (real inside), because the partner is out of scope. No reel
    of the VE-05 data hits it."""
    limit = reel.covered_to_s if reel.covered_to_s is not None else float("inf")
    # The same cutoff on both sides: the analysis saw every instant before `limit`, so a
    # real cut there is in scope (missed = FN) and a predicted one too (unmatched = FP).
    # A tighter cutoff on one side only (`limit - tolerance`) dropped real cuts the model
    # matched just before the end and turned the model's correct cut into an FP.
    real = [c for c in truth.cuts if c < limit]
    predicted = [c for c in model_cuts(reel) if c < limit]
    cuts = match_cuts(predicted, real, tolerance)
    end = max([*(s.end_s for s in reel.shots), *truth.cuts, 0.0])
    bounds = [0.0, *truth.cuts, end]
    people, faces = LabelCounts(), LabelCounts()
    for n in range(len(truth.cuts) + 1 if reel.labelled else 0):
        start, stop = bounds[n], bounds[n + 1]
        if start >= limit:
            break
        middle = (start + min(stop, limit)) / 2
        shot = _shot_at(reel, middle)
        people.add(truth.people[n], shot.people_presence if shot else UNKNOWN)
        faces.add(truth.faces[n], shot.visible_faces if shot else UNKNOWN)
    return {"post_id": truth.post_id, "cuts": cuts, "people": people, "faces": faces}


def score(
    truths: Iterable[Truth],
    reels: Mapping[str, ModelReel],
    tolerance: float = TOLERANCE_S,
) -> dict[str, Any]:
    """The set's micro-averaged cut F1 and label accuracies, plus each reel's line. An
    annotated reel without shots is listed in `missing`, never scored as 0; one with
    detector-only shots counts for cuts and not for labels."""
    total_cuts, people, faces = CutCounts(), LabelCounts(), LabelCounts()
    per_reel: list[dict[str, Any]] = []
    missing: list[str] = []
    for truth in truths:
        reel = reels.get(truth.post_id)
        if reel is None:
            missing.append(truth.post_id)
            continue
        line = score_reel(truth, reel, tolerance)
        total_cuts.add(line["cuts"])
        people.merge(line["people"])
        faces.merge(line["faces"])
        per_reel.append(line)
    return {
        "reels": len(per_reel),
        "missing": missing,
        "tolerance_s": tolerance,
        "cuts": total_cuts,
        "people": people,
        "faces": faces,
        "reopen_detector": total_cuts.f1 is not None and total_cuts.f1 < F1_BAR,
        "per_reel": per_reel,
    }


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.3f}"


def report_markdown(result: Mapping[str, Any]) -> str:
    """The summary as Markdown tables (Spanish), ready to paste into the VE-05 report."""
    cuts: CutCounts = result["cuts"]
    lines = [
        f"Reels puntuados: {result['reels']} · sin planos: "
        f"{', '.join(result['missing']) or 'ninguno'} · tolerancia ±{result['tolerance_s']} s",
        "",
        "| Métrica | Valor |",
        "|---|---|",
        f"| Cortes: precisión | {_pct(cuts.precision)} |",
        f"| Cortes: exhaustividad | {_pct(cuts.recall)} |",
        f"| **Cortes: F1** (umbral {F1_BAR}) | **{_pct(cuts.f1)}** |",
        f"| Cortes: VP / FP / FN | {cuts.tp} / {cuts.fp} / {cuts.fn} |",
    ]
    for label, name in (("people", "Personas"), ("faces", "Rostros")):
        counts: LabelCounts = result[label]
        lines += [
            f"| {name}: acierto (unknown = fallo) | {_pct(counts.accuracy)} |",
            f"| {name}: acierto sobre lo respondido | {_pct(counts.accuracy_answered)} |",
            f"| {name}: planos reales / unknown | {counts.total} / {counts.unknown} |",
        ]
    verdict = "SÍ: F1 < 0,85" if result["reopen_detector"] else "no"
    lines += [f"| ¿Se reabre el detector? | {verdict} |", ""]
    lines += [
        "| Reel | VP | FP | FN | F1 cortes | Personas ok/total | Rostros ok/total |",
        "|---|---|---|---|---|---|---|",
    ]
    for line in result["per_reel"]:
        c, p, f = line["cuts"], line["people"], line["faces"]
        lines.append(
            f"| {line['post_id']} | {c.tp} | {c.fp} | {c.fn} | {_pct(c.f1)} | "
            f"{p.hits}/{p.total} | {f.hits}/{f.total} |"
        )
    return "\n".join(lines)

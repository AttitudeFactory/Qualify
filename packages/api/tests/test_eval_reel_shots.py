"""VE-05's scorer (cuts F1 at ±0.25 s, people/faces per real shot), offline."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from qualify_api.evals.reel_shots import (
    COL_CUTS,
    COL_FACES,
    COL_ID,
    COL_PEOPLE,
    SHEET_COLUMNS,
    ModelReel,
    ModelShot,
    SheetError,
    Truth,
    fill_missing_cuts,
    match_cuts,
    parse_cuts,
    parse_flags,
    read_results,
    read_sheet,
    report_markdown,
    score,
)

SHEET = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "modelos-generativos"
    / "ve05-anotacion-cortes-rostros.csv"
)
RESULTS = Path(__file__).resolve().parents[1] / "evals" / "reel_shots_ai" / "results"


def _reel(post_id: str, *shots: tuple[float, float, str, str], covered: float | None = None):
    return ModelReel(post_id, tuple(ModelShot(*s) for s in shots), covered)


def test_cells_read_spanish_decimals_minutes_and_single_shot() -> None:
    assert parse_cuts("") is None
    assert parse_cuts("ninguno") == ()
    assert parse_cuts("3,5; 1.25 ;0:12,5") == (1.25, 3.5, 12.5)
    assert parse_flags("sí; no;SI") == (True, False, True)
    with pytest.raises(ValueError):
        parse_flags("quizá")


def test_cut_matching_is_one_to_one_within_the_tolerance() -> None:
    # 1.0 matches 1.2 (0.2 s); 1.1 cannot reuse it; 5.0 vs 5.3 is outside ±0.25.
    counts = match_cuts([1.0, 1.1, 5.0], [1.2, 5.3])
    assert (counts.tp, counts.fp, counts.fn) == (1, 2, 1)
    assert counts.f1 == pytest.approx(2 / (2 + 2 + 1))
    exact = match_cuts([2.0], [2.25])
    assert (exact.tp, exact.fp, exact.fn) == (1, 0, 0)


def test_score_cuts_and_labels_per_real_shot() -> None:
    truth = Truth("a", (2.0, 5.0), (True, False, True), (True, False, False))
    model = _reel(
        "a",
        (0.0, 2.1, "observed", "observed"),  # cut at 2.1 matches 2.0
        (2.1, 7.0, "not_observed", "unknown"),  # misses the 5.0 cut
        (7.0, 9.0, "observed", "observed"),  # extra cut at 7.0
    )
    result = score([truth], {"a": model})
    cuts = result["cuts"]
    assert (cuts.tp, cuts.fp, cuts.fn) == (1, 1, 1)
    assert result["reopen_detector"] is True  # F1 0.5 < 0.85
    # real shots' midpoints 1.0, 3.5, 7.0 → model shots 0, 1, 2
    people, faces = result["people"], result["faces"]
    assert (people.hits, people.misses, people.unknown) == (3, 0, 0)
    assert (faces.hits, faces.misses, faces.unknown) == (1, 1, 1)
    assert faces.accuracy == pytest.approx(1 / 3)
    assert faces.accuracy_answered == pytest.approx(1 / 2)
    assert "| a | 1 | 1 | 1 |" in report_markdown(result)


def test_only_the_covered_interval_is_scored_and_missing_reels_are_listed() -> None:
    truth = Truth("b", (10.0, 70.0), (False, True, True), (False, True, True))
    model = _reel(
        "b",
        (0.0, 10.1, "not_observed", "not_observed"),
        (10.1, 60.0, "observed", "observed"),
        covered=60.0,
    )
    result = score([truth, Truth("gone", (), (True,), (True,))], {"b": model})
    cuts = result["cuts"]
    assert (cuts.tp, cuts.fp, cuts.fn) == (1, 0, 0)  # the 70 s cut is past the cover
    assert result["people"].total == 2  # the third real shot starts after 60 s
    assert result["missing"] == ["gone"]
    assert result["reopen_detector"] is False


def test_a_cut_just_before_the_covered_end_counts_on_both_sides_alike() -> None:
    # Cover ends at 28.467; the real cut 28.37 and the model's 28.367 are both inside it.
    truth = Truth("e", (10.0, 28.37), (False,) * 3, (False,) * 3)
    model = _reel(
        "e",
        (0.0, 10.0, "not_observed", "not_observed"),
        (10.0, 28.367, "not_observed", "not_observed"),
        (28.367, 28.467, "not_observed", "not_observed"),
        covered=28.467,
    )
    cuts = score([truth], {"e": model})["cuts"]
    assert (cuts.tp, cuts.fp, cuts.fn) == (2, 0, 0)
    # 28.4 is still within ±0.25 s of the model's 28.367: matched, not missed.
    near = score([Truth("e", (10.0, 28.4), (False,) * 3, (False,) * 3)], {"e": model})
    assert (near["cuts"].tp, near["cuts"].fp, near["cuts"].fn) == (2, 0, 0)
    # A model cut near the end with no real cut there is an FP, not out of scope.
    extra = score([Truth("e", (10.0,), (False,) * 2, (False,) * 2)], {"e": model})
    assert (extra["cuts"].tp, extra["cuts"].fp, extra["cuts"].fn) == (1, 1, 0)
    # A real cut near the end that the model missed is an FN, not out of scope.
    alone = _reel("e", *((0.0, 28.467, "observed", "observed"),), covered=28.467)
    late = score([Truth("e", (28.4,), (True, True), (True, True))], {"e": alone})
    assert (late["cuts"].tp, late["cuts"].fp, late["cuts"].fn) == (0, 0, 1)


def test_a_failed_sheet_scores_its_cuts_from_the_detector_but_no_labels(tmp_path: Path) -> None:
    results = tmp_path / "r.json"
    results.write_text(
        json.dumps(
            {
                "reels": [
                    {
                        "post_id": "c",
                        "analysis": {"status": "failed", "covered_to_s": 9.0},
                        "shots": [],
                        "detector_only_shots": [
                            {"shot_index": 0, "start_s": 0.0, "end_s": 3.0},
                            {"shot_index": 1, "start_s": 3.0, "end_s": 9.0},
                        ],
                    },
                    {"post_id": "d", "analysis": {"status": "failed"}, "shots": []},
                ]
            }
        ),
        encoding="utf-8",
    )
    reels = read_results(results)
    assert set(reels) == {"c"} and reels["c"].labelled is False
    result = score([Truth("c", (3.1,), (True, True), (True, False))], reels)
    assert (result["cuts"].tp, result["cuts"].fp, result["cuts"].fn) == (1, 0, 0)
    assert result["people"].total == 0 and result["faces"].total == 0


def test_a_misaligned_row_is_refused(tmp_path: Path) -> None:
    sheet = tmp_path / "s.csv"
    with sheet.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SHEET_COLUMNS)
        writer.writeheader()
        writer.writerow({COL_ID: "ok", COL_CUTS: "ninguno", COL_PEOPLE: "si", COL_FACES: "no"})
        writer.writerow({COL_ID: "pending"})  # not annotated yet: skipped
        writer.writerow({COL_ID: "bad", COL_CUTS: "1;2", COL_PEOPLE: "si;no", COL_FACES: "si"})
    with pytest.raises(SheetError, match="bad: 2 cortes = 3 planos"):
        read_sheet(sheet)


def test_fallback_reels_count_for_cuts_only_and_need_the_same_detector() -> None:
    shots = ((0.0, 2.0, "observed", "observed"), (2.0, 4.0, "observed", "observed"))
    primary = {"a": ModelReel("a", (ModelShot(*shots[0]),), detector_version="det-1")}
    fallback = {
        "a": ModelReel("a", (), detector_version="det-1"),  # primary wins
        "b": ModelReel("b", tuple(ModelShot(*s) for s in shots), detector_version="det-1"),
    }
    merged, taken = fill_missing_cuts(primary, fallback)
    assert taken == ["b"] and merged["a"] is primary["a"]
    assert merged["b"].labelled is False
    result = score([Truth("b", (2.0,), (True, True), (True, True))], merged)
    assert (result["cuts"].tp, result["cuts"].fp, result["cuts"].fn) == (1, 0, 0)
    assert result["people"].total == 0 and result["faces"].total == 0
    other = {"c": ModelReel("c", (ModelShot(*shots[0]),), detector_version="det-2")}
    with pytest.raises(ValueError, match="c: detector"):
        fill_missing_cuts(primary, other)
    unversioned = {"a": ModelReel("a", (ModelShot(*shots[0]),))}
    with pytest.raises(ValueError, match="detector_version"):
        fill_missing_cuts(unversioned, fallback)


def test_the_committed_sheet_and_results_line_up() -> None:
    """The annotation sheet lists the same 20 reels every exported run has, it is fully
    annotated (207 real shots), and the default scoring (v8 replay + v7 cuts for the reel
    v8 lacks) covers all 20 with a single detector."""
    rows = list(csv.DictReader(SHEET.open(encoding="utf-8-sig", newline="")))
    assert tuple(rows[0].keys()) == SHEET_COLUMNS
    assert len(rows) == 20
    exported = sorted(RESULTS.glob("*.json"))
    assert {p.name for p in exported} >= {
        "ve05-20261105-v7.json",
        "ve05-20261105-v8.json",
        "ve05-20261105-v8-replay.json",
    }
    for path in exported:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert {r[COL_ID] for r in rows} == {r["post_id"] for r in data["reels"]}, path.name
    truths = read_sheet(SHEET)  # raises SheetError on a misaligned annotated row
    assert len(truths) == 20 and sum(len(t.cuts) + 1 for t in truths) == 207
    reels, taken = fill_missing_cuts(
        read_results(RESULTS / "ve05-20261105-v8-replay.json"),
        read_results(RESULTS / "ve05-20261105-v7.json"),
    )
    assert taken == ["7703559161040211233"]
    assert {r.detector_version for r in reels.values()} <= {"luma-diff-hist-1", None}
    assert score(truths, reels)["missing"] == []

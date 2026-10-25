"""Pins the queue simulation to docs/escalar-generacion-concurrencia.md §3 (m-24855154).

If a number here changes, §3 (and the ADR 41 / §4.1 figures quoted from it) changes with it.
"""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from qualify_creative.concurrency_sim import (
    FLEET_SIZES,
    PEAKS,
    Assumptions,
    main,
    omnihuman_first_failing_position,
    omnihuman_mean_wait_minutes,
    omnihuman_saturation_businesses,
    simulate,
)

TYPICAL = Assumptions()
FULL = replace(TYPICAL, quota_use=1.0)
SLOW = replace(TYPICAL, slowdown=2.0)
WORST = replace(TYPICAL, quota_use=1.0, slowdown=2.0)


def test_derived_assumptions_match_the_doc() -> None:
    assert TYPICAL.tasks_per_business_month == pytest.approx(19.2)  # 38.4 at full quota
    assert TYPICAL.draft_share == pytest.approx(20 / 24)
    assert TYPICAL.mean_task_seconds == pytest.approx(110.0)
    assert TYPICAL.mean_burst == pytest.approx(2.4)
    # Tasks in the peak hour, §3.2 column 3.
    assert round(TYPICAL.peak_tasks_per_hour(10, PEAKS["fin de semana"])) == 5
    assert round(TYPICAL.peak_tasks_per_hour(200, PEAKS["fin de semana"])) == 92
    assert round(TYPICAL.peak_tasks_per_hour(1000, PEAKS["fin de semana"])) == 458


def test_is_deterministic() -> None:
    assert simulate(1000, "lunes", replicas=5) == simulate(1000, "lunes", replicas=5)


def test_same_load_gives_same_answer() -> None:
    # 500 businesses ×6 and 1 000 ×3 launch the same tasks per hour (common random numbers).
    assert simulate(500, "fin de semana").wait_p95_s == simulate(1000, "día normal").wait_p95_s


@pytest.mark.parametrize("assumptions", [TYPICAL, FULL, SLOW, WORST])
@pytest.mark.parametrize("peak", list(PEAKS))
def test_fifty_businesses_never_wait_past_the_threshold(
    assumptions: Assumptions, peak: str
) -> None:
    for businesses in (10, 50):
        result = simulate(businesses, peak, assumptions)
        assert result.share_over_threshold == 0.0
        assert result.wait_p95_s <= 60.0


def test_typical_use_holds_up_to_about_500() -> None:
    for businesses in (10, 50, 200):
        assert simulate(businesses, "fin de semana").share_over_threshold == 0.0
    assert simulate(500, "día normal").share_over_threshold == 0.0
    assert simulate(500, "fin de semana").share_over_threshold < 0.01


def test_typical_use_breaks_at_1000() -> None:
    monday = simulate(1000, "lunes")
    assert 0.10 < monday.share_over_threshold < 0.30  # §3.2: 18 %
    weekend = simulate(1000, "fin de semana")
    assert weekend.mean_load == pytest.approx(14.0, abs=0.05)
    assert weekend.share_over_threshold == 1.0
    assert 30 * 60 < weekend.wait_p50_s < weekend.wait_p95_s < 65 * 60  # §3.2: 38 / 57 min


def test_worst_case_breaks_at_about_200() -> None:
    assert simulate(200, "día normal", WORST).share_over_threshold == 0.0
    assert 0.0 < simulate(200, "lunes", WORST).share_over_threshold < 0.15  # §3.3: 5 %
    weekend = simulate(200, "fin de semana", WORST)
    assert weekend.share_over_threshold > 0.7  # §3.3: 82 %
    assert 10 * 60 < weekend.wait_p50_s < 20 * 60  # §3.3: 15 min


def test_slow_byteplus_first_fails_at_500() -> None:
    for peak in PEAKS:
        assert simulate(200, peak, SLOW).share_over_threshold < 0.01
    assert 0.0 < simulate(500, "día normal", SLOW).share_over_threshold < 0.10  # §3.3: 3,8 %


def test_omnihuman_single_slot() -> None:
    assert omnihuman_saturation_businesses(PEAKS["fin de semana"]) == pytest.approx(419, abs=1)
    assert omnihuman_saturation_businesses(PEAKS["día normal"]) == pytest.approx(838, abs=1)
    assert omnihuman_mean_wait_minutes(200, PEAKS["fin de semana"]) == pytest.approx(5.5, abs=0.1)
    assert math.isinf(omnihuman_mean_wait_minutes(500, PEAKS["fin de semana"]))
    assert omnihuman_first_failing_position() == 4


def test_cli_prints_every_table(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--replicas", "2"]) == 0
    out = capsys.readouterr().out
    assert "### 3.2" in out
    assert out.count("### 3.3") == 3
    assert "OmniHuman" in out
    assert len(FLEET_SIZES) == 5

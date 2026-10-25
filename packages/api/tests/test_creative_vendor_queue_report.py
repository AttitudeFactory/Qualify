"""m-24852158: the team's command computes tasks at once, queue wait and render on known
data — the numbers the epic's triggers read."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from qualify_api.creative.vendor_queue_report import (
    OPEN_TASK_CAP,
    TimingRow,
    at_once,
    build_report,
    main,
    model_group,
    percentile,
)

NOW = datetime(2026, 10, 26, 18, 0, tzinfo=UTC)
SINCE = NOW - timedelta(days=7)
T0 = datetime(2026, 10, 25, 15, 0, tzinfo=UTC)  # 10:00 in Bogotá
TENANT_A = UUID("00000000-0000-0000-0000-0000000000a1")
TENANT_B = UUID("00000000-0000-0000-0000-0000000000b2")
SD25 = "dreamina-seedance-2-5-260628"


def _task(
    start_s: float,
    wait_s: float | None,
    render_s: float | None,
    *,
    tenant: UUID = TENANT_A,
    model: str = SD25,
    provider: str = "seedance",
    phase: str = "draft",
    late: bool = False,
    status: str | None = "succeeded",
) -> TimingRow:
    submitted = T0 + timedelta(seconds=start_s)
    running = submitted + timedelta(seconds=wait_s) if wait_s is not None else None
    finished = None
    if render_s is not None:
        finished = (running or submitted) + timedelta(seconds=render_s)
    return TimingRow(
        tenant_id=tenant,
        provider=provider,
        model_id=model,
        phase=phase,
        submitted_at=submitted,
        running_at=running,
        finished_at=finished,
        final_status=status if finished else None,
        finished_late=late,
    )


def test_percentile_is_nearest_rank_on_known_values() -> None:
    values = [float(v) for v in range(1, 21)]  # 1..20
    assert percentile(values, 50) == 10
    assert percentile(values, 95) == 19
    assert percentile(values, 100) == 20
    assert percentile([7.0], 95) == 7
    assert percentile([], 95) is None


def test_model_group_joins_versions_and_drafts_with_finals() -> None:
    assert model_group("seedance", SD25) == "dreamina-seedance-2-5"
    assert model_group("seedance", "dreamina-seedance-2-5-260901") == "dreamina-seedance-2-5"
    assert model_group("omnihuman", "omnihuman-1.5") == "omnihuman"


def test_at_once_counts_the_tasks_in_byteplus_at_each_submission_across_tenants() -> None:
    rows = [
        _task(0, 0, 100),  # [0, 100)
        _task(10, 0, 100, tenant=TENANT_B),  # [10, 110)
        _task(20, 0, 100, phase="final"),  # [20, 120) — a final shares the 10
        _task(100, 0, 50),  # the first one ended exactly now → 3, not 4
        _task(30, 0, 100, provider="omnihuman", model="omnihuman-1.5"),  # its own bucket
    ]
    counts = sorted(
        (r.submitted_at - T0).total_seconds() for r, g, c in at_once(rows, NOW) if c == 3
    )
    by_start = {(r.submitted_at - T0).total_seconds(): c for r, _, c in at_once(rows, NOW)}
    assert by_start == {0: 1, 10: 2, 20: 3, 100: 3, 30: 1}
    assert counts == [20, 100]


def test_report_gives_p95_of_tasks_at_once_and_of_the_wait_on_known_data() -> None:
    # 20 drafts submitted 1 s apart, none ending before the last starts: the n-th sees n
    rows = [_task(i, wait_s=float(i * 10), render_s=60) for i in range(20)]
    report = build_report(rows, since=SINCE, now=NOW)

    (overall,) = report.overall
    assert overall.group == "dreamina-seedance-2-5"
    assert overall.at_once.n == 20
    assert overall.at_once.p50 == 10 and overall.at_once.p95 == 19 and overall.at_once.max == 20
    # waits 0, 10, …, 190 s
    assert overall.wait_seconds.p50 == 90 and overall.wait_seconds.p95 == 180
    assert overall.wait_seconds.max == 190
    assert overall.render_seconds["draft"].p95 == 60

    triggers = {t.name: t.met for t in report.triggers}
    assert triggers["Ticket a BytePlus (m-24852172)"] is True  # p95 19 ≥ 5
    assert triggers["Cola propia con reparto justo"] is True  # max wait 190 s > 60
    assert triggers["«Generar ya» con costo (m-24852171)"] is False  # p95 180 s ≤ 300

    assert [b.label for b in report.days] == ["2026-10-25"]
    assert [b.label for b in report.hours] == ["2026-10-25 10:00"]  # Bogotá time


def test_quiet_week_meets_no_trigger() -> None:
    rows = [_task(i * 3600, 2, 80) for i in range(5)]
    report = build_report(rows, since=SINCE, now=NOW)
    assert not any(t.met for t in report.triggers)
    assert report.overall[0].at_once.max == 1


def test_late_ends_count_at_once_but_not_in_render_and_unknown_waits_are_counted() -> None:
    rows = [
        _task(0, 5, 60),
        _task(10, None, 3000, late=True),  # resumed after the fact
    ]
    report = build_report(rows, since=SINCE, now=NOW)
    (overall,) = report.overall
    assert overall.at_once.max == 2
    assert overall.render_seconds["draft"].n == 1
    assert overall.wait_seconds.n == 1
    assert report.late_ends == 1 and report.unknown_waits == 1


def test_an_open_task_counts_until_the_cap_only() -> None:
    lost = _task(0, None, None, status=None)
    later = _task(OPEN_TASK_CAP.total_seconds() + 1, 0, 30)
    within = _task(60, 0, 30)
    report = build_report([lost, later, within], since=SINCE, now=NOW)
    by_start = {
        (r.submitted_at - T0).total_seconds(): c for r, _, c in at_once([lost, later, within], NOW)
    }
    assert by_start[60] == 2
    assert by_start[OPEN_TASK_CAP.total_seconds() + 1] == 1
    assert report.open_tasks == 1


def test_tasks_before_the_window_are_context_not_samples() -> None:
    before = TimingRow(
        tenant_id=TENANT_A,
        provider="seedance",
        model_id=SD25,
        phase="draft",
        submitted_at=SINCE - timedelta(seconds=30),
        running_at=SINCE - timedelta(seconds=30),
        finished_at=SINCE + timedelta(seconds=100),
        final_status="succeeded",
    )
    inside = TimingRow(
        tenant_id=TENANT_A,
        provider="seedance",
        model_id=SD25,
        phase="draft",
        submitted_at=SINCE + timedelta(seconds=10),
        running_at=SINCE + timedelta(seconds=10),
        finished_at=SINCE + timedelta(seconds=60),
        final_status="succeeded",
    )
    report = build_report([before, inside], since=SINCE, now=NOW)
    assert report.tasks == 1
    assert report.overall[0].at_once.max == 2


def test_cli_prints_the_three_metrics_and_json_reads_back() -> None:
    rows = [_task(i, 1, 60) for i in range(3)]
    seen: list[tuple[datetime, list[UUID]]] = []

    def read(since: datetime, tenants: list[UUID]) -> list[TimingRow]:
        seen.append((since, list(tenants)))
        return rows

    out: list[str] = []
    assert main(["--days", "7"], read=read, now=NOW, out=out.append) == 0
    text = out[-1]
    assert "a la vez" in text and "espera" in text and "render borrador" in text
    assert "Disparadores de la épica" in text
    assert seen[0] == (SINCE, [])

    out.clear()
    assert main(["--json", "--tenant", str(TENANT_A)], read=read, now=NOW, out=out.append) == 0
    payload = json.loads(out[-1])
    assert payload["tasks"] == 3 and payload["scope"] == str(TENANT_A)
    assert payload["overall"][0]["at_once"]["max"] == 3


def test_cli_reports_a_failed_read_with_exit_1() -> None:
    def broken(since: datetime, tenants: list[UUID]) -> list[TimingRow]:
        raise RuntimeError("no database")

    out: list[str] = []
    assert main([], read=broken, now=NOW, out=out.append) == 1
    assert "could not run" in out[-1]

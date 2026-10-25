"""Demand and queue simulation for BytePlus generation concurrency.

Rebuilds the model behind ``docs/escalar-generacion-concurrencia.md`` §3: how many Seedance
tasks a fleet of businesses launches in a peak hour, and how long they wait for one of the
account's concurrent slots (10, FIFO, as BytePlus queues them). Also the analytic M/D/1 view of
OmniHuman's single slot (§3.4).

Pure Python, stdlib only, seeded and deterministic: the same arguments always print the same
numbers, so the doc and ``tests/test_concurrency_sim.py`` can pin them. No vendor calls.

Run it::

    python -m qualify_creative.concurrency_sim          # every table of §3
    python -m qualify_creative.concurrency_sim --replicas 5 --seed 7
"""

from __future__ import annotations

import argparse
import heapq
import math
import random
import sys
from collections.abc import Sequence
from dataclasses import dataclass, replace

#: Bumped whenever the model (not just a parameter) changes, so a number quoted in a doc can
#: say which version produced it.
MODEL_VERSION = "2026-10-26.1"

#: Peak factor over the mean working hour (§3.1): lunch on a normal day, Monday morning, and
#: Thursday/Friday when everybody prepares the weekend.
PEAKS: dict[str, float] = {"día normal": 3.0, "lunes": 4.0, "fin de semana": 6.0}

#: The business counts §3 reports.
FLEET_SIZES: tuple[int, ...] = (10, 50, 200, 500, 1000)


@dataclass(frozen=True)
class Assumptions:
    """Every input of §3.1. Defaults are the doc's values."""

    #: Seedance tasks per business per month with the whole quota: (previews, finals).
    plan_tasks: tuple[tuple[str, int, int], ...] = (
        ("Básico", 20, 4),
        ("Plus", 40, 8),
        ("Pro", 80, 16),
    )
    #: Share of businesses on each plan, same order as ``plan_tasks``.
    plan_mix: tuple[float, ...] = (0.6, 0.3, 0.1)
    #: Share of the monthly quota actually used (0.5 typical, 1.0 everybody exhausts it).
    quota_use: float = 0.5
    draft_seconds: float = 120.0
    final_seconds: float = 60.0
    #: Multiplier on both durations («BytePlus lento» = 2).
    slowdown: float = 1.0
    working_days: int = 22
    working_hours: float = 8.0
    #: Share of the day's tasks that fall inside the working hours.
    working_hours_share: float = 0.7
    #: Tasks launched together by one session, with their probabilities.
    burst_sizes: tuple[int, ...] = (1, 3, 5)
    burst_probs: tuple[float, ...] = (0.5, 0.3, 0.2)
    #: Concurrent tasks per main account (Seedance 2.5, drafts and finals share them).
    slots: int = 10
    #: A task queued longer than this missed the adapter's 8-minute window (pre-#325 code).
    wait_threshold_seconds: float = 360.0
    #: The simulated peak lasts this many hours; only the middle hour is measured.
    peak_hours: int = 3

    @property
    def tasks_per_business_month(self) -> float:
        """Monthly Seedance tasks of the average business at ``quota_use`` (38.4 at 100 %)."""
        full = sum(
            share * (previews + finals)
            for share, (_, previews, finals) in zip(self.plan_mix, self.plan_tasks, strict=True)
        )
        return full * self.quota_use

    @property
    def draft_share(self) -> float:
        """Share of tasks that are drafts (previews): 20 / 24 = 0.83."""
        previews = sum(s * p for s, (_, p, _f) in zip(self.plan_mix, self.plan_tasks, strict=True))
        finals = sum(s * f for s, (_, _p, f) in zip(self.plan_mix, self.plan_tasks, strict=True))
        return previews / (previews + finals)

    @property
    def mean_task_seconds(self) -> float:
        """Mean service time: 110 s with the default durations."""
        d = self.draft_share
        return (d * self.draft_seconds + (1 - d) * self.final_seconds) * self.slowdown

    @property
    def mean_burst(self) -> float:
        return sum(s * p for s, p in zip(self.burst_sizes, self.burst_probs, strict=True))

    def peak_tasks_per_hour(self, businesses: int, peak_factor: float) -> float:
        """Expected tasks launched in one peak hour by ``businesses``."""
        per_day = businesses * self.tasks_per_business_month / self.working_days
        mean_working_hour = per_day * self.working_hours_share / self.working_hours
        return mean_working_hour * peak_factor


@dataclass(frozen=True)
class QueueResult:
    """What one scenario measured, pooled over its replicas."""

    businesses: int
    peak: str
    peak_tasks: float
    mean_load: float
    max_in_system: int
    wait_p50_s: float
    wait_p95_s: float
    share_over_threshold: float


def _poisson_arrivals(rng: random.Random, rate_per_s: float, horizon_s: float) -> list[float]:
    times: list[float] = []
    t = rng.expovariate(rate_per_s)
    while t < horizon_s:
        times.append(t)
        t += rng.expovariate(rate_per_s)
    return times


def _percentile(sorted_values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile; 0 for an empty sample."""
    if not sorted_values:
        return 0.0
    rank = max(1, math.ceil(q * len(sorted_values)))
    return sorted_values[rank - 1]


def _run_replica(
    rng: random.Random, a: Assumptions, tasks_per_hour: float
) -> tuple[list[float], int]:
    """One peak: waits of the tasks launched in the middle hour, and the max in system."""
    horizon = a.peak_hours * 3600.0
    sessions = _poisson_arrivals(rng, tasks_per_hour / a.mean_burst / 3600.0, horizon)
    tasks: list[tuple[float, float]] = []
    for arrival in sessions:
        size = rng.choices(a.burst_sizes, weights=a.burst_probs)[0]
        for _ in range(size):
            draft = rng.random() < a.draft_share
            seconds = (a.draft_seconds if draft else a.final_seconds) * a.slowdown
            tasks.append((arrival, seconds))

    free_at = [0.0] * a.slots  # min-heap of the time each slot frees up
    measure_from, measure_to = 3600.0, 7200.0
    waits: list[float] = []
    finishes: list[float] = []  # min-heap of finish times of tasks still in the system
    max_in_system = 0
    for arrival, seconds in tasks:  # already in arrival order; a burst keeps its order (FIFO)
        while finishes and finishes[0] <= arrival:
            heapq.heappop(finishes)
        start = max(arrival, heapq.heappop(free_at))
        finish = start + seconds
        heapq.heappush(free_at, finish)
        heapq.heappush(finishes, finish)
        max_in_system = max(max_in_system, len(finishes))
        if measure_from <= arrival < measure_to:
            waits.append(start - arrival)
    return waits, max_in_system


def simulate(
    businesses: int,
    peak: str,
    assumptions: Assumptions | None = None,
    *,
    replicas: int = 30,
    seed: int = 20261024,
) -> QueueResult:
    """Simulate ``replicas`` peaks of ``peak`` for ``businesses`` and pool the middle hours."""
    a = assumptions or Assumptions()
    tasks_per_hour = a.peak_tasks_per_hour(businesses, PEAKS[peak])
    # Common random numbers: every scenario draws from the same stream, so two scenarios with
    # the same load (500 businesses ×6 and 1 000 ×3) give the same answer, and a change between
    # scenarios is the model, not the dice.
    rng = random.Random(seed)
    waits: list[float] = []
    max_in_system = 0
    for _ in range(replicas):
        replica_waits, replica_max = _run_replica(rng, a, tasks_per_hour)
        waits.extend(replica_waits)
        max_in_system = max(max_in_system, replica_max)
    waits.sort()
    over = sum(1 for w in waits if w > a.wait_threshold_seconds)
    return QueueResult(
        businesses=businesses,
        peak=peak,
        peak_tasks=tasks_per_hour,
        mean_load=tasks_per_hour * a.mean_task_seconds / 3600.0,
        max_in_system=max_in_system,
        wait_p50_s=_percentile(waits, 0.50),
        wait_p95_s=_percentile(waits, 0.95),
        share_over_threshold=over / len(waits) if waits else 0.0,
    )


# --- OmniHuman: one slot, deterministic render, analytic M/D/1 (§3.4) -------------------------


@dataclass(frozen=True)
class OmniHumanAssumptions:
    #: Share of businesses that make one presenter video a month.
    presenter_share: float = 0.5
    #: Render time of a 30-second presenter (RTF 23–27).
    render_minutes: float = 12.0
    slots: int = 1
    #: The adapter gives up this long after creating the task (queue + render).
    window_minutes: float = 40.0


def omnihuman_load(
    businesses: int,
    peak_factor: float,
    a: OmniHumanAssumptions | None = None,
    base: Assumptions | None = None,
) -> float:
    """Utilization of OmniHuman's slots in the peak hour (1.0 = saturated)."""
    o = a or OmniHumanAssumptions()
    b = base or Assumptions()
    per_day = businesses * o.presenter_share / b.working_days
    per_hour = per_day * b.working_hours_share / b.working_hours * peak_factor
    return per_hour * o.render_minutes / 60.0 / o.slots


def omnihuman_mean_wait_minutes(
    businesses: int, peak_factor: float, a: OmniHumanAssumptions | None = None
) -> float:
    """Pollaczek–Khinchine mean queue wait for M/D/1; ``inf`` at or past saturation."""
    o = a or OmniHumanAssumptions()
    rho = omnihuman_load(businesses, peak_factor, o)
    if rho >= 1.0:
        return math.inf
    return rho * o.render_minutes / (2.0 * (1.0 - rho))


def omnihuman_saturation_businesses(
    peak_factor: float, a: OmniHumanAssumptions | None = None
) -> float:
    """Business count at which OmniHuman's load reaches 1 in that peak."""
    return 1.0 / omnihuman_load(1, peak_factor, a)


def omnihuman_first_failing_position(a: OmniHumanAssumptions | None = None) -> int:
    """Position in line (1 = first) whose queue + render exceeds the window."""
    o = a or OmniHumanAssumptions()
    position = 1
    while position * o.render_minutes <= o.window_minutes:
        position += 1
    return position


# --- Report ---------------------------------------------------------------------------------

#: §3.2 rows: (businesses, peak).
TYPICAL_ROWS: tuple[tuple[int, str], ...] = (
    (10, "fin de semana"),
    (50, "fin de semana"),
    (200, "fin de semana"),
    (500, "día normal"),
    (500, "fin de semana"),
    (1000, "día normal"),
    (1000, "lunes"),
    (1000, "fin de semana"),
)

#: §3.3 scenarios: (label, quota_use, slowdown).
HARD_SCENARIOS: tuple[tuple[str, float, float], ...] = (
    ("Cupo al 100 %, BytePlus normal", 1.0, 1.0),
    ("Cupo al 50 %, BytePlus lento ×2", 0.5, 2.0),
    ("Cupo al 100 % y BytePlus lento ×2 (el peor caso)", 1.0, 2.0),
)


def _fmt_wait(seconds: float) -> str:
    if seconds >= 600:
        return f"{seconds / 60:.0f} min"
    return f"{seconds:.0f} s"


def _fmt_num(value: float, decimals: int = 0) -> str:
    text = f"{value:,.{decimals}f}"
    return text.replace(",", " ").replace(".", ",")


def _row(r: QueueResult) -> str:
    peak = f"{r.peak} ×{PEAKS[r.peak]:g}"
    return (
        f"| {_fmt_num(r.businesses)} | {peak} | {_fmt_num(r.peak_tasks)} | "
        f"{_fmt_num(r.mean_load, 1)} | {r.max_in_system} | "
        f"{_fmt_wait(r.wait_p50_s)} / {_fmt_wait(r.wait_p95_s)} | "
        f"{_fmt_num(r.share_over_threshold * 100, 1)} % |"
    )


_HEADER = (
    "| Negocios | Pico | Tareas en la hora pico | Carga media | Máximo en sistema | "
    "Espera p50 / p95 | Tareas que esperan > 6 min |\n"
    "|---:|---|---:|---:|---:|---|---:|"
)


def report(*, replicas: int = 30, seed: int = 20261024) -> str:
    """The Markdown of §3.2, §3.3 and the OmniHuman figures of §3.4."""
    base = Assumptions()
    lines = [
        f"Modelo {MODEL_VERSION} · {replicas} réplicas · semilla {seed} · "
        f"{_fmt_num(base.tasks_per_business_month * 2, 1)} tareas/negocio/mes con el cupo "
        f"entero · duración media {_fmt_num(base.mean_task_seconds)} s · "
        f"{base.slots} a la vez",
        "",
        "### 3.2 Uso del cupo al 50 %, BytePlus normal",
        "",
        _HEADER,
    ]
    for businesses, peak in TYPICAL_ROWS:
        lines.append(_row(simulate(businesses, peak, base, replicas=replicas, seed=seed)))

    for label, quota_use, slowdown in HARD_SCENARIOS:
        a = replace(base, quota_use=quota_use, slowdown=slowdown)
        lines += ["", f"### 3.3 {label}", "", _HEADER]
        for businesses in FLEET_SIZES:
            for peak in PEAKS:
                lines.append(_row(simulate(businesses, peak, a, replicas=replicas, seed=seed)))

    o = OmniHumanAssumptions()
    lines += [
        "",
        "### 3.4 OmniHuman (1 a la vez, M/D/1 analítico)",
        "",
        f"- Satura (carga 1) en fin de semana ×6 a "
        f"{_fmt_num(omnihuman_saturation_businesses(PEAKS['fin de semana']))} negocios; "
        f"en día normal ×3 a {_fmt_num(omnihuman_saturation_businesses(PEAKS['día normal']))}.",
        f"- Espera media en el pico del fin de semana a 200 negocios: "
        f"{_fmt_num(omnihuman_mean_wait_minutes(200, PEAKS['fin de semana']), 1)} min.",
        f"- Con ventana de {o.window_minutes:g} min y {o.render_minutes:g} min por render, "
        f"falla el puesto {omnihuman_first_failing_position()} de la fila.",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--replicas", type=int, default=30)
    parser.add_argument("--seed", type=int, default=20261024)
    args = parser.parse_args(argv)
    sys.stdout.write(report(replicas=args.replicas, seed=args.seed) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

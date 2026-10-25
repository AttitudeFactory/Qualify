"""The team's measurement of BytePlus's queue (m-24852158). READ-ONLY.

    python -m qualify_api.creative.vendor_queue_report [--days 7] [--tz America/Bogota]
    python -m qualify_api.creative.vendor_queue_report --tenant <uuid> [--json]

(`just creative-queue-report …`.) Reads `creative_vendor_task_timings` (0094) through
`admin_session` — the team's role; no owner screen reads this — and prints, for the
window, per day and per hour (in `--tz`), by model group:

- **tareas a la vez** — for every task, how many tasks of its group were in BytePlus
  (queued or running, itself included) the moment it was submitted; p50 / p95 / max over
  the tasks. BytePlus counts its limit per model, all versions together, drafts and
  finals alike (`docs/escalar-generacion-concurrencia.md` §1.1), so the group is the model
  without its date suffix (`dreamina-seedance-2-5-260628` → `dreamina-seedance-2-5`);
- **espera en cola** — `running_at − submitted_at`, p50 / p95 / max (tasks whose start
  was seen by a live observation);
- **render** — `finished_at − running_at`, p50 / p95 / max, by draft / final (tasks whose
  end was seen live: `finished_late` rows only count in «a la vez»).

And the epic's three triggers over the whole window: p95 a la vez ≥ 5 (ticket to
BytePlus, m-24852172), any wait > 60 s or p95 a la vez ≥ 7 (own queue), p95 wait > 5 min
(«Generar ya», m-24852171).

A task with no end yet counts as in BytePlus until now, at most `OPEN_TASK_CAP` after its
submission (a task lost by every observer would otherwise inflate a week of numbers);
the report says how many there are. Nothing is written, sent or paid; exit 0, or 1 when
it could not run.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
import sys
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

logger = logging.getLogger("qualify_api.creative.vendor_queue_report")

DEFAULT_DAYS = 7
DEFAULT_TZ = "America/Bogota"
#: A task with no end counts as in BytePlus at most this long after its submission.
OPEN_TASK_CAP = timedelta(hours=1)
#: The epic's triggers (ticket m-24852158; `docs/escalar-generacion-concurrencia.md` §5).
TICKET_P95_AT_ONCE = 5
OWN_QUEUE_MAX_WAIT_SECONDS = 60.0
OWN_QUEUE_P95_AT_ONCE = 7
GENERATE_NOW_P95_WAIT_SECONDS = 300.0

_DATE_SUFFIX = re.compile(r"-\d{6}$")


@dataclass(frozen=True)
class TimingRow:
    tenant_id: UUID
    provider: str
    model_id: str
    phase: str
    submitted_at: datetime
    running_at: datetime | None = None
    finished_at: datetime | None = None
    final_status: str | None = None
    finished_late: bool = False


def model_group(provider: str, model_id: str) -> str:
    """The bucket BytePlus counts its concurrency in: the model, every version together.
    OmniHuman is one bucket whatever its req_key."""
    if provider == "omnihuman":
        return "omnihuman"
    return _DATE_SUFFIX.sub("", model_id) or provider


def percentile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile (`q` in 0–100): always one of the values, never
    interpolated — with few tasks, a p95 must be a task that really happened."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(len(ordered) * q / 100))
    return ordered[rank - 1]


@dataclass(frozen=True)
class Stats:
    n: int
    p50: float | None
    p95: float | None
    max: float | None

    @classmethod
    def of(cls, values: Sequence[float]) -> Stats:
        return cls(
            n=len(values),
            p50=percentile(values, 50),
            p95=percentile(values, 95),
            max=max(values) if values else None,
        )


@dataclass(frozen=True)
class _Interval:
    row: TimingRow
    group: str
    start: datetime
    end: datetime


def _intervals(rows: Iterable[TimingRow], now: datetime) -> list[_Interval]:
    found = []
    for row in rows:
        end = row.finished_at
        if end is None:
            end = min(now, row.submitted_at + OPEN_TASK_CAP)
        found.append(_Interval(row, model_group(row.provider, row.model_id), row.submitted_at, end))
    return found


def at_once(rows: Sequence[TimingRow], now: datetime) -> list[tuple[TimingRow, str, int]]:
    """For every task: its group and how many tasks of the group were in BytePlus when it
    was submitted, itself included. A task that ended at the very instant another is
    submitted no longer counts (half-open intervals)."""
    intervals = _intervals(rows, now)
    by_group: dict[str, list[_Interval]] = defaultdict(list)
    for interval in intervals:
        by_group[interval.group].append(interval)
    result = []
    for group, members in by_group.items():
        for task in members:
            count = sum(1 for other in members if other.start <= task.start < other.end)
            result.append((task.row, group, max(count, 1)))
    return result


@dataclass
class Bucket:
    """One line of the report: a window × a model group."""

    label: str
    group: str
    at_once: Stats
    wait_seconds: Stats
    render_seconds: dict[str, Stats] = field(default_factory=dict)


@dataclass
class Trigger:
    name: str
    rule: str
    value: str
    met: bool


@dataclass
class QueueReport:
    since: datetime
    until: datetime
    tz: str
    scope: str
    tasks: int
    open_tasks: int
    late_ends: int
    unknown_waits: int
    overall: list[Bucket]
    days: list[Bucket]
    hours: list[Bucket]
    triggers: list[Trigger]


def _bucket(label: str, group: str, items: Sequence[tuple[TimingRow, int]]) -> Bucket:
    waits = [
        (row.running_at - row.submitted_at).total_seconds()
        for row, _ in items
        if row.running_at is not None
    ]
    renders: dict[str, list[float]] = defaultdict(list)
    for row, _ in items:
        if row.running_at is not None and row.finished_at is not None and not row.finished_late:
            renders[row.phase].append((row.finished_at - row.running_at).total_seconds())
    return Bucket(
        label=label,
        group=group,
        at_once=Stats.of([float(count) for _, count in items]),
        wait_seconds=Stats.of(waits),
        render_seconds={phase: Stats.of(values) for phase, values in sorted(renders.items())},
    )


def _grouped(
    measured: Sequence[tuple[TimingRow, str, int]], key: Callable[[TimingRow], str]
) -> list[Bucket]:
    buckets: dict[tuple[str, str], list[tuple[TimingRow, int]]] = defaultdict(list)
    for row, group, count in measured:
        buckets[(key(row), group)].append((row, count))
    return [_bucket(label, group, items) for (label, group), items in sorted(buckets.items())]


def build_report(
    rows: Sequence[TimingRow],
    *,
    since: datetime,
    now: datetime,
    tz: str = DEFAULT_TZ,
    scope: str = "all-tenants",
) -> QueueReport:
    """The report over the tasks SUBMITTED in [since, now). Tasks submitted before the
    window still count as in BytePlus for the ones inside it, so pass them too: only the
    window's own tasks become samples."""
    zone = ZoneInfo(tz)
    measured = [m for m in at_once(rows, now) if since <= m[0].submitted_at < now]
    window = [row for row, _, _ in measured]

    def day(row: TimingRow) -> str:
        return row.submitted_at.astimezone(zone).strftime("%Y-%m-%d")

    def hour(row: TimingRow) -> str:
        return row.submitted_at.astimezone(zone).strftime("%Y-%m-%d %H:00")

    period = f"últimos {(now - since).days} días"
    overall = _grouped(measured, lambda _row: period)
    all_counts = [float(count) for _, _, count in measured]
    all_waits = [
        (row.running_at - row.submitted_at).total_seconds()
        for row in window
        if row.running_at is not None
    ]
    at_once_all = Stats.of(all_counts)
    waits_all = Stats.of(all_waits)
    triggers = [
        Trigger(
            name="Ticket a BytePlus (m-24852172)",
            rule=f"p95 de tareas a la vez >= {TICKET_P95_AT_ONCE}",
            value=_num(at_once_all.p95),
            met=at_once_all.p95 is not None and at_once_all.p95 >= TICKET_P95_AT_ONCE,
        ),
        Trigger(
            name="Cola propia con reparto justo",
            rule=(
                f"alguna espera > {OWN_QUEUE_MAX_WAIT_SECONDS:.0f} s "
                f"o p95 a la vez >= {OWN_QUEUE_P95_AT_ONCE}"
            ),
            value=f"espera max {_secs(waits_all.max)}, p95 a la vez {_num(at_once_all.p95)}",
            met=(waits_all.max is not None and waits_all.max > OWN_QUEUE_MAX_WAIT_SECONDS)
            or (at_once_all.p95 is not None and at_once_all.p95 >= OWN_QUEUE_P95_AT_ONCE),
        ),
        Trigger(
            name="«Generar ya» con costo (m-24852171)",
            rule=f"espera p95 > {GENERATE_NOW_P95_WAIT_SECONDS / 60:.0f} min",
            value=_secs(waits_all.p95),
            met=waits_all.p95 is not None and waits_all.p95 > GENERATE_NOW_P95_WAIT_SECONDS,
        ),
    ]
    return QueueReport(
        since=since,
        until=now,
        tz=tz,
        scope=scope,
        tasks=len(window),
        open_tasks=sum(1 for row in window if row.finished_at is None),
        late_ends=sum(1 for row in window if row.finished_late),
        unknown_waits=sum(1 for row in window if row.running_at is None),
        overall=overall,
        days=_grouped(measured, day),
        hours=_grouped(measured, hour),
        triggers=triggers,
    )


# -- rendering ----------------------------------------------------------------------------


def _num(value: float | None) -> str:
    return "—" if value is None else f"{value:g}"


def _secs(value: float | None) -> str:
    return "—" if value is None else f"{value:.0f} s"


def _stats_line(stats: Stats, fmt: Callable[[float | None], str]) -> str:
    return f"n={stats.n} p50 {fmt(stats.p50)} · p95 {fmt(stats.p95)} · max {fmt(stats.max)}"


def _bucket_lines(bucket: Bucket) -> list[str]:
    lines = [
        f"  {bucket.label}  {bucket.group}",
        f"    a la vez   {_stats_line(bucket.at_once, _num)}",
        f"    espera     {_stats_line(bucket.wait_seconds, _secs)}",
    ]
    for phase, stats in bucket.render_seconds.items():
        name = "borrador" if phase == "draft" else "final"
        lines.append(f"    render {name:<8}{_stats_line(stats, _secs)}")
    return lines


def render(report: QueueReport) -> str:
    lines = [
        f"Cola de generación — {report.since:%Y-%m-%d %H:%M} a {report.until:%Y-%m-%d %H:%M} "
        f"UTC (horas en {report.tz}; alcance {report.scope})",
        f"Tareas: {report.tasks} · sin fin conocido: {report.open_tasks} · fin visto tarde: "
        f"{report.late_ends} · espera desconocida: {report.unknown_waits}",
        "",
        "Disparadores de la épica:",
    ]
    for trigger in report.triggers:
        verdict = "SE CUMPLE" if trigger.met else "no"
        lines.append(f"  [{verdict}] {trigger.name}: {trigger.rule} → {trigger.value}")
    for title, buckets in (
        ("Todo el periodo", report.overall),
        ("Por día", report.days),
        ("Por hora", report.hours),
    ):
        lines += ["", f"{title}:"]
        if not buckets:
            lines.append("  (sin tareas)")
        for bucket in buckets:
            lines += _bucket_lines(bucket)
    return "\n".join(lines)


def as_json(report: QueueReport) -> str:
    def stats(s: Stats) -> Mapping[str, object]:
        return {"n": s.n, "p50": s.p50, "p95": s.p95, "max": s.max}

    def bucket(b: Bucket) -> Mapping[str, object]:
        return {
            "label": b.label,
            "group": b.group,
            "at_once": stats(b.at_once),
            "wait_seconds": stats(b.wait_seconds),
            "render_seconds": {k: stats(v) for k, v in b.render_seconds.items()},
        }

    payload = {
        "since": report.since.isoformat(),
        "until": report.until.isoformat(),
        "tz": report.tz,
        "scope": report.scope,
        "tasks": report.tasks,
        "open_tasks": report.open_tasks,
        "late_ends": report.late_ends,
        "unknown_waits": report.unknown_waits,
        "triggers": [t.__dict__ for t in report.triggers],
        "overall": [bucket(b) for b in report.overall],
        "days": [bucket(b) for b in report.days],
        "hours": [bucket(b) for b in report.hours],
    }
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)


# -- production read ----------------------------------------------------------------------


def read_timings(*, since: datetime, tenant_ids: Sequence[UUID] = ()) -> list[TimingRow]:
    """Every task submitted since `since − OPEN_TASK_CAP` or still open then — the ones
    that may have been in BytePlus during the window. `admin_session` (BYPASSRLS, the
    team's role, SELECT only on this table — 0094)."""
    from qualify_shared.db.admin import admin_session  # noqa: PLC0415
    from sqlalchemy import or_, select  # noqa: PLC0415

    from qualify_api.creative.models import CreativeVendorTaskTiming as T  # noqa: PLC0415

    lookback = since - OPEN_TASK_CAP
    query = select(T).where(or_(T.submitted_at >= lookback, T.finished_at >= since))
    if tenant_ids:
        query = query.where(T.tenant_id.in_(list(tenant_ids)))
    with admin_session() as session:
        rows = session.scalars(query).all()
        return [
            TimingRow(
                tenant_id=row.tenant_id,
                provider=row.provider,
                model_id=row.model_id,
                phase=row.phase,
                submitted_at=row.submitted_at,
                running_at=row.running_at,
                finished_at=row.finished_at,
                final_status=row.final_status,
                finished_late=row.finished_late,
            )
            for row in rows
        ]


# -- CLI ----------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m qualify_api.creative.vendor_queue_report",
        description="Tasks at once, queue wait and render time of vendor tasks. Read-only.",
    )
    parser.add_argument("--tenant", dest="tenants", action="append", type=UUID, metavar="UUID")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--tz", default=DEFAULT_TZ, help="Timezone of the day/hour buckets.")
    parser.add_argument("--json", action="store_true", help="Print the report as JSON.")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    read: Callable[[datetime, Sequence[UUID]], list[TimingRow]] | None = None,
    now: datetime | None = None,
    out: Callable[[str], object] = print,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.days < 1:
        parser.error("--days must be at least 1")
    try:
        ZoneInfo(args.tz)
    except Exception:  # noqa: BLE001
        parser.error(f"unknown timezone: {args.tz}")
    moment = now or datetime.now(UTC)
    since = moment - timedelta(days=args.days)
    tenant_ids = list(dict.fromkeys(args.tenants or ()))
    _load_dotenv()
    try:
        rows = (read or (lambda s, t: read_timings(since=s, tenant_ids=t)))(since, tenant_ids)
    except Exception as exc:
        logger.exception("creative.queue_report.failed")
        out(f"queue report could not run: {type(exc).__name__}: {exc}")
        return 1
    scope = ",".join(str(t) for t in tenant_ids) if tenant_ids else "all-tenants"
    report = build_report(rows, since=since, now=moment, tz=args.tz, scope=scope)
    out(as_json(report) if args.json else render(report))
    return 0


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv  # noqa: PLC0415
    except ImportError:
        return
    load_dotenv(Path(__file__).resolve().parents[5] / ".env", override=False)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    raise SystemExit(main())

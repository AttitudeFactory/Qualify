"""`FLEET_CALLS_SQL` (m-24921076 review): the fleet's 24 h model-call count, written as
two sums so each half reads a partial index (`ix_pra_finished`, `ix_pra_queue`) instead
of scanning the table on every status poll.

Offline: the semantics are evaluated in SQLite (ISO timestamps compare like the instants
they name; the `CAST … AS timestamptz` is Postgres'), and the invariant the split relies
on — an unfinished row is always `queued`/`running` — is pinned against every write of a
row's status in the code. The index use itself was checked by hand with EXPLAIN on a
temporary table (200 k finished + 50 queued rows): Index Scan on `ix_pra_finished` +
Bitmap Index Scan on `ix_pra_queue`, no Seq Scan."""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from qualify_api.referentes import reel_analysis_store
from qualify_api.referentes.reel_analysis_store import FLEET_CALLS_SQL

ORIGINAL = (
    "SELECT COALESCE(sum(model_calls), 0) FROM public_reel_analyses "
    "WHERE COALESCE(finished_at, CAST(:now AS timestamptz)) >= :since"
)
NOW = datetime(2026, 11, 6, 12, tzinfo=UTC)
SRC = Path(reel_analysis_store.__file__).parent


def _count(
    sql: str, rows: list[tuple[str, str | None, int]], since: datetime, now: datetime
) -> int:
    db = sqlite3.connect(":memory:")
    db.execute(
        "CREATE TABLE public_reel_analyses (status TEXT, finished_at TEXT, model_calls INTEGER)"
    )
    db.executemany("INSERT INTO public_reel_analyses VALUES (?, ?, ?)", rows)
    lite = re.sub(r"CAST\((:\w+) AS timestamptz\)", r"\1", sql)
    return int(db.execute(lite, {"since": since.isoformat(), "now": now.isoformat()}).fetchone()[0])


def _at(hours: float) -> str:
    return (NOW - timedelta(hours=hours)).isoformat()


# rows as the code leaves them: finished ⇔ ok/failed, unfinished ⇔ queued/running
ROWS = [
    ("ok", _at(1), 1),  # finished within the day: counted
    ("failed", _at(30), 2),  # finished before it: not counted
    ("ok", _at(24), 4),  # exactly on the edge: counted
    ("queued", None, 8),  # unfinished: counted while now >= since
    ("running", None, 16),
]


def test_finished_in_the_window_and_every_unfinished_row_count() -> None:
    assert _count(FLEET_CALLS_SQL, ROWS, NOW - timedelta(hours=24), NOW) == 1 + 4 + 8 + 16


def test_a_row_finished_before_the_window_does_not_count() -> None:
    rows = [("failed", _at(30), 2)]
    assert _count(FLEET_CALLS_SQL, rows, NOW - timedelta(hours=24), NOW) == 0


def test_unfinished_rows_count_only_when_now_is_not_before_since() -> None:
    rows = [("queued", None, 8)]
    assert _count(FLEET_CALLS_SQL, rows, NOW, NOW) == 8
    assert _count(FLEET_CALLS_SQL, rows, NOW + timedelta(hours=1), NOW) == 0


@pytest.mark.parametrize(
    ("since", "now"),
    [
        (NOW - timedelta(hours=24), NOW),
        (NOW, NOW),
        (NOW + timedelta(hours=1), NOW),
        (NOW - timedelta(days=3), NOW),
    ],
)
def test_same_answer_as_the_coalesce_it_replaces(since: datetime, now: datetime) -> None:
    assert _count(FLEET_CALLS_SQL, ROWS, since, now) == _count(ORIGINAL, ROWS, since, now)


# -- the invariant the split relies on ------------------------------------------------


def _status_writes() -> list[tuple[str, str, str]]:
    """Every `SET status = '<s>'` on `public_reel_analyses` in the package, with the rest
    of its statement (up to the end of the call's SQL)."""
    found = []
    for path in sorted((SRC.parent).rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"UPDATE public_reel_analyses(?: a)? SET status = '(\w+)'", text):
            # a claim's WHERE sits in its CTE, just before the UPDATE
            head = text[max(m.start() - 300, 0) : m.start()]
            head = head[head.rfind("text(") :] if "text(" in head else ""
            tail = text[m.end() : m.end() + 900]
            end = re.search(r"\n\s*(\{|\),|RETURNING|\.bindparams)", tail)
            found.append((path.name, m.group(1), head + (tail[: end.start()] if end else tail)))
    return found


def test_the_status_writes_are_the_known_ones() -> None:
    names = {(name, status) for name, status, _ in _status_writes()}
    assert names == {
        ("reel_analysis_queue.py", "running"),
        ("reel_analysis_queue.py", "ok"),
        ("reel_analysis_queue.py", "failed"),
        ("reel_analysis_queue.py", "queued"),
    }


def test_every_finish_sets_finished_at() -> None:
    for name, status, sql in _status_writes():
        if status in ("ok", "failed"):
            assert "finished_at = :now" in sql, (name, status, sql)


def test_every_way_into_the_queue_clears_finished_at_or_starts_from_it() -> None:
    """Into `queued`/`running`: either `finished_at = NULL`, or only from a row already
    `queued`/`running` (the lease's `_HOLDING`, the claim's `{where}`)."""
    for name, status, sql in _status_writes():
        if status in ("queued", "running"):
            assert "finished_at = NULL" in sql or "_HOLDING" in sql or "{where}" in sql, (
                name,
                status,
                sql,
            )


def test_a_new_row_starts_unfinished_and_queued() -> None:
    text = (SRC / "reel_analysis_store.py").read_text(encoding="utf-8")
    inserts = re.findall(r"INSERT INTO public_reel_analyses \(([^)]*)\)", text)
    assert inserts and all("finished_at" not in cols and "status" not in cols for cols in inserts)

"""The 30-day purge of the reel videos the weekly run copied (ADR 44 F9; the R8 slice of
VE-12 m-24921060).

`purge_reel_sources(gate, now, execute)` takes, 100 at a time, the `public_reel_analyses`
rows whose copy is due (`source_purge_after <= now`, `source_purged_at IS NULL`), deletes
their `source/` and `frames/` folders through the public door (`PublicObjectGate`) and
only THEN marks both dates (`source_purged_at`, `frames_purged_at`). An R2 error leaves
that row unmarked (the next pass tries again) and the others go on. The row and anything
VE-04c describes stay. Idempotent: a second pass finds nothing due.

Without `execute` it only reports what it would delete and marks nothing. The
`reels-worker` runs it at start and then every `PURGE_EVERY` with
`QUALIFY_REEL_PURGE_EXECUTE` (`1` in the production compose); `just reel-purge
[--execute]` runs it once, now. Every write goes through `reels_worker_session()`.
The purge is global — the copies belong to no business — so it takes no `--tenant`.
"""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from qualify_shared.objects import public_analysis_prefix

from qualify_api.referentes.reel_analysis import (
    AnalysisStore,
    PostgresAnalysisStore,
    production_gate,
)

logger = logging.getLogger(__name__)

PURGE_BATCH = 100
#: VE-12: once a day in the worker's loop (and once at start).
PURGE_EVERY = timedelta(hours=24)
EXECUTE_ENV = "QUALIFY_REEL_PURGE_EXECUTE"
_ON = frozenset({"1", "true", "yes", "on"})
#: A pass stops after this many batches (100 rows each); the next one goes on.
MAX_BATCHES = 50


def execute_from_env() -> bool:
    return os.environ.get(EXECUTE_ENV, "").strip().lower() in _ON


@dataclass
class PurgeReport:
    execute: bool
    #: Rows whose copy was due.
    due: int = 0
    #: Rows marked purged (0 in a dry run).
    purged: int = 0
    #: Rows left unmarked because R2 failed.
    failed: int = 0
    objects: int = 0
    bytes: int = 0


def purge_reel_sources(
    gate: Any,
    now: datetime,
    execute: bool,
    *,
    store: AnalysisStore | None = None,
    batch: int = PURGE_BATCH,
) -> PurgeReport:
    """Delete (or, without `execute`, only count) the copies due at `now`."""
    active = store or PostgresAnalysisStore()
    report = PurgeReport(execute=execute)
    after: tuple[datetime, Any] | None = None
    for _ in range(MAX_BATCHES):
        rows = active.due_for_purge(now=now, limit=batch, after=after)
        if not rows:
            break
        for row in rows:
            report.due += 1
            prefix = public_analysis_prefix(row.network, row.post_id, row.id)
            try:
                found = [
                    gate.delete_public_prefix(prefix + folder, execute=execute)
                    for folder in ("source/", "frames/")
                ]
            except Exception:  # noqa: BLE001 — that row waits for the next pass
                logger.exception("reel source purge failed for analysis %s", row.id)
                report.failed += 1
                continue
            report.objects += sum(f.objects for f in found)
            report.bytes += sum(f.bytes for f in found)
            if execute and active.mark_purged(row.id, now=now):
                report.purged += 1
        last = rows[-1]
        if last.source_purge_after is None:
            break
        after = (last.source_purge_after, last.id)
    logger.info(
        "reel sources purge: due=%d purged=%d failed=%d objects=%d bytes=%d execute=%s",
        report.due,
        report.purged,
        report.failed,
        report.objects,
        report.bytes,
        execute,
    )
    return report


# --- CLI: `just reel-purge [--execute]` ---------------------------------------------------


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(Path(__file__).resolve().parents[5] / ".env", override=False)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m qualify_api.referentes.reel_retention",
        description="Delete the reel videos copied more than 30 days ago (ADR 44 F9).",
    )
    parser.add_argument(
        "--execute", action="store_true", help="Delete for real (default: only report)."
    )
    args = parser.parse_args(argv)
    _load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    report = purge_reel_sources(production_gate(), datetime.now(UTC), args.execute)
    print(
        f"due={report.due} purged={report.purged} failed={report.failed} "
        f"objects={report.objects} bytes={report.bytes} execute={report.execute}"
    )
    return 1 if report.failed else 0


__all__ = [
    "EXECUTE_ENV",
    "PURGE_BATCH",
    "PURGE_EVERY",
    "PurgeReport",
    "execute_from_env",
    "main",
    "purge_reel_sources",
]


if __name__ == "__main__":
    raise SystemExit(main())

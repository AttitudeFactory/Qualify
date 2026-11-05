"""The 30-day purge of the reels' stored sources and frames (ADR 44 F9; the R8 slice of
VE-12 m-24921060, contract in `docs/traspasos/historias-video-por-partes-backend.md`).

`purge_reel_sources(gate, now, execute)` takes, 100 at a time, the `public_reel_analyses`
rows whose objects are due (`source_purge_after <= now`, `source_purged_at IS NULL`,
index `ix_pra_source_purge` of 0119), deletes their `…/source/` and `…/frames/` folders
through the public door (`PublicObjectGate.delete_public_prefix`, the only method this
module calls) and only THEN marks both dates (`source_purged_at`, `frames_purged_at`). An
R2 error leaves that row unmarked (the next pass tries again) and the others go on. The
sheet and its shots stay (the 90-day delete of the rows is the other half of VE-12, not
built). Idempotent: a second pass finds nothing due.

**No object without a date.** The folders come from the row's identity (network, post id,
analysis id), never from `source_key`, and the analysis writes `source_purge_after`
BEFORE it uploads (`AnalysisQueue.set_purge_date`). So an upload whose `record_source`
never landed — the lease lost, the process killed between the PUT and the UPDATE — is
deleted on the same day as any other. A row held by a live lease is left for the next
day, and a row whose date moved meanwhile (revived by a new URL) is not marked: it is
purged on its new date.

Without `execute` it only reports what it would delete and marks nothing. The
`reels-worker --all-tenants` runs it at start and then every `PURGE_EVERY`, with
`QUALIFY_REEL_PURGE_EXECUTE` (`1` in the production compose); `just reel-purge
[--execute]` runs it once, now. It reads and marks through the analysis queue
(`PostgresAnalysisQueue`, as `qualify_reels_worker`). Global — the objects belong to no
business — so it takes no `--tenant`. It never calls a vendor and charges nobody.
"""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from uuid import UUID

from qualify_shared.objects.public import (
    PublicObjectGate,
    reel_frames_prefix,
    reel_source_prefix,
)

from qualify_api.referentes.reel_analysis_store import DueSource

logger = logging.getLogger(__name__)

PURGE_BATCH = 100
#: VE-12: once a day in the worker's loop (and once at start).
PURGE_EVERY = timedelta(hours=24)
EXECUTE_ENV = "QUALIFY_REEL_PURGE_EXECUTE"
_ON = frozenset({"1", "true", "yes", "on"})
#: A pass stops after this many batches (100 rows each); the next one goes on.
MAX_BATCHES = 50


class SourcePurge(Protocol):
    """The two reads/writes of the purge: `PostgresAnalysisQueue` and
    `InMemoryAnalysisStore` (`reel_analysis_store`)."""

    def purge_due(
        self, now: datetime, *, after: tuple[datetime, UUID] | None, limit: int
    ) -> list[DueSource]: ...

    def mark_purged(self, analysis_id: UUID, purge_after: datetime, now: datetime) -> bool: ...


def execute_from_env() -> bool:
    return os.environ.get(EXECUTE_ENV, "").strip().lower() in _ON


@dataclass
class PurgeReport:
    execute: bool
    #: Rows whose objects were due.
    due: int = 0
    #: Rows marked purged (0 in a dry run).
    purged: int = 0
    #: Rows left unmarked because R2 failed.
    failed: int = 0
    objects: int = 0
    bytes: int = 0


def default_store() -> SourcePurge:
    from qualify_api.referentes.reel_analysis_queue import PostgresAnalysisQueue  # noqa: PLC0415

    return PostgresAnalysisQueue()


def production_gate() -> PublicObjectGate:
    """The public door over the real R2 bucket."""
    from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
    from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

    return PublicObjectGate(R2ObjectStore(R2Settings.from_env()))


def purge_reel_sources(
    gate: PublicObjectGate,
    now: datetime,
    execute: bool,
    *,
    store: SourcePurge | None = None,
    batch: int = PURGE_BATCH,
) -> PurgeReport:
    """Delete (or, without `execute`, only count) the objects due at `now`."""
    active = store or default_store()
    report = PurgeReport(execute=execute)
    after: tuple[datetime, UUID] | None = None
    for _ in range(MAX_BATCHES):
        rows = active.purge_due(now, after=after, limit=batch)
        if not rows:
            break
        for row in rows:
            report.due += 1
            try:
                found = [
                    gate.delete_public_prefix(prefix, execute=execute)
                    for prefix in (
                        reel_source_prefix(row.network, row.post_id, row.id),
                        reel_frames_prefix(row.network, row.post_id, row.id),
                    )
                ]
            except Exception:  # noqa: BLE001 — that row waits for the next pass
                logger.exception("reel source purge failed for analysis %s", row.id)
                report.failed += 1
                continue
            report.objects += sum(f.objects for f in found)
            report.bytes += sum(f.bytes for f in found)
            if execute and active.mark_purged(row.id, row.purge_after, now):
                report.purged += 1
        after = (rows[-1].purge_after, rows[-1].id)
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
        description=(
            "Delete the reel sources and frames the analysis stored more than 30 days ago "
            "(ADR 44 F9, VE-12)."
        ),
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
    "MAX_BATCHES",
    "PURGE_BATCH",
    "PURGE_EVERY",
    "PurgeReport",
    "SourcePurge",
    "default_store",
    "execute_from_env",
    "main",
    "production_gate",
    "purge_reel_sources",
]


if __name__ == "__main__":
    raise SystemExit(main())

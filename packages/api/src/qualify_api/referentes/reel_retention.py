"""The 30-day purges of what the reels-worker keeps in R2: the analyses' sources and
frames (ADR 44 F9; the R8 slice of VE-12 m-24921060, contract in
`docs/traspasos/historias-video-por-partes-backend.md`) and the ideas' covers (ADR 42
R12, m-24854859).

`purge_reel_sources(gate, now, execute)` takes, 100 at a time, the `public_reel_analyses`
rows whose objects are due (`source_purge_after <= now`, `source_purged_at IS NULL`,
index `ix_pra_source_purge` of 0119), deletes their `…/source/` and `…/frames/` folders
through the public door (`PublicObjectGate.delete_public_prefix`, the only method this
module calls), lists both folders again, and only when they are empty marks both dates
(`source_purged_at`, `frames_purged_at`). A transient R2 error leaves that row unmarked
(the next pass tries again) and the others go on; it is logged with its traceback once
per pass. **A refusal by the bucket itself** (`DeleteRefused` with a lock or permission
code — the production bucket refuses overwrites, `ObjectLockedByBucketPolicy`, and
nobody has measured whether it refuses deletes too) STOPS the pass at the first row:
every other row would be refused the same way. One ERROR line names the code; nothing
is marked, so the unmarked due rows (`source_purge_after <= now AND source_purged_at IS
NULL`) are the durable record of what still has to go, and tomorrow's pass tries again.
The sheet and its shots stay (the 90-day delete of the rows is out of VE-12's ticket,
not built). Idempotent: a second pass finds nothing due.

The per-business half of VE-12 (RA5: the reel cuts `source-window-*.mp4` a part keeps in
its piece folder) lives in `reel_window_retention`, run by the per-business daily chore.

**No object without a date.** The folders come from the row's identity (network, post id,
analysis id), never from `source_key`, and the analysis writes `source_purge_after`
BEFORE it uploads (`AnalysisQueue.set_purge_date`). So an upload whose `record_source`
never landed — the lease lost, the process killed between the PUT and the UPDATE — is
deleted on the same day as any other. A row held by a live lease is left for the next
day, and a row whose date moved meanwhile (revived by a new URL) is not marked: it is
purged on its new date.

`purge_reel_covers(gate, now, execute)` deletes the R2 copy of a reel's cover
(`public/reel-covers/{network}/{reel_id}.jpg`, `reel_covers`) `COVER_RETENTION` (30 days)
after the last idea that used it — like F9, and longer than R11's 4 weeks of ideas — in
one row-locked transaction (`reel_covers.PostgresCoverStore.purge_cover`, through
`global_session`): it clears `cover_r2_key` / `cover_r2_used_at`, deletes the object, then
commits. An R2 error rolls the clearing back and leaves the row (the next pass tries
again), and an idea that used the copy meanwhile keeps it. A reel that becomes an idea
again after the purge is copied again. It calls `delete_public_object` only: one cover
key, nothing wider.

Without `execute` both only report what they would delete and mark nothing. The
`reels-worker --all-tenants` runs both in the same pass (`purge_all`) at start and then
every `PURGE_EVERY`, under the same `QUALIFY_REEL_PURGE_EXECUTE` (`1` in the production
compose); `just reel-purge [--execute]` runs them once, now. The sources are read and
marked through the analysis queue (`PostgresAnalysisQueue`, as `qualify_reels_worker`).
Global — the objects belong to no business — so it takes no `--tenant`. It never calls a
vendor and charges nobody.
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

from qualify_shared.objects.gate import PrefixDeletion, is_bucket_refusal
from qualify_shared.objects.public import (
    PublicObjectGate,
    reel_frames_prefix,
    reel_source_prefix,
)

from qualify_api.referentes.reel_analysis_store import DueSource
from qualify_api.referentes.reel_covers import CoverStore

logger = logging.getLogger(__name__)

PURGE_BATCH = 100
#: VE-12: once a day in the worker's loop (and once at start).
PURGE_EVERY = timedelta(hours=24)
EXECUTE_ENV = "QUALIFY_REEL_PURGE_EXECUTE"
_ON = frozenset({"1", "true", "yes", "on"})
#: A pass stops after this many batches (100 rows each); the next one goes on.
MAX_BATCHES = 50
#: R12: a cover's R2 copy is deleted this long after the last idea that used it.
COVER_RETENTION = timedelta(days=30)


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
    #: Rows left unmarked because R2 failed (or left objects behind).
    failed: int = 0
    objects: int = 0
    bytes: int = 0
    #: The codes of a delete the bucket refused (a lock rule, no delete rights): the pass
    #: stopped at the first one, since every other row would be refused the same way.
    refused: tuple[str, ...] = ()


def default_store() -> SourcePurge:
    from qualify_api.referentes.reel_analysis_queue import PostgresAnalysisQueue  # noqa: PLC0415

    return PostgresAnalysisQueue()


def default_cover_store() -> CoverStore:
    from qualify_api.referentes.reel_covers import default_store  # noqa: PLC0415

    return default_store()


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
            prefixes = (
                reel_source_prefix(row.network, row.post_id, row.id),
                reel_frames_prefix(row.network, row.post_id, row.id),
            )
            try:
                found = [gate.delete_public_prefix(p, execute=execute) for p in prefixes]
                # A delete that "succeeded" but left objects behind (a lock rule that
                # answers OK, a listing lag) is not a purge: list again before marking.
                left = (
                    sum(gate.delete_public_prefix(p, execute=False).objects for p in prefixes)
                    if execute
                    else 0
                )
            except Exception as exc:  # noqa: BLE001 — that row waits for the next pass
                report.failed += 1
                if is_bucket_refusal(exc):
                    report.refused = getattr(exc, "codes", None) or ("refused",)
                    logger.error(
                        "reel sources purge STOPPED: R2 refused to delete (%s) for analysis "
                        "%s; nothing marked, the next pass tries again. Check the bucket "
                        "lock rules (docs/traspasos/historias-video-por-partes-backend.md, "
                        "VE-12)",
                        ", ".join(report.refused),
                        row.id,
                    )
                    break
                if report.failed == 1:
                    logger.exception("reel source purge failed for analysis %s", row.id)
                continue
            report.objects += sum(f.objects for f in found)
            report.bytes += sum(f.bytes for f in found)
            if left:
                report.failed += 1
                if report.failed == 1:
                    logger.error(
                        "reel source purge: %d object(s) still stored after the delete for "
                        "analysis %s; not marked",
                        left,
                        row.id,
                    )
                continue
            if execute and active.mark_purged(row.id, row.purge_after, now):
                report.purged += 1
        if report.refused:
            break
        after = (rows[-1].purge_after, rows[-1].id)
    log = logger.warning if report.failed else logger.info
    log(
        "reel sources purge: due=%d purged=%d failed=%d refused=%s objects=%d bytes=%d execute=%s",
        report.due,
        report.purged,
        report.failed,
        ",".join(report.refused) or "-",
        report.objects,
        report.bytes,
        execute,
    )
    return report


@dataclass
class CoverPurgeReport:
    execute: bool
    #: Copies whose last use was `COVER_RETENTION` ago or more.
    due: int = 0
    #: Copies deleted and their rows cleared (0 in a dry run).
    purged: int = 0
    #: Copies an idea used again (or another pass cleared) between the read and the lock.
    kept: int = 0
    #: Rows left as they were because R2 or the database failed.
    failed: int = 0
    objects: int = 0
    bytes: int = 0


def purge_reel_covers(
    gate: PublicObjectGate,
    now: datetime,
    execute: bool,
    *,
    store: CoverStore | None = None,
    batch: int = PURGE_BATCH,
) -> CoverPurgeReport:
    """Delete (or, without `execute`, only count) the cover copies unused since
    `now - COVER_RETENTION`."""
    active = store or default_cover_store()
    cutoff = now - COVER_RETENTION
    report = CoverPurgeReport(execute=execute)
    after: tuple[datetime, str, str] | None = None
    for _ in range(MAX_BATCHES):
        rows = active.due_covers(cutoff, after=after, limit=batch)
        if not rows:
            break
        for row in rows:
            report.due += 1
            deleted: list[PrefixDeletion] = []
            try:
                if not execute:
                    deleted.append(gate.delete_public_object(row.key, execute=False))
                elif not active.purge_cover(
                    row.network,
                    row.reel_id,
                    cutoff,
                    lambda key: deleted.append(gate.delete_public_object(key, execute=True)),
                ):
                    report.kept += 1
                    continue
            except Exception:  # noqa: BLE001 — that row waits for the next pass
                logger.exception("reel cover purge failed for %s/%s", row.network, row.reel_id)
                report.failed += 1
                continue
            if execute:
                report.purged += 1
            report.objects += sum(d.objects for d in deleted)
            report.bytes += sum(d.bytes for d in deleted)
        after = (rows[-1].used_at, rows[-1].network, rows[-1].reel_id)
    logger.info(
        "reel covers purge: due=%d purged=%d kept=%d failed=%d objects=%d bytes=%d execute=%s",
        report.due,
        report.purged,
        report.kept,
        report.failed,
        report.objects,
        report.bytes,
        execute,
    )
    return report


@dataclass
class RetentionReport:
    """One daily pass: the analyses' sources and frames, then the ideas' covers."""

    sources: PurgeReport | None = None
    covers: CoverPurgeReport | None = None

    @property
    def failed(self) -> int:
        return sum(r.failed for r in (self.sources, self.covers) if r is not None)


def purge_all(gate: PublicObjectGate, now: datetime, execute: bool) -> RetentionReport:
    """The worker's daily pass (and `just reel-purge`): F9's sources and frames, then R12's
    covers, through one door and under one `execute`. A half that raises does not stop the
    other; the first error is raised once both ran, so the worker logs the step failed."""
    report = RetentionReport()
    errors: list[Exception] = []
    try:
        report.sources = purge_reel_sources(gate, now, execute)
    except Exception as exc:  # noqa: BLE001 — the covers go on; raised below
        errors.append(exc)
    try:
        report.covers = purge_reel_covers(gate, now, execute)
    except Exception as exc:  # noqa: BLE001 — raised below
        errors.append(exc)
    if errors:
        raise errors[0]
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
            "(ADR 44 F9, VE-12) and the idea covers unused for 30 days (ADR 42 R12)."
        ),
    )
    parser.add_argument(
        "--execute", action="store_true", help="Delete for real (default: only report)."
    )
    args = parser.parse_args(argv)
    _load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    report = purge_all(production_gate(), datetime.now(UTC), args.execute)
    for name, part in (("sources", report.sources), ("covers", report.covers)):
        if part is not None:
            print(
                f"{name}: due={part.due} purged={part.purged} failed={part.failed} "
                f"objects={part.objects} bytes={part.bytes} execute={part.execute}"
            )
    return 1 if report.failed else 0


__all__ = [
    "COVER_RETENTION",
    "EXECUTE_ENV",
    "MAX_BATCHES",
    "PURGE_BATCH",
    "PURGE_EVERY",
    "CoverPurgeReport",
    "PurgeReport",
    "RetentionReport",
    "SourcePurge",
    "default_cover_store",
    "default_store",
    "execute_from_env",
    "main",
    "production_gate",
    "purge_all",
    "purge_reel_covers",
    "purge_reel_sources",
]


if __name__ == "__main__":
    raise SystemExit(main())

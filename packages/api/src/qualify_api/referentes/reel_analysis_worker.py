"""Running a reel's shared analysis — the `reels-worker`'s side (ADR 44, m-24921056 VE-04a;
contract: `docs/traspasos/historias-video-por-partes-backend.md` §VE-04a,
`docs/diseno-video-por-planos.md` §13.3).

Only the `reels-worker` (R8, m-24854855) runs this, as `qualify_reels_worker`. Until R8
exists the same code runs locally as `just reel-analysis-tick` (one pass) or
`just reel-analysis-worker` (a pass every few seconds). Three entries, one body:

- `drain_once()` — takes the next row of the queue (a URL still to download first, then
  the on-demand rows by `wanted_at`, then the rest) and runs it. It is the pass R8's loop
  will call between runs.
- `analyze_run_ideas(tenant_id, brand_id, run_id, sources)` — R4's `IdeaAnalyzer` (step 7
  of `reel_runs.run`): makes the rows for an `ok` run's ideas (a `failed` one whose URL had
  expired goes back to the queue with the URL just read) and runs up to
  `QUALIFY_REEL_ANALYSIS_PER_RUN` (10) of them at once, while their URLs are fresh. Reusing
  an `ok` does not count. The business and the run are only logged, never written.
- `run_analysis(analysis_id)` — one row, by id.

What one run does, each stage persisting before the next (a redeploy resumes from the
last one):

1. **Lease**: 2 min, renewed every 40 s by a side thread; every write presents the token.
2. **downloading** (only when no source is stored yet): a URL read more than 20 h ago, or
   past the expiry the CDN signed, fails `source_expired` WITHOUT a request. Otherwise
   `reel_analysis_source.download_source` (CDN hosts only, no redirects, ≤ 80 MiB, chunks
   to a temp file, sha256 on the fly), `remux_video_only` (≤ 60 s, no audio, no re-encode),
   `source_purge_after = now + 30 d` (F9) written on the row BEFORE the upload (VE-12: an
   object whose next UPDATE never lands is still purged), upload through the PUBLIC door
   to `public/reel-analyses/…/source/source.mp4`, then ONE UPDATE records key, hash, size,
   fps, covered interval, `edit_eligible` and clears the signed URL.
3. **describe** (VE-04c, m-24921058, injected): detects shots, samples frames (uploaded
   through `put_frame`), asks Haiku and returns a `DescribeResult`; every model call is
   counted BEFORE it is made (`charge_model_call`: ≤ 2 per row, the fleet's 1,500 a day).
   The result and its shots are written in one transaction with the live token. Without a
   describe step (today) the row is left `queued` with its source stored: «download first,
   analyse later» (§13.3).

Errors: a refusal (off-CDN host, redirect, 4xx, too large, unreadable, expired) fails the
row at once; a transient one (5xx, timeout, a model failure) puts it back in the queue
with a backoff until its third attempt. The fleet cap leaves it `queued` for 15 min
(`fleet_paused` on the screen). Cost: on the row and in Langfuse only (decision #10 of the
epic) — never a business's consumption ledger. Temp files live in one directory removed
on exit, also on error; one analysis at a time per process
(`QUALIFY_REEL_ANALYSIS_CONCURRENCY`, 1).
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Protocol
from uuid import UUID

import httpx
from qualify_shared.objects.public import (
    FRAME_CONTENT_TYPE,
    SOURCE_CONTENT_TYPE,
    PublicObjectGate,
    is_reel_post_id,
    reel_frame_key,
    reel_source_key,
)

from qualify_api.referentes import reel_analysis_source as src
from qualify_api.referentes.reel_analysis import fleet_daily, usable_video_url
from qualify_api.referentes.reel_analysis_store import (
    CALL_FLEET_CAP,
    CALL_LOST,
    CALL_OK,
    AnalysisQueue,
    AnalysisRecord,
    Claimed,
    DescribeResult,
    SourceFacts,
)
from qualify_api.referentes.reel_analysis_types import (
    ANALYSIS_VERSION,
    ERROR_MODEL_FAILED,
    ERROR_SOURCE_EXPIRED,
    ERROR_SOURCE_UNAVAILABLE,
    NETWORKS,
    STAGE_DETECTING,
    STAGE_DOWNLOADING,
    STATUS_FAILED,
    STATUS_OK,
    ReelSource,
)

logger = logging.getLogger(__name__)

LEASE = timedelta(minutes=2)
RENEW_EVERY_SECONDS = 40.0
MAX_ATTEMPTS = 3
#: F9: the source and its frames are kept 30 days (VE-12 purges them).
SOURCE_RETENTION = timedelta(days=30)
#: A retry waits 1, then 2 minutes; the fleet cap, 15.
RETRY_BASE = timedelta(minutes=1)
FLEET_PAUSE = timedelta(minutes=15)
#: Range reads of a stored source when resuming (never the whole object in memory).
READ_CHUNK_BYTES = 8 * 1024 * 1024

PER_RUN_ENV = "QUALIFY_REEL_ANALYSIS_PER_RUN"
DEFAULT_PER_RUN = 10
CONCURRENCY_ENV = "QUALIFY_REEL_ANALYSIS_CONCURRENCY"
DEFAULT_CONCURRENCY = 1
MAX_CONCURRENCY = 2

# What one execution ended in (returned, and logged — never with the URL).
OUTCOME_OK = "ok"
OUTCOME_DOWNLOADED = "downloaded"
OUTCOME_FAILED = "failed"
OUTCOME_RETRY = "retry"
OUTCOME_FLEET_PAUSED = "fleet_paused"
OUTCOME_LOST = "lost"
OUTCOME_SKIPPED = "skipped"


class ModelCallRefused(Exception):
    """`charge_model_call` said no: `reason` is `row_cap`, `fleet_cap` or `lost`."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class DescribeFailed(Exception):
    """The describe step could not produce a sheet (a cut or tool-less answer, a vendor
    error). Retried while attempts remain; then `model_failed`."""


@dataclass(frozen=True)
class DescribeInput:
    """What VE-04c's describe step receives. Everything that writes goes through the
    callbacks, so the lease fence and the public door are never bypassed."""

    record: AnalysisRecord
    source_path: Path
    source: SourceFacts
    set_stage: Callable[[str], None]
    #: Call right BEFORE each model call; raises `ModelCallRefused` when a guard says no.
    charge_model_call: Callable[[], None]
    #: Upload one JPEG frame (`shot` 0–99, `n` 0–99); returns its public key.
    put_frame: Callable[[int, int, bytes], str]


class DescribeStep(Protocol):
    def __call__(self, job: DescribeInput) -> DescribeResult: ...


#: VE-04c (m-24921058) plugs `reel_analysis_ai.describe` in here. Until then a pass only
#: downloads and stores the source («download first, analyse later», §13.3); it never
#: writes an `ok` — a fake sheet would be read by every business and never rewritten.
DEFAULT_DESCRIBE: DescribeStep | None = None


@dataclass
class Outcome:
    analysis_id: UUID | None
    outcome: str
    error_code: str | None = None
    cost_usd: Decimal = Decimal("0")


@dataclass
class Worker:
    """The collaborators of one worker process (injected in tests)."""

    queue: AnalysisQueue
    gate: PublicObjectGate
    describe: DescribeStep | None = DEFAULT_DESCRIBE
    http: httpx.Client | None = None
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    temp_root: str | None = None
    renew_every: float = RENEW_EVERY_SECONDS
    fleet_cap: int | None = None


def _env_int(name: str, default: int, env: Mapping[str, str] | None = None) -> int:
    raw = ((os.environ if env is None else env).get(name) or "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def per_run_limit(env: Mapping[str, str] | None = None) -> int:
    return max(0, _env_int(PER_RUN_ENV, DEFAULT_PER_RUN, env))


def concurrency(env: Mapping[str, str] | None = None) -> int:
    return max(1, min(MAX_CONCURRENCY, _env_int(CONCURRENCY_ENV, DEFAULT_CONCURRENCY, env)))


_slots = threading.BoundedSemaphore(concurrency())


@contextmanager
def _http(worker: Worker) -> Iterator[httpx.Client]:
    if worker.http is not None:
        yield worker.http
        return
    with httpx.Client(timeout=src.TIMEOUT_SECONDS, follow_redirects=False) as client:
        yield client


class _Renewer:
    """Renews the lease every `every` seconds until stopped; remembers a lost lease."""

    def __init__(self, worker: Worker, claimed: Claimed) -> None:
        self._worker = worker
        self._claimed = claimed
        self._stop = threading.Event()
        self.lost = False
        self._thread = threading.Thread(target=self._loop, name="reel-analysis-lease", daemon=True)

    def _loop(self) -> None:
        while not self._stop.wait(self._worker.renew_every):
            ok = self._worker.queue.renew(
                self._claimed.record.id, self._claimed.token, self._worker.clock() + LEASE
            )
            if not ok:
                self.lost = True
                return

    def still_held(self) -> bool:
        """Right before an R2 write: False if the lease was lost, else renew it now (a
        lease another process took cannot be renewed) — so no object is written for a row
        this process no longer holds."""
        if self.lost:
            return False
        ok = self._worker.queue.renew(
            self._claimed.record.id, self._claimed.token, self._worker.clock() + LEASE
        )
        if not ok:
            self.lost = True
        return ok

    def __enter__(self) -> _Renewer:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=5)


def _backoff(attempts: int) -> timedelta:
    return RETRY_BASE * (2 ** max(0, attempts - 1))


def _copy_stored_source(gate: PublicObjectGate, key: str, dest: Path) -> None:
    """A source stored by an earlier pass, back to a temp file in 8 MiB ranges."""
    try:
        size = gate.public_size(key)
    except (AttributeError, NotImplementedError):
        size = None
    with dest.open("wb") as out:
        if size is None:
            shutil.copyfileobj(gate.open_public(key), out, READ_CHUNK_BYTES)
            return
        for start in range(0, size, READ_CHUNK_BYTES):
            end = min(size, start + READ_CHUNK_BYTES) - 1
            shutil.copyfileobj(gate.open_public_range(key, start, end), out, READ_CHUNK_BYTES)


def _facts(record: AnalysisRecord) -> SourceFacts:
    return SourceFacts(
        source_key=record.source_key or "",
        source_sha256=record.source_sha256 or "",
        source_seconds=float(record.source_seconds or 0.0),
        width=int(record.width or 0),
        height=int(record.height or 0),
        fps=float(record.fps or 0.0),
        covered_from_s=float(record.covered_from_s or 0.0),
        covered_to_s=float(record.covered_to_s or 0.0),
        edit_eligible=bool(record.edit_eligible),
    )


def _settle_error(
    worker: Worker, claimed: Claimed, code: str | None, *, retryable: bool
) -> Outcome:
    record, token, now = claimed.record, claimed.token, worker.clock()
    if retryable and claimed.record.attempts < MAX_ATTEMPTS:
        worker.queue.retry_later(record.id, token, code, now + _backoff(record.attempts))
        return Outcome(record.id, OUTCOME_RETRY, code)
    final = code or (ERROR_SOURCE_UNAVAILABLE if record.source_key is None else ERROR_MODEL_FAILED)
    worker.queue.fail(record.id, token, final, now)
    return Outcome(record.id, OUTCOME_FAILED, final)


def _download(
    worker: Worker,
    claimed: Claimed,
    work: Path,
    url_read_at: datetime | None,
    renewer: _Renewer,
) -> SourceFacts | Outcome:
    """Stage 2. Returns the stored source's facts, or the outcome that ended the row."""
    record, token = claimed.record, claimed.token
    worker.queue.set_stage(record.id, token, STAGE_DOWNLOADING)
    url = record.pending_video_url
    now = worker.clock()
    if not url:
        return _settle_error(worker, claimed, ERROR_SOURCE_UNAVAILABLE, retryable=False)
    if src.url_is_stale(url, url_read_at or record.created_at, now):
        logger.info("reel analysis %s: URL too old, not tried (%s)", record.id, src.url_host(url))
        return _settle_error(worker, claimed, ERROR_SOURCE_EXPIRED, retryable=False)
    raw, remuxed = work / "download.bin", work / "source.mp4"
    try:
        with _http(worker) as client:
            got = src.download_source(record.network, url, raw, client=client)
        facts = src.remux_video_only(raw, remuxed)
    except src.SourceError as error:
        logger.info(
            "reel analysis %s: source %s (%s, %s)",
            record.id,
            error.code,
            src.url_host(url),
            error,
        )
        return _settle_error(worker, claimed, error.code, retryable=error.retryable)
    finally:
        raw.unlink(missing_ok=True)
    key = reel_source_key(record.network, record.post_id, record.id)
    if not renewer.still_held():
        logger.info("reel analysis %s: lease lost before storing the source", record.id)
        return Outcome(record.id, OUTCOME_LOST)
    # VE-12: the purge date is on the row before any byte is in R2, so an upload whose
    # `record_source` below never lands (a lost lease, a crash) is still deleted at 30 d.
    if not worker.queue.set_purge_date(record.id, token, now + SOURCE_RETENTION):
        logger.info("reel analysis %s: lease lost before storing the source", record.id)
        return Outcome(record.id, OUTCOME_LOST)
    try:
        with remuxed.open("rb") as body:
            worker.gate.put_public(key, body, SOURCE_CONTENT_TYPE)
    except Exception:
        logger.exception("reel analysis %s: storing the source failed", record.id)
        return _settle_error(worker, claimed, None, retryable=True)
    stored = SourceFacts(
        source_key=key,
        source_sha256=got.sha256,
        source_seconds=facts.source_seconds,
        width=facts.width,
        height=facts.height,
        fps=facts.fps,
        covered_from_s=facts.covered_from_s,
        covered_to_s=facts.covered_to_s,
        edit_eligible=facts.edit_eligible,
    )
    if not worker.queue.record_source(record.id, token, stored, now + SOURCE_RETENTION):
        return Outcome(record.id, OUTCOME_LOST)
    return stored


def _describe(
    worker: Worker,
    claimed: Claimed,
    path: Path,
    facts: SourceFacts,
    describe: DescribeStep,
    renewer: _Renewer,
) -> Outcome:
    """Stage 3: the injected describe step, under the cost guard and the lease fence."""
    record, token = claimed.record, claimed.token
    cap = worker.fleet_cap if worker.fleet_cap is not None else fleet_daily()

    def set_stage(stage: str) -> None:
        worker.queue.set_stage(record.id, token, stage)

    def charge() -> None:
        now = worker.clock()
        answer = worker.queue.add_model_call(
            record.id, token, now=now, since=now - timedelta(hours=24), fleet_cap=cap
        )
        if answer != CALL_OK:
            raise ModelCallRefused(answer)

    def put_frame(shot: int, n: int, jpeg: bytes) -> str:
        import io  # noqa: PLC0415

        key = reel_frame_key(record.network, record.post_id, record.id, shot, n)
        if not renewer.still_held():
            raise ModelCallRefused(CALL_LOST)
        worker.gate.put_public(key, io.BytesIO(jpeg), FRAME_CONTENT_TYPE)
        return key

    set_stage(STAGE_DETECTING)
    try:
        result = describe(
            DescribeInput(
                record=record,
                source_path=path,
                source=facts,
                set_stage=set_stage,
                charge_model_call=charge,
                put_frame=put_frame,
            )
        )
    except ModelCallRefused as refused:
        if refused.reason == CALL_FLEET_CAP:
            logger.warning("reel analysis %s: fleet cap of %d calls a day reached", record.id, cap)
            worker.queue.retry_later(record.id, token, None, worker.clock() + FLEET_PAUSE)
            return Outcome(record.id, OUTCOME_FLEET_PAUSED)
        if refused.reason == CALL_LOST:
            return Outcome(record.id, OUTCOME_LOST)
        worker.queue.fail(record.id, token, ERROR_MODEL_FAILED, worker.clock())
        return Outcome(record.id, OUTCOME_FAILED, ERROR_MODEL_FAILED)
    except Exception:
        logger.exception("reel analysis %s: describe failed", record.id)
        # A retry that would pass the per-row cap fails at its `charge_model_call`.
        return _settle_error(worker, claimed, ERROR_MODEL_FAILED, retryable=True)
    if not worker.queue.complete(record.id, token, result, worker.clock()):
        return Outcome(record.id, OUTCOME_LOST)
    return Outcome(record.id, OUTCOME_OK, cost_usd=result.cost_usd)


def execute(worker: Worker, claimed: Claimed, *, url_read_at: datetime | None = None) -> Outcome:
    """Run one claimed row to its next resting state (see the module docstring)."""
    record = claimed.record
    with _slots, _Renewer(worker, claimed) as renewer:
        work = Path(tempfile.mkdtemp(prefix="qualify-reel-", dir=worker.temp_root))
        try:
            path = work / "source.mp4"
            if record.source_key is None:
                stored = _download(worker, claimed, work, url_read_at, renewer)
                if isinstance(stored, Outcome):
                    return stored
                facts = stored
            else:
                facts = _facts(record)
                if worker.describe is not None:
                    _copy_stored_source(worker.gate, facts.source_key, path)
            if worker.describe is None:
                # Download-only lane: leave it queued with its source stored.
                worker.queue.release(record.id, claimed.token)
                return Outcome(record.id, OUTCOME_DOWNLOADED)
            if renewer.lost:
                return Outcome(record.id, OUTCOME_LOST)
            return _describe(worker, claimed, path, facts, worker.describe, renewer)
        except Exception:
            logger.exception("reel analysis %s: unexpected error", record.id)
            return _settle_error(worker, claimed, None, retryable=True)
        finally:
            shutil.rmtree(work, ignore_errors=True)


def run_analysis(
    analysis_id: UUID, worker: Worker, *, url_read_at: datetime | None = None
) -> Outcome:
    """Claim `analysis_id` and run it; a row held by another live lease (or finished, or
    out of attempts) is left alone: `skipped`."""
    claimed = worker.queue.claim(analysis_id, worker.clock(), LEASE, max_attempts=MAX_ATTEMPTS)
    if claimed is None:
        return Outcome(analysis_id, OUTCOME_SKIPPED)
    return execute(worker, claimed, url_read_at=url_read_at)


def drain_once(worker: Worker) -> Outcome | None:
    """One pass of the queue: close rows out of attempts, then run the next row. Without a
    describe step only rows with a URL still to download are taken."""
    now = worker.clock()
    reaped = worker.queue.reap_exhausted(now, MAX_ATTEMPTS)
    if reaped:
        logger.info("reel analysis: %d row(s) out of attempts marked failed", reaped)
    claimed = worker.queue.claim_next(
        now, LEASE, download_only=worker.describe is None, max_attempts=MAX_ATTEMPTS
    )
    if claimed is None:
        return None
    outcome = execute(worker, claimed)
    logger.info(
        "reel analysis %s: %s%s",
        outcome.analysis_id,
        outcome.outcome,
        f" ({outcome.error_code})" if outcome.error_code else "",
    )
    return outcome


def analyze_run_ideas(
    tenant_id: UUID,
    brand_id: UUID,
    run_id: UUID,
    sources: Sequence[ReelSource],
    *,
    worker: Worker | None = None,
    limit: int | None = None,
) -> Decimal:
    """R4's `IdeaAnalyzer`: the analyses of an `ok` run's ideas, run while their URLs are
    fresh. Returns what the models cost in this call (R4 adds it to the run). Never raises
    for one idea; the business and the run appear only in the log."""
    active = worker or default_worker()
    cap = per_run_limit() if limit is None else limit
    now = active.clock()
    taken = 0
    cost = Decimal("0")
    for source in sources:
        if (
            source.network not in NETWORKS
            or not is_reel_post_id(source.post_id)
            or not source.post_url
        ):
            continue
        url = usable_video_url(source, now)
        try:
            existing = active.queue.get_by_key(source.network, source.post_id, ANALYSIS_VERSION)
            if existing is not None and existing.status == STATUS_OK:
                continue  # reused: does not count
            if taken >= cap:
                logger.info("reels run %s: analysis cap of %d reached", run_id, cap)
                break
            if existing is None and url is None:
                continue  # nothing to download, nothing to queue
            record, _ = active.queue.ensure(
                replace(source, video_url=url or ""), ANALYSIS_VERSION, now
            )
            if record.status == STATUS_FAILED:
                if url is None:
                    continue
                refreshed = active.queue.refresh_url(record.id, url, now, MAX_ATTEMPTS)
                if refreshed is None:
                    continue
                record = refreshed
            if record.status == STATUS_OK:
                continue
            taken += 1
            # The URL is known fresh only if it is the one just read; an older one stored
            # by the screen is judged by the row's age.
            fresh = url is not None and record.pending_video_url == url
            outcome = run_analysis(
                record.id, active, url_read_at=(source.video_url_at or now) if fresh else None
            )
            cost += outcome.cost_usd
        except Exception:
            logger.exception("reels run %s: analysing one idea failed", run_id)
    return cost


# --------------------------------------------------------------------------------------
# wiring and CLI
# --------------------------------------------------------------------------------------


def default_worker() -> Worker:
    """The real worker: Postgres as `qualify_reels_worker` and the R2 bucket."""
    from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
    from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

    from qualify_api.referentes.reel_analysis_queue import PostgresAnalysisQueue  # noqa: PLC0415

    return Worker(
        queue=PostgresAnalysisQueue(),
        gate=PublicObjectGate(R2ObjectStore(R2Settings.from_env())),
    )


def main(argv: Sequence[str] | None = None, *, worker: Worker | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="reel-analysis-worker",
        description=(
            "Drain the shared reel-analysis queue (ADR 44). Downloads from the networks' "
            "CDNs and writes to R2; never calls ScrapeCreators. Without VE-04c it only "
            "downloads and stores sources."
        ),
    )
    parser.add_argument("--once", action="store_true", help="one pass, then exit")
    parser.add_argument("--interval", type=float, default=5.0, help="seconds between passes")
    parser.add_argument(
        "--max", type=int, default=1, help="rows per pass (--once drains up to this many)"
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    active = worker or default_worker()
    try:
        while True:
            for _ in range(max(1, args.max)):
                if drain_once(active) is None:
                    break
            if args.once:
                return 0
            time.sleep(max(0.5, args.interval))
    except KeyboardInterrupt:
        return 0


__all__ = [
    "DEFAULT_DESCRIBE",
    "LEASE",
    "MAX_ATTEMPTS",
    "DescribeFailed",
    "DescribeInput",
    "DescribeStep",
    "ModelCallRefused",
    "Outcome",
    "Worker",
    "analyze_run_ideas",
    "default_worker",
    "drain_once",
    "execute",
    "main",
    "run_analysis",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

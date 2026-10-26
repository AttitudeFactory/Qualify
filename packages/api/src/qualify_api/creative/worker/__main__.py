"""CLI of `creative-worker` (m-24852163). See `qualify_api.creative.worker` and `runner`.

    python -m qualify_api.creative.worker --tenant <uuid> [--tenant <uuid> ...] [--once]
    python -m qualify_api.creative.worker --all-tenants [--interval 2]

Scope is MANDATORY, like the other workers: `--tenant` only claims and recovers those
businesses' jobs (use it locally: the worker sends real, billed tasks to BytePlus once
executors are registered); `--all-tenants` is the production service.

`--once`: one round — lease recovery, claims, every claimed job carried to its end, and
one pass of the m-24852492 recovery — then exit.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import FrameType
from uuid import UUID

from qualify_api.creative import job_queue as q
from qualify_api.creative.worker.downloads import DownloadGate, downloads_allowed
from qualify_api.creative.worker.executor import JobExecutor
from qualify_api.creative.worker.runner import (
    DEFAULT_INTERVAL_SECONDS,
    RECOVERY_EVERY_SECONDS,
    CreativeWorker,
    WorkerConfig,
    run_loop,
)
from qualify_api.creative.worker.store import PostgresQueueStore, QueueStore

logger = logging.getLogger("qualify_api.creative.worker")

MIN_INTERVAL_SECONDS = 0.5


def _load_dotenv() -> None:
    """The repo-root `.env`, never overriding the environment (same as the other CLIs)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(Path(__file__).resolve().parents[6] / ".env", override=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m qualify_api.creative.worker",
        description="Run the generation queue worker (ADR 41) once or in a loop.",
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument(
        "--tenant",
        dest="tenants",
        action="append",
        type=UUID,
        metavar="UUID",
        help="Only this tenant's jobs (repeatable). Use this locally.",
    )
    scope.add_argument(
        "--all-tenants", action="store_true", help="Every tenant's jobs (production)."
    )
    parser.add_argument("--once", action="store_true", help="Run one round and exit.")
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL_SECONDS,
        help=f"Seconds between rounds (default {DEFAULT_INTERVAL_SECONDS:g}).",
    )
    return parser


def production_executors() -> dict[str, JobExecutor]:
    """The executors by pool. Empty until the generator enqueues (m-24852166): with none,
    no job is claimed and the worker runs only the recoveries."""
    return {}


def main(
    argv: Sequence[str] | None = None,
    *,
    store: QueueStore | None = None,
    executors: Mapping[str, JobExecutor] | None = None,
    recovery: Callable[[], object] | None = None,
    install_signals: bool = True,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.interval < MIN_INTERVAL_SECONDS:
        parser.error(f"--interval must be at least {MIN_INTERVAL_SECONDS:g} seconds")
    _load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    try:
        pools = q.parse_vendor_pools(os.environ.get(q.POOLS_ENV))
    except q.VendorPoolsConfigError as exc:
        logger.error("creative.worker.bad_config %s", exc)
        return 2
    scope_ids: list[UUID] | None = None if args.all_tenants else list(dict.fromkeys(args.tenants))
    if recovery is None:
        from qualify_api.creative.vendor_recovery import recovery_chore  # noqa: PLC0415

        recovery = recovery_chore(scope_ids)
    chosen = dict(production_executors() if executors is None else executors)
    # Monitor only the production store; injected stores never reach Redis/webhooks.
    from qualify_api.creative.worker.operations import (  # noqa: PLC0415
        production_monitor,
        read_snapshot,
    )

    monitor = production_monitor(scope_ids) if store is None else None
    original_recovery = recovery

    def maintenance() -> None:
        if original_recovery is not None:
            try:
                original_recovery()
            except Exception:
                logger.exception("creative.worker.legacy_recovery_failed")
        if monitor is not None:
            monitor.check(read_snapshot(now=monitor.clock(), tenant_ids=scope_ids))

    def vendor_busy(busy: object) -> None:
        if monitor is not None and getattr(busy, "code", None) == "QuotaExceeded":
            monitor.quota_exceeded()

    gate = DownloadGate(downloads_allowed())
    worker = CreativeWorker(
        store or PostgresQueueStore(),
        chosen,
        WorkerConfig(pools=pools, tenant_ids=scope_ids),
        downloads=gate,
        on_vendor_busy=vendor_busy,
    )
    if install_signals:
        _stop_on_signals(worker.stop)
    logger.info(
        "creative.worker.start scope=%s mode=%s pools=%s executors=%s downloads=%s",
        "all-tenants" if scope_ids is None else ",".join(str(t) for t in scope_ids),
        "once" if args.once else "loop",
        ",".join(f"{pool}={size}" for pool, size in pools.items()),
        ",".join(sorted(chosen)) or "none",
        gate.limit,
    )
    code = run_loop(
        worker,
        once=args.once,
        interval=args.interval,
        sidecar=maintenance,
        sidecar_every=RECOVERY_EVERY_SECONDS,
        on_round=monitor.beat if monitor is not None else None,
    )
    logger.info("creative.worker.stopped downloads_peak=%s", gate.peak)
    return code


def _stop_on_signals(stop: threading.Event) -> None:
    """SIGTERM (a deploy) and SIGINT (Ctrl+C) end the loop between rounds; in-flight jobs
    hand themselves back at their next poll."""

    def handler(signum: int, frame: FrameType | None) -> None:
        logger.info("creative.worker.stopping signal=%s", signum)
        stop.set()

    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)


if __name__ == "__main__":
    raise SystemExit(main())

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
    """Real submit/poll/finish executors for the prepared jobs of each vendor pool."""
    from qualify_creative.adapters.byteplus_ark import SeedanceVideoAdapter
    from qualify_creative.adapters.byteplus_omnihuman import OmniHumanVideoAdapter

    from qualify_api.creative.composition import (
        ARK_BASE_URL,
        ARK_BASE_URL_ENV,
        DEFAULT_OMNIHUMAN_REQ_KEY,
        DEFAULT_SEEDANCE_MODEL,
        OMNIHUMAN_REQ_KEY_ENV,
        SEEDANCE_MODEL_ENV,
        production_content_service,
    )
    from qualify_api.creative.pipeline import PipelineStore
    from qualify_api.creative.worker.pipeline import PipelineExecutor

    service = production_content_service()
    store = PipelineStore()
    return {
        q.SEEDANCE_POOL: PipelineExecutor(
            service,
            store,
            SeedanceVideoAdapter(
                model=os.environ.get(SEEDANCE_MODEL_ENV) or DEFAULT_SEEDANCE_MODEL,
                base_url=os.environ.get(ARK_BASE_URL_ENV) or ARK_BASE_URL,
            ),
            "seedance",
        ),
        q.OMNIHUMAN_POOL: PipelineExecutor(
            service,
            store,
            OmniHumanVideoAdapter(
                req_key=os.environ.get(OMNIHUMAN_REQ_KEY_ENV) or DEFAULT_OMNIHUMAN_REQ_KEY,
            ),
            "omnihuman",
        ),
    }


def _night_preparation(
    prepare_pipeline: Callable[[], None], tenant_ids: Sequence[UUID] | None
) -> Callable[[], None]:
    import time

    from qualify_api.creative.final_review import nightly_maintenance

    next_night_maintenance = 0.0

    def preparation() -> None:
        nonlocal next_night_maintenance
        now = time.monotonic()
        if now >= next_night_maintenance:
            try:
                night_tenants = tenant_ids
                if night_tenants is None:
                    from qualify_shared.db.creative_worker import creative_worker_session
                    from sqlalchemy import text

                    with creative_worker_session() as session:
                        night_tenants = tuple(
                            session.scalars(
                                text(
                                    "SELECT DISTINCT tenant_id FROM creative_jobs "
                                    "WHERE kind='final' AND status IN ('queued','failed')"
                                )
                            )
                        )
                nightly_maintenance(night_tenants)
            except Exception:
                logger.exception("creative.worker.nightly_maintenance_failed")
            finally:
                next_night_maintenance = now + 60
        prepare_pipeline()

    return preparation


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
    publish_load = None
    if store is None and scope_ids is None:
        from qualify_api.creative.worker.queue_load import production_load_chore  # noqa: PLC0415

        publish_load = production_load_chore(pools=pools)
    chosen = dict(production_executors() if executors is None else executors)
    # Monitor only the production store; injected stores never reach Redis/webhooks.
    from qualify_api.creative.worker.operations import (  # noqa: PLC0415
        production_monitor,
        read_snapshot,
    )

    monitor = production_monitor(scope_ids) if store is None else None
    original_recovery = recovery
    from qualify_api.mail.final_summary import morning_chore

    morning = morning_chore(scope_ids) if store is None and executors is None else None

    def maintenance() -> None:
        if morning is not None:
            try:
                morning()
            except Exception:
                logger.exception("creative.worker.morning_mail_failed")
        if original_recovery is not None:
            try:
                original_recovery()
            except Exception:
                logger.exception("creative.worker.legacy_recovery_failed")
        if publish_load is not None:
            try:
                publish_load()
            except Exception:
                logger.exception("creative.worker.public_load_failed")
        if monitor is not None:
            try:
                monitor.check(read_snapshot(now=monitor.clock(), tenant_ids=scope_ids))
            except Exception:
                logger.exception("creative.worker.queue_monitor_failed")

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
    preparation = None
    if executors is None:
        from qualify_api.creative.composition import production_content_service
        from qualify_api.creative.pipeline import PipelineStore
        from qualify_api.creative.worker.pipeline import PipelinePreparation

        prepare_pipeline = PipelinePreparation(
            production_content_service(), PipelineStore(), scope_ids
        )
        preparation = _night_preparation(prepare_pipeline, scope_ids)

    code = run_loop(
        worker,
        once=args.once,
        interval=args.interval,
        sidecar=maintenance,
        preparation=preparation,
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

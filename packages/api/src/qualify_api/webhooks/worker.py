"""The webhook intake worker (QUA-147): runs the processor and the retention purge.

    python -m qualify_api.webhooks.worker --once            # one batch, then exit
    python -m qualify_api.webhooks.worker [--interval 30]   # a batch every N s until Ctrl+C
    python -m qualify_api.webhooks.worker --purge [--execute]
    python -m qualify_api.webhooks.worker --purge-account <ig_account_id> [--execute]
    python -m qualify_api.webhooks.worker --requeue-comments [--account <ig_id>] [--execute]
    python -m qualify_api.webhooks.worker --requeue-postbacks [--account <ig_id>] [--execute]

(`just webhook-tick`, `just webhook-worker`, `just webhook-purge …`,
`just webhook-requeue-comments`, `just webhook-requeue-postbacks`.)

`--requeue-comments` puts Instagram `comments` changes recorded as `unsupported` before the
`instagram:comments` handler existed back in the queue, so the next batches turn the ones
that @mention the account into mentions. Dry run (a count) unless `--execute`; idempotent
(`WebhookQueue.requeue_unsupported_comments`).

`--requeue-postbacks` does the same for Instagram `postback` items (Ice Breakers, template
buttons, menu items) recorded as `unsupported` before the `instagram:messages` handler read
them (m-24789472): the next batches turn them into inbound messages of Conversaciones,
one per `mid`, and reply to none of them (`WebhookQueue.requeue_unsupported_postbacks`).

In production the loop runs as the `webhook-worker` service of
`deploy/docker-compose.prod.yml`. Locally it runs only when someone starts it, against
whatever database `QUALIFY_WEBHOOK_WORKER_DSN` names (by default the local development
`qualify`).

Loop mode also sweeps mention sentiment still pending, once at start and then every
`SENTIMENT_SWEEP_EVERY` (QUA-152; each mention is normally analyzed right after ingest).

Loop mode also runs the age purge for real, once at start and then every `PURGE_EVERY` —
that is what keeps "29 days + at most 24 h" ≤ 30 days (QUA-127). It deletes only
settled/failed changes older than `RETENTION`, never `pending`/`processing`.
The explicit `--purge` / `--purge-account` commands are DRY RUNS unless `--execute`: they
print what they would delete and delete nothing.

A batch that raises is logged and the loop continues; a crash loses nothing (claimed rows
go stale and are reclaimed). Several workers at once are safe (`FOR UPDATE SKIP LOCKED`,
compare-and-set settlement).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import socket
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from qualify_api.webhooks.processor import DEFAULT_BATCH, production_processor
from qualify_api.webhooks.repository import RETENTION, PurgeReport, WebhookQueue

logger = logging.getLogger("qualify_api.webhooks.worker")

DEFAULT_INTERVAL_SECONDS = 30
MIN_INTERVAL_SECONDS = 5
PURGE_EVERY = timedelta(hours=24)
# QUA-152: how often the loop re-tries mention sentiment still pending. Each mention is
# normally analyzed right after ingest; the sweep catches failures and model outages.
SENTIMENT_SWEEP_EVERY = timedelta(minutes=10)


def _load_dotenv() -> None:
    """Same convention as the planner worker: the repo-root `.env`, never overriding
    what the environment already sets."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(Path(__file__).resolve().parents[5] / ".env", override=False)


def worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m qualify_api.webhooks.worker",
        description="Process recorded Meta webhook changes (QUA-147).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="one batch, then exit")
    mode.add_argument("--purge", action="store_true", help="age purge (dry run unless --execute)")
    mode.add_argument(
        "--purge-account",
        metavar="IG_ACCOUNT_ID",
        help="delete everything recorded for one account (dry run unless --execute)",
    )
    mode.add_argument(
        "--requeue-comments",
        action="store_true",
        help="requeue Instagram comments recorded as unsupported (dry run unless --execute)",
    )
    mode.add_argument(
        "--requeue-postbacks",
        action="store_true",
        help="requeue Instagram postbacks recorded as unsupported (dry run unless --execute)",
    )
    parser.add_argument(
        "--execute", action="store_true", help="really apply (purges and the --requeue-* modes)"
    )
    parser.add_argument("--account", metavar="IG_ACCOUNT_ID", help="--requeue-*: only this account")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--limit", type=int, default=DEFAULT_BATCH)
    return parser


def _report_purge(kind: str, report: PurgeReport) -> None:
    verb = "deleted" if report.executed else "would delete (dry run)"
    print(f"{kind}: {verb} events={report.events} deliveries={report.deliveries}")


def _auto_purge(queue: WebhookQueue) -> None:
    try:
        report = queue.purge_expired(now=datetime.now(UTC), older_than=RETENTION, execute=True)
        logger.info(
            "webhooks.purge events=%d deliveries=%d (older than %s)",
            report.events,
            report.deliveries,
            RETENTION,
        )
    except Exception:  # noqa: BLE001 — a failed purge must not stop processing
        logger.exception("webhooks.purge failed")


async def _sentiment_sweep() -> None:
    """QUA-152: analyze mentions still pending (never analyzed, or failed below the
    attempt limit). The sweep itself never raises; this guard is belt and braces."""
    from qualify_api.mentions.composition import (  # noqa: PLC0415
        sweep_pending_mention_sentiment,
    )

    try:
        report = await asyncio.to_thread(sweep_pending_mention_sentiment)
        logger.info(
            "mentions.sentiment_sweep tenants=%d new=%d failed=%d tenants_errored=%d",
            report.tenants,
            report.new_results,
            report.failed,
            report.tenants_errored,
        )
    except Exception:  # noqa: BLE001 — a failed sweep must not stop processing
        logger.exception("mentions.sentiment_sweep failed")


async def _run_loop(*, interval: int, limit: int) -> None:
    processor = production_processor(worker_id=worker_id())
    queue = WebhookQueue()
    next_purge = time.monotonic()
    next_sweep = time.monotonic()
    logger.info("webhooks.worker started interval=%ss limit=%d", interval, limit)
    while True:
        started = time.monotonic()
        if started >= next_purge:
            _auto_purge(queue)
            next_purge = started + PURGE_EVERY.total_seconds()
        if started >= next_sweep:
            await _sentiment_sweep()
            next_sweep = started + SENTIMENT_SWEEP_EVERY.total_seconds()
        try:
            report = await processor.run_once(limit=limit)
            if report.claimed:
                logger.info(
                    "webhooks.batch claimed=%d outcomes=%s lost=%d",
                    report.claimed,
                    dict(report.outcomes),
                    report.lost,
                )
        except Exception:  # noqa: BLE001 — log and keep going
            logger.exception("webhooks.batch failed")
        await asyncio.sleep(max(0.0, interval - (time.monotonic() - started)))


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    requeue = args.requeue_comments or args.requeue_postbacks
    if args.execute and not (args.purge or args.purge_account or requeue):
        print("--execute only applies to --purge / --purge-account / --requeue-*")
        return 2
    if args.account and not requeue:
        print("--account only applies to --requeue-comments / --requeue-postbacks")
        return 2
    if args.interval < MIN_INTERVAL_SECONDS:
        print(f"--interval must be at least {MIN_INTERVAL_SECONDS}")
        return 2
    _load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    if args.purge:
        report = WebhookQueue().purge_expired(
            now=datetime.now(UTC), older_than=RETENTION, execute=args.execute
        )
        _report_purge(f"purge older than {RETENTION}", report)
        return 0
    if args.purge_account:
        report = WebhookQueue().purge_by_entry_id(entry_id=args.purge_account, execute=args.execute)
        _report_purge(f"purge account {args.purge_account}", report)
        return 0
    if args.requeue_comments:
        count = WebhookQueue().requeue_unsupported_comments(
            now=datetime.now(UTC), execute=args.execute, entry_id=args.account
        )
        verb = "requeued" if args.execute else "would requeue (dry run)"
        print(f"instagram comments: {verb} events={count}")
        return 0
    if args.requeue_postbacks:
        count = WebhookQueue().requeue_unsupported_postbacks(
            now=datetime.now(UTC), execute=args.execute, entry_id=args.account
        )
        verb = "requeued" if args.execute else "would requeue (dry run)"
        print(f"instagram postbacks: {verb} events={count}")
        return 0
    if args.once:
        report = asyncio.run(production_processor(worker_id=worker_id()).run_once(limit=args.limit))
        print(f"claimed={report.claimed} outcomes={dict(report.outcomes)} lost={report.lost}")
        return 0
    try:
        asyncio.run(_run_loop(interval=args.interval, limit=args.limit))
    except KeyboardInterrupt:
        logger.info("webhooks.worker stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

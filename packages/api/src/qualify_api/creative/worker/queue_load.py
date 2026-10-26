"""Anonymous load estimates for the owner-facing queue notice (m-24852170).

No tenant, piece, job or vendor-task identifiers leave this worker-only publisher.
Waiting work is counted in minute buckets; clients compare their own enqueue minute.
Redis loss removes only the estimate, never the queue or its cancellation guarantee.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from qualify_shared.db.admin import admin_session
from qualify_shared.db.creative_worker import creative_worker_session
from sqlalchemy import text

from qualify_api.creative.job_queue import parse_vendor_pools
from qualify_api.creative.queue_visibility import LOAD_KEY, LOAD_TTL
from qualify_api.creative.worker.lanes import reserved_slots

logger = logging.getLogger(__name__)


def publish_load(
    client: Any, *, now: datetime | None = None, pools: dict[str, int] | None = None
) -> None:
    at = now or datetime.now(UTC)
    capacities = pools if pools is not None else parse_vendor_pools(None)
    with admin_session() as session:
        waiting = (
            session.execute(
                text("""
            SELECT vendor_model,
                   CASE WHEN lane='nightly' THEN 'scheduled' WHEN priority>=8 THEN 'now'
                        WHEN kind='final' THEN 'final' ELSE 'standard' END AS lane,
                   floor(extract(epoch from queued_at)/60)::bigint AS minute, count(*) AS count
            FROM creative_jobs WHERE status='queued' AND not_before <= :now
            GROUP BY 1,2,3
        """),
                {"now": at},
            )
            .mappings()
            .all()
        )
        durations = dict(
            session.execute(
                text("""
            SELECT vendor_model, avg(extract(epoch from
                (finished_at-coalesce(running_at,submitted_at)))) AS seconds
            FROM creative_jobs WHERE status='succeeded' AND finished_at > :since
              AND submitted_at IS NOT NULL AND finished_at > coalesce(running_at,submitted_at)
            GROUP BY vendor_model
        """),
                {"since": at - timedelta(hours=24)},
            ).all()
        )
    with creative_worker_session() as session:
        occupied = {
            row["vendor_model"]: row
            for row in session.execute(
                text("""
            SELECT s.vendor_model, count(*) AS provisioned,
                   count(*) FILTER (WHERE s.holder_job_id IS NOT NULL) AS used,
                   count(*) FILTER (WHERE s.holder_job_id IS NOT NULL
                       AND j.kind <> 'final' AND j.priority < 8) AS common_used
            FROM vendor_slots s LEFT JOIN creative_jobs j ON j.id=s.holder_job_id
            GROUP BY s.vendor_model
        """)
            ).mappings()
        }
    data: dict[str, Any] = defaultdict(dict)
    for pool, capacity in capacities.items():
        occupancy = occupied.get(pool, {})
        capacity = min(capacity, int(occupancy.get("provisioned", 0)))
        used = int(occupancy.get("used", 0))
        common_used = int(occupancy.get("common_used", 0))
        for lane in ("now", "final", "standard", "scheduled"):
            # The common lanes cannot use the reserved immediate/final capacity.
            free = max(0, capacity - used)
            if lane not in {"now", "final"}:
                free = min(free, max(0, capacity - reserved_slots(capacity) - common_used))
            data[pool][lane] = {
                "free": free,
                "mean_seconds": float(durations.get(pool) or 0),
                "waiting": {},
            }
    for row in waiting:
        group = data.get(row["vendor_model"], {}).get(row["lane"])
        if group is not None:
            group["waiting"][str(row["minute"])] = int(row["count"])
    client.set(LOAD_KEY, json.dumps(dict(data)), ex=LOAD_TTL)


def production_load_chore(*, pools: dict[str, int]) -> Any:
    import redis  # noqa: PLC0415

    from qualify_api.config import redis_url  # noqa: PLC0415

    client = redis.Redis.from_url(
        redis_url(), decode_responses=True, socket_timeout=0.25, socket_connect_timeout=0.25
    )

    def run() -> None:
        try:
            publish_load(client, pools=pools)
        except Exception:
            logger.warning("creative.queue.estimate_unavailable")

    return run

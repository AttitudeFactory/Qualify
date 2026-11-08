"""Bounded read-only advertising observations; never creates or updates Meta objects."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from uuid import UUID

from qualify_shared.db.admin import admin_session
from sqlalchemy import text

from qualify_api.ads.account_health import refresh_daily_account_health
from qualify_api.ads.results_service import poll_promotion_results

logger = logging.getLogger(__name__)
HEARTBEAT_MAX_AGE = 180


def heartbeat_path() -> Path:
    return Path(tempfile.gettempdir()) / "qualify-ads-reads.heartbeat"


def heartbeat() -> None:
    path = heartbeat_path()
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(str(time.time()), encoding="ascii")
    os.replace(temporary, path)


def healthy() -> bool:
    try:
        age = time.time() - float(heartbeat_path().read_text(encoding="ascii"))
        return 0 <= age <= HEARTBEAT_MAX_AGE
    except (OSError, ValueError):
        return False


def tenants() -> tuple[UUID, ...]:
    """Admin discovery only; all actual observation access uses tenant-scoped doors."""
    with admin_session() as session:
        return tuple(
            session.scalars(
                text("SELECT DISTINCT tenant_id FROM ad_accounts WHERE selected AND available")
            ).all()
        )


def _lock_key(tenant_id: UUID) -> int:
    digest = hashlib.sha256(b"qualify:ads-read-tick:v1:" + tenant_id.bytes).digest()
    return int.from_bytes(digest[:8], signed=True)


async def tick(tenant_id: UUID, *, limit: int = 100) -> dict[str, int]:
    """One tenant per lease. A crash releases the PostgreSQL transaction advisory lock."""
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError("limit must be between one and five hundred")
    counts = {"health_checked": 0, "health_blocked": 0, "checked": 0, "unavailable": 0}
    # Dedicated administrative lease, not a data access shortcut. Observation helpers
    # open their own tenant sessions. A second replica skips instead of duplicating reads.
    with admin_session() as lease:
        acquired = lease.scalar(
            text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": _lock_key(tenant_id)}
        )
        if not acquired:
            return counts | {"busy": 1}
        health = await refresh_daily_account_health(tenant_id=tenant_id)
        counts["health_checked"] = len(health)
        counts["health_blocked"] = sum(not row.can_promote for row in health)
        counts.update(await poll_promotion_results(tenant_id=tenant_id, limit=limit))
    return counts | {"busy": 0}


async def _run(
    *, tenant_id: UUID | None, all_tenants: bool, once: bool, interval: int, limit: int
) -> None:
    if (tenant_id is None) == (not all_tenants):
        raise ValueError("choose exactly one tenant selector")
    if not 10 <= interval <= 60:
        raise ValueError("interval must be between ten and sixty seconds")
    while True:
        heartbeat()
        selected = tenants() if all_tenants else (tenant_id,)
        totals: dict[str, int] = {"tenants": 0, "errors": 0}
        for selected_tenant in selected:
            heartbeat()
            try:
                result = await tick(selected_tenant, limit=limit)
                for key, value in result.items():
                    totals[key] = totals.get(key, 0) + value
                totals["tenants"] += 1
            except Exception:
                # Never print vendor exceptions, account IDs, credentials or payloads.
                totals["errors"] += 1
                logger.error("Advertising observation tick failed; next tick will retry reads")
        print(json.dumps(totals), flush=True)
        if once:
            return
        await asyncio.sleep(interval)


async def run(
    *, tenant_id: UUID | None, all_tenants: bool, once: bool, interval: int, limit: int
) -> None:
    async def pulse() -> None:
        while True:
            heartbeat()
            await asyncio.sleep(30)

    task = asyncio.create_task(pulse())
    try:
        await _run(
            tenant_id=tenant_id, all_tenants=all_tenants, once=once, interval=interval, limit=limit
        )
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def main() -> None:
    parser = argparse.ArgumentParser(description="Actualizar salud y resultados de anuncios")
    parser.add_argument("--healthcheck", action="store_true")
    selector = parser.add_mutually_exclusive_group()
    selector.add_argument("--tenant", type=UUID)
    selector.add_argument("--all-tenants", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=60, choices=range(10, 61))
    parser.add_argument("--limit", type=int, default=100, choices=range(1, 501))
    args = parser.parse_args()
    if args.healthcheck:
        raise SystemExit(0 if healthy() else 1)
    if args.tenant is None and not args.all_tenants:
        parser.error("choose --tenant or --all-tenants")
    asyncio.run(
        run(
            tenant_id=args.tenant,
            all_tenants=args.all_tenants,
            once=args.once,
            interval=args.interval,
            limit=args.limit,
        )
    )


if __name__ == "__main__":
    main()

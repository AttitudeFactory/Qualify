"""Read-only team command: `just creative-queue` (m-24852167)."""

from __future__ import annotations

import argparse
import json
import logging
import os
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import UUID

from qualify_api.creative import job_queue as q
from qualify_api.creative.worker.operations import Snapshot, read_snapshot


def render(snapshot: Snapshot) -> str:
    lines = ["Cola de generación (UTC; solo metadatos)", "Carril / estado / trabajos"]
    lines.extend(f"{r['lane']} / {r['status']} / {r['jobs']}" for r in snapshot.counts)
    lines.append("Espera en cola propia (desde pedido hasta envío; segundos):")
    for row in snapshot.waits:
        p50 = "—" if row["p50"] is None else f"{row['p50']:.1f}"
        p95 = "—" if row["p95"] is None else f"{row['p95']:.1f}"
        lines.append(f"{row['window']}: p50={p50} p95={p95} muestras={row['samples']}")
    sizes = q.parse_vendor_pools(os.environ.get(q.POOLS_ENV))
    for row in snapshot.slots:
        size = min(
            sizes.get(row["vendor_model"], q.DEFAULT_POOL_SIZE),
            row.get("provisioned", q.DEFAULT_POOL_SIZE),
        )
        lines.append(
            f"{row['vendor_model']}: cupos ocupados={row['occupied']}/{size} "
            f"arrendamientos vencidos={row.get('expired', 0)}"
        )
    lines.append(f"Arrendamientos vencidos: {snapshot.expired_leases}")
    lines.append(f"Finales pendientes a <24 h del plazo: {snapshot.urgent_finals}")
    lines.append("Negocios con más trabajos esperando (ids internos):")
    lines.extend(f"{r['tenant_id']}: {r['jobs']}" for r in snapshot.top_tenants)
    lines.append("p95 diario tareas simultáneas (muestras al enviar, últimos 7 días):")
    lines.extend(
        f"{r['day']} {r['vendor_model']}: {r['p95']:.1f}" for r in snapshot.weekly_capacity
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    from qualify_api.creative.worker.__main__ import _load_dotenv  # noqa: PLC0415

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", type=UUID, action="append", help="Filter jobs by tenant id")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    _load_dotenv()
    try:
        snapshot = read_snapshot(now=datetime.now(UTC), tenant_ids=args.tenant, include_slots=True)
    except Exception:
        logging.getLogger(__name__).error("creative.queue.report_failed", exc_info=True)
        return 1
    print(json.dumps(asdict(snapshot), default=str) if args.json else render(snapshot))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

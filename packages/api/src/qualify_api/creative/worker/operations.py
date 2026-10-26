"""Team-only queue operations (m-24852167). Metadata only; never import in request paths.

Redis stores the worker beat and incident latches. The calendar process watches the beat,
so a stopped creative process cannot silence its own alarm. Queue failures never publish.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text

from qualify_api.support.notify import SupportNotifier, production_support_notifier

logger = logging.getLogger(__name__)
PREFIX = "qualify:creative-queue:"
STALE_SECONDS = 300
QUOTA_QUIET_SECONDS = 300


class RedisStore(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str, **kwargs: Any) -> Any: ...
    def delete(self, key: str) -> Any: ...


@dataclass(frozen=True)
class QueueAlert:
    """Compatible with the existing webhook notifier; contains no client content."""

    reference: str
    message: str

    def as_text(self) -> str:
        return f"Cola de generación · {self.reference}\n{self.message}"


@dataclass(frozen=True)
class Snapshot:
    counts: tuple[Mapping[str, Any], ...] = ()
    waits: tuple[Mapping[str, Any], ...] = ()
    top_tenants: tuple[Mapping[str, Any], ...] = ()
    expired_leases: int = 0
    urgent_finals: int = 0
    weekly_capacity: tuple[Mapping[str, Any], ...] = ()
    slots: tuple[Mapping[str, Any], ...] = ()

    def conditions(self) -> dict[str, QueueAlert]:
        active: dict[str, QueueAlert] = {}
        for row in self.waits:
            value = float(row["p95"] or 0)
            if row["window"] == "hour" and value > 300:
                active["wait"] = QueueAlert(
                    "wait", f"Espera p95 última hora: {value:.0f} s (>300)."
                )
        # Each row is a UTC calendar day's p95 over submission samples, as MEDIR defines it.
        for row in self.weekly_capacity:
            if float(row["p95"] or 0) >= 5:
                active["capacity"] = QueueAlert(
                    "capacity", "p95 diario de tareas simultáneas ≥5 en los últimos 7 días."
                )
        if self.urgent_finals:
            active["deadline"] = QueueAlert(
                "deadline", f"Finales pendientes a menos de 24 h del plazo: {self.urgent_finals}."
            )
        return active


# All queries use bind parameters and select only queue metadata, never piece content.
_SCOPE = "(:all_tenants OR tenant_id = ANY(CAST(:tenant_ids AS uuid[])))"
_COUNTS = f"""
SELECT CASE WHEN lane = 'nightly' THEN 'scheduled'
            WHEN priority >= 8 THEN 'now' WHEN kind = 'final' THEN 'final'
            ELSE 'standard' END AS lane, status, count(*) AS jobs
FROM creative_jobs WHERE {_SCOPE} GROUP BY 1, 2 ORDER BY 1, 2
"""
_WAITS = f"""
SELECT windows.label AS window,
       percentile_cont(0.50) WITHIN GROUP
           (ORDER BY EXTRACT(EPOCH FROM (j.submitted_at - j.queued_at))) AS p50,
       percentile_cont(0.95) WITHIN GROUP
           (ORDER BY EXTRACT(EPOCH FROM (j.submitted_at - j.queued_at))) AS p95,
       count(j.id) AS samples
FROM (VALUES ('hour', interval '1 hour'), ('day', interval '24 hours'))
     AS windows(label, duration)
LEFT JOIN creative_jobs j ON j.submitted_at >= :now - windows.duration
    AND j.submitted_at <= :now AND {_SCOPE.replace("OR tenant_id", "OR j.tenant_id")}
GROUP BY windows.label ORDER BY windows.label
"""
_TOP = f"""
SELECT tenant_id, count(*) AS jobs FROM creative_jobs
WHERE status = 'queued' AND {_SCOPE}
GROUP BY tenant_id ORDER BY count(*) DESC, tenant_id LIMIT 10
"""
_URGENT = f"""
SELECT count(*) FILTER (WHERE status IN ('claimed','submitted') AND lease_until < :now)
    AS expired_leases,
count(*) FILTER (WHERE kind = 'final' AND status NOT IN ('succeeded','failed','cancelled')
    AND deadline < :now + interval '24 hours') AS urgent_finals
FROM creative_jobs WHERE {_SCOPE}
"""
# MEDIR samples concurrency when each vendor task is submitted. Counting overlapping
# intervals in SQL avoids retaining a week's task payloads in the 512 MiB worker.
_CAPACITY = f"""
WITH jobs AS (
 SELECT id, provider || ':' || regexp_replace(model_id, '-[0-9]{{6}}$', '') AS vendor_model,
        submitted_at,
        coalesce(finished_at, least(:now, submitted_at + interval '48 hours')) AS ended_at
 FROM creative_vendor_task_timings
 WHERE submitted_at >= :now - interval '9 days' AND submitted_at <= :now AND {_SCOPE}
), events AS (
 SELECT vendor_model, submitted_at AS at, 1 AS delta FROM jobs
 UNION ALL
 SELECT vendor_model, ended_at AS at, -1 AS delta FROM jobs
), levels AS (
 SELECT vendor_model, at,
        sum(sum(delta)) OVER (PARTITION BY vendor_model ORDER BY at) AS simultaneous
 FROM events GROUP BY vendor_model, at
), samples AS (
 SELECT j.vendor_model, (j.submitted_at AT TIME ZONE 'UTC')::date AS day,
        greatest(1, l.simultaneous) AS simultaneous
 FROM jobs j JOIN levels l ON l.vendor_model = j.vendor_model AND l.at = j.submitted_at
 WHERE j.submitted_at >= :now - interval '7 days'
)
SELECT vendor_model, day, percentile_cont(0.95) WITHIN GROUP (ORDER BY simultaneous) AS p95
FROM samples GROUP BY vendor_model, day ORDER BY day, vendor_model
"""
_SLOTS = """
SELECT vendor_model, count(*) AS provisioned,
       count(*) FILTER (WHERE holder_job_id IS NOT NULL) AS occupied,
       count(*) FILTER (WHERE holder_job_id IS NOT NULL AND lease_until < :now) AS expired
FROM vendor_slots GROUP BY vendor_model ORDER BY vendor_model
"""


def read_snapshot(
    *, now: datetime, tenant_ids: Sequence[UUID] | None = None, include_slots: bool = False
) -> Snapshot:
    from qualify_shared.db.admin import admin_session  # noqa: PLC0415

    params = {"now": now, "all_tenants": tenant_ids is None, "tenant_ids": list(tenant_ids or ())}
    with admin_session() as session:
        counts = tuple(dict(r) for r in session.execute(text(_COUNTS), params).mappings())
        waits = tuple(dict(r) for r in session.execute(text(_WAITS), params).mappings())
        top = tuple(dict(r) for r in session.execute(text(_TOP), params).mappings())
        urgent = session.execute(text(_URGENT), params).mappings().one()
        capacity = tuple(dict(r) for r in session.execute(text(_CAPACITY), params).mappings())
    slots: tuple[Mapping[str, Any], ...] = ()
    if include_slots:
        from qualify_shared.db.creative_worker import creative_worker_session  # noqa: PLC0415

        with creative_worker_session() as session:
            slots = tuple(dict(r) for r in session.execute(text(_SLOTS), params).mappings())
    return Snapshot(
        counts, waits, top, urgent["expired_leases"], urgent["urgent_finals"], capacity, slots
    )


def scope_key(tenant_ids: Sequence[UUID] | None) -> str:
    return "all" if tenant_ids is None else ",".join(sorted(str(t) for t in tenant_ids))


class QueueMonitor:
    def __init__(
        self,
        store: RedisStore,
        notifier: SupportNotifier,
        *,
        scope: str = "all",
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store = store
        self.notifier = notifier
        self.scope = scope
        self.clock = clock

    def _key(self, suffix: str) -> str:
        return f"{PREFIX}{self.scope}:{suffix}"

    def beat(self) -> None:
        # Retain the last beat after a process dies, rather than expiring the evidence.
        self.store.set(self._key("beat"), str(self.clock().timestamp()))

    def quota_exceeded(self) -> None:
        self.store.set(self._key("quota"), str(self.clock().timestamp()))

    def publish(self, name: str, alert: QueueAlert | None) -> None:
        key = self._key(f"incident:{name}")
        if alert is None:
            self.store.delete(key)
            return
        delivery = f"{key}:delivery"
        if self.store.get(key) or not self.store.set(delivery, "pending", nx=True, ex=60):
            return
        try:
            # Recheck after taking the delivery lease: another observer may have just sent.
            if not self.store.get(key) and self.notifier.notify(alert):  # type: ignore[arg-type]
                self.store.set(key, "active")
        finally:
            self.store.delete(delivery)

    def check(self, snapshot: Snapshot) -> None:
        active = snapshot.conditions()
        raw = self.store.get(self._key("quota"))
        if raw and self.clock().timestamp() - float(raw) <= QUOTA_QUIET_SECONDS:
            active["quota"] = QueueAlert("quota", "BytePlus respondió HTTP 429 QuotaExceeded.")
        for name in ("wait", "capacity", "deadline", "quota"):
            self.publish(name, active.get(name))

    def watchdog(self) -> None:
        now = self.clock().timestamp()
        raw = self.store.get(self._key("beat"))
        if raw is None:
            # Allow a newly deployed service five minutes to leave its first beat.
            self.store.set(self._key("watch_started"), str(now), nx=True)
            raw = self.store.get(self._key("watch_started"))
        stale = raw is not None and now - float(raw) > STALE_SECONDS
        self.publish(
            "heartbeat",
            QueueAlert("heartbeat", "creative-worker sin latido >5 min.") if stale else None,
        )


def production_monitor(tenant_ids: Sequence[UUID] | None = None) -> QueueMonitor:
    import redis  # noqa: PLC0415

    from qualify_api.config import redis_url  # noqa: PLC0415

    return QueueMonitor(
        redis.Redis.from_url(
            redis_url(), decode_responses=True, socket_timeout=2, socket_connect_timeout=2
        ),
        production_support_notifier(),
        scope=scope_key(tenant_ids),
    )


def watchdog_chore(tenant_ids: Sequence[UUID] | None = None) -> Callable[[], None]:
    monitor = production_monitor(tenant_ids)

    def check() -> None:
        try:
            monitor.watchdog()
        except Exception:
            logger.warning("creative.queue.watchdog_unavailable", exc_info=True)

    return check

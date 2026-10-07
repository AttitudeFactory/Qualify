"""Calendar worker heartbeat: how the Planificador knows a worker is really running.

The Planificador used to ask only the worker embedded in ITS OWN process
(`embedded.calendar_worker().status()`). In production that worker is forced off and
publishing runs in the separate `calendar-worker` container — so the screen said «El
servicio de publicación automática no está disponible» while the service was working.

Now every worker — embedded or CLI — records one beat per tick in Redis (shared by the app
and the worker containers), and the Planificador reads them back:

- one hash, `qualify:calendar-worker:heartbeats`, one field per worker process, whose value
  is the worker's scope (`all` or tenant ids), interval, last tick time and last tick error;
- a beat is FRESH while it is younger than `STALE_AFTER_INTERVALS` intervals plus a grace,
  so one slow tick (a Meta upload) does not flip the screen, a dead worker does within
  minutes;
- a worker covers a tenant when its beat is fresh, its last tick did not fail as a whole
  (`TickReport.error`), and its scope is `all` or lists the tenant.

Reading or writing a beat never raises: a Redis hiccup must not break a tick nor the
Planificador, it only makes the screen fall back to «no disponible».
"""

from __future__ import annotations

import json
import logging
import os
import socket
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

logger = logging.getLogger("qualify_api.planner.heartbeat")

HEARTBEATS_KEY = "qualify:calendar-worker:heartbeats"
ALL_TENANTS = "all"
STALE_AFTER_INTERVALS = 3
GRACE_SECONDS = 30


@dataclass(frozen=True)
class Heartbeat:
    worker_id: str
    all_tenants: bool
    tenant_ids: tuple[UUID, ...]
    interval: int
    at: datetime
    error: str = ""

    def fresh(self, now: datetime) -> bool:
        limit = timedelta(seconds=self.interval * STALE_AFTER_INTERVALS + GRACE_SECONDS)
        return now - self.at <= limit

    def covers(self, tenant_id: UUID, now: datetime) -> bool:
        return (
            self.fresh(now)
            and not self.error
            and (self.all_tenants or tenant_id in self.tenant_ids)
        )

    def to_json(self) -> str:
        return json.dumps(
            {
                "scope": ALL_TENANTS if self.all_tenants else [str(t) for t in self.tenant_ids],
                "interval": self.interval,
                "at": self.at.isoformat(),
                "error": self.error,
            }
        )

    @classmethod
    def from_json(cls, worker_id: str, raw: str) -> Heartbeat | None:
        try:
            data = json.loads(raw)
            scope = data["scope"]
            at = datetime.fromisoformat(data["at"])
            if at.tzinfo is None:
                return None
            return cls(
                worker_id=worker_id,
                all_tenants=scope == ALL_TENANTS,
                tenant_ids=() if scope == ALL_TENANTS else tuple(UUID(t) for t in scope),
                interval=int(data["interval"]),
                at=at,
                error=str(data.get("error", "")),
            )
        except (KeyError, TypeError, ValueError):
            return None


class HeartbeatStore(Protocol):
    def write(self, beat: Heartbeat) -> None: ...

    def read_all(self) -> list[Heartbeat]: ...


class MemoryHeartbeatStore:
    """For tests and for a process with no Redis."""

    def __init__(self) -> None:
        self.beats: dict[str, Heartbeat] = {}

    def write(self, beat: Heartbeat) -> None:
        self.beats[beat.worker_id] = beat

    def read_all(self) -> list[Heartbeat]:
        return list(self.beats.values())


class RedisHeartbeatStore:
    def __init__(self, client, key: str = HEARTBEATS_KEY) -> None:  # noqa: ANN001 — redis.Redis
        self._client = client
        self._key = key

    def write(self, beat: Heartbeat) -> None:
        ttl = beat.interval * STALE_AFTER_INTERVALS + GRACE_SECONDS
        pipe = self._client.pipeline()
        pipe.hset(self._key, beat.worker_id, beat.to_json())
        pipe.expire(self._key, ttl * 10)  # the hash dies once every worker is gone
        pipe.execute()
        self._prune(beat.at)

    def read_all(self) -> list[Heartbeat]:
        raw: Mapping[str, str] = self._client.hgetall(self._key) or {}
        beats = (Heartbeat.from_json(_text(k), _text(v)) for k, v in raw.items())
        return [b for b in beats if b is not None]

    def _prune(self, now: datetime) -> None:
        """Drop the fields of workers that stopped beating long ago (old pids)."""
        stale = [b.worker_id for b in self.read_all() if not b.fresh(now - _PRUNE_MARGIN)]
        if stale:
            self._client.hdel(self._key, *stale)


_PRUNE_MARGIN = timedelta(hours=1)


def _text(value: str | bytes) -> str:
    return value.decode() if isinstance(value, bytes) else value


def worker_id() -> str:
    """One field per worker process: host (the container) and pid."""
    return f"{socket.gethostname()}:{os.getpid()}"


def record_beat(
    store: HeartbeatStore | None,
    *,
    all_tenants: bool,
    tenant_ids: Iterable[UUID],
    interval: int,
    error: str,
    now: datetime | None = None,
) -> None:
    """Write this worker's beat. Never raises — a lost beat only dims the screen."""
    if store is None:
        return
    try:
        store.write(
            Heartbeat(
                worker_id=worker_id(),
                all_tenants=all_tenants,
                tenant_ids=tuple(tenant_ids),
                interval=interval,
                at=now or datetime.now(UTC),
                error=error,
            )
        )
    except Exception:  # noqa: BLE001 — see the docstring
        logger.warning("calendar.heartbeat.write_failed", exc_info=True)


def worker_covers(
    store: HeartbeatStore | None, tenant_id: UUID, now: datetime | None = None
) -> bool:
    """Whether some live worker (any process) publishes this tenant's events."""
    if store is None:
        return False
    try:
        beats = store.read_all()
    except Exception:  # noqa: BLE001 — see the module docstring
        logger.warning("calendar.heartbeat.read_failed", exc_info=True)
        return False
    moment = now or datetime.now(UTC)
    return any(beat.covers(tenant_id, moment) for beat in beats)


_store: HeartbeatStore | None = None


def production_heartbeat_store() -> HeartbeatStore | None:
    """The shared Redis store (`QUALIFY_REDIS_URL`), built once. None if redis is not
    importable — then nothing is recorded and the screen relies on the embedded status."""
    global _store
    if _store is None:
        try:
            import redis  # noqa: PLC0415 — lazy, like publishing.composition

            from qualify_api.config import redis_url  # noqa: PLC0415

            _store = RedisHeartbeatStore(
                redis.Redis.from_url(
                    redis_url(), decode_responses=True, socket_timeout=2, socket_connect_timeout=2
                )
            )
        except Exception:  # noqa: BLE001
            logger.warning("calendar.heartbeat.no_store", exc_info=True)
            return None
    return _store

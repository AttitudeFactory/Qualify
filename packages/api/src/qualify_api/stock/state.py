"""The small Redis state the stock search needs: the 24 h result cache, the per-tenant
fixed-window quotas, and a provider's cool-down after a 429 (plan §3.5).

One `KeyValue` seam, two backends: Redis in the app, `MemoryKeyValue` in tests and as the
fallback when Redis does not answer — degraded to a per-process limit, never to none.
Counters follow `leads/rate_limit.py`: INCR, and EXPIRE only on the window's first hit.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Protocol


class KeyValue(Protocol):
    def get_json(self, key: str) -> Any | None: ...

    def set_json(self, key: str, value: Any, ttl_s: int) -> None: ...

    def incr(self, key: str, window_s: int) -> int: ...

    def ttl(self, key: str) -> int | None: ...


class RedisKeyValue:
    def __init__(self, client: Any) -> None:  # a `redis.Redis` with decode_responses=True
        self._client = client

    def get_json(self, key: str) -> Any | None:
        raw = self._client.get(key)
        return json.loads(raw) if raw else None

    def set_json(self, key: str, value: Any, ttl_s: int) -> None:
        self._client.set(key, json.dumps(value, ensure_ascii=False), ex=ttl_s)

    def incr(self, key: str, window_s: int) -> int:
        count = int(self._client.incr(key))
        if count == 1:
            self._client.expire(key, window_s)
        return count

    def ttl(self, key: str) -> int | None:
        value = int(self._client.ttl(key))
        return value if value > 0 else None


class MemoryKeyValue:
    def __init__(self, clock: Any = time.monotonic) -> None:
        self._clock = clock
        self._data: dict[str, tuple[Any, float]] = {}
        self._lock = threading.Lock()

    def _live(self, key: str) -> tuple[Any, float] | None:
        hit = self._data.get(key)
        if hit is None or hit[1] <= self._clock():
            self._data.pop(key, None)
            return None
        return hit

    def get_json(self, key: str) -> Any | None:
        with self._lock:
            hit = self._live(key)
            return json.loads(hit[0]) if hit else None

    def set_json(self, key: str, value: Any, ttl_s: int) -> None:
        with self._lock:
            self._data[key] = (json.dumps(value, ensure_ascii=False), self._clock() + ttl_s)

    def incr(self, key: str, window_s: int) -> int:
        with self._lock:
            hit = self._live(key)
            count = (hit[0] if hit else 0) + 1
            self._data[key] = (count, hit[1] if hit else self._clock() + window_s)
            return count

    def ttl(self, key: str) -> int | None:
        with self._lock:
            hit = self._live(key)
            return max(1, int(hit[1] - self._clock())) if hit else None


class FallbackKeyValue:
    """Redis first; on any Redis error the in-process store answers (and keeps
    answering for this call) — a stricter, per-process limit instead of none."""

    def __init__(self, primary: KeyValue, fallback: KeyValue | None = None) -> None:
        self._primary = primary
        self._fallback = fallback or MemoryKeyValue()

    def _call(self, name: str, *args: Any) -> Any:
        try:
            return getattr(self._primary, name)(*args)
        except Exception:  # noqa: BLE001 — Redis down must not break the selector
            return getattr(self._fallback, name)(*args)

    def get_json(self, key: str) -> Any | None:
        return self._call("get_json", key)

    def set_json(self, key: str, value: Any, ttl_s: int) -> None:
        self._call("set_json", key, value, ttl_s)

    def incr(self, key: str, window_s: int) -> int:
        return self._call("incr", key, window_s)

    def ttl(self, key: str) -> int | None:
        return self._call("ttl", key)

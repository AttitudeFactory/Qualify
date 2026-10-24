"""Fixed-window rate limiting for the public intake surface.

Redis-backed because the intake endpoint is the first surface in the codebase that
anonymous strangers can POST to. A fixed window (INCR + first-write EXPIRE) is enough
here: the cost being bounded is junk rows in `leads`, not money or platform quota, so
the sliding-window refinement buys nothing yet.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Protocol


class RateLimiter(Protocol):
    def allow(self, key: str) -> bool: ...


class RedisFixedWindowLimiter:
    def __init__(self, client, *, limit: int, window_seconds: int) -> None:  # noqa: ANN001
        self._client = client
        self._limit = limit
        self._window_seconds = window_seconds

    def allow(self, key: str) -> bool:
        full_key = f"leads:intake:{key}"
        count = self._client.incr(full_key)
        if count == 1:
            # Set the window only on the first hit; re-EXPIREing every call would let a
            # steady drip keep the window open forever without ever resetting the count.
            self._client.expire(full_key, self._window_seconds)
        return count <= self._limit


class AllowAllLimiter:
    """Test double, and the explicit spelling of 'no limit' for in-process callers."""

    def allow(self, key: str) -> bool:
        return True


class InProcessFixedWindowLimiter:
    """The same fixed window, held in this process's memory. For the Reflex app, which
    calls the interest service in-process (MARCA-5): it runs as one process in
    production, so a per-process window bounds a loop just as well, and the access
    screen never fails because Redis is away. `clock` is injectable for tests."""

    def __init__(
        self,
        *,
        limit: int,
        window_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window_seconds = window_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._windows: dict[str, tuple[float, int]] = {}

    def allow(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            started, count = self._windows.get(key, (now, 0))
            if now - started >= self._window_seconds:
                started, count = now, 0
            count += 1
            self._windows[key] = (started, count)
            if len(self._windows) > 10_000:  # bound memory: drop expired windows
                self._windows = {
                    k: v for k, v in self._windows.items() if now - v[0] < self._window_seconds
                }
            return count <= self._limit

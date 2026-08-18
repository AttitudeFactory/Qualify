"""Fixed-window rate limiting for the public intake surface.

Redis-backed because the intake endpoint is the first surface in the codebase that
anonymous strangers can POST to. A fixed window (INCR + first-write EXPIRE) is enough
here: the cost being bounded is junk rows in `leads`, not money or platform quota, so
the sliding-window refinement buys nothing yet.
"""

from __future__ import annotations

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

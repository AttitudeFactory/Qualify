"""Per-key attempt throttle for the auth screens (sliding window, in-process).

Why our own, on top of Supabase's: every GoTrue call comes from OUR server, so the
provider's per-IP limits see one IP for every operator — they cannot tell one account
being brute-forced from normal traffic, and an attacker hammering one email would
spend the budget everyone shares. Counting per email here protects the account and
keeps the shared budget for everyone else.

In-process on purpose (no Redis round trip on the login path): with N app workers the
effective limit is N × `max_attempts`, still a hard ceiling on guessing. The clock is
injectable so tests never sleep.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable

#: Above this many tracked keys, keys whose window has fully expired are dropped — a
#: flood of distinct emails cannot grow the map without bound.
_PRUNE_ABOVE = 10_000


class AttemptThrottle:
    """At most `max_attempts` noted attempts per key inside any `window_seconds`."""

    def __init__(
        self,
        max_attempts: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_attempts
        self._window = window_seconds
        self._clock = clock
        self._attempts: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def retry_after(self, key: str) -> int:
        """Whole seconds until `key` may try again; 0 means it may try now."""
        with self._lock:
            now = self._clock()
            attempts = self._live(key, now)
            if len(attempts) < self._max:
                return 0
            return max(1, math.ceil(attempts[0] + self._window - now))

    def note(self, key: str) -> None:
        """Count one attempt against `key` (a failed login, a sent reset email)."""
        with self._lock:
            now = self._clock()
            self._live(key, now).append(now)
            if len(self._attempts) > _PRUNE_ABOVE:
                for stale in [k for k, q in self._attempts.items() if not self._live(k, now)]:
                    del self._attempts[stale]

    def clear(self, key: str) -> None:
        """Forget `key`'s attempts (a successful login)."""
        with self._lock:
            self._attempts.pop(key, None)

    def _live(self, key: str, now: float) -> deque[float]:
        attempts = self._attempts.setdefault(key, deque())
        while attempts and attempts[0] <= now - self._window:
            attempts.popleft()
        return attempts


#: Failed logins per email: 5 in 15 minutes, then wait for the oldest to age out.
login_throttle = AttemptThrottle(max_attempts=5, window_seconds=15 * 60)

#: Recovery emails per address: one a minute (GoTrue enforces the same per email; this
#: answers before spending a provider call and gives the screen a precise wait).
reset_request_throttle = AttemptThrottle(max_attempts=1, window_seconds=60)

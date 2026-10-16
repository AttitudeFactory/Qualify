"""Per-key attempt throttle for the auth screens (sliding window, in-process).

Why our own, on top of Supabase's: every GoTrue call comes from OUR server, so the
provider's per-IP limits see one IP for every operator — they cannot tell one account
being brute-forced from normal traffic, and an attacker hammering one email would
spend the budget everyone shares. Counting per email here protects the account and
keeps the shared budget for everyone else.

How to use it so the ceiling is real: `try_acquire` reserves the attempt — check and
count happen under ONE lock, before the provider is called — so N parallel guesses at
the same email cannot all pass an empty check and only then be counted. On success the
caller `clear`s the key; when the attempt was not a guess at all (provider down, rate
limited upstream) it `forgive`s it, so an outage never locks an operator out.

Keys: callers pass the email **casefolded** (`throttle_key`). The login itself keeps the
email literal (criterion 6), but GoTrue treats `A@b.co` and `a@b.co` as one account, and
a per-variant counter would hand a guesser five attempts per spelling.

Trade-off, accepted on purpose: a key is an email, so anyone who knows an operator's
address can lock it for one window with deliberate wrong guesses. That blocks the
password form only — recovery (`/forgot`, `reset_request_throttle`) stays reachable, and
the window is minutes, not hours. Keying on `(email, client IP)` would reopen the gap
this exists to close (one attacker, many IPs), so we keep the plain key.

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
#: flood of distinct emails cannot grow the map without bound. Read-only lookups never
#: create an entry, so the map only holds keys that were actually counted.
_PRUNE_ABOVE = 10_000


def throttle_key(email: str) -> str:
    """The throttle's view of an email: case-insensitive, otherwise literal (the
    `+alias` stays — it IS a different account)."""
    return email.strip().casefold()


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
        """Whole seconds until `key` may try again; 0 means it may try now. Read-only:
        it never creates an entry for a key it has not counted."""
        with self._lock:
            now = self._clock()
            attempts = self._attempts.get(key)
            if attempts is None:
                return 0
            self._expire(attempts, now)
            return self._wait(attempts, now)

    def try_acquire(self, key: str) -> int:
        """Reserve one attempt for `key`: 0 when it was counted and the caller may
        proceed, otherwise the whole seconds to wait — check and count under one lock,
        so parallel callers cannot all slip through an empty window."""
        with self._lock:
            now = self._clock()
            attempts = self._live(key, now)
            wait = self._wait(attempts, now)
            if wait:
                return wait
            attempts.append(now)
            self._prune(now)
            return 0

    def note(self, key: str) -> None:
        """Count one attempt against `key` after the fact (a sent reset email)."""
        with self._lock:
            now = self._clock()
            self._live(key, now).append(now)
            self._prune(now)

    def forgive(self, key: str) -> None:
        """Un-count the most recent attempt for `key`: the call never reached a verdict
        (provider down, upstream rate limit), so it was not a guess."""
        with self._lock:
            attempts = self._attempts.get(key)
            if attempts:
                attempts.pop()
            if not attempts:
                self._attempts.pop(key, None)

    def clear(self, key: str) -> None:
        """Forget `key`'s attempts (a successful login)."""
        with self._lock:
            self._attempts.pop(key, None)

    def _wait(self, attempts: deque[float], now: float) -> int:
        if len(attempts) < self._max:
            return 0
        return max(1, math.ceil(attempts[0] + self._window - now))

    def _expire(self, attempts: deque[float], now: float) -> None:
        while attempts and attempts[0] <= now - self._window:
            attempts.popleft()

    def _live(self, key: str, now: float) -> deque[float]:
        attempts = self._attempts.setdefault(key, deque())
        self._expire(attempts, now)
        return attempts

    def _prune(self, now: float) -> None:
        if len(self._attempts) > _PRUNE_ABOVE:
            for stale in [k for k, q in self._attempts.items() if not self._live(k, now)]:
                del self._attempts[stale]


#: Failed logins per email: 5 in 15 minutes, then wait for the oldest to age out.
login_throttle = AttemptThrottle(max_attempts=5, window_seconds=15 * 60)

#: Recovery emails per address: one a minute (GoTrue enforces the same per email; this
#: answers before spending a provider call and gives the screen a precise wait).
reset_request_throttle = AttemptThrottle(max_attempts=1, window_seconds=60)

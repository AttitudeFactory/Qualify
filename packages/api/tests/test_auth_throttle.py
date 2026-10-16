"""`qualify_api.auth.throttle`: the ceiling on guessing is a reservation, not a
read-then-write — and the map only ever holds keys that were actually counted."""

from __future__ import annotations

import threading

from qualify_api.auth import AttemptThrottle, throttle_key


class _Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


def test_try_acquire_counts_and_refuses_under_one_lock() -> None:
    clock = _Clock()
    throttle = AttemptThrottle(max_attempts=3, window_seconds=60, clock=clock)
    assert [throttle.try_acquire("k") for _ in range(3)] == [0, 0, 0]
    assert throttle.try_acquire("k") == 60  # full window left: the oldest is "now"
    clock.now += 59.5
    assert throttle.try_acquire("k") == 1
    clock.now += 0.5
    assert throttle.try_acquire("k") == 0  # the oldest aged out


def test_parallel_guesses_cannot_all_pass_the_check() -> None:
    throttle = AttemptThrottle(max_attempts=5, window_seconds=600)
    results: list[int] = []
    gate = threading.Barrier(40)

    def guess() -> None:
        gate.wait()
        results.append(throttle.try_acquire("victim@x.co"))

    threads = [threading.Thread(target=guess) for _ in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(0) == 5  # exactly max_attempts got through


def test_retry_after_is_read_only() -> None:
    throttle = AttemptThrottle(max_attempts=1, window_seconds=60)
    for i in range(50):
        assert throttle.retry_after(f"probe{i}@x.co") == 0
    assert throttle._attempts == {}  # a flood of lookups leaves nothing behind
    throttle.note("a@x.co")
    assert throttle.retry_after("a@x.co") == 60


def test_forgive_gives_back_only_the_attempt_that_reached_no_verdict() -> None:
    throttle = AttemptThrottle(max_attempts=2, window_seconds=60)
    assert throttle.try_acquire("k") == 0
    assert throttle.try_acquire("k") == 0
    throttle.forgive("k")  # the provider was down for the second one
    assert throttle.try_acquire("k") == 0
    assert throttle.try_acquire("k") > 0
    throttle.forgive("k")
    throttle.forgive("k")
    throttle.forgive("k")  # over-forgiving is harmless and leaves no empty entry
    assert "k" not in throttle._attempts


def test_throttle_key_is_case_insensitive_but_keeps_the_alias() -> None:
    assert throttle_key("  Hlrd1993+Polet@Gmail.com ") == "hlrd1993+polet@gmail.com"
    assert throttle_key("a@b.co") != throttle_key("a+x@b.co")

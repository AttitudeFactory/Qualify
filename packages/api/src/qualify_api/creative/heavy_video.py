"""One heavy video job at a time in the creative worker (m-25042483).

A part join (VE-10a/VE-10b: the preview `join` and the 1080p `join_final`, on the
`creative-join` thread) and a local assembly (EF-06 `render_local_part`, on the worker's
main loop) each take a few hundred MiB. Measured together they could pass 700 MiB inside
the creative worker's 768m (`docs/armado-local-medicion.md`), so they never overlap:

- a join takes the gate and WAITS for it (`joining`): the main loop never starts a join
  while it is making a local video, so in practice it never waits;
- a local assembly only TRIES it (`assembling`): with a join in flight it raises
  `LocalAssemblyWait`, a `CheckpointError` — nothing is read, written or charged, the
  preparation is released NOT done and the next pass makes it. It waits, never fails.

The gate is per process: the creative worker runs ONE container with one process
(`deploy/docker-compose.prod.yml`), and a join's encode child is the join's own.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from uuid import UUID

from qualify_api.creative.queue_dispatch import CheckpointError

_GATE = threading.Lock()
#: Drafts whose local video waits, and the monotonic time before which the worker leaves
#: them out of its passes (`hold`, `held`). Per process, like the gate: lost on a restart,
#: which only means one early retry.
_HELD: dict[UUID, float] = {}
_HELD_LOCK = threading.Lock()


class LocalVideoWait(CheckpointError):
    """A local video is not made on this pass and waits — nothing read, written or
    charged, no notice to the owner: the preparation is released NOT done and a later
    pass makes it. Its subclasses say what it waits for; `retry_after_s` > 0 keeps the draft
    out of the worker's passes for that long (`hold`)."""

    retry_after_s: float = 0.0


class LocalAssemblyWait(LocalVideoWait):
    """A local assembly waits for the part join in flight: retried on the next pass,
    never a failed preparation."""


@contextmanager
def joining() -> Iterator[None]:
    """Hold the gate for a part join, waiting for a local assembly to finish first."""
    with _GATE:
        yield


@contextmanager
def assembling() -> Iterator[None]:
    """Hold the gate for a local assembly; `LocalAssemblyWait` at once when a join holds it."""
    if not _GATE.acquire(blocking=False):
        raise LocalAssemblyWait("a part join is running: the local video waits for the next pass")
    try:
        yield
    finally:
        _GATE.release()


def hold(draft_id: UUID, seconds: float, *, clock: Callable[[], float] = time.monotonic) -> None:
    """Leave `draft_id` out of the worker's passes for `seconds` (a waiting local video)."""
    if seconds <= 0:
        return
    with _HELD_LOCK:
        _HELD[draft_id] = clock() + seconds


def held(*, clock: Callable[[], float] = time.monotonic) -> list[UUID]:
    """The drafts still held now; the ones whose time came are forgotten."""
    now = clock()
    with _HELD_LOCK:
        for draft_id in [d for d, until in _HELD.items() if until <= now]:
            del _HELD[draft_id]
        return list(_HELD)


def release_held() -> None:
    """Forget every hold (tests)."""
    with _HELD_LOCK:
        _HELD.clear()


def busy() -> bool:
    """Whether a heavy video job holds the gate now (tests, logs)."""
    return _GATE.locked()


__all__ = [
    "LocalAssemblyWait",
    "LocalVideoWait",
    "assembling",
    "busy",
    "held",
    "hold",
    "joining",
    "release_held",
]

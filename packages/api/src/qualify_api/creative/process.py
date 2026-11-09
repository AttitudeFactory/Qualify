"""Which process this is: the creative worker, or anything else (m-24921059 VE-04d).

Work that must never run inside the Reflex process (a ~295 MiB video cut, while production
Reflex is one 512 MiB process) checks `is_worker_process()`. The marker is set by the
creative worker's own entry point (`creative/worker/__main__.py`) at startup — never by
configuration: every app container reads the same `.env.prod`, so an environment switch
such as `QUALIFY_CREATIVE_DISPATCHER` is equally visible to Reflex and cannot tell them apart.
"""

from __future__ import annotations

_marked = False


def mark_worker_process() -> None:
    """Called once by the creative worker's `main` before it takes any job."""
    global _marked
    _marked = True


def unmark_worker_process() -> None:
    """For tests only: back to «not the worker»."""
    global _marked
    _marked = False


def is_worker_process() -> bool:
    return _marked


__all__ = ["is_worker_process", "mark_worker_process", "unmark_worker_process"]

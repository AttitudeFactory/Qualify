"""Give a heavy video step's freed memory back to the OS before the next one (m-25042483).

The local assembly (EF-06) runs `prepare`, the speed step and the compose one after the
other in the creative worker's process (768m). Each frees its decoder, encoder and frames
when it ends, but glibc keeps the freed heap pages: measured in the EF-15 harness, the
compose of a 4K stretch with 3 texts started on top of ~275 MiB the earlier steps no
longer used, and peaked at 501 MiB RSS. `release_memory` collects Python's cycles (PyAV
frames held by them) and asks glibc to hand the free pages back (`malloc_trim(0)`), so
the next step starts from what is really in use. Linux only (glibc); elsewhere it only
collects. Never raises: memory hygiene must never fail a video.
"""

from __future__ import annotations

import ctypes
import gc
import sys
from typing import Any


def release_memory(*, platform: str = sys.platform, libc: Any = None) -> bool:
    """Collect, then `malloc_trim(0)` on Linux. True when glibc gave pages back."""
    gc.collect()
    if not platform.startswith("linux"):
        return False
    try:
        lib = libc if libc is not None else ctypes.CDLL("libc.so.6")
        return bool(lib.malloc_trim(0))
    except (OSError, AttributeError):  # not glibc (musl): nothing to trim
        return False


__all__ = ["release_memory"]

"""A sign of life on a side thread while a long, silent step runs (m-25103284,
m-25119832): the reaper (`reap_stale_drafts`, 20 min) and the final's stale check judge a
draft dead by how long its stamp has not moved, and a single encode of a minute of
1080×1920 can outlast that without returning once. Its own module so `service` and
`video_pipeline.local` share it without importing each other."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

logger = logging.getLogger(__name__)


@contextmanager
def beating(
    beat: Callable[[], None], every_s: float, *, name: str = "creative-beat"
) -> Iterator[None]:
    """Call `beat` every `every_s` seconds on a daemon thread while the block runs; it
    stops (and is waited for) when the block ends — normally or by an exception, which
    goes up unchanged — so no beat lands after it. A beat that raises is logged and the
    next one is still tried: a sign of life is never a reason to stop the work."""
    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(every_s):
            try:
                beat()
            except Exception as exc:  # noqa: BLE001 — a sign of life, never the work
                logger.warning("creative.heartbeat.beat_failed error_type=%s", type(exc).__name__)

    thread = threading.Thread(target=loop, name=name, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(max(every_s, 1.0) + 5.0)

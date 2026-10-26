"""One bounded, best-effort worker chore; durable work remains in its outbox."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)


class BackgroundChore:
    """Schedule at most one live task, with no pending-submission queue.

    Daemon lifetime is deliberate: deployment must not wait for a whole mail batch.
    A process interrupted during sending resumes through the durable mail outbox's
    lease and provider idempotency key, not by retaining this thread in memory.
    """

    def __init__(self, task: Callable[[], object], stop: threading.Event) -> None:
        self._task = task
        self._stop = stop
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def schedule(self) -> bool:
        with self._lock:
            if self._stop.is_set() or (self._thread is not None and self._thread.is_alive()):
                return False
            thread = threading.Thread(target=self._run, name="creative-morning-mail", daemon=True)
            self._thread = thread
            try:
                thread.start()
            except Exception as exc:
                logger.error("creative.worker.mail_start_failed error_type=%s", type(exc).__name__)
                return False
            return True

    def _run(self) -> None:
        if self._stop.is_set():
            return
        try:
            self._task()
        except Exception as exc:
            # Payloads and recipient addresses must never enter this scheduler's log.
            logger.error("creative.worker.morning_mail_failed error_type=%s", type(exc).__name__)

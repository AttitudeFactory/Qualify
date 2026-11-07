"""Keep a live session's saved state on disk, so a worker restart does not log it out
(m-24946266).

Production runs Reflex's disk state manager (`deploy/docker-compose.prod.yml`, service
`reflex`): each substate of a tab is pickled to its own file under `.states/`, written
only when that substate changes. Every couple of seconds the manager deletes any file
older than `token_expiration` (1 h) by its mtime — whether or not the tab is still in
use. The login (`AuthState`) is written once, when the owner signs in, and rarely again,
so one hour later it exists only in memory. When the worker then dies (the 2026-11-03
OOM kill while reading a big logo) or a deploy restarts it, the tab reconnects to a
state with no login and lands on `/brand/start`.

The fix keeps the policy (a tab idle for an hour still expires) and protects only the
tabs the manager itself counts as live: before each purge, the files of every token
touched within `token_expiration` get their mtime refreshed once they are half that
old. Nothing is rewritten, nothing about the session changes, and a restart finds the
files of every live tab.

Installed once from `Qualify.py`, before the app builds its state manager. The patch is
on a private Reflex method: `install()` refuses (and logs) when the pinned Reflex does
not have the shape it expects, and `test_state_keepalive.py` fails on such an upgrade.

Reflex runs the purge in an executor thread (`run_in_thread` → `run_in_executor`, which
does not copy contextvars), where its `RegistrationContext` is unset and
`BaseState.get_substates()` raises `LookupError` (m-24973694). The state tree is therefore
read from the registration context captured at `install()`, the one the app registers
its states in, whenever the running thread has none.
"""

from __future__ import annotations

import functools
import logging
import os
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from reflex.istate.manager.disk import StateManagerDisk
from reflex.istate.manager.token import BaseStateToken
from reflex_base.registry import RegistrationContext

logger = logging.getLogger(__name__)

#: How often the refresh walks the live tokens; the purge itself runs every ~2 s.
REFRESH_EVERY_SECONDS = 60.0

#: Longest exception message kept in the log line.
_MESSAGE_LIMIT = 200
#: Distinct failure causes remembered, so a cause is logged once (bounded on purpose).
_REPORTED_LIMIT = 32

_INSTALLED_FLAG = "_qualify_keepalive"
_LAST_REFRESH_ATTR = "_qualify_keepalive_at"

#: The app's registration context, captured at `install()` for threads that have none.
_captured_registry: RegistrationContext | None = None
#: Failure causes already logged («Type: message»).
_reported: set[str] = set()


def _registry() -> RegistrationContext:
    """The registration context of this thread, else the one captured at `install()`."""
    try:
        return RegistrationContext.get()
    except LookupError:
        if _captured_registry is None:
            raise LookupError(
                "no Reflex registration context in this thread and none captured at install"
            ) from None
        return _captured_registry


@functools.cache
def _state_tree(root: type) -> tuple[type, ...]:
    """Every state class under `root` (itself included), each once."""
    registry = _registry()
    seen: list[type] = []
    pending = [root]
    while pending:
        cls = pending.pop()
        if cls in seen:
            continue
        seen.append(cls)
        pending.extend(registry.get_substates(cls))
    return tuple(seen)


def _report_failure(exc: Exception) -> None:
    """Log a failed refresh once per distinct cause, with its message (paths and class
    names only: nothing here touches credentials)."""
    cause = f"{type(exc).__name__}: {str(exc)[:_MESSAGE_LIMIT]}"
    if cause in _reported:
        logger.debug("state keepalive: refresh failed again: %s", cause)
        return
    if len(_reported) < _REPORTED_LIMIT:
        _reported.add(cause)
    logger.warning("state keepalive: refresh failed: %s", cause)


def live_state_paths(manager: StateManagerDisk, now: float) -> list[Path]:
    """The state files of every token the manager touched within `token_expiration`."""
    paths: list[Path] = []
    for last_touched, token in list(manager._token_last_touched.values()):
        if now - last_touched > manager.token_expiration:
            continue
        if isinstance(token, BaseStateToken):
            for cls in _state_tree(token.cls.get_root_state()):
                paths.append(manager.token_path(token.with_cls(cls)))
        else:
            paths.append(manager.token_path(token))
    return paths


def refresh(paths: Iterable[Path], now: float, older_than: float) -> int:
    """Set the mtime of each existing file older than `older_than` seconds to `now`."""
    refreshed = 0
    for path in paths:
        try:
            if now - path.stat().st_mtime > older_than:
                os.utime(path, (now, now))
                refreshed += 1
        except FileNotFoundError:
            continue  # a substate never written (never changed) has no file
    return refreshed


def keep_live_states(manager: StateManagerDisk, now: float | None = None) -> int:
    """One refresh pass, at most every `REFRESH_EVERY_SECONDS`. Never raises: the
    purge that follows must run whatever happens here."""
    now = time.time() if now is None else now
    if now - getattr(manager, _LAST_REFRESH_ATTR, 0.0) < REFRESH_EVERY_SECONDS:
        return 0
    try:
        paths = live_state_paths(manager, now)
        if paths:  # the boot-time purge (no tab yet) does not start the throttle
            setattr(manager, _LAST_REFRESH_ATTR, now)
        return refresh(paths, now, manager.token_expiration / 2)
    except Exception as exc:  # noqa: BLE001 — a failed refresh must not stop the purge
        # A failure waits the same interval before the next try, not every purge (~2 s).
        setattr(manager, _LAST_REFRESH_ATTR, now)
        _report_failure(exc)
        return 0


def install() -> bool:
    """Wrap `StateManagerDisk._purge_expired_states` so live tabs are refreshed first.
    Idempotent; False (and a warning) when this Reflex lacks what the patch relies on.
    Also captures the app's registration context for the purge's executor thread."""
    global _captured_registry
    _captured_registry = RegistrationContext.ensure_context()
    _state_tree.cache_clear()  # a hot reload re-registers the state classes
    original: Callable[[Any], None] | None = getattr(
        StateManagerDisk, "_purge_expired_states", None
    )
    if original is None:
        logger.warning("state keepalive: Reflex has no _purge_expired_states; not installed")
        return False
    if getattr(original, _INSTALLED_FLAG, False):
        return True

    @functools.wraps(original)
    def _purge_expired_states(self: StateManagerDisk) -> None:
        if hasattr(self, "_token_last_touched"):
            keep_live_states(self)
        original(self)

    setattr(_purge_expired_states, _INSTALLED_FLAG, True)
    StateManagerDisk._purge_expired_states = _purge_expired_states  # type: ignore[method-assign]
    return True

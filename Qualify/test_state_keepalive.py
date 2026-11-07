"""m-24946266: a live tab's saved state survives the disk manager's purge, so a worker
restart (the 2026-11-03 OOM kill, a deploy) does not log the owner out; an idle tab
still expires as before."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
import reflex as rx
from reflex.istate.manager.disk import StateManagerDisk
from reflex.istate.manager.token import BaseStateToken
from reflex.utils import prerequisites
from reflex.utils.misc import run_in_thread

from . import state_keepalive as keepalive
from .auth_state import AuthState

HOUR = 60 * 60


def _tok(ident: str) -> BaseStateToken:
    return BaseStateToken(ident=ident, cls=rx.State)


@pytest.fixture
def manager(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> StateManagerDisk:
    monkeypatch.setattr(prerequisites, "get_states_dir", lambda: tmp_path)
    return StateManagerDisk(token_expiration=HOUR)


def _auth_file(manager: StateManagerDisk, ident: str, age: float, now: float) -> Path:
    """The pickled AuthState of tab `ident`, last written `age` seconds before `now`."""
    token = BaseStateToken(ident=ident, cls=AuthState)
    path = manager.token_path(token)
    path.write_bytes(b"login")
    os.utime(path, (now - age, now - age))
    return path


def test_the_patch_is_installed_on_the_pinned_reflex() -> None:
    """Fails on a Reflex upgrade that renames what the patch relies on."""
    assert keepalive.install() is True
    assert getattr(StateManagerDisk._purge_expired_states, keepalive._INSTALLED_FLAG)
    assert keepalive.install() is True  # idempotent: never wrapped twice
    wrapped = StateManagerDisk._purge_expired_states.__wrapped__
    assert not getattr(wrapped, keepalive._INSTALLED_FLAG, False)
    for name in ("_token_last_touched", "token_expiration", "token_path"):
        assert name in StateManagerDisk.__dataclass_fields__ or hasattr(StateManagerDisk, name)


def test_a_login_written_long_ago_survives_the_purge_while_its_tab_is_live(
    manager: StateManagerDisk,
) -> None:
    """The bug: AuthState is written at login and rarely again, so the purge deleted it
    an hour later and the next restart found no login."""
    keepalive.install()
    now = time.time()
    live = _auth_file(manager, "live-tab", age=2 * HOUR, now=now)
    idle = _auth_file(manager, "idle-tab", age=2 * HOUR, now=now)
    manager._token_last_touched["live-tab"] = (now - 5, _tok("live-tab"))
    manager._token_last_touched["idle-tab"] = (now - 2 * HOUR, _tok("idle-tab"))

    manager._purge_expired_states()

    assert live.exists(), "a live tab lost its login"
    assert now - live.stat().st_mtime < 60
    assert not idle.exists(), "an idle tab must still expire"


def test_after_a_restart_the_live_tab_still_finds_its_login(
    manager: StateManagerDisk, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    keepalive.install()
    now = time.time()
    path = _auth_file(manager, "tab", age=2 * HOUR, now=now)
    manager._token_last_touched["tab"] = (now, _tok("tab"))
    manager._purge_expired_states()
    # the worker dies; a new one builds its manager and purges on start
    restarted = StateManagerDisk(token_expiration=HOUR)
    assert restarted.token_path(BaseStateToken(ident="tab", cls=AuthState)) == path
    assert path.exists()


def test_a_recent_file_is_left_alone_and_the_walk_is_throttled(
    manager: StateManagerDisk,
) -> None:
    now = time.time()
    path = _auth_file(manager, "tab", age=60, now=now)
    manager._token_last_touched["tab"] = (now, _tok("tab"))
    assert keepalive.keep_live_states(manager, now) == 0
    assert abs(path.stat().st_mtime - (now - 60)) < 1
    os.utime(path, (now - 2 * HOUR, now - 2 * HOUR))
    # within REFRESH_EVERY_SECONDS of the last walk: nothing happens
    assert keepalive.keep_live_states(manager, now + 1) == 0
    assert keepalive.keep_live_states(manager, now + keepalive.REFRESH_EVERY_SECONDS + 1) == 1


def test_a_failing_refresh_never_stops_the_purge(
    manager: StateManagerDisk, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: object) -> list[Path]:
        raise RuntimeError("registry changed")

    monkeypatch.setattr(keepalive, "live_state_paths", boom)
    assert keepalive.keep_live_states(manager, time.time()) == 0


def test_the_whole_state_tree_of_a_tab_is_covered() -> None:
    tree = keepalive._state_tree(rx.State)
    assert rx.State in tree and AuthState in tree
    assert len(tree) == len(set(tree))


def test_the_purge_refreshes_live_tabs_from_reflex_s_executor_thread(
    manager: StateManagerDisk,
) -> None:
    """m-24973694, the production bug: Reflex runs the purge through `run_in_thread`
    (`run_in_executor`, no contextvars), where `RegistrationContext.get()` raises
    LookupError; the keepalive failed every ~2 s and never refreshed a file."""
    keepalive.install()
    keepalive._state_tree.cache_clear()  # a warm cache from the main thread hides the bug
    now = time.time()
    live = _auth_file(manager, "live-tab", age=2 * HOUR, now=now)
    manager._token_last_touched["live-tab"] = (now - 5, _tok("live-tab"))

    asyncio.run(run_in_thread(manager._purge_expired_states))

    assert live.exists(), "a live tab lost its login when the purge ran off the main thread"
    assert now - live.stat().st_mtime < 60
    assert getattr(manager, keepalive._LAST_REFRESH_ATTR) >= now


def test_a_thread_without_any_registration_context_says_so(
    manager: StateManagerDisk,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    keepalive._state_tree.cache_clear()
    monkeypatch.setattr(keepalive, "_captured_registry", None)
    monkeypatch.setattr(keepalive, "_reported", set())
    now = time.time()
    manager._token_last_touched["tab"] = (now, _tok("tab"))

    def walk() -> int:
        return keepalive.keep_live_states(manager, now)

    with caplog.at_level(logging.WARNING, logger=keepalive.__name__):
        assert threading_result(walk) == 0
    assert "LookupError: no Reflex registration context" in caplog.text
    keepalive._state_tree.cache_clear()


def test_a_failure_is_logged_once_per_cause_and_waits_the_refresh_interval(
    manager: StateManagerDisk,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    errors = iter([LookupError("same"), LookupError("same"), KeyError("other")])

    def boom(*_args: object) -> list[Path]:
        raise next(errors)

    monkeypatch.setattr(keepalive, "live_state_paths", boom)
    monkeypatch.setattr(keepalive, "_reported", set())
    now = time.time()
    step = keepalive.REFRESH_EVERY_SECONDS + 1
    with caplog.at_level(logging.WARNING, logger=keepalive.__name__):
        assert keepalive.keep_live_states(manager, now) == 0
        # the next purge (~2 s later) does not retry, so it cannot log again
        assert keepalive.keep_live_states(manager, now + 2) == 0
        assert keepalive.keep_live_states(manager, now + step) == 0
        assert keepalive.keep_live_states(manager, now + 2 * step) == 0
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings == [
        "state keepalive: refresh failed: LookupError: same",
        "state keepalive: refresh failed: KeyError: 'other'",
    ]


def threading_result(fn: Callable[[], int]) -> int:
    """Run `fn` in a fresh thread, which starts with no contextvars set."""
    result: list[int] = []
    worker = threading.Thread(target=lambda: result.append(fn()))
    worker.start()
    worker.join()
    return result[0]

"""Tests for the two concurrency/memory fixes in `publishing_state.py` (found in audit,
2026-08-11): the server-side double-submit guard in `publish()`, and `_pending_bytes`
being released on every failure branch of `publish_background`, not only the success one.

**Why this file needs pytest and cannot run under the plain `python -m` harness** (unlike
`test_publishing_ui.py`/`test_connections.py`): Reflex forbids constructing a `State`
subclass directly (`ReflexRuntimeError`) UNLESS `is_testing_env()` is true, which checks
for `PYTEST_CURRENT_TEST` in the environment — a variable pytest sets, not something a
bare interpreter has. So `PublishState()` below only works inside a pytest run.

**Why this file does NOT exercise `publish_background`/`poll_attempt` end to end:** both
call `self.get_state(ConnectionsState)`, which needs a live `EventContext` (the running
app's state manager) — verified empirically while writing this file: calling it on a
standalone-constructed state raises `LookupError` from the context var, with no
lightweight way to fake it. That is a pre-existing gap (no test anywhere in this repo
drives a `rx.State` through its full event-dispatch machinery), not something these two
fixes could plausibly have introduced or could reasonably close here. Instead:
- The double-submit guard lives entirely in `publish()`, which touches no such context —
  it is exercised directly and completely, including calling the real (not mocked)
  `publish()` method on a real (not mocked) `PublishState` instance.
- The bytes-release fix is exercised two ways: directly against the new
  `_fail_pending_attempt` helper (real behavior, no mocking), and via a source-inspection
  test pinning that all 5 exception branches plus the pre-staging `tenant_id is None`
  branch in `publish_background` route through it — so a future edit that reintroduces an
  inline `self.phase = "failure"` bypassing the helper (and therefore leaking
  `_pending_bytes` again) fails this suite.
"""

from __future__ import annotations

import inspect

import pytest

from .publishing_state import PublishState


class _FakeUpload:
    """The two attributes `PublishState.publish` actually reads off an `rx.UploadFile`."""

    def __init__(self, data: bytes = b"x", content_type: str = "video/mp4") -> None:
        self._data = data
        self.content_type = content_type

    async def read(self) -> bytes:
        return self._data


# --------------------------------------------------------------------------------------
# Fix 1 — server-side double-submit guard in `publish()`
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_rejects_a_resubmit_while_a_previous_attempt_is_in_flight() -> None:
    """The exact scenario the audit flagged: two rapid submissions must not both reach
    `publish_background` — only the guard in `publish()` (not the client-side `disabled=`
    prop, which this test never touches) can stop that, since `publish_background` events
    are NOT ordered relative to each other (Reflex only serializes foreground events)."""
    state = PublishState()
    state.selected_connection_id = "c-1"

    first = await state.publish([_FakeUpload(data=b"first-video")])
    assert first is not None, "the first submission must be accepted"
    assert state.phase == "staging_and_starting"
    key_after_first = state._idempotency_key
    assert key_after_first != ""

    second = await state.publish([_FakeUpload(data=b"second-video")])

    assert second is None, "a resubmit while phase != idle/success/failure must be a no-op"
    assert state.phase == "staging_and_starting"  # untouched by the rejected resubmit
    assert state._idempotency_key == key_after_first  # NOT regenerated
    assert state._pending_bytes == b"first-video"  # NOT overwritten by the second upload


@pytest.mark.asyncio
async def test_publish_rejects_a_resubmit_during_polling_too() -> None:
    """The guard checks `phase not in (idle, success, failure)` — `"polling"` (reached
    after staging succeeds, well past `publish()`) must be rejected exactly like
    `"staging_and_starting"` is."""
    state = PublishState()
    state.selected_connection_id = "c-1"
    state.phase = "polling"
    state._idempotency_key = "already-in-flight"

    result = await state.publish([_FakeUpload()])

    assert result is None
    assert state.phase == "polling"
    assert state._idempotency_key == "already-in-flight"
    assert state._pending_bytes == b""  # never touched


@pytest.mark.asyncio
@pytest.mark.parametrize("resting_phase", ["idle", "success", "failure"])
async def test_publish_accepts_a_new_attempt_once_the_previous_one_has_settled(
    resting_phase: str,
) -> None:
    """The guard must not be so broad it blocks a legitimate NEW publish after the
    previous one finished, in any of its three resting phases."""
    state = PublishState()
    state.selected_connection_id = "c-1"
    state.phase = resting_phase

    result = await state.publish([_FakeUpload(data=b"new-video")])

    assert result is not None
    assert state.phase == "staging_and_starting"
    assert state._pending_bytes == b"new-video"


# --------------------------------------------------------------------------------------
# Fix 2 — `_pending_bytes` released on every failure branch, not just the success one
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fail_pending_attempt_clears_the_buffer_and_records_the_error() -> None:
    state = PublishState()
    state.phase = "staging_and_starting"
    state._idempotency_key = "k-1"
    state._pending_bytes = b"a-whole-reel-worth-of-bytes"

    await state._fail_pending_attempt("k-1", "algo salió mal")

    assert state.phase == "failure"
    assert state.error == "algo salió mal"
    assert state._pending_bytes == b""  # the fix: released, not left buffered


@pytest.mark.asyncio
async def test_fail_pending_attempt_ignores_a_superseded_key() -> None:
    """A stale background task's failure must not clobber a NEWER attempt's in-progress
    state — and must not free bytes that belong to that newer, still-live attempt."""
    state = PublishState()
    state.phase = "polling"  # the newer attempt has already moved past staging
    state._idempotency_key = "k-2"  # the newer attempt's key
    state._pending_bytes = b"newer-attempts-bytes"
    state.error = ""

    await state._fail_pending_attempt("k-1-stale", "this must not land")

    assert state.phase == "polling"  # untouched
    assert state.error == ""  # untouched
    assert state._pending_bytes == b"newer-attempts-bytes"  # NOT freed


def test_every_failure_branch_in_publish_background_uses_the_shared_release_helper() -> None:
    """Pins the fix structurally: the pre-staging `tenant_id is None` branch plus the 5
    exception branches (`R2ConfigurationError`, `(ObjectSizeExceeded, UnsizedStream)`,
    `(TenantPrefixViolation, ValueError)`, `UnknownConnection`, `Exception`) must all
    route through `_fail_pending_attempt` — that is what makes the release unconditional.
    A future edit that reintroduces an inline `self.phase = "failure"` in one of them
    would silently reopen the bytes-retention bug this test guards against.
    """
    # `PublishState.publish_background` (class-level access) is an `EventHandler`
    # wrapper, not the plain function — `.fn` is the underlying coroutine function
    # `inspect.getsource` needs.
    source = inspect.getsource(PublishState.publish_background.fn)
    assert source.count("_fail_pending_attempt(idempotency_key,") == 6, (
        "expected exactly 6 call sites: tenant_id is None + 5 exception branches"
    )
    # No branch may set failure state directly anymore — that was the leaky pattern.
    assert 'self.phase = "failure"' not in source.replace(
        'self.phase = "success" if attempt.status == "published" else "failure"', ""
    )

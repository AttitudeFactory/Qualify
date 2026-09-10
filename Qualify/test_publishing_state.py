"""Tests for the two concurrency/memory fixes in `publishing_state.py` (found in audit,
2026-08-11): the server-side double-submit guard in `publish()`, and `_pending_files`
being released on every failure branch of `publish_background`, not only the success one.

QUA-99 (6/6): `_pending_bytes: bytes` (one buffer) became `_pending_files:
list[_PendingFile]` (QUA-99, 6/6) — every test below that used to poke `_pending_bytes`
directly now uses `_pending_files`, same fixes, same guarantees, just a list instead of
a single buffer. This file also gains coverage for the two genuinely NEW behaviours
`publish()` picked up: buffering 2-10 files in order, and rejecting more than 10 before
reading a single one of them.

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
import reflex as rx

from .publishing_state import (
    _MAX_ITEMS,
    _TOO_MANY,
    PublishState,
    _failure_toast,
    _PendingFile,
    _success_toast,
)


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
    (buffered,) = state._pending_files
    assert buffered.data == b"first-video"  # NOT overwritten by the second upload


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
    assert state._pending_files == []  # never touched


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
    (buffered,) = state._pending_files
    assert buffered.data == b"new-video"


# --------------------------------------------------------------------------------------
# QUA-99 (6/6) — publish() buffers 2-10 files in order, rejects more than 10 up front
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_buffers_two_files_preserving_order() -> None:
    """Order here becomes carousel `position` downstream (`PublishService.start_many`,
    QUA-99 4/6) — must never be re-sorted or reversed."""
    state = PublishState()
    state.selected_connection_id = "c-1"

    result = await state.publish(
        [
            _FakeUpload(data=b"first", content_type="video/mp4"),
            _FakeUpload(data=b"second", content_type="video/quicktime"),
        ]
    )

    assert result is not None
    assert state.phase == "staging_and_starting"
    assert [f.data for f in state._pending_files] == [b"first", b"second"]
    assert [f.content_type for f in state._pending_files] == ["video/mp4", "video/quicktime"]


@pytest.mark.asyncio
async def test_publish_buffers_exactly_ten_files() -> None:
    state = PublishState()
    state.selected_connection_id = "c-1"

    result = await state.publish([_FakeUpload(data=f"v{i}".encode()) for i in range(_MAX_ITEMS)])

    assert result is not None
    assert len(state._pending_files) == _MAX_ITEMS


@pytest.mark.asyncio
async def test_publish_rejects_more_than_ten_files_before_reading_any_of_them() -> None:
    """Rejected in `publish()` itself — before a single `upload.read()` call, so no
    staging, no R2, no Meta call can ever follow an over-the-cap selection."""

    class _ExplodingUpload(_FakeUpload):
        async def read(self) -> bytes:  # pragma: no cover — must never be called
            raise AssertionError("read() must not be called when rejecting for count")

    state = PublishState()
    state.selected_connection_id = "c-1"

    result = await state.publish([_ExplodingUpload() for _ in range(_MAX_ITEMS + 1)])

    assert result is not None  # the failure toast EventSpec, not None (files WAS non-empty)
    assert state.phase == "failure"
    assert state.error == _TOO_MANY
    assert state._pending_files == []


def test_publish_background_dispatches_by_item_count_not_a_parallel_machine() -> None:
    """Structural pin: the ONLY thing that decides which seam `publish_background` calls
    is `len(pending)` — 1 delegates to the UNCHANGED `start_publish`, 2-10 to
    `start_many_publish` (QUA-99, 5/6). Everything else in that handler (the try/except
    tree, phase transitions, toasts, poll handoff) is shared, unified code — not two
    parallel state machines."""
    source = inspect.getsource(PublishState.publish_background.fn)
    assert "len(pending) == 1" in source
    assert "start_publish(" in source
    assert "start_many_publish(" in source


# --------------------------------------------------------------------------------------
# Fix 2 — `_pending_files` released on every failure branch, not just the success one
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fail_pending_attempt_clears_the_buffer_and_records_the_error() -> None:
    state = PublishState()
    state.phase = "staging_and_starting"
    state._idempotency_key = "k-1"
    state._pending_files = [_PendingFile(content_type="video/mp4", data=b"a-whole-reel")]

    await state._fail_pending_attempt("k-1", "algo salió mal")

    assert state.phase == "failure"
    assert state.error == "algo salió mal"
    assert state._pending_files == []  # the fix: released, not left buffered


@pytest.mark.asyncio
async def test_fail_pending_attempt_ignores_a_superseded_key() -> None:
    """A stale background task's failure must not clobber a NEWER attempt's in-progress
    state — and must not free files that belong to that newer, still-live attempt."""
    state = PublishState()
    state.phase = "polling"  # the newer attempt has already moved past staging
    state._idempotency_key = "k-2"  # the newer attempt's key
    newer_files = [_PendingFile(content_type="video/mp4", data=b"newer-attempts-bytes")]
    state._pending_files = newer_files
    state.error = ""

    await state._fail_pending_attempt("k-1-stale", "this must not land")

    assert state.phase == "polling"  # untouched
    assert state.error == ""  # untouched
    assert state._pending_files == newer_files  # NOT freed


def test_every_failure_branch_in_publish_background_uses_the_shared_release_helper() -> None:
    """Pins the fix structurally: the pre-staging `tenant_id is None` branch, the 5
    original exception branches (`R2ConfigurationError`, `(ObjectSizeExceeded,
    UnsizedStream)`, `(TenantPrefixViolation, ValueError)`, `UnknownConnection`,
    `Exception`), plus `TooManyItems` (QUA-99, 6/6, defense-in-depth behind `publish`'s
    own earlier rejection) — 7 sites total — must all route through
    `_fail_pending_attempt`. That is what makes the release unconditional. A future edit
    that reintroduces an inline `self.phase = "failure"` in one of them would silently
    reopen the buffer-retention bug this test guards against.
    """
    # `PublishState.publish_background` (class-level access) is an `EventHandler`
    # wrapper, not the plain function — `.fn` is the underlying coroutine function
    # `inspect.getsource` needs.
    source = inspect.getsource(PublishState.publish_background.fn)
    assert source.count("_fail_pending_attempt(idempotency_key,") == 7, (
        "expected exactly 7 call sites: tenant_id is None + 5 original exception "
        "branches + TooManyItems (QUA-99, 6/6)"
    )
    # No branch may set failure state directly anymore — that was the leaky pattern.
    assert 'self.phase = "failure"' not in source.replace(
        'self.phase = "success" if attempt.status == "published" else "failure"', ""
    )


# --------------------------------------------------------------------------------------
# QUA-98 — both outcomes now toast (success AND failure), on top of the persistent
# `error` callout, which is unchanged. A successful publish also clears the form.
# --------------------------------------------------------------------------------------


def test_success_toast_shows_only_the_headline() -> None:
    """Founder's call after the toast-action investigation: no media id, no
    "Ver detalles", no description at all — just the confirmation. The full id stays
    reachable via `PublishState.attempt.published_media_id` for anything that needs it,
    it just never appears in the toast itself."""
    toast = _success_toast()

    assert isinstance(toast, rx.event.EventSpec)
    representation = repr(toast)
    assert "Publicado correctamente" in representation
    assert "Media ID" not in representation
    assert "Instagram" not in representation
    assert "Ver detalles" not in representation


def test_failure_toast_carries_the_same_text_the_callout_shows() -> None:
    """The toast and the persistent callout must never disagree — same string, two
    surfaces."""
    toast = _failure_toast("No se pudo iniciar la publicación. Vuelve a intentarlo.")

    assert isinstance(toast, rx.event.EventSpec)
    assert "No se pudo iniciar la publicación. Vuelve a intentarlo." in repr(toast)


def test_both_settle_paths_wire_the_result_toast_from_the_same_phase_check() -> None:
    """Structural pin, same technique as the release-helper test above: both places that
    can settle an attempt (`publish_background`'s no-poll-needed path and `poll_attempt`)
    must derive `is_success`/`result_toast` from `self.phase == "success"` the same way —
    never fire a success toast on a failed/still-polling attempt, and never skip the
    failure toast on a genuine failure."""
    for fn in (PublishState.publish_background.fn, PublishState.poll_attempt.fn):
        source = inspect.getsource(fn)
        assert 'is_success = self.phase == "success"' in source, (
            f"{fn.__name__} must gate the toast/form-reset on phase == 'success'"
        )
        assert "_success_toast()" in source
        assert "_failure_toast(self.error)" in source
        assert "rx.clear_selected_files(_UPLOAD_ID)" in source, (
            f"{fn.__name__} must clear the dropzone selection after a successful publish"
        )
        assert 'self.caption = ""' in source, (
            f"{fn.__name__} must clear the caption after a successful publish"
        )
        assert 'self.selected_connection_id = ""' in source, (
            # Caught during pre-commit review: a `replace_all` edit matched this line
            # in `publish_background` but silently missed `poll_attempt` because the
            # two sites are indented differently — the account stayed selected after
            # the (more common) poll-settle success path. This assertion is what would
            # have failed instead of a human catching it by eye.
            f"{fn.__name__} must clear the selected account after a successful publish"
        )

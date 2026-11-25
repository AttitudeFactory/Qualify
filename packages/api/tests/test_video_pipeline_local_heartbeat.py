"""m-25119832: a `local` assembly keeps the draft's progress stamp moving while a long
step runs — the speed step alone measured 867 s without returning (8 stretches, 60 s,
768m and 1 CPU), and the reaper fails a draft after 20 min without a stamp.

Offline: tiny sources encoded here (the fixtures of `test_video_pipeline_local`), the
beat interval shortened to 10 ms and the slow step waiting on an event, not a clock."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest

from qualify_api.creative.heartbeat import beating
from qualify_api.creative.queue_dispatch import SWITCH
from qualify_api.creative.video_pipeline import local

from .test_content_service import TENANT_ID
from .test_video_pipeline_local import (
    PHOTO_KEY,
    SIZE,
    VIDEO_KEY,
    ReadingStore,
    _local_clip,
    _png_bytes,
    _stamped,
    _video_bytes,
)

pytest.importorskip("av")

BEAT_THREAD = "creative-local-beat"
INTERVAL_S = 0.01


@pytest.fixture(autouse=True)
def no_normalize_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    """The `normalize_local` jobs in memory, as `test_video_pipeline_local` does: the real
    door (`gallery_jobs` through `tenant_session`) would reach Postgres — never offline."""
    from qualify_api.creative.video_pipeline import local_sources

    jobs = local_sources.InMemoryLocalSourceJobs()
    monkeypatch.setattr(local_sources, "default_jobs", lambda: jobs)


@pytest.fixture(autouse=True)
def assemble_at_the_sources_size(monkeypatch: pytest.MonkeyPatch) -> None:
    """Assembled at the tiny sources' own 9:16 size, not 1080×1920 (the subject is the
    beat, not the size): `render_local_part` reads it at call time."""
    from qualify_creative.video import prepare

    monkeypatch.setattr(prepare, "TARGET_SIZE", SIZE)


@pytest.fixture
def queue_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SWITCH, "queue")


@pytest.fixture
def sources() -> dict[str, bytes]:
    return {VIDEO_KEY: _video_bytes(4.0), PHOTO_KEY: _png_bytes()}


def _beat_threads(name: str = BEAT_THREAD) -> list[str]:
    return [t.name for t in threading.enumerate() if t.name == name and t.is_alive()]


class Beats:
    """A beat that counts its calls; a step can wait for `n` more of them."""

    def __init__(self) -> None:
        self.calls = 0
        self._changed = threading.Condition()

    def __call__(self) -> None:
        with self._changed:
            self.calls += 1
            self._changed.notify_all()

    def wait_more(self, n: int, timeout: float = 10.0) -> bool:
        """True once `n` beats landed after this call (False after `timeout`)."""
        with self._changed:
            target = self.calls + n
            return self._changed.wait_for(lambda: self.calls >= target, timeout)


def _dir(path: Path) -> Path:
    path.mkdir()
    return path


def _part() -> Any:
    return local.recipe_of(_stamped(_local_clip()))[0]


def test_the_speed_step_beats_while_it_runs_and_its_video_is_unchanged(
    queue_on: None,
    sources: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A `render_speed` that does not return for several beat intervals still sees
    `beat` called meanwhile; the video is the one made without beats, and no beat
    thread is left (nor any beat lands) once the assembly returns."""
    from qualify_creative.video import speed

    real = speed.render_speed
    plain = local.render_local_part(
        _part(), tenant_id=TENANT_ID, store=ReadingStore(sources), root=_dir(tmp_path / "plain")
    )

    beat = Beats()
    during: list[bool] = []

    def slow(*args: Any, **kwargs: Any) -> Any:
        # the step does not return until three beats landed while it ran
        during.append(beat.wait_more(3))
        return real(*args, **kwargs)

    monkeypatch.setattr(local, "LOCAL_HEARTBEAT_EVERY_S", INTERVAL_S)
    monkeypatch.setattr(speed, "render_speed", slow)
    made = local.render_local_part(
        _part(),
        tenant_id=TENANT_ID,
        store=ReadingStore(sources),
        root=_dir(tmp_path / "beating"),
        beat=beat,
    )
    assert during == [True], "fewer than three beats while the speed step ran"
    assert (made.seconds, made.frames, made.width, made.height, made.speed) == (
        plain.seconds,
        plain.frames,
        plain.width,
        plain.height,
        plain.speed,
    )
    assert Path(made.path).exists()
    assert _beat_threads() == []
    after = beat.calls
    time.sleep(INTERVAL_S * 5)  # five intervals: nothing beats once it returned
    assert beat.calls == after


def test_a_speed_step_that_fails_stops_the_beat_and_its_error_goes_up(
    queue_on: None,
    sources: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """`render_speed` raising after a while: the side thread is stopped and waited for,
    and the very exception comes out of `render_local_part`, as it did without beats."""
    from qualify_creative.video import speed

    beat = Beats()
    error = RuntimeError("the encoder broke")

    def broken(*_: Any, **__: Any) -> Any:
        assert beat.wait_more(2), "no beat while the speed step ran"
        raise error

    monkeypatch.setattr(local, "LOCAL_HEARTBEAT_EVERY_S", INTERVAL_S)
    monkeypatch.setattr(speed, "render_speed", broken)
    with pytest.raises(RuntimeError) as raised:
        local.render_local_part(
            _part(), tenant_id=TENANT_ID, store=ReadingStore(sources), root=tmp_path, beat=beat
        )
    assert raised.value is error
    assert _beat_threads() == []
    after = beat.calls
    time.sleep(INTERVAL_S * 5)
    assert beat.calls == after


def test_the_prepare_step_beats_while_it_runs_too(
    queue_on: None,
    sources: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The same side thread covers the steps before the speed one (one stretch's
    prepare of a minute of 4K is not short either)."""
    from qualify_creative.video import prepare

    real = prepare.apply_prepare
    beat = Beats()
    during: list[bool] = []

    def slow(*args: Any, **kwargs: Any) -> Any:
        during.append(beat.wait_more(3))
        return real(*args, **kwargs)

    monkeypatch.setattr(local, "LOCAL_HEARTBEAT_EVERY_S", INTERVAL_S)
    monkeypatch.setattr(prepare, "apply_prepare", slow)
    local.render_local_part(
        _part(), tenant_id=TENANT_ID, store=ReadingStore(sources), root=tmp_path, beat=beat
    )
    assert during and all(during), "fewer than three beats while the prepare step ran"
    assert _beat_threads() == []


def test_without_a_beat_no_thread_is_started(
    queue_on: None,
    sources: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A test or a script without a progress stamp: no side thread at all."""
    from qualify_creative.video import speed

    real = speed.render_speed
    seen: list[list[str]] = []

    def watched(*args: Any, **kwargs: Any) -> Any:
        seen.append(_beat_threads())
        return real(*args, **kwargs)

    monkeypatch.setattr(speed, "render_speed", watched)
    local.render_local_part(
        _part(), tenant_id=TENANT_ID, store=ReadingStore(sources), root=tmp_path
    )
    assert seen == [[]]


def test_a_beat_that_raises_does_not_stop_the_next_ones() -> None:
    """`heartbeat.beating`: a stamp that cannot be written is logged and the next one is
    still tried; the thread ends with the block."""
    calls: list[int] = []
    three = threading.Event()

    def beat() -> None:
        calls.append(1)
        if len(calls) >= 3:
            three.set()
        raise ConnectionError("the database is away")

    with beating(beat, INTERVAL_S, name="heartbeat-test"):
        assert three.wait(10.0)
    assert _beat_threads("heartbeat-test") == []
